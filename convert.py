"""Turning one kind of media into another: a photo into a GIF, a GIF into a video.

Reply to a photo or a video with «تبدیل به گیف» or «تبدیل به استیکر», to a GIF
or an animated sticker with «تبدیل به ویدیو», to a sticker with «تبدیل به عکس».
A GIF or a sticker can be made of one stretch of a video: «تبدیل به گیف ۱:۲۰ تا ۱:۳۵».
And words can be written on a GIF or any sticker: «روش بنویس سلام» (caption()).

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
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

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


class BadSpan(Exception):
    """A stretch of a video that cannot be cut: `reason` is "order", "long" or "past".

    `seconds` is the longest a stretch may be ("long"), or how long the video
    actually is ("past").
    """

    def __init__(self, reason: str, seconds: int = 0):
        super().__init__(reason)
        self.reason, self.seconds = reason, seconds


# The longest stretch each kind of result can be cut from.
SPAN_LIMIT = {"gif": GIF_SECONDS, "sticker": VIDEO_STICKER_SECONDS}


def check_span(target: str, span) -> None:
    """Raise BadSpan unless (start, end) - end None for "from start on" - can be cut.

    Whether the start is inside the video is only known once it is downloaded;
    this is what can be said before that.
    """
    if span is None or target not in SPAN_LIMIT:
        return
    start, end = span
    if end is not None and end <= start:
        raise BadSpan("order")
    if end is not None and end - start > SPAN_LIMIT[target]:
        raise BadSpan("long", SPAN_LIMIT[target])


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
    """Raise if `target` cannot be made from `kind`, or the file is too big to fetch.

    "caption" is words written on it, which only a GIF or a sticker can take.
    """
    allowed = CAPTION_KINDS if target == "caption" else TARGETS.get(target, ())
    if kind not in allowed:
        raise Unsupported(f"{target} from {kind}")
    if size > MAX_INPUT_BYTES:
        raise TooBig(size)


# ------------------------------------------------------------------ helpers
def _run(args: list[str]) -> None:
    done = subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", *args],
                          capture_output=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise RuntimeError("ffmpeg: " + done.stderr.decode("utf-8", "ignore")[-400:])


def _duration(src: Path) -> float | None:
    """How long a video runs, from what ffmpeg says about it; None if it does not say."""
    done = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(src)],
                          capture_output=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    found = re.search(rb"Duration: (\d+):(\d\d):(\d\d(?:\.\d+)?)", done.stderr)
    if found is None:
        return None
    hours, minutes, seconds = found.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _window(src: Path, span, limit: float) -> tuple[list[str], str]:
    """Where to start reading (ffmpeg's -ss) and for how long (its -t).

    No span is the start of the video, as before. A span is cut where it says,
    to the end of the video at the latest, and never longer than `limit`.
    """
    if span is None:
        return [], f"{limit:g}"
    start, end = span
    length = _duration(src)
    if length is not None and start >= length:
        raise BadSpan("past", int(length))
    stop = start + limit if end is None else min(end, start + limit)
    if length is not None:
        stop = min(stop, length)
    return ["-ss", f"{start:g}"], f"{stop - start:g}"


def _vp9(bitrate: str, out: Path) -> list[str]:
    """How a video sticker is written: VP9 with its transparency, no sound."""
    return ["-an", "-c:v", "libvpx-vp9", "-b:v", bitrate, "-crf", "34", "-deadline", "good",
            "-row-mt", "1", "-pix_fmt", "yuva420p", str(out)]


def _webm_within(encode, webm: Path) -> bytes:
    """A video sticker at the first bitrate that keeps it to Telegram's 256 KB."""
    for bitrate in ("700k", "450k", "280k", "160k", "90k"):
        encode(bitrate)
        if webm.stat().st_size <= VIDEO_STICKER_BYTES:
            return webm.read_bytes()
    raise Unsupported("could not fit a video sticker in 256 KB")


def _dimensions(src: Path) -> tuple[int, int] | None:
    """A video's width and height, from what ffmpeg says about it."""
    done = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(src)],
                          capture_output=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    found = re.search(rb"Video: .*?, (\d{2,5})x(\d{2,5})[, \[]", done.stderr)
    return (int(found.group(1)), int(found.group(2))) if found else None


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
def convert(target: str, kind: str, data: bytes, span=None) -> tuple[bytes, str]:
    """Make `target` from `data`, which is a `kind`. Returns (bytes, file extension).

    `span` is (start, end) in seconds, end None for "from start on": the
    stretch of a video or a GIF that a GIF or a video sticker is cut from.
    Anything without a timeline - a photo, an animated sticker - ignores it.
    """
    check_span(target, span)
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
            seek, seconds = _window(src, span, VIDEO_STICKER_SECONDS)
            return _webm_within(lambda bitrate: _run(
                [*seek, "-i", str(src), "-t", seconds, "-vf", scale, *_vp9(bitrate, webm)]),
                webm), "webm"

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
                seek, seconds = _window(src, span, GIF_SECONDS)
                _run([*decoder, *seek, "-i", str(src), "-t", seconds, "-an",
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


# ------------------------------------------------------------------ words on it
# «روش بنویس ...» on a GIF or a sticker: the words at the bottom, white with a
# dark outline, the way a caption sits on a meme - it reads on any picture and
# on a sticker's transparency alike. The words are drawn once, as a transparent
# picture the size of the result, and laid over every frame: by ffmpeg for a
# GIF or a video sticker, by Pillow for a still sticker and for the frames
# rlottie draws from an animated one.
CAPTION_KINDS = ("sticker", "video_sticker", "animated_sticker", "animation")
CAPTION_MAX_CHARS = 120
CAPTION_MIN_SIDE = 480          # a small GIF is enlarged first, or its words would blur
CAPTION_MAX_SIDE = 960          # and a big one kept big enough: the fire clip is 854 wide


def _lay_out(text: str, width: float, height: float, sizes: range):
    """(lines, font, line height, rtl) for `text` in a box, as big as it fits.

    Wrapping greedily leaves one word alone on the last line; the narrowest
    width that still takes as many lines shares the words out evenly. What
    still does not fit is cut short.
    """
    import fonts
    import textkit

    rtl = textkit.is_rtl(text)
    lines, font, line_height = textkit.fit(
        text, lambda s: fonts.load("bold", s), width, height, sizes,
        line_spacing=1.22, rtl=rtl)
    limit = width
    while len(lines) > 1 and limit > width * 0.5:
        tried = textkit.wrap(text, font, limit * 0.95, rtl)
        if len(tried) != len(lines):
            break
        lines, limit = tried, limit * 0.95
    most = max(1, int(height) // line_height)
    if len(lines) > most:
        lines = lines[:most]
        lines[-1] = lines[-1].rstrip() + "…"
    return lines, font, line_height, rtl


def _caption_layer(size: tuple[int, int], text: str) -> Image.Image:
    """The words alone, on a transparent picture of `size`."""
    import textkit

    width, height = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    margin = round(width * 0.05)
    lines, font, line_height, rtl = _lay_out(
        text, width - 2 * margin, height * 0.4,
        range(max(14, height // 6), max(12, height // 22) - 1, -2))
    stroke = max(2, round(font.size / 11))
    draw = ImageDraw.Draw(layer)
    first = height - margin - len(lines) * line_height + line_height // 2
    for i, line in enumerate(lines):
        font.draw_on(draw, (width / 2, first + i * line_height), textkit.shape(line, rtl),
                     fill=(255, 255, 255, 255), anchor="mm",
                     stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    return layer


def _fit_side(size: tuple[int, int], longest: int, at_least: int = 0) -> tuple[int, int]:
    """`size` scaled so its long side is `longest` at most (and `at_least` at
    least), both sides even."""
    w, h = size
    scale = min(longest / max(w, h), max(1.0, at_least / max(w, h)))
    return max(2, round(w * scale / 2) * 2), max(2, round(h * scale / 2) * 2)


def caption_picture(data: bytes, text: str) -> bytes:
    """`text` above a picture of the bot's own making - a quote card - as PNG.

    Only ever the bot's own: a photo someone sends is not something words go
    on (CAPTION_KINDS), but a card made with words asked for alongside is.
    """
    image = Image.open(io.BytesIO(data), formats=("PNG",)).convert("RGB")
    band = _caption_band(image.width, text).convert("RGB")
    out = Image.new("RGB", (image.width, band.height + image.height))
    out.paste(band, (0, 0))
    out.paste(image, (0, band.height))
    buf = io.BytesIO()
    out.save(buf, "PNG", compress_level=6)
    return buf.getvalue()


# The bot's own cards, stickers and clips are mostly words already: a quote, a
# name, a handle. Written over them the caption buries what was made, so on
# those it goes above instead, in black on a white band of its own - the way a
# meme carries a caption over a picture that has words in it.
BAND_PAPER = (255, 255, 255, 255)
BAND_INK = (17, 17, 17, 255)


def _caption_band(width: int, text: str) -> Image.Image:
    """The words in a white band `width` wide and as tall as they need, at most
    three lines."""
    import textkit

    pad = max(8, round(width * 0.045))
    size = max(16, width // 13)
    lines, font, line_height, rtl = _lay_out(
        text, width - 2 * pad, int(size * 1.22) * 3,
        range(size, max(12, width // 30) - 1, -2))
    height = len(lines) * line_height + 2 * pad
    height += height % 2                     # even, for the video it may top
    band = Image.new("RGBA", (width, height), BAND_PAPER)
    draw = ImageDraw.Draw(band)
    for i, line in enumerate(lines):
        font.draw_on(draw, (width / 2, pad + i * line_height + line_height / 2),
                     textkit.shape(line, rtl), fill=BAND_INK, anchor="mm")
    return band


def caption_above(kind: str, data: bytes, text: str) -> tuple[bytes, str]:
    """`text` in a band above a sticker ("sticker", .webp) or a GIF ("animation",
    .mp4) of the bot's own making. Returns (bytes, file extension)."""
    if kind == "sticker":
        image = _open_picture(data).convert("RGBA")
        band = _caption_band(image.width, text)
        out = Image.new("RGBA", (image.width, band.height + image.height), (0, 0, 0, 0))
        out.paste(band, (0, 0))
        out.alpha_composite(image, (0, band.height))
        scale = STICKER_SIDE / max(out.size)
        out = out.resize((max(1, round(out.width * scale)), max(1, round(out.height * scale))),
                         Image.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, "WEBP", quality=90, method=6)
        return buf.getvalue(), "webp"
    if kind != "animation":
        raise Unsupported(f"a band above {kind}")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "in"
        src.write_bytes(data)
        found = _dimensions(src)
        if found is None:
            raise Unsupported("no picture in it")
        w, h = _fit_side(found, CAPTION_MAX_SIDE, CAPTION_MIN_SIDE)
        band = _caption_band(w, text)
        band.convert("RGB").save(tmp / "band.png")
        mp4 = tmp / "out.mp4"
        graph = (f"[0:v]scale={w}:{h}:flags=bicubic,setsar=1,"
                 f"pad={w}:{h + band.height}:0:{band.height}:white[v];[v][1:v]overlay=0:0[out]")
        _run(["-i", str(src), "-i", str(tmp / "band.png"), "-filter_complex", graph,
              "-map", "[out]", "-t", str(GIF_SECONDS), "-an", "-c:v", "libx264",
              "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
              "-movflags", "+faststart", str(mp4)])
        return mp4.read_bytes(), "mp4"


def caption(kind: str, data: bytes, text: str) -> tuple[bytes, str]:
    """`text` written on a GIF or a sticker. Returns (bytes, file extension):
    an mp4 for a GIF, a sticker otherwise - .webp for a still one, .webm for
    one that moves, which an animated (.tgs) sticker becomes too."""
    if kind not in CAPTION_KINDS:
        raise Unsupported(f"words on {kind}")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "in"
        src.write_bytes(data)
        layer_png = tmp / "words.png"

        if kind == "sticker":
            image = _open_picture(data).convert("RGBA")
            # A sticker's long side is exactly 512, so a smaller one grows to it.
            scale = STICKER_SIDE / max(image.size)
            size = (round(image.width * scale), round(image.height * scale))
            image = image.resize(size, Image.LANCZOS)
            image.alpha_composite(_caption_layer(size, text))
            buf = io.BytesIO()
            image.save(buf, "WEBP", quality=90, method=6)
            return buf.getvalue(), "webp"

        webm = tmp / "out.webm"
        if kind == "animated_sticker":
            frames, fps = _tgs_frames(data, max_seconds=VIDEO_STICKER_SECONDS)
            layer = _caption_layer(frames[0].size, text)
            raw = tmp / "frames.rgba"
            with raw.open("wb") as out:
                for frame in frames:
                    frame = frame.convert("RGBA")
                    frame.alpha_composite(layer)
                    out.write(frame.tobytes())
            w, h = frames[0].size
            del frames
            return _webm_within(lambda bitrate: _run(
                ["-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-r", f"{fps:.3f}",
                 "-i", str(raw), "-t", str(VIDEO_STICKER_SECONDS), *_vp9(bitrate, webm)]),
                webm), "webm"

        found = _dimensions(src)
        if found is None:
            raise Unsupported("no picture in it")
        if kind == "video_sticker":
            size = _fit_side(found, STICKER_SIDE, STICKER_SIDE)
        else:
            size = _fit_side(found, CAPTION_MAX_SIDE, CAPTION_MIN_SIDE)
        _caption_layer(size, text).save(layer_png)
        w, h = size
        if kind == "video_sticker":
            graph = (f"[0:v]scale={w}:{h}:flags=area,setsar=1,fps=30,format=rgba[v];"
                     "[v][1:v]overlay=0:0:format=auto[out]")
            return _webm_within(lambda bitrate: _run(
                ["-c:v", "libvpx-vp9", "-i", str(src), "-i", str(layer_png),
                 "-filter_complex", graph, "-map", "[out]", "-t", str(VIDEO_STICKER_SECONDS),
                 *_vp9(bitrate, webm)]), webm), "webm"
        mp4 = tmp / "out.mp4"
        graph = f"[0:v]scale={w}:{h}:flags=bicubic,setsar=1[v];[v][1:v]overlay=0:0[out]"
        _run(["-i", str(src), "-i", str(layer_png), "-filter_complex", graph, "-map", "[out]",
              "-t", str(GIF_SECONDS), "-an", "-c:v", "libx264", "-preset", "veryfast",
              "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)])
        return mp4.read_bytes(), "mp4"
