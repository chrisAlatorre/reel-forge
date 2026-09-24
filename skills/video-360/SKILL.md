---
name: video-360
description: Turns 360 material (Insta360 X3/X4/X5 or any 2:1 equirectangular) into vertical 9:16 shots with a keyframed virtual camera. Use it when there are .insv files or 360 videos, or when someone asks for a tiny planet, a whip-pan, 360 reframing, following a person, or stabilizing spherical footage.
---

# 360 video → 9:16

A 360 video isn't "cropped": it's **reframed**. A 20-second spherical shot yields three or four
different shots depending on where you point the virtual camera, and that camera can move on its own
(pans, whip-pans, a tiny planet unrolling) without anyone having moved the real camera.

Engine: `${CLAUDE_PLUGIN_ROOT}/skills/video-360/scripts/reframe360.py`. Runs with `uv run` and needs no
external services: ffmpeg, OpenCV, Pillow, MediaPipe and `telemetry-parser`.

**Fixed 1080x1920 output.** It's in `W, H` at the top of the script. If your editing engine works at a
higher resolution (1350x2400, say, to leave reframing headroom), the clip gets rescaled on the way in and
loses definition: for tight cuts, also use a wider proxy (below).

## The golden rule

**Look before writing keys.** Nobody guesses a yaw from memory. The cycle is always: contact sheet →
locate the subject in degrees → write `keys.json` → short render → look at the result. Skipping the sheet
costs more time than it saves.

## Folders

Configured with environment variables; otherwise the defaults are used:

| Variable | Default | What it holds |
|---|---|---|
| `REEL_FORGE_360` | `$REEL_FORGE_HOME/360` | originals, `proxies/` and `output/` |
| `REEL_FORGE_CACHE` | `~/.cache/reel-forge` | person-detection model (downloads itself) |
| `REEL_FORGE_LABEL_FONT` | `$REEL_FORGE_CACHE/fonts/Montserrat[wght].ttf` | ttf for the sheet labels; downloaded by `${CLAUDE_PLUGIN_ROOT}/skills/video-engine/scripts/resources.py` (optional) |

`REEL_FORGE_HOME` is `~/Movies/reel-forge` on macOS, `~/Videos/reel-forge` on Linux and
`%USERPROFILE%\Videos\reel-forge` on Windows. The full variable list is in `docs/configuration.md`.

## Flow

```bash
S=${CLAUDE_PLUGIN_ROOT}/skills/video-360/scripts/reframe360.py

uv run $S proxy  VID.insv                              # 1. 3840x1920 equirect at 30 fps
uv run $S sheets VID --n 6 --views ring8 --people      # 2. see where to point
$EDITOR keys.json                                      # 3. write the camera movement
uv run $S render --keys keys.json                      # 4. render 1080x1920
```

The proxy is created the first time any command touches that file; there's no need to call it separately
unless you want a different width or a fixed stitch.

Shortcuts so you don't have to write keys by hand:

```bash
uv run $S planet VID --dur 6 --spin 40 --to-normal 2     # a tiny planet that unrolls
uv run $S follow VID --dur 10 --type selfie|third --target=YAW,PITCH --render
uv run $S telemetry VID.insv                            # what the gyroscope carries
```

`follow` leaves a `keys.json` with `ease: "spline"` already smoothed: a starting point you edit, not the
final delivery.

## Contact sheets

`sheets` produces, per sampled instant: the full equirectangular with a yaw/pitch grid on top, and
beside it 6 views (`--views cube`: front, right, back, left, up, down) or 8 (`--views ring8`: a ring
every 45° with the view tilted slightly down).

- `--n 6` instants is enough for a 20-30 s clip. Go up to 10-12 if the scene changes a lot.
- `--people` runs a detector and writes each person's `yaw,pitch` over them. That's what you copy
  straight into the keys.
- `ring8` is better for **finding** things (it sweeps the whole horizon); `cube` for checking sky and
  nadir.

It costs ~10 s per sheet with person detection.

## Keys: the virtual camera

`keys.json`:

```json
{
  "src": "~/Movies/reel-forge/360/VID.insv",
  "out": "~/Movies/reel-forge/360/output/shot-1.mp4",
  "start": 12.0, "dur": 12, "fps": 30, "speed": 1.0, "audio": true,
  "stab": "visual", "mode": "heading", "level": "auto", "blur": 0.35,
  "keys": [
    {"t": 0,    "planet": true, "yaw": 0},
    {"t": 2.5,  "planet": true, "yaw": 60},
    {"t": 4.0,  "yaw": 90, "pitch": 0, "fov": 80, "ease": "smooth"},
    {"t": 7.0,  "yaw": 130, "punch": 0.25},
    {"t": 7.35, "yaw": 300, "ease": "whip"},
    {"t": 10,   "yaw": 310, "fov": 70}
  ]
}
```

Everything in degrees. Fields missing from a key **are inherited from the previous one**.

