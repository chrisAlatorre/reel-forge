# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Maps a SPOKEN viral audio (a meme, not a song) so the edit can cut by phrase.

A trending song only needs a BPM: the grid is regular and every beat is like the next one. A
spoken audio is the opposite — it has phrases, pauses and **one moment that has to land**. Cutting
it on a BPM grid chops sentences in half and buries the punchline. This script measures the audio
once and writes a `sound-map.json` that says where each phrase starts and ends, how long the pause
after it is, and which phrase is the punchline.

  uv run sound_map.py <URL> sound-map.json                  # fetch, transcribe, map
  uv run sound_map.py --audio local.m4a sound-map.json      # an audio file already on disk
  uv run sound_map.py <URL> sound-map.json --language en --punchline 3
  uv run sound_map.py --audio a.wav sound-map.json --no-transcribe   # pauses only, no text
  uv run sound_map.py --check sound-map.json                # re-read and summarize a map

WHAT THIS AUDIO IS FOR, AND WHAT IT IS NOT FOR
----------------------------------------------
The audio is fetched **to measure it**, the same way the music research fetches a 30 s store
preview to measure BPM. It stays in the cache ($REEL_FORGE_CACHE/sounds/) and the map records
`"embed_in_clean": false`:

  - `x.mp4`          the version that gets uploaded: NO trending audio in it, ever.
  - `x-preview.mp4`  a local preview that may carry it, so the user can see the timing work.

The real sound is attached **inside the app at publish time**, which is also what makes the video
count toward that trend. The map's `usage` block carries this so nothing downstream has to guess.

HOW THE MAP IS BUILT
--------------------
1. **Fetch** with `yt-dlp` (or `uvx yt-dlp` if it is not on the PATH) into the cache, keyed by a
   hash of the URL. A second run over the same URL re-uses it and costs nothing.
2. **Transcribe with word-level timestamps.** `mlx-whisper` on Apple Silicon, `faster-whisper`
   anywhere else; it runs in its own uv environment so this script keeps no heavy dependency.
   The transcript is cached next to the audio.
3. **Group the words into phrases**, splitting on terminal punctuation and on any gap longer than
   `--gap` (0.34 s by default: shorter than that is breathing, not a beat).
4. **Measure every pause** between phrases, and cross-check against ffmpeg's `silencedetect` so a
   pause that the transcriber smoothed over still shows up.
5. **Find the punchline** from the shape of the audio: the phrase that follows the longest pause
   and sits loudest above the median. It is a heuristic and the map says how confident it is —
   listen once and override with `--punchline N` if it picked wrong.

Everything is cached, so an interrupted run resumes for free: re-running after the machine went to
sleep re-uses the download and the transcript and only rebuilds the map.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wordmarks import transcribe_words  # noqa: E402  (same folder, shipped together)

CACHE = Path(os.path.expanduser(os.environ.get("REEL_FORGE_CACHE", "~/.cache/reel-forge"))) / "sounds"
SCHEMA = "sound-map/1"
# A gap shorter than this is breathing inside a phrase, not a beat you can cut on.
DEFAULT_GAP = 0.34
# Terminal punctuation closes a phrase even with no pause after it.
TERMINAL = ".?!…:;。？！"

def die(msg: str, code: int = 1):
    print(f"sound_map: {msg}", file=sys.stderr)
    sys.exit(code)


def sh(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def ffprobe_duration(path: Path) -> float:
    r = sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path))
    try:
        return round(float(r.stdout.strip()), 3)
    except ValueError:
        die(f"ffprobe could not read {path}: is it an audio file?")


