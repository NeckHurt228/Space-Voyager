#!/usr/bin/env python3
"""
study_reference.py - frame-by-frame study of a competitor Short: every caption (what, where, when, how big,
what style), whether a caption TRACKS an object or is screen-locked, whether it is MASKED (a subject passes in
front of it), plus cuts, B&W, flashes, freezes, punch-ins / push-ins, shake and the framing layout.

  python3 tools/study_reference.py references/<channel>/<video>.mp4      # one video
  python3 tools/study_reference.py references/                           # every video not studied yet, then aggregate
  python3 tools/study_reference.py aggregate references/_study           # rebuild references/STYLE_PROFILE.md

Per video it writes references/_study/<channel>/<video>/:
  timeline.json       everything measured (frame-accurate effects, caption instances with per-sample boxes)
  study.md            the readable version: caption table + effects timeline
  sheet_captions.jpg  every overlay caption on its first frame, box + label drawn   } LOOK at these: the numbers
  sheet_tracked.jpg   tracked captions across their life                         } are heuristics, the sheets
  sheet_masked.jpg    masked captions: fully visible vs most covered             } are the proof
  sheet_effects.jpg   frames at cuts / B&W / flash / punch-ins

How it decides (so you know when to doubt it):
  * captions: OCR (RapidOCR) every 1/ocr_fps s. A text box counts as an OVERLAY when it sits on a solid box,
    has a dark outline stroke, or stays fixed on screen while the footage around it moves. Other text
    (signs, uniforms, the bus) is reported as scene text and ignored.
  * tracked: the caption moves > 1.5% of the width AND the footage right around it moves the same way
    (dense optical flow). A caption that moves on its own (slide/bounce) is "animated".
  * masked: pixels that belonged to the caption in its fullest sample are replaced by footage in another
    sample, in one irregular blob (not a word-by-word reveal, not a uniform fade).
Needs: opencv-contrib-python, numpy, rapidocr-onnxruntime (bash tools/setup_vision.sh), ffmpeg.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import statistics as stx
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "references"
VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv", ".m4v")
OCR_W = 540          # OCR / caption analysis width
SIG_W = 270          # per-frame signal width


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def color_name(bgr) -> str:
    hsv = cv2.cvtColor(np.uint8([[bgr]]), cv2.COLOR_BGR2HSV)[0, 0]
    h, s, v = int(hsv[0]) * 2, int(hsv[1]), int(hsv[2])
    if v < 60:
        return "black"
    if s < 55:
        return "white" if v > 170 else "grey"
    if h < 18 or h >= 340:
        return "red"
    if h < 42:
        return "orange"
    if h < 70:
        return "yellow"
    if h < 165:
        return "green"
    if h < 200:
        return "cyan"
    if h < 260:
        return "blue"
    return "pink"


def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a[0], a[1], a[0] + a[2], a[1] + a[3]
    bx1, by1, bx2, by2 = b[0], b[1], b[0] + b[2], b[1] + b[3]
    iw, ih = max(0, min(ax2, bx2) - max(ax1, bx1)), max(0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    return inter / max(1e-6, a[2] * a[3] + b[2] * b[3] - inter)


def center(b):
    return b[0] + b[2] / 2, b[1] + b[3] / 2


def norm_text(t: str) -> str:
    return re.sub(r"[^A-Z0-9*:?!.'\- ]", "", t.upper()).strip()


def tile(imgs: list[np.ndarray], cols: int, w: int = 300) -> np.ndarray | None:
    if not imgs:
        return None
    th = [cv2.resize(i, (w, int(w * i.shape[0] / i.shape[1]))) for i in imgs]
    hmax = max(t.shape[0] for t in th)
    th = [cv2.copyMakeBorder(t, 0, hmax - t.shape[0], 0, 0, cv2.BORDER_CONSTANT) for t in th]
    rows = [th[r:r + cols] for r in range(0, len(th), cols)]
    blank = np.zeros_like(th[0])
    return np.vstack([np.hstack(r + [blank] * (cols - len(r))) for r in rows])


def label(img, txt, y=34, scale=0.8, color=(0, 255, 255)):
    cv2.putText(img, txt, (8, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 5)
    cv2.putText(img, txt, (8, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2)


# --------------------------------------------------------------------------
# pass 1: per-frame signals + OCR samples
# --------------------------------------------------------------------------
def pass1(video: Path, ocr_fps: float):
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    step = max(1, int(round(fps / ocr_fps)))
    sig, dets, grays = [], [], {}
    prev_small, prev_pts = None, None
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        small = cv2.resize(fr, (SIG_W, int(SIG_W * H / W)), interpolation=cv2.INTER_AREA)
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        sh = small.shape[0]
        mid = hsv[int(sh * 0.3): int(sh * 0.7)]
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        rec = {"i": i, "t": round(i / fps, 3), "sat": float(mid[..., 1].mean()), "v": float(hsv[..., 2].mean()),
               "diff": 0.0, "hcorr": 1.0, "scale": 1.0, "dx": 0.0, "dy": 0.0}
        if prev_small is not None:
            rec["diff"] = float(cv2.absdiff(g, prev_small).mean())
            rec["hcorr"] = float(cv2.compareHist(sig[-1]["_hist"], hist, cv2.HISTCMP_CORREL))
            if prev_pts is not None and len(prev_pts) >= 12:
                nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev_small, g, prev_pts, None)
                good = st.ravel() == 1
                if good.sum() >= 10:
                    M, inl = cv2.estimateAffinePartial2D(prev_pts[good], nxt[good], method=cv2.RANSAC,
                                                         ransacReprojThreshold=1.5)
                    if M is not None and inl is not None and inl.sum() >= 8:
                        rec["scale"] = float(np.hypot(M[0, 0], M[1, 0]))
                        rec["dx"], rec["dy"] = float(M[0, 2]) * W / SIG_W, float(M[1, 2]) * W / SIG_W
        rec["_hist"] = hist
        sig.append(rec)
        # features from the middle band (the sharp footage in band layouts)
        band = np.zeros_like(g)
        band[int(sh * 0.2): int(sh * 0.8)] = 255
        prev_pts = cv2.goodFeaturesToTrack(g, 150, 0.01, 6, mask=band)
        prev_small = g
        if i % step == 0:
            im = cv2.resize(fr, (OCR_W, int(OCR_W * H / W)), interpolation=cv2.INTER_AREA)
            res, _ = ocr(im)
            grays[i] = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
            for quad, txt, score in res or []:
                score = float(score)
                if score < 0.55 or not txt.strip():
                    continue
                xs, ys = [p[0] for p in quad], [p[1] for p in quad]
                dets.append({"i": i, "t": round(i / fps, 3), "text": txt.strip(), "score": round(score, 2),
                             "box": [float(min(xs)), float(min(ys)), float(max(xs) - min(xs)), float(max(ys) - min(ys))]})
        i += 1
    cap.release()
    for r in sig:
        r.pop("_hist", None)
    return {"fps": fps, "w": W, "h": H, "n": i, "ocr_step": step}, sig, dets, grays


# --------------------------------------------------------------------------
# captions: group OCR detections into instances
# --------------------------------------------------------------------------
def group(dets: list[dict], step: int) -> list[dict]:
    inst: list[dict] = []
    for d in sorted(dets, key=lambda d: d["i"]):
        best, bscore = None, 0.0
        for c in inst:
            last = c["samples"][-1]
            if d["i"] - last["i"] > 2 * step or d["i"] == last["i"]:
                continue
            ov = iou(d["box"], last["box"])
            (cx, cy), (lx, ly) = center(d["box"]), center(last["box"])
            near = np.hypot(cx - lx, cy - ly) < 0.6 * max(d["box"][3], last["box"][3])
            sim = difflib.SequenceMatcher(None, norm_text(d["text"]), norm_text(c["text"])).ratio()
            s = ov + sim * 0.8 + (0.3 if near else 0)
            if (ov > 0.3 or near) and (sim > 0.35 or ov > 0.55) and s > bscore:
                best, bscore = c, s
        if best is None:
            inst.append({"samples": [d], "text": d["text"]})
        else:
            best["samples"].append(d)
            if len(norm_text(d["text"])) > len(norm_text(best["text"])):
                best["text"] = d["text"]
    return inst


def pixel_style(crop: np.ndarray, tb: tuple[int, int, int, int]) -> dict:
    """Style of one text box. crop = region around the box; tb = text box inside the crop."""
    x, y, w, h = tb
    inner = crop[y:y + h, x:x + w]
    if inner.size == 0:
        return {"style": "plain", "box_color": None, "text_color": "white", "outline": False}
    pad = max(2, h // 10)  # stay inside the box padding, even on big title text
    ring = np.concatenate([crop[max(0, y - 2):y, x:x + w].reshape(-1, 3),
                           crop[y + h:y + h + 2, x:x + w].reshape(-1, 3),
                           crop[y:y + h, max(0, x - pad):x].reshape(-1, 3),
                           crop[y:y + h, x + w:x + w + pad].reshape(-1, 3)])
    # boxed = most of the ring is one flat colour (a subject crossing part of the edge must not break this)
    rmed = np.median(ring, axis=0) if len(ring) else np.zeros(3)
    boxed = bool(len(ring) > 20 and (np.linalg.norm(ring.astype(np.float32) - rmed, axis=1) < 22).mean() > 0.7)
    flat = inner.reshape(-1, 3).astype(np.float32)
    bg = np.median(ring, axis=0) if boxed else np.median(flat, axis=0)
    dist = np.linalg.norm(flat - bg, axis=1)
    fg = flat[dist > np.percentile(dist, 75)]
    text_bgr = np.median(fg, axis=0) if len(fg) else np.array([255, 255, 255])
    # outline: glyph pixels (close to text colour) surrounded by a dark stroke
    tmask = (np.linalg.norm(inner.astype(np.float32) - text_bgr, axis=2) < 60).astype(np.uint8)
    outline = False
    if not boxed and tmask.sum() > 20:
        ringm = cv2.dilate(tmask, np.ones((5, 5), np.uint8)) - tmask
        vals = inner[ringm > 0]
        outline = bool(len(vals) and (vals.max(axis=1) < 70).mean() > 0.45)
    cut = box_cut(crop, tb, bg, text_bgr) if boxed else 0.0
    return {"style": "box" if boxed else ("outline" if outline else "plain"), "box_cut": cut,
            "box_color": color_name(bg) if boxed else None, "text_color": color_name(text_bgr),
            "_text_bgr": text_bgr.tolist(), "_bg_bgr": np.asarray(bg).tolist() if boxed else None}


def box_cut(crop: np.ndarray, tb, bg, text_bgr) -> float:
    """How much of a solid caption box is cut by an irregular (non-straight) edge - the signature of a
    subject passing in front of it. 0 for a clean rectangle."""
    x, y, w, h = tb
    pad = max(4, h // 3)
    x0, x1 = max(0, x - pad * 3), min(crop.shape[1], x + w + pad * 3)
    y0, y1 = max(0, y - 2), min(crop.shape[0], y + h + 2)
    reg = crop[y0:y1, x0:x1].astype(np.float32)
    # the caption's own pixels: the flat box colour (tight: dark clothing next to it is textured) or the glyphs
    own = (np.linalg.norm(reg - np.asarray(bg, np.float32), axis=2) < 16) | \
          (np.linalg.norm(reg - np.asarray(text_bgr, np.float32), axis=2) < 60)
    own = cv2.morphologyEx(own.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
    rows = own.mean(axis=1) > 0.3
    if rows.sum() < 4:
        return 0.0
    own = own[rows]
    cols = own.mean(axis=0)
    xs = np.where(cols > 0.1)[0]
    if len(xs) < 8:
        return 0.0
    cols = cols[xs[0]: xs[-1] + 1]
    # isolated dips are antialiased glyph edges; an occluder leaves a RUN of partly covered columns
    sm = cv2.medianBlur(np.clip(cols * 255, 0, 255).astype(np.uint8).reshape(1, -1), 5).ravel() / 255.0
    part = (sm > 0.08) & (sm < 0.72)
    best = run = 0
    for v in part:
        run = run + 1 if v else 0
        best = max(best, run)
    if best < 5:
        return 0.0
    return round(float(best / len(cols)), 3)


# --------------------------------------------------------------------------
# pass 2: style, masking crops
# --------------------------------------------------------------------------
def pass2(video: Path, meta: dict, inst: list[dict]) -> dict:
    need: dict[int, list] = {}
    for k, c in enumerate(inst):
        ref = max(c["samples"], key=lambda s: s["box"][2] * s["box"][3])
        c["_ref"] = ref
        for s in c["samples"]:
            need.setdefault(s["i"], []).append((k, s))
    frames_keep: dict[int, np.ndarray] = {}
    cap = cv2.VideoCapture(str(video))
    W, H = meta["w"], meta["h"]
    i = 0
    last_needed = max(need) if need else -1
    while i <= last_needed:
        ok, fr = cap.read()
        if not ok:
            break
        if i in need:
            im = cv2.resize(fr, (OCR_W, int(OCR_W * H / W)), interpolation=cv2.INTER_AREA)
            frames_keep[i] = im
            for k, s in need[i]:
                c = inst[k]
                bx = [int(round(v)) for v in s["box"]]
                pad = max(6, bx[3] // 2)
                x0, y0 = max(0, bx[0] - pad), max(0, bx[1] - pad)
                crop = im[y0:bx[1] + bx[3] + pad, x0:bx[0] + bx[2] + pad]
                s["_style"] = pixel_style(crop, (bx[0] - x0, bx[1] - y0, bx[2], bx[3]))
                # aligned crop of the instance's fullest box, for the masking test
                ref = c["_ref"]["box"]
                (rcx, rcy), (scx, scy) = center(ref), center(s["box"])
                moving = c.get("_moving", False)
                ox, oy = (scx - rcx, scy - rcy) if moving else (0, 0)
                rp = max(4, int(ref[3] * 0.25))
                rx0, ry0 = int(ref[0] + ox) - rp, int(ref[1] + oy) - rp
                rx1, ry1 = int(ref[0] + ref[2] + ox) + rp, int(ref[1] + ref[3] + oy) + rp
                if rx0 >= 0 and ry0 >= 0 and rx1 <= im.shape[1] and ry1 <= im.shape[0]:
                    s["_full"] = im[ry0:ry1, rx0:rx1].copy()
        i += 1
    cap.release()
    return frames_keep


def masking(c: dict) -> dict:
    ref = c["_ref"]
    st = ref.get("_style") or {}
    # boxed captions: an irregular silhouette edge cutting into the box (works even when the subject
    # covers part of the caption for its whole life, so no sample shows it complete)
    cuts = [(s["t"], s["_style"].get("box_cut", 0)) for s in c["samples"] if s.get("_style", {}).get("style") == "box"]
    h_med = float(np.median([s["box"][3] for s in c["samples"]]))
    if h_med < 20:  # tiny text (role tags): too few pixels per column to judge an edge
        cuts = []
    cut_hits = [{"t": t, "covered": round(min(1.0, v * 1.5), 2), "side": "?", "evidence": "box edge cut"}
                for t, v in cuts if v > 0.04]
    # a subject crossing a caption covers it for a while: require 4 consecutive samples (~0.4s)
    streak = best = 0
    hit_t = {h["t"] for h in cut_hits}
    for t, _ in cuts:
        streak = streak + 1 if t in hit_t else 0
        best = max(best, streak)
    if best >= 4:
        return {"masked": True, "masked_samples": cut_hits, "max_covered": max(h["covered"] for h in cut_hits)}
    if st.get("style") == "box" or c.get("_moving"):
        return {"masked": False}  # boxed: the edge test above is the reliable one; moving: crops don't align
    if "_full" not in ref or "_text_bgr" not in st:
        return {"masked": False}
    tb = np.array(st["_text_bgr"], np.float32)
    bg = np.array(st["_bg_bgr"], np.float32) if st.get("_bg_bgr") else None

    def own(img):
        f = img.astype(np.float32)
        m = np.linalg.norm(f - tb, axis=2) < 70
        if bg is not None:
            m |= np.linalg.norm(f - bg, axis=2) < 45
        return m

    R = own(ref["_full"])
    if R.sum() < 30:
        return {"masked": False}
    hits = []
    rnorm = norm_text(ref["text"])
    for s in c["samples"]:
        if s is ref or "_full" not in s or s["_full"].shape != ref["_full"].shape:
            continue
        snorm = norm_text(s["text"])
        if snorm and rnorm.startswith(snorm) and len(snorm) < len(rnorm):
            continue  # word-by-word reveal, not masking
        lost = (R & ~own(s["_full"])).astype(np.uint8)
        frac = lost.sum() / R.sum()
        if frac < 0.12:
            continue
        lost = cv2.morphologyEx(lost, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(lost)
        if n < 2:
            continue
        big = 1 + int(np.argmax(stats[1:, 4]))
        share = stats[big, 4] / max(1, stats[1:, 4].sum())
        bx, by, bw, bh = stats[big, :4]
        rect = stats[big, 4] / max(1, bw * bh)
        full_h = lost.shape[0]
        # a fade/flicker loses pixels everywhere; a reveal loses a clean rectangle spanning the full height
        if share > 0.5 and (rect < 0.8 or bh < 0.85 * full_h):
            side = "left" if bx + bw / 2 < lost.shape[1] * 0.4 else ("right" if bx + bw / 2 > lost.shape[1] * 0.6 else "middle")
            hits.append({"t": s["t"], "covered": round(float(frac), 2), "side": side,
                         "from_below": bool(by + bh >= lost.shape[0] - 2)})
    return {"masked": len(hits) > 0, "masked_samples": hits,
            "max_covered": max((h["covered"] for h in hits), default=0.0)}


def motion(c: dict, grays: dict, meta: dict) -> dict:
    """static / tracked / animated, by comparing caption displacement with the footage's flow around it."""
    ss = c["samples"]
    if len(ss) < 3:
        return {"motion": "static", "moved_pct": 0.0}
    # translation counts only when both opposite edges move together; one edge moving alone is the OCR
    # box growing/shrinking (a word reveal, or a subject covering part of the text)
    pos = [np.zeros(2)]
    for a, b in zip(ss, ss[1:]):
        (ax, ay, aw, ah), (bx, by, bw, bh) = a["box"], b["box"]
        d = []
        for e0, e1 in (((ax, ax + aw), (bx, bx + bw)), ((ay, ay + ah), (by, by + bh))):
            dl, dr = e1[0] - e0[0], e1[1] - e0[1]
            same = np.sign(dl) == np.sign(dr) and abs(dl - dr) < 0.5 * max(abs(dl), abs(dr)) + 2
            d.append((dl + dr) / 2 if same else 0.0)
        pos.append(pos[-1] + np.array(d))
    cs = np.array(pos)
    span = float(np.max(np.linalg.norm(cs - np.median(cs, axis=0), axis=1)))
    moved_pct = 100 * span / OCR_W
    hs = np.array([s["box"][3] for s in ss])
    scale_anim = bool(hs.min() < 0.8 * np.median(hs) or hs.max() > 1.25 * np.median(hs))
    if moved_pct < 1.5:
        mags = []
        for a, b in list(zip(ss, ss[1:]))[:6]:
            if a["i"] in grays and b["i"] in grays:
                x, y, w, h = [int(v) for v in a["box"]]
                g0, g1 = grays[a["i"]], grays[b["i"]]
                y0, y1 = max(0, y - 2 * h), min(g0.shape[0], y + 3 * h)
                fl = cv2.calcOpticalFlowFarneback(g0[y0:y1], g1[y0:y1], None, 0.5, 2, 15, 2, 5, 1.1, 0)
                mags.append(float(np.median(np.linalg.norm(fl, axis=2))))
        return {"motion": "static", "moved_pct": round(moved_pct, 1), "scale_anim": scale_anim,
                "bg_moving": bool(mags and np.median(mags) > 0.6)}
    agree, total = 0, 0
    for a, b in zip(ss, ss[1:]):
        if a["i"] not in grays or b["i"] not in grays:
            continue
        d = np.array(center(b["box"])) - np.array(center(a["box"]))
        if np.linalg.norm(d) < 1.0:
            continue
        g0, g1 = grays[a["i"]], grays[b["i"]]
        flow = cv2.calcOpticalFlowFarneback(g0, g1, None, 0.5, 3, 21, 3, 5, 1.1, 0)
        x, y, w, h = [int(v) for v in a["box"]]
        R = int(1.6 * h) + 10
        y0, y1, x0, x1 = max(0, y - R), min(g0.shape[0], y + h + R), max(0, x - R // 2), min(g0.shape[1], x + w + R // 2)
        reg = np.ones((y1 - y0, x1 - x0), bool)
        reg[max(0, y - y0):y - y0 + h, max(0, x - x0):x - x0 + w] = False  # not the caption itself
        f = flow[y0:y1, x0:x1][reg]
        if len(f) == 0:
            continue
        match = (np.linalg.norm(f - d, axis=1) < 0.35 * np.linalg.norm(d) + 1.0).mean()
        total += 1
        agree += match > 0.2
    tracked = total > 0 and agree / total >= 0.5
    return {"motion": "tracked" if tracked else "animated", "moved_pct": round(moved_pct, 1),
            "flow_agree": round(agree / total, 2) if total else None, "scale_anim": scale_anim}


# --------------------------------------------------------------------------
# effects from per-frame signals
# --------------------------------------------------------------------------
def effects(sig: list[dict], fps: float) -> dict:
    sats = [r["sat"] for r in sig]
    base_sat = float(np.median(sats)) if sats else 0
    cuts = [r["t"] for r in sig[1:] if r["hcorr"] < 0.55 or r["diff"] > 40]

    def windows(flags, min_len):
        out, start = [], None
        for r, f in zip(sig, flags):
            if f and start is None:
                start = r["t"]
            if not f and start is not None:
                if r["t"] - start >= min_len:
                    out.append([start, r["t"]])
                start = None
        if start is not None and sig[-1]["t"] - start >= min_len:
            out.append([start, sig[-1]["t"]])
        return out

    bw = windows([r["sat"] < 9 and base_sat > 22 for r in sig], 0.1)
    flashes = [r["t"] for k, r in enumerate(sig[1:], 1) if r["v"] > 200 and r["v"] - sig[k - 1]["v"] > 45]
    freeze = windows([r["diff"] < 0.25 for r in sig], 0.25)
    cutset = set(round(c, 3) for c in cuts)
    punch, push = [], []
    logs = np.log([max(0.5, min(2.0, r["scale"])) for r in sig])
    for r, lg in zip(sig, logs):
        if r["t"] in cutset:
            continue
        if abs(lg) > np.log(1.035):
            punch.append({"t": r["t"], "scale": round(float(np.exp(lg)), 3)})
    win = max(3, int(fps * 0.8))
    k = 0
    while k + win < len(sig):
        seg = logs[k:k + win]
        if all(abs(v) < np.log(1.035) for v in seg) and abs(seg.sum()) > np.log(1.05) and (np.sign(seg) == np.sign(seg.sum())).mean() > 0.8:
            push.append({"start": sig[k]["t"], "end": sig[k + win]["t"], "total": round(float(np.exp(seg.sum())), 3)})
            k += win
        else:
            k += 1
    dx = np.array([r["dx"] for r in sig])
    hf = dx - np.convolve(dx, np.ones(5) / 5, mode="same")
    shake_flags = [abs(v) > 6 for v in hf]
    shake = windows(shake_flags, 0.2)
    return {"cuts": cuts, "bw": bw, "flashes": flashes, "freezes": freeze, "punch_ins": punch,
            "push_ins": push, "shake": shake}


def layout(video: Path, meta: dict) -> dict:
    """Detect the 'sharp centre band + blurred copy above/below' framing."""
    cap = cv2.VideoCapture(str(video))
    profs = []
    for k in range(5):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(meta["n"] * (k + 0.5) / 5))
        ok, fr = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(cv2.resize(fr, (SIG_W, int(SIG_W * meta["h"] / meta["w"]))), cv2.COLOR_BGR2GRAY)
        lap = np.abs(cv2.Laplacian(g, cv2.CV_32F))
        profs.append(lap.mean(axis=1))
    cap.release()
    if not profs:
        return {}
    p = np.median(np.array(profs), axis=0)
    p = np.convolve(p, np.ones(9) / 9, mode="same")
    n = len(p)
    mid = np.median(p[int(n * 0.35): int(n * 0.65)])
    sharp = p > 0.35 * mid
    top = int(np.argmax(sharp[: n // 2])) if sharp[: n // 2].any() else 0
    bot = n - int(np.argmax(sharp[::-1][: n // 2])) if sharp[::-1][: n // 2].any() else n
    band = top > 0.05 * n and bot < 0.95 * n
    out = {"band_layout": bool(band)}
    if band:
        bh = (bot - top) / n * meta["h"]
        out.update({"band_top_pct": round(100 * top / n, 1), "band_bottom_pct": round(100 * bot / n, 1),
                    "band_aspect": round(meta["w"] / bh, 2)})
    return out


# --------------------------------------------------------------------------
# one video
# --------------------------------------------------------------------------
def study(video: Path, out: Path, ocr_fps: float) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    meta, sig, dets, grays = pass1(video, ocr_fps)
    fps, W, H = meta["fps"], meta["w"], meta["h"]
    dur = meta["n"] / fps
    sx = W / OCR_W  # OCR-space -> video pixels
    inst = group(dets, meta["ocr_step"])
    # first motion pass needs only grays; masking crops need to know if an instance moves
    for c in inst:
        c["_motion"] = motion(c, grays, meta)
        c["_moving"] = c["_motion"]["motion"] != "static"
    frames = pass2(video, meta, inst)

    caps = []
    for k, c in enumerate(inst):
        ss = c["samples"]
        styles = [s.get("_style", {}) for s in ss if s.get("_style")]
        if not styles:
            continue
        sty = max(set(x["style"] for x in styles), key=[x["style"] for x in styles].count)
        tcol = max(set(x["text_color"] for x in styles), key=[x["text_color"] for x in styles].count)
        bcol = next((x["box_color"] for x in styles if x["style"] == "box"), None)
        start, end = ss[0]["t"], ss[-1]["t"] + meta["ocr_step"] / fps
        mot = c["_motion"]
        # an overlay: boxed, outlined, or screen-locked while the footage around moves
        vivid = tcol in ("white", "yellow", "red", "green", "cyan", "orange", "black")
        if sty in ("box", "outline"):
            overlay = vivid and len(ss) >= 2
        else:  # plain text: only when it stays put on screen while the footage around it moves
            overlay = vivid and len(ss) >= 3 and mot["motion"] == "static" and mot.get("bg_moving", False)
        if not overlay:
            kind = "scene"
        elif end - start > 0.8 * dur and c["_ref"]["box"][3] * sx < 0.035 * H:
            kind = "watermark"
        else:
            kind = "caption"
        rb = c["_ref"]["box"]
        cx, cy = center(rb)
        mk = masking(c) if kind == "caption" else {"masked": False}
        caps.append({
            "id": k, "kind": kind, "text": c["text"], "start": round(start, 2), "end": round(end, 2),
            "dur": round(end - start, 2), "x_pct": round(100 * cx / OCR_W, 1), "y_pct": round(100 * cy * sx / H, 1),
            "w_pct": round(100 * rb[2] / OCR_W, 1), "text_h_px": round(rb[3] * sx * 1920 / H),
            "style": sty, "box_color": bcol, "text_color": tcol, **mot, **mk,
            "samples": [{"t": s["t"], "box": [round(v * sx) for v in s["box"]], "text": s["text"]} for s in ss],
        })
    # role tags: short text ending in ':' sitting right above another caption at the same time
    for a in caps:
        if a["kind"] != "caption" or not a["text"].rstrip().endswith(":"):
            continue
        for b in caps:
            if b is a or b["kind"] != "caption":
                continue
            if abs(b["start"] - a["start"]) < 0.25 and 0 < b["y_pct"] - a["y_pct"] < 8:
                a["is_tag_for"] = b["id"]
                b["tag"] = a["text"]
    fx = effects(sig, fps)
    lay = layout(video, meta)
    res = {"video": str(video), "duration": round(dur, 2), "fps": fps, "w": W, "h": H, "layout": lay,
           "effects": fx, "captions": caps}
    (out / "timeline.json").write_text(json.dumps(res, indent=1))
    sheets(out, frames, caps, inst, sig, fx, video, meta)
    write_md(out, res)
    return res


def sheets(out: Path, frames: dict, caps: list[dict], inst: list[dict], sig, fx, video: Path, meta: dict) -> None:
    sx = meta["w"] / OCR_W
    cap_imgs, trk_imgs, msk_imgs = [], [], []
    for c in caps:
        if c["kind"] != "caption":
            continue
        s0 = c["samples"][0]
        fi = int(round(s0["t"] * meta["fps"]))
        if fi in frames:
            im = frames[fi].copy()
            x, y, w, h = [int(v / sx) for v in s0["box"]]
            cv2.rectangle(im, (x - 3, y - 3), (x + w + 3, y + h + 3), (0, 255, 255), 2)
            label(im, f"#{c['id']} {c['start']:.2f}-{c['end']:.2f}s", 30, 0.7)
            label(im, f"{c['style']}/{c['text_color']} {c['motion']}{' MASKED' if c.get('masked') else ''}", 60, 0.6)
            cap_imgs.append(im)
        if c["motion"] == "tracked":
            ss = c["samples"]
            for s in [ss[0], ss[len(ss) // 3], ss[2 * len(ss) // 3], ss[-1]]:
                fi = int(round(s["t"] * meta["fps"]))
                if fi in frames:
                    im = frames[fi].copy()
                    x, y, w, h = [int(v / sx) for v in s["box"]]
                    cv2.rectangle(im, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    label(im, f"#{c['id']} t={s['t']:.2f}", 30, 0.7, (0, 255, 0))
                    trk_imgs.append(im)
        if c.get("masked"):
            ins = inst[c["id"]]
            worst = max(c["masked_samples"], key=lambda h: h["covered"])
            ws = next(s for s in ins["samples"] if s["t"] == worst["t"])
            for s, tag in ((ins["_ref"], "full"), (ws, f"covered {worst['covered']:.0%}")):
                fi = s["i"]
                if fi in frames:
                    im = frames[fi].copy()
                    x, y, w, h = [int(v) for v in ins["_ref"]["box"]]
                    cv2.rectangle(im, (x - 4, y - 4), (x + w + 4, y + h + 4), (255, 0, 255), 2)
                    label(im, f"#{c['id']} t={s['t']:.2f} {tag}", 30, 0.7, (255, 0, 255))
                    msk_imgs.append(im)
    for name, imgs, cols in (("sheet_captions.jpg", cap_imgs, 6), ("sheet_tracked.jpg", trk_imgs, 4),
                             ("sheet_masked.jpg", msk_imgs, 4)):
        t = tile(imgs, cols)
        if t is not None:
            cv2.imwrite(str(out / name), t, [cv2.IMWRITE_JPEG_QUALITY, 85])
    # effects: grab frames at event times
    times = ([("cut", t) for t in fx["cuts"]] + [("B&W", w[0]) for w in fx["bw"]] + [("flash", t) for t in fx["flashes"]]
             + [(f"punch x{p['scale']}", p["t"]) for p in fx["punch_ins"]] + [("freeze", w[0]) for w in fx["freezes"]])
    imgs = []
    capv = cv2.VideoCapture(str(video))
    for name, t in sorted(times, key=lambda x: x[1])[:36]:
        capv.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = capv.read()
        if ok:
            im = cv2.resize(fr, (OCR_W, int(OCR_W * meta["h"] / meta["w"])))
            label(im, f"{name} t={t:.2f}", 34, 0.8)
            imgs.append(im)
    capv.release()
    t = tile(imgs, 6)
    if t is not None:
        cv2.imwrite(str(out / "sheet_effects.jpg"), t, [cv2.IMWRITE_JPEG_QUALITY, 85])


def write_md(out: Path, r: dict) -> None:
    L = [f"# Study: {Path(r['video']).name}", "",
         f"{r['duration']}s, {r['w']}x{r['h']} @ {r['fps']:.0f}fps. Layout: " +
         (f"centre band (aspect {r['layout'].get('band_aspect')}, rows {r['layout'].get('band_top_pct')}-{r['layout'].get('band_bottom_pct')}%) with blurred fill"
          if r["layout"].get("band_layout") else "full frame / no blurred band detected"), "",
         "## Captions (overlay text, in order)", "",
         "| # | time | text | tag | y% | x% | w% | text px | style | colour | motion | masked |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in r["captions"]:
        if c["kind"] != "caption" or c.get("is_tag_for") is not None:
            continue
        L.append(f"| {c['id']} | {c['start']:.2f}-{c['end']:.2f} | `{c['text']}` | {c.get('tag', '')} | {c['y_pct']} | {c['x_pct']} | "
                 f"{c['w_pct']} | {c['text_h_px']} | {c['style']}{'/' + c['box_color'] if c['box_color'] else ''} | {c['text_color']} | "
                 f"{c['motion']}{' (pop)' if c.get('scale_anim') else ''} | {'YES ' + str(int(100 * c['max_covered'])) + '%' if c.get('masked') else ''} |")
    wm = [c["text"] for c in r["captions"] if c["kind"] == "watermark"]
    if wm:
        L += ["", f"Watermark: `{wm[0]}`"]
    fx = r["effects"]
    L += ["", "## Effects", "",
          f"- cuts ({len(fx['cuts'])}): {', '.join(f'{t:.2f}' for t in fx['cuts'])}",
          f"- black & white: {', '.join(f'{a:.2f}-{b:.2f}' for a, b in fx['bw']) or 'none'}",
          f"- flashes: {', '.join(f'{t:.2f}' for t in fx['flashes']) or 'none'}",
          f"- freeze frames: {', '.join(f'{a:.2f}-{b:.2f}' for a, b in fx['freezes']) or 'none'}",
          f"- punch-ins (instant zoom): {', '.join(f'{p['t']:.2f} x{p['scale']}' for p in fx['punch_ins']) or 'none'}",
          f"- push-ins (slow zoom): {', '.join(f'{p['start']:.2f}-{p['end']:.2f} x{p['total']}' for p in fx['push_ins']) or 'none'}",
          f"- shake: {', '.join(f'{a:.2f}-{b:.2f}' for a, b in fx['shake']) or 'none'}", "",
          "Scene text ignored: " + (", ".join(f"`{c['text']}`" for c in r["captions"] if c["kind"] == "scene")[:400] or "none"),
          "", "Check the sheets before trusting a 'tracked' or 'masked' call."]
    (out / "study.md").write_text("\n".join(L) + "\n")


# --------------------------------------------------------------------------
# aggregate
# --------------------------------------------------------------------------
def q(vals, p):
    return round(float(np.percentile(vals, p)), 1) if vals else None


def aggregate(study_dir: Path, out_md: Path) -> None:
    runs = sorted(study_dir.rglob("timeline.json"))
    by: dict[str, list[dict]] = {}
    for p in runs:
        r = json.loads(p.read_text())
        ch = p.parent.parent.name if p.parent.parent != study_dir else "misc"
        by.setdefault(ch, []).append(r)
    L = ["# Style profile (measured from reference videos)", "",
         f"Built by `tools/study_reference.py` from {len(runs)} videos in `{study_dir.relative_to(ROOT) if study_dir.is_relative_to(ROOT) else study_dir}`.",
         "Numbers are per channel. y% is the caption centre from the top of the 9:16 frame; text px is the line height on a 1920-high frame.", ""]
    profile = {}
    for ch, rs in sorted(by.items()):
        caps = [c for r in rs for c in r["captions"] if c["kind"] == "caption" and c.get("is_tag_for") is None]
        durs = [r["duration"] for r in rs]
        n = max(1, len(caps))
        tracked = [c for c in caps if c["motion"] == "tracked"]
        masked = [c for c in caps if c.get("masked")]
        animated = [c for c in caps if c["motion"] == "animated"]
        pops = [c for c in caps if c.get("scale_anim")]
        rel_mask = [round(c["start"] / r["duration"], 2) for r in rs for c in r["captions"] if c.get("masked")]
        styles = {}
        for c in caps:
            k = f"{c['style']}{'/' + c['box_color'] if c['box_color'] else ''} + {c['text_color']} text"
            styles[k] = styles.get(k, 0) + 1
        fx = [r["effects"] for r in rs]
        p = {
            "videos": len(rs), "median_len_s": q(durs, 50),
            "captions_per_10s": round(10 * len(caps) / max(1e-6, sum(durs)), 1),
            "caption_dur_s": [q([c["dur"] for c in caps], 25), q([c["dur"] for c in caps], 50), q([c["dur"] for c in caps], 75)],
            "y_pct": [q([c["y_pct"] for c in caps], 10), q([c["y_pct"] for c in caps], 50), q([c["y_pct"] for c in caps], 90)],
            "text_px": [q([c["text_h_px"] for c in caps], 25), q([c["text_h_px"] for c in caps], 50), q([c["text_h_px"] for c in caps], 75)],
            "w_pct_median": q([c["w_pct"] for c in caps], 50),
            "styles": dict(sorted(styles.items(), key=lambda kv: -kv[1])[:6]),
            "tracked_pct": round(100 * len(tracked) / n, 1), "masked_pct": round(100 * len(masked) / n, 1),
            "animated_pct": round(100 * len(animated) / n, 1), "pop_in_pct": round(100 * len(pops) / n, 1),
            "tracked_examples": [f"{c['text']} ({c['start']:.1f}s)" for c in tracked[:8]],
            "masked_examples": [f"{c['text']} ({c['start']:.1f}s, {int(100 * c['max_covered'])}% covered)" for c in masked[:8]],
            "masked_when_rel": rel_mask[:20],
            "videos_with_tracking": sum(1 for r in rs if any(c["motion"] == "tracked" for c in r["captions"] if c["kind"] == "caption")),
            "videos_with_masking": sum(1 for r in rs if any(c.get("masked") for c in r["captions"])),
            "band_layout_pct": round(100 * sum(1 for r in rs if r["layout"].get("band_layout")) / len(rs)),
            "band_aspect_median": q([r["layout"]["band_aspect"] for r in rs if r["layout"].get("band_aspect")], 50),
            "cuts_per_10s": round(10 * sum(len(f["cuts"]) for f in fx) / max(1e-6, sum(durs)), 1),
            "videos_with_bw": sum(1 for f in fx if f["bw"]), "videos_with_flash": sum(1 for f in fx if f["flashes"]),
            "videos_with_freeze": sum(1 for f in fx if f["freezes"]),
            "videos_with_punch_in": sum(1 for f in fx if f["punch_ins"]),
            "bw_when_rel": [round(f["bw"][0][0] / r["duration"], 2) for f, r in zip(fx, rs) if f["bw"]],
        }
        profile[ch] = p
        L += [f"## {ch} ({p['videos']} videos, median {p['median_len_s']}s)", "",
              f"- **Captions:** {p['captions_per_10s']} per 10s, on screen {p['caption_dur_s'][1]}s median (IQR {p['caption_dur_s'][0]}-{p['caption_dur_s'][2]}s)",
              f"- **Position:** centre y {p['y_pct'][1]}% (10-90%: {p['y_pct'][0]}-{p['y_pct'][2]}%), median width {p['w_pct_median']}% of frame",
              f"- **Size:** text line {p['text_px'][1]}px on 1920 (IQR {p['text_px'][0]}-{p['text_px'][2]})",
              f"- **Style:** " + "; ".join(f"{k} x{v}" for k, v in p["styles"].items()),
              f"- **Tracking:** {p['tracked_pct']}% of captions, in {p['videos_with_tracking']}/{p['videos']} videos. e.g. {', '.join(p['tracked_examples']) or '-'}",
              f"- **Masking:** {p['masked_pct']}% of captions, in {p['videos_with_masking']}/{p['videos']} videos, at relative times {p['masked_when_rel'] or '-'}. e.g. {', '.join(p['masked_examples']) or '-'}",
              f"- **Animated (slide/bounce):** {p['animated_pct']}%; pop-in scale: {p['pop_in_pct']}%",
              f"- **Framing:** blurred-band layout in {p['band_layout_pct']}% (band aspect {p['band_aspect_median']})",
              f"- **Effects:** {p['cuts_per_10s']} cuts / 10s; B&W in {p['videos_with_bw']} (at {p['bw_when_rel'] or '-'} of runtime), "
              f"flash in {p['videos_with_flash']}, freeze in {p['videos_with_freeze']}, punch-in in {p['videos_with_punch_in']}", ""]
    out_md.write_text("\n".join(L) + "\n")
    out_md.with_suffix(".json").write_text(json.dumps(profile, indent=1))
    print(f"Wrote {out_md}")


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "aggregate":
        d = Path(sys.argv[2]) if len(sys.argv) > 2 else REF / "_study"
        aggregate(d.resolve(), REF / "STYLE_PROFILE.md")
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="a video, or a folder of videos (references/<channel>/...)")
    ap.add_argument("--ocr-fps", type=float, default=10.0, help="caption samples per second (default 10)")
    ap.add_argument("--out", default=None, help="output folder (default references/_study/<channel>/<video>)")
    ap.add_argument("--force", action="store_true", help="re-study videos that already have a timeline")
    a = ap.parse_args()
    tgt = Path(a.target).resolve()
    vids = [tgt] if tgt.is_file() else sorted(p for p in tgt.rglob("*") if p.suffix.lower() in VIDEO_EXT and "_study" not in p.parts)
    for v in vids:
        ch = v.parent.name if v.parent != REF else "misc"
        out = Path(a.out) if a.out else REF / "_study" / ch / v.stem
        if (out / "timeline.json").exists() and not a.force:
            print(f"skip {v.name} (already studied; --force to redo)")
            continue
        print(f"studying {v.name} ...", flush=True)
        r = study(v, out, a.ocr_fps)
        nc = sum(1 for c in r["captions"] if c["kind"] == "caption")
        print(f"  {nc} captions ({sum(1 for c in r['captions'] if c['motion'] == 'tracked' and c['kind'] == 'caption')} tracked, "
              f"{sum(1 for c in r['captions'] if c.get('masked'))} masked), {len(r['effects']['cuts'])} cuts -> {out}")
    if tgt.is_dir():
        aggregate((REF / "_study").resolve(), REF / "STYLE_PROFILE.md")


if __name__ == "__main__":
    main()
