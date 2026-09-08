"""Telegram quote bot: reply to a message and turn it into a card, sticker or GIF."""
from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ChatAction
from telegram.error import InvalidToken, NetworkError, TelegramError
from telegram.ext import (
    AIORateLimiter,
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)

import animate
import authors
import extract
import fonts
import i18n
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
STATE_FILE = os.getenv("STATE_FILE", "botdata.pkl").strip()
PROXY = os.getenv("PROXY", "").strip()


def _t(key: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    return i18n.t(key, i18n.resolve(update, context.user_data))


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_html(_t("help", update, context))


async def cmd_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = i18n.resolve(update, context.user_data)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(i18n.t("btn_fa", lang), callback_data="lang:fa"),
            InlineKeyboardButton(i18n.t("btn_en", lang), callback_data="lang:en"),
        ],
        [InlineKeyboardButton(i18n.t("btn_auto", lang), callback_data="lang:auto")],
    ])
    await update.effective_message.reply_text(
        i18n.t("lang_prompt", lang), reply_markup=keyboard
    )


async def on_lang_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    choice = query.data.split(":", 1)[1]
    if choice == "auto":
        context.user_data.pop("lang", None)
        message = i18n.t("lang_auto", i18n.resolve(update, context.user_data))
    else:
        context.user_data["lang"] = choice
        message = i18n.t("lang_set", choice)
    await query.answer()
    await query.edit_message_text(message)


async def _build_scene(update: Update, target: Message, text: str):
    author = authors.resolve(target)
    avatar = await authors.fetch_avatar(update.get_bot(), author)
    return await asyncio.to_thread(
        render.build_scene, avatar, text, author.name, author.handle, WATERMARK
    )


async def _prepare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Common guard: must be a reply, and that reply must carry text."""
    message = update.effective_message
    target = message.reply_to_message
    if target is None:
        await message.reply_text(_t("need_reply", update, context))
        return None
    text = extract.quote_text(target)
    if text is None:
        await message.reply_text(_t("need_text", update, context))
        return None
    return target, text


async def cmd_quote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prepared = await _prepare(update, context)
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
        await message.reply_text(_t("failed", update, context))


async def cmd_quote_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prepared = await _prepare(update, context)
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
        await message.reply_text(_t("failed", update, context))


async def cmd_quote_gif(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prepared = await _prepare(update, context)
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
        await message.reply_text(_t("failed", update, context))


async def _grab_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    target = message.reply_to_message
    if target is None:
        await message.reply_text(_t("need_reply", update, context))
        return None
    found = extract.find_media(target)
    if found is None:
        await message.reply_text(_t("need_media", update, context))
        return None
    if found.size and found.size > extract.MAX_DOWNLOAD_BYTES:
        await message.reply_text(_t("too_big", update, context))
        return None
    data = await extract.download(update.get_bot(), found)
    return target, found, data


async def cmd_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    grabbed = await _grab_media(update, context)
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
        await message.reply_text(_t(str(exc), update, context))
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("sticker conversion failed")
        await message.reply_text(_t("failed", update, context))


async def cmd_gif(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    grabbed = await _grab_media(update, context)
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
        await message.reply_text(_t(str(exc), update, context))
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("gif conversion failed")
        await message.reply_text(_t("failed", update, context))


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("handler error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(_t("failed", update, context))
        except TelegramError:
            pass


async def post_init(app: Application) -> None:
    # English is the default menu; Telegram serves the Persian one to Persian clients.
    await app.bot.set_my_commands(
        [BotCommand(name, desc) for name, desc in i18n.COMMANDS["en"]]
    )
    await app.bot.set_my_commands(
        [BotCommand(name, desc) for name, desc in i18n.COMMANDS["fa"]],
        language_code="fa",
    )


def main() -> None:
    if not TOKEN:
        raise SystemExit(
            "BOT_TOKEN is not set. Put it in the .env file.\n"
            "BOT_TOKEN تنظیم نشده. مقدارش را در فایل .env بگذار."
        )
    if fonts.missing_bundled_font():
        log.warning("Vazirmatn not found; run python download_fonts.py for correct Persian.")

    builder = (
        Application.builder()
        .token(TOKEN)
        .rate_limiter(AIORateLimiter())
        .persistence(PicklePersistence(filepath=STATE_FILE))
        .post_init(post_init)
    )
    if PROXY:
        # Both the API calls and the long-polling connection need the proxy.
        log.info("using proxy %s", PROXY)
        builder = builder.proxy(PROXY).get_updates_proxy(PROXY)
    app = builder.build()

    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler(["lang", "language"], cmd_lang))
    app.add_handler(CallbackQueryHandler(on_lang_choice, pattern=r"^lang:"))
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
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except InvalidToken:
        raise SystemExit("\n".join([
            "",
            "Telegram rejected the token. Check BOT_TOKEN in the .env file.",
            "توکن را تلگرام قبول نکرد. مقدار BOT_TOKEN در فایل .env را چک کن.",
            "(باید عیناً همان چیزی باشد که BotFather داده، بدون فاصله یا کوتیشن.)",
        ])) from None
    except NetworkError as exc:
        raise SystemExit("\n".join([
            "",
            f"Could not reach Telegram: {exc}",
            "به تلگرام وصل نشد. اینترنت را چک کن، و اگر لازم است",
            "مقدار PROXY را در فایل .env تنظیم کن (مثلاً socks5://127.0.0.1:1080).",
        ])) from None


if __name__ == "__main__":
    main()
