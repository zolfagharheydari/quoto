"""Telegram quote bot: reply to a message and turn it into a card, sticker or GIF."""
from __future__ import annotations

import asyncio
import io
import logging
import logging.handlers
import time
import re
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from telegram import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ChatAction, ChatMemberStatus
from telegram.error import (
    BadRequest,
    Forbidden,
    InvalidToken,
    NetworkError,
    TelegramError,
)
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    ChatMemberHandler,
    ChosenInlineResultHandler,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    MessageReactionHandler,
    PicklePersistence,
    TypeHandler,
    filters,
)

import admin
import animate
import authors
import extract
import fonts
import i18n
import inline
import reactions
import render
import screenshot
import stickerpack

load_dotenv()

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

# The console window is gone the moment it is closed, and a failure that happens
# once an hour is impossible to catch by watching it. Everything also goes to a
# file next to the code, rotated so it cannot grow without bound.
_log_file = logging.handlers.RotatingFileHandler(
    Path(__file__).with_name("quotebot.log"),
    maxBytes=2_000_000, backupCount=2, encoding="utf-8",
)
_log_file.setFormatter(logging.Formatter(LOG_FORMAT))
logging.getLogger().addHandler(_log_file)

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
# People must be in this channel to use the bot. It is where anything new is
# announced, and it is checked by asking Telegram - which means the bot has to
# be an administrator of it, or it cannot see who is in it.
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "").strip()

# Personal pack names are derived from this, so that a link people share says
# nothing about who made it. The token is a reasonable fallback - it is secret
# and it does not change - but it ties the names to it: regenerate the token
# through BotFather without setting PACK_SALT first and every personal pack is
# orphaned, because the bot will start looking for packs under new names.
PACK_SALT = os.getenv("PACK_SALT", "").strip() or TOKEN
stickerpack.set_salt(PACK_SALT)


def _storage_chat(raw: str) -> str | int | None:
    """The chat inline uploads go to, or None when the setting is unusable.

    Telegram addresses a chat by numeric id or by @name and by nothing else. An
    invite link is the obvious thing to paste here and the one thing that cannot
    work - a bot cannot follow one, and passing it through turns every inline
    query into "Chat not found" with nothing to say why. It is refused here, at
    startup, where the reason can still be printed.
    """
    raw = raw.strip()
    if not raw:
        return None
    if raw.lstrip("-").isdigit():
        return int(raw)
    if raw.startswith("@") and len(raw) > 1:
        return raw
    if "t.me/" in raw or "telegram.me/" in raw or raw.startswith("+"):
        log.warning(
            "STORAGE_CHAT_ID is an invite link (%s). A bot cannot join by link: "
            "add it to the channel as an admin instead, and it will keep the id "
            "itself. Ignoring the setting for now.", raw)
        return None
    log.warning("STORAGE_CHAT_ID=%r is neither a numeric id nor an @name; ignoring it.",
                raw)
    return None


# Inline results must reference stored files; this chat is where they get uploaded.
STORAGE_CHAT: str | int | None = _storage_chat(os.getenv("STORAGE_CHAT_ID", ""))


# Telegram keeps undelivered updates for 24 hours, so a bot that was down all
# night would wake up and answer the whole backlog at once. A command worth
# answering is a recent one; anything older than this is left alone.
MAX_MESSAGE_AGE = timedelta(minutes=5)


async def ignore_stale(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stop updates that queued up while the bot was offline."""
    message = update.message
    if message is None or message.date is None:
        return
    # A queue the owner emptied from the panel: everything sent before that
    # moment is gone, including what Telegram had not handed over yet.
    cutoff = context.bot_data.get("queue_cutoff", 0)
    if cutoff and message.date.timestamp() <= cutoff:
        log.info("dropping a flushed message in %s", message.chat_id)
        raise ApplicationHandlerStop
    age = datetime.now(timezone.utc) - message.date
    if age > MAX_MESSAGE_AGE:
        log.info("ignoring a message %.0f minutes old in %s",
                 age.total_seconds() / 60, message.chat_id)
        raise ApplicationHandlerStop


def _t(key: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    return i18n.t(key, i18n.resolve(update, context.user_data))


async def _send(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str) -> None:
    text = _t(key, update, context).replace("@BOT", f"@{context.bot.username}")
    await update.effective_message.reply_html(text)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Pressing Start is what makes someone reachable, so it is recorded even
    # when the channel turns them away: they are a user of the bot from this
    # moment, they just cannot use it yet.
    context.user_data["started"] = True
    if not await _require_channel(update, context, "need_channel_start"):
        return
    await _send(update, context, "welcome")


async def _has_started(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Whether this user has ever opened a chat with the bot.

    Telegram exposes no flag for it, but it does refuse to let a bot contact
    someone who never started it — so a chat action that costs the user nothing
    answers the question. The result is remembered, so it is asked once.
    """
    if context.user_data.get("started"):
        return True
    user = update.effective_user
    if user is None:
        return False
    try:
        await context.bot.send_chat_action(user.id, ChatAction.TYPING)
    except (Forbidden, BadRequest):
        return False
    context.user_data["started"] = True
    return True


# Asking Telegram on every command would be a round trip per command, and
# membership rarely changes. A "yes" is trusted for a while; a "no" is asked
# again almost immediately, because somebody refused is about to go and join.
_MEMBER_TTL = 10 * 60
_MEMBER_MISS_TTL = 20
_IN_CHANNEL = (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR,
               ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED)


async def _in_channel(bot, user_id: int, cache: dict) -> bool:
    """Whether this person is in the channel. True when there is no channel set.

    It fails open on purpose. If the bot is not an administrator of the channel
    Telegram answers "member list is inaccessible", and treating that as "not a
    member" would lock every user out of the bot over a misconfiguration the
    users cannot see or fix.
    """
    if not REQUIRED_CHANNEL:
        return True
    hit = cache.get(user_id)
    if hit is not None:
        answered, inside = hit
        if _fresh(answered, time.time(),
                  _MEMBER_TTL if inside else _MEMBER_MISS_TTL):
            return inside
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        inside = member.status in _IN_CHANNEL
    except TelegramError as exc:
        if "inaccessible" in str(exc).lower() or "not found" in str(exc).lower():
            log.warning(
                "cannot check %s: %s. Make the bot an administrator of it, or "
                "clear REQUIRED_CHANNEL. Letting everyone through meanwhile.",
                REQUIRED_CHANNEL, exc)
            return True
        log.info("membership check failed for %s: %s", user_id, exc)
        return True
    cache[user_id] = (time.time(), inside)
    return inside


async def _require_channel(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           key: str = "need_channel") -> bool:
    """Whether this person may go on, and the asking if they may not.

    `key` is which way of asking: the greeting at Start, or the plain one
    everywhere else.
    """
    user = update.effective_user
    if user is None:
        return True
    # Excused by the owner: either this person, or the whole chat they are in.
    allowed = admin.exempt(context)
    chat = getattr(update, "effective_chat", None)
    if user.id in allowed or (chat is not None and chat.id in allowed):
        return True
    cache = context.bot_data.setdefault("channel_members", {})
    if await _in_channel(context.bot, user.id, cache):
        return True
    lang = i18n.resolve(update, context.user_data)
    link = f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}"
    await update.effective_message.reply_text(
        i18n.t(key, lang),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(i18n.t("btn_channel", lang), url=link)]]),
    )
    return False


