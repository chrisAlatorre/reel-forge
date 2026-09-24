# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Glues a narration onto an ALREADY rendered video.

It reads a timed script, generates (or reuses) one WAV per line and mixes them onto the MP4 at
the second each line declares. It does not re-render the video: the video stream is copied
through as is.

Usage:
  uv run narrate.py SCRIPT.json VIDEO.mp4 OUT.mp4                     # local voice (voice.py --engine qwen)
  uv run narrate.py SCRIPT.json VIDEO.mp4 OUT.mp4 --engine capcut     # the app's voice (macOS only)
  uv run narrate.py SCRIPT.json VIDEO.mp4 OUT.mp4 --gen VOICE_FOLDER  # WAVs already generated
  uv run narrate.py SCRIPT.json --parse-only                          # validate before generating anything

THE SCRIPT IS A CONTRACT, NOT FREE TEXT
---------------------------------------
The input is a `voice-script` document: the shape lives in `schemas/voice-script.schema.json` and
this script validates the file **before** generating a single WAV, saying exactly which field is
missing. That validation exists because of a real batch: every agent invented its own script
layout, the tolerant parser silently kept nothing, and several narrated videos shipped with no
voice at all and nobody noticed until they were watched.

    {
      "concept": "empty-square", "variant": "B", "lang": "es-MX",
      "video": "empty-square-B.mp4", "video_duration_s": 38.5,
      "engine": "capcut", "voice": "Valentino", "duck_db": -12, "duck_pad_s": 0.3,
      "lines": [
        {"start_s": 0.35, "text": "Nadie te cuenta cómo es el primer día.",
         "duration_hint_s": 2.6, "emphasis": "strong"},
        {"start_s": 6.20, "text": "A las seis de la mañana la plaza está vacía."}
      ],
      "notes": "0.35 comes in over the hook, before the first cut"
    }

`concept`, `variant`, `lang` and `lines` are required, and inside each line `start_s` (the second
it comes in on) and `text` (what gets spoken). `lang`, `engine` and `voice` become this run's
defaults, so the file decides how it is read instead of the command line guessing.

WHO READS IT, WHEN THE FILE DOES NOT SAY
----------------------------------------
With no `engine` in the file and no `--engine` on the command line, `resolve_voice.py` decides and
says why: what the user pinned, then **CapCut's Valentino at 1.4x for Spanish**, then a local
engine as a fallback. When the fallback wins it prints the line the variant's README has to carry,
because a video narrated by the local voice does not sound like the trend and the delivery may not
pretend otherwise.

MARKS FOR THE SUBTITLES
-----------------------
Once the WAVs exist, `wordmarks.py` transcribes them and writes `words.json` next to them: every
word with the second it is spoken, in the video's timeline. Captions are placed from that file,
never from an estimate of how long a sentence "should" take (`--no-word-marks` skips it).

THE OLD FORMAT STILL WORKS, WITH A WARNING
------------------------------------------
A plain-text script is still read, so nothing that exists today breaks:

    0.5   This is where it all starts.
    [3.2] And here it goes on.
    7.0 s | 2.4 s | The third line.

It stops at a "Notes" or "Optional" heading, ignores separators and markdown headings, and drops
lines with no real text — and it now **reports every line it dropped**, because a dropped line is a
sentence that will not be heard. `--strict` refuses the old format outright and turns those reports
into errors.

The video's original audio is preserved and the voice is summed on top; by default the original
audio **ducks under the voice** (`--no-duck` to sum them flat instead).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from resolve_voice import resolve_voice  # noqa: E402  (same folder, shipped together)
from wordmarks import marks_for  # noqa: E402

CAPCUT = HERE / "capcut_voice.py"
LOCAL = HERE / "voice.py"
WORDS = "words.json"
# The contracts live at the plugin's root, next to skills/. $CLAUDE_PLUGIN_ROOT wins when the
# plugin is installed from the cache and this file is not where the schemas are.
SCHEMA_NAME = "voice-script.schema.json"
VALIDATOR = "validate.py"
SCHEMA_DIRS = [Path(p) / "schemas" for p in [os.environ.get("CLAUDE_PLUGIN_ROOT", ""), str(HERE.parents[2])] if p]
CONTRACT = "voice-script"

