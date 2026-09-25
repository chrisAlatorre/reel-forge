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
"""Video engine: builds a video from a JSON spec, in the format the destination asks for.

    uv run scripts/render.py SPEC.json [--out path/output.mp4] [--format 9x16|4x5|1x1|16x9]

Every frame is assembled in numpy and encoded with ffmpeg (`ffmpeg` and `ffprobe` have to be on
the PATH). The full spec format is in SKILL.md.

Spec summary:
{
  "out": "project/video.mp4",           # relative to $REEL_FORGE_OUTPUT, or an absolute path
  "format": "9x16",                     # 9x16 (default) | 4x5 | 1x1 | 16x9
  "fps": 30, "crf": 22,
  "look": "film" | "teal" | "clean", "grain": 0.008,
  "fade_out": 0.4, "audio_fade_out": 1.2,
  "loop": false,                        # true: it closes on its own first frame (put both fades at 0)
  "bpm": 123.0, "beat0": 0.0,
  "segments": [
    {"src": "photo.jpg", "beats": 2, "focus": [0.5, 0.4], "kb": 0.06, "punch": 0.10},
    {"src": "clip.mov", "dur": 2.4, "start": 3.0, "speed": 0.5, "flash": true, "subs": true}
  ],
  "captions": [{"t0": 0.0, "t1": 2.0, "text": "...", "style": "clean", "pos": "low",
                "instant": true},                    # already up on its first frame: for the hook
               {"seg": 3, "text": "..."}],          # tied to the cut instead of to a second
  "sync": {"from": "voice/alignment.json"},          # subtitles taken from the voice, word by word
  "audio": [{"src": "voice/l0.wav", "at": 1.2, "gain": 1.0}],
  "duck": true,                                      # everything drops under the narration
  "preview_audio": {"src": "song.m4a", "offset": 0, "gain": 1.0}
}

The engine produces `video.mp4` (clean, without copyrighted music), `video.timeline.json` (what it
burned in and where every cut fell, which `verify.py` reads) and, if there is `preview_audio`, also
`video-preview.mp4` for review only.

Caption text is written in the run's output language; the engine translates nothing.
"""
import argparse
import json
import math
import os
import re
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


def set_format(name):
    """Switches the canvas (9x16 | 4x5 | 1x1 | 16x9) and re-reads it here and in effects."""
    global W, H, SAFE
    fmt = config.set_format(name)
    W, H, SAFE = config.W, config.H, config.SAFE
    effects.refresh()
    return fmt


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
    # Sizes in a spec are always written in the 9x16 reference (1080x1920); each format rescales
    # them, because a 64 px caption that reads fine on a phone held vertically is tiny on 16x9.
    size = max(16, int(round((size or DEFAULT_SIZE[style]) * config.TEXT_SCALE)))
    if style == "pin":
        return _render_pin(text, size)
    f = font(style, size, text)
    width = config.TEXT_WIDTH  # symmetric margin: centred text never invades the button column
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
    """Expands the captions into already rasterized pieces with their time window.

    Each piece keeps its text and, when it came from the narration, the second the voice actually
    says it (`audio_t0`): the timeline the render writes next to the MP4 carries both, and that is
    what `verify.py` compares to find text drifting away from the voice.
    """
    pieces = []
    for c in caps:
        style, pos = c.get("style", "clean"), c.get("pos", "low")
        common = {"pos": pos, "dx": c.get("dx", 0), "dy": c.get("dy", 0),
                  "source": c.get("source", "spec")}
        for k in ("audio_t0", "audio_t1", "line"):
            if c.get(k) is not None:
                common[k] = c[k]
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
            for k, x in enumerate(groups):
                d = (c["t1"] - c["t0"]) * (len(x) + 2) / total
                # Only the first group starts where the voice does; the rest are shared out by
                # letters, which is an estimate and must not claim to be anchored to the audio.
                piece = {**common, "t0": t, "t1": t + d, "pop": True, "text": x,
                         "img": render_text(x, style, c.get("size"), c.get("color"))}
                if k:
                    piece.pop("audio_t0", None)
                    piece.pop("audio_t1", None)
                pieces.append(piece)
                t += d
        else:
            pieces.append({**common, "t0": c["t0"], "t1": c["t1"], "pop": c.get("pop", True),
                           "instant": bool(c.get("instant")),
                           "text": c["text"],
                           "img": render_text(c["text"], style, c.get("size"), c.get("color"))})
    return pieces


