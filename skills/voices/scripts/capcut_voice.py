# /// script
# requires-python = ">=3.10"
# dependencies = ["pyobjc-framework-Quartz"]
# ///
"""CapCut's narrator voice (macOS), by driving the desktop app with clicks.

macOS ONLY. The voices in CapCut's catalog are ByteDance's and only exist inside the app: there
is no public API, so this automates the interface. It is fragile by definition: it depends on the
window size and on CapCut's version, and an update can break it. The stable path is
`voice.py --engine qwen` (local, Apache-2.0). Use this one only when the script specifically
calls for the app's viral voice.

What it does NOT do and must not do: it clones no real person's voice, it touches no unofficial
APIs and it uses nobody's session or cookies. It only presses buttons in an installed app.

Usage:
  uv run capcut_voice.py --prepare                    # once per batch: leaves CapCut ready
  uv run capcut_voice.py lines.json folder [--speed 1.4] [--voice "Catalog voice name"]
  uv run capcut_voice.py --calibrate                  # a screenshot with the coordinates marked

lines.json: ["sentence 1", "sentence 2", ...]. It writes l0.wav, l1.wav... and durations.json into
the folder, i.e. the SAME contract as scripts/voice.py: narrate.py and the editing engine consume
them unchanged.

CapCut project requirements (--prepare explains them, see SKILL.md):
  - A freshly created project. One with hundreds of generations on it stops producing audio, silently.
  - A single text clip on the text track (the topmost one) with the voice already applied and
    generated once by hand.
For each line the script pastes the text, picks the voice again and presses "Generate voice content"
(recent versions removed the "Update the voice from the script" checkbox, so there is no automatic
regeneration). Every generation adds a new audio track: that's fine, the WAV gets collected from
textReading/.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# CapCut desktop's drafts folder on macOS (movable with $CAPCUT_DRAFTS).
CAPCUT = Path(os.path.expanduser(os.environ.get(
    "CAPCUT_DRAFTS", "~/Movies/CapCut/User Data/Projects/com.lveditor.draft")))
# Only used in messages and diagnostics: the script clicks a fixed grid position, it does not look
# the voice up by name. Pass the real name with --voice or $REEL_FORGE_CAPCUT_VOICE so the messages
# say which one was expected. CapCut's catalog changes by country and by app version.
DEFAULT_VOICE = os.environ.get("REEL_FORGE_CAPCUT_VOICE", "the voice applied to the text clip")
# Coordinates in logical points with CapCut's window at (0, 33) and a size of 1728x999
# (a 1728x1117 point screen). With another screen or version, recalibrate with --calibrate.
WINDOW = {"pos": (0, 33), "size": (1728, 999)}
P = {
    "timeline": (700, 900),        # a point inside the timeline (to scroll it to the top)
    "text_clip": (450, 888),       # the text clip, near its start (track TI, the topmost one)
    "text_tab": (1141, 90),        # the right panel's "Text" tab
    "text_box": (1417, 197),       # the box where the script gets typed
    "tts_tab": (1398, 90),         # the "Text to speech" tab
    "narration_chip": (1550, 138),  # the "Narration" category chip (takes the list to that section)
    "voice": (1380, 436),          # the voice inside the "Narration" grid (4th row, 4th col in 7.5.0)
    "generate": (1634, 739),       # the "Generate voice content" button (bottom right of the panel)
}
# Silence trimmed from both edges + a gentle high-pass (the same "clean" FX as voice.py). No reverb.
TRIM = ("areverse,silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.08,areverse,"
        "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05")
FX = f"{TRIM},highpass=f=60"


def sh(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def cliclick(*args):
    if not shutil.which("cliclick"):
        sys.exit("cliclick is missing: brew install cliclick")
    subprocess.run(["cliclick", *args], check=True)


def place_window():
    """Puts CapCut's window at a known position and size (the coordinates depend on it)."""
    x, y = WINDOW["pos"]
    w, h = WINDOW["size"]
    for prop, val in (("position", f"{{{x}, {y}}}"), ("size", f"{{{w}, {h}}}")):
        sh("osascript", "-e",
           f'tell application "System Events" to tell process "CapCut" to set {prop} of window 1 to {val}')
    time.sleep(1)


