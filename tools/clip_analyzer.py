#!/usr/bin/env python3
"""
clip_analyzer.py - measure a short-form clip and score its structure against
the benchmarks pulled from Combatful / ArmoredPOVs / AirHard.

It measures what can be measured from pixels and audio:
  * duration, resolution, aspect ratio
  * hard cuts (scene changes) and the longest shot without a cut
  * motion curve and loudness curve (per 0.1s)
  * hook energy in the first second (dead start?)
  * candidate PAYOFF moments (biggest combined jump in motion + loudness)
  * tail length after the payoff (does it end on the reaction?)
  * dead-air spans (low motion + low audio) that should be trimmed
  * contact sheets (whole clip, hook strip, payoff strip) for visual review

It does NOT judge content (stakes, twist, emotion) - that is the agent's job,
using the contact sheets and the rubric in .claude/skills/clip-coach/.

Usage:
  python3 tools/clip_analyzer.py path/to/clip.mp4 [--type auto|comedy|story]
                                 [--mode raw|edited] [--out reports/]

Needs ffmpeg + ffprobe on PATH and Pillow (pip install pillow).
"""
from __future__ import annotations

import argparse
import array
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BIN = 0.1  # seconds per analysis bin

# --------------------------------------------------------------------------
# Benchmarks (see .claude/skills/clip-coach/benchmarks.md for the source data)
# --------------------------------------------------------------------------
BENCH = {
    "comedy": {
        "length": (5.0, 10.0),         # sweet spot, seconds
        "length_ok": (4.0, 15.0),      # still acceptable
        "payoff_pos": (0.25, 0.60),    # payoff as fraction of runtime
        "max_tail": 2.5,               # seconds after payoff before the end
        "max_static": 1.5,             # longest span with no visual change
    },
    "story": {
        "length": (20.0, 50.0),
        "length_ok": (15.0, 59.0),
        "payoff_pos": (0.55, 0.88),
        "max_tail": 6.0,
        "max_static": 3.0,
    },
}


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], binary: bool = False) -> str | bytes:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        die(f"command failed: {' '.join(cmd[:4])}...\n{p.stderr.decode(errors='replace')[-800:]}")
    return p.stdout if binary else p.stdout.decode(errors="replace")


# --------------------------------------------------------------------------
# Probing
# --------------------------------------------------------------------------
def probe(path: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", str(path)])
    info = json.loads(out)
    v = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
    a = next((s for s in info["streams"] if s.get("codec_type") == "audio"), None)
    if v is None:
        die("no video stream found")
    w, h = int(v["width"]), int(v["height"])
    # respect rotation metadata (phone footage)
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = abs(int(sd["rotation"]))
    if rot in (90, 270):
        w, h = h, w
    dur = float(info["format"].get("duration") or v.get("duration") or 0)
    num, den = (v.get("avg_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    return {"duration": dur, "width": w, "height": h, "fps": round(fps, 2),
            "has_audio": a is not None}


# --------------------------------------------------------------------------
# Motion / cuts
# --------------------------------------------------------------------------
def scene_scores(path: Path) -> list[tuple[float, float]]:
    out = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-an",
               "-vf", "scale=192:-2,select='gte(scene,0)',metadata=print:file=-",
               "-f", "null", "-"])
    res, t = [], None
    for line in out.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"lavfi\.scene_score=([\d.]+)", line)
        if m and t is not None:
            res.append((t, float(m.group(1))))
    return res


def motion_curve(path: Path, n: int, w: int, h: int) -> list[float]:
    """Mean absolute pixel change between consecutive frames, one value per bin."""
    sw = 48
    sh = max(2, int(round(sw * h / w / 2)) * 2)
    raw = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-an",
               "-vf", f"fps={1 / BIN:g},scale={sw}:{sh},format=gray",
               "-f", "rawvideo", "-"], binary=True)
    size = sw * sh
    frames = [raw[i:i + size] for i in range(0, len(raw) - size + 1, size)]
    out = [0.0]
    for a, b in zip(frames, frames[1:]):
        out.append(sum(abs(x - y) for x, y in zip(a, b)) / size / 255)
    out = (out + [out[-1]] * n)[:n]
    return out