async def _require_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if await _has_started(update, context):
        return True
    lang = i18n.resolve(update, context.user_data)
    button = InlineKeyboardButton(
        i18n.t("btn_start", lang), url=f"https://t.me/{context.bot.username}?start=use"
    )
    await update.effective_message.reply_text(
        i18n.t("need_start", lang), reply_markup=InlineKeyboardMarkup([[button]])
    )
    return False


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


async def on_added_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Introduce the bot the moment it lands in a group."""
    member = update.my_chat_member
    if member.chat.type == "channel":
        await _adopt_storage(update, context)
        return
    if member.chat.type not in ("group", "supergroup"):
        return
    was = member.old_chat_member.status
    now = member.new_chat_member.status
    joined = was in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED) and now in (
        ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR
    )
    if not joined:
        return
    # Groups are greeted in Persian regardless of who added the bot: the intro is
    # read by everyone in the chat, not just by that one person.
    text = i18n.t("group_intro", "fa").replace("@BOT", f"@{context.bot.username}")
    try:
        await context.bot.send_message(member.chat.id, text, parse_mode="HTML")
    except TelegramError as exc:
        log.info("could not greet %s: %s", member.chat.id, exc)


def _same_chat(chat, named: str) -> bool:
    """Whether this chat is the one that setting names, by @name or by id."""
    named = named.strip()
    if not named:
        return False
    if named.lstrip("-").isdigit():
        return chat.id == int(named)
    # A private channel has no username at all, so this has to be asked for
    # rather than read.
    return (getattr(chat, "username", None) or "").lower() == named.lstrip("@").lower()


async def _adopt_storage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Take a channel the owner made the bot an admin of as the inline store.

    Inline results can only point at files Telegram already holds, so every card
    is uploaded somewhere first. A private channel is the tidy place for that,
    and a channel id cannot be typed by hand - it only arrives in an update like
    this one. So rather than asking for it to be copied into .env, the bot keeps
    it the moment it is handed one.

    Only the owner's channel is taken. Anyone may add a bot to their own channel,
    and a bot that adopted whichever one it was added to last would be storing
    its owner's files in a stranger's channel.
    """
    member = update.my_chat_member
    if member.new_chat_member.status != ChatMemberStatus.ADMINISTRATOR:
        return

    # A store named in .env is a decision someone made on purpose, and being
    # given admin rights somewhere else is not a reason to overrule it. Without
    # this, making the bot an admin of any channel - the announcements one, for
    # instance - silently moved every upload there.
    if STORAGE_CHAT:
        log.info("storage is set to %s in .env; leaving %s alone",
                 STORAGE_CHAT, member.chat.id)
        return

    # And the announcements channel is made an admin channel for the opposite
    # reason - so the bot can read its member list - so it is never the store,
    # whatever else is configured.
    if REQUIRED_CHANNEL and _same_chat(member.chat, REQUIRED_CHANNEL):
        log.info("%s is the announcements channel, not a store", REQUIRED_CHANNEL)
        return

    who = member.from_user
    if OWNER_ID is None or who is None or who.id != OWNER_ID:
        log.info("ignoring channel %s: added by %s, not the owner",
                 member.chat.id, who.id if who else "?")
        return

    context.bot_data["storage_chat"] = member.chat.id
    log.info("storage channel set to %s (%s)", member.chat.id, member.chat.title)
    try:
        await context.bot.send_message(OWNER_ID, "\n".join([
            "✅ این کانال از این به بعد انبار فایل‌های حالت inline است:",
            f"<b>{member.chat.title or member.chat.id}</b>",
            f"<code>{member.chat.id}</code>",
            "",
            "دیگر لازم نیست کاری بکنی — همین الان فعال شد و بعد از ریستارت هم یادش می‌ماند.",
            "اگر خواستی ثابتش کنی، همین عدد را در <code>.env</code> مقابل "
            "<code>STORAGE_CHAT_ID</code> بگذار.",
        ]), parse_mode="HTML")
    except TelegramError as exc:
        log.info("could not tell the owner about the storage channel: %s", exc)


