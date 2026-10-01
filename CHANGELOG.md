# Changelog

Format: [Keep a Changelog](https://keepachangelog.com). Versioning: [semantic versioning](https://semver.org);
while the plugin is `0.x`, a breaking change bumps the middle number and the entry says **Breaking** at the top.

Anyone who installed the plugin gets the new version with `claude plugin marketplace update reel-forge`
followed by `claude plugin update reel-forge`. Claude Code flags a pending update in the `/plugin` screen,
but it never updates this plugin on its own unless auto-update is turned on for the marketplace. How to
publish a version and how it reaches people: [`docs/updating.md`](docs/updating.md).

## 0.13.0

The three gaps the 0.12 scoring found, closed in code rather than in advice.

### Added

- **Long holds split themselves.** `variant.py` cuts any clip held past `max_shot` (2.6 s) into
  consecutive pieces of the same take, alternating wide and a 1.22x punch-in (`zoom`, a new segment
  key), on half-beats in a beat grid. The voice keeps its seconds and captions tied to a shot follow
  it. `hero` shots, photos, Lives landing on their still and shots with their own zoom work are left
  alone. A 46 s variant with 9 s holds went from failing `renewal` to a 2.9 s longest wait.
- **`place_facts.py`**: prices, hours, how-to and mistakes for the places a catalog names, each with
  its source and the date it was checked, briefed to the directors. The trend-researcher has a second
  job, `place facts`. It is separate from `facts.py`: that is what the user said happened; this is what
  the world says about a place.
- **The user's own voice on a line**: `"own": "<recording>"` on a voice-script line replaces the
  synthetic read with the recording (silence trimmed, levelled), and the grid takes its real length.
- **`history.py` retention and calibration**: `result` takes the app's retention curve, the average
  watch time and the rubric's `score.json`; `calibrate` ranks which criteria actually move the user's
  audience once there are enough posts, and how much is lost in the first 3 s.
- **A closed loop before delivery**: a variant under 65 on the rubric, or under 5 on promise, open loop
  or payoff, goes back to its builder with the criteria and seconds, and is scored again.

### Changed

- `variant.py` defaults `fade_out` to 0.2 (was 0.45): no fade to black.

## 0.12.0

Scored against the platform. 28 of the most-watched travel TikToks (destination guides, itineraries,
cinematic montages and couple vlogs, 0.13-9.7 M views) and 11 of our own renders were watched end to end and
scored with one rubric by six reviewers, each with references and ours side by side. References
scored 42-76 (mean 59), ours 41-65 (mean 51). Ours already beat them on the open loop, the payoff and
having a person in it — the 0.10 work showed. What cost ours points was the same everywhere, in pace,
renewal and filler (3.4-4.0 of 10 against 6.3-7.2): shots held 3.5-6.7 s on
average with 9-14 s takes where nothing new happened (theirs: 0.9-1.9 s), a first frame that was
not the best one, a hook with no number or stake, closes that faded to black or recycled the
opening take, colour that jumped shot to shot, and foreign speech left untranslated.

### Added

- **`references/rubric.md`**: 16 criteria in six groups (hook 25, retention 20, story and heart 25,
  picture 15, sound 10, packaging 5), anchors per score and a `score.json` format. The critic and the
  story-doctor now score every variant with it; under 60, or under 5 on promise, open loop or
  payoff, is blocking.
- **`watch.py`**: watches a whole video 0-100 % — every frame on labelled sheets (at least one per
  shot, the last frame always included), cuts and shot lengths, cuts per third, transcript, on-screen
  text over time, loudness. The same instrument for references and ours.
- **Gate checks** in `verify.py`: `renewal` fails a stretch over 5 s with no new shot, text or voice
  line (a segment marked `"hero": true` is exempt); `pace` warns over a 3 s mean shot; `hook` warns
  when nothing is on screen or said in the first second, or the opening text runs over 8 words. The
  `ending` check also warns when the last shot is the opening take again.
- Concepts: **The first two seconds and the last two** (frame zero is the best frame, a promise with a
  number or a stake by 0.5 s, an open loop, a close that answers the hook in picture, a fact or an
  opinion in every beat) and numbered cards for lists. Editing: a declared pace curve, split long
  takes, cut on sound. Audio: subtitle foreign speech; narration to one friend, in first person,
  from 0.0 s. A length preference is served with more beats, never with longer shots.

### Changed

- **`"grade": "auto"` is one look per video**, voted by the shots' scenes weighted by length, with a
  separate winner for night shots. The old per-shot behaviour is `"auto-shot"`.
- Closes hold 1.5-2 s on the payoff with `fade_out` 0-0.3: no fade to black.

### Fixed

- A night grade crushed a dark sky between fireworks under the black threshold. The grade now never
  darkens deep shadows below the source (cached LUTs carry a revision), and `black_frames` measures
  true black (`pix_th` 0.05, was 0.12) — a correctly exposed night sky failed the gate.
- A shot asking for more seconds than its clip holds crashed the grade's probe frame
  (`UnidentifiedImageError`); the probe is clamped inside the clip.

## 0.11.1

### Fixed

- **Narrated variants stopped building: the subtitle alignment crashed.** PyAV 19 (resolved fresh by
  uv) removed `av.open(metadata_errors=…)`, which faster-whisper 1.2 still passes, so `transcribe.py
  --align` died with `TypeError: open() got an unexpected keyword argument 'metadata_errors'` and
  every narrated re-render failed. `transcribe.py` and the faster-whisper path of `wordmarks.py` pin
  `av<19`.

## 0.11.0

### Added

- **Colour grades by scene, shot by shot (`grade.py`).** One flat `look` over a whole video treated a
  snowy peak, a neon street and a plate of food the same; the user pointed at a travel reel's
  autumn grade and asked for colour "depending on the landscape or the shot". Eleven grades —
  autumn-moody, forest-deep, golden-hour, night-city, neon-night, tropical-water, alpine-snow,
  overcast-film, urban-clean, food-warm, interior-warm — built from a colourist's controls (per-hue
  HSL, contrast curve, lifted or crushed blacks, split toning, warmth, vibrance), with skin
  protected. `"grade": "auto"`, now the builder's default, picks one per shot from what the frame
  holds (foliage, greens, water, snow, sky, darkness, neon, warmth; catalog tags for food and
  interiors) and records it in the timeline; `grade_strength` keeps a video coherent.