def project() -> Path:
    """The open project's textReading folder (the most recently modified draft)."""
    drafts = [p for p in CAPCUT.glob("*/*") if p.is_dir() and (p / "draft_info.json").exists()]
    if not drafts:
        sys.exit(f"I can't find any CapCut projects in {CAPCUT}")
    d = max(drafts, key=lambda p: p.stat().st_mtime)
    tr = d / "textReading"
    tr.mkdir(exist_ok=True)
    return tr


def scroll(x, y, clicks, n=1):
    """The mouse wheel (cliclick can't scroll)."""
    import Quartz
    Quartz.CGWarpMouseCursorPosition(Quartz.CGPointMake(float(x), float(y)))
    time.sleep(0.2)
    for _ in range(n):
        Quartz.CGEventPost(Quartz.kCGHIDEventTap,
                           Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, clicks))
        time.sleep(0.05)


def set_text(line: str):
    """Pastes the line into the text clip, picks the voice again and presses "Generate voice content".

    Since CapCut 7.5.0 the Text to speech panel no longer carries the "Update the voice from the
    script" checkbox, so changing the text and deselecting regenerates nothing: you have to press
    Generate every time (and click the voice again, because the button stays disabled otherwise).
    """
    def click(k, wait=1.5):
        cliclick(f"c:{P[k][0]},{P[k][1]}")
        time.sleep(wait)

    subprocess.run(["pbcopy"], input=line, text=True, check=True)
    # Scroll the timeline all the way up: the TI track is always at the top. It needs a lot of
    # scrolling because every generation adds a new audio track and the list grows during the batch.
    scroll(*P["timeline"], 5, 30)
    time.sleep(0.6)
    click("text_clip")             # select the text clip
    click("text_tab")
    click("text_box", 0.8)
    cliclick("kd:cmd", "t:a", "ku:cmd"); time.sleep(0.6)
    cliclick("kd:cmd", "t:v", "ku:cmd"); time.sleep(1.0)
    click("tts_tab", 2.0)
    click("narration_chip", 2.0)   # the list always goes back to the start of "Narration"
    click("voice", 2.5)            # re-enables the Generate button
    click("generate", 0.5)


