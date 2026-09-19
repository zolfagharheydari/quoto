"""Renders the quote card: grayscale portrait fading into black, quote, author."""
from __future__ import annotations

import colorsys
import hashlib
import io
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

import fonts
import textkit

# Pillow only refuses an image above ~178 megapixels and merely warns between 89
# and 178, so a 300 KB PNG can still force a 330 MB decode. A picture of a person
# is never near this, and anything past it is refused before a byte is decoded.
Image.MAX_IMAGE_PIXELS = 40_000_000

WIDTH, HEIGHT = 1200, 675
PHOTO_W = int(WIDTH * 0.46)          # portrait occupies the left ~46%
FADE_START = 0.52                    # fraction of PHOTO_W where the fade to black begins
TEXT_X = int(WIDTH * 0.52)
TEXT_W = WIDTH - TEXT_X - int(WIDTH * 0.06)

BG = (0, 0, 0)
QUOTE_COLOR = (244, 244, 244)
NAME_COLOR = (255, 255, 255)
HANDLE_COLOR = (150, 150, 150)
MARK_COLOR = (105, 105, 105)

AVATAR_PALETTE = [
    (200, 90, 80), (90, 130, 200), (95, 175, 120),
    (200, 150, 70), (150, 105, 190), (80, 170, 180),
]


@dataclass
class Scene:
    """A rendered card that can be drawn at any text-reveal progress (for animation)."""

    background: Image.Image
    lines: list[str]
    quote_font: object
    line_height: int
    quote_top: int
    name: str
    name_font: object
    name_y: int
    rtl: bool = False
    watermark: str = ""
    watermark_font: object = None
    # Where the words sit and what colour they are: the three templates differ
    # in this and in the background, and in nothing else - which is what lets
    # one animator draw all of them.
    center_x: int = TEXT_X + TEXT_W // 2
    quote_color: tuple = QUOTE_COLOR
    name_color: tuple = NAME_COLOR
    mark_color: tuple = MARK_COLOR
    fade_to: tuple = (0, 0, 0)
    _shaped: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._shaped = [textkit.shape(line, self.rtl) for line in self.lines]

    def render(self, reveal: float = 1.0, author_alpha: float = 1.0) -> Image.Image:
        img = self.background.copy()
        draw = ImageDraw.Draw(img)
        cx = self.center_x

        total = sum(len(line) for line in self.lines) or 1
        budget = int(total * max(0.0, min(1.0, reveal)))
        for i, logical in enumerate(self.lines):
            if budget <= 0:
                break
            visible = logical if budget >= len(logical) else logical[:budget]
            budget -= len(logical)
            text = (self._shaped[i] if visible == logical
                    else textkit.shape(visible, self.rtl))
            self.quote_font.draw_on(
                draw, (cx, self.quote_top + i * self.line_height), text,
                fill=self.quote_color, anchor="ma")

        if author_alpha > 0:
            a = max(0.0, min(1.0, author_alpha))
            self.name_font.draw_on(
                draw, (cx, self.name_y), textkit.shape(self.name),
                fill=_fade(self.name_color, a, self.fade_to), anchor="ma")

        if self.watermark:
            self.watermark_font.draw_on(draw, (WIDTH - 24, HEIGHT - 22), self.watermark,
                                        fill=self.mark_color, anchor="rs")
        return img


def _fade(color: tuple[int, int, int], alpha: float,
          toward: tuple[int, int, int] = (0, 0, 0)) -> tuple[int, int, int]:
    """The name fading in, from whatever it is fading out of.

    On the dark templates that is black; on the light card it is the paper,
    because a dark name fading towards black would darken in instead of
    appearing.
    """
    return tuple(int(t + (c - t) * alpha) for c, t in zip(color, toward))


def fallback_avatar(seed: str, letter: str, size: int = 640) -> Image.Image:
    """Colored gradient tile with an initial, for users with no profile photo."""
    digest = hashlib.md5(seed.encode()).digest()
    base = AVATAR_PALETTE[digest[0] % len(AVATAR_PALETTE)]
    img = Image.new("RGB", (size, size), base)
    top = Image.new("RGB", (size, size), tuple(min(255, c + 55) for c in base))
    mask = Image.linear_gradient("L").resize((size, size))
    img = Image.composite(img, top, mask)
    draw = ImageDraw.Draw(img)
    font = fonts.load("bold", int(size * 0.45))
    font.draw_on(draw, (size // 2, size // 2), textkit.shape(letter or "?"),
                 fill=(255, 255, 255), anchor="mm")
    return img


def _cover(img: Image.Image, box: tuple[int, int]) -> Image.Image:
    """Resize + center-crop so the image exactly fills `box` without distortion."""
    bw, bh = box
    scale = max(bw / img.width, bh / img.height)
    resized = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                         Image.LANCZOS)
    left = (resized.width - bw) // 2
    top = int((resized.height - bh) * 0.35)  # bias upward: faces sit above center
    top = max(0, min(top, resized.height - bh))
    return resized.crop((left, top, left + bw, top + bh))


