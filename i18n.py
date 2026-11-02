"""Bilingual (Persian/English) message catalog and per-user language resolution."""
from __future__ import annotations

import re

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
        "fa": """سلام! 👋 من <b>Quoto</b> هستم و از پیام‌های این گروه کارت نقل‌قول، استیکر و گیف می‌سازم.

روی هر پیامی <b>ریپلای</b> کنید و بنویسید:
«کوتش کن» • «استیکرش کن» • «گیفش کن» • «شاتش کن» • «آتیشش کن»

⚠️ <b>لطفاً منو ادمین کنید</b>؛ تا ادمین نشم، تلگرام ریپلای‌ها رو بهم نمی‌ده.
هر کسی که می‌خواد ازم استفاده کنه، باید یه بار تو پیوی استارتم کرده باشه.

بقیه‌ی قابلیت‌ها: /help""",
        "en": """Hi! 👋 I'm <b>Quoto</b>, and I turn this group's messages into quote cards, stickers and GIFs.

<b>Reply</b> to any message with /quote, /sticker, /gif, /screenshot or /fire.

⚠️ <b>Please make me an admin</b>; until then Telegram doesn't pass me replies.
Anyone who wants to use me has to have started me once in a private chat.

Everything else: /help""",
    },
    # /help is a short front page, and each of the rest a button away
    # (HELP_SECTIONS): everything in one message was more than anybody read.
    "help": {
        "fa": """📖 <b>راهنمای Quoto</b>

روی هر پیامی <b>ریپلای</b> کن و بنویس:
• «کوتش کن» — کارت نقل‌قول
• «استیکرش کن» — همون کارت، استیکر
• «گیفش کن» — گیفی که جمله رو تایپ می‌کنه
• «شاتش کن» — اسکرین‌شات تلگرامی
• «آتیشش کن» — جمله با آتیش روی کاغذ

دستورهاش: /quote /sticker /gif /screenshot /fire
بدون ریپلای: <code>/quote متن دلخواه</code>

بقیه‌ی کارها تو دکمه‌های پایینه 👇
کانال خبرها: @getQuoto""",
        "en": """📖 <b>Quoto help</b>

<b>Reply</b> to any message with:
• /quote — a quote card
• /sticker — the same card, as a sticker
• /gif — a GIF that types the words out
• /screenshot — a Telegram-style screenshot
• /fire — the words written in fire on paper

No reply: <code>/quote any text</code>

The rest is behind the buttons 👇
News: @getQuoto""",
    },
    "help_convert": {
        "fa": """🔄 <b>تبدیل</b>
روی عکس، ویدیو، گیف یا استیکر ریپلای کن و بنویس:
• «تبدیل به گیف» یا «تبدیل به استیکر» — از عکس و ویدیو
• «تبدیل به ویدیو» — از گیف و استیکر متحرک
• «تبدیل به عکس» — از استیکر

✂️ <b>فقط یه تیکه از ویدیو</b>
«تبدیل به گیف ۱:۲۰ تا ۱:۳۵»
«تبدیل به گیف از ۲:۰۵» — از همون لحظه
گیف تا ۳۰ ثانیه، استیکر تا ۳ ثانیه؛ ویدیو باید زیر ۲۰ مگابایت باشه.""",
        "en": """🔄 <b>Converting</b>
Reply to a photo, video, GIF or sticker with:
• /togif or /tosticker — from a photo or a video
• /tovideo — from a GIF or an animated sticker
• /tophoto — from a sticker

✂️ <b>Just part of a video</b>
<code>/togif 1:20 1:35</code>
<code>/togif 2:05</code> — from that moment on
Up to 30 seconds for a GIF, 3 for a sticker; the video has to be under 20 MB.""",
    },
    "help_words": {
        "fa": """✍️ <b>نوشتن متن</b>
<b>موقع ساختن</b> — متن تو یه نوار بالای کارت یا استیکر میاد:
«استیکرش کن، روش بنویس: سلام»
با «کوتش کن»، «گیفش کن»، «شاتش کن» و «آتیشش کن» هم می‌شه.

<b>روی گیف یا استیکر آماده</b> — متن پایینش نوشته می‌شه، مثل میم:
«روش بنویس: سلام»

تا ۱۲۰ حرف.""",
        "en": """✍️ <b>Adding words</b>
<b>While making it</b> — the words go in a band above the card or sticker:
<code>/sticker caption: hello</code>
The same with /quote, /gif, /screenshot and /fire.

<b>On a GIF or sticker that's already there</b> — along the bottom, meme style:
<code>/text hello</code>

Up to 120 characters.""",
    },
    "help_chats": {
        "fa": """👥 <b>گروه‌ها و چت‌های دیگه</b>
تو هر چتی، حتی پیوی دوستات یا گروهی که عضوش نیستم، روی پیام ریپلای کن و اسمم رو هم بنویس:
<code>@BOT استیکرش کن</code>
<code>@BOT تبدیل به گیف</code>
جواب رو خودم همون‌جا می‌فرستم.

<b>گروه خودت</b>
منو اضافه کن و ادمین کن؛ تا ادمین نباشم تلگرام ریپلای‌ها رو بهم نمی‌ده.""",
        "en": """👥 <b>Groups and other chats</b>
In any chat, even a friend's private chat or a group I'm not in, reply to a message and name me:
<code>@BOT /sticker</code>
<code>@BOT /togif</code>
I answer right there.

<b>Your own group</b>
Add me and make me an admin; until then Telegram doesn't pass me replies.""",
    },
    "help_packs": {
        "fa": """📦 <b>استیکرپک‌ها</b>
<b>پک گروه</b> — هر استیکری که تو گروه ساخته بشه، میره تو پک همون گروه.
• لینکش: /pack
• حذف یه استیکر: روش ریپلای کن و /unpack بزن (ادمین‌ها)
• حذف کل پک: /delpack (ادمین‌ها)

<b>پک‌های خودت</b>، تو پیوی من:
• پک شخصی: /mypack
• پک دلخواه: <code>/newpack اسم</code>، بعد روی هر استیکر بنویس «بذارش تو پک»
• همه‌ی پک‌هات: /packs""",
        "en": """📦 <b>Sticker packs</b>
<b>The group's pack</b> — every sticker made in a group joins that group's pack.
• Its link: /pack
• Remove one sticker: reply to it with /unpack (admins)
• Delete the whole pack: /delpack (admins)

<b>Your own packs</b>, in my private chat:
• Your personal pack: /mypack
• A pack of your choosing: <code>/newpack name</code>, then reply to any sticker with /addsticker
• All your packs: /packs""",
    },
    "help_more": {
        "fa": """🖼 <b>عکس و تنظیمات</b>
• عکس دلخواه روی کوت‌هات: عکس رو با کپشن /avatar بفرست
• کدوم عکست بیاد: /settings
• قالب کارت‌ها: /template
• گیف‌هایی که ساختی: /mygifs
• کوت از حرف بقیه: پیامشون رو اینجا فوروارد کن و روش ریپلای بزن
• زبان: /lang
• پاک کردن اطلاعاتت: /deletemydata

<b>عکس پروفایلت روی کارت نمیاد؟</b> تو تلگرام این رو روی Everybody بذار:
<code>Settings → Privacy and Security → Profile Photo</code>""",
        "en": """🖼 <b>Pictures and settings</b>
• Your own picture on your quotes: send it with /avatar as the caption
• Which picture stands for you: /settings
• The card design: /template
• The GIFs you've made: /mygifs
• Quoting someone else: forward their message here and reply to it
• Language: /lang
• Delete what the bot keeps about you: /deletemydata

<b>Profile photo missing from the card?</b> Set this to Everybody:
<code>Settings → Privacy and Security → Profile Photo</code>""",
    },
    "btn_help_convert": {"fa": "🔄 تبدیل", "en": "🔄 Converting"},
    "btn_help_words": {"fa": "✍️ نوشتن متن", "en": "✍️ Adding words"},
    "btn_help_chats": {"fa": "👥 گروه و چت‌ها", "en": "👥 Groups and chats"},
    "btn_help_packs": {"fa": "📦 استیکرپک‌ها", "en": "📦 Sticker packs"},
    "btn_help_more": {"fa": "🖼 عکس و تنظیمات", "en": "🖼 Pictures and settings"},
    "btn_help_back": {"fa": "« برگشت به راهنما", "en": "« Back to help"},
    # /help as a rich message (Bot API 10.1+, sendRichMessage): a table of the
    # five things the bot is for, and everything else in sections that open
    # when tapped. BOTNAME is the bot's username without the @. If Telegram
    # will not take it, the pages above ("help" and "help_*") go instead.
    "help_rich": {
        "fa": """<h3>📖 راهنمای Quoto</h3>
<p>روی هر پیامی <b>ریپلای</b> کن و بنویس:</p>
<table bordered striped compact>
<tr><th>بنویس</th><th>یا دستور</th><th>چی می‌سازه</th></tr>
<tr><td>«کوتش کن»</td><td>/quote</td><td>کارت نقل‌قول</td></tr>
<tr><td>«استیکرش کن»</td><td>/sticker</td><td>همون کارت، استیکر</td></tr>
<tr><td>«گیفش کن»</td><td>/gif</td><td>گیفی که جمله رو تایپ می‌کنه</td></tr>
<tr><td>«شاتش کن»</td><td>/screenshot</td><td>اسکرین‌شات تلگرامی</td></tr>
<tr><td>«آتیشش کن»</td><td>/fire</td><td>جمله با آتیش روی کاغذ</td></tr>
</table>
<p>بدون ریپلای: <code>/quote متن دلخواه</code></p>
<details><summary>🔄 تبدیل و برش ویدیو</summary>
<p>روی عکس، ویدیو، گیف یا استیکر ریپلای کن و بنویس:</p>
<ul>
<li>«تبدیل به گیف» یا «تبدیل به استیکر» — از عکس و ویدیو</li>
<li>«تبدیل به ویدیو» — از گیف و استیکر متحرک</li>
<li>«تبدیل به عکس» — از استیکر</li>
</ul>
<p><b>فقط یه تیکه از ویدیو:</b></p>
<ul>
<li>«تبدیل به گیف ۱:۲۰ تا ۱:۳۵»</li>
<li>«تبدیل به گیف از ۲:۰۵» — از همون لحظه</li>
</ul>
<p>گیف تا ۳۰ ثانیه، استیکر تا ۳ ثانیه؛ ویدیو باید زیر ۲۰ مگابایت باشه.</p>
</details>
<details><summary>✍️ نوشتن متن</summary>
<p><b>موقع ساختن</b>، تو نواری بالای کارت یا استیکر:</p>
<blockquote>«استیکرش کن، روش بنویس: سلام»</blockquote>
<p>با «کوتش کن»، «گیفش کن»، «شاتش کن» و «آتیشش کن» هم می‌شه.</p>
<p><b>روی گیف یا استیکر آماده</b>، پایینش، مثل میم:</p>
<blockquote>«روش بنویس: سلام»</blockquote>
<p>تا ۱۲۰ حرف.</p>
</details>
<details><summary>👥 گروه‌ها و چت‌های دیگه</summary>
<p>تو هر چتی، حتی پیوی دوستات یا گروهی که عضوش نیستم، روی پیام ریپلای کن و اسمم رو هم بنویس:</p>
<pre>@BOT استیکرش کن</pre>
<p>جواب رو خودم همون‌جا می‌فرستم.</p>
<p>تو گروه خودت منو <b>ادمین</b> کن؛ تا ادمین نباشم، تلگرام ریپلای‌ها رو بهم نمی‌ده.</p>
</details>
<details><summary>📦 استیکرپک‌ها</summary>
<p><b>پک گروه</b> — هر استیکری که تو گروه ساخته بشه، میره تو پک همون گروه:</p>
<ul>
<li>لینکش: /pack</li>
<li>حذف یه استیکر: روش ریپلای کن و /unpack بزن (ادمین‌ها)</li>
<li>حذف کل پک: /delpack (ادمین‌ها)</li>
</ul>
<p><b>پک‌های خودت</b>، تو پیوی من:</p>
<ul>
<li>پک شخصی: /mypack</li>
<li>پک دلخواه: <code>/newpack اسم</code>، بعد روی هر استیکر بنویس «بذارش تو پک»</li>
<li>همه‌ی پک‌هات: /packs</li>
</ul>
</details>
<details><summary>🖼 عکس و تنظیمات</summary>
<ul>
<li>عکس دلخواه روی کوت‌هات: عکس رو با کپشن /avatar بفرست</li>
<li>کدوم عکست بیاد: /settings</li>
<li>قالب کارت‌ها: /template</li>
<li>گیف‌هایی که ساختی: /mygifs</li>
<li>کوت از حرف بقیه: پیامشون رو اینجا فوروارد کن و روش ریپلای بزن</li>
<li>زبان: /lang</li>
<li>پاک کردن اطلاعاتت: /deletemydata</li>
</ul>
<p>عکس پروفایلت روی کارت نمیاد؟ تو تلگرام این رو روی Everybody بذار:</p>
<pre>Settings → Privacy and Security → Profile Photo</pre>
</details>
<hr/>
<tg-button-row>
<tg-button type="url" style="primary" url="https://t.me/BOTNAME?startgroup=true">➕ افزودن به گروه</tg-button>
<tg-button type="url" url="https://t.me/getQuoto">📢 کانال خبرها</tg-button>
</tg-button-row>""",
        "en": """<h3>📖 Quoto help</h3>
<p><b>Reply</b> to any message with:</p>
<table bordered striped compact>
<tr><th>Command</th><th>Makes</th></tr>
<tr><td>/quote</td><td>a quote card</td></tr>
<tr><td>/sticker</td><td>the same card, as a sticker</td></tr>
<tr><td>/gif</td><td>a GIF that types the words out</td></tr>
<tr><td>/screenshot</td><td>a Telegram-style screenshot</td></tr>
<tr><td>/fire</td><td>the words written in fire on paper</td></tr>
</table>
<p>No reply: <code>/quote any text</code></p>
<details><summary>🔄 Converting and cutting video</summary>
<p>Reply to a photo, video, GIF or sticker with:</p>
<ul>
<li>/togif or /tosticker — from a photo or a video</li>
<li>/tovideo — from a GIF or an animated sticker</li>
<li>/tophoto — from a sticker</li>
</ul>
<p><b>Just part of a video:</b> <code>/togif 1:20 1:35</code>, or <code>/togif 2:05</code> from that moment on.</p>
<p>Up to 30 seconds for a GIF, 3 for a sticker; the video has to be under 20 MB.</p>
</details>
<details><summary>✍️ Adding words</summary>
<p><b>While making it</b>, in a band above the card or sticker:</p>
<pre>/sticker caption: hello</pre>
<p>The same with /quote, /gif, /screenshot and /fire.</p>
<p><b>On a GIF or sticker that's already there</b>, along the bottom, meme style:</p>
<pre>/text hello</pre>
<p>Up to 120 characters.</p>
</details>
<details><summary>👥 Groups and other chats</summary>
<p>In any chat, even a friend's private chat or a group I'm not in, reply to a message and name me:</p>
<pre>@BOT /sticker</pre>
<p>I answer right there.</p>
<p>In your own group, make me an <b>admin</b>; until then Telegram doesn't pass me replies.</p>
</details>
<details><summary>📦 Sticker packs</summary>
<p><b>The group's pack</b> — every sticker made in a group joins it:</p>
<ul>
<li>Its link: /pack</li>
<li>Remove one sticker: reply to it with /unpack (admins)</li>
<li>Delete the whole pack: /delpack (admins)</li>
</ul>
<p><b>Your own packs</b>, in my private chat:</p>
<ul>
<li>Your personal pack: /mypack</li>
<li>A pack of your choosing: <code>/newpack name</code>, then reply to any sticker with /addsticker</li>
<li>All your packs: /packs</li>
</ul>
</details>
<details><summary>🖼 Pictures and settings</summary>
<ul>
<li>Your own picture on your quotes: send it with /avatar as the caption</li>
<li>Which picture stands for you: /settings</li>
<li>The card design: /template</li>
<li>The GIFs you've made: /mygifs</li>
<li>Quoting someone else: forward their message here and reply to it</li>
<li>Language: /lang</li>
<li>Delete what the bot keeps about you: /deletemydata</li>
</ul>
<p>Profile photo missing from the card? Set this to Everybody:</p>
<pre>Settings → Privacy and Security → Profile Photo</pre>
</details>
<hr/>
<tg-button-row>
<tg-button type="url" style="primary" url="https://t.me/BOTNAME?startgroup=true">➕ Add to a group</tg-button>
<tg-button type="url" url="https://t.me/getQuoto">📢 News channel</tg-button>
</tg-button-row>""",
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
    "mygifs_intro": {
        "fa": """🎞 تا حالا <b>{count}</b> گیف از <b>{people}</b> نفر ساخته‌ای. جدیدترین‌ها این‌ها هستند.

برای گیف‌های یک نفر بنویس <code>/mygifs اسم</code> — با یوزرنیم یا آیدی عددی هم پیدا می‌شود. از همین‌جا می‌توانی برای هر کسی فورواردشان کنی.""",
        "en": """🎞 You have made <b>{count}</b> GIFs of <b>{people}</b> people. Here are the newest.

For one person's, send <code>/mygifs name</code> — a username or numeric id works too. Forward them on to anyone from here.""",
    },
    "mygifs_none": {
        "fa": "هنوز گیفی نساخته‌ای. روی پیامی ریپلای کن و /gif بزن؛ از این به بعد هر گیفی که بسازی اینجا جمع می‌شود.",
        "en": "You haven't made any GIFs yet. Reply to a message with /gif; every GIF you make from now on is kept here.",
    },
    "btn_mygifs": {"fa": "🔍 گیف‌هایم", "en": "🔍 My GIFs"},
    "gallery_none": {"fa": "گیفی از «{term}» پیدا نشد", "en": "No GIFs of “{term}”"},
    "mygifs_found": {"fa": "🎞 <b>{count}</b> گیف از «{term}»:", "en": "🎞 <b>{count}</b> GIFs of “{term}”:"},
    "mygifs_more": {
        "fa": "و {rest} تای دیگر هم هست؛ برای دیدنشان اسم دقیق‌تری بنویس، مثلاً <code>/mygifs یوزرنیم</code>.",
        "en": "And {rest} more; narrow it down with a fuller name, e.g. <code>/mygifs username</code>.",
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

از این به بعد هر کوت و اسکرین‌شاتی که اینجا بسازی به همین اضافه می‌شود. با /mypack هر وقت خواستی لینکش را بگیر.

اگر استیکر تازه را در پک نمی‌بینی، روی خودِ استیکر بزن یا همین لینک را دوباره باز کن — تلگرام گاهی دیر به‌روزش می‌کند.""",
        "en": """Your own sticker pack is ready 🎉
{link}

Everything you make here joins it from now on. /mypack gives you the link whenever you want it.

Don't see a new sticker in the pack yet? Tap the sticker itself or open this link again - Telegram can be slow to refresh it.""",
    },
    "mypack_link": {
        "fa": """استیکرپک شخصی‌ات:
{link}

هر کوت یا اسکرین‌شاتی که در چت خصوصی من بسازی، خودکار به آن اضافه می‌شود.

اگر استیکر تازه را در پک نمی‌بینی، روی خودِ استیکر بزن یا همین لینک را دوباره باز کن — تلگرام گاهی دیر به‌روزش می‌کند.""",
        "en": """Your own sticker pack:
{link}

Everything you make in my private chat is added to it.

Don't see a new sticker in the pack yet? Tap the sticker itself or open this link again - Telegram can be slow to refresh it.""",
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
    "busy": {
        "fa": "الان سرم خیلی شلوغه 😅 یه دقیقه دیگه دوباره امتحان کن.",
        "en": "I'm swamped right now 😅 Try again in a minute.",
    },
    "inline_wait": {
        "fa": "چند ثانیه صبر کن و دوباره بنویس…",
        "en": "Give it a few seconds, then type again…",
    },
    "forget_ask": {
        "fa": """🗑 <b>پاک کردن اطلاعاتت</b>

این‌ها پاک می‌شوند:
• عکس دلخواه، انتخاب عکس و قالب و زبان
• آرشیو گیف‌هایی که ساخته‌ای
• اسم و یوزرنیمی که ربات از تو دیده

این‌ها می‌مانند: تعداد دفعاتی که عکس دلخواه گذاشته‌ای (برای سهمیه)، و استیکرپک‌هایت — اگر می‌خواهی آن‌ها هم بروند، <b>اول</b> با /delpack پاکشان کن؛ بعد از این کار دیگر نمی‌دانم کدام پک‌ها مال تو بوده‌اند.

این کار برگشت ندارد. مطمئنی؟""",
        "en": """🗑 <b>Delete your data</b>

This deletes:
• your own picture, and your picture, template and language choices
• the archive of GIFs you have made
• the name and username the bot has seen you under

This stays: how many times you have set a picture (for the allowance), and your sticker packs - to delete those too, use /delpack <b>first</b>; after this I no longer know which packs were yours.

This cannot be undone. Are you sure?""",
    },
    "forget_done": {
        "fa": "✅ پاک شد. اگر دوباره از ربات استفاده کنی، فقط چیزهایی که از آن به بعد لازم است نگه داشته می‌شود.",
        "en": "✅ Deleted. If you use the bot again, only what that needs is kept from then on.",
    },
    "forget_cancelled": {
        "fa": "باشه، چیزی پاک نشد.",
        "en": "OK, nothing was deleted.",
    },
    "btn_forget_yes": {"fa": "🗑 بله، پاک کن", "en": "🗑 Yes, delete"},
    "newpack_how": {
        "fa": "اسم پک را بعد از دستور بنویس، مثلاً:\n<code>/newpack میم‌های گروه</code>",
        "en": "Put the pack's name after the command, for example:\n<code>/newpack Group memes</code>",
    },
    "newpack_limit": {
        "fa": "هر نفر حداکثر {max} پک می‌تواند داشته باشد. با /delpack یکی را پاک کن.",
        "en": "Each person can have at most {max} packs. Delete one with /delpack.",
    },
    "newpack_done": {
        "fa": """✅ پک «{title}» آماده است.
حالا روی هر استیکری (یا عکس و ویدیو) ریپلای کن و بنویس «بذارش تو پک» تا به این پک اضافه شود. فقط همان‌هایی که خودت بفرستی داخلش می‌روند.""",
        "en": """✅ The pack “{title}” is ready.
Now reply to any sticker (or photo, or video) with /addsticker and it goes in. Only what you send there goes in.""",
    },
    "addpack_need_reply": {
        "fa": "روی یک استیکر، عکس یا ویدیو ریپلای کن و بنویس «بذارش تو پک».",
        "en": "Reply to a sticker, photo or video with /addsticker.",
    },
    "addpack_no_pack": {
        "fa": "اول با /newpack یک پک بساز، مثلاً: /newpack میم‌های گروه",
        "en": "Make a pack first with /newpack, e.g. /newpack Group memes",
    },
    "addpack_done": {"fa": "✅ به پک «{title}» اضافه شد.", "en": "✅ Added to “{title}”."},
    "addpack_created": {
        "fa": """✅ پک «{title}» ساخته شد و این اولین استیکرش است:
{link}

(ممکن است تا چند دقیقه طول بکشد تا تلگرام استیکرهای تازه را در پک نشان دهد.)""",
        "en": """✅ “{title}” is made, and this is its first sticker:
{link}

(Telegram can take a few minutes to show new stickers in a pack.)""",
    },
    "addpack_full": {
        "fa": "پک «{title}» پر است (۱۲۰ استیکر). با /newpack یک پک تازه بساز.",
        "en": "“{title}” is full (120 stickers). Make another with /newpack.",
    },
    "packs_list": {"fa": """📦 <b>پک‌های تو</b>
{rows}""", "en": """📦 <b>Your packs</b>
{rows}"""},
    "packs_personal": {"fa": "• <b>پک شخصی</b> (خودکار) — {link}", "en": "• <b>Personal pack</b> (automatic) — {link}"},
    "packs_empty": {"fa": "هنوز خالی", "en": "still empty"},
    "packs_none": {
        "fa": "\nبرای پکی که فقط استیکرهای انتخابی خودت داخلش باشد: <code>/newpack اسم</code>",
        "en": "\nFor a pack with only the stickers you choose: <code>/newpack name</code>",
    },
    "packs_target_set": {"fa": "از این به بعد استیکرها به «{title}» می‌روند.", "en": "Stickers now go to “{title}”."},
    "btn_auto_on": {"fa": "🔁 افزودن خودکار به پک شخصی: روشن", "en": "🔁 Auto-add to personal pack: on"},
    "btn_auto_off": {"fa": "🔁 افزودن خودکار به پک شخصی: خاموش", "en": "🔁 Auto-add to personal pack: off"},
    "auto_on": {
        "fa": "از این به بعد استیکرهایی که می‌سازی خودکار به پک شخصی‌ات اضافه می‌شوند.",
        "en": "Stickers you make now join your personal pack automatically.",
    },
    "auto_off": {
        "fa": "دیگر چیزی خودکار به پک شخصی‌ات اضافه نمی‌شود؛ فقط آن‌هایی که خودت با «بذارش تو پک» بفرستی.",
        "en": "Nothing joins your personal pack by itself now; only what you send with /addsticker.",
    },
    "btn_delpack_personal": {"fa": "🗑 پک شخصی", "en": "🗑 Personal pack"},
    "delpack_choose": {
        "fa": "کدام پک پاک شود؟ پاک کردن برگشت ندارد و پک از لیست استیکر همه حذف می‌شود.",
        "en": "Which pack should go? It cannot be undone, and the pack disappears for everyone.",
    },
    "convert_need_reply": {
        "fa": """روی یه عکس، ویدیو، گیف یا استیکر ریپلای کن و بنویس:
«تبدیل به گیف» • «تبدیل به استیکر» • «تبدیل به ویدیو» • «تبدیل به عکس»
فقط یه تیکه از ویدیو: «تبدیل به گیف ۱:۲۰ تا ۱:۳۵»""",
        "en": """Reply to a photo, video, GIF or sticker with:
/togif • /tosticker • /tovideo • /tophoto
Just part of a video: /togif 1:20 1:35""",
    },
    "convert_unsupported": {
        "fa": """این رو نمی‌شه به {target} تبدیل کرد.
عکس و ویدیو ← گیف یا استیکر
گیف و استیکر متحرک ← ویدیو
استیکر ← عکس""",
        "en": """That can't be made into {target}.
Photo or video → GIF or sticker
GIF or animated sticker → video
Sticker → photo""",
    },
    "convert_too_big": {
        "fa": "این فایل بیشتر از ۲۰ مگابایته؛ تلگرام اجازه نمی‌ده ربات فایل بزرگ‌تر از این رو دانلود کنه.",
        "en": "That file is over 20 MB, and Telegram doesn't let bots download anything bigger.",
    },
    "convert_span_order": {
        "fa": "آخر بازه باید بعد از اولش باشه؛ مثلاً «تبدیل به گیف ۱:۲۰ تا ۱:۳۵».",
        "en": "The end has to come after the start - for example /togif 1:20 1:35.",
    },
    "convert_span_long": {
        "fa": "این بازه برای {target} زیادیه؛ حداکثر {seconds} ثانیه می‌شه.",
        "en": "That's too long for {target}: {seconds} seconds at most.",
    },
    "convert_span_past": {
        "fa": "این ویدیو کلاً {length} طول داره؛ شروع بازه باید قبل از اون باشه.",
        "en": "That video is only {length} long; the start has to be before that.",
    },
    "convert_span_how": {
        "fa": """بازه رو این‌جوری بنویس:
/togif 1:20 1:35
یا روی ویدیو ریپلای کن: «تبدیل به گیف ۱:۲۰ تا ۱:۳۵»""",
        "en": """Give the part of the video like this:
/togif 1:20 1:35""",
    },
    "caption_how": {
        "fa": """روی یه گیف یا استیکر ریپلای کن و بنویس:
«روش بنویس: متن دلخواه»
یا /text متن دلخواه

موقع ساختن کوت هم می‌شه: «استیکرش کن، روش بنویس: …»""",
        "en": """Reply to a GIF or a sticker with:
/text your words

Or while making one: /sticker caption: your words""",
    },
    "caption_unsupported": {
        "fa": "متن رو فقط روی گیف و استیکر می‌تونم بنویسم.",
        "en": "I can only write on a GIF or a sticker.",
    },
    "caption_too_long": {
        "fa": "متن حداکثر {max} حرف می‌تونه باشه.",
        "en": "The words can be {max} characters at most.",
    },
    "convert_name_gif": {"fa": "گیف", "en": "a GIF"},
    "convert_name_sticker": {"fa": "استیکر", "en": "a sticker"},
    "convert_name_video": {"fa": "ویدیو", "en": "a video"},
    "convert_name_photo": {"fa": "عکس", "en": "a photo"},
    "guest_how": {
        "fa": """روی یه پیام ریپلای کن و بنویس:
@getquoto_bot کوتش کن — کارت کوت
@getquoto_bot استیکرش کن / گیفش کن / شاتش کن / آتیشش کن
@getquoto_bot استیکرش کن، روش بنویس: سلام — با متن بالاش
@getquoto_bot تبدیل به گیف / استیکر / ویدیو / عکس
@getquoto_bot تبدیل به گیف ۱:۲۰ تا ۱:۳۵ — فقط همون تیکه از ویدیو
@getquoto_bot روش بنویس: متن — روی گیف یا استیکر
@getquoto_bot بذارش تو پک

بدون ریپلای: @getquoto_bot /quote متن — از حرف خودت
لینک پک گروه: @getquoto_bot /pack

برای کارهای بیشتر، ربات رو تو پیوی استارت کن.""",
        "en": """Reply to a message with:
@getquoto_bot /quote — a quote card
@getquoto_bot /sticker, /gif, /screenshot, /fire
@getquoto_bot /sticker caption: hello — with words above it
@getquoto_bot /togif, /tosticker, /tovideo, /tophoto
@getquoto_bot /togif 1:20 1:35 — just that part of a video
@getquoto_bot /text your words — on a GIF or a sticker
@getquoto_bot /addsticker

No reply: @getquoto_bot /quote your text
The group's pack: @getquoto_bot /pack

For more, start the bot in a private chat.""",
    },
    # What a guest is told when they name the bot and ask for nothing it knows
    # (or for /help): only what works as a guest, as a rich message, and at
    # the end that the rest is in the bot itself. BOTNAME is the username
    # without the @. If Telegram will not take it, "guest_how" goes instead.
    "guest_how_rich": {
        "fa": """<h3>👋 سلام، Quoto هستم</h3>
<p>روی یه پیام ریپلای کن و بعد از اسمم بنویس:</p>
<table bordered striped compact>
<tr><th>بنویس</th><th>چی می‌سازه</th></tr>
<tr><td>«کوتش کن»</td><td>کارت نقل‌قول</td></tr>
<tr><td>«استیکرش کن»</td><td>همون کارت، استیکر</td></tr>
<tr><td>«گیفش کن»</td><td>گیفی که جمله رو تایپ می‌کنه</td></tr>
<tr><td>«شاتش کن»</td><td>اسکرین‌شات تلگرامی</td></tr>
<tr><td>«آتیشش کن»</td><td>جمله با آتیش روی کاغذ</td></tr>
</table>
<p>مثلاً:</p>
<pre>@BOT استیکرش کن</pre>
<details><summary>🔄 تبدیل</summary>
<ul>
<li>«تبدیل به گیف» یا «تبدیل به استیکر» — روی عکس یا ویدیو</li>
<li>«تبدیل به ویدیو» — روی گیف یا استیکر متحرک</li>
<li>«تبدیل به عکس» — روی استیکر</li>
<li>«تبدیل به گیف ۱:۲۰ تا ۱:۳۵» — فقط همون تیکه از ویدیو</li>
</ul>
</details>
<details><summary>✍️ نوشتن متن</summary>
<ul>
<li>«استیکرش کن، روش بنویس: سلام» — متن بالای کارت یا استیکر</li>
<li>«روش بنویس: سلام» — روی گیف یا استیکر آماده</li>
</ul>
</details>
<details><summary>➕ بقیه</summary>
<p>بدون ریپلای، از حرف خودت:</p>
<pre>@BOT /quote متن</pre>
<ul>
<li>«پک» — لینک استیکرپک همین گروه</li>
<li>«بذارش تو پک» — استیکر توی پکی که تو ربات ساختی</li>
</ul>
</details>
<hr/>
<p>عکس دلخواه روی کوت‌ها، قالب کارت‌ها، پک‌های خودت و گیف‌هایی که ساختی فقط تو خود ربات‌ان. <b>برای کارهای بیشتر، ربات رو استارت کن</b> 👇</p>
<tg-button-row>
<tg-button type="url" style="primary" url="https://t.me/BOTNAME?start=guest">🤖 شروع Quoto</tg-button>
</tg-button-row>""",
        "en": """<h3>👋 Hi, I'm Quoto</h3>
<p>Reply to a message and write my name with one of these:</p>
<table bordered striped compact>
<tr><th>Write</th><th>Makes</th></tr>
<tr><td>/quote</td><td>a quote card</td></tr>
<tr><td>/sticker</td><td>the same card, as a sticker</td></tr>
<tr><td>/gif</td><td>a GIF that types the words out</td></tr>
<tr><td>/screenshot</td><td>a Telegram-style screenshot</td></tr>
<tr><td>/fire</td><td>the words written in fire on paper</td></tr>
</table>
<p>For example:</p>
<pre>@BOT /sticker</pre>
<details><summary>🔄 Converting</summary>
<ul>
<li>/togif or /tosticker — on a photo or a video</li>
<li>/tovideo — on a GIF or an animated sticker</li>
<li>/tophoto — on a sticker</li>
<li>/togif 1:20 1:35 — just that part of a video</li>
</ul>
</details>
<details><summary>✍️ Adding words</summary>
<ul>
<li>/sticker caption: hello — words above the card or sticker</li>
<li>/text hello — on a GIF or sticker that's already there</li>
</ul>
</details>
<details><summary>➕ More</summary>
<p>No reply, your own words:</p>
<pre>@BOT /quote your text</pre>
<ul>
<li>/pack — this group's sticker pack</li>
<li>/addsticker — the sticker into a pack you made in the bot</li>
</ul>
</details>
<hr/>
<p>Your own picture on quotes, card designs, your own packs and the GIFs you've made are in the bot itself. <b>For more, start the bot</b> 👇</p>
<tg-button-row>
<tg-button type="url" style="primary" url="https://t.me/BOTNAME?start=guest">🤖 Start Quoto</tg-button>
</tg-button-row>""",
    },
    "inline_fire_title": {"fa": "🔥 آتیشش کن", "en": "🔥 Write it in fire"},
    "inline_fire_caption": {"fa": "🔥 داره با آتیش نوشته می‌شه…", "en": "🔥 Being written in fire…"},
    "btn_fire_wait": {"fa": "🔥 در حال نوشتن…", "en": "🔥 Writing…"},
    "fire_wait_alert": {"fa": "چند ثانیه صبر کن، داره می‌سوزه 🔥", "en": "A few seconds - it's burning 🔥"},
    "btn_fire_again": {"fa": "🔥 تو هم بساز", "en": "🔥 Make your own"},
    "inline_fire_hint": {"fa": "بعد از 🔥 متنت رو بنویس", "en": "Type your text after 🔥"},
    "inline_fire_long": {"fa": "متن زیادی بلنده؛ حداکثر {max} حرف 🔥", "en": "Too long: {max} characters at most 🔥"},
    "inline_fire_busy": {"fa": "الان سرم شلوغه، یه دقیقه دیگه 🔥", "en": "Busy right now, try in a minute 🔥"},
    "fire_one_at_a_time": {"fa": "اول بذار قبلی تموم شه 🔥", "en": "Let the last one finish first 🔥"},
    "fire_too_long": {
        "fa": "این متن برای آتیش زدن زیادی بلنده 🔥 روی کاغذ حداکثر {max} حرف جا می‌شه. برای متن بلند /gif رو امتحان کن.",
        "en": "That's too long to write in fire 🔥 The page holds {max} characters at most. Try /gif for longer text.",
    },
    "fire_busy": {
        "fa": "الان چند نفر جلوتر از تو توی صف آتیش‌ان 🔥 یه دقیقه دیگه دوباره امتحان کن.",
        "en": "A few people are ahead of you in the fire queue 🔥 Try again in a minute.",
    },
    "fire_unavailable": {
        "fa": "این قابلیت فعلاً در دسترس نیست.",
        "en": "This isn't available right now.",
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
{link}

اگر استیکر تازه را در پک نمی‌بینی، روی خودِ استیکر بزن یا همین لینک را دوباره باز کن — تلگرام گاهی دیر به‌روزش می‌کند.""",
        "en": """Made a sticker pack for this group 🎉
{link}

Don't see a new sticker in the pack yet? Tap the sticker itself or open this link again - Telegram can be slow to refresh it.""",
    },
    "pack_link": {
        "fa": """استیکرپک این گروه:
{link}

اگر استیکر تازه را در پک نمی‌بینی، روی خودِ استیکر بزن یا همین لینک را دوباره باز کن — تلگرام گاهی دیر به‌روزش می‌کند.""",
        "en": """This group's sticker pack:
{link}

Don't see a new sticker in the pack yet? Tap the sticker itself or open this link again - Telegram can be slow to refresh it.""",
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
# Commands that only mean something inside a group. They are published to
# groups and kept out of the private menu, where they can only answer "not
# here" - a menu entry that cannot work is worse than no entry.
GROUP_ONLY = ("pack",)

PRIVATE_ONLY: dict[str, list[tuple[str, str]]] = {
    "fa": [
        ("mypack", "استیکرپک شخصی خودت"),
        ("newpack", "ساختن پک جدید با استیکرهای انتخابی"),
        ("packs", "پک‌هایت و انتخاب پک مقصد"),
        ("unpack", "حذف یک استیکر از پک شخصی‌ات (روی استیکر ریپلای کن)"),
        ("avatar", "انتخاب عکس دلخواه برای کوت‌هایت"),
        ("settings", "انتخاب اینکه چه عکسی روی کوت‌هایت بنشیند"),
        ("template", "انتخاب قالب کوت‌ها"),
        ("mygifs", "گیف‌هایی که ساخته‌ای، با جستجوی اسم"),
        ("delpack", "حذف کامل پک شخصی‌ات"),
        ("deletemydata", "پاک کردن اطلاعاتی که ربات از تو دارد"),
        ("lang", "تغییر زبان"),
        ("help", "راهنما"),
    ],
    "en": [
        ("mypack", "Your own sticker pack"),
        ("newpack", "Make a new pack of stickers you choose"),
        ("packs", "Your packs, and which one stickers go to"),
        ("unpack", "Remove one sticker from your own pack (reply to it)"),
        ("avatar", "Pick your own picture for your quotes"),
        ("settings", "Choose which picture stands for you"),
        ("template", "Choose the template your quotes use"),
        ("mygifs", "The GIFs you have made, searchable by name"),
        ("delpack", "Delete your own pack entirely"),
        ("deletemydata", "Delete what the bot keeps about you"),
        ("lang", "Change language"),
        ("help", "Help"),
    ],
}

COMMANDS: dict[str, list[tuple[str, str]]] = {
    "fa": [
        ("quote", "کارت نقل‌قول از پیام ریپلای‌شده"),
        ("sticker", "همان کارت، به شکل استیکر"),
        ("gif", "همان کارت، به شکل گیف"),
        ("fire", "متن را با آتش روی کاغذ می‌نویسد"),
        ("screenshot", "پیام به شکل اسکرین‌شات تلگرام"),
        ("togif", "تبدیل ویدیو یا عکس به گیف؛ با زمان، فقط همان تکه"),
        ("text", "نوشتن متن روی گیف یا استیکر"),
        ("pack", "استیکرپک این گروه"),
        ("unpack", "حذف یک استیکر از پک گروه (ادمین)"),
        ("delpack", "حذف کامل پک گروه (ادمین)"),
    ],
    "en": [
        ("quote", "A quote card from the replied-to message"),
        ("sticker", "The same card, as a sticker"),
        ("gif", "The same card, animated"),
        ("fire", "The text, written in fire"),
        ("screenshot", "The message as a Telegram screenshot"),
        ("togif", "Video or photo into a GIF; add times for just a part"),
        ("text", "Write words on a GIF or a sticker"),
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
از پیام‌های تلگرام کارت نقل‌قول، استیکر، گیف، اسکرین‌شات و گیف آتیشی می‌سازم، با اسم و عکس گوینده.

روی هر پیامی ریپلای کن و بنویس «کوتش کن» یا «آتیشش کن». در گروه‌ها کار می‌کنم، و حتی در چت‌هایی که عضوشان نیستم: کافی است @getquoto_bot را صدا بزنی.

کانال خبرها: @getQuoto

برای شروع Start را بزن 👇""",
    "en": """Hi! 👋
I turn Telegram messages into quote cards, stickers, GIFs, screenshots and fire GIFs, with the sender's name and photo.

Reply to any message with /quote or /fire. I work in groups, and even in chats I'm not in: just mention @getquoto_bot.

News channel: @getQuoto

Tap Start to begin 👇""",
}

SHORT_DESCRIPTIONS: dict[str, str] = {
    "fa": """کارت نقل‌قول، استیکر و گیف از پیام‌های تلگرام، با اسم و عکس گوینده. کانال: @getQuoto""",
    "en": """Quote cards, stickers and GIFs from Telegram messages, with the sender's photo. @getQuoto""",
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


# The pages of /help behind its buttons, in the order the buttons go: each is
# STRINGS["help_" + name], with a button STRINGS["btn_help_" + name].
HELP_SECTIONS = ("convert", "words", "chats", "packs", "more")

# A command or a username in a line of Persian. The slash and the @ are
# neutral, so a right-to-left line carries them to the far side of the word:
# "/quote" showed as "quote/" and "@getQuoto" as "getQuoto@". A left-to-right
# mark in front holds each to its word. It is not part of a word, so Telegram
# still finds the command and the mention and makes them tappable.
LRM = chr(0x200E)
_LTR_TOKEN = re.compile(r"(?<![\w/<@" + LRM + r"])(?=[/@][A-Za-z])")


def rtl_safe(text: str) -> str:
    """Persian text with every /command and @username held the right way round."""
    return _LTR_TOKEN.sub(LRM, text)


def t(key: str, lang: str) -> str:
    entry = STRINGS[key]
    text = entry.get(lang) or entry[DEFAULT]
    return rtl_safe(text) if lang == "fa" else text


def whole_help(lang: str) -> str:
    """Every page of /help, one after another, and the rich one: what the checks read."""
    return chr(10).join(t(key, lang) for key in
                        ("help", *(f"help_{name}" for name in HELP_SECTIONS), "help_rich"))
