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
