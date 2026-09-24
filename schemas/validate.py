# /// script
# requires-python = ">=3.10"
# dependencies = ["jsonschema>=4.21"]
# ///
"""Checks that a file an agent wrote actually honours its contract.

Every artifact that travels between reel-forge agents is JSON with a schema in this folder. An
agent that improvises the format forces its batch to be redone, and the failure shows up late:
a narrated variant delivered without voice because the script was free text nobody could parse.

    uv run schemas/validate.py workspace/catalog/catalog-day-03.json --type catalog-item
    uv run schemas/validate.py concepts/empty-square.json            --type concept
    uv run schemas/validate.py .../A/result.json                     --type variant-build-result
    uv run schemas/validate.py .../review.json                       --type review-result
    uv run schemas/validate.py .../voice-script.json                 --type voice-script
    uv run schemas/validate.py .../story/<concept>.json              --type story-review

    uv run schemas/validate.py <file>                  # --type auto: guessed from the file name
    uv run schemas/validate.py <file> --type concept --catalog workspace/catalog/catalog.json

`--type catalog-item` takes a single item, a list of items, or the whole batch file
(`{"batch": ..., "items": [...]}`), and says which item failed.

`--catalog` cross-checks that every catalog id a concept or a build result uses exists and is
`use: true`. That is the check that catches a concept written around material nobody cataloged.

On top of the schema it runs the few rules JSON Schema cannot express: duplicate ids, ranges that
end before they start, narration lines out of order or stepping on each other, a subject count
above what the concept declared.

Exit code 0 if it complies, 1 if it does not, 2 if it could not even be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - uv installs it
    sys.exit("validate.py: jsonschema is missing. Run it with: uv run schemas/validate.py ...")

HERE = Path(__file__).resolve().parent

TYPES = {
    "catalog-item": "catalog-item.schema.json",
    "concept": "concept.schema.json",
    "variant-build-result": "variant-build-result.schema.json",
    "review-result": "review-result.schema.json",
    "voice-script": "voice-script.schema.json",
    "story-review": "story-review.schema.json",
}

# Only for --type auto. A name that matches nothing is not guessed at: it is asked about.
HINTS = (
    ("voice-script", "voice-script"),
    ("voice_script", "voice-script"),
    ("story", "story-review"),
    ("review", "review-result"),
    ("result", "variant-build-result"),
    ("build", "variant-build-result"),
    ("catalog", "catalog-item"),
    ("concept", "concept"),
)


def die(msg: str, code: int = 2) -> None:
    print(f"validate.py: {msg}", file=sys.stderr)
    raise SystemExit(code)


def load_schema(kind: str) -> dict:
    path = HERE / TYPES[kind]
    if not path.exists():
        die(f"the schema {path.name} is not in {HERE}")
    return json.loads(path.read_text())


def guess_type(path: Path) -> str:
    name = path.name.lower()
    for hint, kind in HINTS:
        if hint in name:
            return kind
    die(f"cannot guess the type from '{path.name}'. Pass --type ({', '.join(TYPES)})")
    return ""  # unreachable


def where(err) -> str:
    return "/".join(str(p) for p in err.absolute_path) or "(root)"


def schema_errors(schema: dict, instance, root_ref: str | None = None) -> list[str]:
    """Validates `instance`; with root_ref, against that $def instead of the root."""
    if root_ref:
        schema = {k: v for k, v in schema.items() if k != "$ref"}
        schema["$ref"] = root_ref
    validator = Draft202012Validator(schema)
    return [f"{where(e)}: {e.message}" for e in sorted(validator.iter_errors(instance), key=where)]


# ─────────────────────────────────────────────── the checks JSON Schema cannot express

def check_catalog(items: list[dict]) -> list[str]:
    out, seen = [], {}
    for i, it in enumerate(items):
        tag = it.get("id", f"#{i}")
        if tag in seen:
            out.append(f"{tag}: duplicate id (also at position {seen[tag]}). One id, one moment.")
        seen[tag] = i
        s, e = it.get("start_s"), it.get("end_s")
        if s is not None and e is not None:
            if e <= s:
                out.append(f"{tag}: end_s ({e}) is not after start_s ({s}).")
            elif e - s < 0.8 and it.get("use", True):
                out.append(f"{tag}: the window is {e - s:.2f} s. Under 0.8 s it carries no caption and no stamp.")
    ranges: dict[str, list] = {}
    for it in items:
        if it.get("start_s") is not None and it.get("use", True):
            ranges.setdefault(it.get("path", ""), []).append(it)
    for path, group in ranges.items():
        group.sort(key=lambda x: x["start_s"])
        for a, b in zip(group, group[1:]):
            if b["start_s"] < a.get("end_s", 0):
                out.append(
                    f"{a.get('id')} and {b.get('id')}: their windows overlap in {path}. "
                    "Ranges of one file do not overlap."
                )
    return out


ARC_ORDER = ("hook", "development", "turn", "close")
MAX_BEAT_GAP_S = 5.0    # agents/story-doctor.md: a bigger gap is where the viewer leaves


def check_arc(c: dict) -> list[str]:
    """The arc rules `agents/story-doctor.md` states and JSON Schema cannot express.

    This is the check that exists because of one complaint: the videos open something, never
    develop it and stop mid-air. A concept can satisfy every field of the schema and still be that
    video, so the shape of the arc is verified here, against the concept's own declared seconds.
    """
    out = []
    arc = c.get("arc") or {}
    if not arc:
        return out
    target = c.get("target_duration_s") or 0
    blocks = c.get("structure") or []
    end = blocks[-1].get("t1", target) if blocks else target

    beats = arc.get("development") or []
    for a, b in zip(beats, beats[1:]):
        if b.get("at_s", 0) <= a.get("at_s", 0):
            out.append(f"arc.development: the beat at {b.get('at_s')} s does not come after the one "
                       f"at {a.get('at_s')} s. The beats go in the order they play.")
        elif b["at_s"] - a["at_s"] > MAX_BEAT_GAP_S and not (a.get("mini_hook") or "").strip():
            # A long beat is not the problem; a long beat with nothing pulling the viewer forward
            # is. `mini_hook` is exactly that pull, so a beat that carries one may run as long as
            # its material holds — which is what lets a documentary beat sit at 7 s and a gag not.
            out.append(f"arc.development: {b['at_s'] - a['at_s']:.1f} s between the beat at "
                       f"{a['at_s']} s and the next one, with no `mini_hook` to hold the viewer "
                       f"across it. Over {MAX_BEAT_GAP_S:g} s of nothing new is where they leave: "
                       "split the beat, or give it the reason to stay for the next one.")
    raises = [b.get("raises", "").strip().lower() for b in beats if b.get("raises")]
    if len(raises) != len(set(raises)):
        out.append("arc.development: two beats raise the same thing. That is one beat played twice, "
                   "and it reads as nothing happening.")

    paid = (arc.get("promise") or {}).get("paid_off_at_s")
    if paid is not None and end:
        if paid > end + 0.5:
            out.append(f"arc.promise.paid_off_at_s is {paid} s and the video ends at {end:.1f} s. "
                       "A promise paid after the last frame is a promise never paid.")
        elif paid < end / 3:
            out.append(f"arc.promise.paid_off_at_s is {paid} s, inside the first third of "
                       f"{end:.1f} s. Pay it off in the close or in the turn before it; paid early, "
                       "everything after it is epilogue and the viewer swipes.")

    hook_ends = (arc.get("hook") or {}).get("ends_s")
    hook_blocks = [b for b in blocks if b.get("role") == "hook"]
    if hook_ends is not None and hook_blocks:
        played = max(b.get("t1", 0) for b in hook_blocks)
        if abs(played - hook_ends) > 0.5:
            out.append(f"arc.hook.ends_s says {hook_ends} s and the blocks with role 'hook' run to "
                       f"{played:.2f} s. The arc and the structure are on the same clock.")

    for name in ("turn", "close"):
        at = (arc.get(name) or {}).get("at_s")
        if at is not None and end and at > end + 0.5:
            out.append(f"arc.{name}.at_s is {at} s, past the end of the video ({end:.1f} s).")

    roles = [(i, b["role"]) for i, b in enumerate(blocks) if b.get("role")]
    if roles:
        if len(roles) != len(blocks):
            out.append(f"structure: {len(blocks) - len(roles)} block(s) carry no `role`. A cut that "
                       "serves no stage of the arc is the first one to get trimmed — say what it is for.")
        rank = [ARC_ORDER.index(r) for _i, r in roles if r in ARC_ORDER]
        if rank != sorted(rank):
            out.append("structure: the roles do not run hook → development → turn → close. A close "
                       "in the middle is not a close.")
        if roles[-1][1] != "close":
            out.append(f"structure: the last block's role is '{roles[-1][1]}', not 'close'. The video "
                       "stops on whatever was left over instead of landing on something chosen.")
        closing = sum(b.get("t1", 0) - b.get("t0", 0) for b in blocks if b.get("role") == "close")
        if closing and closing < 1.2:
            out.append(f"structure: the close gets {closing:.2f} s. Under ~1.2 s it goes by before it "
                       "reads, which is exactly what 'it ends too abruptly' means.")

    if c.get("narration") and blocks and not any(b.get("says") for b in blocks):
        out.append("narration is true and no block declares `says`. That field is what ties the voice "
                   "to the picture, and without it verify.py cannot check a single pairing.")

    lengths = [v.get("target_duration_s") for v in c.get("variants") or []
               if v.get("target_duration_s") is not None]
    if any(v.get("differs_in") == "duration" for v in c.get("variants") or []) and len(lengths) > 1:
        if max(lengths) - min(lengths) < 4:
            out.append(f"variants: one of them differs in duration and they all land within "
                       f"{max(lengths) - min(lengths):.1f} s of each other. That is the same video twice.")
    return out


def check_concept(c: dict) -> list[str]:
    out = check_arc(c)
    blocks = c.get("structure", [])
    for a, b in zip(blocks, blocks[1:]):
        if b.get("t0", 0) < a.get("t1", 0):
            out.append(f"structure: the block at {b.get('t0')} s starts before the previous one ends ({a.get('t1')} s).")
    for i, blk in enumerate(blocks):
        if blk.get("t1", 0) <= blk.get("t0", 0):
            out.append(f"structure/{i}: t1 is not after t0.")
        if blk.get("text") and blk.get("t1", 0) - blk.get("t0", 0) < 0.8:
            out.append(f"structure/{i}: on-screen text in a block of {blk.get('t1', 0) - blk.get('t0', 0):.2f} s. It cannot be read.")
    if blocks:
        total = blocks[-1].get("t1", 0)
        target = c.get("target_duration_s", 0)
        if target and abs(total - target) > max(3, target * 0.25):
            out.append(f"the structure runs {total:.1f} s and target_duration_s says {target} s.")
    quota = c.get("subject_quota") or {}
    subj = [b for b in blocks if b.get("subject")]
    if blocks and quota.get("max_ratio") is not None and "subject" in (blocks[0] or {}):
        ratio = len(subj) / len(blocks)
        if ratio > quota["max_ratio"] + 1e-9:
            out.append(
                f"subject_quota: the structure puts the subject in {len(subj)}/{len(blocks)} cuts "
                f"({ratio:.0%}) and the concept declared a ceiling of {quota['max_ratio']:.0%} ({quota.get('kind')})."
            )
    declared = set(c.get("resources") or [])
    used = {b["resource"] for b in blocks if b.get("resource")}
    if declared and used - declared:
        out.append(f"resources: the structure uses ids that are not listed: {', '.join(sorted(used - declared))}.")
    letters = [v.get("letter") for v in c.get("variants", [])]
    if len(set(letters)) != len(letters):
        out.append("variants: two variants share a letter.")
    axes = [v.get("differs_in") for v in c.get("variants", [])]
    if len(set(axes)) < len(axes):
        out.append("variants: two variants move on the same axis (differs_in). They will read the same.")
    return out


def check_voice_script(s: dict) -> list[str]:
    out = []
    lines = s.get("lines", [])
    for i, (a, b) in enumerate(zip(lines, lines[1:])):
        if b.get("start_s", 0) <= a.get("start_s", 0):
            out.append(f"lines/{i + 1}: starts at {b.get('start_s')} s, not after the previous line ({a.get('start_s')} s). They go in order.")
        hint = a.get("duration_hint_s")
        if hint and a.get("start_s", 0) + hint > b.get("start_s", 0) + 1e-9:
            out.append(
                f"lines/{i}: ends around {a['start_s'] + hint:.2f} s and the next one comes in at "
                f"{b.get('start_s')} s. Two voices at once."
            )
    dur = s.get("video_duration_s")
    if dur:
        for i, ln in enumerate(lines):
            if ln.get("start_s", 0) >= dur:
                out.append(f"lines/{i}: starts at {ln['start_s']} s, past the end of the video ({dur} s).")
    if lines and all(ln.get("duck") is False for ln in lines):
        out.append("every line has duck: false. If the music does not drop, the narration is what gets lost.")
    return out


def check_build_result(r: dict) -> list[str]:
    out = []
    cuts, subj = r.get("cuts", 0), r.get("cuts_with_subject", 0)
    if subj > cuts:
        out.append(f"cuts_with_subject ({subj}) is greater than cuts ({cuts}).")
    checks = r.get("checks") or {}
    if checks.get("peak_dbtp") is not None and checks["peak_dbtp"] > -0.5:
        out.append(f"checks: the real peak is {checks['peak_dbtp']} dBTP, above the -0.5 limit.")
    if checks.get("black_frames"):
        out.append(f"checks: {checks['black_frames']} black frames detected and the variant is being returned anyway.")
    a, v = checks.get("audio_duration_s"), checks.get("video_duration_s")
    if a is not None and v is not None and abs(a - v) > 0.5:
        out.append(f"checks: the audio runs {a} s and the video {v} s. The ending goes silent or the music is cut off.")
    if checks.get("audio_tracks") not in (None, 1):
        out.append(f"checks: {checks['audio_tracks']} audio tracks. A delivery carries exactly one.")
    if r.get("out_of_window"):
        out.append(f"out_of_window: {', '.join(r['out_of_window'])}. Every widened window needs the strip you looked at first, in notes.")
    return out


def check_review(r: dict) -> list[str]:
    out = []
    quota = r.get("subject_quota") or {}
    for v in quota.get("per_variant", []):
        if v.get("cuts"):
            ratio = v.get("cuts_with_subject", 0) / v["cuts"]
            if abs(ratio - v.get("ratio", ratio)) > 0.01:
                out.append(f"subject_quota/{v.get('letter')}: ratio says {v.get('ratio')} and the counts give {ratio:.2f}.")
            expected = ratio <= quota.get("max_ratio", 1) + 1e-9
            if quota.get("min_ratio") is not None:
                expected = expected and ratio >= quota["min_ratio"] - 1e-9
            if v.get("pass") != expected:
                out.append(f"subject_quota/{v.get('letter')}: pass is {v.get('pass')} but the ratio {ratio:.2f} against the declared ceiling says {expected}.")
    blocking = [p for p in r.get("problems", []) if p.get("severity") == "blocks" and p.get("status") == "open"]
    for p in blocking:
        if p.get("variant") in r.get("approved", []):
            out.append(f"approved: variant {p['variant']} is approved with an open blocking problem ({p.get('what')}).")
    if not r.get("language_ok", True):
        out.append("language_ok is false: copy in the wrong language blocks delivery, so this cannot be closed.")
    return out


def check_story(s: dict) -> list[str]:
    """The story-doctor's own rules, from agents/story-doctor.md."""
    out = []
    arc = s.get("arc") or {}
    paid = arc.get("promise_paid_off") or {}
    if paid.get("ok") and paid.get("at_s") is None:
        out.append("arc.promise_paid_off: ok is true and there is no at_s. The second the viewer gets "
                   "what they were promised is the whole answer; without it nothing was checked.")
    if paid.get("ok") is False and s.get("verdict") == "ship":
        out.append("verdict is 'ship' with the promise unpaid. That is the one defect that makes a "
                   "video feel cut off no matter how well it is edited: it cannot ship.")
    close = arc.get("close") or {}
    if close.get("ok") is False and s.get("verdict") == "ship":
        out.append("verdict is 'ship' with no close. A video that reaches its last clip stops, it "
                   "does not end.")
    blocking = [f for f in s.get("fixes", []) if f.get("level") == "blocks"]
    if blocking and s.get("verdict") == "ship":
        out.append(f"verdict is 'ship' and {len(blocking)} fix(es) are marked 'blocks'. Either they "
                   "are not blocking, or this is a 'rework'.")
    dur = s.get("duration") or {}
    rec, dec = dur.get("recommended_s"), dur.get("declared_s")
    if rec and dec and abs(rec - dec) > max(2.0, dec * 0.15) and not (dur.get("cut") or dur.get("lengthen")):
        out.append(f"duration: it recommends {rec} s against the {dec} s declared and names neither "
                   "what to cut nor what to lengthen. A different number with no seconds behind it "
                   "is a new template.")
    for i, v in enumerate(dur.get("per_variant") or []):
        if rec and v.get("recommended_s", 0) > rec * 2:
            out.append(f"duration/per_variant/{i}: variant {v.get('letter')} is given "
                       f"{v['recommended_s']} s against the concept's {rec} s. That is another video.")
    if s.get("pass") == "post" and not s.get("variants"):
        out.append("a 'post' pass says nothing about which variants it watched.")
    return out


