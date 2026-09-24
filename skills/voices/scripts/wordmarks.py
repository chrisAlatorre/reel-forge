# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Word-by-word timestamps for a narration that has ALREADY been generated.

    uv run wordmarks.py VOICE_FOLDER --script voice-script.json          # writes VOICE_FOLDER/words.json
    uv run wordmarks.py VOICE_FOLDER --starts 0,4.2,9.8 -o words.json    # without a contract file
    uv run wordmarks.py --audio one.wav --at 3.5                         # a single file, to stdout
    uv run wordmarks.py --check words.json                               # re-read and summarize

WHY THIS EXISTS
---------------
Subtitles used to be placed from an estimate: how long a sentence "should" take, split by letter
count. On screen that drifts — the word lands and the caption arrives a beat later, and at the one
moment that matters (the payoff) it is the drift you notice. The fix is not a better estimate. The
fix is to read the timings **off the voice that will actually be heard**.

So: the voice is generated first (`voice.py` or `capcut_voice.py`, leaving `lN.wav` +
`durations.json`), and this transcribes those WAVs with word-level marks and shifts them onto the
video's timeline using each line's `start_s`. What comes out is `words.json`:

    {"schema": "voice-words/1", "lang": "es-MX", "engine": "mlx-whisper ...", "tolerance_s": 0.25,
     "lines": [{"i": 0, "start_s": 0.35, "end_s": 3.1, "text": "...",
                "words": [{"w": "Nadie", "start": 0.35, "end": 0.62}, ...]}],
     "words": [ ... every word, in video time ... ]}

Every `start`/`end` in there is **video time**, ready to be burned in. The rule the verifier
enforces with 0.25 s of tolerance is the same one in both directions:

  - a caption may not appear before the word is spoken, nor linger after it;
  - and if the voice names something concrete, that image is on screen while it is being said.

Transcribing the generated voice also catches the failure nobody looks for: a TTS that swallowed a
word or read a number wrong. `--check` prints the words whose confidence is low.

The transcriber runs in its own uv environment (mlx-whisper on Apple Silicon, faster-whisper
elsewhere), so this file keeps no heavy dependency and can be imported by the other scripts here.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SCHEMA = "voice-words/1"
# The slack the verifier allows between a word being spoken and its caption being on screen.
TOLERANCE_S = 0.25
MLX_WHISPER = "mlx-whisper"
FASTER_WHISPER = "faster-whisper"
MLX_MODEL = "mlx-community/whisper-large-v3-turbo"
FW_MODEL = "large-v3"
LOW_CONFIDENCE = 0.5

# Runs inside the transcriber's environment, writes a flat word list to a JSON file and exits.
# Kept as a separate program so the heavy import never touches the parent process.
TRANSCRIBER = r'''
import json, sys
audio, out, backend, model_id, language = sys.argv[1:6]
language = language or None
words, detected = [], language
if backend == "mlx":
    import mlx_whisper
    r = mlx_whisper.transcribe(audio, path_or_hf_repo=model_id, word_timestamps=True,
                               language=language, condition_on_previous_text=False)
    detected = r.get("language") or language
    for seg in r.get("segments", []):
        for w in seg.get("words", []) or []:
            words.append({"w": (w.get("word") or "").strip(),
                          "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3),
                          "p": round(float(w.get("probability", 0.0)), 3)})
else:
    from faster_whisper import WhisperModel
    m = WhisperModel(model_id, device="cpu", compute_type="int8")
    segs, info = m.transcribe(audio, word_timestamps=True, language=language,
                              condition_on_previous_text=False)
    for seg in segs:
        for w in seg.words or []:
            words.append({"w": (w.word or "").strip(), "start": round(float(w.start), 3),
                          "end": round(float(w.end), 3), "p": round(float(w.probability or 0.0), 3)})
    detected = info.language or language
json.dump({"language": detected, "words": words}, open(out, "w"), ensure_ascii=False)
'''


def die(msg: str, code: int = 1):
    print(f"wordmarks: {msg}", file=sys.stderr)
    sys.exit(code)


def backend():
    """(backend, uv dependency, model id) for this machine."""
    if sys.platform == "darwin" and os.uname().machine == "arm64":
        return "mlx", MLX_WHISPER, MLX_MODEL
    return "fw", FASTER_WHISPER, FW_MODEL


