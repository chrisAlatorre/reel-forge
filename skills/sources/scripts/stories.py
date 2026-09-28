# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""What the user REMEMBERS about one project, in their own words: the raw material of a story.

    uv run stories.py --project DIR questions [--lang es]      # the interview to send the user
    uv run stories.py --project DIR add --q 2 "Lo que más risa me dio fue…"
    uv run stories.py --project DIR from-audio note.m4a [--q 2] # a voice note, transcribed
    uv run stories.py --project DIR show
    uv run stories.py --project DIR brief                       # the block for an agent prompt
    uv run stories.py --project DIR rm s-003

Why it exists. Three rounds of well-made videos were judged "fine, but something is missing — a
more human touch, something that grabs me". Everything in them came from what a camera recorded
and what an agent could infer: clever devices (scoreboards, quizzes, clocks) over good-looking
shots, read by a synthetic voice. Nothing came from what the person lived. The one input no agent
can produce is the user's memory — the funny thing, the thing that went wrong, the stranger who
explained everything — so the round starts by asking for it, and every concept anchors on it.

How it differs from facts.py. A fact CONSTRAINS what a video may say ("he was not alone"). A story
FEEDS it: a line the narration can say in the user's own words, a moment to build a hook on. Both
live beside the project's workspace, both are local and never uploaded, and both keep only what the
user said — never an inference, never a feeling attributed to them that they did not voice.

    <project>/stories.json          (0600)

Exit codes: 0 fine, 2 bad arguments or no project.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import facts  # noqa: E402  (project resolution and the privacy guard are shared)

FILENAME = "stories.json"
MAX_TEXT = 2000

# The interview. Short, concrete, answerable from the phone in a voice note. They ask for moments
# and feelings the camera cannot see, not for facts the catalog already has.
QUESTIONS = {
    "es": [
        "¿Cuál fue el mejor momento del viaje, y por qué?",
        "¿Qué te dio más risa, o qué salió mal?",
        "¿Qué te sorprendió que no esperabas?",
        "¿Alguien que recuerdes? ¿Qué pasó? (sin datos privados)",
        "¿En qué momento te sentiste más lejos de casa, o más en casa?",
        "Si le contaras a un amigo una sola historia del viaje, ¿cuál sería?",
    ],
    "en": [
        "What was the best moment of the trip, and why?",
        "What made you laugh the most, or what went wrong?",
        "What surprised you that you did not expect?",
        "Anyone you remember? What happened? (no private details)",
        "When did you feel furthest from home, or most at home?",
        "If you told a friend just one story from the trip, which would it be?",
    ],
}


def path(project: Path) -> Path:
    return project / FILENAME


def load(project: Path) -> dict:
    f = path(project)
    if not f.exists():
        return {"version": 1, "stories": []}
    return json.loads(f.read_text(encoding="utf-8"))


def save(project: Path, data: dict) -> Path:
    f = path(project)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkstemp(dir=f.parent, prefix=".stories-")[1])
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(f)
    return f


def guard(text: str) -> str:
    """The privacy refusals of preferences.py (no paths, uuids, e-mails, phones, credentials), with
    room for a voice note: a memory runs longer than a fact."""
    text = " ".join(str(text).split())
    if not text:
        raise SystemExit("stories: the story is empty.")
    for rx, what in facts.preferences.SENSITIVE:
        hit = rx.search(text)
        if hit:
            raise SystemExit(f"stories: that contains what looks like {what} ({hit.group(0)!r}); "
                             "leave it out and keep the rest.")
    return text[:MAX_TEXT]


def add(project: Path, text: str, q=None, source="text", lang="es") -> str:
    text = guard(text)
    data = load(project)
    n = 1 + max([int(s["id"].split("-")[1]) for s in data["stories"]] or [0])
    sid = f"s-{n:03d}"
    qs = QUESTIONS.get(lang[:2], QUESTIONS["es"])
    entry = {"id": sid, "said": text, "source": source,
             "added": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")}
    if q:
        entry["question"] = qs[int(q) - 1] if str(q).isdigit() and 0 < int(q) <= len(qs) else str(q)
    data["stories"].append(entry)
    save(project, data)
    return sid


def transcribe(audio: Path, lang="es") -> str:
    tr = Path(__file__).resolve().parents[2] / "video-engine" / "scripts" / "transcribe.py"
    out = Path(tempfile.mkdtemp(prefix="rf-story-")) / "t.json"
    subprocess.run(["uv", "run", "-q", str(tr), str(audio), "--language", lang[:2], "--out", str(out)],
                   check=True, capture_output=True, text=True)
    data = json.loads(out.read_text())
    return " ".join(s["text"].strip() for s in data.get("raw", []) if s.get("text"))


def cmd_questions(a) -> int:
    for i, q in enumerate(QUESTIONS.get(a.lang[:2], QUESTIONS["es"]), 1):
        print(f"{i}. {q}")
    return 0


def cmd_add(a) -> int:
    print(add(facts.project_dir(a.project), a.text, a.q, "text", a.lang), "saved")
    return 0


def cmd_from_audio(a) -> int:
    text = transcribe(Path(a.audio), a.lang)
    if not text:
        print("stories: nothing intelligible in that audio", file=sys.stderr)
        return 2
    sid = add(facts.project_dir(a.project), text, a.q, f"voice note {Path(a.audio).name}", a.lang)
    print(f"{sid} saved: {text[:160]}")
    return 0


def cmd_show(a) -> int:
    data = load(facts.project_dir(a.project))
    if a.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0
    for s in data["stories"]:
        print(f"{s['id']}  {('[' + s['question'] + '] ') if s.get('question') else ''}{s['said']}")
    return 0


def cmd_brief(a) -> int:
    data = load(facts.project_dir(a.project))
    if not data["stories"]:
        print("No stories from the user for this project (he may have preferred not to answer). Anchor "
              "every concept instead on the top of the best-moments ranking — `rank_moments.py "
              "--catalog <catalog>` — the real laughs, reactions and voices; never invent a memory.")
        return 0
    print("What the user remembers about this trip, IN THEIR OWN WORDS. Anchor every concept on at "
          "least one of these (its id in `anchor_story`). Narration may say them in first person, "
          "tightened but faithful; never add a feeling or an event they did not say.")
    for s in data["stories"]:
        q = f" (to: {s['question']})" if s.get("question") else ""
        print(f"- {s['id']}{q}: «{s['said']}»")
    return 0


def cmd_rm(a) -> int:
    project = facts.project_dir(a.project)
    data = load(project)
    before = len(data["stories"])
    data["stories"] = [s for s in data["stories"] if s["id"] != a.id]
    if len(data["stories"]) == before:
        print(f"stories: no {a.id}", file=sys.stderr)
        return 2
    save(project, data)
    print(f"{a.id} removed")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project")
    ap.add_argument("--lang", default=os.environ.get("REEL_FORGE_LANG", "es"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("questions")
    s = sub.add_parser("add"); s.add_argument("text"); s.add_argument("--q")
    s = sub.add_parser("from-audio"); s.add_argument("audio"); s.add_argument("--q")
    s = sub.add_parser("show"); s.add_argument("--json", action="store_true")
    sub.add_parser("brief")
    s = sub.add_parser("rm"); s.add_argument("id")
    a = ap.parse_args()
    return {"questions": cmd_questions, "add": cmd_add, "from-audio": cmd_from_audio,
            "show": cmd_show, "brief": cmd_brief, "rm": cmd_rm}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