# Rendering costs a second or two of CPU, and updates are handled one at a time,
# so one person holding the command down would starve a whole group. Two seconds
# is invisible in ordinary use and enough to stop that.
RENDER_COOLDOWN = 2.0


def _fresh(stamp: float, now: float, ttl: float) -> bool:
    """Whether `stamp` is within `ttl` of now, and is a time that can be trusted.

    Anything ahead of the clock is not: it is either a timestamp from before the
    clock was set, or - the way this was found - a monotonic() reading that was
    persisted and then outlived the boot it was counted from. Treating it as
    recent is what made the bot ignore two dozen people for a fortnight.
    """
    return 0 <= now - stamp < ttl


def _too_soon(context: ContextTypes.DEFAULT_TYPE) -> bool:
    last = context.user_data.get("last_render", 0.0)
    # Wall clock, not monotonic: this is written to disk and read back after a
    # restart, and monotonic counts from a boot that no longer exists by then.
    now = time.time()
    if _fresh(last, now, RENDER_COOLDOWN):
        return True
    context.user_data["last_render"] = now
    return False


AVATAR_QUOTA = 2   # how many times one person may choose a picture, ever


def _avatar_choice(context: ContextTypes.DEFAULT_TYPE,
                   author: authors.Author) -> tuple[str | None, str]:
    """(their chosen file, the source they asked to be shown)."""
    if author.kind != "user" or author.avatar_key is None:
        return None, authors.DEFAULT_SOURCE
    uid = author.avatar_key
    file_id = context.bot_data.get("avatars", {}).get(uid)
    source = context.bot_data.get("avatar_source", {}).get(uid)
    if source not in authors.SOURCES:
        # Someone who uploaded a picture meant it to be used.
        source = "custom" if file_id else authors.DEFAULT_SOURCE
    if source == "custom" and not file_id:
        source = authors.DEFAULT_SOURCE
    return file_id, source


