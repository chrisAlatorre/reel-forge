# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["numpy<2.3", "opencv-python", "mediapipe==0.10.21"]
# ///
"""What is actually in the rectangle, measured — not what was happening when it was shot.

    uv run framecheck.py PHOTO.jpg
    uv run framecheck.py CLIP.MOV --from 9.6 --to 13.0      # samples the window
    uv run framecheck.py CLIP.MOV --from 9.6 --to 13.0 --json out.json
    uv run framecheck.py PHOTO.jpg --crop 9x16              # judge the crop, not the original

It prints JSON: the numbers, and a `findings` list naming what stands between the camera and the
thing the shot is about. A curator writes `description` from what was HAPPENING; this reads the
frame itself, which is the blind spot. The failure it exists for: a shot of a ship taken
from inside a boat, catalogued as "a ship passes the window", where the bottom third
is two strangers' heads, a window mullion cuts the frame in half and the glass is visibly dirty.
Nothing in `description` or in a 1-5 `quality` was wrong; nobody had looked at the rectangle.

WHAT IT MEASURES
----------------
  foreground_people   faces low and large in the frame: people who are not the subject, close to
                      the lens. Each one with its share of the frame height and where it sits.
  frame_lines         long straight edges crossing the picture: window mullions, bars, door jambs.
                      Counted separately for the ones that cut the frame near its middle.
  haze                veiling glare, the dark-channel measure. Dirty glass, a smeared lens and
                      real fog all raise it; so does a legitimately white sky, which is why this
                      one is reported and never decides on its own.
  contrast            standard deviation of the luma. Low contrast plus high haze is glass.
  clear_band          the tallest horizontal band with no face and no crossing line: how much of
                      the frame is actually free for the subject.

IT DOES NOT DECIDE. It reports. Framing is a judgement and a number that says "0.31 of the height
is taken by a stranger's head" is what that judgement should be made with — the same way the rest
of this plugin measures instead of asserting. `findings` is the shortlist worth arguing about.

THRESHOLDS
----------
Calibrated on real material, printed by `--calibrate` so they can be re-checked. They are
deliberately loose: this flags what deserves a second look, it does not throw material away.
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import cv2
import numpy as np

# Calibrated on real footage; see --calibrate to re-measure on yours.
FACE_LOW_Y = 0.55        # a face whose centre sits below this is "foreground", not "subject"
FACE_BIG = 0.12          # ...and taking this share of the frame height, it blocks
LINE_MIN = 0.45          # a straight edge this long (share of the frame side) is structure
LINE_MID = (0.25, 0.75)  # ...and crossing inside this band, it cuts the picture
HAZE_HIGH = 0.42         # dark channel above this: the frame is veiled
CONTRAST_LOW = 46.0      # luma std below this is flat
CLEAR_MIN = 0.55         # less free height than this and the subject has nowhere to be
BOTTOM_PEOPLE = 0.22     # share of the BOTTOM third that is people, seen from any angle


def to_bgr(path, at=None):
    """The frame AS THE ENGINE WILL SEE IT, which means going through ffmpeg.

    Not cv2.VideoCapture: a phone records 9:16 as a 16:9 stream plus a `rotation -90` display
    matrix, ffmpeg applies it and OpenCV does not. Reading with OpenCV handed this checker a
    landscape frame, so the 9:16 crop was the middle of the wrong picture and the segmenter
    found no people in a shot whose bottom third is two of them. Photos go through ffmpeg too,
    so EXIF orientation is handled the same way.
    """
    p = str(path)
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        dst = Path(d) / "frame.png"
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
        if at is not None:
            cmd += ["-ss", f"{at:.3f}"]
        # 1280 px tall is plenty: every measurement here is a SHARE of the frame (a third, a length
        # relative to the side), and running Hough and the segmenter on a 4K frame cost ~10 s a
        # shot for the same numbers. ffmpeg rotates before it scales, so the orientation holds.
        cmd += ["-i", p, "-frames:v", "1", "-vf", "scale=-2:'min(ih,1280)'", str(dst)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not dst.exists():
            where = "" if at is None else f" at {at:.2f} s"
            sys.exit(f"framecheck: I cannot read {p}{where}. {r.stderr.strip()[:200]}")
        img = cv2.imread(str(dst), cv2.IMREAD_COLOR)
    if img is None:
        sys.exit(f"framecheck: ffmpeg gave me a frame of {p} that I cannot decode")
    return img


def crop_to(img, ratio):
    """Centre crop to an aspect ratio, because a 16:9 source is judged on what will be SEEN."""
    if not ratio:
        return img
    w_r, h_r = (float(x) for x in ratio.lower().split("x"))
    h, w = img.shape[:2]
    want = w_r / h_r
    have = w / h
    if have > want:                       # too wide: trim the sides
        nw = int(round(h * want))
        x0 = (w - nw) // 2
        return img[:, x0:x0 + nw]
    nh = int(round(w / want))             # too tall: trim top and bottom
    y0 = (h - nh) // 2
    return img[y0:y0 + nh, :]


def people_band(img):
    """How much of each horizontal third is covered by PEOPLE, with the segmentation model.

    Face detection is not enough and that is the whole point: the shot that started this rule has
    two strangers with their BACKS to the lens, and no face detector sees the back of a head. The
    segmenter does, because it segments hair, body and clothes.

    Returns {"bottom", "middle", "top"}: the share of each third that is a person.
    """
    import mediapipe as mp
    seg = _segmenter()
    if seg is None:
        return None
    h, w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    f = min(1.0, 768 / max(h, w))
    small = np.ascontiguousarray(cv2.resize(rgb, (round(w * f), round(h * f)),
                                            interpolation=cv2.INTER_AREA))
    res = seg.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=small))
    background = np.squeeze(res.confidence_masks[0].numpy_view().astype(np.float32))
    person = np.clip(1.0 - background, 0.0, 1.0)
    person = (person > 0.55).astype(np.float32)
    n = person.shape[0]
    thirds = {"top": person[: n // 3], "middle": person[n // 3: 2 * n // 3],
              "bottom": person[2 * n // 3:]}
    return {k: round(float(v.mean()), 3) for k, v in thirds.items()}


_DET = []


def _detectors():
    if not _DET:
        import mediapipe as mp
        for model in (0, 1):
            _DET.append(mp.solutions.face_detection.FaceDetection(
                model_selection=model, min_detection_confidence=0.45))
    return _DET


_SEG = []      # built ONCE per process: doing it per frame cost more than the measuring itself,
               # and one video window is five frames


def _segmenter():
    if _SEG:
        return _SEG[0]
    model = _seg_model()
    if model is None:
        _SEG.append(None)
        return None
    from mediapipe.tasks.python import BaseOptions, vision
    op = vision.ImageSegmenterOptions(
        base_options=BaseOptions(model_asset_path=str(model), delegate=BaseOptions.Delegate.CPU),
        running_mode=vision.RunningMode.IMAGE, output_confidence_masks=True)
    _SEG.append(vision.ImageSegmenter.create_from_options(op))
    return _SEG[0]


def _seg_model():
    """The selfie-multiclass model the engine already downloads, wherever it keeps it."""
    env = os.environ.get("REEL_FORGE_MODELS")
    roots = [Path(env)] if env else []
    cache = os.environ.get("REEL_FORGE_CACHE")
    if cache:
        roots.append(Path(cache) / "models")
    roots += [Path.home() / ".cache/reel-forge/models",
              Path(__file__).resolve().parents[2] / "video-engine" / "models"]
    for r in roots:
        f = r / "selfie_multiclass.tflite"
        if f.exists():
            return f
    return None


def faces(img):
    """[(cy, h_share)] of every face, from MediaPipe's short- and long-range detectors."""
    h, w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    out = {}
    for det in _detectors():              # 0: close to the lens. 1: far. The blocker is a 0.
        r = det.process(rgb)
        for d in (r.detections or []):
            b = d.location_data.relative_bounding_box
            cy = float(b.ymin + b.height / 2)
            cx = float(b.xmin + b.width / 2)
            key = (round(cx, 2), round(cy, 2))
            out[key] = max(out.get(key, 0.0), float(b.height))
    return sorted(((cy, hs) for (cx, cy), hs in out.items()), key=lambda t: -t[1])


