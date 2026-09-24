---
description: Inventories and diagnoses the available photo and video sources - how many pieces there are, from which dates, whether the originals are local or in the cloud, and what metadata problems they carry.
argument-hint: "[--dates YYYY-MM-DD..YYYY-MM-DD] [--source PATH] [--detail] [--json]"
---

# /reel-sources — what material exists and what shape it's in

Arguments received: `$ARGUMENTS`

A **read-only diagnostic** command. It edits nothing, exports nothing, downloads nothing from the
cloud and never touches EXIF. Use it to know what you're working with before running `/reel`, and to
understand why something isn't showing up.

| Flag | Effect |
|---|---|
| `--dates A..B` | Limits the inventory to that range |
| `--source PATH` | Only that folder or library |
| `--detail` | On top of the summary, a per-day list with camera and count |
| `--json` | Writes the inventory to `inventory.json` as well as printing the summary |

## Skills and agents

- Main skill: `reel-forge:sources` (detection, metadata reading, counts). The work is done by
  `${CLAUDE_PLUGIN_ROOT}/skills/sources/scripts/inventory.py` and
  `${CLAUDE_PLUGIN_ROOT}/skills/sources/scripts/validate_dates.py`.
- Support: `reel-forge:video-360`, only to identify 360 material (`.insv`, `.insp`, 2:1
  equirectangulars) and tell whether it is local or still in the camera's cloud.
- **Agents: normally none.** This is a fast, sequential command. Scale it like this:

| Situation | Agents |
|---|---|
| Fewer than 4 sources, any size | 0 — do it directly |
| 4+ sources, or slow external volumes | 1 agent per source, max 4, each returning its block of the inventory |
| A library of more than ~50,000 pieces | 1 extra agent just for the per-year metadata sweep |

Never more than 5 agents here: reading metadata is I/O, and more parallel processes make it slower,
not faster.

## What to check

### 1. The system's native library
- **macOS (Apple Photos):** read straight from the library's database, no extra tool. Gives counts, dates,
  favorites, people and whether the original is downloaded or cloud-only, without opening the app.
  Default library at `~/Pictures/Photos Library.photoslibrary`, or wherever `REEL_FORGE_LIBRARY`
  points. **macOS only.**
- **Not macOS:** there is no native library to inventory. Say so plainly and carry on
  with folders. Don't invent an equivalent.

### 2. Folders
Check whichever exist and report each one separately:
`~/Pictures`, `~/Movies` or `~/Videos`, `~/Desktop`, `~/Downloads`, plus any mounted external volume
with a `DCIM/` directory.

### 3. 360, action and drone cameras
- **360:** `.insv` / `.insp` files. If the camera's desktop app is installed (**macOS or Windows**),
  part of the material may live **only in the manufacturer's cloud** and show up as a thumbnail with
  no original. Report it as "in the cloud, needs downloading" and estimate the size: these files are
  big.
- **Action:** `GX######.MP4`, `GOPR####.MP4`, plus the `.LRV`/`.THM` files alongside them (those are
  useless for editing, don't count them as material).
- **Drone:** `DJI_####.MP4`, and the `_D` ones are usually a flat D-Log profile that needs grading
  before use.

### 4. Configuration
`~/.config/reel-forge/config.json` if it exists, and the `REEL_FORGE_SOURCES`, `REEL_FORGE_LIBRARY`,
`REEL_FORGE_HOME`, `REEL_FORGE_OUTPUT` and `REEL_FORGE_WORKSPACE` variables. Whatever they say wins
over automatic detection.

## What to report

One table per source:

| Source | Photos | Videos | Date range | Originals | Size |
|---|---|---|---|---|---|
| System library | 12,480 | 640 | 2019-03 → today | 2,100 cloud-only | ~310 GB |
| ~/Pictures/camera | 820 | 0 | 2024-06 → 2024-09 | local | 9 GB |
| External volume (DCIM) | 0 | 37 | 2024-08 | local | 61 GB |

And below it, a **diagnostics** block with whatever is going to get in the way:

- **Suspicious dates:** groups with a factory date (1970, 2000-01-01) or years outside the rest. Say
  how many, from which camera, and what the real date looks like based on proximity to correctly
  dated material.
- **No location:** how many and from which camera. It can be inferred later from temporal proximity.
- **No EXIF:** files that went through a messaging app; only the filesystem date is left, and that is
  not trustworthy.
- **Time-zone drift:** when the time in the file name and the time in the library disagree. It can
  shift a whole day.
- **Duplicates and bursts:** how many groups, so curation later picks one per group.
- **Formats that need converting:** HEIC (many video tools can't open it directly), phone HDR, drone
  D-Log, 360 `.insv`.
- **Free disk space.** Rule of thumb: below ~20 GB you have to work with proxies; below ~5 GB you
  can't download anything from the cloud.

Close with a two- or three-line recommendation: which range has enough material for a video, what
should be downloaded or corrected first, and whether `/reel` should be run as is or with `--source`.

## What this command does NOT do

- It downloads no originals from any cloud (that's `/reel`, and only for the chosen material).
- It does not fix dates or write EXIF.
- It does not look at the photos one by one: that is curation, and it belongs to `/reel`.
- It does not open the camera apps. If they're needed, it says so and waits for the user to decide.
