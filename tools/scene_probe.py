#!/usr/bin/env python3
"""
scene_probe.py - "where is everything?" for a video, so captions, tracks and masks can be placed by numbers.

  python3 tools/scene_probe.py reports/<clip>/base.mov [--fps 2] [--out reports/<clip>]

Run it on the stage-A base video (render_edit.py --base-only) so every box is in OUTPUT pixels
(1080x1920) and edited-video seconds, exactly what the edit plan uses.

Writes:
  probe.json         per sampled time: objects [{label, score, box}], faces [[x,y,w,h]], person_area (0..1),
                     free_zones (horizontal bands of the safe area with no face/person, best caption spots)
  probe_sheet.jpg    the sampled frames with boxes and labels drawn (#k = detection index) - LOOK at it
Prints a short table: time, what's where, where a caption fits.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vision  # noqa: E402

SAFE_TOP, SAFE_BOTTOM = 170, 1600  # caption-safe vertical range on a 1920-high Short (UI overlays outside)


def free_zones(person: np.ndarray, faces: list, h: int, w: int) -> list[list[int]]:
    """Horizontal bands (y0, y1) inside the safe area where the centre 70% of the width has no face and
    little person coverage."""
    occ = (person > 0.5).astype(np.uint8)
    for (x, y, bw, bh) in faces:
        occ[max(0, y - bh // 3): y + bh + bh // 4, max(0, x - bw // 4): x + bw + bw // 4] = 1
    x0, x1 = int(w * 0.15), int(w * 0.85)
    rows = occ[:, x0:x1].mean(axis=1)
    sy = SAFE_TOP * h // 1920, SAFE_BOTTOM * h // 1920
    free = rows < 0.12
    zones, start = [], None
    for y in range(sy[0], sy[1]):
        if free[y] and start is None:
            start = y
        if (not free[y] or y == sy[1] - 1) and start is not None:
            if y - start > 0.06 * h:
                zones.append([start, y])
            start = None
    return zones


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--fps", type=float, default=2.0, help="samples per second (default 2)")
    ap.add_argument("--out", default=None, help="output folder (default: next to the video)")
    a = ap.parse_args()
    vid = Path(a.video)
    out = Path(a.out) if a.out else vid.parent
    out.mkdir(parents=True, exist_ok=True)
    info = vision.video_info(vid)
    step = max(1, int(round(info["fps"] / a.fps)))
    vis = vision.Vision()
    samples, thumbs = [], []
    for i, fr in vision.read_frames(vid):
        if i % step:
            continue
        t = round(i / info["fps"], 2)
        objs = vis.detect(fr)
        faces = vis.faces(fr)
        person = vis.people(fr)
        zones = free_zones(person, faces, *fr.shape[:2])
        samples.append({"t": t, "objects": objs, "faces": faces,
                        "person_area": round(float((person > 0.5).mean()), 3), "free_zones": zones})
        d = fr.copy()
        for (y0, y1) in zones:
            ov = d.copy(); cv2.rectangle(ov, (0, y0), (d.shape[1], y1), (0, 200, 0), -1)
            d = cv2.addWeighted(ov, 0.18, d, 0.82, 0)
        for k, o in enumerate(objs):
            x, y, bw, bh = o["box"]
            cv2.rectangle(d, (x, y), (x + bw, y + bh), (0, 220, 255), 4)
            cv2.putText(d, f"#{k} {o['label']} {x},{y},{bw},{bh}", (x + 6, max(40, y + 40)),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 220, 255), 3)
        for (x, y, bw, bh) in faces:
            cv2.rectangle(d, (x, y), (x + bw, y + bh), (255, 80, 255), 4)
        cv2.putText(d, f"t={t:.2f}s", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 2.6, (255, 255, 255), 7)
        thumbs.append(cv2.resize(d, (360, int(360 * d.shape[0] / d.shape[1]))))
    vis.close()
    (out / "probe.json").write_text(json.dumps({"video": str(vid), "w": info["w"], "h": info["h"],
                                                "fps": info["fps"], "samples": samples}, indent=1))
    cols = 6
    rows = [thumbs[r:r + cols] for r in range(0, len(thumbs), cols)]
    if rows:
        blank = np.zeros_like(thumbs[0])
        sheet = np.vstack([np.hstack(r + [blank] * (cols - len(r))) for r in rows])
        cv2.imwrite(str(out / "probe_sheet.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(f"{'t':>6}  objects (label x,y,w,h)                                faces  caption-free bands (y)")
    for s in samples:
        ob = "; ".join(f"{o['label']} {','.join(map(str, o['box']))}" for o in s["objects"][:3])
        print(f"{s['t']:6.2f}  {ob[:54]:54}  {len(s['faces']):5}  {s['free_zones']}")
    print(f"Wrote {out / 'probe.json'} and {out / 'probe_sheet.jpg'}")


if __name__ == "__main__":
    main()
