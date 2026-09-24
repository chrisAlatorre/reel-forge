---
description: Turns the user's photos and videos into vertical TikToks/Reels end to end - detects sources, validates metadata, researches trends, analyzes the material with parallel agents, and delivers several concepts with variants.
argument-hint: "[free-form topic or description] [--lang es|en|...] [--auto] [--fast] [--dates YYYY-MM-DD..YYYY-MM-DD] [--place \"City\"] [--source PATH] [--no-trends]"
---

# /reel — vertical recap, end to end

Arguments received: `$ARGUMENTS`

Your job is to deliver **several vertical 1080x1920 concepts, each with variants**, from material the
user already has. You are **autonomous by default**: you research, you decide, you render. You ask
only what is unavoidable, grouped, **once**.

## Flags

| Flag | Effect |
|---|---|
| `--lang TAG` | Language of the on-screen text and the narration (`es`, `en`, `es-MX`, `en-US`, `pt-BR`…). Overrides the config for this run. |
| `--auto` | Zero questions. You assume everything with the "When you can't ask" rules and report what you assumed at the end. |
| `--fast` | Fewer agents (see the scaling table), 2 concepts x 2 variants, no deep trend research. |
| `--dates A..B` | Date range already given; don't ask for it. |
| `--place "X"` | Place or places already given; don't ask for them. |
| `--no-trends` | Skip step 4 and use the base formats from `skills/reel-forge/references/concepts.md`. |
| `--source PATH` | Force a specific folder or library and skip detection. |

