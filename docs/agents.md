# Reel Forge agents

> The agent files live in `agents/`. This document is in `docs/` on purpose: every `.md` inside
> `agents/` gets loaded as an agent, and a README in there breaks plugin validation.

Nine subagents that turn a photo and video library into several vertical TikToks/Reels. Each one does a
single thing, takes and returns **JSON**, and can be launched many times in parallel.

Once the plugin is installed they are invoked with the plugin name in front: `reel-forge:photo-curator`,
`reel-forge:clip-analyst`, and so on.

## The flow

```
       material                  catalog                  ideas                   files
 ┌──────────────────┐     ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
 │ photo-curator    │     │                  │   │ creative-director│   │ video-builder    │
 │ clip-analyst     │ ──► │  catalog/*.json  │──►│   (xN parallel)  │──►│   (xN parallel)  │
 │ 360-scout        │     │                  │   └────────┬─────────┘   └────────┬─────────┘
 └──────────────────┘     └──────────────────┘            │                      │
 ┌──────────────────┐                             ┌───────▼──────────┐   ┌───────▼──────────┐
 │ trend-researcher │ ──► trends/trends.json      │ chief-editor     │   │ critic-reviewer  │
 │      (xN)        │                             │  selection.json  │   │ (1 per concept)  │
 └──────────────────┘                             └───────┬──────────┘   └───────┬──────────┘
                                                          │                      │
                                          ┌───────────────▼──────────────────────▼───────────┐
                                          │ story-doctor — PRE on every concept, POST on      │
                                          │ every rendered variant: arc, ending, duration     │
                                          └───────────────────────────────────────────────────┘
```

The three material stages and the research run **at the same time**. The rest is sequential: no concepts
without a catalog, no building without a selection, no delivery without a review.

The `story-doctor` runs **twice**, and both passes gate what follows: nothing is built before it has
read the concept, and nothing ships before it has watched the render. It is the agent that exists for
one complaint — a video that opens something, never develops it and stops mid-air.

## When to use each one

| Agent | Use it to | Delivers | Instances |
|---|---|---|---|
| `photo-curator` | Choose which photos work out of a batch or a date. Starts from favorites and their neighbours, validates expressions and drops junk | `catalog/catalog-<batch>.json` | 1 per day or per ~150 photos |
| `clip-analyst` | Know which seconds of a clip work and which are filler | `catalog/catalog-<batch>.json` | 1 per video (or per 3-4 short videos) |
| `360-scout` | Pull 9:16 framings out of an equirectangular: sheets, the subject's yaw/pitch, keys and test renders | `catalog/catalog-<batch>.json` + test MP4s | 1 per 360 file |
| `trend-researcher` | Know which formats, hooks and sounds are working **today** for the topic, in the output language's market | `trends/trends.json`, or `trends/trends-<theme>.json` when several run | 1 per theme (formats / sounds / niche), merged into `trends/trends.json` |
| `creative-director` | Propose **one** strong concept: an arc that promises, develops and lands, the seconds that story needs, second-by-second structure and 2-5 variants | `concepts/<slug>.json` | 4-8, each with a different angle |
| `story-doctor` | Judge whether the video is **finished**: does the hook promise, is it paid, does the middle develop, does the ending land, and is the duration the one the story needs | `story/<concept>.json` (pre) and `story/<concept>-post.json` (post) | **1 per concept, per pass** |
| `chief-editor` | Decide what gets built, protecting variety, and say what to fix | `selection.json` | 1, always |
| `video-builder` | Render the variants, export clean + preview, and leave the script of the narration | MP4 + `variant.json` + `spec.json` + `result.json` (+ `voice-script.json`) | **2 per concept**, one variant each |
| `critic-reviewer` | Find concrete defects, check the quota the concept declared, and **fix by re-rendering** | `review.json` + the corrected MP4 + the concept's README | **1 per concept**, sees all its variants together |

## How to scale the number of instances

The general rule: **parallelize what only looks, serialize what decides.** The numbers per phase are in
[`../skills/reel-forge/references/agents.md`](../skills/reel-forge/references/agents.md) and the
reasoning in [`parallelism.md`](parallelism.md); they are not repeated here.

Two things that are easy to get wrong and are worth saying twice:

- **Directors: the variety comes from the angles you assign**, not from asking for "something
  different". Eight directors with no angle return eight photo dumps.
- **Chief editor and reviewer are singular.** The editor is the only one who sees every proposal at
  once; the reviewer is the only one who sees every variant of a concept at once. Duplicate either and
  you lose exactly what the step was for.

When you duplicate instances of any agent, pass it in the invocation: **which batch or angle is its**,
**where it writes**, **which schema it writes to**, **which ids are already taken** and, for anything
that produces copy, **the output language tag**. If two write the same file, work gets lost.

## Contracts between agents

Every artifact that crosses from one agent to another has a JSON Schema in
[`../schemas/`](../schemas/README.md), and each agent validates its own file **before answering**:

```bash
uv run "$CLAUDE_PLUGIN_ROOT/schemas/validate.py" <file> --type <contract>
```

