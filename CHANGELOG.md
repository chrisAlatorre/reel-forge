# Changelog

Format: [Keep a Changelog](https://keepachangelog.com). Versioning: [semantic versioning](https://semver.org);
while the plugin is `0.x`, a breaking change bumps the middle number and the entry says **Breaking** at the top.

Anyone who installed the plugin gets the new version with `claude plugin marketplace update reel-forge`
followed by `claude plugin update reel-forge`. Claude Code flags a pending update in the `/plugin` screen,
but it never updates this plugin on its own unless auto-update is turned on for the marketplace. How to
publish a version and how it reaches people: [`docs/updating.md`](docs/updating.md).

## 0.6.2

What the build phase of the same run found.

### Fixed

- **Two builders drove CapCut at the same time.** Their clicks interleaved, neither got audio, and
  the diagnosis they wrote into the README blamed the voice grid and a missing sign-in — neither was
  true. `capcut_voice.py` now takes a machine-wide lock for its whole batch; a second caller waits for
  it (`REEL_FORGE_CAPCUT_WAIT`, default 30 min) instead of clicking into somebody else's session.
- **`variant.py` wrote `engine: "local"` into the voice-script**, which is not in the schema: every
  narrated delivery failed its own contract, the builders fixed it by hand, and each rebuild broke it
  again. It writes the engine's real name (`qwen`, `voxcpm`, `piper`).

## 0.6.1

What the first end-to-end run of 0.6.0 found.

### Fixed

- **`export.py` could hang forever.** `osxphotos --use-photokit` without the Photos permission does
  not fail: it waits for a dialog nobody sees, at 0 % CPU. Run by an agent, it sat six minutes with
  no output. The export now runs under a watchdog — no output and no new file for 120 s kills it — and
  retries without PhotoKit, saying what that costs (files that live only in iCloud).
- **`framecheck --apply` no longer demotes anything.** On the first full catalog it ran over (296
  moments) it capped 7 at quality 2, and a look at each frame found about 2 real obstructions — tourists
  in front of a temple, pedestrians in front of a tram. The other five were a night market, a concert
  crowd and the subject's own legs in a POV: people who ARE the shot. It now leaves a "needs a look"
  note and the curator decides.
- **A fact must be what the user said, not what was inferred.** The run's own facts carried a split
  date worked out from the catalog (the last photo together); a director then wrote "the 16th: our
  last day together" as a caption — a claim nobody had confirmed. `facts.py` and the `sources`
  skill now say it outright: a detail that was not given is left out, or the fact forbids stating it.
- **The trends reference now asks for `beat0` and says the 30 s preview caps nothing.** A director
  held a concept under 29.5 s because the song's preview was 30 s long, and another proposed
  trimming the song so its first beat fell on frame 0 — which breaks the untrimmed-paste rule the
  beat grid depends on.
- **The workflows sent every agent to `/skills/...`.** They wrote `$CLAUDE_PLUGIN_ROOT` into the
  commands they hand out, and that variable is not set in an agent's shell. They take `plugin_root`
  now, and the orchestrator skill says to pass it.
- **`validate.py` rejected dropped moments** for having no valid window, when a missing window is
  often exactly why a moment was dropped. Items with `use: false` skip the window rules.
- **The docs still told builders to write their own `build.py`** in 35 places — `/reel`, the
  orchestrator, the references, the workflow's fix prompts, the architecture docs. They all point at
  `variant.json` and `variant.py` now, and `/reel` hands the directors the project's facts.

## 0.6.0

What the user tells you, split by what it is; one builder for every variant; and the frame check
running on its own.

### Added

- **`facts.py` — what is TRUE about one project**, in `<project>/facts.json`, beside the workspace
  and never in the plugin. "My friend travelled with me until the last city" is a fact of one trip;
  stored as a global preference, as it once was, it would have been applied to the next trip as if
  it were true there. A fact carries the phrasings it rules out (`--forbid`) and where they become
  true again (`--allow-if`): `check` runs over every narration line and caption and exits 1 on a
  contradiction. The story-doctor gets a sixth question — *is it true?* — and the directors, builders
  and critic all get `facts.py brief`. Tested against a real script that had it wrong: it caught every
  false line in it and passed the corrected rewrite.
- **`skills/video-engine/scripts/variant.py` — the shared builder.** A builder agent writes a
  declarative `variant.json` (shots, the sound under each, the words, the song) instead of its own
  ~400-line build script. Cuts on the beat by default — the first shot absorbs the song's intro and
  narrated cuts move to the next half-beat —, the hook on frame 1, `loop_to_first`, the natural-sound
  mix, the preview bed looped on whole bars, the facts check **before** rendering (exit 4), 720p
  copies that fit their ceilings, the gate, framecheck over every rendered cut, publishing notes, a
  lock per variant (exit 3) and skipping an up-to-date delivery. It reproduced a hand-built variant
  cut for cut.
- **`framecheck.py --catalog --apply`**: the whole catalog in one process, run by the catalog
  workflow right after the merge. Frames are read at 1280 px — every measurement is a share of the
  frame — which took it from ~14 s to ~3 s a moment with the same verdicts.
- **`tests/run.py`**: regression tests on synthetic fixtures (ffmpeg patterns, made-up sentences),
  each named after a bug that shipped with the gate green: `start_s` read as 0, a rotated phone video
  read sideways, the beat grid, the lock, facts vs preferences, the loop seam, and the selfie below.

### Changed

- **`preferences.py add-rule` refuses a sentence that reads like an event** and points at
  `facts.py`; `--global-anyway` overrides it for the rare real rule that mentions a trip.
- **A person facing the lens is not an obstruction.** The first frame check called a selfie with a
  friend "someone blocking the shot". What blocks is bodies with their backs or sides to the camera:
  the segmenter sees a person, the face detector sees no face. That is what the shot that started this had —
  0.50 of the bottom third, not one face — and it is the only thing `--apply` writes back now. A lone
  window edge stays a note in the sidecar.
- The build workflow hands every builder `variant.py` and the facts brief, and takes `project_dir`,
  `workspace` and `deliveries` for projects that predate the standard layout.

## 0.5.0

Never published on its own: it ships inside 0.6.0.

Three things a vertical video needs, and one thing curation was never looking at.

### Added

- **`skills/sources/scripts/framecheck.py`** — what is in the rectangle, measured. Curation answers
  *what was happening* and writes it down; nobody was answering *what the frame looks like*, and
  that is what ships a bad shot. It judges the 9:16 crop, reports people by horizontal third (from
  any angle — a face detector does not see the back of a head), long edges cutting the picture,
  veiling glare and how much height is free. It reports; it never gates.
- **`obstructions`** on the catalog item (`glass`, `frame`, `foreground_people`,
  `foreground_object`, `dirt`, `reflection`). When it is not empty the schema requires `notes` and
  caps `quality` at 2. The curators and the critic both run the check; the critic runs it on the
  rendered file, because the shot that prompted all this passed curation and shipped.
- **`"instant": true`** on a caption: no pop and no 0.06 s fade-in, so the text is already up on its
  first frame. Those two frames are where the scroll is decided.
- **`"loop": true`** in a spec: it reaches the timeline, and `verify.py`'s `ending` then measures the
  SEAM — PSNR between the last frame and the first — instead of looking for a fade. Every looping
  video used to be warned for "ending on a dry cut", which in a loop is the form, not a defect.

### Fixed

- `verify.py` and `transcribe.py` read a line's second as `t`/`at` with a default of 0, while the
  contract calls it `start_s`. Every line aligned at second 0: subtitles piled up at the start and
  `text_sync` passed with 0.00 s of drift because it compared the error against itself.
- `capcut_voice.py` now reads CapCut's server toast (`ax_texts` + `read_toast`) instead of guessing:
  it is not a window and keeps its message in `AXValue`, so `classify()` used to blame the voice
  grid for a refusal that came from the server.

### Numbers these were calibrated on

Every threshold here came from measuring real material, and the ones that did not survive the
measurement were dropped rather than kept as decoration:

- loop seam floor **18 dB**: a closing loop scores 24.2, an ordinary ending 3.7, and the ceiling is
  27.1 — what two CONSECUTIVE frames of one still shot score, because grain is drawn per frame.
- `haze` **never decides on its own**: across nine real shots it does not separate dirty glass from
  weather (a misty seascape 0.47, a dirty boat window 0.39). The two signals that do discriminate
  are people in the bottom third and an edge crossing the frame.

## 0.4.1

Two bugs that made a narrated video ship broken while the gate stayed green, and one diagnosis that
sent you to fix the wrong thing.

### Fixed

- **`start_s` is finally read.** The `voice-script` contract
  (`schemas/voice-script.schema.json`, `narrate.py`) names the second of each line `start_s`, but
  `transcribe.py` and `verify.py` (`parse_script`) read `t` / `at` with a default of 0. A valid
  script therefore aligned every line at second 0: the subtitles piled up in the first seconds and
  `text_sync` reported 0.00 s of drift, because it compared the error against itself. `voice_audible`
  failed the other way, measuring one window over and over and calling an audible narration weak.
  Both now try `start_s`, `t`, `at`, in that order.
- **CapCut's server messages are read instead of guessed.** The "too many people are using this
  feature" notice is not a window — `modal_windows()` never saw it — and it keeps its text in
  `AXValue`, which `ax_nodes()` does not collect. New `ax_texts()` and `read_toast()` catch it in the
  9 s after the Generate click, and `classify()` now reports a server refusal as such instead of
  blaming the click in the voice grid. A refused line stops the batch at once (exit 4, or exit 6 when
  the notice talks about credits) rather than costing two retries and a new project that cannot help.

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
