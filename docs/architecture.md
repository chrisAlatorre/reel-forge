# Architecture

How material travels from your library to the delivered videos, and how the number of parallel agents
gets decided.

## Principles

1. **Context before editing.** You never edit over a list of files. First you catalog what happens inside
   every photo and every video, with exact seconds.
2. **Heavy things don't enter the context.** Agents see thumbnails, contact sheets, frame strips and
   transcriptions, not 4K originals.
3. **Parallel where there's no dependency.** The catalog and the trend research run at the same time; so
   do a concept's two variants.
4. **One render engine.** Every variant comes out of the same script (`skills/video-engine`). If a
   concept needs something different, the engine gets fixed, not copied.
5. **Everything rebuilds from a script.** Every variant leaves its `variant.json`, not just its `spec.json`:
   a spec pointing at a deleted temporary is irreproducible.
6. **Nothing ships unreviewed.** Every concept goes through a reviewer that compares its two variants.
7. **Agents hand each other files, not prose.** Every artifact that crosses a phase is JSON with a
   schema in [`schemas/`](../schemas/README.md), written to disk and validated before the agent
   answers. Free text is where a batch gets silently reinvented and where a narrated video ends up
   shipping mute.
8. **The main path carries no optional extras.** The animated route map, the character intro and the
   person cutout live in the engine and are opt-in per concept, never assumed by the flow.

## Full flow

