# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = [
#   "faster-whisper>=1.1",
# ]
# ///
"""Two jobs, one model: what a clip SAYS, and WHEN the narration says each word.

1. Subtitle candidates from a clip's own audio

    uv run transcribe.py CLIP.mov [CLIP2.mp4 ...]            # writes CLIP.mov.transcript.json
    uv run transcribe.py CLIP.mov --start 12 --dur 6         # only that window (times stay the clip's)
    uv run transcribe.py CLIP.mov --language es --model small
    uv run transcribe.py CLIP.mov --out transcripts/         # somewhere else (read-only libraries)
    uv run transcribe.py CLIP.mov --print                    # only to stdout, writes nothing

2. Subtitles aligned to the narration ALREADY generated (`--align`)

    uv run transcribe.py --align voice/ --script script.json         # writes voice/alignment.json
    uv run transcribe.py --align voice/l0.wav --text "..." --at 0.35
    uv run transcribe.py --align voice/ --script script.json --style box --pos upper

   It reads the WAVs the voices skill left (`l0.wav`, `l1.wav`… + `durations.json`), asks the model
   for **word-by-word** times and writes `alignment.json`: the same words the script says, each with
   the second it is actually pronounced on, plus captions already cut into readable groups **in the
   video's time** (the line's `t` plus the word's offset inside its WAV).

   The engine takes that file straight from the spec, so the text on screen comes from the voice and
   not from an estimate:

       "sync": {"from": "common/voice/alignment.json", "style": "clean", "pos": "low"}

   The written text always wins over what the model heard: the model only contributes the times. A
   TTS voice that swallows a syllable does not get to rewrite the caption.

**When a subtitle belongs, and when it does not** (the same rule is in SKILL.md and editing.md):

- Subtitle it only if that audio **is heard in the final mix** and **adds something**: a line that
  lands, the tone of the moment, a joke, a number nobody would catch otherwise.
- Do NOT subtitle it if the segment is carrying music, TTS narration or a viral audio on top: the
  original voice is not audible there, and a subtitle for something nobody hears reads as a mistake.
- Do NOT subtitle filler ("ah", "well…", "look"), nor anything a stranger says on camera.
- If the transcription is not confident about a stretch, either fix the text by hand or drop it: a
  wrong subtitle on screen is worse than none.
- A narration is the exception: what is spoken IS the text, so it gets subtitled whole — but with
  `--align`, never with times worked out by hand.

Times in mode 1 are always the **source clip's**, never the video's: the engine maps them with the
segment's `start` and `speed`. That way the same transcript works in every variant that uses the
clip. Times in mode 2 are the **video's**, because the narration is already placed on its timeline.

The model is downloaded on first use by faster-whisper (into ~/.cache/huggingface). `small` is the
default because it is the smallest one that gets proper nouns and numbers right; `tiny` mangles
them and `medium` is four times slower with no gain on phone audio.
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_CHARS = 42      # a subtitle line that still fits 9:16 at size 52 without wrapping into three lines
MAX_DUR = 3.2       # seconds per caption: longer than this and it stops being read
MIN_DUR = 0.7
MAX_WORDS = 3       # words per karaoke group, the TikTok rhythm
END_PUNCT = (",", ".", "…", "?", "!", ":", ";")

_MODELS = {}


def model_for(name):
    """One model per process: loading it again for every line costs more than the transcription."""
    if name not in _MODELS:
        from faster_whisper import WhisperModel
        _MODELS[name] = WhisperModel(name, device="cpu", compute_type="int8")
    return _MODELS[name]


def media_duration(src):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(src)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def extract_audio(src, start, dur):
    """16 kHz mono WAV of the window. Returns None if the file carries no audio."""
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                            "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(src)],
                           capture_output=True, text=True)
    if "audio" not in probe.stdout:
        return None
    wav = Path(tempfile.mkdtemp(prefix="reel-forge-asr-")) / "audio.wav"
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(src)]
    if dur:
        cmd += ["-t", str(dur)]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(wav)]
    subprocess.run(cmd, check=True)
    return wav


def split(text, t0, t1):
    """Cuts a long sentence into caption-sized pieces, sharing the time by letter count."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if len(text) <= MAX_CHARS and (t1 - t0) <= MAX_DUR:
        return [(t0, t1, text)]
    words, chunks, current = text.split(), [], ""
    for w in words:
        if current and (len(current) + 1 + len(w) > MAX_CHARS):
            chunks.append(current)
            current = w
        else:
            current = (current + " " + w).strip()
    if current:
        chunks.append(current)
    total = sum(len(c) + 1 for c in chunks)
    out, t = [], t0
    for c in chunks:
        d = (t1 - t0) * (len(c) + 1) / total
        out.append((round(t, 3), round(min(t1, t + d), 3), c))
        t += d
    return out


