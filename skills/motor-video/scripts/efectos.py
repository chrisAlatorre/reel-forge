"""Efectos del motor: recorte de personas, texto detrás del sujeto, presentación de personaje y mapa de ruta.

Este módulo lo importa `render.py`; no se ejecuta solo. Las dependencias pesadas
(mediapipe, el modelo de segmentación) se cargan hasta que un spec las pide.
"""
import json
import math
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

W, H = config.W, config.H


# ------------------------------------------------------------ segmentación

def _modulo_fotos():
    """Importa `comun` del motor de fotos, si está disponible, para limitar la máscara a personas.

    Se busca en $REEL_FORGE_FOTO_SCRIPTS y, si no, en los skills hermanos de fotos.
    Es opcional: sin él la máscara sigue funcionando, solo que puede incluir animales.
    """
    rutas = [os.environ.get("REEL_FORGE_FOTO_SCRIPTS"), os.environ.get("REELFORGE_FOTO_SCRIPTS"),
             Path(__file__).resolve().parent.parent.parent / "motor-foto" / "scripts",
             Path(__file__).resolve().parent.parent.parent / "edicion-fotos" / "scripts"]
    for r in rutas:
        if r and Path(r).is_dir():
            if str(r) not in sys.path:
                sys.path.insert(0, str(r))
            try:
                import comun
                return comun
            except ImportError:
                continue
    return None


