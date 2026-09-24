# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "pillow-heif", "opencv-contrib-python<5", "numpy<2.3"]
# ///
"""Contact sheets, face crops and frame strips: the images the agents LOOK at.

The plugin's rule is that nobody catalogs by file name. This script produces the images an
agent opens with `Read` to genuinely decide what works.

    uv run sheets.py contact list.json --cols 6 --out workspace/sheets/day-03
    uv run sheets.py faces   list.json --out workspace/sheets/faces-day-03
    uv run sheets.py strip   clip.mp4 --fps 1 --cols 8 --out workspace/sheets/

`list.json` accepts three shapes, and you can also pass loose paths on the command line:

    ["~/Pictures/trip/IMG_0001.HEIC", "~/Pictures/trip/IMG_0002.HEIC"]
    [{"id": "p-001", "path": "~/Pictures/trip/IMG_0001.HEIC"}, ...]
    {"items": [{"id": "p-001", "path": "...", "thumbnail": "..."}]}   # inventory.py's output

If an item carries a `thumbnail` (Apple Photos provides one without downloading the original),
that gets used and the original is never touched. That's what makes it possible to catalog a
library that lives in the cloud.

**Every sheet prints the number over each cell** and comes with an `index.json` mapping number →
id and path. If the agent says "number 14", there has to be a 14: without that map the catalog
can't be reconstructed.

Dependencies: Pillow (imaging), OpenCV (face detection, using the classifiers the package itself
ships: nothing gets downloaded) and `ffmpeg`/`ffprobe` on the PATH for the `strip` command.

Cross-platform. The only macOS-only part is the path of the Photos app's thumbnails, and that is
handled by `sources.py`, not by this script.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - without HEIC the rest works the same
    pass

EXT_PHOTO = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".dng", ".webp", ".avif"}

# Contact sheet cell size. 320 px wide is the point where a grimace is still visible without the
# sheet getting heavy: with 30 cells it comes to ~2 MB.
CELL = 320
MARGIN = 6
BAR = 22  # height of the strip carrying the number


# --------------------------------------------------------------------------- inputs


def expand(path) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()


def load_items(entries: list[str]) -> list[dict]:
    """Normalizes whatever comes in (JSON, a folder or loose paths) to [{id, path, used}]."""
    items: list[dict] = []

    for entry in entries:
        p = expand(entry)

        if p.is_dir():
            for child in sorted(p.iterdir()):
                if child.suffix.lower() in EXT_PHOTO:
                    items.append({"path": str(child)})
            continue

        if p.suffix.lower() == ".json":
            data = json.loads(p.read_text(encoding="utf-8"))
            raw = data.get("items", data) if isinstance(data, dict) else data
            for i in raw:
                items.append({"path": i} if isinstance(i, str) else dict(i))
            continue

        items.append({"path": str(p)})

    out = []
    for n, it in enumerate(items, 1):
        path = it.get("thumbnail") or it.get("path")
        if not path:
            continue
        out.append({
            "id": it.get("id") or f"p-{n:03d}",
            "path": str(expand(it.get("path") or path)),
            "used": str(expand(path)),
        })
    return out


def typeface(size: int):
    """A font that exists on the system; if there is none, Pillow's (ugly but legible)."""
    for c in (
        os.environ.get("REEL_FORGE_FONT_SANS"),
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",     # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
        "C:/Windows/Fonts/arialbd.ttf",                          # Windows
    ):
        if c and Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                pass
    return ImageFont.load_default()


# --------------------------------------------------------------------------- contact sheet


