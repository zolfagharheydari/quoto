"""Fetch Vazirmatn into assets/fonts/ so Persian text renders correctly."""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/rastikerdar/vazirmatn/master/fonts/ttf"
FILES = ["Vazirmatn-Regular.ttf", "Vazirmatn-Medium.ttf", "Vazirmatn-Bold.ttf"]
DEST = Path(__file__).parent / "assets" / "fonts"

# Reactions need colour emoji, and the ones a machine happens to have differ:
# Windows draws the flat Segoe set, a bare server draws none at all. Bundling
# Noto means the same picture comes out of every machine, and it is the closest
# freely licensed set to the rounded emoji Telegram itself shows. (Apple's, which
# Telegram uses on iOS, cannot be redistributed.)
EXTRA = {
    "NotoColorEmoji.ttf":
        "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/fonts/"
        "NotoColorEmoji.ttf",
}


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    failed = []
    wanted = {name: f"{BASE}/{name}" for name in FILES}
    wanted.update(EXTRA)
    for name, url in wanted.items():
        target = DEST / name
        if target.exists():
            print(f"= {name} (already here)")
            continue
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                data = resp.read()
            target.write_bytes(data)
            print(f"+ {name} ({len(data) // 1024} KB)")
        except Exception as exc:  # noqa: BLE001 - report and keep going
            failed.append(name)
            print(f"! {name}: {exc}")

    if failed:
        print(
            "\nDownload failed. Grab the TTFs manually from "
            "https://github.com/rastikerdar/vazirmatn/releases "
            f"and drop them in {DEST}"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