def transcribe(src, args):
    wav = extract_audio(src, args.start, args.dur)
    if wav is None:
        return {"src": str(src), "audio": False, "segments": [], "raw": [],
                "note": "the file carries no audio track: there is nothing to subtitle"}

    model = model_for(args.model)
    segments, info = model.transcribe(str(wav), language=args.language, word_timestamps=True,
                                      vad_filter=True, beam_size=5,
                                      condition_on_previous_text=False)
    off = float(args.start or 0)
    raw, caption_ready = [], []
    for s in segments:
        text = (s.text or "").strip()
        if not text:
            continue
        # A whisper "segment" is a sentence, not a subtitle: too long to read on screen.
        confidence = round(float(getattr(s, "avg_logprob", 0.0)), 3)
        no_speech = round(float(getattr(s, "no_speech_prob", 0.0)), 3)
        raw.append({"t0": round(s.start + off, 3), "t1": round(s.end + off, 3), "text": text,
                    "avg_logprob": confidence, "no_speech_prob": no_speech,
                    "words": [{"t0": round(w.start + off, 3), "t1": round(w.end + off, 3),
                               "text": w.word.strip()} for w in (s.words or [])]})
        for a, b, piece in split(text, s.start + off, s.end + off):
            if b - a < MIN_DUR:
                b = a + MIN_DUR
            caption_ready.append({"t0": round(a, 3), "t1": round(b, 3), "text": piece,
                                  "avg_logprob": confidence, "no_speech_prob": no_speech,
                                  "shaky": confidence < -0.8 or no_speech > 0.5})
    wav.unlink(missing_ok=True)
    return {"src": str(src), "audio": True, "model": args.model,
            "language": getattr(info, "language", args.language),
            "language_probability": round(float(getattr(info, "language_probability", 0) or 0), 3),
            "window": {"start": off, "dur": args.dur},
            "_times": "seconds of the SOURCE clip; the engine maps them with the segment's start/speed",
            "_rule": ("subtitle only what is HEARD in the final mix and adds something; if music, TTS "
                      "narration or a viral audio plays over it, do not subtitle it"),
            "_shaky": "true = low confidence: fix the text by hand or drop that line",
            "segments": caption_ready, "raw": raw}


# ------------------------------------------------------------ mode 2: aligning the narration

def _norm(word):
    """A word reduced to what can be compared: the model writes '¿Cuánto?' and hears 'cuanto'."""
    w = re.sub(r"[^\w']+", "", str(word).lower(), flags=re.UNICODE)
    trans = str.maketrans("áàäâéèëêíìïîóòöôúùüûñç", "aaaaeeeeiiiioooouuuunc")
    return w.translate(trans)


def _heard_words(wav, language, model_name):
    """[{t0, t1, text}] of everything the model hears in the WAV, in the WAV's own time."""
    segments, _info = model_for(model_name).transcribe(
        str(wav), language=language, word_timestamps=True, vad_filter=False,
        beam_size=5, condition_on_previous_text=False)
    out = []
    for s in segments:
        for w in (s.words or []):
            text = (w.word or "").strip()
            if text:
                out.append({"t0": float(w.start), "t1": float(w.end), "text": text})
    return out


