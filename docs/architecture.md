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
5. **Everything rebuilds from a script.** Every variant leaves its `build.py`, not just its `spec.json`:
   a spec pointing at a deleted temporary is irreproducible.
6. **Nothing ships unreviewed.** Every concept goes through a reviewer that compares its two variants.

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
                        │ from its own angle, with hook │
                        │ and second-by-second structure│
                        │             │                 │
                        │             v                 │
                        │ chief-editor x1: picks the    │
                        │ best for variety and says     │
                        │ what to fix -> selection      │
                        │ (you confirm here)            │
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
                                        │   7. BUILD  (workflows/build.js)
                                        │   video-builder x2 per concept
                                        │   build.py -> spec.json -> 1080x1920 render
                                        v
                        ┌───────────────────────────────┐
                        │ 8. REVIEW                     │  critic-reviewer,
                        │ looks at frames and listens:  │  1 per concept, sees
                        │ black frames, audio gaps,     │  all its variants
                        │ peak under -0.5 dBTP, audio   │  together before closing
                        │ as long as the video, text    │
                        │ overlaps, wrong facts,        │
                        │ cuts counted                  │
                        │ -> fixes by re-rendering      │
                        └───────────────┬───────────────┘
                                        │ what fails goes back to 7
                                        v
                        ┌───────────────────────────────┐
                        │ 9. DELIVERY                   │
                        │ deliveries/v1/<concept>/      │
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

Then one `chief-editor` reads them all together and chooses: drops the repeats and the weak ones, keeps
the ones that genuinely differ, and says exactly what to fix in each before it gets built. It's the only
point where anybody sees every proposal at once, which is why it's the one that guarantees variety. You
confirm its selection before the rendering starts.

### 7. Build
Two `video-builder` per concept (handed out by `workflows/build.js`), with the same outline and freedom
of execution. The shared work (music bed, 9:16 crops, light copies) is prepared **once** in `common/`;
when each agent did it on its own, one used the raw track and the last seconds of its video came out
silent. Each agent writes its `build.py`, which has to regenerate everything from scratch.

### 8. Review
One `critic-reviewer` per concept, different from whoever built it, with every variant of the concept in
front of it so they can be compared **together**: that's how you find what doesn't show inside a single
one (the same frame with a different treatment, a `look` that washes out the hook, the same shot repeated
in two cuts). A measurable checklist: `blackdetect`, `silencedetect`, loudness and real peak, the audio
track's duration against the video's, the file size, a frame strip genuinely looked at, and a hand count
of the cuts the main person appears in. The reviewer doesn't just report: **it fixes and re-renders**.

### 9. Delivery
Per variant: the clean 1080x1920 MP4 with no copyrighted music, the `-preview` with the song just for
listening, and a 720p copy for chat. One README per concept, with what each variant is, which sound to
add in the app, the suggested hashtags and the timed script if it's narrated. Every round is a new
version: `v2` doesn't touch `v1`.

## How the agent count gets decided

### Photo catalog (phase 4)

| Files | Agents | How they split |
|---|---|---|
| Under 200 | **3** | One per day or per place |
| 200 to 1000 | **6** (8 if the period covers more than 10 days) | One per day, or per batch of ~150 files |
| Over 1000 | **10** | Cheap sift first; then batches of ~150 of what's left |

On top of that table, **never more agents than days**: an agent with half a day of material has nothing
to compare against and repeats what the one next to it already said.

### Video and 360 catalog

| Material | Agents | Why |
|---|---|---|
| Videos | **1 per 4** (configurable) | Actually watching a video is ~15 tool calls (frame strip, crops, transcription, checking a second). Past 4-5, the agent runs out of context and starts describing from memory |
| 360 clips | **1 per clip** | Every equirectangular yields several different framings and needs its own ring sheets. Worth a whole agent even if it's 20 seconds long |

### Trends
**1** by default, in parallel with everything else. Up to **3** when it's worth splitting by theme
(formats, sounds, niche) so one agent doesn't contaminate the other.

### Concepts
**4-8 creative directors** in parallel, one per angle: fewer than 4 and every proposal looks alike; more
than 8 and the chief editor spends more time discarding than choosing. Then **1 chief editor**, always
exactly one, because its job is precisely to see everything together.

### Build
**2 per concept, always.** That's what lets you compare: with one variant you're judging in the abstract;
with three or more, you stop reviewing them. The two get chosen so they read differently (silent with
diegetic sound versus narrated, long versus short, chronological order versus energy order).

### Review
**1 per concept**, different from whoever built it, with every variant in front of it. It measures and
looks at frames, which is cheap, but it also fixes: if it has to re-render, that counts as another render
in the machine's budget.

### Caps and adjustments

- **Practical cap: ~10 agents at a time.** Beyond that, renders start taking minutes and it isn't the
  code's fault, it's the disk and the CPU. With 4 concepts, the build runs in two waves.
- **Short on time** (`--fast`): the agent cap goes up and the frame-strip resolution and transcription
  quality go down.
- **No hurry:** smaller batches (~100 files) for a finer review.
- **Material in the cloud:** the network sets the limit. Catalog with thumbnails, download only the chosen
  originals, and in a single round, after curation.
- **A modest machine** (under 8 GB of free RAM or fewer than 4 cores): cap at 3 agents, because the
  `ffmpeg` preprocessing competes with them.
- **Low disk** (under ~20 GB free): low-resolution proxies and an explicit warning.
- **An agent stalls:** don't wait for it indefinitely. Carry on with what you have and note in the README
  what was left uncataloged.

### Summary

| Phase | Agents | Rule |
|---|---|---|
| Scope, inventory, sift | 0 | Main thread |
| Photo catalog | 3-10 | Table by file count, never more than days |
| Video catalog | 1 per 4 videos | Context per agent, not file count |
| 360 catalog | 1 per clip | Every clip is its own job |
| Trends | 1-3 | In parallel with the catalog |
| Concepts | 4-8 directors + 1 chief editor | One angle per director; the editor chooses and asks for fixes |
| Build | 2 per concept | In waves if it goes past ~8 agents |
| Review | 1 per concept | Sees every variant of the concept and compares them |

## What gets handed between phases

| Artifact | Who writes it | Who reads it |
|---|---|---|
| Source inventory | Phase 2 | Phases 3 and 4 |
| `workspace/sheets/` (contact sheets, strips, face crops) | Phase 3 | Catalog agents |
| `workspace/catalog/catalog-<batch>.json` | Each catalog agent | Phase 4b |
| `workspace/catalog/catalog.json` | Phase 4b | Phases 6 and 7 |
| `workspace/trends/trends.json` | The trend researcher | Phase 6 |
| `keys.json` per 360 clip | `360-scout` | Builders |
| The proposed concepts and `selection.json` | Directors and chief editor | Builders |
| `workspace/concepts/<concept>/common/` | Main thread | Both builders |
| `workspace/concepts/<concept>/<A\|B>/build.py` and `spec.json` | Builder | Render engine and reviewer |
| `deliveries/v1/<concept>/` | Phase 9 | You |

Everything lives in the project's working folder, never in the plugin's repo:

| System | Root (configurable with `REEL_FORGE_HOME`) |
|---|---|
| macOS | `~/Movies/reel-forge/<project>/` |
| Linux | `~/Videos/reel-forge/<project>/` |
| Windows | `%USERPROFILE%\Videos\reel-forge\<project>\` |

`workspace/` can be deleted entirely: it rebuilds from the scripts. `deliveries/` can't.
