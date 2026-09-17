"""Font discovery: prefers bundled Vazirmatn (Persian + Latin), falls back to system fonts.

Vazirmatn covers Persian and Latin and nothing else, so a Chinese, Korean,
Russian or Hindi message used to draw as a row of empty boxes. A card carries
whatever someone actually wrote, so every font is now a *set*: the one that sets
the look, plus whatever else on this machine can draw the characters it cannot.
A run of text is split by which font has the glyphs and drawn piece by piece,
along one shared baseline so the join is invisible.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

log = logging.getLogger(__name__)

FONT_DIR = Path(__file__).parent / "assets" / "fonts"

# Ordered candidates per weight. First existing file wins.
CANDIDATES = {
    "regular": [
        FONT_DIR / "Vazirmatn-Regular.ttf",
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    ],
    "bold": [
        FONT_DIR / "Vazirmatn-Bold.ttf",
        Path("C:/Windows/Fonts/segoeuib.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    ],
    "medium": [
        FONT_DIR / "Vazirmatn-Medium.ttf",
        FONT_DIR / "Vazirmatn-Regular.ttf",
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ],
    # Serif is only used for pure-Latin quotes, to match the reference look.
    "serif": [
        Path("C:/Windows/Fonts/georgia.ttf"),
        Path("C:/Windows/Fonts/times.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
        Path("/System/Library/Fonts/Supplemental/Georgia.ttf"),
    ],
}

# Tried in order for any character the chosen font has no glyph for. Broad
# coverage first, then the scripts that need a font of their own. Missing files
# are skipped, so the same list serves Windows and a Linux server.
FALLBACKS = [
    # Latin, Greek, Cyrillic, Hebrew, Armenian, and a good deal of Arabic
    Path("C:/Windows/Fonts/micross.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    # Chinese
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simsun.ttc"),
    # Japanese
    Path("C:/Windows/Fonts/YuGothR.ttc"),
    Path("C:/Windows/Fonts/meiryo.ttc"),
    # Korean
    Path("C:/Windows/Fonts/malgun.ttf"),
    # All three at once, which is what a server usually has (fonts-noto-cjk)
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    # Devanagari, Tamil, Bengali and the rest of the Indic scripts
    Path("C:/Windows/Fonts/Nirmala.ttf"),
    Path("C:/Windows/Fonts/Nirmala.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"),
    # Thai
    Path("C:/Windows/Fonts/leelawui.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf"),
    # The decorative alphabets people write their display names in - 𝙅𝙪𝙨𝙩,
    # 𝓙𝓾𝓼𝓽, 𝕵𝖚𝖘𝖙 - all live in the Mathematical Alphanumeric Symbols block, and
    # almost no text font carries it. Without one of these they cannot be drawn
    # at all and get folded back to plain letters instead.
    FONT_DIR / "NotoSansMath-Regular.ttf",
    Path("C:/Windows/Fonts/seguisym.ttf"),
    Path("C:/Windows/Fonts/cambria.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansMath-Regular.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf"),
    # A last resort that carries a little of everything
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
]


# Colour emoji live in a font of their own. Segoe is an outline font Pillow can
# draw at any size; Noto is a bitmap one it can only draw at 109, which is why
# every emoji here is rendered large and scaled down afterwards.
EMOJI_FONTS = [
    # A font dropped into assets/fonts by hand wins: putting one there is a
    # deliberate act, and the only reason to do it is to be used.
    FONT_DIR / "Apple Color Emoji.ttc",
    FONT_DIR / "AppleColorEmoji.ttc",
    FONT_DIR / "AppleColorEmoji.ttf",
    # Otherwise the bundled one, so every machine draws the same emoji.
    FONT_DIR / "NotoColorEmoji.ttf",
    Path("C:/Windows/Fonts/seguiemj.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
    Path("/usr/share/fonts/truetype/noto-color-emoji/NotoColorEmoji.ttf"),
    Path("/System/Library/Fonts/Apple Color Emoji.ttc"),
]


@lru_cache(maxsize=None)
def _strikes(path: Path) -> tuple[int, ...]:
    """The pixel sizes a bitmap emoji font will open at.

    A colour emoji font usually holds pictures rather than outlines, and
    FreeType refuses every size except the ones it was built with - "invalid
    pixel size" for anything else. Noto's is 109 and Apple's is 96, so the
    number cannot be guessed; it is read out of the font's own size table.
    """
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return ()
    try:
        with TTFont(str(path), fontNumber=0, lazy=True) as font:
            found = []
            for tag in ("CBLC", "EBLC"):
                if tag in font:
                    found += [st.bitmapSizeTable.ppemX for st in font[tag].strikes]
            if "sbix" in font:
                found += [int(size) for size in font["sbix"].strikes]
            return tuple(sorted({int(f) for f in found if f}))
    except Exception:  # noqa: BLE001 - an unreadable font is simply not used
        return ()


@lru_cache(maxsize=8)
def emoji_font(size: int) -> ImageFont.FreeTypeFont | None:
    """A colour emoji font at this size, or None when the machine has none.

    The size asked for is a preference, not a promise: a bitmap font comes back
    at the one size it has, and the caller scales it. That is why every emoji is
    drawn large and resized rather than requested at its final size.
    """
    for path in EMOJI_FONTS:
        if not path.exists():
            continue
        for attempt in (size, *_strikes(path)):
            try:
                font = ImageFont.truetype(str(path), attempt)
            except OSError:
                continue
            log.info("emoji font: %s at %s", path.name, attempt)
            return font
        log.warning("%s has no size this build of Pillow will open", path.name)
    log.info("no colour emoji font found; reactions will not be drawn")
    return None


@lru_cache(maxsize=None)
def _drawable() -> frozenset:
    """Every code point some font on this machine can draw.

    The union of the fonts that set the look and the fallbacks behind them. It
    answers one question: is it worth keeping this character as it was written,
    or would it come out as an empty box?
    """
    covered: set = set()
    for weight in CANDIDATES:
        path = _resolve(weight)
        if path is not None:
            covered |= _coverage(path)
    for path in _available_fallbacks():
        covered |= _coverage(path)
    log.info("%s characters drawable across the available fonts", len(covered))
    return frozenset(covered)


def can_draw(ch: str) -> bool:
    """Whether this character has a glyph anywhere, rather than a box."""
    return ord(ch) in _drawable()


@lru_cache(maxsize=None)
def _resolve(weight: str) -> Path | None:
    for path in CANDIDATES.get(weight, []):
        if path.exists():
            return path
    return None


@lru_cache(maxsize=None)
def _available_fallbacks() -> tuple[Path, ...]:
    found = tuple(p for p in FALLBACKS if p.exists())
    log.info("%s fallback fonts available", len(found))
    return found


@lru_cache(maxsize=None)
def _coverage(path: Path) -> frozenset:
    """Every code point this font actually has a glyph for.

    Read from the font's own cmap table rather than guessed: asking Pillow to
    draw a character it lacks produces a box silently, and a box is exactly what
    this is here to prevent. A collection (.ttc) is read at its first face.
    """
    try:
        from fontTools.ttLib import TTCollection, TTFont
    except ImportError:
        log.warning("fontTools is not installed; other scripts may draw as boxes")
        return frozenset()
    try:
        if path.suffix.lower() == ".ttc":
            with TTCollection(str(path), lazy=True) as collection:
                return frozenset(collection.fonts[0].getBestCmap())
        with TTFont(str(path), lazy=True) as font:
            return frozenset(font.getBestCmap())
    except Exception:  # noqa: BLE001 - an unreadable font is simply not used
        log.warning("could not read the character table of %s", path)
        return frozenset()


@lru_cache(maxsize=256)
def _truetype(path: Path, size: int) -> ImageFont.FreeTypeFont | None:
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        log.warning("could not open font %s", path)
        return None


class FontSet:
    """One font for the look, and the rest of the machine's fonts for coverage.

    It stands in for a Pillow font everywhere the code measures text, so wrapping
    and fitting need to know nothing about any of this.
    """

    __slots__ = ("primary", "_primary_path", "_paths", "_size", "_cache")

    def __init__(self, primary: ImageFont.FreeTypeFont, primary_path: Path | None = None,
                 paths=(), size: int = 0):
        self.primary = primary
        self._primary_path = primary_path
        self._paths = tuple(paths)
        self._size = size
        self._cache: dict[str, object] = {}

    # -- standing in for a Pillow font -------------------------------------

    def getlength(self, text: str) -> float:
        return sum(font.getlength(part) for part, font in self.runs(text))

    def getmetrics(self):
        return self.primary.getmetrics()

    def getbbox(self, text: str, *args, **kwargs):
        return self.primary.getbbox(text, *args, **kwargs)

    @property
    def size(self):
        return self.primary.size

    # -- the part that matters ---------------------------------------------

    def _font_for(self, ch: str):
        """The first font that can draw this character, or the primary one."""
        hit = self._cache.get(ch)
        if hit is not None:
            return hit
        code = ord(ch)
        font = self.primary
        # A space has no ink; letting it pick its own font would split a run in
        # two for nothing and lose the width the surrounding font gives it.
        covered = (self._primary_path is not None
                   and code in _coverage(self._primary_path))
        if not ch.isspace() and not covered:
            for path in self._paths:
                if code in _coverage(path):
                    loaded = _truetype(path, self._size)
                    if loaded is not None:
                        font = loaded
                        break
        self._cache[ch] = font
        return font

    def runs(self, text: str) -> list:
        """The text split into the longest stretches one font can draw."""
        if not text:
            return []
        out = []
        current = text[0]
        font = self._font_for(text[0])
        for ch in text[1:]:
            nxt = self._font_for(ch)
            if nxt is font:
                current += ch
            else:
                out.append((current, font))
                current, font = ch, nxt
        out.append((current, font))
        return out

    def draw_on(self, draw, xy, text: str, fill=None, anchor: str = "la") -> None:
        """Draw `text`, using a different font for any character the first lacks.

        Every piece is placed on one baseline, taken from the primary font, so a
        Chinese word inside a Persian sentence sits on the line with it instead
        of floating by its own metrics.
        """
        runs = self.runs(text)
        if len(runs) <= 1:
            # The overwhelmingly common case: one font draws the whole line.
            # It is not always the primary - a name written entirely in Hindi
            # is one run in a font the primary knows nothing about.
            font = runs[0][1] if runs else self.primary
            draw.text(xy, text, font=font, fill=fill, anchor=anchor)
            return

        x, y = xy
        horizontal = anchor[0] if anchor else "l"
        vertical = anchor[1] if len(anchor) > 1 else "a"
        total = sum(font.getlength(part) for part, font in runs)
        if horizontal == "m":
            x -= total / 2
        elif horizontal == "r":
            x -= total

        ascent, descent = self.primary.getmetrics()
        if vertical in ("a", "t"):
            baseline = y + ascent
        elif vertical == "m":
            baseline = y + (ascent - descent) / 2
        elif vertical in ("b", "d"):
            baseline = y - descent
        else:                      # "s", the baseline itself
            baseline = y

        for part, font in runs:
            draw.text((x, baseline), part, font=font, fill=fill, anchor="ls")
            x += font.getlength(part)


@lru_cache(maxsize=256)
def load(weight: str, size: int) -> FontSet:
    """A font at `size` for the given weight, backed by the machine's fallbacks."""
    for w in (weight, "regular"):
        path = _resolve(w)
        if path is None:
            continue
        font = _truetype(path, size)
        if font is not None:
            return FontSet(font, path, _available_fallbacks(), size)
    log.warning("no truetype font found; falling back to Pillow default (size is fixed)")
    return FontSet(ImageFont.load_default(size), None, (), size)


def missing_bundled_font() -> bool:
    return not (FONT_DIR / "Vazirmatn-Regular.ttf").exists()
