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

## Who is in the material

Two paths, and the first one only exists on macOS.

**With Apple Photos:** `persons` comes from the library, and `inventory.py --person "Ana Reyes"`
filters on it. Free, accurate, and the user already did the naming.

**Without it** (folders, Linux, Windows, or a library where nobody was ever named), `people.py` in the
`sources` skill works it out from the images:

```bash
S="$CLAUDE_PLUGIN_ROOT/skills/sources/scripts"
uv run "$S/people.py" models --download                  # once: ~39 MB of OpenCV models
uv run "$S/people.py" detect  inventory.json --out workspace/people/faces.json
uv run "$S/people.py" cluster workspace/people/faces.json --out workspace/people/clusters.json \
    --sheets workspace/people/sheets                     # one sheet of crops per person
uv run "$S/people.py" match   workspace/people/faces.json \
    --reference ref1.jpg --reference ref2.jpg --out workspace/people/subject.json
uv run "$S/people.py" pick    workspace/people/subject.json --out chosen.txt
```

- **Ask for 2-3 reference photos of the main subject and use `match`.** It is markedly more accurate
  than grouping blind, and it answers the question that actually matters ("which shots am I in").
- `pick` writes Photos uuids when the material came from the library (which is what `export.py --ids`
  wants) and **file paths** when it came from a folder, where the item ids are only positions.
- `cluster` is the fallback when there is nobody to ask: it produces one sheet per group and **the
  user says which group is them**. The biggest group is usually them, and sometimes their partner.
- It finds faces, not people: backs, helmets, tiny faces in a crowd and heavy backlight are missed,
  and close relatives can share a group. Say so rather than promising a complete set.
- The embeddings are biometric data: they live in `workspace/`, never in `~/.config/`, and they are
  not copied into a delivery or a file name.

The honest limits, the thresholds and the measured numbers are in the
[`sources` skill](../../sources/SKILL.md#who-is-in-the-material-without-apple-photos).

## What we already know about this user

Before proposing anything, read it; the moment they correct something, write it:

```bash
uv run "$S/preferences.py" brief                 # rules, presence, default voice, length, language
uv run "$S/history.py"     bias                  # which formats, lengths and endings did well
```

Two of those lines are instructions, not context, and they decide things this phase cannot decide on
its own:

- **`Default narration voice:`** — every narrated variant uses that voice unless the run's output
  language rules it out. If a variant ends up with a different one, its README says which and why.
- **`Length:`** — when it says the concept decides, the concept decides. `history.py bias` also
  reports the length bands this account has **never posted in**; an empty band is not a bad band, so
  a concept that needs 50 s is allowed to be 50 s rather than trimmed to look like the last one.
- **`by close`** in the bias report is how the account learns which endings landed. A post logged
  with `--close abrupt` is the evidence that the thing the user complained about is real.

Both files live in `~/.config/reel-forge/`. `preferences.py` stores rules, never material, and refuses
paths and file names. The when and the how are in the
[`sources` skill](../../sources/SKILL.md#preferences-that-learn); the four moments the orchestrator
may write there on its own are
[listed there too](../../sources/SKILL.md#the-four-moments-the-orchestrator-writes-here).

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
