# Clip Coach workspace

This repo is an editing assistant for military / airsoft POV clip Shorts.

- When the user shares a clip (file in `clips/` or a URL) or asks about hooks, titles, pacing or
  whether a clip is worth posting, use the `clip-coach` skill (`.claude/skills/clip-coach/`).
- Measure clips with `python3 tools/clip_analyzer.py <clip> --mode raw|edited --out reports`
  and always look at the contact sheets it writes before judging content.
- Results tracking lives in `reports/history.csv`. Keep it up to date when the user reports views.