def check_ids_against_catalog(used: set, catalog_path: Path) -> list[str]:
    try:
        doc = json.loads(catalog_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [f"--catalog: {catalog_path} could not be read ({exc})."]
    items = doc.get("items", doc) if isinstance(doc, dict) else doc
    if not isinstance(items, list):
        return [f"--catalog: {catalog_path} does not hold a list of items."]
    usable = {i.get("id") for i in items if isinstance(i, dict) and i.get("use", True)}
    known = {i.get("id") for i in items if isinstance(i, dict)}
    out = []
    missing = sorted(used - known)
    dropped = sorted((used & known) - usable)
    if missing:
        out.append(f"ids that are NOT in the catalog: {', '.join(missing)}. Inventing material invalidates the whole file.")
    if dropped:
        out.append(f"ids the catalog marked use: false: {', '.join(dropped)}. Say why in the notes or pick another moment.")
    return out


# ───────────────────────────────────────────────────────────────────────── run

def main() -> int:
    ap = argparse.ArgumentParser(description="Validates a reel-forge artifact against its schema.")
    ap.add_argument("file", type=Path)
    ap.add_argument("--type", "-t", default="auto", choices=["auto", *TYPES])
    ap.add_argument("--catalog", type=Path, help="catalog.json, to check that the ids used exist")
    ap.add_argument("--quiet", "-q", action="store_true", help="say nothing when it complies")
    args = ap.parse_args()

    if not args.file.exists():
        die(f"{args.file} does not exist")
    try:
        doc = json.loads(args.file.read_text())
    except json.JSONDecodeError as exc:
        die(f"{args.file} is not valid JSON: {exc}")

    kind = args.type if args.type != "auto" else guess_type(args.file)
    schema = load_schema(kind)
    errors: list[str] = []
    counted = ""

    if kind == "catalog-item":
        if isinstance(doc, dict) and "items" in doc:
            errors += schema_errors(schema, doc, "#/$defs/batch")
            items = doc.get("items") or []
        elif isinstance(doc, list):
            items = doc
            for i, it in enumerate(items):
                errors += [f"items/{i} -> {e}" for e in schema_errors(schema, it)]
        else:
            items = [doc]
            errors += schema_errors(schema, doc)
        if all(isinstance(i, dict) for i in items):
            errors += check_catalog(items)
            counted = f"{len(items)} items"
    else:
        errors += schema_errors(schema, doc)
        if isinstance(doc, dict):
            errors += {
                "concept": check_concept,
                "voice-script": check_voice_script,
                "variant-build-result": check_build_result,
                "review-result": check_review,
                "story-review": check_story,
            }[kind](doc)
            if kind == "voice-script":
                counted = f"{len(doc.get('lines', []))} lines"
            elif kind == "concept":
                counted = f"{len(doc.get('structure', []))} cuts, {len(doc.get('variants', []))} variants"

    if args.catalog and isinstance(doc, dict):
        used = set()
        if kind == "concept":
            used = {b["resource"] for b in doc.get("structure", []) if b.get("resource")} | set(doc.get("resources") or [])
            if (doc.get("hook") or {}).get("resource"):
                used.add(doc["hook"]["resource"])
        elif kind == "variant-build-result":
            used = set(doc.get("moments") or [])
        if used:
            errors += check_ids_against_catalog(used, args.catalog)

    if errors:
        print(f"{args.file}: does NOT comply with {kind} ({len(errors)} problems)")
        for e in errors:
            print(f"  - {e}")
        return 1

    if not args.quiet:
        print(f"{args.file}: complies with {kind}" + (f" ({counted})" if counted else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
