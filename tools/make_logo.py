"""Generate the Quoto logo as SVG and PNG from one geometric definition.

The mark is a Q whose descender is a quotation comma. The ring is drawn as an
arc with a gap at the lower right; the comma sits in that gap, so the letter
and the punctuation are the same stroke.

The comma is the ' glyph from Georgia Bold, converted to outlines, so the SVG
carries real path data and does not depend on the font being installed.

Run:  python tools/make_logo.py
"""
from __future__ import annotations

import math
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw

# --- geometry, as fractions of the canvas ------------------------------------
CENTER = 0.5
RADIUS = 0.295
STROKE = 0.082
ARC_START, ARC_END = 72.0, 14.0     # degrees, y down; the gap sits between them
# Height of the comma's ink, as a fraction of the canvas. Both renderers trim to
# the ink before scaling, so this means the same thing in the SVG and the PNG.
COMMA_HEIGHT = 0.2119
COMMA_ANGLE = 43.0
COMMA_R_X, COMMA_R_Y = 1.02, 1.06   # how far out the comma sits, per axis

SERIF = Path("C:/Windows/Fonts/georgiab.ttf")
COMMA_CHAR = "\u2019"

WHITE = (245, 245, 245)
BLACK = (0, 0, 0)
SIZE = 512
SUPERSAMPLE = 4

OUTDIR = Path(__file__).resolve().parent.parent / "assets" / "logo"


def comma_center(size: float) -> tuple[float, float]:
    a = math.radians(COMMA_ANGLE)
    return (size * (CENTER + RADIUS * COMMA_R_X * math.cos(a)),
            size * (CENTER + RADIUS * COMMA_R_Y * math.sin(a)))


# --- SVG ---------------------------------------------------------------------
def comma_path_and_transform(size: float) -> tuple[str, str]:
    """The comma outline in font units, plus the transform that places it."""
    font = TTFont(SERIF)
    glyph_name = font.getBestCmap()[ord(COMMA_CHAR)]
    glyphs = font.getGlyphSet()

    bounds = BoundsPen(glyphs)
    glyphs[glyph_name].draw(bounds)
    x0, y0, x1, y1 = bounds.bounds

    pen = SVGPathPen(glyphs)
    glyphs[glyph_name].draw(pen)
    path = pen.getCommands()

    scale = size * COMMA_HEIGHT / (y1 - y0)
    cx, cy = comma_center(size)
    # scale(s, -s) flips the font's y-up outline into SVG's y-down space.
    tx = cx - scale * (x0 + x1) / 2
    ty = cy + scale * (y0 + y1) / 2
    return path, f"translate({tx:.3f} {ty:.3f}) scale({scale:.6f} {-scale:.6f})"


def arc_path(size: float) -> str:
    c, r = size * CENTER, size * RADIUS
    a0, a1 = math.radians(ARC_START), math.radians(ARC_END)
    start = (c + r * math.cos(a0), c + r * math.sin(a0))
    end = (c + r * math.cos(a1), c + r * math.sin(a1))
    # sweeps clockwise the long way round, leaving the gap for the comma
    return (f"M {start[0]:.3f} {start[1]:.3f} "
            f"A {r:.3f} {r:.3f} 0 1 1 {end[0]:.3f} {end[1]:.3f}")


def write_svg(path: Path, background: str | None, ink: str = "#F5F5F5") -> None:
    size = float(SIZE)
    comma, transform = comma_path_and_transform(size)
    colour = ink
    bg = (f'  <rect width="{SIZE}" height="{SIZE}" fill="{background}"/>\n'
          if background else "")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" \
width="{SIZE}" height="{SIZE}" role="img" aria-label="Quoto">
  <title>Quoto</title>
{bg}  <path d="{arc_path(size)}" fill="none" stroke="{colour}" \
stroke-width="{size * STROKE:.3f}" stroke-linecap="round"/>
  <path d="{comma}" fill="{colour}" transform="{transform}"/>
</svg>
"""
    path.write_text(svg, encoding="utf-8")
    print("wrote", path.name)


# --- PNG ---------------------------------------------------------------------
def render_png(path: Path, background: tuple[int, int, int] | None,
               ink: tuple[int, int, int] = WHITE) -> None:
    from PIL import ImageFont

    s = SIZE * SUPERSAMPLE
    img = Image.new("RGBA", (s, s), (*background, 255) if background else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c, r, w = s * CENTER, s * RADIUS, int(s * STROKE)
    d.arc([c - r, c - r, c + r, c + r], start=ARC_START, end=ARC_END,
          fill=(*ink, 255), width=w)

    font = ImageFont.truetype(str(SERIF), 1000)
    x0, y0, x1, y1 = font.getbbox(COMMA_CHAR)
    tmp = Image.new("L", (x1 - x0 + 8, y1 - y0 + 8), 0)
    ImageDraw.Draw(tmp).text((-x0 + 4, -y0 + 4), COMMA_CHAR, font=font, fill=255)
    # Trim to the ink first: getbbox() reports a taller box than the glyph draws,
    # so scaling before the crop would size the padding rather than the comma.
    tmp = tmp.crop(tmp.getbbox())
    target_h = s * COMMA_HEIGHT
    scale = target_h / tmp.height
    tmp = tmp.resize((max(1, round(tmp.width * scale)), max(1, round(target_h))),
                     Image.LANCZOS)
    cx, cy = comma_center(s)
    layer = Image.new("RGBA", tmp.size, (*ink, 255))
    img.paste(layer, (int(cx - tmp.width / 2), int(cy - tmp.height / 2)), tmp)

    img.resize((SIZE, SIZE), Image.LANCZOS).save(path)
    print("wrote", path.name)


if __name__ == "__main__":
    OUTDIR.mkdir(parents=True, exist_ok=True)
    # white mark for dark surfaces, black mark for light ones, plus the avatar
    write_svg(OUTDIR / "quoto.svg", background=None)
    write_svg(OUTDIR / "quoto-dark.svg", background=None, ink="#111111")
    write_svg(OUTDIR / "quoto-avatar.svg", background="#000000")
    render_png(OUTDIR / "quoto-mark-512.png", background=None)
    render_png(OUTDIR / "quoto-mark-dark-512.png", background=None, ink=(17, 17, 17))
    render_png(OUTDIR / "quoto-avatar-512.png", background=BLACK)
