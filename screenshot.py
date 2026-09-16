"""Render a message as a chat screenshot, the way Telegram on iOS draws it.

The sender's name sits inside the bubble above the text, coloured per user the
way the app colours it, with the timestamp at the end of the message.

Everything is drawn at SCALE and kept at that size; these are small images and the
extra resolution is what makes them read as a screenshot rather than as artwork.
"""
from __future__ import annotations

import hashlib
import io

from PIL import Image, ImageDraw, ImageFilter

import fonts
import textkit

SCALE = 3

# Telegram picks a sender's name colour from a fixed palette, by account id.
# These are the darker variants, which hold up against a white bubble.
NAME_COLORS = [
    (204, 82, 82), (56, 148, 78), (168, 128, 44), (51, 129, 191),
    (122, 91, 189), (199, 71, 130), (44, 148, 150),
]

# Telegram on iOS: white bubble with a soft shadow, over the pale blue wallpaper.
THEME = {
    "bg": (220, 231, 240),
    "bubble": (255, 255, 255),
    "text": (0, 0, 0),
    "time": (161, 170, 179),
    "radius": 18,
    "avatar": 36,
    "name_size": 15,
    "text_size": 17,
    "time_size": 12,
}

PAD = 18
GAP = 9
BUBBLE_PAD_X = 13
MAX_BUBBLE_W = 430
MAX_LINES = 30


def _px(value: float) -> int:
    return int(value * SCALE)


def name_color(seed: str) -> tuple[int, int, int]:
    digest = hashlib.md5(seed.encode()).digest()
    return NAME_COLORS[digest[0] % len(NAME_COLORS)]


def _circle(avatar: Image.Image, size: int) -> Image.Image:
    """Square-crop an avatar and mask it to a circle, antialiased."""
    side = min(avatar.size)
    left = (avatar.width - side) // 2
    top = (avatar.height - side) // 2
    img = avatar.convert("RGB").crop((left, top, left + side, top + side))
    img = img.resize((size, size), Image.LANCZOS)

    big = size * 4
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, big - 1, big - 1], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask.resize((size, size), Image.LANCZOS))
    return out


def _layout(text: str, font, max_width: int, rtl: bool) -> list[str]:
    lines = textkit.wrap(text, font, max_width, rtl)
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
        lines[-1] = lines[-1] + "…"
    return lines


def _bubble_shape(draw: ImageDraw.ImageDraw, box, radius: int, tail: int, fill) -> None:
    """A rounded bubble with the little spur on its bottom-left corner."""
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=radius, fill=fill,
                           corners=(True, True, True, False))
    draw.polygon([(x0, y1 - tail), (x0, y1), (x0 - int(tail * 0.62), y1)], fill=fill)


def render(avatar: Image.Image, name: str, text: str, time_str: str,
           badge: str | None = None, seed: str = "") -> Image.Image:
    theme = THEME
    # Decorative Unicode in a name or a message would draw as empty boxes.
    name = textkit.normalize_display(name)
    text = textkit.normalize_display(text)
    badge = textkit.normalize_display(badge) if badge else badge
    rtl = textkit.is_rtl(text)

    name_font = fonts.load("bold", _px(theme["name_size"]))
    text_font = fonts.load("regular", _px(theme["text_size"]))
    time_font = fonts.load("regular", _px(theme["time_size"]))
    badge_font = fonts.load("medium", _px(11))

    max_content = _px(MAX_BUBBLE_W - 2 * BUBBLE_PAD_X)
    lines = _layout(text, text_font, max_content, rtl)
    shaped = [textkit.shape(line, rtl) for line in lines]

    accent = name_color(seed or name)
    name_shaped = textkit.shape(name)
    name_w = name_font.getlength(name_shaped)
    badge_pad = _px(6)
    # The badge is text too: a Persian "مالک" needs shaping like everything else.
    badge_shaped = textkit.shape(badge) if badge else ""
    badge_text_w = badge_font.getlength(badge_shaped) if badge else 0
    badge_w = badge_text_w + badge_pad * 2 + _px(6) if badge else 0

    time_w = time_font.getlength(time_str)
    text_w = max([text_font.getlength(s) for s in shaped] or [0])
    content_w = int(min(max(name_w + badge_w, text_w, time_w), max_content))

    line_h = _px(theme["text_size"] + 6)
    name_h = _px(theme["name_size"] + 5)
    time_h = _px(theme["time_size"] + 5)
    pad_x = _px(BUBBLE_PAD_X)
    pad_top = _px(9)
    pad_bottom = _px(8)
    radius = _px(theme["radius"])
    tail = _px(13)

    bubble_w = content_w + pad_x * 2
    bubble_h = pad_top + name_h + len(lines) * line_h + time_h + pad_bottom

    avatar_size = _px(theme["avatar"])
    pad = _px(PAD)
    gap = _px(GAP)

    width = pad + avatar_size + gap + bubble_w + pad
    height = pad + bubble_h + pad

    img = Image.new("RGB", (width, height), theme["bg"])

    bubble_x = pad + avatar_size + gap
    bubble_y = pad
    bubble_bottom = bubble_y + bubble_h
    box = [bubble_x, bubble_y, bubble_x + bubble_w, bubble_bottom]

    # iOS lifts the bubble off the wallpaper with a soft, barely-there shadow.
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    offset = [box[0], box[1] + _px(1), box[2], box[3] + _px(1)]
    _bubble_shape(ImageDraw.Draw(layer), offset, radius, tail, (0, 0, 0, 40))
    layer = layer.filter(ImageFilter.GaussianBlur(_px(1.6)))
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

    draw = ImageDraw.Draw(img)
    _bubble_shape(draw, box, radius, tail, theme["bubble"])

    circle = _circle(avatar, avatar_size)
    img.paste(circle, (pad, bubble_bottom - avatar_size), circle)

    y = bubble_y + pad_top
    draw.text((bubble_x + pad_x, y), name_shaped, font=name_font, fill=accent,
              anchor="la")
    if badge:
        bx = bubble_x + pad_x + name_w + _px(6)
        bh = _px(theme["name_size"] + 3)
        draw.rounded_rectangle(
            [bx, y, bx + badge_text_w + badge_pad * 2, y + bh],
            radius=bh // 2,
            fill=tuple(int(b + (a - b) * 0.22)
                       for a, b in zip(accent, theme["bubble"])),
        )
        draw.text((bx + badge_pad, y + bh // 2), badge_shaped, font=badge_font,
                  fill=accent, anchor="lm")
    y += name_h

    # Right-to-left text hugs the right edge of the bubble, as it does in the app.
    text_x = bubble_x + bubble_w - pad_x if rtl else bubble_x + pad_x
    for shaped_line in shaped:
        draw.text((text_x, y), shaped_line, font=text_font, fill=theme["text"],
                  anchor=("ra" if rtl else "la"))
        y += line_h

    # The timestamp sits at the end of the line, which flips with the text.
    time_x = bubble_x + pad_x if rtl else bubble_x + bubble_w - pad_x
    draw.text((time_x, y), time_str, font=time_font, fill=theme["time"],
              anchor=("la" if rtl else "ra"))

    return img


def to_png(img: Image.Image) -> io.BytesIO:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf
