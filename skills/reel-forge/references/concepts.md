# Concepts and variants

A **concept** is a video idea with a hook of its own and an arc that lands. A **variant** is one way of
executing that same concept. A normal round delivers 3-4 concepts with 2 variants each; a wide round
(the user asking for many options at once) goes up to 10 concepts with up to 5 variants each. The user
picks.

The format is `$CLAUDE_PLUGIN_ROOT/schemas/concept.schema.json`, one file per concept, validated before
it goes anywhere:

```bash
uv run "$CLAUDE_PLUGIN_ROOT/schemas/validate.py" concepts/<slug>.json --type concept \
    --catalog workspace/catalog/catalog.json
```

`--catalog` is not optional in practice: it's what catches a concept written around material that
nobody ever cataloged.

## Where they come from

From the catalog, not from your head. Read the merged catalog and look for:

- The `hook: 5` items: which video starts with this?
- Repetitions: four different scenes of people serving food, three transfers in different vehicles, the
  same gesture five times. A repetition is a concept already made.
- Contrasts: what you expected versus what happened, expensive versus cheap, crowd versus empty.
- A chain: A leads to B leads to C (a route, a day, a process).
- What the agents already put in their `struck_me`.

If you can't write the hook in one sentence, the concept isn't ready. And if you can't say how it
**ends**, it isn't ready either — that half is the one that keeps getting skipped.

## The arc: why a video feels cut off

The complaint this section exists for, in the user's words: *"something is building up and then it cuts
off way too soon"*. That is almost never a rendering problem. It's a concept that opened something,
listed a few shots and stopped. Every concept declares its arc in `arc`, and every second of
`structure` belongs to one of its stages (`role`):

| Stage | Where | What it has to do | Field |
|---|---|---|---|
| **Hook** | 0-3 s | The strongest shot in the catalog, and a question the viewer wants settled | `arc.hook` |
| **Promise** | implicit in the hook | The debt the video takes on: three proofs, the place at the end, why nobody goes back | `arc.promise` |
| **Development** | the middle | Beats that each add something new, with a mini hook every 3-5 s | `arc.development` |
| **Turn** | around 2/3 in | The moment it stops being what it looked like. Required past 35 s | `arc.turn` |
| **Close** | last 2-3 s | It pays the promise and lands | `arc.close` |

- **The promise is the whole thing.** `arc.promise.paid_off_at_s` is a real second in the last third. A
  hook that promises nothing has nothing to pay back, and a promise that's never paid is what "it cuts
  off" means, no matter how clean the edit is.
- **Development is not a list of cuts.** Each beat carries `raises`: what it adds that the previous one
  didn't. A beat you can't fill that in for is padding — and padding is the first thing that goes when
  the video runs long, before any real beat gets trimmed.
- **No gap over 5 s between beats.** Six seconds where nothing new happens and the concept dies there.
- **The close is written before the middle.** Decide how it ends, then build the road to it.

### The five closes that work

Declared in `arc.close.kind`. Anything outside this list is a video that stops rather than ends.

| `kind` | What it is | It works when |
|---|---|---|
| `punchline` | The gag pays off on the last cut | the setup is planted before the midpoint and nobody explains it |
| `back_to_hook` | The opening shot returns, meaning something else | the frame is recognisably the same: same angle, same scale |
| `final_fact` | The number, name or price that reframes what you just saw | the fact is verified in the catalog and was withheld until then |
| `question` | An honest question about what was shown | a stranger can answer it. "Follow for part two" is not a close |
| `loop` | The last frame joins the first, so the replay is seamless | it was built: same framing, same speed, the sound resolving on the cut |

And what makes a close fail, all of it seen in delivered videos:

- ending **mid-pan or mid-gesture**: the single thing that reads most as "it got cut off"
- a caption still on screen on the last frame, so it ends mid-sentence
- the music ending before the picture, or the picture before the music
- the payoff landing and then four more seconds of nothing: it ended and kept running
- `arc.close.lands_because` that says "it's the last clip". That's not a close, that's a leftover.

## Duration: the story decides it