def paste_text(frame, piece, t):
    img = piece["img"]
    age = t - piece["t0"]
    # `instant`: no pop and no fade-in, so the text is already up on its FIRST frame. It is for the
    # hook: 0.06 s of fade is two frames, but they are exactly the two frames where the scroll is
    # decided, and on the first one the text did not exist yet. The fade-out is kept.
    instant = piece.get("instant")
    if piece["pop"] and not instant and age < 0.12:
        e = age / 0.12
        s = 0.86 + 0.14 * (1 - (1 - e) ** 3)
        img = cv2.resize(img, (max(2, int(img.shape[1] * s)), max(2, int(img.shape[0] * s))))
    entrada = 1.0 if instant else min(1.0, age / 0.06)
    global_alpha = entrada * min(1.0, (piece["t1"] - t) / 0.06)
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



# ------------------------------------------------------------ subtitles of the clip's own audio

def _scaled(px):
    """A pixel size written in the 9x16 reference, in the current format."""
    return max(8, int(round(px * config.TEXT_SCALE)))


def _read_transcript(path):
    """A transcript from `transcribe.py`: [{t0, t1, text}] in the SOURCE clip's time."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = data.get("segments", data) if isinstance(data, dict) else data
    out = []
    for e in raw:
        t0 = float(e.get("t0", e.get("start", 0)))
        t1 = float(e.get("t1", e.get("end", t0)))
        text = (e.get("text") or "").strip()
        if text and t1 > t0:
            out.append({"t0": t0, "t1": t1, "text": text})
    return out


def segment_subtitles(s, g0, g1):
    """Captions for what is HEARD in this segment, only if the segment asks for them (`subs`).

    The engine never subtitles on its own: `transcribe.py` proposes candidates and the spec decides,
    segment by segment, which ones get burned in. Accepted forms:

        "subs": true                                   # the sidecar <clip>.transcript.json
        "subs": "transcripts/clip.json"                # a transcript, in the clip's own time
        "subs": {"from": "...", "style": "clean", "pos": "low", "size": 52, "shift": 0.0}
        "subs": [{"t0": 0.2, "t1": 1.6, "text": "..."}]  # by hand, relative to the SEGMENT

    A transcript carries the clip's time, so the engine maps it with the segment's `start` and
    `speed`; anything falling outside the segment is dropped, not squeezed in.
    """
    cfg = s.get("subs")
    if not cfg:
        return []
    if cfg is True:
        cfg = {}
    elif isinstance(cfg, str):
        cfg = {"from": cfg}
    elif isinstance(cfg, list):
        cfg = {"lines": cfg}
    else:
        cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}

    lines = cfg.get("lines")
    if lines is None:
        src = config.path(s["src"]) if s.get("src") else None
        where = cfg.get("from") or (str(src) + ".transcript.json" if src else None)
        if not where:
            raise SystemExit("A segment asks for `subs` but carries neither `from` nor `src`.")
        where = config.path(where)
        if not where.exists():
            raise SystemExit(f"`subs` needs the transcript {where}.\nGenerate it with:  "
                             f"uv run \"{Path(__file__).resolve().parent / 'transcribe.py'}\" \"{src}\"")
        start, speed = float(s.get("start", 0)), float(s.get("speed", 1) or 1)
        lines = [{"t0": (e["t0"] - start) / speed, "t1": (e["t1"] - start) / speed, "text": e["text"]}
                 for e in _read_transcript(where)]

    shift = float(cfg.get("shift", 0.0))
    min_dur = float(cfg.get("min_dur", 0.7))
    out = []
    for e in lines:
        t0 = max(g0, g0 + float(e["t0"]) + shift)
        t1 = min(g1, g0 + float(e["t1"]) + shift)
        if t1 - t0 < 0.2:          # a fragment that barely touches this cut: it cannot be read
            continue
        t1 = min(g1, max(t1, t0 + min_dur))
        cap = {"t0": t0, "t1": t1, "text": e["text"], "style": cfg.get("style", "clean"),
               "pos": cfg.get("pos", "low"), "size": cfg.get("size", 52), "source": "clip"}
        for k in ("color", "words", "pop", "instant", "dx", "dy"):
            if k in cfg:
                cap[k] = cfg[k]
        out.append(cap)
    return out


# ------------------------------------------------------------ text tied to the cut, and to the voice

def anchor_captions(caps, starts, cuts):
    """Resolves the captions that declare `seg` instead of hand-written seconds.

    With no narration underneath, a caption belongs to a shot, not to a number somebody typed:

        {"seg": 3, "text": "…"}                  # it lives and dies with segment 3
        {"seg": [3, 5], "text": "…"}             # from the entry of 3 to the end of 5
        {"seg": 3, "lead": 0.15, "tail": 0.3}    # comes in a touch after the cut, holds past it

    Retyping the seconds every time a duration changes is how text ends up drifting away from the
    picture; `seg` cannot drift, because it is read off the same grid the cuts are.
    """
    out = []
    for c in caps:
        c = {k: v for k, v in c.items() if not k.startswith("_")}
        seg = c.pop("seg", None)
        lead, tail = float(c.pop("lead", 0.0)), float(c.pop("tail", 0.0))
        if seg is not None:
            idx = [seg, seg] if isinstance(seg, int) else [seg[0], seg[-1]]
            n = len(starts)
            for i in idx:
                if not isinstance(i, int) or not -n <= i < n:
                    raise SystemExit(f"A caption points at `seg` {seg}, and the spec has {n} segments.")
            c["t0"] = starts[idx[0]] + lead
            c["t1"] = cuts[idx[1]] + tail
            # Anchored to the grid: it cannot drift, and spanning several shots is what it was
            # asked to do, so the verifier does not read it as text outliving its cut.
            c["source"] = "cut"
        elif "t0" not in c or "t1" not in c:
            raise SystemExit(f"A caption carries neither `t0`/`t1` nor `seg`: {c.get('text', '')[:40]}")
        if c["t1"] <= c["t0"]:
            raise SystemExit(f"A caption ends before it starts ({c['t0']} → {c['t1']}): "
                             f"{c.get('text', '')[:40]}")
        out.append(c)
    return out


def says_of(segment):
    """A segment's `says`: what the narration names while THIS shot is on screen.

        {"src": "cathedral.jpg", "dur": 2.4, "says": "la catedral"}
        {"src": "market.mov", "dur": 3.0, "says": ["el mercado", "seis de la mañana"]}

    It is a promise the spec makes and `verify.py` collects: if the voice says "the cathedral"
    while a beach is on screen, nobody watching believes the video. The engine only records it;
    checking it needs the narration's word times, which is why it travels in the timeline.
    """
    says = segment["says"]
    says = [says] if isinstance(says, str) else list(says)
    out = [str(x).strip() for x in says if str(x).strip()]
    if not out:
        raise SystemExit("A segment carries an empty `says`: name what the voice says there, or drop it.")
    return out


def sync_captions(cfg, total):
    """Subtitles taken from the narration already generated, word by word.

        "sync": {"from": "common/voice/alignment.json", "style": "clean", "pos": "low", "size": 52}
        "sync": "common/voice/alignment.json"

    The file comes out of `transcribe.py --align`, which reads the WAVs the voices skill wrote and
    gives every word the second it is really pronounced on. Subtitles estimated by hand drift from
    the voice by half a second and the drift is invisible in a frame strip, which is why this path
    exists and why `verify.py` refuses more than 0.25 s of it.
    """
    if not cfg:
        return [], []
    if isinstance(cfg, str):
        cfg = {"from": cfg}
    cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}
    where = config.path(cfg.get("from") or "")
    if not where.exists():
        raise SystemExit(f"`sync` needs the alignment {where}.\nGenerate it with:  uv run "
                         f"\"{Path(__file__).resolve().parent / 'transcribe.py'}\" "
                         f"--align <voice folder> --script <voice-script.json>")
    data = json.loads(where.read_text(encoding="utf-8"))
    shift = float(cfg.get("shift", 0.0))
    out = []
    for c in data.get("captions", []):
        t0, t1 = float(c["t0"]) + shift, float(c["t1"]) + shift
        if t0 >= total:
            continue
        cap = {"t0": max(0.0, t0), "t1": min(total, t1), "text": c["text"], "source": "voice",
               "audio_t0": round(float(c.get("audio_t0", c["t0"])), 3),
               "audio_t1": round(float(c.get("audio_t1", c["t1"])), 3),
               "line": c.get("line"),
               "style": cfg.get("style", c.get("style", "clean")),
               "pos": cfg.get("pos", c.get("pos", "low")),
               "size": cfg.get("size", c.get("size", 52))}
        for k in ("color", "pop", "instant", "dx", "dy"):
            if k in cfg:
                cap[k] = cfg[k]
        if cap["t1"] > cap["t0"]:
            out.append(cap)
    if not out:
        raise SystemExit(f"{where} carries no caption inside the video's {total:.2f} s: "
                         f"is it the alignment of another variant?")
    words = [{"t0": round(float(w["t0"]) + shift, 3), "t1": round(float(w["t1"]) + shift, 3),
              "text": w["text"]}
             for line in data.get("lines", []) for w in line.get("words", [])]
    return out, words


# ------------------------------------------------------------ ducking under the narration

DUCK_DEFAULTS = {"db": -12.0, "ramp_s": 0.25, "lead_s": 0.15, "tail_s": 0.35}
_VOICE_HINTS = ("voice", "narration", "narracion", "narração", "narracao", "voz", "tts")


def track_role(a):
    """'voice' | 'sfx' | 'bed'. Explicit `role` wins; otherwise it reads the path.

    The voice contract (`voices` skill) writes l0.wav, l1.wav… inside a `voice/` folder, so a
    narration coming from the plugin is recognised with nothing added to the spec.
    """
    role = str(a.get("role", "")).strip().lower()
    if role in ("voice", "narration", "vo", "tts"):
        return "voice"
    if role in ("sfx", "fx", "effect", "hit"):
        return "sfx"
    if role:
        return "bed"
    src = str(a.get("src", "")).replace("\\", "/").lower()
    name = src.rsplit("/", 1)[-1]
    if re.fullmatch(r"l\d+\.wav", name) or any(h in src for h in _VOICE_HINTS):
        return "voice"
    if "/sfx/" in src:
        return "sfx"
    return "bed"


def duck_settings(value):
    """The spec's `duck`. `false` disables it; a dict overrides the defaults."""
    if value is False or value == 0:
        return None
    cfg = dict(DUCK_DEFAULTS)
    if isinstance(value, dict):
        cfg.update({k: v for k, v in value.items() if not k.startswith("_")})
    db = min(0.0, float(cfg["db"]))
    return {"db": db, "gain": 10 ** (db / 20), "ramp": max(0.02, float(cfg["ramp_s"])),
            "lead": max(0.0, float(cfg["lead_s"])), "tail": max(0.0, float(cfg["tail_s"]))}


