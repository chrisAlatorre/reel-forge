# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "pillow-heif"]
# ///
"""The user's veto over shots of themselves: one sheet to look at, one list of numbers to strike.

    uv run contact_sheet.py sheet --catalog catalog.json --ids ids.txt --out sheet.jpg
    uv run contact_sheet.py sheet --catalog catalog.json --subject --out sheet.jpg   # every usable shot with them
    uv run contact_sheet.py veto  --catalog catalog.json --sheet sheet.json 3 7 12   # strike numbers 3, 7, 12

Why. A rule of "only favourites" kept the user out of trips where he starred nothing, and a video
with no person in it is a postcard. Candid shots (not posed, not performing for the lens) bring him
back — but they are his face, so HE decides: the sheet numbers every candidate, he answers with the
numbers he does not want, and `veto` marks those `use: false` with "vetoed by the user" in the notes.
Nothing is published or uploaded; the sheet is a local JPG to send to him.

Videos are shown by the frame at the middle of their window. Exit 0, or 2 on bad input.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

TILE_W, TILE_H, COLS = 300, 400, 5


def items_of(catalog):
    doc = json.loads(Path(catalog).read_text())
    return doc, (doc["items"] if isinstance(doc, dict) else doc)


def frame(item, root):
    p = Path(os.path.expanduser(item["path"]))
    if not p.is_absolute():
        p = root / p
    if item.get("type") in ("video", "video360"):
        t = (float(item.get("start_s", 0)) + float(item.get("end_s", item.get("start_s", 0)))) / 2
        out = Path(tempfile.mkdtemp(prefix="rf-sheet-")) / "f.jpg"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(p),
                        "-frames:v", "1", str(out)], check=False)
        return Image.open(out).convert("RGB") if out.exists() else None
    return ImageOps.exif_transpose(Image.open(p)).convert("RGB") if p.exists() else None


def cmd_sheet(a):
    doc, items = items_of(a.catalog)
    root = Path(a.catalog).resolve().parents[2]
    if a.ids:
        want = [x.strip() for x in Path(a.ids).read_text().split() if x.strip()]
        chosen = [it for w in want for it in items if it["id"] == w]
    else:
        chosen = [it for it in items if it.get("use", True) is not False
                  and (it.get("subject_present") or it.get("subject"))]
    if not chosen:
        print("contact_sheet: nothing to show", file=sys.stderr)
        return 2
    rows = math.ceil(len(chosen) / COLS)
    sheet = Image.new("RGB", (COLS * TILE_W, rows * (TILE_H + 40)), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    index = []
    for n, it in enumerate(chosen, 1):
        img = frame(it, root)
        x, y = ((n - 1) % COLS) * TILE_W, ((n - 1) // COLS) * (TILE_H + 40)
        if img is not None:
            img.thumbnail((TILE_W - 8, TILE_H - 8))
            sheet.paste(img, (x + (TILE_W - img.width) // 2, y + 4))
        draw.text((x + 10, y + TILE_H + 4), f"{n}", fill="black", font=font)
        index.append({"n": n, "id": it["id"]})
    out = Path(a.out)
    sheet.save(out, quality=88)
    out.with_suffix(".json").write_text(json.dumps(index, indent=1))
    print(json.dumps({"sheet": str(out), "index": str(out.with_suffix('.json')), "shots": len(index)}))
    return 0


def cmd_veto(a):
    doc, items = items_of(a.catalog)
    index = {e["n"]: e["id"] for e in json.loads(Path(a.sheet).read_text())}
    struck = {index[int(n)] for n in a.numbers if int(n) in index}
    for it in items:
        if it["id"] in struck:
            it["use"] = False
            it["notes"] = ((it.get("notes") or "").rstrip() + " | vetoed by the user on the contact sheet").strip(" |")
    tmp = Path(a.catalog).with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    tmp.replace(a.catalog)
    print(json.dumps({"vetoed": sorted(struck)}))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet"); s.add_argument("--catalog", required=True); s.add_argument("--ids")
    s.add_argument("--subject", action="store_true"); s.add_argument("--out", required=True)
    v = sub.add_parser("veto"); v.add_argument("--catalog", required=True); v.add_argument("--sheet", required=True)
    v.add_argument("numbers", nargs="+")
    a = ap.parse_args()
    return {"sheet": cmd_sheet, "veto": cmd_veto}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
