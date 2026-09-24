# /// script
# requires-python = ">=3.10"
# dependencies = ["pyobjc-framework-Quartz"]
# ///
"""Voz de narrador de CapCut (macOS), manejando la app de escritorio a clics.

SOLO macOS. Las voces del catálogo de CapCut son de ByteDance y solo existen dentro de la app: no
hay API pública, así que esto automatiza la interfaz. Es frágil por definición: depende del tamaño
de la ventana y de la versión de CapCut, y una actualización puede romperlo. El camino estable es
`voz.py --motor qwen` (local, Apache-2.0). Usa este solo cuando el guion pida específicamente la
voz viral de la app.

Lo que NO hace ni debe hacer: no clona la voz de ninguna persona real, no toca APIs no oficiales y
no usa la sesión ni las cookies de nadie. Solo pulsa botones de una app instalada.

Uso:
  uv run capcut_voz.py --preparar                      # una sola vez por tanda: deja CapCut listo
  uv run capcut_voz.py lineas.json carpeta [--velocidad 1.4] [--voz "Nombre de la voz del catálogo"]
  uv run capcut_voz.py --calibrar                      # captura de pantalla con las coordenadas marcadas

lineas.json: ["frase 1", "frase 2", ...]. Escribe l0.wav, l1.wav... y duraciones.json en la carpeta,
o sea el MISMO contrato que scripts/voz.py: narrar.py y el motor de edición los consumen sin cambios.

Requisitos del proyecto de CapCut (los explica --preparar, ver SKILL.md):
  - Un proyecto RECIÉN creado. Uno con cientos de generaciones deja de generar audio, en silencio.
  - Un único clip de texto en la pista de texto (la de más arriba) con la voz ya aplicada y generada
    una vez a mano.
Por cada línea el script pega el texto, vuelve a elegir la voz y pulsa "Generar contenido de voz"
(las versiones recientes quitaron la casilla "Actualizar la voz según el guion", así que no hay
regeneración automática). Cada generación añade una pista de audio nueva: da igual, el WAV se
recoge de textReading/.
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

# Carpeta de borradores de CapCut de escritorio en macOS (se puede mover con $CAPCUT_DRAFTS).
CAPCUT = Path(os.path.expanduser(os.environ.get(
    "CAPCUT_DRAFTS", "~/Movies/CapCut/User Data/Projects/com.lveditor.draft")))
# Solo se usa en avisos y diagnóstico: el script pulsa una posición fija de la cuadrícula, no busca
# la voz por nombre. Pásale el nombre real con --voz o con $REEL_FORGE_CAPCUT_VOZ para que los
# mensajes digan cuál se esperaba. El catálogo de CapCut cambia según país y versión de la app.
VOZ_DEFAULT = os.environ.get("REEL_FORGE_CAPCUT_VOZ", "la voz aplicada al clip de texto")
# Coordenadas en puntos lógicos con la ventana de CapCut en (0, 33) y tamaño 1728x999
# (pantalla de 1728x1117 puntos). Con otra pantalla o versión, recalibra con --calibrar.
VENTANA = {"pos": (0, 33), "size": (1728, 999)}
P = {
    "timeline": (700, 900),       # punto dentro de la línea de tiempo (para hacer scroll hasta arriba)
    "clip_texto": (450, 888),     # el clip de texto, cerca de su inicio (pista TI, la de más arriba)
    "tab_texto": (1141, 90),      # pestaña "Texto" del panel derecho
    "caja_texto": (1417, 197),    # caja donde se escribe el guion
    "tab_tts": (1398, 90),        # pestaña "Texto a voz"
    "chip_narracion": (1550, 138),  # chip de categoría "Narración" (lleva la lista a esa sección)
    "voz": (1380, 436),           # la voz dentro de la cuadrícula de "Narración" (4ª fila, 4ª col. en 7.5.0)
    "generar": (1634, 739),       # botón "Generar contenido de voz" (abajo a la derecha del panel)
}
# Recorte de silencios de las orillas + highpass suave (mismo FX "limpio" que voz.py). Sin reverb.
RECORTE = ("areverse,silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.08,areverse,"
           "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05")
FX = f"{RECORTE},highpass=f=60"


def sh(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def cliclick(*args):
    if not shutil.which("cliclick"):
        sys.exit("Falta cliclick: brew install cliclick")
    subprocess.run(["cliclick", *args], check=True)


def ventana():
    """Pone la ventana de CapCut en una posición y tamaño conocidos (las coordenadas dependen de eso)."""
    x, y = VENTANA["pos"]
    w, h = VENTANA["size"]
    for prop, val in (("position", f"{{{x}, {y}}}"), ("size", f"{{{w}, {h}}}")):
        sh("osascript", "-e",
           f'tell application "System Events" to tell process "CapCut" to set {prop} of window 1 to {val}')
    time.sleep(1)


def proyecto() -> Path:
    """Carpeta textReading del proyecto abierto (el borrador modificado más recientemente)."""
    drafts = [p for p in CAPCUT.glob("*/*") if p.is_dir() and (p / "draft_info.json").exists()]
    if not drafts:
        sys.exit(f"No encuentro proyectos de CapCut en {CAPCUT}")
    d = max(drafts, key=lambda p: p.stat().st_mtime)
    tr = d / "textReading"
    tr.mkdir(exist_ok=True)
    return tr


def scroll(x, y, clicks, n=1):
    """Rueda del ratón (cliclick no sabe hacer scroll)."""
    import Quartz
    Quartz.CGWarpMouseCursorPosition(Quartz.CGPointMake(float(x), float(y)))
    time.sleep(0.2)
    for _ in range(n):
        Quartz.CGEventPost(Quartz.kCGHIDEventTap,
                           Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, clicks))
        time.sleep(0.05)


def pon_texto(linea: str):
    """Pega la línea en el clip de texto, vuelve a elegir la voz y pulsa "Generar contenido de voz".

    Desde CapCut 7.5.0 el panel de Texto a voz ya NO trae la casilla "Actualizar la voz según el
    guion", así que cambiar el texto y deseleccionar no regenera nada: hay que pulsar Generar cada
    vez (y volver a hacer clic en la voz, porque el botón se queda deshabilitado si no).
    """
    def clic(k, espera=1.5):
        cliclick(f"c:{P[k][0]},{P[k][1]}")
        time.sleep(espera)

    subprocess.run(["pbcopy"], input=linea, text=True, check=True)
    # sube la línea de tiempo del todo: la pista TI queda siempre arriba. Hace falta mucho scroll
    # porque cada generación añade una pista de audio nueva y la lista crece durante la tanda.
    scroll(*P["timeline"], 5, 30)
    time.sleep(0.6)
    clic("clip_texto")             # selecciona el clip de texto
    clic("tab_texto")
    clic("caja_texto", 0.8)
    cliclick("kd:cmd", "t:a", "ku:cmd"); time.sleep(0.6)
    cliclick("kd:cmd", "t:v", "ku:cmd"); time.sleep(1.0)
    clic("tab_tts", 2.0)
    clic("chip_narracion", 2.0)    # la lista vuelve siempre al principio de "Narración"
    clic("voz", 2.5)               # reactiva el botón Generar
    clic("generar", 0.5)


def espera_wav(tr: Path, previos: set, timeout=90):
    """Devuelve el WAV nuevo, o None si CapCut no generó nada en el plazo."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(1.5)
        nuevos = {p for p in tr.glob("*.wav")} - previos
        if nuevos:
            p = max(nuevos, key=lambda q: q.stat().st_mtime)
            tam = -1
            while tam != p.stat().st_size:   # espera a que termine de escribirse
                tam = p.stat().st_size
                time.sleep(0.8)
            return p
    return None