class Segmentador:
    """Máscara de personas (pelo + cuerpo + ropa + cara) con MediaPipe selfie multiclass y bordes afinados."""

    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        modelo = config.exigir(config.MODELO_SEG, "el modelo de segmentación",
                               "--modelo")
        self.mp = mp
        op = vision.ImageSegmenterOptions(
            base_options=BaseOptions(model_asset_path=str(modelo), delegate=BaseOptions.Delegate.CPU),
            running_mode=vision.RunningMode.IMAGE, output_confidence_masks=True)
        self.seg = vision.ImageSegmenter.create_from_options(op)
        self.fotos = _modulo_fotos()

    def mascara(self, rgb):
        h, w = rgb.shape[:2]
        f = min(1.0, 1024 / max(h, w))
        chica = np.ascontiguousarray(cv2.resize(rgb, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA))
        res = self.seg.segment(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=chica))
        fondo = res.confidence_masks[0].numpy_view().astype(np.float32)
        m = np.clip(1 - np.squeeze(fondo), 0, 1)
        m = cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR)
        m = cv2.GaussianBlur(m, (0, 0), max(1.0, w / 900))  # guidedFilter dejaba bloques NaN/inf
        m = np.nan_to_num(m, nan=0.0, posinf=1.0, neginf=0.0)  # NaN en la máscara = recuadros negros en el video
        m = np.clip((m - 0.15) / 0.7, 0, 1)
        # Solo personas: el modelo "selfie" a veces toma animales peludos como pelo humano.
        # Si el motor de fotos está disponible, se limita con la silueta de Pose, dilatada
        # para no comerse el contorno.
        if self.fotos is not None:
            try:
                personas = self.fotos.detectar_personas(rgb.astype(np.float32) / 255.0)
                if personas:
                    pm = np.zeros((h, w), np.float32)
                    for p in personas:
                        pm = np.maximum(pm, (p["mascara"] > 0.3).astype(np.float32))
                    k = max(9, int(0.015 * max(h, w))) | 1
                    pm = cv2.dilate(pm, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
                    m = m * cv2.GaussianBlur(pm, (0, 0), k / 4)
            except Exception:
                pass
        return m


_SEG = None


def segmentador():
    global _SEG
    if _SEG is None:
        _SEG = Segmentador()
    return _SEG


# ------------------------------------------------------------ texto detrás del sujeto

def render_titulo(texto, fuente, color=(255, 255, 255), sombra=True):
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bb = tmp.textbbox((0, 0), texto, font=fuente)
    tw, th = bb[2] - bb[0] + 40, bb[3] - bb[1] + 40
    im = Image.new("RGBA", (int(tw), int(th)), (0, 0, 0, 0))
    if sombra:
        s = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(s).text((20 - bb[0], 24 - bb[1]), texto, font=fuente, fill=(0, 0, 0, 120))
        im = Image.alpha_composite(im, s.filter(ImageFilter.GaussianBlur(14)))
    ImageDraw.Draw(im).text((20 - bb[0], 20 - bb[1]), texto, font=fuente, fill=tuple(color) + (255,))
    return np.asarray(im).astype(np.float32) / 255


def texto_detras(frame, mascara, titulo, t, y_rel=0.3, entrada=0.25):
    """Pega `titulo` (RGBA float) centrado en y_rel y vuelve a poner a la persona encima."""
    h, w = titulo.shape[:2]
    e = min(1.0, t / entrada)
    s = 0.92 + 0.08 * (1 - (1 - e) ** 3)  # entra creciendo
    if s < 0.999:
        titulo = cv2.resize(titulo, (max(2, int(w * s)), max(2, int(h * s))))
        h, w = titulo.shape[:2]
    alfa_g = min(1.0, t / 0.08)
    if w > W:  # recorta a lo ancho si el título es más ancho que la pantalla
        x0 = (w - W) // 2
        titulo, w = titulo[:, x0:x0 + W], W
    x, y = (W - w) // 2, int(H * y_rel - h / 2)
    y0, y1 = max(0, y), min(H, y + h)
    sub = titulo[y0 - y:y1 - y]
    a = sub[..., 3:4] * alfa_g
    out = frame.astype(np.float32)
    zona = out[y0:y1, x:x + w]
    out[y0:y1, x:x + w] = zona * (1 - a) + sub[..., :3] * 255 * a
    m = mascara[..., None]
    out = out * (1 - m) + frame.astype(np.float32) * m
    return np.clip(out, 0, 255).astype(np.uint8)


# ------------------------------------------------------------ presentación de personaje

def presentacion(frame, mascara, t, dur, lineas_img, contorno=10, y_rel=0.62):
    """Congelado: fondo apagado y desenfocado, la persona recortada con contorno blanco y fichas que entran una por una."""
    f = frame.astype(np.float32)
    e = min(1.0, t / 0.18)
    fondo = cv2.GaussianBlur(frame, (0, 0), 6 * e + 0.01).astype(np.float32)
    gris = fondo.mean(axis=2, keepdims=True)
    fondo = (gris + (fondo - gris) * (1 - 0.6 * e)) * (1 - 0.45 * e)
    m = mascara
    borde = cv2.dilate((m > 0.5).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * contorno + 1,) * 2))
    borde = cv2.GaussianBlur(borde.astype(np.float32), (0, 0), 1.2)[..., None] * e
    out = fondo * (1 - borde) + 255 * borde
    out = out * (1 - m[..., None]) + f * m[..., None]
    # fichas: cada una entra deslizándose desde la izquierda, escalonadas
    y = int(H * y_rel)
    for k, img in enumerate(lineas_img):
        tk = t - 0.25 - k * 0.35
        if tk <= 0:
            break
        ek = min(1.0, tk / 0.2)
        h, w = img.shape[:2]
        x = max(0, int(70 - (1 - ek) * 120))
        a = img[..., 3:4] * ek
        x1 = min(W, x + w)
        out[y:y + h, x:x1] = out[y:y + h, x:x1] * (1 - a[:, :x1 - x]) + img[:, :x1 - x, :3] * 255 * a[:, :x1 - x]
        y += h + 14
    return np.clip(out, 0, 255).astype(np.uint8)


def ficha(texto, fuente, fondo=(255, 255, 255), color=(15, 15, 15)):
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bb = tmp.textbbox((0, 0), texto, font=fuente)
    tw, th = int(bb[2] - bb[0] + 44), int(bb[3] - bb[1] + 30)
    im = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, tw - 1, th - 1], radius=14, fill=tuple(fondo) + (240,))
    d.text((22 - bb[0], 15 - bb[1]), texto, font=fuente, fill=tuple(color) + (255,))
    return np.asarray(im).astype(np.float32) / 255


# ------------------------------------------------------------ mapa de ruta

