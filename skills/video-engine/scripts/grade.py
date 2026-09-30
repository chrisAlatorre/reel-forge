# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["numpy<2.3", "opencv-python-headless<5", "pillow", "pillow-heif"]
# ///
"""Colour grades by scene: the look a colourist would give THIS shot, chosen by looking at it.

    uv run grade.py classify photo.jpg [more.jpg …]          # which grade each one gets, and why
    uv run grade.py demo photo.jpg [more …] --out sheet.jpg   # before / after, side by side
    uv run grade.py apply photo.jpg --grade autumn-moody --out graded.jpg
    uv run grade.py list

Why. One flat `look` over a whole video (film, teal or clean) treats a snowy peak, a neon street
and a plate of food the same. The user pointed at a travel reel — an autumn road, snow on the peaks,
low clouds — and asked for that kind of colour: "guidelines of filters depending on the landscape or
the shot". So a grade is picked per shot from what the frame IS: foliage, forest, water, snow, sky,
night, neon, golden light, an interior. Every grade is built from the same few controls a colourist
uses (per-hue HSL, a contrast curve, lifted or crushed blacks, split toning, warmth, vibrance), and
all of them share one finishing so a video that moves from forest to city still reads as one film.

How it plugs into the engine: a segment's `grade` ("auto", a grade name, or "none"), or the spec's
`grade` for every shot; `grade_strength` (0-1, default 0.85) blends it with the untouched frame.
Photos are graded once per shot, video frame by frame. Skin (orange hues at mid saturation) is
protected from the strongest hue moves so faces don't turn pumpkin.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

# Hue centres in degrees (OpenCV HLS hue is 0-179, i.e. degrees / 2).
HUES = {"red": 0, "orange": 28, "yellow": 52, "green": 110, "aqua": 175, "blue": 215,
        "purple": 270, "magenta": 320}

# Each grade: per-hue {hue shift in degrees, saturation ×, lightness +/-}, a contrast amount
# (S-curve, -1..1), black lift and white roll (0-255), warmth (+ warm / - cool), split toning
# (shadow and highlight tint as RGB, with amounts), overall saturation and vibrance.
GRADES = {
    # The reference: an autumn road under low clouds, snow on the peaks. Oranges and golds glow,
    # greens drop to olive so they stop competing, blues and clouds go slate, shadows deep and a
    # touch teal, highlights warm.
    "autumn-moody": {
        "hsl": {"red": (4, 1.10, -4), "orange": (-2, 1.28, 2), "yellow": (-10, 1.15, -2),
                "green": (-18, 0.62, -10), "aqua": (8, 0.60, -6), "blue": (-6, 0.55, -8)},
        "contrast": 0.30, "lift": 6, "roll": 10, "warmth": 4, "sat": 1.0, "vibrance": 0.10,
        "split": {"shadows": (40, 70, 70), "sh_amt": 0.10, "highs": (255, 205, 150), "hi_amt": 0.08},
        "why": "autumn foliage: warm oranges glow, greens to olive, slate skies, deep shadows"},
    # Green woods, jungle, rice terraces: rich, deep greens without the neon.
    "forest-deep": {
        "hsl": {"yellow": (-6, 0.9, -4), "green": (8, 0.88, -8), "aqua": (6, 0.8, -6),
                "blue": (-4, 0.8, -4), "orange": (0, 1.05, 2)},
        "contrast": 0.24, "lift": 8, "roll": 8, "warmth": -2, "sat": 1.0, "vibrance": 0.08,
        "split": {"shadows": (30, 70, 60), "sh_amt": 0.12, "highs": (255, 235, 200), "hi_amt": 0.05},
        "why": "foliage in green: deep emerald, cool shadows"},
    # Low sun: honey highlights, soft contrast, skin that glows.
    "golden-hour": {
        "hsl": {"orange": (0, 1.12, 3), "yellow": (-4, 1.1, 2), "blue": (-8, 0.8, -4),
                "green": (-10, 0.85, -2)},
        "contrast": 0.14, "lift": 10, "roll": 12, "warmth": 10, "sat": 1.02, "vibrance": 0.10,
        "split": {"shadows": (60, 50, 80), "sh_amt": 0.06, "highs": (255, 200, 130), "hi_amt": 0.12},
        "why": "warm low light: honey highlights, soft contrast"},
    # Blue hour and night streets: teal shadows, warm practicals, clean blacks.
    "night-city": {
        "hsl": {"orange": (0, 1.15, 4), "yellow": (-6, 1.05, 0), "blue": (-6, 1.1, -2),
                "aqua": (-10, 1.1, 0), "green": (40, 0.6, -6)},
        "contrast": 0.22, "lift": 1, "roll": 6, "warmth": -4, "sat": 1.05, "vibrance": 0.12,
        "split": {"shadows": (10, 40, 60), "sh_amt": 0.10, "highs": (255, 190, 120), "hi_amt": 0.06},
        "why": "night or blue hour: teal shadows, warm lights"},
    # Neon: signs, casinos, LED towers. Saturated but controlled, magenta and cyan split.
    "neon-night": {
        "hsl": {"magenta": (-6, 1.15, 0), "purple": (-6, 1.1, 0), "aqua": (0, 1.15, 0),
                "green": (30, 0.7, -8), "orange": (0, 1.05, 0)},
        "contrast": 0.28, "lift": 2, "roll": 6, "warmth": -2, "sat": 1.06, "vibrance": 0.10,
        "split": {"shadows": (40, 20, 80), "sh_amt": 0.14, "highs": (255, 220, 240), "hi_amt": 0.04},
        "why": "neon at night: controlled magenta and cyan, crushed blacks"},
    # Sea, rivers, pools, beaches: turquoise water, warm sand and skin.
    "tropical-water": {
        "hsl": {"aqua": (-6, 1.2, 2), "blue": (-10, 1.1, 0), "green": (20, 0.85, 0),
                "orange": (0, 1.08, 2), "yellow": (-4, 1.0, 2)},
        "contrast": 0.16, "lift": 6, "roll": 8, "warmth": 3, "sat": 1.03, "vibrance": 0.12,
        "split": {"shadows": (20, 80, 90), "sh_amt": 0.08, "highs": (255, 235, 205), "hi_amt": 0.05},
        "why": "water: turquoise, warm skin and sand"},
    # Snow and bright alpine light: clean cool whites, blue shadows, no grey mush.
    "alpine-snow": {
        "hsl": {"blue": (-4, 1.05, -4), "aqua": (0, 0.9, 0), "orange": (0, 1.05, 0),
                "green": (-6, 0.8, -6)},
        "contrast": 0.20, "lift": 4, "roll": 4, "warmth": -5, "sat": 0.98, "vibrance": 0.06,
        "split": {"shadows": (40, 70, 120), "sh_amt": 0.12, "highs": (240, 245, 255), "hi_amt": 0.05},
        "why": "snow and bright high light: cool whites, blue shadows"},
    # Overcast, rain, fog: filmic and muted, never grey mush — shape comes from contrast.
    "overcast-film": {
        "hsl": {"orange": (0, 1.12, 2), "yellow": (-6, 0.95, 0), "green": (-8, 0.75, -6),
                "blue": (-4, 0.7, -4), "aqua": (0, 0.75, -4)},
        "contrast": 0.26, "lift": 12, "roll": 10, "warmth": 2, "sat": 0.94, "vibrance": 0.06,
        "split": {"shadows": (50, 70, 80), "sh_amt": 0.10, "highs": (250, 230, 205), "hi_amt": 0.06},
        "why": "overcast or flat light: filmic, muted, shaped by contrast"},
    # City by day: clean, crisp, a restrained teal-orange.
    "urban-clean": {
        "hsl": {"orange": (0, 1.06, 2), "blue": (-4, 0.95, -2), "aqua": (-4, 0.95, 0),
                "green": (-4, 0.9, -2)},
        "contrast": 0.18, "lift": 5, "roll": 6, "warmth": 1, "sat": 1.0, "vibrance": 0.08,
        "split": {"shadows": (40, 70, 85), "sh_amt": 0.08, "highs": (255, 230, 200), "hi_amt": 0.05},
        "why": "city by day: clean and crisp, gentle teal-orange"},
    # Food: appetite colours, never oversaturated.
    "food-warm": {
        "hsl": {"red": (0, 1.12, 0), "orange": (0, 1.12, 2), "yellow": (-2, 1.1, 2),
                "green": (0, 1.05, 0), "blue": (0, 0.8, 0)},
        "contrast": 0.16, "lift": 4, "roll": 8, "warmth": 5, "sat": 1.04, "vibrance": 0.10,
        "split": {"shadows": (60, 45, 40), "sh_amt": 0.05, "highs": (255, 225, 190), "hi_amt": 0.06},
        "why": "food: warm appetite colours"},
    # Interiors under warm bulbs: tame the orange cast, keep it cosy.
    "interior-warm": {
        "hsl": {"orange": (2, 0.95, 0), "yellow": (-4, 0.9, 0), "blue": (0, 0.9, 0)},
        "contrast": 0.14, "lift": 8, "roll": 10, "warmth": -3, "sat": 0.98, "vibrance": 0.06,
        "split": {"shadows": (40, 50, 70), "sh_amt": 0.08, "highs": (255, 230, 205), "hi_amt": 0.04},
        "why": "indoor warm light: cosy, the orange cast tamed"},
}

_SKIN = (5, 25)        # OpenCV hue units (10°-50°): where faces live
_CACHE = {}


def _hue_luts(p):
    """Three 180-entry tables (hue shift, sat ×, lightness +) blended smoothly between hue centres."""
    shift, sat, lum = np.zeros(180, np.float32), np.ones(180, np.float32), np.zeros(180, np.float32)
    hues = np.arange(180) * 2.0
    for name, (dh, ds, dl) in (p.get("hsl") or {}).items():
        c = HUES[name]
        d = np.minimum(np.abs(hues - c), 360 - np.abs(hues - c))
        w = np.clip(1 - d / 38.0, 0, 1) ** 1.5                  # ±38° soft band
        shift += w * dh
        sat *= 1 + w * (ds - 1)
        lum += w * dl
    return shift / 2.0, sat, lum                              # shift back to OpenCV hue units


def _curve(p):
    x = np.arange(256, dtype=np.float32) / 255
    k = p.get("contrast", 0)
    y = x + k * (x - 0.5) * (1 - np.abs(2 * x - 1)) * 1.6     # S around mid grey
    y = p.get("lift", 0) / 255 + y * (1 - (p.get("lift", 0) + p.get("roll", 0)) / 255)
    return np.clip(y * 255, 0, 255).astype(np.uint8)


def _prepare(name):
    if name not in _CACHE:
        p = GRADES[name]
        _CACHE[name] = (p, _hue_luts(p), _curve(p))
    return _CACHE[name]


def apply(img: np.ndarray, name: str, strength: float = 0.85) -> np.ndarray:
    """RGB uint8 in, RGB uint8 out. `strength` blends with the untouched frame."""
    if not name or name == "none" or name not in GRADES or strength <= 0:
        return img
    p, (shift, satm, lumd), curve = _prepare(name)
    hls = cv2.cvtColor(img, cv2.COLOR_RGB2HLS).astype(np.float32)
    h = hls[..., 0].astype(np.int32) % 180
    s = hls[..., 2] / 255
    # skin guard: mid-saturation orange keeps most of its colour
    skin = ((h >= _SKIN[0]) & (h <= _SKIN[1]) & (s > 0.15) & (s < 0.6)).astype(np.float32) * 0.6
    hls[..., 0] = (hls[..., 0] + shift[h] * (1 - skin)) % 180
    vib = p.get("vibrance", 0) * (1 - s)                      # vibrance: more on the dull colours
    hls[..., 2] = np.clip(hls[..., 2] * (1 + (satm[h] - 1) * (1 - skin)) * (p.get("sat", 1) + vib), 0, 255)
    hls[..., 1] = np.clip(hls[..., 1] + lumd[h] * (1 - skin), 0, 255)
    out = cv2.cvtColor(hls.astype(np.uint8), cv2.COLOR_HLS2RGB)
    out = cv2.LUT(out, np.dstack([curve] * 3)).astype(np.float32)
    lum = out.mean(axis=2, keepdims=True) / 255
    sp = p.get("split") or {}
    if sp:
        sh = np.array(sp["shadows"], np.float32)
        hi = np.array(sp["highs"], np.float32)
        out = out + (sh - out) * (1 - lum) ** 2 * sp.get("sh_amt", 0) \
                  + (hi - out) * lum ** 2 * sp.get("hi_amt", 0)
    w = p.get("warmth", 0)
    if w:
        out[..., 0] += w
        out[..., 2] -= w
    out = np.clip(out, 0, 255)
    if strength < 1:
        out = img.astype(np.float32) + (out - img) * strength
    return out.astype(np.uint8)


def cube(name: str, strength: float = 0.85, size: int = 65) -> Path:
    """The grade as a 3D LUT (.cube) for ffmpeg's lut3d, cached. Video is graded while it decodes
    (in C, threaded): grading it frame by frame in numpy added ~3 s per second of footage."""
    import os
    d = Path(os.path.expanduser(os.environ.get("REEL_FORGE_CACHE", "~/.cache/reel-forge"))) / "grades"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{name}-{int(round(strength * 100))}-{size}.cube"
    if out.exists():
        return out
    g = np.linspace(0, 255, size).round().astype(np.uint8)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")           # .cube order: red varies fastest
    grid = np.stack([r, gg, b], axis=-1).reshape(1, -1, 3)
    graded = apply(grid, name, strength).reshape(-1, 3) / 255.0
    lines = [f'TITLE "reel-forge {name}"', f"LUT_3D_SIZE {size}"]
    lines += [f"{x:.5f} {y:.5f} {z:.5f}" for x, y, z in graded]
    tmp = out.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(out)
    return out


def features(img: np.ndarray) -> dict:
    """What the frame is made of, on a small copy: shares of hue families, light, sky."""
    small = cv2.resize(img, (120, int(120 * img.shape[0] / img.shape[1])), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0] * 2.0, hsv[..., 1] / 255.0, hsv[..., 2] / 255.0
    col = s > 0.28
    top = slice(0, small.shape[0] // 3)

    def share(lo, hi, mask=None, min_s=0.28):
        m = (s > min_s) & (h >= lo) & (h < hi) & (v > 0.10)
        return float((m if mask is None else m & mask).mean())

    low = slice(small.shape[0] // 3, None)          # snow is on the ground, not a white sky
    bright_low_sat = (s[low] < 0.12) & (v[low] > 0.78)
    f = {
        "luma": float(v.mean()), "sat": float(s.mean()),
        "autumn": share(14, 48, min_s=0.45), "green": share(70, 160, min_s=0.2), "water": share(165, 200),
        "blue": share(200, 250), "neon": float(((s > 0.6) & (v > 0.55) & ((h > 270) | (h < 10) | ((h > 160) & (h < 200)))).mean()),
        "snow": float(bright_low_sat.mean()),
        "sky_grey": float(((s[top] < 0.14) & (v[top] > 0.55)).mean()),
        "sky_blue": float((col[top] & (h[top] > 190) & (h[top] < 240)).mean()),
        "dark": float((v < 0.22).mean()), "points": float(((v > 0.92) & (s > 0.2)).mean()),
        "warm_cast": float((small[..., 0].astype(np.float32) - small[..., 2]).mean() / 255),
    }
    return {k: round(x, 3) for k, x in f.items()}


def classify(img: np.ndarray, tags=()) -> tuple[str, dict, str]:
    """(grade, features, reason). Catalog tags win where the pixels cannot tell (food, interior)."""
    f = features(img)
    tags = {t.lower() for t in tags}
    if "food" in tags:
        return "food-warm", f, "tagged food"
    night = f["luma"] < 0.30 and f["dark"] > 0.35
    if night and f["neon"] > 0.02:
        return "neon-night", f, "dark frame with saturated neon"
    if night:
        return "night-city", f, "dark frame: night or blue hour"
    if f["snow"] > 0.18 and f["luma"] > 0.55:
        return "alpine-snow", f, "large bright colourless areas: snow or bright white stone"
    # the dominant colour family decides first, when it covers a real part of the frame
    fam = {"autumn-moody": f["autumn"], "forest-deep": f["green"], "tropical-water": f["water"]}
    if "water" in tags:
        fam["tropical-water"] += 0.05
    best = max(fam, key=fam.get)
    floor = {"autumn-moody": 0.15, "forest-deep": 0.10, "tropical-water": 0.10}
    if fam[best] >= floor[best] and f["luma"] > 0.25:
        why = {"autumn-moody": "saturated warm foliage dominates", "forest-deep": "green foliage dominates",
               "tropical-water": "turquoise water dominates"}[best]
        return best, f, why
    if f["warm_cast"] > 0.10 and f["luma"] > 0.35 and f["sky_blue"] < 0.2:
        if "interior" in tags or f["sky_grey"] < 0.05 and f["sky_blue"] < 0.02 and f["luma"] < 0.5:
            return "interior-warm", f, "warm cast with no sky: an interior"
        return "golden-hour", f, "warm light across the frame"
    if f["sky_grey"] > 0.35:
        return "overcast-film", f, "a grey sky: overcast"
    return "urban-clean", f, "daylight, nothing dominant"


def load(path):
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    return np.asarray(ImageOps.exif_transpose(Image.open(path)).convert("RGB"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("classify"); c.add_argument("images", nargs="+"); c.add_argument("--tags", default="")
    d = sub.add_parser("demo"); d.add_argument("images", nargs="+"); d.add_argument("--out", required=True)
    d.add_argument("--strength", type=float, default=0.85)
    a = sub.add_parser("apply"); a.add_argument("image"); a.add_argument("--grade", default="auto")
    a.add_argument("--strength", type=float, default=0.85); a.add_argument("--out", required=True)
    sub.add_parser("list")
    args = ap.parse_args()
    if args.cmd == "list":
        for k, p in GRADES.items():
            print(f"{k:<16} {p['why']}")
        return
    if args.cmd == "classify":
        for im in args.images:
            g, f, why = classify(load(im), [t for t in args.tags.split(",") if t])
            print(json.dumps({"image": im, "grade": g, "why": why, "features": f}, ensure_ascii=False))
        return
    if args.cmd == "apply":
        img = load(args.image)
        g = classify(img)[0] if args.grade == "auto" else args.grade
        cv2.imwrite(args.out, cv2.cvtColor(apply(img, g, args.strength), cv2.COLOR_RGB2BGR))
        print(g)
        return
    rows = []
    for im in args.images:
        img = load(im)
        g, _, _ = classify(img)
        tw = 360
        th = int(tw * img.shape[0] / img.shape[1])
        a0 = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
        a1 = apply(a0, g, args.strength)
        row = np.hstack([a0, np.full((th, 8, 3), 255, np.uint8), a1])
        cv2.putText(row, g, (tw + 18, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        rows.append(row)
    wmax = max(r.shape[1] for r in rows)
    rows = [np.pad(r, ((0, 8), (0, wmax - r.shape[1]), (0, 0)), constant_values=255) for r in rows]
    cv2.imwrite(args.out, cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR))
    print(args.out)


if __name__ == "__main__":
    sys.exit(main())