def bin_series(points: list[tuple[float, float]], n: int, agg=max) -> list[float]:
    bins: list[list[float]] = [[] for _ in range(n)]
    for t, val in points:
        i = min(int(t / BIN), n - 1)
        bins[i].append(val)
    out, last = [], 0.0
    for b in bins:
        last = agg(b) if b else last * 0.5
        out.append(last)
    return out


# --------------------------------------------------------------------------
# Audio loudness
# --------------------------------------------------------------------------
def loudness(path: Path, n: int) -> list[float]:
    sr = 8000
    raw = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
               "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"], binary=True)
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    step = int(sr * BIN)
    out = []
    for i in range(n):
        chunk = samples[i * step:(i + 1) * step]
        if not chunk:
            out.append(-90.0)
            continue
        rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
        out.append(20 * math.log10(rms / 32768) if rms > 0 else -90.0)
    return out


# --------------------------------------------------------------------------
# Analysis helpers
# --------------------------------------------------------------------------
def norm(xs: list[float]) -> list[float]:
    lo, hi = min(xs), max(xs)
    return [0.0 if hi == lo else (x - lo) / (hi - lo) for x in xs]


def median(xs: list[float]) -> float:
    s = sorted(xs)
    return s[len(s) // 2] if s else 0.0


def find_payoffs(motion: list[float], loud: list[float], dur: float, skip: float = 0.0, k: int = 3):
    """Rank moments where motion and loudness jump relative to the previous second.
    `skip` = seconds of dead start; positions are reported relative to the clip
    as it will be once that dead start is trimmed."""
    n = len(motion)
    win = int(1.0 / BIN)
    jump_l, jump_m = [], []
    for i in range(n):
        prev = slice(max(0, i - win), i) if i else slice(0, 1)
        pl = loud[prev] or [loud[i]]
        pm = motion[prev] or [motion[i]]
        jump_l.append(max(0.0, loud[i] - sum(pl) / len(pl)))
        jump_m.append(max(0.0, motion[i] - sum(pm) / len(pm)))
    jl, jm, la = norm(jump_l), norm(jump_m), norm(loud)
    score = [0.45 * jl[i] + 0.35 * jm[i] + 0.20 * la[i] for i in range(n)]
    s0 = int(round(skip / BIN))
    live = max(1e-6, dur - skip)
    start = s0 + max(1, int(0.12 * (n - s0)))  # a payoff in the first ~12% is just the hook
    cands = []
    order = sorted(range(start, n), key=lambda i: score[i], reverse=True)
    for i in order:
        if all(abs(i - c) * BIN >= 1.0 for c in cands):
            cands.append(i)
        if len(cands) == k:
            break
    return [{"time": round(i * BIN, 2), "position": round((i * BIN - skip) / live, 2),
             "strength": round(score[i], 2),            # relative to the rest of this clip
             "loudness_jump_db": round(jump_l[i], 1),    # absolute: vs previous second
             "motion_jump": round(jump_m[i], 3)} for i in cands]


def dead_spans(motion: list[float], loud: list[float], min_len: float = 0.8):
    med_l = median(loud)
    spans, start = [], None
    for i, (m, l) in enumerate(zip(motion, loud)):
        quiet = m < 0.003 and l < med_l - 4
        if quiet and start is None:
            start = i
        elif not quiet and start is not None:
            if (i - start) * BIN >= min_len:
                spans.append((round(start * BIN, 1), round(i * BIN, 1)))
            start = None
    if start is not None and (len(motion) - start) * BIN >= min_len:
        spans.append((round(start * BIN, 1), round(len(motion) * BIN, 1)))
    return spans


def static_spans(motion: list[float], cuts: list[float], dur: float, thresh: float):
    """Longest stretches with no cut and very low visual change."""
    spans, start = [], 0
    for i, m in enumerate(motion + [1.0]):
        t = i * BIN
        changed = m > 0.008 or any(abs(c - t) < BIN / 2 for c in cuts)
        if changed:
            if (i - start) * BIN >= thresh:
                spans.append((round(start * BIN, 1), round(min(i * BIN, dur), 1)))
            start = i + 1
    return spans


# --------------------------------------------------------------------------
# Contact sheets
# --------------------------------------------------------------------------
def extract_frames(path: Path, outdir: Path, start: float, end: float, fps: float, tag: str):
    outdir.mkdir(parents=True, exist_ok=True)
    pattern = outdir / f"{tag}_%03d.jpg"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.2f}",
         "-to", f"{end:.2f}", "-i", str(path), "-vf", f"fps={fps},scale=-2:360",
         "-q:v", "4", str(pattern)])
    files = sorted(outdir.glob(f"{tag}_*.jpg"))
    return [(start + i / fps, f) for i, f in enumerate(files)]


