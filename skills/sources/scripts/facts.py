# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""What is TRUE about one project: who was there, where, when, what happened.

Two different kinds of correction look alike and must not be stored together:

  * "I don't want to be in every shot" is about how the USER likes videos. It is true next month
    and next trip. It goes in preferences.py, which is global.
  * "that guy is my friend, he travelled with me until the last city" is about what
    HAPPENED on THIS trip. It is false on the next one. It goes here.

Storing the second kind as a preference is a bug with a delay: the next project inherits a fact
about a trip it has nothing to do with, and applies it as if it were true.

Only what the user SAID goes in — never what was inferred. A date read off the catalog and stored
as a fact turns into a claim the video makes in the user's name that nobody confirmed.

The file is local to the project, beside its workspace, never in the plugin and never uploaded:

    <project>/facts.json            (0600; the project is the folder that holds workspace/)

    uv run facts.py --project DIR show
    uv run facts.py --project DIR brief                    # the block for an agent prompt
    uv run facts.py --project DIR add "He travelled with his friend from the start" \\
        --about people --when 2026-07-31..2026-08-16 \\
        --forbid '\\b(llegu[ée]|viaj[ée])\\b[^.!?]{0,40}\\bsol[oa]\\b' --allow-if 'Oporto|Porto' \\
        --said "ese es mi amigo, viajó conmigo"
    uv run facts.py --project DIR check voice-script.json spec.json concept.json
    uv run facts.py --project DIR rm f-002
    uv run facts.py --project DIR adopt-rule r-006         # move a misfiled rule out of preferences

`check` is the backstop, not the judgement. It flags the phrasings a fact forbids — "llegué solo"
when he was not alone — in every line of narration and every caption, unless the same line matches
the fact's `--allow-if` (being alone IS true in the last city). The judgement is the story-doctor's,
which reads `brief` and has to square the whole script with it. What `check` guarantees is that the
one sentence the user already corrected cannot ship again.

Exit codes: 0 clean, 1 a line contradicts a fact, 2 bad arguments or no project.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preferences  # noqa: E402  (same folder: the privacy guard is shared on purpose)

VERSION = 1
FILENAME = "facts.json"
ENV_PROJECT = "REEL_FORGE_PROJECT"
ABOUT = ("people", "itinerary", "event", "place", "other")
MAX_TEXT = 400
MAX_PATTERN = 200


class Refused(ValueError):
    pass


# --------------------------------------------------------------------------- privacy

def guard(text: str, field: str) -> str:
    """Same refusals as preferences.py — no paths, UUIDs, emails, phones or credentials — but a fact
    can be longer than a rule, and it is allowed to name people and places: it never leaves the
    project folder."""
    text = " ".join(str(text).split())
    if not text:
        raise Refused(f"The {field} is empty.")
    if len(text) > MAX_TEXT:
        raise Refused(f"The {field} is longer than {MAX_TEXT} characters. One fact, one sentence.")
    for pattern, what in preferences.SENSITIVE:
        hit = pattern.search(text)
        if hit:
            raise Refused(f"That {field} contains what looks like {what} ({hit.group(0)!r}). A fact "
                          "says what happened; it never points at a file or an identifier.")
    return text


def pattern(expr: str, field: str) -> str:
    expr = str(expr).strip()
    if not expr:
        raise Refused(f"The {field} is empty.")
    if len(expr) > MAX_PATTERN:
        raise Refused(f"The {field} is longer than {MAX_PATTERN} characters.")
    try:
        re.compile(expr, re.I)
    except re.error as e:
        raise Refused(f"The {field} is not a valid regular expression: {e}")
    return expr


# --------------------------------------------------------------------------- the project

def project_dir(given: str | None) -> Path:
    """--project, then $REEL_FORGE_PROJECT, then the nearest folder up from here that holds a
    facts.json or a workspace/run.json. Never a guess: no project found is an error."""
    for cand in (given, os.environ.get(ENV_PROJECT)):
        if cand:
            p = Path(cand).expanduser().resolve()
            if not p.is_dir():
                raise SystemExit(f"facts: {p} is not a folder.")
            return p
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / FILENAME).exists() or (d / "workspace" / "run.json").exists():
            return d
    raise SystemExit("facts: no project. Pass --project <the folder that holds workspace/>, or set "
                     f"${ENV_PROJECT}. Facts belong to one project and are never guessed.")