```text
┌─ SOURCES ──────────────────────────────────────────────────────────────────┐
│  Apple Photos (macOS)   Local folders   Insta360 .insv   External audio     │
└───────────┬────────────────────┬──────────────┬────────────────┬───────────┘
            └────────────────────┴──────┬───────┴────────────────┘
                                        v
                          ┌─────────────────────────────┐
                          │ 1. SCOPE                    │  main thread
                          │ one round of questions:     │  /reel
                          │ material, who appears,      │
                          │ platform, language, vetoes  │
                          └──────────────┬──────────────┘
                                         v
                          ┌─────────────────────────────┐
                          │ 2. INVENTORY                │  skill: sources
                          │ files, real date, type,     │  /reel-sources
                          │ duration, favorite, local   │  no agents
                          │ or in the cloud             │
                          └──────────────┬──────────────┘
                                         v
                          ┌─────────────────────────────┐
                          │ 3. CHEAP SIFT               │  main thread or 1 agent
                          │ out with screenshots, docs, │  before spending agents
                          │ receipts, blurry shots,     │
                          │ dupes + proxies and thumbs  │
                          └──────────────┬──────────────┘
                                         v
        ┌────────────────────────────────┴───────────────────────────────┐
        v                                                                v
┌───────────────────────────────────────┐              ┌──────────────────────────────┐
│ 4. CATALOG   (N agents in parallel)   │              │ 5. TRENDS  (1-3 agents)      │
│ workflow: workflows/catalog.js        │              │ agent: trend-researcher      │
│                                       │              │  - formats and hooks         │
│  photo-curator -> photo batch:        │              │  - sounds with MEASURED BPM  │
│    contact sheet + face crops         │              │  - narration styles          │
│  clip-analyst  -> video batch:        │              │  - in the output language's  │
│    frame strip + audio -> RANGES      │              │    market                    │
│  360-scout     -> 1 clip: ring        │              │  - everything with a source  │
│    sheets, directions, keys.json      │              │                              │
│                                       │              │ -> workspace/trends/         │
│ -> workspace/catalog/catalog-<b>.json │              │       trends.json            │
└───────────────────┬───────────────────┘              └───────────────┬──────────────┘
                    v                                                  │
      ┌───────────────────────────────┐                                │
      │ 4b. VERIFY AND MERGE          │                                │
      │ a second pass over the ranges │                                │
      │ (does the real window show    │                                │
      │ what it claims?), drops dupes │                                │
      │ -> catalog.json               │                                │
      └───────────────┬───────────────┘                                │
                      └──────────────────┬─────────────────────────────┘
                                         v
                        ┌───────────────────────────────┐
                        │ 6. CONCEPTS                   │
                        │ creative-director x4-8, in    │
                        │ parallel: one concept each,   │
                        │ from its own angle, with its  │
                        │ ARC (promise, development,    │
                        │ close), the seconds that      │
                        │ story needs, and second-by-   │
                        │ second structure              │
                        │             │                 │
                        │             v                 │
                        │ chief-editor x1: picks the    │
                        │ best for variety and says     │
                        │ what to fix -> selection      │
                        │ (you confirm here)            │
                        └───────────────┬───────────────┘
                                        v
                        ┌───────────────────────────────┐
                        │ 7. STORY   (pre pass)         │  story-doctor,
                        │ before a single frame is      │  1 per concept
                        │ rendered: does the hook       │
                        │ promise, is the promise paid, │
                        │ does the middle develop, does │
                        │ the close land, and how many  │
                        │ seconds does it really need   │
                        │ -> story/<concept>.json       │
                        │    (its `blocks` are binding) │
                        └───────────────┬───────────────┘
                                        v
        ┌───────────────────────────────┼───────────────────────────────┐
        v                               v                               v
┌──────────────────┐          ┌──────────────────┐          ┌──────────────────┐
│ CONCEPT 1        │          │ CONCEPT 2        │          │ CONCEPT 3        │
│  common/ (music  │          │  common/         │          │  common/         │
│  bed, 9:16       │          │                  │          │                  │
│  crops)          │          │                  │          │                  │
│ ┌──────┐┌──────┐ │          │ ┌──────┐┌──────┐ │          │ ┌──────┐┌──────┐ │
│ │  A   ││  B   │ │          │ │  A   ││  B   │ │          │ │  A   ││  B   │ │
│ └──┬───┘└──┬───┘ │          │ └──┬───┘└──┬───┘ │          │ └──┬───┘└──┬───┘ │
└────┼───────┼─────┘          └────┼───────┼─────┘          └────┼───────┼─────┘
     │       │                     │       │                     │       │
     └───────┴─────────────────────┴───────┴─────────────────────┴───────┘
                                        │   8. COMMON + 9. BUILD
                                        │   (workflows/build.js)
                                        │   video-builder x1 per variant
                                        │   variant.json -> spec.json -> 1080x1920 render
                                        │   + verify.py on every render
                                        v
                        ┌───────────────────────────────┐
                        │ 10. ARC  (post pass)          │  story-doctor,
                        │ watches the rendered variants:│  1 per concept
                        │ does it develop, does the end │
                        │ land or does it just stop,    │
                        │ does the length fit the story │
                        │ -> story/<concept>-post.json  │
                        └───────────────┬───────────────┘
                                        v
                        ┌───────────────────────────────┐
                        │ 10. REVIEW                    │  critic-reviewer,
                        │ looks at frames and listens:  │  1 per concept, sees
                        │ black frames, audio gaps,     │  all its variants
                        │ peak under -0.5 dBTP, audio   │  together before closing
                        │ as long as the video, text    │
                        │ synced to the voice, wrong    │
                        │ facts, cuts counted           │
                        │ -> fixes by re-rendering      │
                        └───────────────┬───────────────┘
                                        │ what fails goes back to 9
                                        v
                        ┌───────────────────────────────┐
                        │ 11. DELIVERY                  │
                        │ v1/<concept>/ (+resources/)  │
                        │  <concept>-A.mp4   (clean)    │
                        │  ...-A-preview.mp4 (song)     │
                        │  ...-A-light.mp4   (720p)     │
                        │  README.md per concept        │
                        │ v2 never overwrites v1        │
                        └───────────────────────────────┘
```

## What happens in each phase

### 1. Scope
One round of questions, at the start: which material and from which period, whether the person appears
and how much, whether anyone must be kept out, platform and duration, output language and narration, and
what must not show up. With `--auto` the defaults are taken and reported. The output language also
governs the trend market and the voice list; if it isn't already set by flag, env var or config, it gets
asked here, once, and saved.

### 2. Inventory
Walks the sources and produces the file list with the real capture date (the one in the name lies when
you cross time zones), type, duration, favorite flag, and whether the original is on disk or only in the
cloud. Fast and it touches nothing. Can be run on its own with `/reel-sources`.

### 3. Cheap sift
Drops what is never going to work before handing out work: screenshots, documents, receipts, screens,
blurry shots and near-identical duplicates. What's dropped gets noted with a reason, not deleted. This is
also where the thumbnails and proxies the agents will look at get generated.

### 4. Catalog
The phase that scales. Each agent gets a batch and the full contract, and returns **moments**, not files:
`(id, start_s, end_s, what you see, what you hear, quality, who's in it)`. The batches don't overlap and
each agent writes its own file to disk **before** answering, so an interruption doesn't force anyone to
look at the same material twice.

