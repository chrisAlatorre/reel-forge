# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""What was published, and how it did.

A run usually ends with three or four variants and the user picks one. Which one they picked is
already a judgement, and what the post did afterwards is the only feedback that isn't an opinion.
Both live here:

    ~/.config/reel-forge/history.json              ($REEL_FORGE_CONFIG_DIR overrides the folder)

    uv run history.py log --project oaxaca --variant B --format photo-dump \\
        --platform tiktok --duration 24 --hook question --close payoff --voice warm-narrator \\
        --music "slow piano, trending" --narration --published 2026-09-21
    uv run history.py result h-004 --views 12400 --saves 310 --likes 980 --comments 22
    uv run history.py show
    uv run history.py bias --platform tiktok           # the weights for the next proposal
    uv run history.py bias --apply                     # and write the verdict into preferences

Only the user's own numbers go in, and only when they say them: nothing here is scraped from any
platform. Paths, file names and identifiers are refused, the same as in `preferences.py`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).parent))
import preferences  # noqa: E402  (shared: config folder, atomic write, privacy guard)

VERSION = 1
FILENAME = "history.json"

PLATFORMS = ("tiktok", "reels", "shorts", "other")

# Duration buckets, in seconds. They exist so the history can answer "how long do this user's
# videos want to be", which is a question the account answers and a template cannot. The edges
# are where the feeds themselves behave differently: under ~12 s a video loops before it is read,
# and past ~60 s it stops being a short and has to earn every second.
BUCKETS = ((0, 12, "under 12s"), (12, 20, "12-20s"), (20, 30, "20-30s"),
           (30, 45, "30-45s"), (45, 60, "45-60s"), (60, 10 ** 9, "over 60s"))
METRICS = ("views", "likes", "saves", "comments", "shares", "followers", "watch_pct")

# A weight below this means "propose it less"; above it, "propose it more". Kept narrow on
# purpose: three posts are not a study, and a 3x multiplier off two data points is superstition.
WEIGHT_MIN, WEIGHT_MAX = 0.7, 1.35
Refused = preferences.Refused


def path() -> Path:
    return preferences.config_dir() / FILENAME


def load() -> dict:
    p = path()
    if not p.exists():
        return {"version": VERSION, "updated": None, "entries": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"warning: {p} couldn't be read ({e}); starting from an empty history.",
              file=sys.stderr)
        return {"version": VERSION, "updated": None, "entries": []}
    data.setdefault("entries", [])
    return data


def save(data: dict) -> Path:
    """Atomic write, `0600`, folder `0700`: the same treatment as the preferences file."""
    data["version"] = VERSION
    data["updated"] = now()
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".history-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target


def next_id(entries: list) -> str:
    used = {int(m.group(1)) for e in entries
            if (m := re.match(r"^h-(\d+)$", str(e.get("id", ""))))}
    return f"h-{(max(used) + 1 if used else 1):03d}"


def find(entries: list, entry_id: str) -> dict | None:
    for entry in entries:
        if entry["id"] == entry_id:
            return entry
    return None


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- log / result

def cmd_log(args) -> int:
    data = load()
    entries = data["entries"]
    entry = {
        "id": next_id(entries),
        "logged": now(),
        "published": args.published,
        "project": preferences.guard(args.project, "project name"),
        "variant": preferences.guard(args.variant, "variant") if args.variant else None,
        "platform": args.platform,
        "format": preferences.guard(args.format, "format"),
        "duration_s": args.duration,
        "hook": preferences.guard(args.hook, "hook") if args.hook else None,
        "close": preferences.guard(args.close, "close") if args.close else None,
        "voice": preferences.guard(args.voice, "voice") if args.voice else None,
        "music": preferences.guard(args.music, "music") if args.music else None,
        "language": args.language,
        "narration": bool(args.narration),
        "note": preferences.guard(args.note, "note") if args.note else None,
        "results": None,
    }
    entries.append(entry)
    save(data)
    print(f"[{entry['id']}] {entry['format']} · {entry['platform']}"
          + (f" · variant {entry['variant']}" if entry["variant"] else ""))
    print("  When the user says how it did:  "
          f"uv run history.py result {entry['id']} --views N --saves N")
    return 0


