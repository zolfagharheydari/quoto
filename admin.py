"""The owner's control panel, reachable with /admin inside Telegram itself.

Everything here is gated on OWNER_ID. A user who is not the owner gets no reply
at all — not an error, not a refusal — so the panel leaves no trace of itself in
an ordinary chat. It is deliberately Persian-only and absent from every command
menu, for the same reason /debug is: it is not a feature of the bot, it is the
operator looking at their own machine.

The numbers it reports are kept in bot_data, which is the same pickle the rest of
the bot persists to, so they survive a restart without a database.
"""
from __future__ import annotations

import asyncio
import html
import logging
import time
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

import reactions

log = logging.getLogger("quotebot.admin")

STARTED_AT = time.time()          # this process, not the bot's whole history
PAGE = 8                          # groups listed per page
LOG_LINES = 25
LOG_CHARS = 3200                  # a Telegram message stops at 4096
BROADCAST_PAUSE = 0.05            # ~20 messages a second, well inside the limits
GROUP_TYPES = ("group", "supergroup")

KINDS = (("quote", "کارت"), ("sticker", "استیکر"),
         ("gif", "گیف"), ("screenshot", "اسکرین‌شات"))


# ---------------------------------------------------------------- bookkeeping

def _users(context) -> dict:
    return context.bot_data.setdefault("users", {})


def _groups(context) -> dict:
    return context.bot_data.setdefault("groups", {})


def _blocked(context) -> set:
    blocked = context.bot_data.get("blocked")
    if not isinstance(blocked, set):
        blocked = set(blocked or ())
        context.bot_data["blocked"] = blocked
    return blocked


def _everyone(context) -> dict:
    """Every person the bot keeps anything about, by id.

    Not bot_data["users"], which is only who has been seen since the tracker
    started running. This is python-telegram-bot's own per-user store, which
    has an entry for anyone who has ever reached a handler.
    """
    app = getattr(context, "application", None)
    return getattr(app, "user_data", None) or {}


def members(context) -> list:
    """The users who have the bot: started it, and have not been turned away.

    Someone who blocked or deleted the bot is not a user of it any more, and
    neither is someone the owner blocked. The first is discovered by sending -
    Telegram says Forbidden - and recorded then, so this stays a plain count of
    what is already known rather than a few hundred requests.
    """
    blocked = _blocked(context)
    return [uid for uid, data in _everyone(context).items()
            if data.get("started") and uid not in blocked]


def lost(context, user_id: int) -> None:
    """Mark that this person is gone: they blocked the bot, or deleted it."""
    data = _everyone(context).get(user_id)
    if data is not None:
        data["started"] = False


def exempt(context) -> set:
    """Who does not have to be in the channel: people and whole groups.

    Starting the bot is still required of them - this excuses one rule, not
    both. A group in here excuses everyone using the bot inside it, which is the
    point: the owner of a group should not have to send their members somewhere
    else to use a bot they already invited.
    """
    allowed = context.bot_data.get("exempt")
    if not isinstance(allowed, set):
        allowed = set(allowed or ())
        context.bot_data["exempt"] = allowed
    return allowed


def note(context: ContextTypes.DEFAULT_TYPE, kind: str) -> None:
    """Record that one card of this kind was made. Called by the render handlers."""
    counts = context.bot_data.setdefault("counts", {})
    counts[kind] = counts.get(kind, 0) + 1


def flush_queue(context: ContextTypes.DEFAULT_TYPE) -> int:
    """Throw away every request that is still waiting to be answered.

    Two things are waiting at any moment, and both have to go. The ones already
    pulled from Telegram sit in the application's own queue and can simply be
    taken out of it. The ones Telegram is still holding have not arrived yet, so
    instead a line is drawn in time: anything sent before this moment is dropped
    as it comes in, the same way a message from before the bot woke up is.

    Returns how many were already in hand; the rest are turned away on arrival.
    """
    context.bot_data["queue_cutoff"] = time.time()
    queue = getattr(getattr(context, "application", None), "update_queue", None)
    dropped = 0
    while queue is not None:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        queue.task_done()
        dropped += 1
    log.info("owner flushed the queue: %s waiting, the rest cut off by time", dropped)
    return dropped