def straight_lines(img):
    """Long straight edges, split into the ones that cut the picture and the rest."""
    h, w = img.shape[:2]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g, (5, 5), 0)
    edges = cv2.Canny(g, 45, 130, apertureSize=3)
    segs = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=90,
                           minLineLength=int(min(h, w) * LINE_MIN), maxLineGap=14)
    crossing, total = [], 0
    for x1, y1, x2, y2 in (segs[:, 0] if segs is not None else []):
        ang = abs(math.degrees(math.atan2(y2 - y1, x2 - x1))) % 180
        horiz = ang < 12 or ang > 168
        vert = 78 < ang < 102
        if not (horiz or vert):
            continue
        length = math.hypot(x2 - x1, y2 - y1)
        if length < (w if horiz else h) * LINE_MIN:
            continue
        total += 1
        pos = ((y1 + y2) / 2 / h) if horiz else ((x1 + x2) / 2 / w)
        if LINE_MID[0] <= pos <= LINE_MID[1]:
            crossing.append({"axis": "h" if horiz else "v", "at": round(float(pos), 3),
                             "len": round(float(length) / (w if horiz else h), 3)})
    crossing.sort(key=lambda c: -c["len"])
    return total, crossing[:6]


def haze(img):
    """Dark-channel prior: min over the channels, then a local minimum. High = veiled."""
    small = cv2.resize(img, (0, 0), fx=0.35, fy=0.35, interpolation=cv2.INTER_AREA)
    dark = small.min(axis=2)
    k = max(3, int(min(small.shape[:2]) * 0.06) | 1)
    dark = cv2.erode(dark, np.ones((k, k), np.uint8))
    return float(dark.mean() / 255.0)


