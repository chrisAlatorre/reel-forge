# Changelog

Format: [Keep a Changelog](https://keepachangelog.com). Versioning: [semantic versioning](https://semver.org);
while the plugin is `0.x`, a breaking change bumps the middle number and the entry says **Breaking** at the top.

Anyone who installed the plugin gets the new version with `claude plugin marketplace update reel-forge`
followed by `claude plugin update reel-forge`. Claude Code flags a pending update in the `/plugin` screen,
but it never updates this plugin on its own unless auto-update is turned on for the marketplace. How to
publish a version and how it reaches people: [`docs/updating.md`](docs/updating.md).

## 0.4.0

There is no 0.3.0: the work planned for it grew into this release and went out under one version.

**Breaking.** A concept now has to declare an **arc** and the **duration that story needs**; the old
shape no longer validates. Everything else is additive. What was tested against real material and what
is still theory: [`docs/status.md`](docs/status.md).

The version this one answers: the videos were well made and they felt **interrupted**. Something built
up and then cut off, and almost everything came out between 15 and 30 s because that was the house
length, not because that was the story. This release makes the story the thing that decides.

### Added
- **A narrative arc, per concept.** `concept.schema.json` requires `arc`: what the hook **promises**,
  the **development** beats with what each one adds that the last one did not, an optional **turn**,
  and a **close** with `lands_because` — the reason it ends the video instead of stopping it, in one of
  five moulds (`punchline`, `back_to_hook`, `final_fact`, `question`, `loop`). Past 35 s the schema
  demands a turn: without one the video flattens out. Every cut in `structure` carries the `role` it
  serves, and cuts with no role are the first to be trimmed.
- **`story-doctor`, the ninth agent.** It asks the one question nothing else asked — is the video
  **finished** — and runs twice: over every concept before a frame is rendered, and over every
  rendered variant before it ships. It returns seconds and catalog ids, never adjectives, and its
  `blocks` fixes are binding on the builder. Its contract is the new
  [`schemas/story-review.schema.json`](schemas/story-review.schema.json).
- **Dynamic durations.** `target_duration_s` is required and comes with `duration_rationale`, which
  has to defend the number in beats (*"hook 3 + three proofs of 7 + turn 4 + close 3"*). The guide
  ranges are there to argue against, not to obey: a gag lands at 10-20 s, a recap at 20-35 s, a
  storytime or a guide at 35-75 s, and there is room past that when every beat brings something new.
  A run of videos that all land within 5 s of each other is itself reported as a finding.
- **Valentino, from CapCut, is the default voice for Spanish.** `resolve_voice.py` is the single
  answer to "who reads this": what the user pinned, then Valentino at 1.4x whenever the output language
  is Spanish and CapCut is installed, then a local engine. When the local path wins it returns the
  sentence the variant's README has to carry — a local voice works and is reproducible, and it does
  **not** sound like the trend, so a delivery never hides which one it used.
- **Captions cut from the voice itself.** `transcribe.py --align` reads the WAVs the narration
  produced and gives every word the second it is really pronounced on; the engine's `sync` takes the
  caption times straight from that file. Hand-timed subtitles drift half a second, read as a dubbed
  video, and no frame strip shows it because every frame on its own looks right.
- **`says`: the voice names it, the picture shows it.** A segment declares what the narration names
  while it is on screen, and `verify.py` checks the pairing against the narration's own word times to
  **0.25 s**, in both directions.
- **`verify.py` is a gate, not a report.** Eleven criteria, and nothing ships without passing: one
  audio track, length, black frames, audio holes, true peak, the voice audible over the bed,
  `text_sync`, `text_cut`, `voice_image`, the **ending**, and the weight of the review copy.
- **`sound_map.py`** maps a spoken viral audio by phrase — where each one starts, how long the pause
  after it is, and which one is the punchline — so a meme audio gets cut on its sentences instead of on
  a BPM grid that chops them in half. **`wordmarks.py`** gives the words a caption has to land on.
- **Preferences and history.** `preferences.py` keeps what the user corrects as *rules* (never a path,
  a file name or an identifier — those are refused with the reason), and `history.py` keeps what was
  published and the numbers the user reports out loud, nothing scraped. `history.py bias` turns them
  into weights per format, per length band and per close.
- **Resuming, per agent.** Every unit owns `workspace/run/<unit>.json`, including each of the story
  doctor's two passes, so a run that dies rebuilds only what is missing.

### Changed
- **`verify.py` can now tell an abrupt ending on a video it did not render.** It measures how hard the
  picture is still moving in the last half second against the video's own average, and how much the
  sound comes down on the last 0.3 s. Both numbers travel in the report even when the check passes.
  Run over the ten finished v6 deliveries it flagged one — music stopped dead at full level with no
  fade — and let the other nine through, which is the point: it discriminates.
- **The fade is no longer mistaken for motion.** A fade to black is the biggest frame-to-frame
  difference in a file; it is now found from the picture's own brightness and excluded before the
  motion is measured. The same walk replaced the old `blackdetect` test for "did it fade", which
  missed any fade that stops short of full black.
- **`validate.py` checks the arc**, which is where "it cuts off too soon" gets caught before anything
  is rendered: beats out of order or more than 5 s apart with nothing holding the viewer across the
  gap, two beats raising the same thing, a promise paid in the first third or after the last frame,
  roles that do not run hook → development → turn → close, a last block that is not the close, a close
  under 1.2 s, a narrated concept where no cut says what the voice names, and variants that all land
  within 4 s of each other while one of them claims to differ in duration.
- **A long beat is fine if it earns it.** The rule "no gap over 5 s between beats" contradicted the
  story-doctor's own example, which defends three proofs of 7 s. A beat may run as long as its
  material holds when it carries a `mini_hook`; 5 s with nothing new *and* no reason to stay is the
  defect. Agent, schema and checker now say the same thing.
- **One variable for the per-user folder.** `REEL_FORGE_CONFIG_DIR` moves `config.json`, `voice.json`,
  `preferences.json` and `history.json`. `REEL_FORGE_CONFIG` is still read as the older spelling.
- **Two to five variants per concept**, one per axis (`sound`, `duration`, `subject_presence`,
  `cutting`, `structure`); a sixth would repeat an axis and read as the same video twice. A short
  variant drops development beats and **keeps the close**.
- `docs/agents.md` and `docs/architecture.md` describe the eleven-phase flow with both story passes,
  instead of the nine-phase one from 0.2.1.

## 0.2.1

A testing pass against a real library and real material. No breaking changes; the flags and the
environment variables are the same. What each fix means is in [`docs/status.md`](docs/status.md).

### Fixed
- **Dates from videos and photos are now on the same clock.** Video dates were read from
  `creation_time` (UTC) instead of Apple's `com.apple.quicktime.creationdate` (local, with its
  offset), so an iPhone clip looked hours away from a photo taken beside it. Photo dates now honour
  `OffsetTimeOriginal`, a folder's items sort by the wall clock rather than by the ISO string, and
  `date_utc` really is UTC.