def make_tracker(owner_id: int | None):
    """A handler that remembers who is using the bot, and stops those who may not.

    It runs before the command handlers, so a blocked user costs nothing beyond
    the dictionary lookup, and a paused bot answers only its owner.
    """

    async def track(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        chat = update.effective_chat
        if user is None or user.is_bot:
            return
        is_owner = owner_id is not None and user.id == owner_id

        if not is_owner and user.id in _blocked(context):
            log.info("blocked user %s ignored", user.id)
            raise ApplicationHandlerStop

        now = time.time()
        record = _users(context).setdefault(user.id, {})
        record["name"] = user.full_name
        record["username"] = user.username or ""
        record.setdefault("first", now)
        record["seen"] = now

        if chat is not None and chat.type in GROUP_TYPES:
            group = _groups(context).setdefault(chat.id, {})
            group["title"] = chat.title or ""
            group.setdefault("first", now)
            group["seen"] = now

        if context.bot_data.get("paused") and not is_owner:
            message = update.effective_message
            if message is not None and (message.text or "").startswith("/"):
                try:
                    await message.reply_text(
                        "ربات موقتاً برای تعمیر خاموش است. کمی بعد دوباره امتحان کن."
                    )
                except TelegramError:
                    pass
            raise ApplicationHandlerStop

    return track


# -------------------------------------------------------------------- the panel

# The avatar quota: how many pictures one person may ever upload. The base
# number lives with the command that spends it; what the owner grants from here
# is kept beside it, per person and for everyone, so the count of what somebody
# has already used stays honest instead of being wound backwards.
def extra_quota(context, user_id: int) -> int:
    """Uploads granted on top of the base allowance, for this person."""
    each = context.bot_data.get("avatar_extra_all", 0)
    mine = (context.bot_data.get("avatar_extra") or {}).get(user_id, 0)
    return each + mine


def grant_quota(context, user_id, count: int) -> None:
    """Give one person, or everyone when user_id is None, `count` more uploads."""
    if user_id is None:
        context.bot_data["avatar_extra_all"] = (
            context.bot_data.get("avatar_extra_all", 0) + count)
        return
    extra = context.bot_data.setdefault("avatar_extra", {})
    extra[user_id] = extra.get(user_id, 0) + count


def reset_quota(context, user_id) -> int:
    """Forget what has been used. Returns how many people that touched."""
    used = context.bot_data.setdefault("avatar_uses", {})
    if user_id is None:
        touched = len(used)
        used.clear()
        return touched
    return 1 if used.pop(user_id, None) is not None else 0


def _quota_text(context):
    used = context.bot_data.get("avatar_uses") or {}
    each = context.bot_data.get("avatar_extra_all", 0)
    extra = context.bot_data.get("avatar_extra") or {}
    spent = sum(1 for n in used.values() if n)
    lines = [
        "<b>🖼 سهمیهٔ آواتار</b>",
        "",
        "کسانی که عکس فرستاده‌اند: <b>{}</b>".format(spent),
        "سهمیهٔ اضافهٔ همگانی: <b>{}</b>".format(each),
        "کسانی که سهمیهٔ اضافهٔ شخصی دارند: <b>{}</b>".format(len(extra)),
        "",
        "«ریست» یعنی مصرفشان صفر می‌شود و دوباره از اول سهمیه دارند.",
        "«افزودن» یعنی سقفشان بالاتر می‌رود و مصرف قبلی سر جایش می‌ماند.",
    ]
    return (chr(10).join(lines), InlineKeyboardMarkup([
        [InlineKeyboardButton("♻️ ریست یک نفر", callback_data="adm:qreset"),
         InlineKeyboardButton("➕ افزودن به یک نفر", callback_data="adm:qgive")],
        [InlineKeyboardButton("♻️ ریست همه", callback_data="adm:qresetall"),
         InlineKeyboardButton("➕ افزودن به همه", callback_data="adm:qgiveall")],
        [InlineKeyboardButton("⬅️ برگشت", callback_data="adm:home")],
    ]))


def _menu(context) -> InlineKeyboardMarkup:
    paused = context.bot_data.get("paused")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 آمار", callback_data="adm:stats"),
         InlineKeyboardButton("👥 گروه‌ها", callback_data="adm:groups:0")],
        [InlineKeyboardButton("📣 پیام همگانی", callback_data="adm:cast"),
         InlineKeyboardButton("🚫 مسدودها", callback_data="adm:blocked")],
        [InlineKeyboardButton("✅ معاف از کانال", callback_data="adm:exempt")],
        [InlineKeyboardButton("🖼 سهمیه آواتار", callback_data="adm:quota"),
         InlineKeyboardButton("📄 لاگ", callback_data="adm:logs")],
        [InlineKeyboardButton("🧹 پاک کردن صف", callback_data="adm:flush")],
        [InlineKeyboardButton("▶️ روشن کردن" if paused else "⏸ خاموش کردن موقت",
                              callback_data="adm:pause")],
        [InlineKeyboardButton("✖️ بستن", callback_data="adm:close")],
    ])