def clear_band(img, blocking_faces, crossing):
    """Tallest horizontal band with nothing BLOCKING in it, as a share of the height.

    Only blocking faces count, not every face in the picture. Counting them all made a couple of
    distant tourists in a plaza read as "the subject has nowhere to be", which is how a check
    starts crying wolf and stops being read.
    """
    h = img.shape[0]
    blocked = []
    for f in blocking_faces:
        cy, hs = f["cy"], f["height_share"]
        blocked.append((max(0.0, cy - hs / 2), min(1.0, cy + hs / 2)))
    for c in crossing:
        if c["axis"] == "h":
            blocked.append((max(0.0, c["at"] - 0.012), min(1.0, c["at"] + 0.012)))
    blocked.sort()
    best, cursor = 0.0, 0.0
    for a, b in blocked:
        best = max(best, a - cursor)
        cursor = max(cursor, b)
    return round(max(best, 1.0 - cursor), 3)


def measure(img):
    f = faces(img)
    n_lines, crossing = straight_lines(img)
    hz = haze(img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    band = people_band(img)
    return {
        "faces": [{"cy": round(cy, 3), "height_share": round(hs, 3)} for cy, hs in f],
        "people_by_third": band,
        "foreground_people": [{"cy": round(cy, 3), "height_share": round(hs, 3)}
                              for cy, hs in f if cy >= FACE_LOW_Y and hs >= FACE_BIG],
        "long_lines": n_lines,
        "crossing_lines": crossing,
        "haze": round(hz, 3),
        "contrast": round(float(gray.std()), 1),
        "clear_band": clear_band(img, [{"cy": cy, "height_share": hs} for cy, hs in f
                                       if cy >= FACE_LOW_Y and hs >= FACE_BIG], crossing),
    }


def findings(m):
    out = []
    band = m.get("people_by_third") or {}
    if blocking_people(m):
        out.append(f"the bottom third is {band['bottom']:.2f} people with their backs to the lens "
                   f"(no face facing the camera there), and the middle only {band.get('middle', 0):.2f}: "
                   f"bystanders between the camera and what the shot is about.")
    for c in m["crossing_lines"][:2]:
        side = "horizontal" if c["axis"] == "h" else "vertical"
        out.append(f"a {side} edge cuts the picture at {c['at']:.2f} and runs {c['len']:.2f} of the "
                   f"frame: a window mullion, a bar or a door jamb between camera and subject.")
    # Haze NEVER speaks on its own. Measured across real material it does not separate dirty
    # glass from genuine weather: a misty seascape scores 0.47 and the dirty boat window 0.39.
    # It only means something once something else says there IS glass — an edge cutting the
    # frame, or bodies right under the lens. Then it says how bad that glass is.
    enclosed = bool(m["crossing_lines"]) or blocking_people(m)
    if enclosed and m["haze"] >= HAZE_HIGH and m["contrast"] <= CONTRAST_LOW:
        out.append(f"and the glass it is shot through is dirty or fogged: haze {m['haze']:.2f} with "
                   f"contrast {m['contrast']:.0f} behind that edge.")
    # One centred edge splits the frame in two halves by definition, so clear_band ~0.5 adds
    # nothing to "there is an edge" — and saying it anyway turns a useful measurement into noise.
    # It only speaks when something else is there: blocking bodies, or more than one edge.
    if m["clear_band"] < CLEAR_MIN and (blocking_people(m) or len(m["crossing_lines"]) > 1):
        out.append(f"only {m['clear_band']:.2f} of the height is free: between the blocking bodies "
                   f"and the edges, the subject has nowhere to be.")
    if m["crossing_lines"] and blocking_people(m):
        out.append("shot from inside something, past people: the classic 'through the window of a "
                   "vehicle' frame. It almost never survives a 9:16 crop.")
    return out


def worst(samples):
    """The sample that deserves the second look: most findings, then least clear band."""
    return max(samples, key=lambda s: (len(s["findings"]), -s["clear_band"]))


def blocking_people(m):
    """Bodies in the bottom third that are NOT facing the lens.

    That is the whole distinction, and it came from a false alarm: a selfie with a friend puts two
    large faces low in the frame, and the first version called them "someone blocking the shot".
    They ARE the shot. What blocks a shot is people with their backs or sides to the camera — the
    segmenter sees their body, the face detector sees no face — which is exactly what the boat
    window had: 0.50 of the bottom third people, and not one face.
    """
    band = m.get("people_by_third") or {}
    if not (band.get("bottom", 0) >= BOTTOM_PEOPLE and band.get("middle", 0) < band["bottom"] / 2):
        return False
    facing = [f for f in m.get("faces", []) if f["cy"] >= FACE_LOW_Y - 0.1]
    return not facing


def obstructions_of(m):
    """The catalog's `obstructions` vocabulary, from the numbers (never from the prose)."""
    people = blocking_people(m)
    out = []
    if people:
        out.append("foreground_people")
    if m["crossing_lines"]:
        out.append("frame")
    if (people or m["crossing_lines"]) and m["haze"] >= HAZE_HIGH and m["contrast"] <= CONTRAST_LOW:
        out += ["glass", "dirt"]
    elif people and m["crossing_lines"]:
        out.append("glass")
    return out


def check_one(source, t0=None, t1=None, samples=5, ratio="9x16"):
    """One photo, or one window of one video. Returns the report for that source."""
    if t0 is None:
        times = [None]
    else:
        t1 = t0 if t1 is None else t1
        n = max(1, samples)
        times = [t0] if n == 1 or t1 <= t0 else [t0 + (t1 - t0) * i / (n - 1) for i in range(n)]
    got, size = [], None
    for t in times:
        img = crop_to(to_bgr(source, t), ratio)
        size = size or f"{img.shape[1]}x{img.shape[0]}"
        m = measure(img)
        m["at_s"] = None if t is None else round(t, 3)
        m["findings"] = findings(m)
        m["obstructions"] = obstructions_of(m)
        got.append(m)
    w = worst(got)
    return {"source": str(source), "crop": ratio or "original", "size": size, "samples": got,
            "verdict": {"at_s": w["at_s"], "findings": w["findings"], "clean": not w["findings"],
                        "obstructions": w["obstructions"]}}


# --------------------------------------------------------------------------- catalog mode

def _items(doc):
    return doc["items"] if isinstance(doc, dict) and "items" in doc else doc


def _resolve(root: Path, rel: str) -> Path:
    p = Path(os.path.expanduser(rel))
    return p if p.is_absolute() else root / p


def check_catalog(catalog: Path, root: Path, samples: int, ratio, apply: bool, only=None):
    """Every usable photo and video window in a catalog, in ONE process, so the models load once.

    With `apply`, the moments with bodies near the lens and their backs to it get a note in the
    catalog ("framecheck, needs a look"), which is what the directors and the critic read. It never
    changes `quality` or `obstructions`: measured on a real catalog, most of those flags were people
    who ARE the shot. Everything else it saw is in the sidecar.
    """
    doc = json.loads(catalog.read_text(encoding="utf-8"))
    items = _items(doc)
    report, changed = {}, 0
    todo = [it for it in items if it.get("use", True) is not False
            and it.get("type") in ("photo", "video", "live") and (not only or it["id"] in only)]
    for k, it in enumerate(todo, 1):
        src = _resolve(root, it["path"])
        if not src.exists():
            report[it["id"]] = {"error": f"not on disk: {it['path']}"}
            continue
        try:
            if it["type"] == "video":
                r = check_one(src, float(it.get("start_s", 0)), float(it.get("end_s", 0)),
                              samples, ratio)
            else:
                r = check_one(src, None, None, 1, ratio)
        except SystemExit as e:           # one unreadable file does not stop the batch
            report[it["id"]] = {"error": str(e)}
            continue
        v = r["verdict"]
        report[it["id"]] = {"clean": v["clean"], "obstructions": v["obstructions"],
                            "findings": v["findings"], "at_s": v["at_s"]}
        print(f"  [{k}/{len(todo)}] {it['id']:<18} "
              f"{'clean' if v['clean'] else ', '.join(v['obstructions']) or 'look at it'}",
              file=sys.stderr, flush=True)
        if apply and "foreground_people" in v["obstructions"]:
            # Annotate, never demote. On the first full catalog this ran over (296 moments), 7 got
            # flagged and about 2 were real — tourists in front of a temple, pedestrians in front of
            # a tram. The rest were a night market, a concert crowd and the subject's own legs in a
            # POV: people who ARE the shot. Pixels cannot tell which, so the tool leaves a note the
            # directors and the critic read, and the curator decides `obstructions` and `quality`.
            note = ("framecheck, needs a look: " + "; ".join(f[:140] for f in v["findings"][:2])
                    + (f" (at {v['at_s']} s)" if v.get("at_s") is not None else ""))
            if "framecheck, needs a look" not in (it.get("notes") or ""):
                it["notes"] = ((it.get("notes") or "").rstrip() + " | " + note).strip(" |")
                changed += 1
    if apply and changed:
        tmp = catalog.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(catalog)
    return report, changed


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="*", help="photos or videos; several at once share the models")
    ap.add_argument("--from", dest="t0", type=float, help="video: start of the window, in seconds")
    ap.add_argument("--to", dest="t1", type=float, help="video: end of the window, in seconds")
    ap.add_argument("--samples", type=int, default=None,
                    help="frames to read inside a video window (default 5; 3 in catalog mode)")
    ap.add_argument("--crop", default="9x16", help="aspect to judge ('9x16', or 'none' for the original")
    ap.add_argument("--catalog", help="check every usable item of a catalog JSON in one process")
    ap.add_argument("--root", help="catalog mode: the folder item paths are relative to "
                                   "(default: the project, two levels above workspace/catalog/)")
    ap.add_argument("--apply", action="store_true",
                    help="catalog mode: leave a 'needs a look' note on moments with bystanders "
                         "near the lens (never changes quality)")
    ap.add_argument("--ids", help="catalog mode: only these ids, comma-separated")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args()
    ratio = None if a.crop.lower() in ("none", "off", "") else a.crop

    if a.catalog:
        cat = Path(a.catalog).expanduser().resolve()
        root = Path(a.root).expanduser().resolve() if a.root else (
            cat.parents[2] if cat.parent.name == "catalog" and cat.parents[1].name == "workspace"
            else cat.parent)
        only = set(a.ids.split(",")) if a.ids else None
        report, changed = check_catalog(cat, root, a.samples or 3, ratio, a.apply, only)
        side = Path(a.json_out) if a.json_out else cat.with_name(cat.stem + ".framecheck.json")
        side.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        flagged = {k: v for k, v in report.items() if v.get("obstructions")}
        print(json.dumps({"catalog": str(cat), "checked": len(report), "flagged": len(flagged),
                          "annotated": changed, "sidecar": str(side),
                          "flagged_ids": {k: v["obstructions"] for k, v in flagged.items()}},
                         ensure_ascii=False, indent=1))
        return

    if not a.sources:
        ap.error("give one or more sources, or --catalog")
    if len(a.sources) == 1:
        out = check_one(a.sources[0], a.t0, a.t1, a.samples or 5, ratio)
    else:
        out = [check_one(src, a.t0, a.t1, a.samples or 5, ratio) for src in a.sources]
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if a.json_out:
        Path(a.json_out).write_text(text, encoding="utf-8")
    print(text)
    # exit 0 always: this reports, it does not gate. The curator decides.


if __name__ == "__main__":
    os.environ.setdefault("GLOG_minloglevel", "2")
    main()
