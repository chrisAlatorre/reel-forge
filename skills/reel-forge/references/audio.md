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
  warning you. `acrossfade=d=1.5` between the preview and a shifted copy, `atrim` to the exact length,
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

**Generic TTS with echo sounds like "a cheap mic, far from the mic" and was rejected in production.**
Use a modern neural voice, dry, with no added echo:

- `skills/voices/scripts/voice.py` generates `l0.wav, l1.wav… + durations.json` (48 kHz, silence
  trimmed, gentle high-pass, two-pass normalization to -16 LUFS). That is **the contract**: any other
  voice source has to deliver the same thing so the engine consumes it unchanged.
- **The voice speaks the output language.** Filter the engine's voice catalog by the language tag before
  offering anything, and write the script in that language. A Spanish voice reading an English script,
  or the other way round, is the first thing anybody notices.
- Use a model with a clear commercial-use license and **designed synthetic voices**, not cloned ones.
- **Never clone a real person's voice** (actors, celebrities, the platform's voice). Don't describe one
  so the model imitates it either.
- Write a new voice's description **in the target language**: asking in English for a Spanish voice
  brings in a foreign accent. Try 3-4 seeds and keep the best.
- Don't stretch the voice to slow it down: it introduces artifacts. For pauses, use commas and periods
  in the script. Numbers spelled out as words.
- If the user wants commercial-service quality, that needs their account and their key: ask them for it,
  don't sign them up.

### Viral narrator voice from an editing app — **macOS only, and fragile**

Some desktop apps write their text-to-speech WAV **straight into the project folder**, before exporting
anything. If the concept calls for that exact voice and the plugin ships the matching automation script,
drive the app by clicks and leave the same contract (`l0.wav… + durations.json`). What you need to know:

- **It's screen-coordinate automation.** There is no API. Any app update moves the buttons and you have
  to recalibrate. Treat it as an optional path, never as a dependency.
- **A heavily used project stops generating**, silently: the dialog appears, closes, and no file shows
  up. One long batch, one new project. If it starts failing, create another and carry on.
- Never type text by simulating keystrokes: spaces and accents get eaten. Copy to the clipboard and
  paste.
- The trend's speed is applied **outside** the app, with `atempo` (which preserves pitch).
- **The fallback path, and the one you should prefer:** generate with the plugin's local TTS. If not
  even that works, deliver the video **without voice** plus a `voice-script.txt` with each line's entry
  second, so the user can add it in the app with two taps.

### Gluing narration onto an already rendered video

`skills/voices/scripts/narrate.py` reads a `voice-script.txt` (`<second>  <text>` per line), generates
or takes the WAVs and mixes them onto the MP4:

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/voices/scripts/narrate.py" voice-script.txt video.mp4 video-narrated.mp4
```

A real trap: in the `amix`, **don't use `duration=first`**. If the video comes in with no audio track,
the first input is the first voice line and the mix gets cut at 3 s. Take the longest and trim it to the
video's length.
