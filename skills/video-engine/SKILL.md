---
name: video-engine
description: reel-forge's render engine. Turns a JSON spec into a vertical 9:16 video (1080x1920) ready for TikTok, Reels or Shorts, with photos, clips, 360 reframes and animated maps; text with a safe area, colour looks, film grain and audio mixing. Use it whenever a plugin video has to be rendered, adjusted or debugged.
---

# Video engine (JSON spec → 9:16)

Everything runs locally. The input is a JSON file; the output, a 1080x1920 MP4. The engine builds each
frame in numpy and encodes it with ffmpeg: it depends on no editor and no service.

```bash
R=${CLAUDE_PLUGIN_ROOT}/skills/video-engine/scripts/render.py
uv run "$R" my-spec.json
uv run "$R" my-spec.json --out ~/Videos/another-path.mp4
```

There is a commented example spec, with every segment type and every text style, in the plugin's
**`examples/spec-example.json`**. It is valid JSON: the engine ignores keys starting with an underscore,
so the comments can stay in your working specs.

Files:

| File | What it does |
|---|---|
| `scripts/render.py` | The engine: reads the spec, builds the frames, mixes the audio, encodes. |
| `scripts/effects.py` | Person segmentation, text behind the subject, character intro, route map. |
| `scripts/config.py` | Canvas, safe area and paths configurable through environment variables. |
| `scripts/resources.py` | Downloads the fonts, the base map and the segmentation model. |

## Requirements

- `ffmpeg` and `ffprobe` on the PATH (`brew install ffmpeg`, `apt install ffmpeg`).
- `uv` to run the scripts: the `# /// script` header declares the dependencies (numpy, opencv, pillow,
  pillow-heif and, only when used, mediapipe and telemetry-parser).
- **Cross-platform**, with two macOS caveats:
  - The Thai and CJK fallback fonts `config.py` defaults to are macOS paths. On Linux or Windows,
    install Noto (`Noto Sans Thai`, `Noto Sans CJK`) and point `REEL_FORGE_FONT_THAI` /
    `REEL_FORGE_FONT_CJK` at them.
  - Scripts with combining marks (Thai, Arabic, Indic) need **libfribidi** for Pillow to use raqm. On
    macOS with Homebrew the engine re-executes itself with the right `DYLD_FALLBACK_LIBRARY_PATH`; on
    Linux, having `libfribidi` installed is enough. Without it, the vowel marks come out as dotted
    circles.

## First run: resources

```
uv run "${CLAUDE_PLUGIN_ROOT}/skills/video-engine/scripts/resources.py" --all
```

Downloads into `$REEL_FORGE_CACHE` (default `~/.cache/reel-forge`):

- **Montserrat** (variable sans) and **Instrument Serif** (italic), from the official Google Fonts repo.
- `ne_50m_land.geojson` from **Natural Earth** (public domain), for the `map` segment.
- `selfie_multiclass.tflite` from **MediaPipe** (Apache-2.0), for `behind` and `cutout`.

### Font licensing (important)

Montserrat and Instrument Serif are under the **SIL Open Font License 1.1 (OFL)**: free to use, including
commercially, and free to embed in videos. The OFL requires keeping the license notice and forbids
selling the fonts on their own. That's why **the repo doesn't ship the .ttf files**: `resources.py`
downloads them alongside their `OFL-*.txt`, which has to stay next to them. If you prefer another
typeface, point `REEL_FORGE_FONT_SANS` / `REEL_FORGE_FONT_SERIF` at it (any `.ttf`/`.otf`; if the sans
is variable, the engine asks it for weight 700/850).

## Configuration (environment variables)

