# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["numpy<2.3", "opencv-contrib-python<5", "pillow", "mediapipe==0.10.21", "telemetry-parser"]
# ///
"""Reencuadre de video 360 (Insta360 X3/X4/X5 o cualquier equirectangular 2:1) a vertical 9:16 con cámara virtual.

Carpetas configurables con $REEL_FORGE_360 (default ~/reel-forge/360) y $REEL_FORGE_CACHE.

Uso (con uv, desde cualquier sitio):
  uv run reencuadre360.py proxy   VID.insv|equirect.mp4 [--ancho 3840]      # crea el proxy equirect a 30 fps
  uv run reencuadre360.py hojas   VID [--inicio 0 --dur 20 --n 6 --estab rumbo --nivel auto]
  uv run reencuadre360.py render  --keys keys.json                          # render con keyframes
  uv run reencuadre360.py planeta VID --inicio 3 --dur 6 [--giro 40 --a-normal 2]
  uv run reencuadre360.py seguir  VID --inicio 0 --dur 12 [--modo selfie|tercera --objetivo 90,-20 --render]
  uv run reencuadre360.py telemetria VID.insv                               # lee el giroscopio del .insv

Convenciones (grados):
  yaw   0 = centro del equirect (frente), + gira a la derecha, 180 = atrás.  No se envuelve: para ir de 170
        a -170 por el camino corto escribe 190.
  pitch + mira arriba, -90 = nadir (tiny planet).  roll + inclina en sentido horario.
  fov   campo de visión HORIZONTAL del cuadro de salida.
  d     proyección: 0 = rectilínea (normal), 1 = estereográfica (tiny planet); intermedios = gran angular
        suave.  Si no se pone, se calcula del fov (auto).

keys.json:
{
  "src": "~/reel-forge/360/VID.insv",  "out": "~/reel-forge/360/salidas/x.mp4",
  "inicio": 12.0, "dur": 12, "fps": 30, "velocidad": 1.0, "audio": true,
  "estab": "no|visual|gyro|auto", "modo": "rumbo|bloqueo", "nivel": "auto|no|gyro|[pitch, roll]",
  "desenfoque": 0.35,                    # obturador virtual (fracción de cuadro) para el motion blur
  "keys": [
    {"t": 0,   "planeta": true, "yaw": 0},                   # tiny planet
    {"t": 2.5, "planeta": true, "yaw": 60},                  # gira el planeta
    {"t": 4.0, "yaw": 90, "pitch": 0, "fov": 80, "ease": "suave"},   # planeta -> vista normal
    {"t": 7.0, "yaw": 130, "punch": 0.25},                   # pan lento + punch de fov al llegar
    {"t": 7.35, "yaw": 300, "ease": "whip"},                 # whip-pan con motion blur automático
    {"t": 10, "yaw": 310, "fov": 70}
  ]
}
ease: lineal | suave | entrada | salida | whip | corte | spline.  El ease de una key dice cómo se LLEGA a ella.
Las claves que falten en una key se heredan de la anterior.
"""
import argparse
import json
import math
import os
import subprocess
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Carpetas de trabajo. Se pueden mover con variables de entorno, así el plugin no impone rutas.
#   REEL_FORGE_360    raíz de los 360 (originales, proxys y salidas).  Default: ~/reel-forge/360
#   REEL_FORGE_CACHE  modelos y cachés descargables.                   Default: ~/.cache/reel-forge
#   REEL_FORGE_FUENTE ttf para las etiquetas de las hojas (opcional).
#                     Default: $REEL_FORGE_CACHE/fonts/Montserrat[wght].ttf (la baja tipografias.py).
RAIZ = Path(os.path.expanduser(os.environ.get("REEL_FORGE_360", "~/reel-forge/360")))
PROXYS = RAIZ / "proxys"
SALIDAS = RAIZ / "salidas"
CACHE = Path(os.path.expanduser(os.environ.get("REEL_FORGE_CACHE", "~/.cache/reel-forge")))
# Fuente de las etiquetas de las hojas. Por default, la que baja `motor-video/scripts/tipografias.py`
# en $REEL_FORGE_CACHE/fonts; si tampoco está, las hojas usan la de PIL (se leen peor, pero funcionan).
FUENTE = Path(os.path.expanduser(os.environ.get(
    "REEL_FORGE_FUENTE", str(CACHE / "fonts" / "Montserrat[wght].ttf"))))
MODELO_PERSONAS = CACHE / "efficientdet_lite0.tflite"
URL_MODELO = ("https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/"
              "float32/latest/efficientdet_lite0.tflite")
W, H = 1080, 1920
FPS = 30
PLANETA = {"pitch": -90.0, "roll": 0.0, "fov": 200.0, "d": 1.0}
# Parámetros del stitch de .insv con v360 (X3/X4/X5: dos pistas HEVC 3840x3840, pista 0 = lente trasera,
# pista 1 = frontal). ih_fov: el disco útil guardado mide ~186-194° según pruebas de otros; 193 por defecto.
INSV = {"fov": 193.0, "orden": "10", "rot_frente": 0, "rot_atras": 0}


def ruta(p):
    return Path(os.path.expanduser(str(p)))


def log(msg):
    print(msg, flush=True)


# ------------------------------------------------------------ ffmpeg / proxys

def sondear(src):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=index,codec_type,width,height,r_frame_rate:format=duration", "-of", "json", str(src)],
                       capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    videos = [s for s in d["streams"] if s["codec_type"] == "video" and s.get("width")]
    num, den = videos[0].get("r_frame_rate", "30/1").split("/")
    return {"videos": videos, "audio": any(s["codec_type"] == "audio" for s in d["streams"]),
            "fps": float(num) / float(den), "dur": float(d["format"].get("duration", 0))}


def es_dual_fisheye(src):
    return ruta(src).suffix.lower() in (".insv", ".lrv")


def filtro_insv(info, ancho, fps, cfg):
    """Filtro de ffmpeg que junta las dos lentes del .insv y las pasa a equirect con v360."""
    rot = {0: "", 90: "transpose=1,", 180: "hflip,vflip,", 270: "transpose=2,"}
    fov = cfg["fov"]
    v360 = (f"v360=input=dfisheye:output=e:ih_fov={fov}:iv_fov={fov}:w={ancho}:h={ancho // 2}"
            f":interp=cubic")
    if len(info["videos"]) >= 2:
        # Dos pistas (X3/X4/X5 a 5.7K+): v360 espera [frente | atrás] lado a lado
        fr, at = ("1", "0") if cfg["orden"] == "10" else ("0", "1")
        return (f"[0:v:{fr}]{rot[cfg['rot_frente']]}null[f];[0:v:{at}]{rot[cfg['rot_atras']]}null[b];"
                f"[f][b]hstack=inputs=2:shortest=1,{v360},fps={fps}[v]")
    # Una pista con los dos círculos lado a lado (LRV, modelos viejos)
    if cfg["orden"] == "10":  # atrás | frente -> se invierten las mitades
        return (f"[0:v:0]split[a][c];[a]crop=iw/2:ih:iw/2:0[f];[c]crop=iw/2:ih:0:0[b];"
                f"[f][b]hstack,{v360},fps={fps}[v]")
    return f"[0:v:0]{v360},fps={fps}[v]"


def ruta_proxy(src, ancho):
    return PROXYS / f"{ruta(src).stem}_{ancho}.mp4"