- Video is graded while it decodes: each grade becomes a cached 65³ `.cube` for ffmpeg's `lut3d`;
  photos are graded once per shot. About a second per render.

## 0.10.2

### Fixed

- **A light copy came out 36 MB**, over the 30 MB a phone upload takes: CRF alone does not bound
  water or foliage. The light copy now has a 2.8 Mbps ceiling.

- **A builder killed four sibling builds.** To stop its own render it matched every
  `resources/A/.build.lock` on the machine. The builder's instructions now say: stop only the PID in
  your own lock file, never `pkill` by pattern, and report a stuck sibling instead of killing it.

## 0.10.1

### Added

- **`rank_moments.py`: the best moments, ranked.** For the user who would rather not answer the
  interview ("instead of random, rank the best moments"): every usable moment scored from the
  catalog's `human` signals — a laugh, a reaction, a real voice, a moment where something happens —
  over how pretty it is. With no stories, `stories.py brief` now points the directors at it.

## 0.10.0

**Breaking: every concept needs a human heart.** Three rounds of well-made videos were judged "fine
overall, but missing a more human touch — something that grabs me". They were clever devices
(scoreboards, quizzes, clocks) over good-looking shots, read by a synthetic voice, with the person
rarely in them and nothing that came from what he lived. A concept now names its `human_anchor` — the
real reaction, voice or face it turns on — and, when the user told stories about the trip, the ones it
is built on (`anchor_story`). `validate.py` sends back a concept without them.

### Added

- **`stories.py`: the interview.** Six short questions (the best moment, what went wrong or made you
  laugh, a surprise, someone you remember, when you felt far from home, the one story you'd tell a
  friend), answered by text or voice note (`from-audio` transcribes it), stored in the project's
  `stories.json` and handed to every agent with `brief`. Only the user's words; never an inferred
  feeling. `/reel` asks them before the concepts.
- **`human` on every catalog moment**: the emotion actually there, whether someone reacts, whether it
  is candid, what a real person says (transcribed), its story potential and the stories it shows.
- **`contact_sheet.py`: the user's veto over shots of himself.** When the preferences allow candid
  (not posed) shots of the subject, one numbered sheet goes to the user and `veto` strikes the numbers
  he names. Nothing with his face is used before he has seen it.
- **The director, the chief editor, the story doctor and the critic** now judge the human heart first:
  a real human moment at the hook or the turn, 2-3 moments where real people are heard and the
  narration is silent, narration from the user's own words, and a stop-scroll test on every render
  ("nothing, but it's pretty" is a blocker).