def _uptime() -> str:
    seconds = int(time.time() - STARTED_AT)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} روز و {hours} ساعت"
    if hours:
        return f"{hours} ساعت و {minutes} دقیقه"
    return f"{minutes} دقیقه"


def _since(stamp: float) -> str:
    seconds = int(time.time() - stamp)
    if seconds < 3600:
        return f"{max(1, seconds // 60)} دقیقه پیش"
    if seconds < 86400:
        return f"{seconds // 3600} ساعت پیش"
    return f"{seconds // 86400} روز پیش"


def _home_text(context) -> str:
    users, groups = members(context), _groups(context)
    counts = context.bot_data.get("counts", {})
    total = sum(counts.values())
    state = "⏸ خاموش" if context.bot_data.get("paused") else "✅ فعال"
    return (
        "<b>پنل مدیریت</b>\n\n"
        f"وضعیت: {state}\n"
        f"روشن از: {_uptime()} پیش\n\n"
        f"👤 کاربران: <b>{len(users)}</b>\n"
        f"👥 گروه‌ها: <b>{len(groups)}</b>\n"
        f"🖼 ساخته‌شده: <b>{total}</b>"
    )


def _stats_text(context) -> str:
    users, groups = members(context), _groups(context)
    counts = context.bot_data.get("counts", {})
    now = time.time()
    # When they were last around is what the tracker knows, and it only knows
    # about people it has seen since it started running.
    seen = _users(context)
    day = sum(1 for uid in users if now - seen.get(uid, {}).get("seen", 0) < 86400)
    week = sum(1 for uid in users
               if now - seen.get(uid, {}).get("seen", 0) < 7 * 86400)
    fresh = sum(1 for uid in users
                if now - seen.get(uid, {}).get("first", 0) < 86400)

    lines = [
        "<b>📊 آمار</b>", "",
        f"👤 کاربران: <b>{len(users)}</b>",
        f"   • امروز فعال: {day}",
        f"   • این هفته فعال: {week}",
        f"   • تازه‌وارد امروز: {fresh}", "",
        f"👥 گروه‌ها: <b>{len(groups)}</b>", "",
        "<b>ساخته‌شده</b>",
    ]
    for key, label in KINDS:
        lines.append(f"   • {label}: {counts.get(key, 0)}")
    lines += [
        f"   <b>مجموع: {sum(counts.values())}</b>", "",
        f"🖼 آواتار دلخواه: {len(context.bot_data.get('avatars', {}))}",
        f"📦 کانال انبار: {context.bot_data.get('storage_chat') or 'تنظیم نشده'}",
        f"🚫 مسدود: {len(_blocked(context))}",
        f"✅ معاف از کانال: {len(exempt(context))}",
        f"👍 ریکشن دنبال‌شده: {reactions.total_tracked(context.bot_data)} پیام",
        f"⏱ روشن از: {_uptime()} پیش",
    ]
    return "\n".join(lines)


