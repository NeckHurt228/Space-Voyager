# Hook library, title formulas, caption spec and pacing templates

## 1. Hook types (ranked by the best result in the benchmark set)

| Type | Best example | First-second recipe |
|---|---|---|
| **Fake problem → reveal** | Graduation surprise, 72.9M | Open on the problem being announced ("we have a small problem…"), with a header describing the place |
| **Real world enters the game** | Homeowner thinks airsoft gun is real, 66.4M | Open on the outsider (homeowner, police, Karen, trespasser) reacting, not on the game |
| **Morality / sportsmanship** | Enemy shows true sportsmanship, 55.1M | Open on the moment of choice: the enemy has the shot, or the opponent is down |
| **Reunion / emotional surprise** (**proven on the user's channel: about 100K on a new channel**) | They never thought they'd see each other, 54.6M | Open on the person who doesn't know yet, with a caption describing them (`*HASN'T SEEN HIM IN 4 YEARS*`) |
| **Clever play / skill** | Spidey senses, 53.1M | Open on the threat approaching, so the viewer sees it before the player reacts |
| **Danger setup → fail** | Soldier breaks physics, 26.6M | Open mid-throw or mid-shot, with a tense drone |
| **Object given a personality** | C-RAM "thinks about it", 26.2M | Give a machine or weapon a `ROLE:` tag and inner thoughts |
| **Breaking a known rule** | Royal Guard breaks character, 38.4M | State the rule in the header or first caption, then show someone pushing it |
| **Comment-argument bait** | Kid burning patch (11.5K comments) | Open on the act that viewers will judge |
| **Misdirect** | Wrong gun, 18.1M | Serious action + goofy music (or the reverse), so the viewer senses a twist coming |
| **Skit / staged comedy** (**proven on the user's channel: 40K+**) | User's own skit | The joke is clear within 2–3s, one idea with a twist at the end; it lands for soldiers and civilians |
| **Relatable service humour** (a complaint, chant or one-liner about military life) | Combatful: "Military Caught Sleeping On Job" 15.4M, "Bro Is Not Getting Payed Enough" 4.8M | Open on the first spoken line. If it's a list or acronym, show a progress tracker (`A R M Y`) so viewers stay for the last item. Veterans comment their own versions |

## 2. Title formulas
**The user's channel standard: every title starts with "When".**
Template: `When [Role] [specific, slightly dramatic action/situation].. [1 emoji] #military #usa`.
The format only works with a specific action ("Breaks Physics" 26.6M vs "Has Too Much Fun" 60K, same format). Hint at the
situation, never the result, and never reuse a title. An ironic title can usually be rewritten into the format
("How Rangers Clear Buildings" → "When Rangers Clear A Building.."). Exception worth A/B testing: Combatful-style
statements for reunions ("He Hasn't Seen His Brother In 4 Years...").

- **Comedy:** `When [Role] [specific dramatic verb + object]..` + 1 emoji (💀 😭) + `#military #usa` (or `#airsoft #fail`)
  - Good: "When Soldier Breaks Physics..", "When C-RAM Goes Too Far 💀..", "When Airsofter Brings Wrong Gun.."
  - Bad: "When Soldier Has Too Much Fun..", "When Soldiers Get Creative.." (vague; the payoff can't be predicted) → 60–500K
- **Story:** `[Superlative] [Event] Ever...` / `He Hasn't Seen His [Relation] In [N] Years...` / `[Person] Makes [Authority] [Break/Do X]`
- **Real-world crossover:** `When [Outsider] Thinks [Game thing] Is Real…`
- Rules: give the setup, never the result. Be specific and slightly dramatic. ≤ 60 characters. End with `..`/`…`.
  Don't reuse an identical title twice on your channel.
- A pop-culture label on a skill clip works: "When John Wick Tries Airsoft…" got 27.9M from a 5s clip.

## 3. Caption spec (house style)
**Before writing any caption text, read `caption-voice.md`.** It has the competitors' verbatim text boxes,
the 70% literal / 30% attitude rule, and the banned "copywriter" vocabulary. This section covers only the look.
- **Position:** next to whoever is speaking or acting (several captions can be on screen at once, one per person). Default is just below the subject's head or chest; action/context captions go near the top of the band. Keep clear of faces, the bottom ~15% and the right-side button column.
- **Role tag:** small Montserrat Bold, uppercase, **coloured text on its own black box**, sitting directly on top of the main box: `SOLDIER:` green, `POV-SOLDIER:` / `AIRSOFTER:` / `SOLDIER 2:` teal, `C-RAM:` / `FIRST SERGEANT:` yellow. Repeat the tag on every spoken line.
- **Main text:** Montserrat ExtraBold, white, on a **solid black rectangle** with tight padding (no outline, no shadow). Speech is typed as spoken (`Marine?`, `The Word..`, `A is for Army`). Actions and thoughts are UPPERCASE in asterisks (`*THROWS GRENADE*`).
- **Colour code:** white = speech and neutral actions. **Red italic with white asterisks = the punchline/thought** (`*SH*T WRONG GUN..*`, `*THINKS ABOUT IT..*`). Yellow small text on black = a side note (`(suspicious)`).
- **Pace:** a new line every 0.5–1.0s in comedy. Word-by-word synced captions for dialogue in story clips.
- **Escalation:** repeated beats become `NO...` → `NOO- X2` → `NO! X3`.
- **Endings:** trail off with `..` on the last caption (`*ENEMY IS COOKED..*`, `DAMN..`).
- **Header:** rare at ArmoredPOVs; Combatful uses one for story clips (`*AT GRADUATION CEREMONY*`). Use the same black-box style.
- **Framing:** a sharp centre band (about 0.74 width:height), with a blurred copy of the same frame filling the top and bottom. Captions appear and disappear on hard cuts, with no pop-in animation.
- **Watermark:** `@yourhandle`, Montserrat SemiBold, white with a soft shadow, about 50px, at the bottom centre (y≈1785 of 1920), all the way through.
- These are the defaults in `tools/render_edit.py`. They were calibrated by rendering competitor captions side by side with their real frames (via `vidiq_get_images`, which is free).

## 4. Sound palette
**Lessons from the user's posted videos (audio-checked):**
- The hit sound (boom) goes **on the payoff only**. Both posted videos put their loudest boom on a setup beat
  (reunion at 4.5s, skit at 1.5s) and left the payoff silent (the skit's freeze).
- **No audio hole longer than about 1s.** The skit had 3.2s at about -30 dB in the middle: keep the original sound or add a quiet bed.
- **Reunions:** start soft music early (about the midpoint) and swell it at the reveal. The posted reunion only brought music in for the last 2.8s.
- **Never put the flash/explosion payoff in black and white.** Switch back to colour right before it (the user's Rangers edit turned the orange flash into a grey smudge).
- **Minimum caption time is about 0.6s** (3 words). The user's Rangers edit had 0.3s captions on the funniest beat (the kick).
- **Export at 1080×1920 minimum (4K if the editor allows), 30/60fps, High/Recommended bitrate.** The user's last 3 posts
  (720p exports) stalled at 1.5–3k; export resolution is being tested as a cause. Never deliver or recommend 720p.
- **Export at about -14 LUFS, true peak -1 dB.** Both posted videos peaked at 0.0 dBFS, and the skit sat at -11.8 LUFS.
Sound effects the user supplies live in `assets/sfx/` and plug into the edit plan as
`{"type": "file", "path": "assets/sfx/fahh.mp3", "at": <payoff s>, "hit": <attack s into the file>, "trim": [0, 1.4], "gain_db": 12}`.
Line the **attack** (not the file start) up with the payoff, and keep it about 1–2 dB louder than the loudest speech.
When a meme SFX lands on a censored word, it can replace the beep: use `{"start": a, "end": b, "tone": false}` in `bleeps`.
- `fahh.mp3`: the "FAHH" reaction groan. Attack at 0.14s, body to about 1.0s, quiet tail to 2.3s. It needs about +12 dB.
- `vine_boom.mp3`: the vine boom (1.3s, hit at 0.05s, loud: -8.9 LUFS). Use it on a censored slur or a sudden reveal. Trim to about 0.9s with `gain_db: -6` to sit level with the other meme sounds.
- `awkward_moment.mp3`: the user's "awkward moment" meme sting (1.5s, attack at 0.0s, fast decay). Use it at the very start; about +7 dB matches FAHH's peak, and it doesn't mask speech because it decays fast.
- `crickets.wav`: synthesized crickets (a fallback, not the user's preferred awkward sound) (2.4s). Under speech, about +8 dB is the most before it starts masking words; check with `transcribe.py` on the first seconds after rendering.
- **Fonts:** set `style.font` / `font_italic` / `font_tag` / `font_watermark` to any family in `assets/fonts/`. The defaults are Montserrat (the competitor match). `FigtreeB`/`FigtreeBI` is the free stand-in for Proxima Nova Bold, which is commercial: if the user supplies the licensed `.otf`, drop it into `assets/fonts/` and use its family name.
| Moment | Comedy | Story |
|---|---|---|
| Hook (0–1s) | Tense drone, or a goofy track to misdirect, or the original sound if it's loud | Original audio (dialogue), with no music yet |
| Build | Drone continues, or silence for 0.3s just before the payoff | Original audio + very soft music |
| Payoff | Bass hit / boom + meme voice ("what the…") + picture to B&W | Music swells, crowd audio up |
| Reaction / end | Laugh clip or cartoon laugh, cut mid-sound | Music peak on the hug or reveal, cut |

## 5. Pacing templates

### Comedy / fail: 7s template
| Out time | Beat | What happens |
|---|---|---|
| 0.0–0.8 | HOOK | Already mid-action. `ROLE: *ACTION*` (yellow). Tense or misdirect audio |
| 0.8–2.0 | BUILD | 1–2 caption swaps (`*WAITING..*`, `*AIMS*`). Slight push-in |
| 2.0–2.5 | PAYOFF (≈30–40%) | Twist frame. B&W/desaturate + bass hit + red caption + punch-in, all at once |
| 2.5–5.5 | REACTION | Meme voice / reaction audio, 1–2 more captions (`DAMN..`), optional overlay (maths formulas, emoji) |
| 5.5–7.0 | CUT | Hard cut mid-laugh. No outro, no "subscribe" card |

### Story / emotional: 30–45s template
| Out time | Beat | What happens |
|---|---|---|
| 0–2s | HOOK | Problem or tension stated in dialogue + header. Speaker tag + word-by-word captions |
| 2–10s | DISCOMFORT | Punch-in on faces. Mood captions (`*DISSAPOINTED*`, `*NERVOUS*`) every 2–3s |
| ~55–65% | MINI-PAYOFF | First crack: `*TRYING NOT TO LAUGH*`, a voice over the speakers, someone stands up |
| 65–85% | PAYOFF | The reveal / hug / break. Music swells, double punch-in, SFX |
| last 2–5s | REACTION | Crowd reaction, `*REUNION HUG*` / `*VICTORY WALK*`, hard cut |

## 6. Retention killers to remove
- Any calm first frame (camera settling, someone about to start talking).
- Two or more seconds where nothing changes on screen: no cut, caption swap, zoom or new sound.
- Explaining the joke after the payoff.
- Showing the payoff in the hook (spoiling it). Show the *stakes*, not the result.
- Outros, end cards, "follow for more".
- A title that reveals the outcome.
