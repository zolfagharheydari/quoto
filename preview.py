"""Render sample cards without touching Telegram. Usage: python preview.py [out_dir]"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

import animate
import render

SAMPLES = [
    ("fa", "من تنبل نیستم، فقط رفتم روی حالت ذخیره انرژی", "علیرضا موسوی", "alireza"),
    ("en", "i'm not lazy, i'm on energy saving mode", "brian", "brian"),
    ("long_fa", "هر وقت فکر کردم دیگه هیچ کاری از دستم برنمیاد، یادم افتاد که "
               "همین فکر کردن هم خودش یه جور کار کردنه و بعد دوباره خوابیدم.",
     "سارا احمدی", "sara_a"),
]


def stand_in_portrait(size: int = 900) -> Image.Image:
    """A synthetic head-and-shoulders shape, only so the layout can be eyeballed."""
    img = Image.new("RGB", (size, size), (58, 58, 62))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        shade = int(30 + 70 * (y / size))
        draw.line([(0, y), (size, y)], fill=(shade, shade, shade + 4))
    draw.ellipse([size * 0.28, size * 0.12, size * 0.72, size * 0.56], fill=(196, 186, 178))
    draw.ellipse([size * 0.24, size * 0.06, size * 0.76, size * 0.34], fill=(30, 28, 30))
    draw.polygon([(size * 0.02, size), (size * 0.28, size * 0.52),
                  (size * 0.72, size * 0.52), (size * 0.98, size)], fill=(24, 24, 26))
    return img


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "preview_out")
    out.mkdir(parents=True, exist_ok=True)
    portrait = stand_in_portrait()

    for tag, text, name, _handle in SAMPLES:
        scene = render.build_scene(portrait, text, name, watermark="@MyQuoteBot")
        scene.render().save(out / f"{tag}.png")
        render.to_sticker_webp(scene.render()).getbuffer()
        print(f"wrote {out / f'{tag}.png'}")

    scene = render.build_scene(portrait, SAMPLES[0][1], SAMPLES[0][2],
                               watermark="@MyQuoteBot")
    buf, ext = animate.to_animation(scene)
    (out / f"animation.{ext}").write_bytes(buf.getvalue())
    print(f"wrote {out / f'animation.{ext}'} ({len(buf.getvalue()) // 1024} KB)")

    # Fallback avatar path (users with no profile photo).
    render.build_scene(render.fallback_avatar("42", "ع"), "بدون عکس پروفایل هم کار می‌کنه",
                       "کاربر بی‌عکس").render().save(out / "no_avatar.png")
    print(f"wrote {out / 'no_avatar.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
