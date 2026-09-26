# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy<2.3", "opencv-python-headless<5"]
# ///
"""Live Photos: the ~3 s of movement behind a still, found, exported and measured.

    uv run live.py scan    --catalog catalog.json [--map library-map.json] [--apply]
    uv run live.py export  --catalog catalog.json --dest material/live [--only-used] [--map …]
    uv run live.py analyze clip.mov [more.mov …] [--json out.json]
    uv run live.py analyze --catalog catalog.json --apply       # every exported companion

The feedback it exists for, translated: *"I don't like it when we put in static photos… the
library's photos are Live, they have some movement: use it like a video of a couple of seconds"*.
On a phone library most photos ARE Live (on one trip, well over half, favourites included), so a
still with a Ken Burns push is, most of the time, a choice nobody made.

What a Live Photo is: the still plus a ~3 s movie, ~1.5 s before the shutter and ~1.5 s after, with
sound, in the library as `<UUID>_3.mov` beside the original (or only in iCloud). The movie is lower
resolution than the still (1440x1080 or 1920x1440 on recent iPhones), which is plenty for a 1080x1920
cut once it is covered, but not for a deep punch-in.

What goes wrong with them, and what `analyze` measures so nobody has to guess:

| problem | how it shows | what analyze does |
|---|---|---|
| the phone being raised or lowered | a burst of whole-frame motion at the start or the end | trims it: the usable window is the longest steady run |
| nothing moves | a still that happens to be a movie | `motion: "static"`, `usable: false` — keep the photo |
| the camera shakes the whole time | whole-frame motion everywhere | `motion: "shaky"`, `usable: false` |
| too short once trimmed | under 1.0 s of steady picture | `usable: false` |

A usable Live comes back as `{"mov", "start_s", "end_s", "still_s", "motion", "usable"}` —
`motion` is `subject` (something in the frame moves, the camera doesn't: the best kind) or `camera`
(a slow, steady drift: reads as handheld video). `still_s` is where the sharp still sits inside the
movie, so a shot can play the movement and **land on the still** (the engine's `tail: "still"`).

`scan` and `analyze --apply` only ADD a `live` object to catalog items; they never change a rating.
Photos only: reading the library is read-only (sqlite), exporting uses osxphotos like export.py.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

LIBRARY = Path(os.path.expanduser(os.environ.get("REEL_FORGE_LIBRARY",
                                                 "~/Pictures/Photos Library.photoslibrary")))
UUID_RE = re.compile(r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}", re.I)
LIVE_SUBTYPE = 2          # ZASSET.ZKINDSUBTYPE for a Live Photo

# analysis thresholds, in fractions of the frame width per second (resolution-independent)
FPS = 10
CAMERA_STEADY = 0.10      # whole-frame motion below this is a steady hand
CAMERA_SWING = 0.35       # above this, the phone is being raised/lowered/swung
SUBJECT_MIN = 0.9         # % of the frame that changes; still Lives measured 0.1-0.56, moving ones 1.1-10
MIN_USABLE_S = 1.0


# --------------------------------------------------------------------------- the library

def _db(library: Path):
    """A private copy of Photos.sqlite: never read the live database while Photos writes to it."""
    src = library / "database" / "Photos.sqlite"
    if not src.exists():
        sys.exit(f"live: no Photos database at {src} (set $REEL_FORGE_LIBRARY)")
    tmp = Path(tempfile.mkdtemp(prefix="rf-live-")) / "Photos.sqlite"
    for suffix in ("", "-wal", "-shm"):
        f = Path(str(src) + suffix)
        if f.exists():
            shutil.copy2(f, Path(str(tmp) + suffix))
    return sqlite3.connect(tmp)


def live_rows(uuids, library=LIBRARY):
    """{uuid: {"live": bool, "local": Path|None}} for the given photo uuids."""
    con = _db(library)
    out = {}
    q = "select ZUUID, ZKINDSUBTYPE, ZDIRECTORY from ZASSET where ZUUID in (%s)"
    uu = list(uuids)
    for k in range(0, len(uu), 500):
        chunk = uu[k:k + 500]
        for uuid, sub, d in con.execute(q % ",".join("?" * len(chunk)), chunk):
            local = None
            if sub == LIVE_SUBTYPE and d is not None:
                cand = library / "originals" / str(d) / f"{uuid}_3.mov"
                local = cand if cand.exists() else None
            out[uuid] = {"live": sub == LIVE_SUBTYPE, "local": local}
    return out


def item_uuid(item, lmap):
    """The library uuid of a catalog item: its own field, the library map, or its path."""
    for key in ("uuid", "library_uuid"):
        if item.get(key):
            return item[key]
    if lmap and item.get("id") in lmap:
        v = lmap[item["id"]]
        return v.get("uuid") if isinstance(v, dict) else v
    m = UUID_RE.search(str(item.get("path", "")))
    return m.group(0).upper() if m else None


def load_catalog(path):
    data = json.loads(Path(path).read_text())
    items = data["items"] if isinstance(data, dict) else data
    return data, items


def load_map(path):
    if not path or not Path(path).exists():
        return {}
    m = json.loads(Path(path).read_text())
    if isinstance(m, dict) and "items" in m:
        m = {x["id"]: x for x in m["items"]}
    return m


# --------------------------------------------------------------------------- analysis

def _frames(mov: Path):
    """Grey frames, 160 px wide, at FPS, rotation applied (ffmpeg, not cv2: cv2 ignores it)."""
    import numpy as np
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(mov), "-vf",
                        f"fps={FPS},scale=160:-2,format=gray", "-f", "rawvideo", "-"],
                       capture_output=True)
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:stream_side_data=rotation:format=duration", "-of", "json",
                        str(mov)], capture_output=True, text=True)
    info = json.loads(p.stdout or "{}")
    st = (info.get("streams") or [{}])[0]
    w, h = st.get("width", 0), st.get("height", 0)
    rot = 0
    for sd in st.get("side_data_list", []) or []:
        rot = int(sd.get("rotation", 0) or 0)
    if abs(rot) in (90, 270):
        w, h = h, w
    if not w or not h:
        return [], 0.0, (0, 0)
    fh = int(round(160 * h / w / 2) * 2)
    size = 160 * fh
    raw = r.stdout
    frames = [np.frombuffer(raw[i * size:(i + 1) * size], np.uint8).reshape(fh, 160)
              for i in range(len(raw) // size)]
    return frames, float(info.get("format", {}).get("duration", 0) or 0), (w, h)


def still_time(mov: Path, duration: float) -> float:
    """Where the still sits in the movie. Apple writes it in a timed-metadata track that ffprobe
    does not expose; on every iPhone Live Photo it is ~1.5 s in, i.e. about the middle."""
    return round(min(1.5, duration / 2) if duration else 1.5, 2)


def analyze(mov: Path) -> dict:
    import cv2
    import numpy as np
    frames, dur, (w, h) = _frames(mov)
    base = {"mov": str(mov), "duration_s": round(dur, 2), "size": [w, h]}
    if len(frames) < 4:
        return {**base, "usable": False, "motion": "unreadable", "why": "fewer than 4 frames decoded"}
    cam, res = [], []
    win = cv2.createHanningWindow(frames[0].shape[::-1], cv2.CV_32F)
    for a, b in zip(frames, frames[1:]):
        fa, fb = a.astype(np.float32), b.astype(np.float32)
        (dx, dy), resp = cv2.phaseCorrelate(fa, fb, win)
        if resp < 0.08:
            # no single shift explains the pair: something big moved inside a still frame, which
            # is subject motion, not the phone moving
            dx = dy = 0.0
        cam.append(float(np.hypot(dx, dy)) / 160 * FPS)          # frame widths per second
        m = np.float32([[1, 0, -dx], [0, 1, -dy]])
        aligned = cv2.warpAffine(fb, m, (fb.shape[1], fb.shape[0]), borderMode=cv2.BORDER_REFLECT)
        c = 8                                                      # ignore the warped border
        # the share of the picture that changed (by more than 30 grey levels) once the camera's own
        # shift is taken out: a small subject moving scores; compression noise on a still does not
        res.append(float((np.abs(aligned[c:-c, c:-c] - fa[c:-c, c:-c]) > 30).mean() * 100))
    cam, res = np.array(cam), np.array(res)
    steady = cam < CAMERA_SWING
    # longest steady run
    best, cur, best_rng = 0, 0, (0, 0)
    for i, ok in enumerate(steady):
        cur = cur + 1 if ok else 0
        if cur > best:
            best, best_rng = cur, (i - cur + 1, i + 1)
    s0, s1 = best_rng[0] / FPS, best_rng[1] / FPS
    # a step or two of margin inside a trimmed edge, where the swing is still settling
    if best_rng[0] > 0:
        s0 += 0.1
    if best_rng[1] < len(steady):
        s1 -= 0.1
    s1 = min(s1, dur) if dur else s1
    run_cam = cam[best_rng[0]:best_rng[1]] if best else cam
    run_res = res[best_rng[0]:best_rng[1]] if best else res
    cam_med, res_med = float(np.median(run_cam)), float(np.percentile(run_res, 75))
    still = still_time(mov, dur)
    out = {**base, "start_s": round(max(0.0, s0), 2), "end_s": round(max(0.0, s1), 2),
           "still_s": still, "camera": round(cam_med, 3), "subject": round(res_med, 2),
           "swing_trimmed": [round(best_rng[0] / FPS, 2), round(max(0.0, dur - best_rng[1] / FPS), 2)]}
    span = out["end_s"] - out["start_s"]
    if float(np.mean(steady)) < 0.35:
        return {**out, "usable": False, "motion": "shaky",
                "why": "the camera swings for most of the movie"}
    if span < MIN_USABLE_S:
        return {**out, "usable": False, "motion": "short",
                "why": f"only {span:.1f} s of steady picture once the swing is trimmed"}
    if res_med >= SUBJECT_MIN and cam_med < CAMERA_SWING:
        return {**out, "usable": True, "motion": "subject",
                "why": "something in the frame moves and the camera holds"}
    if CAMERA_STEADY * 0.3 <= cam_med < CAMERA_SWING:
        return {**out, "usable": True, "motion": "camera",
                "why": "a slow, steady drift: reads as handheld video"}
    return {**out, "usable": False, "motion": "static",
            "why": "nothing moves: the still with a push is the same picture, sharper"}


# --------------------------------------------------------------------------- commands

def cmd_scan(a):
    data, items = load_catalog(a.catalog)
    lmap = load_map(a.map)
    photos = [(it, item_uuid(it, lmap)) for it in items if it.get("type") == "photo"]
    rows = live_rows({u for _, u in photos if u})
    n_live = n_local = 0
    for it, u in photos:
        r = rows.get(u)
        if not r:
            continue
        if r["live"]:
            n_live += 1
            n_local += bool(r["local"])
            it.setdefault("live", {})
            it["live"].update({"available": True, "uuid": u})
            if r["local"] and not it["live"].get("mov"):
                it["live"]["library_mov"] = str(r["local"])
        elif "live" in it and a.apply:
            it.pop("live")
    print(json.dumps({"photos": len(photos), "live": n_live, "local": n_local,
                      "in_icloud_only": n_live - n_local}, indent=1))
    if a.apply:
        Path(a.catalog).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_export(a):
    data, items = load_catalog(a.catalog)
    dest = Path(os.path.expanduser(a.dest))
    dest.mkdir(parents=True, exist_ok=True)
    todo = [it for it in items if (it.get("live") or {}).get("available")
            and (not a.only_used or it.get("use", True) is not False)
            and (a.min_quality is None or (it.get("quality") or 0) >= a.min_quality
                 or it.get("favorite"))]
    copied, missing = 0, []
    for it in todo:
        lv = it["live"]
        out = dest / f"{lv['uuid']}.live.mov"
        if out.exists():
            lv["mov"] = str(out)
            continue
        lib = lv.get("library_mov")
        if lib and Path(lib).exists():
            try:
                os.link(lib, out)          # same volume: a hard link costs no space
            except OSError:
                shutil.copy2(lib, out)
            lv["mov"] = str(out)
            copied += 1
        else:
            missing.append(lv["uuid"])
    if missing and not a.no_icloud:
        # iCloud-only companions: osxphotos downloads the Live Photo and writes the .mov beside it
        osx = shutil.which("osxphotos") or str(Path.home() / ".local/bin/osxphotos")
        tmp = dest / "_icloud"
        tmp.mkdir(exist_ok=True)
        ids = tmp / "uuids.txt"
        ids.write_text("\n".join(missing))
        subprocess.run([osx, "export", str(tmp), "--uuid-from-file", str(ids), "--download-missing",
                        "--skip-edited", "--filename", "{uuid}", "--update", "--no-progress"],
                       check=False)
        for u in list(missing):
            got = next((p for p in tmp.glob(f"{u}*") if p.suffix.lower() == ".mov"), None)
            if got:
                shutil.move(str(got), dest / f"{u}.live.mov")
                missing.remove(u)
                copied += 1
        for it in todo:
            f = dest / f"{it['live']['uuid']}.live.mov"
            if f.exists():
                it["live"]["mov"] = str(f)
    Path(a.catalog).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"wanted": len(todo), "exported": copied, "missing": len(missing),
                      "dest": str(dest)}, indent=1))


def cmd_analyze(a):
    results = []
    if a.catalog:
        data, items = load_catalog(a.catalog)
        for it in items:
            lv = it.get("live") or {}
            if lv.get("mov") and Path(lv["mov"]).exists() and ("usable" not in lv or a.redo):
                r = analyze(Path(lv["mov"]))
                results.append(r)
                if a.apply:
                    lv.update({k: r[k] for k in ("start_s", "end_s", "still_s", "motion", "usable", "why")
                               if k in r})
        if a.apply:
            Path(a.catalog).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for m in a.movs:
        results.append(analyze(Path(m)))
    text = json.dumps(results if len(results) != 1 else results[0], ensure_ascii=False, indent=1)
    if a.json_out:
        Path(a.json_out).write_text(text, encoding="utf-8")
    if a.catalog:
        from collections import Counter
        print(json.dumps({"analyzed": len(results),
                          "motion": Counter(r.get("motion") for r in results),
                          "usable": sum(1 for r in results if r.get("usable"))}, indent=1))
    else:
        print(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="mark which catalog photos are Live Photos")
    s.add_argument("--catalog", required=True)
    s.add_argument("--map", help="library-map.json: catalog id -> library uuid")
    s.add_argument("--apply", action="store_true", help="write the `live` objects into the catalog")
    e = sub.add_parser("export", help="put each Live Photo's movie in a folder")
    e.add_argument("--catalog", required=True)
    e.add_argument("--dest", required=True)
    e.add_argument("--only-used", action="store_true", help="skip items marked use:false")
    e.add_argument("--min-quality", type=int, help="only items rated at least this (favourites always)")
    e.add_argument("--no-icloud", action="store_true", help="only what is already on this Mac")
    z = sub.add_parser("analyze", help="measure the movement and find the usable window")
    z.add_argument("movs", nargs="*")
    z.add_argument("--catalog")
    z.add_argument("--apply", action="store_true")
    z.add_argument("--redo", action="store_true")
    z.add_argument("--json", dest="json_out")
    a = ap.parse_args()
    {"scan": cmd_scan, "export": cmd_export, "analyze": cmd_analyze}[a.cmd](a)


if __name__ == "__main__":
    main()
