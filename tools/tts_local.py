#!/usr/bin/env python3
"""
tts_local.py - voiceover lines with a free local voice (Kokoro, Apache 2.0), for when vidIQ credits run out.

  python3 tools/tts_local.py "At ease means someone important walked in." reports/<clip>/vo/line1.wav \
      [--voice am_onyx] [--speed 1.15] [--max 2.5]

Writes a WAV trimmed to the speech (30 ms lead-in, 80 ms tail) and prints its length; --max warns when
it won't fit the slot. Then point vo_plan.json at it ("lines": [{"at": 0.15, "file": "vo/line1.wav", ...}]).

Voices that suit the personas in voiceover.md:
  deadpan narrator  am_onyx (deep) · bm_george (British storyteller)
  buddy / inner     am_michael · am_puck · am_liam
  drill sergeant    am_fenrir (hard, fast)
Can't listen? Check the take with: python3 tools/transcribe.py <wav> --out <tmp dir>
First run downloads the model (~350 MB) from the kokoro-onnx GitHub release, checked against sha256.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

DIR = Path.home() / ".cache" / "clip-coach" / "tts"
REL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = {"kokoro-v1.0.onnx": "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
         "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"}


def ensure() -> None:
    try:
        import kokoro_onnx, soundfile  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "kokoro-onnx", "soundfile"], check=True)
    DIR.mkdir(parents=True, exist_ok=True)
    for name, sha in FILES.items():
        p = DIR / name
        if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == sha:
            continue
        print(f"downloading {name} ...", file=sys.stderr)
        subprocess.run(["curl", "-fsSL", "-o", str(p) + ".part", REL + name], check=True)
        if hashlib.sha256(Path(str(p) + ".part").read_bytes()).hexdigest() != sha:
            Path(str(p) + ".part").unlink()
            sys.exit(f"checksum mismatch for {name}")
        Path(str(p) + ".part").rename(p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("out")
    ap.add_argument("--voice", default="am_onyx")
    ap.add_argument("--speed", type=float, default=1.1)
    ap.add_argument("--max", type=float, default=None, help="slot length in seconds; warn if the line is longer")
    a = ap.parse_args()
    ensure()
    import numpy as np
    import soundfile as sf
    from kokoro_onnx import Kokoro
    k = Kokoro(str(DIR / "kokoro-v1.0.onnx"), str(DIR / "voices-v1.0.bin"))
    lang = "en-gb" if a.voice.startswith("b") else "en-us"
    audio, sr = k.create(a.text, voice=a.voice, speed=a.speed, lang=lang)
    env = np.abs(audio) > 0.02 * np.abs(audio).max()
    i0, i1 = int(np.argmax(env)), len(audio) - int(np.argmax(env[::-1]))
    audio = audio[max(0, i0 - int(0.03 * sr)): i1 + int(0.08 * sr)]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    sf.write(a.out, audio, sr)
    dur = len(audio) / sr
    print(f"Wrote {a.out} ({dur:.2f}s, {a.voice} x{a.speed})")
    if a.max and dur > a.max:
        print(f"warning: {dur:.2f}s is longer than the {a.max:.2f}s slot - raise --speed (max ~1.25) or cut words")


if __name__ == "__main__":
    main()
