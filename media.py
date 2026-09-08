"""Convert a replied-to message's media to a sticker or an animation, as-is."""
from __future__ import annotations

import io
import logging
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from animate import _ffmpeg

log = logging.getLogger(__name__)

MAX_GIF_SECONDS = 10
STICKER_SIDE = 512
STICKER_MAX_BYTES = 500 * 1024


class ConversionError(RuntimeError):
    """Raised with an i18n key; the handler translates it for the user."""


def _run(args: list[str]) -> None:
    exe = _ffmpeg()
    if not exe:
        # The user is told something vague on purpose; this line is for the operator.
        log.error("ffmpeg not found - install it, or pip install imageio-ffmpeg")
        raise ConversionError("no_ffmpeg")
    proc = subprocess.run([exe, "-y", "-loglevel", "error", *args],
                          capture_output=True, timeout=180)
    if proc.returncode != 0:
        log.warning("ffmpeg: %s", proc.stderr.decode("utf-8", "ignore")[:800])
        raise ConversionError("convert_failed")


def image_to_sticker(data: bytes) -> io.BytesIO:
    """Any still image -> WEBP with its longest side exactly 512px (transparency kept)."""
    img = Image.open(io.BytesIO(data))
    img = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
    scale = STICKER_SIDE / max(img.size)
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                     Image.LANCZOS)
    for quality in (95, 85, 72, 60, 45):
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=quality, method=6)
        if buf.tell() <= STICKER_MAX_BYTES:
            buf.seek(0)
            return buf
    buf.seek(0)
    return buf


def video_to_sticker(data: bytes, suffix: str) -> io.BytesIO:
    """Video/animation -> WEBM VP9 video sticker (<=3s, 512px, 30fps, <=256 KB)."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{suffix}"
        dst = Path(tmp) / "out.webm"
        src.write_bytes(data)
        vf = (f"scale='if(gt(iw,ih),{STICKER_SIDE},-2)':'if(gt(iw,ih),-2,{STICKER_SIDE})'"
              ",fps=30")
        _run(["-t", "3", "-i", str(src), "-vf", vf, "-an",
              "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "40", "-pix_fmt", "yuva420p",
              str(dst)])
        return io.BytesIO(dst.read_bytes())


def to_animation(data: bytes, suffix: str) -> tuple[io.BytesIO, str]:
    """Video/animation/still -> muted MP4 suitable for sendAnimation (Telegram 'GIF')."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{suffix}"
        dst = Path(tmp) / "out.mp4"
        src.write_bytes(data)
        # Even dimensions are mandatory for yuv420p; cap the width so files stay small.
        vf = "scale='min(480,iw)':-2:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2"
        args = ["-t", str(MAX_GIF_SECONDS), "-i", str(src), "-vf", vf, "-an",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]
        if suffix in (".png", ".jpg", ".jpeg", ".webp"):
            args = ["-loop", "1", "-t", "3", "-i", str(src), "-vf", vf,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]
        _run(args)
        return io.BytesIO(dst.read_bytes()), "mp4"


def to_real_gif(data: bytes, suffix: str) -> io.BytesIO:
    """Video -> an actual .gif file (for people who want the file, not Telegram's MP4)."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{suffix}"
        palette = Path(tmp) / "palette.png"
        dst = Path(tmp) / "out.gif"
        src.write_bytes(data)
        chain = "fps=15,scale=400:-1:flags=lanczos"
        _run(["-t", str(MAX_GIF_SECONDS), "-i", str(src), "-vf", f"{chain},palettegen",
              str(palette)])
        _run(["-t", str(MAX_GIF_SECONDS), "-i", str(src), "-i", str(palette),
              "-lavfi", f"{chain}[x];[x][1:v]paletteuse", str(dst)])
        return io.BytesIO(dst.read_bytes())
