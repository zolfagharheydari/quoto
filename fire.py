"""/fire, «آتیشش کن»: the quote written in fire, on the "Gunna writing in fire" clip.

Four shots, and the quote goes where the clip already has writing:

  pen     the text comes out of the pen tip along the fire trail, a line at a
          time, the lines above it rising and fading
  face    the author's name
  page    the quote burned into the page on its own rules - same angle, same
          spacing - with the glove passing in front of it
  fire    the bot's handle

Handwriting fonts: Nastaliq for right-to-left text, a script face for Latin.

Everything that is the same for every quote - the clip scaled down, the old
handwriting erased off the page, how the page moves - is prepared once by
tools/make_fire_base.py and read from assets/fire/. A request only draws text
and encodes, which on the server is a few seconds instead of half a minute.
Without those files the command says it is unavailable rather than failing.
"""
from __future__ import annotations

import json
import logging
import tempfile
import unicodedata
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

import fonts
import textkit

log = logging.getLogger(__name__)

ASSETS = Path(__file__).with_name("assets") / "fire"
BASE = ASSETS / "base.mp4"
GEOMETRY = ASSETS / "page.json"
NASTALIQ = ASSETS / "IranNastaliq.ttf"
SCRIPT = ASSETS / "Cinderella.otf"

W, H, FPS = 1280, 720, 30

# The page holds about this much at a size that can still be read; longer
# quotes are turned away and pointed at /gif, rather than cut short.
MAX_CHARS = 100

PEN = (0.0, 1.9)
FACE = (2.2, 4.3)
PAGE = (4.3, 6.92)
FIRE = (6.92, 8.82)

# Where the pen tip is, read off the frames: (seconds, x, y).
PEN_TIP = [(0.45, 432, 428), (0.80, 420, 440), (1.05, 440, 480), (1.30, 460, 482),
           (1.55, 472, 475), (1.80, 470, 452)]
PEN_SIZE = 64
PEN_ROOM = 400                    # from the left edge of the frame to the pen tip
PEN_SLOPE = np.radians(-9)        # the fire trail rises a little to the left
PEN_SQUASH = 0.82                 # the table, seen at an angle

# The page's rules, measured on the frame at 5.6s: they run 30 degrees down to
# the right, 20px apart at 1080p.
REF = round(5.6 * FPS)
ANGLE = np.radians(30.0)
PITCH = 20 / 1.5
U = np.array([np.cos(ANGLE), np.sin(ANGLE)])          # along a rule
V = np.array([-np.sin(ANGLE), np.cos(ANGLE)])         # to the next one
PAGE_LEN = 245                    # how far the rules run before the glove
RULES_ON_PAGE = 11                # the old handwriting's seven, and room below
PAGE_SCALE = 4                    # the page text is drawn this much larger, then warped down

# How much bigger each handwriting face must be set to read as big as the
# bot's own font at the same size. By eye: Nastaliq's tall strokes fool any
# ink measurement, and the script face is a hairline.
HAND_SCALE = {NASTALIQ.name: 1.3, SCRIPT.name: 1.5}

INK = 0.94                        # how black the writing is, out of 1
LABEL = (255, 236, 205)           # the name and handle: warm white, like the fire
DASH = "—"


def available() -> bool:
    return BASE.exists() and GEOMETRY.exists()


# ------------------------------------------------------------------ timing
def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def window(t: float, start: float, end: float, fade: float = 0.18) -> float:
    """0 outside [start, end], easing up to 1 and back down at the edges."""
    if t < start or t > end:
        return 0.0
    return min(ease((t - start) / fade), ease((end - t) / fade))


# ------------------------------------------------------------------ text
# Pictures, not letters: no handwriting face has them, and a box in the
# middle of a burned-in line looks worse than the gap.
_DROP = {0x200D} | set(range(0xFE00, 0xFE10)) | set(range(0x1F3FB, 0x1F400))


def clean(text: str) -> str:
    """The quote as it will be written: one paragraph, no emoji."""
    kept = "".join(
        ch for ch in text
        if ord(ch) not in _DROP and unicodedata.category(ch) not in ("So", "Cs", "Co", "Cn"))
    return " ".join(kept.split())


