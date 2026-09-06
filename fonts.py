"""Font discovery: prefers bundled Vazirmatn (Persian + Latin), falls back to system fonts."""
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


@lru_cache(maxsize=None)
def _resolve(weight: str) -> Path | None:
    for path in CANDIDATES.get(weight, []):
        if path.exists():
            return path
    return None


@lru_cache(maxsize=256)
def load(weight: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a truetype font at `size`, falling back to Pillow's default."""
    for w in (weight, "regular"):
        path = _resolve(w)
        if path is not None:
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                log.warning("could not open font %s", path)
    log.warning("no truetype font found; falling back to Pillow default (size is fixed)")
    return ImageFont.load_default(size)


def missing_bundled_font() -> bool:
    return not (FONT_DIR / "Vazirmatn-Regular.ttf").exists()
