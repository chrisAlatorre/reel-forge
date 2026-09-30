# The rubric: one ruler for their videos and ours

A short-form video is judged by one number the platform keeps and nobody shows you: **how much of
it people watch, and what they do at the end** (rewatch, save, send, follow). Every criterion below
is a cause of that number that can be seen in the file. The same rubric scores a reference video
from the platform and one of our renders, **with the same instrument** (`video-engine/scripts/watch.py`,
every frame from 0 to the last one, the transcript and the on-screen text). Scoring ours from a
frame strip and theirs from the app is not a comparison.

## How to score

1. Run `watch.py` on the file. Read **every** sheet in order, the transcript and the text track.
   A score given without seeing the last sheet is not a score: the ending is a third of the rubric.
2. Score each criterion 0-10 against the anchors. Write one line of evidence per criterion with the
   second it happens at (`"0.0 s: a hand opens a hotel curtain onto the jungle"`), never an adjective.
3. The total is the weighted sum, out of 100. Round to the unit.
4. Then the two lists that matter more than the number: **what it does that ours don't** and
   **what costs it points**. Each as a general technique, not as a fact about that place.

Anchors: **0** absent or harmful · **3** present but weak · **5** competent, forgettable · **7** good,
a viewer notices it · **9-10** the reason the video works.

## The criteria

### A. Hook — the first 3 seconds (25)

| # | Criterion | Weight | What a 9-10 looks like | What a 3 looks like |
|---|---|---|---|---|
| A1 | **Frame zero** | 8 | The very first frame already shows the best thing: motion in progress, a face mid-reaction, a scale nobody expects. It would stop a thumb with the sound off. | An establishing shot, a logo, a slow fade in, a static photo of the place. |
| A2 | **Promise in ≤ 2 s** | 9 | By 2 s the viewer knows what they get and why to stay: a text or line that opens a question, a number, a stake ("the hotel where the jungle is the wall"). | A title that names the place ("Lisbon ✨"), or nothing said until second 4. |
| A3 | **Open loop** | 8 | Something is withheld that only the end gives back: a countdown, a "wait for it", a question, a before-after. | Everything is shown in the first seconds; there is no reason to reach the end. |

### B. Retention — the middle (20)

| # | Criterion | Weight | 9-10 | 3 |
|---|---|---|---|---|
| B1 | **Pace that fits the format** | 6 | Shot length is chosen: fast montage (0.3-0.8 s) cut to the beat, or a few long held shots that earn their length; the pace **changes** at least once on purpose. | Every shot the same 2-3 s, whatever is in it. |
| B2 | **Renewal every 3-5 s** | 7 | A new piece of information, a new place, a reveal, a text beat or a sound hit keeps arriving; the viewer never has a second to decide to leave. | A stretch of 6+ s where nothing new happens. |
| B3 | **No filler** | 7 | Every shot is the best take of its moment; nothing is there to fill time. The video is as long as its content and not a second longer. | Repeated views of the same thing, shots kept because they exist, padding to reach a length. |

### C. Story and heart (25)

| # | Criterion | Weight | 9-10 | 3 |
|---|---|---|---|---|
| C1 | **Payoff** | 9 | The last seconds answer the hook or turn it: the reveal, the #1, the punchline, the emotional beat. The viewer feels the video ended, not stopped. | It fades out on one more pretty shot. |
| C2 | **A person in it** | 8 | Someone we can read: a face reacting, a hand doing something, a POV with a body in it, a voice with an opinion. We feel what it was like to be there. | Places only, or the person only posing for the camera. |
| C3 | **Specific value or point of view** | 8 | Something the viewer can use or couldn't get elsewhere: a name, a price, an order to do things, a mistake to avoid, or a clearly personal take. | Generic ("amazing place", "must visit") that fits any video of anywhere. |

### D. Picture (15)

| # | Criterion | Weight | 9-10 | 3 |
|---|---|---|---|---|
| D1 | **Shot quality** | 5 | Sharp, stable or deliberately handheld, exposed, composed for 9:16 with the subject in the safe area. | Soft, shaky by accident, blown sky, a subject cut by the crop. |
| D2 | **Look** | 5 | One coherent grade that suits each scene: the cuts feel like the same film. Colour carries mood (warm night, cold morning). | Raw phone colour that changes shot to shot, or one heavy filter over everything. |
| D3 | **Motion and scale** | 5 | Camera movement with intent (push-in, reveal, whip matched across the cut), and a mix of wide, medium and detail shots. | All static, or all the same distance from the subject. |

### E. Sound (10)

| # | Criterion | Weight | 9-10 | 3 |
|---|---|---|---|---|
| E1 | **Sound drives the edit** | 5 | Cuts, reveals and text land on the beat or on sound hits; natural sound (water, crowd, a laugh) is used as a moment, not buried. | Music laid under the picture with no relation to the cuts. |
| E2 | **Voice and mix** | 5 | Narration (if any) sounds like a person talking to one friend, at speed, intelligible over the music; levels are even; no clipping. | Flat reading, voice fighting the music, a jump in level between clips. |

### F. Packaging (5)

| # | Criterion | Weight | 9-10 | 3 |
|---|---|---|---|---|
| F1 | **Text and native feel** | 3 | Few words on screen, big, in the safe zone, on screen long enough to read; it looks like it was made by a person for this app, not an ad or a slideshow. | Long paragraphs, text under the UI, template look. |
| F2 | **A reason to save or send** | 2 | A list, a route, a tip, a feeling someone wants to share ("send this to who you'd go with"). | Nothing to keep. |

Weights add to 100: A 25, B 20, C 25, D 15, E 10, F 5.

## Output

One JSON per video, next to the `.watch/` folder (`score.json`):

```json
{
  "video": "…", "kind": "reference|ours", "format": "montage|narrated list|POV vlog|…",
  "scores": {"A1": {"score": 8, "evidence": "0.0 s: …"}, "…": {}},
  "total": 74,
  "techniques": ["general, reusable things it does well — never a fact about a place"],
  "costs_points": ["what holds it back"],
  "one_line": "why it works or does not, in one sentence"
}
```

## What the references taught (kept here, general)

The first scoring round is in the changelog. The lessons that change how we build are folded into
`concepts.md` (hook, open loop, payoff), `editing.md` (pace, look, text) and `audio.md` (sound as the
edit's clock). When a new round of references teaches something, it goes there — not into this
file, which is only the ruler.
