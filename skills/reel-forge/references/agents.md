# Agents: how many, what you give them and what they return

This is the source of truth for **how many agents to launch** and **what each one's contract is**. The
reasoning behind the numbers, what must never be parallelized and how a run survives an interruption
are in [`docs/parallelism.md`](../../../docs/parallelism.md).

## How many

| Phase | Agents | Rule |
|---|---|---|
| Context, under 200 files | **3** | one per day or per place |
| Context, 200-1000 | **6** (8 if more than 10 days) | one per day, or per batch of ~150 files |
| Context, over 1000 | **10** | cheap sift first; then batches of ~150 of what's left |
| Video | **1 per 4 clips** | watching one clip is ~15 tool calls; past 4-5 the agent describes from memory |
| 360 material | **1 per clip** | every equirectangular clip is its own job |
| Trends | **1-3** | with web search, in parallel with the context phase: formats / sounds / niche |
| Concepts | **4-8 directors** | one per angle, in parallel; they can't see each other |
| Selection | **1 chief editor** | always one: the only one who sees every proposal together |
| Story, before building | **1 story-doctor per concept** | the arc and the seconds each variant needs. Binding |
| Common folder | **1 per concept** | everything the variants share, prepared once, before anybody builds |
| Build | **1 per variant** | one agent, one letter, one folder, one delivery |
| Arc, after rendering | **1 story-doctor per concept** | does it develop, does it land, does the length fit |
| Review | **1 per concept** | different from the builders; reviews every variant together |

The last two run **at the same time**, on the same files, looking for different defects: the
story-doctor asks whether it is a finished video, the reviewer whether it is a well-made one. Their
blockers are then fixed in one pass over the variant's `build.py`.

Never more agents than units of material: an agent with half a day of photos has nothing to compare
against and repeats what the one next to it already said.

Practical cap: **~10 agents at a time**. Beyond that, renders start taking minutes and it isn't the
code's fault. With 4 concepts, launch the build in two waves of 4 agents. A big round — ten concepts
with five variants each — is not fifty agents at once: `workflows/build.js` advances one concept at a
time and caps itself at `min(16, CPUs - 2)`. What makes a round that size survivable is the progress
protocol, not a smaller number.

**How many variants per concept.** Two is the floor, not the rule. Each one moves on **one** axis
(`differs_in`: sound, duration, subject_presence, cutting, structure), so a concept earns as many
variants as it has real axes — three is common, five is what a comparison round asks for. Five variants
that differ only in the copy are one variant with five names, and so are five that all came out the
same length.

**Before launching a wave, stop the machine from sleeping** (macOS: run the round under `caffeinate
-dimsu`). A batch that dies because the lid closed loses every agent that hadn't written its file yet.
See `docs/parallelism.md`.

## General contract

Every agent receives, without exception:

1. The path of its batch or its concept and **the exact list of files or ids** it works with.
2. **The path of the rules**, not a copy of them. What already lives in `references/` and in `schemas/`
   you point at; what is specific to this job — this concept's arc, this variant's letter and seconds,
   this batch's file list — you spell out. A contract copied into six prompts is six copies to keep in
   sync, and the one that drifts is the one that produces the work you have to redo.
3. The **output language tag** if it produces or verifies copy (directors, story-doctor, builders,
   reviewer, trends).
4. **The schema of what it must write**, from `$CLAUDE_PLUGIN_ROOT/schemas/`, and the order to validate
   its own file before answering:
   `uv run "$CLAUDE_PLUGIN_ROOT/schemas/validate.py" <its file> --type <contract>`.
5. The path of **its** output file, different from everyone else's, and **its unit id**: one progress
   file in `<workspace>/run/<unit>.json` that nobody else writes, rewritten at least every ~2 minutes,
   with long work split into steps that each finish inside that window. The shape and the reasoning are
   in the `reel-forge` skill, section **Resuming a run**.
