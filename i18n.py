"""Bilingual (Persian/English) message catalog and per-user language resolution."""
from __future__ import annotations

from telegram import Update

DEFAULT = "en"
SUPPORTED = ("fa", "en")

# Telegram sends BCP-47-ish codes; these all mean "show this person Persian".
_FA_PREFIXES = ("fa", "fa-ir", "per", "prs")

STRINGS: dict[str, dict[str, str]] = {
    "help": {
        "fa": """سلام! من از پیام‌ها عکسِ نقل‌قول می‌سازم.

<b>روی یک پیام ریپلای کن و بفرست:</b>
/q یا /quote — عکس نقل‌قول
/qs — همون نقل‌قول به شکل استیکر
/qg — همون نقل‌قول به شکل گیف (متن تایپ می‌شود)

<b>بدون ریپلای هم می‌شود:</b>
<code>/q هر متنی که بخواهی</code> — به نام خودت ساخته می‌شود

<b>تبدیل خودِ پیام، همان‌طور که هست:</b>
/sticker — عکس یا ویدیو را استیکر می‌کنم
/gif — ویدیو یا استیکر متحرک را گیف می‌کنم

می‌تونی به‌جای دستور، در جواب پیام فقط بنویسی «کوت» یا «quote».
در گروه‌ها هم کار می‌کنم؛ فقط یادت باشه اول روی پیام ریپلای کنی.

/lang — تغییر زبان

<b>در گروهی که عضو نیستم:</b>
کافی است در همان چت بنویسی <code>@BOT متن</code> و از لیستی که باز می‌شود انتخاب کنی.
برای اینکه اسم دیگری زیر کوت بخورد: <code>@BOT متن | اسم</code>""",
        "en": """Hi! I turn messages into quote cards.

<b>Reply to a message and send:</b>
/q or /quote — a quote card
/qs — the same quote as a sticker
/qg — the same quote animated (the text types itself)

<b>Works without a reply too:</b>
<code>/q any text you like</code> — attributed to you

<b>Convert the message itself, as-is:</b>
/sticker — turns a photo or video into a sticker
/gif — turns a video or animated sticker into a GIF

Instead of a command you can just reply with the word "quote".
I work in groups too — just remember to reply to a message first.

/lang — change language

<b>In a chat I'm not a member of:</b>
Just type <code>@BOT some text</code> there and pick from the list that opens.
To credit someone else: <code>@BOT some text | name</code>""",
    },
    "need_reply": {
        "fa": "روی پیامی که می‌خوای ازش عکس بسازم ریپلای کن و دوباره دستور رو بفرست.",
        "en": "Reply to the message you want me to turn into a card, then send the command again.",
    },
    "need_reply_group": {
        "fa": """روی پیامی که می‌خوای ازش عکس بسازم ریپلای کن و دوباره دستور رو بفرست.

اگر ریپلای کردی و باز همین پیام را می‌بینی، یعنی تلگرام ریپلای را به من نمی‌دهد.
راه‌حل (یکی از این دو):
۱) ربات را در گروه ادمین کن، یا
۲) در @BotFather دستور /setprivacy را بزن، ربات را انتخاب کن، Disable را بزن،
   بعد ربات را از گروه حذف کن و دوباره اضافه کن.

تا آن موقع می‌توانی بنویسی: /q هر متنی که بخواهی""",
        "en": """Reply to the message you want me to turn into a card, then send the command again.

If you did reply and still see this, Telegram is not passing the reply to me.
Fix it one of two ways:
1) Make me an admin in this group, or
2) In @BotFather send /setprivacy, pick this bot, choose Disable,
   then remove me from the group and add me again.

Meanwhile you can type: /q any text you like""",
    },
    "need_text": {
        "fa": "اون پیام متنی نداره که بشه نقلش کرد. برای تبدیل خودِ پیام از /sticker یا /gif استفاده کن.",
        "en": "That message has no text to quote. Use /sticker or /gif to convert the message itself.",
    },
    "need_media": {
        "fa": "روی یک عکس، استیکر، گیف یا ویدیو ریپلای کن.",
        "en": "Reply to a photo, sticker, GIF or video.",
    },
    "too_big": {
        "fa": "این فایل بزرگ‌تر از ۲۰ مگابایته و ربات نمی‌تونه دانلودش کنه.",
        "en": "That file is over 20 MB, which is more than a bot is allowed to download.",
    },
    "failed": {
        "fa": "نشد بسازمش. یه بار دیگه امتحان کن.",
        "en": "I couldn't make that. Give it another try.",
    },
    "no_ffmpeg": {
        "fa": "ffmpeg در دسترس نیست؛ برای تبدیل ویدیو لازمه نصب بشه.",
        "en": "ffmpeg isn't available; it's required for video conversion.",
    },
    "convert_failed": {
        "fa": "تبدیل با خطا مواجه شد.",
        "en": "The conversion failed.",
    },
    "lang_prompt": {
        "fa": "زبان ربات را انتخاب کن:",
        "en": "Choose the bot's language:",
    },
    "lang_set": {
        "fa": "زبان روی فارسی تنظیم شد. ✅",
        "en": "Language set to English. ✅",
    },
    "lang_auto": {
        "fa": "زبان خودکار شد؛ از روی تنظیمات تلگرام تو انتخاب می‌شود.",
        "en": "Language set to automatic; I'll follow your Telegram settings.",
    },
    "btn_fa": {"fa": "فارسی", "en": "فارسی"},
    "btn_en": {"fa": "English", "en": "English"},
    "btn_auto": {"fa": "خودکار 🌐", "en": "Automatic 🌐"},
    "inline_empty": {
        "fa": "متن را بنویس تا برایت کوت بسازم",
        "en": "Type some text and I'll turn it into a quote",
    },
    "inline_need_start": {
        "fa": "اول ربات را استارت کن، بعد دوباره امتحان کن",
        "en": "Start the bot first, then try again",
    },
    "inline_photo": {
        "fa": "عکس نقل‌قول",
        "en": "Quote card",
    },
    "inline_command": {
        "fa": "اینجا دستور لازم نیست — فقط خودِ متن را بنویس",
        "en": "No command needed here — just type the text itself",
    },
}

