"""Telegram quote bot: reply to a message and turn it into a card, sticker or GIF."""
from __future__ import annotations

import asyncio
import io
import logging
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ChatAction, ChatMemberStatus
from telegram.error import InvalidToken, NetworkError, TelegramError
from telegram.ext import (
    AIORateLimiter,
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    PicklePersistence,
    filters,
)

import animate
import authors
import extract
import fonts
import i18n
import inline
import media as media_tools
import render
import screenshot
import stickerpack

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
_tz = os.getenv("TIMEZONE", "").strip()
try:
    # Telegram timestamps arrive in UTC; screenshots should show the local clock.
    TZ = ZoneInfo(_tz) if _tz else None
except (ZoneInfoNotFoundError, ValueError):
    log.warning("unknown TIMEZONE %r; screenshot times will be UTC", _tz)
    TZ = None
_owner = os.getenv("OWNER_ID", "").strip()
OWNER_ID: int | None = int(_owner) if _owner.lstrip("-").isdigit() else None
_storage = os.getenv("STORAGE_CHAT_ID", "").strip()
# Inline results must reference stored files; this chat is where they get uploaded.
STORAGE_CHAT: str | int | None = (
    int(_storage) if _storage.lstrip("-").isdigit() else (_storage or None)
)


def _t(key: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    return i18n.t(key, i18n.resolve(update, context.user_data))


async def _send(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str) -> None:
    text = _t(key, update, context).replace("@BOT", f"@{context.bot.username}")
    await update.effective_message.reply_html(text)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send(update, context, "welcome")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send(update, context, "help")


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


async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Report what actually arrived, so a silent failure can be diagnosed.

    Operator-only: it exposes chat ids and resolution internals, which are of no
    use to a user and not theirs to see. Anyone else gets no reply at all.
    """
    user = update.effective_user
    if OWNER_ID is None or (user and user.id != OWNER_ID):
        log.info(
            "/debug from %s ignored; set OWNER_ID=%s in .env to enable it for yourself",
            user.id if user else "?", user.id if user else "<your id>",
        )
        return
    message = update.effective_message
    target = message.reply_to_message
    lines = [
        f"chat: {message.chat.type} ({message.chat_id})",
        f"from: {message.from_user.full_name if message.from_user else None}",
        f"reply_to_message: {'YES' if target else 'NO'}",
    ]
    if target:
        who = target.from_user.full_name if target.from_user else None
        lines += [
            f"  author: {who}",
            f"  sender_chat: {target.sender_chat.title if target.sender_chat else None}",
            f"  text found: {'YES' if extract.quote_text(target) else 'NO'}",
            f"  media found: {'YES' if extract.find_media(target) else 'NO'}",
        ]
    else:
        lines.append("  (اگر ریپلای کرده‌ای و اینجا NO است، ربات ریپلای را نمی‌بیند:")
        lines.append("   ربات را از گروه حذف و دوباره اضافه کن.)")
    who = authors.resolve(target or message)
    lines += [
        f"quoting: {who.name} (@{who.handle or '-'})",
        f"avatar: {await authors.avatar_source(context.bot, who)}",
    ]
    await message.reply_text(chr(10).join(lines))


async def _build_scene(update: Update, target: Message, text: str):
    author = authors.resolve(target)
    avatar = await authors.fetch_avatar(update.get_bot(), author)
    return await asyncio.to_thread(
        render.build_scene, avatar, text, author.name, author.handle, WATERMARK
    )


async def _prepare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Find the message to quote: the replied-to one, or the command's own text.

    Returns (source message, text). The source is what we attribute the quote to
    and what we reply under, so "/q some words" quotes the sender themselves.
    """
    message = update.effective_message
    target = message.reply_to_message
    log.info(
        "quote request in %s (%s): reply=%s args=%s",
        message.chat_id, message.chat.type,
        target.message_id if target else None,
        len(getattr(context, "args", None) or []),
    )
    if target is None:
        typed = " ".join(getattr(context, "args", None) or []).strip()
        if typed:
            return message, typed[:extract.MAX_QUOTE_CHARS]
        # In a group the usual cause is privacy mode eating the reply, so say so.
        key = "need_reply_group" if message.chat.type in ("group", "supergroup") else "need_reply"
        await message.reply_text(_t(key, update, context))
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
        webp = buf.getvalue()
        await message.reply_sticker(io.BytesIO(webp),
                                    reply_to_message_id=target.message_id)
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("quote sticker failed")
        await message.reply_text(_t("failed", update, context))
        return

    # The sticker is already delivered; the pack is a bonus that may quietly fail.
    result = await stickerpack.add_quote(context.bot, message.chat, webp, OWNER_ID)
    if result and result[1]:
        link, _ = result
        await message.reply_text(
            _t("pack_created", update, context).format(link=link),
            disable_web_page_preview=True,
        )


async def cmd_pack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hand back the link to this group's pack."""
    message = update.effective_message
    if message.chat.type not in stickerpack.GROUP_TYPES:
        await message.reply_text(_t("pack_groups_only", update, context))
        return
    link = await stickerpack.link_for(context.bot, message.chat)
    if link is None:
        await message.reply_text(_t("pack_none", update, context))
        return
    await message.reply_text(
        _t("pack_link", update, context).format(link=link),
        disable_web_page_preview=True,
    )


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


def _clock(when) -> str:
    """The time as a chat client prints it: 3:47 PM, not 03:47."""
    if TZ is not None:
        when = when.astimezone(TZ)
    return when.strftime("%I:%M %p").lstrip("0")


async def _badge(bot, chat, author: authors.Author, lang: str) -> str | None:
    """The owner/admin pill Telegram shows beside a name in a group."""
    if chat.type not in ("group", "supergroup") or author.kind != "user":
        return None
    if author.avatar_key is None:
        return None
    try:
        member = await bot.get_chat_member(chat.id, author.avatar_key)
    except TelegramError:
        return None
    if member.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
        return None  # an ordinary member carries no tag at all
    # Whatever this group actually calls them wins; the generic word is the
    # fallback Telegram itself shows when nobody has set a title.
    title = (getattr(member, "custom_title", None) or "").strip()
    if title:
        return title
    return i18n.t(
        "badge_owner" if member.status == ChatMemberStatus.OWNER else "badge_admin",
        lang,
    )


def _screenshot_handler(style: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        prepared = await _prepare(update, context)
        if prepared is None:
            return
        target, text = prepared
        message = update.effective_message
        await message.chat.send_action(ChatAction.UPLOAD_PHOTO)
        try:
            author = authors.resolve(target)
            avatar = await authors.fetch_avatar(context.bot, author)
            badge = await _badge(context.bot, message.chat, author,
                                 i18n.resolve(update, context.user_data))
            image = await asyncio.to_thread(
                screenshot.render, avatar, author.name, text,
                _clock(target.date), badge, author.seed, style,
            )
            buf = await asyncio.to_thread(screenshot.to_png, image)
            await message.reply_photo(buf, reply_to_message_id=target.message_id)
        except TelegramError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("screenshot render failed")
            await message.reply_text(_t("failed", update, context))

    return handler


async def _grab_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    target = message.reply_to_message
    if target is None:
        key = "need_reply_group" if message.chat.type in ("group", "supergroup") else "need_reply"
        await message.reply_text(_t(key, update, context))
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
    """Publish the menus and the pre-Start blurbs, English by default plus Persian.

    Telegram serves each client the variant matching its language, so this
    replaces setting them by hand in BotFather.
    """
    username = app.bot.username

    async def publish(lang: str, **kwargs) -> None:
        await app.bot.set_my_commands(
            [BotCommand(name, desc) for name, desc in i18n.COMMANDS[lang]], **kwargs
        )
        await app.bot.set_my_description(
            i18n.DESCRIPTIONS[lang].replace("@BOT", f"@{username}"), **kwargs
        )
        await app.bot.set_my_short_description(
            i18n.SHORT_DESCRIPTIONS[lang].replace("@BOT", f"@{username}"), **kwargs
        )

    await publish("en")                        # the default every other locale sees
    await publish("fa", language_code="fa")


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

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler(["help", "guide"], cmd_help))
    app.add_handler(CommandHandler(["lang", "language"], cmd_lang))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler(["pack", "stickers"], cmd_pack))
    app.add_handler(CallbackQueryHandler(on_lang_choice, pattern=r"^lang:"))
    app.add_handler(CommandHandler(["q", "quote", "qoute", "quto", "qute", "quot"], cmd_quote))
    app.add_handler(CommandHandler(["qs", "quotesticker"], cmd_quote_sticker))
    app.add_handler(CommandHandler(["qg", "quotegif"], cmd_quote_gif))
    app.add_handler(CommandHandler(["ss", "shot"], _screenshot_handler("telegram")))
    app.add_handler(CommandHandler(["ios", "ssi"], _screenshot_handler("ios")))
    app.add_handler(CommandHandler(["sticker", "s"], cmd_sticker))
    app.add_handler(CommandHandler(["gif", "g"], cmd_gif))
    # Bare-word trigger; only reachable in groups when privacy mode is off.
    app.add_handler(MessageHandler(
        filters.REPLY & filters.Regex(r"(?i)^\s*(کوت|نقل\s*قول|quote|q)\s*$"), cmd_quote
    ))
    app.add_handler(InlineQueryHandler(inline.make_handler(WATERMARK, STORAGE_CHAT)))
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