def audio_duration(src):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=duration:format=duration",
                        "-select_streams", "a:0", "-of", "json", str(src)], capture_output=True, text=True)
    try:
        d = json.loads(r.stdout or "{}")
        for v in ([x.get("duration") for x in d.get("streams", [])] + [d.get("format", {}).get("duration")]):
            if v not in (None, "N/A"):
                return float(v)
    except Exception:
        pass
    return None


def voice_windows(tracks, cfg, total):
    """The stretches where somebody is speaking, with their margin, already merged."""
    raw = []
    for a in tracks:
        if track_role(a) != "voice":
            continue
        dur = a.get("dur")
        if dur is None:
            measured = audio_duration(config.path(a["src"]))
            dur = (measured - float(a.get("offset", 0))) if measured else None
        if not dur or float(dur) <= 0:
            print(f"  duck: I cannot measure {Path(str(a.get('src'))).name}; "
                  f"that line does not duck anything", flush=True)
            continue
        at = float(a.get("at", 0))
        raw.append([max(0.0, at - cfg["lead"]), min(total, at + float(dur) + cfg["tail"])])
    raw.sort()
    merged = []
    for w in raw:
        # Two lines closer than the two ramps: one single duck, or the bed pumps between sentences.
        if merged and w[0] - merged[-1][1] <= 2 * cfg["ramp"]:
            merged[-1][1] = max(merged[-1][1], w[1])
        else:
            merged.append(w)
    return [(round(a, 3), round(b, 3)) for a, b in merged if b > a]


