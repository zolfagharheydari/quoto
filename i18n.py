"""Bilingual (Persian/English) message catalog and per-user language resolution."""
from __future__ import annotations

from telegram import Update

DEFAULT = "fa"
SUPPORTED = ("fa", "en")

# The bot's audience is Persian-speaking, so Persian is the default and English
# is served only to clients that explicitly ask for it.
_EN_PREFIX = "en"

STRINGS: dict[str, dict[str, str]] = {
    "welcome": {
        "fa": """سلام! 👋
من از پیام‌ها عکسِ نقل‌قول می‌سازم — کارتی با متن پیام، اسم گوینده و عکس پروفایلش.

<b>سریع‌ترین راه امتحان کردن:</b>
همین حالا بنویس <code>/quote سلام دنیا</code>

<b>کار اصلی‌ام:</b>
روی هر پیامی ریپلای کن و <code>/quote</code> بفرست.

راهنمای کامل: /help

<b>کانال من:</b> @getQuoto
هر قابلیت تازه‌ای که اضافه شود، هر چیزی که درست شود، آنجا می‌گویم. عضو شدن اختیاری است — فقط اگر دوست داری در جریان باشی.""",
        "en": """Hi! 👋
I turn messages into quote cards carrying the text, the sender's name and their profile photo.

<b>Quickest way to try me:</b>
Send <code>/quote hello world</code> right now

<b>What I'm really for:</b>
Reply to any message and send <code>/quote</code>.

Full guide: /help

<b>My channel:</b> @getQuoto
Anything new, anything fixed, I say it there. Joining is up to you - only if you would like to know.""",
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
    "group_intro": {
        "fa": """سلام! 👋 من <b>Quoto</b> هستم و از پیام‌های این گروه عکسِ نقل‌قول می‌سازم.

<b>چطور کار می‌کنم؟</b>
روی پیامی که می‌خواهید <b>ریپلای</b> کنید، بعد یکی از این‌ها را بفرستید:

<code>/quote</code> — کارت نقل‌قول، به شکل عکس
<code>/sticker</code> — همان کارت، به شکل استیکر
<code>/gif</code> — همان کارت، به شکل گیف با افکت تایپ
<code>/screenshot</code> — اسکرین‌شات، همان‌طور که در تلگرام دیده می‌شود

<b>فارسی هم می‌فهمم</b>
به‌جای دستور، در جواب همان پیام کافی است بنویسید:
«کوتش کن» • «استیکرش کن» • «گیفش کن» • «شاتش کن»

<b>عکس دلخواه</b>
هر کس می‌تواند در چت خصوصی من با <code>/avatar</code> عکسی انتخاب کند که روی کوت‌هایش بنشیند (۲ بار)، و با <code>/settings</code> بگوید کدام عکس نماینده‌اش باشد.

<b>استیکرپک گروه</b>
هر استیکری که اینجا ساخته شود، در یک پک به نام همین گروه جمع می‌شود.
<code>/pack</code> — لینک پک را می‌دهد
<code>/unpack</code> — روی یک استیکر ریپلای کن تا از پک حذف شود (فقط ادمین‌های گروه)
<code>/delpack</code> — کل پک گروه را پاک می‌کند (فقط ادمین‌ها، و برگشت ندارد)

<b>یک نکته</b>
هر کسی که می‌خواهد از من استفاده کند، باید یک بار در چت خصوصی مرا استارت کرده باشد. اگر نکرده باشد، خودم دکمه‌اش را نشانش می‌دهم.

⚠️ <b>لطفاً مرا ادمین کنید</b>
تا ادمین نشوم، تلگرام ریپلای‌ها را به من نمی‌دهد و هیچ‌کدام از دستورهای بالا روی پیام‌ها کار نمی‌کند.

راهنمای کامل: /help""",
        "en": """Hi! 👋 I'm <b>Quoto</b>, and I turn this group's messages into quote cards.

<b>How it works</b>
<b>Reply</b> to the message you want, then send one of these:

<code>/quote</code> — a quote card, as an image
<code>/sticker</code> — the same card, as a sticker
<code>/gif</code> — the same card, animated
<code>/screenshot</code> — a screenshot, the way Telegram draws it

<b>Persian phrases work too</b>
As a reply, instead of a command:
«کوتش کن» • «استیکرش کن» • «گیفش کن» • «شاتش کن»

<b>Your own picture</b>
Anyone can set a picture for their quotes with <code>/avatar</code> in my private chat (twice), and choose which picture stands for them with <code>/settings</code>.

<b>This group's sticker pack</b>
Every sticker made here joins a pack named after the group.
<code>/pack</code> — the link
<code>/unpack</code> — reply to a sticker to take it out of the pack (group admins only)
<code>/delpack</code> — delete the pack entirely (admins in a group, your own in private)

<b>One note</b>
Anyone who wants to use me has to have started me once in a private chat. If they haven't, I'll show them the button.

⚠️ <b>Please make me an admin</b>
Until then Telegram will not pass replies to me, and none of the above will work on your messages.

Full guide: /help""",
    },
    "help": {
        "fa": """📖 <b>راهنمای Quoto</b>

من از پیام‌های تلگرام عکسِ نقل‌قول می‌سازم: کارتی که متن پیام، اسم گوینده و عکس پروفایلش رویش نوشته شده.

➊ <b>ساده‌ترین کار</b>
۱. روی پیامی که می‌خواهی <b>ریپلای</b> کن
۲. بنویس <code>/quote</code> و بفرست
تمام. کارت را همان‌جا می‌فرستم.

➋ <b>شکل‌های خروجی</b>
<code>/quote</code> — کارت نقل‌قول، به شکل عکس
<code>/sticker</code> — همان کارت، به شکل استیکر
<code>/gif</code> — همان کارت، به شکل گیف؛ متن جلوی چشم تایپ می‌شود
<code>/screenshot</code> — پیام را همان‌طور که در تلگرام دیده می‌شود می‌سازد: حباب، عکس پروفایل، اسم و ساعت
اگر پیام ریکشن خورده باشد و ربات از قبل ادمین گروه بوده، ریکشن‌ها هم زیرش می‌آیند.

در گروه، استیکر و اسکرین‌شات به استیکرپک گروه هم اضافه می‌شوند.

یا به‌جای دستور، در جواب پیام فارسی بنویس:
«کوتش کن» • «استیکرش کن» • «گیفش کن» • «شاتش کن»
(در گروه فقط وقتی کار می‌کند که ادمین باشم)

➌ <b>بدون ریپلای هم می‌شود</b>
<code>/quote هر متنی که بخواهی</code>
کارت با اسم و عکس پروفایل خودت ساخته می‌شود.

➍ <b>در گروه</b>
مرا به گروه اضافه کن. اگر ریپلای‌ها را ندیدم و گفتم «روی پیامی ریپلای کن»، یعنی تلگرام اجازه نمی‌دهد پیام‌ها را ببینم؛ در این حالت کافی است مرا در گروه <b>ادمین</b> کنی.

➎ <b>در چتی که عضوش نیستم</b>
لازم نیست اضافه‌ام کنی. در همان چت بنویس:
<code>@BOT متن مورد نظر</code>
منویی باز می‌شود و انتخاب می‌کنی. چون تلگرام در این حالت به من نمی‌گوید روی چه پیامی ریپلای کرده‌ای، متن را باید خودت بنویسی یا پیست کنی. کارت به نام خودت ساخته می‌شود.

➏ <b>کوت گرفتن از حرف دیگران با اسم و عکس خودشان</b>
پیام آن شخص را به همین‌جا (چت خصوصی من) <b>فوروارد</b> کن، بعد روی پیام فورواردشده ریپلای کن و <code>/quote</code> بزن. اسم و عکس پروفایل گوینده‌ی اصلی را خودم برمی‌دارم.

➐ <b>عکس دلخواه برای کوت‌هایت</b>
می‌توانی عکسی انتخاب کنی که به‌جای عکس پروفایلت روی کوت‌ها بنشیند — چه خودت کوت بسازی، چه کس دیگری روی پیامت ریپلای بزند.
در چت خصوصی من عکس را بفرست و در کپشنش بنویس <code>/avatar</code>، یا عکس را بفرست و بعد رویش ریپلای کن و <code>/avatar</code> بزن.
<code>/avatar off</code> دوباره عکس پروفایل تلگرامت را برمی‌گرداند — یا در <code>/settings</code> دکمهٔ حذف را بزن.
می‌خواهی عکس بماند ولی فعلاً استفاده نشود؟ در <code>/settings</code> گزینهٔ دیگری را انتخاب کن؛ عکست غیرفعال می‌شود و پاک نمی‌شود.

⚠️ <b>هر کاربر فقط ۲ بار</b> می‌تواند عکس دلخواه انتخاب کند. بعد از هر انتخاب می‌گویم چند سهمیه‌ات مانده، و وقتی تمام شد دیگر عکس جدیدی پذیرفته نمی‌شود. پاک کردن با <code>/avatar off</code> سهمیه مصرف نمی‌کند.

➑ <b>انتخاب اینکه چه عکسی نمایندهٔ توست</b>
<code>/settings</code> در چت خصوصی، و از بین این‌ها یکی را بزن:
• عکسی که خودت فرستادی
• عکس پروفایل تلگرامت
• عکس پابلیک پروفایلت
• فقط حرف اول اسمت

هر وقت خواستی می‌توانی عوضش کنی؛ این انتخاب سهمیه‌ای ندارد.

<b>📋 همه‌ی دستورها</b>
<code>/quote</code> — از پیام ریپلای‌شده کارت نقل‌قول می‌سازد
<code>/sticker</code> — همان کارت، به شکل استیکر
<code>/gif</code> — همان کارت، به شکل گیف با افکت تایپ
<code>/screenshot</code> — پیام را به شکل اسکرین‌شات تلگرام می‌سازد
<code>/pack</code> — لینک استیکرپک این گروه
<code>/unpack</code> — حذف یک استیکر از پک گروه (ادمین)
<code>/delpack</code> — حذف کامل پک (در گروه: ادمین؛ در پی‌وی: پک شخصی خودت)
<code>/mypack</code> — پک شخصی خودت؛ در همین چت می‌توانی اسمش را عوض کنی، یا روی یک استیکر ریپلای کنی و <code>/unpack</code> بزنی تا حذف شود
<code>/avatar</code> — عکس دلخواه برای کوت‌های خودت (فقط در چت خصوصی، ۲ بار)
<code>/settings</code> — انتخاب اینکه چه عکسی نمایندهٔ توست
<code>/template</code> — انتخاب قالب کوت‌ها: کلاسیک، کلاسیکِ رنگی، تمام‌قاب یا کارت
<code>/lang</code> — تغییر زبان ربات
<code>/help</code> — همین راهنما

<b>معادل فارسی‌شان، در جواب یک پیام:</b>
«کوتش کن» = /quote
«استیکرش کن» = /sticker
«گیفش کن» = /gif
«شاتش کن» = /screenshot

<b>اگر عکس پروفایل روی کارت نیامد</b>
یعنی تنظیمات حریم خصوصی‌ات اجازه نمی‌دهد ببینمش. در تلگرام: Settings ← Privacy and Security ← Profile Photo را روی Everybody بگذار، یا همان‌جا یک Public Photo تعریف کن. اگر هیچ‌کدام نبود، به‌جای عکس، حرف اول اسم را می‌گذارم.
یا اصلاً با <code>/avatar</code> یک عکس دلخواه بگذار تا اصلاً به تنظیمات تلگرام کاری نداشته باشم.""",
        "en": """📖 <b>Quoto help</b>

I turn Telegram messages into quote cards: the message text, the sender's name and their profile photo on one card.

➊ <b>The basic move</b>
1. <b>Reply</b> to the message you want
2. Send <code>/quote</code>
That's it — the card comes back in the same chat.

➋ <b>Output formats</b>
<code>/quote</code> — a quote card, as an image
<code>/sticker</code> — the same card, as a sticker
<code>/gif</code> — the same card, animated; the text types itself
<code>/screenshot</code> — the message as it looks in Telegram: bubble, avatar, name and time
If the message has reactions and the bot was already an admin of the group, they are drawn under it too.

In a group, stickers and screenshots also join the group's sticker pack.

Or say it in Persian, as a reply, instead of using a command:
«کوتش کن» • «استیکرش کن» • «گیفش کن» • «شاتش کن»
(in a group these only reach me once I am an admin)

➌ <b>No reply needed</b>
<code>/quote any text you like</code>
The card is credited to you, with your profile photo.

➍ <b>In a group</b>
Add me to the group. If I answer "reply to a message" even though you did, Telegram is not letting me see it — making me an <b>admin</b> in the group fixes that.

➎ <b>In a chat I'm not in</b>
No need to add me. Type this in that chat:
<code>@BOT your text</code>
A menu opens and you pick one. Telegram never tells me what you replied to in this mode, so the text has to be typed or pasted, and the card is credited to you.

➏ <b>Quoting someone with their own name and photo</b>
<b>Forward</b> their message here to my private chat, then reply to that forwarded message with <code>/quote</code>. I read the original sender's name and photo from the forward.

➐ <b>Your own picture on your quotes</b>
You can pick a picture to use instead of your profile photo — on quotes you make and on quotes others make of you.
In my private chat, send the photo with <code>/avatar</code> as its caption, or send it and then reply to it with <code>/avatar</code>.
<code>/avatar off</code> goes back to your Telegram profile photo — or use the delete button in <code>/settings</code>.
Want to keep the picture but not use it for now? Pick another option in <code>/settings</code>: it is turned off, not deleted.

⚠️ <b>Two changes each, ever.</b> I tell you how many you have left after each one, and once they are gone no new picture is accepted. Clearing with <code>/avatar off</code> costs nothing.

➑ <b>Choosing which picture stands for you</b>
Send <code>/settings</code> in my private chat and pick one:
• the picture you sent
• your Telegram profile photo
• your public profile photo
• just the first letter of your name

Change it whenever you like; this one has no limit.

<b>📋 Every command</b>
<code>/quote</code> — a quote card from the replied-to message
<code>/sticker</code> — the same card, as a sticker
<code>/gif</code> — the same card, animated
<code>/screenshot</code> — the message as a Telegram screenshot
<code>/pack</code> — the link to this group's sticker pack
<code>/unpack</code> — remove one sticker from the pack (admins)
<code>/delpack</code> — delete the pack entirely (admins in a group, your own in private)
<code>/avatar</code> — your own picture for your quotes (private chat, twice)
<code>/settings</code> — choose which picture stands for you
<code>/template</code> — choose the template: classic, tinted, full frame or card
<code>/lang</code> — change the bot's language
<code>/help</code> — this guide

<b>Their Persian equivalents, as a reply:</b>
«کوتش کن» = /quote
«استیکرش کن» = /sticker
«گیفش کن» = /gif
«شاتش کن» = /screenshot

<b>If the profile photo is missing from the card</b>
Your privacy settings are hiding it from me. In Telegram: Settings → Privacy and Security → Profile Photo → Everybody, or set a Public Photo there. With neither, I fall back to the first letter of the name.
Or set a picture with <code>/avatar</code> and your Telegram settings stop mattering.""",
    },
    "avatar_saved": {
        "fa": """عکس دلخواهت ذخیره شد ✅
شما {used} سهمیه از {quota} سهمیه خود را استفاده کردید.""",
        "en": """Saved ✅
You have used {used} of your {quota} changes.""",
    },
    "avatar_saved_last": {
        "fa": """عکس دلخواهت ذخیره شد ✅
شما {used} سهمیه از {quota} سهمیه خود را استفاده کردید و دیگر قادر به انتخاب آواتار جدید نیستید.""",
        "en": """Saved ✅
You have used {used} of your {quota} changes, and cannot choose a new avatar again.""",
    },
    "avatar_quota_spent": {
        "fa": "سهمیه‌ات تمام شده است. هر کاربر فقط {quota} بار می‌تواند عکس دلخواه انتخاب کند.",
        "en": "Your changes are used up. Each person may choose a picture {quota} times.",
    },
    "settings_prompt": {
        "fa": """عکس روی کوت‌هایت از کجا بیاید؟

اگر گزینه‌ای جز عکس خودت را انتخاب کنی، آن عکس فقط <b>غیرفعال</b> می‌شود و پاک نمی‌شود — هر وقت خواستی برمی‌گردانی‌اش، بدون اینکه سهمیه‌ای خرج شود.""",
        "en": """Which picture should stand for you on your quotes?

Choosing anything other than your own picture only <b>turns it off</b> — it is not deleted, and you can switch back any time without spending a change.""",
    },
    "settings_set": {
        "fa": "انجام شد ✅ از این به بعد: {choice}",
        "en": "Done ✅ From now on: {choice}",
    },
    "quota_granted": {
        "fa": """🎁 سهمیهٔ عکس پروفایلت بیشتر شد.

حالا می‌توانی {count} بار دیگر عکس دلخواه انتخاب کنی. با <code>/avatar</code> عکس را بفرست.""",
        "en": """🎁 Your picture allowance just went up.

You can choose a picture {count} more time(s). Send it with <code>/avatar</code>.""",
    },
    "quota_reset": {
        "fa": """♻️ سهمیهٔ عکس پروفایلت از نو شروع شد.

دوباره سهمیهٔ کامل داری. با <code>/avatar</code> عکس تازه بفرست.""",
        "en": """♻️ Your picture allowance has been reset.

You have the full allowance again. Send a new one with <code>/avatar</code>.""",
    },
    "btn_template": {"fa": "🎨 قالب کوت", "en": "🎨 Quote template"},
    "template_prompt": {
        "fa": """کوت‌هایت با کدام قالب ساخته شود؟

شماره‌اش را از روی تصویر بالا انتخاب کن. هر وقت خواستی عوضش کن — روی کوت‌هایی که قبلاً ساخته‌ای اثری ندارد.""",
        "en": """Which template should your quotes be made with?

Pick a number from the picture above. Change it whenever you like — it does not touch quotes you have already made.""",
    },
    "template_set": {
        "fa": "قالب کوت‌هایت شد: {choice} ✅",
        "en": "Your quotes now use: {choice} ✅",
    },
    "template_current": {"fa": "الان: {choice}", "en": "Currently: {choice}"},
    "tpl_classic": {"fa": "1 — کلاسیک", "en": "1 — Classic"},
    "tpl_tinted": {"fa": "2 — کلاسیکِ رنگی", "en": "2 — Classic, tinted"},
    "tpl_portrait": {"fa": "3 — تمام‌قاب", "en": "3 — Full frame"},
    "tpl_card": {"fa": "4 — کارت", "en": "4 — Card"},
    "src_custom": {"fa": "عکسی که خودم فرستادم", "en": "The picture I sent"},
    "src_profile": {"fa": "عکس پروفایل تلگرامم", "en": "My Telegram profile photo"},
    "src_public": {"fa": "عکس پابلیک پروفایلم", "en": "My public profile photo"},
    "src_letter": {"fa": "فقط حرف اول اسمم", "en": "Just the first letter of my name"},
    "avatar_cleared": {
        "fa": """عکس دلخواهت پاک شد. دوباره از عکس پروفایل تلگرامت استفاده می‌کنم.

توجه: سهمیه‌ای که خرج کرده بودی برنمی‌گردد.""",
        "en": """Cleared. I'll go back to your Telegram profile photo.

Note: the change you spent is not given back.""",
    },
    "btn_avatar_delete": {
        "fa": "🗑 حذف کامل عکسی که فرستادم",
        "en": "🗑 Delete the picture I sent",
    },
    "avatar_none": {
        "fa": "عکس دلخواهی نداری که پاک کنم.",
        "en": "You have no chosen picture to clear.",
    },
    "delpack_ask_group": {
        "fa": """مطمئنی؟ می‌خواهی <b>کل استیکرپک این گروه</b> پاک شود.

این کار برگشت‌ناپذیر است: پک از تلگرام حذف می‌شود، لینکش دیگر باز نمی‌شود، و برای <b>هر کسی</b> که آن را به استیکرهایش اضافه کرده هم از بین می‌رود — نه فقط برای این گروه.""",
        "en": """Are you sure? This deletes <b>this group's whole sticker pack</b>.

There is no undo: the pack is removed from Telegram, its link stops working, and it disappears for <b>everyone</b> who ever added it - not only for this group.""",
    },
    "delpack_ask_personal": {
        "fa": """مطمئنی؟ می‌خواهی <b>کل پک شخصی‌ات</b> پاک شود.

این کار برگشت‌ناپذیر است: پک از تلگرام حذف می‌شود، لینکش دیگر باز نمی‌شود، و برای <b>هر کسی</b> که آن را اضافه کرده هم از بین می‌رود.

اگر فقط یک استیکر اضافه است، رویش ریپلای کن و /unpack بزن.""",
        "en": """Are you sure? This deletes <b>your whole pack</b>.

There is no undo: it is removed from Telegram, its link stops working, and it disappears for <b>everyone</b> who ever added it.

If it is one sticker you want gone, reply to it and send /unpack instead.""",
    },
    "btn_delpack_yes": {"fa": "بله، پاکش کن", "en": "Yes, delete it"},
    "btn_delpack_no": {"fa": "بی‌خیال", "en": "Keep it"},
    "delpack_done": {
        "fa": "پک پاک شد. لینکش دیگر کار نمی‌کند ✅",
        "en": "The pack is gone. Its link no longer works ✅",
    },
    "delpack_cancelled": {
        "fa": "کاری نکردم؛ پک سر جایش است.",
        "en": "Nothing done - the pack is still there.",
    },
    "delpack_none": {
        "fa": "پکی برای پاک کردن نیست.",
        "en": "There is no pack to delete.",
    },
    "delpack_failed": {
        "fa": "نشد پاکش کنم. کمی بعد دوباره امتحان کن.",
        "en": "I could not delete it. Try again in a moment.",
    },
    "delpack_not_admin": {
        "fa": "فقط ادمین‌های این گروه می‌توانند پک گروه را پاک کنند.",
        "en": "Only this group's admins can delete the group's pack.",
    },
    "unpack_need_reply": {
        "fa": "روی همان استیکری که می‌خواهی از پک حذف شود ریپلای کن و دوباره این دستور را بفرست.",
        "en": "Reply to the sticker you want out of the pack and send this again.",
    },
    "unpack_not_admin": {
        "fa": "فقط ادمین‌های این گروه می‌توانند استیکری را از پک حذف کنند.",
        "en": "Only this group's admins can remove a sticker from the pack.",
    },
    "unpack_not_ours": {
        "fa": "این استیکر مال پکِ این گروه نیست، پس کاری با آن ندارم.",
        "en": "That sticker is not from this group's pack, so I will not touch it.",
    },
    "unpack_done": {
        "fa": "استیکر از پک حذف شد ✅\n(ممکن است تا چند دقیقه در تلگرام تو کش‌شده بماند.)",
        "en": "Removed from the pack ✅\n(Telegram may keep showing it to you for a few minutes.)",
    },
    "unpack_failed": {
        "fa": "نشد حذفش کنم. کمی بعد دوباره امتحان کن.",
        "en": "I could not remove it. Try again in a moment.",
    },
    "mypack_created": {
        "fa": """استیکرپک شخصی‌ات ساخته شد 🎉
{link}

از این به بعد هر کوت و اسکرین‌شاتی که اینجا یا با حالت inline بسازی به همین اضافه می‌شود. با /mypack هر وقت خواستی لینکش را بگیر.""",
        "en": """Your own sticker pack is ready 🎉
{link}

Everything you make here or with inline mode joins it from now on. /mypack gives you the link whenever you want it.""",
    },
    "mypack_link": {
        "fa": """استیکرپک شخصی‌ات:
{link}

هر کوت یا اسکرین‌شاتی که در چت خصوصی من یا با حالت inline بسازی، خودکار به آن اضافه می‌شود.""",
        "en": """Your own sticker pack:
{link}

Everything you make in my private chat or with inline mode is added to it.""",
    },
    "mypack_none": {
        "fa": """هنوز پکی نداری.

یک کوت بساز — در همین چت <code>/quote سلام دنیا</code> بفرست — و پک خودت ساخته می‌شود.""",
        "en": """You do not have a pack yet.

Make a quote - send <code>/quote hello world</code> here - and yours will be created.""",
    },
    "btn_pack_rename": {"fa": "✏️ تغییر نام پک", "en": "✏️ Rename the pack"},
    "mypack_rename_ask": {
        "fa": """اسم تازهٔ پکت را بفرست.

تا ۶۴ حرف. برای بی‌خیال شدن، هر دستور دیگری بزن.""",
        "en": """Send the new title for your pack.

Up to 64 characters. To drop it, just send any other command.""",
    },
    "mypack_renamed": {
        "fa": "اسم پکت شد: {title} ✅",
        "en": "Your pack is now called: {title} ✅",
    },
    "mypack_rename_failed": {
        "fa": "نشد اسمش را عوض کنم. اگر تازه پک ساخته‌ای، چند لحظه بعد دوباره امتحان کن.",
        "en": "I could not rename it. If the pack is brand new, try again in a moment.",
    },
    "mypack_removed": {
        "fa": """استیکر از پک شخصی‌ات حذف شد ✅
(ممکن است تا چند دقیقه در تلگرام تو کش‌شده بماند.)""",
        "en": """Removed from your pack ✅
(Telegram may keep showing it to you for a few minutes.)""",
    },
    "mypack_not_yours": {
        "fa": "این استیکر مال پک شخصی تو نیست، پس کاری با آن ندارم.",
        "en": "That sticker is not from your own pack, so I will not touch it.",
    },
    "mypack_need_reply": {
        "fa": "روی همان استیکری که می‌خواهی از پکت حذف شود ریپلای کن و دوباره /unpack بفرست.",
        "en": "Reply to the sticker you want out of your pack and send /unpack again.",
    },
    "avatar_private_only": {
        "fa": "این دستور فقط در چت خصوصی من کار می‌کند.",
        "en": "This command only works in my private chat.",
    },
    "avatar_how": {
        "fa": """با این دستور می‌توانی عکسی انتخاب کنی که به‌جای عکس پروفایلت روی کوت‌ها بنشیند.

<b>چطور:</b>
عکس را برایم بفرست و در کپشنش بنویس <code>/avatar</code>
یا عکس را بفرست، بعد روی آن ریپلای کن و <code>/avatar</code> بزن.

<b>برای برگشتن به عکس پروفایل تلگرام:</b>
<code>/avatar off</code>""",
        "en": """This lets you pick a picture to use on your quotes instead of your profile photo.

<b>How:</b>
Send me the photo with <code>/avatar</code> as its caption,
or send the photo, then reply to it with <code>/avatar</code>.

<b>To go back to your Telegram profile photo:</b>
<code>/avatar off</code>""",
    },
    "need_start": {
        "fa": """برای استفاده از من، اول باید یک بار مرا استارت کنی.

روی دکمه‌ی زیر بزن، در چت خصوصی Start را بزن، بعد همین‌جا دوباره امتحان کن.""",
        "en": """You need to start me once before you can use me.

Tap the button below, press Start in the private chat, then try again here.""",
    },
    "btn_start": {"fa": "شروع ربات", "en": "Start the bot"},
    "need_channel": {
        "fa": """برای استفاده از من اول در کانالم عضو شو 👇
همهٔ خبرها و تغییرها آنجا اعلام می‌شود.

بعد از عضو شدن، دوباره همین دستور را بفرست.""",
        "en": """Join my channel to use me 👇
Everything new is announced there.

Once you have joined, send the same command again.""",
    },
    "btn_channel": {"fa": "عضو شدن در کانال", "en": "Join the channel"},
    # The first thing anyone sees. It is a greeting that happens to ask for
    # something, not a refusal - nobody has done anything wrong yet.
    "need_channel_start": {
        "fa": """سلام! 👋
من از پیام‌ها عکسِ نقل‌قول می‌سازم — کارتی با متن پیام، اسم گوینده و عکس پروفایلش.

یک قدم مانده: عضو کانالم شو 👇
همهٔ خبرها و تغییرها آنجا اعلام می‌شود.

بعد از عضو شدن، دوباره /start را بزن تا راهنما را برایت بفرستم.""",
        "en": """Hi! 👋
I turn messages into quote cards carrying the text, the sender's name and their profile photo.

One step first: join my channel 👇
Everything new is announced there.

Once you have joined, send /start again and I'll show you around.""",
    },
    "need_reply": {
        "fa": "روی پیامی که می‌خوای ازش عکس بسازم ریپلای کن و دوباره دستور رو بفرست.",
        "en": "Reply to the message you want me to turn into a card, then send the command again.",
    },
    "need_reply_group": {
        "fa": """روی پیامی که می‌خوای ازش عکس بسازم ریپلای کن و دوباره دستور رو بفرست.

اگر ریپلای کردی و باز همین پیام را می‌بینی، یعنی تلگرام اجازه نمی‌دهد پیام‌ها را ببینم.
کافی است مرا در این گروه ادمین کنی.

تا آن موقع می‌توانی بنویسی: /quote هر متنی که بخواهی""",
        "en": """Reply to the message you want me to turn into a card, then send the command again.

If you did reply and still see this, Telegram is not passing the reply to me.
Making me an admin in this group fixes it.

Meanwhile you can type: /quote any text you like""",
    },
    "need_text": {
        "fa": "اون پیام متنی نداره که بشه نقلش کرد. ",
        "en": "That message has no text to quote. ",
    },
    "failed": {
        "fa": "نشد بسازمش. یه بار دیگه امتحان کن.",
        "en": "I couldn't make that. Give it another try.",
    },
    "inline_empty": {
        "fa": "متن را بنویس تا برایت کوت بسازم",
        "en": "Type some text and I'll turn it into a quote",
    },
    "inline_need_start": {
        "fa": "اول ربات را استارت کن، بعد دوباره امتحان کن",
        "en": "Start the bot first, then try again",
    },
    "pack_created": {
        "fa": """استیکرپک این گروه ساخته شد 🎉
{link}""",
        "en": """Made a sticker pack for this group 🎉
{link}""",
    },
    "pack_link": {
        "fa": """استیکرپک این گروه:
{link}""",
        "en": """This group's sticker pack:
{link}""",
    },
    "pack_none": {
        "fa": "هنوز استیکری برای این گروه ساخته نشده. روی یک پیام ریپلای کن و /sticker بزن.",
        "en": "No pack for this group yet. Reply to a message with /sticker to start one.",
    },
    "pack_groups_only": {
        "fa": "استیکرپک فقط برای گروه‌ها ساخته می‌شود.",
        "en": "Sticker packs are made for groups only.",
    },
    # The pill Telegram itself draws beside a name is in English whatever the
    # app language is, so these are the same in both. A group that has set a
    # custom title still wins over them; this is only the generic fallback.
    "badge_owner": {"fa": "owner", "en": "owner"},
    "badge_admin": {"fa": "admin", "en": "admin"},
    "inline_gif": {
        "fa": "گیف با افکت تایپ",
        "en": "GIF with the typing effect",
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

# Commands Telegram lists in the "/" menu. Both /help and /lang still work in a
# group if typed; they are simply not worth a slot in a group's menu, so they are
# offered in private chats only.
PRIVATE_ONLY: dict[str, list[tuple[str, str]]] = {
    "fa": [
        ("mypack", "استیکرپک شخصی خودت"),
        ("avatar", "انتخاب عکس دلخواه برای کوت‌هایت"),
        ("settings", "انتخاب اینکه چه عکسی روی کوت‌هایت بنشیند"),
        ("template", "انتخاب قالب کوت‌ها"),
        ("delpack", "حذف کامل پک شخصی‌ات"),
        ("lang", "تغییر زبان"),
        ("help", "راهنما"),
    ],
    "en": [
        ("mypack", "Your own sticker pack"),
        ("avatar", "Pick your own picture for your quotes"),
        ("settings", "Choose which picture stands for you"),
        ("template", "Choose the template your quotes use"),
        ("delpack", "Delete your own pack entirely"),
        ("lang", "Change language"),
        ("help", "Help"),
    ],
}

COMMANDS: dict[str, list[tuple[str, str]]] = {
    "fa": [
        ("quote", "کارت نقل‌قول از پیام ریپلای‌شده"),
        ("sticker", "همان کارت، به شکل استیکر"),
        ("gif", "همان کارت، به شکل گیف"),
        ("screenshot", "پیام به شکل اسکرین‌شات تلگرام"),
        ("pack", "استیکرپک این گروه"),
        ("unpack", "حذف یک استیکر از پک گروه (ادمین)"),
        ("delpack", "حذف کامل پک گروه (ادمین)"),
    ],
    "en": [
        ("quote", "A quote card from the replied-to message"),
        ("sticker", "The same card, as a sticker"),
        ("gif", "The same card, animated"),
        ("screenshot", "The message as a Telegram screenshot"),
        ("pack", "This group's sticker pack"),
        ("unpack", "Remove one sticker from the pack (admins)"),
        ("delpack", "Delete the group's pack entirely (admins)"),
    ],
}


# Shown on the empty chat before Start (max 512 chars), and on the bot's profile
# (max 120). Deliberately free of commands: this is a first impression, and the
# command list is one tap away in the menu once someone has started the bot.
DESCRIPTIONS: dict[str, str] = {
    "fa": """سلام! 👋
من از پیام‌ها عکسِ نقل‌قول می‌سازم.

هر پیامی را تبدیل می‌کنم به یک کارت، با متن پیام و اسم و عکس پروفایلِ گوینده‌اش. خروجی را به شکل عکس، استیکر یا گیف می‌گیری.

در گروه‌ها هم کار می‌کنم.

کانال خبرها: @getQuoto

برای شروع Start را بزن 👇""",
    "en": """Hi! 👋
I turn messages into quote cards.

Any message becomes a card carrying its text, the sender's name and their profile photo — as an image, a sticker or an animation.

I work in groups too.

News and updates: @getQuoto

Press Start to begin 👇""",
}

SHORT_DESCRIPTIONS: dict[str, str] = {
    "fa": """از پیام‌های تلگرام عکسِ نقل‌قول می‌سازم، با اسم و عکس پروفایلِ گوینده.
کانال: @getQuoto""",
    "en": """I turn Telegram messages into quote cards with the sender's name and photo.
Channel: @getQuoto""",
}


def normalize(code: str | None) -> str:
    """Map a Telegram language_code onto one of the languages we actually speak."""
    if not code:
        return DEFAULT
    return "en" if code.lower().startswith(_EN_PREFIX) else "fa"


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