Everything else in `$ARGUMENTS` is the **topic**, in plain language ("beach trip", "a day at the
office", "my dog", "the harvest").

## Skills and agents

Plugin skills (invoked as `reel-forge:<name>`):

| Skill | What for |
|---|---|
| `reel-forge` | The orchestrator: selection rules, agent allocation and the detail of each phase in `references/` |
| `sources` | Detecting and inventorying libraries and folders, reading metadata and validating dates |
| `video-engine` | The engine: JSON spec → 9:16 MP4, effects, text, looks, music and mixing |
| `video-360` | Reframing 360 material (Insta360 and friends) to 9:16 |
| `voices` | Narration with local TTS and the CapCut voice |

There is no trends skill and no photo-retouching skill: trends are researched by the
`trend-researcher` agent (detail in `skills/reel-forge/references/trends.md`) and the plugin **does
not retouch people** — the only image treatment is the render's `look`.

Agents you launch in parallel (`reel-forge:<name>`):

| Agent | What it does | When |
|---|---|---|
| `photo-curator` | Reviews a batch of photos: drops half-formed expressions, closed eyes, repeats, receipts and screenshots; rates the good ones 1 to 10 | Step 5, 1 per day or per ~150 |
| `clip-analyst` | Watches a video as frame strips, transcribes, and returns ranges with `start_s`/`end_s` | Step 5, 1 per video (or per 3-4 short ones) |
| `360-scout` | Pulls 9:16 framings out of an equirectangular: sheets, yaw/pitch, and keys verified by rendering | Step 5, 1 per 360 clip |
| `trend-researcher` | Searches the web for current formats and sounds for the topic **in the output language's market**, with source and date | Step 4, 1-3 agents |
| `creative-director` | Proposes **one** concept from an assigned angle, with second-by-second structure | Step 6, 4-8 in parallel |
| `chief-editor` | Reads every concept together, picks for variety and says what to fix | Step 6, always 1 |
| `video-builder` | Builds one variant: writes `build.py` and the spec, renders, and reviews its own frame strip | Step 7, 2 per concept |
| `critic-reviewer` | Compares the concept's variants against each other, verifies with measurements and **fixes** by re-rendering | Step 8, 1 per concept |

With plenty of material, steps 5, 7 and 8 can be run through the plugin's workflows, which write what
each agent returns to disk and let an interrupted run resume: `workflows/catalog.js` (step 5) and
`workflows/build.js` (steps 7 and 8).

### Agent scaling

Count the material **after** filtering by dates and places:

```
photo_batches = ceil(n_photos / 150)      # or one per day, whichever gives more batches
clip_batches  = ceil(n_clips / 4)
batches_360   = n_360_clips               # always one per clip
catalog_agents = min(photo_batches + clip_batches + batches_360, CAP)
```

| Mode | Catalog CAP | Trends | Directors | Build |
|---|---|---|---|---|
| normal | 10 | 2 | 4-8 + 1 chief editor | 3 concepts x 2 builders |
| `--fast` | 4 | 0-1 | 3 + 1 chief editor | 2 concepts x 2 builders |
| under 30 pieces | 2 | 1 | 3 + 1 chief editor | 2 concepts x 2 builders |

**Practical cap: ~10 agents at a time.** The machine is also decoding video, and `ffmpeg` already
uses several cores on its own: more agents is slower, not faster. With 4 concepts, the build runs in
two waves. If a batch takes more than ~10 min, split it in two instead of waiting. The full table and
the reasoning are in `docs/parallelism.md`.

---

## Step 0 — Output language (before anything else)

Resolve the language of the **on-screen text and the narration**, in this order:

1. `--lang` in `$ARGUMENTS`.
2. `$REEL_FORGE_LANG`.
3. The `"lang"` field in `~/.config/reel-forge/config.json`.
4. Nothing set → **ask once**, inside the grouped question of step 2, offering the two most likely
   options (the language the user is writing in, and English) plus "other". With `--auto` and nothing
   configured, use the language the user wrote the request in and say so.

When the answer comes from the user, **write it to `~/.config/reel-forge/config.json`** (create the
file if needed, preserving any other keys) so it never has to be asked again:

```json
{ "lang": "en-US" }
```

Use a BCP-47 tag. The region matters: `es-MX` and `es-ES` are different trend markets, and so are
`en-US` and `en-GB`. If the user gives a bare language, keep it bare rather than inventing a region.

From here on, that tag governs: the captions, the narration script, the voice you pick, the hashtags,
and the market the trend research targets. It does **not** govern the language you speak to the user
in — that stays whatever they are writing in — nor the file names or the JSON keys.

## Step 1 — Detect sources (automatic, no questions yet)

Run detection **before** talking to the user, so the questions already carry real options.

Invoke `reel-forge:sources` (or, if unavailable, do the detection by hand with what follows) and look
for:

1. **The system's native library**
   - **macOS:** Apple Photos. `sources/scripts/inventory.py --source photos` reads the library's
     own database read-only; **it needs no extra tool**, only Full Disk Access for the terminal.
     The library normally lives at `~/Pictures/Photos Library.photoslibrary`, or wherever
     `REEL_FORGE_LIBRARY` points. **This is macOS-only.**
     `osxphotos` is needed **only** to download originals that live in iCloud (step 8).
   - **Other systems:** there is no native library to read. Fallback: folders with EXIF (point 2).
     Say so explicitly, don't fake it.
2. **Folders** — check whichever exist: `~/Pictures`, `~/Movies` (or `~/Videos`), `~/Desktop`,
   `~/Downloads`, and any mounted volume with a `DCIM/` directory (SD cards, a connected phone).
3. **360 camera cloud or app** — Insta360 Studio and similar (**desktop app, macOS or Windows**). On
   macOS the cloud thumbnails usually sit under `~/Library/Application Support/Insta360/`; the `.insv`
   originals have to be downloaded from the app. Without the app: `.insv`/`.insp` files already copied
   to disk, which the `reel-forge:video-360` skill can process directly.
4. **Action cameras and drones** — name patterns: `GX######.MP4`, `GOPR####` (GoPro), `DJI_####`
   (drone), `DJI_*_D.MP4` (D-Log). Look inside the folders and volumes from point 2.
5. **User configuration** — if `~/.config/reel-forge/config.json` exists, its paths win over
   everything above. Environment variables: `REEL_FORGE_SOURCES` (colon-separated list),
   `REEL_FORGE_HOME`, `REEL_FORGE_OUTPUT`, `REEL_FORGE_WORKSPACE`.

Output of this step: a short table with source, photo/video counts, date range, and whether the
originals are **local or in the cloud** (cloud ones have to be downloaded, and that takes time).

## Step 2 — The questions (at most 4, in ONE message)

With `--auto`, skip this entirely. Otherwise send **one** message with whatever is missing, with
numbered options so the user can answer with numbers:

1. **Sources** — "I found A, B and C. All three or just one?" (if there is only one source, don't
   ask: use it).
2. **Date range and/or places** — propose the candidates you saw: "the material clusters into three
   blocks: March 3-9, April 14 and June 2-6. Which one?". If `--dates` or `--place` came in the
   arguments, don't ask.
3. **Topic, trends and output language** — "Should I research current trends? What topic: travel, a
   day at work, pets, countryside, food, sport, other?" and, if step 0 did not resolve it, "what
   language should the on-screen text and the voice be in?". If the topic already came in
   `$ARGUMENTS`, just confirm it inside another question, don't spend a whole one on it.
4. **Metadata inconsistencies** — only if step 3 found something (see below). Asked together with the
   rest, not afterwards.

Rules: no questions about style, duration, music or format — you decide those and present them as
different concepts. Don't ask twice. If the user answers partially, assume the rest and carry on.

**When you can't ask** (`--auto`, or the user doesn't answer): use every local source, take the
largest and most recent date block, topic = the obvious one from places and content, trends = yes,
language = whatever the user wrote the request in.