def duck_shape(windows, ramp):
    """ffmpeg expression, 0 outside the windows and 1 inside, with linear ramps of `ramp` seconds."""
    return "+".join(f"clip(min((t-{a - ramp:.3f})/{ramp:.3f},({b + ramp:.3f}-t)/{ramp:.3f}),0,1)"
                    for a, b in windows)


def track_duck_gain(a, cfg):
    """The linear gain this track drops to while the voice is speaking, or None if it does not duck."""
    own = a.get("duck", True)
    if own is False or track_role(a) in ("voice", "sfx"):
        return None
    if isinstance(own, dict) and "db" in own:
        return 10 ** (min(0.0, float(own["db"])) / 20)
    if isinstance(own, (int, float)) and not isinstance(own, bool):
        return 10 ** (min(0.0, float(own)) / 20)
    return cfg["gain"]


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
    ap = argparse.ArgumentParser(description="Video engine: a JSON spec into an MP4")
    ap.add_argument("spec", help="JSON file with the spec")
    ap.add_argument("--out", help="overrides the spec's `out`")
    ap.add_argument("--format", help="overrides the spec's `format` (9x16 | 4x5 | 1x1 | 16x9)")
    args = ap.parse_args()

    with open(args.spec) as fh:
        spec = json.load(fh)
    fmt = set_format(args.format or spec.get("format") or config.FORMAT)
    fps = spec.get("fps", config.FPS)
    look = LOOKS[spec.get("look", "film")]
    vig = vignette(look["vig"])
    grain = min(spec.get("grain", 0.008), config.GRAIN_MAX)
    rng = np.random.default_rng(7)
    beat = 60 / spec["bpm"] if spec.get("bpm") else None

    # Segment timings on an absolute grid, so they don't accumulate drift against the beat
    t = spec.get("beat0", 0.0)
    cuts, starts = [], []
    for s in spec["segments"]:
        if "beats" in s and beat is None:
            raise SystemExit("A segment uses `beats` but the spec carries no `bpm`.")
        starts.append(t)
        t += s["beats"] * beat if "beats" in s else s["dur"]
        cuts.append(t)
    total = cuts[-1]

    # Subtitles of the clips' own audio: burned in ONLY where the spec asks for them, segment by
    # segment (`"subs"`). The rule for when they belong at all is in SKILL.md.
    # Text comes from one of three places, and every one of them is anchored to something real:
    # the spec's own captions (to a second or, with `seg`, to the cut), the narration already
    # generated (`sync`, word by word) and the clips' own audio (`subs`, per segment).
    captions = anchor_captions(spec.get("captions", []), starts, cuts)
    synced, voice_words = sync_captions(spec.get("sync"), total)
    captions += synced
    for s, g0, g1 in zip(spec["segments"], starts, cuts):
        captions += segment_subtitles(s, g0, g1)
    captions.sort(key=lambda c: c["t0"])
    pieces = prepare_captions(captions)

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
        route_map = effects.RouteMap(s["map"], font("bold", _scaled(54))) if "map" in s else None
        base = _segment_base(s, n, fps, src, focus)
        if base is not None and s.get("stutter"):
            k = int(s["stutter"])  # repeat each frame k times: the low-fps walking effect
            base = [base[(i // k) * k] for i in range(len(base))]
        if base is not None and s.get("freeze"):
            base = [base[0]] * n
        title = None
        if s.get("behind"):
            bh = s["behind"]
            size = _scaled(bh.get("size", 230))
            while True:  # shrink until it fits the width
                title = effects.render_title(bh["text"], font(bh.get("style", "bold"), size, bh["text"]),
                                             bh.get("color", [255, 255, 255]))
                if title.shape[1] <= W * 0.94 or size < 60:
                    break
                size = int(size * 0.93)
        cards = None
        if s.get("cutout"):
            cards = [effects.card(x, font("bold", _scaled(44), x)) for x in s["cutout"].get("lines", [])]
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

    # Automatic ducking: while a voice track is speaking, everything else (ambience, the clip's
    # diegetic sound, the music bed) drops `duck.db` with `duck.ramp_s` ramps and comes back up.
    # It is the engine's job, not each spec's: a narration mixed at the same level as the clip is
    # simply not understood, and that already shipped.
    duck = duck_settings(spec.get("duck", True))
    windows = voice_windows(spec.get("audio", []), duck, total) if duck else []
    shape = duck_shape(windows, duck["ramp"]) if windows else None
    if shape:
        print(f"  duck: {duck['db']:.0f} dB under the voice, {len(windows)} window(s), "
              f"ramps of {duck['ramp']:.2f} s", flush=True)

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
            # asetpts before the adelay: with `-ss` on the input the first pts is not always 0,
            # and the duck expression below reads the VIDEO's t, not the source's.
            chain = (f"[{k}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                     f"asetpts=PTS-STARTPTS,{trim}adelay={ms}|{ms},volume={a.get('gain', 1)}")
            g = track_duck_gain(a, duck) if shape else None
            if g is not None:
                chain += f",volume=volume='1+({g:.5f}-1)*({shape})':eval=frame"
            filters.append(chain + f"[a{k}]")
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

    # The timeline: what the render actually burned in and where every cut fell. `verify.py` reads
    # it to check the text against the voice (0.25 s) and against the cut, and to judge the ending.
    # Reconstructing this from the spec is not the same thing: `words`, `subs` and `sync` all expand
    # into pieces the spec never spelled out.
    speech = voice_windows(spec.get("audio", []), duck_settings({"lead_s": 0, "tail_s": 0}), total)
    timeline = {
        "schema": "render-timeline/1", "video": str(out), "format": fmt, "size": f"{W}x{H}",
        "fps": fps, "duration": round(total, 3),
        "loop": bool(spec.get("loop")),          # the video closes by returning to its first frame
        "fade_out": float(spec.get("fade_out", 0) or 0),
        "audio_fade_out": float(spec.get("audio_fade_out", 1.2) or 0),
        "shots": [dict({"i": i, "t0": round(t0, 3), "t1": round(t1, 3), "dur": round(t1 - t0, 3),
                        "src": Path(str(s.get("src", ""))).name or ("map" if "map" in s else "")},
                       **({"says": says_of(s)} if s.get("says") else {}))
                  for i, (s, t0, t1) in enumerate(zip(spec["segments"], starts, cuts))],
        "words": voice_words,
        "captions": [{k: (round(p[k], 3) if isinstance(p.get(k), float) else p.get(k))
                      for k in ("t0", "t1", "text", "pos", "source", "audio_t0", "audio_t1", "line")
                      if p.get(k) is not None}
                     for p in pieces],
        "voice": [list(w) for w in speech],
    }
    timeline_path = out.with_name(out.stem + ".timeline.json")
    timeline_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps({"out": str(out), "duration": round(total, 2),
                      "timeline": str(timeline_path),
                      "format": fmt, "size": f"{W}x{H}",
                      "duck": {"db": duck["db"], "windows": windows} if shape else None,
                      "preview": str(out.with_name(out.stem + "-preview.mp4")) if spec.get("preview_audio") else None},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
