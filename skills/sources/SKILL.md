---
name: sources
description: Finds, inventories and validates the material (photos and videos) a reel will be made from. Reads the macOS Photos app read-only, plain folders on any system, and 360 camera material. Use it at the start of any reel-forge project, before researching trends or editing anything.
---

# Material sources and metadata

This skill answers three questions, in this order:

1. **What's there?** How many photos and videos, from which dates, from which places, with whom.
2. **Is the metadata usable?** If the dates are broken, everything else (grouping into sessions,
   ordering the story, putting a place on screen) comes out wrong.
3. **What has to be downloaded?** How big it is and what is cloud-only.

It never writes into the Photos library and never modifies original files.

## First thing

```bash
S="$CLAUDE_PLUGIN_ROOT/skills/sources/scripts"
uv run "$S/inventory.py"      --from 2026-08-01 --to 2026-08-20 --summary -o inventory.json
uv run "$S/validate_dates.py" --from 2026-08-01 --to 2026-08-20 --plan corrections.json
```

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

## What to hand the user

After running both tools, tell them in a few lines:

1. How much material there is and from which days and places.
2. How many sessions came out (that hints at how many distinct moments there are).
3. **What they need to confirm**, with the date report as is.
4. How many GB would have to be downloaded if everything were used, and that the normal path is to
   review with thumbnails and download only what gets chosen.

Don't start the trend research or the editing until they answer the date question.

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