6. What it may not do: nobody else renders, nobody touches `common/`, nobody deletes anything, nobody
   publishes anything.

And it returns, in its final message: the path of its file, how many items it cataloged or how many cuts
it assembled, and **the three things that struck it most** (`struck_me`: that's what you use for the
concepts).

| Agent | Writes | Contract |
|---|---|---|
| `photo-curator`, `clip-analyst`, `360-scout` | `workspace/catalog/catalog-<batch>.json` | `catalog-item` |
| `trend-researcher` | `workspace/trends/trends.json` | `trends.md` |
| `creative-director` | `concepts/<slug>.json` | `concept` |
| `chief-editor` | `selection.json` | `concept` (the fixes it asks for) |
| `story-doctor` (pre) | `workspace/story/<concept>.json` | `story-review` |
| `story-doctor` (post) | `workspace/story/<concept>-post.json` | `story-review`, with `pass: "post"` and the variants it watched |
| common-folder agent | `workspace/concepts/<concept>/common/RESOURCES.json` | what each shared file is and where it came from |
| `video-builder` | `workspace/concepts/<concept>/<letter>/result.json` | `variant-build-result` |
| `video-builder` (narrated) | `voice-script.json` next to the MP4 | `voice-script` |
| `critic-reviewer` | `workspace/concepts/<concept>/review.json` | `review-result` |

## Context agent

The brief:

> Catalog the N files in the attached list. For each one: pull a thumbnail or frame strip, **look at
> it**, and write an item in the format of `schemas/catalog-item.schema.json` — one item per moment,
> and videos split into windows with `start_s`/`end_s`; the whole file is never one item. Apply the
> drop rules (`use: false` with a reason, delete nothing). For shots where the subject appears, also
> pull face crops and review the full burst before keeping one. Validate with `schemas/validate.py`,
> write `workspace/catalog/catalog-<batch>.json`, and only then answer. Don't render or edit anything.

What goes wrong if you don't say it:
- It catalogs by file name without opening the image. → Require the `sheet` field with the reference.
- It returns the whole video as one item. → Require at least 2 windows per video over 15 s, or a reason.
- It invents the format. → Hand it the schema file and require the validator to have passed.

## 360 agent