def key_for(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def yt_dlp_cmd() -> list:
    """yt-dlp from the PATH, or run it through uv without installing anything permanently."""
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    if shutil.which("uvx"):
        return ["uvx", "yt-dlp"]
    if shutil.which("uv"):
        return ["uv", "tool", "run", "yt-dlp"]
    die("yt-dlp is missing and there is no uv to run it with: `brew install yt-dlp`, or pass "
        "--audio with a file you already have.", 5)


def fetch(url: str, force: bool = False) -> tuple:
    """Downloads the audio into the cache. Returns (wav_path, metadata). Re-uses a previous run."""
    folder = CACHE / key_for(url)
    folder.mkdir(parents=True, exist_ok=True)
    wav = folder / "audio.wav"
    meta_file = folder / "source.json"
    if wav.exists() and meta_file.exists() and not force:
        print(f"· cached audio: {wav}")
        return wav, json.loads(meta_file.read_text(encoding="utf-8"))

    print(f"· fetching the audio to measure it (it is NOT embedded in what gets uploaded)")
    info_file = folder / "info.json"
    r = subprocess.run([*yt_dlp_cmd(), "--no-playlist", "--no-progress", "-x",
                        "--audio-format", "wav", "--audio-quality", "0",
                        "--write-info-json", "--no-write-playlist-metafiles",
                        "-o", str(folder / "audio.%(ext)s"), url],
                       capture_output=True, text=True)
    if r.returncode != 0 or not wav.exists():
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-4:]
        die("yt-dlp could not download that audio.\n  " + "\n  ".join(tail) +
            "\n  If the platform blocks it, download the audio by hand and pass it with --audio.", 5)
    raw_info = {}
    for candidate in (info_file, folder / "audio.info.json"):
        if candidate.exists():
            raw_info = json.loads(candidate.read_text(encoding="utf-8"))
            break
    meta = {
        "url": url,
        "title": raw_info.get("title"),
        "uploader": raw_info.get("uploader") or raw_info.get("channel"),
        "upload_date": raw_info.get("upload_date"),
        "extractor": raw_info.get("extractor_key"),
        "fetched_on": date.today().isoformat(),
    }
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return wav, meta


def to_wav(src: Path) -> Path:
    """Normalizes any input to 16 kHz mono WAV in the cache: what every transcriber wants."""
    folder = CACHE / hashlib.sha256(str(src.resolve()).encode()).hexdigest()[:16]
    folder.mkdir(parents=True, exist_ok=True)
    wav = folder / "audio.wav"
    if not wav.exists():
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src),
                        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], check=True)
    return wav


def transcribe(wav: Path, language: str | None, force: bool = False) -> dict:
    """Word-level transcript, cached beside the audio.

    The transcriber itself lives in `wordmarks.py`, which is the same one that marks a generated
    narration word by word: one audio path into the plugin, one set of timings everything trusts.
    """
    try:
        return transcribe_words(wav, language, cache=wav.parent / "words.json", force=force)
    except RuntimeError as e:
        die(f"{e}\n  You can map the pauses without text with --no-transcribe, or pass an existing "
            "transcript with --transcript words.json ({\"words\": [{\"w\", \"start\", \"end\"}]}).", 6)


def silences(wav: Path, threshold="-32dB", min_dur=0.18) -> list:
    """ffmpeg's own view of where the audio goes quiet: a cross-check on the transcriber's gaps."""
    r = sh("ffmpeg", "-nostdin", "-hide_banner", "-i", str(wav),
           "-af", f"silencedetect=noise={threshold}:d={min_dur}", "-f", "null", "-")
    out, start = [], None
    for ln in r.stderr.splitlines():
        if "silence_start:" in ln:
            start = float(ln.split("silence_start:")[1].split()[0])
        elif "silence_end:" in ln and start is not None:
            end = float(ln.split("silence_end:")[1].split("|")[0])
            out.append({"start": round(start, 3), "end": round(end, 3),
                        "dur": round(end - start, 3), "kind": "silence"})
            start = None
    return out


def loudness(wav: Path, start: float, end: float) -> float:
    """Mean volume of one slice, in dB. Used to compare phrases against each other, nothing else."""
    if end - start < 0.05:
        return -99.0
    r = sh("ffmpeg", "-nostdin", "-hide_banner", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
           "-i", str(wav), "-af", "volumedetect", "-f", "null", "-")
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", r.stderr)
    return round(float(m.group(1)), 2) if m else -99.0


def group(words: list, gap: float) -> list:
    """Words -> phrases. A phrase closes on terminal punctuation or on a gap longer than `gap`."""
    phrases, current = [], []
    for i, w in enumerate(words):
        if not w.get("w"):
            continue
        current.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        closes = w["w"].rstrip()[-1:] in TERMINAL
        if nxt is not None and nxt["start"] - w["end"] >= gap:
            closes = True
        if nxt is None:
            closes = True
        if closes and current:
            phrases.append(current)
            current = []
    if current:
        phrases.append(current)
    return phrases


