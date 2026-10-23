"""Exercise everything that can be checked without a live bot.

Run after any change:  python selftest.py
Add --api to also create and delete a throwaway sticker pack on Telegram.
"""
from __future__ import annotations

import asyncio
import html.parser
import io
import re
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw
from telegram.ext import ApplicationHandlerStop

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import admin  # noqa: E402
import animate  # noqa: E402
import authors  # noqa: E402
import bot  # noqa: E402
import extract  # noqa: E402
import fonts  # noqa: E402
import i18n  # noqa: E402
import inline  # noqa: E402
import reactions  # noqa: E402
import render  # noqa: E402
import screenshot  # noqa: E402
import stickerpack  # noqa: E402
import textkit  # noqa: E402

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    mark = "ok  " if ok else "FAIL"
    print(f"  [{mark}] {name}{(' — ' + detail) if detail and not ok else ''}")


def section(title: str) -> None:
    print(f"\n{title}")


# --------------------------------------------------------------------------- text
def test_text() -> None:
    section("text handling")
    # A display name written in a decorative alphabet is how that person writes
    # their name, so it is kept whenever a font here has the glyphs, and folded
    # back to plain letters only when nothing can draw it.
    script = "\U0001D4D9\U0001D4FE\U0001D4FC\U0001D4FD"
    if fonts.can_draw(script[0]):
        check("fancy letters kept", textkit.normalize_display(script) == script)
    else:
        check("fancy letters folded when nothing draws them",
              textkit.normalize_display(script) == "Just")
    small = "ᴊᴜsᴛ"
    if fonts.can_draw(small[0]):
        check("small caps kept", textkit.normalize_display(small) == small)
    else:
        check("small caps folded", textkit.normalize_display(small) == "just")
    wide = "ＪＵＳＴ"
    check("fullwidth kept or folded to letters",
          textkit.normalize_display(wide) in (wide, "JUST"))
    # Nothing draws an unassigned plane-16 character, and it has no plain form.
    check("what nothing can draw is dropped",
          textkit.normalize_display("a\U0010FFFDb") == "ab")
    check("emoji stripped", textkit.normalize_display("سلام 🌹 دنیا") == "سلام دنیا")
    check("emoji gap closed", "  " not in textkit.normalize_display("a 🌹 b"))
    check("emoji-only becomes empty", textkit.normalize_display("😂😂😂") == "")
    zwnj = textkit.normalize_display("می‌روم")
    check("Persian half-space kept", "‌" in zwnj, repr(zwnj))

    check("rtl detected", textkit.is_rtl("سلام دنیا"))
    check("ltr detected", not textkit.is_rtl("hello world"))

    # Quotation marks must open on the right of a Persian line and close on the left.
    line = textkit.shape('"تست"', True)
    check("persian quote opens right", line[-1] == '"' and line[0] == '"', repr(line))
    emoji_free_line = textkit.shape("سلام", True)
    check("forced direction shapes", emoji_free_line != "سلام")