def _template(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Which card the person asking for the quote has chosen.

    It follows the person, not the chat: user_data is per user everywhere, so a
    template picked in private is the one they get in every group too.
    """
    chosen = (context.user_data or {}).get("template")
    return chosen if chosen in render.TEMPLATES else render.DEFAULT_TEMPLATE


def _photo_file_id(message: Message | None) -> str | None:
    """The best-resolution photo on a message, if it carries one."""
    if message is None:
        return None
    if message.photo:
        return message.photo[-1].file_id
    doc = message.document
    if doc is not None and (doc.mime_type or "").startswith("image/"):
        return doc.file_id
    return None


async def cmd_avatar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Let someone pin a picture of their own to every quote attributed to them."""
    message = update.effective_message
    lang = i18n.resolve(update, context.user_data)
    if message.chat.type != "private":
        await message.reply_text(i18n.t("avatar_private_only", lang))
        return

    user_id = update.effective_user.id
    avatars = context.bot_data.setdefault("avatars", {})
    args = [a.lower() for a in (getattr(context, "args", None) or [])]

    if args and args[0] in ("off", "remove", "clear", "none", "حذف", "پاک"):
        key = "avatar_cleared" if avatars.pop(user_id, None) else "avatar_none"
        await message.reply_text(i18n.t(key, lang))
        return

    file_id = _photo_file_id(message) or _photo_file_id(message.reply_to_message)
    if file_id is None:
        await message.reply_html(i18n.t("avatar_how", lang))
        return

    used = context.bot_data.setdefault("avatar_uses", {}).get(user_id, 0)
    if used >= AVATAR_QUOTA:
        await message.reply_text(
            i18n.t("avatar_quota_spent", lang).format(quota=AVATAR_QUOTA)
        )
        return

    avatars[user_id] = file_id
    used += 1
    context.bot_data["avatar_uses"][user_id] = used
    context.bot_data.setdefault("avatar_source", {})[user_id] = "custom"
    key = "avatar_saved_last" if used >= AVATAR_QUOTA else "avatar_saved"
    await message.reply_text(i18n.t(key, lang).format(used=used, quota=AVATAR_QUOTA))


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Let someone say which picture should stand for them."""
    message = update.effective_message
    lang = i18n.resolve(update, context.user_data)
    if message.chat.type != "private":
        await message.reply_text(i18n.t("avatar_private_only", lang))
        return

    user_id = update.effective_user.id
    has_custom = bool(context.bot_data.get("avatars", {}).get(user_id))
    _, current = _avatar_choice(
        context, authors.Author("", "", user_id, "user", str(user_id))
    )
    rows = []
    for source in authors.SOURCES:
        if source == "custom" and not has_custom:
            continue
        mark = "✅ " if source == current else ""
        rows.append([InlineKeyboardButton(
            mark + i18n.t(f"src_{source}", lang), callback_data=f"src:{source}"
        )])
    rows.append([InlineKeyboardButton(
        i18n.t("btn_template", lang), callback_data="tpl:menu"
    )])
    # Switching source only turns the picture off; this is how it goes away for
    # good. It is offered last, and only to someone who has one to delete.
    if has_custom:
        rows.append([InlineKeyboardButton(
            i18n.t("btn_avatar_delete", lang), callback_data="avatar:delete"
        )])
    await message.reply_html(
        i18n.t("settings_prompt", lang), reply_markup=InlineKeyboardMarkup(rows)
    )


TEMPLATE_SHEET = Path(__file__).with_name("assets") / "templates.png"


def _template_keyboard(lang: str, current: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            ("✅ " if name == current else "") + i18n.t(f"tpl_{name}", lang),
            callback_data=f"tpl:{name}")]
        for name in render.TEMPLATE_ORDER
    ])


async def _send_templates(message: Message, context: ContextTypes.DEFAULT_TYPE,
                          lang: str) -> None:
    """The cards as one picture, with a button under each number.

    The picture is the same for everyone, so it is uploaded once and then sent
    by the file_id Telegram hands back. The file it was made from is stamped
    beside it: a template added or changed means a new sheet on disk, and the
    file_id from the old one has to be thrown away with it - otherwise the
    buttons offer four cards under a picture of three.
    """
    markup = _template_keyboard(lang, _template(context))
    caption = i18n.t("template_prompt", lang)

    if not TEMPLATE_SHEET.exists():
        await message.reply_text(caption, reply_markup=markup)
        return

    stat = TEMPLATE_SHEET.stat()
    stamp = f"{stat.st_size}:{int(stat.st_mtime)}"
    cached = context.bot_data.get("template_sheet") or {}
    if cached.get("stamp") == stamp and cached.get("id"):
        try:
            await message.reply_photo(cached["id"], caption=caption,
                                      reply_markup=markup)
            return
        except TelegramError as exc:
            # A file_id can stop working; the file on disk cannot.
            log.info("the template sheet file_id no longer works: %s", exc)
            context.bot_data.pop("template_sheet", None)

    with TEMPLATE_SHEET.open("rb") as fh:
        sent = await message.reply_photo(fh, caption=caption, reply_markup=markup)
    if sent.photo:
        context.bot_data["template_sheet"] = {
            "id": sent.photo[-1].file_id, "stamp": stamp}


async def cmd_template(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Choose which card the quotes are drawn on."""
    message = update.effective_message
    lang = i18n.resolve(update, context.user_data)
    if message.chat.type != "private":
        await message.reply_text(i18n.t("avatar_private_only", lang))
        return
    await _send_templates(message, context, lang)


async def on_template_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The template row of /settings: the picture comes as a message of its own."""
    query = update.callback_query
    await query.answer()
    await _send_templates(query.message, context,
                          i18n.resolve(update, context.user_data))


async def on_template_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    name = query.data.split(":", 1)[1]
    lang = i18n.resolve(update, context.user_data)
    if name not in render.TEMPLATES:
        await query.answer()
        return
    context.user_data["template"] = name
    await query.answer()
    # The picture stays; only the caption and the ticks change, so the three
    # cards are still there to compare against after choosing.
    said = i18n.t("template_set", lang).format(choice=i18n.t(f"tpl_{name}", lang))
    markup = _template_keyboard(lang, name)
    if query.message and query.message.photo:
        await query.edit_message_caption(caption=said, reply_markup=markup)
    else:
        await query.edit_message_text(said, reply_markup=markup)


async def on_source_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    source = query.data.split(":", 1)[1]
    lang = i18n.resolve(update, context.user_data)
    if source not in authors.SOURCES:
        await query.answer()
        return
    context.bot_data.setdefault("avatar_source", {})[update.effective_user.id] = source
    await query.answer()
    await query.edit_message_text(
        i18n.t("settings_set", lang).format(choice=i18n.t(f"src_{source}", lang))
    )


async def on_avatar_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Throw away the picture someone uploaded, from the settings screen.

    The quota is not given back, exactly as when /avatar off is used: it counts
    uploads, and deleting one does not un-upload it.
    """
    query = update.callback_query
    lang = i18n.resolve(update, context.user_data)
    user_id = update.effective_user.id
    had = context.bot_data.setdefault("avatars", {}).pop(user_id, None)
    if had:
        # Nothing left to point at, so the choice goes back to the default.
        context.bot_data.setdefault("avatar_source", {})[user_id] = authors.DEFAULT_SOURCE
    await query.answer()
    await query.edit_message_text(i18n.t("avatar_cleared" if had else "avatar_none", lang))


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
            ]
    else:
        lines.append("  (اگر ریپلای کرده‌ای و اینجا NO است، ربات ریپلای را نمی‌بیند:")
        lines.append("   ربات را از گروه حذف و دوباره اضافه کن.)")
    who = authors.resolve(target or message)
    lines += [
        f"quoting: {who.name} (@{who.handle or '-'})",
        f"avatar: {await authors.avatar_source(context.bot, who, *_avatar_choice(context, who))}",
    ]
    await message.reply_text(chr(10).join(lines))


async def _build_scene(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       target: Message, text: str):
    author = authors.resolve(target)
    avatar = await authors.fetch_avatar(
        context.bot, author, *_avatar_choice(context, author)
    )
    return await asyncio.to_thread(
        render.build_scene, avatar, text, author.name, WATERMARK,
        _template(context),
    )


