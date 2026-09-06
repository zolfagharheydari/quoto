"""Telegram quote bot: reply to a message and turn it into a card, sticker or GIF."""
from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import Message, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import (
    AIORateLimiter,
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import animate
import authors
import extract
import fonts
import media as media_tools
import render

load_dotenv()

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("quotebot")

TOKEN = os.getenv("BOT_TOKEN", "").strip()
WATERMARK = os.getenv("WATERMARK", "").strip()

NEED_REPLY = "روی پیامی که می‌خوای ازش عکس بسازم ریپلای کن و دوباره دستور رو بفرست."
NEED_TEXT = "اون پیام متنی نداره که بشه نقلش کرد. برای تبدیل خودِ پیام از /sticker یا /gif استفاده کن."
NEED_MEDIA = "روی یک عکس، استیکر، گیف یا ویدیو ریپلای کن."
TOO_BIG = "این فایل بزرگ‌تر از ۲۰ مگابایته و ربات نمی‌تونه دانلودش کنه."
FAILED = "نشد بسازمش. یه بار دیگه امتحان کن."

HELP = """سلام! من از پیام‌ها عکسِ نقل‌قول می‌سازم.

<b>روی یک پیام ریپلای کن و بفرست:</b>
/q یا /quote — عکس نقل‌قول
/qs — همون نقل‌قول به شکل استیکر
/qg — همون نقل‌قول به شکل گیف (متن تایپ می‌شود)

<b>تبدیل خودِ پیام، همان‌طور که هست:</b>
/sticker — عکس یا ویدیو را استیکر می‌کنم
/gif — ویدیو یا استیکر متحرک را گیف می‌کنم

می‌تونی به‌جای دستور، در جواب پیام فقط بنویسی «کوت» یا «quote».
در گروه‌ها هم کار می‌کنم؛ فقط یادت باشه اول روی پیام ریپلای کنی."""


async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_html(HELP)


async def _build_scene(update: Update, target: Message, text: str):
    author = authors.resolve(target)
    avatar = await authors.fetch_avatar(update.get_bot(), author)
    return await asyncio.to_thread(
        render.build_scene, avatar, text, author.name, author.handle, WATERMARK
    )


async def _prepare(update: Update) -> tuple[Message, str] | None:
    """Common guard: must be a reply, and that reply must carry text."""
    message = update.effective_message
    target = message.reply_to_message
    if target is None:
        await message.reply_text(NEED_REPLY)
        return None
    text = extract.quote_text(target)
    if text is None:
        await message.reply_text(NEED_TEXT)
        return None
    return target, text


async def cmd_quote(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    prepared = await _prepare(update)
    if prepared is None:
        return
    target, text = prepared
    message = update.effective_message
    await message.chat.send_action(ChatAction.UPLOAD_PHOTO)
    try:
        scene = await _build_scene(update, target, text)
        image = await asyncio.to_thread(scene.render)
        buf = await asyncio.to_thread(render.to_png, image)
        await message.reply_photo(buf, reply_to_message_id=target.message_id)
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("quote render failed")
        await message.reply_text(FAILED)


async def cmd_quote_sticker(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    prepared = await _prepare(update)
    if prepared is None:
        return
    target, text = prepared
    message = update.effective_message
    await message.chat.send_action(ChatAction.CHOOSE_STICKER)
    try:
        scene = await _build_scene(update, target, text)
        image = await asyncio.to_thread(scene.render)
        buf = await asyncio.to_thread(render.to_sticker_webp, image)
        await message.reply_sticker(buf, reply_to_message_id=target.message_id)
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("quote sticker failed")
        await message.reply_text(FAILED)


async def cmd_quote_gif(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    prepared = await _prepare(update)
    if prepared is None:
        return
    target, text = prepared
    message = update.effective_message
    await message.chat.send_action(ChatAction.UPLOAD_VIDEO)
    try:
        scene = await _build_scene(update, target, text)
        buf, ext = await asyncio.to_thread(animate.to_animation, scene)
        await message.reply_animation(
            buf, filename=f"quote.{ext}", reply_to_message_id=target.message_id
        )
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("quote gif failed")
        await message.reply_text(FAILED)


async def _grab_media(update: Update) -> tuple[Message, extract.Media, bytes] | None:
    message = update.effective_message
    target = message.reply_to_message
    if target is None:
        await message.reply_text(NEED_REPLY)
        return None
    found = extract.find_media(target)
    if found is None:
        await message.reply_text(NEED_MEDIA)
        return None
    if found.size and found.size > extract.MAX_DOWNLOAD_BYTES:
        await message.reply_text(TOO_BIG)
        return None
    data = await extract.download(update.get_bot(), found)
    return target, found, data


async def cmd_sticker(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    grabbed = await _grab_media(update)
    if grabbed is None:
        return
    target, found, data = grabbed
    message = update.effective_message
    await message.chat.send_action(ChatAction.CHOOSE_STICKER)
    try:
        if found.is_video:
            buf = await asyncio.to_thread(media_tools.video_to_sticker, data, found.suffix)
        else:
            buf = await asyncio.to_thread(media_tools.image_to_sticker, data)
        await message.reply_sticker(buf, reply_to_message_id=target.message_id)
    except media_tools.ConversionError as exc:
        await message.reply_text(str(exc))
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("sticker conversion failed")
        await message.reply_text(FAILED)


async def cmd_gif(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    grabbed = await _grab_media(update)
    if grabbed is None:
        return
    target, found, data = grabbed
    message = update.effective_message
    await message.chat.send_action(ChatAction.UPLOAD_VIDEO)
    try:
        buf, ext = await asyncio.to_thread(media_tools.to_animation, data, found.suffix)
        await message.reply_animation(
            buf, filename=f"converted.{ext}", reply_to_message_id=target.message_id
        )
    except media_tools.ConversionError as exc:
        await message.reply_text(str(exc))
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("gif conversion failed")
        await message.reply_text(FAILED)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("handler error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(FAILED)
        except TelegramError:
            pass


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        ("quote", "ساخت عکس نقل‌قول از پیام ریپلای‌شده"),
        ("qs", "نقل‌قول به شکل استیکر"),
        ("qg", "نقل‌قول به شکل گیف"),
        ("sticker", "تبدیل عکس/ویدیوی ریپلای‌شده به استیکر"),
        ("gif", "تبدیل ویدیو/استیکر ریپلای‌شده به گیف"),
        ("help", "راهنما"),
    ])


def main() -> None:
    if not TOKEN:
        raise SystemExit("BOT_TOKEN تنظیم نشده. مقدارش را در فایل .env بگذار.")
    if fonts.missing_bundled_font():
        log.warning("Vazirmatn پیدا نشد؛ برای فارسیِ درست python download_fonts.py را اجرا کن.")

    app = (
        Application.builder()
        .token(TOKEN)
        .rate_limiter(AIORateLimiter())
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler(["q", "quote"], cmd_quote))
    app.add_handler(CommandHandler(["qs", "quotesticker"], cmd_quote_sticker))
    app.add_handler(CommandHandler(["qg", "quotegif"], cmd_quote_gif))
    app.add_handler(CommandHandler(["sticker", "s"], cmd_sticker))
    app.add_handler(CommandHandler(["gif", "g"], cmd_gif))
    # Bare-word trigger; only reachable in groups when privacy mode is off.
    app.add_handler(MessageHandler(
        filters.REPLY & filters.Regex(r"(?i)^\s*(کوت|نقل\s*قول|quote|q)\s*$"), cmd_quote
    ))
    app.add_error_handler(on_error)

    log.info("bot is up")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