| Variable | Default | What for |
|---|---|---|
| `REEL_FORGE_CACHE` | `~/.cache/reel-forge` | Root of the self-downloaded resources |
| `REEL_FORGE_FONTS` | `$REEL_FORGE_CACHE/fonts` | Typefaces |
| `REEL_FORGE_ASSETS` | `$REEL_FORGE_CACHE/assets` | Base map, sound effects |
| `REEL_FORGE_MODELS` | `$REEL_FORGE_CACHE/models` | Segmentation model |
| `REEL_FORGE_HOME` | `~/Movies/reel-forge` on macOS, `~/Videos/reel-forge` elsewhere | Project root |
| `REEL_FORGE_OUTPUT` | `$REEL_FORGE_HOME` | Base for the spec's relative `out` paths |
| `REEL_FORGE_FONT_SANS` / `_SERIF` | Montserrat / Instrument Serif | Changing the typeface |
| `REEL_FORGE_FONT_THAI` / `_CJK` | auto-detected | Scripts the sans doesn't cover |
| `REEL_FORGE_360_SCRIPTS` | the sibling `video-360` skill | Where to import `reframe360.py` from |

The full list of the plugin's variables is in `docs/configuration.md`.

A relative `"out"` (`"trip/day-one-A.mp4"`) hangs off `REEL_FORGE_OUTPUT`; an absolute one, or one with
`~` or with `$VARIABLE`, is respected as is. The same goes for `src`: a spec can write
`"$REEL_FORGE_ASSETS/sfx/shutter.mp3"` and the engine expands it.

---

## The full JSON spec

```jsonc
{
  "out": "project/video.mp4",   // relative to REEL_FORGE_OUTPUT, or absolute / with ~ / with $VAR
  "fps": 30,                     // default 30
  "crf": 22,                     // x264 quality: 22 ≈ 6 Mbps. Default 22
  "look": "film",                // "film" | "teal" | "clean"
  "grain": 0.008,                // film grain; the engine caps it at 0.012
  "fade_out": 0.4,               // seconds of fade to black at the end (0 = hard cut)
  "audio_fade_out": 1.2,         // audio tail; 0 on videos meant to loop
  "bpm": 123.0,                  // if any segment uses "beats"
  "beat0": 0.0,                  // the second the first beat lands on

  "segments": [ /* see below */ ],
  "captions": [ /* see below */ ],
  "audio": [ /* tracks that DO go in the clean version */ ],
  "preview_audio": { /* copyrighted song, review only */ }
}
```

The engine writes **two files** when there is `preview_audio`: `video.mp4` (clean, the one you upload)
and `video-preview.mp4` (with the song, for review only).

### Segments

Every segment contributes **image only**. Its duration is declared with `dur` (seconds) or with `beats`
(requires `bpm`). Timings are computed on an absolute grid, so the cuts don't accumulate drift even with
40 segments.

**Four source types:**

```jsonc
// 1. Photo (jpg, png, heic — HEIC works via pillow-heif; ffmpeg does NOT open HEIC)
{"src": "~/photos/temple.jpg", "beats": 2, "focus": [0.5, 0.4], "kb": 0.06, "punch": 0.10}

// 2. Video clip (mov, mp4, m4v, mkv). HDR is converted to SDR automatically.
{"src": "~/videos/river.mov", "dur": 2.4, "start": 12.0, "speed": 0.5, "focus": [0.62, 0.5]}

// 3. A 360 clip reframed with a virtual camera (needs the plugin's 360 engine)
{"src": "VID_0012.insv", "dur": 4, "start": 12, "r360": "keys.json"}
{"src": "VID_0012.insv", "dur": 4, "r360": {"keys": [...], "stab": "gyro"}}

// 4. Animated route map (no src)
{"map": {"bbox": [-10.0, 20.0, 35.0, 52.0],
         "stops": [[-9.14, 38.72, "Lisbon"], [-3.70, 40.42, "Madrid"], [12.50, 41.90, "Rome"]]},
 "dur": 5}
```

**Common modifiers** (all optional):