def path(project: Path) -> Path:
    return project / FILENAME


def load(project: Path) -> dict:
    p = path(project)
    if not p.exists():
        return {"version": VERSION, "updated": None, "facts": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"facts: {p} could not be read ({e}). Fix or remove it; it is not "
                         "rebuilt on its own because it holds what the user told us.")
    data.setdefault("facts", [])
    return data


def save(project: Path, data: dict) -> Path:
    data["version"] = VERSION
    data["updated"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    p = path(project)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".facts-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return p


def next_id(data: dict) -> str:
    nums = [int(f["id"][2:]) for f in data["facts"] if re.fullmatch(r"f-\d+", f.get("id", ""))]
    return f"f-{(max(nums) + 1 if nums else 1):03d}"


# --------------------------------------------------------------------------- reading text out

def texts_of(file: Path) -> list[tuple[str, str]]:
    """[(where, text)] out of a voice-script, a render spec, a concept, a timeline or plain text."""
    raw = file.read_text(encoding="utf-8", errors="ignore")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [(f"{file.name}:{i}", ln.strip()) for i, ln in enumerate(raw.splitlines(), 1)
                if ln.strip()]
    out = []

    def walk(node, where):
        if isinstance(node, dict):
            for k, v in node.items():
                # only the keys that end up SAID or SHOWN; ids, paths and notes are not claims
                if k in ("text", "hook_text", "title", "line", "says", "close_text", "caption",
                         "promise", "what", "turn", "narration") and isinstance(v, str):
                    out.append((f"{where}.{k}", v))
                elif isinstance(v, (dict, list)):
                    walk(v, f"{where}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                if isinstance(v, str):      # lines.json: the plain list of sentences voice.py reads
                    out.append((f"{where}[{i}]", v))
                else:
                    walk(v, f"{where}[{i}]")

    walk(data, file.name)
    return out


# --------------------------------------------------------------------------- commands

def cmd_path(a) -> int:
    print(path(project_dir(a.project)))
    return 0


def cmd_show(a) -> int:
    project = project_dir(a.project)
    data = load(project)
    if a.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(f"FACTS  {path(project)}" + ("" if path(project).exists() else "   (not written yet)"))
    print("=" * 60)
    if not data["facts"]:
        print("  None yet. They get written when the user corrects WHAT HAPPENED.")
        return 0
    for f in data["facts"]:
        scope = " · ".join(x for x in (f.get("when"), f.get("where")) if x)
        print(f"  [{f['id']}] {f.get('about', 'other'):<9} {f['text']}" + (f"   ({scope})" if scope else ""))
        for p in f.get("forbid", []):
            print(f"           forbids /{p}/" + (f"  unless /{f['allow_if']}/" if f.get("allow_if") else ""))
    return 0


def cmd_brief(a) -> int:
    """The block the orchestrator pastes into every agent that writes words: directors, the
    story-doctor, builders and the critic. It is short and it is binding."""
    project = project_dir(a.project)
    facts = load(project)["facts"]
    if not facts:
        print("(no project facts recorded)")
        return 0
    print("Facts about this project, confirmed by the user. The narration, the captions and the "
          "descriptions must not contradict any of them:")
    for f in facts:
        scope = ", ".join(x for x in (f.get("when"), f.get("where")) if x)
        print(f"- {f['text']}" + (f" ({scope})" if scope else ""))
    return 0


def cmd_add(a) -> int:
    project = project_dir(a.project)
    data = load(project)
    fact = {"id": next_id(data), "text": guard(a.text, "fact"), "about": a.about,
            "created": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")}
    if a.when:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(\.\.\d{4}-\d{2}-\d{2})?", a.when):
            raise Refused("--when is a date or a range: 2026-07-31 or 2026-07-31..2026-08-16")
        fact["when"] = a.when
    if a.where:
        fact["where"] = guard(a.where, "place")
    if a.forbid:
        fact["forbid"] = [pattern(p, "--forbid") for p in a.forbid]
    if a.allow_if:
        fact["allow_if"] = pattern(a.allow_if, "--allow-if")
    if a.said:
        fact["said"] = guard(a.said, "quote")
    data["facts"].append(fact)
    print(f"{fact['id']} saved in {save(project, data)}")
    return 0


def cmd_rm(a) -> int:
    project = project_dir(a.project)
    data = load(project)
    before = len(data["facts"])
    data["facts"] = [f for f in data["facts"] if f["id"] != a.id]
    if len(data["facts"]) == before:
        print(f"facts: there is no {a.id}", file=sys.stderr)
        return 2
    save(project, data)
    print(f"{a.id} removed")
    return 0


def cmd_check(a) -> int:
    project = project_dir(a.project)
    facts = [f for f in load(project)["facts"] if f.get("forbid")]
    lines = []
    for f in a.files:
        p = Path(f)
        if not p.exists():
            print(f"facts: {p} does not exist", file=sys.stderr)
            return 2
        lines += texts_of(p)
    bad = []
    for where, text in lines:
        for fact in facts:
            allow = fact.get("allow_if")
            if allow and re.search(allow, text, re.I):
                continue
            for p in fact["forbid"]:
                if re.search(p, text, re.I):
                    bad.append({"where": where, "text": text, "fact": fact["id"],
                                "contradicts": fact["text"]})
                    break
    report = {"project": str(project), "lines": len(lines), "facts_checked": len(facts),
              "ok": not bad, "contradictions": bad}
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print(f"{len(lines)} line(s) against {len(facts)} fact(s) with forbidden phrasings")
        for b in bad:
            print(f"  ✗ {b['where']}: {b['text']!r}\n      contradicts [{b['fact']}] {b['contradicts']}")
        if not bad:
            print("  ✓ nothing contradicts a recorded fact")
    return 1 if bad else 0


def cmd_adopt_rule(a) -> int:
    """Moves a rule that was filed as a global preference but is really a fact of this project."""
    project = project_dir(a.project)
    prefs = preferences.load()
    rule = next((r for r in prefs.get("rules", []) if r.get("id") == a.rule), None)
    if rule is None:
        print(f"facts: preferences has no rule {a.rule}", file=sys.stderr)
        return 2
    data = load(project)
    fact = {"id": next_id(data), "text": guard(rule["text"], "fact"), "about": a.about,
            "created": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "moved_from": f"preferences {rule['id']}"}
    if rule.get("said"):
        fact["said"] = guard(rule["said"], "quote")
    data["facts"].append(fact)
    save(project, data)
    prefs["rules"] = [r for r in prefs["rules"] if r.get("id") != a.rule]
    preferences.save(prefs)
    print(f"{a.rule} moved out of the global preferences into {fact['id']} of {path(project)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", help="the project folder (the one that holds workspace/)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("path")
    s = sub.add_parser("show"); s.add_argument("--json", action="store_true")
    sub.add_parser("brief")
    s = sub.add_parser("add")
    s.add_argument("text")
    s.add_argument("--about", choices=ABOUT, default="other")
    s.add_argument("--when", help="YYYY-MM-DD or YYYY-MM-DD..YYYY-MM-DD")
    s.add_argument("--where")
    s.add_argument("--forbid", action="append", help="regex of a phrasing that contradicts it; repeatable")
    s.add_argument("--allow-if", dest="allow_if", help="regex: the line is fine if it also matches this")
    s.add_argument("--said", help="the user's own words, verbatim")
    s = sub.add_parser("rm"); s.add_argument("id")
    s = sub.add_parser("check"); s.add_argument("files", nargs="+"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("adopt-rule"); s.add_argument("rule")
    s.add_argument("--about", choices=ABOUT, default="people")
    a = ap.parse_args()
    try:
        return {"path": cmd_path, "show": cmd_show, "brief": cmd_brief, "add": cmd_add,
                "rm": cmd_rm, "check": cmd_check, "adopt-rule": cmd_adopt_rule}[a.cmd](a)
    except Refused as e:
        print(f"facts: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
