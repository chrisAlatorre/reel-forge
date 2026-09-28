# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""The best moments of a trip, ranked by what makes a person stop scrolling — not by how pretty.

    uv run rank_moments.py --catalog catalog.json [--top 40] [--json out.json]

When the user would rather not answer the interview ("instead of random, rank the best moments"),
this is what the concepts anchor on: every usable moment scored from the catalog's `human` signals,
highest first. A laugh, a reaction, a real voice and a moment where something HAPPENS outrank the
prettiest empty skyline; hook and favourite break the ties.

    score = emotion + 2·reaction + 2·real voice + candid + story_potential + hook/2 + favourite

Emotion weights: laughter 5, surprise 4, joy 3, awe 3, tender 3, fear 3, tension 3, pride 2, none 0.
Moments marked `use: false` or `missing` never rank. Exit 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EMOTION = {"laughter": 5, "surprise": 4, "joy": 3, "awe": 3, "tender": 3, "fear": 3, "tension": 3,
           "pride": 2, "none": 0}


def score(it: dict) -> float:
    h = it.get("human") or {}
    return round(EMOTION.get(h.get("emotion") or "none", 0)
                 + 2 * bool(h.get("reaction")) + 2 * bool(h.get("real_voice")) + bool(h.get("candid"))
                 + float(h.get("story_potential") or 0) + float(it.get("hook") or 0) / 2
                 + bool(it.get("favorite")), 2)


def rank(items, top=40):
    ok = [it for it in items if it.get("use", True) is not False and not it.get("missing")
          and it.get("human")]
    ranked = sorted(ok, key=lambda it: (-score(it), it.get("date", ""), it["id"]))[:top]
    return [{"rank": n, "id": it["id"], "score": score(it), "type": it.get("type"),
             "date": it.get("date"), "emotion": (it.get("human") or {}).get("emotion"),
             "real_voice": (it.get("human") or {}).get("real_voice"),
             "what": (it.get("description") or "")[:200]} for n, it in enumerate(ranked, 1)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args()
    doc = json.loads(Path(a.catalog).read_text())
    items = doc["items"] if isinstance(doc, dict) else doc
    out = rank(items, a.top)
    if not out:
        print("rank_moments: no moment carries `human` yet — run the catalog's human pass first",
              file=sys.stderr)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for m in out:
        voice = f' · voz: «{m["real_voice"][:60]}»' if m.get("real_voice") else ""
        print(f'{m["rank"]:>3}. {m["id"]:<22} {m["score"]:>5}  {m["emotion"] or "-":<9} {m["what"][:90]}{voice}')


if __name__ == "__main__":
    main()