| Key | Default | What it does |
|---|---|---|
| `dur` / `beats` | — | Duration. One of the two, required. |
| `start` | 0 | Entry second inside the source clip. |
| `speed` | 1 | `0.5` = slow motion. With 60 fps material it's **real** slow motion, no interpolation. |
| `focus` | `[0.5, 0.5]` | The point (0-1) that ends up centred when cropping to 9:16. The key thing for landscape photos. |
| `fit` | cover | `"blur"` fits the whole image between two blurred bands of itself. |
| `kb` | 0.05 | Ken Burns: a slow, continuous zoom across the segment. |
| `punch` | 0 | A snap zoom on entry that settles in ~0.22 s. `0.08`-`0.12` is the natural range. |
| `drift` | `[0, 0]` | Lateral/vertical displacement of the framing across the segment. |
| `stutter` | — | Integer: repeats each frame N times. `6` = the low-fps walking effect. |
| `freeze` | false | Freezes the first frame for the whole segment (for `cutout`). |
| `flash` | false | A 3-frame white flash on entry. Only on the drop, once per video. |
| `behind` | — | Giant text **behind the subject** (see below). |
| `cutout` | — | Character intro with a cutout (see below). |

**`behind` — text behind the subject**

```jsonc
"behind": {"text": "SUMMER", "size": 250, "y": 0.16, "style": "bold", "at": 0.0,
           "color": [255, 255, 255]}
```

It cuts the person out and pastes them back on top of the text. **It only reads as an effect if the head
or torso covers part of the text**: pick a photo where the subject is large and set `y` at their head
height. Once or twice per video, maximum. The size scales down automatically until the text fits the
width.

**`cutout` — character intro**

```jsonc
{"src": "photo.jpg", "dur": 2.6, "freeze": true,
 "cutout": {"y": 0.62, "lines": ["28 years old", "3 countries in 20 days", "0 plans"]}}
```

It freezes the frame, dims and blurs the background, cuts the subject out with a white outline and
brings in staggered cards. The cards have to talk **about the cut-out subject**, not about what's behind
them. It works well with a shutter sound and some pops.

Both `behind` and `cutout` use MediaPipe selfie multiclass. If the photo skill is available, the mask
gets constrained with the Pose silhouette so the model doesn't mistake animal fur for human hair. If
black rectangles appear in the video, that's a NaN in the mask.

### Captions

```jsonc
{"t0": 0.0, "t1": 2.4, "text": "things nobody\ntells you about this",
 "style": "clean", "pos": "low", "size": 58, "color": [255, 212, 0],
 "pop": true, "words": false, "dx": 0, "dy": -128}
```

- `t0` / `t1` are **global** video time, not segment time.
- `words: true` splits the text into groups of up to 3 words with time proportional to the letters: the
  karaoke subtitle used over narration.
- `pop` (default `true`): enters with a 0.12 s micro-bounce.
- `dx` / `dy` shift the piece in pixels. A negative `dy` puts a small line (a price) **above** another
  caption, because below is the button zone.
- The caption text is written in the run's **output language**. The engine doesn't translate anything;
  whoever writes the spec is responsible for it.

**Styles:**

| `style` | Default size | When to use it |
|---|---|---|
| `clean` | 64 | The default. White sans with a soft shadow, no thick outline. Subtitles and hooks. |
| `serif` | 96 | Instrument Serif italic with a halo. "Chic" aesthetic, cinematic POV, closers. |
| `yellow` | 96 | Thick yellow with a shadow. A key word: a place, a price, a number. |
| `box` | 58 | Rounded card, the "classic TikTok text". `color` changes the background and the ink is picked automatically by luminance. It's the only one that wraps long text well. |
| `pin` | 46 | A place label with a red pin ("Day 4 · Beijing"). **It doesn't wrap**: one short line. |
| `bold` | 74 | Sans with a thick black outline. Legible over anything, but it reads like an editor from years ago: avoid it. |

**Positions** (`pos`):