class Mapa:
    """Mapa estilo papel con la ruta que se va dibujando y un avión que la recorre."""

    def __init__(self, cfg, fuente):
        self.cfg = cfg
        self.lon0, self.lon1, self.lat0, self.lat1 = cfg["bbox"]
        self.fuente = fuente
        self.paradas = cfg["stops"]
        self.geojson = config.exigir(cfg.get("geojson", config.MAPA_GEOJSON), "el mapa base",
                                     "--mapa")
        # En 9:16 el mapa tiene que ser al menos tan alto como ancho*16/9; si no, la cámara no alcanza
        # a mostrar la ruta completa. Se extiende la latitud en Mercator de forma simétrica.
        falta = (self.lon1 - self.lon0) * H / W - (self._merc(self.lat1) - self._merc(self.lat0))
        if falta > 0:
            def inv(m):
                return math.degrees(2 * math.atan(math.exp(math.radians(m))) - math.pi / 2)
            self.lat1 = inv(self._merc(self.lat1) + falta / 2)
            self.lat0 = inv(self._merc(self.lat0) - falta / 2)
        self.BW = W * 3
        self.BH = int(self.BW * (self._merc(self.lat1) - self._merc(self.lat0)) / (self.lon1 - self.lon0))
        self.base = self._base()

    @staticmethod
    def _merc(la):
        return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(la) / 2)))

    def _xy(self, lon, lat):
        # Mercator con la misma escala en x y en y (con escalas distintas salía estirado en vertical)
        k = self.BW / (self.lon1 - self.lon0)
        return (lon - self.lon0) * k, (self._merc(self.lat1) - self._merc(lat)) * k

    def _base(self):
        im = Image.new("RGB", (self.BW, self.BH), (205, 222, 226))  # mar
        d = ImageDraw.Draw(im)
        with open(self.geojson) as fh:
            geo = json.load(fh)
        for feat in geo["features"]:
            g = feat["geometry"]
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            for poly in polys:
                anillo = poly[0]
                if not any(self.lon0 - 20 < p[0] < self.lon1 + 20 and self.lat0 - 20 < p[1] < self.lat1 + 20
                           for p in anillo):
                    continue
                pts = [self._xy(max(-179, min(179, p[0])), max(-80, min(80, p[1]))) for p in anillo]
                d.polygon(pts, fill=(243, 236, 222), outline=(170, 160, 140))
        im = im.filter(ImageFilter.GaussianBlur(0.6))
        return np.asarray(im)

    def frame(self, t, dur):
        p = min(1.0, max(0.0, (t - 0.15) / (dur * 0.72)))
        p = p * p * (3 - 2 * p)  # ease in-out
        pts = [self._xy(lo, la) for lo, la, _ in self.paradas]
        seglen = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        total = sum(seglen)
        recorrido = p * total
        # posición del avión sobre la polilínea
        acum, pos = 0, pts[0]
        for i, L in enumerate(seglen):
            if acum + L >= recorrido:
                k = (recorrido - acum) / max(L, 1e-6)
                pos = (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k)
                break
            acum += L
        else:
            pos = pts[-1]
        # cámara: arranca mostrando toda la ruta y termina acercándose a la última parada
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        c0 = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        ancho0 = max((max(xs) - min(xs)) * 1.5, (max(ys) - min(ys)) * 1.5 * W / H, W * 0.5)
        ancho0 = min(ancho0, self.BH * W / H * 0.98, self.BW * 0.98)
        ancho1 = ancho0 / 2.2
        c1 = pts[-1]
        k = p ** 1.6
        cxv, cyv = c0[0] + (c1[0] - c0[0]) * k, c0[1] + (c1[1] - c0[1]) * k
        cw = ancho0 * (ancho1 / ancho0) ** k
        ch = cw * H / W
        cxv = float(np.clip(cxv, cw / 2, self.BW - cw / 2))
        cyv = float(np.clip(cyv, ch / 2, self.BH - ch / 2))
        x0, y0 = cxv - cw / 2, cyv - ch / 2
        M = np.float32([[W / cw, 0, -x0 * W / cw], [0, H / ch, -y0 * H / ch]])
        base = cv2.warpAffine(self.base, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        im = Image.fromarray(base)
        d = ImageDraw.Draw(im, "RGBA")

        def a_pantalla(q):
            return ((q[0] - x0) * W / cw, (q[1] - y0) * H / ch)

        # todas las paradas tenues desde el inicio, para dar contexto
        for q0 in pts:
            q = a_pantalla(q0)
            d.ellipse([q[0] - 9, q[1] - 9, q[0] + 9, q[1] + 9], fill=(120, 110, 100, 150))
        # ruta punteada hasta donde va el avión
        acum = 0
        for i, L in enumerate(seglen):
            a, b = pts[i], pts[i + 1]
            hasta = min(1.0, max(0.0, (recorrido - acum) / max(L, 1e-6)))
            acum += L
            if hasta <= 0:
                break
            n = max(2, int(L / 26 * hasta))
            for j in range(n):
                if j % 2:
                    continue
                k0, k1 = j / (L / 26), min(hasta, (j + 1) / (L / 26))
                if k0 >= hasta:
                    break
                p0 = a_pantalla((a[0] + (b[0] - a[0]) * k0, a[1] + (b[1] - a[1]) * k0))
                p1 = a_pantalla((a[0] + (b[0] - a[0]) * k1, a[1] + (b[1] - a[1]) * k1))
                d.line([p0, p1], fill=(200, 45, 45, 255), width=9)
        # paradas ya alcanzadas
        acum, ocupados = 0, []
        for i, (lo, la, nombre) in enumerate(self.paradas):
            if i > 0:
                acum += seglen[i - 1]
            if recorrido + 1 < acum:
                break
            q = a_pantalla(pts[i])
            d.ellipse([q[0] - 14, q[1] - 14, q[0] + 14, q[1] + 14], fill=(200, 45, 45, 255),
                      outline=(255, 255, 255, 255), width=5)
            ocupados.append((q[0] - 16, q[1] - 16, q[0] + 16, q[1] + 16))
        # etiquetas: se prueban 8 posiciones alrededor del punto (a 3 radios) y se usa la primera
        # libre, para que no se encimen. Si la etiqueta queda lejos, se dibuja una línea guía.
        acum = 0
        for i, (lo, la, nombre) in enumerate(self.paradas):
            if i > 0:
                acum += seglen[i - 1]
            if recorrido + 1 < acum:
                break
            q = a_pantalla(pts[i])
            if not (-50 < q[0] < W + 50 and -50 < q[1] < H + 50):
                continue  # parada fuera de cuadro: sin etiqueta
            bb = d.textbbox((0, 0), nombre, font=self.fuente)
            tw, th = bb[2] - bb[0] + 28, bb[3] - bb[1] + 22
            opciones = []
            for r in (36, 90, 150):
                opciones += [(q[0] + r, q[1] - th / 2), (q[0] - r - tw, q[1] - th / 2),
                             (q[0] - tw / 2, q[1] - r - th), (q[0] - tw / 2, q[1] + r),
                             (q[0] + r * 0.7, q[1] - r * 0.7 - th), (q[0] - r * 0.7 - tw, q[1] - r * 0.7 - th),
                             (q[0] + r * 0.7, q[1] + r * 0.7), (q[0] - r * 0.7 - tw, q[1] + r * 0.7)]

            def choca(rc):
                rx0, ry0, rx1, ry1 = rc
                # fuera de la zona segura 9:16 no se pone etiqueta
                if rx0 < 40 or rx1 > W - 40 or ry0 < config.SEGURA["top"] + 10 or ry1 > H - config.SEGURA["bottom"] + 60:
                    return True
                return any(not (rx1 + 8 < a or rx0 - 8 > c or ry1 + 8 < b or ry0 - 8 > e) for a, b, c, e in ocupados)

            elegida = next((rc for rc in ((ox, oy, ox + tw, oy + th) for ox, oy in opciones) if not choca(rc)), None)
            if elegida is None:
                fx = min(W - 40 - tw, max(40, q[0] + 36))
                fy = q[1] - th / 2
                elegida = (fx, fy, fx + tw, fy + th)
            ex0, ey0, ex1, ey1 = elegida
            cx, cy = min(max(q[0], ex0), ex1), min(max(q[1], ey0), ey1)
            if abs(cx - q[0]) + abs(cy - q[1]) > 50:
                d.line([q, (cx, cy)], fill=(255, 255, 255, 230), width=4)
            d.rounded_rectangle([ex0, ey0, ex1, ey1], radius=12, fill=(255, 255, 255, 240))
            d.text((ex0 + 14 - bb[0], ey0 + 11 - bb[1]), nombre, font=self.fuente, fill=(20, 20, 20, 255))
            ocupados.append(elegida)
        # avión
        if p < 1:
            q = a_pantalla(pos)
            d.ellipse([q[0] - 26, q[1] - 26, q[0] + 26, q[1] + 26], fill=(255, 255, 255, 255))
            d.polygon([(q[0] - 14, q[1] + 12), (q[0] + 18, q[1]), (q[0] - 14, q[1] - 12), (q[0] - 6, q[1])],
                      fill=(200, 45, 45, 255))
        return np.asarray(im)
