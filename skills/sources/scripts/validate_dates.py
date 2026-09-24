# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "pillow-heif"]
# ///
"""Metadata report for the user to confirm before any editing happens.

It detects photos with no date, impossible dates, shifted batches and time-zone offsets, and
writes a corrections plan as JSON.

**It never modifies files or the Photos library.** The corrections live in a separate file
(`corrections.json`) that the rest of reel-forge reads to order the material. If you genuinely
want to rewrite the EXIF of files in a folder, there is `--apply-exiftool`, which asks for
confirmation and only touches copies inside an ordinary folder, never the Photos app.

Examples:

    # An on-screen report plus an editable plan
    uv run validate_dates.py --from 2026-08-01 --to 2026-08-20 \\
        --plan corrections.json

    # Accept the automatic proposal for one specific case
    uv run validate_dates.py --plan corrections.json --case distant_batch --accept

    # Set a date by hand for a group that has none
    uv run validate_dates.py --plan corrections.json \\
        --case no_date --date 2026-08-14T09:00

    # Fix a camera's clock: shift everything in a folder by +7 h
    uv run validate_dates.py --source folder:~/Pictures/Insta360 \\
        --plan corrections.json --case all --offset-hours 7
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sources  # noqa: E402
import inventory  # noqa: E402


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

TITLES = {
    "no_date": "No capture date",
    "impossible_date": "Impossible date",
    "distant_batch": "Batch dated far from the rest",
    "mtime_only": "Date taken from the filesystem",
    "time_offset": "Time-zone offset",
}

WHAT_IT_MEANS = {
    "no_date": (
        "With no date they can't be ordered or grouped into sessions. Pick an approximate\n"
        "  date (the day of the trip will do) or leave them out of the project."),
    "impossible_date": (
        "Almost always an external camera that lost the time. If the rest of the batch is\n"
        "  fine, the right move is to shift that group to the real day."),
    "distant_batch": (
        "They are coherent among themselves, so one even offset puts them right. Check that\n"
        "  the order inside the group makes sense before accepting."),
    "mtime_only": (
        "The modification date gets rewritten when files are copied. If the material went\n"
        "  through an SD card or an external drive, it is probably wrong."),
    "time_offset": (
        "Two cameras from the same day with shifted clocks. If you are going to interleave\n"
        "  their shots in one video, they have to be matched or the edit comes out scrambled."),
}


def report_text(cases, summary, plan=None):
    lines = []
    c, r = summary["counts"], summary["actual_range"]
    lines.append("METADATA REPORT")
    lines.append("=" * 60)
    lines.append(f"{c['total']} files · {r['first']} → {r['last']} ({r['days']} days)")
    lines.append(f"GPS {summary['gps']['pct']}% · faces {summary['faces']['pct']}% · "
                 f"{summary['sessions']['total']} sessions")
    if summary["places"]:
        lines.append("Places: " + " · ".join(
            f"{p['place']} ({p['n']})" for p in summary["places"][:8]))
    lines.append("")

    if not cases:
        lines.append("No date problems. The material can be ordered as is.")
        return "\n".join(lines)

    noun = "thing" if len(cases) == 1 else "things"
    lines.append(f"{len(cases)} {noun} to confirm:")
    lines.append("")
    already = set()
    for c in (plan or {}).get("corrections", []):
        already.update(c["ids"])

    for n, case in enumerate(cases, 1):
        settled = " [already confirmed in the plan]" if set(case["ids"]) <= already else ""
        how_many = "1 file" if case["n"] == 1 else f"{case['n']} files"
        lines.append(f"[{n}] {TITLES.get(case['case'], case['case'])}  ({how_many}){settled}")
        lines.append(f"  {case['message']}")
        for ex in case["examples"]:
            lines.append(f"    - {ex}")
        if case["n"] > len(case["examples"]):
            lines.append(f"    … and {case['n'] - len(case['examples'])} more")
        p = case.get("proposal") or {}
        if p.get("equivalent"):
            lines.append(f"  Proposal: {p['equivalent']}")
        elif p.get("action") == "assign_date":
            lines.append("  Proposal: assign them a date by hand (it can't be guessed)")
        lines.append(f"  What it means: {WHAT_IT_MEANS.get(case['case'], '')}")
        if not settled:
            lines.append(f"  Accept: --case {case['case']} --accept")
        lines.append("")

    lines.append("Nothing gets modified until you confirm. The corrections live in the JSON")
    lines.append("plan; the original files and the Photos app are untouched.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The corrections plan
# ---------------------------------------------------------------------------


def load_plan(path):
    p = Path(path).expanduser()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"version": 1, "created": datetime.now().astimezone().isoformat(timespec="seconds"),
            "corrections": []}


def save_plan(plan, path):
    p = Path(path).expanduser()
    plan["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
    p.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def add_correction(plan, ids, action, value, note):
    plan["corrections"] = [c for c in plan["corrections"]
                           if not set(c["ids"]) & set(ids)]
    plan["corrections"].append({
        "ids": ids, "action": action, "value": value, "note": note,
        "confirmed": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    return plan


def apply_plan(items, plan):
    """Returns the items with their dates already corrected, without touching anything on disk."""
    by_id = {i["id"]: i for i in items}
    for c in plan.get("corrections", []):
        for id_ in c["ids"]:
            it = by_id.get(id_)
            if not it:
                continue
            new = _new_date(it, c["action"], c["value"])
            if new:
                it["original_date"] = it["date"]
                it["date"] = sources.iso(new)
                it["date_origin"] = "corrected"
    return items


def _new_date(item, action, value):
    current = None
    if item.get("date"):
        try:
            current = datetime.fromisoformat(item["date"])
        except ValueError:
            current = None
    if action == "assign_date":
        return datetime.fromisoformat(value) if value else None
    if action == "offset_hours" and current:
        return current + timedelta(hours=float(value))
    if action == "offset_days" and current:
        return current + timedelta(days=float(value))
    if action == "offset_minutes" and current:
        return current + timedelta(minutes=float(value))
    return None


# ---------------------------------------------------------------------------
# Optional EXIF writing (folders only)
# ---------------------------------------------------------------------------


def apply_exiftool(items, plan, confirm):
    """Rewrites DateTimeOriginal with exiftool. Only items from a 'folder' source.

    exiftool leaves an `_original` backup next to each file, so it can be undone. Apple Photos
    items are always skipped: to change a date there, the user does it in the app
    (Image → Adjust Date and Time).
    """
    import shutil
    import subprocess

    if not shutil.which("exiftool"):
        return {"ok": False, "reason": "exiftool isn't installed (brew install exiftool)"}

    applied = apply_plan([dict(i) for i in items], plan)
    targets = [i for i in applied
               if i.get("date_origin") == "corrected" and i["source"] == "folder" and i["path"]]
    skipped = [i for i in applied
               if i.get("date_origin") == "corrected" and i["source"] != "folder"]

    if not targets:
        return {"ok": False, "reason": "No folder files with a pending correction",
                "skipped_apple_photos": len(skipped)}
    if not confirm:
        return {"ok": False, "reason": f"--yes was missing: it would rewrite {len(targets)} files",
                "files": [i["path"] for i in targets[:10]],
                "skipped_apple_photos": len(skipped)}

    done, errors = 0, []
    for it in targets:
        date = datetime.fromisoformat(it["date"]).strftime("%Y:%m:%d %H:%M:%S")
        cmd = ["exiftool", f"-DateTimeOriginal={date}", f"-CreateDate={date}", it["path"]]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            done += 1
        else:
            errors.append({"path": it["path"], "error": r.stderr.strip()[:200]})
    return {"ok": True, "rewritten": done, "errors": errors,
            "skipped_apple_photos": len(skipped),
            "backup": "exiftool left an _original file next to each one"}


# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Validates dates and builds a corrections plan for the user to confirm.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    # The same source flags as inventory.py, so both read sources identically.
    inventory.add_source_args(ap)
    ap.set_defaults(full_sessions=True)
    ap.add_argument("--plan", default="corrections.json",
                    help="The plan file (created or updated)")
    ap.add_argument("--json", action="store_true", help="JSON output instead of text")

    g = ap.add_argument_group("Confirming a correction")
    g.add_argument("--case", help="Name of the case to correct, or 'all'")
    g.add_argument("--accept", action="store_true", help="Accepts the case's automatic proposal")
    g.add_argument("--date", help="Assigns this date to the whole case (YYYY-MM-DDTHH:MM)")
    g.add_argument("--offset-hours", type=float)
    g.add_argument("--offset-days", type=float)
    g.add_argument("--offset-minutes", type=float)
    g.add_argument("--discard", action="store_true",
                   help="Marks the case as reviewed without correcting anything")

    g2 = ap.add_argument_group("Writing EXIF (folders only, optional)")
    g2.add_argument("--apply-exiftool", action="store_true")
    g2.add_argument("--yes", action="store_true", help="Confirms the exiftool write")

    args = ap.parse_args()
    summary, items = inventory.build(args)
    cases = summary["date_suspicions"]
    plan = load_plan(args.plan)

    # Confirming a case
    if args.case:
        if args.case == "all":
            ids = [i["id"] for i in items]
            proposal = None
        else:
            chosen = [c for c in cases if c["case"] == args.case]
            if not chosen:
                print(f"There is no '{args.case}' case in this material.", file=sys.stderr)
                sys.exit(1)
            ids = [i for c in chosen for i in c["ids"]]
            proposal = chosen[0].get("proposal")

        if args.discard:
            plan.setdefault("discarded", []).append(
                {"case": args.case, "n": len(ids),
                 "when": datetime.now().astimezone().isoformat(timespec="seconds")})
            action = value = None
        elif args.date:
            action, value = "assign_date", args.date
        elif args.offset_hours is not None:
            action, value = "offset_hours", args.offset_hours
        elif args.offset_days is not None:
            action, value = "offset_days", args.offset_days
        elif args.offset_minutes is not None:
            action, value = "offset_minutes", args.offset_minutes
        elif args.accept and proposal and proposal.get("action", "").startswith("offset"):
            action, value = proposal["action"], proposal["value"]
        else:
            print("Tell me what to do: --accept, --date, --offset-hours, --offset-days "
                  "or --discard.", file=sys.stderr)
            sys.exit(1)

        if action:
            plan = add_correction(plan, ids, action, value, f"case {args.case}")
        path = save_plan(plan, args.plan)
        how_many = "1 file" if len(ids) == 1 else f"{len(ids)} files"
        print(f"Plan updated: {path} ({how_many}, action: {action or 'discard'})")
        return

    if args.apply_exiftool:
        result = apply_exiftool(items, plan, args.yes)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.json:
        print(json.dumps({"summary": summary, "cases": cases, "plan": plan},
                         ensure_ascii=False, indent=2))
    else:
        print(report_text(cases, summary, plan))
        if plan.get("corrections"):
            n = len(plan["corrections"])
            print(f"\nCurrent plan ({args.plan}): {n} "
                  f"{'confirmed correction' if n == 1 else 'confirmed corrections'}.")


if __name__ == "__main__":
    main()
