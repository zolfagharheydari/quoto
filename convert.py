"""Turning one kind of media into another: a photo into a GIF, a GIF into a video.

Reply to a photo or a video with «تبدیل به گیف» or «تبدیل به استیکر», to a GIF
or an animated sticker with «تبدیل به ویدیو», to a sticker with «تبدیل به عکس».

Everything here runs in a worker thread behind its own gate and works on
bytes in a temporary directory; ffmpeg does the video and runs under a
timeout, rlottie draws the animated (.tgs) stickers. Nothing a user sends is
trusted further than it has to be: sizes are checked before anything is
downloaded, pictures are opened only as the formats they claim to be, and a
.tgs is unpacked with a ceiling on what it may expand to.
"""
from __future__ import annotations

import gzip
import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

MAX_INPUT_BYTES = 20 * 1024 * 1024      # the most a bot may download from Telegram
TIMEOUT = 90                             # seconds for any one ffmpeg run

GIF_SECONDS = 30                         # a GIF is a loop, not a film
VIDEO_SECONDS = 60
STILL_GIF_SECONDS = 3                    # a photo made into a GIF: a short still loop
MAX_SIDE = 720

STICKER_SIDE = 512
VIDEO_STICKER_SECONDS = 3                # Telegram's rules for a video sticker
VIDEO_STICKER_BYTES = 256 * 1024
TGS_MAX_JSON = 4 * 1024 * 1024           # an animated sticker is a few hundred KB of JSON at most

PAPER = (255, 255, 255)                  # what transparency becomes in a photo or a video

# What each request can be made from. The source kinds are what media_of() reports.
TARGETS = {
    "gif": ("photo", "video", "video_sticker", "animated_sticker", "animation"),
    "sticker": ("photo", "video", "animation"),
    "video": ("animation", "video_sticker", "animated_sticker"),
    "photo": ("sticker", "video_sticker", "animated_sticker"),
}


class Unsupported(Exception):
    """This cannot be made from that."""


class TooBig(Exception):
    """The file is larger than a bot is allowed to download."""


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def media_of(message):
    """(kind, file_id, size) of what a message carries, or None.

    Kinds: photo, video, animation, sticker (static), video_sticker,
    animated_sticker. A video note counts as a video; a picture or a video
    sent as a file counts as what it is.
    """
    if message is None:
        return None
    if message.sticker is not None:
        s = message.sticker
        kind = ("animated_sticker" if s.is_animated else
                "video_sticker" if s.is_video else "sticker")
        return kind, s.file_id, s.file_size or 0
    if message.animation is not None:
        return "animation", message.animation.file_id, message.animation.file_size or 0
    if message.photo:
        best = message.photo[-1]
        return "photo", best.file_id, best.file_size or 0
    if message.video is not None:
        return "video", message.video.file_id, message.video.file_size or 0
    if getattr(message, "video_note", None) is not None:
        return "video", message.video_note.file_id, message.video_note.file_size or 0
    doc = message.document
    if doc is not None:
        mime = doc.mime_type or ""
        if mime in ("image/jpeg", "image/png", "image/webp"):
            return "photo", doc.file_id, doc.file_size or 0
        if mime.startswith("video/"):
            return "video", doc.file_id, doc.file_size or 0
    return None


def check(target: str, kind: str, size: int) -> None:
    """Raise if `target` cannot be made from `kind`, or the file is too big to fetch."""
    if kind not in TARGETS.get(target, ()):
        raise Unsupported(f"{target} from {kind}")
    if size > MAX_INPUT_BYTES:
        raise TooBig(size)


# ------------------------------------------------------------------ helpers
def _run(args: list[str]) -> None:
    done = subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", *args],
                          capture_output=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise RuntimeError("ffmpeg: " + done.stderr.decode("utf-8", "ignore")[-400:])


def _even_scale(longest: int) -> str:
    """Fit within `longest` on the long side, never enlarge, both sides even."""
    return (f"scale='if(gte(iw,ih),min({longest},iw),-2)':'if(gte(iw,ih),-2,min({longest},ih))'"
            ":flags=area,setsar=1")


def _flatten(image: Image.Image) -> Image.Image:
    """Transparency onto white: what a photo or a video shows instead."""
    image = image.convert("RGBA")
    out = Image.new("RGB", image.size, PAPER)
    out.paste(image, mask=image.getchannel("A"))
    return out


def _open_picture(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data), formats=("JPEG", "PNG", "WEBP"))
    if image.width * image.height > 16_000_000:
        raise Unsupported("picture too large")
    image.load()
    return image


def _tgs_frames(data: bytes, side: int = STICKER_SIDE, max_seconds: float = 10.0):
    """Frames of an animated sticker as RGBA images, and its frame rate."""
    from rlottie_python import LottieAnimation
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as packed:
        raw = packed.read(TGS_MAX_JSON + 1)
    if len(raw) > TGS_MAX_JSON:
        raise Unsupported("animated sticker too large")
    anim = LottieAnimation.from_data(raw.decode("utf-8"))
    try:
        rate = anim.lottie_animation_get_framerate() or 30
        total = anim.lottie_animation_get_totalframe()
        # At most 30 frames a second, and not longer than max_seconds.
        step = max(1, round(rate / 30))
        count = max(1, min(total, int(max_seconds * rate)))
        frames = [anim.render_pillow_frame(frame_num=i, width=side, height=side)
                  for i in range(0, count, step)]
        return frames, rate / step
    finally:
        del anim


