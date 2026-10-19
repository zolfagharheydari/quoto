"""Prepare the clip /fire writes on. Run once, wherever the source video is.

    python tools/make_fire_base.py "Gunna Writing In Fire ... 1080p60.mp4"

Writes two files into assets/fire/:

  base.mp4    the clip at 1280x720, 30 fps, silent, with the handwriting on the
              page already erased - so all a request has to do is write
  page.json   how the page moves: a homography per frame of the page shot,
              from the frame the lines were measured in, and where the first
              rule starts. Kept if it is already there; tracking is slow.

Everything here is the same for every quote, which is why it is done once
instead of on every request. The clip itself is not in the repository; the
fonts (IranNastaliq.ttf, Cinderella.otf) go next to these files by hand.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fire  # noqa: E402

W, H, FPS = fire.W, fire.H, fire.FPS

# Where the first rule of the page starts, at the reference frame. Measured:
# the handwriting's lines found by the rotation that makes their rows most
# distinct, then stepped back one rule so the quote starts above the old text.
ORIGIN = (387.41, 374.18)


def frames(src):
    gen = imageio_ffmpeg.read_frames(src, output_params=["-vf", f"fps={FPS},scale={W}:{H}"])
    next(gen)
    for raw in gen:
        yield np.frombuffer(raw, np.uint8).reshape(H, W, 3)


def track(src):
    """Homography from the reference frame to every frame of the page shot."""
    first, last = round(fire.PAGE[0] * FPS), round(fire.PAGE[1] * FPS)
    gray = {}
    for i, f in enumerate(frames(src)):
        if first <= i <= last:
            gray[i] = cv2.cvtColor(f, cv2.COLOR_RGB2GRAY)
        if i > last:
            break
    # Features on the page and the table, never on the glove that moves over it.
    mask = np.zeros((H, W), np.uint8)
    cv2.fillPoly(mask, [np.int32([[160, 640], [300, 420], [560, 330], [600, 470], [560, 640]])], 255)
    cv2.rectangle(mask, (0, 140), (330, 260), 255, -1)
    cv2.rectangle(mask, (380, 70), (700, 300), 255, -1)

    def walk(step):
        out = {fire.REF: np.eye(3)}
        base = cv2.goodFeaturesToTrack(gray[fire.REF], 400, 0.01, 7, mask=mask)
        prev_pts, prev_i, i = base, fire.REF, fire.REF + step
        while first <= i <= last:
            nxt, st, _ = cv2.calcOpticalFlowPyrLK(gray[prev_i], gray[i], prev_pts, None,
                                                  winSize=(31, 31), maxLevel=4)
            ok = st.ravel() == 1
            base, nxt = base[ok], nxt[ok]
            hom, _ = cv2.findHomography(base, nxt, cv2.RANSAC, 3.0)
            out[i] = hom if hom is not None else out[prev_i]
            prev_pts, prev_i, i = nxt, i, i + step
        return out

    return {**walk(-1), **walk(1)}


def erase_handwriting(frame, region, paper):
    """Paint the page over the old writing: a blur that only averages paper."""
    weight = paper.astype(np.float32) / 255.0
    num = cv2.GaussianBlur(frame.astype(np.float32) * weight[..., None], (0, 0), 7)
    den = cv2.GaussianBlur(weight, (0, 0), 7)[..., None] + 1e-4
    clean = num / den
    k = (region.astype(np.float32) / 255.0 * weight)[..., None]
    return (frame * (1 - k) + clean * k).astype(np.uint8)


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    src = sys.argv[1]
    fire.ASSETS.mkdir(parents=True, exist_ok=True)

    if fire.GEOMETRY.exists():
        page = json.loads(fire.GEOMETRY.read_text())
        homs = {int(k): np.array(v) for k, v in page["homs"].items()}
    else:
        print("tracking the page...")
        homs = track(src)
        fire.GEOMETRY.write_text(json.dumps({
            "origin": ORIGIN,
            "homs": {i: h.tolist() for i, h in sorted(homs.items())},
        }))
    origin = np.array(json.loads(fire.GEOMETRY.read_text())["origin"])

    # The block the old handwriting is in, in the same line space the quote
    # is drawn in: seven and a half rules deep, as long as the lines run.
    block = np.full((int(7.6 * fire.PITCH), int(fire.PAGE_LEN)), 255, np.uint8)
    to_frame = fire.line_space_to_frame(origin, 1)

    writer = imageio_ffmpeg.write_frames(
        str(fire.BASE), (W, H), fps=FPS, codec="libx264", pix_fmt_in="rgb24",
        output_params=["-crf", "17", "-preset", "slow", "-an"], macro_block_size=8)
    writer.send(None)
    for i, f in enumerate(frames(src)):
        t = i / FPS
        out = f
        hom = homs.get(i)
        if fire.PAGE[0] <= t <= fire.PAGE[1] and hom is not None:
            a = fire.window(t, fire.PAGE[0], fire.PAGE[1] - 0.05, fade=0.25)
            region = cv2.warpPerspective(block, hom @ to_frame, (W, H))
            region = cv2.GaussianBlur(region, (0, 0), 3)
            out = erase_handwriting(f, (region * a).astype(np.uint8), fire.paper_mask(f))
        writer.send(np.ascontiguousarray(out).tobytes())
    writer.close()
    print(fire.BASE, fire.BASE.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
