# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = [
#   "numpy<2.3",
#   "opencv-contrib-python<5",
#   "pillow",
#   "pillow-heif",
#   "mediapipe==0.10.21",   # only for `behind` and `cutout`
#   "telemetry-parser",     # only for 360 segments (`r360`)
# ]
# ///
"""Video engine: builds a vertical 9:16 (1080x1920) video from a JSON spec.

    uv run scripts/render.py SPEC.json [--out path/output.mp4]

Every frame is assembled in numpy and encoded with ffmpeg (`ffmpeg` and `ffprobe` have to be on
the PATH). The full spec format is in SKILL.md.

Spec summary:
{
  "out": "project/video.mp4",           # relative to $REEL_FORGE_OUTPUT, or an absolute path
  "fps": 30, "crf": 22,
  "look": "film" | "teal" | "clean", "grain": 0.008,
  "fade_out": 0.4, "audio_fade_out": 1.2,
  "bpm": 123.0, "beat0": 0.0,
  "segments": [
    {"src": "photo.jpg", "beats": 2, "focus": [0.5, 0.4], "kb": 0.06, "punch": 0.10},
    {"src": "clip.mov", "dur": 2.4, "start": 3.0, "speed": 0.5, "flash": true}
  ],
  "captions": [{"t0": 0.0, "t1": 2.0, "text": "...", "style": "clean", "pos": "low"}],
  "audio": [{"src": "voice.wav", "at": 1.2, "gain": 1.0}],
  "preview_audio": {"src": "song.m4a", "offset": 0, "gain": 1.0}
}

The engine produces `video.mp4` (clean, without copyrighted music) and, if there is
`preview_audio`, also `video-preview.mp4` for review only.

Caption text is written in the run's output language; the engine translates nothing.
"""
import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Scripts with combining marks (Thai, Arabic, Indic) need raqm in Pillow, which loads libfribidi
# at runtime; without it the vowel marks come out as dotted circles. dyld only reads the path when
# the process starts, so we have to re-exec. On Linux the library is usually on the system path
# and this does nothing.
for _dir in ("/opt/homebrew/lib", "/usr/local/lib"):
    if os.path.exists(_dir + "/libfribidi.0.dylib") and _dir not in os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", ""):
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = _dir + ":" + os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        os.execv(sys.executable, [sys.executable] + sys.argv)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps  # noqa: E402

import config  # noqa: E402
import effects  # noqa: E402

try:
    import pillow_heif
    pillow_heif.register_heif_opener()   # for iPhone .heic; ffmpeg does NOT open HEIC
except ImportError:
    pass

W, H, MARGIN, SAFE = config.W, config.H, config.MARGIN, config.SAFE


# ------------------------------------------------------------ material

def _ffprobe(src):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=color_transfer,r_frame_rate:format=duration", "-of", "json", src],
                       capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    st = d["streams"][0]
    num, den = st.get("r_frame_rate", "30/1").split("/")
    return {"hdr": st.get("color_transfer") in ("arib-std-b67", "smpte2084"),
            "fps": float(num) / float(den), "dur": float(d["format"]["duration"])}


def cover(img, w, h, focus=(0.5, 0.5)):
    """Scales to cover w x h and crops centring on `focus` (0-1 over the already scaled image)."""
    ih, iw = img.shape[:2]
    s = max(w / iw, h / ih)
    nw, nh = max(w, round(iw * s)), max(h, round(ih * s))
    img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    x = int(np.clip(focus[0] * nw - w / 2, 0, nw - w))
    y = int(np.clip(focus[1] * nh - h / 2, 0, nh - h))
    return img[y:y + h, x:x + w]


