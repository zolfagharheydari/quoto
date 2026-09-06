"""Pull the quotable text and the downloadable media out of a replied-to message."""
from __future__ import annotations

from dataclasses import dataclass

from telegram import Bot, Message

MAX_QUOTE_CHARS = 700
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024   # the Bot API caps getFile downloads at 20 MB


@dataclass
class Media:
    file_id: str
    suffix: str
    is_video: bool
    size: int | None = None


def quote_text(message: Message) -> str | None:
    """The text to put on the card, or None when there is nothing to quote."""
    text = message.text or message.caption
    if text:
        text = text.strip()
    if not text:
        return None
    if len(text) > MAX_QUOTE_CHARS:
        text = text[:MAX_QUOTE_CHARS].rstrip() + "…"
    return text


def find_media(message: Message) -> Media | None:
    if message.photo:
        best = message.photo[-1]
        return Media(best.file_id, ".jpg", False, best.file_size)
    if message.sticker:
        s = message.sticker
        if s.is_animated:            # .tgs is Lottie JSON; no renderer bundled here
            return None
        return Media(s.file_id, ".webm" if s.is_video else ".webp", s.is_video, s.file_size)
    if message.animation:
        return Media(message.animation.file_id, ".mp4", True, message.animation.file_size)
    if message.video:
        return Media(message.video.file_id, ".mp4", True, message.video.file_size)
    if message.video_note:
        return Media(message.video_note.file_id, ".mp4", True, message.video_note.file_size)
    if message.document and message.document.mime_type:
        mime = message.document.mime_type
        if mime.startswith("image/"):
            suffix = "." + mime.split("/", 1)[1].split("+")[0]
            return Media(message.document.file_id, suffix, False, message.document.file_size)
        if mime.startswith("video/"):
            return Media(message.document.file_id, ".mp4", True, message.document.file_size)
    return None


async def download(bot: Bot, media: Media) -> bytes:
    file = await bot.get_file(media.file_id)
    return bytes(await file.download_as_bytearray())
