# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pyobjc-framework-Quartz",
#   "pyobjc-framework-ApplicationServices",
#   "pyobjc-framework-Cocoa",
# ]
# ///
"""CapCut's narrator voice (macOS), by driving the desktop app.

macOS ONLY. The voices in CapCut's catalog are ByteDance's (and, for the newer ones, ElevenLabs'
served through CapCut) and only exist inside the app: there is no public API, so this automates the
interface. It is fragile by definition: it depends on CapCut's version, and an update can break it.
The stable path is `voice.py --engine qwen` (local, Apache-2.0). Use this one only when the script
specifically calls for the app's viral voice.

What it does NOT do and must not do: it clones no real person's voice, it touches no unofficial
APIs and it uses nobody's session or cookies. It only presses buttons in an installed app. It never
signs in, never buys anything and never types a password: if CapCut puts up a sign-in or a paywall,
this script STOPS and says so (exit 6).

The voice it is set up for is **Valentino at 1.4x**, the default for Spanish narration in this
plugin (see resolve_voice.py). Any other catalog voice works the same way: pass its name with
--voice, because since 9.5 the voice is looked up **by name** in the accessibility tree.

Usage:
  uv run capcut_voice.py --prepare                    # once per batch: leaves CapCut ready
  uv run capcut_voice.py lines.json folder [--speed 1.4] [--voice "Valentino"]
  uv run capcut_voice.py --calibrate                  # resolve every UI anchor + a screenshot
  uv run capcut_voice.py --preflight                  # only the checks, generates nothing

lines.json: ["sentence 1", "sentence 2", ...]. It writes l0.wav, l1.wav... and durations.json into
the folder, i.e. the SAME contract as scripts/voice.py: narrate.py and the editing engine consume
them unchanged.

VERSIONS
--------
CapCut moved everything between 7.5 and 9.5, so this script carries one **profile per version
family** and refuses to guess:

  7.5.x   fixed click coordinates (the historical P dict). Kept so an old machine still works.
  9.5.x   accessibility-driven. CapCut 9.x publishes an AX tree with stable descriptions
          (`root_Texto`, `text_tts`, `automationtextArea`, `MTLSTextP:<the clip's text>`,
          `OnlineResourceInfoView:<the voice's name>`), so the tabs, the script box, the text clip
          and the voice tile are all found **by name**, not by pixel.

An unknown version is a hard stop with instructions (exit 3), never a silent half-run. Force one
with --assume-version 9.5 if you have checked the panel by hand with --calibrate.

IT FAILS LOUDLY, NEVER IN SILENCE
---------------------------------
  exit 2  bad arguments
  exit 3  the interface moved (or the version is unknown): run --calibrate and fix the profile
  exit 4  the project is saturated and the new-project retry did not fix it
  exit 5  the environment is missing something (cliclick, CapCut, the drafts folder, permissions)
  exit 6  CapCut demands an account or a Pro/credits plan for text to speech. NOTHING is bought,
          nothing is typed: the run stops and the caller falls back to the local voice.

The batch also runs under `caffeinate`, because a click-driven run dies the moment the machine goes
to sleep and takes the whole batch with it.
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
# In 9.5 the catalog calls it "Valentino💌" (yes, with the emoji), so the match is a **substring,
# case-insensitive** one — "Valentino" finds it. The same name is what the diagnostics compare
# against `draft_info.json`, which is how "the voice click landed outside" is told apart from "the
# project is saturated". CapCut's catalog changes by country and by app version.
DEFAULT_VOICE = os.environ.get("REEL_FORGE_CAPCUT_VOICE", "Valentino")
# The pace of the documentary-narration trend, applied OUTSIDE CapCut with atempo (pitch is kept).
DEFAULT_SPEED = 1.4
# Coordinates in logical points with CapCut's window at (0, 33) and a size of 1728x999
# (a 1728x1117 point screen). With another screen or version, recalibrate with --calibrate.
WINDOW = {"pos": (0, 33), "size": (1728, 999)}
# ---------------------------------------------------------------------------------------------
# 7.5.x: everything by pixel. Left here so a machine still on 7.5 keeps working; it is NOT used on
# 9.x, where the same elements are found by name in the accessibility tree.
# ---------------------------------------------------------------------------------------------
P75 = {
    "timeline": (700, 900),
    "text_clip": (450, 888),
    "text_tab": (1141, 90),
    "text_box": (1417, 197),
    "tts_tab": (1398, 90),
    "narration_chip": (1550, 138),
    "voice": (1380, 436),
    "generate": (1634, 739),
    "media_text_tab": (150, 88),
    "default_text_add": (250, 210),
}
# ---------------------------------------------------------------------------------------------
# 9.5.x: AX descriptions, plus the handful of things CapCut still does not publish.
# Measured 24 sep 2026 on CapCut 9.5.0 (es-MX), window 1728x997 at (0, 33).
# ---------------------------------------------------------------------------------------------
AX95 = {
    # AXDescription -> what it is. These are looked up live, so a moved panel changes nothing.
    "media_text_tab": "root_Texto",                     # left panel, the "Texto" tab
    "default_text_tile": "EffectItemView:Texto predeterminado",
    "text_tab": "text_text",                            # right panel, "Texto"
    "tts_tab": "text_tts",                              # right panel, "Texto a voz"
    "text_box": "automationtextArea",                   # the box the script is pasted into
    "timeline_root": "MainMultiTimelineLayout",         # anchors the Generate button's height
    "clip_prefix": "MTLSTextP:",                        # + the clip's own text
    "voice_prefix": "OnlineResourceInfoView:",          # + the voice's name
}
# The "+" that adds the default text clip appears on hover, at the tile's bottom-right corner, and
# it is not in the AX tree: this is its offset from the tile's top-left.
TILE_PLUS = (73, 72)
# The "Generate voice content" button is not in the AX tree either. It sits at the bottom right of
# the settings panel, so it is anchored to the window's right edge and to the timeline's top: that
# survives dragging the player/timeline divider, which is what used to need a manual calibration.
GENERATE_ANCHOR = {"dx_from_right": -94, "dy_from_timeline_top": -25}
# The voice grid's usable band, in window coordinates. The bottom stops short of the panel because
# 9.5 floats a "Join Pro to use this feature with credits" banner over the last row.
VOICE_BAND = (240, 505)
# Exit codes. Anything other than 0 means nothing usable was produced for the line it stopped on.
EXIT_ARGS = 2
EXIT_UI = 3           # the interface moved, or the CapCut version has no profile here
EXIT_SATURATED = 4    # the project stopped generating and a new project did not fix it
EXIT_ENV = 5          # cliclick / CapCut / the drafts folder / automation permissions
EXIT_LOGIN = 6        # CapCut wants an account or a paid plan. We stop; we never sign in or pay.
# The profile each CapCut version family gets. An unknown version is a hard stop, not a warning:
# on 9.5 the old coordinates pasted text into empty space and the batch produced nothing, twice,
# with no error — which is exactly the failure this table exists to prevent.
PROFILES = {"7.5": "coords", "9.5": "ax"}
VERSION_ALIASES = {"9.4": "9.5", "9.6": "9.5", "7.4": "7.5", "7.6": "7.5"}
# Generations on one project's timeline before it is worth warning, and before this script
# refuses to start a long batch on it. The observed cap sits somewhere around a hundred.
SATURATION_WARN = 60
SATURATION_REFUSE = 100
# Silence trimmed from both edges + a gentle high-pass (the same "clean" FX as voice.py). No reverb.
TRIM = ("areverse,silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.08,areverse,"
        "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05")
FX = f"{TRIM},highpass=f=60"

# Filled in by preflight(); "coords" (7.5.x) or "ax" (9.x).
MODE = "ax"
P = dict(P75)   # only consulted in "coords" mode


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


# ---------------------------------------------------------------------------------------------
# The accessibility layer. CapCut 9.x publishes a usable AX tree — the tabs, the script box, the
# text clip on the timeline and every voice tile carry a stable AXDescription — so the whole cycle
# is driven by name instead of by pixel. This is the single biggest reason a 9.5 update no longer
# silently misses: if an element is gone, it is gone by name and the script says which one.
# ---------------------------------------------------------------------------------------------
_AX = {}


def _ax_api():
    if _AX:
        return _AX
    try:
        from ApplicationServices import (AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
                                         AXValueGetValue, kAXErrorSuccess, kAXValueCGPointType,
                                         kAXValueCGSizeType)
        from AppKit import NSWorkspace
    except ImportError as e:      # pragma: no cover - only off a pyobjc environment
        die(f"the accessibility bindings are missing ({e}). Run this with `uv run`, which installs "
            "pyobjc-framework-ApplicationServices from the header of this file.", EXIT_ENV)
    _AX.update(create=AXUIElementCreateApplication, get=AXUIElementCopyAttributeValue,
               unwrap=AXValueGetValue, ok=kAXErrorSuccess, point=kAXValueCGPointType,
               size=kAXValueCGSizeType, ws=NSWorkspace)
    return _AX


def _ax_attr(el, name):
    a = _ax_api()
    err, val = a["get"](el, name, None)
    return val if err == a["ok"] else None


def _ax_geom(el, name, kind):
    a = _ax_api()
    v = _ax_attr(el, name)
    if v is None:
        return None
    ok, out = a["unwrap"](v, kind, None)
    if not ok:
        return None
    return (out.x, out.y) if kind == a["point"] else (out.width, out.height)


def ax_windows():
    """[(title, subrole, (x, y), (w, h))] for every CapCut window, main one included."""
    a = _ax_api()
    pid = None
    for app in a["ws"].sharedWorkspace().runningApplications():
        if app.localizedName() == "CapCut":
            pid = app.processIdentifier()
    if pid is None:
        return []
    app_el = a["create"](pid)
    out = []
    for w in (_ax_attr(app_el, "AXWindows") or []):
        out.append((_ax_attr(w, "AXTitle") or "", _ax_attr(w, "AXSubrole") or "",
                    _ax_geom(w, "AXPosition", a["point"]), _ax_geom(w, "AXSize", a["size"])))
    return out


def ax_nodes():
    """Every AX element under CapCut's windows, as {desc, role, pos, size, center}."""
    a = _ax_api()
    pid = None
    for app in a["ws"].sharedWorkspace().runningApplications():
        if app.localizedName() == "CapCut":
            pid = app.processIdentifier()
    if pid is None:
        return []
    app_el = a["create"](pid)
    out = []

    def walk(el, depth=0):
        if depth > 40:
            return
        desc = _ax_attr(el, "AXDescription") or ""
        pos = _ax_geom(el, "AXPosition", a["point"])
        size = _ax_geom(el, "AXSize", a["size"])
        if desc and pos and size:
            out.append({"desc": desc, "role": _ax_attr(el, "AXRole") or "",
                        "pos": (round(pos[0]), round(pos[1])),
                        "size": (round(size[0]), round(size[1])),
                        "center": (round(pos[0] + size[0] / 2), round(pos[1] + size[1] / 2))})
        for k in (_ax_attr(el, "AXChildren") or []):
            walk(k, depth + 1)

    for w in (_ax_attr(app_el, "AXWindows") or []):
        walk(w)
    return out


