"""Work out who said the replied-to message, and fetch their avatar."""
from __future__ import annotations

import io
import logging
import time

from PIL import Image
from telegram import Bot, Message
from telegram.error import TelegramError

import render

log = logging.getLogger(__name__)

_AVATAR_TTL = 60 * 60          # profile pictures rarely change within an hour
_AVATAR_MISS_TTL = 5 * 60      # but "no picture" is worth re-checking sooner
_avatar_cache: dict[str, tuple[float, bytes | None, str]] = {}


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


async def fetch_avatar(bot: Bot, author: Author,
                       custom_file_id: str | None = None) -> Image.Image:
    """Profile photo as a PIL image, or a generated fallback tile.

    `custom_file_id` is a picture the author chose for themselves; it beats
    whatever Telegram would show.
    """
    data, source = await _avatar_bytes(bot, author, custom_file_id)
    log.info("avatar for %s: %s", author.seed, source)
    if data:
        try:
            return Image.open(io.BytesIO(data))
        except Exception:  # noqa: BLE001 - malformed avatars shouldn't kill the request
            log.warning("could not decode avatar for %s", author.seed)
    letter = next((c for c in author.name if c.isalnum()), "?")
    return render.fallback_avatar(author.seed, letter.upper())


async def avatar_source(bot: Bot, author: Author,
                        custom_file_id: str | None = None) -> str:
    """Where this author's picture would come from. For diagnostics."""
    _, source = await _avatar_bytes(bot, author, custom_file_id)
    return source


async def _cached(key: str, label: str, fetch) -> tuple[bytes | None, str]:
    """Run `fetch` unless this key was looked up recently."""
    hit = _avatar_cache.get(key)
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
    _avatar_cache[key] = (time.time(), data, source)
    return data, source


async def _download(bot: Bot, file_id: str) -> bytes:
    file = await bot.get_file(file_id)
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


async def _avatar_bytes(bot: Bot, author: Author,
                        custom_file_id: str | None = None) -> tuple[bytes | None, str]:
    """Best available picture, and a label saying where it came from."""
    if custom_file_id:
        # Keyed by the file itself, so choosing a new picture misses the cache
        # rather than needing the old entry hunted down and removed.
        data, source = await _cached(f"custom:{custom_file_id}", "chosen photo",
                                     lambda: _download(bot, custom_file_id))
        if data:
            return data, source
        log.info("chosen photo for %s is gone; falling back", author.seed)
    if author.avatar_key is None:
        return None, "none (no account to look up)"
    key = f"{author.kind}:{author.avatar_key}"
    hit = _avatar_cache.get(key)
    if hit:
        age, data, source = time.time() - hit[0], hit[1], hit[2]
        # Re-check a miss sooner: the user may have just opened their photo up.
        if age < (_AVATAR_TTL if data else _AVATAR_MISS_TTL):
            return data, f"{source} (cached)"

    attempts = (
        [("profile photo", _newest_profile_photo), ("public photo", _public_photo)]
        if author.kind == "user"
        else [("chat photo", _public_photo)]
    )

    data: bytes | None = None
    source = "none (nothing visible to the bot)"
    for label, getter in attempts:
        try:
            data = await getter(bot, author.avatar_key)
        except TelegramError as exc:
            log.info("%s unavailable for %s: %s", label, key, exc)
            continue
        if data:
            source = label
            break

    _avatar_cache[key] = (time.time(), data, source)
    return data, source