def cmd_result(args) -> int:
    data = load()
    entry = find(data["entries"], args.id)
    if not entry:
        print(f"There is no entry {args.id}. `show` lists them.", file=sys.stderr)
        return 1
    results = entry.get("results") or {}
    given = {m: getattr(args, m) for m in METRICS if getattr(args, m) is not None}
    if not given:
        print("Nothing to record: pass at least one of "
              + ", ".join(f"--{m.replace('_', '-')}" for m in METRICS), file=sys.stderr)
        return 1
    for metric, value in given.items():
        if value < 0:
            raise Refused(f"--{metric} can't be negative.")
        results[metric] = value
    results["measured"] = now()
    if args.days is not None:
        results["days_after"] = args.days
    entry["results"] = results
    save(data)
    print(f"[{entry['id']}] " + " · ".join(f"{k} {v:,}" for k, v in given.items()))
    return 0


def cmd_rm(args) -> int:
    data = load()
    kept = [e for e in data["entries"] if e["id"] != args.id]
    if len(kept) == len(data["entries"]):
        print(f"There is no entry {args.id}.", file=sys.stderr)
        return 1
    data["entries"] = kept
    save(data)
    print(f"{args.id} removed")
    return 0


def cmd_show(args) -> int:
    data = load()
    entries = data["entries"]
    if args.platform:
        entries = [e for e in entries if e["platform"] == args.platform]
    entries = sorted(entries, key=lambda e: e.get("published") or e["logged"], reverse=True)
    if args.limit:
        entries = entries[:args.limit]
    if args.json:
        print(json.dumps({"entries": entries}, ensure_ascii=False, indent=2))
        return 0
    p = path()
    print(f"PUBLISHED  {p}" + ("" if p.exists() else "   (nothing logged yet)"))
    print("=" * 72)
    if not entries:
        print("  Nothing yet. Log a post the moment the user says they uploaded one.")
        return 0
    for entry in entries:
        head = f"  [{entry['id']}] {entry.get('published') or entry['logged'][:10]}  " \
               f"{entry['platform']:<7} {entry['format']}"
        if entry.get("variant"):
            head += f" (variant {entry['variant']})"
        print(head)
        bits = [f"{k}: {v}" for k, v in (("hook", entry.get("hook")),
                                         ("close", entry.get("close")),
                                         ("voice", entry.get("voice")),
                                         ("music", entry.get("music"))) if v]
        if entry.get("duration_s"):
            bits.insert(0, f"{entry['duration_s']}s")
        if bits:
            print("        " + " · ".join(bits))
        results = entry.get("results")
        if results:
            nums = " · ".join(f"{m} {results[m]:,}" for m in METRICS if m in results)
            print(f"        -> {nums}")
        else:
            print("        -> no numbers yet")
    return 0


# --------------------------------------------------------------------------- bias

def bucket(seconds) -> str | None:
    """The duration band a post falls in, or None when the length was never recorded."""
    if seconds is None:
        return None
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None
    for low, high, label in BUCKETS:
        if low <= value < high:
            return label
    return None


def rates(entry: dict) -> dict:
    """Absolute numbers don't compare across a 200-view account and a 90k one. Rates do."""
    results = entry.get("results") or {}
    views = results.get("views") or 0
    out = {}
    if views:
        out["views"] = float(views)
        for metric in ("saves", "likes", "comments", "shares", "followers"):
            if results.get(metric) is not None:
                out[f"{metric}_rate"] = results[metric] / views
    if results.get("watch_pct") is not None:
        out["watch_pct"] = float(results["watch_pct"])
    return out


def score(entry: dict, baseline: dict) -> float | None:
    """How this post did against the median post, as one number around 1.0.

    Saves and watch-through are weighted above raw views: views are mostly the algorithm's
    mood on the day, a save is somebody deciding the video was worth keeping.
    """
    mine = rates(entry)
    weights = {"views": 1.0, "saves_rate": 2.0, "watch_pct": 2.0,
               "shares_rate": 1.5, "followers_rate": 1.5, "comments_rate": 1.0,
               "likes_rate": 0.5}
    total, used = 0.0, 0.0
    for key, weight in weights.items():
        base = baseline.get(key)
        if not base or key not in mine:
            continue
        ratio = max(0.2, min(5.0, mine[key] / base))
        total += weight * ratio
        used += weight
    return total / used if used else None


