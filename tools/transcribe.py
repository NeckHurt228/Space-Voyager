#!/usr/bin/env python3
"""
transcribe.py - hear the clip: word-level transcript with timestamps and confidence.

Runs Whisper (small, int8, CPU) via faster-whisper. Two passes:
  1. whole clip, no prompt          -> the main transcript
  2. each spoken line on its own    -> a second opinion (catches words Whisper drops or
                                       merges on noisy, shouted audio)
Words under 0.5 probability are marked with '?' so they get double-checked before
they end up in a caption.

Usage:
  python3 tools/transcribe.py clips/my_clip.mp4 [--prompt "context words"] [--out reports]

Writes reports/<clip>/transcript.json and prints a readable version.
Setup (once per machine): bash tools/setup_asr.sh
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

MODEL_DIR = Path(os.environ.get("CLIP_COACH_ASR_MODEL",
                                Path.home() / ".cache/clip-coach/whisper-small-ct2"))
SR = 16000


def load_audio(path: Path, clean: bool):
    import numpy as np
    af = ["-af", "highpass=f=100,dynaudnorm"] if clean else []
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
                        *af, "-f", "s16le", "-"], capture_output=True)
    if p.returncode != 0:
        sys.exit(f"error: ffmpeg could not decode audio:\n{p.stderr.decode()[-500:]}")
    return np.frombuffer(p.stdout, np.int16).astype(np.float32) / 32768


def words_of(model, audio, offset: float, prompt: str | None):
    segs, _ = model.transcribe(audio, language="en", word_timestamps=True, beam_size=5,
                               initial_prompt=prompt, condition_on_previous_text=False,
                               temperature=0)
    out = []
    for s in segs:
        for w in s.words or []:
            out.append({"word": w.word.strip(), "start": round(w.start + offset, 2),
                        "end": round(w.end + offset, 2), "p": round(w.probability, 2)})
    return out


def lines(words, gap: float = 0.6):
    """Group words into spoken lines at pauses >= gap seconds."""
    res, cur = [], []
    for w in words:
        if cur and w["start"] - cur[-1]["end"] >= gap:
            res.append(cur)
            cur = []
        cur.append(w)
    if cur:
        res.append(cur)
    return [{"start": l[0]["start"], "end": l[-1]["end"],
             "text": " ".join(w["word"] + ("?" if w["p"] < 0.5 else "") for w in l)} for l in res]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip", type=Path)
    ap.add_argument("--prompt", help="context hint, e.g. 'soldier chant, A is for Army'")
    ap.add_argument("--out", type=Path, default=Path("reports"))
    a = ap.parse_args()
    if not (MODEL_DIR / "model.bin").exists():
        sys.exit(f"error: no speech model at {MODEL_DIR}. Run: bash tools/setup_asr.sh")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("error: faster-whisper missing. Run: bash tools/setup_asr.sh")

    model = WhisperModel(str(MODEL_DIR), device="cpu", compute_type="int8",
                         cpu_threads=os.cpu_count() or 4)
    audio = load_audio(a.clip, clean=True)
    dur = len(audio) / SR

    main_words = words_of(model, audio, 0.0, a.prompt)
    # second opinion: re-transcribe each spoken line on its own (padded), so Whisper
    # isn't steered by the surrounding lines and window edges never cut a word
    win_words = []
    for l in lines(main_words):
        t, e = max(0.0, l["start"] - 0.4), min(dur, l["end"] + 0.4)
        win_words += words_of(model, audio[int(t * SR):int(e * SR)], t, None)

    result = {
        "clip": str(a.clip), "duration": round(dur, 2), "model": "whisper-small int8",
        "has_speech": bool(main_words),
        "lines": lines(main_words),
        "lines_windowed": lines(sorted({(w["start"], w["word"]): w for w in win_words}.values(),
                                       key=lambda w: w["start"])),
        "words": main_words,
    }
    outdir = a.out / a.clip.stem
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "transcript.json").write_text(json.dumps(result, indent=2))

    print(f"# Transcript: {a.clip.name} ({dur:.1f}s)   '?' = low confidence, verify")
    if not main_words:
        print("  (no speech detected)")
    print("## Main pass")
    for l in result["lines"]:
        print(f"  {l['start']:5.2f}-{l['end']:5.2f}  {l['text']}")
    print("## Windowed pass (second opinion)")
    for l in result["lines_windowed"]:
        print(f"  {l['start']:5.2f}-{l['end']:5.2f}  {l['text']}")
    print(f"Saved {outdir / 'transcript.json'}")


if __name__ == "__main__":
    main()
