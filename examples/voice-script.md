# Narration script format

A reel-forge voice script is plain text: **one line per sentence, starting with the second it comes in
on**. Nothing else. It's consumed by `skills/voices/scripts/narrate.py`, which generates one WAV per line
and glues them onto an **already rendered** video, without re-encoding the picture.

The file can be called `voice-script.md` or `voice-script.txt` and it ships **next to the MP4**, even when
the variant already has the voice baked in: that way the user can regenerate it with another voice or fix
a sentence without redoing the video.

The sentences are written in the run's **output language** — they're what gets spoken. The headings and
the notes are for whoever edits the file.

## The format

```
2.0   We arrived at night and couldn't see a thing.
6.4   At six in the morning we understood why everyone comes here.
11.8  Three days later we still hadn't come down off the mountain.
17.2  Save the route: part two is already shot.
```

- **First column: the second** the speaking starts, with a decimal point. Separator: two spaces or a tab.
- **Second column: the sentence**, exactly as it will be heard. No quotes, no stage directions, no
  character names.
- The lines go **in order** and **don't overlap**: each sentence has to fit before the next one.
- Everything after a line saying `Notes:` is comments and **doesn't get synthesized**.

### Variants the parser also understands

These show up on their own when the script is written by another agent or copied out of a table. They
work, but for writing from scratch use the one above:

```
[3.2] And here it goes on.
7.0 s | 2.4 s | The third line.
~11.4 s   With an approximate tilde and a duration column.
```

### What the parser ignores

| Ignored | Why |
|---|---|
| Blank lines, `---`, `===` and `#` headings | markdown structure, not script |
| Lines starting with `-`, `*` or `\|` | bullets and tables: **don't put the sentences there** |
| Everything after `Notes:` | comments for the human |
| Everything after `Optional` | an "optional" line usually overlaps a required one and buries it; if you want it, give it a second and move it into the table |
| Sentences under 8 characters or with no letters | leftovers from duration columns |
| Lines starting with `line`, `dur`, `in`, `video` | table headings |

Before generating anything, check how the parsing came out:

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/voices/scripts/narrate.py" voice-script.md --parse-only
```

It prints the `[{t, text}]` JSON it's about to synthesize. If a sentence is missing or a comment slipped
in, you see it there and not after waiting for the render.

## A full example

```markdown
# Script — "Day one" variant B (22.9 s video)

0.35   Nobody tells you what the first day is like.
6.20   At six in the morning the square is empty, and that lasts twenty minutes.
12.10  By midday there wasn't room to move.
18.60  Save the route: part two is already shot.

Notes:
- 0.35 comes in over the hook, before the first cut.
- 6.20 lands on the map segment, which runs 5 s: a long sentence fits.
- The 12.10 one has to end before 15.2, when the yellow caption comes in.
```

## How `narrate.py` consumes it

```bash
# Local voice (default: Qwen3-TTS on MLX, Apple Silicon)
uv run "$CLAUDE_PLUGIN_ROOT/skills/voices/scripts/narrate.py" \
    voice-script.md day-one-B.mp4 day-one-B-narrated.mp4

# With WAVs already generated (no re-synthesis)
uv run .../narrate.py voice-script.md day-one-B.mp4 day-one-B-narrated.mp4 --gen voices-day-one-B/

# The desktop app's voice — macOS ONLY, drives CapCut by clicks
uv run .../narrate.py voice-script.md day-one-B.mp4 day-one-B-narrated.mp4 --engine capcut
```

What it does, in order:

1. **Parses** the script (the rules above).
2. **Synthesizes** each sentence, if the WAVs don't already exist. It writes `lines.json` and calls
   `voice.py` (local) or `capcut_voice.py` (macOS). Both leave the same contract in the folder:
   **`l0.wav`, `l1.wav`… plus `durations.json`**, at 48 kHz, with silence trimmed and normalized to
   −16 LUFS.
3. **Mixes** each WAV onto the video at its line's second, keeps the MP4's original audio and copies the
   video stream through without re-encoding.

That same contract (`lN.wav` + `durations.json`) is what the editing engine consumes: if you'd rather the
voice went in at render time instead of being glued on afterwards, put each WAV in as an `audio` track of
the spec with its `at` set to the line's second (see `examples/spec-example.json`).

- **If `durations.json` is missing, the folder is incomplete**: the synthesizer was cut off mid-batch.
  Run it again; the `lN.wav` files that already exist don't get regenerated.
- **`--volume`** raises or lowers the voice against the video's audio. If you want the music to duck under
  the voice, that gets done when rendering the video, not here.

## Writing the script

- **The seconds come from the spec, not from your ear.** Add up the segment grid (`beats` × 60/bpm, or
  `dur`) and place each sentence inside the segment it refers to. A sentence about a shot that has already
  gone by feels out of sync even when the audio is perfect.
- **Write first, then measure.** Generate the WAVs, read `durations.json` and check that
  `t[i] + duration[i] < t[i+1]`. A sentence that steps on the next one sounds like two voices at once.
- **Pauses with punctuation, not by stretching the audio.** Commas and periods. Don't use `--slow`:
  stretching introduces audible artifacts.
- **Numbers as words**: "twenty minutes", not "20 min". Synthesizers read abbreviations and long figures
  badly.
- **Short sentences**, 6 to 14 words. A long sentence comes out monotone and leaves nowhere to cut.
- **Write it in the output language and pick a voice for that language.** A script in one language read by
  a voice from another is the first thing anyone notices.
- **No real people's voices.** The plugin's voices are synthetic and freely licensed. Don't clone anyone,
  not by audio reference and not by describing them in the voice design.

## Honest limits

| Engine | Where it runs |
|---|---|
| `qwen` / `voxcpm` (default, recommended) | **Apple Silicon** (they use MLX) |
| `piper` | cross-platform |
| `capcut` | **macOS only**: drives the desktop app by clicks, and the app can move its buttons |

If none of them applies on the user's machine, **deliver the video without voice and the
`voice-script.md` alongside it**: with the seconds already worked out, they can add the voice in whatever
app they like.