| `pos` | Where it lands |
|---|---|
| `top` | Top, inside the safe area. A fixed hook. |
| `topleft` | Top left, against the margin. For `pin`. |
| `upper` | ~30 % of the height. **The escape when the text covers a face.** |
| `center` | Screen centre, slightly high. |
| `low` | Bottom, above the button zone. The default. |
| `lowleft` / `lowright` | Bottom left/right. Corner stamps and tags. |

### 9:16 safe area

The canvas is 1080x1920, but the TikTok interface eats the edges:

```
top    150 px   search bar and notices
bottom 480 px   username, description, sound bar
right  180 px   the like / comment / share column
left    60 px   breathing margin
```

Centred captions use a **symmetric 150 px margin** on each side and are centred on `W/2`, not on the
safe area: centring on the safe area (60 left against 180 right) leaves everything visibly pushed to the
left. The usable wrapping width is **780 px**: at `size` 56-58 about 22 characters fit per line; at
62-72, fewer.

---

## Colour looks and grain

| `look` | What it does | When |
|---|---|---|
| `film` | Lifted blacks, warm highlights, green-blue shadows, saturation 0.92, vignette 0.28. | Travel, nostalgia, the body of a video. |
| `teal` | Teal & orange, saturation 1.05, vignette 0.30. | Action, night, city. |
| `clean` | No curve correction, vignette 0.12. | Whites, bright temples, food, snow. |

`film` **kills the whites**: a white temple or a pale wall comes out grey. If the hook depends on that
white, use `clean` for the whole video — and if several people are building variants of the same
concept, compare the same frame across variants, not only within each one.

**Grain.** `grain` is applied fine, **at full resolution and in luminance only**, with less intensity in
the blacks and whites. Generating it at half resolution and scaling it up looks dirty, like compression
noise. Useful range: **0.004 - 0.008**; the engine caps it at 0.012 and `0.03` is unwatchable.

---

## Audio

The engine **does not carry over the clips' audio**. Segments contribute image only: everything you hear
comes from the spec's `audio` tracks.

```jsonc
"audio": [
  {"src": "narration.wav", "at": 0.0,  "gain": 1.0},
  {"src": "ambience.mp3",  "at": 2.5,  "gain": 0.25, "dur": 8.0, "offset": 12.0},
  {"src": "sfx/whoosh.mp3","at": 4.2,  "gain": 0.6}
]
```

| Key | What it does |
|---|---|
| `src` | Any format ffmpeg can read. |
| `at` | The second of the video it comes in on. |
| `gain` | Linear multiplier (`1.0` = as is). |
| `dur` | Trims the track to N seconds, with a 0.3 s fade in and a 0.5 s fade out. |
| `offset` | The second the source is taken from. |

**How it's mixed, and why in two steps.** First every track is mixed into a WAV
(`amix normalize=0` → `apad whole_dur` → `atrim` to the exact length) and then that WAV gets attached to
the video with `-c:v copy`. **A single ffmpeg call with many tracks plus the video hangs with no error**
(it happened with 19 tracks). Don't merge it into one command.

Details that already cost dearly:

- The chain always ends with a **limiter** (`alimiter=limit=0.89`). The sum of the preview song and the
  natural audio reached **+5.8 dBTP** with nothing warning.
- `aresample=async=1:first_pts=0` is mandatory: if **no** track starts at `at: 0`, the mix comes out with
  an initial pts equal to the first `adelay` and the `atrim` clips the audio. A 34.3 s video ended up
  with 9.6 s of audio because of this.
- `"audio_fade_out": 0` on videos meant to loop; the 1.2 s default breaks the seam.
- For diegetic sound (voices, water, party ambience) build **one continuous WAV** separately: each piece
  with `atrim` + `asetpts` + 50 ms fades + `adelay`, everything through `amix normalize=0`, and finally
  `loudnorm I=-16` plus a limiter. Drop it in as a single track at `at: 0`. Photos have no audio: cover
  them with the ambience of the clip from the same scene, or they come in silent.