class Shaped:
    """A face that does its own shaping, through raqm.

    Nastaliq cannot be drawn from pre-shaped presentation forms: its letters
    change shape and position with their neighbours in ways only the font's
    own tables know. So it is handed the text as typed and raqm lays it out -
    the one exception to fonts.py drawing everything pre-shaped.
    """
    raqm = True
    thin = False

    def __init__(self, path: Path, size: int):
        self.size = size
        self.font = ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.RAQM)

    # Nastaliq's own space is a sliver, under a tenth of the em, which runs
    # short words together. Two of them read as a gap.
    @staticmethod
    def _spaced(text: str) -> str:
        return text.replace(" ", "  ")

    def getlength(self, text: str) -> float:
        return self.font.getlength(self._spaced(text), direction="rtl")

    def draw_on(self, draw, xy, text, fill=None, anchor="la"):
        draw.text(xy, self._spaced(text), font=self.font, fill=fill, anchor=anchor,
                  direction="rtl")


class Script(fonts.FontSet):
    """The Latin handwriting: the bot's fallbacks behind it for anything it lacks."""
    __slots__ = ()
    raqm = False
    thin = True                   # a hairline; its strokes are fattened after drawing


@lru_cache(maxsize=1)
def _has_raqm() -> bool:
    return bool(features.check_feature("raqm"))


def face(text: str, size: float, scaled: bool = True):
    """The handwriting face for `text`, at a size that looks like `size`.

    Falls back to the bot's own font when the handwriting can't do the job:
    Nastaliq without raqm to shape it, or a quote with letters it lacks.
    """
    if textkit.is_rtl(text):
        covered = fonts._coverage(NASTALIQ) if NASTALIQ.exists() else frozenset()
        if _has_raqm() and covered and all(ch.isspace() or ord(ch) in covered for ch in text):
            k = HAND_SCALE[NASTALIQ.name] if scaled else 1.0
            return Shaped(NASTALIQ, max(8, int(size * k)))
    elif SCRIPT.exists():
        real = max(8, int(size * (HAND_SCALE[SCRIPT.name] if scaled else 1.0)))
        font = fonts._truetype(SCRIPT, real)
        if font is not None:
            fallbacks = [p for p in (fonts._resolve("bold"),) if p] + list(fonts._available_fallbacks())
            return Script(font, SCRIPT, fallbacks, real)
    return fonts.load("bold", max(8, int(size)))


def prep(text: str, font) -> str:
    """What to hand `font`: the text as typed if it shapes it, else shaped here."""
    if getattr(font, "raqm", False):
        return text
    return textkit.shape(text, textkit.is_rtl(text))


def wrap(text: str, font, width: float) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        test = (line + " " + word).strip()
        if not line or font.getlength(prep(test, font)) <= width:
            line = test
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


def thicken(layer: Image.Image, size: int) -> Image.Image:
    """Fatten hairline strokes so they survive being scaled down."""
    return layer.filter(ImageFilter.MaxFilter(size))


def _strip(font, text: str, height: int, anchor: str, pad: int = 20):
    """One line drawn on its own, and the columns its ink starts and ends at.

    Lines are drawn once, whole, and revealed a slice at a time - the way a
    hand writes, and far cheaper than drawing every frame's prefix again.
    """
    shown = prep(text, font)
    length = font.getlength(shown)
    img = Image.new("L", (int(length) + 2 * pad, height), 0)
    font.draw_on(ImageDraw.Draw(img), (pad + length, height / 2), shown, fill=255, anchor=anchor)
    return img, pad, pad + length


# ------------------------------------------------------------------ compositing
def darken(base: np.ndarray, alpha: np.ndarray, k: float) -> np.ndarray:
    a = alpha.astype(np.float32)[..., None] / 255.0 * k
    return (base.astype(np.float32) * (1 - a)).astype(np.uint8)


def paper_mask(frame: np.ndarray) -> np.ndarray:
    """Where the page shows: bright, so the dark glove in front of it is left out."""
    import cv2
    m = (frame.mean(axis=2) > 70).astype(np.uint8) * 255
    return cv2.GaussianBlur(cv2.erode(m, np.ones((5, 5), np.uint8)), (0, 0), 2)


def line_space_to_frame(origin, scale: float) -> np.ndarray:
    """From a canvas drawn along the rules (x along, y across) to the reference frame."""
    a = np.column_stack([U / scale, V / scale])
    return np.vstack([np.hstack([a, np.asarray(origin, float)[:, None]]), [0, 0, 1]])