EXIT_ARGS = 2
EXIT_CONTRACT = 3   # the script file does not honour the voice-script contract

# The contract's own defaults, repeated here so a file that omits them still gets the behaviour the
# schema documents rather than whatever this script felt like.
DUCK_DB = -12.0
DUCK_PAD_S = 0.3


def die(msg, code=1):
    print(f"\nnarrate: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def schemas_dir():
    for d in SCHEMA_DIRS:
        if (d / SCHEMA_NAME).exists():
            return d
    return None


def validate_with_contract(path, folder):
    """Runs the contracts area's own validator. Returns (ok, output), or None if it cannot run.

    Delegating is the point: `schemas/validate.py` is where the rules live, including the ones JSON
    Schema cannot express (lines out of order, a line stepping on the next one). This script only
    falls back to its own checks when that validator is not reachable.
    """
    v = folder / VALIDATOR
    if not v.exists() or not shutil.which("uv"):
        return None
    r = subprocess.run(["uv", "run", "--quiet", str(v), str(path), "--type", CONTRACT],
                       capture_output=True, text=True)
    if r.returncode not in (0, 1):
        return None      # it could not even run: fall back rather than blame the file
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def resolve(node, root):
    """Follows a local $ref (#/$defs/...). The contracts are self-contained, so nothing else."""
    seen = 0
    while isinstance(node, dict) and "$ref" in node and seen < 10:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            return node
        target = root
        for part in ref[2:].split("/"):
            target = (target or {}).get(part)
        node, seen = target or {}, seen + 1
    return node


def check_against_schema(doc, schema, root=None, path="$"):
    """A deliberately small JSON-Schema subset — type, $ref, required, properties,
    additionalProperties, items, enum, minimum/maximum, minItems, minLength — used only when the
    contracts area's validator cannot be run. Enough to refuse a script that would narrate nothing,
    without pulling jsonschema into a file that has no dependencies."""
    root = root if root is not None else schema
    schema = resolve(schema, root)
    errors = []
    if not isinstance(schema, dict):
        return errors
    types = {"object": dict, "array": list, "string": str, "number": (int, float),
             "integer": int, "boolean": bool, "null": type(None)}
    want = schema.get("type")
    if want:
        allowed = tuple(t for name in ([want] if isinstance(want, str) else want)
                        for t in (types[name],) if name in types)
        flat = tuple(x for t in allowed for x in (t if isinstance(t, tuple) else (t,)))
        if flat and (not isinstance(doc, flat) or (isinstance(doc, bool) and bool not in flat)):
            return [f"{path}: expected {want}, got {type(doc).__name__}"]
    if isinstance(doc, dict):
        props = schema.get("properties") or {}
        for key in schema.get("required", []):
            if key not in doc:
                errors.append(f"{path}: the required field {key!r} is missing")
        if schema.get("additionalProperties") is False:
            for key in doc:
                if key not in props:
                    errors.append(f"{path}.{key}: the contract has no such field "
                                  f"(it knows {sorted(props)})")
        for key, sub in props.items():
            if key in doc:
                errors += check_against_schema(doc[key], sub, root, f"{path}.{key}")
    if isinstance(doc, list):
        if len(doc) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} item(s), has {len(doc)}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(doc):
                errors += check_against_schema(item, item_schema, root, f"{path}[{i}]")
    if isinstance(doc, str) and len(doc) < schema.get("minLength", 0):
        errors.append(f"{path}: has to be at least {schema['minLength']} character(s) long")
    if "enum" in schema and doc not in schema["enum"]:
        errors.append(f"{path}: {doc!r} is not one of {schema['enum']}")
    if isinstance(doc, (int, float)) and not isinstance(doc, bool):
        if "minimum" in schema and doc < schema["minimum"]:
            errors.append(f"{path}: {doc} is below the minimum {schema['minimum']}")
        if "maximum" in schema and doc > schema["maximum"]:
            errors.append(f"{path}: {doc} is above the maximum {schema['maximum']}")
    return errors