async def _prepare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Find the message to quote: the replied-to one, or the command's own text.

    Returns (source message, text). The source is what we attribute the quote to
    and what we reply under, so "/q some words" quotes the sender themselves.
    """
    if not await _require_start(update, context):
        return None
    if not await _require_channel(update, context):
        return None
    if _too_soon(context):
        log.info("ignoring a burst from %s", update.effective_user.id)
        return None
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
        scene = await _build_scene(update, context, target, text)
        image = await asyncio.to_thread(scene.render)
        buf = await asyncio.to_thread(render.to_png, image)
        await message.reply_photo(buf, reply_to_message_id=target.message_id)
        admin.note(context, "quote")
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("quote render failed")
        await message.reply_text(_t("failed", update, context))


async def _announce_pack(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          webp: bytes) -> None:
    """File the sticker where it belongs, and say so only when the pack is new.

    A group's stickers go to that group's pack; anything made in private goes to
    the person's own. The two are different collections on purpose - a group's
    pack is a record of that room, and nobody's private quotes belong in it.
    """
    message = update.effective_message
    if message.chat.type in stickerpack.GROUP_TYPES:
        result = await stickerpack.add_quote(context.bot, message.chat, webp, OWNER_ID)
        created_key = "pack_created"
    else:
        result = await stickerpack.add_personal(
            context.bot, update.effective_user, webp, OWNER_ID)
        created_key = "mypack_created"
    if result and result[1]:
        await message.reply_text(
            _t(created_key, update, context).format(link=result[0]),
            disable_web_page_preview=True,
        )


async def cmd_quote_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prepared = await _prepare(update, context)
    if prepared is None:
        return
    target, text = prepared
    message = update.effective_message
    await message.chat.send_action(ChatAction.CHOOSE_STICKER)
    try:
        scene = await _build_scene(update, context, target, text)
        image = await asyncio.to_thread(scene.render)
        buf = await asyncio.to_thread(render.to_sticker_webp, image)
        webp = buf.getvalue()
        await message.reply_sticker(io.BytesIO(webp),
                                    reply_to_message_id=target.message_id)
        admin.note(context, "sticker")
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("quote sticker failed")
        await message.reply_text(_t("failed", update, context))
        return

    # The sticker is already delivered; the pack is a bonus that may quietly fail.
    await _announce_pack(update, context, webp)


async def cmd_mypack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hand back the link to this person's own pack."""
    message = update.effective_message
    if message.chat.type != "private":
        await message.reply_text(_t("avatar_private_only", update, context))
        return
    link = await stickerpack.personal_link(context.bot, update.effective_user.id)
    if link is None:
        await message.reply_html(_t("mypack_none", update, context))
        return
    lang = i18n.resolve(update, context.user_data)
    await message.reply_text(
        _t("mypack_link", update, context).format(link=link),
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
            i18n.t("btn_pack_rename", lang), callback_data="mypack:rename")]]),
    )


async def on_pack_rename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask for the new title. The next thing they type is it."""
    query = update.callback_query
    context.user_data["await_pack_title"] = True
    await query.answer()
    await query.edit_message_text(_t("mypack_rename_ask", update, context))


async def on_pack_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Whatever they typed while the bot was waiting for a pack title."""
    if not context.user_data.pop("await_pack_title", False):
        return
    title = (update.effective_message.text or "").strip()
    if not title:
        return
    ok = await stickerpack.rename_personal(
        context.bot, update.effective_user.id, title)
    key = "mypack_renamed" if ok else "mypack_rename_failed"
    await update.effective_message.reply_text(
        _t(key, update, context).format(title=title[:stickerpack.MAX_TITLE]))


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


async def _is_group_admin(bot, chat, user) -> bool:
    """Whether this person runs this group."""
    if user is None:
        return False
    try:
        member = await bot.get_chat_member(chat.id, user.id)
    except TelegramError:
        return False
    return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)


async def cmd_unpack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove the replied-to sticker from this group's pack.

    The pack belongs to the group, so the group's admins decide what stays in
    it. Replying to the sticker is the whole interface: it is the one place the
    sticker can be pointed at without listing the pack out in a message.
    """
    message = update.effective_message
    if message.chat.type == "private":
        target = message.reply_to_message
        outcome = await stickerpack.remove_personal(
            context.bot, update.effective_user.id,
            target.sticker if target else None)
        await message.reply_text(_t({
            "ok": "mypack_removed",
            "not_ours": "mypack_not_yours",
            "no_sticker": "mypack_need_reply",
        }.get(outcome, "unpack_failed"), update, context))
        return
    if message.chat.type not in stickerpack.GROUP_TYPES:
        await message.reply_text(_t("pack_groups_only", update, context))
        return
    if not await _is_group_admin(context.bot, message.chat, update.effective_user):
        await message.reply_text(_t("unpack_not_admin", update, context))
        return

    target = message.reply_to_message
    sticker = target.sticker if target else None
    if sticker is None:
        await message.reply_text(_t("unpack_need_reply", update, context))
        return

    outcome = await stickerpack.remove_quote(context.bot, message.chat, sticker)
    key = {
        "ok": "unpack_done",
        "not_ours": "unpack_not_ours",
        "no_sticker": "unpack_need_reply",
        "not_group": "pack_groups_only",
    }.get(outcome, "unpack_failed")
    await message.reply_text(_t(key, update, context))


async def cmd_delpack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Offer to delete a whole pack: the group's here, or your own in private.

    Nothing is deleted by the command itself. It asks, because this is the only
    thing the bot does that cannot be undone and that takes something away from
    people who are not in the conversation.
    """
    message = update.effective_message
    lang = i18n.resolve(update, context.user_data)
    private = message.chat.type == "private"

    if not private:
        if message.chat.type not in stickerpack.GROUP_TYPES:
            await message.reply_text(_t("pack_groups_only", update, context))
            return
        if not await _is_group_admin(context.bot, message.chat, update.effective_user):
            await message.reply_text(_t("delpack_not_admin", update, context))
            return

    what = "me" if private else "group"
    key = "delpack_ask_personal" if private else "delpack_ask_group"
    await message.reply_html(
        i18n.t(key, lang),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(i18n.t("btn_delpack_no", lang),
                                 callback_data="delpack:no"),
            InlineKeyboardButton(i18n.t("btn_delpack_yes", lang),
                                 callback_data=f"delpack:{what}"),
        ]]),
    )


