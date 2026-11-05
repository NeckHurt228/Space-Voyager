# Clip Coach workspace

This repo is an editing assistant for military / airsoft POV clip Shorts.

- When the user shares a clip (file in `clips/` or a URL) or asks about hooks, titles, pacing or
  whether a clip is worth posting, use the `clip-coach` skill (`.claude/skills/clip-coach/`).
- Measure clips with `python3 tools/clip_analyzer.py <clip> --mode raw|edited --out reports`
  and always look at the contact sheets it writes before judging content.
- Always transcribe the audio too: `python3 tools/transcribe.py <clip> --out reports`
  (first run: `bash tools/setup_asr.sh`). The joke is often spoken.
- Results tracking lives in `reports/history.csv`. Keep it up to date when the user reports views.
- **Brutal honesty, always.** The user's words: "If it's ass it's ass, don't lie." Give the real verdict on
  every clip, edit, title and idea, including their own requests, first and without cushioning. See
  "Brutal honesty" in the clip-coach skill.
