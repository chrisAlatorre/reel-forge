"""Configuración compartida del motor de video: lienzo, zona segura y rutas.

Todo se puede cambiar con variables de entorno, así que el motor no depende de
las carpetas de ninguna persona en particular:

    REEL_FORGE_CACHE       recursos que se bajan solos   (default: ~/.cache/reel-forge)
    REEL_FORGE_FONTS       tipografías                   (default: $REEL_FORGE_CACHE/fonts)
    REEL_FORGE_ASSETS      mapa base, efectos de sonido  (default: $REEL_FORGE_CACHE/assets)
    REEL_FORGE_MODELS      modelos                       (default: $REEL_FORGE_CACHE/models)
    REEL_FORGE_HOME        raíz de los proyectos         (default: ~/Movies|~/Videos/reel-forge)
    REEL_FORGE_SALIDA      base de los `out` relativos   (default: $REEL_FORGE_HOME)
    REEL_FORGE_FONT_SANS   .ttf de la sans               (default: Montserrat variable)
    REEL_FORGE_FONT_SERIF  .ttf de la serif              (default: Instrument Serif itálica)
    REEL_FORGE_FONT_THAI   .ttf/.ttc con alfabeto tailandés (opcional)
    REEL_FORGE_FONT_CJK    .ttf/.ttc con chino/japonés/coreano (opcional)

Las tipografías, el mapa y el modelo se bajan con `uv run tipografias.py --todo` (en esta carpeta).
Todas estas rutas quedan exportadas al entorno, así que un spec puede escribir
`"src": "$REEL_FORGE_ASSETS/sfx/obturador.mp3"` y el motor lo expande.
"""
import os
from pathlib import Path

# ------------------------------------------------------------ lienzo

W, H = 1080, 1920          # 9:16, el formato de TikTok/Reels/Shorts
MARGEN = 1.25              # resolución interna extra (1350x2400) para hacer zoom sin perder nitidez
FPS = 30

# Zona segura de TikTok: arriba el buscador, abajo la barra de texto y el pie,
# a la derecha la columna de botones (like, comentar, compartir).
SEGURA = {"top": 150, "bottom": 480, "left": 60, "right": 180}

GRANO_MAX = 0.012          # arriba de esto el grano se ve sucio, no filmico


# ------------------------------------------------------------ rutas

def _env(nombre):
    """Lee REEL_FORGE_X y acepta REELFORGE_X como alias, por si un spec viejo lo usa."""
    return os.environ.get(nombre) or os.environ.get(nombre.replace("REEL_FORGE_", "REELFORGE_"))


def _ruta(nombre, default):
    return Path(os.path.expandvars(os.path.expanduser(str(_env(nombre) or default))))


CACHE = _ruta("REEL_FORGE_CACHE", "~/.cache/reel-forge")
FUENTES = _ruta("REEL_FORGE_FONTS", CACHE / "fonts")
ASSETS = _ruta("REEL_FORGE_ASSETS", CACHE / "assets")
MODELOS = _ruta("REEL_FORGE_MODELS", CACHE / "models")

_peliculas = Path.home() / "Movies"                   # macOS; en Linux/Windows es ~/Videos
HOME = _ruta("REEL_FORGE_HOME", (_peliculas if _peliculas.is_dir() else Path.home() / "Videos") / "reel-forge")
SALIDA = _ruta("REEL_FORGE_SALIDA", HOME)

FUENTE_SANS = _ruta("REEL_FORGE_FONT_SANS", FUENTES / "Montserrat[wght].ttf")
FUENTE_SERIF = _ruta("REEL_FORGE_FONT_SERIF", FUENTES / "InstrumentSerif-Italic.ttf")

MAPA_GEOJSON = ASSETS / "ne_50m_land.geojson"
MODELO_SEG = MODELOS / "selfie_multiclass.tflite"
SFX = ASSETS / "sfx"

# Se exportan (en las dos grafías) para que los specs puedan usarlas dentro de `src`.
for _n, _v in (("CACHE", CACHE), ("FONTS", FUENTES), ("ASSETS", ASSETS), ("MODELS", MODELOS),
               ("HOME", HOME), ("SALIDA", SALIDA)):
    os.environ.setdefault(f"REEL_FORGE_{_n}", str(_v))
    os.environ.setdefault(f"REELFORGE_{_n}", str(_v))


# ------------------------------------------------------------ fuentes de repuesto por alfabeto

# Montserrat e Instrument Serif solo traen latín. Para tailandés o CJK hace falta otra
# tipografía; si no hay ninguna, Pillow dibuja cuadritos. Estas rutas son ejemplos que
# existen en cada sistema: si no tienes ninguna, instala Noto y apunta la variable.
_CANDIDATAS = {
    "thai": ["/System/Library/Fonts/Supplemental/Thonburi.ttc",
             "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
             "C:/Windows/Fonts/leelawui.ttf"],
    "cjk": ["/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "C:/Windows/Fonts/msyh.ttc"],
}


def fuente_alfabeto(cual):
    """Ruta a una tipografía que cubra `cual` ('thai' | 'cjk'), o None si no hay ninguna."""
    propia = _env(f"REEL_FORGE_FONT_{cual.upper()}")
    if propia:
        return Path(os.path.expanduser(propia))
    for r in _CANDIDATAS[cual]:
        if Path(r).exists():
            return Path(r)
    return None


# ------------------------------------------------------------ ayudas

def ruta(valor):
    """Expande ~ y $VARIABLES en cualquier ruta que venga del spec."""
    return Path(os.path.expandvars(os.path.expanduser(str(valor))))


def resolver_salida(valor):
    """`out` del spec: absoluto, con ~ o con $VAR se respeta; relativo cuelga de REEL_FORGE_SALIDA."""
    p = ruta(valor)
    return p if p.is_absolute() else SALIDA / p


_TIPOGRAFIAS = Path(__file__).resolve().parent / "tipografias.py"


def exigir(destino, que, bandera="--todo"):
    if not Path(destino).exists():
        raise SystemExit(f"Falta {que}: {destino}\nBájalo con:  uv run \"{_TIPOGRAFIAS}\" {bandera}")
    return Path(destino)