| Field | What it is |
|---|---|
| `yaw` | 0 = the front of the equirectangular, + to the right, 180 = behind |
| `pitch` | + looks up, −90 = nadir (looking at the ground) |
| `roll` | + tilts clockwise |
| `fov` | **horizontal** field of view of the output frame |
| `d` | projection: 0 rectilinear, 1 stereographic. If you leave it out, it's computed from the `fov` |
| `ease` | how you **arrive** at that key |
| `punch` | snaps the `fov` closed on arrival (0.2 = 20 %) |

**Yaw does not wrap.** To go from 170 to −170 the short way, write **190**, not −170. Otherwise the
camera takes the long way round. This is mistake number one.

`ease`: `linear`, `smooth`, `in`, `out`, `whip`, `cut`, `spline`.

### Whip-pan

Two keys 0.3-0.4 s apart between different directions, with `"ease": "whip"`. The motion blur is computed
from the angular speed: `"blur": 0.35` (the default, light), 0.5 is more noticeable.

It's the effect that sells the 360 best: you look like you have two cameras. But **before landing a whip,
check what's at the destination at that exact second**, with a fixed 2 s render at `fps: 6` pointed
there. A subject who at 24.4 s is split by the seam has cleared it by 24.95.

### Tiny planet

`{"planet": true}` is equivalent to `pitch −90, fov 200, d 1`. With `yaw` the planet spins.

If the next key is a normal view with `ease: "smooth"`, the planet **unrolls** in ~2 s. It's the classic
reveal and it works very well as an opener.

Settings that solve the typical problems:

- **The planet cuts off the subject's head or hat:** raise the `fov` to 235. The planet ends up smaller
  and fits whole.
- **The person filming comes out huge and deformed at the edge:** straight nadir puts whoever is holding
  the camera on the edge of the stereographic projection, flattened. Use
  `"planet": true, "pitch": -60, "fov": 220` with the `yaw` in their direction: they come out small and
  standing on the planet. If the camera is very close, `pitch -45, fov 260`.
- **If the person filming is within 2-3 m of the lens, don't use a tiny planet on that clip.** Rotating
  it doesn't help: the person filming and the subject are usually ~166° apart, so you can only save one,
  and the other gets stretched across half the screen. Swap the planet for a **rectilinear push**
  (`yaw 296→346`, `pitch 12→−3`, `fov 124→70`): the same reveal feeling without deforming faces.
- **Land on the subject of the scene, not on the person filming.** Whoever holds the camera is always an
  arm's length from the lens: the fisheye deforms their face and almost always catches them mid-gesture.
  Pull a `ring8` sheet of the final instants, locate the real subject by yaw, and send the last key
  there.
- **Loop:** the final planet has to use the same geometry and the same spin direction as the first.
- The closing caption goes **on the second the unroll lands**, not before: otherwise it sits on top of a
  spinning planet.

### Low-angle framing

With the camera at knee or chest height, a normal view (`pitch +20..+30`) comes out from below: huge
hands and knees. A **half planet** works better:
`{"yaw": <subject>, "pitch": -12, "fov": 150}` → `{"pitch": -4, "fov": 138}`. The subject appears full
body, with the surroundings around them, and the face lands in the upper third.

## Stabilization and levelling

In the spec, not in the keys:

| Field | Values | What it does |
|---|---|---|
| `stab` | `no`, `visual`, `gyro`, `auto` | where the per-frame orientation comes from |
| `mode` | `heading`, `lock` | `heading` keeps the horizon fixed and the front follows where you're travelling (FlowState-style); `lock` pins the direction in the world |
| `level` | `auto`, `no`, `gyro`, `[pitch, roll]` | straightens the horizon |

