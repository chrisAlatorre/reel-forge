# Audio: music, natural sound and narration

Audio is half the video and it's where the most failures go unnoticed: a gap, a volume peak or a
duplicated track make nothing fail, they just come out wrong.

## Base rule

**The engine doesn't carry over the clips' audio.** Segments contribute image only. Every sound —
diegetic, music, voice — is assembled separately and comes in as `audio` tracks in the spec.

## Diegetic sound (the real audio of the shots)

A proven recipe, in a single script that generates one continuous WAV and comes in as a single track at
`at: 0`:

1. A list of pieces: `(out_t, source, start, duration, gain)`.
2. Each piece: `atrim` + `asetpts` + 50 ms fades at both ends + `adelay` to its second.
3. Everything through `amix` with `normalize=0`.
4. Finally `loudnorm I=-16` and a limiter.

Details that matter:

- **Photos carry no audio.** Cover them with the ambience from the clip of that same scene, or they come
  in silent and the hole is audible. Clean trick: adjacent cuts that share a source get grouped into
  **one piece that keeps running**, so the photos inherit the neighbouring clip's ambience.
- **Per-cut volume, not automatic.** Normalize each piece to its own LUFS target (measure with
  `loudnorm print_format=json`, apply with `volume=NdB`) and leave the final mix at -14 LUFS. That way
  you can design a drop (one scene at -10 and the next at -26) on purpose.
- Near-silent takes (a corridor, an animal breathing): `dynaudnorm=f=180:g=21:p=0.62` before raising
  them, or the track sounds broken.
- **A real J-cut:** to bring the audio in before the image without losing lip sync, also move the
  source's entry point, not just the track.

Mandatory verification:

```bash
ffmpeg -i out.mp4 -af "silencedetect=n=-45dB:d=0.25" -f null -    # gaps
ffmpeg -i out.mp4 -af "loudnorm=print_format=summary" -f null -   # peak below -0.5 dBTP
ffprobe -v error -select_streams a -show_entries stream=index,codec_type -of csv out.mp4  # one track only
```

## Finding the exact second

- The timings the catalog notes drift by several seconds. To nail a line or a beat, **transcribe** the
  audio with word-level marks (a local transcription model is enough) or pull a volume profile every
  0.2 s in the voice band (300-3000 Hz).
- For shouting, a party or a crowd, transcription fails: use **onsets** in that same band (onset
  strength + peak picking) and **validate with a 4 fps strip** who is on screen.
- **The second with the good audio is not the second with the good image.** In a real clip the three
  shouts were at 47.6 / 49.1 / 50.5 s, but the camera was pointed at a wall there: the good image was at
  22.4 s. Separate the image source from the audio source and **look at the frame** of the entry point.

## Music

- **Don't embed copyrighted music in what gets uploaded.** Two files: `x.mp4` clean and
  `x-preview.mp4` with the song, just for the user to hear. The official sound is added in the app.
- A public 30 s preview for measuring BPM and for the preview file. See `trends.md`.
- **Videos over ~29 s need a looped bed**, or the music runs out and the ending goes silent with nothing
  warning you. Now that the length comes from the story, that is most of them: build the loop by
  default and check the last second, which is exactly where a video that "ends abruptly" gives
  itself away. `acrossfade=d=1.5` between the preview and a shifted copy, `atrim` to the exact length,
  `loudnorm I=-22` (a bed, under the natural audio which sits at -16) and gain 1.0 over the normalized
  bed — at gain 0.30 over the raw preview the music is inaudible.
- The bed is made **once, in `common/`**.
- On loops, set the audio fade-out to 0: the default fade breaks the loop.

## Sound effects

Ambiences and light hits: ambience at 0.2-0.3 depending on the scene, a shutter on photos and freezes, a
soft pop when a caption enters, a riser before a reveal, and a dry hit only for the punchline. Use
freely licensed SFX and **keep the license** next to the files. Never the same hit on every cut: it
turns into noise.

## Narration

When: in the documentary/storytime format and in lists. In a photo dump it gets in the way.

### Who reads it

**Not whoever the caller felt like.** `skills/voices/scripts/resolve_voice.py` decides and says why:

1. what the user asked for, or pinned in `~/.config/reel-forge/voice.json`;
2. **CapCut's Valentino at 1.4x** when the output language is Spanish and CapCut is installed — the
   default, because it is the voice this side of the platform actually sounds like;
3. a local engine (`qwen` on Apple Silicon, `piper` elsewhere) as the **fallback**.

