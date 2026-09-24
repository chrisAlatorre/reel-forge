# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "pillow-heif"]
# ///
"""Material inventory for reel-forge.

Given a date range and one or more sources, it produces a JSON of what's there: counts, the
actual range, places, GPS, faces, sessions, date suspicions, the estimated download size and
whether the originals are on disk.

It downloads nothing, exports nothing and modifies nothing. It's the lay of the land before
deciding which material gets used.

Examples:

    # Everything from a trip that lives in the macOS Photos app
    uv run inventory.py --from 2026-08-01 --to 2026-08-20

    # An SD card folder, without touching Photos
    uv run inventory.py --source folder:~/Pictures/Trip --from 2026-08-01

    # Both sources together, a readable summary as well as the JSON
    uv run inventory.py --source photos --source folder:~/Movies/360 \\
        --from 2026-08-01 --to 2026-08-20 --summary -o inventory.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sources  # noqa: E402

GB = 1024 ** 3
MB = 1024 ** 2


def parse_source(text):
    """'photos' | 'photos:/path/lib.photoslibrary' | 'folder:~/Pictures/Trip'"""
    if ":" not in text:
        kind, arg = text, None
    else:
        kind, arg = text.split(":", 1)
    kind = kind.lower()
    if kind in ("photos", "apple-photos"):
        return ("apple-photos", arg)
    if kind in ("folder", "dir"):
        if not arg:
            raise ValueError("The 'folder' source needs a path: --source folder:~/Pictures/Trip")
        return ("folder", arg)
    raise ValueError(f"Unknown source '{text}'. Use 'photos' or 'folder:PATH'.")


def default_sources():
    """Without --source: the Photos app on macOS, plus the folders in REEL_FORGE_SOURCES."""
    out = ["photos"] if sys.platform == "darwin" else []
    out += [f"folder:{c}" for c in sources.env_sources()]
    if not out:
        raise SystemExit(
            "There is no source at all. Outside macOS there is no Photos app:\n"
            "  --source folder:PATH   or   export REEL_FORGE_SOURCES=/path/to/your/material")
    return out


def pct(part, total):
    return round(100 * part / total, 1) if total else 0.0


def build(args):
    date_from = sources.parse_date(args.date_from)
    date_to = sources.parse_date(args.date_to, end_of_day=True)

    all_items, metas, warnings = [], [], []
    for text in args.source or default_sources():
        kind, arg = parse_source(text)
        try:
            if kind == "apple-photos":
                items, meta = sources.read_apple_photos(
                    date_from=date_from, date_to=date_to, lib_path=arg, copy=args.copy_db,
                    include_hidden=args.include_hidden,
                    include_screenshots=not args.no_screenshots,
                    favorites_only=args.favorites_only,
                    person=args.person,
                )
            else:
                items, meta = sources.read_folder(
                    arg, date_from=date_from, date_to=date_to,
                    recursive=not args.no_recursion, use_exiftool=args.exiftool)
            if meta.get("wal_warning"):
                warnings.append(meta["wal_warning"])
            meta["items"] = len(items)
            metas.append(meta)
            all_items.extend(items)
        except sources.LibraryUnavailable as e:
            metas.append({"type": kind, "error": str(e), "items": 0})
            warnings.append(f"Source '{text}' unavailable: {e.args[0].splitlines()[0]}")
        except (FileNotFoundError, ValueError) as e:
            metas.append({"type": kind, "error": str(e), "items": 0})
            warnings.append(f"Source '{text}': {e}")

    total = len(all_items)
    dates = sorted(f for f in (i["date"] for i in all_items) if f)
    with_gps = [i for i in all_items if i["lat"] is not None]
    with_faces = [i for i in all_items if i["faces"]]
    videos = [i for i in all_items if i["type"] in ("video", "360")]
    missing = [i for i in all_items if i["local"] is False]

    # Size: what we already know from the metadata; for anything without a size we use a
    # per-type average, flagged as an estimate.
    known_bytes = sum(i["bytes"] or 0 for i in missing)
    no_size = [i for i in missing if not i["bytes"]]
    average = {"photo": 4 * MB, "video": 90 * MB, "360": 400 * MB}
    estimated_bytes = known_bytes + sum(average.get(i["type"], 4 * MB) for i in no_size)

    people = {}
    for i in all_items:
        for p in i["people"]:
            people[p] = people.get(p, 0) + 1

    sessions = sources.group_sessions(all_items, gap_min=args.gap_min)
    suspicions = sources.detect_suspicions(
        all_items, min_year=args.min_year, far_days=args.far_days,
        gap_min=args.gap_min)

    out = {
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "requested_range": {"from": args.date_from, "to": args.date_to},
        "sources": metas,
        "counts": {
            "total": total,
            "photos": sum(1 for i in all_items if i["type"] == "photo"),
            "videos": sum(1 for i in all_items if i["type"] == "video"),
            "material_360": sum(1 for i in all_items if i["type"] == "360"),
            "favorites": sum(1 for i in all_items if i["favorite"]),
            "screenshots": sum(1 for i in all_items if i["screenshot"]),
        },
        "actual_range": {
            "first": dates[0] if dates else None,
            "last": dates[-1] if dates else None,
            "days": _days(dates),
        },
        "gps": {
            "with_gps": len(with_gps),
            "pct": pct(len(with_gps), total),
            "without_gps": total - len(with_gps),
        },
        "places": sources.place_summary(all_items)[:args.top_places],
        "faces": {
            "with_faces": len(with_faces),
            "pct": pct(len(with_faces), total),
            "people": [{"name": n, "photos": c}
                       for n, c in sorted(people.items(), key=lambda kv: -kv[1])],
        },
        "video": {
            "clips": len(videos),
            "total_duration_s": round(sum(i["duration_s"] or 0 for i in videos), 1),
            "total_duration_min": round(sum(i["duration_s"] or 0 for i in videos) / 60, 1),
        },
        "sessions": {
            "gap_min": args.gap_min,
            "total": len(sessions),
            "list": sessions if args.full_sessions else [
                {k: v for k, v in s.items() if k != "ids"} for s in sessions],
        },
        "date_suspicions": suspicions,
        "download": {
            "local_originals": sum(1 for i in all_items if i["local"]),
            "missing": len(missing),
            "estimated_bytes": estimated_bytes,
            "estimated_gb": round(estimated_bytes / GB, 2),
            "accuracy": ("exact" if not no_size else
                         f"approximate ({len(no_size)} without a size in the database)"),
            "with_local_thumbnail": sum(1 for i in all_items if i["thumbnail"]),
        },
        "warnings": warnings,
    }

    if args.include_items:
        out["items"] = all_items
    return out, all_items


def _days(dates):
    if not dates:
        return 0
    a = datetime.fromisoformat(dates[0])
    b = datetime.fromisoformat(dates[-1])
    return (sources.naive(b) - sources.naive(a)).days + 1


def print_summary(d):
    c, r = d["counts"], d["actual_range"]
    print(f"\n{c['total']} files between {r['first']} and {r['last']} ({r['days']} days)")
    print(f"  {c['photos']} photos · {c['videos']} videos · {c['material_360']} in 360 · "
          f"{c['favorites']} favorites · {c['screenshots']} screenshots")
    print(f"  GPS: {d['gps']['pct']}%   ·   faces: {d['faces']['pct']}%   ·   "
          f"video: {d['video']['total_duration_min']} min")
    if d["places"]:
        print("  Places: " + " · ".join(f"{p['place']} ({p['n']})" for p in d["places"][:6]))
    if d["faces"]["people"]:
        print("  People: " + " · ".join(
            f"{p['name']} ({p['photos']})" for p in d["faces"]["people"][:6]))
    print(f"  Sessions: {d['sessions']['total']} (gaps longer than {d['sessions']['gap_min']} min)")
    dl = d["download"]
    print(f"  Download: {dl['missing']} originals in the cloud ≈ {dl['estimated_gb']} GB "
          f"({dl['accuracy']}); {dl['with_local_thumbnail']} already have a local thumbnail")
    if d["date_suspicions"]:
        print("\n  Dates to confirm:")
        for s in d["date_suspicions"]:
            print(f"    · {s['message']}")
        print("  Run validate_dates.py for the full report.")
    for warning in d["warnings"]:
        print(f"  ! {warning}")
    print()


def add_source_args(ap):
    """The flags both this script and validate_dates.py share, so sources get read identically."""
    ap.add_argument("--from", dest="date_from", help="YYYY-MM-DD (or with a time: YYYY-MM-DDTHH:MM)")
    ap.add_argument("--to", dest="date_to", help="YYYY-MM-DD, inclusive")
    ap.add_argument("--source", action="append",
                    help="'photos', 'photos:/path/lib.photoslibrary' or 'folder:PATH'. "
                         "Repeatable. Default: photos")
    ap.add_argument("--gap-min", type=int, default=90,
                    help="Minutes of gap that open a new session (default: 90)")
    ap.add_argument("--top-places", type=int, default=20)
    ap.add_argument("--min-year", type=int, default=2000,
                    help="Below this year a date is flagged as impossible")
    ap.add_argument("--far-days", type=int, default=180,
                    help="Days away from the median before a batch is flagged as suspicious")
    ap.add_argument("--include-items", action="store_true",
                    help="Puts the full file list into the JSON (it's heavy)")
    ap.add_argument("--full-sessions", action="store_true",
                    help="Includes the ids of each session")

    g = ap.add_argument_group("Apple Photos")
    g.add_argument("--copy-db", action="store_true",
                   help="Copies Photos.sqlite + WAL to a temp folder before reading (slower, up to date)")
    g.add_argument("--include-hidden", action="store_true")
    g.add_argument("--no-screenshots", action="store_true", help="Excludes screenshots")
    g.add_argument("--favorites-only", action="store_true")
    g.add_argument("--person", help="Only assets where Photos recognized this person")

    g2 = ap.add_argument_group("Folders")
    g2.add_argument("--no-recursion", action="store_true")
    g2.add_argument("--exiftool", action="store_true",
                    help="Uses exiftool as a fallback when there is no readable EXIF")
    return ap


def main():
    ap = argparse.ArgumentParser(
        description="Inventory of photos and videos by date range and source.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    add_source_args(ap)
    ap.add_argument("-o", "--out", help="Output JSON file (default: stdout)")
    ap.add_argument("--summary", action="store_true", help="Also print a readable summary")

    args = ap.parse_args()
    data, _ = build(args)

    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).expanduser().write_text(text, encoding="utf-8")
        print(f"Written: {args.out}", file=sys.stderr)
    else:
        print(text)
    if args.summary:
        print_summary(data)


if __name__ == "__main__":
    main()
