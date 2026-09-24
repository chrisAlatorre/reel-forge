# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Pega una narración a un video YA renderizado.

Lee un guion con tiempos, genera (o reutiliza) un WAV por línea y los mezcla sobre el MP4 en el
segundo que indica cada línea. No re-renderiza el video: copia el stream de video tal cual.

Uso:
  uv run narrar.py GUION.txt VIDEO.mp4 SALIDA.mp4                      # voz local (voz.py --motor qwen)
  uv run narrar.py GUION.txt VIDEO.mp4 SALIDA.mp4 --motor capcut       # voz de la app (solo macOS)
  uv run narrar.py GUION.txt VIDEO.mp4 SALIDA.mp4 --gen CARPETA_VOCES  # WAVs ya generados
  uv run narrar.py GUION.txt --solo-parse                              # revisa cómo quedó el parseo

Formato del guion: una línea por intervención, empezando por el segundo en que entra.
Aguanta las variantes que suelen salir de un guion escrito a mano o por otro agente:

    0.5   Aquí empieza todo.
    [3.2] Y aquí sigue.
    7.0 s | 2.4 s | La tercera línea.

Reglas del parser: se corta al llegar a un encabezado "Notas" o "Opcional" (lo de abajo son
comentarios, no líneas), se ignoran separadores y encabezados markdown, y se descartan las líneas
sin texto real. El audio original del video se conserva; la voz se suma encima. Si quieres que la
música baje bajo la voz, hazlo al renderizar el video, no aquí.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
CAPCUT = AQUI / "capcut_voz.py"
LOCAL = AQUI / "voz.py"


def parse(ruta):
    """Devuelve [(segundo, texto)] tolerando los formatos de guion más comunes."""
    lineas = []
    for cruda in Path(ruta).read_text(encoding="utf-8", errors="ignore").splitlines():
        ln = cruda.rstrip()
        # Todo lo que va después del encabezado "Notas" son comentarios: ahí se acaba la tabla.
        # Sin esto, un comentario como "…de 15.8 a 16.9 s). Si la metes antes…" entra como línea.
        if re.match(r"\s*notas?\s*:?\s*$", ln, re.I):
            break
        # El bloque "OPCIONAL" tampoco entra: suele solaparse con una línea obligatoria y taparla.
        # Si de verdad la quieres, muévela a la tabla con su segundo.
        if re.match(r"\s*opcional\b", ln, re.I):
            break
        if not ln.strip() or ln.lstrip().startswith(("---", "===", "#")):
            continue
        m = re.match(r"\s*(?:\[\s*)?~?\s*(\d+(?:\.\d+)?)\s*(?:\])?\s*(?:s\b)?\s*(?:\|)?\s+(?:~?\s*[\d.]+\s*s?\s+)?(.+)$", ln)
        if not m:
            continue
        t, texto = float(m.group(1)), m.group(2).strip(" |")
        texto = re.sub(r"\s{2,}[\d.]+\s*s\.?$", "", texto).strip()
        # Restos de columnas de duración: "0.5  2.4 s  texto", "0.20s ~2.7s texto", "~1.4 s  texto"
        texto = re.sub(r"^(?:s\b|~?\s*[\d.]+\s*s\b|\d+)\s*", "", texto).strip()
        texto = re.sub(r"^~?\s*[\d.]+\s*s\b\s*", "", texto).strip()
        texto = texto.strip(" |\t")   # restos de la columna de duración en guiones con tabla
        if len(texto) < 8 or not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3}", texto):
            continue
        if texto.lower().startswith(("línea", "linea", "entra", "dura", "duración", "duracion",
                                     "video", "opcional", "notas")):
            continue
        lineas.append((t, texto))
    return lineas