async def on_delpack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The answer to that question.

    Whoever presses the button is checked again, not whoever asked. A message
    with buttons sits in the chat where anyone can reach it, so the permission
    has to be read at the moment it is used.
    """
    query = update.callback_query
    what = query.data.split(":", 1)[1]
    message = query.message

    if what == "no":
        await query.answer()
        await query.edit_message_text(_t("delpack_cancelled", update, context))
        return

    if what == "group":
        if message.chat.type not in stickerpack.GROUP_TYPES:
            await query.answer()
            return
        if not await _is_group_admin(context.bot, message.chat, update.effective_user):
            await query.answer(_t("delpack_not_admin", update, context),
                               show_alert=True)
            return
        outcome = await stickerpack.delete_group(context.bot, message.chat)
    else:
        if message.chat.type != "private":
            await query.answer()
            return
        outcome = await stickerpack.delete_personal(
            context.bot, update.effective_user.id)

    await query.answer()
    await query.edit_message_text(_t({
        "ok": "delpack_done",
        "no_pack": "delpack_none",
        "not_group": "pack_groups_only",
    }.get(outcome, "delpack_failed"), update, context))


async def cmd_quote_gif(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prepared = await _prepare(update, context)
    if prepared is None:
        return
    target, text = prepared
    message = update.effective_message
    await message.chat.send_action(ChatAction.UPLOAD_VIDEO)
    try:
        scene = await _build_scene(update, context, target, text)
        buf, ext = await asyncio.to_thread(animate.to_animation, scene)
        await message.reply_animation(
            buf, filename=f"quote.{ext}", reply_to_message_id=target.message_id
        )
        admin.note(context, "gif")
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


async def _badge(bot, chat, author: authors.Author,
                 lang: str) -> tuple[str, bool] | None:
    """The pill Telegram shows beside a name in a group.

    Three things can put one there, and they are checked in the order the app
    shows them:

      the member tag   any member can be given one by an admin, whatever their
                       status. It is a recent addition to the API, and the
                       version of python-telegram-bot here does not model it -
                       it arrives in api_kwargs, which is where unknown fields
                       land - so it has to be read out by name.
      a custom title   an admin's own rank, set by the group.
      owner / admin    the generic word, when an admin has no title of their own.

    An ordinary member with no tag gets nothing, which is what the app draws.

    Returns the text and whether it is an admin's badge. The app draws the two
    differently - an admin's in a coloured pill, a member's as plain grey text -
    so the renderer has to be told which it is holding.
    """
    if chat.type not in ("group", "supergroup") or author.kind != "user":
        return None
    if author.avatar_key is None:
        return None
    try:
        member = await bot.get_chat_member(chat.id, author.avatar_key)
    except TelegramError as exc:
        log.info("no badge for %s in %s: %s", author.avatar_key, chat.id, exc)
        return None

    is_admin = member.status in (ChatMemberStatus.OWNER,
                                 ChatMemberStatus.ADMINISTRATOR)

    tag = str((member.api_kwargs or {}).get("tag") or "").strip()
    if tag:
        return tag, is_admin

    if not is_admin:
        return None
    # Whatever this group actually calls them wins; the generic word is the
    # fallback Telegram itself shows when nobody has set a title.
    title = (getattr(member, "custom_title", None) or "").strip()
    if title:
        return title, True
    return i18n.t(
        "badge_owner" if member.status == ChatMemberStatus.OWNER else "badge_admin",
        lang,
    ), True


async def on_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Keep a running count of the reactions on messages in this chat.

    Telegram will not tell us what a message already carries, so the only way a
    screenshot can show reactions is to have been watching when they arrived.
    This costs a dictionary update and nothing else.
    """
    if update.message_reaction is not None:
        reactions.record_change(context.bot_data, update)
    elif update.message_reaction_count is not None:
        reactions.record_totals(context.bot_data, update)