def ax_find(desc, nodes=None, contains=False):
    """The first element whose AXDescription equals (or contains) `desc`, or None."""
    for n in (nodes if nodes is not None else ax_nodes()):
        if (desc.lower() in n["desc"].lower()) if contains else (n["desc"] == desc):
            return n
    return None


def ax_point(key, nodes=None):
    """The centre of the element the 9.5 profile calls `key`, or None if it is not on screen."""
    n = ax_find(AX95[key], nodes)
    return n["center"] if n else None


def ax_click(key, wait=1.5, nodes=None, what=None):
    pt = ax_point(key, nodes)
    if pt is None:
        die(f"I can't find {what or key} in CapCut's accessibility tree (AXDescription "
            f"{AX95[key]!r}). Either the panel is not open or CapCut renamed it in an update. Run "
            "--calibrate: it lists every anchor and says which ones resolved.", EXIT_UI)
    cliclick(f"c:{pt[0]},{pt[1]}")
    time.sleep(wait)
    return pt


def generate_point(nodes=None):
    """Where the 'Generate voice content' button is. CapCut does not publish it, so it is anchored
    to the window's right edge and to the top of the timeline: dragging the player/timeline divider
    moves it and this follows, which is what the 7.5 procedure needed a manual calibration for."""
    nodes = nodes if nodes is not None else ax_nodes()
    tl = ax_find(AX95["timeline_root"], nodes)
    geom = window_geometry()
    if not tl or not geom:
        return None
    x = geom[0] + geom[2] + GENERATE_ANCHOR["dx_from_right"]
    y = tl["pos"][1] + GENERATE_ANCHOR["dy_from_timeline_top"]
    return (round(x), round(y))