def _groups_page(context, page: int) -> tuple[str, InlineKeyboardMarkup]:
    groups = sorted(_groups(context).items(),
                    key=lambda kv: kv[1].get("seen", 0), reverse=True)
    pages = max(1, (len(groups) + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    chunk = groups[page * PAGE:(page + 1) * PAGE]

    if not chunk:
        body = "هنوز در هیچ گروهی استفاده نشده."
    else:
        rows = []
        for chat_id, info in chunk:
            title = html.escape(info.get("title") or str(chat_id))
            rows.append(f"• <b>{title}</b>\n   <code>{chat_id}</code> — "
                        f"{_since(info.get('seen', time.time()))}")
        body = "\n".join(rows)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("‹ قبلی", callback_data=f"adm:groups:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("بعدی ›", callback_data=f"adm:groups:{page + 1}"))
    keyboard = [nav] if nav else []
    keyboard.append([InlineKeyboardButton("« بازگشت", callback_data="adm:home")])

    text = (f"<b>👥 گروه‌ها</b> ({len(groups)}) — صفحهٔ {page + 1} از {pages}\n\n"
            + body)
    return text, InlineKeyboardMarkup(keyboard)


def _blocked_text(context) -> tuple[str, InlineKeyboardMarkup]:
    blocked = _blocked(context)
    users = _users(context)
    rows = []
    for uid in sorted(blocked):
        name = html.escape(users.get(uid, {}).get("name") or str(uid))
        rows.append(f"• {name} — <code>{uid}</code>")
    body = "\n".join(rows) if rows else "کسی مسدود نیست."
    keyboard = [
        [InlineKeyboardButton("➕ مسدود کردن", callback_data="adm:block"),
         InlineKeyboardButton("➖ آزاد کردن", callback_data="adm:unblock")],
        [InlineKeyboardButton("« بازگشت", callback_data="adm:home")],
    ]
    return f"<b>🚫 مسدودها</b> ({len(blocked)})\n\n{body}", InlineKeyboardMarkup(keyboard)


def _exempt_text(context) -> tuple[str, InlineKeyboardMarkup]:
    allowed = exempt(context)
    users, groups = _users(context), _groups(context)
    rows = []
    for ident in sorted(allowed):
        if ident in groups:
            name = html.escape(groups[ident].get("title") or "")
            what = f"👥 {name}" if name else "👥 گروه"
        else:
            name = html.escape(users.get(ident, {}).get("name") or "")
            what = f"👤 {name}" if name else "👤 کاربر"
        rows.append(f"• {what} — <code>{ident}</code>")
    body = "\n".join(rows) if rows else "کسی معاف نیست."
    keyboard = [
        [InlineKeyboardButton("➕ معاف کردن", callback_data="adm:allow"),
         InlineKeyboardButton("➖ برداشتن", callback_data="adm:disallow")],
        [InlineKeyboardButton("« بازگشت", callback_data="adm:home")],
    ]
    return (f"<b>✅ معاف از عضویت کانال</b> ({len(allowed)})\n\n{body}\n\n"
            f"<i>اینها لازم نیست عضو کانال باشند، ولی باید ربات را استارت "
            f"کرده باشند. شناسهٔ گروه، همه را داخل آن گروه معاف می‌کند.</i>",
            InlineKeyboardMarkup(keyboard))


def _log_text() -> str:
    path = Path(__file__).with_name("quotebot.log")
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"<b>📄 لاگ</b>\n\nخوانده نشد: {html.escape(str(exc))}"
    tail = "\n".join(lines[-LOG_LINES:])[-LOG_CHARS:]
    if not tail.strip():
        return "<b>📄 لاگ</b>\n\nخالی است."
    return f"<b>📄 آخرین {LOG_LINES} خط لاگ</b>\n\n<pre>{html.escape(tail)}</pre>"


_BACK = InlineKeyboardMarkup(
    [[InlineKeyboardButton("« بازگشت", callback_data="adm:home")]]
)


# ------------------------------------------------------------------- handlers

def make_panel(owner_id: int | None):
    """Build the three handlers the panel needs, all closed over the owner's id."""

    def permitted(update: Update) -> bool:
        user = update.effective_user
        return owner_id is not None and user is not None and user.id == owner_id

    async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not permitted(update):
            user = update.effective_user
            log.info("/admin from %s ignored (OWNER_ID is %s)",
                     user.id if user else "?", owner_id)
            return
        context.user_data.pop("admin_await", None)
        await update.effective_message.reply_html(
            _home_text(context), reply_markup=_menu(context)
        )

    async def _show(query, text: str, markup: InlineKeyboardMarkup) -> None:
        """Replace the panel in place, tolerating an unchanged message."""
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
        except TelegramError as exc:
            if "not modified" not in str(exc).lower():
                raise

    async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not permitted(update):
            await query.answer()
            return
        parts = query.data.split(":")
        action = parts[1] if len(parts) > 1 else "home"
        await query.answer()

        if action == "home":
            context.user_data.pop("admin_await", None)
            await _show(query, _home_text(context), _menu(context))
        elif action == "stats":
            await _show(query, _stats_text(context), _BACK)
        elif action == "groups":
            page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            text, markup = _groups_page(context, page)
            await _show(query, text, markup)
        elif action == "blocked":
            text, markup = _blocked_text(context)
            await _show(query, text, markup)
        elif action == "exempt":
            text, markup = _exempt_text(context)
            await _show(query, text, markup)
        elif action == "logs":
            await _show(query, _log_text(), _BACK)
        elif action == "pause":
            context.bot_data["paused"] = not context.bot_data.get("paused")
            log.info("bot %s by the owner",
                     "paused" if context.bot_data["paused"] else "resumed")
            await _show(query, _home_text(context), _menu(context))
        elif action == "quota":
            text, markup = _quota_text(context)
            await _show(query, text, markup)
        elif action in ("qresetall", "qgiveall"):
            # Everyone at once is worth a second look: one press moves the
            # allowance for every person the bot has.
            giving = action == "qgiveall"
            await _show(query, (
                "<b>⚠️ برای همه</b>" + chr(10) + chr(10) +
                ("به سهمیهٔ همهٔ کاربران یکی اضافه می‌شود. مصرف قبلی‌شان سر جایش می‌ماند." if giving else "مصرف همه صفر می‌شود و هر کسی دوباره از اول سهمیهٔ کامل دارد. این کار برگشت ندارد.")
            ), InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ انجام بده",
                                      callback_data="adm:qgo:" + action[1:]),
                 InlineKeyboardButton("✖️ بی‌خیال", callback_data="adm:quota")],
            ]))
        elif action == "qgo":
            what = parts[2] if len(parts) > 2 else ""
            if what == "giveall":
                grant_quota(context, None, 1)
                said = "به سهمیهٔ همه یکی اضافه شد."
            else:
                said = "مصرف {} کاربر صفر شد.".format(reset_quota(context, None))
            log.info("owner changed everyone's avatar quota: %s", what)
            text, markup = _quota_text(context)
            await _show(query, said + chr(10) + chr(10) + text, markup)
        elif action in ("cast", "block", "unblock", "qreset", "qgive",
                        "allow", "disallow"):
            context.user_data["admin_await"] = action
            await _show(query, _PROMPTS[action], _BACK)
        elif action == "flush":
            await _show(query, _FLUSH_PROMPT, InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ پاک کن", callback_data="adm:flushgo"),
                 InlineKeyboardButton("✖️ بی‌خیال", callback_data="adm:home")],
            ]))
        elif action == "flushgo":
            dropped = flush_queue(context)
            await _show(
                query,
                f"<b>🧹 صف پاک شد</b>\n\n"
                f"درخواست‌های در صف: {dropped}\n"
                f"هرچه هم هنوز دست تلگرام مانده، موقع رسیدن رد می‌شود.",
                _menu(context),
            )
        elif action == "castgo":
            await _broadcast(query, context)
        elif action == "close":
            context.user_data.pop("admin_await", None)
            try:
                await query.edit_message_text("پنل بسته شد.")
            except TelegramError:
                pass

    async def on_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Whatever the owner types while the panel is waiting for something."""
        if not permitted(update):
            return
        waiting = context.user_data.get("admin_await")
        if not waiting:
            return
        message = update.effective_message

        if waiting == "cast":
            # The message is copied as it stands, so a photo or a formatted text
            # reaches everyone exactly as it was written here.
            context.user_data["cast_from"] = (message.chat_id, message.message_id)
            context.user_data.pop("admin_await", None)
            # The same list the sending walks. Counting a different one here
            # made the confirmation a guess about somebody else.
            await message.reply_html(
                f"این پیام برای <b>{len(members(context))}</b> کاربر فرستاده می‌شود.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ بفرست", callback_data="adm:castgo"),
                     InlineKeyboardButton("✖️ بی‌خیال", callback_data="adm:home")],
                ]),
            )
            return

        said = (message.text or "").split()
        target = said[0] if said else ""
        count = 1
        if len(said) > 1 and said[1].lstrip("-").isdigit():
            count = max(1, min(50, int(said[1])))
        if not target.lstrip("-").isdigit():
            await message.reply_text("یک شناسهٔ عددی بفرست.")
            return
        user_id = int(target)
        context.user_data.pop("admin_await", None)

        if waiting == "block":
            if owner_id is not None and user_id == owner_id:
                await message.reply_text("خودت را نمی‌شود مسدود کرد.")
                return
            _blocked(context).add(user_id)
            await message.reply_text(f"کاربر {user_id} مسدود شد.")
        elif waiting == "unblock":
            if user_id in _blocked(context):
                _blocked(context).discard(user_id)
                await message.reply_text(f"کاربر {user_id} آزاد شد.")
            else:
                await message.reply_text("این شناسه مسدود نبود.")
        elif waiting == "qreset":
            reset_quota(context, user_id)
            await message.reply_text("سهمیهٔ آواتار کاربر {} از نو شروع شد.".format(user_id))
        elif waiting == "qgive":
            grant_quota(context, user_id, count)
            await message.reply_text("{} سهمیهٔ تازه به کاربر {} داده شد.".format(count, user_id))
        elif waiting == "allow":
            exempt(context).add(user_id)
            what = "گروه" if user_id < 0 else "کاربر"
            await message.reply_text(
                f"{what} {user_id} دیگر لازم نیست عضو کانال باشد.")
        elif waiting == "disallow":
            if user_id in exempt(context):
                exempt(context).discard(user_id)
                await message.reply_text(f"معافیت {user_id} برداشته شد.")
            else:
                await message.reply_text("این شناسه معاف نبود.")

        log.info("owner %s for %s", waiting, user_id)
        await message.reply_html(_home_text(context), reply_markup=_menu(context))

    async def _broadcast(query, context: ContextTypes.DEFAULT_TYPE) -> None:
        source = context.user_data.pop("cast_from", None)
        if source is None:
            await _show(query, "چیزی برای فرستادن نمانده.", _menu(context))
            return
        chat_id, message_id = source
        targets = members(context)
        sent = failed = 0
        await _show(query, f"در حال فرستادن به {len(targets)} کاربر…", _BACK)

        for i, uid in enumerate(targets, 1):
            try:
                await context.bot.copy_message(uid, chat_id, message_id)
                sent += 1
            except Forbidden:
                # They blocked the bot or deleted their account. This is the
                # only moment anyone finds out, so it is written down here and
                # they stop being counted as a user.
                lost(context, uid)
                failed += 1
            except TelegramError:
                # Something else went wrong for this one; no reason to stop.
                failed += 1
            if i % 25 == 0:
                await _show(query, f"فرستاده شد: {sent} از {len(targets)}…", _BACK)
            await asyncio.sleep(BROADCAST_PAUSE)

        log.info("broadcast finished: %s sent, %s failed", sent, failed)
        await _show(
            query,
            f"<b>📣 پیام همگانی تمام شد</b>\n\n"
            f"✅ رسید: {sent}\n"
            f"✖️ نرسید: {failed}",
            _menu(context),
        )

    return cmd_admin, on_button, on_input


_PROMPTS = {
    "cast": ("<b>📣 پیام همگانی</b>\n\n"
             "پیامی که می‌خواهی برای همه برود را همین‌جا بفرست — متن، عکس، هرچه باشد "
             "عیناً همان‌طور کپی می‌شود.\nقبل از فرستادن یک بار تأیید می‌گیرم."),
    "block": "<b>🚫 مسدود کردن</b>\n\nشناسهٔ عددی کاربر را بفرست.",
    "unblock": "<b>➖ آزاد کردن</b>\n\nشناسهٔ عددی کاربر را بفرست.",
    "allow": ("<b>✅ معاف کردن</b>\n\n"
              "شناسهٔ عددی کاربر یا گروه را بفرست.\n"
              "شناسهٔ گروه‌ها منفی است و در صفحهٔ گروه‌ها دیده می‌شود."),
    "disallow": ("<b>➖ برداشتن معافیت</b>\n\n"
                 "شناسهٔ عددی را بفرست."),
    "qreset": ("<b>♻️ ریست سهمیهٔ یک نفر</b>" + chr(10) + chr(10) + "شناسهٔ عددی کاربر را بفرست تا مصرفش صفر شود."),
    "qgive": ("<b>➕ افزودن سهمیه به یک نفر</b>" + chr(10) + chr(10) + "شناسهٔ عددی کاربر را بفرست تا یک سهمیهٔ تازه بگیرد. برای بیشتر، تعداد را بعد از شناسه بنویس، مثل <code>123456789 3</code>"),
}

_FLUSH_PROMPT = (
    "<b>🧹 پاک کردن صف</b>\n\n"
    "هر دستوری که هنوز جواب داده نشده دور ریخته می‌شود — هم آن‌هایی که "
    "دریافت شده‌اند و هم آن‌هایی که هنوز دست تلگرام است.\n\n"
    "کاربرانی که دستور داده‌اند جوابی نمی‌گیرند و باید دوباره بفرستند. "
    "این کار برگشت ندارد."
)