- **A strict pinned voice.** `voice.json` with `strict: true` means that voice or none: no fallback
  voice, no local voice; a variant whose voice could not be generated renders nothing (exit 5) and is
  run again later. `variant.py` honours it even when its own `variant.json` names the engine.

## 0.9.5

### Fixed

- **Highway exit signs were flagged as licence plates.** "51D", "16C": a plate now needs 4+
  characters.
- **The fallback voice was not found after a layout reset.** A docked, narrower panel has more rows,
  and `pick_voice()` ran out of scrolls before reaching it: it now allows 600.
- **A silent refusal never reached the fallback voice.** When Valentino's tile was clicked, the text
  was on the clip and even a brand-new project wrote nothing, the batch stopped as "saturated" and
  the run fell to the local voice; that case now counts as the voice failing, and the whole batch is
  redone with the fallback voice first.

## 0.9.4

### Fixed

- **CapCut's side panel came loose and the batch gave up.** CapCut 9.5 lets its inspector float as a
  window of its own ("setting"); once detached, every anchor was wrong and the script took the
  window for a modal ("usually the sign-in sheet") — twice in two rounds, sending narrated variants
  to the local voice. `capcut_voice.py` now docks it back through CapCut → Diseño → "Restablecer
  diseño actual" before a batch and before every line.
- **The length refit only helped narrated variants.** A beat-cut variant with no voice came out at
  40 s against a 45 s floor; `refit()` now runs on every build.
- **`live.py` could not link photos named by capture time** to their Live Photo: it now also reads
  the library uuid from a `_metadata.json` beside the file, and from the item's notes.

## 0.9.3

### Fixed

- **`voice_audible` failed narrations anyone could understand.** It compared every line with one
  background for the whole video; a narration interleaved with a loud, designed beat (a banquet
  chant that is the payoff) read as "under the background" and transcribed word for word. Each line
  is now compared with the quiet stretches near it (within 10 s, never the ending's own sound after
  the last line), and when the level still says "buried" the mix is transcribed: a line whose words
  are recognised (60 %+, accents folded) is audible. `--script-lang` sets the ASR language;
  `variant.py` passes it.

## 0.9.2

### Fixed

- **A round of 30 variants ran the Mac out of memory.** A dozen builders rendered at once, each
  holding its clips' frames in memory; macOS paused CapCut, and five narrations fell back to the
  local voice. Renders now take one of a few machine-wide slots (`$REEL_FORGE_RENDERS`, default one
  per ~12 GB of RAM, 1-4) and wait for a free one.
- **A paused CapCut was reported as a sign-in sheet.** `capcut_voice.py` now checks whether macOS
  suspended CapCut (process state T, "en pausa" in the Force Quit window) and says so, with the way
  out — and how to put back a side panel that came loose ("Restablecer diseño actual").