class Label:
    """Text over the picture with a soft shadow, drawn once and faded per frame."""

    def __init__(self, parts):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for font, xy, text, anchor in parts:
            font.draw_on(d, (xy[0] + 2, xy[1] + 3), text, fill=(0, 0, 0, 190), anchor=anchor)
            font.draw_on(d, xy, text, fill=LABEL + (255,), anchor=anchor)
        box = layer.getbbox() or (0, 0, 1, 1)
        x0, y0, x1, y1 = box
        arr = np.asarray(layer.crop(box)).astype(np.float32)
        self.box = (x0, y0, x1, y1)
        self.rgb = arr[..., :3]
        self.alpha = arr[..., 3:4] / 255.0

    def over(self, frame: np.ndarray, a: float) -> np.ndarray:
        x0, y0, x1, y1 = self.box
        out = frame.copy()
        k = self.alpha * a
        region = out[y0:y1, x0:x1].astype(np.float32)
        out[y0:y1, x0:x1] = (region * (1 - k) + self.rgb * k).astype(np.uint8)
        return out


# ------------------------------------------------------------------ the pen shot
def _tip_at(t: float) -> np.ndarray:
    pts = PEN_TIP
    if t <= pts[0][0]:
        return np.array(pts[0][1:], float)
    for (t0, x0, y0), (t1, x1, y1) in zip(pts, pts[1:]):
        if t <= t1:
            k = (t - t0) / (t1 - t0)
            k = k * k * (3 - 2 * k)
            return np.array([x0 + (x1 - x0) * k, y0 + (y1 - y0) * k])
    return np.array(pts[-1][1:], float)


class PenShot:
    """The quote coming out of the pen, a line at a time.

    The current line ends at the pen tip; once it is full it moves up and the
    next starts again at the pen. Two lines above it stay in view, fading.
    """

    WIDTH = PEN_ROOM + 60

    def __init__(self, quote: str):
        font = face(quote, PEN_SIZE)
        self.rtl = textkit.is_rtl(quote)
        self.lines = wrap(quote, font, PEN_ROOM)
        # Nastaliq's tails reach well into the line below; it needs more air.
        self.line_h = int(font.size * (1.45 if getattr(font, "raqm", False) else 1.15))
        strip_h = self.line_h * 2
        self.strips = []
        for line in self.lines:
            img, start, end = _strip(font, line, strip_h, "rm")
            if getattr(font, "thin", False):
                img = thicken(img, 3)
            self.strips.append((np.asarray(img), start, end))
        self.total = sum(len(l) for l in self.lines) or 1

    def mask(self, t: float):
        import cv2
        p = max(0.0, min(1.0, (t - 0.55) / 1.15))
        done = p * self.total
        shown = []                               # (line index, how much of it)
        for i, line in enumerate(self.lines):
            if done <= 0:
                break
            shown.append((i, min(1.0, done / len(line))))
            done -= len(line)
        if not shown:
            return None
        current, into = shown[-1]
        lift = ease(min(1.0, into * 4)) if current else 1.0

        canvas_h = self.line_h * 4
        base_y = canvas_h - self.line_h
        right = self.WIDTH - 20
        canvas = np.zeros((canvas_h, self.WIDTH), np.uint8)
        for back, (i, k) in enumerate(reversed(shown[-3:])):
            y = base_y - back * self.line_h + (1 - lift) * self.line_h * (1 if back else 0)
            fade = (1.0, 0.55, 0.25)[back]
            strip, start, end = self.strips[i]
            w = (end - start) * k
            # The written part, with the end the line grows from pinned at the
            # pen: its right end, which is where a Persian line starts and
            # where a Latin one has got to so far.
            if self.rtl:
                a, b, pin = int(end - w), strip.shape[1], end
            else:
                a, b, pin = 0, int(start + w), int(start + w)
            part = strip[:, a:b]
            if fade < 1:
                part = (part.astype(np.float32) * fade).astype(np.uint8)
            x = int(round(right - (pin - a)))
            y0 = int(round(y - strip.shape[0] / 2))
            _paste_max(canvas, part, x, y0)

        tip = _tip_at(t) + np.array([-14, -6])
        c, s = np.cos(PEN_SLOPE), np.sin(PEN_SLOPE)
        m = np.array([[c, -s * PEN_SQUASH], [s, c * PEN_SQUASH]])
        offset = tip - m @ np.array([right, base_y])
        return cv2.warpAffine(canvas, np.hstack([m, offset[:, None]]), (W, H),
                              flags=cv2.INTER_LINEAR)

    def apply(self, frame: np.ndarray, t: float, a: float) -> np.ndarray:
        import cv2
        mask = self.mask(t)
        if mask is None:
            return frame
        # Black, like ink, softened to sit in the shot's own focus.
        return darken(frame, cv2.GaussianBlur(mask, (0, 0), 0.8), INK * a)


