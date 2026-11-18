---
name: make-short
description: Turns a raw military / airsoft / POV clip into a finished, upload-ready Short in the AirHard / ArmoredPOVs / Combatful style, with the cut, captions placed beside the action, captions that track moving people or objects, text masked behind a subject, B&W / punch-in / boom on the payoff, blurred-band framing, watermark and -14 LUFS sound. Use when the user sends a raw clip and wants the full video made (not just advice).
argument-hint: <clip path in clips/> [notes: what happens, who says what, handle for the watermark]
---

# Make Short: raw clip in, finished Short out

You are the user's editor. They send a raw clip (`$ARGUMENTS`). You deliver `reports/<clip>/final.mp4`
at 1080x1920, ready to upload, plus the title and the one voiceover line. Work through every step;
**look** at every image a step writes (contact sheets, probe sheet, QA sheet) before deciding anything.

Read before you start (don't work from memory):
- `references/STYLE_PROFILE.md`: **measured** from the competitors' own videos by `tools/study_reference.py`
  (caption position, size, timing, how often and when they track and mask). If it exists, its numbers
  override the defaults in this skill and in `techniques.md`. If it doesn't exist yet, say so once in your
  reply: the tracking/masking choices are then this skill's defaults, not measured competitor behaviour.
- `techniques.md` (this folder): when to track, when to mask, caption placement, the edit-plan fields.
- `.claude/skills/clip-coach/caption-voice.md`: how captions must read. Run every caption against it.
- `.claude/skills/clip-coach/hook-library.md` (pacing templates, SFX, title formula) and `scoring.md`.

House rules (from the user, never break them):
- **Brutal honesty first.** Open with the score and verdict in plain words. If the clip is weak, say "this is
  weak" in the first line, then make the video anyway, because they asked for it.
- **No slow motion on payoffs.** Export **1080x1920** (the renderer's default; never lower).
- **One transformative voiceover line** in every video (`clip-coach/voiceover.md` section 0): a rule line
  before the payoff or a "why" line after it, placed in a quiet gap, never on the payoff.
- Never put B&W on a flash / explosion payoff (switch back to colour right before it). Minimum caption time
  is about 0.6s. Boom on the payoff only. No audio hole longer than about 1s.

---

## Step 0: Tools ready?
```bash
python3 -c "import cv2, mediapipe, rapidocr_onnxruntime" 2>/dev/null || bash tools/setup_vision.sh
python3 -c "import faster_whisper" 2>/dev/null || bash tools/setup_asr.sh
```

## Step 1: Watch and listen (clip-coach Steps 1-3)
```bash
python3 tools/clip_analyzer.py "<clip>" --mode raw --out reports
python3 tools/transcribe.py "<clip>" --out reports
```
Read `sheet_overview.jpg`, `sheet_hook.jpg`, `sheet_payoff.jpg` and the transcript. Then decide:
the payoff (source second), the trim-in, what to cut, the format (comedy 5-10s / story 20-50s), the hook type.
Score it with `scoring.md` and write the verdict line now. Never caption a word you're not sure you heard.
If the two transcription passes disagree on a word that goes on screen, ask the user (one question, both readings).

## Step 2: Stage A, the cut and the framing
Write `reports/<clip>/edit_plan.json` with the **structure only**: `source`, `segments` (source seconds;
jump-cut dead air, start already moving, hard-cut ≤2.5s after the payoff in comedy), `style.band_aspect`
(0.74 unless the profile says otherwise; full-frame vertical sources: omit it), `zooms` (small punch-in on
the payoff, optional slow push in the build), `bw` (payoff window, not on flashes), `sfx` (boom on the payoff,
meme SFX from `assets/sfx/` only where `hook-library.md` says), `bleeps`, `watermark` (ask for the handle if
you don't know it; never invent one). Then:
```bash
python3 tools/render_edit.py reports/<clip>/edit_plan.json --base-only
python3 tools/scene_probe.py reports/<clip>/base.mov --fps 3
```
**Look at `probe_sheet.jpg`.** It shows every person, face and object with its box in output pixels
(1080x1920, edited seconds) and shades the bands where a caption fits without covering anyone.
All x/y/box numbers you write from here on come from this sheet and `probe.json`.

## Step 3: Captions, tracking, masking
Write the captions (caption-voice rules: ~70% literal `*ACTION*`, attitude only on the payoff and the last line,
`ROLE:` tags, red italic punchline, `..` endings, 1-4 words, 2-4 word chunks for speech). Then for each caption decide,
using `techniques.md` (or the profile's measured rates):
1. **Where:** beside the person speaking/acting, in a free band from the probe, never on a face, inside the safe
   area (y 170-1600, clear of the right-side buttons). Several speakers → several captions, each beside its owner.
2. **Static or tracked:** track it (`"follow"`) when its subject moves more than ~8% of the frame width while it's
   on screen (walking soldier, moving vehicle, a thrown object) or the camera pans across the subject. Otherwise static.
   A marker (red circle + arrow) on a moving thing always tracks.
3. **Masked or not:** at most ONE masked caption per video (`"behind"`), and only the title-style kind: big text
   (size 120-200) in the hook or on a reveal, with a clear foreground subject crossing its lower part. Never mask the
   punchline or a speech caption (legibility beats style).

Add the `tracks`, `masks`, `captions`, `markers`, `header` fields (formats in `techniques.md`) and render:
```bash
python3 tools/render_edit.py reports/<clip>/edit_plan.json      # stage A is cached, only captions re-render
python3 tools/qa_sheet.py reports/<clip>/edit_plan.json
```

## Step 4: QA, then fix and re-render (loop until clean)
Open `qa_sheet.jpg` (and `_2`, `_3`...). For every tile check, and fix in the plan:
- A caption on a face or on the action → move it (another free band, `anchor: below/above`, or x/y).
- A tracked caption that drifts off its subject, or `render_edit.py` warned `lost ... %` → move the track's `box` to a
  more textured, tighter part of the subject (torso / helmet, not a blank wall), or make that caption static.
- A masked caption that is unreadable (more than ~40% of its letters covered at its start, or the readable part spells
  something else, like "ERO") → move/resize the text so the subject covers only its lower part or one end, or drop the mask.
- Text smaller than ~50% of the width on main captions, touching the bottom red line or the right button column.
- Payoff frame: B&W + punch-in + boom land together; flash payoffs stay in colour.
Then measure the export:
```bash
python3 tools/clip_analyzer.py reports/<clip>/final.mp4 --mode edited --out reports --payoff <edited payoff s>
```
Fix what it flags (static stretches, tail length, payoff timing). Two QA rounds is normal; don't deliver after zero.

## Step 5: Voiceover line
Write the ONE line (rule line before the payoff, or "why" line after it) with its exact edited-time slot in a quiet
gap. If the user has a recording or TTS take, put it in `reports/<clip>/vo_plan.json`, run
`python3 tools/vo_mix.py check` then `mix` (the renderer mixes it when `vo_plan` is set → `final_vo.mp4`).
If there is no audio for it yet, render without it and give them the line + timestamp to record, and add its
caption (`NARRATOR:` tag, 2-4 word chunks) to the plan so the captions are already in place.

## Step 6: Deliver
In chat, short and skimmable:
1. **Score + verdict** (one line, honest).
2. The video: `reports/<clip>/final.mp4` (or `final_vo.mp4`), length, and send it with SendUserFile.
3. **3 titles** ("When [Role] ..." format, never the outcome), first one recommended.
4. **VO line** + where it goes (if not mixed in).
5. **What I did** as a short edit list (time → caption / effect / tracked / masked), so they can tweak it in their editor.
6. Anything you weren't sure of (a misheard word, a guessed handle, tracking that needed a fallback).
Append the clip to `reports/history.csv` (clip-coach Step 7) with `vo_style` filled in.

## When the user sends feedback
Change the plan, re-render (stage A cache makes caption-only changes fast), re-run the QA sheet, look at it, deliver.