def estado(draft: Path) -> dict:
    """Lee draft_info.json: qué texto tiene el clip, si la casilla sigue activa y qué voz usa.

    Sirve para distinguir los dos fallos posibles cuando no sale audio:
      - el texto del clip NO cambió  -> los clics caen mal, hay que recalibrar
      - el texto SÍ cambió           -> CapCut recibió el guion y se negó a generar
    """
    f = draft / "draft_info.json"
    try:
        d = json.loads(f.read_text())
    except Exception as e:
        return {"error": str(e)}
    textos = [json.loads(t["content"]).get("text", "") for t in d.get("materials", {}).get("texts", [])]
    auto = [t.get("tts_auto_update") for t in d.get("materials", {}).get("texts", [])]
    voces = [a.get("tone_effect_name", "") for a in d.get("materials", {}).get("audios", [])]
    return {"texto": textos[0] if textos else None, "auto_update": auto[0] if auto else None,
            "voces": voces, "guardado": f.stat().st_mtime}


def diagnostico(draft: Path, linea: str, voz: str = VOZ_DEFAULT) -> str:
    e = estado(draft)
    if e.get("error"):
        return f"no pude leer draft_info.json ({e['error']})"
    llego = (e.get("texto") or "").strip() == linea.strip()
    if not llego:
        return ("el texto NO llegó al clip (el clip dice "
                f"{(e.get('texto') or '')[:40]!r}): los clics caen mal, corre --calibrar y ajusta el dict P")
    if not any(voz in v for v in e.get("voces") or []):
        return (f"el texto sí llegó, pero ningún clip de audio usa {voz}: el clic en la cuadrícula de "
                "voces cayó fuera. Corre --calibrar y ajusta P['chip_narracion'] y P['voz'].")
    return (f"el texto sí llegó y la voz es {voz}, pero CapCut no escribió audio. Suele ser que el "
            "proyecto se quedó en mal estado (pasa después de muchas regeneraciones): crea un proyecto "
            "nuevo con --preparar y vuelve a intentarlo. Si tampoco, prueba a mano con una voz SIN rombo "
            "(p. ej. 'Sneaky Guy'): si esa sí genera, el problema es sólo con las voces premium.")


