# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""What a viewer can USE about the places in a project: a price, an opening hour, how to get there,
the mistake everyone makes. Researched on the web, every one with its source.

Scored against the platform's best travel videos, ours lost the most on "a reason to save or send
it" (3.3 of 10) and on specific value (4.7): the references said "$41 the Skydeck, $5 the photo",
"30 min by train", "go at night, there is no line"; ours said "place · date". The catalog knows what
is in each frame; it does not know what the place costs. This file is where that lives.

It is NOT facts.py. facts.py holds what the USER said happened on the trip (who was there), and a
line that contradicts it is blocked. This holds what the WORLD says about a place, with a link and
a date — prices go stale, so every fact carries when it was checked.

    <project>/workspace/place_facts.json

    uv run place_facts.py --project DIR add "Tokyo Tower" "Main deck ¥1,200 adults" \\
        --kind price --source https://… --checked 2026-09-30
    uv run place_facts.py --project DIR show
    uv run place_facts.py --project DIR brief            # the block for a director's prompt
    uv run place_facts.py --project DIR places           # the places the catalog names, to research
    uv run place_facts.py --project DIR rm pf-004

Kinds: price · time (hours, how long, when to go) · how (getting there, booking) · tip ·
mistake (what to avoid) · number (a height, an age, a count). A fact without a source is refused:
an invented price said in the user's voice is worse than no price.

Exit codes: 0 ok, 2 bad arguments or no project.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

KINDS = ("price", "time", "how", "tip", "mistake", "number")
MAX_TEXT = 300


def store(project: Path) -> Path:
    ws = project / "workspace"
    if not ws.is_dir():
        sys.exit(f"place_facts: {project} has no workspace/ — is it a project folder?")
    return ws / "place_facts.json"


def load(p: Path) -> list[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("facts", [])
    except (OSError, ValueError):
        return []


def save(p: Path, facts: list[dict]):
    p.write_text(json.dumps({"schema": "place-facts/1", "facts": facts}, ensure_ascii=False, indent=1),
                 encoding="utf-8")


def catalog_places(project: Path) -> list[tuple[str, int]]:
    """The places the catalog names, most used first: what to research."""
    counts: dict[str, int] = {}
    for f in (project / "workspace" / "catalog").glob("*.json"):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = doc.get("items", doc) if isinstance(doc, dict) else doc
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            for key in ("place", "location", "city"):
                v = it.get(key)
                if isinstance(v, dict):
                    v = v.get("name") or v.get("city")
                if isinstance(v, str) and v.strip():
                    counts[v.strip()] = counts.get(v.strip(), 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", type=Path, required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("place")
    a.add_argument("text")
    a.add_argument("--kind", choices=KINDS, required=True)
    a.add_argument("--source", required=True, help="the URL the fact was read on")
    a.add_argument("--checked", default=date.today().isoformat(), help="YYYY-MM-DD it was read")
    sub.add_parser("show")
    sub.add_parser("brief")
    sub.add_parser("places")
    r = sub.add_parser("rm")
    r.add_argument("id")
    args = ap.parse_args()

    p = store(args.project.expanduser())
    facts = load(p)
    if args.cmd == "add":
        if not re.match(r"https?://", args.source):
            sys.exit("place_facts: --source must be the URL you read it on")
        if len(args.text) > MAX_TEXT:
            sys.exit(f"place_facts: keep a fact under {MAX_TEXT} characters — one usable thing")
        n = 1 + max((int(f["id"].split("-")[1]) for f in facts if f.get("id", "").startswith("pf-")), default=0)
        facts.append({"id": f"pf-{n:03d}", "place": args.place, "kind": args.kind, "text": args.text,
                      "source": args.source, "checked": args.checked})
        save(p, facts)
        print(f"pf-{n:03d} added")
    elif args.cmd == "rm":
        keep = [f for f in facts if f.get("id") != args.id]
        if len(keep) == len(facts):
            sys.exit(f"place_facts: no {args.id}")
        save(p, keep)
    elif args.cmd == "places":
        for name, k in catalog_places(args.project.expanduser()):
            have = sum(1 for f in facts if f["place"].lower() == name.lower())
            print(f"{k:4}  {name}" + (f"  ({have} facts)" if have else ""))
    elif args.cmd == "show":
        print(json.dumps(facts, ensure_ascii=False, indent=1))
    else:
        if not facts:
            print("No place facts yet. Research them (trend-researcher, job `place facts`) before the "
                  "concepts: every beat of a guide, a list or a route needs one usable thing.")
            return 0
        print("PLACE FACTS — usable things a viewer can save; each one sourced. Say them as facts "
              "(\"la entrada cuesta…\"), never as what the user paid unless the user said so; never "
              "invent one that is not here.")
        by: dict[str, list[dict]] = {}
        for f in facts:
            by.setdefault(f["place"], []).append(f)
        for place, fs in by.items():
            print(f"- {place}")
            for f in fs:
                print(f"    [{f['id']} {f['kind']}] {f['text']}  (checked {f['checked']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
