"""Telegram quote bot: reply to a message and turn it into a card, sticker or GIF."""
from __future__ import annotations

import asyncio
import html
import io
import logging
import logging.handlers
import time
import re
import os
import uuid
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
    InputMediaAnimation,
    Message,
    Update,
)
from telegram.constants import ChatAction, ChatMemberStatus, MessageEntityType
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
import convert
import extract
import fire
import gallery
import fonts
import i18n
import inline
import reactions
import render
import screenshot
import stickerpack
import textkit
import throttle

load_dotenv()

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Everything the bot writes - its state and its log - goes in one directory.
# On the server that is /var/lib/quoto, kept apart from the code so the code
# can be read-only to the bot: a process that can rewrite its own source, or
# the pickle it loads at startup, turns any one bug into a permanent foothold.
# Unset, it is the code's own directory, which is what a laptop wants.
STATE_DIR = Path(os.getenv("STATE_DIR", "").strip() or Path(__file__).parent)

# The console window is gone the moment it is closed, and a failure that happens
# once an hour is impossible to catch by watching it. Everything also goes to a
# file, rotated so it cannot grow without bound.
LOG_FILE = STATE_DIR / "quotebot.log"
admin.LOG_FILE = LOG_FILE
_log_file = logging.handlers.RotatingFileHandler(
    LOG_FILE, maxBytes=2_000_000, backupCount=2, encoding="utf-8",
)
_log_file.setFormatter(logging.Formatter(LOG_FORMAT))
logging.getLogger().addHandler(_log_file)

log = logging.getLogger("quotebot")

TOKEN = os.getenv("BOT_TOKEN", "").strip()
WATERMARK = os.getenv("WATERMARK", "").strip()
STATE_FILE = str(STATE_DIR / (os.getenv("STATE_FILE", "").strip() or "botdata.pkl"))
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


def _as_chat(update: Update) -> bool:
    """Whether the message was sent as a chat: as a channel, or by an anonymous admin.

    Telegram fills the sender in with a stand-in bot account then - Channel_Bot,
    GroupAnonymousBot - and puts the real sender in sender_chat. It is a person
    all the same, just not one with an account the bot can see; treating the
    stand-in as a bot ignored them, and asking it to press Start asked the
    impossible.
    """
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    return bool(getattr(user, "is_bot", False)
                and getattr(message, "sender_chat", None) is not None)


async def _require_channel(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           key: str = "need_channel") -> bool:
    """Whether this person may go on, and the asking if they may not.

    `key` is which way of asking: the greeting at Start, or the plain one
    everywhere else.
    """
    user = update.effective_user
    if user is None or _as_chat(update):
        return True     # a channel or an anonymous admin has nobody to join with
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
    if _as_chat(update):
        return True     # a channel cannot press Start; its files go where the reply is
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
            f"<b>{html.escape(member.chat.title or str(member.chat.id))}</b>",
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
    return authors.choice_for(context.bot_data, author)


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
    # A picture sent as a file is not recompressed by Telegram, so it can be
    # anything its sender made it: only the formats a card can use, and only
    # at the size of a photo. The type is the sender's word for it, so the
    # decoder checks again, but there is no reason to take it on at all.
    doc = message.document
    if (doc is not None and doc.mime_type in AVATAR_DOC_TYPES
            and (doc.file_size or 0) <= authors.MAX_AVATAR_BYTES):
        return doc.file_id
    return None


AVATAR_DOC_TYPES = ("image/jpeg", "image/png", "image/webp")


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

    # The base allowance plus whatever the owner has handed out from the panel,
    # to this person or to everyone.
    allowed = AVATAR_QUOTA + admin.extra_quota(context, user_id)
    used = context.bot_data.setdefault("avatar_uses", {}).get(user_id, 0)
    if used >= allowed:
        await message.reply_text(
            i18n.t("avatar_quota_spent", lang).format(quota=allowed)
        )
        return

    avatars[user_id] = file_id
    used += 1
    context.bot_data["avatar_uses"][user_id] = used
    context.bot_data.setdefault("avatar_source", {})[user_id] = "custom"
    key = "avatar_saved_last" if used >= allowed else "avatar_saved"
    await message.reply_text(i18n.t(key, lang).format(used=used, quota=allowed))


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
    # Laying a long quote out is real work too; it waits its turn with the rest.
    return await throttle.RENDER.run(
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
    typed = " ".join(getattr(context, "args", None) or []).strip()
    # Words for the result can follow the command. With a reply the rest of
    # the command is otherwise unused; without one it is the quote itself,
    # so there the words have to be set apart, with a comma or a new line.
    typed, words = split_caption(typed, loose=target is not None)
    if words is not None:
        context.caption_words = words
    if target is None:
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


# The CPU-bound halves of the commands, each one job for the render gate.
def _card_png(scene):
    return render.to_png(scene.render())


def _card_webp(scene) -> bytes:
    return render.to_sticker_webp(scene.render()).getvalue()


def _screenshot_sticker(*args) -> bytes:
    """The message as a sticker: the bubble alone, on a transparent background."""
    return screenshot.sticker(*args)


async def cmd_quote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prepared = await _prepare(update, context)
    if prepared is None:
        return
    target, text = prepared
    message = update.effective_message
    await message.chat.send_action(ChatAction.UPLOAD_PHOTO)
    try:
        scene = await _build_scene(update, context, target, text)
        buf = await throttle.RENDER.run(_card_png, scene)
        if _words_for(context):
            buf = io.BytesIO(await _with_words("photo", buf.getvalue(), _words_for(context)))
        await message.reply_photo(buf, reply_to_message_id=target.message_id)
        admin.note(context, "quote")
    except throttle.Busy:
        await message.reply_text(_t("busy", update, context))
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
        if not context.user_data.get("auto_pack", True):
            return              # they asked for only the stickers they choose
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
        webp = await throttle.RENDER.run(_card_webp, scene)
        webp = await _with_words("sticker", webp, _words_for(context))
        await message.reply_sticker(io.BytesIO(webp),
                                    reply_to_message_id=target.message_id)
        admin.note(context, "sticker")
    except throttle.Busy:
        await message.reply_text(_t("busy", update, context))
        return
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
    auto = context.user_data.get("auto_pack", True)
    await message.reply_text(
        _t("mypack_link", update, context).format(link=link),
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(i18n.t("btn_pack_rename", lang), callback_data="mypack:rename")],
            [InlineKeyboardButton(i18n.t("btn_auto_on" if auto else "btn_auto_off", lang),
                                  callback_data="cpk:auto")],
        ]),
    )


PACK_TITLE_WAIT = 10 * 60


async def on_pack_rename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask for the new title. The next thing they type is it."""
    query = update.callback_query
    context.user_data["await_pack_title"] = time.time()
    await query.answer()
    await query.edit_message_text(_t("mypack_rename_ask", update, context))


async def on_pack_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Whatever they typed while the bot was waiting for a pack title.

    Only for a while after the button. Waiting for good meant that someone who
    pressed it and changed their mind had their pack renamed days later, after
    whatever they next wrote to the bot.
    """
    asked = context.user_data.pop("await_pack_title", None)
    # True is how the wait was written down before it carried a time.
    if asked is None or asked is True or not _fresh(asked, time.time(), PACK_TITLE_WAIT):
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
    link = await stickerpack.link_for_adopting(context.bot, message.chat, OWNER_ID)
    if link is None:
        await message.reply_text(_t("pack_none", update, context))
        return
    await message.reply_text(
        _t("pack_link", update, context).format(link=link),
        disable_web_page_preview=True,
    )