def duracion(f: Path) -> float:
    r = sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f))
    return round(float(r.stdout), 3)


def loudnorm_2p(src: Path, dst: Path, velocidad: float):
    """atempo (mantiene el tono) + recorte de silencios + loudnorm de 2 pasadas a -16 LUFS."""
    pre = f"atempo={velocidad:.4f},{FX}" if velocidad != 1.0 else FX
    ln = "loudnorm=I=-16:TP=-1.5:LRA=11"
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(src), "-af", f"{pre},{ln}:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True, check=True)
    m = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
    medido = (f"{ln}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
              f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-af", f"{pre},{medido}",
                    "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)], check=True)


def preparar():
    print("Pasos manuales (una sola vez por tanda, ~1 minuto):\n"
          "  1. CapCut → Archivo → Nuevo proyecto. SIEMPRE uno nuevo: un proyecto con cientos de\n"
          "     regeneraciones deja de generar audio (falla en silencio, sin mensaje).\n"
          "  2. Texto → Agregar texto → pasa el ratón por 'Texto predeterminado' y pulsa su botón +.\n"
          "  3. Panel derecho → pestaña 'Texto' → pega ahí la primera línea (Cmd+V; NO escribas con\n"
          "     AppleScript: se come los espacios y los acentos).\n"
          "  4. Pestaña 'Texto a voz' → chip 'Narración' → clic en la voz → 'Generar contenido de voz'.\n"
          "     Debe aparecer una pista de audio 'Texto a voz <la voz>'.\n"
          "  5. Arrastra hacia abajo la línea que separa el reproductor de la línea de tiempo hasta que\n"
          "     el botón 'Generar contenido de voz' quede a la altura que dice P['generar'] (--calibrar).\n"
          "Luego: uv run capcut_voz.py lineas.json carpeta/")
    sh("open", "-a", "CapCut")
    ventana()


def cortar(src: Path, out: Path, n: int, velocidad: float, umbral="-38dB", minimo=0.45):
    """Plan B: un solo audio con todo el guion, cortado por silencios en l0.wav, l1.wav...

    Útil si el ciclo de la app falla: pega el guion entero (una línea por párrafo), genera una vez
    y corta aquí. Ajusta --umbral/--minimo si sale un número de trozos distinto al de líneas.
    """
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(src), "-af",
                        f"silencedetect=noise={umbral}:d={minimo}", "-f", "null", "-"],
                       capture_output=True, text=True, check=True)
    ini, fin = [], []
    for ln in r.stderr.splitlines():
        if "silence_start:" in ln:
            fin.append(float(ln.split("silence_start:")[1].split()[0]))
        elif "silence_end:" in ln:
            ini.append(float(ln.split("silence_end:")[1].split("|")[0]))
    total = duracion(src)
    cortes = list(zip([0.0] + ini, fin + [total]))
    cortes = [(a, b) for a, b in cortes if b - a > 0.3]
    print(f"{len(cortes)} trozos detectados (esperabas {n})")
    out.mkdir(parents=True, exist_ok=True)
    dur = {}
    for i, (a, b) in enumerate(cortes):
        trozo = out / f"l{i}.crudo.wav"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-ss", f"{a:.3f}",
                        "-to", f"{b:.3f}", "-c:a", "pcm_s16le", str(trozo)], check=True)
        loudnorm_2p(trozo, out / f"l{i}.wav", velocidad)
        trozo.unlink()
        dur[f"l{i}"] = duracion(out / f"l{i}.wav")
        print(f"l{i} {dur[f'l{i}']}s")
    json.dump(dur, open(out / "duraciones.json", "w"), ensure_ascii=False, indent=1)


