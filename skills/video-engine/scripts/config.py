"""Shared configuration for the video engine: canvas, safe area and paths.

Everything can be changed with environment variables, so the engine depends on nobody's
particular folders:

    REEL_FORGE_CACHE       self-downloaded resources      (default: ~/.cache/reel-forge)
    REEL_FORGE_FONTS       typefaces                      (default: $REEL_FORGE_CACHE/fonts)
    REEL_FORGE_ASSETS      base map, sound effects        (default: $REEL_FORGE_CACHE/assets)
    REEL_FORGE_MODELS      models                         (default: $REEL_FORGE_CACHE/models)
    REEL_FORGE_HOME        project root                   (default: ~/Movies|~/Videos/reel-forge)
    REEL_FORGE_OUTPUT      base for relative `out` paths  (default: $REEL_FORGE_HOME)
    REEL_FORGE_FONT_SANS   .ttf of the sans               (default: variable Montserrat)
    REEL_FORGE_FONT_SERIF  .ttf of the serif              (default: Instrument Serif italic)
    REEL_FORGE_FONT_THAI   .ttf/.ttc covering Thai        (optional)
    REEL_FORGE_FONT_CJK    .ttf/.ttc covering CJK         (optional)

The full list of the plugin's variables is in docs/configuration.md.

The typefaces, the map and the model are downloaded with `uv run resources.py --all` (in this
folder). All these paths are exported back into the environment, so a spec can write
`"src": "$REEL_FORGE_ASSETS/sfx/shutter.mp3"` and the engine expands it.
"""
import os
from pathlib import Path

# ------------------------------------------------------------ canvas

W, H = 1080, 1920          # 9:16, the TikTok/Reels/Shorts format
MARGIN = 1.25              # extra internal resolution (1350x2400) so we can zoom without losing sharpness
FPS = 30

# TikTok's safe area: the search bar at the top, the caption bar and footer at the bottom,
# the button column (like, comment, share) on the right.
SAFE = {"top": 150, "bottom": 480, "left": 60, "right": 180}

GRAIN_MAX = 0.012          # above this the grain looks dirty, not filmic


# ------------------------------------------------------------ paths

def _path(name, default):
    return Path(os.path.expandvars(os.path.expanduser(str(os.environ.get(name) or default))))


CACHE = _path("REEL_FORGE_CACHE", "~/.cache/reel-forge")
FONTS = _path("REEL_FORGE_FONTS", CACHE / "fonts")
ASSETS = _path("REEL_FORGE_ASSETS", CACHE / "assets")
MODELS = _path("REEL_FORGE_MODELS", CACHE / "models")

_movies = Path.home() / "Movies"                      # macOS; on Linux/Windows it is ~/Videos
HOME = _path("REEL_FORGE_HOME", (_movies if _movies.is_dir() else Path.home() / "Videos") / "reel-forge")
OUTPUT = _path("REEL_FORGE_OUTPUT", HOME)

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