def wait_for_wav(tr: Path, before: set, timeout=90):
    """Returns the new WAV, or None if CapCut generated nothing within the time limit."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(1.5)
        new = {p for p in tr.glob("*.wav")} - before
        if new:
            p = max(new, key=lambda q: q.stat().st_mtime)
            size = -1
            while size != p.stat().st_size:   # wait for it to finish being written
                size = p.stat().st_size
                time.sleep(0.8)
            return p
    return None


def state(draft: Path) -> dict:
    """Reads draft_info.json: what text the clip carries, whether the checkbox is still on, and
    which voice it uses.

    It tells the two possible failures apart when no audio comes out:
      - the clip's text did NOT change  -> the clicks are landing wrong, recalibrate
      - the text DID change             -> CapCut got the script and refused to generate
    """
    f = draft / "draft_info.json"
    try:
        d = json.loads(f.read_text())
    except Exception as e:
        return {"error": str(e)}
    texts = [json.loads(t["content"]).get("text", "") for t in d.get("materials", {}).get("texts", [])]
    auto = [t.get("tts_auto_update") for t in d.get("materials", {}).get("texts", [])]
    voices = [a.get("tone_effect_name", "") for a in d.get("materials", {}).get("audios", [])]
    return {"text": texts[0] if texts else None, "auto_update": auto[0] if auto else None,
            "voices": voices, "saved": f.stat().st_mtime}


def diagnose(draft: Path, line: str, voice: str = DEFAULT_VOICE) -> str:
    e = state(draft)
    if e.get("error"):
        return f"I couldn't read draft_info.json ({e['error']})"
    arrived = (e.get("text") or "").strip() == line.strip()
    if not arrived:
        return ("the text did NOT reach the clip (the clip says "
                f"{(e.get('text') or '')[:40]!r}): the clicks are landing wrong, run --calibrate and adjust the P dict")
    if not any(voice in v for v in e.get("voices") or []):
        return (f"the text did arrive, but no audio clip uses {voice}: the click in the voice grid "
                "landed outside. Run --calibrate and adjust P['narration_chip'] and P['voice'].")
    return (f"the text arrived and the voice is {voice}, but CapCut wrote no audio. Usually the "
            "project got into a bad state (it happens after many regenerations): create a new "
            "project with --prepare and try again. If that doesn't work either, try by hand with a "
            "voice with NO diamond badge: if that one generates, the problem is only with the "
            "premium voices.")


def duration(f: Path) -> float:
    r = sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f))
    return round(float(r.stdout), 3)


def loudnorm_2pass(src: Path, dst: Path, speed: float):
    """atempo (preserves pitch) + silence trimming + a 2-pass loudnorm to -16 LUFS."""
    pre = f"atempo={speed:.4f},{FX}" if speed != 1.0 else FX
    ln = "loudnorm=I=-16:TP=-1.5:LRA=11"
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(src), "-af", f"{pre},{ln}:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True, check=True)
    m = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
    measured = (f"{ln}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
                f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-af", f"{pre},{measured}",
                    "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)], check=True)


def prepare():
    print("Manual steps (once per batch, ~1 minute):\n"
          "  1. CapCut -> File -> New project. ALWAYS a new one: a project with hundreds of\n"
          "     regenerations stops producing audio (it fails silently, with no message).\n"
          "  2. Text -> Add text -> hover over 'Default text' and press its + button.\n"
          "  3. Right panel -> 'Text' tab -> paste the first line there (Cmd+V; do NOT type with\n"
          "     AppleScript: it eats the spaces and the accents).\n"
          "  4. 'Text to speech' tab -> 'Narration' chip -> click the voice -> 'Generate voice content'.\n"
          "     An audio track 'Text to speech <the voice>' has to appear.\n"
          "  5. Drag the divider between the player and the timeline down until the 'Generate voice\n"
          "     content' button sits at the height P['generate'] says (--calibrate).\n"
          "Then: uv run capcut_voice.py lines.json folder/")
    sh("open", "-a", "CapCut")
    place_window()


def split_by_silence(src: Path, out: Path, n: int, speed: float, threshold="-38dB", min_silence=0.45):
    """Plan B: one audio file with the whole script, cut by silences into l0.wav, l1.wav...

    Useful if the app's cycle fails: paste the whole script (one line per paragraph), generate
    once and cut here. Adjust --threshold/--min-silence if the number of chunks doesn't match the
    number of lines.
    """
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(src), "-af",
                        f"silencedetect=noise={threshold}:d={min_silence}", "-f", "null", "-"],
                       capture_output=True, text=True, check=True)
    starts, ends = [], []
    for ln in r.stderr.splitlines():
        if "silence_start:" in ln:
            ends.append(float(ln.split("silence_start:")[1].split()[0]))
        elif "silence_end:" in ln:
            starts.append(float(ln.split("silence_end:")[1].split("|")[0]))
    total = duration(src)
    cuts = list(zip([0.0] + starts, ends + [total]))
    cuts = [(a, b) for a, b in cuts if b - a > 0.3]
    print(f"{len(cuts)} chunks detected" + (f" (you expected {n})" if n else ""))
    out.mkdir(parents=True, exist_ok=True)
    durations = {}
    for i, (a, b) in enumerate(cuts):
        chunk = out / f"l{i}.raw.wav"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-ss", f"{a:.3f}",
                        "-to", f"{b:.3f}", "-c:a", "pcm_s16le", str(chunk)], check=True)
        loudnorm_2pass(chunk, out / f"l{i}.wav", speed)
        chunk.unlink()
        durations[f"l{i}"] = duration(out / f"l{i}.wav")
        print(f"l{i} {durations[f'l{i}']}s")
    json.dump(durations, open(out / "durations.json", "w"), ensure_ascii=False, indent=1)


def calibrate():
    place_window()
    out = Path(tempfile.gettempdir()) / "capcut-calibrate.png"
    sh("screencapture", "-x", str(out))
    marks = ",".join(f"{k}=({v[0]},{v[1]})" for k, v in P.items())
    print(f"Screenshot at {out}. Current coordinates (logical points): {marks}\n"
          "Open it and check that each point lands where it says. If not, adjust this script's P dict.")


def main():
    ap = argparse.ArgumentParser(description="CapCut's narrator voice, driven by clicks (macOS)")
    ap.add_argument("lines", nargs="?", help="JSON file with the list of sentences")
    ap.add_argument("out", nargs="?", help="output folder for l0.wav, l1.wav… and durations.json")
    ap.add_argument("--speed", type=float, default=1.4, help="1.4 is the trend's pace (default)")
    ap.add_argument("--voice", default=DEFAULT_VOICE, help="the voice's name in the catalog (messages and diagnostics only)")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--keep-raw", action="store_true", help="also keeps the wav exactly as CapCut produced it")
    ap.add_argument("--split", metavar="AUDIO.WAV",
                    help="plan B: cuts an audio file holding the whole script by silences (uses 'out' as the folder)")
    ap.add_argument("--threshold", default="-38dB")
    ap.add_argument("--min-silence", type=float, default=0.45)
    a = ap.parse_args()
    if a.prepare:
        return prepare()
    if a.calibrate:
        return calibrate()
    if a.split:
        # With --split the lines file is optional, so a single positional IS the output folder:
        # `--split audio.wav ./out` has to work without a placeholder lines.json in front.
        out = a.out or a.lines
        lines_file = a.lines if a.out else None
        if not out:
            ap.error("--split needs the output folder: --split AUDIO.WAV OUT_FOLDER")
        n = len(json.load(open(lines_file))) if lines_file else 0
        return split_by_silence(Path(a.split), Path(out), n, a.speed, a.threshold, a.min_silence)
    if not a.lines or not a.out:
        ap.error("lines.json and the output folder are missing")

    lines = json.load(open(a.lines))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tr = project()
    e = state(tr.parent)
    print(f"CapCut project: {tr.parent}\n  text clip: {(e.get('text') or '')[:50]!r} · "
          f"voices on the timeline: {sorted(set(e.get('voices') or []))}")
    if len(e.get("voices") or []) > 60:
        print("  WARNING: this project already carries a lot of generations; if it starts failing, create a new one")
    if not any(a.voice in v for v in e.get("voices") or []):
        print(f"  WARNING: no audio clip uses {a.voice}: apply the voice again (see --prepare)")
    sh("open", "-a", "CapCut")
    time.sleep(2)
    place_window()

    durations = {}
    for i, line in enumerate(lines):
        final = out / f"l{i}.wav"
        if final.exists():   # resume: don't spend quota on what is already done
            durations[f"l{i}"] = duration(final)
            print(f"l{i} {durations[f'l{i}']}s  ·  (already there)", flush=True)
            continue
        raw = None
        for attempt in (1, 2):
            before = set(tr.glob("*.wav"))
            set_text(line)
            raw = wait_for_wav(tr, before)
            if raw:
                break
            print(f"l{i}: no audio on the first attempt, retrying…", flush=True)
            time.sleep(3)
        if not raw:
            # durations.json is deliberately NOT written: that is the "incomplete folder" signal
            # narrate.py uses to call this script again.
            sys.exit(f"CapCut generated no audio for l{i} ({line[:50]!r}).\n  Diagnosis: "
                     f"{diagnose(tr.parent, line, a.voice)}\n  What got generated so far stays in {out} "
                     f"(running it again resumes from l{i}).")
        if a.keep_raw:
            shutil.copy2(raw, out / f"l{i}.capcut.wav")
        loudnorm_2pass(raw, final, a.speed)
        durations[f"l{i}"] = duration(final)
        print(f"l{i} {durations[f'l{i}']}s  ·  {line[:60]}", flush=True)
    json.dump(durations, open(out / "durations.json", "w"), ensure_ascii=False, indent=1)
    print(f"\n{len(lines)} lines in {out} (+ durations.json)")


if __name__ == "__main__":
    main()