def crear_proxy(src, ancho=3840, fps=FPS, cfg_insv=None, forzar=False):
    """Baja el 360 a un equirect `ancho` x `ancho/2` a `fps` (h264). v360 sobre 8K cuadro por cuadro es lento;
    todo lo demás trabaja sobre este proxy."""
    src = ruta(src)
    out = ruta_proxy(src, ancho)
    if out.exists() and not forzar and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    PROXYS.mkdir(parents=True, exist_ok=True)
    info = sondear(src)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-stats", "-y"]
    if es_dual_fisheye(src):
        cmd += ["-hwaccel", "videotoolbox", "-i", str(src), "-filter_complex",
                filtro_insv(info, ancho, fps, {**INSV, **(cfg_insv or {})}), "-map", "[v]"]
    else:
        cmd += ["-i", str(src), "-vf", f"scale={ancho}:{ancho // 2}:flags=area,fps={fps}", "-map", "0:v:0"]
    if info["audio"]:
        cmd += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-g", "30", str(out)]
    t0 = time.time()
    log(f"proxy: {src.name} -> {out.name}")
    subprocess.run(cmd, check=True)
    log(f"proxy listo en {time.time() - t0:.1f} s ({info['dur']:.1f} s de video)")
    return out


class Lector:
    """Lee cuadros del proxy por un pipe de ffmpeg, desde el cuadro `f0`."""

    def __init__(self, proxy, f0=0, fps=FPS, tam=None, gris=False):
        info = sondear(proxy)
        v = info["videos"][0]
        self.w, self.h = tam or (v["width"], v["height"])
        self.canales = 1 if gris else 3
        vf = [f"scale={self.w}:{self.h}:flags=area"] if tam else []
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{f0 / fps:.4f}", "-i", str(proxy)]
        cmd += (["-vf", ",".join(vf)] if vf else []) + ["-f", "rawvideo", "-pix_fmt", "gray" if gris else "rgb24", "-"]
        # stderr callado: al cerrar el pipe a la mitad ffmpeg se queja ("Error muxing a packet")
        self.p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 8)
        self.i = f0 - 1
        self.ultimo = None

    def leer(self):
        n = self.w * self.h * self.canales
        raw = self.p.stdout.read(n)
        if len(raw) < n:
            return None
        self.i += 1
        forma = (self.h, self.w) if self.canales == 1 else (self.h, self.w, 3)
        self.ultimo = np.frombuffer(raw, np.uint8).reshape(forma)
        return self.ultimo

    def cuadro(self, idx):
        """Avanza hasta el cuadro idx (solo hacia adelante). Al final del clip repite el último."""
        while self.i < idx:
            if self.leer() is None:
                break
        return self.ultimo

    def cerrar(self):
        self.p.stdout.close()
        self.p.kill()


# ------------------------------------------------------------ geometría

def rot_yaw(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rot_pitch(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, s], [0, -s, c]])


def rot_roll(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]])


def rot_camara(yaw, pitch, roll=0.0):
    """Matriz cámara -> mundo. Ejes: x derecha, y arriba, z al frente."""
    return rot_yaw(math.radians(yaw)) @ rot_pitch(math.radians(pitch)) @ rot_roll(math.radians(roll))


def rodrigues(v):
    return cv2.Rodrigues(np.asarray(v, np.float64).reshape(3, 1))[0]


def vec_rot(R):
    return cv2.Rodrigues(np.asarray(R, np.float64))[0].ravel()


def ortonormal(R):
    u, _, vt = np.linalg.svd(R)
    return u @ vt


def rot_entre(a, b):
    """Rotación mínima que lleva el vector a al b."""
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    eje = np.cross(a, b)
    s = np.linalg.norm(eje)
    if s < 1e-9:
        return np.eye(3)
    return rodrigues(eje / s * math.atan2(s, float(np.dot(a, b))))


def dir_a_angulos(v):
    """Vector (mundo) -> (yaw, pitch) en grados."""
    v = v / np.linalg.norm(v)
    return math.degrees(math.atan2(v[0], v[2])), math.degrees(math.asin(np.clip(v[1], -1, 1)))


def angulos_a_dir(yaw, pitch):
    y, p = math.radians(yaw), math.radians(pitch)
    return np.array([math.cos(p) * math.sin(y), math.sin(p), math.cos(p) * math.cos(y)])


def fov_max(d):
    """Mayor fov horizontal representable con la proyección d (rectilínea < 180°)."""
    return 2 * math.degrees(math.acos(-d)) - 12


def d_auto(fov):
    return float(np.clip((fov - 90) / 110, 0, 1))


@lru_cache(maxsize=6)
def rayos(w, h, fov, d):
    """Rayos de cámara (h, w, 3) para la perspectiva general: centro de proyección a distancia d detrás del
    centro de la esfera (d=0 gnomónica, d=1 estereográfica). r = (d+1) sen θ / (d + cos θ)."""
    fov = min(fov, fov_max(d))
    mitad = math.radians(fov) / 2
    r_borde = (d + 1) * math.sin(mitad) / (d + math.cos(mitad))
    x = ((np.arange(w, dtype=np.float32) + 0.5) / w * 2 - 1) * r_borde
    y = ((0.5 - (np.arange(h, dtype=np.float32) + 0.5) / h) * 2) * r_borde * h / w
    xx, yy = np.meshgrid(x, y)
    r = np.hypot(xx, yy)
    k = r / (d + 1)
    theta = np.arctan(k) + np.arcsin(np.clip(k * d / np.sqrt(1 + k * k), -1, 1))
    phi = np.arctan2(yy, xx)
    st = np.sin(theta)
    out = np.empty((h, w, 3), np.float32)
    out[..., 0] = st * np.cos(phi)
    out[..., 1] = st * np.sin(phi)
    out[..., 2] = np.cos(theta)
    return out


