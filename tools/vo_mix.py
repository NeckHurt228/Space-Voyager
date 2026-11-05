#!/usr/bin/env python3
"""
vo_mix.py - fit, check and mix a voiceover onto a short.

Two subcommands:

  check  PLAN.json            Timing check without audio: estimates each line's
                              spoken length from its word count and flags lines that
                              don't fit their slot or talk over the payoff.

  mix    VIDEO PLAN.json      Places the voiceover lines at their timestamps, ducks the
         [--out OUT.mp4]      clip's own audio under the voice, normalises loudness to
                              -14 LUFS (Shorts level) and writes a new mp4. The video
                              stream is copied untouched.

PLAN.json
---------
{
  "vo_file": "reports/clip/vo.mp3",   # ONE take with all lines, separated by pauses
                                      # (TTS output or your own recording)
  "payoff": 4.2,                      # seconds in the EDITED video; VO must not cover it
  "duck_db": 12,                      # how far the clip audio drops under the voice
  "vo_gain_db": 0,
  "wps": 2.8,                         # speaking rate for `check` (words per second)
  "video_len": 7.4,                   # edited video length, so `check` can flag overruns
  "vo_is_hook": true,                 # false when the clip's own audio is the hook and
                                      # the VO only comes in later (e.g. a closing line)
  "lines": [
    {"at": 0.15, "text": "Day one of sandbag detail."},
    {"at": 4.9,  "text": "He did not need to go that fast."},
    {"at": 6.4,  "text": "Nobody asked him to."}
  ]
}
Instead of "vo_file", each line may have its own "file".

When one vo_file is used, it is split into len(lines) pieces at its longest pauses,
so a single TTS call (one credit charge) or a single recorded take covers the whole video.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PAYOFF_GUARD = 0.35  # seconds either side of the payoff the voice must stay clear of


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        die(f"{cmd[0]} failed:\n{p.stderr[-1200:]}")
    return p.stdout + p.stderr


def duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)])
    return float(out.strip().splitlines()[0])


def has_audio(path: Path) -> bool:
    out = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
               "stream=index", "-of", "csv=p=0", str(path)])
    return bool(out.strip())


def words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


def est_len(text: str, wps: float) -> float:
    # pauses written into the line ("...", "-", ",") cost time too
    pauses = text.count("...") * 0.35 + text.count(",") * 0.15 + text.count(" - ") * 0.25
    return round(words(text) / wps + pauses + 0.15, 2)


# --------------------------------------------------------------------------
def split_take(vo: Path, n: int) -> list[tuple[float, float]]:
    """Split one take into n speech segments at its n-1 longest pauses."""
    total = duration(vo)
    out = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(vo),
               "-af", "silencedetect=n=-38dB:d=0.18", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    gaps = list(zip(starts, ends + [total] * (len(starts) - len(ends))))

    # leading / trailing silence of the whole take
    # (mp3 encoder padding means the last silence can end ~50ms before the file does)
    head = gaps[0][1] if gaps and gaps[0][0] <= 0.12 else 0.0
    tail = gaps[-1][0] if gaps and gaps[-1][1] >= total - 0.12 else total
    inner = [g for g in gaps if g[0] > head + 0.01 and g[1] < tail - 0.01]

    if n == 1:
        return [(head, tail)]
    if len(inner) < n - 1:
        die(f"voiceover has only {len(inner) + 1} speech parts but the plan has {n} lines. "
            "Leave a clear pause (about 0.6s) between lines, or give each line its own file.")
    cut = sorted(sorted(inner, key=lambda g: g[1] - g[0], reverse=True)[: n - 1])
    segs, cur = [], head
    for s, e in cut:
        segs.append((cur, s))
        cur = e
    segs.append((cur, tail))
    if min(b - a for a, b in segs) < 0.12:
        die("voiceover splits into a fragment shorter than 0.12s, so the take probably has fewer lines "
            f"than the plan ({n}). Check the pauses between lines or the number of lines.")
    return [(round(a, 3), round(b, 3)) for a, b in segs]


# --------------------------------------------------------------------------
def timing_table(lines, lens, payoff, video_len=None, vo_is_hook=True) -> list[str]:
    rows, issues = [], []
    for i, (ln, d) in enumerate(zip(lines, lens)):
        start, end = ln["at"], ln["at"] + d
        nxt = lines[i + 1]["at"] if i + 1 < len(lines) else (video_len or end)
        flag = []
        if end > nxt + 0.05:
            flag.append(f"runs {end - nxt:.2f}s into the next line"
                        if i + 1 < len(lines) else f"runs {end - nxt:.2f}s past the end")
        if payoff is not None and start < payoff + PAYOFF_GUARD and end > payoff - PAYOFF_GUARD:
            flag.append(f"talks over the payoff at {payoff}s, so move it after {payoff + PAYOFF_GUARD:.2f}s")
        if i == 0 and vo_is_hook and start > 0.4:
            flag.append("first line starts late; the voice should hit within 0.3s")
        rows.append(f"  {i + 1}. {start:5.2f}-{end:5.2f}s ({d:.2f}s)  {ln.get('text', '')[:60]}"
                    + ("" if not flag else "   <-- " + "; ".join(flag)))
        issues += flag
    rows.append("  OK, everything fits." if not issues else f"  {len(issues)} issue(s) to fix.")
    return rows


def cmd_check(plan: dict) -> None:
    wps = float(plan.get("wps", 2.8))
    lines = plan["lines"]
    lens = [est_len(ln.get("text", ""), wps) for ln in lines]
    print(f"Estimated at {wps} words/s:")
    print("\n".join(timing_table(lines, lens, plan.get("payoff"), plan.get("video_len"),
                                  plan.get("vo_is_hook", True))))


def cmd_mix(video: Path, plan: dict, plan_dir: Path, out: Path) -> None:
    lines = plan["lines"]
    if not lines:
        die("plan has no lines")
    lines = sorted(lines, key=lambda l: l["at"])

    def resolve(p: str) -> Path:
        q = Path(p)
        if not q.is_absolute() and not q.exists():
            q = plan_dir / q
        if not q.exists():
            die(f"audio file not found: {p}")
        return q

    inputs, pieces = [str(video)], []  # pieces: (input_idx, trim_start, trim_end)
    if plan.get("vo_file"):
        vo = resolve(plan["vo_file"])
        inputs.append(str(vo))
        for a, b in split_take(vo, len(lines)):
            pieces.append((1, a, b))
    else:
        for ln in lines:
            if "file" not in ln:
                die("each line needs a 'file' when no 'vo_file' is given")
            f = resolve(ln["file"])
            inputs.append(str(f))
            pieces.append((len(inputs) - 1, 0.0, duration(f)))

    vlen = duration(video)
    lens = [round(b - a, 2) for _, a, b in pieces]
    print("Measured voiceover timing:")
    print("\n".join(timing_table(lines, lens, plan.get("payoff"), vlen, plan.get("vo_is_hook", True))))

    gain = float(plan.get("vo_gain_db", 0))
    duck = float(plan.get("duck_db", 12))
    f = []
    for k, ((idx, a, b), ln) in enumerate(zip(pieces, lines)):
        ms = int(round(ln["at"] * 1000))
        f.append(f"[{idx}:a]atrim={a}:{b},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,"
                 f"afade=t=in:d=0.02,afade=t=out:st={max(0, b - a - 0.04):.3f}:d=0.04,"
                 f"volume={gain}dB,adelay={ms}|{ms}[v{k}]")
    vo_bus = "".join(f"[v{k}]" for k in range(len(pieces)))
    f.append(f"{vo_bus}amix=inputs={len(pieces)}:normalize=0:duration=longest,apad,"
             f"atrim=0:{vlen:.3f}[vo]")
    if has_audio(video):
        # deterministic ducking: we know exactly when each line plays, so dip the clip
        # audio by duck_db over those windows with a 0.1s fade-in and 0.25s release
        floor = 10 ** (-duck / 20)
        ramps = [f"clip(min((t-{ln['at'] - 0.1:.3f})/0.1,({ln['at'] + d + 0.25:.3f}-t)/0.25),0,1)"
                 for ln, d in zip(lines, lens)]
        env = ramps[0]
        for r in ramps[1:]:
            env = f"max({env},{r})"
        f.append(f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                 f"volume=eval=frame:volume='1-{1 - floor:.4f}*{env}'[ducked]")
        f.append("[ducked][vo]amix=inputs=2:normalize=0:duration=first[mix]")
    else:
        f.append("[vo]anull[mix]")
    base = ["ffmpeg", "-hide_banner", "-nostats", "-y"]
    for i in inputs:
        base += ["-i", i]

    # pass 1: measure loudness of the mix
    target = "I=-14:TP=-1.5:LRA=11"
    meas = run(base + ["-filter_complex", ";".join(f + [f"[mix]loudnorm={target}:print_format=json[aout]"]),
                       "-map", "[aout]", "-f", "null", "-"])
    m = json.loads(meas[meas.rfind("{"): meas.rfind("}") + 1])
    norm = (f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
            f"offset={m['target_offset']}:linear=true")

    # pass 2: render with the measured values (accurate on short clips)
    run(base + ["-loglevel", "error", "-filter_complex", ";".join(f + [f"[mix]{norm}[aout]"]),
                "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(out)])
    print(f"Wrote {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("plan", type=Path)
    m = sub.add_parser("mix")
    m.add_argument("video", type=Path)
    m.add_argument("plan", type=Path)
    m.add_argument("--out", type=Path)
    a = ap.parse_args()
    for t in ("ffmpeg", "ffprobe"):
        if not shutil.which(t):
            die(f"{t} not found on PATH")
    plan = json.loads(a.plan.read_text())
    if a.cmd == "check":
        cmd_check(plan)
    else:
        if not a.video.exists():
            die(f"{a.video} not found")
        out = a.out or a.video.with_name(a.video.stem + "_vo.mp4")
        cmd_mix(a.video, plan, a.plan.parent, out)


if __name__ == "__main__":
    main()