def build_phrases(words: list, wav: Path, gap: float) -> list:
    out = []
    for i, ws in enumerate(group(words, gap)):
        start, end = ws[0]["start"], ws[-1]["end"]
        text = " ".join(w["w"] for w in ws).strip()
        text = re.sub(r"\s+([,.;:!?…])", r"\1", text)
        out.append({
            "i": i, "start": round(start, 3), "end": round(end, 3),
            "dur": round(end - start, 3), "text": text,
            "words": ws,
            "mean_db": loudness(wav, start, end),
            "confidence": round(statistics.fmean([w.get("p", 0.0) for w in ws]), 3) if ws else 0.0,
        })
    for i, p in enumerate(out):
        p["pause_before"] = round(p["start"] - out[i - 1]["end"], 3) if i else round(p["start"], 3)
        p["pause_after"] = round(out[i + 1]["start"] - p["end"], 3) if i + 1 < len(out) else 0.0
    return out


def phrases_from_silence(wav: Path, total: float, sil: list) -> list:
    """--no-transcribe: the phrases are simply what sits between the silences. No text."""
    spans, cursor = [], 0.0
    for s in sil:
        if s["start"] - cursor > 0.25:
            spans.append((cursor, s["start"]))
        cursor = s["end"]
    if total - cursor > 0.25:
        spans.append((cursor, total))
    out = []
    for i, (a, b) in enumerate(spans):
        out.append({"i": i, "start": round(a, 3), "end": round(b, 3), "dur": round(b - a, 3),
                    "text": "", "words": [], "mean_db": loudness(wav, a, b), "confidence": 0.0})
    for i, p in enumerate(out):
        p["pause_before"] = round(p["start"] - out[i - 1]["end"], 3) if i else round(p["start"], 3)
        p["pause_after"] = round(out[i + 1]["start"] - p["end"], 3) if i + 1 < len(out) else 0.0
    return out


def find_punchline(phrases: list, total: float) -> dict:
    """The remate: the phrase after the longest pause, loudest over the median, late in the audio.

    A heuristic, and it says so. In a meme audio the setup is followed by a beat of silence and
    then the line everybody quotes, usually louder and usually near the end. When two phrases score
    close together the confidence drops and you are meant to listen once and pass --punchline.
    """
    if not phrases:
        return {}
    if len(phrases) == 1:
        return {"phrase": 0, "start": phrases[0]["start"], "end": phrases[0]["end"],
                "why": "there is only one phrase in this audio", "confidence": "high"}
    pauses = [p["pause_before"] for p in phrases[1:]] or [0.0]
    longest_pause = max(pauses)
    dbs = [p["mean_db"] for p in phrases if p["mean_db"] > -90]
    median_db = statistics.median(dbs) if dbs else -99.0
    scored = []
    for p in phrases:
        pause_score = (p["pause_before"] / longest_pause) if longest_pause > 0.01 else 0.0
        loud_score = max(0.0, (p["mean_db"] - median_db)) / 6.0 if p["mean_db"] > -90 else 0.0
        late_score = (p["start"] / total) if total > 0 else 0.0
        # The pause before a line is the strongest signal by far: it is the setup landing. Loudness
        # and position only break ties.
        scored.append((2.0 * pause_score + 1.0 * min(loud_score, 1.5) + 0.6 * late_score, p))
    scored.sort(key=lambda x: -x[0])
    best_score, best = scored[0]
    runner = scored[1][0] if len(scored) > 1 else 0.0
    margin = best_score - runner
    confidence = "high" if margin >= 0.8 else ("medium" if margin >= 0.35 else "low")
    why = (f"pause of {best['pause_before']:.2f} s before it "
           f"(the longest is {longest_pause:.2f} s), {best['mean_db'] - median_db:+.1f} dB over the "
           f"median phrase, starts at {100 * best['start'] / total:.0f} % of the audio")
    return {"phrase": best["i"], "start": best["start"], "end": best["end"], "why": why,
            "confidence": confidence, "margin_over_runner_up": round(margin, 3),
            "heuristic": "listen to it once; --punchline N overrides it"}


