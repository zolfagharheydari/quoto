"""Fetch the fonts the bot draws with into assets/fonts/.

Every file is fetched from a fixed commit or release - never a branch, which
can change under the same URL - and checked against the SHA-256 recorded here
before it is written. A font is parsed by native code in every render, so a
file that is not exactly the one that was looked at is not used at all.

To move to a newer version: download it, look at it, and put its new URL and
hash here.
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

DEST = Path(__file__).parent / "assets" / "fonts"

_VAZIRMATN = ("https://raw.githubusercontent.com/rastikerdar/vazirmatn/"
              "6e553e33489a8f9dfaccc76860a2e3f3c1e66de7/fonts/ttf/")

# name: (url, sha256)
FONTS = {
    # Persian, in three weights.
    "Vazirmatn-Regular.ttf": (
        _VAZIRMATN + "Vazirmatn-Regular.ttf",
        "b69fd4c680b8f3f225feabcc655a2c585d97627b8f5f5c0f9985e894069f3a56"),
    "Vazirmatn-Medium.ttf": (
        _VAZIRMATN + "Vazirmatn-Medium.ttf",
        "b986623e4ddef10755e04be39f8ea7bcb1dc08bfe8dd0aa6af395736f256ad4a"),
    "Vazirmatn-Bold.ttf": (
        _VAZIRMATN + "Vazirmatn-Bold.ttf",
        "f635fdbea28f265de395ba83b4b1570dcf2f58d13c65469e61903b1c2d2ae723"),
    # The decorative alphabets display names are written in. Without it they
    # cannot be drawn and get folded back to plain letters.
    "NotoSansMath-Regular.ttf": (
        "https://raw.githubusercontent.com/google/fonts/"
        "47d54ca1ebb14fd864695f1d39dc734f39017c33/ofl/notosansmath/NotoSansMath-Regular.ttf",
        "3f495fe933c06786e4d5f6d86b8ee70b6753a68ee3b9d87528726de0f6e2c47d"),
    # Reactions need colour emoji, and the ones a machine happens to have
    # differ: Windows draws the flat Segoe set, a bare server none at all.
    # Noto v2.051, the closest freely licensed set to Telegram's own.
    "NotoColorEmoji.ttf": (
        "https://raw.githubusercontent.com/googlefonts/noto-emoji/"
        "f3ae03f5e9b3b8516fa151f7168159ca1a3e7515/fonts/NotoColorEmoji.ttf",
        "72a635cb3d2f3524c51620cdde406b217204e8a6a06c6a096ff8ed4b5fd6e27b"),
}

# Apple's emoji are what Telegram shows on iOS. Apple does not license the font
# for use off its own devices, so it is fetched only when asked for by name
# (--apple), and that choice is whoever runs this. A prebuilt copy from a
# third-party repository - one fixed release of it, checked like the rest.
APPLE = {
    "AppleColorEmoji.ttf": (
        "https://github.com/samuelngs/apple-emoji-ttf/releases/download/"
        "macos-26-20260219-2aa12422/AppleColorEmoji-Linux.ttf",
        "535a043af04706d24471059e64745bfc80d6617ada2eea3435dc5620dc0f5318"),
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(fonts: dict) -> list[str]:
    """Download what is missing; check what is there. Returns the names that failed."""
    DEST.mkdir(parents=True, exist_ok=True)
    failed = []
    for name, (url, expected) in fonts.items():
        target = DEST / name
        if target.exists():
            if _sha256(target.read_bytes()) == expected:
                print(f"= {name}")
            else:
                # Not deleted: it may be a deliberate local change. But it is
                # not the file this list vouches for, and that is worth saying.
                print(f"! {name} is here but is not the expected file "
                      f"(sha256 differs); remove it to fetch the checked one")
                failed.append(name)
            continue
        if not url.startswith("https://"):
            print(f"! {name}: refusing a non-https URL")
            failed.append(name)
            continue
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "quotebot"})
            # https only (checked above), and the bytes are hash-checked below.
            with urllib.request.urlopen(request, timeout=600) as resp:  # nosec B310
                data = resp.read()
        except Exception as exc:  # noqa: BLE001 - report and keep going
            print(f"! {name}: {exc}")
            failed.append(name)
            continue
        got = _sha256(data)
        if got != expected:
            print(f"! {name}: downloaded file does not match its hash "
                  f"(got {got[:16]}..., expected {expected[:16]}...); not saved")
            failed.append(name)
            continue
        target.write_bytes(data)
        print(f"+ {name} ({len(data) // 1024} KB, verified)")
    return failed


def main() -> int:
    failed = fetch(APPLE if "--apple" in sys.argv else FONTS)
    if failed:
        print("\nSome fonts are missing or unverified: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
