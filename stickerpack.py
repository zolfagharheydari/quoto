"""A sticker pack per group, collecting the quotes made in it.

The first /qs in a group creates a pack named after the group, with the group's
photo as its thumbnail; every later one is appended. Telegram packs are owned by
a user account rather than by a bot, so they are all created under OWNER_ID —
without it there is nobody to own them and the feature stays off.

A pack failing is never allowed to cost the user their sticker: every error here
is logged and swallowed, and the caller still sends what it rendered.
"""
from __future__ import annotations

import io
import logging

from PIL import Image
from telegram import Bot, Chat, InputSticker
from telegram.error import TelegramError

log = logging.getLogger("quotebot.pack")

EMOJI = "💬"
MAX_NAME = 64
MAX_TITLE = 64
THUMB_SIDE = 100
GROUP_TYPES = ("group", "supergroup")


def pack_name(chat_id: int, bot_username: str) -> str:
    """A pack name Telegram will accept: letters, digits and _, ending in _by_bot."""
    suffix = f"_by_{bot_username}"
    return f"q{abs(chat_id)}"[: MAX_NAME - len(suffix)] + suffix


def pack_title(chat_title: str | None) -> str:
    return (chat_title or "Quotes").strip()[:MAX_TITLE] or "Quotes"


def pack_link(name: str) -> str:
    return f"https://t.me/addstickers/{name}"


def _thumbnail(data: bytes) -> io.BytesIO | None:
    """The group photo as a 100x100 WEBP, which is what a pack thumbnail must be."""
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:  # noqa: BLE001 - a broken chat photo is not worth failing over
        log.warning("could not decode the chat photo for a pack thumbnail")
        return None
    img = img.resize((THUMB_SIDE, THUMB_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=90, method=6)
    buf.seek(0)
    return buf


async def _chat_photo(bot: Bot, chat: Chat) -> bytes | None:
    if chat.photo is None:
        return None
    try:
        file = await bot.get_file(chat.photo.big_file_id)
        return bytes(await file.download_as_bytearray())
    except TelegramError as exc:
        log.info("no chat photo for the pack thumbnail: %s", exc)
        return None


async def _exists(bot: Bot, name: str) -> bool:
    try:
        await bot.get_sticker_set(name)
        return True
    except TelegramError:
        # Telegram answers a missing set with an error rather than an empty result.
        return False


async def add_quote(bot: Bot, chat: Chat, webp: bytes,
                    owner_id: int | None) -> tuple[str, bool] | None:
    """Put this sticker in the chat's pack. Returns (link, just_created), or None.

    None means the pack was not touched — not a group, no OWNER_ID, or Telegram
    refused — and the caller should carry on regardless.
    """
    if owner_id is None:
        log.info("OWNER_ID is not set, so group sticker packs are disabled")
        return None
    if chat.type not in GROUP_TYPES:
        return None

    name = pack_name(chat.id, bot.username)
    sticker = InputSticker(sticker=io.BytesIO(webp), emoji_list=[EMOJI], format="static")

    try:
        if await _exists(bot, name):
            await bot.add_sticker_to_set(user_id=owner_id, name=name, sticker=sticker)
            return pack_link(name), False

        await bot.create_new_sticker_set(
            user_id=owner_id, name=name, title=pack_title(chat.title),
            stickers=[sticker],
        )
        photo = await _chat_photo(bot, chat)
        if photo:
            thumb = _thumbnail(photo)
            if thumb:
                try:
                    await bot.set_sticker_set_thumbnail(
                        name=name, user_id=owner_id, format="static", thumbnail=thumb
                    )
                except TelegramError as exc:
                    log.info("could not set the pack thumbnail: %s", exc)
        return pack_link(name), True
    except TelegramError as exc:
        # Most often the pack is full, or OWNER_ID never started the bot.
        log.warning("sticker pack update failed for %s: %s", name, exc)
        return None


async def link_for(bot: Bot, chat: Chat) -> str | None:
    """The chat's pack link, if a pack has actually been created."""
    if chat.type not in GROUP_TYPES:
        return None
    name = pack_name(chat.id, bot.username)
    return pack_link(name) if await _exists(bot, name) else None
