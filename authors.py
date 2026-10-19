"""Work out who said the replied-to message, and fetch their avatar."""
from __future__ import annotations

import asyncio
import io
import logging
import time
from collections import OrderedDict

from PIL import Image
from telegram import Bot, Message
from telegram.error import TelegramError

import render

log = logging.getLogger(__name__)

_AVATAR_TTL = 60 * 60          # profile pictures rarely change within an hour
_AVATAR_MISS_TTL = 5 * 60      # but "no picture" is worth re-checking sooner
# Least recently used first. Bounded by bytes, not entries: one uploaded
# picture can weigh what a thousand profile thumbnails do, and a cache that only
# ever grew was a slow leak with a ceiling set by how many people use the bot.
_avatar_cache: OrderedDict[str, tuple[float, bytes | None, str]] = OrderedDict()
CACHE_BYTES = 48 * 1024 * 1024


def _cache_get(key: str):
    hit = _avatar_cache.get(key)
    if hit is not None:
        _avatar_cache.move_to_end(key)
    return hit


def forget(key: str) -> None:
    _avatar_cache.pop(key, None)


def forget_prefix(prefix: str) -> None:
    for key in [k for k in _avatar_cache if k.startswith(prefix)]:
        del _avatar_cache[key]


def _cache_put(key: str, data: bytes | None, source: str) -> None:
    _avatar_cache[key] = (time.time(), data, source)
    _avatar_cache.move_to_end(key)
    total = sum(len(entry[1] or b"") for entry in _avatar_cache.values())
    while total > CACHE_BYTES and len(_avatar_cache) > 1:
        _, (_, dropped, _) = _avatar_cache.popitem(last=False)
        total -= len(dropped or b"")


class Author:
    __slots__ = ("name", "handle", "avatar_key", "kind", "seed")

    def __init__(self, name: str, handle: str, avatar_key: int | None, kind: str, seed: str):
        self.name = name or "کاربر ناشناس"
        self.handle = handle or ""
        self.avatar_key = avatar_key      # user_id or chat_id, None when unavailable
        self.kind = kind                  # "user" | "chat" | "hidden"
        self.seed = seed                  # stable string for the fallback avatar color


def resolve(message: Message) -> Author:
    """Prefer the original author of a forward over whoever pasted it into the chat."""
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        kind = getattr(origin, "type", None)
        user = getattr(origin, "sender_user", None)
        if user is not None:
            return _from_user(user)
        hidden = getattr(origin, "sender_user_name", None)
        if hidden:
            return Author(hidden, "", None, "hidden", hidden)
        chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
        if chat is not None:
            return _from_chat(chat)
        log.debug("unhandled forward origin type %s", kind)

    if message.sender_chat is not None:
        return _from_chat(message.sender_chat)
    if message.from_user is not None:
        return _from_user(message.from_user)
    return Author("کاربر ناشناس", "", None, "hidden", str(message.message_id))


def _from_user(user) -> Author:
    name = " ".join(filter(None, [user.first_name, user.last_name])) or user.username or "کاربر"
    return Author(name, user.username or "", user.id, "user", str(user.id))


def _from_chat(chat) -> Author:
    return Author(chat.title or chat.full_name or "کانال", chat.username or "",
                  chat.id, "chat", str(chat.id))


SOURCES = ("custom", "profile", "public", "letter")
DEFAULT_SOURCE = "profile"


def choice_for(bot_data, author: Author) -> tuple[str | None, str]:
    """(the picture they uploaded, the source they asked for) for this author.

    It lives here rather than beside the commands because every path that draws
    an author needs it. Inline had its own half of this - it passed the uploaded
    file but not the source, and the source is what decides whether the file is
    used at all, so anyone who had chosen their own picture got their Telegram
    one instead the moment they used inline mode.
    """
    if author.kind != "user" or author.avatar_key is None:
        return None, DEFAULT_SOURCE
    uid = author.avatar_key
    file_id = (bot_data.get("avatars") or {}).get(uid)
    source = (bot_data.get("avatar_source") or {}).get(uid)
    if source not in SOURCES:
        # Someone who uploaded a picture meant it to be used.
        source = "custom" if file_id else DEFAULT_SOURCE
    if source == "custom" and not file_id:
        source = DEFAULT_SOURCE
    return file_id, source


async def fetch_avatar(bot: Bot, author: Author, custom_file_id: str | None = None,
                       source: str = DEFAULT_SOURCE) -> Image.Image:
    """Profile photo as a PIL image, or a generated fallback tile.

    `source` is what this author asked to be shown: their own uploaded picture,
    their Telegram profile photo, the public one, or just their initial.
    """
    data, source = await _avatar_bytes(bot, author, custom_file_id, source)
    log.info("avatar for %s: %s", author.seed, source)
    if data:
        try:
            # Off the event loop: a picture somebody uploaded can take seconds
            # to decode, and every other user would wait for it.
            return await asyncio.to_thread(decode, data)
        except Exception:  # noqa: BLE001 - malformed avatars shouldn't kill the request
            log.warning("could not decode avatar for %s", author.seed)
    letter = next((c for c in author.name if c.isalnum()), "?")
    return render.fallback_avatar(author.seed, letter.upper())


