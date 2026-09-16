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
from telegram.error import TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

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

def _menu(context) -> InlineKeyboardMarkup:
    paused = context.bot_data.get("paused")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 آمار", callback_data="adm:stats"),
         InlineKeyboardButton("👥 گروه‌ها", callback_data="adm:groups:0")],
        [InlineKeyboardButton("📣 پیام همگانی", callback_data="adm:cast"),
         InlineKeyboardButton("🚫 مسدودها", callback_data="adm:blocked")],
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
    users, groups = _users(context), _groups(context)
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
    users, groups = _users(context), _groups(context)
    counts = context.bot_data.get("counts", {})
    now = time.time()
    day = sum(1 for u in users.values() if now - u.get("seen", 0) < 86400)
    week = sum(1 for u in users.values() if now - u.get("seen", 0) < 7 * 86400)
    fresh = sum(1 for u in users.values() if now - u.get("first", 0) < 86400)

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
        f"🚫 مسدود: {len(_blocked(context))}",
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
        elif action == "logs":
            await _show(query, _log_text(), _BACK)
        elif action == "pause":
            context.bot_data["paused"] = not context.bot_data.get("paused")
            log.info("bot %s by the owner",
                     "paused" if context.bot_data["paused"] else "resumed")
            await _show(query, _home_text(context), _menu(context))
        elif action in ("cast", "block", "unblock", "quota"):
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
            await message.reply_html(
                f"این پیام برای <b>{len(_users(context))}</b> کاربر فرستاده می‌شود.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ بفرست", callback_data="adm:castgo"),
                     InlineKeyboardButton("✖️ بی‌خیال", callback_data="adm:home")],
                ]),
            )
            return

        target = (message.text or "").strip()
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
        elif waiting == "quota":
            context.bot_data.setdefault("avatar_uses", {}).pop(user_id, None)
            await message.reply_text(f"سهمیهٔ آواتار کاربر {user_id} صفر شد.")

        log.info("owner %s for %s", waiting, user_id)
        await message.reply_html(_home_text(context), reply_markup=_menu(context))

    async def _broadcast(query, context: ContextTypes.DEFAULT_TYPE) -> None:
        source = context.user_data.pop("cast_from", None)
        if source is None:
            await _show(query, "چیزی برای فرستادن نمانده.", _menu(context))
            return
        chat_id, message_id = source
        targets = [uid for uid in _users(context) if uid not in _blocked(context)]
        sent = failed = 0
        await _show(query, f"در حال فرستادن به {len(targets)} کاربر…", _BACK)

        for i, uid in enumerate(targets, 1):
            try:
                await context.bot.copy_message(uid, chat_id, message_id)
                sent += 1
            except TelegramError:
                # Someone who blocked the bot or deleted their account: expected,
                # and no reason to stop the rest of the run.
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
    "quota": ("<b>🖼 سهمیهٔ آواتار</b>\n\n"
              "شناسهٔ عددی کاربر را بفرست تا سهمیه‌اش دوباره از صفر شروع شود."),
}

_FLUSH_PROMPT = (
    "<b>🧹 پاک کردن صف</b>\n\n"
    "هر دستوری که هنوز جواب داده نشده دور ریخته می‌شود — هم آن‌هایی که "
    "دریافت شده‌اند و هم آن‌هایی که هنوز دست تلگرام است.\n\n"
    "کاربرانی که دستور داده‌اند جوابی نمی‌گیرند و باید دوباره بفرستند. "
    "این کار برگشت ندارد."
)
