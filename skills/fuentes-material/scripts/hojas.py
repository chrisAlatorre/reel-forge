# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "pillow-heif", "opencv-contrib-python<5", "numpy<2.3"]
# ///
"""Hojas de contacto, recortes de cara y tiras de cuadros: lo que los agentes MIRAN.

La regla del plugin es que nadie cataloga por nombre de archivo. Este script produce las imágenes
que un agente abre con `Read` para decidir de verdad qué sirve.

    uv run hojas.py contacto lista.json --cols 6 --salida taller/hojas/dia-03
    uv run hojas.py caras    lista.json --salida taller/hojas/caras-dia-03
    uv run hojas.py tira     clip.mp4 --fps 1 --cols 8 --salida taller/hojas/

`lista.json` acepta tres formas, y también se pueden pasar rutas sueltas en la línea de comandos:

    ["~/Pictures/viaje/IMG_0001.HEIC", "~/Pictures/viaje/IMG_0002.HEIC"]
    [{"id": "f-001", "ruta": "~/Pictures/viaje/IMG_0001.HEIC"}, ...]
    {"items": [{"id": "f-001", "ruta": "...", "miniatura": "..."}]}   # salida de inventario.py

Si un item trae `miniatura` (Apple Photos la da sin bajar el original), se usa esa y no se toca el
original. Es lo que permite catalogar una biblioteca que vive en la nube.

**Cada hoja lleva el número impreso encima de cada celda** y se acompaña de un `indice.json` que mapea
número → id y ruta. Si el agente dice "la 14", tiene que existir una 14: sin ese mapa, el catálogo no
se puede reconstruir.

Dependencias: Pillow (imagen), OpenCV (detección de caras, con los clasificadores que trae el propio
paquete: no baja nada) y `ffmpeg`/`ffprobe` en el PATH para el comando `tira`.

Multiplataforma. La única parte que solo existe en macOS es la ruta de miniaturas de la app Fotos, y
eso lo resuelve `fuentes.py`, no este script.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - sin HEIC el resto funciona igual
    pass

EXT_FOTO = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".dng", ".webp", ".avif"}

# Tamaño de la celda de la hoja de contacto. 320 px de ancho es el punto donde todavía se distingue
# una mueca sin que la hoja pese de más: con 30 celdas quedan ~2 MB.
CELDA = 320
MARGEN = 6
BARRA = 22  # alto de la franja con el número


# --------------------------------------------------------------------------- entradas


def expandir(ruta) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(ruta)))).resolve()


def cargar_items(entradas: list[str]) -> list[dict]:
    """Normaliza lo que venga (JSON, carpeta o rutas sueltas) a [{id, ruta, miniatura}]."""
    items: list[dict] = []

    for entrada in entradas:
        p = expandir(entrada)

        if p.is_dir():
            for hijo in sorted(p.iterdir()):
                if hijo.suffix.lower() in EXT_FOTO:
                    items.append({"ruta": str(hijo)})
            continue

        if p.suffix.lower() == ".json":
            datos = json.loads(p.read_text(encoding="utf-8"))
            crudos = datos.get("items", datos) if isinstance(datos, dict) else datos
            for i in crudos:
                items.append({"ruta": i} if isinstance(i, str) else dict(i))
            continue

        items.append({"ruta": str(p)})

    salida = []
    for n, it in enumerate(items, 1):
        ruta = it.get("miniatura") or it.get("ruta") or it.get("path")
        if not ruta:
            continue
        salida.append({
            "id": it.get("id") or f"f-{n:03d}",
            "ruta": str(expandir(it.get("ruta") or ruta)),
            "usada": str(expandir(ruta)),
        })
    return salida


def tipografia(tam: int):
    """Una fuente que exista en el sistema; si no hay ninguna, la de Pillow (fea pero legible)."""
    for c in (
        os.environ.get("REEL_FORGE_FONT_SANS"),
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",   # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
        "C:/Windows/Fonts/arialbd.ttf",                          # Windows
    ):
        if c and Path(c).exists():
            try:
                return ImageFont.truetype(c, tam)
            except Exception:
                pass
    return ImageFont.load_default()


# --------------------------------------------------------------------------- hoja de contacto


def celda(img: Image.Image, numero: int, etiqueta: str, fuente) -> Image.Image:
    """Miniatura cuadrada con el número impreso en una franja abajo."""
    lienzo = Image.new("RGB", (CELDA, CELDA + BARRA), (18, 18, 18))
    copia = img.copy()
    copia.thumbnail((CELDA - MARGEN * 2, CELDA - MARGEN * 2), Image.LANCZOS)
    lienzo.paste(copia, ((CELDA - copia.width) // 2, (CELDA - MARGEN * 2 - copia.height) // 2 + MARGEN))

    d = ImageDraw.Draw(lienzo)
    d.rectangle([0, CELDA, CELDA, CELDA + BARRA], fill=(0, 0, 0))
    d.text((6, CELDA + 3), f"{numero}", fill=(255, 220, 0), font=fuente)
    d.text((44, CELDA + 4), etiqueta[:34], fill=(190, 190, 190), font=fuente)
    return lienzo


def abrir(ruta: str) -> Image.Image | None:
    try:
        img = Image.open(ruta)
        img.load()
        return img.convert("RGB")
    except Exception as e:
        print(f"  no se pudo abrir {ruta}: {e}", file=sys.stderr)
        return None


def hoja_contacto(items: list[dict], salida: Path, cols: int, por_hoja: int) -> dict:
    salida.mkdir(parents=True, exist_ok=True)
    fuente = tipografia(16)
    indice, hojas = [], []

    for h, inicio in enumerate(range(0, len(items), por_hoja), 1):
        lote = items[inicio:inicio + por_hoja]
        celdas = []
        for n, it in enumerate(lote, inicio + 1):
            img = abrir(it["usada"])
            if img is None:
                continue
            celdas.append(celda(img, n, Path(it["ruta"]).name, fuente))
            indice.append({"n": n, "id": it["id"], "ruta": it["ruta"], "hoja": h})

        if not celdas:
            continue

        ancho = min(cols, len(celdas))          # no dejes columnas vacías con lotes chicos
        filas = (len(celdas) + ancho - 1) // ancho
        pliego = Image.new("RGB", (ancho * CELDA, filas * (CELDA + BARRA)), (18, 18, 18))
        for k, c in enumerate(celdas):
            pliego.paste(c, ((k % ancho) * CELDA, (k // ancho) * (CELDA + BARRA)))

        destino = salida / f"hoja-{h:02d}.jpg"
        pliego.save(destino, quality=88)
        hojas.append(str(destino))
        print(f"  {destino}  ({len(celdas)} miniaturas)")

    return {"tipo": "contacto", "hojas": hojas, "indice": indice}


# --------------------------------------------------------------------------- recortes de cara


def detector():
    """Clasificador de caras de OpenCV.

    Los XML vienen dentro del paquete `opencv-contrib-python` **4.x**; OpenCV 5 los quitó, y por eso
    la cabecera `# /// script` pide `<5`. Con `$REEL_FORGE_CASCADA` se puede apuntar a otro XML.
    """
    import cv2

    propia = os.environ.get("REEL_FORGE_CASCADA")
    if propia:
        ruta = Path(propia)
    elif hasattr(cv2, "data") and getattr(cv2.data, "haarcascades", None):
        ruta = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    else:
        ruta = Path("haarcascade_frontalface_default.xml")

    if not ruta.exists():
        raise SystemExit(
            "OpenCV no trae el clasificador de caras (OpenCV 5 lo quitó del paquete).\n"
            "Córrelo con `uv run`, que respeta el pin `opencv-contrib-python<5` de la cabecera,\n"
            "o apunta a un XML propio con $REEL_FORGE_CASCADA."
        )
    return cv2.CascadeClassifier(str(ruta))


def caras_de(img: Image.Image, casc) -> list[tuple[int, int, int, int]]:
    import cv2
    import numpy as np

    chico = img.copy()
    chico.thumbnail((900, 900), Image.LANCZOS)
    escala = img.width / chico.width
    gris = cv2.cvtColor(np.array(chico), cv2.COLOR_RGB2GRAY)
    cajas = casc.detectMultiScale(gris, scaleFactor=1.15, minNeighbors=5, minSize=(40, 40))
    return [tuple(int(v * escala) for v in c) for c in cajas]


def hoja_caras(items: list[dict], salida: Path, cols: int, por_hoja: int, holgura: float) -> dict:
    """Una hoja solo con las caras, numerada igual que la hoja de contacto.

    Es el paso que más videos ha salvado: en una miniatura de 180 px no se ve que alguien está a media
    palabra. Los números coinciden con los de `contacto` sobre la MISMA lista, así que las dos hojas
    se leen juntas.
    """
    salida.mkdir(parents=True, exist_ok=True)
    casc = detector()
    fuente = tipografia(16)
    recortes, indice, sin_cara = [], [], []

    for n, it in enumerate(items, 1):
        img = abrir(it["usada"])
        if img is None:
            continue
        cajas = caras_de(img, casc)
        if not cajas:
            sin_cara.append({"n": n, "id": it["id"], "ruta": it["ruta"]})
            continue
        x, y, w, h = max(cajas, key=lambda c: c[2] * c[3])   # la cara más grande = el sujeto
        d = int(max(w, h) * holgura)
        cx, cy = x + w // 2, y + h // 2
        caja = (max(0, cx - d), max(0, cy - d), min(img.width, cx + d), min(img.height, cy + d))
        recortes.append((n, it, img.crop(caja)))
        indice.append({"n": n, "id": it["id"], "ruta": it["ruta"], "caja": [x, y, w, h]})

    hojas = []
    for h_i, inicio in enumerate(range(0, len(recortes), por_hoja), 1):
        lote = recortes[inicio:inicio + por_hoja]
        celdas = [celda(rec, n, Path(it["ruta"]).name, fuente) for n, it, rec in lote]
        ancho = min(cols, len(celdas))          # no dejes columnas vacías con lotes chicos
        filas = (len(celdas) + ancho - 1) // ancho
        pliego = Image.new("RGB", (ancho * CELDA, filas * (CELDA + BARRA)), (18, 18, 18))
        for k, c in enumerate(celdas):
            pliego.paste(c, ((k % ancho) * CELDA, (k // ancho) * (CELDA + BARRA)))
        destino = salida / f"caras-{h_i:02d}.jpg"
        pliego.save(destino, quality=90)
        hojas.append(str(destino))
        print(f"  {destino}  ({len(celdas)} caras)")

    if sin_cara:
        print(f"  sin cara detectada: {len(sin_cara)} (van en indice.json como `sin_cara`)")
    return {"tipo": "caras", "hojas": hojas, "indice": indice, "sin_cara": sin_cara}


# --------------------------------------------------------------------------- tira de cuadros


def duracion(video: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(video)],
            capture_output=True, text=True, check=True).stdout.strip()
        return float(out)
    except Exception:
        return None


def tira(video: Path, salida: Path, fps: float, cols: int, filas: int,
         inicio: float | None, dur: float | None) -> dict:
    """Tira de cuadros con ffmpeg: 1 fps para catalogar, 4 fps para cazar el cuadro de un corte.

    Un mosaico de `cols x filas` cubre `cols*filas/fps` segundos. Si el clip da para más, se escriben
    varias tiras numeradas y cada una dice qué segundos abarca (eso es lo que hace utilizable el
    `inicio_s`/`fin_s` del catálogo).
    """
    if not shutil.which("ffmpeg"):
        raise SystemExit("hace falta `ffmpeg` en el PATH")
    salida.mkdir(parents=True, exist_ok=True)

    total = duracion(video)
    t0 = inicio or 0.0
    largo = dur if dur is not None else ((total - t0) if total else None)
    por_tira = cols * filas / fps

    tiras, n = [], 0
    while True:
        desde = t0 + n * por_tira
        if largo is not None and desde >= t0 + largo - 1e-6:
            break
        trozo = por_tira if largo is None else min(por_tira, t0 + largo - desde)
        destino = salida / f"{video.stem}-tira-{n + 1:02d}.jpg"
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y",
               "-ss", f"{desde:.3f}", "-t", f"{trozo:.3f}", "-i", str(video),
               "-vf", f"fps={fps},scale=216:-2,tile={cols}x{filas}",
               "-frames:v", "1", str(destino)]
        subprocess.run(cmd, check=True)
        if not destino.exists():
            break
        tiras.append({"archivo": str(destino), "desde_s": round(desde, 2),
                      "hasta_s": round(desde + trozo, 2), "fps": fps, "rejilla": f"{cols}x{filas}"})
        print(f"  {destino}  [{desde:.1f}s - {desde + trozo:.1f}s]")
        n += 1
        if largo is None or n > 200:
            break

    return {"tipo": "tira", "video": str(video), "duracion_s": total, "tiras": tiras}


# --------------------------------------------------------------------------- cli


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Hojas de contacto, recortes de cara y tiras de cuadros para catalogar material.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Ejemplos:\n"
               "  uv run hojas.py contacto lista.json --cols 6 --salida taller/hojas/dia-03\n"
               "  uv run hojas.py caras    ~/Pictures/viaje --salida taller/hojas/caras\n"
               "  uv run hojas.py tira     clip.mp4 --fps 1 --cols 8 --salida taller/hojas\n")
    ap.add_argument("comando", choices=["contacto", "caras", "tira"])
    ap.add_argument("entradas", nargs="+",
                    help="lista.json, una carpeta, rutas sueltas; para `tira`, el video")
    ap.add_argument("--salida", default="hojas", help="carpeta de salida (default: ./hojas)")
    ap.add_argument("--cols", type=int, default=6, help="columnas de la rejilla (default: 6)")
    ap.add_argument("--por-hoja", type=int, default=30,
                    help="miniaturas por hoja (default: 30; más de 36 y no distingues una mueca)")
    ap.add_argument("--holgura", type=float, default=1.1,
                    help="`caras`: cuánto se abre el recorte alrededor de la cara (default: 1.1)")
    ap.add_argument("--fps", type=float, default=1.0, help="`tira`: cuadros por segundo (default: 1)")
    ap.add_argument("--filas", type=int, default=4, help="`tira`: filas de la rejilla (default: 4)")
    ap.add_argument("--inicio", type=float, help="`tira`: segundo inicial")
    ap.add_argument("--dur", type=float, help="`tira`: segundos a cubrir")
    args = ap.parse_args()

    salida = expandir(args.salida)

    if args.comando == "tira":
        video = expandir(args.entradas[0])
        if not video.exists():
            raise SystemExit(f"no existe: {video}")
        res = tira(video, salida, args.fps, args.cols, args.filas, args.inicio, args.dur)
    else:
        items = cargar_items(args.entradas)
        if not items:
            raise SystemExit("no hay nada que procesar: revisa la lista o la carpeta")
        print(f"{len(items)} archivos")
        if args.comando == "contacto":
            res = hoja_contacto(items, salida, args.cols, args.por_hoja)
        else:
            res = hoja_caras(items, salida, args.cols, args.por_hoja, args.holgura)

    (salida / "indice.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"índice: {salida / 'indice.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
