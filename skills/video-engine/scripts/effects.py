"""Engine effects: person cutout, text behind the subject, character intro and route map.

This module is imported by `render.py`; it doesn't run on its own. The heavy dependencies
(mediapipe, the segmentation model) are only loaded when a spec asks for them.
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


# ------------------------------------------------------------ segmentation

def _photo_module():
    """Imports the photo engine's `common` module, if available, to limit the mask to people.

    It looks in $REEL_FORGE_PHOTO_SCRIPTS and then in sibling photo skills. It is optional:
    without it the mask still works, it just may include animals.
    """
    paths = [os.environ.get("REEL_FORGE_PHOTO_SCRIPTS"),
             Path(__file__).resolve().parent.parent.parent / "photo-engine" / "scripts"]
    for p in paths:
        if p and Path(p).is_dir():
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))
            try:
                import common
                return common
            except ImportError:
                continue
    return None


class Segmenter:
    """A person mask (hair + body + clothes + face) with MediaPipe selfie multiclass and refined edges."""

    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        model = config.require(config.SEG_MODEL, "the segmentation model", "--model")
        self.mp = mp
        op = vision.ImageSegmenterOptions(
            base_options=BaseOptions(model_asset_path=str(model), delegate=BaseOptions.Delegate.CPU),
            running_mode=vision.RunningMode.IMAGE, output_confidence_masks=True)
        self.seg = vision.ImageSegmenter.create_from_options(op)
        self.photos = _photo_module()

    def mask(self, rgb):
        h, w = rgb.shape[:2]
        f = min(1.0, 1024 / max(h, w))
        small = np.ascontiguousarray(cv2.resize(rgb, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA))
        res = self.seg.segment(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=small))
        background = res.confidence_masks[0].numpy_view().astype(np.float32)
        m = np.clip(1 - np.squeeze(background), 0, 1)
        m = cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR)
        m = cv2.GaussianBlur(m, (0, 0), max(1.0, w / 900))  # guidedFilter left NaN/inf blocks
        m = np.nan_to_num(m, nan=0.0, posinf=1.0, neginf=0.0)  # a NaN in the mask = black rectangles in the video
        m = np.clip((m - 0.15) / 0.7, 0, 1)
        # People only: the "selfie" model sometimes takes furry animals for human hair.
        # If the photo engine is available, constrain with the Pose silhouette, dilated so it
        # doesn't eat the outline.
        if self.photos is not None:
            try:
                people = self.photos.detect_people(rgb.astype(np.float32) / 255.0)
                if people:
                    pm = np.zeros((h, w), np.float32)
                    for p in people:
                        pm = np.maximum(pm, (p["mask"] > 0.3).astype(np.float32))
                    k = max(9, int(0.015 * max(h, w))) | 1
                    pm = cv2.dilate(pm, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
                    m = m * cv2.GaussianBlur(pm, (0, 0), k / 4)
            except Exception:
                pass
        return m


_SEG = None


def segmenter():
    global _SEG
    if _SEG is None:
        _SEG = Segmenter()
    return _SEG


# ------------------------------------------------------------ text behind the subject

def render_title(text, typeface, color=(255, 255, 255), shadow=True):
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bb = tmp.textbbox((0, 0), text, font=typeface)
    tw, th = bb[2] - bb[0] + 40, bb[3] - bb[1] + 40
    im = Image.new("RGBA", (int(tw), int(th)), (0, 0, 0, 0))
    if shadow:
        s = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(s).text((20 - bb[0], 24 - bb[1]), text, font=typeface, fill=(0, 0, 0, 120))
        im = Image.alpha_composite(im, s.filter(ImageFilter.GaussianBlur(14)))
    ImageDraw.Draw(im).text((20 - bb[0], 20 - bb[1]), text, font=typeface, fill=tuple(color) + (255,))
    return np.asarray(im).astype(np.float32) / 255


def text_behind(frame, mask, title, t, y_rel=0.3, entry=0.25):
    """Pastes `title` (RGBA float) centred at y_rel and puts the person back on top."""
    h, w = title.shape[:2]
    e = min(1.0, t / entry)
    s = 0.92 + 0.08 * (1 - (1 - e) ** 3)  # it grows on entry
    if s < 0.999:
        title = cv2.resize(title, (max(2, int(w * s)), max(2, int(h * s))))
        h, w = title.shape[:2]
    global_alpha = min(1.0, t / 0.08)
    if w > W:  # crop the width if the title is wider than the screen
        x0 = (w - W) // 2
        title, w = title[:, x0:x0 + W], W
    x, y = (W - w) // 2, int(H * y_rel - h / 2)
    y0, y1 = max(0, y), min(H, y + h)
    sub = title[y0 - y:y1 - y]
    a = sub[..., 3:4] * global_alpha
    out = frame.astype(np.float32)
    zone = out[y0:y1, x:x + w]
    out[y0:y1, x:x + w] = zone * (1 - a) + sub[..., :3] * 255 * a
    m = mask[..., None]
    out = out * (1 - m) + frame.astype(np.float32) * m
    return np.clip(out, 0, 255).astype(np.uint8)


# ------------------------------------------------------------ character intro

def character_intro(frame, mask, t, dur, card_images, outline=10, y_rel=0.62):
    """A freeze frame: dimmed, blurred background, the person cut out with a white outline, and cards entering one by one."""
    f = frame.astype(np.float32)
    e = min(1.0, t / 0.18)
    background = cv2.GaussianBlur(frame, (0, 0), 6 * e + 0.01).astype(np.float32)
    grey = background.mean(axis=2, keepdims=True)
    background = (grey + (background - grey) * (1 - 0.6 * e)) * (1 - 0.45 * e)
    m = mask
    edge = cv2.dilate((m > 0.5).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * outline + 1,) * 2))
    edge = cv2.GaussianBlur(edge.astype(np.float32), (0, 0), 1.2)[..., None] * e
    out = background * (1 - edge) + 255 * edge
    out = out * (1 - m[..., None]) + f * m[..., None]
    # cards: each one slides in from the left, staggered
    y = int(H * y_rel)
    for k, img in enumerate(card_images):
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


def card(text, typeface, background=(255, 255, 255), color=(15, 15, 15)):
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bb = tmp.textbbox((0, 0), text, font=typeface)
    tw, th = int(bb[2] - bb[0] + 44), int(bb[3] - bb[1] + 30)
    im = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, tw - 1, th - 1], radius=14, fill=tuple(background) + (240,))
    d.text((22 - bb[0], 15 - bb[1]), text, font=typeface, fill=tuple(color) + (255,))
    return np.asarray(im).astype(np.float32) / 255


# ------------------------------------------------------------ route map

class RouteMap:
    """A paper-style map with the route being drawn and a plane travelling along it."""

    def __init__(self, cfg, typeface):
        self.cfg = cfg
        self.lon0, self.lon1, self.lat0, self.lat1 = cfg["bbox"]
        self.font = typeface
        self.stops = cfg["stops"]
        self.geojson = config.require(cfg.get("geojson", config.MAP_GEOJSON), "the base map", "--map")
        # In 9:16 the map has to be at least as tall as width*16/9; otherwise the camera can't
        # show the whole route. The latitude gets extended symmetrically in Mercator space.
        short = (self.lon1 - self.lon0) * H / W - (self._merc(self.lat1) - self._merc(self.lat0))
        if short > 0:
            def inv(m):
                return math.degrees(2 * math.atan(math.exp(math.radians(m))) - math.pi / 2)
            self.lat1 = inv(self._merc(self.lat1) + short / 2)
            self.lat0 = inv(self._merc(self.lat0) - short / 2)
        self.BW = W * 3
        self.BH = int(self.BW * (self._merc(self.lat1) - self._merc(self.lat0)) / (self.lon1 - self.lon0))
        self.base = self._base()

    @staticmethod
    def _merc(la):
        return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(la) / 2)))

    def _xy(self, lon, lat):
        # Mercator with the same scale in x and y (with different scales it came out vertically stretched)
        k = self.BW / (self.lon1 - self.lon0)
        return (lon - self.lon0) * k, (self._merc(self.lat1) - self._merc(lat)) * k

    def _base(self):
        im = Image.new("RGB", (self.BW, self.BH), (205, 222, 226))  # sea
        d = ImageDraw.Draw(im)
        with open(self.geojson) as fh:
            geo = json.load(fh)
        for feat in geo["features"]:
            g = feat["geometry"]
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            for poly in polys:
                ring = poly[0]
                if not any(self.lon0 - 20 < p[0] < self.lon1 + 20 and self.lat0 - 20 < p[1] < self.lat1 + 20
                           for p in ring):
                    continue
                pts = [self._xy(max(-179, min(179, p[0])), max(-80, min(80, p[1]))) for p in ring]
                d.polygon(pts, fill=(243, 236, 222), outline=(170, 160, 140))
        im = im.filter(ImageFilter.GaussianBlur(0.6))
        return np.asarray(im)

    def frame(self, t, dur):
        p = min(1.0, max(0.0, (t - 0.15) / (dur * 0.72)))
        p = p * p * (3 - 2 * p)  # ease in-out
        pts = [self._xy(lo, la) for lo, la, _ in self.stops]
        seglen = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        total = sum(seglen)
        travelled = p * total
        # the plane's position along the polyline
        acc, pos = 0, pts[0]
        for i, L in enumerate(seglen):
            if acc + L >= travelled:
                k = (travelled - acc) / max(L, 1e-6)
                pos = (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k)
                break
            acc += L
        else:
            pos = pts[-1]
        # camera: starts showing the whole route and ends zooming into the last stop
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        c0 = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        width0 = max((max(xs) - min(xs)) * 1.5, (max(ys) - min(ys)) * 1.5 * W / H, W * 0.5)
        width0 = min(width0, self.BH * W / H * 0.98, self.BW * 0.98)
        width1 = width0 / 2.2
        c1 = pts[-1]
        k = p ** 1.6
        cxv, cyv = c0[0] + (c1[0] - c0[0]) * k, c0[1] + (c1[1] - c0[1]) * k
        cw = width0 * (width1 / width0) ** k
        ch = cw * H / W
        cxv = float(np.clip(cxv, cw / 2, self.BW - cw / 2))
        cyv = float(np.clip(cyv, ch / 2, self.BH - ch / 2))
        x0, y0 = cxv - cw / 2, cyv - ch / 2
        M = np.float32([[W / cw, 0, -x0 * W / cw], [0, H / ch, -y0 * H / ch]])
        base = cv2.warpAffine(self.base, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        im = Image.fromarray(base)
        d = ImageDraw.Draw(im, "RGBA")

        def to_screen(q):
            return ((q[0] - x0) * W / cw, (q[1] - y0) * H / ch)

        # every stop shown faintly from the start, for context
        for q0 in pts:
            q = to_screen(q0)
            d.ellipse([q[0] - 9, q[1] - 9, q[0] + 9, q[1] + 9], fill=(120, 110, 100, 150))
        # dashed route up to where the plane is
        acc = 0
        for i, L in enumerate(seglen):
            a, b = pts[i], pts[i + 1]
            upto = min(1.0, max(0.0, (travelled - acc) / max(L, 1e-6)))
            acc += L
            if upto <= 0:
                break
            n = max(2, int(L / 26 * upto))
            for j in range(n):
                if j % 2:
                    continue
                k0, k1 = j / (L / 26), min(upto, (j + 1) / (L / 26))
                if k0 >= upto:
                    break
                p0 = to_screen((a[0] + (b[0] - a[0]) * k0, a[1] + (b[1] - a[1]) * k0))
                p1 = to_screen((a[0] + (b[0] - a[0]) * k1, a[1] + (b[1] - a[1]) * k1))
                d.line([p0, p1], fill=(200, 45, 45, 255), width=9)
        # stops already reached
        acc, taken = 0, []
        for i, (lo, la, name) in enumerate(self.stops):
            if i > 0:
                acc += seglen[i - 1]
            if travelled + 1 < acc:
                break
            q = to_screen(pts[i])
            d.ellipse([q[0] - 14, q[1] - 14, q[0] + 14, q[1] + 14], fill=(200, 45, 45, 255),
                      outline=(255, 255, 255, 255), width=5)
            taken.append((q[0] - 16, q[1] - 16, q[0] + 16, q[1] + 16))
        # labels: 8 positions around the point are tried (at 3 radii) and the first free one wins,
        # so they don't overlap. If a label ends up far away, a leader line gets drawn.
        acc = 0
        for i, (lo, la, name) in enumerate(self.stops):
            if i > 0:
                acc += seglen[i - 1]
            if travelled + 1 < acc:
                break
            q = to_screen(pts[i])
            if not (-50 < q[0] < W + 50 and -50 < q[1] < H + 50):
                continue  # stop outside the frame: no label
            bb = d.textbbox((0, 0), name, font=self.font)
            tw, th = bb[2] - bb[0] + 28, bb[3] - bb[1] + 22
            options = []
            for r in (36, 90, 150):
                options += [(q[0] + r, q[1] - th / 2), (q[0] - r - tw, q[1] - th / 2),
                            (q[0] - tw / 2, q[1] - r - th), (q[0] - tw / 2, q[1] + r),
                            (q[0] + r * 0.7, q[1] - r * 0.7 - th), (q[0] - r * 0.7 - tw, q[1] - r * 0.7 - th),
                            (q[0] + r * 0.7, q[1] + r * 0.7), (q[0] - r * 0.7 - tw, q[1] + r * 0.7)]

            def collides(rc):
                rx0, ry0, rx1, ry1 = rc
                # no label goes outside the 9:16 safe area
                if rx0 < 40 or rx1 > W - 40 or ry0 < config.SAFE["top"] + 10 or ry1 > H - config.SAFE["bottom"] + 60:
                    return True
                return any(not (rx1 + 8 < a or rx0 - 8 > c or ry1 + 8 < b or ry0 - 8 > e) for a, b, c, e in taken)

            chosen = next((rc for rc in ((ox, oy, ox + tw, oy + th) for ox, oy in options) if not collides(rc)), None)
            if chosen is None:
                fx = min(W - 40 - tw, max(40, q[0] + 36))
                fy = q[1] - th / 2
                chosen = (fx, fy, fx + tw, fy + th)
            ex0, ey0, ex1, ey1 = chosen
            cx, cy = min(max(q[0], ex0), ex1), min(max(q[1], ey0), ey1)
            if abs(cx - q[0]) + abs(cy - q[1]) > 50:
                d.line([q, (cx, cy)], fill=(255, 255, 255, 230), width=4)
            d.rounded_rectangle([ex0, ey0, ex1, ey1], radius=12, fill=(255, 255, 255, 240))
            d.text((ex0 + 14 - bb[0], ey0 + 11 - bb[1]), name, font=self.font, fill=(20, 20, 20, 255))
            taken.append(chosen)
        # the plane
        if p < 1:
            q = to_screen(pos)
            d.ellipse([q[0] - 26, q[1] - 26, q[0] + 26, q[1] + 26], fill=(255, 255, 255, 255))
            d.polygon([(q[0] - 14, q[1] + 12), (q[0] + 18, q[1]), (q[0] - 14, q[1] - 12), (q[0] - 6, q[1])],
                      fill=(200, 45, 45, 255))
        return np.asarray(im)