## Step 3 — Validate metadata and flag inconsistencies

Before analyzing anything, check date, time and location of every piece (`exiftool`, `ffprobe`, or the
library's own fields). Look specifically for:

- **Impossible or factory dates**: 1970, 2000-01-01, or years outside the rest of the batch. Typical
  of an external camera (action, 360, drone, DSLR) whose clock was never set. You spot it because a
  whole group of files shares a constant offset.
- **Time-zone drift**: the time in the file name doesn't match the library's time. It can shift a
  whole day and make an on-screen caption show the wrong date. Always compare against the rest of the
  same day's material.
- **No location**: external cameras almost never carry GPS. It can be inferred from temporal proximity
  to a phone photo that does have it (±30 min).
- **No EXIF**: files that went through a messaging app. Only the filesystem date is left, and that is
  not trustworthy.
- **Duplicates and bursts**: group them; a burst is treated as one scene from which you pick the best
  take.

When you find something, **flag it inside the grouped question of step 2** with concrete numbers and
a proposal:

> I found 48 files from an external camera dated 2015; by proximity they should be April 14-16
> (offset of −9 years 1 month 3 days). Should I correct them with that offset, use another date, or
> leave them out?

If the user agrees to correct, **don't touch the originals**: write the correction into a project
manifest (`dates.json` in the workspace folder) and have the rest of the flow read from there. EXIF is
only rewritten if the user explicitly asks, and always on copies.

With `--auto`: apply the inferred offset when the evidence is strong (a whole group with a constant
offset and clear overlap with correctly dated material); otherwise leave those pieces out and report it.

## Step 4 — Trends (in parallel with step 5)

Unless `--no-trends`, launch `trend-researcher` (1-3 agents per the scaling table) with the confirmed
topic **and the output language tag**. What has to come back, with date and source:

- Current formats for that topic and their optimal duration.
- Concrete sounds: title, artist, **measured BPM** (not estimated), and whether they are trending in
  the market of the chosen language and region.
- Text and narration styles that are working, and the ones that already look dated.

The market follows the language: `es-MX` means Mexican Spanish TikTok, `en-US` means US English
TikTok. Those are different sound charts, different hooks and different caption styles. The report has
to state which market it looked at, so nobody assumes the wrong one.

**Never invent "trending" songs or BPM.** If the agent couldn't measure it, the concept ships without
beat cutting. Full detail in `/reel-trends`.

## Step 5 — Material analysis (parallel agents)

Split the material per the scaling formula.

- `photo-curator` per photo batch: returns, per photo, whether it works and why not if it doesn't
  (half-formed expression, closed eyes, cropped face, motion blur, repeat). With bursts, it picks
  **one** and drops the rest.
- `clip-analyst` per clip batch: frame strip + audio transcription, returning moments with `start_s`,
  `end_s`, what happens, what you hear and how strong it is as a hook. A long clip almost always has
  10 good seconds and the rest is filler; the catalog is what keeps the bad piece out.
- 360 material: the catalog is by **direction** (yaw/pitch), not only by time — the same second has
  several possible framings. `360-scout` does it, one per clip. See `reel-forge:video-360`.

Every agent writes into a shared catalog in the workspace folder. **The catalog's
`start_s`/`end_s` window is binding**: whoever ignores it ends up using a frame that is not the one
that was cataloged.

## Step 6 — Concepts (directors + chief editor)

Two steps, and the order matters.

**6a. Directors.** Launch **4 to 8 `creative-director` in parallel**, each with the full catalog, the
trends, and **a different, explicit angle** that you assign: narrated documentary, pure natural sound,
guide with prices, visual gag, POV, list with a payoff, block counter. They can't see each other: the
variety comes from the angles you hand out, not from asking them for "something different". Each one
returns **a single concept** with:

- A first-second hook (the strongest shot goes first).
- Second-by-second structure, with a mini hook every 3-5 s.
- Target duration and whether it cuts to the beat or to natural sound.
- Whether it carries narration, music, or only diegetic audio.
- Which catalog moments it uses, **by id**, and the ratio of cuts with and without the subject.

**6b. Chief editor.** A single `chief-editor` reads them all together and picks **3** (2 with
`--fast`) looking for real variety, drops the repeats and the weak ones, and says exactly what to fix
in each before it gets built. It is the only point in the flow where somebody sees every proposal at
once; two chief editors contradict each other and the variety is lost.

A concept that uses an id that isn't in the catalog is a serious defect: it doesn't get built.

You confirm the selection in one line and move on. **Don't ask the user to pick a concept**: picking
is far easier once you can watch the videos.

## Step 7 — Variants

Per concept, **2 variants**, one `video-builder` each. The variants change something you can notice:
duration, with or without voice, hook order, music versus natural sound. Each builder:

1. Writes its `build.py`, which generates the JSON spec and renders with the `reel-forge:video-engine`
   engine (`uv run "$CLAUDE_PLUGIN_ROOT/skills/video-engine/scripts/render.py" spec.json`). The
   `build.py` has to rebuild everything from scratch, with no dependency on temporaries.
2. Pulls its own frame strip and **looks at it**: text readable, not covering faces, crops that don't
   cut off heads, facts and dates correct.
3. Leaves the project reproducible: a script that rebuilds everything from scratch, not a loose spec
   pointing at temporaries.

Cross-cutting rules every builder respects:

- **The same person must not be in every cut.** Mix landscape, detail, food, people, moments with
  nobody in them. A video where the author is in every cut reads as vain.
- Vertical safe area: 150 px at the top, 480 px at the bottom (that's where the app's buttons are),
  180 px on the right.
- Hard cuts with punch-in. No cross-fades, wipes or RGB glitch.
- Grain almost invisible.
- **Copyrighted music: never embedded in the version you upload.** Two files ship: the clean one and
  a `-preview` with the song, just to review. The real song goes on in the app, which also makes it
  count toward the trend.
- All on-screen text and narration in the resolved output language, and no factual caption (date,
  place, price) that you haven't verified against the metadata or a source.

## Step 8 — Verify and deliver

One `critic-reviewer` per concept compares **across** variants, not just within each one: the same
frame with a different treatment, a `look` that drifted by accident, the same shot repeated in two
cuts. Technical checklist:

- Black frames, long silences and audio peaks (the final peak must sit below −0.5 dBTP).
- The audio track lasts exactly as long as the video (if the song ends early, the last seconds are
  silent and nothing warns you).
- One frame strip per variant, actually looked at.
- Count by hand how many cuts the main person appears in.

Delivery goes to `<root>/<project>/deliveries/<version>/`, where `<root>` is `REEL_FORGE_HOME` if set,
and otherwise `~/Movies/reel-forge` on macOS, `~/Videos/reel-forge` on Linux and
`%USERPROFILE%\Videos\reel-forge` on Windows:

- Clean 1080x1920 MP4s, compressed enough to stay under ~30 MB.
- Light 720p copies for sending over chat.
- A single `README.md` per concept: what each variant is, which sound to add in the app, the suggested
  hashtags (3-5, in the output language) and, if there is narration without an embedded voice, the
  script with its timings.

Close with a 5-8 line summary: which concepts there are, how they differ, what you assumed and what is
still to be decided. No filler.

## If something fails

- **No material in the range**: say so and propose the adjacent range that does have material. Don't
  widen it on your own without saying so.
- **Originals in the cloud**: download only the chosen ones, after curation, never the whole library.
- **Low disk space**: `/reel-sources` reports it. Under ~20 GB free, work with low-resolution proxies
  and say so.
- **An agent stalls**: don't wait for it indefinitely. Carry on with what you have and note in the
  README what was left uncataloged.
