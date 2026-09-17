"""Render a message as a chat screenshot, the way Telegram on iOS draws it.

The sender's name sits inside the bubble above the text, coloured per user the
way the app colours it; a Persian message pushes the sender's badge across to
the far edge. The timestamp stays in the bottom-right corner either way, as it
does on an incoming message in the app.

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

# Telegram on iOS: white bubble with a soft shadow, over the default wallpaper.
THEME = {
    "bg": (170, 195, 150),   # only seen if the wallpaper cannot be built
    "bubble": (255, 255, 255),
    "text": (0, 0, 0),
    "time": (161, 170, 179),
    "radius": 18,
    "avatar": 36,
    "name_size": 15,
    "text_size": 17,
    "time_size": 12,
}

# Telegram's own default wallpaper: four colours, one at each corner, blended
# into each other. The app builds it the same way - the whole picture is a 2x2
# image scaled up - so upscaling a 2x2 here is not an approximation of it, it is
# the same construction.
WALLPAPER = ((219, 221, 187), (213, 216, 134),
             (107, 165, 135), (136, 184, 132))


def _wallpaper(size: tuple[int, int]) -> Image.Image:
    """The default chat background at this size."""
    corners = Image.new("RGB", (2, 2))
    corners.putdata(list(WALLPAPER))
    # Bilinear, not bicubic: bicubic overshoots at the edges and pushes the
    # corner colours past themselves, which is visible as a bright rim.
    return corners.resize(size, Image.BILINEAR)


# A reaction pill: the emoji, then how many people chose it. No faces - who
# reacted is nobody's business once the message leaves the group.
REACTION_SIZE = 15
REACTION_GAP = 5
REACTION_PAD_X = 8


def _emoji_tile(font, emoji: str, cell: int) -> Image.Image | None:
    """The emoji in a square of its own, centred on the pixels it actually inks.

    Centring by anchor centres the glyph's *advance*, and an emoji written with
    a variation selector - a heart, say - has an advance wider than itself, so
    it lands left of the middle and the count beside it looks adrift. Worse, it
    can land far enough left to run off the scratch tile and lose a slice of
    itself. Drawing it large, cropping to its ink and fitting that to the cell
    makes every emoji sit the same way, whatever shape it is, and scales down a
    bitmap font's fixed-size glyphs on the way.
    """
    if font is None:
        return None
    tile = ink = None
    for big in (cell * 4, cell * 8):
        tile = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        try:
            ImageDraw.Draw(tile).text((big // 2, big // 2), emoji, font=font,
                                      embedded_color=True, anchor="mm")
        except Exception:  # noqa: BLE001 - an emoji the font cannot draw
            return None
        ink = tile.getbbox()
        if ink is None:
            return None
        if ink[0] > 0 and ink[1] > 0 and ink[2] < big and ink[3] < big:
            break
    tile = tile.crop(ink)
    scale = min(cell / tile.width, cell / tile.height)
    tile = tile.resize((max(1, round(tile.width * scale)),
                        max(1, round(tile.height * scale))), Image.LANCZOS)
    out = Image.new("RGBA", (cell, cell), (0, 0, 0, 0))
    out.paste(tile, ((cell - tile.width) // 2, (cell - tile.height) // 2))
    return out


def _row_width(row, gap: float) -> float:
    return sum(p[3] for p in row) + gap * max(0, len(row) - 1)


def _wrap_pills(pills: list, max_width: float, gap: float) -> list[list]:
    """Break the pills into rows that fit. A pill never splits, so one wider
    than the whole bubble simply gets a row to itself."""
    rows: list[list] = []
    current: list = []
    for pill in pills:
        candidate = current + [pill]
        if current and _row_width(candidate, gap) > max_width:
            rows.append(current)
            current = [pill]
        else:
            current = candidate
    if current:
        rows.append(current)
    return rows


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
           badge: str | None = None, seed: str = "",
           reactions: list[tuple[str, int]] | None = None) -> Image.Image:
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

    # The reaction row, if there is one. Its width has a say in how wide the
    # bubble gets, the same as any other line inside it.
    count_font = fonts.load("medium", _px(REACTION_SIZE - 2))
    emoji_font = fonts.emoji_font(_px(REACTION_SIZE))
    cell = _px(REACTION_SIZE)
    pill_h = _px(REACTION_SIZE + 9)
    pill_gap = _px(REACTION_GAP)
    pill_pad = _px(REACTION_PAD_X)
    pills = []
    if emoji_font is not None:
        for emoji, count in (reactions or []):
            c_text = str(count)
            c_w = count_font.getlength(c_text)
            pills.append((emoji, c_text, c_w,
                          pill_pad * 2 + cell + _px(4) + c_w))

    # Every reaction is drawn, so a message with a dozen of them wraps onto more
    # rows instead of quietly losing some. The timestamp shares the last row
    # when there is room for it, and takes one of its own when there is not.
    rows = _wrap_pills(pills, max_content, pill_gap)
    rows_w = max((_row_width(r, pill_gap) for r in rows), default=0)
    last_w = _row_width(rows[-1], pill_gap) if rows else 0
    time_shares_row = bool(rows) and last_w + _px(10) + time_w <= max_content
    if time_shares_row:
        rows_w = max(rows_w, last_w + _px(10) + time_w)

    content_w = int(min(max(name_w + badge_w, text_w, time_w, rows_w), max_content))

    line_h = _px(theme["text_size"] + 6)
    name_h = _px(theme["name_size"] + 5)
    time_h = _px(theme["time_size"] + 5)
    pad_x = _px(BUBBLE_PAD_X)
    pad_top = _px(9)
    pad_bottom = _px(8)
    radius = _px(theme["radius"])
    tail = _px(13)

    bubble_w = content_w + pad_x * 2
    # With reactions the rows take the place of the timestamp's own line, unless
    # the last of them is too full to hold the time as well.
    if rows:
        tail_h = _px(3) + len(rows) * (pill_h + _px(4)) + _px(2)
        if not time_shares_row:
            tail_h += time_h
    else:
        tail_h = time_h
    bubble_h = pad_top + name_h + len(lines) * line_h + tail_h + pad_bottom

    avatar_size = _px(theme["avatar"])
    pad = _px(PAD)
    gap = _px(GAP)

    width = pad + avatar_size + gap + bubble_w + pad
    height = pad + bubble_h + pad

    img = _wallpaper((width, height))

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
    # The name keeps the left edge in either direction. In Persian the badge is
    # pushed to the opposite edge instead of trailing the name.
    name_x = bubble_x + pad_x
    name_font.draw_on(draw, (name_x, y), name_shaped, fill=accent, anchor="la")
    if badge:
        pill_w = badge_text_w + badge_pad * 2
        bx = (bubble_x + bubble_w - pad_x - pill_w) if rtl else (name_x + name_w + _px(6))
        bh = _px(theme["name_size"] + 3)
        draw.rounded_rectangle(
            [bx, y, bx + pill_w, y + bh],
            radius=bh // 2,
            fill=tuple(int(b + (a - b) * 0.22)
                       for a, b in zip(accent, theme["bubble"])),
        )
        badge_font.draw_on(draw, (bx + badge_pad, y + bh // 2), badge_shaped,
                           fill=accent, anchor="lm")
    y += name_h

    # Right-to-left text hugs the right edge of the bubble, as it does in the app.
    text_x = bubble_x + bubble_w - pad_x if rtl else bubble_x + pad_x
    for shaped_line in shaped:
        text_font.draw_on(draw, (text_x, y), shaped_line, fill=theme["text"],
                          anchor=("ra" if rtl else "la"))
        y += line_h

    # The timestamp stays in the bottom-right corner whichever way the text runs,
    # as it does on an incoming message in the app.
    if not rows:
        time_font.draw_on(draw, (bubble_x + bubble_w - pad_x, y), time_str,
                          fill=theme["time"], anchor="ra")
        return img

    # Reactions sit at the bottom left in either direction - the app puts them
    # there in Persian too - and the time keeps the corner it has always had.
    y += _px(3)
    pill_fill = tuple(int(b + (a - b) * 0.16)
                      for a, b in zip(accent, theme["bubble"]))
    for row in rows:
        x = bubble_x + pad_x
        for emoji, c_text, c_w, w in row:
            draw.rounded_rectangle([x, y, x + w, y + pill_h],
                                   radius=pill_h // 2, fill=pill_fill)
            middle = y + pill_h // 2
            tile = _emoji_tile(emoji_font, emoji, cell)
            if tile is not None:
                img.paste(tile, (int(x + pill_pad), int(middle - cell // 2)), tile)
            count_font.draw_on(draw, (x + pill_pad + cell + _px(4), middle), c_text,
                               fill=accent, anchor="lm")
            x += w + pill_gap
        y += pill_h + _px(4)

    if time_shares_row:
        time_font.draw_on(draw, (bubble_x + bubble_w - pad_x, y - pill_h // 2 - _px(4)),
                          time_str, fill=theme["time"], anchor="rm")
    else:
        time_font.draw_on(draw, (bubble_x + bubble_w - pad_x, y), time_str,
                          fill=theme["time"], anchor="ra")

    return img


def to_png(img: Image.Image) -> io.BytesIO:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf
