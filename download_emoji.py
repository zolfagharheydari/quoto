"""Fetch the Twemoji PNG set into assets/emoji/.

The bundled fonts have no emoji glyphs, and rendering emoji from a colour font
needs libraqm to join families, flags and skin tones into single glyphs — which
the usual Pillow wheels are built without. Pasting a picture per emoji sidesteps
both problems and gets the composite sequences right, because each one is simply
its own file.

Run once after installing: python download_emoji.py
"""
from __future__ import annotations

import io
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

# The npm package ships only SVG, which Pillow cannot read, so the PNGs come
# from the repository archive instead.
ARCHIVE = "https://codeload.github.com/jdecked/twemoji/tar.gz/refs/heads/main"
WANTED = "assets/72x72/"
OUTDIR = Path(__file__).parent / "assets" / "emoji"


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "quotebot-setup"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main() -> int:
    if OUTDIR.exists() and any(OUTDIR.glob("*.png")):
        count = len(list(OUTDIR.glob("*.png")))
        print(f"{count} emoji already in {OUTDIR}; delete the folder to re-download")
        return 0

    print("downloading the Twemoji archive ...")
    blob = _get(ARCHIVE)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    written = 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar:
            # Members sit under a "twemoji-main/" prefix; take only the 72px PNGs.
            if not member.isfile() or WANTED not in member.name:
                continue
            if not member.name.endswith(".png"):
                continue
            source = tar.extractfile(member)
            if source is None:
                continue
            with (OUTDIR / Path(member.name).name).open("wb") as target:
                shutil.copyfileobj(source, target)
            written += 1

    size = sum(f.stat().st_size for f in OUTDIR.glob("*.png"))
    print(f"wrote {written} images to {OUTDIR} ({size / 1e6:.1f} MB)")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
