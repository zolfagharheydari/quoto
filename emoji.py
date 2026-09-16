"""Draw emoji as pictures, because no font we can ship draws them for us.

Pillow can render a colour font, but joining a family, a flag or a skin tone into
one glyph needs libraqm, which the usual wheels are built without — so those come
out as their separate pieces. Twemoji gives every sequence its own file, named
after its codepoints, so looking one up is exact and the composites are right.

Run download_emoji.py once to populate assets/emoji/; without it the module stays
quiet and text simply renders as before, emoji and all missing.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

EMOJI_DIR = Path(__file__).parent / "assets" / "emoji"

VS16 = "️"
ZWJ = "‍"
KEYCAP = "⃣"
SKIN = "\U0001F3FB-\U0001F3FF"
TAGS = "\U000E0020-\U000E007F"
REGIONAL = "\U0001F1E6-\U0001F1FF"

# Broad enough for the pictographic blocks; anything matched that has no file
# simply falls through and is drawn as text.
BASE = (
    "\U0001F000-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "\U00002700-\U000027BF"
    "\U0000FE0F\U00002122\U000000A9\U000000AE"
    "\U0001F900-\U0001F9FF"
)
_PIECE = f"[{BASE}][{SKIN}{VS16}{TAGS}]*"
CLUSTER_RE = re.compile(
    "(?:"
    f"[{REGIONAL}]{{2}}"                       # a flag is two regional letters
    f"|[0-9#*]{VS16}?{KEYCAP}"                 # a keycap digit
    f"|{_PIECE}(?:{ZWJ}{_PIECE})*"             # everything else, ZWJ-joined
    ")"
)


def _stem(cluster: str) -> str:
    return "-".join(f"{ord(ch):x}" for ch in cluster)


@lru_cache(maxsize=2048)
def _path(cluster: str) -> Path | None:
    """Twemoji drops the variation selector from most names, but not all."""
    for candidate in (cluster, cluster.replace(VS16, "")):
        if not candidate:
            continue
        path = EMOJI_DIR / f"{_stem(candidate)}.png"
        if path.exists():
            return path
    return None


@lru_cache(maxsize=512)
def _tile(cluster: str, size: int) -> Image.Image | None:
    path = _path(cluster)
    if path is None:
        return None
    try:
        return Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
    except Exception:  # noqa: BLE001 - a bad file should not break a render
        log.warning("could not read emoji %s", path)
        return None


def available() -> bool:
    return EMOJI_DIR.is_dir() and any(EMOJI_DIR.glob("*.png"))


def split_runs(text: str) -> list[tuple[bool, str]]:
    """The text as alternating (is_emoji, chunk) pieces, in order."""
    runs: list[tuple[bool, str]] = []
    last = 0
    for match in CLUSTER_RE.finditer(text):
        cluster = match.group()
        if _path(cluster) is None:
            continue  # nothing to paste; leave it in the text run
        if match.start() > last:
            runs.append((False, text[last:match.start()]))
        runs.append((True, cluster))
        last = match.end()
    if last < len(text):
        runs.append((False, text[last:]))
    return runs


def box(font) -> tuple[int, int]:
    """(tile size, advance) for emoji drawn alongside this font."""
    size = max(8, int(getattr(font, "size", 16)))
    return size, int(size * 1.18)


def measure(text: str, font) -> float:
    """Width of the text with emoji counted as square tiles."""
    if not text:
        return 0.0
    size, advance = box(font)
    total = 0.0
    for is_emoji, chunk in split_runs(text):
        total += advance if is_emoji else font.getlength(chunk)
    return total


def draw_line(image: Image.Image, draw, xy: tuple[float, float], text: str,
              font, fill, anchor: str = "la") -> None:
    """Draw one already-shaped line, pasting emoji where they belong.

    `anchor` takes the horizontal half of Pillow's anchors — l, m or r — and the
    vertical position is the top of the line, as with Pillow's "a".
    """
    size, advance = box(font)
    runs = split_runs(text)
    x, y = xy
    if anchor and anchor[0] in ("m", "r"):
        width = measure(text, font)
        x -= width / 2 if anchor[0] == "m" else width

    # Sit the tile on the text's own body rather than on the line box.
    ascent, _ = font.getmetrics()
    top = y + max(0, ascent - size) * 0.72

    for is_emoji, chunk in runs:
        if is_emoji:
            tile = _tile(chunk, size)
            if tile is not None:
                image.paste(tile, (int(x + (advance - size) / 2), int(top)), tile)
            x += advance
        else:
            draw.text((x, y), chunk, font=font, fill=fill, anchor="la")
            x += font.getlength(chunk)


# The bidi pass reorders a line character by character and drops joiners, which
# takes a family or a skin tone apart. Standing each cluster in for a single
# private-use character keeps it whole and lets it move as one unit; the stand-ins
# are unique, so putting the clusters back does not depend on their final order.
_PLACEHOLDER_BASE = 0xE000


def protect(text: str) -> tuple[str, dict[str, str]]:
    """Replace emoji clusters with single stand-in characters."""
    mapping: dict[str, str] = {}
    out: list[str] = []
    last = 0
    for match in CLUSTER_RE.finditer(text):
        cluster = match.group()
        if _path(cluster) is None:
            continue
        out.append(text[last:match.start()])
        stand_in = chr(_PLACEHOLDER_BASE + len(mapping))
        mapping[stand_in] = cluster
        out.append(stand_in)
        last = match.end()
    out.append(text[last:])
    return "".join(out), mapping


def restore(text: str, mapping: dict[str, str]) -> str:
    if not mapping:
        return text
    return "".join(mapping.get(ch, ch) for ch in text)
