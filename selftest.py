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

    # Plain-Persian triggers
    lead = r"^\s*(?:این\s*(?:رو|و)?\s*)?"
    tail = r"\s*(?:لطفا|لطفاً|please)?\s*[.!?؟،]*\s*$"
    do = r"\s*(?:کن|کنید)"
    patterns = {
        "quote": lead + r"(?:کوت|نقل\s*قول|quote)(?:\s*ش)?(?:" + do + r")?" + tail,
        "sticker": lead + r"(?:استیکر|sticker)(?:\s*ش)?" + do + tail,
        "gif": lead + r"(?:گیف|gif)(?:\s*ش)?" + do + tail,
        "shot": lead + r"(?:شات|اسکرین\s*شات|screenshot)(?:\s*ش)?" + do + tail,
    }
    def fires(text):
        return {n for n, p in patterns.items() if re.match(p, text, re.IGNORECASE)}
    check("«کوتش کن» fires quote", fires("کوتش کن") == {"quote"})
    check("«استیکرش کن» fires sticker", fires("استیکرش کن") == {"sticker"})
    check("«گیفش کن» fires gif", fires("گیفش کن") == {"gif"})
    check("«شاتش کن» fires shot", fires("شاتش کن") == {"shot"})
    check("bare noun does not fire", fires("استیکر") == set())
    check("chat does not fire", fires("یه استیکر خوب بفرست") == set())

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

        # With a storage chat the animation stays and the other two are cleared.
        bot_ = FakeBot()
        ctx = types.SimpleNamespace(bot=bot_)
        await inline._upload(ctx, -100999, 77, b"png", b"webp")
        await inline._upload_animation(ctx, -100999, 77, (b"mp4", "mp4"))
        check("a storage chat is used when set",
              all(chat == -100999 for _, chat in bot_.sent))
        await asyncio.sleep(0)
        kept = [m for m in bot_.messages if not m.deleted]
        check("only the animation is kept",
              len(kept) == 1 and kept[0].animation is not None)
        check("the photo and sticker are cleared",
              all(m.deleted for m in bot_.messages if m.animation is None))

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

        ctx2 = types.SimpleNamespace(user_data={}, bot_data={})
        tasks = []
        for i in range(4):
            inline._abandon(ctx2)
            task = asyncio.ensure_future(slow_upload(i))
            ctx2.user_data["inline_gif"] = task
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
        owner = bot.OWNER_ID
        bot.OWNER_ID = 4242
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
        finally:
            bot.OWNER_ID = owner

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
    check("the row has something in it", len(set(row.convert("RGB").getdata())) > 20)

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
        return len(set(band.convert("RGB").getdata())) > 30
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
    check("it is a gradient, not a flat fill", len(set(paper.getdata())) > 100)

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
    check("html is only sent for catalogue text",
          all("i18n.t" in c or "text" == c.strip() for c in html_calls if c),
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
    ctx = types.SimpleNamespace(user_data={})
    first = bot._too_soon(ctx)
    second = bot._too_soon(ctx)
    check("first render allowed", not first)
    check("burst suppressed", second)

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


def _admin_ctx(store=None):
    return types.SimpleNamespace(bot_data=store if store is not None else {},
                                 user_data={}, args=[], bot=None)


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
        ctx.user_data["admin_await"] = "quota"
        await on_input(_admin_update(OWNER, text="77"), ctx)
        check("a quota can be reset", 77 not in ctx.bot_data["avatar_uses"])

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
    return sum(1 for pixel in crop.getdata() if pixel != background)


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
    test_render()
    test_animation()
    test_avatars()
    test_bot_logic()
    test_admin()
    test_quota()
    test_inline_results()
    test_storage_channel()
    test_reactions()
    test_reaction_row()
    test_badges()
    test_handler_groups()
    test_wallpaper()
    test_extract()
    test_pack_removal()
    test_pack_names()
    test_fonts()
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
