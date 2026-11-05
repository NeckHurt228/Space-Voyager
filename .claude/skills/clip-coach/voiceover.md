# Voiceover: funny, human, timed to the edit

**Be honest about this one:** none of the three benchmark channels use a narrator. They use short
meme voice clips ("oh my god, what the…") and captions. So voiceover is a *differentiator*, not a
proven formula. Log every VO video with its `vo_style` in `reports/history.csv` and compare its
views against non-VO videos once there are 5+ of each. Keep using a style only if it beats the
captions-only version.

## 1. Pick a persona (one per video)

| Persona | When it fits | Sounds like | vidIQ voice (ElevenLabs) |
|---|---|---|---|
| **Inner monologue** (first person, the soldier's thoughts) | Struggle, effort, fear, bad decisions | Tired, honest, a little desperate | Chris (charming, down-to-earth) · Will (relaxed) · Roger (laid-back) |
| **Deadpan narrator** (fake documentary, bone-dry) | Fails, absurd situations, slow realisations | Calm and serious about something stupid | Brian (deep, resonant) · Bill (wise, mature) · George (storyteller) |
| **Buddy commentator** (the friend watching, "bro…") | Clever plays, pranks, cooked moments | Disbelief, laughing under the words | Liam (social-media energy) · Charlie (energetic) |
| **Object voice** (the C-RAM / grenade / sandbag talks) | Machines, gear, weapons doing something | Sly, menacing or smug | Callum (husky trickster) |
| **Drill sergeant** (over-the-top authority) | Training, discipline, punishment PT | Loud and furious, but you can tell it's a bit | Adam (dominant, firm) · Harry (fierce warrior) |

The user's own cloned voice (shows `isCustom: true` in `vidiq_voiceover_list_voices`) or their
own recording beats all of these for sounding human. Offer it first if they have one.

## 2. Writing rules (the funny part)
1. **Say what the viewer feels, never what they see.** The picture already shows "he is running".
   The VO says the thing behind it: "If I stop, they give me another bag."
2. **Understatement beats exaggeration.** "He did not need to go that fast." is funnier than "HE'S SO FAST LOL".
3. **Specific beats generic.** "Day forty-seven." / "His third sandbag of the morning." Made-up specifics sell it.
   Don't invent real names, units or claims about real people.
4. **Formality mismatch:** a serious documentary tone for something dumb, or a casual voice for something dangerous.
5. **One idea per line; 3–8 words.** About 2.8 words per second. A 7s comedy clip holds **2 lines, 3 at most**.
6. **The last line undercuts.** End on a short, flat line ("Nobody asked him to.") and cut right after it.

## 3. Timing rules (the retention part)
| Beat | VO job |
|---|---|
| 0.0–0.3s | **Line 1 starts here.** It frames the situation or gives the stakes ("If I stop… they give me another bag."). No "so", no warm-up |
| Build | Silence or one short line. Let the clip's own audio breathe |
| **Payoff ±0.35s** | **No VO.** The payoff sound (bass hit, whoosh, meme SFX) gets this space alone. `vo_mix.py` flags any line that covers it |
| Right after the payoff | **The punchline line.** A reaction, understatement or deadpan observation |
| Last 0.5s | A hard cut right after the last word, or mid-laugh |

## 4. Making TTS sound human
- Use contractions everywhere: "he's", "can't", "didn't".
- Write pauses into the text: `...` gives a beat, a comma gives a breath, and a new line gives a longer pause.
- One filler at most per video ("uh," / "yeah," / "okay."). More sounds fake.
- Use sentence fragments: "Still running. Somewhere."
- Self-corrections work: "He's fast. He's... not that fast."
- Write numbers and acronyms the way they're said: "forty-seven", "M-R-E", "P-T".
- Don't use ALL CAPS or several exclamation marks; TTS overacts. Make the *words* carry the energy.
- Match the voice to the energy: deadpan → Brian/Bill; excitement → Liam/Charlie.

## 5. Off-limits
- "Guys", "wait for it", "you won't believe", "watch till the end": these are retention-bait phrases people recognise and skip.
- Explaining the joke after it lands.
- Slurs, punching down (disability, ethnicity), or jokes about real casualties. Never put VO on real combat
  footage where people are hurt or killed.
- Imitating a real, recognisable person's voice (celebrities, famous narrators). Use a *style* (deadpan
  documentary), not a person.

## 6. Captions with a voiceover
When the VO speaks, the caption **is** the VO text: word-synced, with the role tag in the persona's name
(`HIM (THINKING):`, `NARRATOR:`, `C-RAM:`). Action captions (`*FULL SEND*`) appear only in the gaps
between VO lines. Never show two different texts at once.

## 7. Production pipeline
1. **Write the plan** at `reports/<clip>/vo_plan.json`:
   ```json
   {"vo_file": "vo.mp3", "payoff": 4.2, "duck_db": 12,
    "lines": [{"at": 0.15, "text": "..."}, {"at": 4.6, "text": "..."}]}
   ```
   `at` and `payoff` are times in the **edited** video, not the source clip.
2. **Check timing:** `python3 tools/vo_mix.py check reports/<clip>/vo_plan.json`. Fix every flagged line
   by shortening the text or moving `at`.
3. **Generate the voice: one take for all lines.**
   - vidIQ: `vidiq_voiceover_generate` with the chosen `voiceId`, script = all lines joined with
     `"\n\n...\n\n"` (forces a clear pause the splitter can find). It costs 14 credits per video (under 1000 characters).
     Check `vidiq_balance` first. Poll `vidiq_job_poll`, then download the MP3 URL into `reports/<clip>/vo.mp3`.
   - Own recording: read all lines in one take with about a 1-second pause between them, then save it as `vo.mp3`/`.wav`.
   - Listen to the take before mixing (or ask the user to). If a line sounds robotic, rewrite it (shorter,
     more contractions, a `...`) and regenerate. Don't fix it in the mix.
4. **Mix:** `python3 tools/vo_mix.py mix <edited_video.mp4> reports/<clip>/vo_plan.json`
   It splits the take at its longest pauses, places each line at its `at`, ducks the clip audio
   by `duck_db` (12 dB default; 8 if the original audio is the joke, 14+ for loud music), keeps the
   payoff gap clean, and normalises to -14 LUFS. The video stream is copied as-is.
5. **Re-check:** run `clip_analyzer.py --mode edited` on the result. The hook energy in second 1 should now
   be higher, because the voice starts immediately.
