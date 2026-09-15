"""Animated output: a typewriter reveal of the quote, encoded as MP4 (preferred) or GIF."""
from __future__ import annotations

import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from render import Scene

log = logging.getLogger(__name__)

FPS = 16
ANIM_W, ANIM_H = 800, 450          # both even; required by yuv420p

# The typing pass is timed by how much there is to type, so a long quote does not
# race past at the same speed a three-word one is comfortable at. Clamped at both
# ends: short quotes should not crawl, long ones should not outstay the reader.
TYPE_CPS = 15.0                    # characters revealed per second
MIN_TYPE_SECONDS = 2.4
MAX_TYPE_SECONDS = 9.0
LEAD_IN_SECONDS = 0.4              # a beat on the empty card before typing starts
AUTHOR_FADE_SECONDS = 0.6          # the name fading in once the quote is done
HOLD_SECONDS = 1.4                 # everything on screen, before the loop restarts


def _ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # pragma: no cover - optional dependency
        log.info("no ffmpeg available; falling back to GIF")
        return None


def _timeline(scene: Scene) -> tuple[int, int, int, int]:
    """Frame counts for (lead-in, typing, author fade, hold)."""
    chars = sum(len(line) for line in scene.lines) or 1
    seconds = min(MAX_TYPE_SECONDS, max(MIN_TYPE_SECONDS, chars / TYPE_CPS))
    return (
        max(1, round(LEAD_IN_SECONDS * FPS)),
        max(1, round(seconds * FPS)),
        max(1, round(AUTHOR_FADE_SECONDS * FPS)),
        max(1, round(HOLD_SECONDS * FPS)),
    )


def _frames(scene: Scene) -> list[Image.Image]:
    lead, typing, fade, hold = _timeline(scene)
    out = []
    for i in range(lead + typing + fade + hold):
        reveal = (i - lead) / typing
        author = (i - lead - typing) / fade
        frame = scene.render(reveal=reveal, author_alpha=author)
        out.append(frame.resize((ANIM_W, ANIM_H), Image.LANCZOS))
    return out


def to_gif(scene: Scene) -> io.BytesIO:
    frames = _frames(scene)
    # One shared adaptive palette keeps the grayscale portrait from flickering.
    palette = frames[-1].convert("P", palette=Image.ADAPTIVE, colors=128)
    quantized = [f.quantize(palette=palette, dither=Image.FLOYDSTEINBERG) for f in frames]
    buf = io.BytesIO()
    quantized[0].save(
        buf, "GIF", save_all=True, append_images=quantized[1:],
        duration=int(1000 / FPS), loop=0, optimize=True, disposal=1,
    )
    buf.seek(0)
    return buf


def to_mp4(scene: Scene) -> io.BytesIO | None:
    exe = _ffmpeg()
    if not exe:
        return None
    frames = _frames(scene)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "quote.mp4"
        cmd = [
            exe, "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{ANIM_W}x{ANIM_H}", "-r", str(FPS), "-i", "pipe:0",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(out),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for frame in frames:
                proc.stdin.write(frame.convert("RGB").tobytes())
            proc.stdin.close()
        except BrokenPipeError:
            pass
        _, err = proc.communicate(timeout=120)
        if proc.returncode != 0 or not out.exists():
            log.warning("ffmpeg failed: %s", err.decode("utf-8", "ignore")[:500])
            return None
        return io.BytesIO(out.read_bytes())


def to_animation(scene: Scene) -> tuple[io.BytesIO, str]:
    """Returns (buffer, extension). MP4 when ffmpeg is around, otherwise GIF."""
    mp4 = to_mp4(scene)
    if mp4 is not None:
        return mp4, "mp4"
    return to_gif(scene), "gif"