async def cmd_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prepared = await _prepare(update, context)
    if prepared is None:
        return
    target, text = prepared
    message = update.effective_message
    await message.chat.send_action(ChatAction.UPLOAD_PHOTO)
    try:
        author = authors.resolve(target)
        avatar = await authors.fetch_avatar(
            context.bot, author, *_avatar_choice(context, author)
        )
        marked = await _badge(context.bot, message.chat, author,
                              i18n.resolve(update, context.user_data))
        badge, badge_is_admin = marked if marked else (None, False)
        seen = reactions.for_message(
            context.bot_data, message.chat_id, target.message_id)
        image = await asyncio.to_thread(
            screenshot.render, avatar, author.name, text,
            _clock(target.date), badge, author.seed, seen, badge_is_admin,
        )
        buf = await asyncio.to_thread(screenshot.to_png, image)
        await message.reply_photo(buf, reply_to_message_id=target.message_id)
        admin.note(context, "screenshot")
        webp = (await asyncio.to_thread(render.to_sticker_webp, image)).getvalue()
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("screenshot render failed")
        await message.reply_text(_t("failed", update, context))
        return

    await _announce_pack(update, context, webp)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    where = "unknown"
    if isinstance(update, Update):
        message = update.effective_message
        where = (f"chat {update.effective_chat.id if update.effective_chat else '?'}"
                 f", text {message.text!r}" if message else "no message")
    log.error("handler error (%s)", where, exc_info=context.error)
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
        core = [BotCommand(n, d) for n, d in i18n.COMMANDS[lang]]
        extra = [BotCommand(n, d) for n, d in i18n.PRIVATE_ONLY[lang]]
        # A group's "/" menu stays short; help and lang belong in the bot's own chat.
        await app.bot.set_my_commands(
            core + extra, scope=BotCommandScopeAllPrivateChats(), **kwargs
        )
        await app.bot.set_my_commands(
            core, scope=BotCommandScopeAllGroupChats(), **kwargs
        )
        await app.bot.set_my_commands(core, **kwargs)  # anywhere else
        await app.bot.set_my_description(
            i18n.DESCRIPTIONS[lang].replace("@BOT", f"@{username}"), **kwargs
        )
        await app.bot.set_my_short_description(
            i18n.SHORT_DESCRIPTIONS[lang].replace("@BOT", f"@{username}"), **kwargs
        )

    # Persian is the default here for the same reason it is in i18n: English goes
    # only to clients that ask for it, everyone else gets Persian.
    await publish("fa")
    await publish("en", language_code="en")


async def on_chosen_inline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """File an inline quote in its maker's pack, once they have actually sent it.

    Offering three results is not the same as sending one. Filing at the moment
    they were offered put a sticker in someone's pack for every phrase they
    typed and thought better of.

    Telegram only sends this update when inline feedback is switched on for the
    bot (BotFather, /setinlinefeedback). Without it nothing arrives here and
    nothing is filed - which is the safe way round.
    """
    chosen = update.chosen_inline_result
    if chosen is None:
        return
    sticker_id = inline.sticker_for(context, chosen.result_id)
    if sticker_id is None:
        log.debug("chosen result %s is not one we remember", chosen.result_id)
        return
    try:
        # A file_id already on Telegram's servers is a sticker they will accept,
        # so nothing has to be rendered or uploaded a second time.
        await stickerpack.add_personal(
            context.bot, chosen.from_user, sticker_id, OWNER_ID)
    except TelegramError as exc:
        log.info("could not file a sent inline sticker for %s: %s",
                 chosen.from_user.id, exc)


async def _inline_gate(context: ContextTypes.DEFAULT_TYPE, user) -> str | None:
    """What stands between this person and an inline result, if anything.

    Inline mode used to be the one way in that asked for nothing. That was not
    a decision, it was an oversight: the same two rules apply here as anywhere.
    """
    if not context.user_data.get("started"):
        try:
            await context.bot.send_chat_action(user.id, ChatAction.TYPING)
        except (Forbidden, BadRequest):
            return "inline_need_start"
        context.user_data["started"] = True
    if user.id in admin.exempt(context):
        return None
    cache = context.bot_data.setdefault("channel_members", {})
    if not await _in_channel(context.bot, user.id, cache):
        return "need_channel"
    return None