def modal_windows():
    """CapCut's modal dialogs, ignoring the two tiny helper windows it always keeps around.

    This is how the sign-in wall is caught: pressing Generate on 9.5 without an account opens a
    ~355x600 dialog, and the script has to stop there instead of clicking blindly through it.
    """
    out = []
    for title, subrole, pos, size in ax_windows():
        if not size or title == "CapCut":
            continue
        if size[0] >= 280 and size[1] >= 320:
            out.append((title, subrole, pos, size))
    return out


# CapCut's server notices are NOT windows: they are a toast that lives ~2 s inside the main
# window, some 4-5 s after pressing Generate. modal_windows() never sees it, which is why
# classify() used to blame the voice grid for a refusal that came from the server.
SERVER_TOASTS = (
    ("busy", ("demasiadas personas", "too many people", "try again later",
              "intenta de nuevo", "intentalo de nuevo", "inténtalo de nuevo",
              # seen on 26 sep 2026 a second BEFORE the "too many people" toast, on the same
              # refusal of Valentino; the text was plain Spanish that the same voice read on 22 sep
              "no es compatible con la conversion", "no es compatible con la conversión",
              "not compatible with text to speech")),
    ("network", ("sin conexion", "sin conexión", "network error", "error de red",
                 "check your network", "revisa tu conexion", "revisa tu conexión")),
    ("quota", ("creditos", "créditos", "credits", "limite", "límite", "limit reached")),
)


def ax_texts():
    """Every piece of text CapCut shows (the AXValue of its AXStaticText), which ax_nodes() drops.

    ax_nodes() only keeps elements that carry an AXDescription; a toast has none, it keeps its
    message in AXValue. Without this the server's notice is invisible to the script.
    """
    a = _ax_api()
    pid = None
    for app in a["ws"].sharedWorkspace().runningApplications():
        if app.localizedName() == "CapCut":
            pid = app.processIdentifier()
    if pid is None:
        return []
    out = []

    def walk(el, depth=0):
        if depth > 40:
            return
        v = _ax_attr(el, "AXValue")
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
        for k in (_ax_attr(el, "AXChildren") or []):
            walk(k, depth + 1)

    for w in (_ax_attr(_ax_api()["create"](pid), "AXWindows") or []):
        walk(w)
    return out


PICKED = {}   # voice -> whether its tile was found by name and clicked in this run


def read_toast(seconds=9.0):
    """Watches for the server's toast for `seconds`. Returns (kind, text), or None.

    It samples fast on purpose: the notice lasts ~2 s. It returns as soon as it finds one.
    """
    t0 = time.time()
    while time.time() - t0 < seconds:
        for t in ax_texts():
            low = t.lower()
            for kind, needles in SERVER_TOASTS:
                if any(n in low for n in needles):
                    return kind, t
        time.sleep(0.15)
    return None


def window_geometry():
    """(x, y, w, h) of CapCut's MAIN window, or None if System Events cannot see it.

    Not `window 1`: CapCut 9.x keeps a couple of tiny helper windows around and one of them is
    often first, so pinning "window 1" used to move a 183x88 dialog and leave every coordinate
    pointing at nothing.
    """
    r = osa('tell application "System Events" to tell process "CapCut" to '
            'tell (first window whose subrole is "AXStandardWindow") to '
            'get position & size')
    try:
        nums = [int(float(n)) for n in r.stdout.strip().split(", ")]
        return tuple(nums[:4]) if len(nums) >= 4 else None
    except ValueError:
        return None


def place_window(strict: bool = False):
    """Puts CapCut's window at a known position and size.

    In "ax" mode the coordinates come from the accessibility tree, so the exact size matters much
    less — but the window still has to be on screen and not full screen, and `strict` is what
    catches a missing Accessibility permission before the first click goes somewhere random.
    """
    x, y = WINDOW["pos"]
    w, h = WINDOW["size"]
    for prop, val in (("position", f"{{{x}, {y}}}"), ("size", f"{{{w}, {h}}}")):
        osa('tell application "System Events" to tell process "CapCut" to tell '
            f'(first window whose subrole is "AXStandardWindow") to set {prop} to {val}')
    time.sleep(1)
    if not strict:
        return None
    got = window_geometry()
    if got is None:
        die("System Events cannot see CapCut's window. Open CapCut with a project on screen, and "
            "grant Accessibility + Automation permissions to the terminal in System Settings → "
            "Privacy & Security. This does not work over a remote session or with the display off.",
            EXIT_ENV)
    # The window manager clamps the height to the usable screen (997 instead of 999 on a 1117-point
    # screen), so the tolerance on the size is deliberately loose.
    if abs(got[0] - x) > 4 or abs(got[1] - y) > 4 or abs(got[2] - w) > 8 or abs(got[3] - h) > 12:
        if MODE == "coords":
            die(f"CapCut's window would not go to {x},{y} {w}x{h}: it is at {got[0]},{got[1]} "
                f"{got[2]}x{got[3]}. Every coordinate in P assumes the documented geometry, so the "
                "clicks would land in the wrong place. Leave full screen, or re-measure with "
                "--calibrate and adjust WINDOW and P.", EXIT_UI)
        print(f"  note: CapCut's window is {got[2]}x{got[3]} at {got[0]},{got[1]}, not the "
              f"documented {w}x{h} at {x},{y}. On 9.x that is fine — the anchors come from the "
              "accessibility tree — as long as the window is not full screen.")
    return got


