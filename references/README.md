# Reference videos (competitor study)

Put competitor Shorts here, one folder per channel, and the study tool measures them frame by frame:

```
references/
  AirHardReal/   ArmoredPOVs/   combatful/      <- videos (git-ignored, private study only)
  _study/<channel>/<video>/study.md, timeline.json, sheet_*.jpg   <- per-video results (text is committed)
  STYLE_PROFILE.md / .json                                        <- the per-channel summary the agents read
```

## Get the videos (on your own computer: YouTube is blocked in cloud sessions)

```bash
pip install -U yt-dlp
python3 tools/fetch_references.py @AirHardReal @ArmoredPOVs @combatful --top 25
```

It downloads each channel's 25 most-viewed Shorts plus its 5 newest, at 1080p or higher.

## Study them

```bash
bash tools/setup_vision.sh                     # once
python3 tools/study_reference.py references/   # studies every new video, then writes STYLE_PROFILE.md
```

Then commit `references/STYLE_PROFILE.md`, `.json` and the `_study/**/study.md` + `timeline.json` files (the videos and
sheets stay local). From then on `/make-short` uses the measured numbers instead of its defaults.
