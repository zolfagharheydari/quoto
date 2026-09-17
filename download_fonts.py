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


# Apple's emoji are what Telegram itself shows on iOS, and they are the ones
# people picture when they picture a reaction. Apple does not license the font
# for use off its own devices, so this is never fetched by default: it happens
# only when someone asks for it by name, and that choice is theirs to make.
APPLE = {
    "name": "AppleColorEmoji.ttf",
    "repo": "samuelngs/apple-emoji-ttf",
    "asset": "AppleColorEmoji-Linux.ttf",
}


def fetch_apple() -> int:
    """Download a prebuilt Apple emoji font from its most recent release."""
    import json

    DEST.mkdir(parents=True, exist_ok=True)
    target = DEST / APPLE["name"]
    if target.exists():
        print(f"= {APPLE['name']} (already here)")
        return 0
    try:
        url = f"https://api.github.com/repos/{APPLE['repo']}/releases"
        headers = {"User-Agent": "quotebot"}
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as resp:
            releases = json.loads(resp.read())
        asset = next(
            a for release in releases for a in release.get("assets", [])
            if a["name"] == APPLE["asset"]
        )
        request = urllib.request.Request(asset["browser_download_url"], headers=headers)
        with urllib.request.urlopen(request, timeout=600) as resp:
            data = resp.read()
        target.write_bytes(data)
        print(f"+ {APPLE['name']} ({len(data) // 1024 // 1024} MB)")
    except Exception as exc:  # noqa: BLE001
        print(f"! {APPLE['name']}: {exc}")
        print(f"  Grab {APPLE['asset']} from a release of "
              f"https://github.com/{APPLE['repo']} and save it to "
              f"{DEST / APPLE['name']}")
        return 1
    return 0


def main() -> int:
    if "--apple" in sys.argv:
        return fetch_apple()
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