def clamp(value: float) -> float:
    return round(max(WEIGHT_MIN, min(WEIGHT_MAX, value)), 2)


def confidence(n: int) -> str:
    return "anecdote" if n < 2 else "low" if n < 4 else "usable"


def group_weights(scored: list[tuple[dict, float]], key: str, of=None) -> list[dict]:
    """Weights per value of `key`. `of` derives the value instead of reading the field."""
    groups: dict[str, list[float]] = {}
    for entry, value in scored:
        name = of(entry) if of else entry.get(key)
        if name:
            groups.setdefault(str(name), []).append(value)
    out = []
    for name, values in groups.items():
        raw = median(values)
        # An anecdote gets pulled most of the way back to neutral. One lucky post is not a format.
        damped = 1.0 + (raw - 1.0) * (0.35 if len(values) < 2 else 0.7 if len(values) < 4 else 1.0)
        out.append({key: name, "n": len(values), "score": round(raw, 2),
                    "weight": clamp(damped), "confidence": confidence(len(values))})
    return sorted(out, key=lambda g: (-g["weight"], -g["n"]))


def cmd_bias(args) -> int:
    data = load()
    entries = [e for e in data["entries"] if e.get("results")]
    if args.platform:
        entries = [e for e in entries if e["platform"] == args.platform]

    baseline_source = [rates(e) for e in entries]
    baseline = {}
    for key in ("views", "saves_rate", "likes_rate", "comments_rate", "shares_rate",
                "followers_rate", "watch_pct"):
        values = [r[key] for r in baseline_source if key in r]
        if values:
            baseline[key] = median(values)

    scored = [(e, s) for e in entries if (s := score(e, baseline)) is not None]
    report = {
        "generated": now(),
        "platform": args.platform,
        "logged": len(data["entries"]),
        "with_numbers": len(scored),
        "baseline": {k: round(v, 4) for k, v in baseline.items()},
        "formats": group_weights(scored, "format"),
        "hooks": group_weights(scored, "hook"),
        "closes": group_weights(scored, "close"),
        "voices": group_weights(scored, "voice"),
        "lengths": group_weights(scored, "length", of=lambda e: bucket(e.get("duration_s"))),
        "notes": [],
    }
    if len(scored) < 3:
        report["notes"].append(
            "Fewer than 3 posts with numbers: treat every weight as a hint, not a rule.")
    if len(scored) < len(entries):
        report["notes"].append("Posts without numbers are ignored; they carry no signal.")

    # What the account has never tried is as useful as what it has, and it is the one thing a
    # weight table can't say on its own: an empty bucket looks exactly like a bad one.
    timed = [e for e, _ in scored if bucket(e.get("duration_s"))]
    if not timed:
        report["notes"].append(
            "No post has a length recorded, so this says nothing about duration. "
            "Pass --duration when logging.")
    else:
        seen = {bucket(e.get("duration_s")) for e in timed}
        untried = [label for _, _, label in BUCKETS if label not in seen]
        report["untried_lengths"] = untried
        if untried:
            report["notes"].append(
                "Never posted at these lengths: " + ", ".join(untried)
                + ". An empty band is not a bad band — there is simply no evidence either way, "
                "so a longer concept is worth trying rather than ruled out.")
    if any((e.get("close") or "").lower() == "abrupt" for e, _ in scored):
        report["notes"].append(
            "Some posts are logged with an abrupt close. Compare their weight against the ones "
            "that land: an ending that stops mid-thought is the cheapest thing to fix.")
    if not any(e.get("close") for e, _ in scored):
        report["notes"].append(
            "No post records how it ends (--close), so nothing here can tell you which endings "
            "land. It is the field worth filling next.")
    report["notes"].append(
        "A weight multiplies how often a format gets proposed, never whether it is allowed: "
        f"the range is {WEIGHT_MIN}-{WEIGHT_MAX} on purpose.")
    report["notes"].append(
        "Posting time, the sound used and plain luck move these numbers more than the edit does.")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"WHAT TO PROPOSE MORE  ({report['with_numbers']} post(s) with numbers"
              + (f", {args.platform}" if args.platform else "") + ")")
        print("=" * 72)
        if not scored:
            print("  Nothing measured yet. Until then, propose whatever fits the material.")
        for group, label in (("formats", "format"), ("lengths", "length"), ("hooks", "hook"),
                             ("closes", "close"), ("voices", "voice")):
            rows = report[group]
            if not rows:
                continue
            print(f"\n  by {label}:")
            for row in rows:
                arrow = "more" if row["weight"] > 1.05 else \
                        "less" if row["weight"] < 0.95 else "same"
                print(f"    {row[label]:<22} weight {row['weight']:<5} {arrow:<5} "
                      f"(n={row['n']}, {row['confidence']})")
        print("\n  " + "\n  ".join(report["notes"]))

    if args.apply:
        applied = apply_to_preferences(report)
        print("\n  preferences updated: " + (", ".join(applied) if applied else "nothing solid enough"))
    return 0


