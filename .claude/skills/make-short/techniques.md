# Techniques: placement, tracking, masking, and the edit-plan fields

**Where these rules come from.** The placement rules come from the clip-coach research (7 competitor hits
broken down second by second, plus frame calibration against ArmoredPOVs covers). The **tracking and masking rules
are editorial defaults**: the competitors' videos have not been measured frame by frame yet (YouTube is blocked from
the cloud sessions this was built in). Once `references/STYLE_PROFILE.md` exists, its measured numbers win: how often each
channel tracks or masks, where in the video, at what size and height. Update this file to match it.

## 1. Placement (measured / calibrated)
- Captions sit **next to whoever is speaking or acting**, several on screen at once if several people talk.
  Default: just below the subject's head/chest; action/context captions near the top of the band.
- Never on a face, never on the action itself (the grenade, the fall, the hit). Use the probe's free bands.
- Safe area: y 170-1600 of 1920, x clear of the right button column (~x > 930 below mid-height).
- Main caption ~88px Montserrat ExtraBold on a black box; spans 50-70% of the width on the key lines.
- They appear and disappear on hard cuts. No pop-in animation (until the profile says otherwise).

## 2. Tracking: when a caption or marker follows something
**Track when** (any one):
- its subject **moves more than ~8% of the frame width** (≈90px) while the caption is up: a soldier running across,
  a vehicle, a thrown grenade, a drone;
- the camera pans/whips while the caption labels one person (a static caption would end up over the wrong person);
- it's a **marker** (red circle + arrow) pointing at something that moves. Markers on moving things always track.

**Don't track when**: the subject is roughly still (static text is easier to read); the move is a fast whip where
the tracker loses it (`lost` > 15% warning) — use a static caption or a cut instead; the caption is a header/context
line (`*AT GRADUATION CEREMONY*`) or the watermark.

**How**: anchor role/speech captions **above** the head (`anchor: "above"`) so they never cover the face; object
labels `below` or `above` whichever side has room. Track box = a tight, textured part of the subject (torso, helmet,
vehicle body), 80-250px, taken from `probe_sheet.jpg` at a frame where it's clearly visible (`at`). The tracker runs
backwards and forwards from `at`, so pick the clearest frame, not necessarily the first.

## 3. Masking: text behind a subject
The look: a big title word sits behind a person/vehicle, which passes in front of it. It reads as "produced" and
is strong in a **hook** or on a **reveal**. Costs legibility, so:
- **At most one masked caption per video.** Big text only (size 120-220), 1-3 words, title-like (`*CONTACT FRONT*`,
  `BRO IS COOKED`), not a speech caption and not the punchline.
- The subject covers **at most ~40%** of the letters at the moment the text appears, and the readable part must not
  spell a different word. Best: the subject overlaps the text's lower half or crosses one end.
- Needs a clear foreground subject separated from the background (person close to camera, vehicle). Small, distant or
  blurry subjects give a ragged cut: skip masking there.
- Subjects: `"people"` = everyone in frame (cleanest edges, use when only one person overlaps the text);
  `"person:<track>"` = only the tracked person (when several people are in frame); `"track:<track>"` = any tracked
  object, via a point segmenter (vehicles, weapons) — check its edge on the QA sheet, it can bleed into similar background.

## 4. Edit-plan fields added for this (all output pixels 1080x1920, edited seconds)
```json
"tracks": [
  {"id": "runner", "at": 2.4, "box": [430, 820, 180, 260]},
  {"id": "nade",   "at": 3.1, "point": [612, 905], "size": 90}
],
"masks": [
  {"id": "m1", "subject": "person:runner"}
],
"captions": [
  {"start": 0.0, "end": 1.4, "text": "*CONTACT FRONT*", "size": 170, "y": 640, "behind": "m1"},
  {"start": 1.5, "end": 3.0, "tag": "SOLDIER:", "text": "*SPRINTS*", "follow": "runner", "anchor": "above"},
  {"start": 3.0, "end": 4.2, "tag": "SOLDIER:", "text": "*THROWS GRENADE*", "x": 540, "y": 1180}
],
"markers": [{"start": 3.1, "end": 4.0, "follow": "nade", "r": 60}]
```
- `follow` + `anchor` (`above` | `below` | `center`) + optional `offset: [dx, dy]`; x/y are ignored while following and
  the caption is clamped inside the safe area.
- `behind: "<mask id>"`: the caption is drawn under the subject cut-out (feathered 3px edge, grown 2px).
  Mask options: `feather`, `grow`.
- `render_edit.py --base-only` renders just the cut/framing (`base.mov`) to pick numbers from; the full render reuses it
  while `source/segments/zooms/bw/shake/sfx/bleeps/style.band_aspect/grade/zoom_center` don't change.
- After a render, `reports/<clip>/tracks.json` has every track's path and `lost` share.
