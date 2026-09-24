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

The voice it is set up for is **Valentino at 1.4x**, the default for Spanish narration in this
plugin (see resolve_voice.py). Any other catalog voice works the same way: recalibrate P['voice']
onto its cell and pass --voice with its name.

Usage:
  uv run capcut_voice.py --prepare                    # once per batch: leaves CapCut ready
  uv run capcut_voice.py lines.json folder [--speed 1.4] [--voice "Valentino"]
  uv run capcut_voice.py --calibrate                  # a screenshot with the coordinates marked
  uv run capcut_voice.py --preflight                  # only the checks, generates nothing

lines.json: ["sentence 1", "sentence 2", ...]. It writes l0.wav, l1.wav... and durations.json into
the folder, i.e. the SAME contract as scripts/voice.py: narrate.py and the editing engine consume
them unchanged.

IT FAILS LOUDLY, NEVER IN SILENCE
---------------------------------
Two things go wrong in a real batch, and both used to look like "it just stopped working":

  - **The interface moved.** A CapCut update shifts the buttons and every click lands somewhere
    else. The text never reaches the clip, so the script keeps generating nothing.
  - **The project got saturated.** After roughly a hundred generations CapCut stops writing WAVs:
    the "Generating…" dialog appears, closes, and no file shows up, with no error at all.

The script tells them apart by reading the project's own `draft_info.json`, says which one it is in
one actionable line, and **for saturation it retries once with a brand-new project**. If it still
cannot generate, it exits with a non-zero code and what got generated so far stays on disk so a
re-run resumes:

  exit 2  bad arguments
  exit 3  the interface moved: run --calibrate and fix the P dict
  exit 4  the project is saturated and the new-project retry did not fix it
  exit 5  the environment is missing something (cliclick, CapCut, the drafts folder, permissions)

The batch also runs under `caffeinate`, because a click-driven run dies the moment the machine goes
to sleep and takes the whole batch with it.

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
# The voice this path exists for. **Valentino** is the narrator voice the Spanish-speaking side of
# the platform actually sounds like, and it is the default for any Spanish run where CapCut is
# installed (`resolve_voice.py` is where that decision is made).
#
# Careful: the script clicks a fixed grid position, it does NOT look the voice up by name. The name
# is what the diagnostics compare against `draft_info.json` — that is how "the click landed outside
# the grid" is told apart from "the project is saturated" — and what the messages say. Point
# P['voice'] at the right cell with --calibrate, then pass the name with --voice or
# $REEL_FORGE_CAPCUT_VOICE. CapCut's catalog changes by country and by app version.
DEFAULT_VOICE = os.environ.get("REEL_FORGE_CAPCUT_VOICE", "Valentino")
# The pace of the documentary-narration trend, applied OUTSIDE CapCut with atempo (pitch is kept).
DEFAULT_SPEED = 1.4
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
    "voice": (1380, 436),          # Valentino inside the "Narration" grid (4th row, 4th col in 7.5.0)
    "generate": (1634, 739),       # the "Generate voice content" button (bottom right of the panel)
    # Only used by the automatic recovery (a new project after saturation). They are NOT exercised
    # by a normal batch, so treat them as unverified until --calibrate has confirmed them: the
    # recovery checks its own result in draft_info.json, so a wrong coordinate here ends in exit 4
    # with the manual steps, never in a silent half-built project.
    "media_text_tab": (150, 88),   # the left panel's "Text" tab (Media / Audio / Text / Stickers…)
    "default_text_add": (250, 210),  # the "+" on the "Default text" tile of that panel
}
# Exit codes. Anything other than 0 means nothing usable was produced for the line it stopped on.
EXIT_ARGS = 2
EXIT_UI = 3           # the interface moved: the clicks no longer land where they should
EXIT_SATURATED = 4    # the project stopped generating and a new project did not fix it
EXIT_ENV = 5          # cliclick / CapCut / the drafts folder / automation permissions
# The CapCut versions this coordinate table was written against. A different one is not fatal —
# it is a warning, because the checks below catch a real mismatch anyway.
KNOWN_VERSIONS = ("7.5.",)
# Generations on one project's timeline before it is worth warning, and before this script
# refuses to start a long batch on it. The observed cap sits somewhere around a hundred.
SATURATION_WARN = 60
SATURATION_REFUSE = 100
# Silence trimmed from both edges + a gentle high-pass (the same "clean" FX as voice.py). No reverb.
TRIM = ("areverse,silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.08,areverse,"
        "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05")
