"""Shared configuration for the video engine: canvas, safe area and paths.

Everything can be changed with environment variables, so the engine depends on nobody's
particular folders:

    REEL_FORGE_CACHE       self-downloaded resources      (default: ~/.cache/reel-forge)
    REEL_FORGE_FONTS       typefaces                      (default: $REEL_FORGE_CACHE/fonts)
    REEL_FORGE_ASSETS      base map, sound effects        (default: $REEL_FORGE_CACHE/assets)
    REEL_FORGE_MODELS      models                         (default: $REEL_FORGE_CACHE/models)
    REEL_FORGE_HOME        where projects live            (default: <the videos folder>/Reel Forge)
    REEL_FORGE_OUTPUT      base for relative `out` paths  (default: $REEL_FORGE_HOME)
    REEL_FORGE_FONT_SANS   .ttf of the sans               (default: variable Montserrat)
    REEL_FORGE_FONT_SERIF  .ttf of the serif              (default: Instrument Serif italic)
    REEL_FORGE_FONT_THAI   .ttf/.ttc covering Thai        (optional)
    REEL_FORGE_FONT_CJK    .ttf/.ttc covering CJK         (optional)
    REEL_FORGE_FORMAT      default aspect ratio           (9x16 | 4x5 | 1x1 | 16x9; the spec wins)

The full list of the plugin's variables is in docs/configuration.md.

The typefaces, the map and the model are downloaded with `uv run resources.py --all` (in this
folder). All these paths are exported back into the environment, so a spec can write
`"src": "$REEL_FORGE_ASSETS/sfx/shutter.mp3"` and the engine expands it.
"""
import os
import sys
from pathlib import Path

# ------------------------------------------------------------ canvas and formats

MARGIN = 1.25              # extra internal resolution (x1.25) so we can zoom without losing sharpness
FPS = 30
GRAIN_MAX = 0.012          # above this the grain looks dirty, not filmic

# One spec, four destinations. Each format carries its own canvas, its own safe area (what the
# app's interface covers) and its own text scale, because a `size` that reads well on a phone held
# vertically is tiny on a landscape frame.
#
#   safe   pixels the interface eats on each side
#   text   multiplier applied to every caption `size`; sizes in a spec are ALWAYS written in the
#          9x16 reference (1080x1920) and the engine rescales them for the target format
#   width  fraction of the canvas width centred text may occupy before it wraps
FORMATS = {
    # TikTok / Reels / Shorts: search bar on top, caption bar and footer at the bottom, and the
    # like / comment / share column on the right.
    "9x16": {"size": (1080, 1920), "text": 1.00, "width": 0.722,
             "safe": {"top": 150, "bottom": 480, "left": 60, "right": 180}},
    # Instagram feed: the tallest thing the feed does not crop. The interface sits below the media.
    "4x5": {"size": (1080, 1350), "text": 0.92, "width": 0.75,
            "safe": {"top": 70, "bottom": 140, "left": 60, "right": 60}},
    # Square: feed, LinkedIn, carousels.
    "1x1": {"size": (1080, 1080), "text": 0.88, "width": 0.75,
            "safe": {"top": 60, "bottom": 110, "left": 60, "right": 60}},
    # Landscape: YouTube, a site, a TV. The player's progress bar eats the bottom.
    "16x9": {"size": (1920, 1080), "text": 0.62, "width": 0.60,
             "safe": {"top": 80, "bottom": 130, "left": 100, "right": 100}},
}

# What people write in a spec when they mean one of the four above.
FORMAT_ALIASES = {"9:16": "9x16", "vertical": "9x16", "portrait": "9x16", "reel": "9x16",
                  "4:5": "4x5", "feed": "4x5", "1:1": "1x1", "square": "1x1",
                  "16:9": "16x9", "landscape": "16x9", "horizontal": "16x9", "youtube": "16x9"}

# The spec's `format` wins; $REEL_FORGE_FORMAT only changes the default for specs that declare none.
FORMAT = "9x16"
if os.environ.get("REEL_FORGE_FORMAT"):
    _want = os.environ["REEL_FORGE_FORMAT"].strip().lower().replace(" ", "")
    FORMAT = FORMAT_ALIASES.get(_want, _want if _want in FORMATS else FORMAT)
W, H = FORMATS[FORMAT]["size"]
SAFE = dict(FORMATS[FORMAT]["safe"])
TEXT_SCALE = FORMATS[FORMAT]["text"]
TEXT_WIDTH = int(W * FORMATS[FORMAT]["width"])


def normalize_format(name):
    """'9:16', 'vertical', '9x16' -> '9x16'. Raises on anything the engine cannot render."""
    key = str(name or FORMAT).strip().lower().replace(" ", "")
    key = FORMAT_ALIASES.get(key, key)
    if key not in FORMATS:
        raise SystemExit(f"Unknown `format`: {name}. Options: {', '.join(FORMATS)}")
    return key