def make_sheet(frames, dest: Path, cols: int, title: str):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("warning: Pillow missing, skipping contact sheets (pip install pillow)", file=sys.stderr)
        return None
    if not frames:
        return None
    imgs = [(t, Image.open(f).convert("RGB")) for t, f in frames]
    tw = 200
    th = int(imgs[0][1].height * tw / imgs[0][1].width)
    rows = math.ceil(len(imgs) / cols)
    head = 34
    sheet = Image.new("RGB", (cols * tw, rows * (th + 22) + head), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=16)
    except TypeError:
        font = ImageFont.load_default()
    d.text((8, 8), title, fill=(255, 220, 80), font=font)
    for k, (t, im) in enumerate(imgs):
        x, y = (k % cols) * tw, head + (k // cols) * (th + 22)
        sheet.paste(im.resize((tw, th)), (x, y))
        d.text((x + 6, y + th + 2), f"{t:5.2f}s", fill=(230, 230, 230), font=font)
    sheet.save(dest, quality=85)
    return str(dest)


# --------------------------------------------------------------------------
# Structural scoring (40 of 100 points; the other 60 are content, judged by the agent)
# --------------------------------------------------------------------------
def band_score(x: float, sweet: tuple, ok: tuple, pts: float) -> float:
    if sweet[0] <= x <= sweet[1]:
        return pts
    if ok[0] <= x <= ok[1]:
        edge = sweet[0] if x < sweet[0] else sweet[1]
        far = ok[0] if x < sweet[0] else ok[1]
        return round(pts * (1 - 0.6 * abs(x - edge) / max(abs(far - edge), 1e-6)), 1)
    return 0.0


def score_structure(r: dict, b: dict, mode: str) -> dict:
    s, notes = {}, []
    dur = r["duration"]
    payoff = r["payoff_candidates"][0] if r["payoff_candidates"] else None

    if mode == "raw":
        # raw clips get trimmed - score the length the clip would have once trimmed
        usable = dur - sum(e - st for st, e in r["dead_spans"])
        if payoff:
            usable = min(usable, payoff["time"] + b["max_tail"] - r["hook"]["dead_start_s"])
        s["length"] = band_score(usable, b["length"], b["length_ok"], 8)
        notes.append(f"Usable length after trimming dead air and the tail is about {usable:.1f}s "
                     f"(target {b['length'][0]:.0f}-{b['length'][1]:.0f}s).")
    else:
        s["length"] = band_score(dur, b["length"], b["length_ok"], 8)
        notes.append(f"Length {dur:.1f}s (target {b['length'][0]:.0f}-{b['length'][1]:.0f}s).")

    key = "_after_trim" if mode == "raw" else ""
    hm = r["hook"][f"motion_first_1s{key}"]
    hl = r["hook"][f"loudness_first_1s{key}_db" if key else "loudness_first_1s_db"]
    hook = 0.0
    hook += 4 if hm >= 0.02 else (2 if hm >= 0.006 else 0)
    if not r["has_audio"]:
        notes.append("No audio track. Shorts without sound lose the scroll-stop; add music/SFX.")
    elif hl > r["audio"]["median_db"] - 3:
        hook += 4
    elif hl > r["audio"]["median_db"] - 10:
        hook += 2
    if r["hook"]["dead_start_s"] > 0.3:
        if mode == "edited":
            hook = max(0, hook - 3)
        notes.append(f"Dead start: the first {r['hook']['dead_start_s']:.1f}s is quiet/static. Cut it.")
    s["hook_energy"] = hook

    if payoff:
        s["payoff_timing"] = band_score(payoff["position"], b["payoff_pos"],
                                        (max(0, b["payoff_pos"][0] - 0.2), min(1, b["payoff_pos"][1] + 0.12)), 8)
        tail = dur - payoff["time"]
        if mode == "raw":
            s["tail"] = 6.0  # fixable by trimming - reported as a cut instruction below
        else:
            s["tail"] = 6.0 if tail <= b["max_tail"] else max(0.0, round(6 - 2 * (tail - b["max_tail"]), 1))
        if tail > b["max_tail"]:
            notes.append(f"{tail:.1f}s runs after the payoff at {payoff['time']}s. Hard-cut by "
                         f"{payoff['time'] + b['max_tail']:.1f}s, ideally mid-reaction.")
        punch = max(payoff["loudness_jump_db"] / 8.0, payoff["motion_jump"] / 0.06)
        s["payoff_punch"] = round(4 * min(1.0, punch), 1)
        if punch < 0.5:
            notes.append(f"Payoff at {payoff['time']}s barely stands out (+{payoff['loudness_jump_db']} dB). "
                         "Stack a bass hit/meme SFX + punch-in + colour change on it.")
    else:
        s["payoff_timing"] = s["tail"] = s["payoff_punch"] = 0.0
        notes.append("No clear payoff moment detected in motion or audio.")

    dead_total = sum(e - st for st, e in r["dead_spans"])
    if mode == "raw":
        s["dead_air"] = 6.0  # raw footage gets trimmed; reported as cut suggestions instead
    else:
        s["dead_air"] = max(0.0, round(6 - 4 * dead_total, 1))
        if r["static_spans"]:
            notes.append("Static stretches with nothing changing on screen: " +
                         ", ".join(f"{a}-{c}s" for a, c in r["static_spans"]) +
                         ". Add a caption change, punch-in or SFX there.")
    if r["dead_spans"]:
        notes.append("Dead air to cut: " + ", ".join(f"{a}-{c}s" for a, c in r["dead_spans"]))

    total = round(sum(s.values()), 1)
    return {"points": s, "total": total, "max": 40, "notes": notes}


# --------------------------------------------------------------------------
def analyze(path: Path, clip_type: str, mode: str, out_root: Path) -> dict:
    meta = probe(path)
    dur = meta["duration"]
    if dur <= 0:
        die("could not read duration")
    n = max(1, math.ceil(dur / BIN))

    sc = scene_scores(path)
    motion = motion_curve(path, n, meta["width"], meta["height"])
    cuts = [round(t, 2) for t, v in sc if v >= 0.35 and t > 0.05]
    loud = loudness(path, n) if meta["has_audio"] else [-90.0] * n

    if clip_type == "auto":
        clip_type = "comedy" if dur <= 18 else "story"
    b = BENCH[clip_type]

    shots = [0.0] + cuts + [dur]
    longest_shot = max((shots[i + 1] - shots[i] for i in range(len(shots) - 1)), default=dur)

    first = max(1, int(1.0 / BIN))
    med_l = median(loud)
    dead_start = 0.0
    for m, l in zip(motion, loud):
        if m < 0.004 and l < med_l - 6:
            dead_start += BIN
        else:
            break

    ds = int(round(dead_start / BIN))
    r = {
        "file": str(path),
        "clip_type": clip_type,
        "mode": mode,
        **meta,
        "aspect": f"{meta['width']}:{meta['height']}",
        "vertical": meta["height"] > meta["width"],
        "cuts": cuts,
        "cuts_per_10s": round(len(cuts) / dur * 10, 2),
        "longest_shot_s": round(longest_shot, 2),
        "hook": {
            # measured on the first second of the clip as it plays (and after trimming dead start)
            "motion_first_1s": round(sum(motion[:first]) / first, 4),
            "loudness_first_1s_db": round(sum(loud[:first]) / first, 1),
            "motion_first_1s_after_trim": round(sum(motion[ds:ds + first]) / first, 4),
            "loudness_first_1s_after_trim_db": round(sum(loud[ds:ds + first]) / first, 1),
            "dead_start_s": round(dead_start, 1),
        },
        "audio": {"median_db": round(med_l, 1), "peak_db": round(max(loud), 1)},
        "payoff_candidates": find_payoffs(motion, loud, dur, dead_start),
        "dead_spans": dead_spans(motion, loud),
        "static_spans": static_spans(motion, cuts, dur, b["max_static"]),
        "curves": {"bin_s": BIN,
                   "motion": [round(x, 3) for x in motion],
                   "loudness_db": [round(x, 1) for x in loud]},
    }
    r["structure_score"] = score_structure(r, b, mode)

    # contact sheets
    outdir = out_root / path.stem
    frames_dir = outdir / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    fps_all = min(4.0, max(0.5, 24 / dur))
    sheets = {}
    sheets["overview"] = make_sheet(extract_frames(path, frames_dir, 0, dur, fps_all, "all"),
                                    outdir / "sheet_overview.jpg", 6, f"{path.name}: overview")
    sheets["hook"] = make_sheet(extract_frames(path, frames_dir, 0, min(2.0, dur), 6, "hook"),
                                outdir / "sheet_hook.jpg", 6, "HOOK: first 2 seconds")
    if r["payoff_candidates"]:
        p = r["payoff_candidates"][0]["time"]
        sheets["payoff"] = make_sheet(
            extract_frames(path, frames_dir, max(0, p - 1.0), min(dur, p + 1.5), 6, "payoff"),
            outdir / "sheet_payoff.jpg", 6, f"PAYOFF candidate @ {p}s")
    r["sheets"] = {k: v for k, v in sheets.items() if v}
    shutil.rmtree(frames_dir, ignore_errors=True)

    (outdir / "analysis.json").write_text(json.dumps(r, indent=2))
    return r


def summary(r: dict) -> str:
    s = r["structure_score"]
    lines = [
        f"# {Path(r['file']).name}  ({r['clip_type']}, {r['mode']})",
        f"- Length {r['duration']:.1f}s | {r['aspect']} {'vertical' if r['vertical'] else 'horizontal, needs a 9:16 crop or blurred bars'}",
        f"- Cuts: {len(r['cuts'])} ({r['cuts_per_10s']}/10s) | longest shot {r['longest_shot_s']}s",
        f"- Hook: motion {r['hook']['motion_first_1s']}, loudness {r['hook']['loudness_first_1s_db']} dB "
        f"(median {r['audio']['median_db']}), dead start {r['hook']['dead_start_s']}s",
        "- Payoff candidates: " + (", ".join(f"{p['time']}s ({int(p['position']*100)}%, strength {p['strength']})"
                                        for p in r["payoff_candidates"]) or "none"),
        f"- STRUCTURE SCORE: {s['total']}/40  " + " ".join(f"{k}={v}" for k, v in s["points"].items()),
    ]
    lines += [f"  * {n}" for n in s["notes"]]
    if not r["vertical"]:
        lines.insert(2, "  * Source is horizontal: centre-crop to 9:16 or use blurred top/bottom bars.")
    lines += ["- Contact sheets:"] + [f"  * {k}: {v}" for k, v in r["sheets"].items()]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip", type=Path)
    ap.add_argument("--type", choices=["auto", "comedy", "story"], default="auto")
    ap.add_argument("--mode", choices=["raw", "edited"], default="raw",
                    help="raw = source clip before editing; edited = your finished short")
    ap.add_argument("--out", type=Path, default=Path("reports"))
    ap.add_argument("--json", action="store_true", help="print full JSON instead of summary")
    a = ap.parse_args()
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            die(f"{tool} not found on PATH")
    if not a.clip.exists():
        die(f"{a.clip} not found")
    r = analyze(a.clip, a.type, a.mode, a.out)
    print(json.dumps(r, indent=2) if a.json else summary(r))


if __name__ == "__main__":
    main()
