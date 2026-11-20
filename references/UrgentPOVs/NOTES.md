# UrgentPOVs: style study (Nov 20, 2026)

**What this is based on, honestly:** the channel's full Shorts list (229 videos: IDs, titles, view counts, pulled
with yt-dlp) and the **cover frame of each of the 20 study videos** (10 most viewed + 10 latest), several at full
720×1280. The videos themselves could not be downloaded in the cloud session: YouTube answers that machine with its
bot-check page. So everything about **timing, caption pace, animation, tracking, masking, sound and cuts is still
unmeasured.** Run `python3 tools/fetch_references.py --ids-file references/UrgentPOVs/ids.txt` on your own computer,
then `python3 tools/study_reference.py references/UrgentPOVs/` for the frame-by-frame part.

## The 20 videos

| # | Views | ID | Title | Cover shows |
|---|---|---|---|---|
| T1 | 94M | Sc3n3oXwfQs | "One Round Every Two Seconds" 🤔 | `Shooter:` *Broke the rules* (italic) + `Narrator:` he know.. ; band layout |
| T2 | 64M | WnBQMCKjxis | Trying the Sterling Sub! | `Soldier:` That's cool. ; band layout |
| T3 | 45M | _omSI575zu0 | Tank Commander Realizes How SLOW His Loader is! | `Commander:` Let's go! x2 ; band layout |
| T4 | 40M | 0mKOd94KYFg | SIG P320 Discharge in Holster! | `Other Student:` Yep. ; band layout |
| T5 | 36M | KKumx-CZItU | Finger Popping a Howitzer! | red italic *~4,000 lbs recoiling* (stat callout, no tag) ; band |
| T6 | 30M | LaKnxzGaXnQ | When Marines Get BORED! 😂 | red *TANK* label over one Marine who is **cut out with a white glow** (subject highlight) |
| T7 | 29M | R8xibhyoSSY | American Marine POV Training! | `US Marine:` you're good to go- ; band |
| T8 | 27M | p-Z7CYVrnkc | Forky Promoted to Commander! 🤣 | `Narrator:` squad gets bored.. + `Forky:` *Enters Room* (an object gets a speaker tag) |
| T9 | 27M | hbRlCWMsx60 | Soldier Throws TOO EARLY! | `Instructor:` I didn't + small italic note (Really mad) ; band |
| T10 | 25M | U1PKkWMIPcY | Steak Breakfast in the Army! | `Superior #2:` Boom! placed beside the speaker (top-left) |
| L1 | 266K | SpyX4ZnCGk4 | Young Prodigy SMOKES Their Stage! 😳 | `Narrator:` He was about + unboxed italic label *Time: 10:33* |
| L2 | 5.7M | sSxDGFiYolw | Deployed Life Be like.. 😂 | `Soldier #2:` missiled AGAIN" + note (Last thing you wanna hear) |
| L3 | 729K | xzch9VghPbw | C-RAM Intercepts Drone! | `Narrator:` an incoming drone |
| L4 | 249K | tz44W3zFpbg | Go Airborne They Said! 😂 | `Narrator:` they said.. |
| L5 | 9.5M | JCJkBFmGj2Q | He Thinks This is Warzone! 😂 | `Paratrooper:` I don't know what I'm doing |
| L6 | 4.9M | 0wiMzHx-GdA | Stealth Bomber Flyover! | `Spectator #2:` LOOK AT IT! |
| L7 | 581K | ZY0Nca_gvwA | Watching a C-17 Airdrop! | `Narrator:` parachute rigger's + unboxed label *Drop 1/4* |
| L8 | 4.6M | YUjuYlmpYLA | Student Becomes Drill Sergeant! 😂 | `Narrator:` He really didn't + `Context:` (Drill sergeant let him take over) |
| L9 | 12M | oHKlHdsy8n8 | Army Vet CALLS OUT "Navy Seal"! | `Narrator:` This veteran |
| L10 | 7.3M | bIgX99kEONs | Their LAST Meal! 😳 | `Soldier:` How's your |

