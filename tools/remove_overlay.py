#!/usr/bin/env python3
"""
remove_overlay.py - remove a baked-in static overlay (emojis, sticker, small text, watermark)
from a video by inpainting it frame by frame.

How it works: inside the box you give, pixels that stay still while the video moves behind them
are the overlay. That gives an exact mask. Every frame from the overlay's first appearance to the
end is rebuilt from the surrounding image (OpenCV Telea inpainting); on very bright, flat frames
(e.g. a flashbang flash) the whole box is rebuilt.

Usage:
  python3 tools/remove_overlay.py IN.mp4 OUT.mp4 --box x0,x1,y0,y1 [--sample-from 3.8]

  --box          pixel box around the overlay (find it from a frame grab; add a few px margin)
  --sample-from  a time (s) after which the overlay is definitely on screen, used to learn its mask
Needs: pip install opencv-python-headless numpy

Limits: works best on small overlays over moving footage. Over detailed areas the patch can look
like a soft smudge; a caption box placed over the same spot hides it completely.
"""
import argparse, json, subprocess, sys
import numpy as np


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--box", required=True, help="x0,x1,y0,y1")
    ap.add_argument("--sample-from", type=float, default=None)
    a = ap.parse_args()
    import cv2

    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                      "stream=width,height,avg_frame_rate", "-of", "json", a.src],
                                     capture_output=True, text=True).stdout)["streams"][0]
    W, H = int(info["width"]), int(info["height"])
    num, den = info["avg_frame_rate"].split("/"); fps = float(num) / float(den)
    x0, x1, y0, y1 = [int(v) for v in a.box.split(",")]

    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", a.src, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).copy(); n = len(fr)
    s0 = int((a.sample_from if a.sample_from is not None else 0.6 * n / fps) * fps)
    late = fr[s0:].astype(np.float32)[:, y0:y1, x0:x1]
    std = late.std(0).mean(2); tmpl = np.median(late, 0)

    m = (std < 9).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    k, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    keep = np.zeros_like(m)
    for i in range(1, k):
        if stats[i, cv2.CC_STAT_AREA] > 120:
            keep[lab == i] = 255
    keep = cv2.dilate(keep, np.ones((5, 5), np.uint8))
    mask = np.zeros((H, W), np.uint8); mask[y0:y1, x0:x1] = keep
    inside = keep > 0
    if not inside.any():
        sys.exit("error: no static overlay found in that box (check --box / --sample-from)")

    first = next((i for i in range(n)
                  if np.abs(fr[i, y0:y1, x0:x1].astype(np.float32) - tmpl).mean(2)[inside].mean() < 28), None)
    if first is None:
        sys.exit("error: overlay not detected in any frame")
    for i in range(first, n):
        bgr = cv2.cvtColor(fr[i], cv2.COLOR_RGB2BGR)
        use = mask
        if fr[i].mean() > 120:  # washed-out / flash frame: flat background, rebuild the whole box
            use = np.zeros_like(mask); use[max(0, y0 - 4):y1 + 4, max(0, x0 - 6):x1 + 6] = 255
        out = cv2.inpaint(bgr, use, 6, cv2.INPAINT_TELEA)
        blur = cv2.GaussianBlur(out, (5, 5), 0); mm = (cv2.GaussianBlur(use, (9, 9), 0) / 255.0)[..., None]
        fr[i] = cv2.cvtColor((blur * mm + out * (1 - mm)).astype(np.uint8), cv2.COLOR_BGR2RGB)
    print(f"overlay removed from frames {first}-{n - 1} ({(n - first) / fps:.2f}s)")

    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-r", f"{fps:g}", "-i", "-", "-i", a.src, "-map", "0:v", "-map", "1:a?", "-c:v", "libx264",
                          "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "copy",
                          "-movflags", "+faststart", a.dst], stdin=subprocess.PIPE)
    p.stdin.write(fr.tobytes()); p.stdin.close(); p.wait()


if __name__ == "__main__":
    main()