A **second pass** verifies the video and 360 ranges by looking at the real window: a badly noted range
puts a shot into the edit that isn't the one the catalog claimed. At the end the batches are merged,
duplicates are dropped, and what's left uncovered gets reported.

### 5. Trends
Runs in parallel with phase 4 because it doesn't depend on it. Returns current formats with their
structure, sounds with a BPM measured on the real preview (not assumed) and style notes, each with a
source and a date, **for the market of the chosen language and region**. Anything without a source
doesn't go in. With `--no-trends` it gets skipped and the concepts use the skill's base formats.

### 6. Concepts
Two steps. First, 4 to 8 `creative-director` in parallel, each with the full catalog, the trends and **a
different angle**: one on the beat, one narrated, one with few long shots, one a list. Each director
returns one concept, with a first-second hook, a second-by-second structure, the moments it uses by id
and the ratio of cuts with and without the subject.

Every concept also carries an **arc** and the **duration that arc needs**. The arc is four fields — what
the hook promises, the beats that develop it, the optional turn, and the close with the reason it lands —
and `target_duration_s` is argued in beats in `duration_rationale`, never taken from a house length. That
is what makes one concept 14 s and the next one 52 s instead of every video coming out the same size, and
why a video stops feeling like it was interrupted: the ending was planned before the middle was written.

Each concept also declares **its own subject quota** (`subject_quota`): how much of the video the main
person may occupy, according to what the concept is — a first-person POV and a piece where the place is
the protagonist are not held to the same number. The ceilings per kind are in
`skills/reel-forge/references/concepts.md`, and the reviewer verifies against what the concept declared.

Then one `chief-editor` reads them all together and chooses: drops the repeats and the weak ones, keeps
the ones that genuinely differ, and says exactly what to fix in each before it gets built. It's the only
point where anybody sees every proposal at once, which is why it's the one that guarantees variety. You
confirm its selection before the rendering starts.

### 7. Story (pre pass)
One `story-doctor` per concept, **before a single frame is rendered** — it is the cheapest agent in the
flow and the one that prevents the most wasted rendering. It answers five questions with a second and a
quote each: does the hook promise something, is the promise paid off and where, does the middle develop
or is it loose cuts, does the ending land or does it just stop, and is there too much time or too little
and where. It returns `story/<concept>.json` (`story-review` contract) with a verdict, corrections that
name a second and a catalog id, and the seconds each variant needs defended in beats. Its `blocks` fixes
are binding on the builder.

Its other job is that **durations stop being all the same**: a run of videos that all land within 5 s of
each other is itself a finding, because the length is coming from a template and not from the stories.

### 8. Common and 9. Build
One `video-builder` per variant (handed out by `workflows/build.js`), with the same outline and freedom
of execution. The shared work (music bed, 9:16 crops, light copies) is prepared **once** in `common/`;
when each agent did it on its own, one used the raw track and the last seconds of its video came out
silent. Each agent writes its `variant.json`, which the shared `variant.py` uses to regenerate everything from scratch, and its
`result.json` with the counts and the measurements it actually ran.

A narrated variant also writes its `voice-script.json`: every line with the second it comes in on, how
long it runs and whether the music ducks under it. That file is the contract — when the script was left
as prose in an answer, the narration step had nothing to parse and the variant shipped mute — and the
`duck` field is what stops anybody lowering a clip's audio by hand so the voice can be heard.

For a narrated variant the captions are **cut from the voice that was generated**, not from estimates:
`transcribe.py --align` gives every word the second it is really pronounced on, and the spec's `sync`
takes the caption times from that file. Half a second of drift reads as a dubbed video and no frame strip
shows it, because every frame on its own looks right. Every render passes `verify.py` before it leaves
the builder.

### 10. Arc (post pass) and Review
The same `story-doctor` watches the rendered variants: the frame strip, the last four seconds of audio
and the last 0.6 s frame by frame, hunting for the endings that read as "it got cut off" — a last frame
caught mid-pan, music that stops before the picture, a caption still on screen on the last frame, a
promise paid and then four more seconds of nothing, variants that all run the same length when the
concept said they differed in duration. It writes `story/<concept>-post.json`.
One `critic-reviewer` per concept, different from whoever built it, with every variant of the concept in
front of it so they can be compared **together**: that's how you find what doesn't show inside a single
one (the same frame with a different treatment, a `look` that washes out the hook, the same shot repeated
in two cuts). A measurable checklist: `blackdetect`, `silencedetect`, loudness and real peak, the audio
track's duration against the video's, the file size, a frame strip genuinely looked at, and a hand count
of the cuts the main person appears in, checked against **the concept's own quota** and not against a
fixed number. The reviewer doesn't just report: **it fixes and re-renders**.

