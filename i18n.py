"""Bilingual (Persian/English) message catalog and per-user language resolution."""
from __future__ import annotations

from telegram import Update

DEFAULT = "en"
SUPPORTED = ("fa", "en")

# Telegram sends BCP-47-ish codes; these all mean "show this person Persian".
_FA_PREFIXES = ("fa", "fa-ir", "per", "prs")

STRINGS: dict[str, dict[str, str]] = {
    "welcome": {
        "fa": """سلام! 👋
من از پیام‌ها عکسِ نقل‌قول می‌سازم — یک کارت سیاه‌وسفید با متن پیام، اسم گوینده و عکس پروفایلش.

<b>سریع‌ترین راه امتحان کردن:</b>
همین حالا بنویس <code>/q سلام دنیا</code>

<b>کار اصلی‌ام:</b>
روی هر پیامی ریپلای کن و <code>/q</code> بفرست.

راهنمای کامل: /help""",
        "en": """Hi! 👋
I turn messages into quote cards — black and white, carrying the text, the sender's name and their profile photo.

<b>Quickest way to try me:</b>
Send <code>/q hello world</code> right now

<b>What I'm really for:</b>
Reply to any message and send <code>/q</code>.

Full guide: /help""",
    },
    "help": {
        "fa": """📖 <b>راهنمای Quoto</b>

من از پیام‌های تلگرام عکسِ نقل‌قول می‌سازم: یک کارت سیاه‌وسفید که متن پیام، اسم گوینده و عکس پروفایلش رویش نوشته شده.

➊ <b>ساده‌ترین کار</b>
۱. روی پیامی که می‌خواهی <b>ریپلای</b> کن
۲. بنویس <code>/q</code> و بفرست
تمام. کارت را همان‌جا می‌فرستم.

➋ <b>سه شکل خروجی</b>
<code>/q</code> — عکس
<code>/qs</code> — استیکر
<code>/qg</code> — گیف؛ متن جلوی چشم تایپ می‌شود
هر سه یک کارت‌اند، فقط قالبشان فرق دارد.

➌ <b>بدون ریپلای هم می‌شود</b>
<code>/q هر متنی که بخواهی</code>
کارت با اسم و عکس پروفایل خودت ساخته می‌شود.

➍ <b>تبدیل خودِ فایل</b>
<code>/sticker</code> — عکس یا ویدیوی ریپلای‌شده را استیکر می‌کند
<code>/gif</code> — ویدیو یا استیکر متحرک را گیف می‌کند
اینجا کارتی ساخته نمی‌شود؛ خودِ فایل عوض می‌شود.

➎ <b>در گروه</b>
مرا به گروه اضافه کن. اگر ریپلای‌ها را ندیدم و گفتم «روی پیامی ریپلای کن»، یعنی تلگرام اجازه نمی‌دهد پیام‌ها را ببینم؛ در این حالت کافی است مرا در گروه <b>ادمین</b> کنی.

➏ <b>در چتی که عضوش نیستم</b>
لازم نیست اضافه‌ام کنی. در همان چت بنویس:
<code>@BOT متن مورد نظر</code>
منویی باز می‌شود و انتخاب می‌کنی. چون تلگرام در این حالت به من نمی‌گوید روی چه پیامی ریپلای کرده‌ای، متن را باید خودت بنویسی یا پیست کنی.
برای اینکه اسم شخص دیگری زیر کوت بخورد:
<code>@BOT متن | اسم</code>

➐ <b>کوت گرفتن از حرف دیگران با اسم و عکس خودشان</b>
پیام آن شخص را به همین‌جا (چت خصوصی من) <b>فوروارد</b> کن، بعد روی پیام فورواردشده ریپلای کن و <code>/q</code> بزن. اسم و عکس پروفایل گوینده‌ی اصلی را خودم برمی‌دارم.

➑ <b>زبان</b>
<code>/lang</code> — فارسی، انگلیسی یا خودکار

<b>اگر عکس پروفایل روی کارت نیامد</b>
یعنی تنظیمات حریم خصوصی‌ات اجازه نمی‌دهد ببینمش. در تلگرام: Settings ← Privacy and Security ← Profile Photo را روی Everybody بگذار، یا همان‌جا یک Public Photo تعریف کن. اگر هیچ‌کدام نبود، به‌جای عکس، حرف اول اسم را می‌گذارم.""",
        "en": """📖 <b>Quoto help</b>

I turn Telegram messages into quote cards: a black-and-white card carrying the message text, the sender's name and their profile photo.

➊ <b>The basic move</b>
1. <b>Reply</b> to the message you want
2. Send <code>/q</code>
That's it — the card comes back in the same chat.

➋ <b>Three output formats</b>
<code>/q</code> — an image
<code>/qs</code> — a sticker
<code>/qg</code> — an animation; the text types itself
Same card, different wrapper.

➌ <b>No reply needed</b>
<code>/q any text you like</code>
The card is credited to you, with your profile photo.

➍ <b>Converting the file itself</b>
<code>/sticker</code> — turns the replied-to photo or video into a sticker
<code>/gif</code> — turns a video or animated sticker into a GIF
No card here; the file itself is converted.

➎ <b>In a group</b>
Add me to the group. If I answer "reply to a message" even though you did, Telegram is not letting me see it — making me an <b>admin</b> in the group fixes that.

➏ <b>In a chat I'm not in</b>
No need to add me. Type this in that chat:
<code>@BOT your text</code>
A menu opens and you pick one. Telegram never tells me what you replied to in this mode, so the text has to be typed or pasted.
To credit someone else:
<code>@BOT your text | name</code>

➐ <b>Quoting someone with their own name and photo</b>
<b>Forward</b> their message here to my private chat, then reply to that forwarded message with <code>/q</code>. I read the original sender's name and photo from the forward.

➑ <b>Language</b>
<code>/lang</code> — Persian, English, or automatic

<b>If the profile photo is missing from the card</b>
Your privacy settings are hiding it from me. In Telegram: Settings → Privacy and Security → Profile Photo → Everybody, or set a Public Photo there. With neither, I fall back to the first letter of the name.""",
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
# (max 120). Deliberately free of commands: this is a first impression, and the
# command list is one tap away in the menu once someone has started the bot.
DESCRIPTIONS: dict[str, str] = {
    "fa": """سلام! 👋
من از پیام‌ها عکسِ نقل‌قول می‌سازم.

هر پیامی را تبدیل می‌کنم به یک کارت سیاه‌وسفید، با متن پیام و اسم و عکس پروفایلِ گوینده‌اش. خروجی را به شکل عکس، استیکر یا گیف می‌گیری.

در گروه‌ها هم کار می‌کنم.

برای شروع Start را بزن 👇""",
    "en": """Hi! 👋
I turn messages into quote cards.

Any message becomes a black-and-white card carrying its text, the sender's name and their profile photo — as an image, a sticker or an animation.

I work in groups too.

Press Start to begin 👇""",
}

SHORT_DESCRIPTIONS: dict[str, str] = {
    "fa": "از پیام‌های تلگرام عکسِ نقل‌قول می‌سازم، با اسم و عکس پروفایلِ گوینده.",
    "en": "I turn Telegram messages into quote cards with the sender's name and photo.",
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