Channel: 229 Shorts, median 368K views, 26 videos ≥10M, 88 ≥1M, 98 under 200K. The top 50 videos hold 88% of all views.

## Captions: what they look like (calibrated, now `"style": {"preset": "urgent"}` in render_edit.py)
- **Sentence case**, not all caps. Open Sans (regular weight), white, ~84px on a 1080-wide frame.
  **CAPS only for the shouted/stressed word**: "missiled AGAIN", "LOOK AT IT!".
- **Translucent dark box** (~65% black) hugging each line tightly. Not the solid black ArmoredPOVs box.
- **Speaker tag** in coloured text on its own small translucent box, centred right on top of the line, no gap.
  The tag names the person by role, numbered when there are several: `Soldier:`, `Soldier #2:`, `Superior #2:`,
  `Other Student:`, `Spectator #2:`, `US Marine:`, `Paratrooper:`, `Instructor:`, `Commander:`. **Objects get tags too**
  (`Forky:`). Each speaker keeps one colour (green / blue / yellow-orange); **`Narrator:` is always red; `Context:` is orange.**
- **Speech is captioned verbatim in 2-5 word chunks** that cut mid-sentence ("He was about", "How's your",
  "parachute rigger's", "This veteran"), with `..` for trailing off, `-` for cut-off speech ("you're good to go-"),
  `x2` for repeats ("Let's go! x2").
- **Italic in asterisks = action or stat**, sentence case: `*Broke the rules*`, `*Enters Room*`; red italic for a
  number that makes the clip impressive: `*~4,000 lbs recoiling*`; red caps for a nickname label: `*TANK*`.
- **Note line**: small italic lime/yellow text right under a line, in brackets, the editor's aside:
  `(Really mad)`, `(Last thing you wanna hear)`.
- **Context line**: `Context:` tag + italic bracketed sentence explaining what the viewer can't see:
  `(Drill sergeant let him take over)`. Same size as speech.
- **Unboxed info labels**, small white italic, top-left: `*Time: 10:33*`, `*Drop 1/4*` (counters, timers).
- **Placement**: narrator and context lines sit centred around mid-frame; a speaker's line sits **beside that
  speaker** (`Superior #2:` top-left next to his face, `Instructor:` next to the instructor). Never on faces in the covers.

## Why they do it (reading the covers against the view counts)
- **Narrated reposts are the current format.** 7 of the 10 latest covers show a `Narrator:` line against 2 of the top 10.
  The narrator explains the clip ("an incoming drone", "parachute rigger's", "This veteran") so a civilian follows it.
  This is the same move as your voiceover rule, and it confirms the VO plan.
- **Every spoken word is on screen.** Most viewers scroll muted; the tag tells them *who* is talking, which matters in
  crowded military clips. Colour per speaker lets you follow a back-and-forth without reading the tags.
- **The note/context lines carry the joke or the stakes** the footage can't: (Really mad), (Drill sergeant let him take over).
- **Horizontal sources go in the blurred-band layout** (most of the top 10, older uploads); vertical sources run full frame
  (most of the latest).
- **Subject highlight** (T6): one person cut out with a white glow, everyone else normal, plus a red label. Used to
  point at *who* the joke is about in a crowd. Seen once in 20 covers.

## Titles (all 229)
- 96% contain "!", 67% have an ALL-CAPS word ("SMOKES", "SLOW", "TOO EARLY", "BORED", "CALLS OUT", "LAST").
- Only 3% start with "When". Pattern: **[Subject] [VERB/claim]!** e.g. "Tank Commander Realizes How SLOW His Loader is!".
- 22% have an emoji (😂 32, 😳 9). Median views **1.8M with an emoji vs 280K without**. That may partly reflect *when*
  emoji were used (recent uploads with credit tags), so treat it as a lead, not proof.
- 26% credit the source in the title: `(TT: @handle)` / `(YT: @handle)`, mostly on recent uploads.

## Still unknown until the videos are studied
Caption timing and pace, whether captions animate or track, how often they mask, cut rhythm, zooms, B&W, SFX and music,
narrator voice and placement, video length, where the payoff lands.
