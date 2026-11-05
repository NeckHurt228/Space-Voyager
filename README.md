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
4. **Checks your finished edit** and lists what slipped.
5. **Learns from results**: it logs every clip in `reports/history.csv`. After 10+ posted clips with
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

## The analyzer on its own

```
python3 tools/clip_analyzer.py clips/my_clip.mp4 --mode raw     # before editing
python3 tools/clip_analyzer.py clips/my_final.mp4 --mode edited # after editing
```

It measures length, cuts, motion and loudness per 0.1s, dead starts, payoff candidates (the biggest
jumps in loudness and motion), tail after the payoff, and dead air. It also writes contact sheets of the
whole clip, the hook and the payoff. It needs `ffmpeg` and Python 3 with Pillow (`pip install pillow`).

## Files
- `.claude/skills/clip-coach/SKILL.md`: the agent's workflow
- `.claude/skills/clip-coach/benchmarks.md`: the research data (top videos, second-by-second breakdowns)
- `.claude/skills/clip-coach/scoring.md`: the 100-point rubric and tiers
- `.claude/skills/clip-coach/hook-library.md`: hook types, title formulas, caption style, sound palette, pacing templates
- `tools/clip_analyzer.py`: the measurement script

Optional: connect vidIQ in Claude to analyse clips from URLs and to pull fresh benchmark data.