- **The "two cameras, shifted clocks" heuristic no longer splits a folder by file-extension length**
  (which reported a nonsense `num28*` group). It keys on the camera marker in the name.
- **`export.py --dry-run` no longer copies the thumbnails for real.** It reports `would_copy` and
  writes nothing.
- **`voice.py` downloads its piper voice.** The default used to be a Spanish model that nothing ever
  fetched, so the first run died on a missing file. The voice now follows `--language` /
  `REEL_FORGE_LANG` (English by default) and the model downloads itself on first use.
- **`narrate.py` takes `--language`** and forwards it, so a run in one language can no longer be
  narrated by another language's default voice.
- **`capcut_voice.py --split AUDIO.WAV OUT_FOLDER`** works without a placeholder lines file.
- **The 360 proxy is ~43 % smaller.** `crf` went from a hardcoded 16 to a configurable 20
  (`--crf`, `REEL_FORGE_PROXY_CRF`): 127 MB instead of 221 MB for the same clip, same encode time.
- **`level: "auto"` no longer rotates a horizon on two bad readings.** It needs at least 3 and
  refuses anything beyond 25°, and it points at `--stab gyro`, which uses the accelerometer.

### Changed
- The documentation no longer claims `osxphotos` is required to **read** Apple Photos. The library's
  own database is read directly (read-only); `osxphotos` is needed only to **download** iCloud
  originals.
- **One catalog filename, everywhere.** `photo-curator`, `clip-analyst` and `360-scout` write
  `catalog/catalog-<batch>.json`, the name the workflows already merge on. They each used to document
  a filename of their own (`photos-…`, `video-…`, `360-…`), so an agent invoked outside
  `workflows/catalog.js` left a file the merge step never picked up.
- `trend-researcher` writes `trends/trends.json` — the path `workflows/build.js` reads — instead of
  `research/trends-<topic>.json`, with `trends/trends-<theme>.json` for parallel instances.
- `claude plugin marketplace add .` is rejected by the CLI (`Invalid marketplace source format`); the
  release checklist in [`docs/updating.md`](docs/updating.md) now uses `./`.

## 0.2.0

**Breaking.** The plugin is now entirely in English, and the environment variables were unified. If you
had any of the old variables exported, rename them — the old names are no longer read. The table is in
[`docs/configuration.md`](docs/configuration.md#renamed-in-020).

### Added
- **Configurable output language.** The on-screen text and the narration follow a language you pick with
  `--lang`, `REEL_FORGE_LANG` or the `"lang"` field in `~/.config/reel-forge/config.json`. The first time,
  the plugin asks once and remembers the answer.
- The trend research now targets **the market of that language and region** (`es-MX` is Mexican TikTok,
  `en-US` is US TikTok) and says which market it looked at in its report.
- The voice list is **filtered by language**, and the reviewer checks that no video ships with mixed
  languages.
- `docs/configuration.md`: one page listing every environment variable and the config file.
- This changelog.

### Changed
- Everything in the repo — commands, skills, agents, docs, script help text and CLI flags — is in
  English. The file and directory names changed accordingly (`commands/reel-fuentes.md` →
  `commands/reel-sources.md`, `skills/motor-video` → `skills/video-engine`, and so on).
- Unified environment variables: `REEL_FORGE_SOURCES`, `REEL_FORGE_LIBRARY`, `REEL_FORGE_HOME`,
  `REEL_FORGE_WORKSPACE`, `REEL_FORGE_OUTPUT`. The old Spanish names and the underscore-less
  `REELFORGE_*` aliases are gone.
- Unified script paths: everything lives in `${CLAUDE_PLUGIN_ROOT}/skills/<skill>/scripts/`, and every
  document references it that way. There is no `${CLAUDE_PLUGIN_ROOT}/scripts/`.
- Unified output root across commands, skills and workflows: `REEL_FORGE_HOME` if set, otherwise
  `~/Movies/reel-forge` on macOS, `~/Videos/reel-forge` on Linux and `%USERPROFILE%\Videos\reel-forge`
  on Windows. The folders inside a project are now `workspace/` and `deliveries/`.
- `REEL_FORGE_360` now defaults to `$REEL_FORGE_HOME/360` instead of a root of its own.

## 0.1.0

First version. The 9-phase flow, 5 skills, 8 agents, 2 workflows, the render engine, the 360 engine and
the local TTS.