- **Dark caption cards made different variants look the same.** `compare_variants.py` compares
  frames that identify a shot; darkened or featureless frames (a quiz's blurred cards, black) are
  left out, after a pair with no clip in common measured 64 % shared.

## 0.9.1

### Fixed

- **`live.py` and `doctor.py` left a 2.4 GB copy of the Photos database behind on every run.** They
  read a private copy (never the live database while Photos writes to it) and never deleted it:
  five runs left 12 GB in the temp folder of a disk with 12 GB free. The copy is now removed as
  soon as it has been read.

## 0.9.0

### Added

- **Narrated variants keep the length the user asked for.** A voice that reads faster than planned
  (CapCut's Valentino at 1.4x) shortened a narrated variant to 38 s against a 45-90 s preference.
  `variant.py` now refits after the real voice: the missing seconds go to shots that can hold
  longer — stills, Lives landing on their still, clips with source left — never past a clip's
  end and never to the close. The floor is `min_s` or the user's length preference; when the story
  is simply too short it says so ("add a beat") instead of padding.
- **The voice is balanced against the clips by itself.** When the gate fails only because the voice
  sits under the clips' own sound, `variant.py` lowers the natural sound 4 dB and rebuilds (twice at
  most), and the final mix now has a limiter, so a louder voice can no longer push it past the
  -0.5 dBTP ceiling. Both were fixed by hand, a few dB at a time, in the previous round.
- **Strangers' plates, phones and e-mails are flagged.** `framecheck.py` reads the text in each
  frame with macOS Vision (the whole frame and four enlarged quarters, fragments of one line joined)
  and reports a legible plate, phone or e-mail as a finding; in catalog mode it leaves a "private
  text" note. A delivered variant had shown a readable licence plate that only a human caught.
- **`doctor.py`: is every catalog moment still on disk?** It repoints moved files (same name, or a
  working copy that still holds the window, originals preferred over a round's trimmed copies) and
  marks the rest `missing`, with the Photos uuid when the file only lives in the library. The
  catalog workflow runs it before the concepts: one round had 88 broken paths that every director
  went looking for on its own.
- **A Spanish fallback voice that sounds like the default.** If Valentino is refused or missing,
  `capcut_voice.py` redoes the whole batch with CapCut's "Guía de video" (a Latin-American male
  narrator at Valentino's pitch) instead of dropping to the local voice; `--fallback-voice`
  changes it. One voice per video, always, and the one used is recorded.
- **Every build writes its status into the concept's README**, between markers: length, cuts,
  voice (and whether it was a fallback), gate, framecheck. After a re-render, seven READMEs had kept
  the old voice and the old seconds.
- **Live Photos: Apple's own data.** `live.py` reads the still's exact instant from Apple's one-sample
  metadata track (1.17 s into one movie, not the assumed middle) and Apple's
  `LivePhotoVitalityScore`, which now also keeps a lifeless Live as a still.
- **`stabilize: true`** on a clip runs ffmpeg's deshake first, for handheld Lives and walking shots.

### Fixed

- `pick_voice()` could not find a voice above the one picked last: it only ever scrolled down. It
  now starts from the top of the catalog, and goes back up once when the list stops moving.
- Before building a new CapCut project because the text clip "disappeared", the timeline is scrolled
  up: stacked voice tracks push the text track off screen, out of the accessibility tree.

## 0.8.2

### Fixed

- **Eight narrated variants of a 30-video round fell back to the local voice** over a CapCut project
  that had lost its text clip. `capcut_voice.py` now builds a new project on its own — before the
  batch when the project has no text clip or is saturated, and mid-batch when the clip disappears —
  and answers 9.5's *"¿Seguro que quieres crear un nuevo proyecto?"*, which it used to leave open
  while it looked for the clip in the old project. The same eight then narrated with Valentino.
- **`voice_audible` failed CapCut's narration for the wrong reason.** It measured a fixed 2.5 s after
  every line; Valentino at 1.4x says a line in ~1.4-1.9 s, so the window was mostly silence and a
  narration that transcribes word for word came out "barely over the background". The window is now
  the line's own duration (`duration_hint_s`, `dur` or `end_s`, from the voice script).
- `variant.py` recorded CapCut's banner line ("CapCut 9.5.0 → profile…") as the reason it fell back;
  it now records the script's own verdict.

## 0.8.1

### Fixed

- **`live.py export` brought no movies from iCloud.** `osxphotos --download-missing` downloads the
  still of a Live Photo and not its movie (a real run: 320 photos asked, 15 stills, 0 movies). The
  iCloud-only ones are now exported by the Photos app itself, one per call, `using originals`, which
  writes the `.HEIC` and the `.mov` (same run: 320 of 320). `--timeout` sets the seconds per download.

## 0.8.0

**Breaking: what counts as a variant.** A pair of variants now has to differ in its middle: under 60 %
of the shots shared once rendered, and every non-base variant names at least 40 % new material in the
concept (`new_resources`). A new hook, a new close or a voice over the same cut no longer passes on its
own — a round passed that way on every pair and the critic still wrote *"after the first ~6 s, A and B
are the same video"*.

### Added

- **Live Photos as movement.** `skills/sources/scripts/live.py` finds which catalog photos are Live
  Photos (`scan`), puts their ~1.5-3 s movies in the workspace (`export`, from the library or through
  osxphotos for iCloud-only ones) and measures each one (`analyze`): the phone being raised or lowered
  is trimmed, and the movement is classed as `subject`, `camera`, `static` or `shaky`. The catalog
  workflow runs all three. On one real library well over half the photos were Live, favourites
  included, and the plugin had been using every one of them as a still with a push.
- **The engine plays a clip and lands on a still.** A video segment takes `end` (the source second
  where the usable picture stops) and `tail`: `hold` (the old behaviour), `boomerang`, or `still` with
  a `still` image — the Live Photo's movement, then the sharp photo for the rest of the shot. The
  shared builder resolves `still` like `src`, and the natural sound stops at `end` too.
- **The Spanish fallback voice ships with the plugin.** `skills/voices/designed/narrador-mx.json` is
  the recipe (a description and a seed for Qwen3-TTS VoiceDesign, no recording of anyone);
  `voice.py` designs it into the cache the first time it is asked for, and `resolve_voice.py` returns
  it at 1.15x whenever a Spanish run falls back to `qwen`.
- **`capcut_voice.py --busy-wait MIN`** (default 20, `$REEL_FORGE_CAPCUT_BUSY_WAIT`): when CapCut's
  server refuses the voice as busy, the batch retries on a 1, 2, 4, 8… min schedule instead of giving
  up at once. The refusal is per voice and temporary: on 26 sep 2026 it lasted until CapCut was
  relaunched, and Valentino then generated on the first try.

### Changed

- **CapCut Pro is the recommended setup** for Spanish narration: Valentino, the viral narrator, is an
  ElevenLabs voice served through CapCut and generates with a signed-in Pro account. Without it, the
  run narrates with `narrador-mx` and the README says so.
- The selection rules, the concept reference and the agents (creative director, chief editor,
  builder, critic, story doctor) say it: **photos move** — a still with a push is for photos with no
  usable movement — and **variants differ in the middle**.

### Fixed

- **A busy refusal was reported as a missed click.** The server's toast lasts ~2 s and the script
  polled too slowly to read it, then blamed the voice grid and sent the user to `--calibrate`. It now
  polls every 0.15 s, reads the "not compatible with text to speech" toast that precedes the refusal,
  and when the voice tile was found by name and clicked but no track uses it, calls it what it is: a
  server refusal.
- `export.py` checks that Photos answers before exporting, instead of hanging on a stuck Photos app.
- **`schemas/catalog-item.schema.json` was never in the repository**: the `.gitignore` rule for run
  catalogs (`catalog*.json`) matched it, so a fresh clone had a validator and workflows pointing at a
  schema that did not exist. It is tracked now.

## 0.7.1

### Added

- **`notes` for a run.** Both workflows take `args.notes` and hand it to every agent of the run, as
  context that adds to their definitions and overrides nothing. There was no way to tell the catalog
  agents what a run had prepared for them — that the file names carry the capture time and a
  favourite flag, that the dates live in a sidecar because thumbnails have no EXIF — short of editing
  the workflow.

## 0.7.0

**Breaking: where things are saved.** Projects now live in the user's videos folder under `Reel
Forge/<project title>/` (macOS `~/Movies/Reel Forge`, Windows `%USERPROFILE%\Videos\Reel Forge`,
Linux `$XDG_VIDEOS_DIR/Reel Forge`), rounds are `v1/`, `v2/`… straight under the project, and a
concept's folder holds **only its upload-ready videos**: everything else — README, previews, light
copies, reports, voice scripts, the shared material and each variant's build — is in `resources/`.
`REEL_FORGE_HOME` still overrides the root. The paths contain spaces; everything quotes them.

### Added

- **`upload.py` — the upload-ready encode.** The file loose in a concept's folder is no longer the
  render but an encode made for the platform's own re-encode to start from: 1080x1920, H.264 High,
  `yuv420p`, 30 fps constant, BT.709 tagged on every frame, CRF 17 capped at 14 Mbps, 2 s closed GOP,
  AAC-LC 48 kHz 256 kbps, `+faststart`. The publishing notes remind the user to turn on "Upload in HD",
  without which the app compresses on the phone first. A test caught the first version writing only
  the colour matrix and leaving primaries and transfer untagged.
- **`compare_variants.py` — can a viewer tell two variants apart?** Frame by frame on the rendered
  files, or by file and moment on the specs. A pair passes only if it changes the hook, the close, the
  voice or at least 40 % of the shots. Run over the previous round it reproduced the user's complaint
  exactly: all five concepts shipped two variants a viewer would take for the same video.

### Changed

- **Variants change what a viewer sees.** The old rule kept the hook and the close fixed and moved
  one small thing; "same cuts, other song" (the uploads carry no song) and "the same minus two shots"
  were valid variants. `differs_in` is now `base`, `hook`, `close`, `voice` or `shots`; `hook_resource`
  and `close_resource` name the new shot; the validator rejects a song-only variant and a second base;
  the story-doctor and the critic run `compare_variants.py` and a failing pair is a blocker.
- **Length preferences come in seconds.** `short` 15-25 s, `medium` 25-45 s, `long` 45-90 s, and the
  format tables' usual ranges become a floor. A user who said "they all feel short" had just received a
  round of 13-31 s, because every family in the tables anchors on 12-35 s.
- `verify.py` finds the timeline and the preview in `resources/` on its own, and the file-size
  ceiling rose to 280 MB (under the app's ~287 MB): the old 120 MB would have failed exactly the
  longer videos.

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