def calibrar():
    ventana()
    out = Path(tempfile.gettempdir()) / "capcut-calibrar.png"
    sh("screencapture", "-x", str(out))
    marcas = ",".join(f"{k}=({v[0]},{v[1]})" for k, v in P.items())
    print(f"Captura en {out}. Coordenadas actuales (puntos lógicos): {marcas}\n"
          "Ábrela y comprueba que cada punto cae donde dice. Si no, ajusta el dict P de este script.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lineas", nargs="?")
    ap.add_argument("salida", nargs="?")
    ap.add_argument("--velocidad", type=float, default=1.4, help="1.4 es el ritmo del trend (default)")
    ap.add_argument("--voz", default=VOZ_DEFAULT, help="nombre de la voz en el catálogo (solo para avisos y diagnóstico)")
    ap.add_argument("--preparar", action="store_true")
    ap.add_argument("--calibrar", action="store_true")
    ap.add_argument("--crudo", action="store_true", help="guarda también el wav tal cual sale de CapCut")
    ap.add_argument("--cortar", metavar="AUDIO.WAV",
                    help="plan B: corta por silencios un audio con todo el guion (usa 'salida' como carpeta)")
    ap.add_argument("--umbral", default="-38dB")
    ap.add_argument("--minimo", type=float, default=0.45)
    a = ap.parse_args()
    if a.preparar:
        return preparar()
    if a.calibrar:
        return calibrar()
    if a.cortar:
        if not a.salida:
            ap.error("con --cortar hace falta la carpeta de salida")
        n = len(json.load(open(a.lineas))) if a.lineas else 0
        return cortar(Path(a.cortar), Path(a.salida), n, a.velocidad, a.umbral, a.minimo)
    if not a.lineas or not a.salida:
        ap.error("faltan lineas.json y carpeta de salida")

    lineas = json.load(open(a.lineas))
    out = Path(a.salida)
    out.mkdir(parents=True, exist_ok=True)
    tr = proyecto()
    e = estado(tr.parent)
    print(f"Proyecto de CapCut: {tr.parent}\n  clip de texto: {(e.get('texto') or '')[:50]!r} · "
          f"voces en la línea de tiempo: {sorted(set(e.get('voces') or []))}")
    if len(e.get("voces") or []) > 60:
        print("  ⚠️  este proyecto ya lleva muchísimas generaciones; si empieza a fallar, crea uno nuevo")
    if not any(a.voz in v for v in e.get("voces") or []):
        print(f"  ⚠️  ningún clip de audio usa {a.voz}: vuelve a aplicar la voz (ver --preparar)")
    sh("open", "-a", "CapCut")
    time.sleep(2)
    ventana()

    dur = {}
    for i, linea in enumerate(lineas):
        final = out / f"l{i}.wav"
        if final.exists():   # reanudar: no regastes cuota en lo que ya está hecho
            dur[f"l{i}"] = duracion(final)
            print(f"l{i} {dur[f'l{i}']}s  ·  (ya estaba)", flush=True)
            continue
        crudo = None
        for intento in (1, 2):
            previos = set(tr.glob("*.wav"))
            pon_texto(linea)
            crudo = espera_wav(tr, previos)
            if crudo:
                break
            print(f"l{i}: sin audio en el 1er intento, reintento…", flush=True)
            time.sleep(3)
        if not crudo:
            # a propósito NO se escribe duraciones.json: es la señal de "carpeta incompleta"
            # que usa narrar.py para volver a llamar a este script.
            sys.exit(f"CapCut no generó audio para l{i} ({linea[:50]!r}).\n  Diagnóstico: "
                     f"{diagnostico(tr.parent, linea, a.voz)}\n  Lo generado hasta aquí queda en {out} "
                     f"(al volver a correrlo se reanuda desde l{i}).")
        if a.crudo:
            shutil.copy2(crudo, out / f"l{i}.capcut.wav")
        loudnorm_2p(crudo, final, a.velocidad)
        dur[f"l{i}"] = duracion(final)
        print(f"l{i} {dur[f'l{i}']}s  ·  {linea[:60]}", flush=True)
    json.dump(dur, open(out / "duraciones.json", "w"), ensure_ascii=False, indent=1)
    print(f"\n{len(lineas)} líneas en {out} (+ duraciones.json)")


if __name__ == "__main__":
    main()
