# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Downloads the resources the engine does NOT keep in the repo: typefaces, base map and segmentation model.

    uv run scripts/resources.py           # typefaces only (Montserrat + Instrument Serif)
    uv run scripts/resources.py --map     # + the Natural Earth world map (for the `map` segment)
    uv run scripts/resources.py --model   # + the person segmentation model (for `behind` and `cutout`)
    uv run scripts/resources.py --all     # all three

Everything lands in $REEL_FORGE_CACHE (default ~/.cache/reel-forge). Nothing is versioned in the repo.

LICENSES
- Montserrat and Instrument Serif: SIL Open Font License 1.1 (OFL). Free to use, embed and
  redistribute, including commercially, but the OFL requires keeping the license notice and
  forbids selling the fonts on their own. That is why this script downloads them from the
  official Google Fonts repository together with their OFL.txt, instead of putting the .ttf
  files in the repo.
- Natural Earth (ne_50m_land): public domain, no attribution required.
- MediaPipe's selfie_multiclass: Apache-2.0 (Google).
"""
import argparse
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

GF = "https://github.com/google/fonts/raw/main/ofl"

TYPEFACES = [
    (f"{GF}/montserrat/Montserrat%5Bwght%5D.ttf", "Montserrat[wght].ttf"),
    (f"{GF}/montserrat/OFL.txt", "OFL-Montserrat.txt"),
    (f"{GF}/instrumentserif/InstrumentSerif-Italic.ttf", "InstrumentSerif-Italic.ttf"),
    (f"{GF}/instrumentserif/InstrumentSerif-Regular.ttf", "InstrumentSerif-Regular.ttf"),
    (f"{GF}/instrumentserif/OFL.txt", "OFL-InstrumentSerif.txt"),
]

MAP = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson",
       "ne_50m_land.geojson")

MODEL = ("https://storage.googleapis.com/mediapipe-models/image_segmenter/"
         "selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite",
         "selfie_multiclass.tflite")


def download(url, target):
    target = Path(target)
    if target.exists() and target.stat().st_size > 0:
        print(f"  already there: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading  : {target.name}")
    tmp = target.with_suffix(target.suffix + ".partial")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        f.write(r.read())
    tmp.replace(target)


def main():
    ap = argparse.ArgumentParser(description="Video engine resources")
    ap.add_argument("--map", action="store_true", help="the Natural Earth world map")
    ap.add_argument("--model", action="store_true", help="the person segmentation model")
    ap.add_argument("--all", action="store_true", help="typefaces + map + model")
    a = ap.parse_args()

    print(f"Typefaces → {config.FONTS}")
    for url, name in TYPEFACES:
        download(url, config.FONTS / name)

    if a.map or a.all:
        print(f"Map → {config.ASSETS}")
        download(MAP[0], config.ASSETS / MAP[1])

    if a.model or a.all:
        print(f"Model → {config.MODELS}")
        download(MODEL[0], config.MODELS / MODEL[1])

    print("\nDone. The fonts are used under SIL OFL 1.1; keep the OFL-*.txt files next to the .ttf files.")


if __name__ == "__main__":
    main()
