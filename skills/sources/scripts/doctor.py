# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Is every moment of the catalog actually on disk? Finds the ones that moved, before anybody plans.

    uv run doctor.py --catalog catalog.json                      # report only
    uv run doctor.py --catalog catalog.json --apply              # repoint the ones found
    uv run doctor.py --catalog catalog.json --roots ~/Movies ~/Desktop --apply

Why it exists: in one round, 88 of 1,479 catalog moments pointed at files that were not there (the
material folder had been reorganised between rounds). Every creative director met the same broken
paths and went looking on its own; some found the files in an older working folder, some dropped the
moment, and a chief editor still selected two that no disk held. One pass here, before the concepts,
settles it for everybody.

For each item whose `path` does not exist it looks, in this order:
  1. the same file name under the roots (the project folder first, then ~/Movies by default);
  2. a working copy whose name carries the original's stem (`…-IMG_6202-1080.mp4` for IMG_6202.MOV);
  3. the Photos library, by original file name — then it says so, with the uuid to export
     (`export.py --export`), because a file that only lives in the library is not on disk.

`--apply` rewrites `path` for the found ones (the old one stays in `path_was`) and marks the rest
`missing: true` with the reason in `notes`, so a director can tell a moment it cannot use from one it
can. Nothing is copied, moved or deleted.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

MEDIA = {".mov", ".mp4", ".m4v", ".jpg", ".jpeg", ".heic", ".png", ".insv", ".insp", ".mkv"}
SKIP_DIRS = {".photoslibrary", ".git", "node_modules", "__pycache__", ".Trash"}
LIBRARY = Path(os.path.expanduser(os.environ.get("REEL_FORGE_LIBRARY",
                                                 "~/Pictures/Photos Library.photoslibrary")))


def index(roots):
    """{lowercase file name: [paths]} for every media file under the roots."""
    idx = {}
    for root in roots:
        root = Path(os.path.expanduser(str(root)))
        if not root.exists():
            continue
        for dirpath, dirnames, files in os.walk(root):
            dirnames[:] = [d for d in dirnames if not any(d.endswith(x) or d == x for x in SKIP_DIRS)]
            for f in files:
                if Path(f).suffix.lower() in MEDIA:
                    idx.setdefault(f.lower(), []).append(Path(dirpath) / f)
    return idx


def library_names():
    """{ORIGINAL FILE NAME: uuid} from a private copy of the Photos database (read-only)."""
    src = LIBRARY / "database" / "Photos.sqlite"
    if not src.exists():
        return {}
    tmpdir = Path(tempfile.mkdtemp(prefix="rf-doctor-"))
    tmp = tmpdir / "Photos.sqlite"
    try:
        for suf in ("", "-wal", "-shm"):
            if Path(str(src) + suf).exists():
                shutil.copy2(Path(str(src) + suf), Path(str(tmp) + suf))
        con = sqlite3.connect(tmp)
        rows = con.execute("select a.ZORIGINALFILENAME, z.ZUUID from ZADDITIONALASSETATTRIBUTES a "
                           "join ZASSET z on z.Z_PK = a.ZASSET where z.ZTRASHEDSTATE = 0").fetchall()
        con.close()
    except sqlite3.Error:
        return {}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)   # ~2.4 GB per run otherwise
    return {str(n).upper(): u for n, u in rows if n}


ROUND_COPY = re.compile(r"/v\d+/[^/]+/resources/")   # a round's shared material: often trimmed


def seconds(p):
    import subprocess
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                        str(p)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def rank(paths, project):
    """Outside a round's resources/ first (those are often trimmed), then the project's own copy,
    then the largest (an original over a proxy)."""
    return sorted(paths, key=lambda p: (bool(ROUND_COPY.search(str(p))),
                                        not str(p).startswith(str(project)), -p.stat().st_size))


def long_enough(item, p):
    """A video copy has to hold the moment's window; a trimmed working copy does not."""
    if item.get("type") not in ("video", "video360") or Path(p).suffix.lower() in (".jpg", ".jpeg", ".heic", ".png"):
        return True
    need = float(item.get("end_s") or 0)
    return need == 0 or seconds(p) >= need - 0.05


def find(item, idx, stems, project):
    path = Path(os.path.expanduser(item["path"]))
    name = path.name.lower()
    for p in rank(idx.get(name, []), project):
        if long_enough(item, p):
            return p, "same name"
    stem = re.escape(path.stem.lower())
    hits = [p for key, ps in stems.items() if re.search(rf"(^|[-_]){stem}([-_.]|$)", key) for p in ps]
    for p in rank(hits, project):
        if long_enough(item, p):
            return p, "working copy of the same original"
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--roots", nargs="*", help="where to look (default: the project folder, then ~/Movies)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args()
    cat = Path(a.catalog)
    doc = json.loads(cat.read_text(encoding="utf-8"))
    items = doc["items"] if isinstance(doc, dict) else doc
    project = cat.resolve().parents[2] if len(cat.resolve().parents) > 2 else cat.parent
    roots = a.roots or [project, "~/Movies"]
    broken = [it for it in items if it.get("path") and not Path(os.path.expanduser(it["path"])).exists()]
    report = {"items": len(items), "broken": len(broken), "found": [], "in_library": [], "missing": []}
    if broken:
        idx = index(roots)
        lib = library_names()
        for it in broken:
            got, how = find(it, idx, idx, project)
            if got:
                report["found"].append({"id": it["id"], "was": it["path"], "now": str(got), "how": how})
                if a.apply:
                    it["path_was"], it["path"] = it["path"], str(got)
                    it.pop("missing", None)
                continue
            uuid = lib.get(Path(it["path"]).name.upper())
            entry = {"id": it["id"], "path": it["path"]}
            if uuid:
                entry["uuid"] = uuid
                report["in_library"].append(entry)
                why = f"not on disk; in the Photos library as {uuid}: export it by uuid first"
            else:
                report["missing"].append(entry)
                why = "not on disk and not in the Photos library under this name"
            if a.apply:
                it["missing"] = True
                if "doctor:" not in (it.get("notes") or ""):
                    it["notes"] = ((it.get("notes") or "").rstrip() + f" | doctor: {why}").strip(" |")
    if a.apply and broken:
        tmp = cat.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(cat)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if a.json_out:
        Path(a.json_out).write_text(text, encoding="utf-8")
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in report.items()}))
    for e in report["missing"][:10]:
        print(f"  missing: {e['id']}  {e['path']}", file=sys.stderr)
    sys.exit(0 if not report["missing"] else 1)


if __name__ == "__main__":
    main()