def genera(motor, lineas, carpeta, velocidad, voz):
    """Llama al sintetizador que toque. Ambos dejan lN.wav + duraciones.json en la carpeta."""
    tmp = carpeta / "lineas.json"
    tmp.write_text(json.dumps([x for _, x in lineas], ensure_ascii=False), encoding="utf-8")
    if motor == "capcut":
        if sys.platform != "darwin":
            sys.exit("--motor capcut solo funciona en macOS (automatiza la app de escritorio). Usa el local.")
        cmd = ["uv", "run", str(CAPCUT), str(tmp), str(carpeta), "--velocidad", str(velocidad)]
        if voz:
            cmd += ["--voz", voz]
    else:
        cmd = ["uv", "run", str(LOCAL), str(tmp), str(carpeta), "--motor", motor]
        if voz:
            cmd += ["--voz", voz]
    subprocess.run(cmd, check=True)


def ffprobe(*args):
    return subprocess.run(["ffprobe", "-v", "error", *args], capture_output=True, text=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser(description="Mezcla una narración sobre un video ya renderizado")
    ap.add_argument("guion")
    ap.add_argument("video", nargs="?")
    ap.add_argument("salida", nargs="?")
    ap.add_argument("--motor", default="qwen", choices=["qwen", "voxcpm", "piper", "capcut"],
                    help="qwen (local, default) | voxcpm | piper | capcut (macOS, voz de la app)")
    ap.add_argument("--voz", help="nombre de la voz para el motor elegido")
    ap.add_argument("--gen", help="carpeta con l0.wav… ya generados; si no, los genera")
    ap.add_argument("--velocidad", type=float, default=1.4, help="solo --motor capcut: ritmo del trend")
    ap.add_argument("--volumen", type=float, default=1.0, help="ganancia de la voz sobre el audio del video")
    ap.add_argument("--solo-parse", action="store_true")
    a = ap.parse_args()

    lineas = parse(a.guion)
    if not lineas:
        sys.exit(f"sin líneas en {a.guion}")
    print(json.dumps([{"t": t, "texto": x} for t, x in lineas], ensure_ascii=False, indent=1))
    if a.solo_parse:
        return
    if not (a.video and a.salida):
        ap.error("faltan VIDEO.mp4 y SALIDA.mp4")

    carpeta = Path(a.gen) if a.gen else Path(a.salida).parent / ("voces-" + Path(a.salida).stem)
    carpeta.mkdir(parents=True, exist_ok=True)
    # duraciones.json es la señal de "carpeta completa": si falta, se (re)genera y se reanuda sola.
    if not (carpeta / "duraciones.json").exists():
        genera(a.motor, lineas, carpeta, a.velocidad, a.voz)

    wavs = [carpeta / f"l{i}.wav" for i in range(len(lineas))]
    faltan = [w for w in wavs if not w.exists()]
    if faltan:
        sys.exit(f"faltan audios: {faltan[:3]}")

    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", a.video]
    filtros = []
    for i, ((t, _), w) in enumerate(zip(lineas, wavs)):
        cmd += ["-i", str(w)]
        ms = int(t * 1000)
        filtros.append(f"[{i + 1}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                       f"adelay={ms}|{ms},volume={a.volumen}[v{i}]")

    tiene_audio = bool(ffprobe("-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", a.video))
    entradas = ("[0:a]" if tiene_audio else "") + "".join(f"[v{i}]" for i in range(len(lineas)))
    n = len(lineas) + (1 if tiene_audio else 0)
    largo = float(ffprobe("-show_entries", "format=duration", "-of", "csv=p=0", a.video))
    # OJO: nada de duration=first. Si el video viene SIN audio, la primera entrada del amix es la
    # primera línea de voz y la mezcla se corta al acabar esa línea. Se toma la más larga y se
    # recorta a la duración del video.
    filtros.append(f"{entradas}amix=inputs={n}:normalize=0:duration=longest,"
                   f"atrim=0:{largo:.3f},asetpts=N/SR/TB,alimiter=limit=0.95[a]")
    cmd += ["-filter_complex", ";".join(filtros), "-map", "0:v", "-map", "[a]", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", a.salida]
    subprocess.run(cmd, check=True)
    print("ok:", a.salida)


if __name__ == "__main__":
    main()
