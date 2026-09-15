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

RTL_RE = re.compile(r"[\u0590-\u05FF\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")

def is_rtl(text: str) -> bool:
    """True when the string is predominantly right-to-left."""
    rtl = len(RTL_RE.findall(text))
    letters = sum(1 for ch in text if unicodedata.category(ch).startswith("L"))
    return letters > 0 and rtl / letters > 0.3


def shape(text: str) -> str:
    """Turn a logical-order string into a visual-order, glyph-shaped string."""
    if not RTL_RE.search(text):
        return text
    return get_display(arabic_reshaper.reshape(text))


def width_of(text: str, font) -> float:
    return font.getlength(shape(text))


def wrap(text: str, font, max_width: float) -> list[str]:
    """Greedy word wrap on logical text. Returns logical lines (not yet shaped)."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for word in paragraph.split(" "):
            candidate = f"{current} {word}".strip()
            if current and width_of(candidate, font) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
            # A single word longer than the line: hard-break it by characters.
            while width_of(current, font) > max_width and len(current) > 1:
                cut = len(current) - 1
                while cut > 1 and width_of(current[:cut], font) > max_width:
                    cut -= 1
                lines.append(current[:cut])
                current = current[cut:]
        if current:
            lines.append(current)
    return lines


def fit(text: str, font_loader, max_width: float, max_height: float,
        sizes: range, line_spacing: float = 1.35) -> tuple[list[str], object, int]:
    """Pick the largest font size whose wrapped text fits the box.

    `font_loader` is a callable size -> font. Returns (logical lines, font, line_height).
    """
    best = None
    for size in sizes:  # descending
        font = font_loader(size)
        line_height = int(size * line_spacing)
        lines = wrap(text, font, max_width)
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
_INVISIBLE = str.maketrans({
    "​": "", "‎": "", "‏": "", "﻿": "",
    "︎": "", "️": "", " ": " ",
})


def normalize_display(text: str) -> str:
    """Fold decorative Unicode back to letters the bundled fonts can actually draw."""
    if not text:
        return text
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_SMALL_CAPS).translate(_INVISIBLE)
    # Whatever is left and still unprintable would come out as a box; drop it.
    cleaned = "".join(
        ch for ch in text
        if ch in "‌\n" or unicodedata.category(ch) not in ("Cn", "Co", "Cs", "Cf")
    )
    return cleaned.strip()


def normalize_name(text: str) -> str:
    """Like normalize_display, but strips emoji too.

    A name is a label, so losing the roses costs nothing and spares us a row of
    boxes the bundled fonts cannot draw. Message text keeps its emoji, because a
    message that is nothing but emoji would otherwise come out empty. If a name
    happens to be all emoji, the original is kept for the same reason.
    """
    cleaned = normalize_display(text)
    stripped = "".join(
        ch for ch in cleaned if unicodedata.category(ch) not in ("So", "Sk")
    )
    stripped = " ".join(stripped.split())
    return stripped or cleaned