def _fade_mask(width: int, height: int) -> Image.Image:
    """Horizontal alpha ramp: opaque on the left, transparent where it meets the black."""
    start = int(width * FADE_START)
    row = []
    for x in range(width):
        if x <= start:
            row.append(255)
        else:
            t = (x - start) / max(1, width - start)
            row.append(int(255 * (1 - t) ** 1.6))
    strip = Image.new("L", (width, 1))
    strip.putdata(row)
    return strip.resize((width, height))


def build_background(avatar: Image.Image, bg: tuple = BG) -> Image.Image:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), bg)
    photo = _cover(avatar.convert("RGB"), (PHOTO_W, HEIGHT))
    photo = ImageEnhance.Contrast(photo).enhance(1.06)
    photo = ImageEnhance.Brightness(photo).enhance(0.95)
    canvas.paste(photo, (0, 0), _fade_mask(PHOTO_W, HEIGHT))
    return canvas


def _dominant(img: Image.Image) -> tuple[int, int, int]:
    """The colour the picture is mostly made of, pulled back to a usable one.

    Taken straight, this is unusable half the time: a photo against a white wall
    gives near-white, a night shot gives near-black, and the card either
    disappears into its frame or the frame turns into the plain black template.
    Hue and a floor of saturation are kept; lightness is pushed into a band
    where a white card still reads against it and dark type on the frame still
    reads too.
    """
    small = img.convert("RGB").resize((40, 40)).quantize(
        colors=5, method=Image.MEDIANCUT)
    palette = small.getpalette()
    best = max(small.getcolors(), key=lambda c: c[0])[1]
    r, g, b = (c / 255 for c in palette[best * 3:best * 3 + 3])
    h, light, sat = colorsys.rgb_to_hls(r, g, b)
    light = min(0.60, max(0.34, light))
    sat = min(0.85, max(0.22, sat))
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, light, sat))


def _shade(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(c * factor))) for c in color)


def _circle(img: Image.Image, size: int) -> Image.Image:
    """The picture as a round badge, drawn large and shrunk so the edge is clean."""
    side = min(img.size)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    face = img.convert("RGB").crop(
        (left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)
    big = size * 4
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, big - 1, big - 1], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(face, (0, 0), mask.resize((size, size), Image.LANCZOS))
    return out


def _prepare(quote: str, name: str) -> tuple[str, str, bool]:
    # Decorative Unicode in a name or a message would draw as empty boxes.
    quote = textkit.normalize_display(quote)
    name = textkit.normalize_display(name)
    quote = " ".join(quote.split()) if "\n" not in quote else quote.strip()
    return quote, name, textkit.is_rtl(quote)