def apply_to_preferences(report: dict) -> list[str]:
    """Only formats with real evidence cross over into the preferences file.

    `bias` is recomputed from numbers every time; `preferences.json` is what the user believes.
    Writing a one-post fluke into it would be putting an accident into their profile.
    """
    prefs = preferences.load()
    changed = []
    for row in report["formats"]:
        if row["confidence"] == "anecdote":
            continue
        name = row["format"]
        if row["weight"] >= 1.15:
            target, opposite = "formats.worked", "formats.failed"
        elif row["weight"] <= 0.85:
            target, opposite = "formats.failed", "formats.worked"
        else:
            continue
        current = preferences.dig(prefs, target) or []
        if name.lower() in [v.lower() for v in current]:
            continue
        preferences.put(prefs, target, current + [name])
        other = preferences.dig(prefs, opposite) or []
        preferences.put(prefs, opposite, [v for v in other if v.lower() != name.lower()])
        changed.append(f"{target} += {name}")
    if changed:
        preferences.save(prefs)
    return changed


# --------------------------------------------------------------------------- cli

def main() -> int:
    ap = argparse.ArgumentParser(
        prog="history.py",
        description="What got published and how it did, so the next proposal isn't a guess.")
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("log", help="record the variant the user actually uploaded")
    s.add_argument("--project", required=True, help="the run it came from, as a short name")
    s.add_argument("--format", required=True,
                   help="photo-dump, talking-head, 360-reveal, day-in-the-life, before-after…")
    s.add_argument("--variant", help="which of the run's variants (A, B, 2…)")
    s.add_argument("--platform", choices=PLATFORMS, default="tiktok")
    s.add_argument("--duration", type=float, help="length of the video, in seconds")
    s.add_argument("--hook", help="what the first 2 s do: question, claim, motion, reveal…")
    s.add_argument("--close",
                   help="how it ends: payoff, callback, reveal, punchline, open-loop, abrupt. "
                        "Worth recording even when it is 'abrupt' — that is the one to stop doing.")
    s.add_argument("--voice", help="the narration voice, by the name the user knows it by")
    s.add_argument("--music", help="the sound or trend used")
    s.add_argument("--language", help="BCP-47, if it wasn't the usual one")
    s.add_argument("--narration", action="store_true", help="it carried a voice-over")
    s.add_argument("--published", help="YYYY-MM-DD (the day it went up)")
    s.add_argument("--note", help="one line the user said about it")
    s.set_defaults(func=cmd_log)

    s = sub.add_parser("result", help="add the numbers the user reports")
    s.add_argument("id")
    for metric in METRICS:
        s.add_argument(f"--{metric.replace('_', '-')}", type=float if metric == "watch_pct" else int,
                       dest=metric, help=f"{metric.replace('_', ' ')} as the user reports it")
    s.add_argument("--days", type=int, help="days after publishing that these numbers are from")
    s.set_defaults(func=cmd_result)

    s = sub.add_parser("show", help="what has been published")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--platform", choices=PLATFORMS)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("bias", help="weights for the next proposal, from the numbers")
    s.add_argument("--platform", choices=PLATFORMS)
    s.add_argument("--json", action="store_true")
    s.add_argument("--apply", action="store_true",
                   help="also write the solid verdicts into preferences.json")
    s.set_defaults(func=cmd_bias)

    s = sub.add_parser("rm", help="remove an entry")
    s.add_argument("id")
    s.set_defaults(func=cmd_rm)

    sub.add_parser("path", help="print the file's path").set_defaults(
        func=lambda _a: (print(path()), 0)[1])

    args = ap.parse_args()
    try:
        return args.func(args)
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
