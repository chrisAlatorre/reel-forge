# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Baja los recursos que el motor NO guarda en el repo: tipografías, mapa base y modelo de segmentación.

    uv run scripts/tipografias.py            # solo tipografías (Montserrat + Instrument Serif)
    uv run scripts/tipografias.py --mapa     # + mapa mundial de Natural Earth (para el segmento `map`)
    uv run scripts/tipografias.py --modelo   # + modelo de segmentación de personas (para `behind` y `cutout`)
    uv run scripts/tipografias.py --todo     # los tres

Todo cae en $REEL_FORGE_CACHE (default ~/.cache/reel-forge). Nada se versiona en el repo.

LICENCIAS
- Montserrat e Instrument Serif: SIL Open Font License 1.1 (OFL). Se pueden usar, incrustar y
  redistribuir gratis, incluso comercialmente, pero la OFL exige conservar el aviso de licencia
  y NO vender las fuentes solas. Por eso este script las baja del repositorio oficial de Google
  Fonts junto con su OFL.txt en vez de meter los .ttf en el repo.
- Natural Earth (ne_50m_land): dominio público, sin atribución obligatoria.
- selfie_multiclass de MediaPipe: Apache-2.0 (Google).
"""
import argparse
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

GF = "https://github.com/google/fonts/raw/main/ofl"

TIPOGRAFIAS = [
    (f"{GF}/montserrat/Montserrat%5Bwght%5D.ttf", "Montserrat[wght].ttf"),
    (f"{GF}/montserrat/OFL.txt", "OFL-Montserrat.txt"),
    (f"{GF}/instrumentserif/InstrumentSerif-Italic.ttf", "InstrumentSerif-Italic.ttf"),
    (f"{GF}/instrumentserif/InstrumentSerif-Regular.ttf", "InstrumentSerif-Regular.ttf"),
    (f"{GF}/instrumentserif/OFL.txt", "OFL-InstrumentSerif.txt"),
]

MAPA = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson",
        "ne_50m_land.geojson")

MODELO = ("https://storage.googleapis.com/mediapipe-models/image_segmenter/"
          "selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite",
          "selfie_multiclass.tflite")


def bajar(url, destino):
    destino = Path(destino)
    if destino.exists() and destino.stat().st_size > 0:
        print(f"  ya estaba: {destino}")
        return
    destino.parent.mkdir(parents=True, exist_ok=True)
    print(f"  bajando  : {destino.name}")
    tmp = destino.with_suffix(destino.suffix + ".parcial")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        f.write(r.read())
    tmp.replace(destino)


def main():
    ap = argparse.ArgumentParser(description="Recursos del motor de video")
    ap.add_argument("--mapa", action="store_true", help="mapa mundial de Natural Earth")
    ap.add_argument("--modelo", action="store_true", help="modelo de segmentación de personas")
    ap.add_argument("--todo", action="store_true", help="tipografías + mapa + modelo")
    a = ap.parse_args()

    print(f"Tipografías → {config.FUENTES}")
    for url, nombre in TIPOGRAFIAS:
        bajar(url, config.FUENTES / nombre)

    if a.mapa or a.todo:
        print(f"Mapa → {config.ASSETS}")
        bajar(MAPA[0], config.ASSETS / MAPA[1])

    if a.modelo or a.todo:
        print(f"Modelo → {config.MODELOS}")
        bajar(MODELO[0], config.MODELOS / MODELO[1])

    print("\nListo. Las fuentes se usan bajo SIL OFL 1.1; conserva los OFL-*.txt junto a los .ttf.")


if __name__ == "__main__":
    main()
