# Changelog

Format: [Keep a Changelog](https://keepachangelog.com). Versioning: [semantic versioning](https://semver.org);
while the plugin is `0.x`, a breaking change bumps the middle number and the entry says **Breaking** at the top.

Anyone who installed the plugin gets the new version with `claude plugin marketplace update reel-forge`
followed by `claude plugin update reel-forge`. Claude Code flags a pending update in the `/plugin` screen,
but it never updates this plugin on its own unless auto-update is turned on for the marketplace. How to
publish a version and how it reaches people: [`docs/updating.md`](docs/updating.md).

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