def capcut_version():
    """CapCut's version string, or None."""
    for app in (Path("/Applications/CapCut.app"), Path(os.path.expanduser("~/Applications/CapCut.app"))):
        plist = app / "Contents" / "Info.plist"
        if plist.exists():
            r = sh("defaults", "read", str(plist.with_suffix("")), "CFBundleShortVersionString")
            v = r.stdout.strip()
            if v:
                return v
    return None


def profile_for(version, assumed=None):
    """('9.5', 'ax') for a known version. An unknown one stops the run with instructions."""
    if assumed:
        family = VERSION_ALIASES.get(assumed, assumed)
        if family not in PROFILES:
            die(f"--assume-version {assumed}: I only carry profiles for "
                f"{', '.join(sorted(PROFILES))}.", EXIT_ARGS)
        return family, PROFILES[family]
    if not version:
        die("I can't read CapCut's version (no CapCut.app in /Applications or ~/Applications). "
            "Install CapCut, or pass --assume-version 9.5 if it lives somewhere else.", EXIT_ENV)
    family = ".".join(version.split(".")[:2])
    family = VERSION_ALIASES.get(family, family)
    if family in PROFILES:
        return family, PROFILES[family]
    die(f"CapCut {version} is a version this script has never been calibrated against. It carries "
        f"profiles for {', '.join(sorted(PROFILES))} only, and running the wrong one is how a batch "
        "ends up pasting text into empty space and generating nothing, silently.\n"
        "  What to do: run `--calibrate` with CapCut open on a project with a text clip. It prints "
        "every UI anchor and says which ones still resolve. If they all resolve, re-run the batch "
        f"with `--assume-version 9.5`; if they don't, the descriptions in AX95 are what changed.",
        EXIT_UI)


def drafts() -> list:
    """Every CapCut draft folder, in both layouts.

    CapCut <=7.5 nested them by date (`com.lveditor.draft/09/22`); 9.x puts each project in a
    folder of its own name right under the drafts root (`com.lveditor.draft/0924 (2)`). Globbing
    only `*/*` meant that on 9.5 the "current project" was silently an old September draft, and the
    script waited for a WAV in a folder CapCut was no longer writing to.
    """
    found = {}
    for pattern in ("*", "*/*"):
        for p in CAPCUT.glob(pattern):
            if p.is_dir() and (p / "draft_info.json").exists():
                found[str(p)] = p
    return list(found.values())


def project() -> Path:
    """The open project's textReading folder (the most recently modified draft)."""
    found = drafts()
    if not found:
        die(f"I can't find any CapCut projects in {CAPCUT}. Open CapCut, create a project and run "
            "--prepare. If your drafts live elsewhere, point $CAPCUT_DRAFTS at them.", EXIT_ENV)
    d = max(found, key=lambda p: (p / "draft_info.json").stat().st_mtime)
    tr = d / "textReading"
    tr.mkdir(exist_ok=True)
    return tr


def keep_awake():
    """Holds the machine awake for as long as this process lives."""
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
    time.sleep(0.15)
    for _ in range(n):
        Quartz.CGEventPost(Quartz.kCGHIDEventTap,
                           Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, clicks))
        time.sleep(0.05)


def pick_voice(voice: str, max_scrolls: int = 220) -> bool:
    """Scrolls the voice grid until `voice` is visible and clicks it. 9.x only.

    The catalog is one long virtualised list (categories first, then a section per language) and
    the tile has to be **clicked, every line**, because the Generate button goes back to disabled
    once the clip already carries a voice. The AX tree publishes every tile as
    `OnlineResourceInfoView:<name>`, so this is a search by name, not a memorised grid cell —
    which is what broke when 9.5 reshuffled the catalog and took Valentino out of "Narración".
    """
    top, bot = VOICE_BAND
    probe = None
    for _ in range(max_scrolls):
        nodes = ax_nodes()
        hit = ax_find(AX95["voice_prefix"] + voice, nodes, contains=True)
        if probe is None:
            tile = next((n for n in nodes if n["desc"].startswith(AX95["voice_prefix"])), None)
            probe = tile["center"] if tile else (1450, 400)
        if hit:
            x, y = hit["center"]
            if y > bot:
                # 9.5 floats a "Join Pro…" banner over the bottom of the panel; the top strip of
                # the last row is still clickable, and the last row is exactly where Valentino is.
                y = hit["pos"][1] + 8
            if top <= y <= bot:
                cliclick(f"c:{x},{y}")
                time.sleep(2.0)
                return True
            scroll(probe[0], probe[1], -1 if y > bot else 1, 1)
        else:
            scroll(probe[0], probe[1], -3, 3)
        time.sleep(0.3)
    return False


LAST_TOAST = None   # (clase, texto) del ultimo aviso del servidor, o None


