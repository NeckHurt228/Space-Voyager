# Clip Coach workspace

This repo is an editing assistant for military / airsoft POV clip Shorts.

- When the user shares a clip (file in `clips/` or a URL) or asks about hooks, titles, pacing or
  whether a clip is worth posting, use the `clip-coach` skill (`.claude/skills/clip-coach/`).
- When the user sends a raw clip and wants the **full video made**, use the `make-short` skill
  (`.claude/skills/make-short/`): it renders the finished Short with tracked captions and masking, and checks its own
  render frame by frame. Otherwise the user's default applies (clean cut + step-by-step edit guide).
- `references/STYLE_PROFILE.md` (when present) is measured from the competitors' own videos by
  `tools/study_reference.py`. Its numbers beat the written defaults on caption position, size, timing, tracking and masking.
- Measure clips with `python3 tools/clip_analyzer.py <clip> --mode raw|edited --out reports`
  and always look at the contact sheets it writes before judging content.
- Always transcribe the audio too: `python3 tools/transcribe.py <clip> --out reports`
  (first run: `bash tools/setup_asr.sh`). The joke is often spoken.
- Results tracking lives in `reports/history.csv`. Keep it up to date when the user reports views.
- **Brutal honesty, always.** The user's words: "If it's ass it's ass, don't lie." Give the real verdict on
  every clip, edit, title and idea, including their own requests, first and without cushioning. See
  "Brutal honesty" in the clip-coach skill.
- `CLIP_CHECKLIST.md` is the user's plain-language guide to picking clips. Keep it consistent with
  `scoring.md`, and add new clips to its examples table when they teach a clear lesson.
- The user **must** add ONE transformative voiceover line to every video (a rule line before the payoff, or a "why" line
  after it). See `voiceover.md` section 0. Always deliver it with exact placement in a quiet gap.
- **User preferences:** no slow motion on payoffs (the user disliked it on the Rangers flashbang). The user often edits
  videos themselves: then deliver a clean cut plus a step-by-step edit guide, not a rendered edit.
- **Export:** the user wants **4K (2160×3840) 60 fps** finished videos (Nov 18). Never below 1080×1920 (the user is testing whether 720p exports caused 3 posts to stall at
  1.5–3k). Note: the files the user uploads here are often shrunk copies, so never infer their posted resolution from them.