def _fit(body: str, rtl: bool, width: int, height: int, sizes: range):
    """Lay the quote out, and cut it off rather than let it shrink out of sight."""
    # A Persian quote needs Vazirmatn; a Latin one looks closer to the reference
    # in serif.
    weight = "medium" if rtl else "serif"
    loader = lambda s: fonts.load(weight, s)  # noqa: E731
    lines, font, line_height = textkit.fit(
        body, loader, width, height, sizes, line_spacing=1.34, rtl=rtl)
    max_lines = max(1, height // line_height)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip() + "…"
    return lines, font, line_height


def _classic(avatar, quote, name, watermark, rtl, tinted: bool = False) -> Scene:
    """The original: the portrait fading into black, the words to its right.

    `tinted` keeps every line of it and changes one thing - the side the words
    sit on is a dark shade of the photo's own colour instead of flat black.
    """
    # A straight quote for Persian: it is symmetric, so it needs none of the
    # mirroring the guillemets did, and it reads the same at both ends.
    open_q, close_q = ('"', '"') if rtl else ("“", "”")
    max_text_h = int(HEIGHT * 0.68)

    # A long quote used to shrink to 22px, which is unreadable at a glance; 30 is
    # the floor now, and anything that still will not fit is trimmed instead.
    lines, quote_font, line_height = _fit(
        f"{open_q}{quote}{close_q}", rtl, TEXT_W, max_text_h, range(60, 29, -2))

    quote_h = len(lines) * line_height
    # Only the name sits under the quote now, so the text block gets the rest.
    top = (HEIGHT - (quote_h + 56 + 36)) // 2

    base = _dominant(avatar) if tinted else None
    side = _shade(base, 0.28) if tinted else BG
    return Scene(
        background=build_background(avatar, side),
        lines=lines,
        quote_font=quote_font,
        line_height=line_height,
        quote_top=top,
        rtl=rtl,
        name=f"- {name}" if not rtl else f"— {name}",
        name_font=fonts.load("bold", 36),
        name_y=top + quote_h + 56,
        watermark=watermark,
        watermark_font=fonts.load("regular", 19),
        quote_color=(247, 246, 242) if tinted else QUOTE_COLOR,
        # The watermark has to lift off a coloured side, not off black, so it
        # is a lighter shade of that side rather than the fixed grey.
        mark_color=_shade(base, 0.75) if tinted else MARK_COLOR,
        fade_to=side,
    )


def _tinted(avatar, quote, name, watermark, rtl) -> Scene:
    """The original card, with the side beside the portrait taking the photo's colour."""
    return _classic(avatar, quote, name, watermark, rtl, tinted=True)


def _portrait(avatar, quote, name, watermark, rtl) -> Scene:
    """The picture filling the card, blurred and dimmed, the words over it."""
    open_q, close_q = ('"', '"') if rtl else ("“", "”")
    lines, quote_font, line_height = _fit(
        f"{open_q}{quote}{close_q}", rtl, int(WIDTH * 0.78), int(HEIGHT * 0.44),
        range(60, 29, -2))

    block = len(lines) * line_height
    top = (HEIGHT - block) // 2 + 26
    face_size = 108

    canvas = _cover(avatar.convert("RGB"), (WIDTH, HEIGHT))
    canvas = canvas.filter(ImageFilter.GaussianBlur(7))
    canvas = ImageEnhance.Brightness(canvas).enhance(0.42)
    face = _circle(avatar, face_size)
    canvas.paste(face, ((WIDTH - face_size) // 2, top - 150), face)

    return Scene(
        background=canvas,
        lines=lines,
        quote_font=quote_font,
        line_height=line_height,
        quote_top=top,
        rtl=rtl,
        name=name,
        name_font=fonts.load("bold", 34),
        name_y=top + block + 34,
        watermark=watermark,
        watermark_font=fonts.load("regular", 19),
        center_x=WIDTH // 2,
        quote_color=(255, 255, 255),
        name_color=(225, 225, 225),
        mark_color=(200, 200, 200),
    )


def _card(avatar, quote, name, watermark, rtl) -> Scene:
    """A pale card on a frame coloured by the picture itself."""
    base = _dominant(avatar)
    lines, quote_font, line_height = _fit(
        quote, rtl, int(WIDTH * 0.62), int(HEIGHT * 0.36), range(58, 29, -2))

    block = len(lines) * line_height
    top = (HEIGHT - block) // 2 + 22
    face_size = 96
    paper = (250, 249, 246)

    canvas = Image.new("RGB", (WIDTH, HEIGHT), base)
    # A flat rectangle of colour looks like a mistake; a very soft glow behind
    # the card is enough to make it look lit.
    glow = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(glow).ellipse(
        [-WIDTH // 3, -HEIGHT, WIDTH + WIDTH // 3, HEIGHT + HEIGHT // 2], fill=90)
    canvas = Image.composite(
        Image.new("RGB", (WIDTH, HEIGHT), tuple(min(255, c + 45) for c in base)),
        canvas, glow.filter(ImageFilter.GaussianBlur(120)))

    pad = 64
    box = [pad, pad, WIDTH - pad, HEIGHT - pad]
    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [box[0], box[1] + 6, box[2], box[3] + 6], radius=34, fill=(0, 0, 0, 70))
    canvas = Image.alpha_composite(
        canvas.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(18)))
    ImageDraw.Draw(canvas).rounded_rectangle(box, radius=34, fill=paper)

    face = _circle(avatar, face_size)
    canvas.paste(face, ((WIDTH - face_size) // 2, top - 150), face)

    return Scene(
        background=canvas.convert("RGB"),
        lines=lines,
        quote_font=quote_font,
        line_height=line_height,
        quote_top=top,
        rtl=rtl,
        name=name,
        name_font=fonts.load("bold", 30),
        name_y=top + block + 30,
        watermark=watermark,
        watermark_font=fonts.load("regular", 19),
        center_x=WIDTH // 2,
        quote_color=(28, 28, 30),
        name_color=_shade(base, 0.8),
        # The watermark sits on the frame, not on the card, so it is shaded
        # against the frame's own colour.
        mark_color=_shade(base, 0.55),
        fade_to=paper,
    )


TEMPLATES = {
    "classic": _classic,
    "tinted": _tinted,
    "portrait": _portrait,
    "card": _card,
}
# The order they are offered in, and the numbers people see beside them.
TEMPLATE_ORDER = ["classic", "tinted", "portrait", "card"]
DEFAULT_TEMPLATE = "classic"


def build_scene(avatar: Image.Image, quote: str, name: str,
                watermark: str = "", template: str = DEFAULT_TEMPLATE) -> Scene:
    quote, name, rtl = _prepare(quote, name)
    builder = TEMPLATES.get(template, TEMPLATES[DEFAULT_TEMPLATE])
    return builder(avatar, quote, name, watermark, rtl)


def render_quote(avatar: Image.Image, quote: str, name: str,
                 watermark: str = "", template: str = DEFAULT_TEMPLATE) -> Image.Image:
    return build_scene(avatar, quote, name, watermark, template).render()


def to_png(img: Image.Image) -> io.BytesIO:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf


def to_sticker_webp(img: Image.Image) -> io.BytesIO:
    """Telegram static stickers: WEBP, longest side exactly 512px, under 512 KB."""
    scale = 512 / max(img.size)
    resized = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                         Image.LANCZOS)
    for quality in (92, 80, 68, 55, 42):
        buf = io.BytesIO()
        resized.save(buf, "WEBP", quality=quality, method=6)
        if buf.tell() <= 500 * 1024:
            buf.seek(0)
            return buf
    buf.seek(0)
    return buf
