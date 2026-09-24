# Plugin status

What is **genuinely tested** on a machine, what is written but **unverified**, and what is missing.
Review date: **2026-09-24**, in three passes — the third is the 0.4.0 integration pass, at the top of
"Genuinely tested". Environment: macOS **26.6.2** (build 25G83, Apple Silicon
M3 Max), Claude Code **2.1.281**, Python **3.12** via `uv` 0.12.8, ffmpeg/ffprobe **9.0.2** from
Homebrew, `exiftool` on the PATH, `osxphotos` **0.77.0** in `~/.local/bin`.

The second pass ran every script against a real 5,036-item Apple Photos library, a 118-file folder of
originals, exported `.MOV` clips and real Insta360 X5 `.insv` files. Wall-clock times below are from
that machine, and each one names the command that produced it.

This document gets updated when something changes column. If it says "tested", it's because it was run.

---

## Genuinely tested

### The 0.4.0 pass: arc, dynamic durations, synced captions

Run on the same machine, against the **real v6 deliveries** (10 finished MP4s across 4 concepts, some
narrated, some silent) and against a purpose-built render. What was actually executed:

| What | Command | Result |
|---|---|---|
| Every script compiles | `python3 -m py_compile` over all 22 `.py` | passes |
| Every script's CLI | `uv run <script> --help` × 22 | 21 answer; `effects.py` is a module with no CLI |
| Every JSON parses | the 6 schemas, 2 manifests, `spec-example.json` | passes |
| Both workflows parse | `node --check workflows/*.js` | passes |
| A valid concept | `validate.py concept-good.json --type concept` | complies: 6 cuts, 3 variants, full `arc`, `target_duration_s` 31 s |
| A story-broken concept | the same file with the promise paid at 3 s, a 15.5 s gap with no `mini_hook`, the close in the middle and no `says` | **8 problems**, each naming the second and the field |
| A schema-broken concept | 48 s with no `arc.turn`, a resource not in `resources`, two variants on the same axis | **4 problems** |
| The story-doctor's own example | extracted from `agents/story-doctor.md`, `--type story-review` | complies against the new schema |
| A story review that ships anyway | the same, forced to `verdict: "ship"` | **4 problems**, including "the promise unpaid cannot ship" |
| Every JSON example in the docs | extracted from `agents/*.md` and `references/*.md` and validated against its contract | 6 examples, **all comply** — an agent that copies its own doc produces a valid file |
| `resolve_voice()` on Spanish | `--lang es-MX`, `--lang es` | `capcut` / **Valentino** / 1.4x, with the reason |
| `resolve_voice()` on English | `--lang en-US` | local `qwen`, no false "fallback" flag |
| `resolve_voice()` forced local | `--lang es --local-only` | local engine **plus** the `disclose` sentence for the README and a warning |
| `sound_map.py` on a short audio | 12 s WAV, `--no-transcribe` | 4 phrases with their pauses, punchline picked at 10.3 s with its confidence |
| A full render with synced captions | 4 photos + 2 voice lines + `sync` from an `alignment.json` | 10.0 s out, `timeline.json` written with `shots`, `words`, `captions` and `voice` |
| `verify.py` on that render | no flags | `text_sync` **pass** (worst drift 0.00 s), `text_cut` pass, `voice_image` pass on 2 promises |
| `verify.py` against a deliberately broken timeline | captions shifted +0.55 s, one `says` moved to the wrong shot, one `says` never spoken | `text_sync` **fail** (0.55 s over the 0.25 ceiling, each caption named), `voice_image` **fail** on both defects |
| `verify.py` on the 10 real v6 MP4s | no timeline, no spec, no script — the hardest case | ran on all 10; `ending` measured on every one |