def set_text(line: str, voice: str = DEFAULT_VOICE):
    """Pastes the line into the text clip, picks the voice again and presses Generate.

    Since CapCut 7.5 the Text to speech panel no longer carries the "Update the voice from the
    script" checkbox (9.5 did not bring it back), so changing the text regenerates nothing: you
    have to press Generate every time, and click the voice again first because the button stays
    disabled otherwise.
    """
    subprocess.run(["pbcopy"], input=line, text=True, check=True)

    if MODE == "coords":       # 7.5.x, everything by pixel
        def click(k, wait=1.5):
            cliclick(f"c:{P[k][0]},{P[k][1]}")
            time.sleep(wait)
        scroll(*P["timeline"], 5, 30)
        time.sleep(0.6)
        click("text_clip")
        click("text_tab")
        click("text_box", 0.8)
        cliclick("kd:cmd", "t:a", "ku:cmd"); time.sleep(0.6)
        cliclick("kd:cmd", "t:v", "ku:cmd"); time.sleep(1.0)
        click("tts_tab", 2.0)
        click("narration_chip", 2.0)
        click("voice", 2.5)
        click("generate", 0.5)
        return

    # 9.x: the text clip is published as MTLSTextP:<its own text>, so it gets clicked by name and
    # there is no scrolling-the-timeline-far-enough ritual any more.
    nodes = ax_nodes()
    clip = next((n for n in nodes if n["desc"].startswith(AX95["clip_prefix"])), None)
    if clip is None:
        die("there is no text clip on the timeline (nothing called MTLSTextP:… in the "
            "accessibility tree). Follow --prepare: a new project, Texto → Texto predeterminado → "
            "the + button, and the voice applied once by hand.", EXIT_UI)
    cliclick(f"c:{clip['center'][0]},{clip['center'][1]}")
    time.sleep(1.2)
    ax_click("text_tab", 1.5, what="the right panel's 'Texto' tab")
    ax_click("text_box", 0.8, what="the script box")
    cliclick("kd:cmd", "t:a", "ku:cmd"); time.sleep(0.5)
    cliclick("kd:cmd", "t:v", "ku:cmd"); time.sleep(1.2)
    ax_click("tts_tab", 2.5, what="the right panel's 'Texto a voz' tab")
    PICKED[voice] = pick_voice(voice)
    if not PICKED[voice]:
        die(f"I scrolled the whole voice catalog and {voice!r} is not in it. CapCut's catalog "
            "changes by country and by version, and in 9.5 the name carries an emoji "
            "(\"Valentino💌\"), which the substring match handles. Open the 'Texto a voz' panel and "
            "check the name by hand, then pass it with --voice.", EXIT_UI)
    before = len(modal_windows())
    pt = generate_point()
    if pt is None:
        die("I can't anchor the 'Generar contenido de voz' button (the timeline root is not in the "
            "accessibility tree). Run --calibrate.", EXIT_UI)
    cliclick(f"c:{pt[0]},{pt[1]}")
    globals()["LAST_TOAST"] = read_toast(9.0)   # el aviso sale a los ~4-5 s y dura ~2 s
    if len(modal_windows()) > before:
        die("CapCut put up a dialog instead of generating: on 9.5 text to speech is behind an "
            "account (the sign-in sheet with TikTok / Apple / Google) and the voices carry a "
            "'Join Pro to use this feature with credits' banner.\n"
            "  This script never signs in, never types a password and never buys anything, so it "
            "stops here.\n"
            "  What to do: sign in to CapCut by hand once, check that pressing 'Generar contenido "
            "de voz' produces an audio track, and run this again — it resumes where it stopped. "
            "If it asks for a paid plan, this path is closed: narrate with `voice.py --engine "
            "qwen` and say so in the variant's README (resolve_voice.py prints the sentence).",
            EXIT_LOGIN)


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
    """Reads draft_info.json: what text the clip carries and which voices the timeline uses."""
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
    """Why no audio came out, as (kind, message)."""
    if LAST_TOAST:
        kind, text = LAST_TOAST
        common = (f"CapCut mostro este aviso al generar: {text!r}. El rechazo viene de su "
                  "servidor, no de la automatizacion: el texto llego al clip y el boton se pulso "
                  "bien. Ni un proyecto nuevo ni recalibrar cambian nada.")
        if kind == "busy":
            return "server", (common + " Es saturacion de esa voz: vuelve a intentarlo en un rato "
                              "o en otra franja horaria. Mientras, narra con `voice.py --engine "
                              "qwen` y dilo en el README de la variante.")
        if kind == "network":
            return "server", (common + " Es la red: revisa la conexion y vuelve a correrlo (el "
                              "batch reanuda donde se quedo).")
        return "login", (common + " Habla de creditos o de limite: este camino pide plan de pago "
                         "y el script no compra nada. Usa `voice.py --engine qwen`.")
    e = state(draft)
    if e.get("error"):
        return "unreadable", (f"I couldn't read draft_info.json ({e['error']}). Check that CapCut is "
                              f"open on a real project and that {CAPCUT} is the right drafts folder "
                              "($CAPCUT_DRAFTS).")
    arrived = (e.get("text") or "").strip() == line.strip()
    if not arrived:
        return "ui", ("the text did NOT reach the clip (the clip says "
                      f"{(e.get('text') or '')[:40]!r}): the clicks are landing wrong. CapCut almost "
                      "certainly moved its buttons in an update. Run --calibrate: it resolves every "
                      "anchor by name and says which one is gone.")
    if not any(voice.lower() in v.lower() for v in e.get("voices") or []) and PICKED.get(voice):
        # The tile WAS found by name and clicked (pick_voice returned True), the text is on the clip,
        # and still no track with that voice: that is the server refusing that one voice with a
        # toast this run did not manage to read (it lasts ~2 s). Blaming the grid here sent the
        # 26 sep 2026 run to --calibrate for a refusal that a later retry simply got past.
        return "server", (f"the text arrived and the {voice} tile was clicked by name, but no track "
                          "uses it: CapCut refused that voice (its 'too many people' toast lasts ~2 s "
                          "and was missed). Not the interface; retrying later is what works.")
    if not any(voice.lower() in v.lower() for v in e.get("voices") or []):
        return "ui", (f"the text did arrive, but no audio clip uses {voice}: the click in the voice "
                      "grid landed outside, or the catalog renamed the voice. Run --calibrate and "
                      "check the name in the 'Texto a voz' panel (9.5 calls it \"Valentino💌\").")
    return "saturated", (f"the text arrived and the voice is {voice}, but CapCut wrote no audio. "
                         "That is the saturated project: after ~100 generations it stops producing "
                         "WAVs with no error. The cure is a NEW project. If a new project doesn't "
                         "generate either, the wall is the account/credits one instead — check by "
                         "hand that 'Generar contenido de voz' does not open the sign-in sheet.")