def map_to_written(heard, text, duration=None):
    """Gives each WRITTEN word the second it is pronounced on.

    The model contributes times, never text: a TTS voice that swallows a syllable, or a transcript
    that writes "veinte" where the script says "20", must not rewrite the caption. Written words the
    model did not hear get their time by interpolating between the neighbours that were matched.
    """
    written = [w for w in re.split(r"\s+", str(text).strip()) if w]
    if not written:
        return []
    if not heard:
        # No usable ASR (a silent WAV, a model that heard nothing): share the length by letters so
        # the caller still gets a usable window instead of nothing.
        end = duration or (0.35 * len(written))
        total = sum(len(w) + 1 for w in written)
        t, out = 0.0, []
        for w in written:
            d = end * (len(w) + 1) / total
            out.append({"t0": round(t, 3), "t1": round(t + d, 3), "text": w, "heard": False})
            t += d
        return out

    a = [_norm(w["text"]) for w in heard]
    b = [_norm(w) for w in written]
    times = [None] * len(written)
    for op, i0, i1, j0, j1 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            for k in range(j1 - j0):
                times[j0 + k] = (heard[i0 + k]["t0"], heard[i0 + k]["t1"])
        elif op == "replace":
            # It heard something over this stretch, just not these words: share the stretch out.
            t0, t1 = heard[i0]["t0"], heard[i1 - 1]["t1"]
            n = max(1, j1 - j0)
            for k in range(n):
                times[j0 + k] = (t0 + (t1 - t0) * k / n, t0 + (t1 - t0) * (k + 1) / n)
        # "delete": the model heard words the script does not carry -> ignored
        # "insert": written words nobody heard -> filled in below

    first = next((i for i, t in enumerate(times) if t), None)
    last = next((i for i in range(len(times) - 1, -1, -1) if times[i]), None)
    if first is None:                                    # nothing matched at all
        return map_to_written([], text, duration or heard[-1]["t1"])
    end = duration or heard[-1]["t1"]
    # the holes: before the first anchor, between two anchors, and after the last one
    i = 0
    while i < len(times):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(times) and times[j] is None:
            j += 1
        t0 = times[i - 1][1] if i > 0 else max(0.0, times[first][0] - 0.25 * (first - i + 1))
        t1 = times[j][0] if j < len(times) else max(t0 + 0.2, min(end, times[last][1] + 0.6))
        n = j - i
        for k in range(n):
            times[i + k] = (t0 + (t1 - t0) * k / n, t0 + (t1 - t0) * (k + 1) / n)
        i = j

    out, cursor = [], 0.0
    for word, (t0, t1) in zip(written, times):
        t0 = max(cursor, t0)                   # never let a word start before the previous one ended
        t1 = max(t0 + 0.08, t1)
        cursor = t0
        out.append({"t0": round(t0, 3), "t1": round(t1, 3), "text": word})
    return out


def group_words(words, max_words=MAX_WORDS, max_chars=MAX_CHARS, max_dur=MAX_DUR):
    """Groups the words into readable captions: up to `max_words`, cutting at punctuation."""
    groups, current = [], []
    for w in words:
        nxt = current + [w]
        text = " ".join(x["text"] for x in nxt)
        too_long = len(text) > max_chars or (nxt[-1]["t1"] - nxt[0]["t0"]) > max_dur
        if current and too_long:
            groups.append(current)
            current = [w]
        else:
            current = nxt
        # Cutting at every comma leaves one-word flashes: punctuation only breaks a
        # group that already carries two words.
        if len(current) >= max_words or (len(current) >= 2 and current[-1]["text"].endswith(END_PUNCT)):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    out = []
    for g in groups:
        out.append({"t0": round(g[0]["t0"], 3), "t1": round(g[-1]["t1"], 3),
                    "text": " ".join(x["text"] for x in g)})
    # A group that lands under MIN_DUR is unreadable: stretch it into the gap before the next one.
    for i, g in enumerate(out):
        limit = out[i + 1]["t0"] if i + 1 < len(out) else g["t1"] + MIN_DUR
        if g["t1"] - g["t0"] < MIN_DUR:
            g["t1"] = round(min(max(g["t0"] + MIN_DUR, g["t1"]), max(limit, g["t1"])), 3)
    return out