# A card shows the avatar at a few hundred pixels. Anything far past this is
# not a photo of someone but a picture built to be expensive: a small PNG can
# declare tens of thousands of pixels a side and cost gigabytes to unpack.
MAX_AVATAR_PIXELS = 16_000_000
AVATAR_FORMATS = ("JPEG", "PNG", "WEBP")


def decode(data: bytes) -> Image.Image:
    """An uploaded or downloaded picture, refused before decoding if it is a trap.

    open() reads only the header, so the size is known before a pixel is
    unpacked. Pillow's own guard only warns below twice MAX_IMAGE_PIXELS; this
    refuses outright, and at a far lower size.
    """
    image = Image.open(io.BytesIO(data), formats=AVATAR_FORMATS)
    width, height = image.size
    if width * height > MAX_AVATAR_PIXELS:
        raise ValueError(f"avatar is {width}x{height}, past the limit")
    # A JPEG can be decoded straight to a smaller size, which is all the card needs.
    image.draft("RGB", (1280, 1280))
    image.load()
    return image


async def avatar_source(bot: Bot, author: Author, custom_file_id: str | None = None,
                        source: str = DEFAULT_SOURCE) -> str:
    """Where this author's picture would come from. For diagnostics."""
    _, label = await _avatar_bytes(bot, author, custom_file_id, source)
    return label


async def _cached(key: str, label: str, fetch) -> tuple[bytes | None, str]:
    """Run `fetch` unless this key was looked up recently."""
    hit = _cache_get(key)
    if hit:
        age, data, source = time.time() - hit[0], hit[1], hit[2]
        if age < (_AVATAR_TTL if data else _AVATAR_MISS_TTL):
            return data, f"{source} (cached)"
    try:
        data = await fetch()
    except TelegramError as exc:
        log.info("%s unavailable for %s: %s", label, key, exc)
        data = None
    source = label if data else "none"
    _cache_put(key, data, source)
    return data, source


MAX_AVATAR_BYTES = 5 * 1024 * 1024


async def _download(bot: Bot, file_id: str) -> bytes | None:
    file = await bot.get_file(file_id)
    # A profile photo is a few hundred kilobytes. What is past this was
    # uploaded as a file to be heavy, and is not fetched at all.
    if (getattr(file, "file_size", None) or 0) > MAX_AVATAR_BYTES:
        log.info("not fetching a %s-byte picture", file.file_size)
        return None
    return bytes(await file.download_as_bytearray())


async def _newest_profile_photo(bot: Bot, user_id: int) -> bytes | None:
    """The user's current profile photo, when their privacy settings expose it."""
    photos = await bot.get_user_profile_photos(user_id, limit=1)
    if not photos.total_count or not photos.photos:
        return None
    # Sizes come smallest-first; the last one is the highest resolution.
    return await _download(bot, photos.photos[0][-1].file_id)


async def _public_photo(bot: Bot, chat_id: int) -> bytes | None:
    """The photo Telegram shows to everyone else.

    When someone limits who may see their profile photo they can set a separate
    public one; getUserProfilePhotos returns nothing for us, but the chat still
    carries that fallback. This is also the path for channels and groups.
    """
    chat = await bot.get_chat(chat_id)
    if chat.photo is None:
        return None
    return await _download(bot, chat.photo.big_file_id)


async def _avatar_bytes(bot: Bot, author: Author, custom_file_id: str | None = None,
                        source: str = DEFAULT_SOURCE) -> tuple[bytes | None, str]:
    """Best available picture, and a label saying where it came from."""
    if source == "letter":
        return None, "initial (chosen)"
    if source == "custom" and custom_file_id:
        # Keyed by the file itself, so choosing a new picture misses the cache
        # rather than needing the old entry hunted down and removed.
        data, label = await _cached(f"custom:{custom_file_id}", "chosen photo",
                                    lambda: _download(bot, custom_file_id))
        if data:
            return data, label
        log.info("chosen photo for %s is gone; falling back", author.seed)
    if author.avatar_key is None:
        return None, "none (no account to look up)"

    if author.kind != "user":
        attempts = [("chat photo", _public_photo)]
    elif source == "public":
        # Asked for the public one specifically, so do not fall back to the other.
        attempts = [("public photo", _public_photo)]
    else:
        attempts = [("profile photo", _newest_profile_photo),
                    ("public photo", _public_photo)]

    # The chain differs by source, so it has to be part of the key: a "public
    # only" answer must not be served to someone who asked for the full chain.
    key = f"{author.kind}:{author.avatar_key}:{attempts[0][0]}"
    hit = _cache_get(key)
    if hit:
        age, cached, cached_label = time.time() - hit[0], hit[1], hit[2]
        # Re-check a miss sooner: the user may have just opened their photo up.
        if age < (_AVATAR_TTL if cached else _AVATAR_MISS_TTL):
            return cached, f"{cached_label} (cached)"

    data: bytes | None = None
    found = "none (nothing visible to the bot)"
    for label, getter in attempts:
        try:
            data = await getter(bot, author.avatar_key)
        except TelegramError as exc:
            log.info("%s unavailable for %s: %s", label, key, exc)
            continue
        if data:
            found = label
            break

    _cache_put(key, data, found)
    return data, found
