# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Per-user preferences that learn from corrections.

Everything the user corrects about a reel ("that pose again, no", "I don't want to be in every
shot", "that voice sounds robotic", "the photo dump worked, the talking-head didn't") belongs
here, as a rule, so the next run doesn't repeat the mistake. It is a single local file:

    ~/.config/reel-forge/preferences.json          ($REEL_FORGE_CONFIG_DIR overrides the folder)

created on first write, `0600`, never uploaded anywhere.

    uv run preferences.py show
    uv run preferences.py brief                       # the block to paste into an agent prompt
    uv run preferences.py get presence
    uv run preferences.py set presence low
    uv run preferences.py set voice "CapCut Valentino"      # the default when there is narration
    uv run preferences.py set length dynamic                # the concept decides how long it runs
    uv run preferences.py add voices.rejected "over-bright newsreader"
    uv run preferences.py add-rule "no arms-crossed poses" --kind avoid --topic pose
    uv run preferences.py rm-rule r-003

**What must never land in this file:** a path to a photo, a file name, a library UUID, an email
address, a phone number, a password or an API key. It stores *rules*, not material. Anything that
looks like one of those is refused with the reason, and the user is asked to phrase it as a rule
("no shots of me holding documents" instead of a path).
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

VERSION = 1

EXAMPLES = """examples:
  uv run preferences.py show
  uv run preferences.py brief
  uv run preferences.py set presence low
  uv run preferences.py set voice "CapCut Valentino"
  uv run preferences.py set length dynamic
  uv run preferences.py add voices.rejected "over-bright newsreader"
  uv run preferences.py add-rule "no arms-crossed poses" --kind avoid --topic pose
"""

ENV_CONFIG_DIR = "REEL_FORGE_CONFIG_DIR"
DEFAULT_CONFIG_DIR = "~/.config/reel-forge"
FILENAME = "preferences.json"

# How much the user wants to appear on screen. It is a dial, not a yes/no: "low" still lets a
# reel open on their face, it just stops every third shot from being a selfie.
PRESENCE = ("none", "rare", "low", "medium", "high")

# How long the user wants their videos. `dynamic` is the honest default: the concept decides,
# a 12 s joke stays 12 s and a story that needs 50 s gets 50 s. The fixed values are for a user
# who says outright "always keep them under 20 seconds".
LENGTH = ("short", "medium", "long", "dynamic")

# Scalar keys, with their validator. Anything outside this table has to be a rule or a list entry,
# which is what keeps the file from turning into a junk drawer.
SCALARS = {
    "language": ("BCP-47 tag: en, es-MX, pt-BR", re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")),
    "presence": (f"one of {', '.join(PRESENCE)}", None),
    "pace": ("slow, medium or fast", re.compile(r"^(slow|medium|fast)$")),
    "captions": ("on, off or sparse", re.compile(r"^(on|off|sparse)$")),
    "narration": ("on, off or sometimes", re.compile(r"^(on|off|sometimes)$")),
    "length": (f"one of {', '.join(LENGTH)}", None),
    "voice": ("the default narration voice, by the name the user calls it", None),
}

# List keys. `add` / `remove` work on these.
LISTS = (
    "voices.preferred",
    "voices.rejected",
    "formats.worked",
    "formats.failed",
    "music.preferred",
    "music.rejected",
)

RULE_KINDS = ("avoid", "prefer", "always", "never")
RULE_TOPICS = ("pose", "gesture", "topic", "framing", "voice", "music", "text", "pace",
               "format", "person", "place", "other")


# --------------------------------------------------------------------------- privacy guard

SENSITIVE = [
    (re.compile(r"(/Users/|/home/|[A-Za-z]:\\\\Users\\\\)[^\s/\\]+"), "a home folder path"),
    (re.compile(r"(?:(?:~|\.{1,2})/|(?<![\w])/)[\w.\-]+/[\w.\-]+"), "a file path"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"), "an email address"),
    (re.compile(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
                r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b"), "a library UUID"),
    (re.compile(r"\b(IMG|DSC|DCIM|PXL|VID|MVIMG|GOPR|GX\d\d|DJI|IMG_E)[_-]?\d{3,}\b", re.I),
     "a camera file name"),
    (re.compile(r"\.(jpe?g|heic|heif|png|tiff?|dng|mov|mp4|m4v|insv|insp|360|webp|avif)\b", re.I),
     "a file name"),
    (re.compile(r"(?<!\d)\+?\d[\d ().-]{8,}\d(?!\d)"), "a phone number"),
    (re.compile(r"\b(pass(word|wd)|api[_ -]?key|secret|token|bearer|cvv|iban)\b", re.I),
     "a credential"),
    (re.compile(r"\b\d{13,19}\b"), "a long number that could be a card"),
]

MAX_TEXT = 200


class Refused(ValueError):
    """The value carries something this file must not store."""


def guard(text: str, field: str = "value") -> str:
    """Refuses anything that looks like material, an identifier or a secret."""
    text = " ".join(str(text).split())
    if not text:
        raise Refused(f"The {field} is empty.")
    if len(text) > MAX_TEXT:
        raise Refused(f"The {field} is longer than {MAX_TEXT} characters. A rule is one sentence.")
    for pattern, what in SENSITIVE:
        hit = pattern.search(text)
        if hit:
            raise Refused(
                f"That {field} contains what looks like {what} ({hit.group(0)!r}).\n"
                "This file stores rules, not material: phrase it as something the editor can "
                "apply to any photo, for example 'no shots of me holding documents'."
            )
    return text


# --------------------------------------------------------------------------- the file

def config_dir() -> Path:
    return Path(os.environ.get(ENV_CONFIG_DIR) or DEFAULT_CONFIG_DIR).expanduser()


def path() -> Path:
    return config_dir() / FILENAME


def blank() -> dict:
    return {
        "version": VERSION,
        "updated": None,
        "language": None,
        "presence": None,
        "pace": None,
        "captions": None,
        "narration": None,
        "length": None,
        "voice": None,
        "voices": {"preferred": [], "rejected": []},
        "formats": {"worked": [], "failed": []},
        "music": {"preferred": [], "rejected": []},
        "rules": [],
    }


def load() -> dict:
    """Never fails: a missing or broken file comes back as an empty set of preferences."""
    p = path()
    data = blank()
    if not p.exists():
        return data
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"warning: {p} couldn't be read ({e}); starting from empty preferences.",
              file=sys.stderr)
        return data
    if not isinstance(raw, dict):
        return data
    for key, value in raw.items():
        if key in data and isinstance(data[key], dict) and isinstance(value, dict):
            data[key].update(value)
        else:
            data[key] = value
    data.setdefault("rules", [])
    return data


def save(data: dict) -> Path:
    """Atomic write, `0600`, folder `0700`. The file is the user's, not the project's."""
    data["version"] = VERSION
    data["updated"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".preferences-", suffix=".json")
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


# --------------------------------------------------------------------------- dotted access

def dig(data: dict, key: str):
    node = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def put(data: dict, key: str, value) -> None:
    parts = key.split(".")
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
        if not isinstance(node, dict):
            raise Refused(f"'{key}' can't be set: '{part}' is not a section.")
    node[parts[-1]] = value


def check_scalar(key: str, value: str) -> str:
    value = guard(value, f"value of '{key}'")
    if key == "presence" and value not in PRESENCE:
        raise Refused(f"'presence' is one of {', '.join(PRESENCE)}, not {value!r}.")
    if key == "length" and value not in LENGTH:
        raise Refused(
            f"'length' is one of {', '.join(LENGTH)}, not {value!r}.\n"
            "Unless the user actually asked for a fixed length, 'dynamic' is the right answer: "
            "the concept decides how long the video is.")
    rule = SCALARS.get(key)
    if rule and rule[1] and not rule[1].match(value):
        raise Refused(f"'{key}' expects {rule[0]}; got {value!r}.")
    return value


# --------------------------------------------------------------------------- commands

def cmd_show(args) -> int:
    data = load()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    p = path()
    print(f"PREFERENCES  {p}" + ("" if p.exists() else "   (not written yet)"))
    print("=" * 60)
    scalars = [(k, data.get(k)) for k in SCALARS if data.get(k)]
    if scalars:
        print("  " + " · ".join(f"{k}: {v}" for k, v in scalars))
    for key in LISTS:
        values = dig(data, key) or []
        if values:
            print(f"  {key}: " + ", ".join(values))
    rules = data.get("rules") or []
    if not rules:
        print("\n  No rules yet. They get written when the user corrects something.")
        return 0
    print(f"\n{len(rules)} rule(s):")
    for rule in rules:
        hits = f"  (applied {rule['hits']}x)" if rule.get("hits") else ""
        print(f"  [{rule['id']}] {rule['kind']:<6} {rule.get('topic', 'other'):<8} "
              f"{rule['text']}{hits}")
    return 0


def cmd_brief(args) -> int:
    """The block an orchestrator pastes into the prompt of every agent that decides something.

    Short on purpose: rules the agent can act on, no metadata, no ids unless asked.
    """
    data = load()
    lines = []
    head = [f"{k}={data[k]}" for k in SCALARS if data.get(k) and k not in ("voice", "length")]
    if head:
        lines.append("Viewer preferences: " + ", ".join(head))
    if data.get("voice"):
        lines.append(f"Default narration voice: {data['voice']}. "
                     "Use it whenever the video is narrated and the language matches; "
                     "if you use another one, say which and why in the variant README.")
    length = data.get("length")
    if length == "dynamic":
        lines.append("Length: the concept decides. Do not cut a story short to hit a template "
                     "length, and do not pad a short idea to fill one.")
    elif length:
        lines.append(f"Length: the user asked for {length} videos, but never at the cost of "
                     "the ending — a video that stops mid-thought is worse than a long one.")
    for key, label in (("voices.rejected", "Voices to avoid"),
                       ("voices.preferred", "Voices that work"),
                       ("formats.worked", "Formats that worked"),
                       ("formats.failed", "Formats that failed"),
                       ("music.rejected", "Music to avoid")):
        values = dig(data, key) or []
        if values:
            lines.append(f"{label}: " + ", ".join(values))
    hard = [r for r in data.get("rules", []) if r["kind"] in ("never", "avoid")]
    soft = [r for r in data.get("rules", []) if r["kind"] in ("always", "prefer")]
    if hard:
        lines.append("Never do this (the user said so):")
        lines += [f"- {r['text']}" + (f"  [{r['id']}]" if args.ids else "") for r in hard]
    if soft:
        lines.append("Do this when you can:")
        lines += [f"- {r['text']}" + (f"  [{r['id']}]" if args.ids else "") for r in soft]
    if not lines:
        print("(no preferences recorded yet)")
        return 0
    print("\n".join(lines))
    return 0


def cmd_get(args) -> int:
    value = dig(load(), args.key)
    if value is None:
        print("")
        return 1
    print(json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value)
    return 0


def cmd_set(args) -> int:
    data = load()
    key = args.key
    if key in LISTS or isinstance(dig(data, key), list):
        raise Refused(f"'{key}' is a list: use `add {key} \"...\"` or `remove {key} \"...\"`.")
    if key not in SCALARS:
        raise Refused(
            f"Unknown key '{key}'. Settable keys: {', '.join(sorted(SCALARS))}.\n"
            "Anything else that the user corrects goes in as a rule: `add-rule \"...\"`.")
    value = check_scalar(key, args.value)
    put(data, key, value)
    save(data)
    print(f"{key} = {value}")
    return 0


def cmd_add(args) -> int:
    data = load()
    key = args.key
    if key not in LISTS:
        raise Refused(f"'{key}' is not a list. Lists: {', '.join(LISTS)}.")
    value = guard(args.value, f"entry of '{key}'")
    current = dig(data, key) or []
    if value.lower() in [v.lower() for v in current]:
        print(f"{key}: already there")
        return 0
    put(data, key, current + [value])
    # The opposite list loses it: "this voice works now" cancels "this voice doesn't".
    section, leaf = key.split(".", 1)
    opposite = {"preferred": "rejected", "rejected": "preferred",
                "worked": "failed", "failed": "worked"}.get(leaf)
    if opposite:
        other = dig(data, f"{section}.{opposite}") or []
        kept = [v for v in other if v.lower() != value.lower()]
        if len(kept) != len(other):
            put(data, f"{section}.{opposite}", kept)
            print(f"  (dropped from {section}.{opposite})")
    save(data)
    print(f"{key} += {value}")
    return 0


def cmd_remove(args) -> int:
    data = load()
    current = dig(data, args.key)
    if not isinstance(current, list):
        raise Refused(f"'{args.key}' is not a list.")
    kept = [v for v in current if v.lower() != args.value.strip().lower()]
    if len(kept) == len(current):
        print(f"{args.key}: {args.value!r} wasn't there")
        return 1
    put(data, args.key, kept)
    save(data)
    print(f"{args.key} -= {args.value}")
    return 0


def next_id(rules: list) -> str:
    used = {int(m.group(1)) for r in rules
            if (m := re.match(r"^r-(\d+)$", str(r.get("id", ""))))}
    return f"r-{(max(used) + 1 if used else 1):03d}"


def cmd_add_rule(args) -> int:
    data = load()
    text = guard(args.text, "rule")
    said = guard(args.said, "quote") if args.said else None
    rules = data.setdefault("rules", [])
    for rule in rules:
        if rule["text"].lower() == text.lower():
            rule["hits"] = int(rule.get("hits", 0)) + 1
            rule["kind"] = args.kind
            save(data)
            print(f"[{rule['id']}] already existed; the user has now corrected it "
                  f"{rule['hits']} more time(s). It is not a hint any more.")
            return 0
    rule = {
        "id": next_id(rules),
        "kind": args.kind,
        "topic": args.topic,
        "text": text,
        "hits": 0,
        "created": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    if said:
        rule["said"] = said
    rules.append(rule)
    save(data)
    print(f"[{rule['id']}] {rule['kind']} {rule['topic']}: {rule['text']}")
    return 0


def cmd_rm_rule(args) -> int:
    data = load()
    rules = data.get("rules", [])
    kept = [r for r in rules if r["id"] != args.id]
    if len(kept) == len(rules):
        print(f"There is no rule {args.id}.", file=sys.stderr)
        return 1
    data["rules"] = kept
    save(data)
    print(f"{args.id} removed")
    return 0


def cmd_path(_args) -> int:
    print(path())
    return 0


# --------------------------------------------------------------------------- cli

def main() -> int:
    ap = argparse.ArgumentParser(
        prog="preferences.py",
        description="Per-user reel-forge preferences, learned from what the user corrects.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EXAMPLES,
    )
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("show", help="everything that is stored")
    s.add_argument("--json", action="store_true", help="the raw file")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("brief", help="the block to paste into an agent prompt")
    s.add_argument("--ids", action="store_true", help="print the rule ids as well")
    s.set_defaults(func=cmd_brief)

    s = sub.add_parser("get", help="read one key (dotted: voices.rejected)")
    s.add_argument("key")
    s.set_defaults(func=cmd_get)

    s = sub.add_parser("set", help=f"write one of: {', '.join(sorted(SCALARS))}")
    s.add_argument("key")
    s.add_argument("value")
    s.set_defaults(func=cmd_set)

    s = sub.add_parser("add", help=f"append to a list: {', '.join(LISTS)}")
    s.add_argument("key")
    s.add_argument("value")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("remove", help="drop an entry from a list")
    s.add_argument("key")
    s.add_argument("value")
    s.set_defaults(func=cmd_remove)

    s = sub.add_parser("add-rule", help="record something the user corrected")
    s.add_argument("text", help="the rule, in the imperative: 'no arms-crossed poses'")
    s.add_argument("--kind", choices=RULE_KINDS, default="avoid")
    s.add_argument("--topic", choices=RULE_TOPICS, default="other")
    s.add_argument("--said", help="the user's own words, if they help (also filtered)")
    s.set_defaults(func=cmd_add_rule)

    s = sub.add_parser("rm-rule", help="remove a rule by id")
    s.add_argument("id")
    s.set_defaults(func=cmd_rm_rule)

    sub.add_parser("path", help="print the file's path").set_defaults(func=cmd_path)

    args = ap.parse_args()
    try:
        return args.func(args)
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