def read_script(path):
    """[{t, text, file?}] from a voice-script (the JSON contract) or from the old plain text."""
    p = Path(os.path.expandvars(os.path.expanduser(str(path))))
    if not p.exists():
        sys.exit(f"missing script: {p}")
    raw = p.read_text(encoding="utf-8", errors="ignore")
    if p.suffix.lower() == ".json" or raw.lstrip().startswith("{"):
        data = json.loads(raw)
        lines = data.get("lines", data if isinstance(data, list) else [])
        out = []
        for i, ln in enumerate(lines):
            if not isinstance(ln, dict) or not str(ln.get("text", "")).strip():
                continue
            out.append({"t": float(next((ln[k] for k in ("start_s", "t", "at")
                                         if ln.get(k) is not None), 0.0)),
                        "text": str(ln["text"]).strip(),
                        "file": ln.get("file"), "i": i})
        return out, (data.get("lang") if isinstance(data, dict) else None)
    # Old plain-text script: "<second>  <sentence>", stopping at a Notes heading.
    out = []
    for ln in raw.splitlines():
        if re.match(r"[#\s]*(notes?|notas?|optional|opcional)\b", ln, re.I):
            break
        m = re.match(r"\s*(?:\[\s*)?~?\s*(\d+(?:\.\d+)?)\s*(?:\])?\s*(?:s\b)?\s*\|?\s+(.+)$", ln)
        if m and len(m.group(2).strip(" |")) >= 8:
            out.append({"t": float(m.group(1)), "text": m.group(2).strip(" |"), "file": None,
                        "i": len(out)})
    return out, None


def line_wavs(where, lines):
    """Pairs every script line with its WAV: the line's own `file`, or l0.wav, l1.wav… in order."""
    where = Path(os.path.expandvars(os.path.expanduser(str(where))))
    if where.is_file():
        return [(lines[0] if lines else {"t": 0.0, "text": "", "i": 0}, where)]
    if not where.is_dir():
        sys.exit(f"missing voice folder: {where}")
    pairs, missing = [], []
    for k, ln in enumerate(lines):
        wav = where / (ln.get("file") or f"l{ln.get('i', k)}.wav")
        if wav.exists():
            pairs.append((ln, wav))
        else:
            missing.append(wav.name)
    if missing:
        sys.exit(f"the voice folder {where} is missing: {', '.join(map(str, missing))}\n"
                 f"Generate the narration first (voices skill) and align afterwards.")
    return pairs


def align(where, lines, args):
    """Word-by-word times for an already generated narration, in the VIDEO's time."""
    pairs = line_wavs(where, lines)
    aligned, captions, overlaps = [], [], []
    for ln, wav in pairs:
        at = float(ln.get("t", 0))
        dur = media_duration(wav)
        heard = _heard_words(wav, args.language, args.model)
        words = map_to_written(heard, ln["text"], dur)
        aligned.append({"i": ln.get("i", len(aligned)), "at": round(at, 3), "file": wav.name,
                        "dur": round(dur, 3) if dur else None, "text": ln["text"],
                        "heard": len(heard),
                        "words": [{"t0": round(at + w["t0"], 3), "t1": round(at + w["t1"], 3),
                                   "text": w["text"]} for w in words]})
        for g in group_words(words):
            captions.append({"t0": round(at + g["t0"], 3), "t1": round(at + g["t1"], 3),
                             "text": g["text"], "style": args.style, "pos": args.pos,
                             "size": args.size, "audio_t0": round(at + g["t0"], 3),
                             "audio_t1": round(at + g["t1"], 3), "line": ln.get("i", 0)})
    for a, b in zip(aligned, aligned[1:]):
        end = (a["words"][-1]["t1"] if a["words"] else a["at"])
        if b["at"] < end - 0.05:
            overlaps.append(f"line {a['i']} still speaking at {end:.2f} s when line {b['i']} "
                            f"comes in at {b['at']:.2f} s")
    # Two captions on top of each other read as a flicker: close each one at the next one's entry.
    for c, nxt in zip(captions, captions[1:]):
        c["t1"] = round(min(c["t1"], max(c["t0"] + 0.25, nxt["t0"])), 3)
    return {"schema": "caption-sync/1", "voice": str(where), "model": args.model,
            "language": args.language,
            "_times": "seconds of the VIDEO: the line's `t` plus the word's offset inside its WAV",
            "_rule": ("the written text wins; the model only contributes times. Feed it to the engine "
                      "with \"sync\": {\"from\": \"<this file>\"} and verify.py checks the drift"),
            "overlaps": overlaps, "lines": aligned, "captions": captions}