def diagnose(draft: Path, line: str, voice: str = DEFAULT_VOICE) -> str:
    return classify(draft, line, voice)[1]


def menu_new_project() -> bool:
    """File → New project, by NAME. Falls back to Cmd+N. Returns whether the menu click worked.

    The 7.5 version clicked "menu item 1 of menu 1 of menu bar item 1", which on 9.5 is the app
    menu's "About" — it opened an about box and the batch carried on against the same project.
    """
    r = osa('tell application "System Events" to tell process "CapCut"\n'
            ' repeat with mb in menu bar items of menu bar 1\n'
            '  try\n'
            '   repeat with mi in menu items of menu 1 of mb\n'
            '    set n to name of mi\n'
            '    if n contains "Nuevo proyecto" or n contains "New project" or n contains "New Project" then\n'
            '     click mi\n'
            '     return "ok"\n'
            '    end if\n'
            '   end repeat\n'
            '  end try\n'
            ' end repeat\n'
            ' return "no"\n'
            'end tell')
    return "ok" in (r.stdout or "")


def new_project(voice: str, sample: str) -> Path:
    """Creates a fresh CapCut project and rebuilds the text clip in it. Returns its textReading."""
    before = {str(p) for p in drafts()}
    print("· the project is saturated: creating a new one and rebuilding the text clip", flush=True)
    if not menu_new_project():
        cliclick("kd:cmd", "t:n", "ku:cmd")
    time.sleep(6)
    place_window()

    subprocess.run(["pbcopy"], input=sample, text=True, check=True)
    if MODE == "coords":
        def click(k, wait=1.5):
            cliclick(f"c:{P[k][0]},{P[k][1]}")
            time.sleep(wait)
        click("media_text_tab", 2.0)
        click("default_text_add", 2.5)
        click("text_tab")
        click("text_box", 0.8)
        cliclick("kd:cmd", "t:a", "ku:cmd"); time.sleep(0.5)
        cliclick("kd:cmd", "t:v", "ku:cmd"); time.sleep(1.0)
        click("tts_tab", 2.0)
        click("narration_chip", 2.0)
        click("voice", 2.5)
        click("generate", 0.5)
    else:
        ax_click("media_text_tab", 2.5, what="the left panel's 'Texto' tab")
        tile = ax_find(AX95["default_text_tile"])
        if tile is None:
            die("the 'Texto predeterminado' tile is not there, so I can't build a text clip. Do it "
                "by hand (--prepare) and run this again: the batch resumes.", EXIT_UI)
        # The "+" only exists while the pointer is over the tile, and it is not in the AX tree.
        cliclick(f"m:{tile['center'][0]},{tile['center'][1]}")
        time.sleep(0.8)
        cliclick(f"c:{tile['pos'][0] + TILE_PLUS[0]},{tile['pos'][1] + TILE_PLUS[1]}")
        time.sleep(3.0)
        set_text(sample, voice)
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
            f"(it says {(e.get('text') or '')[:40]!r}). Build the clip by hand following --prepare "
            "and run this again: the batch resumes where it stopped.", EXIT_UI)
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
    version = capcut_version()
    family, _ = profile_for(version)
    print(f"CapCut {version or '(unknown)'} → profile {family}\n"
          "Manual steps (once per batch, ~1 minute):\n"
          "  1. CapCut → Archivo → Nuevo proyecto. ALWAYS a new one: a project with hundreds of\n"
          "     regenerations stops producing audio (it fails silently, with no message).\n"
          "  2. Texto → 'Texto predeterminado' → hover it and press its + button.\n"
          "  3. Right panel → 'Texto' tab → paste the first line there (Cmd+V; do NOT type with\n"
          "     AppleScript: it eats the spaces and the accents).\n"
          f"  4. 'Texto a voz' tab → find {DEFAULT_VOICE} → 'Generar contenido de voz'. An audio\n"
          "     track with the voice's name has to appear.\n"
          "  5. On 9.5 that step needs you to be SIGNED IN to CapCut. If a sign-in sheet comes up,\n"
          "     this path is unavailable until you sign in by hand — the script will not do it.\n"
          "Then: uv run capcut_voice.py lines.json folder/")
    sh("open", "-a", "CapCut")
    place_window()


def split_by_silence(src: Path, out: Path, n: int, speed: float, threshold="-38dB", min_silence=0.45):
    """Plan B: one audio file with the whole script, cut by silences into l0.wav, l1.wav..."""
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