- **`visual`**: optical flow + RANSAC between frames, detects scene cuts. Works with any equirectangular,
  whatever it came from. It's rotation-only: it doesn't fix rolling shutter or parallax, and it drifts
  slowly in yaw (in `heading` mode you don't notice).
- **`gyro`/`auto`**: only with `.insv`, which carries the IMU. The IMU→image rotation **self-calibrates**
  against the visual rotation (Kabsch + a ±0.3 s offset search), so it doesn't depend on the factory
  matrix, which varies between cameras.
- **`level: "auto"`** uses the accelerometer if there's a gyroscope, and otherwise the vanishing point of
  the vertical lines every 2 s. It needs real verticals (poles, buildings, trees). In open landscape (sea,
  mountains) it finds none: it says so and leaves that shot unlevelled. There, use the `.insv` gyro or
  set the degrees by hand with `"level": [pitch, roll]`.

The result is cached next to the proxy (`.orient-*.npz`, `.level-*.npy`): computed once per clip.

## Following a person

```bash
uv run $S follow VID --start 0 --dur 12 --type selfie --target 90,-20 --hz 6 --render
```

Detects people with MediaPipe (`efficientdet_lite0`, downloaded to the cache), samples at `--hz`,
smooths the 3D vector with a One-Euro filter and writes `spline` keys.

- `--type selfie`: a tight framing on the person. `--type third`: a wider shot, the person off-centre.
- `--target YAW,PITCH` tells it who to follow when there are several people. Get it from the sheet with
  `--people`.
- Near the nadir (a person holding the camera on a stick) their yaw changes extremely fast. The smoothing
  helps, but if the person walks around the camera, the view spins with them. Check the keys by hand
  there.
- It costs ~2.3 s per second of clip with 10 views per sample.

## The .insv format

An X3/X4/X5 `.insv` **is not a spherical video**: it's the raw material of the two lenses.

- **Two 3840x3840 HEVC tracks**, one per lens, each with a ~193° fisheye circle (the stored usable disc
  measures between ~186° and ~194° depending on the model).
- On the X5, **track 0 = rear lens, track 1 = front**.
- AAC audio.
- A **trailer** at the end of the file with the telemetry (gyroscope and accelerometer) and that specific
  camera's factory calibration.
- Older models and the `.lrv` files (the low-resolution proxy the camera records alongside) may carry both
  circles side by side in a single track.

The script converts it to an equirectangular with ffmpeg:

```
[0:v:1]null[f];[0:v:0]null[b];[f][b]hstack=inputs=2:shortest=1,
v360=input=dfisheye:output=e:ih_fov=193:iv_fov=193:w=3840:h=1920:interp=cubic
```

That is: the two lenses side by side (**front first**) and `v360` in dual-fisheye mode.

If the result comes out mirrored, rotated or with an odd seam, adjust the stitch and redo it:

```bash
uv run $S proxy VID.insv --order 01 --rot-front 90 --rot-back 270 --fov 190 --force
```

The telemetry is read with [telemetry-parser](https://github.com/AdrianEddy/telemetry-parser)
(`uv run $S telemetry VID.insv` prints the model, the sample rate and the ranges).

### When NOT to use this stitch

`v360` treats each lens as an ideal fisheye and **doesn't apply the camera's calibration**: on objects
near the seam (someone walking past a metre away, an animal against the lens) the join shows, and it
sometimes splits the subject in two.

For a final delivery with material near the seam, the best path is:

1. Export the **flat 360 (equirectangular)** from **Insta360 Studio** (macOS and Windows only), with
   FlowState and the horizon already applied.
2. Reframe that MP4 here with `"stab": "no"` and `"level": "no"` (they're already done).

The script accepts any 2:1 equirectangular, not just `.insv`.

An alternative without Studio: [insv-stitch](https://github.com/BenjaminHenriksson/insv-stitch) (MIT),
which does use the MEI model with the calibration stored in the file.

## Proxies and resolution

All the work (sheets, stabilization, following, rendering) happens on a 30 fps equirectangular proxy,
because running `v360` over 8K frame by frame is glacial.

- Default: `--width 3840` (3840x1920). With that proxy, a 70° `fov` window uses ~750 px of source, so a
  1080 output is already upscaled.
- **Heavy zoom (`fov` < ~50) looks soft.** For tight punch-ins: `proxy --width 5760`.
- **Slow motion:** the proxy is 30 fps. For `"speed": 0.5` with 60 fps clips you have to create the proxy
  at 60 (the `FPS` constant in the script).
- The proxy is reused as long as it's newer than the original; `--force` rebuilds it.

## Reference timings

Measured on a MacBook Pro M3 Max. These are orders of magnitude, not promises.

| Step | Time |
|---|---|
| 8K → 3840 proxy (20.8 s of video) | 9.9 s |
| 1080x1920 render with planet, pan and whip (12 s) | 6.5 s (~55 fps) |
| Visual stabilization (29 s, 873 pairs) | 9 s, once per proxy and then cached |
| Levelling by vertical lines (29 s clip) | 7-8 s |
| `follow` at 6 Hz with 10 views per sample | ~2.3 s per second of clip |
| A 3-instant sheet with person detection | ~10 s |

The proxy uses `-hwaccel videotoolbox`, which is **macOS**. On Linux or Windows it works the same without
that flag, just slower; remove it from the command if it errors.

## Limitations you have to tell the user about

- **The stitch seam shows** on nearby objects, around yaw ±90 with the `v360` stitch. For shots where
  that matters, export from Studio.
- **The selfie stick isn't removed.** Studio removes it; `v360` doesn't. In a tiny planet it sits at the
  centre of the planet, where it shows least, but it's there.
- **The nadir is the weak point.** Directly below the camera is the stick, the hand or the ground right
  against the lens. Avoid keys with `pitch` between −70 and −85 unless you're doing a tiny planet on
  purpose.
- Visual stabilization is **rotation-only**: it doesn't fix walking shake (translation) or rolling
  shutter.
- Auto-levelling **doesn't work in open landscape**: without verticals there is no reference.
- The output is fixed at 1080x1920.

## Common mistakes, in order

1. Writing the yaw wrapped (−170 instead of 190) and having the camera take the long way round.
2. Landing a whip or an unroll on whoever is holding the camera.
3. Assembling the keys without having looked at a contact sheet.
4. A tight punch-in with the 3840 proxy (it looks soft).
5. Leaving a tiny planet on a clip where the person filming is right against the lens.
6. Putting the closing caption up before the unroll lands.
