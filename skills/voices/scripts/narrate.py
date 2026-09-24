# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Glues a narration onto an ALREADY rendered video.

It reads a timed script, generates (or reuses) one WAV per line and mixes them onto the MP4 at
the second each line declares. It does not re-render the video: the video stream is copied
through as is.

Usage:
  uv run narrate.py SCRIPT.txt VIDEO.mp4 OUT.mp4                      # local voice (voice.py --engine qwen)
  uv run narrate.py SCRIPT.txt VIDEO.mp4 OUT.mp4 --engine capcut      # the app's voice (macOS only)
  uv run narrate.py SCRIPT.txt VIDEO.mp4 OUT.mp4 --gen VOICE_FOLDER   # WAVs already generated
  uv run narrate.py SCRIPT.txt --parse-only                           # check how the parsing came out

Script format: one line per delivery, starting with the second it comes in on. It tolerates the
variants that tend to come out of a hand-written script or one written by another agent:

    0.5   This is where it all starts.
    [3.2] And here it goes on.
    7.0 s | 2.4 s | The third line.

Parser rules: it stops at a "Notes" or "Optional" heading (everything below is comments, not
lines), separators and markdown headings are ignored, and lines with no real text get dropped.
The video's original audio is preserved; the voice is summed on top. If you want the music to
duck under the voice, do it when rendering the video, not here.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAPCUT = HERE / "capcut_voice.py"
LOCAL = HERE / "voice.py"


def parse(path):
    """Returns [(second, text)], tolerating the most common script formats."""
    lines = []
    for source_line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        ln = source_line.rstrip()
        # Everything after a "Notes" heading is comments: that is where the table ends.
        # Without this, a comment like "…from 15.8 to 16.9 s). If you bring it in earlier…"
        # comes through as a line.
        # The scripts themselves are written in the run's output language, so the heading is
        # matched in the handful of languages the plugin actually ships voices for.
        if re.match(r"[#\s]*(notes?|notas?|observaciones|obs)\s*:?\s*$", ln, re.I):
            break
        # The "OPTIONAL" block doesn't come in either: it usually overlaps a required line and
        # buries it. If you really want it, move it into the table with its own second.
        if re.match(r"[#\s]*(optional|opcional|opcionais)\b", ln, re.I):
            break
        if not ln.strip() or ln.lstrip().startswith(("---", "===", "#")):
            continue
        m = re.match(r"\s*(?:\[\s*)?~?\s*(\d+(?:\.\d+)?)\s*(?:\])?\s*(?:s\b)?\s*(?:\|)?\s+(?:~?\s*[\d.]+\s*s?\s+)?(.+)$", ln)
        if not m:
            continue
        t, text = float(m.group(1)), m.group(2).strip(" |")
        text = re.sub(r"\s{2,}[\d.]+\s*s\.?$", "", text).strip()
        # Leftovers from duration columns: "0.5  2.4 s  text", "0.20s ~2.7s text", "~1.4 s  text"
        text = re.sub(r"^(?:s\b|~?\s*[\d.]+\s*s\b|\d+)\s*", "", text).strip()
        text = re.sub(r"^~?\s*[\d.]+\s*s\b\s*", "", text).strip()
        text = text.strip(" |\t")   # leftovers from the duration column in tabular scripts
        if len(text) < 8 or not re.search(r"[^\W\d_]{3}", text, re.UNICODE):
            continue
        if text.lower().startswith(("line", "in", "dur", "duration", "video", "optional", "notes")):
            continue
        lines.append((t, text))
    return lines


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
    ap.add_argument("--engine", default="qwen", choices=["qwen", "voxcpm", "piper", "capcut"],
                    help="qwen (local, default) | voxcpm | piper | capcut (macOS, the app's voice)")
    ap.add_argument("--voice", help="the voice name for the chosen engine")
    ap.add_argument("--language", default=os.environ.get("REEL_FORGE_LANG"),
                    help="the narration's language, e.g. en, es-MX (default: $REEL_FORGE_LANG)")
    ap.add_argument("--gen", help="a folder with l0.wav… already generated; otherwise it generates them")
    ap.add_argument("--speed", type=float, default=1.4, help="--engine capcut only: the trend's pace")
    ap.add_argument("--volume", type=float, default=1.0, help="the voice's gain over the video's audio")
    ap.add_argument("--parse-only", action="store_true")
    a = ap.parse_args()

    lines = parse(a.script)
    if not lines:
        sys.exit(f"no lines in {a.script}")
    print(json.dumps([{"t": t, "text": x} for t, x in lines], ensure_ascii=False, indent=1))
    if a.parse_only:
        return
    if not (a.video and a.out):
        ap.error("VIDEO.mp4 and OUT.mp4 are missing")

    folder = Path(a.gen) if a.gen else Path(a.out).parent / ("voices-" + Path(a.out).stem)
    folder.mkdir(parents=True, exist_ok=True)
    # durations.json is the "folder is complete" signal: if it's missing, it gets (re)generated
    # and resumes on its own.
    if not (folder / "durations.json").exists():
        generate(a.engine, lines, folder, a.speed, a.voice, a.language)

    wavs = [folder / f"l{i}.wav" for i in range(len(lines))]
    missing = [w for w in wavs if not w.exists()]
    if missing:
        sys.exit(f"missing audio: {missing[:3]}")

    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", a.video]
    filters = []
    for i, ((t, _), w) in enumerate(zip(lines, wavs)):
        cmd += ["-i", str(w)]
        ms = int(t * 1000)
        filters.append(f"[{i + 1}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                       f"adelay={ms}|{ms},volume={a.volume}[v{i}]")

    has_audio = bool(ffprobe("-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", a.video))
    inputs = ("[0:a]" if has_audio else "") + "".join(f"[v{i}]" for i in range(len(lines)))
    n = len(lines) + (1 if has_audio else 0)
    length = float(ffprobe("-show_entries", "format=duration", "-of", "csv=p=0", a.video))
    # CAREFUL: no duration=first. If the video comes in WITHOUT audio, the amix's first input is
    # the first voice line and the mix gets cut when that line ends. Take the longest one, PAD it
    # to the video's length and only then trim: `atrim` alone cannot extend, so without the `apad`
    # a silent video ends up with an audio track that stops at the last narration line.
    filters.append(f"{inputs}amix=inputs={n}:normalize=0:duration=longest,"
                   f"apad=whole_dur={length:.3f},atrim=0:{length:.3f},"
                   f"asetpts=N/SR/TB,alimiter=limit=0.95[a]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[a]", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", a.out]
    subprocess.run(cmd, check=True)
    print("ok:", a.out)


if __name__ == "__main__":
    main()