def register(app: Application) -> None:
    """Attach every handler to the application.

    Groups matter here and are easy to get wrong: only the first matching
    handler in a group runs, so two handlers that both match everything must
    not share one. Keeping this out of main() is what lets the self test build
    an application and look at what actually got registered.
    """
    # Runs before everything else, so a stale command never reaches a handler.
    app.add_handler(TypeHandler(Update, ignore_stale), group=-2)
    # Then the bookkeeping: who is using the bot, and who may not. It must be
    # a group of its own: only the first matching handler in a group runs, and
    # the stale check above matches every update there is - sharing a group
    # with it meant this never ran at all.
    app.add_handler(TypeHandler(Update, admin.make_tracker(OWNER_ID)), group=-1)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("lang", cmd_lang))
    app.add_handler(CallbackQueryHandler(on_lang_choice, pattern=r"^lang:"))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler("pack", cmd_pack))
    app.add_handler(CommandHandler(["mypack", "my_pack", "mypak"], cmd_mypack))
    app.add_handler(CommandHandler(["unpack", "unpak", "delsticker"], cmd_unpack))
    app.add_handler(CommandHandler(["delpack", "deletepack", "dellpack"], cmd_delpack))
    app.add_handler(CommandHandler(["avatar", "avatr", "avater"], cmd_avatar))
    app.add_handler(CommandHandler(["settings", "setting"], cmd_settings))
    app.add_handler(CommandHandler(
        ["template", "templates", "tpl", "style"], cmd_template))
    app.add_handler(CallbackQueryHandler(on_source_choice, pattern=r"^src:"))
    app.add_handler(CallbackQueryHandler(on_avatar_delete, pattern=r"^avatar:delete$"))
    app.add_handler(CallbackQueryHandler(on_pack_rename, pattern=r"^mypack:rename$"))
    # The menu button first: "tpl:menu" would otherwise be read as a template
    # named "menu", and only the first matching handler in a group runs.
    app.add_handler(CallbackQueryHandler(on_delpack, pattern=r"^delpack:"))
    app.add_handler(CallbackQueryHandler(on_template_menu, pattern=r"^tpl:menu$"))
    app.add_handler(CallbackQueryHandler(on_template_choice, pattern=r"^tpl:"))
    # The operator's own panel: unlisted, and silent for everybody else.
    cmd_admin, on_admin_button, on_admin_input = admin.make_panel(OWNER_ID)
    app.add_handler(CommandHandler(["admin", "panel"], cmd_admin))
    app.add_handler(CallbackQueryHandler(on_admin_button, pattern=r"^adm:"))
    # A photo captioned /avatar: CommandHandler only ever looks at message text.
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.IMAGE)
        & filters.CaptionRegex(r"(?i)^/avat"), cmd_avatar))
    # What the owner types while the panel is waiting for it. Registered before
    # the quote handlers so a broadcast draft is never mistaken for a command,
    # and narrowed to the owner so nobody else's message ever reaches it.
    if OWNER_ID is not None:
        app.add_handler(MessageHandler(
            filters.User(OWNER_ID) & filters.ChatType.PRIVATE
            & ~filters.COMMAND & ~filters.REPLY, on_admin_input))
    # The menu lists the first name of each; the rest are common misspellings,
    # unlisted, so a slip of the fingers still does what was meant.
    app.add_handler(CommandHandler(
        ["quote", "qoute", "quto", "qute", "quot", "quoet"], cmd_quote))
    app.add_handler(CommandHandler(
        ["sticker", "stiker", "stickr", "sticekr", "stcker"], cmd_quote_sticker))
    app.add_handler(CommandHandler(["gif", "gfi"], cmd_quote_gif))
    app.add_handler(CommandHandler(
        ["screenshot", "screenshoot", "screanshot", "screnshot", "sceenshot"],
        cmd_screenshot))
    # Saying it in plain Persian instead of typing a command. These are ordinary
    # messages, so in a group they only reach the bot once it is an admin.
    # "اینو استیکرش کن لطفا!" should work as readily as "استیکرش کن".
    lead = r"^\s*(?:این\s*(?:رو|و)?\s*)?"
    tail = r"\s*(?:لطفا|لطفاً|please)?\s*[.!?؟،]*\s*$"
    do = r"\s*(?:کن|کنید)"
    triggers = [
        (lead + r"(?:کوت|نقل\s*قول|quote)(?:\s*ش)?(?:" + do + r")?" + tail, cmd_quote),
        (lead + r"(?:استیکر|sticker)(?:\s*ش)?" + do + tail, cmd_quote_sticker),
        (lead + r"(?:گیف|gif)(?:\s*ش)?" + do + tail, cmd_quote_gif),
        (lead + r"(?:شات|اسکرین\s*شات|screenshot)(?:\s*ش)?" + do + tail, cmd_screenshot),
    ]
    for pattern, handler in triggers:
        app.add_handler(MessageHandler(
            filters.REPLY & filters.Regex(re.compile(pattern, re.IGNORECASE)), handler
        ))
    # A group of its own: the owner's panel already takes private text in group
    # 0, and only the first matching handler in a group runs, so sharing one
    # would mean the owner could never rename their own pack.
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.REPLY,
        on_pack_title), group=1)
    app.add_handler(ChatMemberHandler(on_added_to_group, ChatMemberHandler.MY_CHAT_MEMBER))
    # Reactions are only delivered while the bot is an administrator of the
    # group, and only from the moment it became one.
    app.add_handler(MessageReactionHandler(on_reaction))
    app.add_handler(InlineQueryHandler(
        inline.make_handler(WATERMARK, STORAGE_CHAT, _inline_gate)))
    app.add_handler(ChosenInlineResultHandler(on_chosen_inline))
    app.add_error_handler(on_error)


def _ensure_event_loop() -> None:
    """Give run_polling a loop to find on Python 3.14.

    3.14 stopped having asyncio.get_event_loop() create one when the thread has
    none, and python-telegram-bot 21.9 calls it on the way into run_polling - so
    the bot died at startup with "There is no current event loop in thread
    'MainThread'". This is what PTB 22.8 does about it upstream; when we move to
    that version, this can go.
    """
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


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
        # The defaults are five seconds for everything, which is fine for a text
        # reply and much too tight for uploading a video over a slow or proxied
        # link — Telegram also takes its time answering a video upload. That is
        # how /gif ends up posting "sending video" and then nothing.
        .connect_timeout(20.0)
        .read_timeout(40.0)
        .write_timeout(60.0)
        .media_write_timeout(180.0)
        .pool_timeout(10.0)
        .rate_limiter(AIORateLimiter())
        .persistence(PicklePersistence(filepath=STATE_FILE))
        .post_init(post_init)
    )
    if PROXY:
        # Both the API calls and the long-polling connection need the proxy.
        log.info("using proxy %s", PROXY)
        builder = builder.proxy(PROXY).get_updates_proxy(PROXY)
    app = builder.build()

    register(app)

    _ensure_event_loop()
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