def mapas(M, w, h, fov, d, src_w, src_h):
    """Tablas de remap: cuadro de salida -> pixel del equirect fuente. M = corrección @ cámara.
    Los rayos se rotan a media resolución y el campo de vectores (suave) se sube con interpolación lineal:
    mismo resultado a la vista y ~2.5x más rápido. arctan2/arcsin sí van a resolución completa."""
    if w >= 400 and h >= 400:
        ry = rayos(w // 2, h // 2, round(fov, 3), round(d, 4))
        v = cv2.resize(ry @ M.T.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    else:
        v = rayos(w, h, round(fov, 3), round(d, 4)) @ M.T.astype(np.float32)
    x, y, z = v[..., 0], v[..., 1], v[..., 2]
    lon = np.arctan2(x, z)
    lat = np.arctan2(y, np.hypot(x, z))
    mx = (lon * np.float32(1 / (2 * np.pi)) + np.float32(0.5)) * np.float32(src_w) - np.float32(0.5)
    my = np.clip((np.float32(0.5) - lat * np.float32(1 / np.pi)) * np.float32(src_h) - np.float32(0.5), 0, src_h - 1)
    return mx, my


def vista(eq, C, yaw, pitch, roll=0.0, fov=90.0, d=0.0, w=W, h=H, interp=cv2.INTER_LINEAR):
    """Renderiza una cámara virtual sobre el equirect `eq`. C: corrección (mundo virtual -> fuente)."""
    M = C @ rot_camara(yaw, pitch, roll)
    mx, my = mapas(M, w, h, fov, d, eq.shape[1], eq.shape[0])
    return cv2.remap(eq, mx, my, interp, borderMode=cv2.BORDER_WRAP)


# ------------------------------------------------------------ orientación: estabilización y nivel

def _pixeles_a_vectores(pts, w, h):
    lon = ((pts[:, 0] + 0.5) / w - 0.5) * 2 * np.pi
    lat = (0.5 - (pts[:, 1] + 0.5) / h) * np.pi
    return np.stack([np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon)], 1)


def kabsch(a, b):
    """R que minimiza |b - R a| (filas = vectores)."""
    u, _, vt = np.linalg.svd(a.T @ b)
    s = np.diag([1, 1, np.sign(np.linalg.det(vt.T @ u.T))])
    return vt.T @ s @ u.T


def rotacion_ransac(a, b, umbral_deg=0.45, iters=150, rng=None):
    """Rotación entre dos cuadros equirect a partir de puntos seguidos, robusta a gente que se mueve."""
    rng = rng or np.random.default_rng(0)
    if len(a) < 8:
        return np.eye(3), 0
    cos_u = math.cos(math.radians(umbral_deg))
    mejor, mejor_n = None, -1
    for _ in range(iters):
        idx = rng.choice(len(a), 3, replace=False)
        R = kabsch(a[idx], b[idx])
        n = int((((a @ R.T) * b).sum(1) > cos_u).sum())
        if n > mejor_n:
            mejor, mejor_n = R, n
    dentro = ((a @ mejor.T) * b).sum(1) > cos_u
    if dentro.sum() >= 6:
        mejor = kabsch(a[dentro], b[dentro])
    return mejor, int(dentro.sum())


def rotaciones_visuales(proxy, lat_min=-20, lat_max=70, ancho=1024):
    """ΔR entre cuadros consecutivos (b = ΔR a) con esquinas + flujo óptico LK sobre el equirect reducido.
    Se ignoran el nadir (bastón, bici, la propia persona) y los polos."""
    lec = Lector(proxy, 0, tam=(ancho, ancho // 2), gris=True)
    w, h = lec.w, lec.h
    fila = np.arange(h)
    lat = (0.5 - (fila + 0.5) / h) * 180
    mascara = np.zeros((h, w), np.uint8)
    mascara[(lat > lat_min) & (lat < lat_max), 16:w - 16] = 255
    prev = lec.leer()
    deltas, inliers = [], []
    rng = np.random.default_rng(1)
    while True:
        cur = lec.leer()
        if cur is None:
            break
        p0 = cv2.goodFeaturesToTrack(prev, 700, 0.01, 8, mask=mascara)
        R, n = np.eye(3), 0
        if p0 is not None and len(p0) > 10:
            p1, st, _ = cv2.calcOpticalFlowPyrLK(prev, cur, p0, None, winSize=(21, 21), maxLevel=3)
            ok = st.ravel() == 1
            a = _pixeles_a_vectores(p0[ok, 0], w, h)
            b = _pixeles_a_vectores(p1[ok, 0], w, h)
            R, n = rotacion_ransac(a, b, rng=rng)
        deltas.append(R)
        inliers.append(n)
        prev = cur
    lec.cerrar()
    deltas, inliers = np.array(deltas), np.array(inliers)
    # Corte de escena (clip ya editado) o cuadro roto: casi ningún punto coincide. Ahí no hay rotación real.
    cortes = np.where(inliers < max(15, 0.12 * np.median(inliers)))[0] + 1
    deltas[cortes - 1] = np.eye(3)
    return deltas, inliers, cortes


def integrar(deltas):
    """O_t (fuente del cuadro t -> referencia = cuadro 0): O_{t+1} = O_t ΔR^T."""
    O = [np.eye(3)]
    for R in deltas:
        O.append(ortonormal(O[-1] @ R.T))
    return np.array(O)


def tramos(n, cortes):
    """[(ini, fin)] de cada toma entre cortes."""
    b = [0] + [int(c) for c in cortes if 0 < c < n] + [n]
    return [(b[i], b[i + 1]) for i in range(len(b) - 1) if b[i + 1] > b[i]]


def leer_imu(src):
    """Giroscopio (°/s) y acelerómetro (m/s²) del .insv con telemetry-parser (AdrianEddy, soporta X5)."""
    import telemetry_parser
    tp = telemetry_parser.Parser(str(src))
    imu = tp.normalized_imu()
    if not imu:
        raise RuntimeError("El archivo no trae IMU legible")
    t = np.array([s["timestamp_ms"] for s in imu]) / 1000.0
    g = np.array([s["gyro"] for s in imu], np.float64)
    a = np.array([s.get("accl") or [0, 0, 0] for s in imu], np.float64)
    return {"t": t, "gyro": g, "accl": a, "camara": tp.camera, "modelo": tp.model}


def _rotvec_gyro_por_cuadro(imu, n, fps, desfase=0.0):
    """Integra el giro (IMU) en cada intervalo de cuadro -> rotvec en radianes (n-1, 3)."""
    t, g = imu["t"] + desfase, np.radians(imu["gyro"])
    bordes = np.arange(n) / fps
    acum = np.concatenate([[[0.0, 0.0, 0.0]], np.cumsum((g[1:] + g[:-1]) / 2 * np.diff(t)[:, None], 0)])
    return np.diff(np.stack([np.interp(bordes, t, acum[:, j]) for j in range(3)], 1), axis=0)


def calibrar_imu(imu, deltas, fps):
    """Encuentra la rotación IMU -> equirect (y el desfase de tiempo) comparando el giro con la rotación
    medida en la imagen: rotvec(ΔR) ≈ -M ω dt. Así no dependemos de la orientación de fábrica del IMU."""
    vis = -np.array([vec_rot(R) for R in deltas])
    n = len(deltas) + 1
    mejor = None
    for desfase in np.arange(-0.3, 0.301, 0.02):
        gy = _rotvec_gyro_por_cuadro(imu, n, fps, desfase)
        mov = (np.linalg.norm(vis, axis=1) > math.radians(0.3)) & (np.linalg.norm(gy, axis=1) > 1e-4)
        if mov.sum() < 20:
            continue
        M = kabsch(gy[mov], vis[mov])
        err = float(np.median(np.linalg.norm(gy[mov] @ M.T - vis[mov], axis=1)))
        if mejor is None or err < mejor[2]:
            mejor = (M, desfase, err, int(mov.sum()))
    if mejor is None:
        raise RuntimeError("La cámara casi no se mueve: no se puede calibrar el IMU contra la imagen")
    return mejor


def orientacion_gyro(imu, M, desfase, n, fps, ganancia=0.02):
    """O_t integrando el giroscopio (ya en ejes del equirect) con corrección de inclinación por
    acelerómetro (filtro complementario tipo Mahony). Devuelve O y el vector 'arriba' en la referencia."""
    rv = _rotvec_gyro_por_cuadro(imu, n, fps, desfase) @ M.T
    t_c = np.arange(n) / fps
    acc = np.stack([np.interp(t_c, imu["t"] + desfase, imu["accl"][:, j]) for j in range(3)], 1) @ M.T
    # Gravedad: el acelerómetro en reposo marca +g hacia arriba. Si la mayoría apunta abajo, se invierte.
    if np.median(acc[:, 1]) < 0:
        acc = -acc
    norma = np.linalg.norm(acc, axis=1)
    quieto = np.abs(norma - 9.81) < 1.5
    primer_s = slice(0, max(5, int(fps)))
    arriba_ref = acc[primer_s][quieto[primer_s]].mean(0) if quieto[primer_s].any() else acc[0]
    arriba_ref = arriba_ref / np.linalg.norm(arriba_ref)
    O = [np.eye(3)]
    for i in range(n - 1):
        R = ortonormal(O[-1] @ rodrigues(rv[i]))
        if quieto[i + 1]:
            medido = R @ (acc[i + 1] / norma[i + 1])
            eje = np.cross(medido, arriba_ref)
            R = ortonormal(rodrigues(eje * ganancia) @ R)
        O.append(R)
    return np.array(O), arriba_ref


def _segmentos(gris):
    try:
        lsd = cv2.createLineSegmentDetector()
        seg = lsd.detect(gris)[0]
    except Exception:
        seg = cv2.ximgproc.createFastLineDetector().detect(gris)
    return np.zeros((0, 4)) if seg is None else seg.reshape(-1, 4)


def arriba_por_verticales(eq, C=np.eye(3), tam=640, rng=None):
    """Estima la dirección 'arriba' (en coords de la corrección C) con el punto de fuga de las líneas
    verticales (postes, edificios, árboles), en 8 vistas de 90°. Devuelve (vector, n_segmentos) o None."""
    rng = rng or np.random.default_rng(2)
    normales, pesos = [], []
    r_borde = math.tan(math.radians(45))
    for yaw in range(0, 360, 45):
        Rv = C @ rot_camara(yaw, 0)
        img = cv2.cvtColor(cv2.remap(eq, *mapas(Rv, tam, tam, 90, 0, eq.shape[1], eq.shape[0]), cv2.INTER_LINEAR,
                                     borderMode=cv2.BORDER_WRAP), cv2.COLOR_RGB2GRAY)
        for x1, y1, x2, y2 in _segmentos(img):
            largo = math.hypot(x2 - x1, y2 - y1)
            if largo < tam * 0.06:
                continue
            ang = abs(math.degrees(math.atan2(x2 - x1, y2 - y1)))
            if min(ang, 180 - ang) > 40:  # solo casi verticales
                continue
            p = []
            for x, y in ((x1, y1), (x2, y2)):
                c = np.array([((x + 0.5) / tam * 2 - 1) * r_borde, (0.5 - (y + 0.5) / tam) * 2 * r_borde, 1.0])
                p.append(Rv @ (c / np.linalg.norm(c)))
            n = np.cross(p[0], p[1])
            normales.append(n / np.linalg.norm(n))
            pesos.append(largo)
    if len(normales) < 12:
        return None
    N, wts = np.array(normales), np.array(pesos)
    mejor, mejor_s = None, -1
    sen_u = math.sin(math.radians(1.2))
    for _ in range(400):
        i, j = rng.choice(len(N), 2, replace=False)
        u = np.cross(N[i], N[j])
        if np.linalg.norm(u) < 0.2:
            continue
        u /= np.linalg.norm(u)
        u *= np.sign(u[1]) or 1
        if u[1] < math.cos(math.radians(40)):
            continue
        s = wts[np.abs(N @ u) < sen_u].sum()
        if s > mejor_s:
            mejor, mejor_s = u, s
    if mejor is None:
        return None
    dentro = np.abs(N @ mejor) < sen_u
    if dentro.sum() < 12:  # con menos segmentos coincidentes la lectura es ruido (paisajes sin verticales)
        return None
    A = (N[dentro] * wts[dentro, None]).T @ N[dentro]
    u = np.linalg.eigh(A)[1][:, 0]
    u *= np.sign(u[1])
    return u, int(dentro.sum())


def suavizar_serie(x, sigma):
    if sigma <= 0 or len(x) < 3:
        return x
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    xp = np.pad(x, (r, r), mode="edge")
    return np.convolve(xp, k, mode="valid")


class Orientacion:
    """Corrección por cuadro C_t (mundo virtual nivelado -> fuente del cuadro t) para un proxy.

    estab: no | visual | gyro | auto (gyro si hay .insv con IMU, si no visual)
    modo:  rumbo  = horizonte fijo y el frente sigue suavemente hacia donde va la cámara (tipo FlowState)
           bloqueo = dirección fija en el mundo (el yaw de las keys es absoluto)
    nivel: auto (acelerómetro si hay gyro; si no, líneas verticales cada 2 s y por toma) | gyro | no |
           [pitch, roll] manual
    Todo se calcula una vez por proxy (clip completo) y se guarda en caché junto al proxy.
    """

    def __init__(self, src, proxy, estab="no", modo="rumbo", nivel="auto", suave_rumbo=1.2, fps=FPS):
        self.fps = fps
        info = sondear(proxy)
        self.n = max(1, round(info["dur"] * fps))
        self.O = np.repeat(np.eye(3)[None], self.n, 0)
        self.cortes = np.array([], int)
        arriba = None
        if estab in ("visual", "gyro", "auto"):
            O, arriba, self.cortes = self._estabilizar(src, proxy, estab)
            m = min(len(O), self.n)
            self.O[:m] = O[:m]
        # Nivel: L_t (referencia -> mundo nivelado), por cuadro
        self.L = np.repeat(np.eye(3)[None], self.n, 0)
        if isinstance(nivel, (list, tuple)):
            self.L[:] = rot_roll(math.radians(nivel[1])) @ rot_pitch(math.radians(nivel[0]))
        elif nivel in ("gyro", "auto") and arriba is not None:
            self.L[:] = rot_entre(arriba, np.array([0.0, 1.0, 0.0]))
            log("nivel: acelerómetro")
        elif nivel == "auto":
            cache = proxy.with_suffix(f".nivel-{estab}.npy")
            if cache.exists() and cache.stat().st_mtime >= proxy.stat().st_mtime:
                self.L = np.load(cache)
            else:
                self.L = self._nivel_visual(proxy)
                np.save(cache, self.L)
        # Rumbo suavizado, reiniciado en cada toma
        self.rumbo = None
        if estab != "no" and modo == "rumbo":
            frente = np.einsum("nij,njk,k->ni", self.L, self.O, np.array([0.0, 0.0, 1.0]))
            h = np.arctan2(frente[:, 0], frente[:, 2])
            self.rumbo = np.zeros(self.n)
            for a, b in tramos(self.n, self.cortes):
                hu = np.unwrap(h[a:b])
                self.rumbo[a:b] = suavizar_serie(hu, suave_rumbo * fps) - hu[0]

    def _estabilizar(self, src, proxy, estab):
        cache = proxy.with_suffix(f".orient-{estab}.npz")
        if cache.exists() and cache.stat().st_mtime >= proxy.stat().st_mtime:
            z = np.load(cache, allow_pickle=True)
            if "cortes" in z.files:  # cachés viejas sin cortes se recalculan
                log(f"orientación (caché): {z['fuente']}")
                return z["O"], (z["arriba"] if z["arriba"].size else None), z["cortes"]
        t0 = time.time()
        deltas, inl, cortes = rotaciones_visuales(proxy)
        log(f"estab visual: {len(deltas)} pares en {time.time() - t0:.1f} s (mediana {int(np.median(inl))} "
            f"puntos buenos, {len(cortes)} cortes de escena en {[round(c / self.fps, 1) for c in cortes]} s)")
        O, arriba, fuente = integrar(deltas), None, "visual"
        if estab in ("gyro", "auto") and es_dual_fisheye(src):
            try:
                imu = leer_imu(src)
                M, desf, err, nmov = calibrar_imu(imu, deltas, self.fps)
                O, arriba = orientacion_gyro(imu, M, desf, len(O), self.fps)
                fuente = f"gyro (desfase {desf:+.2f} s, error {math.degrees(err):.2f}°/cuadro, {nmov} cuadros)"
            except Exception as e:  # noqa: BLE001
                log(f"gyro no disponible ({e}); se queda la estabilización visual")
                if estab == "gyro":
                    raise
        np.savez(cache, O=O, arriba=arriba if arriba is not None else np.array([]), fuente=fuente, cortes=cortes)
        log(f"orientación: {fuente}")
        return O, arriba, cortes

    def _nivel_visual(self, proxy, cada_s=2.0):
        """'Arriba' por punto de fuga vertical cada `cada_s` segundos (en coords de referencia), filtrado por
        toma e interpolado. Corrige la inclinación de la cámara y la deriva de la estabilización visual."""
        t0 = time.time()
        lec = Lector(proxy, 0, tam=(2048, 1024))
        L = np.repeat(np.eye(3)[None], self.n, 0)
        paso = max(1, int(cada_s * self.fps))
        total, inclin, sin_nivel = 0, [], []
        for a, b in tramos(self.n, self.cortes):
            idxs = sorted(set(list(range(a + 2, b, paso)) + [max(a, b - 3)]))
            muestras = []
            for idx in idxs:
                eq = lec.cuadro(idx)
                if eq is None:
                    break
                r = arriba_por_verticales(eq, self.O[idx].T)
                if r:
                    muestras.append((idx, r[0]))
            total += len(muestras)
            if not muestras:
                sin_nivel.append(f"{a / self.fps:.1f}-{b / self.fps:.1f} s")
                continue
            ts = np.array([m[0] for m in muestras], float)
            us = np.array([m[1] for m in muestras])
            if len(us) >= 3:  # mediana móvil de 3 para tirar lecturas raras
                us = np.array([np.median(us[max(0, i - 1):i + 2], 0) for i in range(len(us))])
            for i in range(a, b):
                u = np.array([np.interp(i, ts, us[:, j]) for j in range(3)])
                L[i] = rot_entre(u / np.linalg.norm(u), np.array([0.0, 1.0, 0.0]))
            inclin += [math.degrees(math.acos(np.clip(u[1] / np.linalg.norm(u), -1, 1))) for u in us]
        lec.cerrar()
        if not total:
            log("nivel: no encontré líneas verticales; se deja como viene")
        else:
            log(f"nivel: {total} lecturas de líneas verticales en {time.time() - t0:.1f} s, "
                f"inclinación corregida {np.median(inclin):.1f}° (máx {max(inclin):.1f}°)")
        if sin_nivel:
            log(f"nivel: sin líneas verticales confiables en {sin_nivel}; ahí usa gyro o --nivel pitch,roll")
        return L

    def C(self, idx):
        idx = int(np.clip(idx, 0, self.n - 1))
        C = self.O[idx].T @ self.L[idx].T
        if self.rumbo is not None:
            C = C @ rot_yaw(self.rumbo[idx])
        return C


# ------------------------------------------------------------ cámara virtual (keyframes)

def ease(nombre, u):
    u = min(1.0, max(0.0, u))
    if nombre == "lineal":
        return u
    if nombre == "entrada":
        return u ** 3
    if nombre == "salida":
        return 1 - (1 - u) ** 3
    if nombre == "whip":  # casi todo el recorrido en el centro del intervalo
        k = 6.0
        return 0.5 * (1 + math.tanh(k * (u - 0.5)) / math.tanh(k / 2))
    if nombre == "corte":
        return 1.0 if u >= 1 else 0.0
    return u * u * u * (u * (6 * u - 15) + 10)  # suave (smootherstep)


CAMPOS = ("yaw", "pitch", "roll", "fov", "d")


def preparar_keys(keys):
    """Ordena, hereda campos faltantes y resuelve 'planeta' y 'd' automático."""
    keys = sorted([dict(k) for k in keys], key=lambda k: k["t"])
    prev = {"yaw": 0.0, "pitch": 0.0, "roll": 0.0, "fov": 80.0}
    out = []
    for k in keys:
        base = dict(prev)
        if k.get("planeta"):
            base.update(PLANETA)
        elif "d" not in k and prev.get("_planeta"):
            base.pop("d", None)  # al salir del planeta, d vuelve a automático
        for c in CAMPOS:
            if c in k:
                base[c] = float(k[c])
        hereda_d = prev.get("_d_fijo", False) and not prev.get("_planeta")
        base["_d_fijo"] = "d" in k or bool(k.get("planeta")) or hereda_d
        if not base["_d_fijo"]:
            base["d"] = d_auto(base["fov"])
        base["_planeta"] = bool(k.get("planeta"))
        base.update({"t": float(k["t"]), "ease": k.get("ease", "suave"), "punch": float(k.get("punch", 0))})
        out.append(base)
        prev = base
    return out


def _catmull(p0, p1, p2, p3, u):
    return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * u ** 3)


def camara_en(keys, t):
    if t <= keys[0]["t"]:
        cam = {c: keys[0][c] for c in CAMPOS}
    elif t >= keys[-1]["t"]:
        cam = {c: keys[-1][c] for c in CAMPOS}
    else:
        i = max(j for j in range(len(keys)) if keys[j]["t"] <= t)
        a, b = keys[i], keys[i + 1]
        u = (t - a["t"]) / max(1e-6, b["t"] - a["t"])
        if b["ease"] == "spline":
            p0, p3 = keys[max(0, i - 1)], keys[min(len(keys) - 1, i + 2)]
            cam = {c: _catmull(p0[c], a[c], b[c], p3[c], u) for c in CAMPOS}
        else:
            e = ease(b["ease"], u)
            cam = {c: a[c] + (b[c] - a[c]) * e for c in CAMPOS}
    # punch: el fov se cierra de golpe al llegar a la key y se asienta en ~0.25 s
    for k in keys:
        if k["punch"] and k["t"] <= t < k["t"] + 0.25:
            e = (t - k["t"]) / 0.25
            cam["fov"] *= 1 - k["punch"] * (1 - e) ** 3
    cam["fov"] = min(cam["fov"], fov_max(cam["d"]))
    return cam


def _angulo_entre(c0, c1):
    f0 = rot_camara(c0["yaw"], c0["pitch"]) @ np.array([0, 0, 1.0])
    f1 = rot_camara(c1["yaw"], c1["pitch"]) @ np.array([0, 0, 1.0])
    giro = math.degrees(math.acos(np.clip(f0 @ f1, -1, 1)))
    return giro + abs(c1["roll"] - c0["roll"]) * 0.5 + abs(c1["fov"] - c0["fov"]) * 0.3


def render_cuadro(eq, C, keys, t, fps, w, h, obturador=0.35, interp=cv2.INTER_LINEAR):
    """Un cuadro; si la cámara gira rápido promedia sub-cuadros (motion blur de rotación)."""
    cam = camara_en(keys, t)
    if obturador > 0:
        dt = obturador / fps
        c0, c1 = camara_en(keys, t - dt / 2), camara_en(keys, t + dt / 2)
        grados = _angulo_entre(c0, c1)
        # un sub-cuadro cada ~0.5° de giro durante el obturador; el paso en pixeles queda chico
        n = int(np.clip(math.ceil(grados / 0.5), 1, 24)) if grados > 1.0 else 1
        if n > 1:
            # los sub-cuadros van a media resolución: el barrido tapa la diferencia y cuesta 1/4
            wm, hm = w // 2, h // 2
            acc = np.zeros((hm, wm, 3), np.float32)
            for j in range(n):
                cj = camara_en(keys, t + (j / (n - 1) - 0.5) * dt)
                acc += vista(eq, C, cj["yaw"], cj["pitch"], cj["roll"], cj["fov"], cj["d"], wm, hm, interp)
            return cv2.resize((acc / n).astype(np.uint8), (w, h), interpolation=cv2.INTER_CUBIC)
    return vista(eq, C, cam["yaw"], cam["pitch"], cam["roll"], cam["fov"], cam["d"], w, h, interp)


# ------------------------------------------------------------ render

def _cargar_spec(spec):
    if isinstance(spec, (str, Path)):
        spec = json.load(open(ruta(spec)))
    return dict(spec)


def _preparar(spec):
    src = ruta(spec["src"])
    proxy = crear_proxy(src, spec.get("ancho_proxy", 3840))
    nivel = spec.get("nivel", "auto")
    ori = Orientacion(src, proxy, spec.get("estab", "no"), spec.get("modo", "rumbo"), nivel,
                      spec.get("suave_rumbo", 1.2))
    return src, proxy, ori


def cuadros(spec, n=None, fps=FPS, w=W, h=H, inicio=None):
    """Generador de cuadros RGB reencuadrados (lo usa render.py con segmentos "r360")."""
    spec = _cargar_spec(spec)
    src, proxy, ori = _preparar(spec)
    keys = preparar_keys(spec["keys"])
    inicio = spec.get("inicio", 0.0) if inicio is None else inicio
    vel = spec.get("velocidad", 1.0)
    n = n or round(spec.get("dur", keys[-1]["t"]) * fps)
    f0 = round(inicio * FPS)
    lec = Lector(proxy, f0)
    interp = cv2.INTER_CUBIC if spec.get("calidad") == "alta" else cv2.INTER_LINEAR
    obt = spec.get("desenfoque", 0.35)
    hilos = spec.get("hilos", min(8, os.cpu_count() or 4))
    # Los cuadros se leen en orden y se renderizan en paralelo (numpy y cv2 sueltan el GIL)
    with ThreadPoolExecutor(hilos) as ex:
        cola = deque()
        try:
            for i in range(n):
                t = i / fps
                idx = f0 + int(round(t * vel * FPS))
                eq = lec.cuadro(idx)
                if eq is None:
                    raise RuntimeError(f"Sin cuadros en {proxy.name} desde {inicio}s")
                cola.append(ex.submit(render_cuadro, eq, ori.C(idx), keys, t, fps, w, h, obt, interp))
                if len(cola) >= hilos * 2:
                    yield cola.popleft().result()
            while cola:
                yield cola.popleft().result()
        finally:
            lec.cerrar()


def render(spec):
    spec = _cargar_spec(spec)
    t0 = time.time()
    src, proxy, ori = _preparar(spec)
    t_prep = time.time() - t0
    keys = preparar_keys(spec["keys"])
    fps = spec.get("fps", FPS)
    dur = spec.get("dur", keys[-1]["t"])
    n = round(dur * fps)
    out = ruta(spec.get("out", SALIDAS / f"{src.stem}_9x16.mp4"))
    out.parent.mkdir(parents=True, exist_ok=True)
    w, h = spec.get("w", W), spec.get("h", H)
    inicio, vel = spec.get("inicio", 0.0), spec.get("velocidad", 1.0)
    info = sondear(proxy)
    con_audio = spec.get("audio", True) and info["audio"] and vel == 1
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", str(fps), "-i", "-"]
    if con_audio:
        cmd += ["-ss", str(inicio), "-t", str(dur), "-i", str(proxy), "-map", "0:v", "-map", "1:a",
                "-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(out)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t1 = time.time()
    for i, fr in enumerate(cuadros(spec, n, fps, w, h)):
        enc.stdin.write(np.ascontiguousarray(fr).tobytes())
        if i % 60 == 0:
            log(f"  cuadro {i}/{n}")
    enc.stdin.close()
    enc.wait()
    t_render = time.time() - t1
    res = {"out": str(out), "dur": dur, "cuadros": n, "prep_s": round(t_prep, 1), "render_s": round(t_render, 1),
           "fps_render": round(n / max(t_render, 1e-6), 1)}
    log(json.dumps(res, ensure_ascii=False))
    return res


# ------------------------------------------------------------ hojas de contacto

def _fuente(tam):
    """Fuente de las etiquetas. Sin FUENTE (o si no es variable) cae a la de PIL, que es legible pero fea."""
    try:
        f = ImageFont.truetype(str(FUENTE), tam)
    except Exception:
        return ImageFont.load_default()
    try:
        f.set_variation_by_axes([700])   # peso bold si la fuente es variable
    except Exception:
        pass
    return f


def _etiqueta(d, xy, texto, f):
    bb = d.textbbox(xy, texto, font=f)
    d.rectangle([bb[0] - 5, bb[1] - 3, bb[2] + 5, bb[3] + 3], fill=(0, 0, 0))
    d.text(xy, texto, font=f, fill=(255, 255, 255))


VISTAS = {
    "cubo": [("frente", 0, 0), ("derecha", 90, 0), ("atrás", 180, 0), ("izquierda", -90, 0),
             ("arriba", 0, 90), ("abajo", 0, -90)],
    "anillo8": [(f"yaw {y}", y, -10) for y in (0, 45, 90, 135, 180, -135, -90, -45)],
}


def hojas(src, inicio=0.0, dur=None, n=6, por_hoja=3, vistas="cubo", estab="no", modo="rumbo", nivel="auto",
          personas=False, out_dir=None):
    """Hojas de contacto: por instante, el equirect con rejilla de yaw/pitch y 6 (cubo) u 8 (anillo) vistas,
    para decidir hacia dónde mirar. Con personas=True marca a la gente detectada con su yaw/pitch."""
    src = ruta(src)
    proxy = crear_proxy(src)
    ori = Orientacion(src, proxy, estab, modo, nivel)
    dur = dur or (ori.n / FPS - inicio)
    out_dir = ruta(out_dir or SALIDAS / f"hojas_{src.stem}")
    out_dir.mkdir(parents=True, exist_ok=True)
    tiempos = np.linspace(inicio, inicio + dur - 0.1, n)
    lista = VISTAS[vistas]
    EW, EH, VT = 900, 450, 225
    cols = 3 if vistas == "cubo" else 4
    filas_v = math.ceil(len(lista) / cols)
    fila_h = max(EH, filas_v * VT) + 44
    ancho = EW + cols * VT + 30
    f_chica, f_grande = _fuente(17), _fuente(24)
    detector = Detector() if personas else None
    salidas = []
    for h0 in range(0, n, por_hoja):
        grupo = tiempos[h0:h0 + por_hoja]
        hoja = Image.new("RGB", (ancho, fila_h * len(grupo)), (24, 24, 24))
        d = ImageDraw.Draw(hoja)
        for r, t in enumerate(grupo):
            idx = round(t * FPS)
            lec = Lector(proxy, idx)
            eq = lec.leer()
            lec.cerrar()
            C = ori.C(idx)
            y0 = r * fila_h
            _etiqueta(d, (10, y0 + 8), f"t = {t:.1f} s", f_grande)
            # equirect ya corregido (nivel/estabilización) para que los yaw coincidan con el render
            plano = vista_equirect(eq, C, EW, EH)
            hoja.paste(Image.fromarray(plano), (0, y0 + 44))
            for yaw in range(-180, 181, 45):
                x = int((yaw / 360 + 0.5) * EW)
                d.line([(x, y0 + 44), (x, y0 + 44 + EH)], fill=(255, 255, 0) if yaw == 0 else (200, 200, 200), width=1)
                _etiqueta(d, (min(x + 3, EW - 40), y0 + 48), str(yaw), f_chica)
            for pitch in (-45, 0, 45):
                y = int(y0 + 44 + (0.5 - pitch / 180) * EH)
                d.line([(0, y), (EW, y)], fill=(160, 160, 160), width=1)
                _etiqueta(d, (4, y + 2), f"{pitch}", f_chica)
            if detector:
                for p in detector.personas_360(eq, C):
                    x = int((((p["yaw"] + 180) % 360) / 360) * EW)
                    y = int(y0 + 44 + (0.5 - p["pitch"] / 180) * EH)
                    s = max(8, int(p["alto"] / 180 * EH / 2))
                    d.rectangle([x - s // 2, y - s, x + s // 2, y + s], outline=(255, 60, 60), width=3)
                    _etiqueta(d, (x - 30, y + s + 2), f"{p['yaw']:.0f},{p['pitch']:.0f}", f_chica)
            for k, (nombre, yaw, pitch) in enumerate(lista):
                im = vista(eq, C, yaw, pitch, 0, 100, 0, VT, VT)
                x = EW + 10 + (k % cols) * (VT + 5)
                y = y0 + 44 + (k // cols) * (VT + 5)
                hoja.paste(Image.fromarray(im), (x, y))
                _etiqueta(d, (x + 6, y + 6), f"{nombre} ({yaw},{pitch})", f_chica)
        ruta_hoja = out_dir / f"hoja_{h0 // por_hoja + 1:02d}.jpg"
        hoja.save(ruta_hoja, quality=88)
        salidas.append(str(ruta_hoja))
    log(json.dumps({"hojas": salidas}, ensure_ascii=False))
    return salidas


def vista_equirect(eq, C, w, h):
    """Re-proyecta el equirect completo con la corrección C (para ver el horizonte ya nivelado)."""
    if np.allclose(C, np.eye(3)):
        return cv2.resize(eq, (w, h), interpolation=cv2.INTER_AREA)
    xs = ((np.arange(w) + 0.5) / w - 0.5) * 2 * np.pi
    ys = (0.5 - (np.arange(h) + 0.5) / h) * np.pi
    lon, lat = np.meshgrid(xs, ys)
    v = np.stack([np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon)], -1).reshape(-1, 3) @ C.T
    lo, la = np.arctan2(v[:, 0], v[:, 2]), np.arcsin(np.clip(v[:, 1], -1, 1))
    mx = ((lo / (2 * np.pi) + 0.5) * eq.shape[1] - 0.5).reshape(h, w).astype(np.float32)
    my = np.clip((0.5 - la / np.pi) * eq.shape[0] - 0.5, 0, eq.shape[0] - 1).reshape(h, w).astype(np.float32)
    return cv2.remap(eq, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


# ------------------------------------------------------------ detección y seguimiento de personas

class Detector:
    """Personas con MediaPipe ObjectDetector (EfficientDet-Lite0, 14 MB, CPU) sobre vistas perspectivas."""

    # anillo al horizonte + anillo mirando abajo (bastón de selfie: la persona queda a -30..-60°)
    VISTAS = [(y, 0) for y in range(0, 360, 60)] + [(y, -50) for y in (0, 90, 180, 270)]

    def __init__(self, umbral=0.35, tam=512, fov=100):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        if not MODELO_PERSONAS.exists():
            MODELO_PERSONAS.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["curl", "-sL", "-o", str(MODELO_PERSONAS), URL_MODELO], check=True)
        self.mp = mp
        op = vision.ObjectDetectorOptions(base_options=BaseOptions(model_asset_path=str(MODELO_PERSONAS)),
                                          running_mode=vision.RunningMode.IMAGE, max_results=12,
                                          score_threshold=umbral, category_allowlist=["person"])
        self.det = vision.ObjectDetector.create_from_options(op)
        self.tam, self.fov = tam, fov

    def personas_360(self, eq, C=np.eye(3)):
        """Lista de {yaw, pitch, alto (°), score} en el mundo virtual (mismo sistema que las keys)."""
        tam, fov = self.tam, self.fov
        r_borde = math.tan(math.radians(fov / 2))
        hallazgos = []
        for yaw, pitch in self.VISTAS:
            Rv = rot_camara(yaw, pitch)
            img = np.ascontiguousarray(vista(eq, C, yaw, pitch, 0, fov, 0, tam, tam))
            res = self.det.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=img))
            for dt in res.detections:
                b = dt.bounding_box
                if b.height < tam * 0.06:
                    continue
                cx, cy = b.origin_x + b.width / 2, b.origin_y + b.height / 2
                borde = min(b.origin_x, b.origin_y, tam - b.origin_x - b.width, tam - b.origin_y - b.height) < 4
                rays = []
                for x, y in ((cx, cy), (cx, b.origin_y), (cx, b.origin_y + b.height)):
                    c = np.array([((x + 0.5) / tam * 2 - 1) * r_borde, (0.5 - (y + 0.5) / tam) * 2 * r_borde, 1.0])
                    rays.append(Rv @ (c / np.linalg.norm(c)))
                yw, pt = dir_a_angulos(rays[0])
                alto = math.degrees(math.acos(np.clip(rays[1] @ rays[2], -1, 1)))
                hallazgos.append({"yaw": yw, "pitch": pt, "alto": alto, "score": dt.categories[0].score,
                                  "dir": rays[0], "borde": borde})
        # quitar duplicados de vistas que se traslapan: se queda la que no toca el borde / la más alta
        hallazgos.sort(key=lambda p: (p["borde"], -p["alto"]))
        unicos = []
        for p in hallazgos:
            if all(math.degrees(math.acos(np.clip(p["dir"] @ q["dir"], -1, 1))) > 0.5 * max(p["alto"], q["alto"])
                   for q in unicos):
                unicos.append(p)
        return unicos


class UnoEuro:
    """Filtro One-Euro (Casiez 2012): suaviza mucho cuando va lento y responde cuando hay movimiento."""

    def __init__(self, min_corte=0.4, beta=0.02, d_corte=1.0):
        self.mc, self.beta, self.dc = min_corte, beta, d_corte
        self.x = self.dx = None

    @staticmethod
    def _alfa(corte, dt):
        tau = 1 / (2 * math.pi * corte)
        return 1 / (1 + tau / dt)

    def __call__(self, x, dt):
        if self.x is None:
            self.x, self.dx = x, 0.0
            return x
        dx = (x - self.x) / dt
        a_d = self._alfa(self.dc, dt)
        self.dx = a_d * dx + (1 - a_d) * self.dx
        corte = self.mc + self.beta * abs(self.dx)
        a = self._alfa(corte, dt)
        self.x = a * x + (1 - a) * self.x
        return self.x


def _dist_ang(a, b):
    return math.degrees(math.acos(np.clip(angulos_a_dir(a[0], a[1]) @ angulos_a_dir(b[0], b[1]), -1, 1)))


def seguir(src, inicio=0.0, dur=10.0, modo="selfie", objetivo=None, hz=6.0, estab="no", modo_estab="rumbo",
           nivel="auto", fov_fijo=None, out_keys=None):
    """Sigue a la persona: detecta cada 1/hz s, asocia al objetivo, suaviza con One-Euro y escribe keys.
    modo selfie: la persona al centro, zoom según su tamaño.  modo tercera: 'palo de selfie invisible' en
    3ª persona: se mira hacia la persona desde arriba, con ella en el tercio inferior y gran angular."""
    src = ruta(src)
    proxy = crear_proxy(src)
    ori = Orientacion(src, proxy, estab, modo_estab, nivel)
    det = Detector()
    lec = Lector(proxy, round(inicio * FPS))
    paso = 1 / hz
    t0 = time.time()
    pista, ultimo, perdido = [], None, 0.0
    t = 0.0
    while t < dur:
        idx = round((inicio + t) * FPS)
        eq = lec.cuadro(idx)
        if eq is None:
            break
        gente = det.personas_360(eq, ori.C(idx))
        elegido = None
        if gente:
            if ultimo is None:
                if objetivo:
                    elegido = min(gente, key=lambda p: _dist_ang((p["yaw"], p["pitch"]), objetivo))
                else:
                    elegido = max(gente, key=lambda p: p["alto"])
            else:
                limite = 20 + 60 * (paso + perdido)
                cerca = [p for p in gente if _dist_ang((p["yaw"], p["pitch"]), ultimo[:2]) < limite]
                if cerca:
                    elegido = min(cerca, key=lambda p: _dist_ang((p["yaw"], p["pitch"]), ultimo[:2])
                                  + 0.3 * abs(p["alto"] - ultimo[2]))
                elif perdido > 1.5:  # se perdió: reengancha a la persona más grande
                    elegido = max(gente, key=lambda p: p["alto"])
        if elegido:
            yw = elegido["yaw"]
            if ultimo is not None:  # desenvolver el yaw respecto al anterior
                yw = ultimo[0] + ((yw - ultimo[0] + 180) % 360 - 180)
            ultimo = (yw, elegido["pitch"], elegido["alto"])
            pista.append((t, *ultimo))
            perdido = 0.0
        else:
            perdido += paso
        t += paso
    lec.cerrar()
    log(f"seguir: {len(pista)} detecciones en {time.time() - t0:.1f} s")
    if not pista:
        raise RuntimeError("No encontré personas en el clip")
    # Suavizado One-Euro sobre el VECTOR de dirección (no sobre yaw/pitch): cerca del nadir, donde queda la
    # persona con bastón de selfie, un paso chico cambia mucho el yaw y el filtro en ángulos da tirones.
    lento = modo == "tercera"
    filtros = [UnoEuro(0.2 if lento else 0.35, 0.3 if lento else 0.6) for _ in range(3)]
    f_alto = UnoEuro(0.15, 0.0)
    keys, t_prev, yaw_prev = [], None, None
    for t, yw, pt, alto in pista:
        dt = paso if t_prev is None else max(1e-3, t - t_prev)
        t_prev = t
        v = angulos_a_dir(yw, pt)
        v = np.array([f(float(c), dt) for f, c in zip(filtros, v)])
        yw, pt = dir_a_angulos(v)
        if yaw_prev is not None:
            yw = yaw_prev + ((yw - yaw_prev + 180) % 360 - 180)
        yaw_prev = yw
        alto = f_alto(alto, dt)
        if modo == "tercera":
            fov = fov_fijo or 105.0
            vfov = _vfov(fov)
            pitch = pt + vfov * 0.2  # persona en el tercio inferior, mirando hacia adelante
        else:
            # la persona ocupa ~45 % del alto; vfov >= 80 (hfov ~50) porque con un proxy 4K más zoom se ve suave
            vfov = float(np.clip(alto / 0.45, 80, 115))
            fov = fov_fijo or _hfov(vfov)
            pitch = pt + alto * 0.08
        keys.append({"t": round(t, 3), "yaw": round(yw, 2), "pitch": round(float(np.clip(pitch, -85, 60)), 2),
                     "fov": round(fov, 2), "ease": "spline"})
    if keys[0]["t"] > 0:
        keys.insert(0, {**keys[0], "t": 0.0})
    spec = {"src": str(src), "inicio": inicio, "dur": dur, "estab": estab, "modo": modo_estab, "nivel": nivel,
            "keys": keys}
    out_keys = ruta(out_keys or SALIDAS / f"seguir_{src.stem}.json")
    out_keys.parent.mkdir(parents=True, exist_ok=True)
    json.dump(spec, open(out_keys, "w"), indent=1, ensure_ascii=False)
    log(json.dumps({"keys": str(out_keys), "n_keys": len(keys)}, ensure_ascii=False))
    return spec, out_keys


def _vfov(hfov, aspecto=H / W):
    return math.degrees(2 * math.atan(math.tan(math.radians(min(hfov, 170)) / 2) * aspecto))


def _hfov(vfov, aspecto=H / W):
    return math.degrees(2 * math.atan(math.tan(math.radians(vfov) / 2) / aspecto))


# ------------------------------------------------------------ tiny planet

def spec_planeta(src, inicio=0.0, dur=6.0, giro=40.0, a_normal=None, yaw_final=0.0, fov_final=80.0):
    """Tiny planet que gira `giro` grados; con a_normal=s termina desenrollándose a la vista normal."""
    keys = [{"t": 0, "planeta": True, "yaw": 0.0, "ease": "lineal"}]
    if a_normal:
        t_sale = max(0.5, dur - a_normal)
        keys.append({"t": t_sale, "planeta": True, "yaw": giro, "ease": "lineal"})
        keys.append({"t": dur, "yaw": yaw_final, "pitch": 0, "fov": fov_final, "ease": "suave"})
    else:
        keys.append({"t": dur, "planeta": True, "yaw": giro, "ease": "lineal"})
    return {"src": str(src), "inicio": inicio, "dur": dur, "keys": keys,
            "out": str(SALIDAS / f"planeta_{ruta(src).stem}.mp4")}


# ------------------------------------------------------------ CLI

def _nivel_arg(s):
    if s in ("auto", "no", "gyro"):
        return s
    p, r = (float(x) for x in s.split(","))
    return [p, r]


def main():
    ap = argparse.ArgumentParser(description="Reencuadre 360 -> 9:16")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def comunes(p):
        p.add_argument("src")
        p.add_argument("--inicio", type=float, default=0.0)
        p.add_argument("--dur", type=float)
        p.add_argument("--estab", default="no", choices=["no", "visual", "gyro", "auto"])
        p.add_argument("--modo", default="rumbo", choices=["rumbo", "bloqueo"])
        p.add_argument("--nivel", default="auto", type=_nivel_arg, help="auto | no | gyro | pitch,roll")

    p = sub.add_parser("proxy")
    p.add_argument("src")
    p.add_argument("--ancho", type=int, default=3840)
    p.add_argument("--fov", type=float, default=INSV["fov"], help="ih_fov/iv_fov del stitch .insv")
    p.add_argument("--orden", default=INSV["orden"], help="10 = pista 1 frontal (X5), 01 = pista 0 frontal")
    p.add_argument("--rot-frente", type=int, default=0)
    p.add_argument("--rot-atras", type=int, default=0)
    p.add_argument("--forzar", action="store_true")

    p = sub.add_parser("hojas")
    comunes(p)
    p.add_argument("--n", type=int, default=6)
    p.add_argument("--por-hoja", type=int, default=3)
    p.add_argument("--vistas", default="cubo", choices=list(VISTAS))
    p.add_argument("--personas", action="store_true")
    p.add_argument("--out")

    p = sub.add_parser("render")
    p.add_argument("--keys", required=True)
    p.add_argument("--out")

    p = sub.add_parser("planeta")
    comunes(p)
    p.add_argument("--giro", type=float, default=40)
    p.add_argument("--a-normal", type=float)
    p.add_argument("--yaw-final", type=float, default=0)
    p.add_argument("--out")

    p = sub.add_parser("seguir")
    comunes(p)
    p.add_argument("--tipo", default="selfie", choices=["selfie", "tercera"])
    p.add_argument("--objetivo", help="yaw,pitch aproximados de la persona a seguir (ver hojas)")
    p.add_argument("--hz", type=float, default=6)
    p.add_argument("--fov", type=float)
    p.add_argument("--render", action="store_true")
    p.add_argument("--out")

    p = sub.add_parser("telemetria")
    p.add_argument("src")

    a = ap.parse_args()
    if a.cmd == "proxy":
        crear_proxy(a.src, a.ancho, cfg_insv={"fov": a.fov, "orden": a.orden, "rot_frente": a.rot_frente,
                                              "rot_atras": a.rot_atras}, forzar=a.forzar)
    elif a.cmd == "hojas":
        hojas(a.src, a.inicio, a.dur, a.n, a.por_hoja, a.vistas, a.estab, a.modo, a.nivel, a.personas, a.out)
    elif a.cmd == "render":
        spec = _cargar_spec(a.keys)
        if a.out:
            spec["out"] = a.out
        render(spec)
    elif a.cmd == "planeta":
        spec = spec_planeta(a.src, a.inicio, a.dur or 6, a.giro, a.a_normal, a.yaw_final)
        spec.update({"estab": a.estab, "modo": a.modo, "nivel": a.nivel})
        if a.out:
            spec["out"] = a.out
        render(spec)
    elif a.cmd == "seguir":
        obj = tuple(float(x) for x in a.objetivo.split(",")) if a.objetivo else None
        if obj and len(obj) == 1:
            obj = (obj[0], 0.0)
        spec, ruta_keys = seguir(a.src, a.inicio, a.dur or 10, a.tipo, obj, a.hz, a.estab, a.modo, a.nivel, a.fov)
        if a.render:
            spec["out"] = a.out or str(ruta_keys.with_suffix(".mp4"))
            render(spec)
    elif a.cmd == "telemetria":
        imu = leer_imu(ruta(a.src))
        t, g = imu["t"], imu["gyro"]
        print(json.dumps({"camara": imu["camara"], "modelo": imu["modelo"], "muestras": len(t),
                          "hz": round((len(t) - 1) / max(1e-6, t[-1] - t[0]), 1),
                          "dur_s": round(float(t[-1] - t[0]), 2),
                          "gyro_max_dps": np.abs(g).max(0).round(1).tolist(),
                          "accl_media": imu["accl"].mean(0).round(2).tolist()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