def calibrate(voice=DEFAULT_VOICE, assumed=None):
    """Resolves every anchor and says which ones are gone. This is the whole diagnosis.

    On 9.x it does not print a list of pixels to edit by hand: it prints, for each named element,
    whether CapCut still publishes it and where it currently is. An anchor that says "MISSING" is
    the thing that broke.
    """
    global MODE, P
    version = capcut_version()
    family, MODE = profile_for(version, assumed)
    sh("open", "-a", "CapCut")
    time.sleep(2)
    place_window()
    out = Path(tempfile.gettempdir()) / "capcut-calibrate.png"
    sh("screencapture", "-x", str(out))
    print(f"CapCut {version or '(unknown)'} → profile {family} ({MODE})")
    if MODE == "coords":
        marks = ",".join(f"{k}=({v[0]},{v[1]})" for k, v in P.items())
        print(f"Screenshot at {out}. Current coordinates (logical points): {marks}\n"
              "Open it and check that each point lands where it says. If not, adjust P75.")
        return
    nodes = ax_nodes()
    print(f"Screenshot at {out}. {len(nodes)} accessibility elements under CapCut's windows.")
    print("Anchors (they are looked up by name at run time, so 'ok' means it still works):")
    for key, desc in AX95.items():
        if key.endswith("_prefix"):
            hits = [n for n in nodes if n["desc"].startswith(desc)]
            print(f"  {key:18s} {desc!r:42s} {len(hits)} element(s)"
                  + (f", e.g. {hits[0]['desc'][:40]!r} at {hits[0]['center']}" if hits else "  ← MISSING"))
            continue
        n = ax_find(desc, nodes)
        # These three only exist while the right tab is open, so "MISSING" here is only a problem
        # if it is still missing with a text clip selected and that tab in front.
        hint = "  (open the 'Texto' tab with a clip selected)" if key == "text_box" else ""
        print(f"  {key:18s} {desc!r:42s} "
              + (f"ok at {n['center']}" if n else f"← MISSING{hint}"))
    g = generate_point(nodes)
    print(f"  {'generate':18s} {'(anchored, not published by CapCut)':42s} "
          + (f"ok at {g}" if g else "← can't anchor it: the timeline root is missing"))
    hit = ax_find(AX95["voice_prefix"] + voice, nodes, contains=True)
    print(f"  {'voice':18s} {voice!r:42s} "
          + (f"visible at {hit['center']} ({hit['desc']})" if hit else
             "not on screen right now (it is found by scrolling during a run)"))
    mods = modal_windows()
    if mods:
        print(f"  WARNING: {len(mods)} modal dialog(s) open in CapCut: {mods}. Close them, they "
              "sit on top of the panel.")


def preflight(voice: str = DEFAULT_VOICE, long_batch: bool = True, assumed=None) -> Path:
    """Everything that has to be true before the first click. Returns the project's textReading."""
    global MODE, P
    if sys.platform != "darwin":
        die("this path only works on macOS: it automates the CapCut desktop app. Use "
            "`voice.py --engine qwen` (local, cross-platform on Apple Silicon) or `--engine piper` "
            "anywhere.", EXIT_ENV)
    if not shutil.which("cliclick"):
        die("cliclick is missing: brew install cliclick", EXIT_ENV)
    if not shutil.which("ffmpeg"):
        die("ffmpeg is missing: brew install ffmpeg", EXIT_ENV)
    version = capcut_version()
    family, MODE = profile_for(version, assumed)
    sh("open", "-a", "CapCut")
    time.sleep(2)
    place_window(strict=True)

    tr = project()
    e = state(tr.parent)
    if e.get("error"):
        die(f"I couldn't read {tr.parent}/draft_info.json ({e['error']}). Open a real project in "
            "CapCut and run --prepare.", EXIT_ENV)
    voices = e.get("voices") or []
    print(f"CapCut {version or '(unknown version)'} → profile {family} ({MODE}) · "
          f"project: {tr.parent}\n"
          f"  text clip: {(e.get('text') or '')[:50]!r} · voices on the timeline: {sorted(set(voices))}\n"
          f"  generations on this project: {len(voices)}")
    if e.get("text") is None:
        die("this project has no text clip, so there is nothing to paste into. Follow --prepare: a "
            "new project, one text clip, the voice applied and generated once by hand.", EXIT_ENV)
    if MODE == "ax":
        missing = [k for k, d in AX95.items()
                   if not k.endswith("_prefix") and k not in ("default_text_tile",)
                   and ax_find(d) is None]
        # The right-panel tabs only exist while a text clip is selected, so a missing tts_tab here
        # is not fatal: the cycle selects the clip first. A missing left panel is.
        hard = [k for k in missing if k in ("media_text_tab", "timeline_root")]
        if hard:
            die(f"CapCut {version} does not publish {', '.join(hard)} in its accessibility tree any "
                "more, so the 9.5 profile cannot drive it. Run --calibrate and update AX95.",
                EXIT_UI)
        if missing:
            print(f"  note: not on screen right now (normal until a clip is selected): "
                  f"{', '.join(missing)}")
        mods = modal_windows()
        if mods:
            die("CapCut has a modal dialog open (usually the sign-in sheet). Close it, or sign in "
                "by hand if you want the app's voices; this script never signs in. Then run this "
                "again.", EXIT_LOGIN)
    if not any(voice.lower() in v.lower() for v in voices):
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


def machine_lock(timeout_s=int(os.environ.get("REEL_FORGE_CAPCUT_WAIT", "1800"))):
    """One CapCut driver per machine. Two builders drove the same CapCut window at once in a real
    run: their clicks interleaved, neither got audio, and the diagnosis blamed the voice grid. The
    lock is taken for the whole batch; a second caller WAITS for it (up to `timeout_s`) instead of
    clicking into somebody else's session."""
    import fcntl
    root = Path(os.environ.get("REEL_FORGE_CACHE") or Path.home() / ".cache/reel-forge")
    root.mkdir(parents=True, exist_ok=True)
    fh = open(root / "capcut.lock", "a+")
    t0 = time.time()
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fh.seek(0); fh.truncate(); fh.write(f"pid {os.getpid()}"); fh.flush()
            return fh
        except BlockingIOError:
            if time.time() - t0 > timeout_s:
                die(f"CapCut has been busy with another batch for {timeout_s // 60} min "
                    f"({root / 'capcut.lock'}). Two drivers at once corrupt each other's clicks; "
                    "run this again when the other one is done.", EXIT_ENV)
            if int(time.time() - t0) % 60 < 5:
                print("· CapCut is being driven by another batch: waiting for it", flush=True)
            time.sleep(5)


