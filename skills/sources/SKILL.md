---
name: sources
description: Finds, inventories and validates the material (photos and videos) a reel will be made from, works out who is in it with or without Apple Photos, and keeps the user's learned preferences and published history. Reads the macOS Photos app read-only, plain folders on any system, and 360 camera material. Use it at the start of any reel-forge project, before researching trends or editing anything, and again whenever the user corrects something or says they published.
---

# Material sources and metadata

This skill answers five questions, in this order:

1. **What's there?** How many photos and videos, from which dates, from which places, with whom.
2. **Is the metadata usable?** If the dates are broken, everything else (grouping into sessions,
   ordering the story, putting a place on screen) comes out wrong.
3. **What has to be downloaded?** How big it is and what is cloud-only.
4. **Who is in it?** Named people when the Photos app has them, and face grouping from the images
   themselves when it doesn't ([`people.py`](#who-is-in-the-material-without-apple-photos)).
5. **What do we already know about this user?** What they have corrected before and what they have
   published ([`preferences.py`](#preferences-that-learn), [`history.py`](#what-got-published-and-how-it-did)).

It never writes into the Photos library and never modifies original files. The only thing it writes
outside the project is the user's own preferences and publishing history, in `~/.config/reel-forge/`.

## First thing

```bash
S="$CLAUDE_PLUGIN_ROOT/skills/sources/scripts"
uv run "$S/preferences.py"    brief                                        # what this user already told us
uv run "$S/facts.py" --project <project> brief                            # what is true about THIS project
uv run "$S/inventory.py"      --from 2026-08-01 --to 2026-08-20 --summary -o inventory.json
uv run "$S/validate_dates.py" --from 2026-08-01 --to 2026-08-20 --plan corrections.json
```

`preferences.py brief` goes first and costs nothing: it prints a handful of lines that belong in the
prompt of every agent that decides anything. Skipping it is how a run repeats a mistake the user
already corrected once.

The first says what's there. The second produces the report the user has to confirm. **Don't move on
to the rest of the pipeline until the dates are settled**: if a batch says 2014 and the trip was in
2026, the video's timeline comes out scrambled and you don't notice until the render.

`uv run` installs the dependencies by itself (Pillow and pillow-heif, about 30 MB the first time). The
scripts live in `skills/sources/scripts/` and share `sources.py`.

## The sources

| Source | How you ask for it | Where it runs | What it gives |
|---|---|---|---|
| macOS Photos app | `--source photos` (default) | **macOS only** | dates with time zone, GPS already resolved to place names, favorites, faces and named people, local thumbnails, whether the original is downloaded |
| A plain folder | `--source folder:~/Pictures/Trip` | any system | date and GPS from EXIF, duration and size, all local |
| 360 camera | see the section below | mixed | whatever is possible; part of it needs the user |

Without `--source`, macOS uses the Photos app plus whatever folders are in `REEL_FORGE_SOURCES`
(colon-separated). Outside macOS, only those folders, and if none is configured the script says so
instead of guessing.

They can be combined, and `--source` is repeatable:

```bash
uv run "$S/inventory.py" --from 2026-08-01 --to 2026-08-20 \
  --source photos \
  --source folder:~/Pictures/Insta360 \
  --summary -o inventory.json
```

---

## Apple Photos (macOS)

### The database is read, read-only

The Photos app keeps everything in `~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite`
(if the user's library is elsewhere, pass `--source photos:/path/lib.photoslibrary` or export
`REEL_FORGE_LIBRARY`).

It gets opened like this, and only like this:

```python
sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
```

- `mode=ro`: SQLite doesn't even ask for write permission.
- `immutable=1`: it promises nobody is changing the file, so SQLite **doesn't read the WAL and doesn't
  create lock files**. It's the only combination where it is impossible to damage the library even with
  the Photos app open.

The price of `immutable=1` is that changes from the last few minutes (a photo just imported, a favorite
just starred) may not show up yet, because they live in `Photos.sqlite-wal`. When that matters,
`--copy-db` copies `Photos.sqlite` + `-wal` + `-shm` to a temporary folder and reads the copy:
up to date, but the database can be several GB.

### Permissions

The first read fails with `unable to open database file` if the process doesn't have **Full Disk
Access**:

> System Settings → Privacy & Security → Full Disk Access → add the app you're running this from
> (Terminal, iTerm, Claude Code, VS Code…) and **restart it**.

macOS shows no dialog that can be accepted from a remote session: if the user is on their phone,
somebody has to accept it physically on the Mac. Tell them instead of retrying.

### Tables that matter

| Table | What for |
|---|---|
| `ZASSET` | one row per photo or video: date, GPS, size, duration, favorite, hidden, trashed |
| `ZADDITIONALASSETATTRIBUTES` | time zone, original file name, size in bytes, reverse geocoding |
| `ZDETECTEDFACE` | every detected face, with its position and quality |
| `ZPERSON` | the people the user has already named |
| `ZINTERNALRESOURCE` | which versions are downloaded and which live only in iCloud |

The details of the columns, the traps and example queries are in
[`photos-reference.md`](photos-reference.md). What always has to be kept in mind:

- **Dates are Core Data**: seconds since 1 January 2001 UTC.
  `datetime(ZDATECREATED + 978307200, 'unixepoch')` gives UTC. The wall-clock time of the place (the one
  the user remembers) is that plus `ZTIMEZONEOFFSET`. If you put a date on screen in the video, use the
  local time of the place, not UTC: between two distant zones there are 12-15 hours and a whole day
  slips through.
- **`ZFAVORITE = 1`** marks the favorites. It's the cheapest and most honest signal of what the user
  liked: when picking shots where they appear, start there and then widen to anything within ±10 minutes.
- **`ZDETECTEDFACE.ZCENTERY` is inverted** (0 at the bottom, 1 at the top). To crop a face over an image
  of height `H`: `y = (1 - ZCENTERY) * H`, `x = ZCENTERX * W`, side = `ZSIZE * max(W, H)`. Do it the
  right way up and your crops come out of the feet instead of the face.
- **`ZTRASHEDSTATE = 0`** always, or you end up including photos the user already deleted.

### Thumbnails: reviewing without downloading anything

Photos already generated a thumbnail for every asset, and it's on disk even if the original is
iCloud-only:

```
<library>/resources/derivatives/<first letter of the UUID>/<UUID>_1_105_c.jpeg
```

They're about 1200 px on the long side: more than enough for contact sheets, for checking expressions
and for cropping faces. Videos leave a `.THM` with the cover frame.

```bash
uv run "$S/export.py" --thumbnails --ids chosen.txt --dest ./contacts
```

**This is the right path:** review everything with thumbnails, decide, and only then download the
originals of the chosen ones. Downloading first and deciding later can mean 100 GB of network traffic
to use 30 files.

### Downloading the chosen originals

With [osxphotos](https://github.com/RhetTbull/osxphotos):

```bash
uv tool install osxphotos          # lands in ~/.local/bin/osxphotos
osxphotos --version
```

And to export only what was chosen:

```bash
uv run "$S/export.py" --export --ids chosen.txt --dest ./originals --dry-run
uv run "$S/export.py" --export --ids chosen.txt --dest ./originals
```

which underneath runs:

```bash
osxphotos export ./originals \
  --uuid-from-file chosen.txt \
  --download-missing --use-photokit \
  --skip-original-if-edited --export-by-date \
  --report ./originals/_report.csv --retry 3
```

- `--uuid-from-file`: one UUID per line. That's what makes it download 30 files instead of the entire
  library.
- `--download-missing --use-photokit`: without these, files that only exist in iCloud export empty or
  don't export at all. PhotoKit is the only thing that genuinely asks iCloud for the file, and it only
  works on macOS.
- `--dry-run` first, always: it reports how many are missing (`missing: N`) without using the network.
- This is slow because of the network, not the CPU. With hundreds of videos, warn the user before
  starting.

Watch out: **the exported file name carries the local time of the place** where it was taken, and the
database stores the instant in UTC. Don't mix the two when naming folders.

---

## Plain folders (any operating system)

```bash
uv run "$S/inventory.py" --source folder:~/Pictures/Trip --from 2026-08-01 --summary
```

It walks recursively (`--no-recursion` for the top level only), ignores hidden files and anything that
isn't a photo or a video, and pulls metadata with whatever is installed:

| Tool | What for | If it's missing |
|---|---|---|
| Pillow + pillow-heif | EXIF from JPEG, PNG, TIFF, HEIC | installed automatically by `uv run` |
| `ffprobe` (ships with ffmpeg) | duration, resolution, date and GPS of video | `brew install ffmpeg` · without it there is no video duration |
| `exiftool` | odd formats: `.insv`, `.dng`, `.360` | `brew install exiftool` · enabled with `--exiftool` |

The order it looks for the date, most to least trustworthy:

1. `DateTimeOriginal` from EXIF (or `creation_time` / `com.apple.quicktime.creationdate` on video).
2. The date inside the **file name**: `IMG_20260815_143012.jpg`, `PXL_20260815_203012345.jpg`,
   `VID_20240115_180230_00_012.insv`, `2026-08-15 14.30.12.jpg`.
3. The file's `mtime`. **This one gets flagged as suspicious**, because copying with `cp` or pulling
   from an external drive rewrites it.

GPS comes from EXIF (`GPSLatitude`/`GPSLongitude`) or from Apple's `ISO6709` tag in `.mov` files. In
folders **there are no place names**: the pretty name ("Oaxaca, Mexico") only comes from the Photos app,
which already did the reverse geocoding. If the material comes from a folder and you need names, either
geocode separately or ask the user.

---

## 360 cameras and other clouds

What can be automated and what can't, said plainly.

### Insta360 (Studio, macOS and Windows)

| Thing | Automatable? |
|---|---|
| Listing the `.insv` files already on disk | **Yes.** They're ordinary files: `--source folder:~/Movies/Insta360`. `exiftool` gets the date and sometimes GPS out of them. |
| Seeing what's in the cloud without downloading it | **Partly.** Studio leaves 2:1 equirectangular thumbnails in its support folder; they're enough to choose from. On macOS: `~/Library/Application Support/Insta360/Insta360 Studio/account_info/thumbnail/cloud_cache/`. That path changes between versions: verify it before trusting it. |
| Downloading from the cloud | **No.** There is no public API and no CLI. The user has to open Studio and download them, or connect the camera by cable. |
| Stitching and exporting flat | **Not from the shell.** Studio has no CLI. The free alternative is [insv-stitch](https://github.com/BenjaminHenriksson/insv-stitch); the stitch ffmpeg does with `v360` treats each lens as an ideal fisheye and the seam shows on nearby objects. |

In practice: **ask the user to export from Studio whatever they want to use** (flat 360, horizon already
levelled) into a folder, and from there on it's an ordinary folder. An `.insv` file is heavy; don't
download it "just in case".

### Google Photos, iCloud web, Dropbox and the rest

- **Google Photos**: the Library API no longer lets a third-party app read a user's whole library. The
  real path is **Google Takeout**, which the user requests and downloads themselves; you get a ZIP with
  the files and a `.json` per photo carrying date and GPS. Once unzipped it's an ordinary folder.
- **iCloud on the web**: no API. On macOS the right way is the Photos app (above).
- **Dropbox, Drive, an external disk**: if they're mounted, they're ordinary folders. Watch out for
  "cloud-only" folders (Drive File Stream, iCloud Drive with "Optimize Storage"): the file looks like
  it exists but reading its EXIF triggers a download. When a scan is suddenly glacial, that's why.

General rule: if a source can't be read without going through its app, say what the user has to do, in
one concrete step, instead of inventing a fragile detour.

---

## Metadata validation

This is the part that prevents the most problems. `validate_dates.py` looks for five things:

| Case | What it is | Proposal |
|---|---|---|
| `no_date` | No EXIF, no date in the name, nothing | Assign one by hand |
| `impossible_date` | Year before 2000 (`--min-year`) or in the future | Move the group to the real day |
| `distant_batch` | A group that is coherent internally but more than 180 days (`--far-days`) from the material's median | An even offset in days, already computed |
| `mtime_only` | The date comes from the filesystem, which gets rewritten on copy | Review |
| `time_offset` | Two cameras from the same day with times shifted by an almost whole number of hours | An offset in hours, already computed |

The classic case is the external camera (GoPro, Insta360, DSLR) that lost its clock battery and started
at 2014 or 1970: its files are coherent with each other, they're just shifted as a block.

### What the report looks like

```
METADATA REPORT
============================================================
1,284 files · 2026-08-01T09:12:03-05:00 → 2026-08-14T22:41:19-05:00 (14 days)
GPS 91.4% · faces 38.2% · 27 sessions
Places: Oaxaca de Juárez, Mexico (412) · Puerto Escondido, Mexico (338) · Hierve el Agua, Mexico (96)

2 things to confirm:

[1] Impossible date  (120 files)
  120 files with an impossible date (years 2014). Typical of an external camera with a dead clock battery.
    - GOPR0142.MP4 → 2014-01-01T00:04:11
    - GOPR0143.MP4 → 2014-01-01T00:07:52
    - GOPR0144.MP4 → 2014-01-01T00:11:30
    … and 117 more
  Proposal: assign them a date by hand (it can't be guessed)
  What it means: Almost always an external camera that lost the time. If the rest of the
  batch is fine, the right move is to shift that group to the real day.
  Accept: --case impossible_date --accept

[2] Time-zone offset  (63 files)
  The DJI* files run ~-5 h against the IMG* files from the same day. Usually the camera's
  time zone.
    - DJI_0031.JPG → 2026-08-06T04:22:10-05:00
    - DJI_0032.JPG → 2026-08-06T04:23:44-05:00
  Proposal: shift the group +5 h
  What it means: Two cameras from the same day with shifted clocks. If you're going to
  interleave their shots in one video, they have to be matched up or the edit comes out scrambled.
  Accept: --case time_offset --accept

Nothing gets modified until you confirm. The corrections live in the JSON
plan; the original files and the Photos app are untouched.
```

**Show this report to the user and wait for their answer.** Don't accept proposals on their behalf: a
wrong offset reorders the entire video.

### Confirming

```bash
# accept the offset the script computed
uv run "$S/validate_dates.py" --plan corrections.json --case time_offset --accept

# set a date by hand for a whole case
uv run "$S/validate_dates.py" --plan corrections.json --case impossible_date --date 2026-08-06T10:00

# or your own offset
uv run "$S/validate_dates.py" --plan corrections.json --case distant_batch --offset-days 4380
uv run "$S/validate_dates.py" --plan corrections.json --case time_offset --offset-hours 5

# mark it reviewed without correcting
uv run "$S/validate_dates.py" --plan corrections.json --case mtime_only --discard
```

Everything ends up in `corrections.json`, which looks like this:

```json
{
  "version": 1,
  "created": "2026-08-22T18:04:11-05:00",
  "corrections": [
    {
      "ids": ["GOPR0142.MP4", "GOPR0143.MP4"],
      "action": "offset_days",
      "value": 4600,
      "note": "case impossible_date",
      "confirmed": "2026-08-22T18:05:02-05:00"
    }
  ]
}
```

The rest of reel-forge reads that file with `validate_dates.apply_plan(items, plan)` and works with the
corrected dates. **The original files and the Photos app do not change.**

If you genuinely have to rewrite the EXIF of files in a folder:

```bash
uv run "$S/validate_dates.py" --source folder:~/Pictures/Trip \
  --plan corrections.json --apply-exiftool          # shows what it would do
uv run "$S/validate_dates.py" --source folder:~/Pictures/Trip \
  --plan corrections.json --apply-exiftool --yes    # does it
```

It only touches files from a `folder` source, never the Photos app, and exiftool leaves an `_original`
backup next to each file. To change a date inside Photos, the user does it in the app:
select → **Image → Adjust Date and Time**.

### Sessions

A gap of more than 90 minutes opens a new "session" (`--gap-min`). It's the natural unit of a trip: a
meal, a walk, a sunset. It's far more useful than calendar days for structuring the reel, because a day
with 400 photos is really six different moments.

---

## `inventory.py`: the JSON

```bash
uv run "$S/inventory.py" --from 2026-08-01 --to 2026-08-14 \
  --source photos --source folder:~/Pictures/GoPro \
  --summary -o inventory.json
```

Output (trimmed, with sample data):

```json
{
  "generated": "2026-08-22T18:02:44-05:00",
  "requested_range": { "from": "2026-08-01", "to": "2026-08-14" },
  "sources": [
    {
      "type": "apple-photos",
      "library": "~/Pictures/Photos Library.photoslibrary",
      "read_mode": "mode=ro&immutable=1",
      "wal_warning": "With immutable=1 the WAL isn't read: changes from the last few minutes may be missing. Use --copy-db if you just imported or starred something.",
      "items": 1164
    },
    {
      "type": "folder",
      "root": "~/Pictures/GoPro",
      "ignored_files": 3,
      "tools": { "ffprobe": true, "exiftool": true },
      "items": 120
    }
  ],
  "counts": {
    "total": 1284,
    "photos": 1041,
    "videos": 231,
    "material_360": 12,
    "favorites": 143,
    "screenshots": 8
  },
  "actual_range": {
    "first": "2026-08-01T09:12:03-05:00",
    "last": "2026-08-14T22:41:19-05:00",
    "days": 14
  },
  "gps": { "with_gps": 1174, "pct": 91.4, "without_gps": 110 },
  "places": [
    { "place": "Oaxaca de Juárez, Mexico", "n": 412,
      "first": "2026-08-01T09:12:03-05:00", "last": "2026-08-05T23:10:44-05:00" },
    { "place": "Puerto Escondido, Mexico", "n": 338,
      "first": "2026-08-06T07:41:12-05:00", "last": "2026-08-11T19:55:01-05:00" }
  ],
  "faces": {
    "with_faces": 490, "pct": 38.2,
    "people": [
      { "name": "Ana Reyes", "photos": 212 },
      { "name": "Luis Mena", "photos": 87 }
    ]
  },
  "video": { "clips": 243, "total_duration_s": 8742.6, "total_duration_min": 145.7 },
  "sessions": {
    "gap_min": 90,
    "total": 27,
    "list": [
      { "session": 1, "start": "2026-08-01T09:12:03-05:00", "end": "2026-08-01T11:48:20-05:00",
        "duration_min": 156.3, "n": 74, "photos": 68, "videos": 6, "favorites": 9,
        "with_faces": 31, "place": "Oaxaca de Juárez, Mexico" }
    ]
  },
  "date_suspicions": [
    {
      "case": "impossible_date",
      "n": 120,
      "ids": ["GOPR0142.MP4", "GOPR0143.MP4"],
      "examples": ["GOPR0142.MP4 → 2014-01-01T00:04:11"],
      "years": [2014],
      "message": "120 files with an impossible date (years 2014). Typical of an external camera with a dead clock battery.",
      "proposal": { "action": "assign_date", "value": null }
    }
  ],
  "download": {
    "local_originals": 402,
    "missing": 882,
    "estimated_bytes": 41234567890,
    "estimated_gb": 38.4,
    "accuracy": "exact",
    "with_local_thumbnail": 1150
  },
  "warnings": []
}
```

Notes on the JSON:

- `actual_range` may not match `requested_range`: that's where you see the user got the dates wrong.
- `download.accuracy` says `"exact"` when every size came from the database, or
  `"approximate (N without a size in the database)"` when some had to be estimated (4 MB per photo,
  90 MB per video, 400 MB per 360 file).
- `with_local_thumbnail` is how many can be reviewed **without downloading anything**. If that number
  is high, start there.
- `--include-items` adds the full file list. It's heavy, but it's what the next pipeline step consumes.
- `--full-sessions` adds the ids of each session.

### Flags you'll use often

```bash
--favorites-only          # only ZFAVORITE=1: what the user already liked
--person "Ana Reyes"      # only where Photos recognized that person
--no-screenshots          # drop screenshots
--include-hidden          # include the Hidden album (off by default)
--copy-db                 # read the copy with the WAL: up to date, slower
--gap-min 45              # finer sessions
--exiftool                # fallback for odd formats in folders
```

To find out who you can filter on:

```bash
uv run python -c "import sources, json; print(json.dumps(sources.library_people(minimum=20), ensure_ascii=False, indent=2))"
```

---

---

## `framecheck.py`: what is in the rectangle

Curation answers two questions and only writes down the easy one. *What was happening* goes into
`description` and is usually right. *What the frame actually looks like* is the one nobody checks,
and it is the one that ships a bad shot.

```
FC="uv run ${CLAUDE_PLUGIN_ROOT}/skills/sources/scripts/framecheck.py"
$FC PHOTO.jpg
$FC CLIP.MOV --from 9.6 --to 13.0
$FC A.jpg B.jpg C.MOV                               # several at once: the models load once
$FC --catalog workspace/catalog/catalog.json --apply   # the whole catalog, ~3 s a moment
```

**Catalog mode is how it normally runs**: the catalog workflow calls it right after the merge. With
`--apply` it writes `obstructions` back only for the case that is never a judgement — bodies near the
lens under the subject — and caps that item's `quality` at 2 with the reason in `notes`. What is a
judgement (a lone window edge: a bullet train with the country going past is a good shot) goes only
into `catalog.framecheck.json` beside the catalog, for the directors to weigh. Frames are read at
1280 px tall, since every measurement is a share of the frame; on 4K sources that took it from ~14 s
to ~3 s a moment with identical verdicts.

It judges the **9:16 crop**, which is what will be seen rather than what was shot, and it reads
frames through **ffmpeg**, not OpenCV, because a phone stores a vertical video as a horizontal
stream plus a rotation flag — reading it the other way measures the middle of the wrong picture.
It fills `obstructions` on the catalog item, and the schema then requires `notes` and caps
`quality` at 2.

| It reports | Which means |
|---|---|
| `people_by_third` | share of each horizontal third that is a person, **from any angle**. A face detector does not see the back of a head, and the shot this exists for is two strangers with their backs to the lens. |
| `crossing_lines` | long straight edges cutting the picture: window mullions, bars, door jambs. |
| `haze`, `contrast` | veiling glare and flatness. |
| `clear_band` | tallest band of height with nothing blocking in it. |
| `findings` | the shortlist worth arguing about. Empty means nothing stood out. |

**`haze` never speaks on its own, and that is a measured decision, not caution.** Across real
material it does not separate dirty glass from real weather: a misty seascape scores 0.47 and the
dirty boat window 0.39. It only becomes a finding once something else establishes there *is* glass
— an edge cutting the frame, or bodies right under the lens. The two signals that do discriminate
are people in the bottom third and a crossing edge.

It reports; it never gates and never deletes. A shot through a bullet-train window with the country
going past is a good shot; the same technique over the one thing the caption names is not. That
difference is a judgement, and the point of the numbers is that the judgement gets made with them.

---

## Who is in the material, without Apple Photos

Apple Photos hands over `faces` and `people` for free, and `--person "Ana Reyes"` filters on them.
Outside macOS that information does not exist, and inside macOS it is empty for anybody the user
never named. [`people.py`](scripts/people.py) works it out from the images themselves, on any system.

```bash
uv run "$S/people.py" models --download                     # once: ~230 KB + ~39 MB of models
uv run "$S/people.py" detect  inventory.json --out workspace/people/faces.json
uv run "$S/people.py" cluster workspace/people/faces.json \
    --out workspace/people/clusters.json --sheets workspace/people/sheets
uv run "$S/people.py" match   workspace/people/faces.json \
    --reference ~/Pictures/refs/1.jpg --reference ~/Pictures/refs/2.jpg \
    --out workspace/people/subject.json
uv run "$S/people.py" pick    workspace/people/subject.json --out chosen.txt
```

It takes the same input as `sheets.py` (an `inventory.py` JSON, a folder, or loose paths) and **the
numbering matches `sheets.py contact` over the same list**, so "number 14" means one thing across
both. If an item carries a Photos thumbnail, that is what gets read: nothing is downloaded.

### The two questions, and which one to ask

| The user's question | Command | What it needs |
|---|---|---|
| "How many different people are in this trip, and which one is me?" | `cluster` | nothing but the material |
| "Which shots am *I* in?" | `match` | **2-3 reference photos of the subject** |

**`match` is the accurate one, and it is the one to steer the user to**: ask them for two or three
clear, front-lit photos where their face is large and unobstructed, preferably from different days.
One reference works and the script says so, but the hit rate drops noticeably. `cluster` is for when
there is nobody to ask: it groups the faces and produces one sheet of crops per group
(`workspace/people/sheets/c-01.jpg`), and **the user says which group is the subject**. The biggest
group is usually them and sometimes their partner; do not decide it on your own.

`pick` turns either report into a one-line-per-item file. What it writes depends on where the
material came from, because the two paths need different things: **Photos uuids** when the list came
from the library, which is what `export.py --export --ids` consumes, and **file paths** when it came
from a folder, because there the item ids are positions in a list and mean nothing on their own.
`--write ids` / `--write paths` forces one, and forcing `ids` on folder material warns that
`export.py` will find nothing.

### Backends, in the order the script picks them

| Backend | Detection | Embeddings (grouping) | Where it comes from |
|---|---|---|---|
| **YuNet + SFace** (default) | good, with the 5 landmarks | yes | ONNX from the OpenCV Zoo, downloaded once into `$REEL_FORGE_MODELS` |
| MediaPipe | good | **no** | only if installed: `uv run --with mediapipe people.py detect …` |
| Haar cascade | weak | **no** | always there, bundled with OpenCV |

Without embeddings there is nothing to group or compare: `cluster` and `match` stop with the exact
command to fix it. Measured on a 10-photo folder of ~960 px JPEGs: YuNet found 20 faces in all 10
files, the Haar cascade found 13 in 9 of them. That gap is the whole reason the download exists.

### Thresholds and speed

- `--threshold` is cosine similarity between embeddings; the default **0.363** is SFace's own
  recommendation for "same person". Raise it to 0.45 when the group is picking up a sibling; lower it
  to ~0.30 when the subject wears sunglasses or a beard appears mid-trip, then check the sheet.
- `--min-area` (default 0.15 % of the frame) drops the crowd in the background. Raise it to 1.0 when
  everything on the street is being detected.
- `match` also reports a **borderline** band just under the threshold. That band is where profile
  shots, sunglasses and relatives live: show it to the user instead of guessing.
- Grouping compares every pair. Measured: 1,500 faces group in ~2 s, 3,000 in ~17 s, and memory grows
  with the square. `--max-faces` (default 1,500) stops it before it gets silly; narrow the list to a
  day, a session or the favourites instead of raising it.

### Honest limits of this path

- It is **face** recognition, not person recognition: a shot from behind, a helmet, a full-face mask
  or a face smaller than the threshold is simply not found. For a trip full of back-of-the-head and
  drone shots, expect a low hit rate and say so.
- Close relatives, and especially twins, land in one group at the default threshold.
- Children change enough between trips that photos a year apart may not match.
- Sunglasses, heavy backlight, motion blur and small faces all cost accuracy, in that order.
- Nothing here is as good as what Apple Photos already computed. **On macOS with a library where the
  user has named people, use the Photos path** (`--person`) and keep this one for folders, for other
  systems, and for people the user never named.
- Face embeddings are **biometric data**. They are written to the `--out` path inside `workspace/`,
  never to `~/.config/reel-forge/`, and they never leave the machine. They are not copied into a
  delivery, a README or a file name, and deleting the workspace deletes them.
- The models are downloaded from the OpenCV Zoo on GitHub the first time. On a machine with no
  network, download them elsewhere and point `$REEL_FORGE_YUNET` / `$REEL_FORGE_SFACE` at the files.

---

## Preferences that learn

A user corrects the same thing twice and the second time is on us. Every correction goes into

```
~/.config/reel-forge/preferences.json          # $REEL_FORGE_CONFIG_DIR overrides the folder
```

through [`preferences.py`](scripts/preferences.py), and comes back into the next run through
`preferences.py brief`.

```bash
uv run "$S/preferences.py" show                                     # everything stored
uv run "$S/preferences.py" brief                                    # the block for an agent prompt
uv run "$S/preferences.py" get presence
uv run "$S/preferences.py" set presence low
uv run "$S/preferences.py" set voice "<the voice they asked for>"   # the default when narrated
uv run "$S/preferences.py" set length dynamic                       # the concept sets the length
uv run "$S/preferences.py" add voices.rejected "over-bright newsreader"
uv run "$S/preferences.py" add-rule "no arms-crossed poses" --kind avoid --topic pose
uv run "$S/preferences.py" rm-rule r-003
uv run "$S/preferences.py" path                                     # where the file is
```

### What it can hold

| Key | Values | What it decides |
|---|---|---|
| `language` | BCP-47 (`es-MX`, `en-US`, `pt-BR`) | the language of the narration and the on-screen text |
| `presence` | `none` `rare` `low` `medium` `high` | how much the subject appears. It is a dial, not a switch: `low` still lets a reel open on their face, it just stops every third shot being them |
| `voice` | free text, the name the user calls it | **the default narration voice.** Anything else has to be justified in the variant's README |
| `length` | `short` `medium` `long` `dynamic` | `dynamic` is the honest default: the concept decides how long the video runs, not a template |
| `pace` | `slow` `medium` `fast` | how fast the cuts come |
| `captions` | `on` `off` `sparse` | on-screen text |
| `narration` | `on` `off` `sometimes` | whether there is a voice at all |
| `voices.preferred` / `voices.rejected` | lists | voices that worked and voices that did not |
| `formats.worked` / `formats.failed` | lists | filled by hand or by `history.py bias --apply` |
| `music.preferred` / `music.rejected` | lists | sounds to reach for and sounds to stop using |
| `rules` | `add-rule` / `rm-rule` | everything else, as one sentence an editor can apply to any photo |

`voice` and `length` are the two `brief` prints as their own lines, because they are instructions
rather than context: "use this voice unless the language rules it out" and "do not cut the story to
fit a length".

### When to write, exactly

The moment the user corrects something — not at the end of the run, when it has been forgotten. Each
of these is one command, run as soon as they say it:

| What the user says | What to run |
|---|---|
| "I didn't like that shot", "not that pose again" | `add-rule "no arms-crossed poses" --kind avoid --topic pose` |
| "I'm in too many of these" | `set presence low` |
| "I barely want to appear" | `set presence rare` |
| "that voice sounds robotic", "not that voice" | `add voices.rejected "<voice>"` |
| "this voice, always" | `add voices.preferred "<voice>"` |
| "keep it in Spanish" | `set language es-MX` |
| "the photo dump worked, the talking head didn't" | `add formats.worked photo-dump` · `add formats.failed talking-head` |
| "don't put text over my face" | `add-rule "no captions over the subject's face" --kind never --topic text` |
| "stop using that sound" | `add music.rejected "<sound>"` |
| "always this voice" (a specific one, by name) | `set voice "<voice>"` · `add voices.preferred "<voice>"` |
| "it cuts off too soon", "it ends abruptly" | `add-rule "every video lands its ending: no cut on the last beat" --kind never --topic pace` |
| "they're all too short", "some should be longer" | `set length dynamic` |
| "don't show me in every shot" | `set presence low` · `add-rule "don't show the subject in every cut" --kind never --topic person` |
| "only use shots I starred" | `add-rule "shots of the subject come from their favourites only" --kind always --topic person` |
| "no work screens / receipts / screenshots" | `add-rule "no receipts, screenshots or work screens" --kind never --topic topic` |

`--kind` is `avoid`, `never`, `prefer` or `always`; `never` and `always` are the hard ones, and
`brief` prints them under "Never do this (the user said so)". If the same rule is added twice the
script does not duplicate it — it counts the correction, which is the signal that it stopped being a
hint. Say back in one line what was recorded, so the user can correct the correction.

### The four moments the orchestrator writes here

Everything above is the user speaking. The orchestrator writes on its own in exactly four places,
and nowhere else — a preferences file that fills up with guesses is worse than an empty one,
because every later run trusts it:

| When | What it writes | Why then |
|---|---|---|
| **The first run**, after the user answers the language question | `set language <tag>` | it was asked once; asking again every run is the mistake this file exists to prevent |
| **The first run**, after the user picks or confirms a narration voice | `set voice "<voice>"` | from then on it is the default and only a language mismatch overrides it |
| **The moment a correction is spoken**, mid-run, not at the end | the matching row of the table above | at the end of the run it has already been forgotten, and half of it was said in passing |
| **After `history.py bias --apply`**, once there are enough posts | `formats.worked` / `formats.failed` | those two come from numbers, not opinion, and `--apply` only copies the verdicts that are not built on a single post |

Never write a preference from a single inference ("they picked variant B, so they like photo dumps"):
that belongs in `history.py log`, where it is one data point among many, not in the profile that every
future run reads as fact. And say back in one line what was recorded — a preference the user did not
know was being stored is one they cannot correct.

### What must never go in that file

The script refuses it, with the reason: paths, file names (`IMG_4821.HEIC`), library UUIDs, email
addresses, phone numbers, long card-like numbers and anything that smells of a credential. It stores
**rules, not material**: "no shots of me holding documents", never a path to the photo. If a
refusal fires, rephrase the rule so it applies to any photo rather than to one file.

The file is written `0600` in a `0700` folder, atomically, and nothing in it is ever uploaded.

---

## Facts of the project: what happened

Preferences are about the user and hold on every project. Facts are about **one** project — who was
there, where, when — and they live with it, in `<project>/facts.json`, written by
[`facts.py`](scripts/facts.py):

```bash
F="uv run $S/facts.py --project <the folder that holds workspace/>"
$F add "They travelled with a friend from the start, through the first three cities" \
   --about people --when 2026-07-31..2026-08-16 \
   --forbid '\b(llegu[ée]|viaj[ée]|viajaba)\b[^.!?]{0,40}\bsol[oa]\b' --allow-if 'Oporto|Porto' \
   --said "<the user's words>"
$F brief                                   # paste into every agent that writes words
$F check voice-script.json spec.json       # exit 1: a line contradicts a fact
$F show · $F rm f-002 · $F adopt-rule r-006   # adopt-rule: move a misfiled preference here
```

| What the user says | Where it goes |
|---|---|
| "that's my friend, not a stranger", "we split up in the last city", "that was the 3rd" | `facts.py add` |
| "I don't want to appear so much", "not that voice", "no forced poses" | `preferences.py` |

Write a fact **the moment the user corrects what happened**, with `--said` quoting them, and give it
the phrasings it rules out (`--forbid`) plus the context where those phrasings become true again
(`--allow-if`: being alone IS true once the friend has gone home). `check` then catches the exact sentence the user
already rejected, in any narration or caption, before it can ship again. It is a backstop: the
story-doctor still reads `brief` and squares the whole story with it, because a false premise rarely
comes out as one forbidden phrase.

`preferences.py add-rule` refuses a sentence that reads like an event and sends it here. That is on
purpose: filed as a preference, "the friend travelled along until the last city" would be applied to the
next trip, where nobody was along.

---

## What got published, and how it did

The variant the user actually uploaded is a judgement they already made, and what the post did
afterwards is the only feedback that is not an opinion. Both live in

```
~/.config/reel-forge/history.json              # $REEL_FORGE_CONFIG_DIR overrides the folder
```

through [`history.py`](scripts/history.py).

```bash
# the moment they say "I uploaded the second one"
uv run "$S/history.py" log --project oaxaca --variant B --format photo-dump \
    --platform tiktok --duration 24 --hook question --close payoff --voice warm-narrator \
    --music "slow piano, trending" --narration --published 2026-09-21

# days later, when they report numbers -- only what they say, nothing is scraped
uv run "$S/history.py" result h-004 --views 12400 --saves 310 --likes 980 --comments 22 --days 7

uv run "$S/history.py" show
uv run "$S/history.py" bias --platform tiktok        # before proposing the next concepts
uv run "$S/history.py" bias --apply                  # and write the solid verdicts into preferences
```

`--duration` and `--close` are the two fields worth insisting on. `--duration` is how the history
learns how long *this* account's videos want to be, and `--close` is how it learns which endings
land — `payoff`, `callback`, `reveal`, `punchline`, `open-loop`, or `abrupt` when it just stopped.
Logging `abrupt` honestly is the point: it is the only way the report can later show that the posts
that ended in mid-air did worse.

### How it biases the next proposal

`bias` turns the numbers into a weight per `format`, per **length band**, per `hook`, per `close`
and per `voice`:

- Rates, not totals: `saves ÷ views` compares across a 200-view post and a 90k one; raw views do not.
  A save weighs about twice a view, and watch-through the same, because a save is somebody deciding
  the video was worth keeping.
- Each post is scored against the **median** post, so the account's own size cancels out.
- A group's weight is the median of its posts' scores, **damped by how few there are**: one post moves
  the weight about a third of the way, two or three about two thirds, four or more all the way.
- The weight is clamped to **0.70 – 1.35**. It changes how often a format is proposed, never whether
  it is allowed. A format the user loves does not get retired because one post landed at a bad hour.

The length bands are `under 12s`, `12-20s`, `20-30s`, `30-45s`, `45-60s` and `over 60s`. The report
also names the bands the account has **never posted in**, which is the one thing a weight table
cannot say by itself: an empty band looks exactly like a bad one, and it is not. If every logged post
is under 30 s, the history has no evidence at all that a 50 s cut would do worse — so a concept that
needs 50 s gets to be 50 s, and the run finds out.

Use it like this: run `bias` before writing concepts, propose more of what is above 1.05 and less of
what is below 0.95, and **say why in one line** ("your last two photo dumps saved twice as well as the
talking heads, so two of these three are photo dumps"). Never present a weight as a rule — posting
time, the sound and plain luck move these numbers more than the edit does, and the report says so.

Lengths, hooks and closes are **reported, never applied**: they steer one run's proposals and are
recomputed from the numbers every time. Only formats cross into the profile, and only when the
evidence is real. `--apply` copies those solid verdicts (weight ≥ 1.15 or ≤ 0.85, and never from a
single post) into `preferences.json` as `formats.worked` / `formats.failed`, where they become part of
what every run reads.

---

## What to hand the user

After running both tools, tell them in a few lines:

1. How much material there is and from which days and places.
2. How many sessions came out (that hints at how many distinct moments there are).
3. **What they need to confirm**, with the date report as is.
4. How many GB would have to be downloaded if everything were used, and that the normal path is to
   review with thumbnails and download only what gets chosen.
5. Who is in it: the named people if Photos has them, or the groups from `people.py cluster` with
   their sheets, asking which one is the subject.

Don't start the trend research or the editing until they answer the date question.

And at the other end of the run, when they have picked and posted one: `history.py log` it, and
whatever they corrected along the way goes into `preferences.py` **while they are still saying it**.

## Honest limits

- **The Photos app only exists on macOS.** On Linux or Windows this skill works with folders only: no
  favorites, no named people, no place names and no free thumbnails.
- **Without Full Disk Access there is nothing to be done**, and that permission is granted by hand on
  the Mac.
- **Place names only come from Apple Photos.** In folders there are coordinates, not names.
- **Thumbnails are not usable for the final render**: they're ~1200 px. They're for choosing.
- **`--download-missing` needs network and patience**, and `--use-photokit` only works on macOS.
- **Insta360 and Google Photos have no public way to bulk download.** There the user has to do their
  part.
- **Face grouping is not as good as Apple Photos', and it is faces, not people**: a back, a helmet or
  a tiny face is never found, close relatives can land in one group. The detail is in
  [the people section](#who-is-in-the-material-without-apple-photos).
- **Preferences and history are per user and per machine.** They live in `~/.config/reel-forge/`,
  they are not synced anywhere, and a fresh machine starts knowing nothing. They are also only as
  good as what got written into them during the runs.
- **The published numbers are whatever the user reports.** Nothing is scraped from any platform, so
  the history has the gaps the user leaves, and a handful of posts is not evidence.
