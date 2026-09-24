# Where the material comes from

The goal of this phase is a file list with: path, capture date and time, type, duration, whether it's
starred as a favorite, and a local thumbnail so it can be looked at without downloading the original.

## A plain folder (any system) — the default path

Always works, and it's the one to use unless the user says otherwise.

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/sources/scripts/inventory.py" \
    --source folder:~/Pictures/trip --out workspace/catalog/inventory.json
```

It pulls the capture date from the metadata (EXIF `DateTimeOriginal`, and `creation_time` from ffprobe
for video). **The filesystem date lies**: copying a folder rewrites all of them to the same day.

If there is no date metadata, use the file name as a hint (`IMG_20240115_180230`, `PXL_20240115_...`,
`VID_...`) and **say so**: a tidy recap built on invented dates is noticeable.

## Apple Photos — **macOS only**

Gives what a folder can't: favorites, detected people, grouped bursts and local thumbnails of material
that lives in iCloud.

- Tool: [`osxphotos`](https://github.com/RhetTbull/osxphotos), installed with `uv tool install osxphotos`.
- **The local thumbnails (`path_derivatives`) are enough for the contact sheets.** Don't download
  anything yet: on a large library that's tens of GB.
- Download only the chosen material, at the end of the concepts phase:
  `osxphotos export <destination> --uuid-from-file chosen.txt --download-missing --use-photokit`
- Fields that matter: `favorite`, `date`, `persons`, `burst`, `screenshot`, `ismissing`.
- **Never write into the Photos library.** Read-only, and export to a separate folder.
- Faces and internal identifiers are personal data: use them in the workspace and **don't copy them into
  the READMEs or into delivery file names**.

Bursts and neighbouring shots are found by time: for every candidate, pull everything within ±10
minutes. That's where the good photo is (selection rule 3).

## Other libraries

- **Google Photos:** there is no good API for this. Ask the user to run Google Takeout and treat the
  resulting folder as a plain folder; the JSON next to each file carries the real date and the favorite
  flag.
- **Android / DCIM:** a plain folder. `PXL_`/`VID_` names already carry date and time.
- **360 camera (Insta360 and similar):** see `video360.md`. `.insv` files are cataloged separately, one
  agent per clip.

## Cheap sift (phase 3)

Before spending agents on looking at images, remove the obvious with rules, without looking:

- screenshots (the library's flag, or an exact screen aspect ratio)
- files under ~150 KB or with a shorter side below 640 px
- videos under 1 s
- exact duplicates (hash) and near-duplicates (perceptual hash, distance ≤ 4)
- very dark or blown-out photos (histogram: more than 70 % of pixels below 25 or above 230)
- blurry photos (Laplacian variance below the batch's 10th percentile, **relative to the batch**: a
  fixed threshold throws away usable night shots)

Everything sifted out goes into a list with its reason, not into the bin. The user can ask for something
back.

## Privacy

- The material never leaves the machine. Don't upload it to external services to "analyze" it.
- Paths, library identifiers and people's names stay inside `workspace/`.
- If you spot documents, screens with work on them, licence plates, addresses or identifiable minors,
  drop them and say so in one line. Don't describe them in detail in the README.