def transcribe_words(wav, language=None, cache=None, force=False, quiet=False) -> dict:
    """Word-level transcript of one audio file: {"language", "engine", "words": [{w,start,end,p}]}.

    Times are the file's own. Shared with `sound_map.py`, which maps a viral audio the same way.
    Raises RuntimeError when the transcriber cannot run, so the caller decides whether that is
    fatal: for a sound map it is, for a narration's captions it is a warning and an estimate.
    """
    wav = Path(wav)
    cache = Path(cache) if cache else None
    if cache and cache.exists() and not force:
        if not quiet:
            print(f"· cached transcript: {cache}")
        return json.loads(cache.read_text(encoding="utf-8"))
    kind, dep, model = backend()
    if not quiet:
        print(f"· transcribing with {dep} ({model}); the first run downloads the model")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        prog = Path(tmp) / "transcribe_words.py"
        prog.write_text(TRANSCRIBER, encoding="utf-8")
        out = Path(tmp) / "words.json"
        try:
            r = subprocess.run(["uv", "run", "--quiet", "--no-project", "--python", "3.12",
                                "--with", dep, "python", str(prog), str(wav), str(out),
                                kind, model, language or ""], capture_output=True, text=True)
        except OSError as e:
            # No uv on this machine: a RuntimeError like any other failure, so the caller decides
            # whether it is fatal instead of dying on a traceback.
            raise RuntimeError(f"I could not run {dep} ({e}). uv is what installs it: "
                               "https://docs.astral.sh/uv/") from e
        if r.returncode != 0 or not out.exists():
            tail = (r.stderr or r.stdout or "").strip().splitlines()[-6:]
            raise RuntimeError(f"{dep} could not transcribe {wav.name}: " + " / ".join(tail))
        data = json.loads(out.read_text(encoding="utf-8"))
    data["engine"] = f"{dep} {model}"
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def duration_of(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return round(float(r.stdout.strip()), 3)
    except ValueError:
        return 0.0


def wavs_in(folder: Path, count=None) -> list:
    """l0.wav, l1.wav… in index order, the contract every voice source here leaves behind."""
    found, i = [], 0
    while True:
        w = folder / f"l{i}.wav"
        if not w.exists():
            break
        found.append(w)
        i += 1
        if count and i >= count:
            break
    return found


def marks_for(folder, starts, language=None, force=False, quiet=False, texts=None) -> dict:
    """Word marks for a generated narration, shifted onto the video's timeline.

    `starts[i]` is the second line i comes in on (the contract's `start_s`). Anything the
    transcriber could not read comes back as a line with an empty `words` list and a warning: a
    missing mark has to be visible, because the caption for that line would otherwise be placed
    from an estimate without anybody knowing.
    """
    folder = Path(folder)
    wavs = wavs_in(folder, len(starts) if starts else None)
    if not wavs:
        die(f"{folder} holds no l0.wav: generate the voice first (voice.py or capcut_voice.py)", 2)
    if starts and len(starts) != len(wavs):
        print(f"  WARNING: the script has {len(starts)} line(s) and the folder holds {len(wavs)} "
              "WAV(s); the extra ones are ignored", file=sys.stderr)
    lines, every, warnings, engine, detected = [], [], [], None, language
    for i, wav in enumerate(wavs):
        at = float(starts[i]) if starts and i < len(starts) else None
        if at is None:
            at = round(sum(duration_of(w) for w in wavs[:i]), 3)
            if i == 0:
                warnings.append("no start times were given, so the lines were laid end to end. "
                                "Pass --script or --starts for the real timeline.")
        dur = duration_of(wav)
        entry = {"i": i, "start_s": round(at, 3), "end_s": round(at + dur, 3),
                 "wav": wav.name, "duration_s": dur, "words": []}
        if texts and i < len(texts):
            entry["text"] = texts[i]
        try:
            data = transcribe_words(wav, language, cache=wav.with_suffix(".words.json"),
                                    force=force, quiet=quiet)
        except RuntimeError as e:
            warnings.append(f"l{i}: {e}. Its caption cannot be placed from the voice; either fix "
                            "the transcriber or leave that line without a burned-in caption.")
            lines.append(entry)
            continue
        engine = engine or data.get("engine")
        detected = detected or data.get("language")
        words = [{"w": w["w"], "start": round(at + w["start"], 3), "end": round(at + w["end"], 3),
                  "p": w.get("p", 0.0), "line": i}
                 for w in data.get("words", []) if w.get("w")]
        if not words:
            warnings.append(f"l{i}: the transcriber heard no words in {wav.name}. Listen to it: "
                            "a silent WAV is a line nobody will hear either.")
        entry["words"] = [{k: v for k, v in w.items() if k != "line"} for w in words]
        if words:
            entry["text_heard"] = " ".join(w["w"] for w in words)
            # The marks come from the audio, so they cannot run past it by more than rounding.
            if words[-1]["end"] > entry["end_s"] + 0.05:
                warnings.append(f"l{i}: the last word ends at {words[-1]['end']} s but the WAV ends "
                                f"at {entry['end_s']} s: the marks do not belong to this audio")
        weak = [w["w"] for w in words if 0 < w.get("p", 0) < LOW_CONFIDENCE]
        if weak:
            entry["low_confidence"] = weak
        lines.append(entry)
        every.extend(words)
    # Two lines speaking at once is audible; with the real marks it is also measurable.
    for a, b in zip(lines, lines[1:]):
        if a["words"] and b["words"] and a["words"][-1]["end"] > b["start_s"] + 1e-6:
            warnings.append(f"l{a['i']} is still speaking at {a['words'][-1]['end']} s and l{b['i']} "
                            f"comes in at {b['start_s']} s: shorten the line or move the next one")
    return {"schema": SCHEMA, "lang": detected or language, "engine": engine,
            "tolerance_s": TOLERANCE_S, "source_folder": folder.name,
            "rule": "Captions are placed from these marks, not from an estimate. A caption may not "
                    "appear before its word is spoken nor linger after it, and whatever the voice "
                    f"names is on screen while it is named — both within {TOLERANCE_S} s.",
            "warnings": warnings, "lines": lines, "words": every}


def summarize(m: dict):
    print(f"\n{m.get('schema')}  ·  {m.get('lang') or 'unknown language'}  ·  "
          f"{len(m.get('words', []))} word(s) in {len(m.get('lines', []))} line(s)  ·  "
          f"engine {m.get('engine') or '(none)'}")
    for ln in m.get("lines", []):
        heard = ln.get("text_heard") or ln.get("text") or "(nothing was heard)"
        print(f"  [{ln['i']:>2}] {ln['start_s']:>6.2f}-{ln['end_s']:<6.2f} {heard[:70]}")
        if ln.get("low_confidence"):
            print(f"       low confidence on: {', '.join(ln['low_confidence'][:8])}")
    for w in m.get("warnings", []):
        print(f"  WARNING: {w}")


def starts_from_script(path: Path):
    """(starts, texts, lang) out of a voice-script contract file."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("lines"), list):
        die(f"{path} is not a voice-script (an object with a \"lines\" array)", 2)
    starts, texts = [], []
    for i, ln in enumerate(doc["lines"]):
        if not isinstance(ln, dict) or not isinstance(ln.get("start_s"), (int, float)):
            die(f"{path}: line {i} has no numeric 'start_s'; validate it with "
                "schemas/validate.py --type voice-script", 2)
        starts.append(float(ln["start_s"]))
        texts.append(ln.get("text", ""))
    return starts, texts, doc.get("lang")


def main():
    ap = argparse.ArgumentParser(description="Word-by-word marks of a generated narration")
    ap.add_argument("folder", nargs="?", help="the folder with l0.wav… and durations.json")
    ap.add_argument("--script", help="the voice-script.json the seconds come from")
    ap.add_argument("--starts", help="comma-separated seconds, one per line, instead of --script")
    ap.add_argument("--audio", help="a single WAV instead of a folder")
    ap.add_argument("--at", type=float, default=0.0, help="--audio only: the second it comes in on")
    ap.add_argument("--language", default=os.environ.get("REEL_FORGE_LANG"),
                    help="the narration's language (default: $REEL_FORGE_LANG; empty = detect it)")
    ap.add_argument("-o", "--out", help="where to write words.json (default: FOLDER/words.json)")
    ap.add_argument("--force", action="store_true", help="ignore the cached per-line transcripts")
    ap.add_argument("--check", metavar="WORDS.JSON", help="re-read a words.json and summarize it")
    a = ap.parse_args()

    if a.check:
        f = Path(a.check)
        if not f.exists():
            die(f"{f} does not exist", 2)
        m = json.loads(f.read_text(encoding="utf-8"))
        if m.get("schema") != SCHEMA:
            die(f"{f} is not a {SCHEMA} file (it says {m.get('schema')!r})", 2)
        return summarize(m)

    if a.audio:
        wav = Path(a.audio)
        if not wav.exists():
            die(f"{wav} does not exist", 2)
        try:
            data = transcribe_words(wav, a.language, cache=wav.with_suffix(".words.json"),
                                    force=a.force)
        except RuntimeError as e:
            die(str(e), 6)
        words = [{"w": w["w"], "start": round(a.at + w["start"], 3),
                  "end": round(a.at + w["end"], 3), "p": w.get("p", 0.0)}
                 for w in data.get("words", []) if w.get("w")]
        print(json.dumps({"schema": SCHEMA, "lang": data.get("language"),
                          "engine": data.get("engine"), "tolerance_s": TOLERANCE_S,
                          "words": words}, ensure_ascii=False, indent=1))
        return

    if not a.folder:
        ap.error("the folder with l0.wav… is missing (or use --audio for a single file)")
    starts, texts, lang = None, None, None
    if a.script:
        starts, texts, lang = starts_from_script(Path(a.script))
    elif a.starts:
        starts = [float(x) for x in a.starts.replace(" ", "").split(",") if x]
    m = marks_for(a.folder, starts, a.language or lang, force=a.force, texts=texts)
    out = Path(a.out) if a.out else Path(a.folder) / "words.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    summarize(m)
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