| Agent | Writes | Contract |
|---|---|---|
| `photo-curator`, `clip-analyst`, `360-scout` | `catalog/catalog-<batch>.json` | `catalog-item` |
| `creative-director` | `concepts/<slug>.json` | `concept` |
| `story-doctor` | `story/<concept>.json`, `story/<concept>-post.json` | `story-review` |
| `chief-editor` | `selection.json` | its own report; the concepts it cites are `concept` |
| `video-builder` | `<letter>/result.json`, and `voice-script.json` when narrated | `variant-build-result`, `voice-script` |
| `critic-reviewer` | `review.json` | `review-result` |

The conventions the schemas enforce — id format, seconds, 1-5 ratings, paths without anyone's home
directory, English keys with only the on-screen copy in the output language, nothing invented and
nothing deleted — are written once in [`../schemas/README.md`](../schemas/README.md).

Every agent writes its JSON **and** replies with a short text summary: whoever invoked it reads the
summary, the next agent reads the JSON. If the two disagree, the file wins.

## What the plugin lends them

Agents call the plugin's scripts through `${CLAUDE_PLUGIN_ROOT}`, which Claude Code substitutes when it
loads them. **Every script lives under `skills/<skill>/scripts/`; there is no top-level `scripts/`
folder.**

| Path | What for |
|---|---|
| `${CLAUDE_PLUGIN_ROOT}/skills/video-engine/scripts/render.py` | Render engine: JSON spec → 1080x1920 MP4 |
| `${CLAUDE_PLUGIN_ROOT}/skills/video-360/scripts/reframe360.py` | Proxy, perspective sheets, keys and 360 rendering |
| `${CLAUDE_PLUGIN_ROOT}/skills/sources/scripts/inventory.py` | Photo and video inventory (Apple Photos or a folder) |
| `${CLAUDE_PLUGIN_ROOT}/skills/sources/scripts/sheets.py` | Contact sheets, face crops and frame strips |
| `${CLAUDE_PLUGIN_ROOT}/skills/sources/scripts/validate_dates.py` | Metadata report and the corrections plan |
| `${CLAUDE_PLUGIN_ROOT}/skills/sources/scripts/export.py` | Thumbnails and selective export from Apple Photos |
| `${CLAUDE_PLUGIN_ROOT}/skills/video-engine/scripts/verify.py` | The delivery gate: audio, length, black frames, peak, text sync, voice-to-picture and the ending |
| `${CLAUDE_PLUGIN_ROOT}/skills/video-engine/scripts/transcribe.py` | What a clip says, and **when** the narration says each word (`--align`) |
| `${CLAUDE_PLUGIN_ROOT}/skills/voices/scripts/resolve_voice.py` | Which voice narrates this run, and why: Valentino for Spanish, a local engine as the fallback |
| `${CLAUDE_PLUGIN_ROOT}/skills/voices/scripts/voice.py` · `narrate.py` · `capcut_voice.py` | Narration and mixing onto an already rendered MP4 |
| `${CLAUDE_PLUGIN_ROOT}/skills/voices/scripts/sound_map.py` · `wordmarks.py` | A spoken viral audio mapped by phrase, and the words a caption has to land on |
| `${CLAUDE_PLUGIN_ROOT}/skills/sources/scripts/history.py` · `people.py` · `preferences.py` | What has already been published, who is in the library, and what the user keeps asking for |
| `${CLAUDE_PLUGIN_ROOT}/skills/*/SKILL.md` | The long guides: `video-engine`, `video-360`, `voices`, `sources` |
| `${CLAUDE_PLUGIN_ROOT}/skills/reel-forge/references/` | The detail of every phase of the flow |
| `${CLAUDE_PLUGIN_ROOT}/examples/spec-example.json` | The engine's commented spec, valid JSON |
| `${CLAUDE_PLUGIN_ROOT}/schemas/` | The JSON Schemas every agent writes to, and `validate.py` |

If any of those files gets renamed, update this table and the agents that mention it.

## System dependencies (say them, don't assume them)

- **Apple Photos and its detected faces: macOS only** (read from the library's own database; `osxphotos`
  is only needed to download iCloud originals). On any other system the
  path is a folder of files with EXIF dates and a list of favorites.
- **Insta360 Studio** (macOS/Windows) gives the best 360 stitch. Without it, the plugin does an
  approximate stitch with `ffmpeg v360` and the seam shows on nearby objects.
- **CapCut** for the app's narration voice: macOS/Windows only, with the app installed. When the output
  language is Spanish this is the **default** narrator — Valentino at 1.4x, the voice that side of the
  platform actually sounds like. Without CapCut the run falls back to a local engine, which works and is
  reproducible but does **not** sound like the trend, so the variant's README has to say so.
  `resolve_voice.py` makes that call once per run and carries the sentence to disclose in `disclose`.
- **macOS `say`** is not used as a final voice; the plugin's local TTS is cross-platform.
- `ffmpeg`, `ffprobe` and `uv` are always required.

When an agent depends on something that isn't there, it reports it in `warnings` or
`system_dependencies` and carries on down the fallback path. None of them should pretend it did something
it couldn't do.