def assign_roles(phrases: list, punch_index: int):
    for p in phrases:
        if p["i"] < punch_index:
            p["role"] = "setup"
        elif p["i"] == punch_index:
            p["role"] = "punchline"
        else:
            p["role"] = "tag"


def build_map(wav: Path, meta: dict, words_data: dict, gap: float,
              punch_override: int | None, no_transcribe: bool) -> dict:
    total = ffprobe_duration(wav)
    sil = silences(wav)
    if no_transcribe:
        phrases = phrases_from_silence(wav, total, sil)
        transcript = {"engine": None, "language": None,
                      "note": "--no-transcribe: the phrases come from silence detection, with no text"}
    else:
        phrases = build_phrases(words_data.get("words", []), wav, gap)
        transcript = {"engine": words_data.get("engine"), "language": words_data.get("language"),
                      "words": len(words_data.get("words", []))}
    if not phrases:
        die("no phrases came out of this audio: it may be music with no speech, or the transcriber "
            "heard nothing. Try --no-transcribe to at least map the pauses.", 7)

    punch = find_punchline(phrases, total)
    if punch_override is not None:
        if not 0 <= punch_override < len(phrases):
            die(f"--punchline {punch_override} is out of range: this audio has {len(phrases)} phrases (0-{len(phrases) - 1})", 2)
        p = phrases[punch_override]
        punch = {"phrase": p["i"], "start": p["start"], "end": p["end"],
                 "why": "set by hand with --punchline", "confidence": "given"}
    assign_roles(phrases, punch["phrase"])

    # Gaps the transcriber saw, plus the ones ffmpeg saw that it did not. Both matter: a pause the
    # edit can breathe in is a pause however it was measured.
    pauses = [{"start": p["end"], "end": round(p["end"] + p["pause_after"], 3),
               "dur": p["pause_after"], "kind": "speech_gap"}
              for p in phrases if p["pause_after"] >= gap]
    for s in sil:
        if not any(abs(s["start"] - q["start"]) < 0.2 for q in pauses):
            pauses.append(s)
    pauses.sort(key=lambda q: q["start"])

    # Things that are not fatal but that would quietly produce a bad edit: they go into the map and
    # get printed, because the whole point of measuring is not having to guess later.
    warnings = []
    overlapping = [p["i"] for p in phrases if p["pause_after"] < -0.01]
    if overlapping:
        warnings.append(f"phrases {overlapping} overlap the next one: the marks do not line up, "
                        "check --gap or the transcript before cutting on them")
    if phrases[-1]["end"] > total + 0.05:
        warnings.append(f"the last phrase ends at {phrases[-1]['end']} s but the audio is {total} s: "
                        "the transcript does not belong to this audio, or it drifted")
    weak = [p["i"] for p in phrases if 0 < p["confidence"] < 0.5]
    if weak:
        warnings.append(f"phrases {weak} were transcribed with low confidence: read them before "
                        "putting a cut on their text")
    if punch.get("confidence") == "low":
        warnings.append("the punchline was picked with low confidence: listen to the audio once and "
                        "pass --punchline N if it chose wrong")

    return {
        "schema": SCHEMA,
        "source": {**meta, "audio_cache": str(wav), "duration_s": total},
        "warnings": warnings,
        "usage": {
            "embed_in_clean": False,
            "embed_in_preview": True,
            "note": "This audio was fetched to measure it. It never goes into the file that gets "
                    "uploaded: only into the local -preview. The user attaches the real sound "
                    "inside the app at publish time, which is also what makes the video count "
                    "toward the trend.",
        },
        "transcript": transcript,
        "phrases": phrases,
        "punchline": punch,
        "pauses": pauses,
        # Every phrase start, so the edit can cut per phrase instead of on a BPM grid.
        "cut_grid": [p["start"] for p in phrases],
        "editing": {
            "cut_on": "phrase starts (cut_grid); a cut inside a phrase reads as a mistake",
            "punchline_lands_on": "the best take in the concept: the punchline phrase gets the "
                                  "strongest shot, and no cut happens inside it",
            "breathe_in": "the pauses: a reaction shot or a beat of held frame fits there",
            "total_s": total,
        },
    }