- Normalize **piece by piece** to its own LUFS target (`loudnorm print_format=json` to measure,
  `volume=NdB` to apply) and leave the final mix at -14 LUFS. That way you can design a volume drop on
  purpose without the video jumping by accident. Near-silent takes need
  `dynaudnorm=f=180:g=21:p=0.62` before you raise them, or the track sounds broken.
- Check for gaps with `silencedetect=n=-45dB:d=0.25`, and that the audio lasts exactly as long as the
  video with `ffprobe -select_streams a:0 -show_entries stream=duration`.

### Music

```jsonc
"preview_audio": {"src": "song.m4a", "offset": 0.0, "gain": 1.0}
```

`preview_audio` generates a separate **`video-preview.mp4`**. The clean version **never** carries the
song: in the app you add the official sound, which also makes it count toward the trend.

To cut on the beat, measure the audio's BPM (with `librosa.beat.beat_track`, for example) and use `bpm` +
`beats` in the segments. **Music store previews last 30 s**: on a 34 s video the music simply runs out
and the last seconds go silent without the render warning you. Past ~29 s, build a looped bed first
(`acrossfade=d=1.5` between the preview and a shifted copy of itself, `atrim` to the length you need,
`loudnorm I=-22`) and pass it with `gain 1.0`; lowering the `gain` on the raw preview makes it inaudible.

---

## Animated route map

```jsonc
{"map": {"bbox": [lon0, lon1, lat0, lat1],
         "stops": [[lon, lat, "City"], [lon, lat, "City"]],
         "geojson": "route/optional.geojson"},
 "dur": 5}
```

A paper-style map in a Mercator projection with **the same scale in x and y** (with different scales the
world comes out stretched). The route is drawn as a dashed line while a plane travels it; the camera
starts showing the full journey and ends zooming into the last stop.

Two solved problems worth not breaking:

- **Automatic latitude extension.** In 9:16 the map has to be at least as tall as `width × 16/9`. If the
  `bbox` is flatter than that, the engine extends the latitude symmetrically **in Mercator space** (not
  in degrees) so the whole route fits from the first frame.
- **Labels that don't overlap.** Each label tries 8 positions around its point, at three different radii,
  and takes the first free one; if it ends up far from the point, a leader line is drawn. Labels that
  would fall outside the safe area are dropped, and stops outside the frame get no label. Even so, with
  stops less than ~50 km apart, check the frame: they can stack. If they get in the way, remove a stop or
  split the route into two map segments.
- Stop names are copy: write them in the output language.

Maps are always rendered with the `clean` look and no grain, even if the video uses another look.

---

## Verify before delivering

No render gets delivered without being looked at. Commands that catch almost everything:

```bash
# frame strip: always the first thing
ffmpeg -v error -i video.mp4 -vf "fps=2,scale=216:384,tile=12x6" strip.png

# black frames, audio gaps and peaks
ffmpeg -v error -i video.mp4 -vf blackdetect=d=0.08:pix_th=0.12 -f null -
ffmpeg -v error -i video.mp4 -af silencedetect=n=-45dB:d=0.25 -f null -
ffmpeg -v error -i video.mp4 -af loudnorm=print_format=summary -f null -   # peak below -0.5 dBTP

# the audio has to last exactly as long as the video, and there must be ONE track
ffprobe -v error -show_entries stream=index,codec_type,duration -of compact video.mp4
```

On the strip, check: the text is readable, it covers no face, no crop cuts off a head, the facts on
screen are true, and long captions don't drop orphan words.

---

## Mistakes already made, don't repeat them

1. **Centring text on the safe area instead of on the screen.** The safe area is asymmetric (60 px left,
   180 right because of the button column). Centring on it leaves every caption visibly pushed left.
   Centre on `W/2` with a symmetric 150 px margin.
2. **Covering the subject's face with the text.** `pos: "low"` lands at ~0.69 of the height, which in a
   vertical close-up is exactly the mouth. Changing the `focus` doesn't fix it if the original photo is
   landscape, because the crop already takes the full height: move the text to `pos: "upper"` and find an
   empty wall. Check it on the strip, not from memory.
