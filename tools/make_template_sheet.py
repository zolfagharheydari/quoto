"""Draws assets/templates.png: the three cards, numbered, one under the other.

This is what someone sees above the buttons in /template, so it has to be the
real renderer - a hand-drawn mockup would drift the moment a template changed.
Run it again whenever one of them is touched.
"""
from __future__ import annotations

import pathlib
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import fonts  # noqa: E402
import render  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "templates.png"

QUOTE = "هر که بامش بیش، برفش بیشتر"
WHO = "SEP"
MARK = "@getquoto_bot"

CARD_W = 900
GAP = 20
BACK = (20, 20, 22)


def sample() -> Image.Image:
    demo = ROOT / "assets" / "demo" / "sep.jpg"
    if demo.exists():
        return Image.open(demo).convert("RGB")
    return render.fallback_avatar("sheet", "S").convert("RGB")


def numbered(card: Image.Image, n: int) -> Image.Image:
    """A dark disc with the number in it, in the corner of the card.

    Dark with a light ring, so it sits on the black templates and on the pale
    one without a second design.
    """
    card = card.convert("RGB").resize(
        (CARD_W, round(CARD_W * render.HEIGHT / render.WIDTH)), Image.LANCZOS)
    d = ImageDraw.Draw(card)
    r, m = 26, 18
    d.ellipse([m, m, m + 2 * r, m + 2 * r], fill=(18, 18, 20),
              outline=(245, 245, 245), width=3)
    fonts.load("bold", 30).draw_on(
        d, (m + r, m + r + 1), str(n), fill=(255, 255, 255), anchor="mm")
    return card


def main() -> None:
    src = sample()
    cards = [numbered(render.render_quote(src, QUOTE, WHO, MARK, name), i)
             for i, name in enumerate(render.TEMPLATE_ORDER, 1)]

    h = sum(c.height for c in cards) + GAP * (len(cards) + 1)
    sheet = Image.new("RGB", (CARD_W + 2 * GAP, h), BACK)
    y = GAP
    for card in cards:
        sheet.paste(card, (GAP, y))
        y += card.height + GAP
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT, optimize=True)
    print(f"{OUT} {sheet.size} {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