COMMANDS: dict[str, list[tuple[str, str]]] = {
    "fa": [
        ("quote", "ساخت عکس نقل‌قول از پیام ریپلای‌شده"),
        ("qs", "نقل‌قول به شکل استیکر"),
        ("qg", "نقل‌قول به شکل گیف"),
        ("sticker", "تبدیل عکس/ویدیوی ریپلای‌شده به استیکر"),
        ("gif", "تبدیل ویدیو/استیکر ریپلای‌شده به گیف"),
        ("lang", "تغییر زبان"),
        ("help", "راهنما"),
    ],
    "en": [
        ("quote", "Make a quote card from the replied-to message"),
        ("qs", "The quote as a sticker"),
        ("qg", "The quote as an animation"),
        ("sticker", "Turn the replied-to photo/video into a sticker"),
        ("gif", "Turn the replied-to video/sticker into a GIF"),
        ("lang", "Change language"),
        ("help", "Help"),
    ],
}


# Shown on the empty chat before Start (max 512 chars), and on the bot's profile
# (max 120). "@BOT" is replaced with the real username when these are uploaded.
DESCRIPTIONS: dict[str, str] = {
    "fa": """سلام! 👋
من از پیام‌ها عکسِ نقل‌قول می‌سازم.

روی هر پیامی ریپلای کن و /q بفرست — متن پیام را با اسم و عکس پروفایلِ گوینده تبدیل به یک کارت سیاه‌وسفید می‌کنم.

/qs — همان کارت به شکل استیکر
/qg — همان کارت، متحرک

در گروه‌ها هم کار می‌کنم. در چت‌هایی که عضو نیستم کافی است بنویسی @BOT و بعدش متن.

برای شروع Start را بزن 👇""",
    "en": """Hi! 👋
I turn messages into quote cards.

Reply to any message with /q and I'll set its text against the sender's name and profile photo, on a black-and-white card.

/qs — the same card as a sticker
/qg — the same card, animated

I work in groups too. In chats I'm not a member of, just type @BOT followed by your text.

Press Start to begin 👇""",
}

SHORT_DESCRIPTIONS: dict[str, str] = {
    "fa": "از پیام‌ها عکسِ نقل‌قول می‌سازم، با اسم و عکس پروفایلِ گوینده. روی پیام ریپلای کن و /q بفرست.",
    "en": "I turn messages into quote cards with the sender's name and photo. Reply to a message and send /q.",
}


def normalize(code: str | None) -> str:
    """Map a Telegram language_code onto one of the languages we actually speak."""
    if not code:
        return DEFAULT
    code = code.lower()
    return "fa" if code.startswith(_FA_PREFIXES) else "en"


def resolve(update: Update, user_data: dict | None) -> str:
    """A manual /lang choice wins; otherwise follow the user's Telegram language."""
    chosen = (user_data or {}).get("lang")
    if chosen in SUPPORTED:
        return chosen
    user = update.effective_user
    return normalize(user.language_code if user else None)


def t(key: str, lang: str) -> str:
    entry = STRINGS[key]
    return entry.get(lang) or entry[DEFAULT]