There is no house length, and nothing in this plugin defaults to 20 or 30 seconds. Each concept
declares `target_duration_s` **with** `duration_rationale`, counted in beats — *hook 3 + three proofs of
7 + turn 4 + close 3 = 31 s* — and the number is argued from there.

| What it is | Usually lands | It goes longer when |
|---|---|---|
| Gag, ranking, expectation vs reality | 10-20 s | the payoff needs a setup nobody expects |
| Recap, POV, photo dump | 20-35 s | there's a real turn in the middle |
| Storytime, guide, documentary | 35-75 s | every beat brings a new fact and the material holds |

Guides to argue against, not lengths to obey. The two rules that actually decide:

- **More story than time → it goes up.** Trimming a beat to hit a length is exactly what produces the
  abrupt ending. Name the starving beat and give it its seconds.
- **Padding → it goes down.** A 40 s concept with 12 s of pretty shots that add nothing is a 28 s
  concept.

Past 75 s the material has to earn every second, and the concept says why in `notes`. And across a
delivery: **if the concepts of a round all land within 5 s of each other, the durations came from a template
and not from the stories** — the chief editor treats that as a bad selection.

## Subject quota: it is declared per concept

The old rule was one number for every video ("the subject in half the cuts or fewer"), and it was wrong
in both directions: it let a first-person POV get blocked and it let a landscape video ship with the
person in 45 % of the cuts. **Each concept declares its own ceiling, in `subject_quota`, and the
reviewer verifies the built variants against that number** — not against a fixed one.

| `kind` | What the concept is | Ceiling (`max_ratio`) |
|---|---|---|
| `first_person` | The person is the story: POV, talking to camera, a piece to camera | **0.80** |
| `recap` | The trip or the event told through them: the default for a recap | **0.50** |
| `place_first` | The place, the food, the animal or the group is the protagonist and they are a guest | **0.25** |
| `custom` | Anything the user explicitly asked for | any, with `note` saying who asked and why |

- The ratio is `cuts_with_subject / cuts`, **counted by hand** on the finished variant, never estimated.
- The schema refuses a `max_ratio` above its `kind`'s ceiling, and the validator refuses a structure
  that already breaks its own quota before anything gets rendered.
- Set `min_ratio` when the concept stops working without them: a first-person POV with two cuts of the
  person is a different video.
- `place_first` is where the original feedback came from — *"it's cringe that you're in all of them"* —
  and in production the range that worked was 14-35 %.
- The user overrides any of this. When they do, it's `custom` with the reason written down, so the
  reviewer doesn't block what was asked for.

## The concepts of a round have to differ from each other

Four photo dumps with different songs is not a delivery. One `family` each, not repeated while there
are families left — and in a wide round of 10, where the eight families run out, a repeat only counts
as a different concept if its arc, its length and its material are all different from the other one's:

| `family` | What it is | Where it usually lands |
|---|---|---|
| `beat_photo_dump` | many short shots on a beat grid | 12-25 s |
| `cinematic_pov` | few long shots, slow motion, serif text, almost no cuts | 15-30 s |
| `narrated_documentary` | voice-over with a story structure, music bed | 35-75 s |
| `list` | "things nobody tells you": a visible counter, one block per point | 25-50 s, about 8 s per point |
| `expectation_vs_reality` | pairs of shots, hard cut in the middle | 12-25 s |
| `chain_or_route` | each block enters through a vehicle, a place, a step | 30-60 s |
| `natural_sound` | no music and no voice, pure diegetic audio | 20-45 s |
| `character` | freeze frame with a cutout and data cards | 15-35 s |

These are where each family tends to land once its arc is written, not a budget to fill. A `list` with
three points is 25 s; the same format with six is 50 s, and shrinking it to 25 is how the last two
points end up with two seconds each.

## The variants of a concept

Two by default, up to five when the user wants a wide comparison. They have to read differently in the
first 3 s, and each one moves on **one** axis (`differs_in`); two variants that move on the same axis
are the same variant. There are five axes, so **five variants is the ceiling** — a sixth would repeat
one. What each axis means:

| `differs_in` | One side | The other |
|---|---|---|
| `sound` | silent, diegetic only | narrated |
| `duration` | full at 45 s | 18 s: hook, one beat and the same close |
| `subject_presence` | the subject as protagonist | pure b-roll |
| `cutting` | cut to the beat | long shots |
| `structure` | the beats in the order they happened | the turn moved to the front, told backwards |