One per clip. Receives the path of the `.insv` or the equirectangular and returns one item **per
direction** (yaw, pitch, fov, and what's there). See `video360.md`. It doesn't render the final video:
it leaves `keys.json` ready plus a note on what's in each direction.

## Trend agent

See `trends.md`. Returns `workspace/trends/trends.json` with formats, sounds with measured BPM, hooks
and voices, **each with a source and a date**, and the `market` field stating which language and region
it researched. If it found no source, it doesn't include the item.

Every format comes back with **the length it actually runs and how it closes**, cited. That is the
evidence the concepts weigh their own duration against: a market whose working format is a 50-second
narrated piece is not one where everything should come out at 25 s.

## Creative directors (4-8, in parallel)

Each receives the merged catalog, the trends, the output language and **an angle you assign**. It
returns `concepts/<slug>.json` with **one single concept**, not three half ones.

> Propose ONE concept for a <platform> vertical, from this angle: **<angle>**. On-screen text and
> narration in <language tag>. Write it in the format of `schemas/concept.schema.json` and validate it
> with `--catalog`: using an id that isn't in the catalog invalidates your whole concept. Declare
> `subject_quota` (`kind` + `max_ratio`) according to what the concept is — the table is in
> `concepts.md` — and keep the structure inside it. Deliver: the first-second hook, the promise, a
> second-by-second structure with the id of each cut, **a planned close** (which shot it ends on and the
> last caption), whether it cuts to the beat or to natural sound, whether it carries narration, and 2 to
> 5 variants that each move on a different axis. The **target duration comes from the beats you wrote**,
> not from a house default: a gag is 8-12 s and a list with five points is 40-60 s, and both are
> correct. The story-doctor will check that number and may change it.

Angles that split well (one per director, never repeated): narrated documentary · pure natural sound ·
guide with prices · visual gag · POV · list with a payoff · block counter · one long take · before and
after.

**The variety comes from the angles you hand out, not from asking them for "something different".**
Eight directors with no assigned angle return eight photo dumps.

## Chief editor (1, always one)

Reads **every** concept and the catalog, and decides what gets built.

> Read all the `concepts/*.json` and the catalog. Pick the 3 that differ most from each other (different
> `family`) and that can genuinely be built with the material available. Drop the repeats and the weak
> ones, and say why. For each chosen one, write the **required fixes** to apply before building it.
> Flag as a serious defect any concept that doesn't validate, or whose `subject_quota` doesn't match
> what the concept actually is. Write `selection.json`.

Two chief editors contradict each other and you lose exactly what this step is for. You confirm its
selection in one line before the rendering starts.

## Story doctor, first pass (1 per concept, before anything is built)

It is the cheapest agent in the round and the one that decides whether the rest were worth launching.
The defect it exists for, in the user's words: *"something is being developed and it gets cut too
soon"*, and *"almost all of them last less than 30 seconds"*.

> Take concept "<name>" apart into its arc — **hook → promise → development → turn → close** — against the catalog. Say which
> beats repeat the one before them and have to be cut, and **whether there is a close at all** — a
> last shot that pays the promise off and holds, not the last clip on the list. If the payoff shot
> doesn't exist in the material, say so now (`verdict: "rework"`) instead of letting five agents render
> around a hole. Then **set the duration of each variant from its own beats**, in `per_variant`, each
> one defended `in_beats` (*hook 3 + three proofs of 7 + close 4*): they must not all come out the same
> length, and a short variant keeps the whole arc and loses middle beats, never the close. Fixes are
> written as instructions a builder can apply, each with its `level`; `blocks` is **binding**. Write
> `workspace/story/<concept>.json`.

What goes wrong if you don't say it:
- It returns a critique instead of instructions. → Require every fix as "open on <id>", "cut the third
  beat", "the close is <id>, held 2 s, with the caption <text>".
- It gives every variant the same duration. → Require `in_beats` per variant.
- It invents the payoff shot. → Require every id to exist in the catalog, and `reject` when it doesn't.

## Common-folder agent (1 per concept, before any builder)

It exports the originals of the assigned moments, prepares the 9:16 crops and the pre-renders, renders
the 360 framings from `360-scout`'s keys and builds the looped, normalized music bed — once, in
`workspace/concepts/<slug>/common/`, with `RESOURCES.json` written last. It builds no variant and writes
into nobody's variant folder. When each builder did this for itself, one used the raw 30 s preview and
the last seconds of its video came out silent.

## Builder agents (1 per variant)

Each one receives: the full concept (validated), the story-doctor's `story.json`, the merged catalog,
the output language, the `common/` folder already prepared and **its letter** with the variant it owns.

> Build variant <letter> of concept "<name>", and only that one. Apply the story-doctor's
> blocking fixes before rendering, and build the arc it set, down to a close that holds.
> Your length is <n> s (±10 %); if the story needs another, change it and write down why — never hit a
> number by trimming the close. Use only catalog ids and **respect the `start_s`/`end_s` windows**; if
> you have to widen one, look at the strip first and declare it in `out_of_window`. On-screen text and
> narration in <language tag>. Write `concepts/<concept>/<letter>/build.py` to generate the spec and
> render: it has to rebuild everything from scratch, with no dependency on temporaries. **If it is
> narrated, the voice is generated before the text is written** — `voice-script.json`
> (`schemas/voice-script.schema.json`) proved to parse, then the WAVs line by line with the default
> voice for the output language — **and the subtitles take their times from that voice**
> (`transcribe.py --align` → `alignment.json`, `"sync"` in the spec); over a clip's own audio they come
> from `"subs"`, with no audio from `"seg"`, and the segments the voice names declare `"says"`. Never
> type a subtitle's seconds. Count the cuts where the subject appears by hand. Run the gate with
> `--spec` and, when narrated, `--script`, with the render's `timeline.json` beside the MP4. Write and
> validate `result.json` (`variant-build-result`) before answering. Don't touch `common/` or another
> builder's folder.

How the variants split: one axis each (`differs_in`), from the table in `concepts.md`. The shared work
(9:16 crops, looped music bed, exported originals) is already in `common/` — never redone per builder.

## Reviewer agent (1 per concept)

It built neither variant. It receives every variant, the concept, the output language and the checklist
from `delivery.md`.

> Review every variant of concept "<name>". Pull an `fps=2,tile=12x6` strip of each and look at them.
> Re-run the gate yourself on every delivered file, with `--spec` and, when narrated, `--script`, and
> check its text and ending criteria say `pass` and not `skip` — a missing `timeline.json` skips them. **Compare the same frame between the variants**: if the hook looks different, say which
> one is wrong. **Spot-check three captions per variant with the audio playing**: on screen while that
> word is being said (0.25 s), and when a line names something concrete, that thing is what is on
> screen. Check that every caption and narration line is in <language tag>, correctly spelled, and say
> **which voice** each narrated variant used — a backup voice instead of the default goes in the README
> in its own line. Count the cuts with the subject by hand and check the ratio against **the concept's
> own `subject_quota`**, not against a fixed number. Write `review.json`
> (`schemas/review-result.schema.json`): each problem with its exact second and its `severity`. What
> blocks, you fix yourself — the correction goes inside the variant's `build.py` and you re-render. In
> `workflows/build.js` that is the **Fix** stage, which is only paid for if something is marked
> `blocks`.

## Story doctor, second pass (1 per concept, on the rendered files)

It runs in parallel with the reviewer and owns one question: **is this a finished video?**

> Watch every variant of "<name>": an `fps=2,tile=12x6` strip AND the last 3 seconds at 8 fps. Per
> variant: does it **develop** (or is the middle four shots of the same idea — name the second where it
> stalls), does it **land or does it stop** (an ending that cuts off mid-movement or mid-word is
> `blocks`), and does the **duration fit** what it is telling — report it even when that means the
> variant should be longer than it was asked to be. Across the set, say in `spread` whether every
> variant came out the same length. Write the fixes as something a builder can apply to `build.py`:
> which shot, which second, how long it holds, each with its `level`. Write
> `workspace/story/<concept>-post.json`; don't re-render anything yourself.

A close that has to be extended is extended **with material** — hold the shot, add the missing beat —
never by freezing the last frame, which reads as a bug.

What the reviewer has found in production, which is why it exists:
- a `look` that washed out the hook in 2 of 4 deliveries, because nobody compared across variants
- captions with hand-written `\n` that dropped an orphan word once the size went down
- a stamp on screen for 0.39 s, illegible
- a post-processing script with no execute permission that nobody was calling, so the audio kept
  clipping
- two cuts from the same clip 4° apart, which read as an editing mistake
- a narrated variant delivered mute: the builder left the script as prose in its answer, and the
  narration step had nothing it could parse
- captions written from an estimate before the voice existed: by the end of the video the text was a
  line and a half behind what was being said
- a line naming a place over a shot of somewhere else, which is what makes a video feel assembled
  rather than told

## Hygiene

- **One agent, one output file.** Two agents writing the same file overwrite each other silently.
- **Write the JSON at the end, complete, before answering.** If an agent fails halfway, its output file
  must not exist: that's the "redo this batch" signal.
- **Validate before answering.** A file that doesn't validate is a file the next phase can't read.
- Nobody deletes original material. Nobody publishes. Nobody spends money.
- Read the results before moving to the next phase. A bad catalog gets multiplied by 4 concepts.