Branch 3 on a Spanish video is not a neutral choice: it does not sound like the trend, so the
variant's README carries the sentence the resolver returns ("Narrated with the local voice (qwen),
not with Valentino: …"). The scripts print it; do not deliver without it.

`skills/voices/scripts/voice.py` generates `l0.wav, l1.wav… + durations.json` (48 kHz, silence
trimmed, gentle high-pass, two-pass normalization to -16 LUFS). That is **the contract**: any other
voice source, the app path included, leaves the same three things so the engine consumes it
unchanged.

**Generic TTS with echo sounds like "a cheap mic, far from the mic" and was rejected in production.**
Dry, no added echo, ever.

- Use a model with a clear commercial-use license and **designed synthetic voices**, not cloned ones.
- **Never clone a real person's voice** (actors, celebrities, the platform's voice). Don't describe
  one so the model imitates it either.
- Write a new voice's description **in the target language**: asking in English for a Spanish voice
  brings in a foreign accent. Try 3-4 seeds and keep the best.
- Don't stretch the voice to slow it down: it introduces artifacts. For pauses, use commas and
  periods in the script. Numbers spelled out as words.
- If the user wants commercial-service quality, that needs their account and their key: ask them for
  it, don't sign them up.

### The narration is what sets the length

The script is written for the story — an opening, a middle that develops it, a landing — and the
video lasts however long that takes. `resolve_voice.py --estimate-file voice-script.json` gives the
seconds before anything is synthesized, so the concept can be planned against a real length instead
of a template's 15 s. Once the WAVs exist, `durations.json` is the truth and the grid is rebuilt
around it. Never trim the last line or speed the voice up to hit a length nobody chose on purpose:
that is exactly the video that feels cut off.

### Subtitles come from the voice, not from an estimate

If a segment carries narration, its captions are placed from
`skills/voices/scripts/wordmarks.py`'s `words.json`: every word with the second it is spoken, in the
video's timeline, transcribed from the WAV that will actually be heard. `narrate.py` writes it
automatically. The rule, checked with **0.25 s** of tolerance, runs both ways:

- a caption may not appear before its word is spoken, nor linger after it;
- if the voice **names something concrete**, that image is on screen while it is named. A line about
  the market over a shot of the beach is the same mistake as a late caption.

With no narration, the text is tied to the cut and to what is on screen. And a subtitle for audio
nobody hears — the clip's own voice under music or TTS — is always wrong; see `editing.md`.

### Valentino, and what it costs

The app path is **macOS only and fragile**: it is screen-coordinate automation, there is no API, and
a CapCut update moves the buttons. What you need to know before depending on it:

- **A heavily used project stops generating**, silently: the dialog appears, closes, and no file
  shows up. One long batch, one new project. The script detects it, retries once with a fresh
  project and, if that fails too, exits non-zero with what to do — never half a folder pretending to
  be finished.
- Never type text by simulating keystrokes: spaces and accents get eaten. Copy to the clipboard and
  paste.
- The 1.4x is applied **outside** the app, with `atempo` (which preserves pitch).
- **If it breaks**, the local voice takes over and the README says so; if not even that works,
  deliver the video **without voice** plus the `voice-script` with each line's entry second, so the
  user adds it in the app with two taps.

### Gluing narration onto an already rendered video

`skills/voices/scripts/narrate.py` reads the `voice-script` (validated against
`schemas/voice-script.schema.json`), generates or reuses the WAVs and mixes them onto the MP4
without re-rendering it:

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/voices/scripts/narrate.py" voice-script.json --parse-only
uv run "$CLAUDE_PLUGIN_ROOT/skills/voices/scripts/narrate.py" voice-script.json video.mp4 out.mp4
```

It ducks the video's own audio under each line marked `duck: true` (`duck_db`, with a `duck_pad_s`
ramp), keyed by the voice itself so the music comes back up in the gaps.

A real trap: in the `amix`, **don't use `duration=first`**. If the video comes in with no audio
track, the first input is the first voice line and the mix gets cut at 3 s. Take the longest, pad it
to the video's length and trim there.

## Spoken viral audios

A trending song needs a BPM; a spoken meme audio needs its phrases.
`skills/voices/scripts/sound_map.py` writes a `sound-map.json` with every phrase's start and end,
the pause after it and which one is the **punchline**. Cut on `cut_grid` (the phrase starts), never
inside a phrase, put the best shot on the punchline and breathe in the pauses.

Like the music preview, that audio is fetched **to measure it**: `"embed_in_clean": false`. The file
that gets uploaded carries no trending audio — only the local `-preview` does — and the user
attaches the real sound in the app at publish time, which is what makes the video count toward the
trend.
