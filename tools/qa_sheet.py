#!/usr/bin/env python3
"""
qa_sheet.py - frames from a rendered edit at every moment that can go wrong, labelled, on one sheet.

  python3 tools/qa_sheet.py reports/<clip>/edit_plan.json [--video reports/<clip>/final.mp4]

Grabs, from the render: each caption 0.12s after it appears and at its middle, each tracked caption /
marker at start-middle-end (does it stick?), each masked ("behind") caption at start-middle-end (is the
subject in front, is the text still readable?), every B&W / flash / zoom start, and the last frame.
Writes reports/<clip>/qa_sheet.jpg (+ qa_sheet_2.jpg ... when there are many). Look at every tile.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--video", default=None)
    a = ap.parse_args()
    plan_p = Path(a.plan).resolve()
    plan = json.loads(plan_p.read_text())
    vid = Path(a.video) if a.video else Path(plan.get("output", plan_p.parent / "final.mp4"))
    vid = vid if vid.is_absolute() else ROOT / vid
    moments: list[tuple[float, str]] = []
    for c in plan.get("captions", []):
        txt = c["text"].replace("\n", " ")[:22]
        kind = "TRACK " if c.get("follow") else ("BEHIND " if c.get("behind") else "")
        if c.get("follow") or c.get("behind"):
            for f, nm in ((0.12, "start"), (0.5, "mid"), (0.92, "end")):
                moments.append((c["start"] + f * (c["end"] - c["start"]), f"{kind}{nm}: {txt}"))
        else:
            moments.append((c["start"] + min(0.12, (c["end"] - c["start"]) / 2), f"in: {txt}"))
            moments.append(((c["start"] + c["end"]) / 2, f"mid: {txt}"))
    for mk in plan.get("markers", []):
        for f in (0.1, 0.5, 0.9):
            moments.append((mk["start"] + f * (mk["end"] - mk["start"]), "marker"))
    for b in plan.get("bw", []):
        moments.append((b["start"] + 0.05, "B&W"))
    for z in plan.get("zooms", []):
        moments.append((z["start"] + 0.05, f"zoom {z.get('to', z.get('scale', ''))}"))
    for fl in plan.get("flashes", []):
        moments.append((fl["at"] + 0.03, "flash"))
    cap = cv2.VideoCapture(str(vid))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    moments.append((max(0, dur - 0.05), "last frame"))
    moments.sort()
    tiles = []
    for t, lab in moments:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        if not ok:
            continue
        im = cv2.resize(fr, (360, 640))
        for col, th in (((0, 0, 0), 5), ((0, 255, 255), 2)):
            cv2.putText(im, f"{t:.2f}s", (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.85, col, th)
            cv2.putText(im, lab, (8, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, th)
        # safe-area guides: bottom 15% (captions/UI) and the right button column
        cv2.line(im, (0, int(640 * 0.85)), (360, int(640 * 0.85)), (0, 0, 255), 1)
        cv2.line(im, (int(360 * 0.86), int(640 * 0.45)), (int(360 * 0.86), 640), (0, 0, 255), 1)
        tiles.append(im)
    cap.release()
    per = 18
    outs = []
    for k in range(0, len(tiles), per):
        chunk = tiles[k:k + per]
        rows = [chunk[r:r + 6] for r in range(0, len(chunk), 6)]
        blank = np.zeros_like(chunk[0])
        sheet = np.vstack([np.hstack(r + [blank] * (6 - len(r))) for r in rows])
        name = "qa_sheet.jpg" if k == 0 else f"qa_sheet_{k // per + 1}.jpg"
        cv2.imwrite(str(plan_p.parent / name), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])
        outs.append(plan_p.parent / name)
    print("Wrote " + ", ".join(str(o) for o in outs))


if __name__ == "__main__":
    main()
