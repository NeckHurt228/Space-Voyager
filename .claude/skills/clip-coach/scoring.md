# Scoring rubric (100 points)

These are heuristics drawn from the benchmark set, not a view predictor. Calibrate them with
`reports/history.csv` once real results come in (see SKILL.md, Step 7).

## A. Content: 60 points (judged by the agent from the contact sheets, notes or vidIQ watch)

| # | Item | Pts | Full marks when… | Zero when… |
|---|---|---|---|---|
| A1 | **Payoff / twist** | 15 | There is one unmistakable moment: a fail, reveal, clever play, or a rule breaking | It's just "something cool" or informational (the "Chops Wood" / "How Much Weight" type) |
| A2 | **Stakes in second 1** | 10 | Danger, embarrassment, conflict or a rule about to break is visible immediately | Calm setup; the stakes only become clear later |
| A3 | **Understandable with the sound off** | 10 | A non-fan gets the situation in under 2s from the visuals plus one caption | It needs context, in-jokes or long dialogue to understand |
| A4 | **Hook-type fit** | 10 | Clearly one of the proven types in `hook-library.md` (best: real world enters the game, danger→fail, sportsmanship, reunion, rule-break) | Fits none of them |
| A5 | **Emotional intensity** | 5 | A strong laugh, wince, "aww" or anger | Mild "huh" |
| A6 | **Comment-argument potential** | 5 | Viewers will take sides (cheating, Karen, kids, "would you have shot", "was that fair") | Nothing to argue about |
| A7 | **Novelty** | 5 | The viewer has never seen this exact thing | A repost of a clip the niche already used heavily |

Partial credit is fine. Give a one-line reason for each score.

## B. Structure: 40 points (measured by `tools/clip_analyzer.py`)

| # | Item | Pts | Target (comedy / story) |
|---|---|---|---|
| B1 | Length (in raw mode, after the recommended trims) | 8 | 5–10s / 20–50s |
| B2 | Hook energy in second 1 (motion + loudness) | 8 | Moving and loud from frame 1 |
| B3 | Payoff timing (% of runtime) | 8 | 25–60% / 55–85% |
| B4 | Tail after the payoff | 6 | ≤2.5s / ≤6s, ending on the reaction |
| B5 | Payoff punch (absolute jump in loudness or motion) | 4 | +8 dB or a big visual jump |
| B6 | Dead air / static stretches (edited mode) | 6 | None |

In **raw** mode, B4 and B6 get full marks because they're fixable by trimming. The analyzer
prints them as trim instructions instead. In **edited** mode they're scored for real.

If the analyzer's payoff candidate is the wrong moment (check `sheet_payoff.jpg`), re-score B3
and B4 using the correct timestamp, and say so.

## Tiers

| Total | Tier | Verdict |
|---|---|---|
| 80–100 | Breakout candidate | **POST IT**. Put the effort into the title and hook |
| 65–79 | Solid | **POST IT** after the plan's fixes |
| 50–64 | Average | **FIX THEN POST**, only if the fixes raise the content items; editing alone won't save it |
| < 50 | Weak | **SKIP**. Find a clip with a real payoff |

**Hard rule:** if A1 (payoff) is below 6, the verdict is SKIP regardless of the total. In the
benchmark set, no clip without a payoff broke out, whatever the editing.