def fit_with_background(img, w, h, y_rel=0.45):
    """`fit: "blur"`: fits the whole image and fills the rest with a blurred version of itself."""
    background = cover(img, w, h)
    background = cv2.GaussianBlur(cv2.resize(background, (w // 8, h // 8)), (0, 0), 3)
    background = (cv2.resize(background, (w, h)) * 0.72).astype(np.uint8)
    ih, iw = img.shape[:2]
    s = min(w / iw, h / ih)
    fg = cv2.resize(img, (round(iw * s), round(ih * s)), interpolation=cv2.INTER_AREA)
    y = int(np.clip(h * y_rel - fg.shape[0] / 2, 0, h - fg.shape[0]))
    x = (w - fg.shape[1]) // 2
    background[y:y + fg.shape[0], x:x + fg.shape[1]] = fg
    return background


def load_photo(src):
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    return np.asarray(im)


def video_frames(src, start, n, speed, fps):
    """Yields n RGB frames of the clip, already SDR, rotation applied, at the working resolution."""
    info = _ffprobe(src)
    vf = []
    if info["hdr"]:
        vf.append("colorspace=all=bt709:iall=bt2020:itrc=bt2020-10:format=yuv420p")
    if speed != 1:
        vf.append(f"setpts=PTS/{speed}")
    vf.append(f"fps={fps}")
    vf.append("scale='if(gt(iw,ih),2400,-2)':'if(gt(iw,ih),-2,2400)'")
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-i", src, "-vf", ",".join(vf),
           "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    raw = p.stdout.read()
    p.wait()
    # The real dimensions after the container's rotation and the scaling can only be known by
    # decoding: we ask for one frame as PNG instead of computing them by hand.
    probe = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-i", src,
                            "-vf", ",".join(vf), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                           capture_output=True, check=True).stdout
    import io
    w0, h0 = Image.open(io.BytesIO(probe)).size
    size = w0 * h0 * 3
    frames = [np.frombuffer(raw[i * size:(i + 1) * size], np.uint8).reshape(h0, w0, 3)
              for i in range(len(raw) // size)]
    if not frames:
        raise RuntimeError(f"No frames from {src} at {start}s")
    while len(frames) < n:  # clip shorter than requested: freeze the last frame
        frames.append(frames[-1])
    return frames[:n]


# ------------------------------------------------------------ colour look

def _curve(points):
    x, y = zip(*points)
    return np.clip(np.interp(np.arange(256), x, y), 0, 255).astype(np.uint8)


LOOKS = {
    # Warm colour-negative film: lifted blacks, warm highlights, green-blue shadows
    "film": {"r": _curve([(0, 14), (64, 66), (128, 136), (192, 204), (255, 250)]),
             "g": _curve([(0, 12), (64, 64), (128, 131), (192, 196), (255, 244)]),
             "b": _curve([(0, 20), (64, 64), (128, 122), (192, 182), (255, 232)]),
             "sat": 0.92, "vig": 0.28},
    # Cinematic teal & orange
    "teal": {"r": _curve([(0, 4), (64, 58), (128, 134), (192, 206), (255, 255)]),
             "g": _curve([(0, 8), (64, 64), (128, 128), (192, 194), (255, 250)]),
             "b": _curve([(0, 22), (64, 76), (128, 124), (192, 176), (255, 236)]),
             "sat": 1.05, "vig": 0.30},
    # No correction: real colour, minimal vignette. Best for whites and bright temples.
    "clean": {"r": _curve([(0, 0), (255, 255)]), "g": _curve([(0, 0), (255, 255)]),
              "b": _curve([(0, 0), (255, 255)]), "sat": 1.05, "vig": 0.12},
}


def vignette(strength):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
    return (1 - strength * np.clip((r - 0.45) / 0.55, 0, 1) ** 1.6)[..., None].astype(np.float32)


def apply_look(img, look, vig, grain, rng):
    out = np.dstack([cv2.LUT(img[..., i], look[c]) for i, c in enumerate("rgb")]).astype(np.float32)
    if look["sat"] != 1:
        grey = out.mean(axis=2, keepdims=True)
        out = grey + (out - grey) * look["sat"]
    out *= vig
    if grain > 0:
        # FINE grain, at full resolution and in luminance only. Generating it at half resolution
        # and scaling it up looks dirty, like compression noise. Keep grain <= 0.012.
        noise = rng.standard_normal((H, W, 1)).astype(np.float32)
        light = out.mean(axis=2, keepdims=True) / 255
        out += noise * grain * 255 * (0.35 + 0.65 * (1 - np.abs(light * 2 - 1)))  # less in blacks and whites
    return np.clip(out, 0, 255).astype(np.uint8)


# ------------------------------------------------------------ text

DEFAULT_SIZE = {"bold": 74, "serif": 96, "box": 58, "clean": 64, "yellow": 96, "pin": 46}

_THAI = ("฀", "๿")
_CJK = ("　", "鿿")


def font(style, size, text=""):
    """The style's typeface, with an automatic fallback if the text carries Thai or CJK."""
    if any(_THAI[0] <= ch <= _THAI[1] for ch in text):
        alt = config.script_font("thai")
        if alt:
            return ImageFont.truetype(str(alt), size, index=0 if style == "serif" else 1)
    if any(_CJK[0] <= ch <= _CJK[1] for ch in text):
        alt = config.script_font("cjk")
        if alt:
            return ImageFont.truetype(str(alt), size, index=1)
    if style == "serif":
        return ImageFont.truetype(str(config.require(config.FONT_SERIF, "the serif typeface")), size)
    f = ImageFont.truetype(str(config.require(config.FONT_SANS, "the sans typeface")), size)
    try:
        f.set_variation_by_axes([700 if style in ("clean", "pin") else 850])
    except Exception:
        pass   # the sans is not a variable font: use it as is
    return f


def _wrap(draw, text, f, width):
    """Wraps by width while RESPECTING the \\n characters the text already carries.

    Careful: a hand-written \\n does not guarantee the break, because each line still gets
    wrapped by width. If the line does not fit, it gets split anyway and drops orphan words.
    """
    lines = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split():
            attempt = (current + " " + word).strip()
            if draw.textlength(attempt, font=f) <= width or not current:
                current = attempt
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return "\n".join(lines)


def render_text(text, style="clean", size=None, color=None):
    size = size or DEFAULT_SIZE[style]
    if style == "pin":
        return _render_pin(text, size)
    f = font(style, size, text)
    width = W - 2 * 150  # symmetric margin: centred text never invades the button column
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    txt = _wrap(tmp, text, f, width)
    spacing = int(size * 0.18)
    bb = tmp.multiline_textbbox((0, 0), txt, font=f, align="center", spacing=spacing, stroke_width=6)
    tw, th = int(bb[2] - bb[0] + 100), int(bb[3] - bb[1] + 90)
    im = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pos = (50 - bb[0], 45 - bb[1])
    if style == "box":
        # TikTok's "classic text" card. `color` changes the background; the ink is picked by luminance.
        bg = tuple(color or (255, 255, 255))
        lum = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
        ink = (12, 12, 12, 255) if lum > 140 else (255, 255, 255, 255)
        d.rounded_rectangle([0, 0, tw - 1, th - 1], radius=22, fill=bg + (245,))
        d.multiline_text(pos, txt, font=f, fill=ink, align="center", spacing=spacing)
    elif style == "serif":
        # A wide dark halo plus a close shadow: a thin serif disappears over bright skies
        for alpha, blur, stroke in ((150, 22, 10), (215, 5, 2)):
            shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
            ImageDraw.Draw(shadow).multiline_text((pos[0], pos[1] + 2), txt, font=f, fill=(0, 0, 0, alpha),
                                                  align="center", spacing=spacing,
                                                  stroke_width=stroke, stroke_fill=(0, 0, 0, alpha))
            im = Image.alpha_composite(im, shadow.filter(ImageFilter.GaussianBlur(blur)))
        ImageDraw.Draw(im).multiline_text(pos, txt, font=f, fill=(255, 250, 240, 255), align="center",
                                          spacing=spacing)
    elif style == "yellow":
        # A key word (a place, a price) in thick yellow with a shadow: the route-guide look
        shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).multiline_text((pos[0] + 3, pos[1] + 5), txt, font=f, fill=(0, 0, 0, 170),
                                              align="center", spacing=spacing, stroke_width=5,
                                              stroke_fill=(0, 0, 0, 170))
        im = Image.alpha_composite(im, shadow.filter(ImageFilter.GaussianBlur(6)))
        ImageDraw.Draw(im).multiline_text(pos, txt, font=f, fill=tuple(color or (255, 212, 0)) + (255,),
                                          align="center", spacing=spacing, stroke_width=3,
                                          stroke_fill=(40, 25, 0, 255))
    elif style == "clean":
        # Minimal: white sans, soft shadow, no thick outline. The default for subtitles.
        shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).multiline_text((pos[0], pos[1] + 3), txt, font=f, fill=(0, 0, 0, 200),
                                              align="center", spacing=spacing, stroke_width=4,
                                              stroke_fill=(0, 0, 0, 200))
        im = Image.alpha_composite(im, shadow.filter(ImageFilter.GaussianBlur(9)))
        ImageDraw.Draw(im).multiline_text(pos, txt, font=f, fill=(255, 255, 255, 255), align="center",
                                          spacing=spacing)
    else:  # "bold": thick black outline. Always legible, but it reads like an editor from years ago.
        d.multiline_text(pos, txt, font=f, fill=(255, 255, 255, 255), align="center",
                         spacing=spacing, stroke_width=7, stroke_fill=(0, 0, 0, 255))
    return np.asarray(im).astype(np.float32) / 255


def _render_pin(text, size):
    """A fixed place label with a red pin ("Day 4 · City"). It does not wrap: one short line."""
    f = font("pin", size, text)
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bb = tmp.textbbox((0, 0), text, font=f)
    tw, th = int(bb[2] - bb[0]), int(bb[3] - bb[1])
    r = int(size * 0.36)
    W0, H0 = tw + r * 2 + 70, th + 40
    im = Image.new("RGBA", (W0, H0), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, W0 - 1, H0 - 1], radius=H0 // 2, fill=(15, 15, 15, 150))
    cx, cy = 22 + r, H0 // 2 - 4
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(235, 50, 50, 255))
    d.polygon([(cx - r * 0.7, cy + r * 0.5), (cx + r * 0.7, cy + r * 0.5), (cx, cy + r * 1.7)],
              fill=(235, 50, 50, 255))
    d.ellipse([cx - r * 0.38, cy - r * 0.38, cx + r * 0.38, cy + r * 0.38], fill=(255, 255, 255, 255))
    d.text((cx + r + 16 - bb[0], (H0 - th) // 2 - bb[1]), text, font=f, fill=(255, 255, 255, 255))
    return np.asarray(im).astype(np.float32) / 255


def prepare_captions(caps):
    """Expands the captions into already rasterized pieces with their time window."""
    pieces = []
    for c in caps:
        style, pos = c.get("style", "clean"), c.get("pos", "low")
        common = {"pos": pos, "dx": c.get("dx", 0), "dy": c.get("dy", 0)}
        if c.get("words"):
            # Word-by-word subtitle in groups of up to 3, timed proportionally to the letters
            groups, g = [], []
            for w in c["text"].split():
                g.append(w)
                if len(g) == 3 or w.endswith((",", ".", "…", "?", "!")):
                    groups.append(" ".join(g))
                    g = []
            if g:
                groups.append(" ".join(g))
            total = sum(len(x) + 2 for x in groups)
            t = c["t0"]
            for x in groups:
                d = (c["t1"] - c["t0"]) * (len(x) + 2) / total
                pieces.append({"t0": t, "t1": t + d, "pop": True,
                               "img": render_text(x, style, c.get("size"), c.get("color")), **common})
                t += d
        else:
            pieces.append({"t0": c["t0"], "t1": c["t1"], "pop": c.get("pop", True),
                           "img": render_text(c["text"], style, c.get("size"), c.get("color")), **common})
    return pieces


def paste_text(frame, piece, t):
    img = piece["img"]
    age = t - piece["t0"]
    if piece["pop"] and age < 0.12:
        e = age / 0.12
        s = 0.86 + 0.14 * (1 - (1 - e) ** 3)
        img = cv2.resize(img, (max(2, int(img.shape[1] * s)), max(2, int(img.shape[0] * s))))
    global_alpha = min(1.0, age / 0.06) * min(1.0, (piece["t1"] - t) / 0.06)
    h, w = img.shape[:2]
    # Genuinely centred on the SCREEN (cx = W/2), not on the safe area (which is asymmetric:
    # 60 px on the left and 180 on the right). Centring on the safe area leaves captions
    # visibly pushed to the left.
    y_by_pos = {"top": SAFE["top"] + 40, "topleft": SAFE["top"] + 20, "upper": H * 0.30 - h / 2,
                "center": (H - h) / 2 - 60, "low": H - SAFE["bottom"] - h - 20,
                "lowleft": H - SAFE["bottom"] - h - 20, "lowright": H - SAFE["bottom"] - h - 20}
    if piece["pos"] not in y_by_pos:
        raise SystemExit(f"Unknown `pos`: {piece['pos']}. Options: {', '.join(y_by_pos)}")
    x0, y0 = int(W / 2 - w / 2), int(y_by_pos[piece["pos"]])
    if piece["pos"] == "topleft":
        x0 = SAFE["left"]
    elif piece["pos"] == "lowleft":
        x0 = SAFE["left"] - 40          # the PNG carries 50 px of air on each side
    elif piece["pos"] == "lowright":
        x0 = W - SAFE["right"] - w + 40
    x0 += int(piece.get("dx", 0))
    y0 += int(piece.get("dy", 0))
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x0 + w), min(H, y0 + h)
    sub = img[: y1 - y0, : x1 - x0]
    a = sub[..., 3:4] * global_alpha
    zone = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = (zone * (1 - a) + sub[..., :3] * 255 * a).astype(np.uint8)


# ------------------------------------------------------------ assembly

def _engine_360():
    """Imports `reframe360` from the sibling `video-360` skill (or from $REEL_FORGE_360_SCRIPTS)."""
    candidates = [os.environ.get("REEL_FORGE_360_SCRIPTS"),
                  Path(__file__).resolve().parent,
                  Path(__file__).resolve().parent.parent.parent / "video-360" / "scripts"]
    for c in candidates:
        if c and Path(c).is_dir() and (Path(c) / "reframe360.py").exists():
            if str(c) not in sys.path:
                sys.path.insert(0, str(c))
            import reframe360
            return reframe360
    raise SystemExit("A segment asks for `r360` but I cannot find `reframe360.py` (the `video-360` skill).\n"
                     "Remove the `r360` from the segment or point $REEL_FORGE_360_SCRIPTS at that folder.")


def _segment_base(s, n, fps, src, focus):
    """The segment's frames at the working resolution (W*MARGIN x H*MARGIN). None = a map."""
    WM, HM = int(W * MARGIN), int(H * MARGIN)
    if "map" in s:
        return None
    if s.get("r360"):
        reframe360 = _engine_360()
        r = s["r360"]
        r = json.loads(config.path(r).read_text()) if isinstance(r, str) else dict(r)
        r.setdefault("src", src)
        r.setdefault("start", s.get("start", 0))
        return list(reframe360.frames(r, n, fps, WM, HM))
    if src.lower().endswith((".mov", ".mp4", ".m4v", ".mkv", ".insv")):
        raw = video_frames(src, s.get("start", 0), n, s.get("speed", 1), fps)
        if s.get("fit") == "blur":
            return [fit_with_background(c, WM, HM) for c in raw]
        return [cover(c, WM, HM, focus) for c in raw]
    photo = load_photo(src)
    single = fit_with_background(photo, WM, HM) if s.get("fit") == "blur" else cover(photo, WM, HM, focus)
    return [single] * n


def main():
    ap = argparse.ArgumentParser(description="Vertical 9:16 video engine")
    ap.add_argument("spec", help="JSON file with the spec")
    ap.add_argument("--out", help="overrides the spec's `out`")
    args = ap.parse_args()

    with open(args.spec) as fh:
        spec = json.load(fh)
    fps = spec.get("fps", config.FPS)
    look = LOOKS[spec.get("look", "film")]
    vig = vignette(look["vig"])
    grain = min(spec.get("grain", 0.008), config.GRAIN_MAX)
    rng = np.random.default_rng(7)
    beat = 60 / spec["bpm"] if spec.get("bpm") else None

    # Segment timings on an absolute grid, so they don't accumulate drift against the beat
    t = spec.get("beat0", 0.0)
    cuts = []
    for s in spec["segments"]:
        if "beats" in s and beat is None:
            raise SystemExit("A segment uses `beats` but the spec carries no `bpm`.")
        t += s["beats"] * beat if "beats" in s else s["dur"]
        cuts.append(t)
    total = cuts[-1]
    pieces = prepare_captions(spec.get("captions", []))

    out = config.resolve_output(args.out or spec["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    silent = out.with_name(out.stem + ".video.mp4")
    enc = subprocess.Popen(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                            "-crf", str(spec.get("crf", 22)),
                            "-pix_fmt", "yuv420p", str(silent)], stdin=subprocess.PIPE)
    start = spec.get("beat0", 0.0)
    for s, end in zip(spec["segments"], cuts):
        n = round(end * fps) - round(start * fps)
        src = str(config.path(s["src"])) if s.get("src") else ""
        focus = s.get("focus", [0.5, 0.5])
        route_map = effects.RouteMap(s["map"], font("bold", 54)) if "map" in s else None
        base = _segment_base(s, n, fps, src, focus)
        if base is not None and s.get("stutter"):
            k = int(s["stutter"])  # repeat each frame k times: the low-fps walking effect
            base = [base[(i // k) * k] for i in range(len(base))]
        if base is not None and s.get("freeze"):
            base = [base[0]] * n
        title = None
        if s.get("behind"):
            bh = s["behind"]
            size = bh.get("size", 230)
            while True:  # shrink until it fits the width
                title = effects.render_title(bh["text"], font(bh.get("style", "bold"), size, bh["text"]),
                                             bh.get("color", [255, 255, 255]))
                if title.shape[1] <= W * 0.94 or size < 60:
                    break
                size = int(size * 0.93)
        cards = None
        if s.get("cutout"):
            cards = [effects.card(x, font("bold", 44, x)) for x in s["cutout"].get("lines", [])]
        masks = {}   # a one-entry cache: on photos the base frame repeats
        kb, punch = s.get("kb", 0.05), s.get("punch", 0.0)
        m = None
        for i, b in enumerate(base if base is not None else [None] * n):
            tg = (round(start * fps) + i) / fps
            if b is None:
                frame = route_map.frame(i / fps, n / fps)
                frame = apply_look(frame, LOOKS["clean"], vig, 0, rng)
            else:
                # zoom: a slow Ken Burns (kb) plus an entry "punch" that settles with an ease-out
                z = 1 + kb * (i / max(1, n - 1))
                if punch:
                    e = min(1.0, (i / fps) / 0.22)
                    z += punch * (1 - e) ** 3
                cw, ch = int(W * MARGIN) / z, int(H * MARGIN) / z
                x0 = (int(W * MARGIN) - cw) / 2 + (s.get("drift", [0, 0])[0] * int(W * MARGIN) * i / max(1, n))
                y0 = (int(H * MARGIN) - ch) / 2 + (s.get("drift", [0, 0])[1] * int(H * MARGIN) * i / max(1, n))
                M = np.float32([[W / cw, 0, -x0 * W / cw], [0, H / ch, -y0 * H / ch]])
                frame = cv2.warpAffine(b, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                if title is not None or cards is not None:
                    # the mask is computed over the base and warped exactly like the image
                    if id(b) not in masks:
                        masks = {id(b): effects.segmenter().mask(b)}
                    m = cv2.warpAffine(masks[id(b)], M, (W, H), flags=cv2.INTER_LINEAR)
                frame = apply_look(frame, look, vig, grain, rng)
                if title is not None and i / fps >= s["behind"].get("at", 0.0):
                    frame = effects.text_behind(frame, m, title, i / fps - s["behind"].get("at", 0.0),
                                                s["behind"].get("y", 0.3))
                if cards is not None:
                    frame = effects.character_intro(frame, m, i / fps, n / fps, cards,
                                                    y_rel=s["cutout"].get("y", 0.62))
                if s.get("flash") and i < 3:
                    a = [0.85, 0.45, 0.15][i]
                    frame = (frame * (1 - a) + 255 * a).astype(np.uint8)
            for p in pieces:
                if p["t0"] <= tg < p["t1"]:
                    paste_text(frame, p, tg)
            fo = spec.get("fade_out", 0)
            if fo and tg > total - fo:
                frame = (frame * max(0.0, (total - tg) / fo)).astype(np.uint8)
            enc.stdin.write(np.ascontiguousarray(frame).tobytes())
        start = end
        print(f"  {Path(src).name or 'map'}: {n} frames", flush=True)
    enc.stdin.close()
    enc.wait()

    # "audio_fade_out": seconds of tail at the end (default 1.2; 0 for seamless loops).
    # The limiter keeps the sum of the tracks from clipping: a mix with music on top of the
    # natural audio easily reaches +5 dBTP with nothing warning.
    afo = float(spec.get("audio_fade_out", 1.2))
    audio_tail = (f",afade=t=out:st={max(0, total - afo)}:d={afo}" if afo > 0 else "") + ",alimiter=limit=0.89:level=false"

    def mix(target, tracks):
        if not tracks:
            if target == out:
                os.replace(silent, target)
            else:
                subprocess.run(["cp", str(silent), str(target)], check=True)
            return
        # TWO STEPS: first the audio alone into a WAV, then attach it to the video. A single
        # ffmpeg call with many tracks (~19) plus the video hangs with no error.
        wav = out.with_name(out.stem + ".mix.wav")
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
        filters = []
        for k, a in enumerate(tracks):
            cmd += ["-ss", str(a.get("offset", 0)), "-i", str(config.path(a["src"]))]
            ms = int(a.get("at", 0) * 1000)
            trim = (f"atrim=0:{a['dur']},afade=t=in:d=0.3,"
                    f"afade=t=out:st={max(0, a['dur'] - 0.5)}:d=0.5," if a.get("dur") else "")
            filters.append(f"[{k}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,{trim}"
                           f"adelay={ms}|{ms},volume={a.get('gain', 1)}[a{k}]")
        mixed = "".join(f"[a{k}]" for k in range(len(tracks)))
        # aresample first_pts=0: if NO track starts at at=0, the mix comes out with an initial pts
        # equal to the first adelay and the atrim below clips the audio to (total - that adelay).
        filters.append(f"{mixed}amix=inputs={len(tracks)}:normalize=0:duration=longest,"
                       f"apad=whole_dur={total},aresample=async=1:first_pts=0,atrim=0:{total}{audio_tail}[a]")
        cmd += ["-filter_complex", ";".join(filters), "-map", "[a]", "-t", str(total), str(wav)]
        subprocess.run(cmd, check=True, timeout=600)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(silent), "-i", str(wav), "-map", "0:v",
                        "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", str(total),
                        "-movflags", "+faststart", str(target)], check=True, timeout=600)
        wav.unlink()

    clean = spec.get("audio", [])
    if spec.get("preview_audio"):
        mix(out.with_name(out.stem + "-preview.mp4"), clean + [spec["preview_audio"]])
    mix(out, clean)
    if silent.exists():
        silent.unlink()
    print(json.dumps({"out": str(out), "duration": round(total, 2),
                      "preview": str(out.with_name(out.stem + "-preview.mp4")) if spec.get("preview_audio") else None},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
