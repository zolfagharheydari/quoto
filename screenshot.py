"""Render a message as a chat screenshot: a bubble, an avatar, a name, a time.

Two skins, Telegram dark and iOS light. Both lay the message out the way the real
client does — incoming bubble on the left, name above the text, time below it —
and both mirror the text when it is right-to-left, the way Telegram does.

Everything is drawn at SCALE and kept at that size; these are small images and the
extra resolution is what makes them read as a screenshot rather than as artwork.
"""
from __future__ import annotations

import hashlib
import io

from PIL import Image, ImageDraw

import fonts
import textkit

SCALE = 3

# Telegram's own palette for sender names, picked per user id the way the app does.
NAME_COLORS = [
    (225, 112, 118), (123, 200, 98), (229, 202, 119), (101, 170, 221),
    (166, 149, 231), (238, 122, 174), (110, 201, 203),
]

TELEGRAM = {
    "bg": (23, 33, 43),
    "bubble": (24, 37, 51),
    "text": (233, 237, 240),
    "time": (109, 127, 143),
    "radius": 16,
    "avatar": 42,
    "name_size": 15,
    "text_size": 17,
    "time_size": 12,
}

IOS = {
    "bg": (255, 255, 255),
    "bubble": (233, 233, 235),
    "text": (0, 0, 0),
    "time": (142, 142, 147),
    "name": (142, 142, 147),
    "radius": 19,
    "avatar": 30,
    "name_size": 12,
    "text_size": 17,
    "time_size": 12,
}

PAD = 18
GAP = 9
BUBBLE_PAD_X = 13
MAX_BUBBLE_W = 430
MAX_LINES = 30


def _px(value: int) -> int:
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


def _layout(text: str, font, max_width: int) -> list[str]:
    lines = textkit.wrap(text, font, max_width)
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
        lines[-1] = lines[-1] + "…"
    return lines


def _tail(draw: ImageDraw.ImageDraw, x: int, bottom: int, size: int,
          colour: tuple[int, int, int]) -> None:
    """The little spur on the bottom-left of an incoming bubble."""
    draw.polygon(
        [(x, bottom - size), (x, bottom), (x - int(size * 0.62), bottom)],
        fill=colour,
    )


def render(avatar: Image.Image, name: str, text: str, time_str: str,
           badge: str | None = None, seed: str = "", style: str = "telegram") -> Image.Image:
    theme = IOS if style == "ios" else TELEGRAM
    ios = style == "ios"
    rtl = textkit.is_rtl(text)

    name_font = fonts.load("medium" if ios else "bold", _px(theme["name_size"]))
    text_font = fonts.load("regular", _px(theme["text_size"]))
    time_font = fonts.load("medium", _px(theme["time_size"]))
    badge_font = fonts.load("medium", _px(11))

    max_content = _px(MAX_BUBBLE_W - 2 * BUBBLE_PAD_X)
    lines = _layout(text, text_font, max_content)
    shaped = [textkit.shape(line) for line in lines]

    accent = name_color(seed or name)
    name_shaped = textkit.shape(name)
    name_w = name_font.getlength(name_shaped)
    badge_w = 0
    badge_pad = _px(6)
    if badge:
        badge_w = badge_font.getlength(badge) + badge_pad * 2 + _px(6)

    time_w = time_font.getlength(time_str)
    text_w = max([text_font.getlength(s) for s in shaped] or [0])

    # iOS puts the sender name above the bubble, so it doesn't widen it.
    header_w = 0 if ios else name_w + badge_w
    content_w = int(max(header_w, text_w, time_w))
    content_w = min(content_w, max_content)

    line_h = _px(theme["text_size"] + 6)
    name_h = _px(theme["name_size"] + 5)
    time_h = _px(theme["time_size"] + 5)
    pad_x = _px(BUBBLE_PAD_X)
    pad_top = _px(9)
    pad_bottom = _px(8)

    bubble_w = content_w + pad_x * 2
    # iOS carries the time above the conversation, not inside the bubble.
    bubble_h = (pad_top + (0 if ios else name_h) + len(lines) * line_h
                + (0 if ios else time_h) + pad_bottom)

    avatar_size = _px(theme["avatar"])
    pad = _px(PAD)
    gap = _px(GAP)
    name_above_h = _px(theme["name_size"] + 6) if ios else 0
    time_header_h = _px(theme["time_size"] + 14) if ios else 0

    width = pad + avatar_size + gap + bubble_w + pad
    height = pad + time_header_h + name_above_h + bubble_h + pad

    img = Image.new("RGB", (width, height), theme["bg"])
    draw = ImageDraw.Draw(img)

    if ios:
        # iMessage shows the time as a centred separator above the conversation.
        draw.text((width // 2, pad), time_str, font=time_font,
                  fill=theme["time"], anchor="ma")

    bubble_x = pad + avatar_size + gap
    bubble_y = pad + time_header_h + name_above_h
    bubble_bottom = bubble_y + bubble_h

    if ios:
        draw.text((bubble_x + pad_x, pad + time_header_h), textkit.shape(name),
                  font=name_font, fill=theme["name"], anchor="la")

    draw.rounded_rectangle(
        [bubble_x, bubble_y, bubble_x + bubble_w, bubble_bottom],
        radius=_px(theme["radius"]), fill=theme["bubble"],
        corners=(True, True, True, False),
    )
    _tail(draw, bubble_x, bubble_bottom, _px(13), theme["bubble"])

    circle = _circle(avatar, avatar_size)
    img.paste(circle, (pad, bubble_bottom - avatar_size), circle)

    y = bubble_y + pad_top
    if not ios:
        draw.text((bubble_x + pad_x, y), name_shaped, font=name_font,
                  fill=accent, anchor="la")
        if badge:
            bx = bubble_x + pad_x + name_w + _px(6)
            bh = _px(theme["name_size"] + 3)
            draw.rounded_rectangle(
                [bx, y, bx + badge_font.getlength(badge) + badge_pad * 2, y + bh],
                radius=bh // 2,
                fill=tuple(int(b + (a - b) * 0.25)
                           for a, b in zip(accent, theme["bubble"])),
            )
            draw.text((bx + badge_pad, y + bh // 2), badge, font=badge_font,
                      fill=accent, anchor="lm")
        y += name_h

    # Right-to-left text hugs the right edge of the bubble, as it does in the app.
    text_x = bubble_x + bubble_w - pad_x if rtl else bubble_x + pad_x
    anchor = "ra" if rtl else "la"
    for shaped_line in shaped:
        draw.text((text_x, y), shaped_line, font=text_font, fill=theme["text"],
                  anchor=anchor)
        y += line_h

    if not ios:
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