def wait_out_busy(tr: Path, line: str, a, i: int):
    """The server's "too many people" is a refusal of ONE voice for a while, not a verdict.

    Seen on 24 sep 2026 (nine refusals in 25 min) and again early on 26 sep; fifteen minutes later that
    day, with nothing changed but CapCut relaunched, Valentino generated on the first try. So a busy
    refusal waits and retries on a doubling schedule (1, 2, 4, 8… min) for up to --busy-wait minutes
    before the batch gives up and the run falls back to the local voice. Returns the WAV or None.
    """
    budget = a.busy_wait * 60
    if budget <= 0:
        return None
    kind, _ = classify(tr.parent, line, a.voice)
    if kind != "server" or (LAST_TOAST and LAST_TOAST[0] != "busy"):
        return None
    t0, pause = time.time(), 60
    while time.time() - t0 + pause <= budget:
        print(f"l{i}: CapCut refused {a.voice} (busy); retrying in {pause // 60} min "
              f"({int((budget - (time.time() - t0)) // 60)} min left of --busy-wait)", flush=True)
        time.sleep(pause)
        before = set(tr.glob("*.wav"))
        set_text(line, a.voice)
        raw = wait_for_wav(tr, before)
        if raw:
            return raw
        pause = min(pause * 2, 16 * 60)
    return None


def main():
    ap = argparse.ArgumentParser(description="CapCut's narrator voice, driven by clicks (macOS)")
    ap.add_argument("lines", nargs="?", help="JSON file with the list of sentences")
    ap.add_argument("out", nargs="?", help="output folder for l0.wav, l1.wav… and durations.json")
    ap.add_argument("--speed", type=float, default=DEFAULT_SPEED,
                    help=f"{DEFAULT_SPEED} is the trend's pace (default), applied with atempo after CapCut")
    ap.add_argument("--voice", default=DEFAULT_VOICE,
                    help=f"the voice's name in the catalog (default: {DEFAULT_VOICE}). On 9.x it is "
                         "matched as a case-insensitive substring, so 'Valentino' finds 'Valentino💌'")
    ap.add_argument("--assume-version", metavar="X.Y",
                    help="use this profile instead of the installed CapCut's version (7.5 or 9.5)")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--preflight", action="store_true",
                    help="only run the checks (CapCut, version, window, permissions, project) and exit")
    ap.add_argument("--new-project-on-saturation", action=argparse.BooleanOptionalAction, default=True,
                    help="when the project stops generating, create a new one and retry once (default: yes)")
    ap.add_argument("--busy-wait", type=float, metavar="MIN",
                    default=float(os.environ.get("REEL_FORGE_CAPCUT_BUSY_WAIT", "20")),
                    help="when the server says the voice is busy, keep retrying for up to MIN minutes "
                         "(default 20, $REEL_FORGE_CAPCUT_BUSY_WAIT; 0 = give up at once)")
    ap.add_argument("--keep-raw", action="store_true", help="also keeps the wav exactly as CapCut produced it")
    ap.add_argument("--split", metavar="AUDIO.WAV",
                    help="plan B: cuts an audio file holding the whole script by silences (uses 'out' as the folder)")
    ap.add_argument("--threshold", default="-38dB")
    ap.add_argument("--min-silence", type=float, default=0.45)
    a = ap.parse_args()
    _lock = machine_lock()   # noqa: F841 — held until the process exits; see machine_lock()
    if a.prepare:
        return prepare()
    if a.calibrate:
        return calibrate(a.voice, a.assume_version)
    if a.split:
        out = a.out or a.lines
        lines_file = a.lines if a.out else None
        if not out:
            ap.error("--split needs the output folder: --split AUDIO.WAV OUT_FOLDER")
        n = len(json.load(open(lines_file))) if lines_file else 0
        return split_by_silence(Path(a.split), Path(out), n, a.speed, a.threshold, a.min_silence)
    if a.preflight:
        return preflight(a.voice, long_batch=False, assumed=a.assume_version)
    if not a.lines or not a.out:
        ap.error("lines.json and the output folder are missing")

    lines = json.load(open(a.lines))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pending = sum(1 for i in range(len(lines)) if not (out / f"l{i}.wav").exists())
    awake = keep_awake()
    tr = preflight(a.voice, long_batch=pending > 0, assumed=a.assume_version)

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
            set_text(line, a.voice)
            raw = wait_for_wav(tr, before)
            if raw:
                break
            if LAST_TOAST:     # el servidor ya dijo que no: reintentar al instante no sirve
                break
            print(f"l{i}: no audio on the first attempt, retrying…", flush=True)
            time.sleep(3)
        if not raw:
            raw = wait_out_busy(tr, line, a, i)
        if not raw:
            kind, why = classify(tr.parent, line, a.voice)
            head = f"CapCut generated no audio for l{i} ({line[:50]!r}).\n  Diagnosis: {why}"
            kept = (f"\n  What got generated so far stays in {out} (running it again resumes from "
                    f"l{i}); durations.json is deliberately not written, which is how narrate.py "
                    "knows the folder is incomplete.")
            if kind in ("ui", "unreadable"):
                die(head + kept, EXIT_UI if kind == "ui" else EXIT_ENV)
            if kind == "server":     # un proyecto nuevo no arregla un no del servidor
                die(head + kept, EXIT_SATURATED)
            if kind == "login":
                die(head + kept, EXIT_LOGIN)
            if not a.new_project_on_saturation:
                die(head + "\n  (--no-new-project-on-saturation, so no automatic retry)" + kept,
                    EXIT_SATURATED)
            if recovered:
                die(head + "\n  A new project was already tried in this run and it did not help: "
                           "this is not the saturation wall. Check by hand that 'Generar contenido "
                           "de voz' does not open the sign-in sheet — on 9.5 the app's voices need "
                           "an account." + kept, EXIT_SATURATED)
            recovered = True
            tr = new_project(a.voice, line)   # exits non-zero on its own if it cannot rebuild
            before = set(tr.glob("*.wav"))
            raw = wait_for_wav(tr, before, timeout=20) or None
            if not raw:
                set_text(line, a.voice)
                raw = wait_for_wav(tr, before)
            if not raw:
                die(head + "\n  A brand-new project did not generate either, so this is not the "
                           "saturation wall. Check by hand whether CapCut asks you to sign in or to "
                           "join Pro; if it does, use the local path, `voice.py --engine qwen`."
                    + kept, EXIT_SATURATED)
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
