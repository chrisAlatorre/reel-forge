---
name: voices
description: Narration and voice-over for vertical videos with local, freely licensed TTS (Qwen3-TTS, VoxCPM, Piper), designing synthetic voices from a description, speaker treatment, and mixing the narration onto an already rendered video. Use it when someone asks for a voice-over, narration, a TikTok voice, TTS, dubbing, or adding a voice to a video.
---

# Voices and narration

Two paths, and it's worth understanding why there are two:

| Path | What it is | When |
|---|---|---|
| **Local** (`scripts/voice.py`) | open-weight models, run on the machine, clear license | **the default, always** |
| **App** (`scripts/capcut_voice.py`) | drives CapCut by clicks to get a voice from its catalog | only if the concept asks for that exact viral voice |

The first is reproducible, cross-platform and clearly usable commercially. The second depends on an
interface that can change tomorrow.

Both routes leave **the same contract**: `l0.wav, l1.wav…` + `durations.json` in a folder, 48 kHz mono,
−16 LUFS. Anything that consumes narration (the editing engine, `narrate.py`) works the same with either.

## Language first

Every video has an **output language** (`REEL_FORGE_LANG`, the `"lang"` field in
`~/.config/reel-forge/config.json`, or the run's `--lang`). Resolve it before offering anything, because
it decides which voices are even candidates.

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

## The CapCut path (macOS only)

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
uv run $C lines.json voices/ --speed 1.4 --voice "Voice name"   # --voice only labels the messages
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

### The warning you owe the user

This path **depends on CapCut's interface and it will break**. It already happened once mid-batch, and
silently. It also depends on that voice still being in their country's catalog. If it breaks and there's
no time to recalibrate, deliver the video **without voice** plus a `voice-script.txt` with the timings,
and let the user add it in the app. For everything else: `voice.py --engine qwen`.

## Gluing the narration onto an already rendered video

`scripts/narrate.py` takes a timed script and a finished MP4 and mixes the voice on top **without
re-rendering the video** (`-c:v copy`).

```bash
N=${CLAUDE_PLUGIN_ROOT}/skills/voices/scripts/narrate.py

uv run $N script.txt video.mp4 video-narrated.mp4                  # local voice (qwen)
uv run $N script.txt video.mp4 video-narrated.mp4 --engine capcut  # the app's voice (macOS)
uv run $N script.txt video.mp4 video-narrated.mp4 --gen voices/    # WAVs already generated
uv run $N script.txt --parse-only                                  # check the parsing before generating
```

Script format: one line per delivery, starting with the second it comes in on. The parser tolerates the
variants that come out of a hand-written script or one written by another agent:

```
0.5   This is where it all starts.
[3.2] And here it goes on.
7.0 s | 2.4 s | The third line.
~9.8 s  The fourth.
```

Parser rules:

- **It stops at a `Notes` or `Optional` heading.** Everything below is comments, not lines. Without this,
  a comment like "…from 15.8 to 16.9 s, if you bring it in earlier…" comes through as narration. A block
  marked "optional" usually overlaps a required line and buries it completely: if you really want it, move
  it into the table with its own second.
- Separators, markdown headings and lines with no real text are ignored.
- Leftover duration columns get cleaned up.

**Always run `--parse-only` first** and look at the list it prints. It takes a second and it saves you
generating twenty lines of garbage.

Mixing details:

- The video's original audio **is preserved**; the voice is summed on top with `adelay` + `amix`. If you
  want the music to duck under the voice, do it when rendering the video, not here.
- **If the video comes in with no audio track, the mix still lasts as long as the video.** With
  `amix duration=first` the first input would be the first voice line and the mix got cut when it ended
  (at 3 s of a 35 s video, with nothing warning). It uses `duration=longest` plus an `atrim` to the
  video's exact duration.
- At the end, `alimiter=limit=0.95`: the voice on top of the original audio clips easily.
- `--volume` adjusts the voice's gain. `--gen` reuses an already generated folder; if `durations.json` is
  missing, it treats the folder as incomplete and regenerates (resuming).

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