async def _runs_group(bot, update: Update) -> bool:
    """Whether whoever sent this runs the group it was sent in.

    An admin who posts anonymously is signed as the group itself, with a
    stand-in bot as the sender - and only admins can post that way, so that
    is proof enough. Everyone else is checked by asking Telegram.
    """
    message = update.effective_message
    sender_chat = getattr(message, "sender_chat", None)
    if sender_chat is not None and message.chat is not None and sender_chat.id == message.chat.id:
        return True
    return await _is_group_admin(bot, message.chat, update.effective_user)


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
        outcome = await stickerpack.remove_from_own(
            context.bot,
            _own_pack_names(context.bot.username, update.effective_user.id, context.user_data),
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
    if not await _runs_group(context.bot, update):
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


MYGIFS_SHOWN = 8       # sent at once; a search narrows it down from there


async def cmd_mygifs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """This person's GIFs, sent back here: the newest, or one person's.

    "/mygifs" alone sends the newest few; "/mygifs ali" sends the ones of Ali
    - by name, username or numeric id. It used to open a gallery in inline
    mode, which is switched off now; sending them here is what that gallery
    was for in the end, and they can be forwarded on from here.
    """
    message = update.effective_message
    lang = i18n.resolve(update, context.user_data)
    if message.chat.type != "private":
        await message.reply_text(i18n.t("avatar_private_only", lang))
        return
    term = " ".join(context.args or []).strip()
    archive = context.user_data.get(gallery.KEY) or []
    if not archive:
        await message.reply_html(i18n.t("mygifs_none", lang))
        return
    found = gallery.search(context.user_data, term)
    if not found:
        await message.reply_text(i18n.t("gallery_none", lang).format(term=term[:40]))
        return
    if term:
        # The term is theirs and goes into HTML: escaped, not trusted.
        await message.reply_html(i18n.t("mygifs_found", lang).format(
            count=len(found), term=html.escape(term[:40])))
    else:
        await message.reply_html(i18n.t("mygifs_intro", lang).format(
            count=len(archive), people=gallery.people(context.user_data)))
    for entry in found[:MYGIFS_SHOWN]:
        try:
            await message.reply_animation(entry["f"])
        except TelegramError as exc:
            # A file_id can stop working; the rest of the list still can.
            log.info("an archived GIF could not be sent: %s", exc)
    if len(found) > MYGIFS_SHOWN:
        await message.reply_html(i18n.t("mygifs_more", lang).format(
            rest=len(found) - MYGIFS_SHOWN))


async def cmd_deletemydata(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Offer to forget what the bot keeps about this person. Asks first."""
    message = update.effective_message
    lang = i18n.resolve(update, context.user_data)
    if message.chat.type != "private":
        await message.reply_text(i18n.t("avatar_private_only", lang))
        return
    await message.reply_html(
        i18n.t("forget_ask", lang),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(i18n.t("btn_delpack_no", lang), callback_data="forget:no"),
            InlineKeyboardButton(i18n.t("btn_forget_yes", lang), callback_data="forget:yes"),
        ]]),
    )


def forget_user(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Everything kept about this person, gone - except what keeps the rules.

    Kept on purpose: how many avatar uploads they have used (forgetting it
    would hand out a fresh allowance to anyone who asked), and whether the
    owner blocked or excused them. Those are numbers and ids, and they are
    what the owner's decisions rest on.
    """
    store = context.bot_data
    file_id = (store.get("avatars") or {}).pop(user_id, None)
    if file_id:
        authors.forget(f"custom:{file_id}")
    authors.forget_prefix(f"user:{user_id}:")
    (store.get("avatar_source") or {}).pop(user_id, None)
    (store.get("users") or {}).pop(user_id, None)
    (store.get("channel_members") or {}).pop(user_id, None)
    inline.forget_user(store, user_id)
    context.application.drop_user_data(user_id)


async def on_forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    lang = i18n.resolve(update, context.user_data)
    await query.answer()
    if query.data != "forget:yes" or query.message.chat.type != "private":
        await query.edit_message_text(i18n.t("forget_cancelled", lang))
        return
    forget_user(context, update.effective_user.id)
    log.info("forgot a user at their request")
    await query.edit_message_text(i18n.t("forget_done", lang))


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
        if not await _runs_group(context.bot, update):
            await message.reply_text(_t("delpack_not_admin", update, context))
            return

    if private and _own_packs(context.user_data):
        # Their own packs too: which one goes is theirs to say.
        rows = [[InlineKeyboardButton(i18n.t("btn_delpack_personal", lang),
                                      callback_data="delpack:me")]]
        rows += [[InlineKeyboardButton("🗑 " + p["title"][:40], callback_data=f"delpack:c{p['n']}")]
                 for p in _own_packs(context.user_data)]
        rows.append([InlineKeyboardButton(i18n.t("btn_delpack_no", lang),
                                          callback_data="delpack:no")])
        await message.reply_html(i18n.t("delpack_choose", lang),
                                 reply_markup=InlineKeyboardMarkup(rows))
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
    elif what.startswith("c") and what[1:].isdigit():
        if message.chat.type != "private":
            await query.answer()
            return
        n = int(what[1:])
        packs = _own_packs(context.user_data)
        if not any(p["n"] == n for p in packs):
            await query.answer()
            return
        outcome = await stickerpack.delete_named(
            context.bot, stickerpack.custom_name(update.effective_user.id, n, context.bot.username))
        if outcome in ("ok", "no_pack"):
            # Gone from Telegram, or never made it there: either way, gone from the list.
            packs[:] = [p for p in packs if p["n"] != n]
            outcome = "ok"
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
        buf, ext = await throttle.RENDER.run(animate.to_animation, scene)
        if ext == "mp4" and _words_for(context):
            buf = io.BytesIO(await _with_words("animation", buf.getvalue(), _words_for(context)))
        sent = await message.reply_animation(
            buf, filename=f"quote.{ext}", reply_to_message_id=target.message_id
        )
        admin.note(context, "gif")
        # Filed under whoever made it, so they can find it again by who is in it.
        made = sent.animation or sent.document
        # Sent as a channel, the sender is a stand-in shared by every channel:
        # an archive under it would be everyone's, so there is none.
        if made is not None and not _as_chat(update):
            gallery.record(context.user_data, made.file_id,
                           authors.resolve(target), text)
    except throttle.Busy:
        await message.reply_text(_t("busy", update, context))
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("quote gif failed")
        await message.reply_text(_t("failed", update, context))


async def _keep_showing(chat, action: str, done: asyncio.Event) -> None:
    """Repeat a chat action until `done`: Telegram drops each after five seconds."""
    while not done.is_set():
        try:
            await chat.send_action(action)
        except TelegramError:
            return
        try:
            await asyncio.wait_for(done.wait(), 4.5)
        except asyncio.TimeoutError:
            pass


async def cmd_fire(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The quote written in fire, on the Gunna clip.

    One clip at a time (throttle.FIRE): a render takes both of the server's
    cores for a few seconds. Past a short queue, people are told to come back.
    """
    prepared = await _prepare(update, context)
    if prepared is None:
        return
    target, text = prepared
    message = update.effective_message
    if not fire.available():
        await message.reply_text(_t("fire_unavailable", update, context))
        return
    quote = fire.clean(text)
    if not quote:
        await message.reply_text(_t("need_text", update, context))
        return
    if len(quote) > fire.MAX_CHARS:
        await message.reply_text(
            _t("fire_too_long", update, context).format(max=fire.MAX_CHARS))
        return
    if throttle.FIRE.full:
        await message.reply_text(_t("fire_busy", update, context))
        return

    author = authors.resolve(target)
    done = asyncio.Event()
    showing = asyncio.create_task(
        _keep_showing(message.chat, ChatAction.UPLOAD_VIDEO, done))
    try:
        data = await throttle.FIRE.run(
            fire.render, quote, author.name, f"@{context.bot.username}")
        data = await _with_words("animation", data, _words_for(context))
        sent = await message.reply_animation(
            io.BytesIO(data), filename="fire.mp4",
            reply_to_message_id=target.message_id)
        admin.note(context, "fire")
        made = sent.animation or sent.document
        if made is not None and not _as_chat(update):
            gallery.record(context.user_data, made.file_id, author, text)
    except throttle.Busy:
        await message.reply_text(_t("fire_busy", update, context))
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("fire render failed")
        await message.reply_text(_t("failed", update, context))
    finally:
        done.set()
        await showing


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
        webp = await throttle.RENDER.run(
            _screenshot_sticker, avatar, author.name, text,
            _clock(target.date), badge, author.seed, seen, badge_is_admin,
        )
        webp = await _with_words("sticker", webp, _words_for(context))
        await message.reply_sticker(io.BytesIO(webp), reply_to_message_id=target.message_id)
        admin.note(context, "screenshot")
    except throttle.Busy:
        await message.reply_text(_t("busy", update, context))
        return
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("screenshot render failed")
        await message.reply_text(_t("failed", update, context))
        return

    await _announce_pack(update, context, webp)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    # The connection, not the code: Telegram answering 502 now and then, a
    # dropped read, a timeout. Polling retries on its own, and a traceback for
    # each one buried the real faults in the log.
    if isinstance(error, NetworkError) and not isinstance(error, BadRequest):
        log.warning("network trouble talking to Telegram: %s", error)
        return
    # A button or a query answered after Telegram stopped waiting - most often
    # on the heels of a slow connection. Nothing is broken and nobody is left
    # without an answer they could still use.
    if isinstance(error, BadRequest) and inline._closed(error):
        log.info("answered after Telegram had stopped waiting: %s", error)
        return
    where = "no update"
    if isinstance(update, Update):
        message = update.effective_message
        chat = update.effective_chat.id if update.effective_chat else "?"
        # What someone wrote is theirs and does not belong in a log file; how
        # long it was and which command it was is enough to reproduce.
        text = (message.text or message.caption or "") if message else ""
        command = text.split(maxsplit=1)[0][:32] if text.startswith("/") else ""
        where = f"chat {chat}, {len(text)} chars" + (f", command {command!r}" if command else "")
    log.error("handler error (%s)", where, exc_info=error)
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
        # The private menu is the shared commands plus the private ones. A
        # command that exists in both is described twice, and the private
        # wording is the right one there: /unpack and /delpack mean the
        # person's own pack in a private chat and the group's in a group.
        # Anything group-only is left out entirely rather than sitting in the
        # menu only to answer "not here".
        private_names = {c.command for c in extra}
        shared = [c for c in core
                  if c.command not in private_names
                  and c.command not in i18n.GROUP_ONLY]
        # A group's "/" menu stays short; help and lang belong in the bot's own chat.
        await app.bot.set_my_commands(
            shared + extra, scope=BotCommandScopeAllPrivateChats(), **kwargs
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
    # And again, tagged. Telegram keeps a per-language menu separately from the
    # default and serves it to that language in preference, so a Persian menu
    # published by an older version of this code went on being served long
    # after the default had moved on - Persian clients were missing half the
    # commands while everyone else saw them. Writing the tag keeps the two from
    # drifting apart again.
    await publish("fa", language_code="fa")
    await publish("en", language_code="en")


# Whose inline fire clip is being made right now: one at a time each, so a
# person tapping the result over and over does not fill the queue alone.
_fire_inline_running: set[int] = set()


async def _fire_inline(context: ContextTypes.DEFAULT_TYPE, chosen, lang: str) -> None:
    """Render the text of a sent inline fire placeholder and swap the clip in.

    The placeholder carries a button for exactly this: without a keyboard,
    Telegram does not say which message the result became, and there would be
    nothing to edit.
    """
    if chosen.inline_message_id is None:
        log.info("an inline fire result arrived without a message to edit")
        return
    user = chosen.from_user
    # Inline is always the sender's own words, under their own name.
    author = authors.Author(user.full_name, user.username or "", user.id, "user", str(user.id))
    await _fire_into(context, chosen.inline_message_id, inline.fire_text(chosen.query) or "",
                     author, user, lang)


async def _fire_into(context: ContextTypes.DEFAULT_TYPE, message_id: str, text: str,
                     author: authors.Author, maker, lang: str, words: str | None = None) -> None:
    """Render `text` in fire, credited to `author`, and swap it into an inline message.

    Inline mode and guest mode both send a placeholder first - an answer cannot
    wait the seconds a render takes - and land here to replace it. `maker` is
    whoever asked: one clip at a time each, and it goes in their archive.
    """
    async def say(key: str) -> None:
        try:
            await context.bot.edit_message_caption(
                inline_message_id=message_id, caption=i18n.t(key, lang), reply_markup=None)
        except TelegramError as exc:
            log.info("could not update an inline fire message: %s", exc)

    if maker.id in _fire_inline_running:
        await say("fire_one_at_a_time")
        return
    quote = fire.clean(text)
    if not quote or len(quote) > fire.MAX_CHARS or not fire.available():
        await say("failed")
        return

    _fire_inline_running.add(maker.id)
    try:
        data = await throttle.FIRE.run(
            fire.render, quote, author.name, f"@{context.bot.username}")
        data = await _with_words("animation", data, words)
        store = STORAGE_CHAT or context.bot_data.get("storage_chat")
        upload = await context.bot.send_animation(
            store or maker.id, io.BytesIO(data), filename="fire.mp4",
            disable_notification=True)
        made = upload.animation or upload.document
        await context.bot.edit_message_media(
            inline_message_id=message_id,
            media=InputMediaAnimation(made.file_id),
            reply_markup=inline.fire_again_markup(lang, context.bot.username))
        # The upload was only ever a way to get a file_id, which outlives it.
        try:
            await upload.delete()
        except TelegramError:
            pass
        if author.avatar_key == maker.id and not words:   # a clip with words is that one's own
            inline.fire_remember(context.bot_data, inline.fire_key(maker.id, quote), made.file_id)
        if not getattr(maker, "is_bot", False):
            gallery.record(context.user_data, made.file_id, author, quote)
        admin.note(context, "fire")
    except throttle.Busy:
        await say("fire_busy")
    except Exception:  # noqa: BLE001 - the message is already out; say so in it
        log.exception("fire into an inline message failed")
        await say("failed")
    finally:
        _fire_inline_running.discard(maker.id)


# ------------------------------------------------------------------ packs of one's own
# /newpack makes a pack; replying to a sticker with «بذارش تو پک» puts that one
# sticker in it - nothing else goes in. A photo or a video replied to is made
# into a sticker first. /packs lists them and picks which one stickers go to.
# The personal pack that fills itself still exists, and can be told to stop.
_PACK_WORDS = r"(?:تو|توی|به|داخل)?\s*پک(?:\s*م|\s*خودم)?"
ADD_RE = re.compile(
    r"^\s*(?:این\s*(?:رو|و)?\s*)?(?:"
    r"(?:بذار|بزار|ببر|بفرست|اضافه\s*کن|اد\s*کن)(?:\s*ش)?\s*" + _PACK_WORDS
    + r"|اضافه\s*(?:ش\s*)?(?:کن\s*)?به\s*پک(?:\s*م|\s*خودم)?"
    r"|add\s+(?:it\s+)?to\s+(?:my\s+)?pack)"
    r"(?:\s*(?:لطفا|لطفاً|please))?[\s.!?؟،]*$", re.IGNORECASE)


def is_add_phrase(text: str) -> bool:
    if not text or len(text) > TRIGGER_MAX_CHARS:
        return False
    if re.fullmatch(r"/(?:addsticker|add)(?:@\w+)?", text.strip(), re.IGNORECASE):
        return True                   # the command, as a guest writes it
    return ADD_RE.search(text) is not None


def _own_packs(user_data) -> list[dict]:
    packs = user_data.get("packs")
    if not isinstance(packs, list):
        packs = []
        user_data["packs"] = packs
    return packs


def _target_pack(user_data) -> dict | None:
    """The pack stickers go to: the one chosen, or the newest."""
    packs = _own_packs(user_data)
    chosen = user_data.get("pack_target")
    for pack in packs:
        if pack["n"] == chosen:
            return pack
    return packs[-1] if packs else None


def _own_pack_names(bot_username: str, user_id: int, user_data) -> set[str]:
    names = {stickerpack.personal_name(user_id, bot_username)}
    names |= {stickerpack.custom_name(user_id, p["n"], bot_username)
              for p in _own_packs(user_data)}
    return names


async def cmd_newpack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A new pack of one's own, named. It exists on Telegram from its first sticker."""
    message = update.effective_message
    lang = i18n.resolve(update, context.user_data)
    title = " ".join(context.args or []).strip()[:stickerpack.MAX_TITLE]
    if not title:
        await message.reply_html(i18n.t("newpack_how", lang))
        return
    packs = _own_packs(context.user_data)
    if len(packs) >= stickerpack.MAX_CUSTOM_PACKS:
        await message.reply_text(i18n.t("newpack_limit", lang).format(
            max=stickerpack.MAX_CUSTOM_PACKS))
        return
    n = max((p["n"] for p in packs), default=0) + 1
    packs.append({"n": n, "title": title})
    context.user_data["pack_target"] = n
    await message.reply_text(i18n.t("newpack_done", lang).format(title=title))


def _packs_keyboard(lang: str, user_data) -> InlineKeyboardMarkup:
    target = _target_pack(user_data)
    rows = [[InlineKeyboardButton(
        ("✅ " if target and p["n"] == target["n"] else "🎯 ") + p["title"][:40],
        callback_data=f"cpk:use:{p['n']}")] for p in _own_packs(user_data)]
    auto = user_data.get("auto_pack", True)
    rows.append([InlineKeyboardButton(
        i18n.t("btn_auto_on" if auto else "btn_auto_off", lang), callback_data="cpk:auto")])
    return InlineKeyboardMarkup(rows)


async def cmd_packs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """This person's packs, with their links, and which one stickers go to."""
    message = update.effective_message
    lang = i18n.resolve(update, context.user_data)
    user_id = update.effective_user.id
    username = context.bot.username
    lines = []
    personal = await stickerpack.personal_link(context.bot, user_id)
    lines.append(i18n.t("packs_personal", lang).format(
        link=personal or i18n.t("packs_empty", lang)))
    target = _target_pack(context.user_data)
    for p in _own_packs(context.user_data):
        link = await stickerpack.link_if_exists(
            context.bot, stickerpack.custom_name(user_id, p["n"], username))
        mark = " 🎯" if target and p["n"] == target["n"] else ""
        lines.append(f"• <b>{html.escape(p['title'])}</b>{mark} — "
                     + (link or i18n.t("packs_empty", lang)))
    if not _own_packs(context.user_data):
        lines.append(i18n.t("packs_none", lang))
    # Titles are theirs, escaped above; the frame around them is the catalogue's.
    await message.reply_html(i18n.t("packs_list", lang).format(rows=chr(10).join(lines)),
                             disable_web_page_preview=True,
                             reply_markup=_packs_keyboard(lang, context.user_data))


async def on_packs_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    lang = i18n.resolve(update, context.user_data)
    parts = query.data.split(":")
    if parts[1] == "auto":
        context.user_data["auto_pack"] = not context.user_data.get("auto_pack", True)
        await query.answer(i18n.t("auto_on" if context.user_data["auto_pack"] else "auto_off", lang),
                           show_alert=True)
    elif parts[1] == "use" and len(parts) > 2 and parts[2].isdigit():
        n = int(parts[2])
        pack = next((p for p in _own_packs(context.user_data) if p["n"] == n), None)
        if pack is None:
            await query.answer()
            return
        context.user_data["pack_target"] = n
        await query.answer(i18n.t("packs_target_set", lang).format(title=pack["title"]))
    else:
        await query.answer()
        return
    try:
        await query.edit_message_reply_markup(_packs_keyboard(lang, context.user_data))
    except TelegramError:
        pass


async def _add_replied(context, source, user, lang: str) -> str:
    """Put the replied-to sticker (or picture, or video) in this person's pack.

    Returns the text to answer with - the same words in a chat, a group or a
    guest answer.
    """
    pack = _target_pack(context.user_data)
    if pack is None:
        return i18n.t("addpack_no_pack", lang)
    if source is not None and source.sticker is not None:
        item, fmt, emoji = (source.sticker.file_id, stickerpack.sticker_format(source.sticker),
                            source.sticker.emoji)
    elif source is not None and convert.media_of(source) is not None:
        try:
            kind, data = await _download_media(context, source, "sticker")
            made, ext = await throttle.MEDIA.run(convert.convert, "sticker", kind, data)
        except convert.Unsupported:
            return i18n.t("addpack_need_reply", lang)
        except convert.TooBig:
            return i18n.t("convert_too_big", lang)
        item, fmt, emoji = _named(made, ext), ("video" if ext == "webm" else "static"), None
    else:
        return i18n.t("addpack_need_reply", lang)
    name = stickerpack.custom_name(user.id, pack["n"], context.bot.username)
    outcome = await stickerpack.add_sticker(context.bot, name, pack["title"], item, fmt,
                                            emoji, OWNER_ID)
    if outcome == "full":
        return i18n.t("addpack_full", lang).format(title=pack["title"])
    if isinstance(outcome, str):
        return i18n.t("failed", lang)
    link, created = outcome
    admin.note(context, "sticker")
    key = "addpack_created" if created else "addpack_done"
    return i18n.t(key, lang).format(title=pack["title"], link=link)


async def on_add_to_pack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not await _require_start(update, context):
        return
    if not await _require_channel(update, context):
        return
    if _too_soon(context):
        return
    lang = i18n.resolve(update, context.user_data)
    try:
        said = await _add_replied(context, message.reply_to_message, update.effective_user, lang)
    except throttle.Busy:
        said = i18n.t("busy", lang)
    await message.reply_text(said, disable_web_page_preview=True)


# ------------------------------------------------------------------ conversions
# «تبدیل به گیف» on a photo or a video, «تبدیل به ویدیو» on a GIF or an animated
# sticker, «تبدیل به عکس» on a sticker - and the same as /togif, /tosticker,
# /tovideo and /tophoto. convert.py does the work; this is the asking.
_CONVERT_NAMES = {"گیف": "gif", "gif": "gif", "استیکر": "sticker", "sticker": "sticker",
                  "ویدیو": "video", "ویدئو": "video", "فیلم": "video", "video": "video",
                  "عکس": "photo", "تصویر": "photo", "photo": "photo"}
_CONVERT_WORD = "(?P<w{n}>" + "|".join(_CONVERT_NAMES) + ")"
CONVERT_RE = re.compile(
    r"^\s*(?:این\s*(?:رو|و)?\s*)?(?:"
    r"تبدیل(?:\s*ش)?(?:\s*کن(?:ید)?)?\s*به\s*" + _CONVERT_WORD.format(n=1)
    + r"(?:\s*کن(?:ید)?)?"
    r"|به\s*" + _CONVERT_WORD.format(n=2) + r"\s*تبدیل(?:\s*ش)?\s*کن(?:ید)?"
    r"|(?:convert\s+)?to\s+" + _CONVERT_WORD.format(n=3) + r")"
    r"(?:\s*(?:لطفا|لطفاً|please))?[\s.!?؟،]*$", re.IGNORECASE)


# One stretch of a video, for its GIF or its sticker: «تبدیل به گیف ۱:۲۰ تا ۱:۳۵»,
# «از ثانیه ۱۰ تا ۲۰», «از ۲:۰۵», /togif 1:20 1:35. Persian digits are digits,
# and a dot does what a colon does, since 1.20 is how a minute and twenty
# seconds often gets typed. A bare number on its own in a phrase is not a time
# - «تبدیل به گیف ۵» says nothing about where - unless it follows «از».
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫", "01234567890123456789.")
_TIME = r"(?<![\d:.])\d{1,3}(?:[:.]\d{1,2}){0,2}(?![\d:.])"
_SECONDS_WORD = r"(?:\s*(?:ثانیه|sec|s)\b)?"
_SPAN_RE = re.compile(
    r"(?:(?:از|from)\s*)?(?:ثانیه\s*)?(?P<a>" + _TIME + ")" + _SECONDS_WORD
    + r"(?:\s*(?:تا|الی|to|-|–|—)\s*|\s+)(?:ثانیه\s*)?(?P<b>" + _TIME + ")" + _SECONDS_WORD
    + r"|(?:از|from)\s*(?:ثانیه\s*)?(?P<c>" + _TIME + ")" + _SECONDS_WORD
    + r"|(?P<d>(?<![\d:.])\d{1,3}[:.]\d{1,2}(?:[:.]\d{1,2})?(?![\d:.]))", re.IGNORECASE)
CONVERT_MAX_CHARS = 60      # «این رو از ثانیه ۱۰ تا ثانیه ۲۰ تبدیل به گیف کن لطفا» is 50


def _seconds(stamp: str) -> int:
    total = 0
    for part in re.split(r"[:.]", stamp):
        total = total * 60 + int(part)
    return total


def take_span(text: str) -> tuple[str, tuple[int, int | None] | None]:
    """The words without a stretch of time in them, and the stretch: (start, end),
    end None for "from start on", or None when no time was given."""
    plain = (text or "").translate(_DIGITS)
    found = _SPAN_RE.search(plain)
    if found is None:
        return text, None
    a, b, c, d = found.group("a", "b", "c", "d")
    span = (_seconds(a), _seconds(b)) if a else (_seconds(c or d), None)
    rest = plain[:found.start()] + " " + re.sub(r"^\s*(?:رو|را)(?!\S)", "", plain[found.end():])
    return " ".join(rest.split()), span


def args_span(words: str) -> tuple[int, int | None] | None:
    """The stretch typed after /togif or /tosticker - "1:20 1:35", "1:20-1:35",
    "از 75", or just "75" - or None if the words are not one."""
    plain = " ".join((words or "").translate(_DIGITS).split())
    if not plain or len(plain) > CONVERT_MAX_CHARS:
        return None
    if re.fullmatch(_TIME, plain):
        return _seconds(plain), None
    rest, span = take_span(plain)
    return None if rest else span


def convert_request(text: str) -> tuple[str, tuple[int, int | None] | None] | None:
    """(what to make, which stretch of the video) that a phrase asks for, or None."""
    if not text or len(text) > CONVERT_MAX_CHARS:
        return None
    command = re.match(r"^\s*/to(gif|sticker|video|photo)(?:@\w+)?(?:\s+|$)", text, re.IGNORECASE)
    if command:                       # the commands, as a guest writes them
        after = text[command.end():].strip()
        span = args_span(after)
        if after and span is None:
            return None
        return command.group(1).lower(), span
    rest, span = take_span(text)
    match = CONVERT_RE.search(rest) if len(rest) <= TRIGGER_MAX_CHARS else None
    if match is None:
        return None
    word = next(v for k, v in match.groupdict().items() if v)
    return _CONVERT_NAMES[word.lower()], span


def convert_target(text: str) -> str | None:
    """What a phrase asks the replied-to media to become, if it is a conversion."""
    request = convert_request(text)
    return request[0] if request else None


def _stamp(seconds: int) -> str:
    """1:05, the way a video player shows a time."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _span_problem(exc: "convert.BadSpan", target: str, lang: str) -> str:
    """What to say about a stretch of video that cannot be cut."""
    return i18n.t(f"convert_span_{exc.reason}", lang).format(
        target=i18n.t(f"convert_name_{target}", lang), seconds=exc.seconds,
        length=_stamp(exc.seconds))


class _ConvertPhrase(filters.MessageFilter):
    """A message asking for a conversion, maybe of one stretch of a video."""

    def filter(self, message: Message) -> bool:
        return convert_request(message.text or "") is not None


async def _download_media(context, target_message, target: str, span=None):
    """(kind, bytes) of the media to convert; raises convert.Unsupported / TooBig,
    and BadSpan for a stretch that cannot be cut whatever the video is."""
    found = convert.media_of(target_message)
    if found is None:
        raise convert.Unsupported("no media")
    kind, file_id, size = found
    convert.check(target, kind, size)
    convert.check_span(target, span)
    file = await context.bot.get_file(file_id)
    convert.check(target, kind, file.file_size or 0)
    return kind, bytes(await file.download_as_bytearray())


def _named(data: bytes, ext: str) -> io.BytesIO:
    """Bytes with a file name, which is how Telegram tells a .webm sticker from a .webp."""
    buf = io.BytesIO(data)
    buf.name = f"quoto.{ext}"
    return buf


async def _convert_and_reply(update: Update, context: ContextTypes.DEFAULT_TYPE,
                             target: str, span=None) -> None:
    message = update.effective_message
    if not await _require_start(update, context):
        return
    if not await _require_channel(update, context):
        return
    if _too_soon(context):
        log.info("ignoring a burst from %s", update.effective_user.id)
        return
    source = message.reply_to_message
    lang = i18n.resolve(update, context.user_data)
    if source is None or convert.media_of(source) is None:
        await message.reply_text(i18n.t("convert_need_reply", lang))
        return
    action = {"gif": ChatAction.UPLOAD_VIDEO, "video": ChatAction.UPLOAD_VIDEO,
              "sticker": ChatAction.CHOOSE_STICKER, "photo": ChatAction.UPLOAD_PHOTO}[target]
    await message.chat.send_action(action)
    try:
        kind, data = await _download_media(context, source, target, span)
        result, ext = await throttle.MEDIA.run(convert.convert, target, kind, data, span)
        if target in convert.SPAN_LIMIT:            # a GIF or a sticker: words go on those
            result = await _with_words(_MADE_KIND.get(ext, ""), result, _words_for(context),
                                       own=False)
        reply = source.message_id
        if target == "gif":
            await message.reply_animation(_named(result, ext), reply_to_message_id=reply)
        elif target == "video":
            await message.reply_video(_named(result, ext), supports_streaming=True,
                                      reply_to_message_id=reply)
        elif target == "sticker":
            await message.reply_sticker(_named(result, ext), reply_to_message_id=reply)
        else:
            await message.reply_photo(_named(result, ext), reply_to_message_id=reply)
        admin.note(context, "convert")
    except convert.Unsupported:
        await message.reply_text(i18n.t("convert_unsupported", lang).format(
            target=i18n.t(f"convert_name_{target}", lang)))
    except convert.TooBig:
        await message.reply_text(i18n.t("convert_too_big", lang))
    except convert.BadSpan as exc:
        await message.reply_text(_span_problem(exc, target, lang))
    except throttle.Busy:
        await message.reply_text(i18n.t("busy", lang))
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("conversion to %s failed", target)
        await message.reply_text(i18n.t("failed", lang))


# What a conversion's result is, by its extension, for writing on it.
_MADE_KIND = {"mp4": "animation", "webp": "sticker", "webm": "video_sticker"}


async def on_convert_phrase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    request = convert_request(update.effective_message.text or "")
    if request is not None:
        await _convert_and_reply(update, context, *request)


def _convert_command(target: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        words, caption = split_caption(" ".join(context.args or []))
        if caption is not None and target in convert.SPAN_LIMIT:
            context.caption_words = caption     # /togif 1:20 1:35 روش بنویس: سلام
        else:
            words = " ".join(context.args or [])
        span = args_span(words)
        if words and span is None and target in convert.SPAN_LIMIT:
            # Words that were meant as a time and are not one: better to say
            # how than to make a GIF of the first thirty seconds instead.
            await update.effective_message.reply_text(_t("convert_span_how", update, context))
            return
        await _convert_and_reply(update, context, target, span)
    return handler


# ------------------------------------------------------------------ words on it
# «روش بنویس سلام» on a GIF or a sticker - or «بنویس روش ...», «متن بذار ...»,
# /text - and the words go along its bottom, the way a meme carries them. A GIF
# stays a GIF and a sticker a sticker. The verb has to end where it ends: «روش
# بنویسی کد» is somebody talking about a way of writing code, not an order.
_CAPTION_VERB = (
    r"(?:(?:رو\s*ش|روی\s*(?:ش|این|اینو))\s*(?:بنویس(?:ید)?|متن\s*(?:بذار|بزار|بنویس)(?:ید)?)"
    r"|بنویس(?:ید)?\s*رو\s*ش|متن\s*(?:رو\s*ش\s*)?(?:بذار|بزار)(?:ید)?"
    # In English, "caption:" or "text:" - the colon is what makes it an ask.
    r"|(?:caption|text)(?=\s*[:：]))(?!\w)")
CAPTION_RE = re.compile(r"^\s*" + _CAPTION_VERB + r"(?:\s*[:：])?(?P<words>.*)$",
                        re.IGNORECASE | re.DOTALL)
# The same, after something else that was asked for: «استیکرش کن، روش بنویس: سلام».
_CAPTION_CLAUSE_RE = re.compile(r"(?:^|(?<=[\s،,\-–—]))" + _CAPTION_VERB
                                + r"(?:\s*[:：])?(?P<words>.*)$", re.IGNORECASE | re.DOTALL)
_JOINT = " \t\n،,-–—"
CAPTION_COMMAND_RE = re.compile(r"^\s*/(?:text|caption)(?:@\w+)?(?:\s+|$)(?P<words>.*)$",
                                re.IGNORECASE | re.DOTALL)
CAPTION_MESSAGE_CHARS = 300


def caption_request(text: str) -> str | None:
    """The words someone wants written on what they replied to, or None if this
    is not that. An empty string is the asking without the words."""
    if not text or len(text) > CAPTION_MESSAGE_CHARS:
        return None
    found = CAPTION_COMMAND_RE.match(text) or CAPTION_RE.match(text)
    return found.group("words").strip() if found else None


def split_caption(text: str, loose: bool = True) -> tuple[str, str | None]:
    """«استیکرش کن، روش بنویس: سلام» -> ("استیکرش کن", "سلام"): what to make,
    and the words to write on it - (text, None) when none were asked for.

    `loose` takes the words wherever they start. Not loose, they need a comma,
    a dash, a new line or a «و» before them, or nothing at all: that is for
    someone's own words being quoted, where «یه روش بنویس که...» is a sentence.
    """
    if not text or len(text) > CAPTION_MESSAGE_CHARS:
        return text, None
    found = _CAPTION_CLAUSE_RE.search(text)
    if found is None:
        return text, None
    before = text[:found.start()]
    rest = before.rstrip(_JOINT)
    if rest == "و" or rest.endswith((" و", "\nو")):
        rest = rest[:-1].rstrip(_JOINT)
    joined = len(before.rstrip()) != len(rest) or not rest
    if not loose and not joined:
        return text, None
    return rest, found.group("words").strip()


def _made_with_caption(text: str):
    """(how, what, words) for something to make with words on it - «استیکرش کن،
    روش بنویس: سلام», «تبدیل به گیف ۱:۲۰ تا ۱:۳۵، روش بنویس: ...» - or None.

    `how` is "make", with the kind of card to make, or "convert", with the
    conversion asked for: only a GIF or a sticker, which is what words go on.
    """
    rest, words = split_caption(text)
    if words is None or not rest or len(rest) > TRIGGER_MAX_CHARS:
        return None
    for kind, pattern in TRIGGERS.items():
        if pattern.search(rest):
            return "make", kind, words
    request = convert_request(rest)
    if request is not None and request[0] in convert.SPAN_LIMIT:
        return "convert", request, words
    return None


def _maker(kind: str):
    """The handler that makes a `kind`, looked up when it is needed."""
    return {"quote": cmd_quote, "sticker": cmd_quote_sticker, "gif": cmd_quote_gif,
            "shot": cmd_screenshot, "fire": cmd_fire}[kind]


async def _with_words(kind: str, data: bytes, words: str | None, own: bool = True) -> bytes:
    """`data` with the words asked for along with it, or as it was.

    `own` is the bot's own card, sticker or clip, which is mostly words already:
    the caption goes in a band above it (convert.caption_above). Otherwise -
    someone's video made into a GIF - it is written over the picture, as on
    any GIF. `kind` is "photo" for a card, or one of convert.CAPTION_KINDS.
    Too many words are cut short rather than refused: the thing itself was
    asked for too, and is worth more than the last of a long caption.
    """
    words = _caption_words(words)
    if not words:
        return data
    if len(words) > convert.CAPTION_MAX_CHARS:
        words = words[:convert.CAPTION_MAX_CHARS - 1].rstrip() + "…"
    if kind == "photo":
        return await throttle.RENDER.run(convert.caption_picture, data, words)
    write = convert.caption_above if own else convert.caption
    result, _ = await throttle.MEDIA.run(write, kind, data, words)
    return result


def _words_for(context) -> str | None:
    """The words asked for along with this update's request, if any."""
    return getattr(context, "caption_words", None)


class _MadeWithCaption(filters.MessageFilter):
    """A reply asking for a card, a GIF or a sticker with words on it."""

    def filter(self, message: Message) -> bool:
        return _made_with_caption(message.text or "") is not None


async def on_made_with_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    found = _made_with_caption(update.effective_message.text or "")
    if found is None:
        return
    how, what, words = found
    context.caption_words = words
    if how == "make":
        await _maker(what)(update, context)
    else:
        await _convert_and_reply(update, context, *what)


class _CaptionPhrase(filters.MessageFilter):
    """A message asking for words on a GIF or a sticker."""

    def filter(self, message: Message) -> bool:
        return caption_request(message.text or "") is not None


def _caption_words(words: str | None) -> str:
    """What can be drawn of them: emoji go, as on a card."""
    return textkit.normalize_display(words or "")


async def _caption_and_reply(update: Update, context: ContextTypes.DEFAULT_TYPE,
                             words: str | None) -> None:
    message = update.effective_message
    if not await _require_start(update, context):
        return
    if not await _require_channel(update, context):
        return
    if _too_soon(context):
        log.info("ignoring a burst from %s", update.effective_user.id)
        return
    lang = i18n.resolve(update, context.user_data)
    source = message.reply_to_message
    words = _caption_words(words)
    if source is None or convert.media_of(source) is None or not words:
        await message.reply_text(i18n.t("caption_how", lang))
        return
    if len(words) > convert.CAPTION_MAX_CHARS:
        await message.reply_text(i18n.t("caption_too_long", lang).format(
            max=convert.CAPTION_MAX_CHARS))
        return
    await message.chat.send_action(ChatAction.CHOOSE_STICKER)
    try:
        kind, data = await _download_media(context, source, "caption")
        result, ext = await throttle.MEDIA.run(convert.caption, kind, data, words)
        if ext == "mp4":
            await message.reply_animation(_named(result, ext),
                                          reply_to_message_id=source.message_id)
        else:
            await message.reply_sticker(_named(result, ext),
                                        reply_to_message_id=source.message_id)
        admin.note(context, "convert")
    except convert.Unsupported:
        await message.reply_text(i18n.t("caption_unsupported", lang))
    except convert.TooBig:
        await message.reply_text(i18n.t("convert_too_big", lang))
    except throttle.Busy:
        await message.reply_text(i18n.t("busy", lang))
    except TelegramError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("writing on a %s failed", convert.media_of(source)[0])
        await message.reply_text(i18n.t("failed", lang))


async def cmd_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/text, on a reply to a GIF or a sticker. The words are taken as typed,
    line breaks and all, rather than from args, which loses them."""
    found = CAPTION_COMMAND_RE.match(update.effective_message.text or "")
    words = found.group("words") if found else " ".join(context.args or [])
    await _caption_and_reply(update, context, words)


async def on_caption_phrase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    words = caption_request(update.effective_message.text or "")
    if words is not None:
        await _caption_and_reply(update, context, words)


# ------------------------------------------------------------------ guest mode
# Mentioned in a chat the bot is not in: "@getquoto_bot" as a reply to a
# message, maybe with a phrase - «گیفش کن», /sticker - or "@getquoto_bot some
# words" with no reply at all. Telegram hands over the summoning message and
# the one it replies to, and takes exactly one answer, sent into that chat as
# the bot's. Everything else about the bot - its gates, its renderers, its
# limits - is the same as anywhere.
_GUEST_COMMANDS = {
    "quote": ("quote", "qoute", "quto", "qute", "quot", "quoet", "q"),
    "sticker": ("sticker", "stiker", "stickr", "sticekr", "stcker"),
    "gif": ("gif", "gfi"),
    "shot": ("screenshot", "screenshoot", "screanshot", "screnshot", "sceenshot"),
    "fire": ("fire", "fier", "fir"),
}


# Near enough to a command counts as the command when the bot has been
# mentioned by name: «بشات», «اسکرینش کن», «گیفشش», /scrennshot. The words
# that only carry the asking - «کن», «لطفا», «اینو» - are set aside, and what
# is left has to be one of these, give or take a letter or two for a longer
# word and none for a short one, so «شاد» is not «شات» and «کیف» is not «گیف».
# Anything longer than a couple of words is a sentence, not a command.
_FILLER = {"لطفا", "لطفاً", "please", "pls", "plz", "کن", "کنید", "بکن", "بکنش", "بزن",
           "بزنش", "بده", "بدش", "بساز", "بسازش", "اینو", "این", "رو", "و", "یه", "یک"}
_KIND_WORDS = {
    "quote": ("کوت", "کوتش", "کوتشو", "نقلقول", "نقلقولش", "quote", "qoute"),
    "sticker": ("استیکر", "استیکرش", "استیکرشو", "استیکرکن", "sticker"),
    "gif": ("گیف", "گیفش", "گیفشو", "gif"),
    "shot": ("شات", "شاتش", "شاتشو", "بشات", "بشاتش", "اسکرین", "اسکرینش", "اسکرینشات",
             "اسکرینشاتش", "screenshot", "screen", "shot", "ss"),
    "fire": ("آتیش", "آتیشش", "آتیششو", "اتیش", "اتیشش", "آتش", "آتشش", "اتش", "fire"),
}


def _distance(a: str, b: str, limit: int) -> int:
    """Edit distance, giving up once it is past `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


def fuzzy_kind(text: str) -> str | None:
    """Which command these few words are near, if they are near one at all."""
    words = [w for w in gallery.fold(re.sub(r"[.!?؟،,]", " ", text or "")).split()
             if w not in _FILLER]
    if not words or len(words) > 2:
        return None
    word = "".join(words)
    best, best_kind = None, None
    for kind, names in _KIND_WORDS.items():
        for name in names:
            name = gallery.fold(name).replace(" ", "")
            allowed = 0 if len(name) <= 3 else 1 if len(name) <= 6 else 2
            d = _distance(word, name, allowed)
            if d <= allowed and (best is None or d < best):
                best, best_kind = d, kind
    return best_kind


# Marks a client may put around a mention in right-to-left text: invisible,
# and enough to stop a phrase being recognised.
_DIRECTION_MARKS = dict.fromkeys(map(ord, "\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
                                         "\u2066\u2067\u2068\u2069\ufeff"), " ")


def guest_request(text: str, bot_username: str, near: bool = True) -> tuple[str, str]:
    """(what to make, any words of their own) from a guest summoning message.

    The mention alone makes a card of what it replies to; anything written
    after it has to be one of the commands or phrases - "unknown" otherwise,
    and the caller decides what that might still be (a pack link, adding to a
    pack, a conversion) before showing how it is used. It used to make a card
    of whatever had been written, which is how a mistyped command became a
    card nobody asked for.
    """
    rest = (text or "").translate(_DIRECTION_MARKS)
    rest = re.sub(rf"@{re.escape(bot_username)}\b", " ", rest, flags=re.IGNORECASE)
    rest = " ".join(rest.split())
    if not rest:
        return "unknown", ""          # the name alone asks for nothing in particular
    command = re.match(r"^/([A-Za-z]+)(?:@\w+)?(?:\s+|$)", rest)
    if command:
        name = command.group(1).lower()
        for kind, names in _GUEST_COMMANDS.items():
            if name in names:
                return kind, rest[command.end():].strip()
        close = fuzzy_kind(name) if near else None
        if close is not None and not name.startswith(("to", "add", "pack")):
            return close, rest[command.end():].strip()
    for kind, pattern in TRIGGERS.items():
        if len(rest) <= TRIGGER_MAX_CHARS and pattern.search(rest):
            return kind, ""
    close = fuzzy_kind(rest) if near else None
    if close is not None:
        return close, ""
    return "unknown", rest


def _guest_text(lang: str, key: str, start_with: str | None = None, **fields):
    """A plain message as the one guest answer: when a picture cannot be made.

    `start_with` is the bot's username, when the answer should carry the button
    that opens it.
    """
    markup = None
    if start_with:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(
            i18n.t("btn_start", lang), url=f"https://t.me/{start_with}?start=guest")]])
    return _guest_said(i18n.t(key, lang).format(**fields), markup)


def _guest_said(text: str, markup=None):
    """Plain words as the one guest answer."""
    from telegram import InlineQueryResultArticle, InputTextMessageContent
    return InlineQueryResultArticle(
        id=f"t{uuid.uuid4().hex[:16]}", title="Quoto",
        input_message_content=InputTextMessageContent(text, disable_web_page_preview=True),
        reply_markup=markup)


async def _guest_upload(context, kind: str, data, user_id: int) -> str:
    """Put a picture up to get a file_id, and take the message down again."""
    store = STORAGE_CHAT or context.bot_data.get("storage_chat") or user_id
    send = getattr(context.bot, {"card": "send_photo", "shot": "send_photo",
                                 "sticker": "send_sticker", "gif": "send_animation",
                                 "video": "send_video"}[kind])
    extra = {"filename": "quote.mp4"} if kind in ("gif", "video") else {}
    message = await send(store, data, disable_notification=True, **extra)
    if kind in ("card", "shot"):
        file_id = message.photo[-1].file_id
    elif kind == "sticker":
        file_id = message.sticker.file_id
    elif kind == "video":
        file_id = (message.video or message.document).file_id
    else:
        file_id = (message.animation or message.document).file_id
    try:
        await message.delete()
    except TelegramError:
        pass
    return file_id


async def _guest_convert(context, source, target: str, user_id: int, lang: str, span=None,
                         words: str | None = None):
    """The one guest answer for a conversion: the converted file, or why not."""
    from telegram import (InlineQueryResultCachedMpeg4Gif, InlineQueryResultCachedPhoto,
                          InlineQueryResultCachedSticker, InlineQueryResultCachedVideo)
    try:
        kind, data = await _download_media(context, source, target, span)
        result, ext = await throttle.MEDIA.run(convert.convert, target, kind, data, span)
        if target in convert.SPAN_LIMIT:
            result = await _with_words(_MADE_KIND.get(ext, ""), result, words, own=False)
    except convert.BadSpan as exc:
        return _guest_said(_span_problem(exc, target, lang))
    except convert.Unsupported:
        return _guest_text(lang, "convert_unsupported",
                           target=i18n.t(f"convert_name_{target}", lang))
    except convert.TooBig:
        return _guest_text(lang, "convert_too_big")
    admin.note(context, "convert")
    uid = uuid.uuid4().hex[:16]
    if target == "gif":
        file_id = await _guest_upload(context, "gif", _named(result, ext), user_id)
        return InlineQueryResultCachedMpeg4Gif(id=f"g{uid}", mpeg4_file_id=file_id)
    if target == "video":
        file_id = await _guest_upload(context, "video", _named(result, ext), user_id)
        return InlineQueryResultCachedVideo(id=f"v{uid}", video_file_id=file_id, title="Quoto")
    if target == "sticker":
        file_id = await _guest_upload(context, "sticker", _named(result, ext), user_id)
        return InlineQueryResultCachedSticker(id=f"s{uid}", sticker_file_id=file_id)
    file_id = await _guest_upload(context, "card", _named(result, ext), user_id)
    return InlineQueryResultCachedPhoto(id=f"p{uid}", photo_file_id=file_id)


async def _guest_caption(context, source, words: str, user_id: int, lang: str):
    """The one guest answer for words on a GIF or a sticker: the result, or why not."""
    from telegram import InlineQueryResultCachedMpeg4Gif, InlineQueryResultCachedSticker
    words = _caption_words(words)
    if source is None or convert.media_of(source) is None or not words:
        return _guest_text(lang, "caption_how")
    if len(words) > convert.CAPTION_MAX_CHARS:
        return _guest_text(lang, "caption_too_long", max=convert.CAPTION_MAX_CHARS)
    try:
        kind, data = await _download_media(context, source, "caption")
        result, ext = await throttle.MEDIA.run(convert.caption, kind, data, words)
    except convert.Unsupported:
        return _guest_text(lang, "caption_unsupported")
    except convert.TooBig:
        return _guest_text(lang, "convert_too_big")
    admin.note(context, "convert")
    uid = uuid.uuid4().hex[:16]
    if ext == "mp4":
        file_id = await _guest_upload(context, "gif", _named(result, ext), user_id)
        return InlineQueryResultCachedMpeg4Gif(id=f"g{uid}", mpeg4_file_id=file_id)
    file_id = await _guest_upload(context, "sticker", _named(result, ext), user_id)
    return InlineQueryResultCachedSticker(id=f"s{uid}", sticker_file_id=file_id)


# "@getquoto_bot /pack" - or «پک», «لینک پک» - for the group's pack link.
_PACK_LINK_RE = re.compile(r"/pack(?:@\w+)?|پک(?:\s*گروه)?|لینک\s*پک(?:\s*گروه)?", re.IGNORECASE)


async def _group_pack_text(context, chat, lang: str) -> str:
    """What /pack says, for a guest asking from a chat the bot is not in."""
    if chat is None or chat.type not in stickerpack.GROUP_TYPES:
        return i18n.t("pack_groups_only", lang)
    link = await stickerpack.link_for_adopting(context.bot, chat, OWNER_ID)
    if link is None:
        return i18n.t("pack_none", lang)
    return i18n.t("pack_link", lang).format(link=link)


async def _guest_into_group_pack(context, chat, webp: bytes) -> None:
    """A sticker made as a guest in a group joins that group's pack, as it would
    if the bot were a member. After the answer, so the answer does not wait."""
    if chat is None or chat.type not in stickerpack.GROUP_TYPES:
        return
    try:
        await stickerpack.add_quote(context.bot, chat, webp, OWNER_ID)
    except TelegramError as exc:
        log.info("could not file a guest sticker in its group's pack: %s", exc)


async def on_guest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A guest summoning: make what was asked for and answer with it, once."""
    from telegram import (InlineQueryResultCachedMpeg4Gif, InlineQueryResultCachedPhoto,
                          InlineQueryResultCachedSticker)
    message = update.guest_message
    user = update.effective_user
    query_id = getattr(message, "guest_query_id", None)
    as_chat = _as_chat(update)
    if query_id is None or user is None or (user.is_bot and not as_chat):
        raise ApplicationHandlerStop
    lang = i18n.resolve(update, context.user_data)
    username = context.bot.username

    async def answer(result):
        try:
            return await context.bot.answer_guest_query(query_id, result)
        except BadRequest as exc:
            log.info("a guest query could not be answered: %s", exc)
            return None

    try:
        if _too_soon(context):
            log.info("ignoring a guest burst from %s", user.id)
            return
        # A guest asks nothing of anyone - no Start, no channel: being mentioned
        # in a chat is the whole of the invitation. That holds while there is
        # a storage channel for what is made; without one, files go through
        # the person's own chat with the bot, which needs them to have started it.
        refused = None
        if not (STORAGE_CHAT or context.bot_data.get("storage_chat")):
            refused = await _inline_gate(context, user)
        if refused:
            key = "need_start" if refused == "inline_need_start" else refused
            await answer(_guest_text(lang, key, username if key == "need_start" else None))
            return

        said_text = message.text or message.caption or ""
        # Telegram also sends a guest message when someone replies to one of
        # the bot's own messages without naming it - usually just talking.
        # Then only an exact command is taken, and nothing else is answered.
        named = re.search(rf"@{re.escape(username)}\b", said_text, re.IGNORECASE) is not None
        kind, own = guest_request(said_text, username, near=named)
        target = message.reply_to_message
        # «@getquoto_bot استیکرش کن، روش بنویس: سلام»: what to make, and words
        # for it. Without a reply, «/quote ...» is their own words, so the
        # words for the result need a comma or a new line before them there.
        made_words = None
        rest, asked = split_caption(said_text, loose=target is not None)
        if asked is not None:
            asked_kind, asked_own = guest_request(rest, username, near=named)
            asked_convert = convert_request(asked_own) if asked_kind == "unknown" else None
            if asked_kind != "unknown" or (asked_convert is not None
                                           and asked_convert[0] in convert.SPAN_LIMIT):
                kind, own, made_words = asked_kind, asked_own, asked
        if kind == "unknown":
            # Not a command for a card: maybe one of the other things a guest
            # can ask for, and if not, how it is used - never a card of it.
            wanted = convert_request(own)
            words = caption_request(own)
            if _PACK_LINK_RE.fullmatch(own):
                said = _guest_said(await _group_pack_text(context, message.chat, lang))
            elif is_add_phrase(own):
                said = _guest_said(await _add_replied(context, target, user, lang))
            elif words is not None:
                said = await _guest_caption(context, target, words, user.id, lang)
            elif wanted is not None:
                said = (await _guest_convert(context, target, wanted[0], user.id, lang, wanted[1],
                                             made_words)
                        if target is not None and convert.media_of(target) is not None
                        else _guest_text(lang, "convert_need_reply"))
            elif named:
                said = _guest_text(lang, "guest_how")
            else:
                return              # a reply to the bot that asked for nothing
            await answer(said)
            return
        if target is not None:
            text = extract.quote_text(target)
            author = authors.resolve(target)
        else:
            text = textkit.normalize_display(own)[:extract.MAX_QUOTE_CHARS] if own else None
            # Whoever sent the mention - a person, or the channel they posted as.
            author = authors.resolve(message)
        if not text:
            await answer(_guest_text(lang, "guest_how"))
            return
        log.info("guest request: %s in %s", kind, message.chat.type if message.chat else "?")

        if kind == "fire":
            quote = fire.clean(text)
            if not fire.available():
                await answer(_guest_text(lang, "fire_unavailable"))
                return
            if not quote or len(quote) > fire.MAX_CHARS:
                await answer(_guest_text(lang, "fire_too_long", max=fire.MAX_CHARS))
                return
            if throttle.FIRE.full:
                await answer(_guest_text(lang, "fire_busy"))
                return
            waiting = await inline._fire_placeholder(
                context, STORAGE_CHAT or context.bot_data.get("storage_chat"), user.id)
            sent = await answer(InlineQueryResultCachedMpeg4Gif(
                id=f"f{uuid.uuid4().hex[:16]}", mpeg4_file_id=waiting,
                caption=i18n.t("inline_fire_caption", lang),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    i18n.t("btn_fire_wait", lang), callback_data="fire:wait")]])))
            if sent is not None:
                context.application.create_task(
                    _fire_into(context, sent.inline_message_id, quote, author, user, lang,
                               made_words))
            return

        avatar = await authors.fetch_avatar(context.bot, author, *_avatar_choice(context, author))
        if kind == "shot":
            webp = await throttle.RENDER.run(
                _screenshot_sticker, avatar, author.name, text,
                _clock(target.date if target else message.date), None, author.seed, [], False)
            webp = await _with_words("sticker", webp, made_words)
            result = InlineQueryResultCachedSticker(
                id=f"s{uuid.uuid4().hex[:16]}",
                sticker_file_id=await _guest_upload(context, "sticker", webp, user.id))
            admin.note(context, "screenshot")
            context.application.create_task(_guest_into_group_pack(context, message.chat, webp))
        else:
            scene = await throttle.RENDER.run(
                render.build_scene, avatar, text, author.name, WATERMARK, _template(context))
            if kind == "sticker":
                webp = await throttle.RENDER.run(_card_webp, scene)
                webp = await _with_words("sticker", webp, made_words)
                result = InlineQueryResultCachedSticker(
                    id=f"s{uuid.uuid4().hex[:16]}",
                    sticker_file_id=await _guest_upload(context, "sticker", webp, user.id))
                context.application.create_task(
                    _guest_into_group_pack(context, message.chat, webp))
            elif kind == "gif":
                buf, ext = await throttle.RENDER.run(animate.to_animation, scene)
                if ext == "mp4" and made_words:
                    buf = io.BytesIO(await _with_words("animation", buf.getvalue(), made_words))
                file_id = await _guest_upload(context, "gif", buf, user.id)
                result = InlineQueryResultCachedMpeg4Gif(
                    id=f"g{uuid.uuid4().hex[:16]}", mpeg4_file_id=file_id)
                if not as_chat:     # a stand-in account is shared; it keeps no archive
                    gallery.record(context.user_data, file_id, author, text)
            else:
                png = await throttle.RENDER.run(_card_png, scene)
                if made_words:
                    png = io.BytesIO(await _with_words("photo", png.getvalue(), made_words))
                result = InlineQueryResultCachedPhoto(
                    id=f"p{uuid.uuid4().hex[:16]}",
                    photo_file_id=await _guest_upload(context, "card", png, user.id))
            admin.note(context, kind if kind in ("sticker", "gif") else "quote")
        await answer(result)
    except throttle.Busy:
        await answer(_guest_text(lang, "busy"))
    except TelegramError as exc:
        log.info("guest request failed: %s", exc)
    except Exception:  # noqa: BLE001 - one bad request must not reach the other handlers
        log.exception("guest request failed")
    finally:
        # Nothing else is meant for a guest message: the reply triggers and the
        # private-text handlers would otherwise answer it as if the bot were
        # a member of a chat it is not in.
        raise ApplicationHandlerStop


# Named in a group the bot is a member of. There is no guest message then:
# «@getquoto_bot /pack» arrives as an ordinary message, and nothing read it -
# CommandHandler only sees a command at the very start of a message, and the
# phrases are anchored to the start too. So the words the help teaches did
# nothing in exactly the groups that had added the bot. They are read here the
# way on_guest reads them, after every handler that already understood one.
async def on_group_mention(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«@getquoto_bot پک», «@getquoto_bot /sticker» and the rest, from a member."""
    message = update.effective_message
    username = context.bot.username
    text = (message.text or "").translate(_DIRECTION_MARKS)
    mention = re.compile(rf"@{re.escape(username)}\b", re.IGNORECASE)
    if not mention.search(text):
        return                  # someone else's name
    # «@getquoto_bot استیکرش کن، روش بنویس: سلام»: the words go with what is made.
    before, asked = split_caption(text, loose=message.reply_to_message is not None)
    if asked is not None and mention.sub(" ", before).strip():
        context.caption_words = asked
        text = before
    rest = " ".join(mention.sub(" ", text).split())
    command = re.match(r"^/([A-Za-z_]+)(?:@\w+)?(?:\s+|$)", rest)
    if command:
        # Any of the bot's commands, as if it had been typed on its own.
        name = command.group(1).lower()
        for handler in context.application.handlers.get(0, []):
            if isinstance(handler, CommandHandler) and name in handler.commands:
                context.args = rest[command.end():].split()
                await handler.callback(update, context)
                return
    kind, own = guest_request(text, username)
    if kind in ("quote", "sticker", "gif", "shot", "fire"):
        context.args = own.split()
        await _maker(kind)(update, context)
    elif _PACK_LINK_RE.fullmatch(own):
        await cmd_pack(update, context)
    elif is_add_phrase(own):
        await on_add_to_pack(update, context)
    elif caption_request(own) is not None:
        await _caption_and_reply(update, context, caption_request(own))
    elif convert_request(own) is not None:
        await _convert_and_reply(update, context, *convert_request(own))
    elif text.lstrip().lower().startswith("@" + username.lower()) and not _too_soon(context):
        # Spoken to, but asked for nothing it knows: how it is used. Named in
        # passing, in the middle of someone's sentence, it stays out of it.
        await message.reply_text(_t("guest_how", update, context))


async def on_fire_wait(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The button on a placeholder: nothing to do but say it is coming."""
    await update.callback_query.answer(_t("fire_wait_alert", update, context))


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
    if chosen.result_id.startswith(inline.FIRE_RESULT):
        # The placeholder went out; the clip is made now, off this handler,
        # and put in its place when it is ready.
        context.application.create_task(
            _fire_inline(context, chosen, i18n.resolve(update, context.user_data)))
        return
    gif_id = inline.gif_for(context, chosen.result_id)
    if gif_id is not None:
        # An inline quote is always in the sender's own words, so it is filed
        # under them.
        user = chosen.from_user
        gallery.record(context.user_data, gif_id, authors.Author(
            user.full_name, user.username or "", user.id, "user", str(user.id)),
            chosen.query)
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


# "اینو استیکرش کن لطفا!" should work as readily as "استیکرش کن".
#
# Whitespace is matched in one run at the end, never in quantifiers side by
# side. The first version had three \s* in a row in its tail, and a reply of
# "quote", a few thousand spaces and an "x" made re backtrack through every
# way of sharing the spaces out between them: a minute per pattern, five
# patterns, all of it on the event loop - one message stopped the bot for
# everybody. _ShortText caps what reaches these at all, as a second wall.
_LEAD = r"^\s*(?:این\s*(?:رو|و)?\s*)?"
_TAIL = r"(?:\s*(?:لطفا|لطفاً|please))?[\s.!?؟،]*$"
_DO = r"\s*(?:کن|کنید)"
TRIGGERS = {
    name: re.compile(_LEAD + body + _TAIL, re.IGNORECASE)
    for name, body in (
        ("quote", r"(?:کوت|نقل\s*قول|quote)(?:\s*ش)?(?:" + _DO + r")?"),
        ("sticker", r"(?:استیکر|sticker)(?:\s*ش)?" + _DO),
        ("gif", r"(?:گیف|gif)(?:\s*ش)?" + _DO),
        ("shot", r"(?:(?:شات|اسکرین\s*شات|screenshot)(?:\s*ش)?" + _DO
                 + r"|ب\s*شات(?:\s*ش)?(?:" + _DO + r")?)"),
        # «آتیشش کن», and the ways it gets typed: اتیشش, آتشش, آتیش بزن.
        ("fire", r"(?:آتیش|اتیش|آتش|اتش|fire)(?:\s*ش)?\s*(?:کن|کنید|بزن|بزنید)"),
    )
}
TRIGGER_MAX_CHARS = 40     # «اینو اسکرین شاتش کنید لطفاً!» is 29


class _ShortText(filters.MessageFilter):
    """Only messages short enough to be one of the phrases above."""

    def filter(self, message: Message) -> bool:
        return bool(message.text) and len(message.text) <= TRIGGER_MAX_CHARS


INLINE_MODE = False


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
    # Guest messages first: they would otherwise match the reply triggers and
    # the private-text handlers. on_guest stops every later group too.
    app.add_handler(MessageHandler(filters.UpdateType.GUEST_MESSAGE, on_guest))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("lang", cmd_lang))
    app.add_handler(CallbackQueryHandler(on_lang_choice, pattern=r"^lang:"))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler("pack", cmd_pack))
    app.add_handler(CommandHandler(["mypack", "my_pack", "mypak"], cmd_mypack))
    app.add_handler(CommandHandler(["unpack", "unpak", "delsticker"], cmd_unpack))
    app.add_handler(CommandHandler(["delpack", "deletepack", "dellpack"], cmd_delpack))
    app.add_handler(CommandHandler(["mygifs", "mygif", "gifs"], cmd_mygifs))
    app.add_handler(CommandHandler(["deletemydata", "forgetme"], cmd_deletemydata))
    app.add_handler(CallbackQueryHandler(on_forget, pattern=r"^forget:"))
    app.add_handler(CallbackQueryHandler(on_fire_wait, pattern=r"^fire:wait$"))
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
    app.add_handler(CommandHandler(["fire", "fier", "fir"], cmd_fire))
    app.add_handler(CommandHandler(["newpack", "makepack"], cmd_newpack))
    app.add_handler(CommandHandler(["packs", "mypacks"], cmd_packs))
    app.add_handler(CommandHandler(["addsticker", "add"], on_add_to_pack))
    app.add_handler(CallbackQueryHandler(on_packs_button, pattern=r"^cpk:"))
    app.add_handler(CommandHandler(["togif"], _convert_command("gif")))
    app.add_handler(CommandHandler(["tosticker"], _convert_command("sticker")))
    app.add_handler(CommandHandler(["tovideo"], _convert_command("video")))
    app.add_handler(CommandHandler(["tophoto"], _convert_command("photo")))
    app.add_handler(CommandHandler(["text", "caption"], cmd_text))
    app.add_handler(CommandHandler(
        ["screenshot", "screenshoot", "screanshot", "screnshot", "sceenshot"],
        cmd_screenshot))
    # Saying it in plain Persian instead of typing a command. These are ordinary
    # messages, so in a group they only reach the bot once it is an admin.
    handlers = {"quote": cmd_quote, "sticker": cmd_quote_sticker, "gif": cmd_quote_gif,
                "shot": cmd_screenshot, "fire": cmd_fire}
    app.add_handler(MessageHandler(
        filters.REPLY & _ConvertPhrase(), on_convert_phrase))
    app.add_handler(MessageHandler(filters.REPLY & _CaptionPhrase(), on_caption_phrase))
    app.add_handler(MessageHandler(filters.REPLY & _MadeWithCaption(), on_made_with_caption))
    app.add_handler(MessageHandler(
        filters.REPLY & _ShortText() & filters.Regex(ADD_RE), on_add_to_pack))
    for name, pattern in TRIGGERS.items():
        app.add_handler(MessageHandler(
            filters.REPLY & _ShortText() & filters.Regex(pattern), handlers[name]
        ))
    # The bot named in a group it is in, with what a guest would write after
    # it. Last in the group, so it only sees what nothing above understood.
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.TEXT & filters.Entity(MessageEntityType.MENTION),
        on_group_mention))
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
    # Inline mode is switched off in BotFather: with it on, typing the bot's
    # name opened the inline menu, and that stood in the way of mentioning it
    # as a guest - which does the same job and also knows what was replied to.
    # The handlers are kept, so turning it back on is this flag and BotFather.
    if INLINE_MODE:
        app.add_handler(InlineQueryHandler(
            inline.make_handler(WATERMARK, STORAGE_CHAT, _inline_gate)))
        app.add_handler(ChosenInlineResultHandler(on_chosen_inline))
    app.add_error_handler(on_error)


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
