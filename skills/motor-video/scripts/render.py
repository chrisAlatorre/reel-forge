# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = [
#   "numpy<2.3",
#   "opencv-contrib-python<5",
#   "pillow",
#   "pillow-heif",
#   "mediapipe==0.10.21",   # solo para `behind` y `cutout`
#   "telemetry-parser",     # solo para segmentos 360 (`r360`)
# ]
# ///
"""Motor de video: arma un vertical 9:16 (1080x1920) a partir de un spec JSON.

    uv run scripts/render.py SPEC.json [--out ruta/salida.mp4]

Todo se renderiza cuadro por cuadro en numpy y se codifica con ffmpeg (hace falta
`ffmpeg` y `ffprobe` en el PATH). El formato completo del spec está en SKILL.md.

Resumen del spec:
{
  "out": "proyecto/video.mp4",          # relativo a $REEL_FORGE_SALIDA, o ruta absoluta
  "fps": 30, "crf": 22,
  "look": "film" | "teal" | "clean", "grain": 0.008,
  "fade_out": 0.4, "audio_fade_out": 1.2,
  "bpm": 123.0, "beat0": 0.0,
  "segments": [
    {"src": "foto.jpg", "beats": 2, "focus": [0.5, 0.4], "kb": 0.06, "punch": 0.10},
    {"src": "clip.mov", "dur": 2.4, "start": 3.0, "speed": 0.5, "flash": true}
  ],
  "captions": [{"t0": 0.0, "t1": 2.0, "text": "...", "style": "clean", "pos": "low"}],
  "audio": [{"src": "voz.wav", "at": 1.2, "gain": 1.0}],
  "preview_audio": {"src": "cancion.m4a", "offset": 0, "gain": 1.0}
}

El motor genera `video.mp4` (limpio, sin música con copyright) y, si hay
`preview_audio`, también `video-preview.mp4` solo para revisar.
"""
import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Los alfabetos con marcas combinadas (tailandés, árabe, índicos) necesitan raqm en Pillow,
# que carga libfribidi en tiempo de ejecución; sin él salen círculos punteados en las vocales.
# dyld solo lee la ruta al arrancar el proceso, así que hay que re-ejecutar. En Linux la
# librería suele estar en el path del sistema y esto no hace nada.
for _dir in ("/opt/homebrew/lib", "/usr/local/lib"):
    if os.path.exists(_dir + "/libfribidi.0.dylib") and _dir not in os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", ""):
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = _dir + ":" + os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        os.execv(sys.executable, [sys.executable] + sys.argv)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps  # noqa: E402

import config  # noqa: E402
import efectos  # noqa: E402

try:
    import pillow_heif
    pillow_heif.register_heif_opener()   # para .heic del iPhone; ffmpeg NO abre HEIC
except ImportError:
    pass

W, H, MARGEN, SEGURA = config.W, config.H, config.MARGEN, config.SEGURA


# ------------------------------------------------------------ material

def _ffprobe(src):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=color_transfer,r_frame_rate:format=duration", "-of", "json", src],
                       capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    st = d["streams"][0]
    num, den = st.get("r_frame_rate", "30/1").split("/")
    return {"hdr": st.get("color_transfer") in ("arib-std-b67", "smpte2084"),
            "fps": float(num) / float(den), "dur": float(d["format"]["duration"])}


def cubrir(img, w, h, focus=(0.5, 0.5)):
    """Escala para cubrir w x h y recorta centrando en `focus` (0-1 sobre la imagen ya escalada)."""
    ih, iw = img.shape[:2]
    s = max(w / iw, h / ih)
    nw, nh = max(w, round(iw * s)), max(h, round(ih * s))
    img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    x = int(np.clip(focus[0] * nw - w / 2, 0, nw - w))
    y = int(np.clip(focus[1] * nh - h / 2, 0, nh - h))
    return img[y:y + h, x:x + w]


