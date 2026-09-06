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
_avatar_cache: dict[str, tuple[float, bytes | None]] = {}


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


async def fetch_avatar(bot: Bot, author: Author) -> Image.Image:
    """Profile photo as a PIL image, or a generated fallback tile."""
    data = await _avatar_bytes(bot, author)
    if data:
        try:
            return Image.open(io.BytesIO(data))
        except Exception:  # noqa: BLE001 - malformed avatars shouldn't kill the request
            log.warning("could not decode avatar for %s", author.seed)
    letter = next((c for c in author.name if c.isalnum()), "?")
    return render.fallback_avatar(author.seed, letter.upper())


async def _avatar_bytes(bot: Bot, author: Author) -> bytes | None:
    if author.avatar_key is None:
        return None
    key = f"{author.kind}:{author.avatar_key}"
    hit = _avatar_cache.get(key)
    if hit and time.time() - hit[0] < _AVATAR_TTL:
        return hit[1]

    data: bytes | None = None
    try:
        if author.kind == "user":
            photos = await bot.get_user_profile_photos(author.avatar_key, limit=1)
            if photos.total_count:
                # Sizes come smallest-first; the last one is the highest resolution.
                file = await bot.get_file(photos.photos[0][-1].file_id)
                data = bytes(await file.download_as_bytearray())
        else:
            chat = await bot.get_chat(author.avatar_key)
            if chat.photo is not None:
                file = await bot.get_file(chat.photo.big_file_id)
                data = bytes(await file.download_as_bytearray())
    except TelegramError as exc:
        log.info("avatar unavailable for %s: %s", key, exc)

    _avatar_cache[key] = (time.time(), data)
    return data
