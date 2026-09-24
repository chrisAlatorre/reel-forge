# Editing: the engine, the effects and what already cost dearly

Engine: `skills/video-engine/scripts/render.py`. It reads a JSON spec and renders a vertical
1080x1920. It needs `ffmpeg` on the PATH. Works on macOS, Linux and Windows.

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/video-engine/scripts/render.py" spec.json
```

**One engine only: the plugin's.** If a project kept its own copy of the script, compare it before
rendering: the same spec with two different engine versions gives different results, and that bug takes
hours to find.

## Spec

```json
{
  "out": "trip/deliveries/v1/concept/concept-A.mp4",
  "crf": 22,
  "look": "film|teal|clean",
  "grain": 0.008,
  "bpm": 123.0, "beat0": 0.0,
  "fade_out": 0.4,
  "audio_fade_out": 1.2,
  "preview_audio": {"src": "common/song.m4a", "offset": 0.0, "gain": 1.0},
  "audio": [{"src": "common/natural_audio.wav", "at": 0.0, "gain": 1.0}],
  "segments": [
    {"src": "common/p01.jpg", "beats": 2, "focus": [0.5, 0.4], "kb": 0.06, "punch": 0.10},
    {"src": "common/c03.mp4", "dur": 2.4, "start": 3.0, "speed": 0.5, "flash": true}
  ],
  "captions": [
    {"t0": 0.0, "t1": 2.0, "text": "nobody tells you this", "style": "clean", "pos": "upper"}
  ]
}
```

- `out` relative to `$REEL_FORGE_OUTPUT`, or absolute / with `~` / with `$VAR`.
- `focus`: the point (0-1) that ends up centred when cropping to 9:16.
- `kb`: slow zoom over the segment. `punch`: a snap zoom that settles in ~0.2 s.
- `speed 0.5` over 60 fps material gives real slow motion, without interpolation.
- `beats` instead of `dur` when the spec carries `bpm`.
- The engine works internally with a 1.25 margin (1350x2400) so it can zoom without losing sharpness.
  Anything you pre-render with ffmpeg should **already be 1350x2400**, or it gets rescaled on the way in.

### `crf`

The historical default (`crf 18`) gave ~11 Mbps: 35 s weighed 50-80 MB, far more than survives an upload
and too much to send over chat. **Use `"crf": 22`** for 1080p deliveries (35 s ≈ 27 MB, no visible
difference). The light copies go at 720p and crf 24 (4-11 MB).

### `grain`

Grain of 0.03 at half resolution "shows up massively". Grain goes fine, at full resolution and in
luminance only: **`grain` ≤ 0.008**. The engine caps it at 0.012.

## Framing to 9:16

- **Don't use a blurred background as a default.** A horizontal photo letterboxed between two blurred
  bands ends up small, and two of those in a row read as the same shot repeated. Use `focus` with the
  subject's point and let it fill the frame. The blurred background is only for what genuinely can't be
  cropped.
- Check that the crop doesn't cut off heads or leave someone stuck to the edge.

## Text

- **9:16 safe area:** 150 px top, **480 px bottom** (that's where the app's buttons and description
  live) and 180 px right. A chip "right at the bottom" gets covered by the interface.
- Genuinely centred: on the screen's centre, with a symmetric margin.
- Styles: `clean` (minimal, the default for subtitles), `serif` (the "chic" look), `box` (the classic
  labelled card), `bold` (thick outline — avoid it, it reads as dated).
- **Text over a close-up face: move it up.** The low position lands at ~0.69 of the height, which in a
  vertical frame is exactly the mouth. Changing the `focus` doesn't fix it if the original photo is
  landscape.
- **A manual line break isn't enough.** The engine wraps by width *inside* each line, so at size 56-58
  about 22 characters fit per line, and fewer at 62-72. Captions that already carried `\n` still dropped
  an orphan word. **Every time you change the size, look at the rendered frame and count the lines.** A
  single word alone on its line over a frozen frame looks bad.
- **Non-Latin scripts:** a Latin typeface carries no ideographs and no Indic scripts (you get boxes),
  and without the complex-shaping library the vowel marks come out as dotted circles. The engine swaps
  fonts when it detects those scripts; if it still fails, generate the text as a PNG with a system font
  that does cover them and overlay it after the render, copying the audio through.
- **Language:** all on-screen copy is in the resolved output language. Don't mix languages in one video,
  and don't leave a caption in the language of the original concept because "it sounded better".

## Effects

| Effect | When | Careful |
|---|---|---|
| `punch` | almost any beat cut | 0.08-0.15; more feels abrupt |
| `flash` | only at the strong moment | 2-3 frames, once per video |
| `stutter: 6` | walking, POV | it gets tiring fast |
| text behind the subject | 1-2 times per video | **only** if the head or torso covers part of the text: pick a shot where the subject is large and put the text at head height |
| cutout with outline + freeze | character intro | the cards have to talk **about the cut-out subject**, not about what's beside them |
| route map | travel recap | labels that don't overlap (8 positions around the point, a leader line if it lands far); the map extends its latitude so that in 9:16 the whole route is visible from the start |

**At most 2 effects per cut.** Avoid: RGB glitch, long fades, the same whoosh on every cut, neon
subtitles with emoji.

Person segmentation (for text-behind and cutout) uses a local model. If black rectangles appear, that's
a NaN in the mask: re-run that segment or drop the effect.

## What the engine does NOT do

- **It doesn't rotate.** For a micro-rotation on entry, pre-render the piece with ffmpeg at 1350x2400
  and drop it in as a normal clip. Crop with margin (1440x2560 → 1350x2400) so the rotation's empty
  corners never show.
- **It doesn't do animated zoom with a variable-size `crop`** — ffmpeg evaluates those expressions once.
  Use `zoompan`, with output at 1350x2400 and `fps=30`.
- **ffmpeg doesn't open HEIC.** Convert the photo to JPG with the image library before touching it with
  ffmpeg.
- **It doesn't take the clips' audio.** See `audio.md`: diegetic sound is assembled separately and comes
  in as a single track.

## Retouching people: not in the plugin

**reel-forge doesn't retouch faces or bodies.** There is no retouching script and there is no pretence
that there will be: the only thing that modifies the image is the render's `look`, applied evenly across
the whole variant.

If the user asks for it, say so plainly and give the two honest outs:

1. **Choose better**, which is what actually changes the result: favorites, the full burst, face crops
   to drop half-formed expressions. See `selection.md`.
2. **Let them retouch the photo themselves** in whatever app they already use, and add the retouched
   file to the catalog as one more shot.

And if it ever gets added, it should follow these rules, which came out of a "this was too much":

- Face and under-eyes yes; body, very little. No inflated arms.
- Even silhouette, **never an hourglass shape**.
- **The background rules:** if there are poles, columns, frames, railings or a horizon next to an arm or
  the torso, the retouch is very light or doesn't happen. A bent column gives everything away.
- Maximum displacement relative to shoulder width: 2-5 % is fine, above ~7 % it already looks edited.
- With several people, confirm the detected skeleton is the subject's before touching anything.
- Never on clips. For the subject in close-up, use a photo; clips are for action and landscape.

## Mistakes that already happened (don't repeat them)

- **Using a range outside its cataloged window.** Out came strangers' faces against the lens.
- **Two nearly identical cuts from the same clip.** Two reframes 4° apart read as an editing mistake.
  Separate the angle or change the subject.
- **A wrong date on screen** from confusing the local time of the place with the home one: 14 h of
  difference eats a whole day. The metadata's capture date wins.
- **A 0.39 s stamp.** Invisible. Minimum ~0.8 s and it comes in with the cut.
- **Deleting the pre-renders without the builder regenerating them.** The specs pointed at temporaries
  and the project became irreproducible. Always rebuild from `build.py`, never from a loose spec.
- **A helper script with no execute permission** that nobody was calling: the preview kept coming out
  clipped on every rebuild. If a step fixes something, it goes inside the script that renders, not in
  the README.
- **In zsh, `$VAR[a1]` inside a `filter_complex` eats the label** (zsh reads it as an array index). The
  result: an mp4 with two audio tracks and no error at all. Always use `${VAR}[a1]` and check with
  `ffprobe -show_entries stream=index,codec_type`.
