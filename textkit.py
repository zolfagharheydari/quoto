"""RTL-aware text shaping and wrapping.

Persian/Arabic needs two passes before it can be drawn by Pillow:
  1. arabic_reshaper  -> pick the right contextual glyph form for each letter
  2. bidi.get_display -> reorder the logical string into visual order

Wrapping must happen on the *logical* string, before reshaping, otherwise word
boundaries land in the wrong place.
"""
from __future__ import annotations

import re
import unicodedata

import arabic_reshaper
from bidi.algorithm import get_display

import fonts

RTL_RE = re.compile(r"[\u0590-\u05FF\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")

def is_rtl(text: str) -> bool:
    """True when the string is predominantly right-to-left."""
    rtl = len(RTL_RE.findall(text))
    letters = sum(1 for ch in text if unicodedata.category(ch).startswith("L"))
    return letters > 0 and rtl / letters > 0.3


def shape(text: str, rtl: bool | None = None) -> str:
    """Turn a logical-order string into a visual-order, glyph-shaped string.

    `rtl` forces the base direction. Pass the direction of the whole paragraph
    when shaping its lines one at a time: a line of nothing but emoji carries no
    direction of its own, and left to itself would lay out left-to-right in the
    middle of a Persian quote.
    """
    if rtl is None:
        if not RTL_RE.search(text):
            return text
        rtl = True
    return get_display(arabic_reshaper.reshape(text), base_dir="R" if rtl else "L")


def width_of(text: str, font, rtl: bool | None = None) -> float:
    return font.getlength(shape(text, rtl))


def wrap(text: str, font, max_width: float, rtl: bool | None = None) -> list[str]:
    """Greedy word wrap on logical text. Returns logical lines (not yet shaped)."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for word in paragraph.split(" "):
            candidate = f"{current} {word}".strip()
            if current and width_of(candidate, font, rtl) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
            # A single word longer than the line: hard-break it by characters.
            while width_of(current, font, rtl) > max_width and len(current) > 1:
                cut = len(current) - 1
                while cut > 1 and width_of(current[:cut], font, rtl) > max_width:
                    cut -= 1
                lines.append(current[:cut])
                current = current[cut:]
        if current:
            lines.append(current)
    return lines


def fit(text: str, font_loader, max_width: float, max_height: float,
        sizes: range, line_spacing: float = 1.35,
        rtl: bool | None = None) -> tuple[list[str], object, int]:
    """Pick the largest font size whose wrapped text fits the box.

    `font_loader` is a callable size -> font. Returns (logical lines, font, line_height).
    """
    best = None
    for size in sizes:  # descending
        font = font_loader(size)
        line_height = int(size * line_spacing)
        lines = wrap(text, font, max_width, rtl)
        if len(lines) * line_height <= max_height:
            return lines, font, line_height
        best = (lines, font, line_height)
    return best  # smallest size; caller may clip


# Display names love decorative Unicode: 𝓙𝓾𝓼𝓽, ＪＵＳＴ, ᴊᴜsᴛ. The bundled fonts have
# no glyphs for any of it, so it would draw as blank boxes. NFKC folds most of it
# back to plain letters; small capitals are real letters, so NFKC leaves them and
# they need a map of their own.
_SMALL_CAPS = str.maketrans({
    "ᴀ": "a", "ʙ": "b", "ᴄ": "c", "ᴅ": "d", "ᴇ": "e",
    "ꜰ": "f", "ɢ": "g", "ʜ": "h", "ɪ": "i", "ᴊ": "j",
    "ᴋ": "k", "ʟ": "l", "ᴍ": "m", "ɴ": "n", "ᴏ": "o",
    "ᴘ": "p", "ǫ": "q", "ʀ": "r", "ꜱ": "s", "ᴛ": "t",
    "ᴜ": "u", "ᴠ": "v", "ᴡ": "w", "ʏ": "y", "ᴢ": "z",
})

# Invisible characters that only cause trouble. U+200C is deliberately absent:
# Persian needs it between letters (می‌روم), and dropping it would misspell words.
ZWNJ = chr(0x200C)   # the Persian half-space, which must survive

_INVISIBLE = str.maketrans({
    "​": "", "‎": "", "‏": "", "﻿": "",
    "︎": "", "️": "", " ": " ",
})


_UNPRINTABLE = ("Cn", "Co", "Cs", "Cf", "So", "Sk")


def normalize_display(text: str) -> str:
    """Keep what can be drawn, fold what cannot, drop what is left.

    A display name written in 𝙎𝙢𝙖𝙡𝙡 𝘾𝙖𝙥𝙨 or 𝓼𝓬𝓻𝓲𝓹𝓽 is how that person writes
    their name, so it is kept as they wrote it whenever a font here has the
    glyphs. Only when nothing can draw a character is it folded back to the
    plain letter it stands for - NFKC does most of that, and small capitals are
    real letters NFKC leaves alone, so they need a map of their own.

    Emoji go regardless. They would be drawn from a different font at a
    different size, and leaving them in left a hole in the line the width of the
    missing glyph; taking them out closes the gap, because the spaces around
    them collapse.
    """
    if not text:
        return text
    text = text.translate(_INVISIBLE)
    keep = ZWNJ + chr(10)
    out = []
    for ch in text:
        if ch in keep:
            out.append(ch)
            continue
        if unicodedata.category(ch) in _UNPRINTABLE:
            continue
        if fonts.can_draw(ch):
            out.append(ch)
            continue
        # Nothing on this machine has a glyph for it, so fall back to whatever
        # plain letters it decomposes to - and drop even those if they are no
        # more drawable than the original.
        folded = unicodedata.normalize("NFKC", ch).translate(_SMALL_CAPS)
        out.extend(
            c for c in folded
            if unicodedata.category(c) not in _UNPRINTABLE and fonts.can_draw(c)
        )
    cleaned = "".join(out)
    # Collapse the run of spaces an omitted emoji leaves, line by line.
    return chr(10).join(
        " ".join(line.split()) for line in cleaned.split(chr(10))
    ).strip()
