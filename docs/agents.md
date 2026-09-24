# Reel Forge agents

> The agent files live in `agents/`. This document is in `docs/` on purpose: every `.md` inside
> `agents/` gets loaded as an agent, and a README in there breaks plugin validation.

Eight subagents that turn a photo and video library into several vertical TikToks/Reels. Each one does a
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
 ┌──────────────────┐                                     ▼                      ▼
 │ trend-researcher │ ──► trends/trends.json      ┌──────────────────┐   ┌──────────────────┐
 │      (xN)        │                             │ chief-editor     │   │ critic-reviewer  │
 └──────────────────┘                             │  selection.json  │   │ (1 per concept)  │
                                                  └──────────────────┘   └──────────────────┘
```

The three material stages and the research run **at the same time**. The rest is sequential: no concepts
without a catalog, no building without a selection, no delivery without a review.

## When to use each one

| Agent | Use it to | Delivers | Instances |
|---|---|---|---|
| `photo-curator` | Choose which photos work out of a batch or a date. Starts from favorites and their neighbours, validates expressions and drops junk | `catalog/catalog-<batch>.json` | 1 per day or per ~150 photos |
| `clip-analyst` | Know which seconds of a clip work and which are filler | `catalog/catalog-<batch>.json` | 1 per video (or per 3-4 short videos) |
| `360-scout` | Pull 9:16 framings out of an equirectangular: sheets, the subject's yaw/pitch, keys and test renders | `catalog/catalog-<batch>.json` + test MP4s | 1 per 360 file |
| `trend-researcher` | Know which formats, hooks and sounds are working **today** for the topic, in the output language's market | `trends/trends.json`, or `trends/trends-<theme>.json` when several run | 1 per theme (formats / sounds / niche), merged into `trends/trends.json` |
| `creative-director` | Propose **one** strong concept with second-by-second structure and 3-4 variants | `concepts/<slug>.json` | 4-8, each with a different angle |
| `chief-editor` | Decide what gets built, protecting variety, and say what to fix | `selection.json` | 1, always |
| `video-builder` | Render the variants, export clean + preview and write the README | MP4 + `build.py` + `spec.json` + `README.md` | **2 per concept**, one variant each |
| `critic-reviewer` | Find concrete defects and **fix them by re-rendering** | `review-<concept>.json` + a corrected MP4 | **1 per concept**, sees all its variants together |

## How to scale the number of instances

The general rule: **parallelize what only looks, serialize what decides.**

- **Catalog (curator, analyst, scout).** Split by the natural unit: a day of photos, one video, one 360
  file. With material from a long trip it's normal to launch 10-20 instances. Start with 4-6 at a time and
  raise it if the machine can take it: the render and `ffmpeg` are what weigh, and several sessions
  competing turn a 3-second photo into minutes.
- **Trends.** 2 or 3 instances: one for formats and hooks, one for sounds with BPM, one for the niche or
  the destination. More than that and they repeat each other.
- **Directors.** This is where the flow's leverage is: **launch 4 to 8, each with a different, explicit
  angle** (narrated documentary, pure natural sound, guide with prices, visual gag, POV, list with a
  payoff, block counter). They can't see each other: the variety comes from the angles you assign, not
  from asking them for "something different".
- **Chief editor: always one.** It's the only one that sees the whole set. Two chief editors contradict
  each other and the variety is lost.
- **Builders: two per concept**, one variant each. A single one with four variants copies itself: it
  changes the copy and keeps the same edit. Two independent ones genuinely diverge. With more variants,
  hand them out in pairs, but **fix the look, the music bed and the 9:16 crops in common** and have them
  all write into the same README. The classic mistake is one builder leaving a `look` the other had
  already rejected, so the hook comes out washed out in half the deliveries.
- **Reviewers: one per concept**, always, even when "it looks fine", and never one of the builders. It has
  to see **all the variants together**: what shows up most often (a `look` that washes out the hook, the
  same shot in two variants) only shows by comparison. It fixes what blocks; if a fix changes the idea, it
  escalates to the chief editor.

When you duplicate instances of any agent, pass it in the invocation: **which batch or angle is its**,
**where it writes**, **which ids are already taken** and, for anything that produces copy, **the output
language tag**. If two write the same file, work gets lost.

## Contracts between agents

- **Resource ids:** `p-###` a photo, `v-<clip>-<letter>` a video range, `r-<clip>-<letter>` a 360 reframe.
  A concept only uses ids that exist in the catalog.
- **Times** in seconds with 2 decimals. A range's times are relative to the start of its file; the 360
  keys' times are relative to the start of the range.
- **Quality and potential** as integers 1 to 10, with the criteria written into each agent.
- **Paths** with `~` or relative to the working folder. Never an absolute path from anyone's machine.
- **Language:** the catalog, the JSON keys and the notes are in English; the on-screen copy, the
  narration and the hashtags are in the run's output language.
- **Nobody invents material.** If something is missing, it goes into `missing`, `pending` or `not_found`.
- Every agent writes its JSON **and** replies with a short text summary: whoever invoked it reads the
  summary, the next agent reads the JSON.

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
| `${CLAUDE_PLUGIN_ROOT}/skills/voices/scripts/voice.py` · `narrate.py` | Local TTS narration and mixing onto an already rendered MP4 |
| `${CLAUDE_PLUGIN_ROOT}/skills/*/SKILL.md` | The long guides: `video-engine`, `video-360`, `voices`, `sources` |
| `${CLAUDE_PLUGIN_ROOT}/skills/reel-forge/references/` | The detail of every phase of the flow |
| `${CLAUDE_PLUGIN_ROOT}/examples/spec-example.json` | The engine's commented spec, valid JSON |

If any of those files gets renamed, update this table and the agents that mention it.

## System dependencies (say them, don't assume them)

- **Apple Photos and its detected faces: macOS only** (read from the library's own database; `osxphotos`
  is only needed to download iCloud originals). On any other system the
  path is a folder of files with EXIF dates and a list of favorites.
- **Insta360 Studio** (macOS/Windows) gives the best 360 stitch. Without it, the plugin does an
  approximate stitch with `ffmpeg v360` and the seam shows on nearby objects.
- **CapCut** for the app's narration voice: macOS/Windows only, with the app installed. Without it, the
  variant ships without voice plus a `voice-script.txt` with the timings.
- **macOS `say`** is not used as a final voice; the plugin's local TTS is cross-platform.
- `ffmpeg`, `ffprobe` and `uv` are always required.

When an agent depends on something that isn't there, it reports it in `warnings` or
`system_dependencies` and carries on down the fallback path. None of them should pretend it did something
it couldn't do.