def ajustar_con_fondo(img, w, h, y_rel=0.45):
    """`fit: "blur"`: encaja la imagen completa y rellena con una versión desenfocada de sí misma."""
    fondo = cubrir(img, w, h)
    fondo = cv2.GaussianBlur(cv2.resize(fondo, (w // 8, h // 8)), (0, 0), 3)
    fondo = (cv2.resize(fondo, (w, h)) * 0.72).astype(np.uint8)
    ih, iw = img.shape[:2]
    s = min(w / iw, h / ih)
    fg = cv2.resize(img, (round(iw * s), round(ih * s)), interpolation=cv2.INTER_AREA)
    y = int(np.clip(h * y_rel - fg.shape[0] / 2, 0, h - fg.shape[0]))
    x = (w - fg.shape[1]) // 2
    fondo[y:y + fg.shape[0], x:x + fg.shape[1]] = fg
    return fondo


def cargar_foto(src):
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    return np.asarray(im)


def frames_video(src, start, n, speed, fps):
    """Genera n cuadros RGB del clip, ya en SDR, con rotación aplicada y a la resolución de trabajo."""
    info = _ffprobe(src)
    vf = []
    if info["hdr"]:
        vf.append("colorspace=all=bt709:iall=bt2020:itrc=bt2020-10:format=yuv420p")
    if speed != 1:
        vf.append(f"setpts=PTS/{speed}")
    vf.append(f"fps={fps}")
    vf.append("scale='if(gt(iw,ih),2400,-2)':'if(gt(iw,ih),-2,2400)'")
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-i", src, "-vf", ",".join(vf),
           "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    raw = p.stdout.read()
    p.wait()
    # Las dimensiones reales tras la rotación del contenedor y el escalado solo se saben
    # decodificando: se pide un cuadro como PNG en vez de calcularlas a mano.
    probe = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-i", src,
                            "-vf", ",".join(vf), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                           capture_output=True, check=True).stdout
    import io
    w0, h0 = Image.open(io.BytesIO(probe)).size
    tam = w0 * h0 * 3
    cuadros = [np.frombuffer(raw[i * tam:(i + 1) * tam], np.uint8).reshape(h0, w0, 3)
               for i in range(len(raw) // tam)]
    if not cuadros:
        raise RuntimeError(f"Sin cuadros de {src} desde {start}s")
    while len(cuadros) < n:  # clip más corto de lo pedido: congela el último cuadro
        cuadros.append(cuadros[-1])
    return cuadros[:n]


# ------------------------------------------------------------ look de color

def _curva(puntos):
    x, y = zip(*puntos)
    return np.clip(np.interp(np.arange(256), x, y), 0, 255).astype(np.uint8)


LOOKS = {
    # Película cálida tipo negativo de color: negros levantados, luces cálidas, sombras verde-azul
    "film": {"r": _curva([(0, 14), (64, 66), (128, 136), (192, 204), (255, 250)]),
             "g": _curva([(0, 12), (64, 64), (128, 131), (192, 196), (255, 244)]),
             "b": _curva([(0, 20), (64, 64), (128, 122), (192, 182), (255, 232)]),
             "sat": 0.92, "vig": 0.28},
    # Teal & orange cinematográfico
    "teal": {"r": _curva([(0, 4), (64, 58), (128, 134), (192, 206), (255, 255)]),
             "g": _curva([(0, 8), (64, 64), (128, 128), (192, 194), (255, 250)]),
             "b": _curva([(0, 22), (64, 76), (128, 124), (192, 176), (255, 236)]),
             "sat": 1.05, "vig": 0.30},
    # Sin corrección: color real, viñeta mínima. Lo mejor para blancos y templos claros.
    "clean": {"r": _curva([(0, 0), (255, 255)]), "g": _curva([(0, 0), (255, 255)]),
              "b": _curva([(0, 0), (255, 255)]), "sat": 1.05, "vig": 0.12},
}


def vineta(fuerza):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
    return (1 - fuerza * np.clip((r - 0.45) / 0.55, 0, 1) ** 1.6)[..., None].astype(np.float32)


def aplicar_look(img, look, vig, grano, rng):
    out = np.dstack([cv2.LUT(img[..., i], look[c]) for i, c in enumerate("rgb")]).astype(np.float32)
    if look["sat"] != 1:
        gris = out.mean(axis=2, keepdims=True)
        out = gris + (out - gris) * look["sat"]
    out *= vig
    if grano > 0:
        # Grano FINO, a resolución completa y solo en luminancia. Generarlo a media resolución
        # y escalarlo se ve sucio, como ruido de compresión. Mantener grain <= 0.012.
        ruido = rng.standard_normal((H, W, 1)).astype(np.float32)
        luz = out.mean(axis=2, keepdims=True) / 255
        out += ruido * grano * 255 * (0.35 + 0.65 * (1 - np.abs(luz * 2 - 1)))  # menos en negros y blancos
    return np.clip(out, 0, 255).astype(np.uint8)


# ------------------------------------------------------------ textos

TAM_DEFAULT = {"bold": 74, "serif": 96, "box": 58, "clean": 64, "yellow": 96, "pin": 46}

_THAI = ("฀", "๿")
_CJK = ("　", "鿿")


def fuente(estilo, tam, texto=""):
    """Tipografía del estilo, con repuesto automático si el texto trae tailandés o CJK."""
    if any(_THAI[0] <= ch <= _THAI[1] for ch in texto):
        alt = config.fuente_alfabeto("thai")
        if alt:
            return ImageFont.truetype(str(alt), tam, index=0 if estilo == "serif" else 1)
    if any(_CJK[0] <= ch <= _CJK[1] for ch in texto):
        alt = config.fuente_alfabeto("cjk")
        if alt:
            return ImageFont.truetype(str(alt), tam, index=1)
    if estilo == "serif":
        return ImageFont.truetype(str(config.exigir(config.FUENTE_SERIF, "la tipografía serif")), tam)
    f = ImageFont.truetype(str(config.exigir(config.FUENTE_SANS, "la tipografía sans")), tam)
    try:
        f.set_variation_by_axes([700 if estilo in ("clean", "pin") else 850])
    except Exception:
        pass   # la sans no es variable: se usa tal cual
    return f


def _envolver(draw, texto, f, ancho):
    """Envuelve por ancho RESPETANDO los \\n que ya traiga el texto.

    Ojo: un \\n a mano no garantiza el corte, porque cada renglón se sigue envolviendo
    por ancho. Si el renglón no cabe, se parte igual y suelta palabras huérfanas.
    """
    lineas = []
    for parrafo in texto.split("\n"):
        actual = ""
        for palabra in parrafo.split():
            prueba = (actual + " " + palabra).strip()
            if draw.textlength(prueba, font=f) <= ancho or not actual:
                actual = prueba
            else:
                lineas.append(actual)
                actual = palabra
        lineas.append(actual)
    return "\n".join(lineas)


def render_texto(texto, estilo="clean", tam=None, color=None):
    tam = tam or TAM_DEFAULT[estilo]
    if estilo == "pin":
        return _render_pin(texto, tam)
    f = fuente(estilo, tam, texto)
    ancho = W - 2 * 150  # margen simétrico: así el texto centrado nunca invade la barra de botones
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    txt = _envolver(tmp, texto, f, ancho)
    espaciado = int(tam * 0.18)
    bb = tmp.multiline_textbbox((0, 0), txt, font=f, align="center", spacing=espaciado, stroke_width=6)
    tw, th = int(bb[2] - bb[0] + 100), int(bb[3] - bb[1] + 90)
    im = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pos = (50 - bb[0], 45 - bb[1])
    if estilo == "box":
        # Caja estilo "texto clásico" de TikTok. `color` cambia el fondo; la tinta se elige por luminancia.
        fondo = tuple(color or (255, 255, 255))
        lum = 0.299 * fondo[0] + 0.587 * fondo[1] + 0.114 * fondo[2]
        tinta = (12, 12, 12, 255) if lum > 140 else (255, 255, 255, 255)
        d.rounded_rectangle([0, 0, tw - 1, th - 1], radius=22, fill=fondo + (245,))
        d.multiline_text(pos, txt, font=f, fill=tinta, align="center", spacing=espaciado)
    elif estilo == "serif":
        # Halo oscuro amplio + sombra cercana: el serif delgado se pierde sobre cielos claros
        for alfa, desenfoque, grosor in ((150, 22, 10), (215, 5, 2)):
            sombra = Image.new("RGBA", im.size, (0, 0, 0, 0))
            ImageDraw.Draw(sombra).multiline_text((pos[0], pos[1] + 2), txt, font=f, fill=(0, 0, 0, alfa),
                                                  align="center", spacing=espaciado,
                                                  stroke_width=grosor, stroke_fill=(0, 0, 0, alfa))
            im = Image.alpha_composite(im, sombra.filter(ImageFilter.GaussianBlur(desenfoque)))
        ImageDraw.Draw(im).multiline_text(pos, txt, font=f, fill=(255, 250, 240, 255), align="center",
                                          spacing=espaciado)
    elif estilo == "yellow":
        # Palabra clave (lugar, precio) en amarillo grueso con sombra: el look de las guías de ruta
        sombra = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(sombra).multiline_text((pos[0] + 3, pos[1] + 5), txt, font=f, fill=(0, 0, 0, 170),
                                              align="center", spacing=espaciado, stroke_width=5,
                                              stroke_fill=(0, 0, 0, 170))
        im = Image.alpha_composite(im, sombra.filter(ImageFilter.GaussianBlur(6)))
        ImageDraw.Draw(im).multiline_text(pos, txt, font=f, fill=tuple(color or (255, 212, 0)) + (255,),
                                          align="center", spacing=espaciado, stroke_width=3,
                                          stroke_fill=(40, 25, 0, 255))
    elif estilo == "clean":
        # Minimalismo: sans blanca, sombra suave, sin contorno grueso. El default para subtítulos.
        sombra = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(sombra).multiline_text((pos[0], pos[1] + 3), txt, font=f, fill=(0, 0, 0, 200),
                                              align="center", spacing=espaciado, stroke_width=4,
                                              stroke_fill=(0, 0, 0, 200))
        im = Image.alpha_composite(im, sombra.filter(ImageFilter.GaussianBlur(9)))
        ImageDraw.Draw(im).multiline_text(pos, txt, font=f, fill=(255, 255, 255, 255), align="center",
                                          spacing=espaciado)
    else:  # "bold": contorno negro grueso. Legible siempre, pero se ve a editor de hace años.
        d.multiline_text(pos, txt, font=f, fill=(255, 255, 255, 255), align="center",
                         spacing=espaciado, stroke_width=7, stroke_fill=(0, 0, 0, 255))
    return np.asarray(im).astype(np.float32) / 255


def _render_pin(texto, tam):
    """Etiqueta fija de lugar con pin rojo ("Día 4 · Ciudad"). No envuelve: una sola línea corta."""
    f = fuente("pin", tam, texto)
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bb = tmp.textbbox((0, 0), texto, font=f)
    tw, th = int(bb[2] - bb[0]), int(bb[3] - bb[1])
    r = int(tam * 0.36)
    W0, H0 = tw + r * 2 + 70, th + 40
    im = Image.new("RGBA", (W0, H0), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, W0 - 1, H0 - 1], radius=H0 // 2, fill=(15, 15, 15, 150))
    cx, cy = 22 + r, H0 // 2 - 4
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(235, 50, 50, 255))
    d.polygon([(cx - r * 0.7, cy + r * 0.5), (cx + r * 0.7, cy + r * 0.5), (cx, cy + r * 1.7)],
              fill=(235, 50, 50, 255))
    d.ellipse([cx - r * 0.38, cy - r * 0.38, cx + r * 0.38, cy + r * 0.38], fill=(255, 255, 255, 255))
    d.text((cx + r + 16 - bb[0], (H0 - th) // 2 - bb[1]), texto, font=f, fill=(255, 255, 255, 255))
    return np.asarray(im).astype(np.float32) / 255


def preparar_captions(caps):
    """Expande los captions en piezas ya rasterizadas con su ventana de tiempo."""
    piezas = []
    for c in caps:
        estilo, pos = c.get("style", "clean"), c.get("pos", "low")
        comun = {"pos": pos, "dx": c.get("dx", 0), "dy": c.get("dy", 0)}
        if c.get("words"):
            # Subtítulo palabra por palabra en grupos de hasta 3, con tiempo proporcional a las letras
            grupos, g = [], []
            for p in c["text"].split():
                g.append(p)
                if len(g) == 3 or p.endswith((",", ".", "…", "?", "!")):
                    grupos.append(" ".join(g))
                    g = []
            if g:
                grupos.append(" ".join(g))
            total = sum(len(x) + 2 for x in grupos)
            t = c["t0"]
            for x in grupos:
                d = (c["t1"] - c["t0"]) * (len(x) + 2) / total
                piezas.append({"t0": t, "t1": t + d, "pop": True,
                               "img": render_texto(x, estilo, c.get("size"), c.get("color")), **comun})
                t += d
        else:
            piezas.append({"t0": c["t0"], "t1": c["t1"], "pop": c.get("pop", True),
                           "img": render_texto(c["text"], estilo, c.get("size"), c.get("color")), **comun})
    return piezas


def pegar_texto(frame, pieza, t):
    img = pieza["img"]
    edad = t - pieza["t0"]
    if pieza["pop"] and edad < 0.12:
        e = edad / 0.12
        s = 0.86 + 0.14 * (1 - (1 - e) ** 3)
        img = cv2.resize(img, (max(2, int(img.shape[1] * s)), max(2, int(img.shape[0] * s))))
    alfa_global = min(1.0, edad / 0.06) * min(1.0, (pieza["t1"] - t) / 0.06)
    h, w = img.shape[:2]
    # Centrado real en la PANTALLA (cx = W/2), no en la zona segura (que es asimétrica:
    # 60 px a la izquierda y 180 a la derecha). Centrar en la zona segura deja los textos
    # visiblemente cargados a la izquierda.
    y_por_pos = {"top": SEGURA["top"] + 40, "topleft": SEGURA["top"] + 20, "upper": H * 0.30 - h / 2,
                 "center": (H - h) / 2 - 60, "low": H - SEGURA["bottom"] - h - 20,
                 "lowleft": H - SEGURA["bottom"] - h - 20, "lowright": H - SEGURA["bottom"] - h - 20}
    if pieza["pos"] not in y_por_pos:
        raise SystemExit(f"`pos` desconocida: {pieza['pos']}. Opciones: {', '.join(y_por_pos)}")
    x0, y0 = int(W / 2 - w / 2), int(y_por_pos[pieza["pos"]])
    if pieza["pos"] == "topleft":
        x0 = SEGURA["left"]
    elif pieza["pos"] == "lowleft":
        x0 = SEGURA["left"] - 40          # el PNG trae 50 px de aire a cada lado
    elif pieza["pos"] == "lowright":
        x0 = W - SEGURA["right"] - w + 40
    x0 += int(pieza.get("dx", 0))
    y0 += int(pieza.get("dy", 0))
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x0 + w), min(H, y0 + h)
    sub = img[: y1 - y0, : x1 - x0]
    a = sub[..., 3:4] * alfa_global
    zona = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = (zona * (1 - a) + sub[..., :3] * 255 * a).astype(np.uint8)


# ------------------------------------------------------------ armado

def _motor_360():
    """Importa `reencuadre360` del skill hermano `video-360` (o de $REEL_FORGE_360_SCRIPTS)."""
    candidatas = [os.environ.get("REEL_FORGE_360_SCRIPTS"),
                  Path(__file__).resolve().parent,
                  Path(__file__).resolve().parent.parent.parent / "video-360" / "scripts"]
    for c in candidatas:
        if c and Path(c).is_dir() and (Path(c) / "reencuadre360.py").exists():
            if str(c) not in sys.path:
                sys.path.insert(0, str(c))
            import reencuadre360
            return reencuadre360
    raise SystemExit("Un segmento pide `r360` pero no encuentro `reencuadre360.py` (skill `video-360`).\n"
                     "Quita el `r360` del segmento o apunta $REEL_FORGE_360_SCRIPTS a esa carpeta.")


def _base_segmento(s, n, fps, src, focus):
    """Cuadros del segmento a la resolución de trabajo (W*MARGEN x H*MARGEN). None = mapa."""
    WM, HM = int(W * MARGEN), int(H * MARGEN)
    if "map" in s:
        return None
    if s.get("r360"):
        reencuadre360 = _motor_360()
        r = s["r360"]
        r = json.loads(config.ruta(r).read_text()) if isinstance(r, str) else dict(r)
        r.setdefault("src", src)
        r.setdefault("inicio", s.get("start", 0))
        return list(reencuadre360.cuadros(r, n, fps, WM, HM))
    if src.lower().endswith((".mov", ".mp4", ".m4v", ".mkv", ".insv")):
        crudos = frames_video(src, s.get("start", 0), n, s.get("speed", 1), fps)
        if s.get("fit") == "blur":
            return [ajustar_con_fondo(c, WM, HM) for c in crudos]
        return [cubrir(c, WM, HM, focus) for c in crudos]
    foto = cargar_foto(src)
    unica = ajustar_con_fondo(foto, WM, HM) if s.get("fit") == "blur" else cubrir(foto, WM, HM, focus)
    return [unica] * n


def main():
    ap = argparse.ArgumentParser(description="Motor de video vertical 9:16")
    ap.add_argument("spec", help="archivo JSON con el spec")
    ap.add_argument("--out", help="sobrescribe el `out` del spec")
    args = ap.parse_args()

    with open(args.spec) as fh:
        spec = json.load(fh)
    fps = spec.get("fps", config.FPS)
    look = LOOKS[spec.get("look", "film")]
    vig = vineta(look["vig"])
    grano = min(spec.get("grain", 0.008), config.GRANO_MAX)
    rng = np.random.default_rng(7)
    beat = 60 / spec["bpm"] if spec.get("bpm") else None

    # Tiempos de cada segmento sobre una rejilla absoluta, para no acumular desfase con el beat
    t = spec.get("beat0", 0.0)
    cortes = []
    for s in spec["segments"]:
        if "beats" in s and beat is None:
            raise SystemExit("Un segmento usa `beats` pero el spec no trae `bpm`.")
        t += s["beats"] * beat if "beats" in s else s["dur"]
        cortes.append(t)
    total = cortes[-1]
    piezas = preparar_captions(spec.get("captions", []))

    out = config.resolver_salida(args.out or spec["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    mudo = out.with_name(out.stem + ".video.mp4")
    enc = subprocess.Popen(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                            "-crf", str(spec.get("crf", 22)),
                            "-pix_fmt", "yuv420p", str(mudo)], stdin=subprocess.PIPE)
    inicio = spec.get("beat0", 0.0)
    for s, fin in zip(spec["segments"], cortes):
        n = round(fin * fps) - round(inicio * fps)
        src = str(config.ruta(s["src"])) if s.get("src") else ""
        focus = s.get("focus", [0.5, 0.5])
        mapa = efectos.Mapa(s["map"], fuente("bold", 54)) if "map" in s else None
        base = _base_segmento(s, n, fps, src, focus)
        if base is not None and s.get("stutter"):
            k = int(s["stutter"])  # repite cada cuadro k veces: efecto de pocos fps al caminar
            base = [base[(i // k) * k] for i in range(len(base))]
        if base is not None and s.get("freeze"):
            base = [base[0]] * n
        titulo = None
        if s.get("behind"):
            bh = s["behind"]
            tam = bh.get("size", 230)
            while True:  # bajar el tamaño hasta que quepa a lo ancho
                titulo = efectos.render_titulo(bh["text"], fuente(bh.get("style", "bold"), tam, bh["text"]),
                                               bh.get("color", [255, 255, 255]))
                if titulo.shape[1] <= W * 0.94 or tam < 60:
                    break
                tam = int(tam * 0.93)
        fichas = None
        if s.get("cutout"):
            fichas = [efectos.ficha(x, fuente("bold", 44, x)) for x in s["cutout"].get("lines", [])]
        mascaras = {}   # caché de una sola entrada: en fotos el cuadro base se repite
        kb, punch = s.get("kb", 0.05), s.get("punch", 0.0)
        m = None
        for i, b in enumerate(base if base is not None else [None] * n):
            tg = (round(inicio * fps) + i) / fps
            if b is None:
                frame = mapa.frame(i / fps, n / fps)
                frame = aplicar_look(frame, LOOKS["clean"], vig, 0, rng)
            else:
                # zoom: Ken Burns lento (kb) y "punch" de entrada que se asienta con ease-out
                z = 1 + kb * (i / max(1, n - 1))
                if punch:
                    e = min(1.0, (i / fps) / 0.22)
                    z += punch * (1 - e) ** 3
                cw, ch = int(W * MARGEN) / z, int(H * MARGEN) / z
                x0 = (int(W * MARGEN) - cw) / 2 + (s.get("drift", [0, 0])[0] * int(W * MARGEN) * i / max(1, n))
                y0 = (int(H * MARGEN) - ch) / 2 + (s.get("drift", [0, 0])[1] * int(H * MARGEN) * i / max(1, n))
                M = np.float32([[W / cw, 0, -x0 * W / cw], [0, H / ch, -y0 * H / ch]])
                frame = cv2.warpAffine(b, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                if titulo is not None or fichas is not None:
                    # la máscara se calcula sobre la base y se deforma igual que la imagen
                    if id(b) not in mascaras:
                        mascaras = {id(b): efectos.segmentador().mascara(b)}
                    m = cv2.warpAffine(mascaras[id(b)], M, (W, H), flags=cv2.INTER_LINEAR)
                frame = aplicar_look(frame, look, vig, grano, rng)
                if titulo is not None and i / fps >= s["behind"].get("at", 0.0):
                    frame = efectos.texto_detras(frame, m, titulo, i / fps - s["behind"].get("at", 0.0),
                                                 s["behind"].get("y", 0.3))
                if fichas is not None:
                    frame = efectos.presentacion(frame, m, i / fps, n / fps, fichas, y_rel=s["cutout"].get("y", 0.62))
                if s.get("flash") and i < 3:
                    a = [0.85, 0.45, 0.15][i]
                    frame = (frame * (1 - a) + 255 * a).astype(np.uint8)
            for p in piezas:
                if p["t0"] <= tg < p["t1"]:
                    pegar_texto(frame, p, tg)
            fo = spec.get("fade_out", 0)
            if fo and tg > total - fo:
                frame = (frame * max(0.0, (total - tg) / fo)).astype(np.uint8)
            enc.stdin.write(np.ascontiguousarray(frame).tobytes())
        inicio = fin
        print(f"  {Path(src).name or 'mapa'}: {n} cuadros", flush=True)
    enc.stdin.close()
    enc.wait()

    # "audio_fade_out": segundos de salida al final (default 1.2; 0 para loops sin costura).
    # El limitador evita que la suma de pistas sature: una mezcla con música encima del audio
    # real llega fácil a +5 dBTP sin que nada avise.
    afo = float(spec.get("audio_fade_out", 1.2))
    fin_audio = (f",afade=t=out:st={max(0, total - afo)}:d={afo}" if afo > 0 else "") + ",alimiter=limit=0.89:level=false"

    def mezclar(destino, pistas):
        if not pistas:
            if destino == out:
                os.replace(mudo, destino)
            else:
                subprocess.run(["cp", str(mudo), str(destino)], check=True)
            return
        # DOS PASOS: primero solo el audio a WAV y luego se pega al video. Una sola llamada de
        # ffmpeg con muchas pistas (~19) más el video se queda colgada sin error.
        wav = out.with_name(out.stem + ".mezcla.wav")
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
        filtros = []
        for k, a in enumerate(pistas):
            cmd += ["-ss", str(a.get("offset", 0)), "-i", str(config.ruta(a["src"]))]
            ms = int(a.get("at", 0) * 1000)
            corte = (f"atrim=0:{a['dur']},afade=t=in:d=0.3,"
                     f"afade=t=out:st={max(0, a['dur'] - 0.5)}:d=0.5," if a.get("dur") else "")
            filtros.append(f"[{k}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,{corte}"
                           f"adelay={ms}|{ms},volume={a.get('gain', 1)}[a{k}]")
        mezcla = "".join(f"[a{k}]" for k in range(len(pistas)))
        # aresample first_pts=0: si NINGUNA pista arranca en at=0, la mezcla sale con pts inicial
        # igual al primer adelay y el atrim de abajo recorta el audio a (total - ese adelay).
        filtros.append(f"{mezcla}amix=inputs={len(pistas)}:normalize=0:duration=longest,"
                       f"apad=whole_dur={total},aresample=async=1:first_pts=0,atrim=0:{total}{fin_audio}[a]")
        cmd += ["-filter_complex", ";".join(filtros), "-map", "[a]", "-t", str(total), str(wav)]
        subprocess.run(cmd, check=True, timeout=600)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(mudo), "-i", str(wav), "-map", "0:v",
                        "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", str(total),
                        "-movflags", "+faststart", str(destino)], check=True, timeout=600)
        wav.unlink()

    limpias = spec.get("audio", [])
    if spec.get("preview_audio"):
        mezclar(out.with_name(out.stem + "-preview.mp4"), limpias + [spec["preview_audio"]])
    mezclar(out, limpias)
    if mudo.exists():
        mudo.unlink()
    print(json.dumps({"out": str(out), "duracion": round(total, 2),
                      "preview": str(out.with_name(out.stem + "-preview.mp4")) if spec.get("preview_audio") else None},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
