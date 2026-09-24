# 360 material to 9:16

An equirectangular clip isn't one shot: it's many. A single file yields the hook, the b-roll and the
close. That's why it gets **one agent per clip**.

Engine: `skills/video-360/scripts/reframe360.py` (a keyframed virtual camera over the equirectangular).
In the spec, a segment with `"r360": "keys.json"` gets rendered by that engine and then goes through the
2D engine's look, text and audio.

## Flow

1. **Proxy.** Convert the original into a manageable equirectangular (3840x1920 at 30 fps). It happens
   automatically the first time you run any command on that clip.
2. **Sheets.** `sheets VID --n 6 [--views ring8] [--people]`: the levelled equirectangular, a yaw/pitch
   grid and 6 or 8 ring views, with people labelled with their `yaw,pitch`. **Look at them before
   writing a single key.**
3. **Keys.** Write `keys.json` and render: `render --keys keys.json`.
4. **Shortcuts.** `planet` (an unrolling tiny planet) and `follow` (tracks a person and generates
   smoothed keys you can edit by hand).

## Keys

- `yaw` 0 = front, + to the right. **It does not wrap:** to go from 170 to -170 the short way, write
  190. `pitch` + is up. `fov` is horizontal.
- `ease` says how you **arrive** at that key: smooth, linear, in, out, whip, cut or spline. Missing
  fields are inherited from the previous key.
- A 0.3-0.4 s `whip` between two directions: the motion blur is computed from the speed. A snap `fov`
  close on arrival finishes it nicely.
- Stabilization: visual (optical flow) or gyro if the file carries telemetry. `heading` mode keeps the
  horizon fixed and the front follows your travel; `lock` pins the direction in the world.
- Auto-levelling needs verticals (poles, buildings, trees). In open landscape it finds none: it says so
  and leaves that shot unlevelled.

## What was learned the hard way

- **Tiny planet: NO if the person filming is right against the lens.** With the camera a metre from a
  face, the stereographic projection deforms it at any orientation: at the top it squashes, at the bottom
  it stretches across half the screen. Rotating the planet doesn't fix it, because the subject you want
  up top and the person filming are ~166° apart and you can only pick one. **Swap it for a rectilinear
  push** (`fov` from ~124 to ~70, `pitch` from +12 to -3, yaw turning toward the subject): the same
  reveal feeling and no deformed faces. The planet is reserved for clips where nobody is within 2-3 m of
  the lens.
- **Land on the subject of the scene, not on the person filming.** Whoever holds the stick is always at
  ~180° and a metre away: the fisheye deforms their face and almost always catches them mid-word. Pull a
  ring sheet of the final instants, locate the subject by yaw and send the last key there.
- **A wider tiny planet looks better:** at `fov` 200 the subject fills the edge; at 235 the planet sits
  small and doesn't cut off heads or hats.
- **The stitch seam splits anything crossing ±90° of yaw.** Before landing a whip in a direction, render
  2 s static at 6 fps facing that way and see from which instant the subject has cleared the seam. Land
  there.
- **Two reframes of the same clip at similar yaw read as the same shot.** Separate them by at least 90°
  of yaw or change the subject.
- **If the concept needs a framing the 360 render can't give**, don't redo the keys: pre-render that
  piece with an animated zoom in ffmpeg (`zoompan`, not a variable `crop`) and use it as a normal clip.
- The closing caption goes in **the second the camera lands**, not at the start of the clip: otherwise
  it sits on top of a spinning planet.

## How the 360 agent catalogs

Instead of time ranges, **direction** ranges: for every time window, what's at each yaw.

```json
{
  "id": "v360-04",
  "path": "~/Videos/360/clip04.insv",
  "type": "video360",
  "duration_s": 29.0,
  "windows": [
    {"start_s": 0.0, "end_s": 2.0, "note": "the only clean window: looking at the lens, nobody crossing"},
    {"start_s": 2.4, "end_s": 6.5, "note": "someone walks through the foreground, half the screen"},
    {"start_s": 6.6, "end_s": 29.0, "note": "turns away and stays in profile, looking out of frame"}
  ],
  "directions": [
    {"yaw": -180, "yaw_end": -120, "what_it_is": "him and his companions", "subject": true},
    {"yaw": -30, "yaw_end": 90, "what_it_is": "river and bank, nobody in frame", "tags": ["empty", "water"]},
    {"yaw": 126, "yaw_end": 160, "what_it_is": "the bow going down the river: the best b-roll, zero faces"}
  ],
  "required_pitch": 15,
  "note": "with a lower pitch, a knee fills the bottom third in every frame"
}
```

## Honest limits

- **Proprietary formats:** the native files of 360 cameras (`.insv`, for example) are two fisheye tracks
  plus telemetry. The stitch the engine does treats each lens as an ideal fisheye, so **the seam on
  nearby objects isn't as good as the manufacturer's software**. For final quality, export the flat 360
  from the official software (with its stabilization and horizon already applied) and reframe it here
  with stabilization off.
- The manufacturer's software is **macOS/Windows only** and has to be driven by hand.
- Visual stabilization is rotation-only (it doesn't fix rolling shutter or parallax) and drifts slowly in
  yaw; in `heading` mode you don't notice.
- With a 3840 proxy, a 70° window uses ~750 px of source: for strong punch-ins, generate a wider proxy.
- The stick or mount **is not removed**: in a tiny planet it sits in the centre.
- The 360 engine's output is 1080x1920 and the 2D engine works at 1350x2400, so every 360 clip gets
  rescaled by 25 % on the way into the spec. It barely shows, but for tight cuts a wider proxy is worth
  it.
- Slow motion: the proxy is 30 fps. For half speed with 60 fps material, generate the proxy at 60.