FX = f"{TRIM},highpass=f=60"


def sh(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def die(msg: str, code: int):
    """Every failure leaves through here: a code that is not 0 and a message that says what to do."""
    sys.stdout.flush()   # or the message lands above the progress lines it refers to
    print(f"\ncapcut_voice: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def cliclick(*args):
    if not shutil.which("cliclick"):
        die("cliclick is missing: brew install cliclick", EXIT_ENV)
    subprocess.run(["cliclick", *args], check=True)


def osa(script: str):
    return sh("osascript", "-e", script)


def window_geometry():
    """(x, y, w, h) of CapCut's window, or None if System Events cannot see it."""
    r = osa('tell application "System Events" to tell process "CapCut" to '
            'get (position of window 1) & (size of window 1)')
    try:
        nums = [int(float(n)) for n in r.stdout.strip().split(", ")]
        return tuple(nums[:4]) if len(nums) >= 4 else None
    except ValueError:
        return None


def place_window(strict: bool = False):
    """Puts CapCut's window at a known position and size (the coordinates depend on it).

    With strict=True it also reads the geometry back. If the window did not move, every coordinate
    in P is meaningless and the run has to stop: that is usually a missing Accessibility permission
    or a CapCut that is not actually open, and clicking anyway is how a batch ends up pasting text
    into whatever app is underneath.
    """
    x, y = WINDOW["pos"]
    w, h = WINDOW["size"]
    for prop, val in (("position", f"{{{x}, {y}}}"), ("size", f"{{{w}, {h}}}")):
        osa(f'tell application "System Events" to tell process "CapCut" to set {prop} of window 1 to {val}')
    time.sleep(1)
    if not strict:
        return None
    got = window_geometry()
    if got is None:
        die("System Events cannot see CapCut's window. Open CapCut with a project on screen, and "
            "grant Accessibility + Automation permissions to the terminal in System Settings → "
            "Privacy & Security. This does not work over a remote session or with the display off.",
            EXIT_ENV)
    if abs(got[0] - x) > 4 or abs(got[1] - y) > 4 or abs(got[2] - w) > 8 or abs(got[3] - h) > 8:
        die(f"CapCut's window would not go to {x},{y} {w}x{h}: it is at {got[0]},{got[1]} "
            f"{got[2]}x{got[3]}. Every coordinate in P assumes the documented geometry, so the "
            "clicks would land in the wrong place. Usually the screen is smaller than 1728x1117, or "
            "the window is full screen. Leave full screen, or re-measure with --calibrate and adjust "
            "WINDOW and P.", EXIT_UI)
    return got


def capcut_version():
    """CapCut's version string, or None. Only used to warn that P may be stale."""
    for app in (Path("/Applications/CapCut.app"), Path(os.path.expanduser("~/Applications/CapCut.app"))):
        plist = app / "Contents" / "Info.plist"
        if plist.exists():
            r = sh("defaults", "read", str(plist.with_suffix("")), "CFBundleShortVersionString")
            v = r.stdout.strip()
            if v:
                return v
    return None


def drafts() -> list:
    return [p for p in CAPCUT.glob("*/*") if p.is_dir() and (p / "draft_info.json").exists()]


def project() -> Path:
    """The open project's textReading folder (the most recently modified draft)."""
    found = drafts()
    if not found:
        die(f"I can't find any CapCut projects in {CAPCUT}. Open CapCut, create a project and run "
            "--prepare. If your drafts live elsewhere, point $CAPCUT_DRAFTS at them.", EXIT_ENV)
    d = max(found, key=lambda p: p.stat().st_mtime)
    tr = d / "textReading"
    tr.mkdir(exist_ok=True)
    return tr


def keep_awake():
    """Holds the machine awake for as long as this process lives.

    A click-driven batch dies the second the display sleeps, and it takes every line that had not
    been written yet with it. `caffeinate -w <pid>` goes away on its own when this process ends,
    including when it is killed.
    """
    if sys.platform != "darwin" or not shutil.which("caffeinate"):
        return None
    try:
        return subprocess.Popen(["caffeinate", "-dimsu", "-w", str(os.getpid())],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None


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


def classify(draft: Path, line: str, voice: str = DEFAULT_VOICE) -> tuple:
    """Why no audio came out, as (kind, message). The kind decides what happens next.

      "unreadable" → the draft can't be read at all: environment problem.
      "ui"         → the text never reached the clip, or the voice grid click missed. The interface
                     moved and no amount of retrying fixes it; recalibrate.
      "saturated"  → the text arrived, the voice is right, CapCut simply wrote nothing. That is the
                     hundred-generations wall, and a NEW PROJECT is the known cure.
    """
    e = state(draft)
    if e.get("error"):
        return "unreadable", (f"I couldn't read draft_info.json ({e['error']}). Check that CapCut is "
                              f"open on a real project and that {CAPCUT} is the right drafts folder "
                              "($CAPCUT_DRAFTS).")
    arrived = (e.get("text") or "").strip() == line.strip()
    if not arrived:
        return "ui", ("the text did NOT reach the clip (the clip says "
                      f"{(e.get('text') or '')[:40]!r}): the clicks are landing wrong. CapCut almost "
                      "certainly moved its buttons in an update. Run --calibrate, compare the "
                      "screenshot against the P dict and fix the coordinates.")
    if not any(voice in v for v in e.get("voices") or []):
        return "ui", (f"the text did arrive, but no audio clip uses {voice}: the click in the voice "
                      "grid landed outside. Run --calibrate and adjust P['narration_chip'] and "
                      "P['voice'] (the grid is redrawn between versions and between countries).")
    return "saturated", (f"the text arrived and the voice is {voice}, but CapCut wrote no audio. "
                         "That is the saturated project: after ~100 generations it stops producing "
                         "WAVs with no error. The cure is a NEW project. If a new project doesn't "
                         "generate either, apply a voice with NO diamond badge by hand: if that one "
                         "works, the cap is on the premium voices only.")


def diagnose(draft: Path, line: str, voice: str = DEFAULT_VOICE) -> str:
    return classify(draft, line, voice)[1]


def new_project(voice: str, sample: str) -> Path:
    """Creates a fresh CapCut project and rebuilds the text clip in it. Returns its textReading.

    This is the recovery from a saturated project, and it is the only automatic retry the script
    does. Everything it presses is verified afterwards against draft_info.json: if the new draft
    never appears, or the text never lands in it, the caller fails with a non-zero exit instead of
    carrying on against a project that cannot generate.
    """
    before = {str(p) for p in drafts()}
    print("· the project is saturated: creating a new one and rebuilding the text clip", flush=True)
    # The menu item is more robust than a coordinate, but its name is localized, so Cmd+N is the
    # fallback. Whether either worked is decided by the draft check below, not by the return code.
    osa('tell application "System Events" to tell process "CapCut" to click menu item 1 of menu 1 '
        'of menu bar item 1 of menu bar 1')
    time.sleep(1.5)
    cliclick("kd:cmd", "t:n", "ku:cmd")
    time.sleep(6)
    place_window()

    # A brand-new project has no draft_info.json until it holds something, so the text clip gets
    # built first and the new draft is looked for afterwards.
    def click(k, wait=1.5):
        cliclick(f"c:{P[k][0]},{P[k][1]}")
        time.sleep(wait)

    subprocess.run(["pbcopy"], input=sample, text=True, check=True)
    click("media_text_tab", 2.0)      # left panel → Text
    click("default_text_add", 2.5)    # "Default text" → +
    click("text_tab")
    click("text_box", 0.8)
    cliclick("kd:cmd", "t:a", "ku:cmd"); time.sleep(0.5)
    cliclick("kd:cmd", "t:v", "ku:cmd"); time.sleep(1.0)
    click("tts_tab", 2.0)
    click("narration_chip", 2.0)
    click("voice", 2.5)
    click("generate", 0.5)
    time.sleep(8)

    fresh = [p for p in drafts() if str(p) not in before]
    if not fresh:
        die("I pressed 'New project' and rebuilt the text clip, but no new CapCut draft appeared in "
            f"{CAPCUT}. Do it by hand — the steps are in --prepare — and run this again: what was "
            "already generated is kept and the batch resumes.", EXIT_SATURATED)
    d = max(fresh, key=lambda p: p.stat().st_mtime)
    e = state(d)
    if (e.get("text") or "").strip() != sample.strip():
        die(f"the new project was created ({d.name}) but the text never reached its clip "
            f"(it says {(e.get('text') or '')[:40]!r}). The coordinates for building a text clip "
            "(P['media_text_tab'], P['default_text_add']) are the least exercised ones in this "
            "script. Build the clip by hand following --prepare and run this again: the batch "
            "resumes where it stopped.", EXIT_UI)
    tr = d / "textReading"
    tr.mkdir(exist_ok=True)
    print(f"· new project ready: {d.name}", flush=True)
    return tr


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
          f"  4. 'Text to speech' tab -> 'Narration' chip -> click {DEFAULT_VOICE} -> 'Generate voice\n"
          "     content'. An audio track 'Text to speech <the voice>' has to appear.\n"
          "     Another voice works too: recalibrate P['voice'] onto its cell and pass --voice.\n"
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


def preflight(voice: str = DEFAULT_VOICE, long_batch: bool = True) -> Path:
    """Everything that has to be true before the first click. Returns the project's textReading.

    Checking up front is the difference between "it stopped after line 3 and nobody knows why" and
    a message that names the problem before a single WAV has been generated.
    """
    if sys.platform != "darwin":
        die("this path only works on macOS: it automates the CapCut desktop app. Use "
            "`voice.py --engine qwen` (local, cross-platform on Apple Silicon) or `--engine piper` "
            "anywhere.", EXIT_ENV)
    if not shutil.which("cliclick"):
        die("cliclick is missing: brew install cliclick", EXIT_ENV)
    if not shutil.which("ffmpeg"):
        die("ffmpeg is missing: brew install ffmpeg", EXIT_ENV)
    version = capcut_version()
    if version and not any(version.startswith(k) for k in KNOWN_VERSIONS):
        print(f"  WARNING: CapCut {version}; the coordinates in P were measured on "
              f"{'/'.join(KNOWN_VERSIONS)}x. If the text stops reaching the clip, that's why: "
              "--calibrate.")
    sh("open", "-a", "CapCut")
    time.sleep(2)
    place_window(strict=True)

    tr = project()
    e = state(tr.parent)
    if e.get("error"):
        die(f"I couldn't read {tr.parent}/draft_info.json ({e['error']}). Open a real project in "
            "CapCut and run --prepare.", EXIT_ENV)
    voices = e.get("voices") or []
    print(f"CapCut {version or '(unknown version)'} · project: {tr.parent}\n"
          f"  text clip: {(e.get('text') or '')[:50]!r} · voices on the timeline: {sorted(set(voices))}\n"
          f"  generations on this project: {len(voices)}")
    if e.get("text") is None:
        die("this project has no text clip, so there is nothing to paste into. Follow --prepare: a "
            "new project, one text clip, the voice applied and generated once by hand.", EXIT_ENV)
    if not any(voice in v for v in voices):
        print(f"  WARNING: no audio clip uses {voice}: apply the voice again (see --prepare)")
    if len(voices) >= SATURATION_REFUSE and long_batch:
        die(f"this project already carries {len(voices)} generations, past the ~{SATURATION_REFUSE} "
            "point where CapCut stops writing WAVs without saying so. Start a NEW project "
            "(--prepare) before running a batch on it. The batch resumes from where it stopped.",
            EXIT_SATURATED)
    if len(voices) >= SATURATION_WARN:
        print(f"  WARNING: {len(voices)} generations on this project. It usually gives out around "
              f"{SATURATION_REFUSE}; if it starts failing, this script will create a new one.")
    return tr


def main():
    ap = argparse.ArgumentParser(description="CapCut's narrator voice, driven by clicks (macOS)")
    ap.add_argument("lines", nargs="?", help="JSON file with the list of sentences")
    ap.add_argument("out", nargs="?", help="output folder for l0.wav, l1.wav… and durations.json")
    ap.add_argument("--speed", type=float, default=DEFAULT_SPEED,
                    help=f"{DEFAULT_SPEED} is the trend's pace (default), applied with atempo after CapCut")
    ap.add_argument("--voice", default=DEFAULT_VOICE,
                    help=f"the voice's name in the catalog (default: {DEFAULT_VOICE}); it names the "
                         "voice in the messages and in the draft_info.json check, it does not select it")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--preflight", action="store_true",
                    help="only run the checks (CapCut, window, permissions, project state) and exit")
    ap.add_argument("--new-project-on-saturation", action=argparse.BooleanOptionalAction, default=True,
                    help="when the project stops generating, create a new one and retry once (default: yes)")
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
    if a.preflight:
        return preflight(a.voice, long_batch=False)
    if not a.lines or not a.out:
        ap.error("lines.json and the output folder are missing")

    lines = json.load(open(a.lines))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pending = sum(1 for i in range(len(lines)) if not (out / f"l{i}.wav").exists())
    awake = keep_awake()
    tr = preflight(a.voice, long_batch=pending > 0)

    durations = {}
    recovered = False   # the new-project retry is allowed exactly once per run
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
            kind, why = classify(tr.parent, line, a.voice)
            head = f"CapCut generated no audio for l{i} ({line[:50]!r}).\n  Diagnosis: {why}"
            kept = (f"\n  What got generated so far stays in {out} (running it again resumes from "
                    f"l{i}); durations.json is deliberately not written, which is how narrate.py "
                    "knows the folder is incomplete.")
            # The interface moving is not something retrying fixes: stop on the first line instead
            # of burning through twenty of them producing nothing.
            if kind in ("ui", "unreadable"):
                die(head + kept, EXIT_UI if kind == "ui" else EXIT_ENV)
            if not a.new_project_on_saturation:
                die(head + "\n  (--no-new-project-on-saturation, so no automatic retry)" + kept,
                    EXIT_SATURATED)
            if recovered:
                die(head + "\n  A new project was already tried in this run and it did not help: "
                           "this is not the saturation wall. Check by hand with a voice with NO "
                           "diamond badge, and if that one generates, the cap is on the premium "
                           "voices in your country's catalog." + kept, EXIT_SATURATED)
            recovered = True
            tr = new_project(a.voice, line)   # exits non-zero on its own if it cannot rebuild
            before = set(tr.glob("*.wav"))
            raw = wait_for_wav(tr, before, timeout=20) or None
            if not raw:
                set_text(line)
                raw = wait_for_wav(tr, before)
            if not raw:
                die(head + "\n  A brand-new project did not generate either, so this is not the "
                           "saturation wall. Try by hand with a voice with NO diamond badge: if that "
                           "one generates, the cap is on the premium voices. Otherwise use the local "
                           "path, `voice.py --engine qwen`." + kept, EXIT_SATURATED)
        if a.keep_raw:
            shutil.copy2(raw, out / f"l{i}.capcut.wav")
        loudnorm_2pass(raw, final, a.speed)
        durations[f"l{i}"] = duration(final)
        print(f"l{i} {durations[f'l{i}']}s  ·  {line[:60]}", flush=True)
    json.dump(durations, open(out / "durations.json", "w"), ensure_ascii=False, indent=1)
    print(f"\n{len(lines)} lines in {out} (+ durations.json)")
    if awake:
        awake.terminate()


if __name__ == "__main__":
    main()