# --------------------------------------------------------------------------- i18n
def test_i18n() -> None:
    section("i18n")
    gaps = [(k, l) for k, v in i18n.STRINGS.items() for l in ("fa", "en") if l not in v]
    check("every string in both languages", not gaps, str(gaps))

    # A key that is asked for but never written raises KeyError at the moment
    # somebody uses the feature, in the middle of a handler, and they are told
    # the render failed when it did not. mypack_created shipped that way.
    asked = set()
    for module in ("bot.py", "inline.py", "admin.py"):
        source = (ROOT / module).read_text(encoding="utf-8")
        asked |= set(re.findall(r'_t\(\s*"([a-z0-9_]+)"', source))
        asked |= set(re.findall(r'i18n\.t\(\s*"([a-z0-9_]+)"', source))
        # Not every key is written at the call. Some are chosen first and
        # handed over in a variable, and mypack_created - the one that got
        # through - was exactly that, so scanning only the calls would have
        # missed it.
        asked |= set(re.findall(r'_key = "([a-z0-9_]+)"', source))
        for block in re.findall(r"_t\(\{(.*?)\}", source, re.DOTALL):
            asked |= set(re.findall(r':\s*"([a-z0-9_]+)"', block))
        # ... and the fallback of a lookup that picks one.
        asked |= set(re.findall(r'\.get\([^,()]+,\s*"([a-z0-9_]+)"\)', source))
    missing = sorted(k for k in asked if k not in i18n.STRINGS)
    check("every string the code asks for exists", not missing, str(missing))
    check("the scan reaches a key handed over in a variable",
          "mypack_created" in asked)
    check("and one chosen by a lookup", "mypack_removed" in asked
          and "unpack_failed" in asked)
    check("the scan found the strings to check", len(asked) >= 40, str(len(asked)))

    allowed = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "span",
               "tg-spoiler", "a", "code", "pre", "blockquote"}

    class Tags(html.parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.bad = [], []

        def handle_starttag(self, tag, attrs):
            if tag not in allowed:
                self.bad.append(tag)
            self.stack.append(tag)

        def handle_endtag(self, tag):
            if self.stack and self.stack[-1] == tag:
                self.stack.pop()
            else:
                self.bad.append("mismatch " + tag)

    for key in ("welcome", "help", "group_intro"):
        for lang in ("fa", "en"):
            text = i18n.t(key, lang).replace("@BOT", "@getquoto_bot")
            parser = Tags()
            parser.feed(text)
            check(f"{key}/{lang} html", not (parser.bad or parser.stack),
                  str(parser.bad or parser.stack))
            check(f"{key}/{lang} length", len(text) <= 4096, str(len(text)))

    for lang in ("fa", "en"):
        desc = i18n.DESCRIPTIONS[lang]
        short = i18n.SHORT_DESCRIPTIONS[lang]
        check(f"description/{lang} <= 512", len(desc) <= 512, str(len(desc)))
        check(f"about/{lang} <= 120", len(short) <= 120, str(len(short)))

    check("default language is Persian", i18n.DEFAULT == "fa")
    check("german gets Persian", i18n.normalize("de") == "fa")
    check("english gets English", i18n.normalize("en-US") == "en")

    # No guide may advertise a command that is not registered.
    registered = set(re.findall(r'CommandHandler\(\s*\[?([^)\]]*)',
                                (ROOT / "bot.py").read_text(encoding="utf-8")))
    names = set(re.findall(r'"([a-z]+)"', " ".join(registered)))
    advertised = set()
    for key in ("help", "group_intro", "welcome"):
        for lang in ("fa", "en"):
            # (?<!<) so a closing tag like </b> is not read as a command
            advertised |= set(re.findall(r"(?<!<)/([a-z]+)", i18n.t(key, lang)))
    unknown = {c for c in advertised - names if c not in {"setprivacy", "setuserpic"}}
    check("guides only mention real commands", not unknown, str(unknown))

    menu = {n for n, _ in i18n.COMMANDS["fa"]} | {n for n, _ in i18n.PRIVATE_ONLY["fa"]}
    check("menu commands are registered", menu <= names, str(menu - names))


# --------------------------------------------------------------------------- render
def _avatar() -> Image.Image:
    img = Image.new("RGB", (400, 400))
    draw = ImageDraw.Draw(img)
    for y in range(400):
        draw.line([(0, y), (400, y)], fill=(40 + y // 4, 90, 160 - y // 6))
    return img


def test_command_menus() -> None:
    section("command menus")

    for lang in ("fa", "en"):
        group = [n for n, _ in i18n.COMMANDS[lang]]
        private_only = {n for n, _ in i18n.PRIVATE_ONLY[lang]}
        # The same rule post_init publishes with.
        private = [n for n in group
                   if n not in private_only and n not in i18n.GROUP_ONLY]
        private += [n for n, _ in i18n.PRIVATE_ONLY[lang]]

        check(f"{lang}: no command is listed twice in private",
              len(private) == len(set(private)),
              str([n for n in private if private.count(n) > 1]))
        check(f"{lang}: a group-only command is not offered in private",
              all(n not in private for n in i18n.GROUP_ONLY))
        check(f"{lang}: /pack is still offered in a group", "pack" in group)
        # /unpack and /delpack exist in both, and the private menu has to carry
        # the private wording - in a private chat they mean your own pack.
        for name in ("unpack", "delpack"):
            said = dict(i18n.PRIVATE_ONLY[lang]).get(name, "")
            check(f"{lang}: /{name} in private is described as your own",
                  bool(said) and "گروه" not in said and "group" not in said, said)

    registered = (ROOT / "bot.py").read_text(encoding="utf-8")
    for name, _ in i18n.COMMANDS["fa"] + i18n.PRIVATE_ONLY["fa"]:
        check(f"/{name} in the menu is a command that exists",
              f'"{name}"' in registered, name)


def test_render() -> None:
    section("rendering")
    avatar = _avatar()
    short = render.build_scene(avatar, "سلام دنیا", "علی", "@bot")
    long_fa = render.build_scene(avatar, "طولانی " * 90, "علی", "@bot")
    latin = render.build_scene(avatar, "hello there, this is a quote", "Sam", "@bot")

    check("card size", short.render().size == (render.WIDTH, render.HEIGHT))
    check("short text gets a large font", short.quote_font.size >= 50,
          str(short.quote_font.size))
    check("long text stays readable", long_fa.quote_font.size >= 30,
          str(long_fa.quote_font.size))
    check("long text is trimmed, not clipped", long_fa.lines[-1].endswith("…"))
    check("persian uses straight quotes", short.lines[0].startswith('"'))
    check("latin uses curly quotes", latin.lines[0].startswith("“"))
    check("rtl flag set", short.rtl and not latin.rtl)

    png = render.to_png(short.render()).getvalue()
    check("png produced", png.startswith(b"\x89PNG") and len(png) > 1000)

    webp = render.to_sticker_webp(short.render()).getvalue()
    check("sticker under 512 KB", len(webp) <= 512 * 1024, f"{len(webp)//1024} KB")
    sticker = Image.open(io.BytesIO(webp))
    check("sticker longest side 512", max(sticker.size) == 512, str(sticker.size))

    fallback = render.fallback_avatar("42", "ع")
    check("fallback avatar drawn", fallback.size == (640, 640))

    shot = screenshot.render(avatar, "SAli", "سلام خوبی؟", "11:12 AM", "مالک", "555")
    check("screenshot produced", shot.width > 100 and shot.height > 100)
    shot_en = screenshot.render(avatar, "Sam", "hello there", "3:47 PM", None, "1")
    check("screenshot latin produced", shot_en.width > 100)


def test_templates() -> None:
    section("templates")
    avatar = _avatar()

    check("the default is the card the bot has always drawn",
          render.DEFAULT_TEMPLATE == "classic")
    check("every template offered is one that exists",
          all(n in render.TEMPLATES for n in render.TEMPLATE_ORDER))
    check("every template has a name to show",
          all(f"tpl_{n}" in i18n.STRINGS for n in render.TEMPLATE_ORDER))
    check("the picture of the three is there",
          bot.TEMPLATE_SHEET.exists(), str(bot.TEMPLATE_SHEET))

    for name in render.TEMPLATE_ORDER:
        for label, quote, who in [("persian", "سلام دنیا", "علی"),
                                  ("latin", "hello there, a quote", "Sam"),
                                  ("long", "طولانی " * 60, "علی")]:
            scene = render.build_scene(avatar, quote, who, "@bot", name)
            img = scene.render()
            check(f"{name} draws a {label} quote",
                  img.size == (render.WIDTH, render.HEIGHT))
            # Everything is centred on a block whose height depends on the
            # quote, so a long one is where a layout runs off the card.
            check(f"{name} keeps the {label} name on the card",
                  0 < scene.name_y < render.HEIGHT - 40, str(scene.name_y))
            # Two of them hang a round portrait above the words; that headroom
            # is the part a long quote pushes off the top edge.
            head = {"portrait": 194, "card": 150}.get(name, 0)
            check(f"{name} keeps the {label} quote on the card",
                  scene.quote_top - head >= 0, str(scene.quote_top))

    # Half the photos in the world are a person against a white wall, and the
    # other half are taken at night. Neither may produce a frame that swallows
    # the card or one that is just the black template again.
    for label, colour in [("white", (252, 252, 252)), ("black", (3, 3, 4)),
                          ("grey", (128, 128, 128))]:
        r, g, b = render._dominant(Image.new("RGB", (80, 80), colour))
        light = (max(r, g, b) + min(r, g, b)) / 510
        check(f"a {label} picture still gives a usable frame",
              0.30 <= light <= 0.64, f"{light:.2f}")

    # The tinted side carries the same near-white type the black one does, so
    # whatever the photo is, it has to stay dark enough to read off.
    for label, colour in [("white", (252, 252, 252)), ("yellow", (250, 220, 40)),
                          ("black", (3, 3, 4))]:
        side = render.render_quote(
            Image.new("RGB", (80, 80), colour), "x", "y", "", "tinted"
        ).getpixel((render.WIDTH - 40, 40))
        lum = 0.2126 * side[0] + 0.7152 * side[1] + 0.0722 * side[2]
        check(f"the tinted side stays dark for a {label} picture", lum < 90,
              f"{lum:.0f}")

    # The sheet is cached by file_id, and a new template means a new sheet.
    class SheetMessage:
        def __init__(self) -> None:
            self.sent = []

        async def reply_photo(self, what, caption=None, reply_markup=None):
            self.sent.append(what)
            return types.SimpleNamespace(
                photo=[types.SimpleNamespace(file_id="SHEET1")])

    async def sheets():
        msg = SheetMessage()
        ctx = types.SimpleNamespace(bot_data={}, user_data={})
        await bot._send_templates(msg, ctx, "fa")
        check("the sheet is uploaded the first time",
              not isinstance(msg.sent[-1], str))
        await bot._send_templates(msg, ctx, "fa")
        check("and sent by file_id after that", msg.sent[-1] == "SHEET1")

        # A regenerated sheet is a different file; the old file_id must go.
        stamped = ctx.bot_data["template_sheet"]["stamp"]
        ctx.bot_data["template_sheet"]["stamp"] = stamped + "-old"
        await bot._send_templates(msg, ctx, "fa")
        check("a changed sheet is uploaded again, not served from the old id",
              not isinstance(msg.sent[-1], str))

    asyncio.run(sheets())

    # The handle is the only thing on a card that says where it came from, so
    # every template has to keep it readable against its own corner - which is
    # black on one, a dark tint on another and a mid-tone frame on the third.
    def luminance(c):
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    for name in render.TEMPLATE_ORDER:
        scene = render.build_scene(avatar, "سلام", "علی", "@getquoto_bot", name)
        corner = scene.background.convert("RGB").getpixel(
            (render.WIDTH - 60, render.HEIGHT - 28))
        gap = abs(luminance(scene.mark_color) - luminance(corner))
        check(f"{name} keeps the handle readable in its corner", gap > 55,
              f"{gap:.0f}")
        check(f"{name} draws the handle at a size a phone can read",
              scene.watermark_font.size >= 24, str(scene.watermark_font.size))

    unknown = render.build_scene(avatar, "x", "y", "@bot", "no-such-template")
    check("an unknown template falls back rather than raising",
          unknown.center_x == render.build_scene(avatar, "x", "y", "@bot").center_x)

    same = inline.cache_key(7, "A", "classic", "hi")
    check("the same query is the same picture",
          inline.cache_key(7, "A", "classic", "hi") == same)
    check("a different template is a different picture",
          inline.cache_key(7, "A", "card", "hi") != same)
    check("a different avatar is a different picture",
          inline.cache_key(7, "B", "classic", "hi") != same)
    check("somebody else is a different picture",
          inline.cache_key(8, "A", "classic", "hi") != same)

    ctx = types.SimpleNamespace(user_data={})
    check("nothing chosen means the default", bot._template(ctx) == "classic")
    ctx.user_data["template"] = "card"
    check("a choice is honoured", bot._template(ctx) == "card")
    ctx.user_data["template"] = "; drop table"
    check("a made-up choice is ignored", bot._template(ctx) == "classic")


def test_animation() -> None:
    section("animation")
    scene = render.build_scene(_avatar(), "یک جمله‌ی نمونه برای تست", "علی", "@bot")
    lead, typing, fade, hold = animate._timeline(scene)
    total = (lead + typing + fade + hold) / animate.FPS
    check("timeline within bounds", 2 < total < 15, f"{total:.1f}s")
    mp4 = animate.to_mp4(scene)
    check("mp4 rendered", mp4 is not None and len(mp4.getvalue()) > 2000,
          "ffmpeg missing" if mp4 is None else "")
    buf, ext = animate.to_animation(scene)
    check("animation has a format", ext in ("mp4", "gif") and len(buf.getvalue()) > 2000)


# --------------------------------------------------------------------------- avatars
def test_avatars() -> None:
    section("avatar sources")
    pictures = {}
    for name, colour in (("profile", (60, 60, 200)), ("public", (200, 60, 60)),
                         ("custom", (60, 200, 60))):
        buf = io.BytesIO()
        Image.new("RGB", (200, 200), colour).save(buf, "PNG")
        pictures[name] = buf.getvalue()

    class FakeFile:
        def __init__(self, data):
            self.data = data

        async def download_as_bytearray(self):
            return bytearray(self.data)

    class FakeBot:
        async def get_file(self, file_id):
            if file_id == "CUSTOM":
                return FakeFile(pictures["custom"])
            if file_id == "pub":
                return FakeFile(pictures["public"])
            return FakeFile(pictures["profile"])

        async def get_user_profile_photos(self, user_id, limit=1):
            return types.SimpleNamespace(
                total_count=1, photos=[[types.SimpleNamespace(file_id="big")]])

        async def get_chat(self, chat_id):
            return types.SimpleNamespace(
                photo=types.SimpleNamespace(big_file_id="pub"))

    async def run():
        author = authors.Author("SAli", "sali", 555, "user", "555")
        seen = {}
        for source in authors.SOURCES:
            authors._avatar_cache.clear()
            image = await authors.fetch_avatar(FakeBot(), author, "CUSTOM", source)
            seen[source] = image.convert("RGB").getpixel((3, 3))
        check("custom honoured", seen["custom"] == (60, 200, 60), str(seen["custom"]))
        check("profile honoured", seen["profile"] == (60, 60, 200), str(seen["profile"]))
        check("public honoured", seen["public"] == (200, 60, 60), str(seen["public"]))
        check("letter honoured", seen["letter"] not in
              ((60, 200, 60), (60, 60, 200), (200, 60, 60)), str(seen["letter"]))

        # A public-only answer must not be served to a profile request.
        authors._avatar_cache.clear()
        await authors.fetch_avatar(FakeBot(), author, None, "public")
        again = await authors.fetch_avatar(FakeBot(), author, None, "profile")
        check("cache keyed by source",
              again.convert("RGB").getpixel((3, 3)) == (60, 60, 200))

    asyncio.run(run())


# --------------------------------------------------------------------------- bot logic
def test_bot_logic() -> None:
    section("bot logic")

    def ctx(store=None):
        return types.SimpleNamespace(bot_data=store if store is not None else {},
                                     user_data={}, args=[])

    author = authors.Author("SAli", "sali", 555, "user", "555")
    store = {"avatars": {555: "FILE"}, "avatar_source": {555: "letter"}}
    check("stored source wins", bot._avatar_choice(ctx(store), author) == ("FILE", "letter"))
    check("upload implies custom",
          bot._avatar_choice(ctx({"avatars": {555: "F"}}), author) == ("F", "custom"))
    check("no picture means profile",
          bot._avatar_choice(ctx({}), author) == (None, authors.DEFAULT_SOURCE))
    check("custom without a file falls back",
          bot._avatar_choice(ctx({"avatar_source": {555: "custom"}}), author)[1]
          == authors.DEFAULT_SOURCE)
    channel = authors.Author("کانال", "", -100, "chat", "-100")
    check("channels have no choice",
          bot._avatar_choice(ctx(store), channel) == (None, authors.DEFAULT_SOURCE))

    # Plain-Persian triggers: the bot's own patterns, not a copy of them.
    def fires(text):
        return {n for n, p in bot.TRIGGERS.items() if p.search(text)}
    check("«کوتش کن» fires quote", fires("کوتش کن") == {"quote"})
    check("«استیکرش کن» fires sticker", fires("استیکرش کن") == {"sticker"})
    check("«گیفش کن» fires gif", fires("گیفش کن") == {"gif"})
    check("«شاتش کن» fires shot", fires("شاتش کن") == {"shot"})
    for said in ("آتیشش کن", "اینو آتیشش کن لطفا", "اتیشش کن!", "آتیش بزن", "آتشش کن"):
        check(f"«{said}» fires fire", fires(said) == {"fire"})
    for said in ("اینو استیکرش کن لطفا!", "کوت", "quote please", "اینو اسکرین شاتش کنید لطفاً!",
                 "  گیفش کن  ", "کوتش کن ؟"):
        check(f"«{said.strip()}» still fires", len(fires(said)) == 1, str(fires(said)))
    check("talk about fire does not fire", fires("آتیش گرفت") == set())
    check("bare noun does not fire", fires("استیکر") == set())
    check("chat does not fire", fires("یه استیکر خوب بفرست") == set())
    longest = max(("اینو اسکرین شاتش کنید لطفاً!", "اینو نقل قولش کنید please!"), key=len)
    check("every phrase is under the length cap",
          len(longest) <= bot.TRIGGER_MAX_CHARS, str(len(longest)))

    # A reply of "quote", thousands of spaces and an "x" used to take re a
    # minute per pattern, on the event loop. Telegram allows 4096 characters.
    for padding in (" ", "\n", " "):
        attack = "quote" + padding * 4090 + "x"
        started = time.perf_counter()
        for pattern in bot.TRIGGERS.values():
            pattern.search(attack)
        took = time.perf_counter() - started
        check(f"no backtracking blow-up on {padding!r}", took < 0.05, f"{took:.3f}s")
    check("long messages never reach the patterns",
          not bot._ShortText().filter(types.SimpleNamespace(text="کوتش کن" + " " * 60)))
    check("short ones do", bot._ShortText().filter(types.SimpleNamespace(text="کوتش کن")))

    # Inline query cleaning
    for raw, expect_hint in (("/quote", True), ("/qoute", True), ("سلام", False)):
        stripped = inline.LEADING_COMMAND_RE.sub("", raw).strip()
        hint = not stripped or bool(inline.COMMAND_ONLY_RE.match(stripped))
        check(f"inline {raw!r}", hint == expect_hint)
    check("inline strips the command",
          inline.LEADING_COMMAND_RE.sub("", "/quote سلام").strip() == "سلام")

    # Stale updates
    async def stale(minutes, has_message=True, cutoff=0):
        message = None
        if has_message:
            message = types.SimpleNamespace(
                date=datetime.now(timezone.utc) - timedelta(minutes=minutes),
                chat_id=-1)
        try:
            await bot.ignore_stale(
                types.SimpleNamespace(message=message),
                types.SimpleNamespace(bot_data={"queue_cutoff": cutoff}))
            return True
        except Exception:
            return False

    check("fresh message passes", asyncio.run(stale(1)))
    check("old message stopped", not asyncio.run(stale(30)))
    check("button press unaffected", asyncio.run(stale(999, has_message=False)))
    # A queue the owner emptied: sent before the cutoff, so it never runs.
    check("flushed message stopped",
          not asyncio.run(stale(1, cutoff=time.time())))
    check("message after the flush passes",
          asyncio.run(stale(0, cutoff=time.time() - 600)))

    # Clock
    when = datetime(2026, 9, 15, 7, 42, tzinfo=timezone.utc)
    check("clock formatted", re.fullmatch(r"\d{1,2}:\d{2} [AP]M", bot._clock(when)),
          bot._clock(when))


def test_quota() -> None:
    section("avatar quota")

    class Msg:
        def __init__(self, photo=None):
            self.chat = types.SimpleNamespace(type="private")
            self.photo = photo or []
            self.document = None
            self.reply_to_message = None
            self.out = []
            self.markup = None

        async def reply_text(self, text, reply_markup=None, **kwargs):
            self.out.append(text)
            self.markup = reply_markup

        async def reply_html(self, text, reply_markup=None, **kwargs):
            self.out.append(text)
            self.markup = reply_markup or self.markup

    def photo(file_id):
        return [types.SimpleNamespace(file_id=file_id)]

    async def run():
        store = {}
        results = []
        for i in range(3):
            message = Msg(photo=photo(f"P{i}"))
            update = types.SimpleNamespace(
                effective_message=message,
                effective_user=types.SimpleNamespace(id=7, language_code="fa"))
            await bot.cmd_avatar(update, types.SimpleNamespace(
                bot_data=store, user_data={}, args=[]))
            results.append(message.out[0])
        check("first save counts one", "1" in results[0] and "2" in results[0])
        check("second save is the last", "قادر" in results[1] or "cannot" in results[1])
        check("third save refused", "تمام" in results[2] or "used up" in results[2])
        check("only two recorded", store["avatar_uses"][7] == bot.AVATAR_QUOTA)
        check("second picture kept", store["avatars"][7] == "P1")

        # Clearing does not refund
        message = Msg()
        update = types.SimpleNamespace(
            effective_message=message,
            effective_user=types.SimpleNamespace(id=7, language_code="fa"))
        await bot.cmd_avatar(update, types.SimpleNamespace(
            bot_data=store, user_data={}, args=["off"]))
        check("cleared", 7 not in store["avatars"])
        check("quota not refunded", store["avatar_uses"][7] == bot.AVATAR_QUOTA)

    asyncio.run(run())

    # The same thing from the settings screen, where there is a button for it.
    class Query:
        def __init__(self):
            self.text = None

        async def answer(self, *a, **k):
            pass

        async def edit_message_text(self, text, **kwargs):
            self.text = text

    async def deleting():
        store = {"avatars": {7: "P1"}, "avatar_uses": {7: 2},
                 "avatar_source": {7: "custom"}}
        ctx = types.SimpleNamespace(bot_data=store, user_data={}, args=[])

        message = Msg()
        update = types.SimpleNamespace(
            effective_message=message,
            effective_user=types.SimpleNamespace(id=7, language_code="fa"))
        await bot.cmd_settings(update, ctx)
        buttons = [b.callback_data for row in message.markup.inline_keyboard for b in row]
        check("settings offers a delete button", "avatar:delete" in buttons)

        query = Query()
        update = types.SimpleNamespace(
            callback_query=query, effective_message=message,
            effective_user=types.SimpleNamespace(id=7, language_code="fa"))
        await bot.on_avatar_delete(update, ctx)
        check("the button deletes the picture", 7 not in store["avatars"])
        check("the source goes back to the default",
              store["avatar_source"][7] == authors.DEFAULT_SOURCE)
        check("deleting refunds nothing", store["avatar_uses"][7] == 2)
        check("and it says so", "پاک شد" in query.text)

        # Pressing it twice must not pretend to delete something again.
        query = Query()
        await bot.on_avatar_delete(update, ctx)
        message2 = Msg()
        update2 = types.SimpleNamespace(
            effective_message=message2,
            effective_user=types.SimpleNamespace(id=7, language_code="fa"))
        await bot.cmd_settings(update2, ctx)
        buttons = [b.callback_data for row in message2.markup.inline_keyboard for b in row]
        check("with nothing to delete the button is gone", "avatar:delete" not in buttons)

    asyncio.run(deleting())


def test_inline_results() -> None:
    section("inline results")

    three = inline.build_results("fa", "PH", "ST", "AN")
    check("three things are offered", len(three) == 3, str(len(three)))
    check("the photo comes first", three[0].photo_file_id == "PH")
    check("then the sticker", three[1].sticker_file_id == "ST")
    check("then the animation", three[2].mpeg4_file_id == "AN")
    check("the animation is labelled", bool(three[2].title))
    check("every result has its own id", len({r.id for r in three}) == 3)

    two = inline.build_results("fa", "PH", "ST", None)
    check("no animation means no third result", len(two) == 2)

    # Uploading: all three go up, and the scratch copies are cleaned away when
    # there is no storage chat to keep them in.
    class Msg:
        def __init__(self, kind):
            self.message_id = 1
            self.deleted = False
            self.photo = [types.SimpleNamespace(file_id="PH")] if kind == "photo" else []
            self.sticker = types.SimpleNamespace(file_id="ST") if kind == "sticker" else None
            self.animation = (types.SimpleNamespace(file_id="AN")
                              if kind == "animation" else None)

        async def delete(self):
            self.deleted = True

    class FakeBot:
        def __init__(self):
            self.sent = []
            self.messages = []

        def _make(self, kind, chat_id):
            self.sent.append((kind, chat_id))
            msg = Msg(kind)
            self.messages.append(msg)
            return msg

        async def send_photo(self, chat_id, *a, **k):
            return self._make("photo", chat_id)

        async def send_sticker(self, chat_id, *a, **k):
            return self._make("sticker", chat_id)

        async def send_animation(self, chat_id, *a, **k):
            return self._make("animation", chat_id)

    async def uploading():
        # The photo and the sticker go up together, and the answer waits only on
        # them; the animation is uploaded on its own so it can be given up on.
        bot_ = FakeBot()
        ctx = types.SimpleNamespace(bot=bot_)
        ids = await inline._upload(ctx, None, 77, b"png", b"webp")
        check("the quick two are uploaded together",
              [kind for kind, _ in bot_.sent] == ["photo", "sticker"], str(bot_.sent))
        check("the user's own chat is the scratch space",
              all(chat == 77 for _, chat in bot_.sent))
        await asyncio.sleep(0)  # the deleting is scheduled, not awaited
        check("scratch copies are deleted", all(m.deleted for m in bot_.messages))
        check("their file ids come back", ids == ("PH", "ST"), str(ids))

        animation_id = await inline._upload_animation(
            ctx, None, 77, (b"mp4", "mp4"))
        check("the animation goes up by itself", animation_id == "AN")

        # With a storage chat, nothing stays: the file ids outlive the messages.
        bot_ = FakeBot()
        ctx = types.SimpleNamespace(bot=bot_)
        await inline._upload(ctx, -100999, 77, b"png", b"webp")
        await inline._upload_animation(ctx, -100999, 77, (b"mp4", "mp4"))
        check("a storage chat is used when set",
              all(chat == -100999 for _, chat in bot_.sent))
        await asyncio.sleep(0)
        kept = [m for m in bot_.messages if not m.deleted]
        check("nothing is kept in the storage channel, the GIF included",
              not kept and any(m.animation is not None for m in bot_.messages))

        # The cache: the same words twice should not be rendered twice.
        ctx = types.SimpleNamespace(bot=bot_, bot_data={})
        check("nothing is cached to begin with",
              inline._cached(ctx, "k") is None)
        inline._remember(ctx, "k", ("PH", "ST", "AN"))
        check("and then it is", inline._cached(ctx, "k") == ("PH", "ST", "AN"))
        for i in range(inline.CACHE_LIMIT + 20):
            inline._remember(ctx, f"k{i}", ("P", "S", None))
        check("the cache is bounded",
              len(ctx.bot_data["inline_cache"]) == inline.CACHE_LIMIT,
              str(len(ctx.bot_data["inline_cache"])))
        check("and the oldest went first", "k" not in ctx.bot_data["inline_cache"])

    async def not_blocking():
        # The deleting must not be awaited inside _upload: an inline query is
        # answered on this path and every round trip is felt.
        class SlowMsg(Msg):
            async def delete(self):
                await asyncio.sleep(0.2)
                self.deleted = True

        class SlowBot(FakeBot):
            def _make(self, kind, chat_id):
                self.sent.append((kind, chat_id))
                msg = SlowMsg(kind)
                self.messages.append(msg)
                return msg

        ctx = types.SimpleNamespace(bot=SlowBot())
        started = time.monotonic()
        await inline._upload(ctx, -100999, 77, b"png", b"webp")
        check("cleanup does not hold up the answer",
              time.monotonic() - started < 0.1,
              f"{time.monotonic() - started:.2f}s")

        # A slow animation must not hold up the answer either: past its share of
        # the budget the query is answered with the two that are ready.
        async def slow_gif():
            await asyncio.sleep(5)
            return "AN"

        gif = asyncio.ensure_future(slow_gif())
        started = time.monotonic()
        late = None
        try:
            late = await asyncio.wait_for(asyncio.shield(gif), 0.2)
        except asyncio.TimeoutError:
            pass
        check("a slow animation is given up on",
              late is None and time.monotonic() - started < 1)
        check("but it is left running, to land in the cache", not gif.done())
        gif.cancel()

        # A sentence typed one word at a time must not leave a file in the
        # channel per word: each keystroke abandons what the last one started.
        uploaded = []

        async def slow_upload(tag):
            try:
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                raise
            uploaded.append(tag)
            return "AN"

        typist = 4242
        tasks = []
        for i in range(4):
            inline._abandon(typist)
            task = asyncio.ensure_future(slow_upload(i))
            inline._remember_task(typist, task)
            tasks.append(task)
            await asyncio.sleep(0.05)     # still typing
        await asyncio.sleep(0.8)          # the last one finishes
        check("only the last keystroke reaches the channel",
              uploaded == [3], str(uploaded))
        check("the abandoned ones are cancelled",
              all(t.cancelled() for t in tasks[:-1]))

        # The wait is whatever is left of the budget, so a run that was
        # already slow gets none of it.
        spare = inline.SAFE_TOTAL - 0.2
        check("a quick run has time for the animation",
              spare >= inline.MIN_WAIT, f"{spare:.1f}s")
        spare = inline.SAFE_TOTAL - (inline.SAFE_TOTAL + 1)
        check("a slow one has none", spare < inline.MIN_WAIT, f"{spare:.1f}s")

    asyncio.run(uploading())
    asyncio.run(not_blocking())

    # The setting people actually get wrong: pasting an invite link, which a bot
    # cannot follow, and which used to break every inline query with no clue why.
    check("a numeric id is kept", bot._storage_chat("-1001234567890") == -1001234567890)
    check("an @name is kept", bot._storage_chat("@store") == "@store")
    check("an empty setting is nothing", bot._storage_chat("  ") is None)
    for link in ("t.me/+ztLZKbb", "https://t.me/joinchat/xx", "+ztLZKbb"):
        check(f"an invite link is refused ({link[:12]})", bot._storage_chat(link) is None)
    check("gibberish is refused", bot._storage_chat("my channel") is None)


def test_persisted_state() -> None:
    section("what gets written to disk")

    import pickle

    # Everything in user_data, chat_data and bot_data is pickled by
    # python-telegram-bot on a timer. Something unpicklable in there does not
    # raise where it was put: it kills the persistence loop, quietly, and
    # nothing is saved from then until the next restart - which is when the
    # file is read back. That is how a whole day of settings can vanish.
    async def run():
        loop = asyncio.get_running_loop()

        async def forever():
            await asyncio.sleep(30)

        task = loop.create_task(forever())
        user_data = {"inline_seq": "123", "started": True}
        inline._remember_task(7, task)

        check("a running gif is kept out of the persisted store",
              all(not isinstance(v, asyncio.Task) for v in user_data.values()))
        try:
            pickle.dumps(user_data)
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
        check("so the store still pickles", ok)
        check("and the task is held beside it", inline._running.get(7) is task)

        inline._abandon(7)
        check("abandoning cancels it", task.cancelled() or task.cancelling())
        check("and lets go of it", 7 not in inline._running)

        # A gif that finishes on its own must not be remembered for ever.
        done = loop.create_task(asyncio.sleep(0))
        inline._remember_task(8, done)
        await asyncio.sleep(0.05)
        check("a finished one is forgotten too", 8 not in inline._running)

    asyncio.run(run())

    source = (ROOT / "inline.py").read_text(encoding="utf-8")
    check("inline puts nothing but plain values in user_data",
          'user_data["inline_gif"]' not in source)

    # The rest of what the bot stores, as it stores it.
    sample = {
        "started": True, "lang": "fa", "template": "card",
        "last_render": 1.0, "await_pack_title": True,
        "admin_await": "qgive", "cast_from": (1, 2),
        "blocked": {1, 2}, "exempt": {3}, "queue_cutoff": 1.0,
        "avatar_extra_all": 2, "avatar_uses": {7: 1},
        "template_sheet": {"id": "X", "stamp": "1:2"},
        "paused": False, "storage_chat": -100,
    }
    try:
        pickle.loads(pickle.dumps(sample))
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    check("every other kind of stored value survives a round trip", ok)


def test_gif_archive() -> None:
    section("gif archive")

    import pickle
    import gallery

    def person(name, handle="", uid=None, kind="user"):
        return authors.Author(name, handle, uid, kind, str(uid))

    ali = person("علی رضایی", "ali_r", 101)
    sara = person("Sara K", "sarak", 202)
    chan = person("کانال خبری", "news", -100500, kind="chat")

    data = {}
    gallery.record(data, "F1", ali, "سلام")
    gallery.record(data, "F2", sara, "hello")
    gallery.record(data, "F3", ali, "دوباره")
    gallery.record(data, "F4", chan, "خبر")

    def ids(found):
        return [g["f"] for g in found]

    check("everything, newest first", ids(gallery.search(data)) == ["F4", "F3", "F2", "F1"])
    check("found by part of the name", ids(gallery.search(data, "علی")) == ["F3", "F1"])
    check("found by username", ids(gallery.search(data, "sarak")) == ["F2"])
    check("with or without the @", ids(gallery.search(data, "@ali_r")) == ["F3", "F1"])
    check("found by numeric id", ids(gallery.search(data, "202")) == ["F2"])
    check("an id matches whole, not as a fragment", gallery.search(data, "20") == [])
    check("case does not matter", ids(gallery.search(data, "SARA")) == ["F2"])
    # A name typed on one keyboard, searched for on another.
    check("Arabic yeh and kaf find the Persian ones",
          ids(gallery.search(data, "علي رضايي")) == ["F3", "F1"])
    check("a channel is found by its title", ids(gallery.search(data, "خبری")) == ["F4"])
    check("a channel keeps no user id", gallery.search(data, "خبری")[0]["u"] is None)
    check("nothing found is an empty list", gallery.search(data, "nobody") == [])
    check("people are counted once each", gallery.people(data) == 3)

    gallery.record(data, "F1", ali, "سلام")
    check("the same file is filed once", ids(gallery.search(data)).count("F1") == 1)
    check("and moves to the front", ids(gallery.search(data))[0] == "F1")

    big = {}
    for i in range(gallery.LIMIT + 25):
        gallery.record(big, f"X{i}", ali)
    check("the archive is bounded", len(big[gallery.KEY]) == gallery.LIMIT)
    check("and the oldest go first", big[gallery.KEY][0]["f"] == "X25")

    try:
        pickle.dumps(data)
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    check("the archive pickles with the rest of user_data", ok)

    # Inline: "#name" opens the gallery instead of making a quote.
    class Query:
        def __init__(self, text, offset=""):
            self.query, self.offset, self.id = text, offset, "q1"
            self.from_user = types.SimpleNamespace(id=7, language_code="en",
                                                   first_name="M", last_name=None,
                                                   username="m")
            self.answered = None

        async def answer(self, results, **kwargs):
            self.answered = (results, kwargs)

    many = {}
    for i in range(60):
        gallery.record(many, f"M{i}", ali if i % 2 else sara)

    async def run():
        handler = inline.make_handler("@b", None, None)
        ctx = types.SimpleNamespace(user_data=many, bot_data={}, bot=None)

        async def ask(text, offset=""):
            q = Query(text, offset)
            update = types.SimpleNamespace(inline_query=q, effective_user=q.from_user)
            await handler(update, ctx)
            return q.answered

        results, kw = await ask("#علی")
        check("#name answers from the archive", len(results) == 30)
        check("with only that person", all(r.mpeg4_file_id.startswith("M") and
                                           int(r.mpeg4_file_id[1:]) % 2 for r in results))
        check("gallery ids can never be taken for a new quote",
              all(r.id.startswith("g") for r in results))
        check("and the answer is personal", kw.get("is_personal") is True)

        results, kw = await ask("#")
        check("a page is at most what Telegram takes", len(results) == gallery.PAGE)
        check("and says where the next one starts", kw.get("next_offset") == str(gallery.PAGE))
        results, kw = await ask("#", offset=str(gallery.PAGE))
        check("the second page has the rest", len(results) == 10 and not kw.get("next_offset"))

        results, kw = await ask("#nobody")
        check("no match is said on the button", not results and kw.get("button") is not None
              and "nobody" in kw["button"].text)

        results, kw = await ask("")
        check("an empty query shows the archive", len(results) == gallery.PAGE)
        check("and still offers to make a quote", kw.get("button") is not None)

    asyncio.run(run())

    # Sending a GIF from inline files it; picking from the gallery does not.
    async def chosen():
        ctx = types.SimpleNamespace(user_data={"inline_offered_gif": {"r1": "GIF1"}},
                                    bot_data={}, bot=None)
        user = types.SimpleNamespace(id=7, full_name="Me", username="me")

        def update(result_id):
            return types.SimpleNamespace(chosen_inline_result=types.SimpleNamespace(
                result_id=result_id, from_user=user, query="my words"))

        await bot.on_chosen_inline(update("r1"), ctx)
        filed = ctx.user_data.get(gallery.KEY, [])
        check("a GIF sent from inline is filed", [g["f"] for g in filed] == ["GIF1"])
        check("under the person who sent it", filed and filed[0]["u"] == 7)
        check("with their words", filed and filed[0]["q"] == "my words")
        await bot.on_chosen_inline(update("g3"), ctx)
        check("resending from the gallery files nothing new",
              len(ctx.user_data.get(gallery.KEY, [])) == 1)

    asyncio.run(chosen())

    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    gif_cmd = source[source.index("async def cmd_quote_gif"):]
    gif_cmd = gif_cmd[:gif_cmd.index("\ndef ")]
    check("/gif files what it sends", "gallery.record(" in gif_cmd)


def test_storage_channel() -> None:
    section("storage channel")

    from telegram.constants import ChatMemberStatus

    class Bot_:
        def __init__(self):
            self.told = []

        async def send_message(self, chat_id, text, **kwargs):
            self.told.append((chat_id, text))

    def event(chat_id, actor_id, status=ChatMemberStatus.ADMINISTRATOR,
              kind="channel"):
        return types.SimpleNamespace(my_chat_member=types.SimpleNamespace(
            chat=types.SimpleNamespace(id=chat_id, type=kind, title="انبار"),
            from_user=types.SimpleNamespace(id=actor_id),
            old_chat_member=types.SimpleNamespace(status=ChatMemberStatus.LEFT),
            new_chat_member=types.SimpleNamespace(status=status),
        ))

    async def run():
        owner, store_was = bot.OWNER_ID, bot.STORAGE_CHAT
        bot.OWNER_ID, bot.STORAGE_CHAT = 4242, None
        try:
            store, fake = {}, Bot_()
            ctx = types.SimpleNamespace(bot_data=store, user_data={}, bot=fake)
            await bot._adopt_storage(event(-1001, 4242), ctx)
            check("the owner's channel is adopted", store.get("storage_chat") == -1001)
            check("and the owner is told", fake.told and "-1001" in fake.told[0][1])

            # Anyone can add a bot to their own channel; that must not move the store.
            store, fake = {"storage_chat": -1001}, Bot_()
            ctx = types.SimpleNamespace(bot_data=store, user_data={}, bot=fake)
            await bot._adopt_storage(event(-2002, 9999), ctx)
            check("a stranger's channel is ignored", store["storage_chat"] == -1001)
            check("and nobody is told", not fake.told)

            # Added as a plain member, with no right to post: not a store.
            store, fake = {}, Bot_()
            ctx = types.SimpleNamespace(bot_data=store, user_data={}, bot=fake)
            await bot._adopt_storage(
                event(-3003, 4242, status=ChatMemberStatus.MEMBER), ctx)
            check("a non-admin channel is ignored", "storage_chat" not in store)

            # With no owner configured there is nobody to trust.
            bot.OWNER_ID = None
            store, fake = {}, Bot_()
            ctx = types.SimpleNamespace(bot_data=store, user_data={}, bot=fake)
            await bot._adopt_storage(event(-4004, 4242), ctx)
            check("without an owner nothing is adopted", "storage_chat" not in store)
            # A store named in .env is not overruled by adoption.
            bot.STORAGE_CHAT = -1009999
            store, fake = {}, Bot_()
            ctx = types.SimpleNamespace(bot_data=store, user_data={}, bot=fake)
            await bot._adopt_storage(event(-5005, 4242), ctx)
            check("a configured store is left alone", "storage_chat" not in store)
        finally:
            bot.OWNER_ID, bot.STORAGE_CHAT = owner, store_was

    asyncio.run(run())


LAUGH, HEART, THUMB, FIRE = "😂", "❤️", "👍", "🔥"


def test_reactions() -> None:
    section("reactions")

    def emoji(char):
        return types.SimpleNamespace(emoji=char)

    def change(chat_id, message_id, old, new):
        return types.SimpleNamespace(
            message_reaction=types.SimpleNamespace(
                chat=types.SimpleNamespace(id=chat_id), message_id=message_id,
                old_reaction=[emoji(c) for c in old],
                new_reaction=[emoji(c) for c in new]),
            message_reaction_count=None)

    data = {}
    reactions.record_change(data, change(-1, 5, [], [LAUGH]))
    check("a new reaction counts", reactions.for_message(data, -1, 5) == [(LAUGH, 1)])

    reactions.record_change(data, change(-1, 5, [], [LAUGH]))
    reactions.record_change(data, change(-1, 5, [], [HEART]))
    check("more of the same add up",
          dict(reactions.for_message(data, -1, 5)) == {LAUGH: 2, HEART: 1})

    # Someone swapping one reaction for another moves the count, not adds to it.
    reactions.record_change(data, change(-1, 5, [LAUGH], [HEART]))
    check("changing one's mind moves the count",
          dict(reactions.for_message(data, -1, 5)) == {LAUGH: 1, HEART: 2})

    # Taking the last one back leaves nothing behind, not a zero.
    data2 = {}
    reactions.record_change(data2, change(-1, 9, [], [FIRE]))
    reactions.record_change(data2, change(-1, 9, [FIRE], []))
    check("taking it back removes it", reactions.for_message(data2, -1, 9) == [])
    check("and keeps no empty entry", not data2["reactions"][-1])

    # Most reacted first, and never more than fits across a bubble.
    data3 = {}
    for char, times in ((LAUGH, 3), (HEART, 7), (THUMB, 1), (FIRE, 5)):
        for _ in range(times):
            reactions.record_change(data3, change(-1, 1, [], [char]))
    for extra in ("😮", "😢", "🎉"):
        reactions.record_change(data3, change(-1, 1, [], [extra]))
    shown = reactions.for_message(data3, -1, 1)
    check("the most reacted comes first", shown[0] == (HEART, 7), str(shown))
    check("in descending order",
          [n for _, n in shown] == sorted([n for _, n in shown], reverse=True))
    # Nothing is dropped: a message reacted to seven ways shows seven.
    check("every reaction is kept", len(shown) == 7, str(len(shown)))

    # A custom emoji is a file, not a character: nothing to draw, so not counted.
    data4 = {}
    custom = types.SimpleNamespace(
        message_reaction=types.SimpleNamespace(
            chat=types.SimpleNamespace(id=-1), message_id=2,
            old_reaction=[], new_reaction=[types.SimpleNamespace(custom_emoji_id="x")]),
        message_reaction_count=None)
    reactions.record_change(data4, custom)
    check("a custom emoji is skipped", reactions.for_message(data4, -1, 2) == [])

    # Anonymous chats send the totals instead, and those replace what we had.
    data5 = {}
    reactions.record_change(data5, change(-1, 3, [], [LAUGH]))
    totals = types.SimpleNamespace(
        message_reaction=None,
        message_reaction_count=types.SimpleNamespace(
            chat=types.SimpleNamespace(id=-1), message_id=3,
            reactions=[types.SimpleNamespace(type=emoji(LAUGH), total_count=42)]))
    reactions.record_totals(data5, totals)
    check("totals replace a running count",
          reactions.for_message(data5, -1, 3) == [(LAUGH, 42)])

    # A busy group must not grow this without end.
    data6 = {}
    for message_id in range(reactions.MAX_MESSAGES_PER_CHAT + 25):
        reactions.record_change(data6, change(-1, message_id, [], [LAUGH]))
    kept = data6["reactions"][-1]
    check("old messages are dropped",
          len(kept) == reactions.MAX_MESSAGES_PER_CHAT, str(len(kept)))
    check("and it is the oldest that go", 0 not in kept and 424 in kept)
    check("the count is reported", reactions.total_tracked(data6) == len(kept))

    # A message nobody reacted to has nothing, which is the honest answer.
    check("an unseen message has none", reactions.for_message({}, -7, 7) == [])


def test_reaction_row() -> None:
    section("the reaction row")

    font = fonts.emoji_font(45)
    check("a colour emoji font was found", font is not None,
          "none on this machine; reactions will be left off")
    if font is None:
        return

    # The bug worth keeping a test for: a heart drawn into too small a tile lost
    # a slice of its left side, because its advance is wider than its ink.
    tiles = {name: screenshot._emoji_tile(font, char, 45)
             for name, char in (("heart", HEART), ("laugh", LAUGH), ("thumb", THUMB))}
    for name, tile in tiles.items():
        check(f"the {name} is drawn", tile is not None and tile.getbbox() is not None)
    widths = [t.crop(t.getbbox()).width for t in tiles.values()]
    check("every emoji fills its cell alike",
          max(widths) - min(widths) <= 12, str(widths))

    avatar = render.fallback_avatar("x", "A")
    plain = screenshot.render(avatar, "Ali", "سلام", "14:17", None, "ali")
    with_row = screenshot.render(avatar, "Ali", "سلام", "14:17", None, "ali",
                                 [(LAUGH, 4), (HEART, 2)])
    check("the row makes the bubble taller", with_row.height > plain.height)
    check("and wide enough for itself", with_row.width > plain.width)
    check("no reactions changes nothing",
          screenshot.render(avatar, "Ali", "سلام", "14:17", None, "ali", []).size
          == plain.size)

    # The count is drawn in the accent colour, so the row must actually have ink.
    row = with_row.crop((0, with_row.height - 120, with_row.width, with_row.height))
    check("the row has something in it", len(set(row.convert("RGB").get_flattened_data())) > 20)

    # The time shares the reaction row rather than stacking under it whenever
    # the two fit side by side, which for a short message they always do.
    short = screenshot.render(avatar, "Ali", "مرسی", "14:17", None, "ali", [(HEART, 5)])
    stacked = screenshot.render(avatar, "Ali", "مرسی", "14:17", None, "ali")
    check("a lone reaction does not push the time onto its own line",
          short.height - stacked.height < screenshot._px(
              screenshot.THEME["time_size"] + 5) + screenshot._px(
              screenshot.REACTION_SIZE + 9),
          f"{short.height} vs {stacked.height}")

    # Wrapping: a dozen reactions go onto more rows rather than losing any.
    many = [(c, 9) for c in "😂❤️👍🔥😮😢🎉🤯👏🙃😡💯"]
    tall = screenshot.render(avatar, "Ali", "سلام", "14:17", None, "ali", many)
    check("many reactions make it taller still", tall.height > with_row.height)
    check("and no wider than a bubble may be",
          tall.width <= screenshot._px(screenshot.MAX_BUBBLE_W) + screenshot._px(
              screenshot.PAD * 2 + screenshot.GAP + screenshot.THEME["avatar"]) + 4,
          str(tall.width))

    pill = (None, "9", 10.0, 100.0)
    rows = screenshot._wrap_pills([pill] * 10, 340, 5)
    check("pills wrap at the width given", len(rows) > 1, str(len(rows)))
    check("and none are lost", sum(len(r) for r in rows) == 10)
    check("a single oversized pill still gets a row",
          len(screenshot._wrap_pills([(None, "9", 10.0, 999.0)], 100, 5)) == 1)


def test_badges() -> None:
    section("name badges")

    from telegram.constants import ChatMemberStatus
    from telegram.error import TelegramError

    def member(status, title=None, tag=None, fail=False):
        class B:
            async def get_chat_member(self, chat_id, user_id):
                if fail:
                    raise TelegramError("nope")
                return types.SimpleNamespace(
                    status=status, custom_title=title,
                    api_kwargs={"tag": tag} if tag else {})
        return B()

    chat = types.SimpleNamespace(id=-100, type="supergroup")
    who = authors.Author("Ali", "ali", 7, "user", "7")

    def badge(bot_):
        return asyncio.run(bot._badge(bot_, chat, who, "fa"))

    # The new one: a tag an admin set on an ordinary member.
    check("a member's tag is shown",
          badge(member(ChatMemberStatus.MEMBER, tag="تحت تعقیب"))
          == ("تحت تعقیب", False))
    check("a plain member with no tag has none",
          badge(member(ChatMemberStatus.MEMBER)) is None)
    check("a tag wins over the generic word",
          badge(member(ChatMemberStatus.ADMINISTRATOR, tag="افراسیاب"))
          == ("افراسیاب", True))
    check("an admin's own title is shown",
          badge(member(ChatMemberStatus.ADMINISTRATOR, title="چیل")) == ("چیل", True))
    check("an admin with neither gets the generic word",
          badge(member(ChatMemberStatus.ADMINISTRATOR))
          == (i18n.t("badge_admin", "fa"), True))
    check("the owner gets theirs",
          badge(member(ChatMemberStatus.OWNER)) == (i18n.t("badge_owner", "fa"), True))
    check("a blank tag counts as none",
          badge(member(ChatMemberStatus.MEMBER, tag="   ")) is None)
    check("a failed lookup is not a badge",
          badge(member(ChatMemberStatus.ADMINISTRATOR, fail=True)) is None)

    # Not a group, so no badge whatever the member record says.
    private = types.SimpleNamespace(id=7, type="private")
    check("private chats have no badges",
          asyncio.run(bot._badge(member(ChatMemberStatus.OWNER), private, who, "fa"))
          is None)
    # The app dresses the two differently, so the pictures must differ too.
    tile = render.fallback_avatar("b", "A")
    def shot(is_admin):
        return screenshot.render(tile, "Ali", "سلام", "14:17", "چیل",
                                 "ali", None, is_admin)
    # The badge takes the far edge of the bubble in either direction, so an
    # English message must not have it trailing the name.
    def badge_at_edge(text):
        shot = screenshot.render(tile, "Sep", text, "11:18 PM", "admin", "sep")
        # The pill is tinted, so it is neither the bubble's white nor the
        # wallpaper: look for it in the top-right corner of the bubble.
        band = shot.crop((shot.width // 2, 0, shot.width, shot.height // 3))
        return len(set(band.convert("RGB").get_flattened_data())) > 30
    check("the badge sits at the far edge in English",
          badge_at_edge("Hello my name is window"))
    check("and in Persian", badge_at_edge("سلام اسم من پنجره است"))

    check("a tag is not drawn like a rank",
          render.to_png(shot(True)).getvalue() != render.to_png(shot(False)).getvalue())
    check("and takes less room, having no pill",
          shot(False).width < shot(True).width)

    channel = authors.Author("کانال", "", -100, "chat", "-100")
    check("a channel has no badge",
          asyncio.run(bot._badge(member(ChatMemberStatus.OWNER), chat, channel, "fa"))
          is None)


def test_gates() -> None:
    section("who may use the bot")

    from telegram.constants import ChatMemberStatus
    from telegram.error import TelegramError

    class ChannelBot:
        username = "getquoto_bot"

        def __init__(self, status=ChatMemberStatus.MEMBER, error=None):
            self.status, self.error, self.asked = status, error, 0

        async def get_chat_member(self, chat_id, user_id):
            self.asked += 1
            if self.error:
                raise TelegramError(self.error)
            return types.SimpleNamespace(status=self.status)

    def inside(status=None, error=None, cache=None, channel="@chan"):
        was, bot.REQUIRED_CHANNEL = bot.REQUIRED_CHANNEL, channel
        try:
            bot_ = ChannelBot(status or ChatMemberStatus.MEMBER, error)
            got = asyncio.run(bot._in_channel(bot_, 7, cache if cache is not None else {}))
            return got, bot_
        finally:
            bot.REQUIRED_CHANNEL = was

    check("a member is let in", inside(ChatMemberStatus.MEMBER)[0])
    check("an admin of it too", inside(ChatMemberStatus.ADMINISTRATOR)[0])
    check("someone who left is not", not inside(ChatMemberStatus.LEFT)[0])
    check("someone banned is not", not inside(ChatMemberStatus.BANNED)[0])

    # The one that matters: a bot that is not an admin of the channel cannot see
    # who is in it, and must not answer "nobody" - that would lock out everyone.
    check("an unreadable channel lets everyone through",
          inside(error="Member list is inaccessible")[0])
    check("so does one that does not exist",
          inside(error="Chat not found")[0])
    check("no channel set means no gate", inside(channel="")[0])

    # A yes is remembered; asking Telegram per command would be a round trip
    # per command.
    cache = {}
    first, bot_ = inside(ChatMemberStatus.MEMBER, cache=cache)
    check("a yes is cached", cache and first)
    was, bot.REQUIRED_CHANNEL = bot.REQUIRED_CHANNEL, "@chan"
    try:
        again = ChannelBot(ChatMemberStatus.MEMBER)
        asyncio.run(bot._in_channel(again, 7, cache))
        check("and not asked again", again.asked == 0)
    finally:
        bot.REQUIRED_CHANNEL = was

    # Start is the first thing anyone does, so it asks for the channel itself
    # rather than handing over a guide to a bot they cannot use yet.
    class Msg_:
        def __init__(self):
            self.out = []
            self.markup = None

        async def reply_text(self, text, reply_markup=None, **kwargs):
            self.out.append(text)
            self.markup = reply_markup

        async def reply_html(self, text, **kwargs):
            self.out.append(text)

    async def starting(status):
        was, bot.REQUIRED_CHANNEL = bot.REQUIRED_CHANNEL, "@chan"
        try:
            message = Msg_()
            ctx = types.SimpleNamespace(
                bot=ChannelBot(status), bot_data={}, user_data={})
            update = types.SimpleNamespace(
                effective_message=message,
                effective_user=types.SimpleNamespace(id=7, language_code="fa"))
            await bot.cmd_start(update, ctx)
            return message, ctx
        finally:
            bot.REQUIRED_CHANNEL = was

    # The welcome mentions the channel too, so the two are told apart by what
    # only one of them says: the prompt asks, the welcome hands over the guide.
    asking = "یک قدم مانده"
    message, ctx = asyncio.run(starting(ChatMemberStatus.LEFT))
    check("someone outside is asked to join at Start",
          asking in message.out[0], message.out[0][:40])
    check("and gets a button to do it", message.markup is not None)
    check("but is still recorded as having started", ctx.user_data["started"])

    message, _ = asyncio.run(starting(ChatMemberStatus.MEMBER))
    check("a member gets the welcome instead",
          asking not in message.out[0] and "/help" in message.out[0],
          message.out[0][:40])

    # The owner can excuse a person, or a whole group, from the channel.
    async def excused(ident, in_chat=None):
        was, bot.REQUIRED_CHANNEL = bot.REQUIRED_CHANNEL, "@chan"
        try:
            message = Msg_()
            ctx = types.SimpleNamespace(
                bot=ChannelBot(ChatMemberStatus.LEFT),
                bot_data={"exempt": {ident}}, user_data={})
            update = types.SimpleNamespace(
                effective_message=message,
                effective_chat=types.SimpleNamespace(id=in_chat or 7),
                effective_user=types.SimpleNamespace(id=7, language_code="fa"))
            return await bot._require_channel(update, ctx)
        finally:
            bot.REQUIRED_CHANNEL = was

    check("an excused person is let through", asyncio.run(excused(7)))
    check("an excused group lets its members through",
          asyncio.run(excused(-100, in_chat=-100)))
    check("and excusing one group does not excuse another",
          not asyncio.run(excused(-100, in_chat=-200)))
    check("somebody with no excuse is still asked",
          not asyncio.run(excused(999)))

    # The excuse covers the channel and nothing else: Start is still required.
    ctx = types.SimpleNamespace(bot_data={"exempt": {7}})
    check("the excuse is only about the channel",
          7 in admin.exempt(ctx) and "started" not in str(admin.exempt(ctx)))

    # The announcements channel must never be adopted as the file store.
    chan = types.SimpleNamespace(id=-100, type="channel", title="Quoto",
                                 username="getQuoto")
    check("matched by @name", bot._same_chat(chan, "@getquoto"))
    check("matched by id", bot._same_chat(chan, "-100"))
    check("and nothing else is", not bot._same_chat(chan, "@other"))

    async def adopting():
        was_owner, bot.OWNER_ID = bot.OWNER_ID, 4242
        was_chan, bot.REQUIRED_CHANNEL = bot.REQUIRED_CHANNEL, "@getQuoto"
        was_store, bot.STORAGE_CHAT = bot.STORAGE_CHAT, None
        try:
            class Bot_:
                async def send_message(self, *a, **k):
                    pass

            store = {}
            ctx = types.SimpleNamespace(bot_data=store, user_data={}, bot=Bot_())
            event = types.SimpleNamespace(my_chat_member=types.SimpleNamespace(
                chat=chan, from_user=types.SimpleNamespace(id=4242),
                old_chat_member=types.SimpleNamespace(status=ChatMemberStatus.LEFT),
                new_chat_member=types.SimpleNamespace(
                    status=ChatMemberStatus.ADMINISTRATOR)))
            await bot._adopt_storage(event, ctx)
            check("the announcements channel is not taken as the store",
                  "storage_chat" not in store)

            other = types.SimpleNamespace(id=-200, type="channel", title="Store",
                                          username="somewhere")
            event.my_chat_member.chat = other
            await bot._adopt_storage(event, ctx)
            check("but another channel still is", store.get("storage_chat") == -200)
        finally:
            bot.OWNER_ID, bot.REQUIRED_CHANNEL = was_owner, was_chan
            bot.STORAGE_CHAT = was_store

    asyncio.run(adopting())

    # Users: those who started and were not turned away, not everyone seen.
    class App:
        def __init__(self, user_data):
            self.user_data = user_data

    ctx = types.SimpleNamespace(
        bot_data={"blocked": {3}},
        application=App({1: {"started": True}, 2: {"started": True},
                         3: {"started": True}, 4: {}, 5: {"lang": "fa"}}))
    check("only those who started count", sorted(admin.members(ctx)) == [1, 2])
    admin.lost(ctx, 1)
    check("and one who blocked the bot stops counting",
          admin.members(ctx) == [2])
    check("no application means no guessing",
          admin.members(types.SimpleNamespace(bot_data={})) == [])

    # The number shown before sending has to be the number that will be sent to.
    # It was counting the tracker's list, which is a different population and a
    # smaller one, so the confirmation described somebody else's broadcast.
    source = (ROOT / "admin.py").read_text(encoding="utf-8")
    confirm = next(line for line in source.splitlines()
                   if "کاربر فرستاده می‌شود" in line)
    check("the confirmation counts the people who will get it",
          "members(context)" in confirm, confirm.strip())


def test_handler_groups() -> None:
    section("handler registration")

    from telegram.ext import Application, TypeHandler

    app = Application.builder().token("123456:selftest").build()
    bot.register(app)

    # Only the first matching handler in a group runs. A TypeHandler on Update
    # matches everything, so two of them in one group means the second never
    # runs - which is exactly how the tracker was silently dead.
    catch_all = {}
    for group, handlers in app.handlers.items():
        for handler in handlers:
            if isinstance(handler, TypeHandler):
                catch_all.setdefault(group, []).append(handler)
    crowded = {g: len(h) for g, h in catch_all.items() if len(h) > 1}
    check("no two catch-all handlers share a group", not crowded, str(crowded))
    check("there are two of them", sum(len(h) for h in catch_all.values()) == 2,
          str(catch_all))

    # And the stale check has to come first, or it would be recording the very
    # updates it exists to throw away.
    groups = sorted(catch_all)
    stale = catch_all[groups[0]][0].callback
    check("the stale check runs first", stale is bot.ignore_stale)
    check("and the handlers proper come after everything",
          max(app.handlers) >= 0 and min(app.handlers) < 0)


def test_wallpaper() -> None:
    section("screenshot wallpaper")
    paper = screenshot._wallpaper((120, 60))
    check("it is the size asked for", paper.size == (120, 60))
    corners = [paper.getpixel(xy) for xy in ((0, 0), (119, 0), (0, 59), (119, 59))]
    names = ("top-left", "top-right", "bottom-left", "bottom-right")
    # Scaling up cannot reproduce the four colours exactly at the very edge,
    # so what matters is that each corner is nearest to its own.
    for i, (got, where) in enumerate(zip(corners, names)):
        distances = [sum((a - b) ** 2 for a, b in zip(got, want))
                     for want in screenshot.WALLPAPER]
        check(f"the {where} corner is its colour",
              distances.index(min(distances)) == i, f"{got}")
    check("it is a gradient, not a flat fill", len(set(paper.get_flattened_data())) > 100)

    # The bubble has to stay readable on it, which is the whole point of the
    # white fill; a screenshot is still rendered end to end.
    img = screenshot.render(render.fallback_avatar("w", "W"), "Sep",
                            "دانلود بلو بانک", "12:56 AM", "admin", "w")
    check("a screenshot still renders", img.width > 100 and img.height > 50)
    check("the background is no longer flat blue",
          img.getpixel((2, 2)) != (220, 231, 240), str(img.getpixel((2, 2))))


def test_extract() -> None:
    section("extract")
    def message(text):
        return types.SimpleNamespace(text=text, caption=None)
    check("plain text kept", extract.quote_text(message("سلام")) == "سلام")
    check("emoji-only is textless", extract.quote_text(message("😂😂")) is None)
    check("blank is textless", extract.quote_text(message("   ")) is None)
    long_text = extract.quote_text(message("ا" * 900))
    check("long text truncated", len(long_text) <= extract.MAX_QUOTE_CHARS + 1)
    check("and says it was cut", long_text.endswith("…"))
    check("text at the limit is left alone",
          extract.quote_text(message("ا" * extract.MAX_QUOTE_CHARS))
          == "ا" * extract.MAX_QUOTE_CHARS)
    # Nothing past the cut is normalized, so a tail of emoji costs nothing
    # and cannot add to what is shown.
    tail = extract.quote_text(message("ا" * 700 + "😀" * 3000))
    check("the tail is never read", len(tail) == extract.MAX_QUOTE_CHARS + 1)


def test_pack_removal() -> None:
    section("removing a sticker")

    from telegram.constants import ChatMemberStatus
    from telegram.error import TelegramError

    OURS = -1001111
    THEIRS = -1002222

    class PackBot:
        username = "getquoto_bot"

        def __init__(self, fail=False, admin=True):
            self.deleted = []
            self.fail = fail
            self.admin = admin

        async def delete_sticker_from_set(self, file_id):
            if self.fail:
                raise TelegramError("nope")
            self.deleted.append(file_id)

        async def get_chat_member(self, chat_id, user_id):
            status = (ChatMemberStatus.ADMINISTRATOR if self.admin
                      else ChatMemberStatus.MEMBER)
            return types.SimpleNamespace(status=status)

    def chat(chat_id=OURS, kind="supergroup"):
        return types.SimpleNamespace(id=chat_id, type=kind, title="گروه")

    def sticker(owner_chat=OURS, file_id="S1"):
        return types.SimpleNamespace(
            file_id=file_id,
            set_name=stickerpack.pack_name(owner_chat, "getquoto_bot"))

    async def run():
        bot_ = PackBot()
        got = await stickerpack.remove_quote(bot_, chat(), sticker())
        check("a sticker from this pack is removed", got == "ok", got)
        check("and it is the one that was pointed at", bot_.deleted == ["S1"])

        # The boundary: every group's pack is created by the same bot, so the
        # set name is the only thing keeping one group out of another's pack.
        bot_ = PackBot()
        got = await stickerpack.remove_quote(bot_, chat(), sticker(owner_chat=THEIRS))
        check("another group's pack is refused", got == "not_ours", got)
        check("and nothing is deleted", not bot_.deleted)

        bot_ = PackBot()
        check("a private chat has no pack",
              await stickerpack.remove_quote(bot_, chat(kind="private"), sticker())
              == "not_group")
        check("nothing to delete is said so",
              await stickerpack.remove_quote(bot_, chat(), None) == "no_sticker")

        bot_ = PackBot(fail=True)
        check("a refusal from Telegram is reported",
              await stickerpack.remove_quote(bot_, chat(), sticker()) == "failed")

    asyncio.run(run())

    # The command in front of it.
    class Msg:
        def __init__(self, reply=None, kind="supergroup"):
            self.chat = types.SimpleNamespace(id=OURS, type=kind, title="گروه")
            self.chat_id = OURS
            self.reply_to_message = reply
            self.out = []

        async def reply_text(self, text, **kwargs):
            self.out.append(text)

        async def reply_html(self, text, **kwargs):
            self.out.append(text)

    def update_for(message):
        return types.SimpleNamespace(
            effective_message=message,
            effective_chat=message.chat,
            effective_user=types.SimpleNamespace(id=7, language_code="fa"))

    async def command():
        bot_ = PackBot(admin=False)
        message = Msg(reply=types.SimpleNamespace(sticker=sticker()))
        await bot.cmd_unpack(update_for(message),
                             types.SimpleNamespace(bot=bot_, user_data={}, bot_data={}))
        check("a plain member is refused", "ادمین" in message.out[0])
        check("and nothing is deleted for them", not bot_.deleted)

        bot_ = PackBot(admin=True)
        message = Msg(reply=types.SimpleNamespace(sticker=sticker()))
        await bot.cmd_unpack(update_for(message),
                             types.SimpleNamespace(bot=bot_, user_data={}, bot_data={}))
        check("an admin may remove one", bot_.deleted == ["S1"])

        bot_ = PackBot(admin=True)
        message = Msg(reply=None)
        await bot.cmd_unpack(update_for(message),
                             types.SimpleNamespace(bot=bot_, user_data={}, bot_data={}))
        check("without a reply it explains itself", "ریپلای" in message.out[0])
        check("and deletes nothing", not bot_.deleted)

        bot_ = PackBot(admin=True)
        message = Msg(reply=types.SimpleNamespace(sticker=sticker()), kind="private")
        await bot.cmd_unpack(update_for(message),
                             types.SimpleNamespace(bot=bot_, user_data={}, bot_data={}))
        check("it is refused outside a group", bool(message.out) and not bot_.deleted)

    asyncio.run(command())


def test_personal_pack() -> None:
    section("personal sticker pack")

    from telegram.error import TelegramError

    name = stickerpack.personal_name(5345287543, "getquoto_bot")
    check("the name ends with the bot", name.endswith("_by_getquoto_bot"))
    check("allowed characters only", re.fullmatch(r"[A-Za-z0-9_]+", name), name)
    check("within 64", len(name) <= stickerpack.MAX_NAME, str(len(name)))

    # A user and a group must never produce the same pack name: only the prefix
    # keeps them apart.
    clash = stickerpack.pack_name(-5345287543, "getquoto_bot")
    check("a person and a group never collide", name != clash, f"{name} vs {clash}")

    check("the title carries the name",
          "SEP" in stickerpack.personal_title("SEP"))
    check("and survives having none", stickerpack.personal_title(None))
    check("a very long name is cut to fit",
          len(stickerpack.personal_title("ط" * 200)) <= stickerpack.MAX_TITLE)

    class PackBot:
        username = "getquoto_bot"

        def __init__(self, exists=False, fail=False):
            self.exists, self.fail = exists, fail
            self.created, self.added = [], []

        async def get_sticker_set(self, name):
            if not self.exists:
                raise TelegramError("not found")
            return types.SimpleNamespace(name=name)

        async def create_new_sticker_set(self, user_id, name, title, stickers):
            if self.fail:
                raise TelegramError("nope")
            self.created.append((user_id, name, title))

        async def add_sticker_to_set(self, user_id, name, sticker):
            if self.fail:
                raise TelegramError("nope")
            self.added.append((user_id, name))

    person = types.SimpleNamespace(id=7, full_name="SEP")

    async def run():
        bot_ = PackBot(exists=False)
        got = await stickerpack.add_personal(bot_, person, b"webp", 4242)
        check("the first sticker creates the pack",
              got is not None and got[1] and bot_.created)
        check("and it is created under the owner's account",
              bot_.created[0][0] == 4242)

        bot_ = PackBot(exists=True)
        got = await stickerpack.add_personal(bot_, person, b"webp", 4242)
        check("later ones are appended", got is not None and not got[1])
        check("to the same pack", bot_.added and bot_.added[0][1] ==
              stickerpack.personal_name(person.id, "getquoto_bot"))

        bot_ = PackBot(exists=True, fail=True)
        check("a refusal from Telegram costs nothing",
              await stickerpack.add_personal(bot_, person, b"webp", 4242) is None)

        check("without an owner there is no pack",
              await stickerpack.add_personal(PackBot(), person, b"webp", None) is None)

        check("a pack that exists has a link",
              await stickerpack.personal_link(PackBot(exists=True), 7) is not None)
        check("and one that does not, does not",
              await stickerpack.personal_link(PackBot(exists=False), 7) is None)

    asyncio.run(run())

    # Where a sticker is filed depends on where it was made.
    class Msg:
        def __init__(self, kind):
            self.chat = types.SimpleNamespace(id=-100 if kind != "private" else 7,
                                              type=kind, title="گروه")
            self.chat_id = self.chat.id
            self.out = []

        async def reply_text(self, text, **kwargs):
            self.out.append(text)

        async def reply_html(self, text, **kwargs):
            self.out.append(text)

    async def filing():
        filed = []

        async def fake_group(bot_, chat, webp, owner):
            filed.append(("group", chat.id))
            return "link", False

        async def fake_personal(bot_, user, webp, owner):
            filed.append(("personal", user.id))
            return "link", False

        was = stickerpack.add_quote, stickerpack.add_personal
        stickerpack.add_quote, stickerpack.add_personal = fake_group, fake_personal
        try:
            for kind, expect in (("supergroup", "group"), ("private", "personal")):
                message = Msg(kind)
                update = types.SimpleNamespace(
                    effective_message=message,
                    effective_user=types.SimpleNamespace(id=7, language_code="fa"))
                await bot._announce_pack(
                    update, types.SimpleNamespace(bot=None, user_data={}), b"webp")
                check(f"a sticker made in a {kind} goes to the {expect} pack",
                      filed[-1][0] == expect, str(filed[-1]))
        finally:
            stickerpack.add_quote, stickerpack.add_personal = was

    asyncio.run(filing())


def test_pack_editing() -> None:
    section("editing your own pack")

    from telegram.error import TelegramError

    class PackBot:
        username = "getquoto_bot"

        def __init__(self, fail=False):
            self.fail = fail
            self.titled, self.deleted = [], []

        async def set_sticker_set_title(self, name, title):
            if self.fail:
                raise TelegramError("nope")
            self.titled.append((name, title))

        async def delete_sticker_from_set(self, file_id):
            if self.fail:
                raise TelegramError("nope")
            self.deleted.append(file_id)

    mine = stickerpack.personal_name(7, "getquoto_bot")

    def sticker(set_name=mine, file_id="S1"):
        return types.SimpleNamespace(set_name=set_name, file_id=file_id)

    async def run():
        bot_ = PackBot()
        check("a pack can be renamed",
              await stickerpack.rename_personal(bot_, 7, "پک من"))
        check("under its own name", bot_.titled and bot_.titled[0][0] == mine)

        long_title = "ط" * 200
        bot_ = PackBot()
        await stickerpack.rename_personal(bot_, 7, long_title)
        check("a long title is cut to what Telegram takes",
              len(bot_.titled[0][1]) <= stickerpack.MAX_TITLE)

        check("a refusal is reported, not raised",
              not await stickerpack.rename_personal(PackBot(fail=True), 7, "x"))

        # The check that matters: every pack the bot made is one it may delete
        # from, so the set name is what keeps one person out of another's.
        bot_ = PackBot()
        check("a sticker of mine is removed",
              await stickerpack.remove_personal(bot_, 7, sticker()) == "ok")
        check("and it is the one pointed at", bot_.deleted == ["S1"])

        bot_ = PackBot()
        check("somebody else's pack is refused",
              await stickerpack.remove_personal(
                  bot_, 7, sticker(set_name="u999_by_getquoto_bot")) == "not_ours")
        check("and nothing is deleted", not bot_.deleted)
        check("another person's own pack is refused too",
              await stickerpack.remove_personal(
                  bot_, 8, sticker()) == "not_ours")
        check("nothing to remove is said so",
              await stickerpack.remove_personal(bot_, 7, None) == "no_sticker")

    asyncio.run(run())

    # Inline: offering is not sending.
    ctx = types.SimpleNamespace(user_data={})
    results = inline.build_results("fa", "PH", "ST", "AN")
    inline.remember_offer(ctx, results, "ST")
    check("each offered result points at its sticker",
          all(inline.sticker_for(ctx, r.id) == "ST" for r in results))
    check("something never offered is unknown",
          inline.sticker_for(ctx, "made-up") is None)

    for i in range(inline.OFFERED_LIMIT + 10):
        inline.remember_offer(ctx, [types.SimpleNamespace(id=f"r{i}")], "S")
    check("the note of what was offered is bounded",
          len(ctx.user_data["inline_offered"]) <= inline.OFFERED_LIMIT,
          str(len(ctx.user_data["inline_offered"])))


def test_pack_deletion() -> None:
    section("deleting a whole pack")

    from telegram.error import TelegramError

    class DropBot:
        username = "getquoto_bot"

        def __init__(self, exists=True, fail=False):
            self.exists, self.fail = exists, fail
            self.deleted = []

        async def get_sticker_set(self, name):
            if not self.exists:
                raise TelegramError("not found")
            return types.SimpleNamespace(name=name)

        async def delete_sticker_set(self, name):
            if self.fail:
                raise TelegramError("nope")
            self.deleted.append(name)

    group = types.SimpleNamespace(type="supergroup", id=-1001111, title="g")
    other = types.SimpleNamespace(type="supergroup", id=-1002222, title="o")

    async def run():
        b = DropBot()
        check("a group's pack is deleted",
              await stickerpack.delete_group(b, group) == "ok")
        check("and it is that group's pack, under both names it has had",
              b.deleted == [stickerpack.pack_name(group.id, b.username),
                            stickerpack.legacy_pack_name(group.id, b.username)],
              str(b.deleted))
        check("never another group's",
              stickerpack.pack_name(other.id, b.username) not in b.deleted
              and stickerpack.legacy_pack_name(other.id, b.username) not in b.deleted)

        b = DropBot()
        check("a person's own pack is deleted",
              await stickerpack.delete_personal(b, 7) == "ok")
        check("and only ever their own",
              b.deleted == [stickerpack.personal_name(7, b.username)])

        b = DropBot(exists=False)
        check("nothing to delete is said, not attempted",
              await stickerpack.delete_personal(b, 7) == "no_pack" and not b.deleted)

        check("a refusal is reported, not raised",
              await stickerpack.delete_personal(DropBot(fail=True), 7) == "failed")
        check("a private chat has no group pack",
              await stickerpack.delete_group(
                  DropBot(), types.SimpleNamespace(type="private", id=7)) == "not_group")

    asyncio.run(run())

    # The command asks before it does anything: this cannot be undone and it
    # takes the pack away from everyone who added it, not just from whoever
    # typed the command.
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    asked = source[source.index("async def cmd_delpack"):source.index("async def on_delpack")]
    check("the command itself deletes nothing",
          "delete_group" not in asked and "delete_personal" not in asked)
    acted = source[source.index("async def on_delpack"):]
    acted = acted[:acted.index("async def cmd_quote_gif")]
    check("the button checks who pressed it, not who asked",
          "_is_group_admin" in acted)


def test_pack_names() -> None:
    section("sticker pack naming")
    name = stickerpack.pack_name(-1001234567890, "getquoto_bot")
    check("name ends with the bot", name.endswith("_by_getquoto_bot"))
    check("name is allowed characters", re.fullmatch(r"[A-Za-z0-9_]+", name), name)
    check("name within 64", len(name) <= stickerpack.MAX_NAME, str(len(name)))
    long_title = stickerpack.pack_title("گروه " * 40)
    check("title within 64", len(long_title) <= stickerpack.MAX_TITLE)
    check("empty title falls back", stickerpack.pack_title("   ") == "Quotes")
    check("link shape", stickerpack.pack_link("x").startswith("https://t.me/addstickers/"))

    # A personal pack name is a public link. It must not carry the id it was
    # made from, and it must not be reachable by guessing ids either, which is
    # why the digest is salted.
    stickerpack.set_salt("a-salt")
    uid = 123456789
    mine = stickerpack.personal_name(uid, "getquoto_bot")
    check("personal name is allowed characters",
          re.fullmatch(r"[A-Za-z0-9_]+", mine), mine)
    check("personal name within 64", len(mine) <= stickerpack.MAX_NAME, str(len(mine)))
    check("personal name ends with the bot", mine.endswith("_by_getquoto_bot"))
    check("the user id is nowhere in the name", str(uid) not in mine, mine)
    check("the same person always gets the same pack",
          stickerpack.personal_name(uid, "getquoto_bot") == mine)
    check("two people get different packs",
          stickerpack.personal_name(uid + 1, "getquoto_bot") != mine)

    # Without this an id is ten digits and a digest of one is brute-forced in
    # seconds, so the name would hide nothing at all.
    stickerpack.set_salt("another-salt")
    check("a different salt gives a different name",
          stickerpack.personal_name(uid, "getquoto_bot") != mine)
    stickerpack.set_salt("a-salt")
    check("and the first salt gives the first name back",
          stickerpack.personal_name(uid, "getquoto_bot") == mine)

    # The old scheme was the id itself; every link made under it is meant to
    # stop being found.
    check("the old id-shaped name is not what is looked up now",
          mine != f"u{uid}_by_getquoto_bot")
    check("a user and a group can never collide",
          mine != stickerpack.pack_name(uid, "getquoto_bot"))


def test_fire() -> None:
    section("fire")
    import fire

    said = "سلام 🔥\nدنیا 👍🏽"
    check("emoji are dropped, lines joined",
          fire.clean(said) == "سلام دنیا", repr(fire.clean(said)))
    check("persian zero-width non-joiner kept",
          "‌" in fire.clean("می‌روم"))
    check("nothing but emoji is nothing", fire.clean("🔥🔥") == "")
    check("window is shut outside its span",
          fire.window(0.5, 1, 2) == 0 and fire.window(1.5, 1, 2) == 1)

    # The menus, the guides and the handlers all know it.
    for lang in i18n.SUPPORTED:
        check(f"/fire in the {lang} menu",
              "fire" in {n for n, _ in i18n.COMMANDS[lang]})
        check(f"/fire in the {lang} help", "/fire" in i18n.t("help", lang))
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    check("/fire registered", '["fire", "fier", "fir"], cmd_fire' in source)
    body = source[source.index("async def cmd_fire"):source.index("def _clock")]
    check("too long is turned away before rendering",
          body.index("MAX_CHARS") < body.index("fire.render"))
    check("a render never runs on the event loop",
          re.search(r"throttle\.FIRE\.run\(\s*fire\.render", body) is not None)
    check("a full queue is turned away before anything else",
          body.index("throttle.FIRE.full") < body.index("throttle.FIRE.run"))
    check("fire is counted in the stats", "fire" in {k for k, _ in admin.KINDS})

    if not fire.available():
        print("  (assets/fire missing - rendering not tested)")
        return
    # Reveal: nothing before the pen starts, everything by the end, more in between.
    geometry = fire._geometry()
    for quote in ("Stay hungry, stay foolish",
                  "The best way to predict the future is to create it, so start today."):
        page = fire.PageShot(quote, geometry)
        empty, half, full = (int(page.canvas(p).astype(bool).sum()) for p in (0, 0.5, 1))
        check(f"page reveals in order ({len(quote)} chars)", empty == 0 < half < full,
              f"{empty} {half} {full}")
        check(f"page fits without cutting ({len(quote)} chars)",
              not any(l.endswith("…") for l in page.lines), str(page.lines))
    pen = fire.PenShot("Stay hungry, stay foolish")
    check("pen writes nothing before it starts", pen.mask(0.3) is None)
    check("pen has written by the end", int((pen.mask(1.8) > 0).sum()) > 500)
    longest = "x" * 9 + " " + "word " * ((fire.MAX_CHARS - 10) // 5)
    page = fire.PageShot(longest[:fire.MAX_CHARS], geometry)
    check("the longest allowed quote still fits the page",
          not any(l.endswith("…") for l in page.lines), str(len(page.lines)))

    data = fire.render("Stay hungry, stay foolish", "Steve Jobs", "@getquoto_bot")
    check("renders an mp4", data[4:8] == b"ftyp", data[:12].hex())
    check("small enough to send as a GIF", 200_000 < len(data) < 10_000_000, str(len(data)))
    import imageio_ffmpeg
    import tempfile as _tempfile
    with _tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "fire.mp4"
        clip.write_bytes(data)
        frames = imageio_ffmpeg.read_frames(str(clip))
        meta = next(frames)
        frames.close()
    check("sent at the size and rate chosen for speed",
          tuple(meta["size"]) == fire.OUT_SIZE and round(meta["fps"]) == fire.OUT_FPS,
          f"{meta['size']} {meta['fps']}")
    check("the clip is already there at that size",
          fire.BASE_SMALL.exists(), "run tools/make_fire_base.py --small")


def test_inline_fire() -> None:
    section("fire in inline mode")
    import fire
    import gallery
    import throttle

    for typed, expected in (("🔥 سلام", "سلام"), ("🔥️ hi", "hi"), ("/fire hi", "hi"),
                            ("/fire@getquoto_bot hi", "hi"), ("🔥", ""), ("سلام 🔥", None),
                            ("/fireman x", None), ("hi", None)):
        check(f"inline {typed!r} -> {expected!r}", inline.fire_text(typed) == expected)

    class Sent:
        def __init__(self, file_id):
            self.animation = types.SimpleNamespace(file_id=file_id)
            self.document = None
            self.deleted = False

        async def delete(self):
            self.deleted = True

    class FireBot:
        username = "getquoto_bot"

        def __init__(self):
            self.uploads, self.edits, self.captions = [], [], []

        async def send_animation(self, chat, data, **kw):
            self.uploads.append(chat)
            return Sent(f"FILE{len(self.uploads)}")

        async def edit_message_media(self, inline_message_id, media, reply_markup=None):
            self.edits.append((inline_message_id, media.media, reply_markup))

        async def edit_message_caption(self, inline_message_id, caption, reply_markup=None):
            self.captions.append(caption)

    class Query:
        def __init__(self, uid=7):
            self.from_user = types.SimpleNamespace(id=uid)
            self.answers = []

        async def answer(self, results, **kw):
            self.answers.append((results, kw))

    def ctx_for(b, store=None):
        app = types.SimpleNamespace(create_task=lambda coro: asyncio.ensure_future(coro))
        return types.SimpleNamespace(bot=b, bot_data=store if store is not None else {},
                                     user_data={}, application=app)

    if not fire.available():
        print("  (assets/fire missing - inline fire not tested)")
        return

    async def offer(text, store=None, b=None):
        b = b or FireBot()
        q = Query()
        c = ctx_for(b, store)
        await inline.answer_fire(q, c, text, "fa", -100555)
        return q, c, b

    q, c, b = asyncio.run(offer("سلام دنیا"))
    results = q.answers[0][0]
    check("an uncached text gets the placeholder",
          len(results) == 1 and results[0].id.startswith(inline.FIRE_RESULT))
    check("with a button, so the sent message can be edited later",
          results[0].reply_markup is not None)
    check("the placeholder is uploaded once to the store", b.uploads == [-100555])
    q2, _, b2 = asyncio.run(offer("یه چیز دیگه", store=c.bot_data))
    check("and reused after that", b2.uploads == [])

    q, _, _ = asyncio.run(offer("x" * (fire.MAX_CHARS + 1)))
    check("too long is refused in the list itself",
          q.answers[0][0] == [] and q.answers[0][1].get("button") is not None)
    q, _, _ = asyncio.run(offer(""))
    check("nothing after the 🔥 gets a hint", q.answers[0][0] == [])

    store = {}
    inline.fire_remember(store, inline.fire_key(7, "سلام دنیا"), "DONE")
    q, c, b = asyncio.run(offer("سلام دنیا", store=store))
    results = q.answers[0][0]
    check("a text made before is offered finished",
          len(results) == 1 and results[0].mpeg4_file_id == "DONE" and not b.uploads)
    check("and filed in their archive when sent",
          c.user_data["inline_offered_gif"].get(results[0].id) == "DONE")

    # Sent: rendered, uploaded, and swapped into the message that went out.
    real_render = fire.render
    fire.render = lambda quote, who, handle: b"MP4"
    try:
        b = FireBot()
        c = ctx_for(b)
        chosen = types.SimpleNamespace(
            result_id=inline.FIRE_RESULT + "abc", inline_message_id="IMID", query="🔥 سلام دنیا",
            from_user=types.SimpleNamespace(id=7, full_name="SAli", username="sali"))
        bot.STORAGE_CHAT, saved_store = -100555, bot.STORAGE_CHAT
        try:
            asyncio.run(bot._fire_inline(c, chosen, "fa"))
        finally:
            bot.STORAGE_CHAT = saved_store
        check("the finished clip replaces the placeholder",
              b.edits and b.edits[0][0] == "IMID" and b.edits[0][1] == "FILE1")
        check("with the button to make your own", b.edits[0][2] is not None)
        check("it is remembered for the same text",
              inline.fire_cached(c.bot_data, inline.fire_key(7, "سلام دنیا")) == "FILE1")
        check("and filed in the maker's archive",
              [g["f"] for g in c.user_data.get(gallery.KEY, [])] == ["FILE1"])
        check("and nobody is left marked as rendering", not bot._fire_inline_running)

        b = FireBot()
        asyncio.run(bot._fire_inline(ctx_for(b), types.SimpleNamespace(
            result_id=inline.FIRE_RESULT + "x", inline_message_id=None, query="🔥 hi",
            from_user=chosen.from_user), "fa"))
        check("without a message to edit, nothing is rendered", not b.uploads and not b.edits)

        bot._fire_inline_running.add(7)
        b = FireBot()
        asyncio.run(bot._fire_inline(ctx_for(b), chosen, "fa"))
        bot._fire_inline_running.discard(7)
        check("one at a time per person", not b.uploads and b.captions)
    finally:
        fire.render = real_render

    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    chosen_body = source[source.index("async def on_chosen_inline"):]
    check("a fire result is handed off before anything else is filed",
          chosen_body.index("FIRE_RESULT") < chosen_body.index("gif_for"))
    store = {"fire_inline": {"7:a": {"id": "x", "at": time.time()},
                             "8:b": {"id": "y", "at": time.time()}}}
    inline.forget_user(store, 7)
    check("deleting your data removes your fire clips too", set(store["fire_inline"]) == {"8:b"})
    for lang in i18n.SUPPORTED:
        check(f"the {lang} help says how to mention the bot as a guest",
              "<code>@BOT</code>" in i18n.t("help", lang))


def test_guest() -> None:
    section("guest mode")
    import datetime as _dt
    from telegram import Chat as _Chat, Message as _Message, Update as _Update, User as _User
    from telegram.ext import ApplicationHandlerStop as _Stop

    for typed, expected in (("@getquoto_bot", ("quote", "")),
                            ("@getquoto_bot گیفش کن", ("gif", "")),
                            ("@GetQuoto_Bot /sticker", ("sticker", "")),
                            ("@getquoto_bot آتیشش کن", ("fire", "")),
                            ("@getquoto_bot شاتش کن", ("shot", "")),
                            ("@getquoto_bot سلام دنیا", ("quote", "سلام دنیا")),
                            ("/fire@getquoto_bot از شنبه", ("fire", "از شنبه"))):
        check(f"guest {typed!r}", bot.guest_request(typed, "getquoto_bot") == expected,
              str(bot.guest_request(typed, "getquoto_bot")))

    class GuestBot:
        username = "getquoto_bot"

        def __init__(self):
            self.answers, self.uploads, self.deleted, self.actions = [], [], 0, []

        async def answer_guest_query(self, query_id, result):
            self.answers.append((query_id, result))
            return types.SimpleNamespace(inline_message_id="IM1")

        async def send_chat_action(self, chat_id, action):
            self.actions.append(chat_id)

        def _sent(self, kind):
            bot_ = self

            class Sent:
                photo = [types.SimpleNamespace(file_id=f"{kind}-id")]
                sticker = types.SimpleNamespace(file_id=f"{kind}-id")
                animation = types.SimpleNamespace(file_id=f"{kind}-id")
                document = None

                async def delete(self):
                    bot_.deleted += 1
            return Sent()

        async def send_photo(self, chat, data, **kw):
            self.uploads.append(("photo", chat))
            return self._sent("photo")

        async def send_sticker(self, chat, data, **kw):
            self.uploads.append(("sticker", chat))
            return self._sent("sticker")

        async def send_animation(self, chat, data, **kw):
            self.uploads.append(("animation", chat))
            return self._sent("animation")

        async def get_user_profile_photos(self, user_id, limit=1):
            return types.SimpleNamespace(total_count=0, photos=[])

        async def get_chat(self, chat_id):
            return types.SimpleNamespace(photo=None)

        async def get_chat_member(self, chat_id, user_id):
            return types.SimpleNamespace(status="member")

    now = _dt.datetime.now(_dt.timezone.utc)
    caller = _User(7, "SAli", False, language_code="fa")
    friend = _User(8, "Hedieh", False)
    chat = _Chat(-100777, "supergroup")

    def guest_update(text, reply_text=None):
        replied = (_Message(5, now, chat, from_user=friend, text=reply_text)
                   if reply_text else None)
        message = _Message(9, now, chat, from_user=caller, text=text,
                           reply_to_message=replied, guest_query_id="GQ")
        return _Update(1, guest_message=message)

    def run_guest(text, reply_text=None, started=True, store=-100555):
        b = GuestBot()
        tasks = []
        ctx = types.SimpleNamespace(
            bot=b, user_data={"started": started} if started else {}, bot_data={"exempt": {7}},
            application=types.SimpleNamespace(create_task=lambda c: tasks.append(c) or c.close()))
        saved = bot.STORAGE_CHAT
        bot.STORAGE_CHAT = store
        try:
            asyncio.run(bot.on_guest(guest_update(text, reply_text), ctx))
            stopped = False
        except _Stop:
            stopped = True
        finally:
            bot.STORAGE_CHAT = saved
        return b, ctx, stopped, tasks

    b, ctx, stopped, _ = run_guest("@getquoto_bot", "آدم‌ها عوض نمی‌شن")
    check("a reply and a mention make a card", len(b.answers) == 1
          and b.answers[0][0] == "GQ" and getattr(b.answers[0][1], "photo_file_id", None) == "photo-id")
    check("uploaded to the store and taken down again",
          b.uploads == [("photo", -100555)] and b.deleted == 1)
    check("and nothing else handles a guest message", stopped)

    b, ctx, _, _ = run_guest("@getquoto_bot گیفش کن", "قهوه‌ی سوم")
    check("«گیفش کن» makes a GIF", getattr(b.answers[0][1], "mpeg4_file_id", None) == "animation-id")
    check("filed in the caller's archive, under the person quoted",
          [g["u"] for g in ctx.user_data.get("gifs", [])] == [8])

    b, _, _, _ = run_guest("@getquoto_bot /sticker", "قهوه‌ی سوم")
    check("/sticker makes a sticker", getattr(b.answers[0][1], "sticker_file_id", None) == "sticker-id")

    b, _, _, _ = run_guest("@getquoto_bot شاتش کن", "اینترنت قطع شد")
    check("«شاتش کن» makes a screenshot", getattr(b.answers[0][1], "photo_file_id", None) == "photo-id")

    b, _, _, _ = run_guest("@getquoto_bot حرف خودم")
    check("with no reply, their own words are quoted",
          getattr(b.answers[0][1], "photo_file_id", None) == "photo-id")

    b, _, _, _ = run_guest("@getquoto_bot")
    check("nothing to quote gets the how-to", b.answers and b.answers[0][1].type == "article")

    import fire as _fire
    if _fire.available():
        b, _, _, tasks = run_guest("@getquoto_bot آتیشش کن", "از شنبه، این بار جدی")
        check("fire sends the placeholder first", b.answers
              and getattr(b.answers[0][1], "mpeg4_file_id", None) == "animation-id"
              and b.answers[0][1].reply_markup is not None)
        check("and renders into the message it became", len(tasks) == 1)

    # A guest asks nothing: not Start, not the channel - while there is a store.
    class NotStarted(GuestBot):
        async def send_chat_action(self, chat_id, action):
            from telegram.error import Forbidden as _Forbidden
            raise _Forbidden("bot was blocked by the user")

        async def get_chat_member(self, chat_id, user_id):
            return types.SimpleNamespace(status="left")

    def run_stranger(store):
        b = NotStarted()
        ctx = types.SimpleNamespace(bot=b, user_data={}, bot_data={},
                                    application=types.SimpleNamespace(create_task=lambda c: c.close()))
        saved, saved_channel = bot.STORAGE_CHAT, bot.REQUIRED_CHANNEL
        bot.STORAGE_CHAT, bot.REQUIRED_CHANNEL = store, "@somechannel"
        try:
            asyncio.run(bot.on_guest(guest_update("@getquoto_bot", "آدم‌ها عوض نمی‌شن"), ctx))
        except _Stop:
            pass
        finally:
            bot.STORAGE_CHAT, bot.REQUIRED_CHANNEL = saved, saved_channel
        return b
    # Someone posting as a channel, or as an anonymous admin: the sender Telegram
    # gives is a stand-in bot, and the real one is in sender_chat.
    def run_as_chat(stand_in_id, sender_chat, reply_text="آدم‌ها عوض نمی‌شن", text="@getquoto_bot"):
        b = GuestBot()
        ctx = types.SimpleNamespace(bot=b, user_data={}, bot_data={},
                                    application=types.SimpleNamespace(create_task=lambda c: c.close()))
        stand_in = _User(stand_in_id, "Channel", True)
        replied = (_Message(5, now, chat, from_user=friend, text=reply_text) if reply_text else None)
        message = _Message(9, now, chat, from_user=stand_in, sender_chat=sender_chat, text=text,
                           reply_to_message=replied, guest_query_id="GQ")
        saved = bot.STORAGE_CHAT
        bot.STORAGE_CHAT = -100555
        try:
            asyncio.run(bot.on_guest(_Update(1, guest_message=message), ctx))
        except _Stop:
            pass
        finally:
            bot.STORAGE_CHAT = saved
        return b, ctx
    channel = _Chat(-100999, "channel", title="کانال من")
    b, ctx = run_as_chat(136817688, channel)
    check("someone posting as a channel gets their card",
          b.answers and getattr(b.answers[0][1], "photo_file_id", None) == "photo-id")
    b, ctx = run_as_chat(136817688, channel, reply_text=None, text="@getquoto_bot از طرف کانال")
    check("with no reply, the channel's own words are quoted under the channel",
          b.answers and getattr(b.answers[0][1], "photo_file_id", None) == "photo-id")
    b, ctx = run_as_chat(1087968824, chat, text="@getquoto_bot گیفش کن")
    check("an anonymous admin gets theirs", b.answers
          and getattr(b.answers[0][1], "mpeg4_file_id", None) == "animation-id")
    check("and nothing is filed under the shared stand-in account", not ctx.user_data.get("gifs"))
    b = GuestBot()
    ctx = types.SimpleNamespace(bot=b, user_data={}, bot_data={})
    lone_bot = _Message(9, now, chat, from_user=_User(55, "SomeBot", True), text="@getquoto_bot",
                        reply_to_message=_Message(5, now, chat, from_user=friend, text="hi"),
                        guest_query_id="GQ")
    try:
        asyncio.run(bot.on_guest(_Update(1, guest_message=lone_bot), ctx))
    except _Stop:
        pass
    check("another bot is still ignored", not b.answers)

    # In a group the bot is in, a channel is not asked to press Start.
    asked = []

    async def as_channel_gate():
        message = types.SimpleNamespace(sender_chat=channel,
                                        reply_text=lambda *a, **k: asked.append(a))
        update = types.SimpleNamespace(effective_user=_User(136817688, "Channel", True),
                                       effective_message=message,
                                       effective_chat=types.SimpleNamespace(id=-100777))
        ctx = types.SimpleNamespace(bot=None, user_data={}, bot_data={})
        return (await bot._require_start(update, ctx), await bot._require_channel(update, ctx))
    check("a channel sender passes the Start and channel gates", asyncio.run(as_channel_gate()) == (True, True)
          and not asked)

    b = run_stranger(-100555)
    check("someone who never started the bot, outside the channel, still gets the card",
          b.answers and getattr(b.answers[0][1], "photo_file_id", None) == "photo-id")
    b = run_stranger(None)
    check("without a store, they are asked to start the bot first",
          b.answers and b.answers[0][1].type == "article")
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    body = source[source.index("async def on_guest"):]
    body = body[:body.index("\nasync def ", 10)]
    check("the same gate as inline mode", "_inline_gate(context, user)" in body)
    check("the same cooldown", "_too_soon(context)" in body)
    check("renders wait in the same queue", body.count("throttle.RENDER.run(") >= 4)
    reg = source[source.index("def register"):]
    check("guest messages are handled before anything else in their group",
          reg.index("GUEST_MESSAGE") < reg.index('CommandHandler("start"'))

    # Inline mode is off; the archive is searched in the bot's own chat.
    check("inline handlers are not registered while it is off", bot.INLINE_MODE is False)
    check("nothing offers a switch into inline mode",
          "switch_inline_query" not in source
          and "switch_inline_query" not in (ROOT / "inline.py").read_text(encoding="utf-8"))

    def mygifs_run(args, archive):
        sent, said = [], []

        async def reply_animation(file_id):
            sent.append(file_id)

        async def reply_html(text, **kw):
            said.append(text)

        message = types.SimpleNamespace(chat=types.SimpleNamespace(type="private"),
                                        reply_animation=reply_animation, reply_html=reply_html,
                                        reply_text=reply_html)
        update = types.SimpleNamespace(effective_message=message,
                                       effective_user=types.SimpleNamespace(id=7, language_code="fa"))
        ctx = types.SimpleNamespace(args=args, user_data={"gifs": archive, "lang": "fa"})
        asyncio.run(bot.cmd_mygifs(update, ctx))
        return sent, said

    archive = [{"f": f"F{i}", "u": 8 if i % 2 else 9, "n": "Hedieh" if i % 2 else "Amir",
                "h": "", "q": "", "t": i} for i in range(20)]
    sent, said = mygifs_run([], archive)
    check("/mygifs alone sends the newest few", sent == [f"F{i}" for i in range(19, 19 - bot.MYGIFS_SHOWN, -1)])
    check("and says there are more", len(said) == 2)
    sent, _ = mygifs_run(["hedieh"], archive)
    check("/mygifs name sends that person's", sent and all(int(f[1:]) % 2 for f in sent))
    marked = archive + [{"f": "FX", "u": None, "n": "<b>x", "h": "", "q": "", "t": 99}]
    sent, said = mygifs_run(["<b>x"], marked)
    check("a typed name cannot inject markup",
          sent == ["FX"] and "<b>x" not in said[0] and "&lt;b&gt;x" in said[0], str(said[:1]))


def test_convert() -> None:
    section("converting media")
    import convert
    import gzip as _gzip
    import json as _json
    import subprocess as _sp
    import tempfile as _tempfile

    for said, expected in (("تبدیل به گیف", "gif"), ("تبدیلش کن به استیکر", "sticker"),
                           ("به ویدیو تبدیلش کن", "video"), ("اینو تبدیل کن به عکس", "photo"),
                           ("تبدیل به گیف کن لطفا", "gif"), ("to gif", "gif"),
                           ("convert to sticker", "sticker"), ("تبدیل به فیلم", "video"),
                           ("گیفش کن", None), ("تبدیل به پیتزا", None),
                           ("حرف ما تبدیل به گیف شد", None)):
        check(f"«{said}» -> {expected}", bot.convert_target(said) == expected)
    started = time.perf_counter()
    bot.CONVERT_RE.search("تبدیل به" + " " * 4000 + "x")
    check("the conversion phrase cannot be made to backtrack", time.perf_counter() - started < 0.05)

    # What may be made from what.
    for target, kind, ok in (("gif", "photo", True), ("sticker", "video", True),
                             ("video", "animated_sticker", True), ("photo", "sticker", True),
                             ("photo", "video", False), ("video", "photo", False),
                             ("sticker", "sticker", False)):
        try:
            convert.check(target, kind, 1000)
            allowed = True
        except convert.Unsupported:
            allowed = False
        check(f"{kind} -> {target} {'allowed' if ok else 'refused'}", allowed == ok)
    try:
        convert.check("gif", "video", convert.MAX_INPUT_BYTES + 1)
        refused = False
    except convert.TooBig:
        refused = True
    check("a file past the download limit is refused before fetching", refused)

    def ns(**kw):
        base = dict(sticker=None, animation=None, photo=None, video=None, video_note=None,
                    document=None)
        base.update(kw)
        return types.SimpleNamespace(**base)
    sticker = lambda **kw: types.SimpleNamespace(file_id="S", file_size=10,
                                                 is_animated=False, is_video=False, **kw)
    check("a static sticker is a sticker", convert.media_of(ns(sticker=sticker()))[0] == "sticker")
    check("a .tgs is an animated sticker", convert.media_of(ns(sticker=types.SimpleNamespace(
        file_id="S", file_size=10, is_animated=True, is_video=False)))[0] == "animated_sticker")
    check("a picture sent as a file is a photo", convert.media_of(ns(document=types.SimpleNamespace(
        mime_type="image/png", file_id="D", file_size=5)))[0] == "photo")
    check("text is nothing to convert", convert.media_of(ns()) is None)

    # Every conversion, on real files.
    ff = convert.ffmpeg_exe()
    with _tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        buf = io.BytesIO()
        Image.new("RGB", (900, 600), (40, 90, 160)).save(buf, "JPEG")
        photo = buf.getvalue()
        _sp.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                 "testsrc=size=640x360:rate=25:duration=2", "-c:v", "libx264", "-pix_fmt",
                 "yuv420p", str(tmp / "v.mp4")], check=True)
        video = (tmp / "v.mp4").read_bytes()
        frames = []
        for i in range(30):
            im = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
            ImageDraw.Draw(im).ellipse([40 + i * 6, 156, 240 + i * 6, 356], fill=(30, 90, 230, 255))
            frames.append(im.tobytes())
        _sp.run([ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s",
                 "512x512", "-r", "30", "-i", "-", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                 "-b:v", "200k", "-auto-alt-ref", "0", "-an", str(tmp / "s.webm")],
                input=b"".join(frames), check=True)
        video_sticker = (tmp / "s.webm").read_bytes()
        buf = io.BytesIO()
        st = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        ImageDraw.Draw(st).rectangle([100, 100, 400, 400], fill=(230, 60, 90, 255))
        st.save(buf, "WEBP")
        still_sticker = buf.getvalue()
        lottie = {"v": "5.5.2", "fr": 30, "ip": 0, "op": 30, "w": 512, "h": 512, "assets": [],
                  "layers": [{"ty": 4, "ind": 1, "ip": 0, "op": 30, "st": 0, "sr": 1,
                              "ks": {"o": {"a": 0, "k": 100}, "r": {"a": 0, "k": 0},
                                     "p": {"a": 0, "k": [256, 256, 0]}, "a": {"a": 0, "k": [0, 0, 0]},
                                     "s": {"a": 0, "k": [100, 100, 100]}},
                              "shapes": [{"ty": "gr", "it": [
                                  {"ty": "rc", "d": 1, "s": {"a": 0, "k": [200, 200]},
                                   "p": {"a": 0, "k": [0, 0]}, "r": {"a": 0, "k": 20}},
                                  {"ty": "fl", "c": {"a": 0, "k": [0.2, 0.7, 0.4, 1]},
                                   "o": {"a": 0, "k": 100}},
                                  {"ty": "tr", "p": {"a": 0, "k": [0, 0]}, "a": {"a": 0, "k": [0, 0]},
                                   "s": {"a": 0, "k": [100, 100]}, "r": {"a": 0, "k": 0},
                                   "o": {"a": 0, "k": 100}}]}]}]}
        tgs = _gzip.compress(_json.dumps(lottie).encode())
        samples = {"photo": photo, "video": video, "animation": video,
                   "sticker": still_sticker, "video_sticker": video_sticker,
                   "animated_sticker": tgs}
        expected_ext = {"gif": "mp4", "video": "mp4", "photo": "png"}
        for target, kinds in convert.TARGETS.items():
            for kind in kinds:
                try:
                    data, ext = convert.convert(target, kind, samples[kind])
                    ok = bool(data) and ext == expected_ext.get(
                        target, "webp" if kind == "photo" else "webm")
                    detail = f"{len(data)} bytes .{ext}"
                except Exception as exc:  # noqa: BLE001
                    ok, detail = False, repr(exc)
                check(f"{kind} becomes {target}", ok, detail)
        data, _ = convert.convert("sticker", "video", video)
        check("a video sticker keeps to 256 KB", len(data) <= convert.VIDEO_STICKER_BYTES)
        data, _ = convert.convert("photo", "sticker", still_sticker)
        png = Image.open(io.BytesIO(data)).convert("RGB")
        check("a sticker's transparency becomes white in a photo", png.getpixel((10, 10)) == (255, 255, 255)
              and png.getpixel((256, 256))[0] > 200)
        data, _ = convert.convert("video", "animation", video)
        probe = _sp.run([ff, "-i", "-"], input=data, capture_output=True)
        check("a video gets a sound track, so Telegram keeps it a video",
              b"Audio:" in probe.stderr)
        big = _gzip.compress(b"{" + b" " * (convert.TGS_MAX_JSON + 10) + b"}")
        try:
            convert.convert("video", "animated_sticker", big)
            refused = False
        except convert.Unsupported:
            refused = True
        check("an animated sticker that unpacks into megabytes is refused", refused)

    # The bot replies with the right kind of message, under the media.
    sent = []

    class Reply:
        def __init__(self):
            self.chat = types.SimpleNamespace(send_action=self.noop, type="private")
            self.reply_to_message = types.SimpleNamespace(
                message_id=5, sticker=None, animation=None, video=None, video_note=None,
                document=None, photo=[types.SimpleNamespace(file_id="P", file_size=2000)])

        async def noop(self, *a, **kw):
            return None

        def __getattr__(self, name):
            if name.startswith("reply_"):
                async def record(*a, **kw):
                    sent.append((name, kw.get("reply_to_message_id")))
                return record
            raise AttributeError(name)

    class ConvertBot:
        async def get_file(self, file_id):
            class F:
                file_size = len(photo)

                async def download_as_bytearray(self):
                    return bytearray(photo)
            return F()

    async def run(target):
        message = Reply()
        update = types.SimpleNamespace(effective_message=message,
                                       effective_user=types.SimpleNamespace(id=7, language_code="fa"),
                                       effective_chat=types.SimpleNamespace(id=7))
        ctx = types.SimpleNamespace(bot=ConvertBot(), user_data={"started": True},
                                    bot_data={"exempt": {7}})
        await bot._convert_and_reply(update, ctx, target)
    sent.clear()
    asyncio.run(run("gif"))
    check("a photo made into a GIF is sent as an animation under it", sent == [("reply_animation", 5)], str(sent))
    sent.clear()
    asyncio.run(run("video"))
    check("a photo cannot be made into a video, and says so", sent and sent[0][0] == "reply_text", str(sent))
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    check("conversions wait in their own queue", "throttle.MEDIA.run(convert.convert" in source)
    for target in ("gif", "sticker", "video", "photo"):
        check(f"/to{target} is registered", f'["to{target}"], _convert_command("{target}")' in source)


def test_custom_packs() -> None:
    section("packs of one's own")
    stickerpack.set_salt("a-salt")
    uid = 123456789
    a = stickerpack.custom_name(uid, 1, "getquoto_bot")
    check("a custom pack name says nothing about its owner", str(uid) not in a, a)
    check("and is a name Telegram accepts", re.fullmatch(r"[A-Za-z0-9_]+", a)
          and len(a) <= stickerpack.MAX_NAME and a.endswith("_by_getquoto_bot"))
    check("each pack of the same person differs", a != stickerpack.custom_name(uid, 2, "getquoto_bot"))
    check("and from the personal pack", a != stickerpack.personal_name(uid, "getquoto_bot"))
    for said, ok in (("بذارش تو پک", True), ("اضافه کن به پک", True), ("ببرش تو پک خودم", True),
                     ("add to pack", True), ("پک خوبیه", False), ("بذار بریم", False)):
        check(f"«{said}» {'adds' if ok else 'does not add'}", bot.is_add_phrase(said) == ok)

    class PackBot:
        username = "getquoto_bot"

        def __init__(self, full=False):
            self.sets, self.full, self.calls = {}, full, []

        async def get_sticker_set(self, name):
            from telegram.error import TelegramError as _TE
            if name not in self.sets:
                raise _TE("STICKERSET_INVALID")
            return types.SimpleNamespace(name=name)

        async def create_new_sticker_set(self, user_id, name, title, stickers):
            self.calls.append(("create", name, title, stickers[0].format))
            self.sets[name] = [stickers[0]]

        async def add_sticker_to_set(self, user_id, name, sticker):
            from telegram.error import BadRequest as _BR
            if self.full:
                raise _BR("Stickers_too_much")
            self.calls.append(("add", name, sticker.format))
            self.sets[name].append(sticker)

    def reply_to(sticker_kind="static"):
        st = types.SimpleNamespace(file_id="ST1", emoji="😂", is_animated=sticker_kind == "animated",
                                   is_video=sticker_kind == "video", set_name="x")
        return types.SimpleNamespace(sticker=st, animation=None, photo=None, video=None,
                                     video_note=None, document=None)

    user = types.SimpleNamespace(id=uid)
    saved = bot.OWNER_ID
    bot.OWNER_ID = 42
    try:
        b = PackBot()
        ctx = types.SimpleNamespace(bot=b, user_data={}, bot_data={})
        said = asyncio.run(bot._add_replied(ctx, reply_to(), user, "fa"))
        check("with no pack yet, they are told to make one", "/newpack" in said)

        ctx.user_data["packs"] = [{"n": 1, "title": "میم‌ها"}, {"n": 2, "title": "رفقا"}]
        ctx.user_data["pack_target"] = 1
        said = asyncio.run(bot._add_replied(ctx, reply_to("video"), user, "fa"))
        name1 = stickerpack.custom_name(uid, 1, "getquoto_bot")
        check("the first sticker makes the chosen pack", b.calls and b.calls[0][:2] == ("create", name1)
              and b.calls[0][3] == "video", str(b.calls))
        check("and the answer carries its link", "t.me/addstickers/" + name1 in said)
        said = asyncio.run(bot._add_replied(ctx, reply_to("animated"), user, "fa"))
        check("the next one is added to it", b.calls[-1] == ("add", name1, "animated"))
        ctx.user_data["pack_target"] = 2
        asyncio.run(bot._add_replied(ctx, reply_to(), user, "fa"))
        check("switching the target sends stickers to the other pack",
              b.calls[-1][1] == stickerpack.custom_name(uid, 2, "getquoto_bot"))

        full = PackBot(full=True)
        full.sets[name1] = []
        ctx_full = types.SimpleNamespace(bot=full, bot_data={},
                                         user_data={"packs": [{"n": 1, "title": "میم‌ها"}],
                                                    "pack_target": 1})
        said = asyncio.run(bot._add_replied(ctx_full, reply_to(), user, "fa"))
        check("a full pack is said, not raised", "۱۲۰" in said)
        said = asyncio.run(bot._add_replied(ctx, types.SimpleNamespace(
            sticker=None, animation=None, photo=None, video=None, video_note=None, document=None),
            user, "fa"))
        check("text cannot go in a pack", "ریپلای" in said)
    finally:
        bot.OWNER_ID = saved

    # /newpack.
    def newpack(args, user_data):
        said = []

        async def reply(text, **kw):
            said.append(text)
        message = types.SimpleNamespace(reply_text=reply, reply_html=reply)
        update = types.SimpleNamespace(effective_message=message,
                                       effective_user=types.SimpleNamespace(id=uid, language_code="fa"))
        asyncio.run(bot.cmd_newpack(update, types.SimpleNamespace(args=args, user_data=user_data)))
        return said
    data = {}
    check("/newpack with no name says how", "/newpack" in newpack([], data)[0] and not data.get("packs"))
    newpack(["میم‌های", "گروه"], data)
    check("/newpack makes the pack and aims at it",
          data["packs"] == [{"n": 1, "title": "میم‌های گروه"}] and data["pack_target"] == 1)
    for i in range(stickerpack.MAX_CUSTOM_PACKS):
        newpack([f"p{i}"], data)
    check("there is a ceiling on packs per person", len(data["packs"]) == stickerpack.MAX_CUSTOM_PACKS)

    # Their own packs are theirs to take stickers out of, and nobody else's.
    names = bot._own_pack_names("getquoto_bot", uid, {"packs": [{"n": 3, "title": "t"}]})
    check("/unpack reaches a custom pack", stickerpack.custom_name(uid, 3, "getquoto_bot") in names)
    check("and the personal one", stickerpack.personal_name(uid, "getquoto_bot") in names)
    check("but not another person's", stickerpack.custom_name(uid + 1, 3, "getquoto_bot") not in names)

    # The personal pack can stop filling itself.
    filed = []

    async def announce(auto):
        message = types.SimpleNamespace(chat=types.SimpleNamespace(type="private"))
        update = types.SimpleNamespace(effective_message=message, effective_user=types.SimpleNamespace(id=uid))
        real = stickerpack.add_personal

        async def fake(*a, **kw):
            filed.append(1)
            return None
        stickerpack.add_personal = fake
        try:
            await bot._announce_pack(update, types.SimpleNamespace(
                bot=None, user_data={} if auto is None else {"auto_pack": auto}), b"webp")
        finally:
            stickerpack.add_personal = real
    asyncio.run(announce(None))
    check("by default what is made in private still joins the personal pack", filed == [1])
    asyncio.run(announce(False))
    check("switched off, it does not", filed == [1])

    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    check("a custom pack can be deleted from /delpack", 'callback_data=f"delpack:c{p[\'n\']}"' in source)
    for lang in i18n.SUPPORTED:
        names_ = {n for n, _ in i18n.PRIVATE_ONLY[lang]}
        check(f"/newpack and /packs in the {lang} menu", {"newpack", "packs"} <= names_)


def test_review_fixes() -> None:
    section("review fixes")
    import throttle
    from telegram.error import BadRequest as _BadRequest, NetworkError as _NetworkError

    # arabic_reshaper rebuilt its ligature table on every call; ours keeps it.
    check("the reshaper keeps its ligature table", hasattr(textkit._reshaper, "__ligatures_re"))
    started = time.perf_counter()
    for _ in range(200):
        textkit.shape("سلام دنیا، این یک آزمایش است", True)
    took = time.perf_counter() - started
    check("shaping is quick", took < 0.5, f"{took:.2f}s for 200")
    long_fa = ("این یک جمله‌ی طولانی برای آزمایش است که باید چند خط بشه " * 14)[:700]
    started = time.perf_counter()
    render.build_scene(_avatar(), long_fa, "SEP", "", "portrait")
    took = time.perf_counter() - started
    check("a 700-character quote lays out in well under the seconds it took",
          took < 3.0, f"{took:.2f}s")
    check("plain left-to-right text is not shaped", textkit.shape("hello 123", False) == "hello 123")
    check("a right-to-left line of digits is still ordered right to left",
          textkit.shape("123 456", True) != "123 456")

    # The typing GIF draws a repeated frame once.
    scene = render.build_scene(_avatar(), "کوتاه", "SEP", "", "classic")
    frames = list(animate._iter_frames(scene))
    distinct = len({id(f) for f in frames})
    check("repeated animation frames are reused", distinct < len(frames), f"{distinct}/{len(frames)}")
    check("and the last one shows the name", frames[-1] is frames[-2])

    # Layout waits its turn with the rest of the rendering.
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    build = source[source.index("async def _build_scene"):]
    build = build[:build.index("\nasync def ", 10)]
    check("layout goes through the render gate", "throttle.RENDER.run(" in build)
    check("in inline too", "throttle.RENDER.run(\n                render.build_scene"
          in (ROOT / "inline.py").read_text(encoding="utf-8"))

    # An inline query Telegram closed is not an error, whichever path answers it.
    class ClosedQuery:
        query = "🔥 "
        offset = ""
        id = "q"
        from_user = types.SimpleNamespace(id=7, first_name="a", last_name="", username="",
                                          language_code="fa", is_bot=False)

        async def answer(self, *a, **kw):
            raise _BadRequest("Query is too old and response timeout expired or query id is invalid")

    async def closed_run():
        handler = inline.make_handler("", None, None)
        update = types.SimpleNamespace(inline_query=ClosedQuery(), effective_user=ClosedQuery.from_user)
        ctx = types.SimpleNamespace(user_data={}, bot_data={}, bot=None, application=None)
        try:
            await handler(update, ctx)
            return True
        except Exception:  # noqa: BLE001
            return False
    check("a closed inline query is not raised as an error", asyncio.run(closed_run()))

    # Network trouble is a warning, not a traceback and a "failed" to the user.
    sent = []

    async def error_run(error):
        update = types.SimpleNamespace()
        ctx = types.SimpleNamespace(error=error)
        await bot.on_error(update, ctx)

    import logging as _logging
    records = []
    handler = _logging.Handler()
    handler.emit = records.append
    bot.log.addHandler(handler)
    try:
        asyncio.run(error_run(_NetworkError("Bad Gateway")))
    finally:
        bot.log.removeHandler(handler)
    check("a network error is logged as a warning",
          records and all(r.levelno == _logging.WARNING and not r.exc_info for r in records))

    # Waiting for a pack title does not last for ever.
    renamed = []

    async def title_run(asked):
        ctx = types.SimpleNamespace(user_data={"await_pack_title": asked}, bot=None)
        message = types.SimpleNamespace(text="new title")
        update = types.SimpleNamespace(effective_message=message,
                                       effective_user=types.SimpleNamespace(id=7, language_code="fa"))
        real = stickerpack.rename_personal

        async def fake(bot_, uid, title):
            renamed.append(title)
            return True
        stickerpack.rename_personal = fake

        async def reply(text):
            return None
        message.reply_text = reply
        try:
            await bot.on_pack_title(update, ctx)
        finally:
            stickerpack.rename_personal = real
    asyncio.run(title_run(time.time() - 3600))
    check("a pack title typed long after the button is not taken", renamed == [])
    asyncio.run(title_run(True))
    check("nor one left over from before the wait had a time", renamed == [])
    asyncio.run(title_run(time.time() - 5))
    check("one typed straight after is", renamed == ["new title"])

    unit = (ROOT / "deploy" / "quoto.service").read_text(encoding="utf-8")
    check("a stop lets the request in hand finish", "KillMode=mixed" in unit)
    check("the render gate is shared, not one per caller", isinstance(throttle.RENDER, throttle.Gate))


def test_hardening() -> None:
    section("security fixes")
    import throttle
    import download_fonts

    # Avatars: refused before decoding, not after.
    def png(w, h):
        buf = io.BytesIO()
        Image.new("RGB", (w, h)).save(buf, "PNG")
        return buf.getvalue()

    check("an ordinary picture decodes", authors.decode(png(640, 640)).size == (640, 640))
    try:
        authors.decode(png(4100, 4100))
        refused = False
    except ValueError:
        refused = True
    check("a picture past the pixel limit is refused", refused)
    gif = io.BytesIO()
    Image.new("RGB", (10, 10)).save(gif, "GIF")
    try:
        authors.decode(gif.getvalue())
        refused = False
    except Exception:  # noqa: BLE001
        refused = True
    check("formats a card does not use are refused", refused)
    source = (ROOT / "authors.py").read_text(encoding="utf-8")
    check("decoding happens off the event loop",
          "asyncio.to_thread(decode, data)" in source)

    def doc(mime, size):
        return types.SimpleNamespace(photo=None, document=types.SimpleNamespace(
            mime_type=mime, file_size=size, file_id="F"))
    check("a picture file of photo size is accepted",
          bot._photo_file_id(doc("image/png", 300_000)) == "F")
    check("a huge picture file is not",
          bot._photo_file_id(doc("image/png", 15_000_000)) is None)
    check("an image type a card cannot use is not",
          bot._photo_file_id(doc("image/tiff", 1000)) is None)

    # The avatar cache is bounded by bytes, oldest out first.
    authors._avatar_cache.clear()
    chunk = b"x" * (authors.CACHE_BYTES // 4)
    for i in range(10):
        authors._cache_put(f"k{i}", chunk, "test")
    held = sum(len(v[1] or b"") for v in authors._avatar_cache.values())
    check("the avatar cache stays under its budget", held <= authors.CACHE_BYTES, str(held))
    check("and the newest entry survives", "k9" in authors._avatar_cache)
    check("the oldest went first", "k0" not in authors._avatar_cache)
    authors._avatar_cache.clear()

    # The render gate: a fixed number run, a fixed number wait, the rest are told.
    async def gate_run():
        gate = throttle.Gate(slots=1, queue=1)
        release = __import__("threading").Event()
        first = asyncio.ensure_future(gate.run(release.wait, 5))
        await asyncio.sleep(0.05)
        second = asyncio.ensure_future(gate.run(lambda: "second"))
        await asyncio.sleep(0.05)
        try:
            await gate.run(lambda: "third")
            turned_away = False
        except throttle.Busy:
            turned_away = True
        # The first caller gives up; the thread does not, and its slot is held.
        first.cancel()
        await asyncio.sleep(0.05)
        still_held = not second.done()
        release.set()
        result = await asyncio.wait_for(second, 5)
        return turned_away, still_held, result, gate.pending

    turned_away, still_held, result, pending = asyncio.run(gate_run())
    check("past slots and queue, a request is turned away", turned_away)
    check("an abandoned job keeps its slot until its thread ends", still_held)
    check("then the next one runs", result == "second")
    check("and nothing is left counted", pending == 0, str(pending))
    for name in ("cmd_quote", "cmd_quote_sticker", "cmd_quote_gif", "cmd_screenshot"):
        body = (ROOT / "bot.py").read_text(encoding="utf-8")
        body = body[body.index(f"async def {name}("):]
        body = body[:body.index("\nasync def ", 10)]
        check(f"{name} renders through the gate", "throttle.RENDER.run(" in body)
        check(f"{name} answers when busy", "throttle.Busy" in body)
    inline_source = (ROOT / "inline.py").read_text(encoding="utf-8")
    check("inline renders through the gate",
          inline_source.count("throttle.RENDER.run(") >= 2)
    check("inline has a cooldown between renders", "INLINE_COOLDOWN" in inline_source)

    # Inline cache entries expire.
    ctx = types.SimpleNamespace(bot_data={}, user_data={})
    inline._remember(ctx, "7:x", ("P", "S", None))
    ctx.bot_data["inline_cache"]["7:x"]["at"] -= inline.CACHE_TTL + 1
    check("an expired inline entry is not served", inline._cached(ctx, "7:x") is None)
    ctx.bot_data["inline_cache"]["7:old"] = ("P", "S", None)
    check("an entry from before times were kept is not served",
          inline._cached(ctx, "7:old") is None)
    inline._remember(ctx, "8:y", ("P", "S", None))
    check("expired entries are cleared out", set(ctx.bot_data["inline_cache"]) == {"8:y"})

    # Deleting your data.
    user_store = {7: {"gifs": [1], "lang": "en"}, 8: {"lang": "fa"}}
    app = types.SimpleNamespace(drop_user_data=lambda uid: user_store.pop(uid, None))
    store = {"avatars": {7: "F7", 8: "F8"}, "avatar_source": {7: "custom"},
             "users": {7: {"name": "x"}, 8: {"name": "y"}},
             "avatar_uses": {7: 2}, "blocked": {7}, "channel_members": {7: (0, True)},
             "inline_cache": {"7:a": {"ids": (), "at": time.time()},
                              "8:b": {"ids": (), "at": time.time()}}}
    authors._cache_put("custom:F7", b"img", "x")
    authors._cache_put("user:7:profile photo", b"img", "x")
    bot.forget_user(types.SimpleNamespace(bot_data=store, application=app), 7)
    check("their own data is gone",
          7 not in user_store and 7 not in store["avatars"]
          and 7 not in store["users"] and 7 not in store["avatar_source"]
          and "7:a" not in store["inline_cache"] and 7 not in store["channel_members"])
    check("their cached pictures are gone",
          "custom:F7" not in authors._avatar_cache
          and "user:7:profile photo" not in authors._avatar_cache)
    check("nobody else's is touched",
          8 in user_store and store["avatars"].get(8) == "F8" and "8:b" in store["inline_cache"])
    check("the allowance and a block survive it - they are the rules, not data",
          store["avatar_uses"] == {7: 2} and 7 in store["blocked"])
    authors._avatar_cache.clear()
    for lang in i18n.SUPPORTED:
        check(f"/deletemydata in the {lang} menu",
              "deletemydata" in {n for n, _ in i18n.PRIVATE_ONLY[lang]})

    # Group pack names say nothing about the group.
    stickerpack.set_salt("a-salt")
    gid = -1001234567890
    name = stickerpack.pack_name(gid, "getquoto_bot")
    check("a group's pack name does not contain its id", str(abs(gid)) not in name, name)
    check("and is not the old one", name != stickerpack.legacy_pack_name(gid, "getquoto_bot"))
    check("and differs from a personal one",
          name != stickerpack.personal_name(abs(gid), "getquoto_bot"))

    # An old id-named pack is carried over, sticker for sticker, and left alone.
    from telegram.error import TelegramError as _TE

    class MoveBot:
        username = "getquoto_bot"

        def __init__(self, old_count):
            self.sets = {stickerpack.legacy_pack_name(gid, self.username): [
                types.SimpleNamespace(file_id=f"S{i}", emoji="💬") for i in range(old_count)]}
            self.calls = []

        async def get_sticker_set(self, name):
            if name not in self.sets:
                raise _TE("not found")
            return types.SimpleNamespace(name=name, title="Old", stickers=self.sets[name])

        async def create_new_sticker_set(self, user_id, name, title, stickers):
            self.calls.append(("create", len(stickers)))
            self.sets[name] = [types.SimpleNamespace(file_id=s.sticker, emoji="💬")
                               for s in stickers]

        async def add_sticker_to_set(self, user_id, name, sticker):
            self.calls.append(("add", 1))
            self.sets[name].append(types.SimpleNamespace(file_id=sticker.sticker, emoji="💬"))

    chat = types.SimpleNamespace(type="supergroup", id=gid, title="g")
    mover = MoveBot(old_count=70)
    moved = asyncio.run(stickerpack._adopt_legacy(mover, chat, owner_id=1))
    new_set = mover.sets.get(stickerpack.pack_name(gid, mover.username), [])
    check("an old group pack is carried over", moved and len(new_set) == 70, str(len(new_set)))
    check("in one create of fifty and adds for the rest",
          mover.calls[0] == ("create", 50) and len(mover.calls) == 21)
    check("by the files Telegram already holds", new_set[0].file_id == "S0")
    check("and the old pack is left where it is",
          len(mover.sets[stickerpack.legacy_pack_name(gid, mover.username)]) == 70)
    again = MoveBot(old_count=3)
    asyncio.run(stickerpack._adopt_legacy(again, chat, owner_id=1))
    asyncio.run(stickerpack._adopt_legacy(again, chat, owner_id=1))
    check("it happens once", len(again.calls) == 1)
    nothing = MoveBot(old_count=0)
    nothing.sets.clear()
    check("a group with no old pack gets nothing made for it",
          asyncio.run(stickerpack._adopt_legacy(nothing, chat, owner_id=1)) is False
          and not nothing.calls)

    # The owner's pack tool only reaches this bot's packs.
    for text, expected in (
        ("https://t.me/addstickers/gabc_by_getquoto_bot", "gabc_by_getquoto_bot"),
        ("gabc_by_getquoto_bot", "gabc_by_getquoto_bot"),
        ("https://t.me/addstickers/Animals_by_otherbot", None),
        ("https://t.me/addstickers/Animals", None),
        ("rm -rf /", None),
    ):
        check(f"pack tool reads {text!r}",
              admin.pack_from_text(text, "getquoto_bot") == expected)

    # Logs keep no message text.
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    handler = source[source.index("async def on_error"):source.index("async def post_init")]
    check("an error log does not carry what was written", "message.text!r" not in handler)

    # State and log live where STATE_DIR says.
    check("state goes in the state directory", bot.STATE_FILE.startswith(str(bot.STATE_DIR)))
    check("so does the log", admin.LOG_FILE == bot.LOG_FILE)
    unit = (ROOT / "deploy" / "quoto.service").read_text(encoding="utf-8")
    for line in ("StateDirectory=quoto", "MemoryMax=", "CPUQuota=", "NoNewPrivileges=true",
                 "ProtectSystem=strict", "CapabilityBoundingSet="):
        check(f"service has {line}", line in unit)
    check("the code is not writable by the service", "ReadWritePaths=/opt/quoto" not in unit)

    # Downloads are pinned and checked.
    for fonts_ in (download_fonts.FONTS, download_fonts.APPLE):
        for font, (url, digest) in fonts_.items():
            check(f"{font} comes from a fixed revision",
                  "/main/" not in url and "/master/" not in url and "latest" not in url)
            check(f"{font} has a hash", re.fullmatch(r"[0-9a-f]{64}", digest) is not None)
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        check(f"{line} is pinned exactly", "==" in line and ">" not in line)
        pkg = re.split(r"[\[=]", line)[0].lower()
        check(f"{pkg} is in the lock with hashes",
              re.search(rf"^{re.escape(pkg)}==\S+ \\\n\s+--hash=sha256:", lock,
                        re.MULTILINE | re.IGNORECASE) is not None)

    # No invisible direction marks hiding in the source.
    controls = {0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068,
                0x2069, 0x200E, 0x200F, 0x061C}
    for path in ROOT.glob("*.py"):
        hidden = [c for c in path.read_text(encoding="utf-8") if ord(c) in controls]
        check(f"{path.name} has no bidirectional control characters", not hidden)


def test_fonts() -> None:
    section("fonts")
    check("Vazirmatn present", not fonts.missing_bundled_font())
    for weight in ("regular", "bold", "medium", "serif"):
        font = fonts.load(weight, 40)
        check(f"{weight} loads", font.getlength("آزمایش test") > 0)


def test_api() -> None:
    section("live Telegram (sticker pack round trip)")
    import os

    from dotenv import load_dotenv
    from telegram import Bot

    load_dotenv(ROOT / ".env")
    token = os.getenv("BOT_TOKEN", "").strip()
    owner = int(os.getenv("OWNER_ID", "0") or 0)
    if not token or not owner:
        check("BOT_TOKEN and OWNER_ID set", False, "skipping the live test")
        return

    async def run():
        chat = types.SimpleNamespace(type="supergroup", id=-1009999000002,
                                     title="selftest", photo=None)
        webp = render.to_sticker_webp(
            render.build_scene(_avatar(), "تست", "تست", "").render()).getvalue()
        async with Bot(token) as telegram:
            name = stickerpack.pack_name(chat.id, telegram.username)
            created = await stickerpack.add_quote(telegram, chat, webp, owner)
            check("pack created", created is not None and created[1], str(created))
            appended = await stickerpack.add_quote(telegram, chat, webp, owner)
            check("pack appended", appended is not None and not appended[1], str(appended))
            check("link found", await stickerpack.link_for(telegram, chat) is not None)
            try:
                await telegram.delete_sticker_set(name)
                check("pack deleted", True)
            except Exception as exc:  # noqa: BLE001
                check("pack deleted", False, f"remove {name} by hand: {exc}")

    asyncio.run(run())


# --------------------------------------------------------------------------- security
def test_security() -> None:
    section("access and isolation")
    source = (ROOT / "bot.py").read_text(encoding="utf-8")

    # Identity must always come from the update, never from anything a user typed.
    # The right-hand side is read directly: a lookahead here would be defeated by
    # \s* matching nothing and testing the space instead of the value.
    assigned = re.findall(r"user_id\s*=\s*([A-Za-z_][\w.]*)", source)
    forged = [rhs for rhs in assigned
              if rhs not in {"owner_id", "OWNER_ID"}
              and not rhs.startswith(("update.", "user.", "query."))]
    check("no user id taken from input", not forged, str(forged))

    # Only static catalogue strings may be parsed as HTML.
    html_calls = re.findall(r"reply_html\(([^)]*)\)|parse_mode=\"HTML\"", source)
    # _t is the same lookup with the language already resolved: it takes a key
    # out of the catalogue and nothing else, so it is as safe as i18n.t.
    check("html is only sent for catalogue text",
          all("i18n.t" in c or c.strip().startswith("_t(")
              or "text" == c.strip() for c in html_calls if c),
          str(html_calls))

    class Msg:
        def __init__(self, chat_type):
            self.chat = types.SimpleNamespace(type=chat_type)
            self.photo = [types.SimpleNamespace(file_id="X")]
            self.document = None
            self.reply_to_message = None
            self.out = []
            self.markup = None

        async def reply_text(self, text, reply_markup=None, **kwargs):
            self.out.append(text)
            self.markup = reply_markup

        async def reply_html(self, text, **kwargs):
            self.out.append(text)

    def update_for(message, user_id=7):
        return types.SimpleNamespace(
            effective_message=message,
            effective_user=types.SimpleNamespace(id=user_id, language_code="fa"))

    async def run():
        # Personal settings cannot be changed from a group.
        store = {}
        group = Msg("supergroup")
        await bot.cmd_avatar(update_for(group),
                             types.SimpleNamespace(bot_data=store, user_data={}, args=[]))
        check("avatar refused in a group", not store.get("avatars"))
        group2 = Msg("supergroup")
        await bot.cmd_settings(update_for(group2),
                               types.SimpleNamespace(bot_data=store, user_data={}, args=[]))
        check("settings refused in a group", group2.markup is None)

        # One person's picture cannot be set by another.
        store = {}
        for uid in (11, 22):
            private = Msg("private")
            await bot.cmd_avatar(update_for(private, uid),
                                 types.SimpleNamespace(bot_data=store, user_data={}, args=[]))
        check("pictures stored per user", set(store["avatars"]) == {11, 22})
        check("quota counted per user",
              store["avatar_uses"] == {11: 1, 22: 1}, str(store["avatar_uses"]))

        # A crafted callback value must not become a source.
        edited = []

        async def noop(*args, **kwargs):
            pass

        async def edit(text, **kwargs):
            edited.append(text)

        query = types.SimpleNamespace(data="src:../../etc/passwd",
                                      answer=noop, edit_message_text=edit)
        ctx = types.SimpleNamespace(bot_data=store, user_data={}, args=[])
        await bot.on_source_choice(
            types.SimpleNamespace(callback_query=query,
                                  effective_user=types.SimpleNamespace(id=11, language_code="fa")),
            ctx)
        # Uploading set it to "custom"; a bogus callback must leave that alone.
        check("bad callback value rejected",
              store.get("avatar_source", {}).get(11) == "custom" and not edited,
              str(store.get("avatar_source")))

        # /debug answers nobody but the operator.
        saved = bot.OWNER_ID
        try:
            bot.OWNER_ID = 999
            stranger = Msg("private")
            stranger.reply_to_message = None
            await bot.cmd_debug(update_for(stranger, 7),
                                types.SimpleNamespace(bot_data={}, user_data={}, args=[]))
            check("debug ignores strangers", not stranger.out)
        finally:
            bot.OWNER_ID = saved

    asyncio.run(run())

    # A decompression bomb must never reach the renderer.
    from PIL import Image as PILImage
    check("image size is capped", PILImage.MAX_IMAGE_PIXELS <= 50_000_000,
          str(PILImage.MAX_IMAGE_PIXELS))

    bomb = io.BytesIO()
    Image.new("RGB", (9000, 9000)).save(bomb, "PNG")
    payload = bomb.getvalue()

    class FakeFile:
        async def download_as_bytearray(self):
            return bytearray(payload)

    class FakeBot:
        async def get_file(self, file_id):
            return FakeFile()

        async def get_user_profile_photos(self, user_id, limit=1):
            return types.SimpleNamespace(
                total_count=1, photos=[[types.SimpleNamespace(file_id="x")]])

        async def get_chat(self, chat_id):
            return types.SimpleNamespace(photo=None)

    async def bomb_run():
        authors._avatar_cache.clear()
        author = authors.Author("SAli", "sali", 555, "user", "555")
        image = await authors.fetch_avatar(FakeBot(), author)
        return image.size

    check("oversized picture falls back", asyncio.run(bomb_run()) == (640, 640))

    # One person cannot monopolise the renderer.
    # Inline and the commands must decide a picture the same way. They did not:
    # inline handed the uploaded file to fetch_avatar without the source, and
    # the source is what decides whether that file is used at all - so anyone
    # who had chosen their own picture got their Telegram one in inline mode.
    person = authors.Author("SEP", "sep", 7, "user", "7")
    cases = [
        ("an uploaded picture", {"avatars": {7: "F"}}, ("F", "custom")),
        ("one that was turned off",
         {"avatars": {7: "F"}, "avatar_source": {7: "profile"}}, ("F", "profile")),
        ("the public one", {"avatar_source": {7: "public"}}, (None, "public")),
        ("just the initial", {"avatar_source": {7: "letter"}}, (None, "letter")),
        ("nothing chosen", {}, (None, authors.DEFAULT_SOURCE)),
        ("a source that is not one of ours",
         {"avatar_source": {7: "; drop"}}, (None, authors.DEFAULT_SOURCE)),
        ("a custom source with no file",
         {"avatar_source": {7: "custom"}}, (None, authors.DEFAULT_SOURCE)),
    ]
    for label, data, want in cases:
        got = authors.choice_for(data, person)
        check(f"{label} resolves the same for both", got == want, f"{got} != {want}")
        through_commands = bot._avatar_choice(
            types.SimpleNamespace(bot_data=data), person)
        check(f"{label} is what the commands use too", through_commands == got)

    source = (ROOT / "inline.py").read_text(encoding="utf-8")
    check("inline passes the source, not only the file",
          "authors.choice_for(" in source and "chosen, avatar_source)" in source)
    check("and two sources are two different cached pictures",
          inline.cache_key(7, "custom:F", "classic", "hi")
          != inline.cache_key(7, "profile:F", "classic", "hi"))

    ctx = types.SimpleNamespace(user_data={})
    first = bot._too_soon(ctx)
    second = bot._too_soon(ctx)
    check("first render allowed", not first)
    check("burst suppressed", second)

    # The cooldown is written to disk and read back after a restart. It used to
    # hold time.monotonic(), which counts from a boot; once the machine
    # rebooted, every stored value was far in the future of the new clock, so
    # everyone who had ever made a quote was refused - silently, and until the
    # uptime climbed past the old reading. Two dozen people were, for a
    # fortnight. A stamp ahead of the clock is never treated as recent.
    ctx = types.SimpleNamespace(user_data={"last_render": time.time() + 1_000_000})
    check("a timestamp from the future does not lock anyone out",
          not bot._too_soon(ctx))
    check("and it is replaced with a real one",
          abs(ctx.user_data["last_render"] - time.time()) < 5)

    ctx = types.SimpleNamespace(user_data={"last_render": 1_398_774.0})
    check("a leftover monotonic reading does not either", not bot._too_soon(ctx))

    check("a stamp within the window is fresh",
          bot._fresh(100.0, 101.0, 2.0))
    check("an old stamp is not", not bot._fresh(100.0, 200.0, 2.0))
    check("a future stamp is not", not bot._fresh(200.0, 100.0, 2.0))

    # The token must not be written anywhere the repository tracks.
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check(".env is ignored", ".env" in ignored)
    check("state file is ignored", "botdata.pkl" in ignored)
    # Naming the setting in an error message is fine; printing its value is not.
    leaks = [line.strip() for line in source.splitlines()
             if re.search(r"(log\.\w+|print|reply_text|send_message|SystemExit)"
                          r".*\bTOKEN\b(?!_)", line)
             and "os.getenv" not in line]
    check("token value never printed", not leaks, str(leaks))


# --------------------------------------------------------------------------- admin panel
OWNER = 4242


class _AdminBot:
    """Just enough bot for the panel: it writes down who it told what."""

    def __init__(self, refuse=()):
        self.sent = []
        self.refuse = set(refuse)

    async def send_message(self, chat_id, text, **kwargs):
        from telegram.error import Forbidden
        if chat_id in self.refuse:
            raise Forbidden("blocked")
        self.sent.append((chat_id, text))


def _admin_ctx(store=None, bot=None, people=None):
    ctx = types.SimpleNamespace(bot_data=store if store is not None else {},
                                user_data={}, args=[], bot=bot or _AdminBot())
    # The panel reads the per-user store off the application, which is where
    # a person's language lives and how it knows who has started the bot.
    ctx.application = types.SimpleNamespace(user_data=people or {})
    return ctx


def _admin_update(user_id, chat_type="private", text="/quote", chat_id=-100123,
                  title="گروه تست"):
    message = types.SimpleNamespace(text=text, chat_id=chat_id, replies=[])

    async def reply_text(body, **kwargs):
        message.replies.append(body)

    message.reply_text = reply_text
    message.reply_html = reply_text
    return types.SimpleNamespace(
        effective_user=types.SimpleNamespace(
            id=user_id, is_bot=False, full_name="کاربر", username="u"),
        effective_chat=types.SimpleNamespace(id=chat_id, type=chat_type, title=title),
        effective_message=message,
    )


def test_admin() -> None:
    section("admin panel")

    track = admin.make_tracker(OWNER)

    async def run_track(update, store):
        ctx = _admin_ctx(store)
        try:
            await track(update, ctx)
            return True, ctx
        except ApplicationHandlerStop:
            return False, ctx

    async def run() -> None:
        # Ordinary use is recorded.
        store = {}
        allowed, ctx = await run_track(_admin_update(7, "supergroup"), store)
        check("a user is remembered", allowed and 7 in store["users"])
        check("a group is remembered", -100123 in store["groups"])
        check("the group keeps its title", store["groups"][-100123]["title"] == "گروه تست")

        # A private chat is not filed as a group.
        store = {}
        await run_track(_admin_update(8, "private", chat_id=8), store)
        check("private chats are not groups", not store.get("groups"))

        # Blocking.
        store = {"blocked": {9}}
        allowed, _ = await run_track(_admin_update(9), store)
        check("a blocked user is stopped", not allowed)
        allowed, _ = await run_track(_admin_update(10), store)
        check("everyone else passes", allowed)
        store = {"blocked": {OWNER}}
        allowed, _ = await run_track(_admin_update(OWNER), store)
        check("the owner cannot be locked out", allowed)

        # Pausing.
        store = {"paused": True}
        update = _admin_update(11)
        allowed, _ = await run_track(update, store)
        check("pausing stops a stranger", not allowed)
        check("and says why", any("تعمیر" in r for r in update.effective_message.replies))
        allowed, _ = await run_track(_admin_update(OWNER), store)
        check("pausing lets the owner through", allowed)

    asyncio.run(run())

    # Counting.
    ctx = _admin_ctx()
    admin.note(ctx, "gif")
    admin.note(ctx, "gif")
    admin.note(ctx, "quote")
    check("cards are counted", ctx.bot_data["counts"] == {"gif": 2, "quote": 1})

    # The panel refuses a stranger before it renders anything.
    cmd_admin, on_button, on_input = admin.make_panel(OWNER)

    async def stranger() -> None:
        update = _admin_update(99)
        await cmd_admin(update, _admin_ctx())
        check("the panel ignores strangers", not update.effective_message.replies)
        update = _admin_update(OWNER)
        await cmd_admin(update, _admin_ctx())
        check("the panel opens for the owner", len(update.effective_message.replies) == 1)

    asyncio.run(stranger())

    # An unset OWNER_ID must not turn the panel into an open door.
    open_admin, _, _ = admin.make_panel(None)

    async def nobody() -> None:
        update = _admin_update(1)
        await open_admin(update, _admin_ctx())
        check("no owner means no panel", not update.effective_message.replies)

    asyncio.run(nobody())

    # The owner cannot block themselves out of their own bot.
    async def self_block() -> None:
        ctx = _admin_ctx()
        ctx.user_data["admin_await"] = "block"
        update = _admin_update(OWNER, text=str(OWNER))
        await on_input(update, ctx)
        check("the owner cannot block themselves", OWNER not in ctx.bot_data.get("blocked", set()))

        ctx = _admin_ctx()
        ctx.user_data["admin_await"] = "block"
        update = _admin_update(OWNER, text="not a number")
        await on_input(update, ctx)
        check("a non-numeric id is refused", not ctx.bot_data.get("blocked"))
        check("and the panel keeps waiting", ctx.user_data.get("admin_await") == "block")

        ctx = _admin_ctx({"avatar_uses": {77: 2}})
        ctx.user_data["admin_await"] = "qreset"
        await on_input(_admin_update(OWNER, text="77"), ctx)
        check("a quota can be reset", 77 not in ctx.bot_data["avatar_uses"])

        # Granting is not resetting: the allowance goes up and what they have
        # already spent is left alone, so the count they are shown stays true.
        ctx = _admin_ctx({"avatar_uses": {77: 2}})
        ctx.user_data["admin_await"] = "qgive"
        await on_input(_admin_update(OWNER, text="77 3"), ctx)
        check("a number after the id grants that many",
              admin.extra_quota(ctx, 77) == 3)
        check("and what they spent is untouched", ctx.bot_data["avatar_uses"][77] == 2)
        check("nobody else is given anything", admin.extra_quota(ctx, 78) == 0)

        ctx = _admin_ctx()
        ctx.user_data["admin_await"] = "qgive"
        await on_input(_admin_update(OWNER, text="77"), ctx)
        check("an id on its own grants one", admin.extra_quota(ctx, 77) == 1)

        # The person hears about it, in their own language, and the owner is
        # told whether it got through.
        ctx = _admin_ctx(people={77: {"started": True, "lang": "en"}})
        ctx.user_data["admin_await"] = "qgive"
        update = _admin_update(OWNER, text="77 2")
        await on_input(update, ctx)
        check("the person is told they were granted more",
              ctx.bot.sent and ctx.bot.sent[0][0] == 77)
        check("in their own language, with the number in it",
              "2 more time" in ctx.bot.sent[0][1], ctx.bot.sent[0][1][:60])
        check("and the owner is told it arrived",
              any("خبرش را هم دادم" in r for r in update.effective_message.replies))

        ctx = _admin_ctx(people={77: {"started": True}})
        ctx.user_data["admin_await"] = "qreset"
        await on_input(_admin_update(OWNER, text="77"), ctx)
        check("a reset is announced too", len(ctx.bot.sent) == 1)
        check("in Persian by default", "سهمیهٔ عکس" in ctx.bot.sent[0][1])

        # Somebody who blocked the bot cannot be told, and saying so is the
        # moment the bot finds out they are gone.
        people = {77: {"started": True}}
        ctx = _admin_ctx(bot=_AdminBot(refuse={77}), people=people)
        ctx.user_data["admin_await"] = "qgive"
        update = _admin_update(OWNER, text="77")
        await on_input(update, ctx)
        check("the grant still happens when they cannot be reached",
              admin.extra_quota(ctx, 77) == 1)
        check("the owner is told it did not arrive",
              any("نتوانستم خبرش کنم" in r for r in update.effective_message.replies))
        check("and they stop counting as a user", not people[77]["started"])

        ctx = _admin_ctx()
        ctx.user_data["admin_await"] = "qgive"
        await on_input(_admin_update(OWNER, text="77 999999"), ctx)
        check("a silly number is capped", admin.extra_quota(ctx, 77) <= 50,
              str(admin.extra_quota(ctx, 77)))

        # Everyone at once, and it reaches people the bot has never seen.
        ctx = _admin_ctx({"avatar_uses": {77: 2, 78: 1}})
        admin.grant_quota(ctx, None, 2)
        check("everyone gets it", admin.extra_quota(ctx, 12345) == 2)
        check("and it stacks with a personal grant",
              (admin.grant_quota(ctx, 77, 1), admin.extra_quota(ctx, 77))[1] == 3)
        check("resetting everyone clears every count",
              admin.reset_quota(ctx, None) == 2 and not ctx.bot_data["avatar_uses"])
        check("but not what was granted", admin.extra_quota(ctx, 77) == 3)

        # Nothing typed while the panel is idle is ever acted on.
        ctx = _admin_ctx()
        await on_input(_admin_update(OWNER, text="123"), ctx)
        check("idle input is ignored", not ctx.bot_data)

    asyncio.run(self_block())

    # Emptying the queue: what is in hand goes, and a line is drawn in time.
    queue = asyncio.Queue()
    for i in range(3):
        queue.put_nowait(i)
    ctx = _admin_ctx()
    ctx.application = types.SimpleNamespace(update_queue=queue)
    before = time.time()
    check("waiting updates are dropped", admin.flush_queue(ctx) == 3)
    check("the queue is empty after", queue.empty())
    check("a cutoff is recorded", ctx.bot_data["queue_cutoff"] >= before)
    ctx = _admin_ctx()
    check("no queue is not an error", admin.flush_queue(ctx) == 0)
    check("and a cutoff is still set", "queue_cutoff" in ctx.bot_data)

    # The screens render, and their numbers are the ones in bot_data.
    store = {"users": {1: {"seen": time.time(), "first": time.time()}},
             "groups": {-1: {"title": "یک", "seen": time.time()}},
             "counts": {"quote": 3}}
    ctx = _admin_ctx(store)
    check("home reports the totals", "3" in admin._home_text(ctx))
    check("stats name every kind",
          all(label in admin._stats_text(ctx) for _, label in admin.KINDS))
    text, _ = admin._groups_page(ctx, 0)
    check("groups list themselves", "یک" in text)
    beyond, _ = admin._groups_page(ctx, 99)
    check("a page past the end clamps", "صفحهٔ 1 از 1" in beyond)
    empty, _ = admin._groups_page(_admin_ctx(), 0)
    check("no groups reads plainly", "هنوز" in empty)
    check("the log screen renders", "لاگ" in admin._log_text())

    # A group title with markup in it must not reach Telegram as markup.
    ctx = _admin_ctx({"groups": {-5: {"title": "<b>x</b>", "seen": time.time()}}})
    text, _ = admin._groups_page(ctx, 0)
    check("group titles are escaped", "<b>x</b>" not in text and "&lt;b&gt;" in text)

    # The panel is the operator's, so it is in no published menu.
    listed = {name for lang in i18n.SUPPORTED
              for name, _ in i18n.COMMANDS[lang] + i18n.PRIVATE_ONLY[lang]}
    check("admin is unlisted", "admin" not in listed and "panel" not in listed)


# --------------------------------------------------------------------------- fallback fonts
def _ink(img: Image.Image, box) -> int:
    """How many pixels in this box are not the background colour."""
    crop = img.convert("RGB").crop(box)
    background = crop.getpixel((0, 0))
    return sum(1 for pixel in crop.get_flattened_data() if pixel != background)


def test_no_double_shaping() -> None:
    section("layout engine")

    from PIL import Image, ImageDraw, ImageFont

    font = fonts.load("medium", 40)
    engine = font.primary.layout_engine
    check("fonts are opened with the basic layout engine",
          engine == ImageFont.Layout.BASIC, str(engine))

    # The real check, and the one that fails on a Pillow built with libraqm if
    # the engine is ever let go. Text arrives here already reshaped: in
    # presentation forms, in visual order. A layout engine that shapes it again
    # turns every letter back into its isolated form, so an initial seen and an
    # isolated seen - two different shapes - come out as the same pixels. That
    # is exactly how Persian ended up reversed and unjoined on the server.
    def ink(ch: str) -> bytes:
        img = Image.new("L", (90, 90), 0)
        fonts.load("medium", 48).draw_on(
            ImageDraw.Draw(img), (45, 45), ch, fill=255, anchor="mm")
        return img.tobytes()

    initial, isolated = "ﺳ", "ﺱ"   # SEEN, joined on the left vs alone
    check("a joined letter is not drawn as a lone one", ink(initial) != ink(isolated))

    # And the shaped sentence keeps the first word on the right, where Persian
    # puts it.
    shaped = textkit.shape("تست سرور", True)
    check("the shaped line is in visual order", shaped[0] == "ﺭ", hex(ord(shaped[0])))


def test_fallback_fonts() -> None:
    section("other scripts")

    vazir = fonts.FONT_DIR / "Vazirmatn-Regular.ttf"
    if vazir.exists():
        covered = fonts._coverage(vazir)
        check("the bundled font's table is readable", len(covered) > 200, str(len(covered)))
        check("it has Persian", ord("س") in covered)
        check("it has Latin", ord("A") in covered)
        check("it has no Chinese", ord("你") not in covered)

    available = fonts._available_fallbacks()
    check("fallback fonts were found", bool(available),
          "none on this machine; other scripts will still draw as boxes")

    font = fonts.load("medium", 40)
    check("a font set stands in for a font",
          hasattr(font, "getlength") and hasattr(font, "draw_on"))
    check("Persian stays in one run", len(font.runs("سلام دنیا")) == 1)
    check("an empty string has no runs", font.runs("") == [])

    # Width has to account for the fallback, or wrapping would overflow.
    check("width is measured across runs",
          font.getlength("سلام 你好") > font.getlength("سلام "))

    if available:
        runs = font.runs("你好")
        check("Chinese leaves the primary font", runs[0][1] is not font.primary)
        mixed = font.runs("سلام 你好 ok")
        check("a mixed line splits into runs", len(mixed) >= 3)
        check("and loses nothing", "".join(part for part, _ in mixed) == "سلام 你好 ok")

    # Nothing on earth draws a private-use character; it must not raise.
    # Plane 16 is unassigned, so no font claims it and the primary draws the box.
    lonely = font.runs("\U0010FFFD")
    check("an undrawable character falls back to the primary",
          len(lonely) == 1 and lonely[0][1] is font.primary)

    # The real proof: ink on the card where there used to be boxes.
    if available:
        box = (render.TEXT_X, 150, render.WIDTH - 40, render.HEIGHT - 200)
        avatar = render.fallback_avatar("x", "K")
        chinese = _ink(render.render_quote(avatar, "你好世界，这是测试", "王"), box)
        korean = _ink(render.render_quote(avatar, "안녕하세요 테스트입니다", "김"), box)
        check("Chinese draws something", chinese > 500, str(chinese))
        check("Korean draws something", korean > 500, str(korean))

        # A name in another script reaches the avatar tile too, which is a single
        # run and so took a different path through the drawing code.
        tile = render.fallback_avatar("y", "김")
        check("an initial in another script draws",
              _ink(tile, (0, 0, tile.width, tile.height)) > 200)

    # Every anchor the renderer uses must survive the multi-font path.
    img = Image.new("RGB", (400, 120), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    small = fonts.load("regular", 28)
    for i, anchor in enumerate(("la", "ma", "ra", "lm", "rs")):
        small.draw_on(draw, (200, 10 + i), "a你b", fill=(255, 255, 255), anchor=anchor)
    check("every anchor draws without error", _ink(img, (0, 0, 400, 120)) > 0)


def main() -> int:
    test_text()
    test_i18n()
    test_command_menus()
    test_render()
    test_templates()
    test_animation()
    test_avatars()
    test_bot_logic()
    test_admin()
    test_quota()
    test_inline_results()
    test_persisted_state()
    test_gif_archive()
    test_storage_channel()
    test_reactions()
    test_reaction_row()
    test_badges()
    test_gates()
    test_handler_groups()
    test_wallpaper()
    test_extract()
    test_pack_removal()
    test_personal_pack()
    test_pack_editing()
    test_pack_deletion()
    test_pack_names()
    test_fonts()
    test_fire()
    test_inline_fire()
    test_hardening()
    test_review_fixes()
    test_guest()
    test_convert()
    test_custom_packs()
    test_no_double_shaping()
    test_fallback_fonts()
    test_security()
    if "--api" in sys.argv:
        test_api()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    for name in FAIL:
        print(f"  failed: {name}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