# ------------------------------------------------------------ CLI

def main():
    ap = argparse.ArgumentParser(description="Subtitle candidates from a clip, or subtitles aligned "
                                             "to an already generated narration")
    ap.add_argument("clips", nargs="*", help="video or audio files (mode 1)")
    ap.add_argument("--model", default=os.environ.get("REEL_FORGE_WHISPER_MODEL", "small"),
                    help="tiny | base | small (default) | medium | large-v3, or a local path")
    ap.add_argument("--language", default=os.environ.get("REEL_FORGE_LANG"),
                    help="the SPOKEN language, e.g. es, en (default: detected)")
    ap.add_argument("--start", type=float, default=0.0, help="transcribe only from this second")
    ap.add_argument("--dur", type=float, help="…and only this many seconds")
    ap.add_argument("--out", help="folder (or file, for a single clip) for the transcript")
    ap.add_argument("--print", dest="show", action="store_true", help="stdout only, write nothing")
    ap.add_argument("--align", help="the narration's voice folder (l0.wav…) or a single WAV")
    ap.add_argument("--script", help="the voice-script the narration was generated from")
    ap.add_argument("--text", help="the line's text, when --align gets a single WAV")
    ap.add_argument("--at", type=float, default=0.0, help="the second that single WAV comes in on")
    ap.add_argument("--style", default="clean", help="caption style for the aligned subtitles")
    ap.add_argument("--pos", default="low", help="caption position for the aligned subtitles")
    ap.add_argument("--size", type=int, default=52, help="caption size (9x16 reference)")
    args = ap.parse_args()

    # `--language` is the language SPOKEN in the clip, which has nothing to do with the run's
    # output language: a clip in Spanish subtitled into English needs translating, not transcribing.
    if args.align:
        if args.script:
            lines, lang = read_script(args.script)
            if not lines:
                sys.exit(f"no lines parsed out of {args.script}")
        elif args.text:
            lines, lang = [{"t": args.at, "text": args.text, "file": None, "i": 0}], None
        else:
            sys.exit("--align needs --script (the voice-script) or --text plus --at")
        if not args.language and lang:
            args.language = str(lang).split("-")[0].lower()
        data = align(args.align, lines, args)
        text = json.dumps(data, ensure_ascii=False, indent=1)
        if not args.show:
            where = Path(os.path.expandvars(os.path.expanduser(args.align)))
            target = Path(args.out) if args.out else (where if where.is_dir() else where.parent) / "alignment.json"
            if target.is_dir():
                target = target / "alignment.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            print(f"{len(data['lines'])} line(s), {len(data['captions'])} caption(s) → {target}",
                  file=sys.stderr)
            for o in data["overlaps"]:
                print(f"  overlap: {o}", file=sys.stderr)
        print(text)
        return

    if not args.clips:
        sys.exit("give me a clip to transcribe, or --align with --script")

    results = []
    for clip in args.clips:
        src = Path(os.path.expandvars(os.path.expanduser(clip))).resolve()
        if not src.exists():
            sys.exit(f"missing file: {src}")
        data = transcribe(src, args)
        if not args.show:
            if args.out:
                out = Path(os.path.expandvars(os.path.expanduser(args.out)))
                target = out if (out.suffix == ".json" and len(args.clips) == 1) else out / (src.name + ".transcript.json")
            else:
                target = src.with_name(src.name + ".transcript.json")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            data["out"] = str(target)
            print(f"{src.name}: {len(data['segments'])} candidate(s) → {target}", file=sys.stderr)
        results.append(data)

    print(json.dumps(results if len(results) > 1 else results[0], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