def cell(img: Image.Image, number: int, label: str, font) -> Image.Image:
    """A square thumbnail with the number printed on a strip underneath."""
    canvas = Image.new("RGB", (CELL, CELL + BAR), (18, 18, 18))
    copy = img.copy()
    copy.thumbnail((CELL - MARGIN * 2, CELL - MARGIN * 2), Image.LANCZOS)
    canvas.paste(copy, ((CELL - copy.width) // 2, (CELL - MARGIN * 2 - copy.height) // 2 + MARGIN))

    d = ImageDraw.Draw(canvas)
    d.rectangle([0, CELL, CELL, CELL + BAR], fill=(0, 0, 0))
    d.text((6, CELL + 3), f"{number}", fill=(255, 220, 0), font=font)
    d.text((44, CELL + 4), label[:34], fill=(190, 190, 190), font=font)
    return canvas


def open_image(path: str) -> Image.Image | None:
    try:
        img = Image.open(path)
        img.load()
        return img.convert("RGB")
    except Exception as e:
        print(f"  couldn't open {path}: {e}", file=sys.stderr)
        return None


def contact_sheet(items: list[dict], out: Path, cols: int, per_sheet: int) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    font = typeface(16)
    index, sheets = [], []

    for h, start in enumerate(range(0, len(items), per_sheet), 1):
        batch = items[start:start + per_sheet]
        cells = []
        for n, it in enumerate(batch, start + 1):
            img = open_image(it["used"])
            if img is None:
                continue
            cells.append(cell(img, n, Path(it["path"]).name, font))
            index.append({"n": n, "id": it["id"], "path": it["path"], "sheet": h})

        if not cells:
            continue

        width = min(cols, len(cells))          # don't leave empty columns on small batches
        rows = (len(cells) + width - 1) // width
        page = Image.new("RGB", (width * CELL, rows * (CELL + BAR)), (18, 18, 18))
        for k, c in enumerate(cells):
            page.paste(c, ((k % width) * CELL, (k // width) * (CELL + BAR)))

        target = out / f"sheet-{h:02d}.jpg"
        page.save(target, quality=88)
        sheets.append(str(target))
        print(f"  {target}  ({len(cells)} thumbnails)")

    return {"kind": "contact", "sheets": sheets, "index": index}


# --------------------------------------------------------------------------- face crops


def detector():
    """OpenCV's face classifier.

    The XML files ship inside the `opencv-contrib-python` **4.x** package; OpenCV 5 removed
    them, which is why the `# /// script` header pins `<5`. With `$REEL_FORGE_CASCADE` you can
    point at a different XML.
    """
    import cv2

    own = os.environ.get("REEL_FORGE_CASCADE")
    if own:
        path = Path(own)
    elif hasattr(cv2, "data") and getattr(cv2.data, "haarcascades", None):
        path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    else:
        path = Path("haarcascade_frontalface_default.xml")

    if not path.exists():
        raise SystemExit(
            "OpenCV doesn't ship the face classifier (OpenCV 5 removed it from the package).\n"
            "Run this with `uv run`, which honours the `opencv-contrib-python<5` pin in the header,\n"
            "or point at your own XML with $REEL_FORGE_CASCADE."
        )
    return cv2.CascadeClassifier(str(path))


def faces_in(img: Image.Image, casc) -> list[tuple[int, int, int, int]]:
    import cv2
    import numpy as np

    small = img.copy()
    small.thumbnail((900, 900), Image.LANCZOS)
    scale = img.width / small.width
    grey = cv2.cvtColor(np.array(small), cv2.COLOR_RGB2GRAY)
    boxes = casc.detectMultiScale(grey, scaleFactor=1.15, minNeighbors=5, minSize=(40, 40))
    return [tuple(int(v * scale) for v in c) for c in boxes]


def face_sheet(items: list[dict], out: Path, cols: int, per_sheet: int, padding: float) -> dict:
    """A sheet of faces only, numbered the same as the contact sheet.

    It's the step that has saved the most videos: in a 180 px thumbnail you can't see that
    somebody is mid-word. The numbers match the ones from `contact` over the SAME list, so the
    two sheets can be read together.
    """
    out.mkdir(parents=True, exist_ok=True)
    casc = detector()
    font = typeface(16)
    crops, index, no_face = [], [], []

    for n, it in enumerate(items, 1):
        img = open_image(it["used"])
        if img is None:
            continue
        boxes = faces_in(img, casc)
        if not boxes:
            no_face.append({"n": n, "id": it["id"], "path": it["path"]})
            continue
        x, y, w, h = max(boxes, key=lambda c: c[2] * c[3])   # the largest face = the subject
        d = int(max(w, h) * padding)
        cx, cy = x + w // 2, y + h // 2
        box = (max(0, cx - d), max(0, cy - d), min(img.width, cx + d), min(img.height, cy + d))
        crops.append((n, it, img.crop(box)))
        index.append({"n": n, "id": it["id"], "path": it["path"], "box": [x, y, w, h]})

    sheets = []
    for h_i, start in enumerate(range(0, len(crops), per_sheet), 1):
        batch = crops[start:start + per_sheet]
        cells = [cell(crop, n, Path(it["path"]).name, font) for n, it, crop in batch]
        width = min(cols, len(cells))          # don't leave empty columns on small batches
        rows = (len(cells) + width - 1) // width
        page = Image.new("RGB", (width * CELL, rows * (CELL + BAR)), (18, 18, 18))
        for k, c in enumerate(cells):
            page.paste(c, ((k % width) * CELL, (k // width) * (CELL + BAR)))
        target = out / f"faces-{h_i:02d}.jpg"
        page.save(target, quality=90)
        sheets.append(str(target))
        print(f"  {target}  ({len(cells)} faces)")

    if no_face:
        print(f"  no face detected: {len(no_face)} (they go into index.json as `no_face`)")
    return {"kind": "faces", "sheets": sheets, "index": index, "no_face": no_face}


# --------------------------------------------------------------------------- frame strip


def duration(video: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(video)],
            capture_output=True, text=True, check=True).stdout.strip()
        return float(out)
    except Exception:
        return None


def strip(video: Path, out: Path, fps: float, cols: int, rows: int,
          start: float | None, dur: float | None) -> dict:
    """A frame strip with ffmpeg: 1 fps to catalog, 4 fps to hunt down a cut's exact frame.

    A `cols x rows` mosaic covers `cols*rows/fps` seconds. If the clip runs longer, several
    numbered strips get written and each one says which seconds it covers (that is what makes
    the catalog's `start_s`/`end_s` usable).
    """
    if not shutil.which("ffmpeg"):
        raise SystemExit("`ffmpeg` has to be on the PATH")
    out.mkdir(parents=True, exist_ok=True)

    total = duration(video)
    t0 = start or 0.0
    length = dur if dur is not None else ((total - t0) if total else None)
    per_strip = cols * rows / fps

    strips, n = [], 0
    while True:
        at = t0 + n * per_strip
        if length is not None and at >= t0 + length - 1e-6:
            break
        chunk = per_strip if length is None else min(per_strip, t0 + length - at)
        target = out / f"{video.stem}-strip-{n + 1:02d}.jpg"
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y",
               "-ss", f"{at:.3f}", "-t", f"{chunk:.3f}", "-i", str(video),
               "-vf", f"fps={fps},scale=216:-2,tile={cols}x{rows}",
               "-frames:v", "1", str(target)]
        subprocess.run(cmd, check=True)
        if not target.exists():
            break
        strips.append({"file": str(target), "from_s": round(at, 2),
                       "to_s": round(at + chunk, 2), "fps": fps, "grid": f"{cols}x{rows}"})
        print(f"  {target}  [{at:.1f}s - {at + chunk:.1f}s]")
        n += 1
        if length is None or n > 200:
            break

    return {"kind": "strip", "video": str(video), "duration_s": total, "strips": strips}


# --------------------------------------------------------------------------- cli


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Contact sheets, face crops and frame strips for cataloging material.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  uv run sheets.py contact list.json --cols 6 --out workspace/sheets/day-03\n"
               "  uv run sheets.py faces   ~/Pictures/trip --out workspace/sheets/faces\n"
               "  uv run sheets.py strip   clip.mp4 --fps 1 --cols 8 --out workspace/sheets\n")
    ap.add_argument("command", choices=["contact", "faces", "strip"])
    ap.add_argument("inputs", nargs="+",
                    help="list.json, a folder, loose paths; for `strip`, the video")
    ap.add_argument("--out", default="sheets", help="output folder (default: ./sheets)")
    ap.add_argument("--cols", type=int, default=6, help="grid columns (default: 6)")
    ap.add_argument("--per-sheet", type=int, default=30,
                    help="thumbnails per sheet (default: 30; past 36 you can't tell a grimace apart)")
    ap.add_argument("--padding", type=float, default=1.1,
                    help="`faces`: how far the crop opens around the face (default: 1.1)")
    ap.add_argument("--fps", type=float, default=1.0, help="`strip`: frames per second (default: 1)")
    ap.add_argument("--rows", type=int, default=4, help="`strip`: grid rows (default: 4)")
    ap.add_argument("--start", type=float, help="`strip`: starting second")
    ap.add_argument("--dur", type=float, help="`strip`: seconds to cover")
    args = ap.parse_args()

    out = expand(args.out)

    if args.command == "strip":
        video = expand(args.inputs[0])
        if not video.exists():
            raise SystemExit(f"doesn't exist: {video}")
        res = strip(video, out, args.fps, args.cols, args.rows, args.start, args.dur)
    else:
        items = load_items(args.inputs)
        if not items:
            raise SystemExit("there is nothing to process: check the list or the folder")
        print(f"{len(items)} files")
        if args.command == "contact":
            res = contact_sheet(items, out, args.cols, args.per_sheet)
        else:
            res = face_sheet(items, out, args.cols, args.per_sheet, args.padding)

    (out / "index.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"index: {out / 'index.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
