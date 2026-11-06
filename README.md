# Clip Coach

An AI editing partner for short-form military / airsoft POV clips, built on benchmarks from
**Combatful**, **ArmoredPOVs** and **AirHard**.

For each clip, it:
1. **Scores** the clip out of 100: 60 points for content (payoff, stakes, sound-off clarity, hook type,
   emotion, comment potential, novelty) and 40 for structure, measured from the video file. It then gives a verdict:
   POST IT / FIX THEN POST / SKIP.
2. **Builds the hook**: the trim-in frame, first caption, opening sound and 3 ranked titles.
3. **Writes a pacing plan**: a second-by-second edit list (captions + colours, SFX, effects, where
   the payoff lands, where to hard-cut), plus a `captions.srt` you can import into your editor.
4. **Writes and mixes a voiceover**: funny, human-sounding scripts in one of 5 personas (inner monologue,
   deadpan narrator, buddy commentator, object voice, drill sergeant). It checks the timing so the
   voice never covers the payoff, generates the audio with vidIQ's ElevenLabs voices (or uses your own
   recording), and mixes it in with ducking and Shorts-level loudness.
5. **Checks your finished edit** and lists what slipped.
6. **Learns from results**: it logs every clip in `reports/history.csv`. After 10+ posted clips with
   views, it tells you which rubric items actually predict *your* views.

## Use it

With Claude Code in this folder:

```
/clip-coach clips/my_clip.mp4  the soldier throws the grenade and it bounces back into the trench
```

```
/clip-coach https://www.tiktok.com/@someone/video/123...
```

```
/clip-coach review my edit: clips/my_clip_final.mp4
```

Put raw footage in `clips/`. Reports, contact sheets and captions go to `reports/<clip-name>/`.
Neither folder is committed to git.

## Listening to the clip

```
bash tools/setup_asr.sh                          # once: installs Whisper small (~250MB, checksum-verified)
python3 tools/transcribe.py clips/my_clip.mp4    # word-timed transcript, low-confidence words marked '?'
```

## The analyzer on its own

```
python3 tools/clip_analyzer.py clips/my_clip.mp4 --mode raw     # before editing
python3 tools/clip_analyzer.py clips/my_final.mp4 --mode edited # after editing
python3 tools/clip_analyzer.py clips/my_final.mp4 --mode edited --payoff 8.5  # if the punchline is spoken
```

It measures length, cuts, motion and loudness per 0.1s, dead starts, payoff candidates (the biggest
jumps in loudness and motion), tail after the payoff, and dead air. It also writes contact sheets of the
whole clip, the hook and the payoff. It needs `ffmpeg` and Python 3 with Pillow (`pip install pillow`).

## Voiceover on its own

```
python3 tools/vo_mix.py check reports/my_clip/vo_plan.json          # do the lines fit their slots?
python3 tools/vo_mix.py mix clips/my_edit.mp4 reports/my_clip/vo_plan.json
```

Give it one voice take with all the lines separated by pauses (TTS output or your own recording).
It splits the take, places each line at its time, lowers the clip's own sound under the voice
by 12 dB, and normalises the result to -14 LUFS.

## Rendering the edit

```
python3 tools/render_edit.py reports/my_clip/edit_plan.json
```

It renders a 1080x1920 Short in the competitor style: jump cuts, bleeps, punch-ins and shake, black and white on the payoff,
ArmoredPOVs-style captions (Montserrat on black boxes, coloured role tags, red italic punchlines), a centre band with blurred bars, a bass-hit SFX, and -14 LUFS loudness. It also mixes in the
voiceover when one exists.

## Files
- `.claude/skills/clip-coach/SKILL.md`: the agent's workflow
- `.claude/skills/clip-coach/benchmarks.md`: the research data (top videos, second-by-second breakdowns)
- `.claude/skills/clip-coach/scoring.md`: the 100-point rubric and tiers
- `.claude/skills/clip-coach/hook-library.md`: hook types, title formulas, caption style, sound palette, pacing templates
- `.claude/skills/clip-coach/voiceover.md`: VO personas, voices, humour and timing rules, pipeline
- `tools/clip_analyzer.py`: the measurement script
- `tools/vo_mix.py`: voiceover timing check and mixer
- `tools/render_edit.py`: renders the finished edit from an edit plan
- `tools/remove_overlay.py`: removes baked-in emojis, stickers or small text from a clip (needs `opencv-python-headless`)
- `assets/fonts/`: Montserrat (captions) and Anton fonts (SIL Open Font License)
- `tools/transcribe.py` + `tools/setup_asr.sh`: speech-to-text so the agent hears the clip
- `.claude/skills/clip-coach/caption-voice.md`: the competitors' verbatim captions and the caption-writing rules

Optional: connect vidIQ in Claude to analyse clips from URLs and to pull fresh benchmark data.
