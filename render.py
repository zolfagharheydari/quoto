"""Renders the quote card: grayscale portrait fading into black, quote, author."""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageEnhance

import fonts
import textkit

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
    watermark: str = ""
    watermark_font: object = None
    _shaped: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._shaped = [textkit.shape(line) for line in self.lines]

    def render(self, reveal: float = 1.0, author_alpha: float = 1.0) -> Image.Image:
        img = self.background.copy()
        draw = ImageDraw.Draw(img)
        cx = TEXT_X + TEXT_W // 2

        total = sum(len(line) for line in self.lines) or 1
        budget = int(total * max(0.0, min(1.0, reveal)))
        for i, logical in enumerate(self.lines):
            if budget <= 0:
                break
            visible = logical if budget >= len(logical) else logical[:budget]
            budget -= len(logical)
            text = self._shaped[i] if visible == logical else textkit.shape(visible)
            draw.text((cx, self.quote_top + i * self.line_height), text,
                      font=self.quote_font, fill=QUOTE_COLOR, anchor="ma")

        if author_alpha > 0:
            a = max(0.0, min(1.0, author_alpha))
            draw.text((cx, self.name_y), textkit.shape(self.name), font=self.name_font,
                      fill=_fade(NAME_COLOR, a), anchor="ma")

        if self.watermark:
            draw.text((WIDTH - 24, HEIGHT - 22), self.watermark,
                      font=self.watermark_font, fill=MARK_COLOR, anchor="rs")
        return img


def _fade(color: tuple[int, int, int], alpha: float) -> tuple[int, int, int]:
    return tuple(int(c * alpha) for c in color)


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
    draw.text((size // 2, size // 2), textkit.shape(letter or "?"), font=font,
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


def build_background(avatar: Image.Image) -> Image.Image:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BG)
    photo = _cover(avatar.convert("RGB"), (PHOTO_W, HEIGHT))
    photo = ImageEnhance.Contrast(photo).enhance(1.06)
    photo = ImageEnhance.Brightness(photo).enhance(0.95)
    canvas.paste(photo, (0, 0), _fade_mask(PHOTO_W, HEIGHT))
    return canvas


def build_scene(avatar: Image.Image, quote: str, name: str,
                watermark: str = "") -> Scene:
    # Decorative Unicode in a name or a message would draw as empty boxes.
    quote = textkit.normalize_display(quote)
    name = textkit.normalize_display(name)
    quote = " ".join(quote.split()) if "\n" not in quote else quote.strip()
    rtl = textkit.is_rtl(quote)
    open_q, close_q = ("«", "»") if rtl else ("\u201c", "\u201d")
    body = f"{open_q}{quote}{close_q}"

    # A Persian quote needs Vazirmatn; a Latin one looks closer to the reference in serif.
    weight = "medium" if rtl else "serif"
    loader = lambda s: fonts.load(weight, s)  # noqa: E731

    name_font = fonts.load("bold", 36)
    # Only the name sits under the quote now, so the text block gets the rest.
    author_block = 36
    max_text_h = int(HEIGHT * 0.68)

    # A long quote used to shrink to 22px, which is unreadable at a glance; 30 is
    # the floor now, and anything that still will not fit is trimmed instead.
    lines, quote_font, line_height = textkit.fit(
        body, loader, TEXT_W, max_text_h, range(60, 29, -2), line_spacing=1.34
    )
    max_lines = max(1, max_text_h // line_height)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip() + "…"

    quote_h = len(lines) * line_height
    block_h = quote_h + 56 + author_block
    top = (HEIGHT - block_h) // 2
    name_y = top + quote_h + 56

    return Scene(
        background=build_background(avatar),
        lines=lines,
        quote_font=quote_font,
        line_height=line_height,
        quote_top=top,
        name=f"- {name}" if not rtl else f"— {name}",
        name_font=name_font,
        name_y=name_y,
        watermark=watermark,
        watermark_font=fonts.load("regular", 19),
    )


def render_quote(avatar: Image.Image, quote: str, name: str,
                 watermark: str = "") -> Image.Image:
    return build_scene(avatar, quote, name, watermark).render()


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