def set_format(name):
    """Switches the canvas, the safe area and the text scale. Call it BEFORE rendering anything.

    render.py and effects.py cache W/H for speed, so both call their `refresh()` right after this.
    """
    global FORMAT, W, H, SAFE, TEXT_SCALE, TEXT_WIDTH
    FORMAT = normalize_format(name)
    f = FORMATS[FORMAT]
    W, H = f["size"]
    SAFE = dict(f["safe"])
    TEXT_SCALE = f["text"]
    TEXT_WIDTH = int(W * f["width"])
    return FORMAT


# ------------------------------------------------------------ paths

def _path(name, default):
    return Path(os.path.expandvars(os.path.expanduser(str(os.environ.get(name) or default))))


CACHE = _path("REEL_FORGE_CACHE", "~/.cache/reel-forge")
FONTS = _path("REEL_FORGE_FONTS", CACHE / "fonts")
ASSETS = _path("REEL_FORGE_ASSETS", CACHE / "assets")
MODELS = _path("REEL_FORGE_MODELS", CACHE / "models")

# The user's own videos folder, whatever the system calls it, and inside it one folder named after
# the plugin. Finder shows ~/Movies as "Películas" / "Movies"; Windows shows %USERPROFILE%\Videos as
# "Vídeos"; Linux has an XDG setting for it. The folder on disk is what matters, not its label.
APP_FOLDER = "Reel Forge"


def _videos_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Movies"
    if os.name == "nt":
        return Path(os.environ.get("USERPROFILE") or home) / "Videos"
    try:                                           # Linux and the rest: ask XDG, then fall back
        import subprocess
        r = subprocess.run(["xdg-user-dir", "VIDEOS"], capture_output=True, text=True, timeout=5)
        d = Path(r.stdout.strip())
        if r.returncode == 0 and d.is_dir() and d != home:
            return d
    except Exception:
        pass
    return home / "Videos"


HOME = _path("REEL_FORGE_HOME", _videos_dir() / APP_FOLDER)
OUTPUT = _path("REEL_FORGE_OUTPUT", HOME)

# Inside a concept's folder only the upload-ready videos sit loose; everything else lives here.
RESOURCES = "resources"

FONT_SANS = _path("REEL_FORGE_FONT_SANS", FONTS / "Montserrat[wght].ttf")
FONT_SERIF = _path("REEL_FORGE_FONT_SERIF", FONTS / "InstrumentSerif-Italic.ttf")

MAP_GEOJSON = ASSETS / "ne_50m_land.geojson"
SEG_MODEL = MODELS / "selfie_multiclass.tflite"
SFX = ASSETS / "sfx"

# Exported so specs can use them inside `src`.
for _n, _v in (("CACHE", CACHE), ("FONTS", FONTS), ("ASSETS", ASSETS), ("MODELS", MODELS),
               ("HOME", HOME), ("OUTPUT", OUTPUT)):
    os.environ.setdefault(f"REEL_FORGE_{_n}", str(_v))


# ------------------------------------------------------------ fallback fonts per script

# Montserrat and Instrument Serif only carry Latin. Thai or CJK needs another typeface; with
# none available, Pillow draws boxes. These paths are examples that exist on each system: if you
# have none of them, install Noto and point the variable at it.
_CANDIDATES = {
    "thai": ["/System/Library/Fonts/Supplemental/Thonburi.ttc",
             "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
             "C:/Windows/Fonts/leelawui.ttf"],
    "cjk": ["/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "C:/Windows/Fonts/msyh.ttc"],
}


def script_font(which):
    """Path to a typeface covering `which` ('thai' | 'cjk'), or None if there is none."""
    own = os.environ.get(f"REEL_FORGE_FONT_{which.upper()}")
    if own:
        return Path(os.path.expanduser(own))
    for p in _CANDIDATES[which]:
        if Path(p).exists():
            return Path(p)
    return None


# ------------------------------------------------------------ helpers

def path(value):
    """Expands ~ and $VARIABLES in any path coming from the spec."""
    return Path(os.path.expandvars(os.path.expanduser(str(value))))


def resolve_output(value):
    """The spec's `out`: absolute, with ~ or with $VAR is respected; relative hangs off REEL_FORGE_OUTPUT."""
    p = path(value)
    return p if p.is_absolute() else OUTPUT / p


_RESOURCES = Path(__file__).resolve().parent / "resources.py"


def require(target, what, flag="--all"):
    if not Path(target).exists():
        raise SystemExit(f"Missing {what}: {target}\nDownload it with:  uv run \"{_RESOURCES}\" {flag}")
    return Path(target)