3. **Grain at half resolution.** It looks dirty, like compression noise. Fine, at full resolution, in
   luminance only and `grain ≤ 0.008`.
4. **30 s music previews on longer videos.** The song runs out by itself and the ending goes silent with
   no warning. Build the looped bed before rendering.
5. **Copyrighted music embedded in the final version.** Only in the `-preview`. The clean one gets
   uploaded and the official sound goes on in the app.
6. **Not verifying with frame strips.** Everything on this list shows up in an `fps=2` strip. No strip,
   no delivery.
7. **Trusting a hand-written `\n`.** The engine wraps by width **inside each line**, so a `\n` guarantees
   nothing: if the line doesn't fit, it gets split anyway and drops an orphan word, which looks terrible
   on a frozen frame. And every time you lower the `size`, look at the frame again: text that broke
   nicely at 62 px drops its last word at 54.
8. **`fit: "blur"` for landscape photos.** It leaves them small, letterboxed between two blurred bands;
   two in a row read as the same shot repeated. Use `focus` on the subject and let the photo fill the
   frame. `blur` is only for material that genuinely cannot be cropped.
9. **Stamps or tags under ~0.8 s.** They can't be read. Corner tags come in **with the cut**, not
   mid-shot.
10. **Putting a date or a place on screen without verifying it.** The file name carries the local time of
    where it was taken and the library database the machine's zone: a whole day slips between the two.
    Verify against the metadata, not against the name.
11. **Assuming the second with the good audio is the second with the good image.** The audio peak (a
    shout, a laugh) usually lands while the camera is pointing elsewhere. Separate the image clip from
    the audio clip and **look at the frame** of the `start` before pinning it.
12. **`look: "film"` over whites.** It leaves temples and pale walls grey. If the hook depends on the
    white, the whole video goes `clean`.
13. **Leaving the default `crf` high.** `crf 18` gives ~11-19 Mbps: 35 s weighs 50-80 MB, more than any
    messaging app takes and far more than the platform keeps. `crf 22` leaves those 35 s at ~27 MB with
    no visible difference; the review copies go at 720p and `crf 24`.
14. **Two reframes of the same 360 clip at similar yaw** read as an editing mistake: same composition,
    same background. Separate them by at least 90° of yaw or change the subject.
15. **Deleting the pre-renders without the builder regenerating them.** If the spec points at a temporary
    MP4 and you clean it up, the JSON becomes irreproducible. Always rebuild from the script that builds
    the spec, never from the loose spec.
16. **Patching by hand what the engine gets wrong.** If a step fixes something (normalizing the preview,
    overlaying CJK subtitles), it goes inside the script that renders, not in the README: on the next
    rebuild the mistake comes back silently.

## Known limits

- **It doesn't rotate the image.** For a micro-rotation on entry, pre-render the piece with ffmpeg at
  **1350x2400** (= 1080x1920 × the 1.25 `MARGIN`) and drop it in as a normal clip.
- **It doesn't animate zoom inside ffmpeg for you.** If you need a framing the material doesn't have,
  pre-render it with `zoompan` (not with `crop`: ffmpeg evaluates `w`/`h` once) and output at 1350x2400
  so the engine doesn't rescale it again.
- **ffmpeg doesn't open HEIC.** iPhone photos are loaded by Pillow; if you need to pass them through an
  ffmpeg filter, convert them to JPG first.
- **CJK inside the render depends on the fallback font.** With none installed you get boxes: install one
  and point `REEL_FORGE_FONT_CJK` at it, or overlay the glyphs as a PNG on the already rendered MP4 with
  `overlay=enable='between(t,a,b)'`, copying the audio through.
- **`r360` segments need the plugin's 360 engine** (the `video-360` skill). Without it, the engine says so
  and stops instead of rendering something different.