### 11. Delivery
Per variant: the clean 1080x1920 MP4 with no copyrighted music, the `-preview` with the song just for
listening, and a 720p copy for chat. One README per concept, with what each variant is, which sound to
add in the app, the suggested hashtags and the timed script if it's narrated. Every round is a new
version: `v2` doesn't touch `v1`.

## How the agent count gets decided

The table — how many agents per phase, and how the batches split — lives in one place:
[`skills/reel-forge/references/agents.md`](../skills/reel-forge/references/agents.md), which is what
the orchestrator loads when it reaches that phase. [`parallelism.md`](parallelism.md) explains the
reasoning, the caps that actually bind, what must never be parallelized and how a run survives the
machine going to sleep.

What's worth keeping in mind at the architecture level:

- **The context phase is the bottleneck and where the value is.** Everything downstream is a function
  of how well the material got looked at.
- **Never more agents than units of material.** An agent with half a day of photos repeats what the one
  next to it already said.
- **~10 agents at a time**, because `ffmpeg` is already parallel internally and four simultaneous
  renders take almost as long as four in series.
- **What decides is serialized**: one chief editor, one reviewer per concept. A committee produces four
  videos that look alike.
- **Adjust for the machine, not for the material**: fewer than 4 cores or under 8 GB free → cap at 3
  agents; material in the cloud → the network sets the limit, catalog from thumbnails and download the
  chosen originals in a single round; under ~20 GB free disk → low-resolution proxies and say so.
- **An agent stalls:** don't wait for it indefinitely. Carry on with what you have and note in the
  README what was left uncataloged.

## What gets handed between phases

Everything an agent hands to another agent is **JSON with a schema in
[`schemas/`](../schemas/README.md)**, written to disk before the agent answers and validated with
`schemas/validate.py`. The chat message is a summary of the file, never the result itself.

| Artifact | Who writes it | Who reads it | Contract |
|---|---|---|---|
| Source inventory | Phase 2 | Phases 3 and 4 | — |
| `workspace/sheets/` (contact sheets, strips, face crops) | Phase 3 | Catalog agents | — |
| `workspace/catalog/catalog-<batch>.json` | Each catalog agent | Phase 4b | `catalog-item` |
| `workspace/catalog/catalog.json` | Phase 4b | Phases 6, 7 and 9 | `catalog-item` |
| `workspace/trends/trends.json` | The trend researcher | Phase 6 | `references/trends.md` |
| `keys.json` per 360 clip | `360-scout` | Builders | `video-360` skill |
| `concepts/<slug>.json` | Directors | Story doctor, chief editor, builders | `concept` |
| `selection.json` | Chief editor | You and the builders | its own report |
| `workspace/story/<concept>.json` | `story-doctor`, pre pass | Builders (its `blocks` are binding) | `story-review` |
| `workspace/concepts/<concept>/common/` | Main thread | Every builder of that concept | `RESOURCES.json` |
| `<letter>/variant.json`, `spec.json` and `result.json` | Builder | Render engine and reviewer | `variant-build-result` |
| `<variant>.timeline.json` next to the MP4 | Render engine | `verify.py`, story doctor, reviewer | `render-timeline/1` |
| `common/voice/alignment.json` | `transcribe.py --align` | The engine's `sync`, and `verify.py` | `caption-sync/1` |
| `voice-script.json` next to the MP4 | Builder, when narrated | The narration step and the user | `voice-script` |
| `workspace/story/<concept>-post.json` | `story-doctor`, post pass | Reviewer and you | `story-review` |
| `workspace/concepts/<concept>/review.json` | Reviewer | You | `review-result` |
| `v1/<concept>/` (upload-ready videos only) and `v1/<concept>/resources/` (everything else) | Phase 11 | You | — |

Everything lives in the project's working folder, never in the plugin's repo:

| System | Root (configurable with `REEL_FORGE_HOME`) |
|---|---|
| macOS | `~/Movies/Reel Forge/<project>/` |
| Linux | `~/Videos/Reel Forge/<project>/` |
| Windows | `%USERPROFILE%\Videos\Reel Forge\<project>\` |

`workspace/` can be deleted entirely: it rebuilds from the scripts. The round folders (`v1/`, `v2/`…) can't.