def _frames_to_mp4(frames, fps: float, out: Path, audio: bool) -> None:
    """Pipe RGB frames into H.264, with a silent track when it is to be a video."""
    w, h = frames[0].size
    args = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", f"{fps:.3f}", "-i", "-"]
    if audio:
        args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest", "-c:a", "aac"]
    else:
        args += ["-an"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-movflags", "+faststart", str(out)]
    raw = b"".join(_flatten(f).tobytes() for f in frames)
    done = subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", *args], input=raw,
                          capture_output=True, timeout=TIMEOUT)
    if done.returncode != 0:
        raise RuntimeError("ffmpeg: " + done.stderr.decode("utf-8", "ignore")[-400:])


# What transparency in a video sticker becomes in a video: white, as in a photo.
_ON_WHITE = ("[0:v]format=rgba,setsar=1[s];color=c=white,format=rgb24[bg];"
             "[bg][s]scale2ref[bg][s];[bg][s]overlay=shortest=1:format=auto,setsar=1")


# ------------------------------------------------------------------ conversions
def convert(target: str, kind: str, data: bytes) -> tuple[bytes, str]:
    """Make `target` from `data`, which is a `kind`. Returns (bytes, file extension)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "in"
        src.write_bytes(data)
        out = tmp / "out"

        if target == "photo":
            if kind == "sticker":
                image = _flatten(_open_picture(data))
            elif kind == "animated_sticker":
                frames, _ = _tgs_frames(data, max_seconds=0.01)
                image = _flatten(frames[0])
            else:  # a video sticker: its first frame, alpha kept by the VP9 decoder
                _run(["-c:v", "libvpx-vp9", "-i", str(src), "-frames:v", "1",
                      "-f", "image2", "-vcodec", "png", str(out)])
                image = _flatten(Image.open(out, formats=("PNG",)))
            buf = io.BytesIO()
            image.save(buf, "PNG")
            return buf.getvalue(), "png"

        if target == "sticker":
            if kind == "photo":
                image = _open_picture(data).convert("RGBA")
                image.thumbnail((STICKER_SIDE, STICKER_SIDE), Image.LANCZOS)
                # A sticker's long side is exactly 512, so a small picture grows to it.
                scale = STICKER_SIDE / max(image.size)
                if scale > 1:
                    image = image.resize((round(image.width * scale), round(image.height * scale)),
                                         Image.LANCZOS)
                buf = io.BytesIO()
                image.save(buf, "WEBP", quality=90, method=6)
                return buf.getvalue(), "webp"
            # A video or a GIF: a video sticker, which Telegram holds to 3 seconds,
            # 512 pixels on the long side, no sound and 256 KB.
            webm = out.with_suffix(".webm")
            scale = (f"scale='if(gte(iw,ih),{STICKER_SIDE},-2)':'if(gte(iw,ih),-2,{STICKER_SIDE})'"
                     ":flags=area,fps=30")
            for bitrate in ("700k", "450k", "280k", "160k", "90k"):
                _run(["-i", str(src), "-t", str(VIDEO_STICKER_SECONDS), "-an", "-vf", scale,
                      "-c:v", "libvpx-vp9", "-b:v", bitrate, "-crf", "34", "-deadline", "good",
                      "-row-mt", "1", "-pix_fmt", "yuva420p", str(webm)])
                if webm.stat().st_size <= VIDEO_STICKER_BYTES:
                    return webm.read_bytes(), "webm"
            raise Unsupported("could not fit a video sticker in 256 KB")

        mp4 = out.with_suffix(".mp4")
        if target == "gif":
            if kind == "photo":
                image = _open_picture(data).convert("RGB")
                image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
                still = tmp / "still.png"
                image.save(still)
                _run(["-loop", "1", "-i", str(still), "-t", str(STILL_GIF_SECONDS), "-r", "10",
                      "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset",
                      "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-an",
                      "-movflags", "+faststart", str(mp4)])
            elif kind == "animated_sticker":
                frames, fps = _tgs_frames(data)
                _frames_to_mp4(frames, fps, mp4, audio=False)
            else:
                decoder = ["-c:v", "libvpx-vp9"] if kind == "video_sticker" else []
                _run([*decoder, "-i", str(src), "-t", str(GIF_SECONDS), "-an",
                      *(["-filter_complex", _ON_WHITE + "," + _even_scale(MAX_SIDE)]
                        if kind == "video_sticker" else ["-vf", _even_scale(MAX_SIDE)]),
                      "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                      "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)])
            return mp4.read_bytes(), "mp4"

        if target == "video":
            if kind == "animated_sticker":
                frames, fps = _tgs_frames(data)
                _frames_to_mp4(frames, fps, mp4, audio=True)
                return mp4.read_bytes(), "mp4"
            decoder = ["-c:v", "libvpx-vp9"] if kind == "video_sticker" else []
            graph = (_ON_WHITE + "," + _even_scale(MAX_SIDE) if kind == "video_sticker"
                     else _even_scale(MAX_SIDE))
            # A silent track, so Telegram keeps it a video instead of calling it a GIF.
            _run([*decoder, "-i", str(src), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                  "-t", str(VIDEO_SECONDS), "-filter_complex", f"{graph}[v]", "-map", "[v]",
                  "-map", "1:a", "-shortest", "-c:v", "libx264", "-preset", "veryfast",
                  "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
                  "-movflags", "+faststart", str(mp4)])
            return mp4.read_bytes(), "mp4"

    raise Unsupported(target)
