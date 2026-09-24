# Reel Forge

A [Claude Code](https://claude.com/claude-code) plugin that turns your photo and video library into
vertical TikToks/Reels/Shorts (1080x1920). Everything runs locally: your material never leaves your
machine.

This is not a template exporter. The plugin **looks at your material** frame by frame, catalogs it
with several agents in parallel, researches which formats and sounds are working right now, proposes
concepts that differ from each other, and renders **several variants of every concept** so you can
compare. Each video is built as a story with an opening, a development and an ending that lands, and
**its length comes from that story**, not from a house default: a gag runs 12 s and a narrated guide
runs 60 s, in the same round.

## What it does

1. **Sources.** Finds your material: Apple Photos on macOS, or any folder on any OS. Reports how many
   pieces there are, from which dates, and whether the originals are on disk or only in the cloud.
2. **Cheap sift.** Drops screenshots, documents, receipts, blurry shots and duplicates before spending
   agents on them.
3. **Catalog with parallel agents.** Each agent gets a batch, **actually looks at it** (contact
   sheets, frame strips, face crops, audio transcription) and returns *moments*: a 40 s clip yields
   3-6 usable seconds, with start and end in seconds.
4. **Trends.** An agent researches formats, hooks, styles and sounds with **measured BPM**, each one
   with its source and date, **for the market of the language you picked**. It never invents
   "trending" songs.
5. **Concepts.** Several creative directors each propose, from their own angle, a concept with a hook
   and a second-by-second structure; a chief editor picks the best ones looking for variety and says
   what to fix before building them.
6. **Story.** A story doctor takes each chosen concept apart into opening → development → **ending**,
   says what is missing for the arc to close, and sets **the seconds each variant needs**, defended
   beat by beat. Its blocking corrections are applied before anything renders.
7. **Build.** One builder per variant: JSON spec → 9:16 render with beat cuts, punch-ins, text inside
   the safe area, audio mix and narration. When there is narration the **voice is generated first** and
   the captions are derived from it word by word, so the text lands on the word being said.
8. **Review.** Two agents on the same files: the story doctor asks whether each variant develops and
   **lands or just stops**, the reviewer hunts concrete defects — black frames, audio gaps, overlapping
   text, captions out of sync, wrong facts, repeated material. Both fix by re-rendering.
9. **Delivery.** A clean 1080p version (no copyrighted music), a preview with the song just so you can
   hear it, a 720p copy for your phone and a README per concept — with each variant's duration and why
   it runs that long. **Nothing reaches the delivery folder without passing `verify.py`**; what cannot
   be made to pass is stated in the README instead of shipped quietly.

An interrupted run (a closed laptop, a dead session) is **picked up, not restarted**: every agent
writes its progress to disk as it goes, and re-running the same command skips whatever is already
finished.

## Five-step demo

```text
# 1. Install the plugin (inside Claude Code)
/plugin marketplace add chrisAlatorre/reel-forge
/plugin install reel-forge@reel-forge
```

```bash
# 2. Check the two required dependencies
ffmpeg -version | head -1 && uv --version
```

```text
# 3. See what material you have and in what shape
/reel-sources --dates 2026-04-10..2026-04-18

# 4. Start the full run
/reel the weekend on the coast, 30 seconds, with narration --lang en

# 5. Claude asks once (material, whether you appear, platform, language),
#    catalogs, proposes concepts and delivers several variants of each in
#    ~/Movies/reel-forge/<project>/deliveries/v1/   (macOS; ~/Videos/... on Linux)
```

If your material is not in Apple Photos, say so in plain language (`/reel something with the dog
clips in ~/Videos/max`) or pin it once and for all:

```bash
export REEL_FORGE_SOURCES="$HOME/Pictures/coast:$HOME/Videos/coast"
```

## On-screen language

The plugin separates **its own language** (it talks to you in whatever language you write in) from
the **output language**: the on-screen text, the captions and the narration of the video itself.
That one is explicit, because it also decides which market the trend research looks at and which
voices are offered.

| How to set it | Example | Scope |
|---|---|---|
| `--lang` flag | `/reel the trip --lang en` | this run only |
| `REEL_FORGE_LANG` env var | `export REEL_FORGE_LANG=es-MX` | this shell |
| `"lang"` in `~/.config/reel-forge/config.json` | `{"lang": "en-US"}` | remembered everywhere |

The value is a BCP-47 tag: `en`, `es`, or with a region when the region matters — `es-MX`, `en-US`,
`pt-BR`. The region is what tells the trend researcher whether to look at TikTok in Mexican Spanish
or TikTok in US English; those are different markets with different sounds.

**The first time**, if nothing is configured, Claude asks once and saves the answer to
`~/.config/reel-forge/config.json`. After that it never asks again unless you pass `--lang` or run
`/reel-voice --lang <tag>`.

What follows the language: the on-screen captions, the narration script, the TTS voice (the voice
list is filtered to voices that actually speak it), the hashtags, and the market the trend research
targets. What does **not**: the file names, the JSON keys of the catalog and the specs, and this
documentation.

## Requirements

| Requirement | What for | Required |
|---|---|---|
| Claude Code | Runs the plugin | Yes |
| `ffmpeg` and `ffprobe` (with `libx264` and `libfreetype`) | All rendering, analysis and verification | Yes |
| [`uv`](https://docs.astral.sh/uv/) | Runs the Python scripts; installs their dependencies by itself | Yes |
| Python 3.10-3.12 | `uv` downloads it if you don't have it | Yes (via `uv`) |
| Material in a folder | Universal source, any OS | One of the two |
| macOS + Apple Photos | Reading your Photos library: favorites, faces, places, local thumbnails. Read straight from the library's database, **no extra tool** | One of the two |
| [`osxphotos`](https://github.com/RhetTbull/osxphotos) | Only to **download** the originals of the chosen material from iCloud (`uv tool install osxphotos`) | Optional |
| ~20 GB free disk | Proxies, frames and downloaded models | Recommended |
| CapCut (macOS) | The app's narrator voice, driven by clicks | Optional |
| Insta360 Studio (macOS, Windows) | Quality stitching of `.insv` files | Optional |
| Local TTS model (downloads itself, ~4 GB) | Narration without paid services | Optional |

**macOS-only paths:** reading Apple Photos, the system voice (`say`), driving CapCut
by clicks and automating Insta360 Studio. On Linux and Windows the plugin works end to end through the
**fallback path**: material from a folder, metadata from EXIF, bundled fonts and narration with the
local TTS (or delivery without voice, so you add it in the phone app).
Details in [`docs/installation.md`](docs/installation.md).

## Installation

The repo is both the plugin and its marketplace, so installing takes two steps: register the
marketplace, then install the plugin.

Inside Claude Code:

```text
/plugin marketplace add chrisAlatorre/reel-forge
/plugin install reel-forge@reel-forge
```

From the terminal, the same thing:

```bash
claude plugin marketplace add chrisAlatorre/reel-forge
claude plugin install reel-forge@reel-forge
```

To develop it locally, the marketplace is the cloned folder:

```bash
git clone https://github.com/chrisAlatorre/reel-forge.git
claude plugin marketplace add ./reel-forge          # local path, not the remote repo
claude plugin install reel-forge@reel-forge
```

Check that it landed:

```bash
claude plugin validate ./reel-forge --strict   # manifests, skills and agents
claude plugin list                             # reel-forge@reel-forge, enabled
claude plugin details reel-forge               # the skills and the 9 agents
```

`claude plugin install` accepts `-s user` (default, all your projects), `-s project` (shared through
git) and `-s local` (this machine only). Per-OS steps and dependency checks in
[`docs/installation.md`](docs/installation.md).

### Updating

```bash
claude plugin marketplace update reel-forge    # pull the new manifest
claude plugin update reel-forge                # install the new version
```

Claude Code checks the marketplace when it starts and tells you in the `/plugin` screen when an
installed plugin has a newer version; it does not upgrade on its own. `claude plugin update` with no
argument updates everything you have installed. What changed in each version is in
[`CHANGELOG.md`](CHANGELOG.md), and the plugin also tells you at the start of a `/reel` run when the
config file it reads was written by an older version.

## Usage

```text
/reel <what you want>
```

Examples:

```text
/reel a recap of the weekend at the beach, 25 seconds, no voice
/reel something funny with the dog clips in ~/Videos/max
/reel the June trip --auto --dates 2026-06-03..2026-06-12 --lang en
```

The command asks **once, up front and all together**: which material, whether you appear and how
much, whether anyone must be kept out, platform and duration, output language and whether you want
narration, and what must not show up. With `--auto` it takes the defaults and tells you which ones.
With `--fast` it drops the analysis resolution to deliver sooner.

| Command | What it does |
|---|---|
| `/reel` | Full run, from sources to delivery |
| `/reel-sources` | Inventories and diagnoses the available material, edits nothing |
| `/reel-trends <topic>` | Researches current formats and sounds and measures the BPM of the candidates |
| `/reel-voice` | Configures and tests the narration voices, and pins your favorite |

## Map of skills and agents

**Skills** (`skills/`): knowledge Claude loads when it reaches that phase.

| Skill | What for |
|---|---|
| `reel-forge` | Orchestrator: the 9-phase flow, the selection rules and where everything is saved. The detail lives in `skills/reel-forge/references/` |
| `sources` | Finding and inventorying material (Apple Photos or any folder), metadata and thumbnails |
| `video-engine` | Render engine: JSON spec → 1080x1920, effects, text and safe area |
| `video-360` | Reframing equirectangular and `.insv` footage to 9:16 with a virtual camera and keyframes |
| `voices` | Narration: local TTS, the CapCut voice, and how to glue it onto an already rendered video |

**Agents** (`agents/`): subagents that run in parallel, each with its own context.

| Agent | How many | What it does |
|---|---|---|
| `photo-curator` | 1 per day or per ~150 photos | Reviews a batch of photos and returns the moments that work, each rated for quality and for hook |
| `clip-analyst` | 1 per video (or per 3-4 short ones) | Watches the video as frame strips, transcribes, and returns ranges with start and end |
| `360-scout` | 1 per clip | Finds the usable framings by yaw/pitch and leaves the camera keys ready |
| `trend-researcher` | 1-3 | Looks for current formats, hooks and sounds in the target language's market, citing source and date |
| `creative-director` | 4-8 | Each proposes **one** strong concept from a different angle, with second-by-second structure |
| `chief-editor` | 1 | Picks the best concepts looking for variety, drops the repeats and says what to fix |
| `story-doctor` | 1 per concept, twice | Before building: the arc and the seconds each variant needs. After rendering: does it develop, does it **land or just stop** |
| `video-builder` | 1 per variant | Writes the builder script and the spec for its variant, generates the voice, syncs the captions to it and renders |
| `critic-reviewer` | 1 per concept | Compares the variants against each other, hunts concrete defects by looking and listening, and **fixes** them by re-rendering |

Once the plugin is installed they are invoked with the plugin name in front:
`reel-forge:photo-curator`, `reel-forge:creative-director`, and so on. The detail of each one is in
`docs/agents.md`.

**Workflows** (`workflows/`): `catalog.js` splits photos, videos and 360 clips across N agents;
`build.js` runs a concept through story → common folder → one agent per variant → arc and craft review
→ fixes. Both read the run ledger first, skip whatever is already finished on disk and write their
progress as they go, so an interrupted run resumes without repeating work.

The **agent count** comes from how much material there is and how much time you have; the table and
its caps are in [`docs/architecture.md`](docs/architecture.md).

## Honest limitations

- **It uploads and publishes nothing.** The plugin hands you files; posting them is on you.
- **Copyrighted music is never embedded.** The clean version ships without the song and a separate
  `-preview` is generated just so you can hear it. You add the official sound in the app, which also
  makes the video count toward that trend.
- **Apple Photos is macOS only.** On other systems you lose favorites, faces and place names from the
  Photos database; the plugin falls back to EXIF and its own detection, which is poorer.
- **Originals in iCloud have to be downloaded.** With an optimized library you only have thumbnails:
  the catalog is built from those and only the chosen material is downloaded in full, which takes time.
- **CapCut and Insta360 Studio are driven by clicks.** They are third-party apps with no API: an
  update can break the flow. There is always a fallback path without them.
- **Stitching `.insv` without Insta360 Studio is approximate.** The seam on nearby objects is not the
  same; for a final delivery, export the flat 360 from Studio and reframe it here.
- **Rendering is local and slow.** A 30 s video can take 3 to 10 minutes counting proxies, analysis
  and verification.
- **The default narrator voice needs CapCut, on macOS.** For narration in Spanish the default is the
  app's viral voice, driven by clicks — so on Linux, on Windows, or without the app, you get the local
  TTS instead, and the concept's README says which voice it used and why. Synthetic voices sound
  synthetic: the local ones do well in neutral Spanish and in English, but a genuinely good voice needs
  a paid service on your own account.
- **Non-Latin scripts need system fonts.** Thai, Chinese and Arabic need fonts with those glyphs and,
  for vowel marks, Pillow built with raqm.
- **Trends expire.** What gets researched today may be useless in a month: they are re-researched on
  every run, never stored as truth.
- **It does not clone real people's voices**, nor generate material that impersonates anyone.

## What needs your permission

| Permission | When it's asked | What for | If you deny it |
|---|---|---|---|
| Photos (macOS: *Privacy & Security → Photos*) | Downloading originals with `osxphotos` | Full-resolution originals that only live in iCloud | Render from the local thumbnails |
| Full Disk Access (macOS) | Reading the Photos database and thumbnails | Contact sheets without downloading originals | Export the material to a folder yourself |
| iCloud download | Downloading the originals of the chosen material | Rendering at full resolution | Renders from thumbnails, at lower quality |
| Automation and Accessibility (macOS) | Driving CapCut or Insta360 Studio | Narration voice and 360 stitching | Local TTS or delivery without voice; 360 with approximate stitching |
| Network access | Researching trends and downloading 30 s previews | Real formats, sounds and BPM | You pick the format and the music yourself (`--no-trends`) |
| Writing to the output folder | Cataloging and rendering | Saving workspace, proxies and deliveries | Nothing runs |
| Running `ffmpeg`, `uv` and the plugin's scripts | Every phase | All the processing | Nothing runs |

The plugin asks for **no** passwords, tokens or accounts. All image, video and audio processing is
local; the only things that reach the internet are the trend searches and the 30 s previews.

Before publishing or deleting anything, the plugin stops and asks.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — the full 9-phase flow and what gets handed between phases.
- [`docs/parallelism.md`](docs/parallelism.md) — how many agents to launch and what is **not** parallelized.
- [`docs/agents.md`](docs/agents.md) — the nine agents, their contracts and how to scale each one.
- [`docs/installation.md`](docs/installation.md) — per-OS installation, updates and dependency checks.
- [`docs/configuration.md`](docs/configuration.md) — environment variables, the config file and the output language.
- [`docs/updating.md`](docs/updating.md) — publishing a version, how it reaches people who already installed it, versioning and changelog.
- [`docs/status.md`](docs/status.md) — what is actually tested, what is theoretical and what comes next.
- `skills/reel-forge/references/` — the detail of each phase, which Claude reads when it gets there.

## License

MIT. See [`LICENSE`](LICENSE).

**The repo ships no fonts, music or sound effects.** The typefaces (Montserrat and Instrument Serif,
SIL OFL 1.1), the base map (Natural Earth, public domain) and the segmentation model (Apache-2.0) are
downloaded by `skills/video-engine/scripts/resources.py` into `$REEL_FORGE_CACHE`, each with its
license alongside. Sound effects are yours to put in `$REEL_FORGE_ASSETS/sfx/`.