SHAPE = ('    {"concept": "empty-square", "variant": "B", "lang": "en-US",\n'
         '     "video": "day-one-B.mp4", "engine": "qwen", "duck_db": -12,\n'
         '     "lines": [{"start_s": 0.35, "text": "The sentence, exactly as it will be heard.",\n'
         '                "duration_hint_s": 2.6, "duck": true}]}\n'
         "  `start_s` is the second the line comes in on and `text` is what gets spoken. The full\n"
         f"  field list, with what each one is for, is in schemas/{SCHEMA_NAME}.")


def read_contract(doc, source):
    """Validates a voice-script document and pulls the lines out of it.

    Returns (lines, meta, warnings), or exits with exactly which field is missing. The validation
    runs BEFORE anything is synthesized, because the failure it exists to catch is a narrated
    variant that shipped with no voice at all: every agent had invented its own script layout, the
    tolerant parser kept nothing, and nobody found out until somebody watched the video.
    """
    errors, warnings = [], []
    folder = schemas_dir()
    if not isinstance(doc, dict):
        die(f"{source}: a voice-script is a JSON object with a \"lines\" array; this file holds a "
            f"{type(doc).__name__}.\n\n  The shape it expects:\n{SHAPE}", EXIT_CONTRACT)

    delegated = validate_with_contract(source, folder) if folder else None
    if delegated is not None:
        ok, output = delegated
        if not ok:
            die(f"{source} does not honour the {CONTRACT} contract "
                f"({folder / SCHEMA_NAME}):\n{output}\n\n  The shape it expects:\n{SHAPE}",
                EXIT_CONTRACT)
    elif folder:
        schema = json.loads((folder / SCHEMA_NAME).read_text(encoding="utf-8"))
        errors += check_against_schema(doc, schema, schema, "$")
        warnings.append(f"validated with this script's own subset check; for the authoritative one "
                        f"run: uv run {folder / VALIDATOR} {source} --type {CONTRACT}")
    else:
        warnings.append(f"this copy of the plugin has no schemas/{SCHEMA_NAME}, so only the checks "
                        "built into this script ran")

    raw = doc.get("lines")
    if raw is None:
        errors.append("$: the required field 'lines' is missing — the array of "
                      "{\"start_s\": <second>, \"text\": \"<what gets spoken>\"}")
    elif not isinstance(raw, list) or not raw:
        errors.append("$.lines: it has to be a non-empty array of {\"start_s\", \"text\"} objects")

    lines, ducks, hints = [], [], []
    for i, item in enumerate(raw or []):
        where = f"$.lines[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{where}: expected an object with 'start_s' and 'text', got {type(item).__name__}")
            continue
        t, text = item.get("start_s"), item.get("text")
        if t is None and "t" in item:
            # Read it, and say so: an early hand-written file used "t" and the contract calls it
            # "start_s". Tolerated so an existing file still narrates, never left unmentioned.
            t = item.get("t")
            warnings.append(f"{where}: the field is called 'start_s' in the contract, not 't'. "
                            "It was read anyway; rename it.")
        if t is None:
            errors.append(f"{where}: 'start_s' is missing (the second the line comes in on)")
        elif isinstance(t, bool) or not isinstance(t, (int, float)):
            errors.append(f"{where}.start_s: has to be a number of seconds, got {t!r}")
        elif t < 0:
            errors.append(f"{where}.start_s: {t} is negative")
        if text is None:
            errors.append(f"{where}: 'text' is missing (what actually gets spoken)")
        elif not isinstance(text, str) or not text.strip():
            errors.append(f"{where}.text: has to be a non-empty string, got {text!r}")
        if isinstance(t, (int, float)) and not isinstance(t, bool) and isinstance(text, str) and text.strip():
            lines.append((float(t), text.strip()))
            ducks.append(item.get("duck", True) is not False)
            hints.append(item.get("duration_hint_s"))

    if errors:
        head = f"{source} does not honour the {CONTRACT} contract"
        if folder:
            head += f" ({folder / SCHEMA_NAME})"
        die(head + ":\n  - " + "\n  - ".join(errors) + "\n\n  The shape it expects:\n" + SHAPE,
            EXIT_CONTRACT)

    # Not contract violations by themselves, but each one produces a video that sounds wrong.
    for i in range(1, len(lines)):
        if lines[i][0] < lines[i - 1][0]:
            warnings.append(f"line {i} comes in at {lines[i][0]} s, before line {i - 1} at "
                            f"{lines[i - 1][0]} s: the lines are out of order")
        elif lines[i][0] == lines[i - 1][0]:
            warnings.append(f"lines {i - 1} and {i} both come in at {lines[i][0]} s: they will "
                            "speak on top of each other")
        elif hints[i - 1] and lines[i - 1][0] + hints[i - 1] > lines[i][0] + 1e-9:
            warnings.append(f"line {i - 1} is expected to run until "
                            f"{lines[i - 1][0] + hints[i - 1]:.2f} s and line {i} comes in at "
                            f"{lines[i][0]} s: two voices at once")
    length = doc.get("video_duration_s")
    if length:
        for i, (t, _) in enumerate(lines):
            if t >= length:
                warnings.append(f"line {i} comes in at {t} s, past the end of the video ({length} s)")
    if lines and not any(ducks):
        warnings.append("every line carries duck: false. If the video's own audio does not drop, "
                        "the narration is what gets lost — that is exactly the delivery that had to "
                        "be fixed by hand.")

    meta = {"lang": doc.get("lang"), "engine": doc.get("engine"), "voice": doc.get("voice"),
            "video": doc.get("video"), "video_duration_s": length, "concept": doc.get("concept"),
            "variant": doc.get("variant"), "notes": doc.get("notes"),
            "duck_db": doc.get("duck_db", DUCK_DB), "duck_pad_s": doc.get("duck_pad_s", DUCK_PAD_S),
            "ducks": ducks, "wavs": [item.get("wav") if isinstance(item, dict) else None for item in (raw or [])]}
    return lines, meta, warnings