def _paste_max(canvas: np.ndarray, part: np.ndarray, x: int, y: int) -> None:
    """Lay `part` on `canvas` at (x, y), keeping the brighter of the two, clipped."""
    h, w = part.shape
    cx0, cy0 = max(0, x), max(0, y)
    cx1, cy1 = min(canvas.shape[1], x + w), min(canvas.shape[0], y + h)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    src = part[cy0 - y:cy1 - y, cx0 - x:cx1 - x]
    np.maximum(canvas[cy0:cy1, cx0:cx1], src, out=canvas[cy0:cy1, cx0:cx1])


# ------------------------------------------------------------------ the page shot
class PageShot:
    """The quote on the page's own rules, revealed as the glove moves along.

    As big as fits: short quotes get bigger letters on every third rule (every
    fourth in Nastaliq, whose tails need the room), longer ones smaller.
    """

    def __init__(self, quote: str, geometry: dict):
        self.rtl = textkit.is_rtl(quote)
        self.homs = geometry["homs"]
        self.origin = geometry["origin"]
        font, self.lines, self.step = self._plan(quote)
        S = PAGE_SCALE
        big = face(quote, font.size * S, scaled=False)
        self.size = (int(PAGE_LEN * S), int((len(self.lines) * self.step + 1) * PITCH * S))
        w, _ = self.size
        self.parts = []                    # (ink, x, y, ink starts, ink ends) per line
        for i, line in enumerate(self.lines):
            baseline = (i + 1) * self.step * PITCH * S
            shown = prep(line, big)
            lw = big.getlength(shown)
            height = int(big.size * 3)
            img = Image.new("L", (int(lw) + 8 * S, height), 0)
            # Baseline two thirds down, which leaves room for tall strokes above
            # and Nastaliq's tails below.
            by = int(height * 0.62)
            big.draw_on(ImageDraw.Draw(img), (img.width - 4 * S, by), shown, fill=255, anchor="rs")
            if getattr(big, "thin", False):
                img = thicken(img, 5)
            x = (w - 2 * S) - (img.width - 4 * S) if self.rtl else 2 * S - 4 * S
            self.parts.append((np.asarray(img), x, int(baseline - by),
                               4 * S, 4 * S + lw))
        self.total = sum(len(l) for l in self.lines) or 1

    @staticmethod
    def _plan(quote: str):
        nastaliq = getattr(face(quote, 10), "raqm", False)
        # (letters as tall as this many rules, a line every this many rules)
        plans = ((3, 4), (2.5, 3)) if nastaliq else ((3, 3), (2, 2))
        for size_rules, step in plans:
            font = face(quote, size_rules * PITCH * 0.95)
            lines = wrap(quote, font, PAGE_LEN)
            if len(lines) <= RULES_ON_PAGE // step:
                return font, lines, step
        lines = lines[:RULES_ON_PAGE // step]
        lines[-1] = lines[-1].rstrip() + "…"
        return font, lines, step

    def canvas(self, p: float) -> np.ndarray:
        w, h = self.size
        out = np.zeros((h, w), np.uint8)
        done = p * self.total
        for line, (ink, x, y, start, end) in zip(self.lines, self.parts):
            if done <= 0:
                break
            k = min(1.0, done / len(line))
            done -= len(line)
            cut = (end - start) * k
            if self.rtl:
                part, px = ink[:, int(end - cut):], x + int(end - cut)
            else:
                part, px = ink[:, :int(start + cut)], x
            _paste_max(out, part, px, y)
        return out

    def apply(self, frame: np.ndarray, i: int, t: float, a: float) -> np.ndarray:
        import cv2
        hom = self.homs.get(i)
        if hom is None:
            return frame
        p = (t - PAGE[0] - 0.15) / 1.75
        if p <= 0:
            return frame
        m = hom @ line_space_to_frame(self.origin, PAGE_SCALE)
        ink = cv2.warpPerspective(self.canvas(min(1.0, p)), m, (W, H), flags=cv2.INTER_AREA)
        ink = (ink.astype(np.float32) * paper_mask(frame) / 255.0).astype(np.uint8)
        return darken(frame, cv2.GaussianBlur(ink, (0, 0), 0.6), 0.93 * a)


# ------------------------------------------------------------------ face and end
def _name_label(who: str) -> Label | None:
    who = clean(who)
    if not who:
        return None
    rtl = textkit.is_rtl(who)
    size = 82 if rtl else 54
    # A long name shrinks to fit rather than running off the frame.
    while True:
        font = face(who, size)
        shown = prep(who, font) if getattr(font, "raqm", False) else (
            DASH + " " + prep(who, font))
        width = font.getlength(shown)
        if width <= W - 160 or size <= 24:
            break
        size = int(size * 0.9)
    if getattr(font, "raqm", False):
        # Nastaliq's own dash sits high above the line; the bot's font draws
        # it, on the right, where a right-to-left line starts.
        return Label([(font, (W / 2, 572), shown, "ms"),
                      (fonts.load("bold", 48), (W / 2 + width / 2 + 18, 552), DASH, "lm")])
    return Label([(font, (W / 2, 600), shown, "mm")])


@lru_cache(maxsize=1)
def _geometry() -> dict:
    page = json.loads(GEOMETRY.read_text())
    return {"origin": np.array(page["origin"], float),
            "homs": {int(k): np.array(v, float) for k, v in page["homs"].items()}}


# Longer than any render has taken on the server, by a wide margin. Past it,
# something is stuck - ffmpeg waiting on a pipe, a disk that stopped - and the
# job is killed rather than holding the only slot until the next restart.
RENDER_TIMEOUT = 90
FRAME_BYTES = W * H * 3


def _ffmpeg() -> str:
    import shutil
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def render(quote: str, who: str, handle: str) -> bytes:
    """The clip with `quote` written in it, as a silent MP4 - a GIF, to Telegram.

    Two ffmpeg processes, one reading the base clip and one encoding, with
    frames passed between them here. Both are killed by a timer if the whole
    thing runs past RENDER_TIMEOUT, which turns a hang into an exception.
    """
    import subprocess
    import threading

    quote = clean(quote)
    pen = PenShot(quote)
    page = PageShot(quote, _geometry())
    name = _name_label(who)
    mark = Label([(fonts.load("medium", 34), (W - 40, 630), handle, "rm")])
    exe = _ffmpeg()

    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "fire.mp4"
        reader = subprocess.Popen(
            [exe, "-loglevel", "error", "-i", str(BASE),
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        writer = subprocess.Popen(
            [exe, "-y", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
             "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(out_path)],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        expired = threading.Event()

        def kill():
            expired.set()
            for proc in (reader, writer):
                proc.kill()

        timer = threading.Timer(RENDER_TIMEOUT, kill)
        timer.start()
        try:
            i = 0
            while True:
                raw = reader.stdout.read(FRAME_BYTES)
                if len(raw) < FRAME_BYTES:
                    break
                t = i / FPS
                frame = None

                def pixels():
                    return frame if frame is not None else np.frombuffer(
                        raw, np.uint8).reshape(H, W, 3)

                a = window(t, PEN[0] + 0.45, PEN[1] + 0.3, fade=0.12)
                if a:
                    frame = pen.apply(pixels(), t, a)
                a = window(t, FACE[0] + 0.3, FACE[1] - 0.05)
                if a and name is not None:
                    frame = name.over(pixels(), a)
                if PAGE[0] <= t <= PAGE[1]:
                    a = window(t, PAGE[0], PAGE[1] - 0.05, fade=0.25)
                    if a:
                        frame = page.apply(pixels(), i, t, a)
                a = window(t, FIRE[0] + 0.5, FIRE[1] + 1, fade=0.3)
                if a:
                    frame = mark.over(pixels(), a)
                writer.stdin.write(raw if frame is None
                                   else np.ascontiguousarray(frame).tobytes())
                i += 1
            writer.stdin.close()
            writer.wait()
            reader.wait()
        except (BrokenPipeError, OSError, ValueError):
            if not expired.is_set():
                raise
        finally:
            timer.cancel()
            for proc in (reader, writer):
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        if expired.is_set():
            raise TimeoutError(f"fire render took longer than {RENDER_TIMEOUT}s")
        if writer.returncode != 0 or i == 0:
            raise RuntimeError(f"ffmpeg failed (exit {writer.returncode}, {i} frames)")
        return out_path.read_bytes()
