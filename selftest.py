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
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import animate  # noqa: E402
import authors  # noqa: E402
import bot  # noqa: E402
import extract  # noqa: E402
import fonts  # noqa: E402
import i18n  # noqa: E402
import inline  # noqa: E402
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
    check("fancy letters folded", textkit.normalize_display("\U0001D4D9\U0001D4FE\U0001D4FC\U0001D4FD") == "Just")
    check("fullwidth folded", textkit.normalize_display("ＪＵＳＴ") == "JUST")
    check("small caps folded", textkit.normalize_display("ᴊᴜsᴛ") == "just")
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
    async def stale(minutes, has_message=True):
        message = None
        if has_message:
            message = types.SimpleNamespace(
                date=datetime.now(timezone.utc) - timedelta(minutes=minutes),
                chat_id=-1)
        try:
            await bot.ignore_stale(types.SimpleNamespace(message=message), None)
            return True
        except Exception:
            return False

    check("fresh message passes", asyncio.run(stale(1)))
    check("old message stopped", not asyncio.run(stale(30)))
    check("button press unaffected", asyncio.run(stale(999, has_message=False)))

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

        async def reply_html(self, text, **kwargs):
            self.out.append(text)

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


def test_extract() -> None:
    section("extract")
    def message(text):
        return types.SimpleNamespace(text=text, caption=None)
    check("plain text kept", extract.quote_text(message("سلام")) == "سلام")
    check("emoji-only is textless", extract.quote_text(message("😂😂")) is None)
    check("blank is textless", extract.quote_text(message("   ")) is None)
    long_text = extract.quote_text(message("ا" * 900))
    check("long text truncated", len(long_text) <= extract.MAX_QUOTE_CHARS + 1)


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


def main() -> int:
    test_text()
    test_i18n()
    test_render()
    test_animation()
    test_avatars()
    test_bot_logic()
    test_quota()
    test_extract()
    test_pack_names()
    test_fonts()
    test_security()
    if "--api" in sys.argv:
        test_api()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    for name in FAIL:
        print(f"  failed: {name}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