**What the ending check found on the real v6 files.** The measurements are `end motion` (how hard the
picture is still moving in the last half second, against the video's own average) and `sound down`
(how much the audio comes down on the last 0.3 s):

| Variant | Verdict | Why |
|---|---|---|
| `V3-brindis-seco` | **ends on a dry cut** | the sound is at full level on the last frame (down only 2.5 dB) and there is no fade — the music stops dead |
| `V3-seca-16s` | lands, worth a look | only 5.3 dB of taper, but it does fade and the picture has settled (1.0x) |
| the other 8 | land | motion 0.3x-1.5x, sound down 8-30 dB |

That spread is the point: the check discriminates instead of flagging everything. Two of the numbers
are measured off the file alone, so it works on any MP4 — including the ones rendered before the
timeline sidecar existed.

**`verify.py` cannot check text on the v6 files**, and says so rather than passing them: they carry
burned-in captions but no `timeline.json` and no spec, so `text_sync`, `text_cut` and `voice_image`
all come back `skip` with the reason. Text verification is real from 0.4.0 renders onward.

**The v6 `build-*.json` and `review*.json` do not comply with any contract** — they are pre-schema
files, half of them with Spanish keys (`concepto`, `variantes`, `entrega`). `validate.py` rejects all
9 of them, listing every missing required field. That is the failure the schemas were added to stop,
caught in the open.

### The plugin loads and installs

```bash
claude plugin validate . --strict                   # manifests + skills + agents: passes
claude plugin marketplace add ./reel-forge
claude plugin install reel-forge@reel-forge
claude plugin details reel-forge
```

`details` reports **9 skills** (the 5 in `skills/` plus the 4 commands in `commands/`, which load as
skills) and, since 0.4.0, **9 agents** — `story-doctor` is the new one. The ~1,336-token always-present
figure was measured with `claude plugin details` on 0.2.1 and has **not** been re-measured since. The
exact procedure is in [`installation.md`](installation.md).

A real (non-temporary) install was then done at user scope, and a live Claude Code session listed every
component, including the two workflows, which `claude plugin details` does not count:

```
skills/commands  reel, reel-sources, reel-trends, reel-voice, reel-forge,
                 sources, video-engine, video-360, voices
workflows        reel-forge:reel-forge-catalog, reel-forge:reel-forge-build
agents           360-scout, chief-editor, clip-analyst, creative-director,
                 critic-reviewer, photo-curator, story-doctor, trend-researcher,
                 video-builder
```

That listing is from the 0.2.1 install; `story-doctor` is shown here because it is in `agents/`, but a
live session has not been asked to list the components again since.

### Installing from the private repository

```bash
claude plugin marketplace add chrisAlatorre/reel-forge   # -> "Cloning via SSH: git@github.com:…"
claude plugin install reel-forge@reel-forge
```

Both succeeded against the private repo. Claude Code resolves the `owner/repo` shorthand to an **SSH**
clone, so a GitHub token from `gh auth login` is not what authenticates it: whoever installs it needs an
SSH key with read access. Noted in [`updating.md`](updating.md#private-repositories).

### Updating

Tested by bumping `version` in `plugin.json` and running the documented flow:

```bash
claude plugin marketplace update reel-forge   # "Successfully updated marketplace"
claude plugin update reel-forge               # "updated from 0.2.0 to 0.2.1. Restart to apply changes."
```

With no version change it answers `already at the latest version` **and the cached copy stays stale** —
verified by editing a file without bumping the version and confirming the edit never reached
`~/.claude/plugins/cache/reel-forge/reel-forge/0.2.0/`. Confirmed: the update is pulled, never pushed,
and it takes effect on restart. The whole publish-and-receive cycle is in [`updating.md`](updating.md).

### The render engine, first pass

A real render from the author's own material (16 photos + a 30 s clip), 18.4 s of output, exercising
**every segment type and every text style in one spec**:

| Exercised | Result |
|---|---|
| Photo with `kb`, `punch`, `flash`, `focus` | OK |
| Video clip with `start` / `dur` / `speed` | OK |
| `behind` (giant text behind the subject, MediaPipe) | OK, the cutout reads correctly |
| `cutout` + `freeze` (character intro with cards) | OK, white outline and staggered cards |
| Animated route `map` (3 stops) | OK, dashed route, non-overlapping labels, plane |
| `stutter`, `fit: "blur"`, `drift` | OK |
| The six caption styles (`clean`, `pin`, `serif`, `box`, `yellow`, `bold`) + `words` | all legible and inside the safe area |
| `audio` tracks + `preview_audio` | both files produced (clean and `-preview`) |

Verification on the output, with the plugin's own checklist:

```
1080x1920 · video 18.400 s · audio 18.400 s   (they match exactly)
blackdetect  -> 0 black frames
silencedetect-> 0 audio gaps
loudnorm     -> true peak -17.8 dBTP (below the -0.5 limit)
temporaries  -> cleaned up (.video.mp4 and .mix.wav removed)
```

The frame strip was looked at, not just measured.

### The render engine, second pass (a different spec, after the fixes)

A fresh spec over real material — 3 photos (`.HEIC`, straight off an iPhone), 2 clips,
an animated `map` with 4 stops, 4 caption styles and 2 narration tracks:

```
uv run render.py spec-test.json      ->  14.1 s of output in 32.3 s wall clock
1080x1920 · video 14.100 s · audio 14.100 s   (exactly equal)
blackdetect   -> 0 black frames
loudnorm      -> true peak -4.7 dBTP (below the -0.5 limit)
temporaries   -> cleaned up
```

The frame strip was looked at: captions legible and inside the safe area, `behind` cutout correct,
`fit: "blur"` correct, the map's route drawn and zoomed. One cosmetic finding: a `box` caption placed
over a `map` segment can land on top of the map's own stop labels — the engine does not know about
them, so that stays the spec author's job.

### The 360 engine, first pass

On a real Insta360 **X5** `.insv` (490 MB, 20 s):

| Step | Result |
|---|---|
| `telemetry` | reads the IMU: X5, 20,880 samples at 996 Hz |
| `proxy` | 3840x1920 equirect at 30 fps, 15.5 s for a 20 s clip |
| `sheets --views ring8 --people` | yaw/pitch grid + 8 views, people labelled with their `yaw,pitch` |
| `--stab gyro` | the IMU self-calibrates against the image: offset +0.00 s, error 0.25°/frame |
| `render --keys` | tiny planet → unroll → whip-pan with automatic motion blur, 240 frames at ~39 fps |
| `planet` shortcut | OK |
| `follow --target` | tracks the person across yaw 173→203 and writes 24 smoothed `spline` keys |
| An `r360` segment inside a `render.py` spec | **OK** — the cross-skill import works |

The `r360` path is the integration between the two engines and it had never been run. It works.

### The 360 engine, second pass (after the proxy and levelling fixes)

On a real X5 `.insv` (304 MB, 11.7 s, handheld, two people and an animal in frame):

| Command | Result | Time |
|---|---|---|
| `reframe360.py telemetry` | X5, 12,608 IMU samples at 996.5 Hz | 0.2 s |
| `reframe360.py proxy` | 3840x1920 equirect, **127 MB at the new `crf 20`** (was 221 MB at `crf 16`) | 9.5 s |
| `reframe360.py sheets --views ring8 --people` | grid + 8 views + people labelled with `yaw,pitch`; the bad auto-level is now refused instead of applied | 7.1 s |
| `reframe360.py render --keys keys360.json --stab gyro` | 120 frames at 39.7 fps, whip-pan, horizon level from the accelerometer, audio kept | 7.4 s (4.1 s prep) |
| An `r360` segment inside a `render.py` spec | photo → 360 whip-pan in one render, caption across both | 11.2 s for 4.5 s of output |

### Contact sheets, face crops and frame strips

`sheets.py` on a real folder of 89 photos and a real 33 s 4K clip:

| Command | Result | Time |
|---|---|---|
| `sheets.py contact <folder> --per-sheet 30` | 3 sheets (30+30+29) plus `index.json` | 13.3 s |
| `sheets.py faces a.HEIC b.HEIC c.HEIC` | 3 faces found, one crop sheet, `index.json` | 0.9 s |
| `sheets.py strip VID.MOV` | 2 strips covering 0-33.3 s, seconds recorded in the index | 6.4 s |

### Inventory, Apple Photos and date validation

Run against a **real 5,036-item Apple Photos library** and against a loose folder:

| Command | Result | Time |
|---|---|---|
| `inventory.py --source photos --from 2026-07-28 --to 2026-08-25 --summary` | 5,036 items, 4,430 photos / 606 videos, places, people, 64 sessions, 125.21 GB still in iCloud | **1.3 s** |
| `inventory.py --source folder:<118 files> --summary` | counts, real range, 28 sessions, GPS 89 % | 1.0 s |
| `inventory.py --source photos --favorites-only --include-items` | 30 favourites with their `ZUUID` and local thumbnail path | 0.05 s |
| `validate_dates.py --source folder:<copies>` | report, no file touched | 0.1 s |
| `validate_dates.py … --case distant_batch --accept` | correction written to `plan.json` | 0.1 s |
| `validate_dates.py … --apply-exiftool --yes` | 2 files rewritten +4,244 days (2015-01-02 → 2026-08-16), `_original` backups left beside them | 0.4 s |

**Reading Apple Photos needs no `osxphotos`.** `sources.py` opens the library's own SQLite with
`mode=ro&immutable=1`; only Full Disk Access for the terminal is required. The docs used to say
otherwise and were corrected in this pass.

### Selective export from Apple Photos

| Command | Result | Time |
|---|---|---|
| `export.py --thumbnails --ids ids.txt --dest ./thumbs --dry-run` | reports `would_copy: 3`, writes nothing | 0.04 s |
| `export.py --thumbnails --ids ids.txt --dest ./thumbs` | 3 thumbnails copied out of the library | 0.04 s |
| `export.py --export --ids ids2.txt --dest ./orig --dry-run` | osxphotos 0.77.0 reports `exported: 3, missing: 1` | 8.0 s |
| `export.py --export --ids ids2.txt --dest ./orig` | originals in `YYYY/MM/DD/`, `_report.csv`, 11 MB for 2 live photos | 7.8 s |

### Narration

| Command | Result | Time |
|---|---|---|
| `voice.py lines.json ./voice --engine piper --language English` | downloads `en_US-ryan-high` (109 MB) and writes `l0.wav`, `l1.wav`, `durations.json`, 48 kHz mono | 9.1 s (first run, with the download) |
| `voice.py lines-es.json ./voice-es --engine piper --language es-MX` | downloads `es_MX-claude-high`, writes the same contract | 5.8 s |
| `narrate.py script.md --parse-only` | 3 lines with their seconds; the `Notes:` block dropped | 0.1 s |
| `narrate.py script.md in.mp4 out.mp4 --engine piper` | audio and video both exactly 14.100 s | 2.0 s |
| `narrate.py script-es.md … --language es-MX` | Spanish, accents and `Notas:` respected, duration kept | 1.0 s |
| `capcut_voice.py --calibrate` | takes the screenshot and prints the eight click points | 1 s |
| `capcut_voice.py --split joined.wav ./split-out` | cuts a single WAV into `l0.wav`/`l1.wav` + `durations.json` by silence | 0.4 s |

The click-driven CapCut path (`--prepare`) is still unrun: it takes over the desktop and needs an
open CapCut project with a text clip. `--calibrate` proving that the screenshot and the coordinate
table work is as far as this pass went.

### Every script compiles and answers `--help`

All **22** `.py` files pass `python3 -m py_compile`. **21** answer `--help` under `uv run`, re-checked
after every fix in the 0.4.0 pass. `effects.py` is the exception: it is a module `render.py` imports,
it has no CLI, and outside `uv run render.py` it cannot even import (`cv2` is not in its own header).
`config.py`, `sources.py` and `resolve_voice.py` are also importable modules, but all three do answer
`--help` on their own.

### The workflows, dry-run with stubbed agents

Beyond parsing, both scripts were **executed** under a harness that provides the Workflow tool's
globals (`phase`, `agent`, `parallel`, `pipeline`, `log`, `args`, `budget`) and returns a
schema-shaped placeholder from every `agent()` instead of spawning one. That exercises the real
control flow — batching arithmetic, prompt assembly, phase assignment and the returned object —
without any model calls.

With 12 photos over 2 days, 6 videos and 2 `.insv` clips:

| Script | Agents | Per phase | Result |
|---|---|---|---|
| `catalog.js` | 12 | Photos 2, Videos 2, 360 2, Trends 1, Verify 4, Merge 1 | returns `catalog` + `moments`, phases all declared |
| `build.js` | 10 | Common 2, Build 4, Review 2, Fix 2 | returns `deliveries` + per-concept variants |

Also confirmed statically: a literal `export const meta` at the top, a `return` at the end, and no
`Date.now()`, `Math.random()`, `new Date()`, `require()` or `process.*` — the things that break
`resume`. Every phase used is declared in `meta.phases` and every declared phase is used.

**This is not the same as a live run.** No agent was actually spawned and `resumeFromRunId` was never
exercised; the Workflow tool was not available in the reviewing session.

---

## Written but unverified

Nothing here is known to be broken: it simply **wasn't run**. This list is what survived the second
pass; everything that left it is in the section above, with the command and the time it took.

| What | Why it wasn't tested | How it would be tested |
|---|---|---|
| **A live workflow run** | The reviewing session had no Workflow tool. Both scripts were dry-run with stubbed agents (above), which covers the control flow but spawns nothing | `Workflow({ scriptPath: "<plugin>/workflows/catalog.js", args: {...} })`, then interrupt it and relaunch with `resumeFromRunId` |
| **The 9 agents** | No agent was invoked: their prompts and contracts are reviewed text, not executed. The 0.4.0 pass validated the JSON every agent's own doc shows, which is as close as you get without spawning one | One full `/reel` run over a small folder |

### What 0.4.0 changed and has **not** been proven end to end

The machinery below was written, wired and unit-tested; what has not happened is a real run where an
agent actually uses it. Read this as "the plumbing holds, nobody has run water through it".

| What | What was proven | What is still theory |
|---|---|---|
| **The arc** (`arc` in the concept contract) | `validate.py` accepts a good one and names 8 defects in a broken one; the canonical example in `creative-director.md` validates | That a `creative-director` actually writes one worth building, and that the arc makes the finished video feel whole |
| **The story-doctor** | Its agent file, its schema and its checks agree; its own documented output validates; `build.js` wires both passes with their own resume units | It has never been invoked. Its verdicts, its blocking fixes and whether the builder obeys them are unproven |
| **Dynamic durations** | `target_duration_s` + `duration_rationale` are required; the schema demands a `turn` past 35 s; `validate.py` flags variants that all land within 4 s of each other | That a run actually produces a 14 s video next to a 52 s one. Every v6 delivery is 9-32 s, which is the problem this was built for |
| **Valentino by default** | `resolve_voice()` returns CapCut/Valentino/1.4x for `es` and `es-MX`, local for `en-US`, and carries `disclose` when it falls back | The full CapCut click path (`capcut_voice.py --prepare`) is still unrun — it takes over the desktop. No 0.4.0 video has been narrated by Valentino yet |
| **Synced captions** | A real render with `sync` produced captions at 0.00 s drift; a deliberately broken timeline was caught at 0.55 s | `transcribe.py --align` against a **real** TTS WAV. The alignment used in the test was hand-written to the contract, not produced by whisper |
| **`voice_image`** (the voice names it, the shot shows it) | Caught both defects: a phrase never spoken, and a phrase spoken while another shot is up | No agent has written a `says` yet: the field exists and nothing fills it in production |
| **Resuming** | The units are on disk per agent, including the two story passes | `resumeFromRunId` has never been exercised |
| **Preferences and history** | `preferences.py` and `history.py` answer `--help` and refuse paths and identifiers | Nothing has written to them from a run, and no `bias --apply` has ever steered a proposal |
| **`capcut_voice.py --prepare`** | It drives CapCut by clicking and takes over the desktop; it needs an open project with a text clip. `--calibrate` and `--split` were both run | `--calibrate` first, then `--prepare` with CapCut open |
| **`voice.py --engine qwen/voxcpm`** | The models are a ~4 GB download and need Apple Silicon with MLX | `voice.py lines.json out --engine qwen`; `piper` is the cross-platform path and it **was** run, in two languages |
| **`--create-voice` (VoiceDesign)** | Same ~4 GB download | `--create-voice narrator --description "…" --seed 11` |
| **Linux and Windows** | The review was on macOS 26.6.2 | `render.py` and `sheets.py` matter most there |
| **iCloud download of material not on disk** | Every original the export touched was already local, so `--download-missing --use-photokit` never had to pull from the network | Export a UUID whose `local` is `false` in the inventory |

---

## Known issues

- **An already rendered video used as a source segment brings its burned-in text with it.** Obvious
  in hindsight, and it showed up immediately in a test render: the source clip's subtitles appear
  underneath the new captions. The catalog should mark clips that already carry burned-in text.
- **A caption placed over a `map` segment can collide with the map's own stop labels.** The engine
  lays the map labels out to avoid each other, but it does not know about the spec's captions. Seen
  with a `box` caption over a 4-stop route. Whoever writes the spec has to look at the frame.
- **The `distant_batch` case always trusts the majority.** If most of a folder carries the wrong
  date, `validate_dates.py` proposes "correcting" the few files that are right. The report shows both
  groups and nothing is written until `--accept`, so it is visible, but it is worth knowing.

### Fixed in the 0.4.0 pass

- **`verify.py` could not see an abrupt ending on a video it had not rendered.** The `ending` check
  had three symptoms and all three needed a timeline or captions, so on the 10 real v6 files it only
  ever said "no fade at the end" — one symptom, never enough to flag anything. It now measures two
  things off the file itself: how hard the picture is still moving in the last half second against the
  video's own average, and how much the sound comes down on the last 0.3 s. Both travel in the report
  even when the check passes, so the story-doctor can argue with numbers.
- **The fade was being read as motion.** A fade to black is the biggest frame-to-frame difference in
  the whole file, so the first version of that measurement reported every faded video as cut off —
  `V3-seca-16s` came back at 9.2x when its picture had actually settled. The fade is now found from
  the picture's own brightness (and taken from the timeline's `fade_out` when there is one) and
  excluded before the motion is measured. The same walk fixed `faded`, which used `blackdetect` and
  missed any fade that does not reach full black.
- **`validate.py` did not check the arc at all.** A concept could satisfy every field of
  `concept.schema.json` and still be the video the user complained about. It now checks the rules
  `agents/story-doctor.md` states: beats in order and none more than 5 s apart without a `mini_hook`,
  no two beats raising the same thing, the promise paid outside the first third and before the last
  frame, `arc.hook.ends_s` on the same clock as the blocks with `role: "hook"`, roles running
  hook → development → turn → close, a last block that is the close, a close over 1.2 s, `says` on a
  narrated concept, and variants that all land within 4 s while one claims to differ in duration.
- **The 5 s beat rule contradicted the story-doctor's own worked example.** The agent file said "no
  gap over 5 s between beats" while its example defended "three proofs of 7 s". Reconciled in the
  agent, the schema and the checker: a long beat is fine when it carries a `mini_hook`; 5 s with
  nothing new *and* no reason to stay is the defect.
- **The story-doctor's output crossed four agents with no schema.** Everything else that travels
  between agents has one, and `docs/agents.md` claimed the chief editor wrote to the `concept`
  contract, which it does not. Added `schemas/story-review.schema.json` (derived field by field from
  the agent's own documented output, which validates against it) and a `story-review` type in
  `validate.py` that refuses a `ship` verdict with the promise unpaid, the close missing or a blocking
  fix still open.
- **Two environment variables named the same folder.** `preferences.py` and `history.py` read
  `REEL_FORGE_CONFIG_DIR`; `resolve_voice.py` read `REEL_FORGE_CONFIG`, and `docs/configuration.md`
  documented the split as a limitation. `REEL_FORGE_CONFIG_DIR` now moves all four files and the old
  spelling is still read.
- **`docs/agents.md` and `docs/architecture.md` were still describing 0.2.1.** Eight agents, nine
  phases, no story-doctor, no `verify.py`, no `transcribe.py`, no `resolve_voice.py`, and a contracts
  table pointing the chief editor at the wrong schema. Both now match `SKILL.md` and `build.js`.

### Fixed in the 0.2.1 pass

- **Video dates were read in UTC while photo dates were read as a bare wall clock.** `_ffprobe` took
  `creation_time` (UTC) before Apple's `com.apple.quicktime.creationdate` (local **with** its offset),
  so an iPhone clip and a photo taken beside it came out 8 h apart, and the folder's date range mixed
  offset-aware and naive strings. The order was flipped, `_exif_pillow` now honours
  `OffsetTimeOriginal`, and `read_folder` sorts by the wall clock instead of by the ISO string.
  On the 118-file test folder the session count went from a wrong 36 to 28.
- **`date_utc` was not UTC.** It held the local ISO string with its offset. Now converted.
- **The camera-shift heuristic grouped files by name length.** `IMG_4934.MOV` and `IMG_4980.HEIC`
  landed in different "cameras" because `.MOV` and `.HEIC` are different lengths, and the label came
  out as `num28*`. It now keys on the first run of letters anywhere in the stem, and the message
  names a real example file. The false positive disappeared and a genuine one surfaced (files saved
  from a Chinese app, 5 h off, with no EXIF offset tag).
- **`export.py --dry-run` copied the thumbnails for real.** `copy_thumbnails` ignored the flag
  entirely. It now reports `would_copy` and writes nothing, not even the destination folder.
- **`voice.py` had no way to get a voice.** The default was a Spanish model that nothing ever
  downloaded, so the first run died with a `FileNotFoundError` on a missing `.onnx.json`. The voice
  is now picked from `--language`/`REEL_FORGE_LANG` (English by default), and the `.onnx` + `.onnx.json`
  pair downloads itself from `rhasspy/piper-voices` on first use, with a readable error if it can't.
- **`narrate.py` could not pass a language through.** It called `voice.py` without `--language`, so a
  run in one language could be narrated by the default voice of another. It now takes `--language`
  (defaulting to `$REEL_FORGE_LANG`) and forwards it.
- **The 360 proxy was bigger than the original.** `crf 16` gave ~160 Mbps: 221 MB of proxy for a
  304 MB clip. Now `crf 20` by default (`--crf`, or `REEL_FORGE_PROXY_CRF`): **127 MB, same 9.5 s
  encode**, and sheets and reframes at 1080 look the same.
- **`level: "auto"` with `stab: "no"` rotated a horizon by 34°** on the strength of two vertical-line
  readings. Levelling a shot now needs at least 3 readings and refuses a reading beyond 25°, saying
  so and pointing at `--stab gyro`. With `--stab gyro` the accelerometer is used and the horizon is
  right.
- **`capcut_voice.py --split` needed a placeholder positional.** `--split audio.wav ./out` errored
  with "needs the output folder" because the single positional filled `lines`. A lone positional is
  now the output folder.
- **The docs claimed `osxphotos` was required to read Apple Photos.** It is not — it is only needed
  to download iCloud originals. Corrected in `README.md`, `commands/reel.md`, `commands/reel-sources.md`,
  `agents/photo-curator.md`, `skills/reel-forge/SKILL.md`, `docs/agents.md` and `docs/installation.md`.

---

## Next steps, in order

1. **One full end-to-end run** with 30-50 real files and `/reel --auto`. It is the only way to know
   whether the agents' prompts produce what their contracts promise. Everything else on this list
   comes out of that.
2. **Run the two workflows for real** with the Workflow tool, `resume` included: deliberately
   interrupt a `catalog.js` run and relaunch it with `resumeFromRunId` to confirm no work gets
   repeated. The dry run covers the control flow but not the agents or the cache.
3. **Decide whether the workflows should use the plugin's agents.** Today they call `agent()` with the
   full prompt embedded, so `agents/*.md` and the prompts in `workflows/*.js` describe the same work in
   two places. Either the workflows pass `agentType`, or the prompts get trimmed to what the workflow
   adds. Until then, **any contract change has to be made in both**.
4. **Test on Linux.** `render.py` and `sheets.py` first; the Thai and CJK fallback fonts are written
   for macOS and there `REEL_FORGE_FONT_THAI` and `REEL_FORGE_FONT_CJK` have to be pointed manually.
5. **Add evals** (`claude plugin eval`) with two or three cases: that `/reel-sources` doesn't invent
   material, that a concept doesn't use ids outside the catalog, and that the trend researcher doesn't
   invent a song. Those are the three failures that cost the most.
6. **A test for the output language**: that a run with `--lang en` produces no Spanish caption and
   picks an English voice, and vice versa. The voice half is now enforced in `voice.py`; the caption
   half still depends on the agents.
7. **Try `--engine qwen`** once, to know whether the ~4 GB download is worth recommending over piper.