def summarize(m: dict):
    src = m.get("source", {})
    print(f"\n{src.get('title') or src.get('url') or src.get('audio_cache')}  ·  {src.get('duration_s')} s")
    punch = m.get("punchline", {})
    for p in m.get("phrases", []):
        mark = "  <<< PUNCHLINE" if p["i"] == punch.get("phrase") else ""
        text = p["text"] or "(no text: mapped from the pauses)"
        print(f"  [{p['i']:>2}] {p['start']:>6.2f}-{p['end']:<6.2f} ({p['dur']:>4.2f}s, "
              f"pause after {p['pause_after']:>4.2f}s) {text}{mark}")
    if punch:
        print(f"\npunchline: phrase {punch.get('phrase')} at {punch.get('start')} s "
              f"· confidence {punch.get('confidence')} · {punch.get('why')}")
    for w in m.get("warnings", []):
        print(f"WARNING: {w}")
    print("clean version: NO trending audio. -preview only, and the user attaches the real sound "
          "in the app.")


def main():
    ap = argparse.ArgumentParser(
        description="Maps a spoken viral audio into phrases, pauses and a punchline (sound-map.json)")
    ap.add_argument("url", nargs="?", help="the page the audio lives on (yt-dlp downloads it into the cache)")
    ap.add_argument("out", nargs="?", help="where to write sound-map.json")
    ap.add_argument("--audio", help="an audio file already on disk, instead of a URL")
    ap.add_argument("--transcript", help="a transcript you already have: {\"words\": [{\"w\", \"start\", \"end\"}]}")
    ap.add_argument("--language", default=os.environ.get("REEL_FORGE_LANG"),
                    help="the audio's language (default: $REEL_FORGE_LANG; empty = detect it)")
    ap.add_argument("--gap", type=float, default=DEFAULT_GAP,
                    help=f"a pause this long or longer closes a phrase (default {DEFAULT_GAP} s)")
    ap.add_argument("--punchline", type=int, help="force the punchline to be this phrase index")
    ap.add_argument("--no-transcribe", action="store_true",
                    help="map the pauses only, with no text (no model download)")
    ap.add_argument("--refetch", action="store_true", help="ignore the cached download and transcript")
    ap.add_argument("--check", metavar="SOUND-MAP.JSON", help="re-read a map and print its summary")
    a = ap.parse_args()

    if a.check:
        f = Path(a.check)
        if not f.exists():
            die(f"{f} does not exist", 2)
        m = json.loads(f.read_text(encoding="utf-8"))
        if m.get("schema") != SCHEMA:
            die(f"{f} is not a {SCHEMA} file (it says {m.get('schema')!r})", 2)
        return summarize(m)

    # With --audio the URL positional is not used, so a single positional IS the output path:
    # `--audio meme.wav sound-map.json` has to work without a placeholder in front of it.
    if a.audio and a.url and not a.out:
        a.url, a.out = None, a.url
    if not a.out:
        ap.error("where should sound-map.json go? `sound_map.py <URL> sound-map.json`")
    if bool(a.url) == bool(a.audio):
        ap.error("pass either a URL or --audio FILE, not both and not neither")

    CACHE.mkdir(parents=True, exist_ok=True)
    if a.audio:
        src = Path(a.audio)
        if not src.exists():
            die(f"{src} does not exist", 2)
        wav = to_wav(src)
        meta = {"url": None, "title": src.name, "local_file": str(src),
                "fetched_on": date.today().isoformat()}
    else:
        wav, meta = fetch(a.url, force=a.refetch)
        wav = to_wav(wav)

    words_data = {}
    if not a.no_transcribe:
        if a.transcript:
            words_data = json.loads(Path(a.transcript).read_text(encoding="utf-8"))
            words_data.setdefault("engine", f"given: {a.transcript}")
            if not words_data.get("words"):
                die(f"{a.transcript} carries no \"words\" list with start/end marks", 2)
        else:
            words_data = transcribe(wav, a.language, force=a.refetch)

    m = build_map(wav, meta, words_data, a.gap, a.punchline, a.no_transcribe)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    summarize(m)
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