def parse(path):
    """Returns [(second, text)], tolerating the most common script formats."""
    return parse_legacy(path)[0]


def parse_legacy(path):
    """The old plain-text format. Returns ([(second, text)], dropped, stopped_at).

    `dropped` is every non-empty line that carried something but did not become narration. It is
    reported, not hidden: a dropped line is a sentence the viewer will never hear, and that is
    exactly how narrated videos shipped mute.
    """
    lines, dropped, stopped_at = [], [], None
    for n, source_line in enumerate(Path(path).read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        ln = source_line.rstrip()
        # Everything after a "Notes" heading is comments: that is where the table ends.
        # Without this, a comment like "…from 15.8 to 16.9 s). If you bring it in earlier…"
        # comes through as a line.
        # The scripts themselves are written in the run's output language, so the heading is
        # matched in the handful of languages the plugin actually ships voices for.
        if re.match(r"[#\s]*(notes?|notas?|observaciones|obs)\s*:?\s*$", ln, re.I):
            stopped_at = (n, ln.strip(), "a 'Notes' heading: everything below it is comments")
            break
        # The "OPTIONAL" block doesn't come in either: it usually overlaps a required line and
        # buries it. If you really want it, move it into the table with its own second.
        if re.match(r"[#\s]*(optional|opcional|opcionais)\b", ln, re.I):
            stopped_at = (n, ln.strip(), "an 'Optional' heading: an optional line usually buries a required one")
            break
        if not ln.strip() or ln.lstrip().startswith(("---", "===", "#")):
            continue
        m = re.match(r"\s*(?:\[\s*)?~?\s*(\d+(?:\.\d+)?)\s*(?:\])?\s*(?:s\b)?\s*(?:\|)?\s+(?:~?\s*[\d.]+\s*s?\s+)?(.+)$", ln)
        if not m:
            dropped.append((n, ln.strip(), "it does not start with the second the line comes in on"))
            continue
        t, text = float(m.group(1)), m.group(2).strip(" |")
        text = re.sub(r"\s{2,}[\d.]+\s*s\.?$", "", text).strip()
        # Leftovers from duration columns: "0.5  2.4 s  text", "0.20s ~2.7s text", "~1.4 s  text"
        text = re.sub(r"^(?:s\b|~?\s*[\d.]+\s*s\b|\d+)\s*", "", text).strip()
        text = re.sub(r"^~?\s*[\d.]+\s*s\b\s*", "", text).strip()
        text = text.strip(" |\t")   # leftovers from the duration column in tabular scripts
        if len(text) < 8 or not re.search(r"[^\W\d_]{3}", text, re.UNICODE):
            dropped.append((n, ln.strip(), "what is left after the second is too short to be a sentence"))
            continue
        if text.lower().startswith(("line", "in", "dur", "duration", "video", "optional", "notes")):
            dropped.append((n, ln.strip(), "it reads as a table heading, not as narration"))
            continue
        lines.append((t, text))
    return lines, dropped, stopped_at


def read_script(path, strict=False):
    """Reads a script, whichever format it is in. Returns (lines, meta, report).

    A JSON file is the voice-script contract and gets validated. Anything else is the old plain
    text: it still works, and it says so, because a script format nobody checks is how a narrated
    video ends up silent.
    """
    f = Path(path)
    if not f.exists():
        die(f"{f} does not exist", EXIT_ARGS)
    text = f.read_text(encoding="utf-8", errors="ignore")
    looks_json = f.suffix.lower() == ".json" or text.lstrip().startswith(("{", "["))
    if looks_json:
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as e:
            die(f"{f} looks like a voice-script JSON but it does not parse: {e}", EXIT_CONTRACT)
        lines, meta, warnings = read_contract(doc, str(f))
        return lines, meta, {"format": CONTRACT, "warnings": warnings, "dropped": [], "stopped_at": None}

    if strict:
        die(f"{f} is in the old plain-text format and --strict was given. Convert it with "
            f"`narrate.py {f} --to-json voice-script.json --lang <tag> --concept <id> "
            "--variant <A-H>` and run again.", EXIT_CONTRACT)
    lines, dropped, stopped_at = parse_legacy(f)
    warnings = [f"{f} is in the old plain-text format. It still narrates, but nothing validates it: "
                f"the contract is schemas/{SCHEMA_NAME} and --to-json converts this file into one."]
    return lines, {}, {"format": "legacy-text", "warnings": warnings, "dropped": dropped,
                       "stopped_at": stopped_at}


def report(path, lines, meta, info, strict=False):
    """Prints what was understood and what was thrown away, before anything gets generated."""
    print(f"script: {path}  ·  format: {info['format']}  ·  {len(lines)} line(s)")
    asked = {k: meta.get(k) for k in ("concept", "variant", "lang", "engine", "voice", "video")
             if meta.get(k)}
    if asked:
        print("  the file asks for: " + "  ".join(f"{k}={v}" for k, v in asked.items()))
    if meta.get("ducks"):
        print(f"  ducking: {meta['duck_db']} dB with a {meta['duck_pad_s']} s ramp on "
              f"{sum(1 for d in meta['ducks'] if d)}/{len(meta['ducks'])} line(s)")
    print(json.dumps([{"start_s": t, "text": x} for t, x in lines], ensure_ascii=False, indent=1))
    if info.get("stopped_at"):
        n, txt, why = info["stopped_at"]
        print(f"  stopped reading at line {n} ({txt[:40]!r}): {why}")
    for n, txt, why in info.get("dropped", []):
        print(f"  DROPPED line {n}: {txt[:60]!r} — {why}")
    for w in info.get("warnings", []):
        print(f"  WARNING: {w}")
    if strict and (info.get("dropped") or info.get("warnings")):
        die("--strict: the script has warnings or dropped lines, and every dropped line is a "
            "sentence nobody will hear. Fix them, or drop --strict.", EXIT_CONTRACT)


def to_json(path, lines, dest, lang, concept, variant, video=None):
    """Writes an old plain-text script out as a contract file, so it only has to be fixed once."""
    missing = [n for n, v in (("--lang", lang), ("--concept", concept), ("--variant", variant)) if not v]
    if missing:
        die(f"--to-json needs {', '.join(missing)}: the contract requires concept, variant and lang, "
            "and they are not in a plain-text script. Example: --lang en-US --concept empty-square "
            "--variant B", EXIT_ARGS)
    doc = {"concept": concept, "variant": variant, "lang": lang}
    if video:
        doc["video"] = Path(video).name
    doc["lines"] = [{"start_s": round(t, 2), "text": x} for t, x in lines]
    Path(dest).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    folder = schemas_dir()
    print(f"converted {path} -> {dest} ({len(lines)} lines). Read it before narrating with it, and "
          "add duration_hint_s per line so the overlap check can run.")
    if folder:
        print(f"  validate it: uv run {folder / VALIDATOR} {dest} --type {CONTRACT}")


def generate(engine, lines, folder, speed, voice, language=None):
    """Calls whichever synthesizer applies. Both leave lN.wav + durations.json in the folder."""
    tmp = folder / "lines.json"
    tmp.write_text(json.dumps([x for _, x in lines], ensure_ascii=False), encoding="utf-8")
    if engine == "capcut":
        if sys.platform != "darwin":
            sys.exit("--engine capcut only works on macOS (it automates the desktop app). Use the local one.")
        cmd = ["uv", "run", str(CAPCUT), str(tmp), str(folder), "--speed", str(speed)]
        if voice:
            cmd += ["--voice", voice]
    else:
        cmd = ["uv", "run", str(LOCAL), str(tmp), str(folder), "--engine", engine]
        if voice:
            cmd += ["--voice", voice]
        # Without this the synthesizer falls back to its own default voice, and a run in one
        # language ends up narrated in another.
        if language:
            cmd += ["--language", language]
    subprocess.run(cmd, check=True)


def ffprobe(*args):
    return subprocess.run(["ffprobe", "-v", "error", *args], capture_output=True, text=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser(description="Mixes a narration onto an already rendered video")
    ap.add_argument("script")
    ap.add_argument("video", nargs="?")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--engine", choices=["qwen", "voxcpm", "piper", "capcut"],
                    help="qwen | voxcpm | piper | capcut (macOS, the app's voice). With nothing "
                         "here and nothing in the script, resolve_voice.py decides: what is "
                         "pinned, then Valentino at 1.4x for Spanish, then a local engine.")
    ap.add_argument("--voice", help="the voice name for the chosen engine")
    ap.add_argument("--language", default=os.environ.get("REEL_FORGE_LANG"),
                    help="the narration's language, e.g. en, es-MX (default: $REEL_FORGE_LANG)")
    ap.add_argument("--gen", help="a folder with l0.wav… already generated; otherwise it generates them")
    ap.add_argument("--speed", type=float, help="--engine capcut only: the trend's pace (default 1.4)")
    ap.add_argument("--local-only", action="store_true",
                    help="never the app voice, even for Spanish (it says so in the delivery line)")
    ap.add_argument("--word-marks", action=argparse.BooleanOptionalAction, default=True,
                    help=f"transcribe the generated voice into {WORDS} so the captions are placed "
                         "from the words actually spoken (default: yes)")
    ap.add_argument("--volume", type=float, default=1.0, help="the voice's gain over the video's audio")
    ap.add_argument("--parse-only", action="store_true",
                    help="validate the script and print what it understood; generate nothing")
    ap.add_argument("--strict", action="store_true",
                    help="refuse the old plain-text format and treat every dropped line as an error")
    ap.add_argument("--to-json", metavar="OUT.json",
                    help="convert an old plain-text script into a voice-script contract file")
    ap.add_argument("--concept", help="--to-json only: the concept id the contract requires")
    ap.add_argument("--variant", help="--to-json only: the variant letter the contract requires")
    ap.add_argument("--duck", action=argparse.BooleanOptionalAction, default=True,
                    help="duck the video's own audio under the voice (default: yes)")
    ap.add_argument("--duck-db", type=float,
                    help="how far the video's audio drops while a line speaks, in dB "
                         f"(negative; default: the script's duck_db, or {DUCK_DB})")
    a = ap.parse_args()

    lines, meta, info = read_script(a.script, strict=a.strict)
    if not lines:
        die(f"no lines came out of {a.script}. In the contract that is the \"lines\" array; in the "
            "old plain-text format, one line per sentence starting with the second it comes in on. "
            "Run --parse-only to see exactly what was read and what was dropped.", EXIT_CONTRACT)
    report(a.script, lines, meta, info, strict=a.strict)
    if a.to_json:
        return to_json(a.script, lines, a.to_json, a.language or meta.get("lang"),
                       a.concept, a.variant, a.video)
    if a.parse_only:
        return
    if not (a.video and a.out):
        ap.error("VIDEO.mp4 and OUT.mp4 are missing")

    # What the command line asks for wins over the file, the file wins over the defaults, and when
    # neither says, resolve_voice decides and explains itself. The contract exists so the run stops
    # guessing, not so it stops being steerable.
    language = a.language or meta.get("lang")
    engine = a.engine or meta.get("engine")
    voice = a.voice or meta.get("voice")
    speed = a.speed
    if engine != "none":
        choice = resolve_voice(lang=language, engine=engine, voice=voice, speed=speed,
                               local_only=a.local_only)
        engine, voice = choice["engine"], choice["voice"]
        speed = choice["speed"]
        language = language or choice["language"] or None
        print(f"  voice: {engine}" + (f" / {voice}" if voice else "") + f" at {speed}x — {choice['reason']}")
        for w in choice["warnings"]:
            print(f"  WARNING: {w}")
        if choice["disclose"]:
            print(f"  README line for this variant: {choice['disclose']}")
    if engine == "none":
        die(f"{a.script} says engine: \"none\" — that variant is meant to ship WITHOUT voice, with "
            "this file alongside it so the user can add the narration themselves. Pass --engine "
            "explicitly if you do want to synthesize it now.", EXIT_CONTRACT)
    if meta.get("video") and Path(meta["video"]).name != Path(a.video).name:
        print(f"  WARNING: the script says it belongs to {meta['video']!r} and you passed "
              f"{Path(a.video).name!r}. The seconds were worked out against the other video.")

    folder = Path(a.gen) if a.gen else Path(a.out).parent / ("voices-" + Path(a.out).stem)
    folder.mkdir(parents=True, exist_ok=True)
    # durations.json is the "folder is complete" signal: if it's missing, it gets (re)generated
    # and resumes on its own.
    if not (folder / "durations.json").exists():
        generate(engine, lines, folder, speed, voice, language)

    # The contract lets a line name its own file; without one it is l0.wav, l1.wav… in index order,
    # which is the contract every voice source in this plugin leaves behind.
    named = meta.get("wavs") or []
    wavs = [folder / (named[i] or f"l{i}.wav") if i < len(named) and named[i] else folder / f"l{i}.wav"
            for i in range(len(lines))]
    missing = [w for w in wavs if not w.exists()]
    if missing:
        die(f"missing audio: {[str(w) for w in missing[:3]]}. The synthesizer stopped before "
            "finishing; run it again and it resumes from the line it stopped on.")

    # The captions come from the voice, not from an estimate: transcribe what was generated and
    # write every word with the second it is spoken, already shifted onto the video's timeline.
    # It is best-effort — a machine with no transcriber still gets its narrated video — but when it
    # cannot run it says so, because the alternative is captions placed by guesswork.
    if a.word_marks:
        try:
            marks = marks_for(folder, [t for t, _ in lines], language,
                              texts=[x for _, x in lines], quiet=True)
            (folder / WORDS).write_text(json.dumps(marks, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
            if marks["words"]:
                print(f"  word marks: {folder / WORDS} ({len(marks['words'])} words, "
                      f"±{marks['tolerance_s']} s). Place the captions from it.")
            else:
                print(f"  word marks: {folder / WORDS} carries NO words, so nothing can be captioned "
                      "from the voice. Fix the transcriber, or ship this variant without burned-in "
                      "captions rather than placing them by estimate.")
            for w in marks["warnings"]:
                print(f"  WARNING: {w}")
        except SystemExit:
            raise
        except Exception as e:      # noqa: BLE001 - never lose a finished narration over this
            print(f"  WARNING: no word marks were written ({e}). Any caption on top of this "
                  f"narration would be placed from an estimate: run "
                  f"`uv run {HERE / 'wordmarks.py'} {folder} --script {a.script}` before burning "
                  "captions in.")

    # Now that the WAVs exist, the real durations are known: this is the check the script format
    # could only guess at with duration_hint_s.
    real = [float(ffprobe("-show_entries", "format=duration", "-of", "csv=p=0", str(w))) for w in wavs]
    for i in range(len(lines) - 1):
        over = (lines[i][0] + real[i]) - lines[i + 1][0]
        if over > 0.01:
            print(f"  WARNING: line {i} runs until {lines[i][0] + real[i]:.2f} s and line {i + 1} "
                  f"comes in at {lines[i + 1][0]:.2f} s: {over:.2f} s of two voices at once. "
                  "Shorten the sentence or move the second one.")

    has_audio = bool(ffprobe("-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", a.video))
    length = float(ffprobe("-show_entries", "format=duration", "-of", "csv=p=0", a.video))
    ducks = meta.get("ducks") or [True] * len(lines)
    ducks = [bool(ducks[i]) if i < len(ducks) else True for i in range(len(lines))]
    duck_db = -abs(a.duck_db if a.duck_db is not None else float(meta.get("duck_db", DUCK_DB)))
    pad = float(meta.get("duck_pad_s", DUCK_PAD_S))
    ducking = has_audio and a.duck and any(ducks)

    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", a.video]
    filters = []
    for i, ((t, _), w) in enumerate(zip(lines, wavs)):
        cmd += ["-i", str(w)]
        ms = int(t * 1000)
        chain = (f"[{i + 1}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                 f"adelay={ms}|{ms},volume={a.volume}")
        # A stream label can only be consumed once, so a line that also keys the ducking gets split
        # here: [v<i>] is what you hear, [k<i>] is what pushes the video's audio down.
        if ducking and ducks[i]:
            filters.append(f"{chain}[p{i}]")
            filters.append(f"[p{i}]asplit=2[v{i}][k{i}]")
        else:
            filters.append(f"{chain}[v{i}]")

    def mix_into(labels, name):
        """amix refuses a single input, and anull is the honest no-op for that case."""
        if len(labels) == 1:
            filters.append(f"{labels[0]}anull[{name}]")
        else:
            filters.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest[{name}]")

    mix_into([f"[v{i}]" for i in range(len(lines))], "vox")

    if ducking:
        # The real failure this replaces: a delivery where the clip's own audio buried the narration
        # and had to be turned down by hand afterwards. sidechaincompress pulls the video's audio
        # down only while the voice is speaking and lets it back up in the gaps, and only the lines
        # the contract marks `duck: true` key it.
        mix_into([f"[k{i}]" for i in range(len(lines)) if ducks[i]], "voxkey")
        ratio = min(20.0, max(1.5, 10 ** (abs(duck_db) / 20.0)))
        attack = max(5, int(pad * 1000 / 4))
        release = max(50, int(pad * 1000))
        filters.append("[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[bg]")
        filters.append(f"[bg][voxkey]sidechaincompress=threshold=0.02:ratio={ratio:.2f}:"
                       f"attack={attack}:release={release}:makeup=1[ducked]")
        filters.append("[ducked][vox]amix=inputs=2:normalize=0:duration=longest[mix]")
    elif has_audio:
        filters.append("[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[bg]")
        filters.append("[bg][vox]amix=inputs=2:normalize=0:duration=longest[mix]")
    else:
        filters.append("[vox]anull[mix]")

    # CAREFUL: no duration=first anywhere above. If the video comes in WITHOUT audio, the amix's
    # first input is the first voice line and the mix gets cut when that line ends. Take the
    # longest one, PAD it to the video's length and only then trim: `atrim` alone cannot extend, so
    # without the `apad` a silent video ends up with an audio track that stops at the last line.
    filters.append(f"[mix]apad=whole_dur={length:.3f},atrim=0:{length:.3f},"
                   f"asetpts=N/SR/TB,alimiter=limit=0.95[a]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[a]", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", a.out]
    subprocess.run(cmd, check=True)
    print(f"ok: {a.out} · ducking: " +
          (f"{duck_db:.0f} dB on {sum(ducks)}/{len(lines)} line(s)" if ducking else
           "off (the video carries no audio track)" if not has_audio else "off"))


if __name__ == "__main__":
    main()
