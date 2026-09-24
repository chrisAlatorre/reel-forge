---
name: voices
description: Narration and voice-over for vertical videos. It decides which voice reads a run (CapCut's Valentino for Spanish, local freely licensed TTS otherwise), generates it with Qwen3-TTS, VoxCPM or Piper, designs synthetic voices from a description, marks the result word by word so the subtitles come from the voice, maps spoken viral audios, and mixes narration onto an already rendered video. Use it when someone asks for a voice-over, narration, a TikTok voice, TTS, dubbing, subtitles that match the voice, or adding a voice to a video.
---

# Voices and narration

Two paths, and which one runs is **not** the caller's whim: `scripts/resolve_voice.py` decides.

| Path | What it is | When |
|---|---|---|
| **App** (`scripts/capcut_voice.py`) | drives CapCut by clicks and collects the WAV | **the default for Spanish**, with **Valentino at 1.4x** |
| **Local** (`scripts/voice.py`) | open-weight models, run on the machine, clear license | every other language, and the fallback when CapCut is not there |

Both leave **the same contract**: `l0.wav, l1.wav… + durations.json` in a folder, 48 kHz mono,
−16 LUFS. Anything that consumes narration (the editing engine, `narrate.py`) works the same with
either. A third file, `words.json`, carries the word-by-word marks (see below) and is what the
subtitles are placed from.

## Who reads it: `resolve_voice.py`

```bash
R=${CLAUDE_PLUGIN_ROOT}/skills/voices/scripts/resolve_voice.py

uv run $R --lang es-MX            # what would narrate right now, and why
uv run $R --lang en-US --json     # the same, for another script to read
uv run $R --lang es --local-only  # never the app path (it still says it is a fallback)
```

The order, and it is not negotiable:

1. **What the user asked for** — `--engine` / `--voice`, the script's own `engine` field, or the
   voice pinned in `~/.config/reel-forge/voice.json`. A pinned voice that does not speak the run's
   language is **not** used silently: it is reported and the resolution carries on.
2. **CapCut's Valentino at 1.4x**, whenever the output language is Spanish and CapCut is installed.
   That is the voice the Spanish-speaking side of the platform actually sounds like; a local voice
   there reads as a robot next to it.
3. **A local engine** — `qwen` on Apple Silicon, `piper` anywhere else.

Branch 3 on a Spanish run is a **fallback**, and the delivery may not hide it. `resolve_voice()`
returns `disclose`, one sentence, and that sentence goes **in the variant's README**:

> Narrated with the local voice (qwen), not with Valentino: CapCut is not installed on this
> machine. The trend voice can be added in the app at publish time.

`narrate.py` prints it, and `voice.py` prints it too when it is called directly for Spanish, so
there is no way to generate that fallback without the sentence appearing.

## The length comes from the script

A video is not 15 s because 15 s is what the template said. **Write the narration the story needs
— a hook, a middle that develops it, a landing — and let the edit be as long as that takes.** Some
concepts land in 12 s; a story with a turn in it needs 40, 60 or more, and cutting it at 20 leaves
the viewer with the feeling that something was interrupted.

```bash
uv run $R --estimate-file voice-script.json   # ~seconds of narration, per line and total
```

The estimate is what the concept is planned against; once the WAVs exist, `durations.json` is the
truth and the grid is rebuilt around it. What is never acceptable is the reverse: trimming the last
line, or speeding the voice up, to make a story fit a length nobody chose on purpose.

## Language first

Every video has an **output language** (`REEL_FORGE_LANG`, the `"lang"` field in
`~/.config/reel-forge/config.json`, or the run's `--lang`). Resolve it before offering anything, because
it decides which voices are even candidates — and, for Spanish, it is what sends the run to Valentino.
`resolve_voice.py` reads those three sources in that order, so use it instead of re-implementing them.

- **Filter the catalog by language and region.** A voice trained on Iberian Spanish reading a Mexican
  script is immediately noticeable, and so is a US voice reading British copy. If there is no voice for
  the exact region, offer the closest one and say plainly that the accent won't match.
- **The script goes in that language**, and so does the description you use to design a voice.
- If the pinned voice in `~/.config/reel-forge/voice.json` doesn't match the run's language, say so in
  one line and offer to pick a voice for the new language instead of silently reading with the wrong
  accent.

Which engine covers what, as of this writing: `qwen` and `voxcpm` handle Spanish and English well
(designed voices, any accent you describe); `piper` has per-language voice packs, so you download the
one matching the tag (`es_MX-*`, `en_US-*`, `pt_BR-*`…) and there simply is no voice for a language with
no pack.

## What is forbidden

This isn't a style recommendation, it's the line you don't cross:

- **Do not clone a real person's voice.** Not actors, not creators, not celebrities, not a friend, and
  not the user themselves from audio that isn't theirs and current. The models here clone from a
  reference: that reference has to be a **designed synthetic voice** (see below) or audio the user has
  explicit permission for.
- **Do not describe a real person** when designing a voice ("like the narrator of that documentary",
  "so-and-so's voice"). Describe timbre, age, accent and pace, never a person.
- **Do not use unofficial APIs that require the user's session.** The TikTok TTS endpoint with a
  `session id` and `edge-tts`-style wrappers belong here: they're internal services, they violate the
  terms, they can get the account banned and they break without warning. If a paid service is needed, the
  user opens their own account and their own API key.
- **Do not embed voices with a dubious license in anything branded or budgeted.** For that, a commercial
  service with a written license.

If the user insists on cloning someone, explain the problem once and offer to design a synthetic voice
with a similar timbre. Don't do it.

## The local path

The fallback, and the default outside Spanish. Everything here is freely licensed and reproducible,
and none of it sounds like the trend: when it narrates a **Spanish** variant, the README carries
the sentence from `resolve_voice.py` (the script prints it for you).

```bash
V=${CLAUDE_PLUGIN_ROOT}/skills/voices/scripts/voice.py

echo '["First sentence.", "Second sentence."]' > lines.json
uv run $V lines.json voices/ --engine qwen --voice narrator
```

Out comes `voices/l0.wav`, `voices/l1.wav` and `voices/durations.json`.

### Engines

| Engine | Model | License | Platform | Notes |
|---|---|---|---|---|
| `qwen` | Qwen3-TTS 12Hz 1.7B | Apache-2.0 | MLX = **Apple Silicon** | the best measured; ~3-5 s per line |
| `voxcpm` | VoxCPM2 | Apache-2.0 | MLX = **Apple Silicon** | native 48 kHz; the female voice sometimes lisps |
| `piper` | Piper | MIT | any | fast, light, lower quality; the path off a Mac |

`qwen` and `voxcpm` run in a separate environment with `mlx-audio`: the script relaunches itself with
`uv run --with mlx-audio`. The first time they download ~4 GB from Hugging Face.

**Off Apple Silicon**, use `--engine piper` (voices from `huggingface.co/rhasspy/piper-voices`, MIT,
stored in `$REEL_FORGE_CACHE/voices/`) or run Qwen3-TTS/VoxCPM from their official PyTorch repos. Don't
promise MLX on Linux or Windows.

With `piper` the voice **follows the run's output language**: pass `--language en` / `--language es-MX`
(or set `REEL_FORGE_LANG`) and the script picks the matching voice and downloads the `.onnx` +
`.onnx.json` pair on first use — about 60-110 MB, once per voice. `--voice <id>` names one outright and
wins over the language. With neither, it uses `en_US-ryan-high`. Known languages: `en`, `es`, `pt`, `fr`,
`de`, `it`; for anything else, pass `--voice` with an id from the repo, or use `--engine qwen`.

`--preset tiktok` is **Spanish only** (it imitates the generic TTS timbre of the video apps, with Latin
American phonemes). It ignores `--language` and says so.

Measured metrics (UTMOSv2 / WER with whisper large-v3, Spanish):

| Voice | UTMOS | WER |
|---|---|---|
| qwen, narrator | 3.64 | 0 % |
| qwen, narrator (f) | 3.82 | 0 % |
| voxcpm, narrator | 3.69 | — |
| piper | 2.58 | — |

Rejected and why: Chatterbox (MIT, good but it speaks fast and invents words in the female voice), ZONOS2
(the voice changes between lines), F5-TTS / Fish / OpenAudio / Voxtral / Higgs / OmniVoice
(**non-commercial** weights). macOS `say` and the system voices sound like a 2010 robot: no.

### Designing a voice from a description

Qwen3-TTS VoiceDesign generates a voice **that doesn't exist** from a text description. That voice gets
saved as a reference (`.wav` + `.json` with the read text, the description, the seed and the license) and
then the engines clone it line by line.

```bash
uv run $V --create-voice narrator \
  --description "Native Mexican Spanish speaker, man around 40, deep warm baritone, unhurried pace, documentary tone, no foreign accent" \
  --seed 11
```

What genuinely matters when writing the description:

- **Write it in the voice's language.** An English description for a Spanish voice comes out with an
  American accent: in testing, up to 20 % English phonemes in female voices.
- Say **where the speaker is from** ("native Mexican Spanish speaker"), not just the language.
- Describe **timbre, age, register and pace**. Never a specific person.
- **Try 3 or 4 seeds** (`--seed`) and keep whichever sounds best. The same description with another seed
  gives another voice.
- Keep the reference: as long as the `.wav` and its `.json` are there, every video in the project sounds
  like the same person.

### Writing so it sounds good

- **No `--slow`.** Stretching the audio introduces artifacts (in one test, estimated PESQ went from 4.3 to
  2.3 with a factor of 1.08). To pause, **punctuate**: commas, periods and short sentences.
- **Numbers as words.** "twenty-three degrees", not "23°".
- One idea per line. The lines are the units you later place on the timeline.
- Acronyms and odd names: write them as they're pronounced.

## Speaker treatment

The chain applied to each line (the `clean` preset, the default for the new engines):

1. **Silence trimming** at both edges (`silenceremove` with `areverse`). The space between lines is set by
   the edit, not by the WAV.
2. **High-pass at 60 Hz**: removes rumble without thinning the voice.
3. **Two-pass linear loudnorm to −16 LUFS / −1.5 dBTP**, 48 kHz mono. Two passes: first measure with
   `print_format=json`, then apply with the measured values. A single pass pumps.

And what it does **not** carry:

> **No reverb. Ever.** The historical preset carried an `aecho=0.8:0.5:35:0.12` to "give it body" and the
> result was exactly the opposite: the voice sounded **far from the mic, like a cheap mic**. A TikTok
> voice-over has to sound pressed against the ear. No room, no echo, no "ambience". If it sounds dry,
> that's right.

Compression and EQ, sparingly: in timbre-matching tests, adding brightness and compression **lowered**
the similarity and didn't improve intelligibility. The `announcer` preset (high-pass 70 + a 160 Hz and
3.5 kHz lift + 3:1 compressor + echo) stays in the script only for historical compatibility. **Use
`clean`.**

Presets available with `--fx`: `clean` (default and recommended), `tiktok` (dry, to imitate the flat
timbre of the apps' TTS), `announcer` (historical, with echo: don't use it).

## The CapCut path — Valentino (macOS only)

**This is the default for Spanish.** `resolve_voice.py` sends any Spanish run here as long as
CapCut is installed, with the voice **Valentino** at **1.4x**.

**What it is.** The voices in CapCut's catalog are ByteDance's and only exist inside the app: there is no
public API. `scripts/capcut_voice.py` automates the desktop application — it pastes each line into a text
clip, picks the voice and presses "Generate voice content" — and collects the WAV.

**Why it works without exporting anything.** CapCut writes the text-to-speech audio straight into the
project folder, before any export:

```
~/Movies/CapCut/User Data/Projects/com.lveditor.draft/<MM>/<DD>/textReading/<hash>.wav
```

(there's a copy in `.../User Data/Cache/ttsTemp/`). It's a 128 kbps MP3 inside a `.wav` container,
44.1 kHz mono. You just copy it and run it through ffmpeg: no video export, no watermark. The folder can
be moved with `$CAPCUT_DRAFTS`.

### How it's used

```bash
C=${CLAUDE_PLUGIN_ROOT}/skills/voices/scripts/capcut_voice.py

uv run $C --prepare                   # prints the manual steps and positions the window
uv run $C lines.json voices/ --speed 1.4 --voice "Valentino"    # Valentino at 1.4x = the default
uv run $C --preflight                 # only the checks: CapCut, window, permissions, project state
uv run $C --calibrate                 # screenshot with the current coordinates
```

Manual preparation, **once per batch** (~1 minute):

1. **A NEW project** (File → New project). No video needs to be added.
2. Text → Add text → the `+` button on "Default text".
3. Right panel, **Text** tab: paste the first sentence with **Cmd+V**.
4. **Text to speech** tab → category chip → click the voice → **Generate voice content**. An audio track
   with the voice's name has to appear.
5. Drag the divider between the player and the timeline until the "Generate voice content" button sits
   where `P['generate']` says (check it with `--calibrate`).

After that, the script runs the full cycle per line: scroll the timeline up → select the text clip →
paste → Text to speech tab → chip → click the voice → Generate → wait for the WAV → convert it. ~25 s per
line. **It resumes on its own**: if `lN.wav` already exists it skips it.

Note: **the voice is chosen by the click coordinate**, not by `--voice`. That parameter only makes the
messages and the diagnostics name the right voice. To change voice, recalibrate `P['voice']` (and
`P['narration_chip']` if it's in another category) with `--calibrate`.

Speed is applied **outside** CapCut with `atempo` (which preserves pitch). `1.4` is the pace of the
documentary-narration trend.

### Rules that cost blood

- **A new project per batch.** A project with ~110 regenerations on it stops writing WAVs: the
  "Generating the voice…" dialog appears, closes, and no file shows up, **with no error message at all**.
  The free voices kept working in that same project, so it looks like a per-project cap on the premium
  voices. A new project generated on the first try.
- **Never type with `osascript ... keystroke`**: CapCut eats the spaces and the accents
  ("Everysummer,aspecimen…"). Always `pbcopy` + Cmd+V.
- **Everything goes through coordinate clicks.** There is no API and no usable accessibility tree. The
  script pins the window at `(0, 33)` with size `1728x999` via AppleScript before every pass. With a
  different screen or version, `--calibrate` leaves a screenshot and the coordinates of the `P`
  dictionary.
- **Watch the Dock:** a click near the bottom edge brings another app to the front.
- **The voice panel redraws** (sometimes one column, sometimes a grid) and scrolls back to the top when
  you re-enter. That's why the cycle always presses the category chip before looking for the voice: it
  leaves the list in a known place.
- **The Generate button gets disabled** once the clip already has a voice; it re-enables when you click
  the voice in the catalog again.
- **Every generation adds a new audio track** (recent versions removed the "Update the voice from the
  script" checkbox). That's why the script scrolls a long way up before each click: with 20 tracks, a
  short scroll leaves the click on an audio track and the text gets pasted in the wrong place.

### When no audio comes out

The script reads the project's `draft_info.json` and tells the two failures apart without guessing:

- **the text did NOT reach the clip** → the clicks are landing wrong: `--calibrate` and adjust `P`.
- **the text did arrive but no track uses that voice** → the click in the grid landed outside.
- **the text arrived and the voice is right, but there's no WAV** → the project is burnt: create a new
  one. To confirm, apply a free voice by hand: if that one generates, the cap is on the premium voices.

Plan B if the interface moved the buttons: paste **the whole script at once** (one line per paragraph),
generate once and cut by silences.

```bash
uv run $C lines.json voices/ --split ".../textReading/<the wav>.wav" --threshold -38dB --min-silence 0.45
```

It prints how many chunks it detected so you can compare against the number of lines.

### It fails loudly, with a code, never in silence

The two failures that used to look identical are now told apart by reading the project's own
`draft_info.json`, and each leaves a different exit code:

| Code | What happened | What to do |
|---|---|---|
| 3 | **the interface moved**: the text never reached the clip, or the voice-grid click landed outside | `--calibrate` and fix `P`; retrying changes nothing |
| 4 | **the project is saturated** and a brand-new project did not fix it either | check by hand with a voice with no diamond badge |
| 5 | environment: no cliclick, no CapCut, no drafts folder, no Accessibility permission | the message names the missing piece |

Saturation is the only one it retries: it creates a new project, rebuilds the text clip, verifies
against `draft_info.json` that the text actually landed, and carries on — **once per run**. What was
already generated stays on disk and `durations.json` is deliberately not written, which is how
`narrate.py` knows the folder is incomplete and how a re-run resumes.

### The warning you owe the user

This path **depends on CapCut's interface and it will break**. It already happened once mid-batch, and
silently. It also depends on Valentino still being in their country's catalog. If it breaks and there's
no time to recalibrate, deliver the video **without voice** plus the `voice-script` with the timings,
and let the user add it in the app. Otherwise the local path takes over, and the variant's README
says which voice actually read it.

## Marks for the subtitles: `wordmarks.py`

Subtitles used to be placed from an estimate of how long a sentence "should" take. On screen that
drifts, and it drifts worst at the payoff. **When there is narration, the captions come from the
voice that will actually be heard.**

```bash
W=${CLAUDE_PLUGIN_ROOT}/skills/voices/scripts/wordmarks.py

uv run $W voices/ --script voice-script.json     # writes voices/words.json
uv run $W --check voices/words.json              # re-read it: lines, words, low-confidence ones
```

It transcribes the generated `lN.wav` with word-level timestamps and shifts them onto the video's
timeline with each line's `start_s`, so every `start`/`end` in `words.json` is **video time**. The
rule it exists to serve, checked with **0.25 s** of tolerance and in both directions:

- a caption may not appear before its word is spoken, nor linger after it;
- and if the voice **names something concrete**, that image is on screen while it is named.

`narrate.py` writes `words.json` on its own after generating; it is best-effort, and when the
transcriber cannot run it says so instead of leaving captions to guesswork. Transcribing the
generated voice also catches the failure nobody looks for: a TTS that swallowed a word or read a
number wrong shows up as a low-confidence word.

## Spoken viral audios: `sound_map.py`

A trending song only needs a BPM. A **spoken** audio — a meme, a line everybody quotes — has
phrases, pauses and one moment that has to land, and cutting it on a BPM grid chops sentences in
half and buries the punchline.

```bash
M=${CLAUDE_PLUGIN_ROOT}/skills/voices/scripts/sound_map.py

uv run $M <URL> sound-map.json                 # fetch, transcribe, map
uv run $M --audio meme.m4a sound-map.json      # a file already on disk
uv run $M --check sound-map.json               # re-read and summarize
```

It writes `cut_grid` (every phrase start: **cut there, never inside a phrase**), the pause after
each phrase (where a reaction shot or a held frame fits) and which phrase is the **punchline**,
with how confident that guess is — `--punchline N` overrides it after one listen.

The audio is fetched **to measure it**, exactly like the 30 s preview used for BPM. The map says so
itself with `"embed_in_clean": false`: the file that gets uploaded carries **no** trending audio,
only the local `-preview` does, and the user attaches the real sound in the app at publish time,
which is also what makes the video count toward the trend.

## Gluing the narration onto an already rendered video

`scripts/narrate.py` takes a **voice-script** and a finished MP4 and mixes the voice on top
**without re-rendering the video** (`-c:v copy`).

```bash
N=${CLAUDE_PLUGIN_ROOT}/skills/voices/scripts/narrate.py

uv run $N voice-script.json --parse-only                              # ALWAYS first: validate, generate nothing
uv run $N voice-script.json video.mp4 video-narrated.mp4              # the voice resolve_voice.py picks
uv run $N voice-script.json video.mp4 out.mp4 --engine capcut         # force the app's voice
uv run $N voice-script.json video.mp4 out.mp4 --gen voices/           # WAVs already generated
uv run $N old-script.txt --to-json voice-script.json --lang es-MX --concept x --variant B
```

### The script is a contract

The input is a `voice-script` document, and its shape lives in `schemas/voice-script.schema.json`.
`narrate.py` validates the file **before generating a single WAV** — delegating to
`schemas/validate.py` when it can reach it — and names the field that is missing:

```json
{"concept": "empty-square", "variant": "B", "lang": "es-MX",
 "video": "empty-square-B.mp4", "video_duration_s": 38.5,
 "engine": "capcut", "voice": "Valentino", "duck_db": -12, "duck_pad_s": 0.3,
 "lines": [{"start_s": 0.35, "text": "Nadie te cuenta cómo es el primer día.",
            "duration_hint_s": 2.6, "emphasis": "strong"},
           {"start_s": 6.20, "text": "A las seis de la mañana la plaza está vacía."}]}
```

That validation exists because of a real batch: every agent invented its own layout, the tolerant
parser silently kept nothing, and narrated variants shipped **mute** without anybody noticing until
they were watched. The old plain-text format (`0.5  the line…`) still narrates, with a warning and a
report of every line it dropped; `--strict` refuses it and `--to-json` converts it once and for all.

`engine: "none"` means that variant is meant to ship **without** voice, with the file alongside it so
the user adds the narration themselves — `narrate.py` refuses to synthesize it unless `--engine` is
passed on purpose.

### What it does with it

- It resolves the voice (`--engine` → the file's `engine` → `resolve_voice.py`) and prints the reason
  plus, on a Spanish fallback, the README sentence.
- It generates into `voices-<name>/`, or reuses `--gen`. `durations.json` is the "this folder is
  complete" signal: without it the folder is regenerated, resuming line by line.
- Once the WAVs exist it checks the **real** durations — the overlap `duration_hint_s` could only
  guess at — and warns when a line is still speaking as the next one comes in.
- It writes `words.json` with the word-by-word marks (`--no-word-marks` skips it).
- **It ducks**: the video's own audio drops under every line marked `duck: true` by `duck_db` with a
  `duck_pad_s` ramp, through a `sidechaincompress` keyed by the voice itself, so the music comes
  back up in the gaps. That replaces a delivery where the clip's audio buried the narration and had
  to be pulled down by hand afterwards.
- **If the video comes in with no audio track, the mix still lasts as long as the video.** With
  `amix duration=first` the first input would be the first voice line and the mix got cut when it
  ended (at 3 s of a 35 s video, with nothing warning). It uses `duration=longest`, an `apad` to the
  video's length and only then an `atrim` — `atrim` alone cannot extend.
- At the end, `alimiter=limit=0.95`: the voice on top of the original audio clips easily.

## Common mistakes

1. Adding reverb "to give it body": it sounds far from the mic.
2. Stretching the audio with `--slow` instead of punctuating the script.
3. Writing the voice description in English and getting a Spanish voice with an American accent.
4. Numbers as digits: the TTS reads them wrong or skips them.
5. Reusing the same CapCut project all week until it stops generating, silently.
6. Passing the whole script to `narrate.py` with the notes at the end, and narrating them.
7. Assuming MLX runs on Linux.
8. Generating the script in one language and the voice in another, because the pinned voice was never
   re-checked against the run's language.
9. Narrating a Spanish video with a local voice **without saying so**. Valentino is the default;
   anything else is a fallback and the variant's README carries the reason.
10. Placing the subtitles from an estimate when `words.json` exists. If there is narration, the
    captions come from the voice, within 0.25 s.
11. Writing the script to fit a length somebody picked in advance. The story sets the length: write
    the beginning, the middle and the landing, estimate it, and let the edit be that long.
12. Cutting a spoken viral audio on a BPM grid instead of on `sound_map.py`'s phrase starts, which
    is how a punchline ends up split across a cut.