With five variants, hand out one axis each and write in every `what` what it is testing. Five variants
that all move on `cutting` are one variant rendered five times, and the validator rejects the file.

What **doesn't** change between variants: the concept, the hook, the promise, **the close**, the output
language and the subject quota. If those change, they're two concepts and you have to say so.

**A short variant drops development beats, never the close.** Cutting the ending to make a video shorter
is the exact defect this whole section exists to prevent.

## Structure

`structure` is the second-by-second edit: ordered blocks, no overlaps, each with its catalog id, its
`role` in the arc, what you see, the on-screen text if any, the sound and whether the subject is in it.
What decides whether it works:

- **The first shot is the video's decision.** It's the one with the highest `hook`, not the first
  chronologically.
- A mini hook every 3-5 s. Six seconds where nothing new happens and the concept dies there.
- Two consecutive cuts from the same scene, the same colour or the same framing read as a mistake.
  Change the scene, the scale or the direction. Don't open two blocks with the same composition.
- The last block's `role` is `close` and its `t1` lands near `target_duration_s`.
- If you're cutting to the beat, the timings sit on the BPM grid (`bpm`, `beat0_s`), with the BPM
  measured on the real preview.

### Picture and voice say the same thing

- If the concept is narrated, the block says which line is spoken over it (`says`). **If the voice names
  something concrete, that cut has to show it** — the reviewer checks the pairing with a tolerance of
  0.25 s, so a line about the market over a shot of the beach comes back as a defect.
- Captions in a narrated variant are cut from the **generated voice**, word by word: the concept writes
  the copy, the timing comes from the synthesized audio, never from an estimate.
- With no narration, the text is tied to the cut and to what's on screen: in with the cut, out with the
  shot it belongs to.
- Narration in Spanish uses CapCut's **Valentino** by default; the local engines are the fallback and
  the variant's README says so when one is used.

The rules about what the text does on screen — safe area, size, line breaks, how long a stamp has to
last — are the engine's, in `editing.md`. Don't restate them here; read them before writing captions.

## The story doctor

A separate agent (`story-doctor`) reads the arc twice, and it's the only one whose job is whether the
video is *finished*:

- **Before building**, on the concept: does the hook promise something, is the promise paid, does the
  middle develop, does the close land, and is the duration the one the story needs. It returns
  `story/<concept>.json` with fixes that name a second and an id.
- **After rendering**, on each variant: it watches the frame strip and the last four seconds, hunting
  endings mid-pan, captions on the last frame, music that stops before the picture, and variants that
  all came out the same length.

Its `blocks` fixes are the promise unpaid, the missing close and the broken arc. Those get applied
before the concept is built or before the variant ships; everything else is optional and the director or
the reviewer decides.

## Before sending to build

- Does each concept have a **close with a mould** and a `lands_because` that says something?
- Does `arc.promise.paid_off_at_s` point at a real second, in the last third?
- Does `duration_rationale` add up to `target_duration_s` beat by beat, and does the structure actually
  end there?
- Do the concepts of the round **differ in length**, not just in format?
- Do they use different material? If two are fighting over the same 6 good shots, split them: each one
  keeps a hook of its own.
- Does each one meet **its own** quota, separately? An average across the delivery is not enough.
- Does `common/` already have the crops, the music bed and the exported photos? If not, the builders
  will each do it their own way.
- Does the concept validate against the schema, with `--catalog`? A concept that cites an id that isn't
  there is a serious defect, and the chief editor is instructed to flag it as one.

## Extras, off the main path

The engine can do a few things that are **not** part of the normal flow: the animated route map, the
character intro with a person cutout, text behind the subject, tiny planet. They're in `editing.md`
under extras and in the `video-engine` skill.

Treat them as opt-in: a concept may ask for one when the material genuinely calls for it (a route that
only reads on a map, a guide with a card per stop), and it says so explicitly in `notes`. A concept
that needs one to be interesting isn't ready — and nothing in the main flow should assume they exist,
because they cost pre-rendering, they download a base map and they fail differently on each system.
