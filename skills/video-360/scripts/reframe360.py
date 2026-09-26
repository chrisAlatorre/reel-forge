# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["numpy<2.3", "opencv-contrib-python<5", "pillow", "mediapipe==0.10.21", "telemetry-parser"]
# ///
"""Reframes 360 video (Insta360 X3/X4/X5 or any 2:1 equirectangular) to vertical 9:16 with a virtual camera.

Folders are configurable with $REEL_FORGE_360 (default $REEL_FORGE_HOME/360) and $REEL_FORGE_CACHE.
The full list of the plugin's variables is in docs/configuration.md.

Usage (with uv, from anywhere):
  uv run reframe360.py proxy   VID.insv|equirect.mp4 [--width 3840]     # creates the 30 fps equirect proxy
  uv run reframe360.py sheets  VID [--start 0 --dur 20 --n 6 --stab heading --level auto]
  uv run reframe360.py render  --keys keys.json                         # render with keyframes
  uv run reframe360.py planet  VID --start 3 --dur 6 [--spin 40 --to-normal 2]
  uv run reframe360.py follow  VID --start 0 --dur 12 [--type selfie|third --target 90,-20 --render]
  uv run reframe360.py telemetry VID.insv                               # reads the .insv gyroscope

Conventions (degrees):
  yaw   0 = the centre of the equirect (front), + turns right, 180 = behind. It does not wrap: to go
        from 170 to -170 the short way, write 190.
  pitch + looks up, -90 = nadir (tiny planet).  roll + tilts clockwise.
  fov   the output frame's HORIZONTAL field of view.
  d     projection: 0 = rectilinear (normal), 1 = stereographic (tiny planet); in between = a soft
        wide angle. If you leave it out, it gets computed from the fov (automatic).

keys.json:
{
  "src": "~/Movies/Reel Forge/360/VID.insv",  "out": "~/Movies/Reel Forge/360/output/x.mp4",
  "start": 12.0, "dur": 12, "fps": 30, "speed": 1.0, "audio": true,
  "stab": "no|visual|gyro|auto", "mode": "heading|lock", "level": "auto|no|gyro|[pitch, roll]",
  "blur": 0.35,                          # the virtual shutter (a fraction of a frame) for motion blur
  "keys": [
    {"t": 0,   "planet": true, "yaw": 0},                    # tiny planet
    {"t": 2.5, "planet": true, "yaw": 60},                   # spin the planet
    {"t": 4.0, "yaw": 90, "pitch": 0, "fov": 80, "ease": "smooth"},   # planet -> normal view
    {"t": 7.0, "yaw": 130, "punch": 0.25},                   # slow pan + an fov punch on arrival
    {"t": 7.35, "yaw": 300, "ease": "whip"},                 # whip-pan with automatic motion blur
    {"t": 10, "yaw": 310, "fov": 70}
  ]
}
ease: linear | smooth | in | out | whip | cut | spline. A key's ease says how you ARRIVE at it.
Missing keys are inherited from the previous one.
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

# Working folders. They can be moved with environment variables, so the plugin imposes no paths.
#   REEL_FORGE_360         360 root (originals, proxies and output).
#                          Default: $REEL_FORGE_HOME/360
#   REEL_FORGE_HOME        project root. Default: ~/Movies/Reel Forge on macOS, ~/Videos/... elsewhere
#   REEL_FORGE_CACHE       downloadable models and caches. Default: ~/.cache/reel-forge
#   REEL_FORGE_LABEL_FONT  ttf for the sheet labels (optional).
#                          Default: $REEL_FORGE_CACHE/fonts/Montserrat[wght].ttf (resources.py downloads it).
_MOVIES = Path.home() / "Movies"
HOME = Path(os.path.expanduser(os.environ.get(
    "REEL_FORGE_HOME", str((_MOVIES if _MOVIES.is_dir() else Path.home() / "Videos") / "reel-forge"))))
ROOT = Path(os.path.expanduser(os.environ.get("REEL_FORGE_360", str(HOME / "360"))))
PROXIES = ROOT / "proxies"
OUTPUT = ROOT / "output"
CACHE = Path(os.path.expanduser(os.environ.get("REEL_FORGE_CACHE", "~/.cache/reel-forge")))
# The sheet labels' font. By default, the one `video-engine/scripts/resources.py` downloads into
# $REEL_FORGE_CACHE/fonts; if that isn't there either, the sheets fall back to PIL's (uglier, but legible).
LABEL_FONT = Path(os.path.expanduser(os.environ.get(
    "REEL_FORGE_LABEL_FONT", str(CACHE / "fonts" / "Montserrat[wght].ttf"))))
PEOPLE_MODEL = CACHE / "efficientdet_lite0.tflite"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/"
             "float32/latest/efficientdet_lite0.tflite")
W, H = 1080, 1920
FPS = 30
PLANET = {"pitch": -90.0, "roll": 0.0, "fov": 200.0, "d": 1.0}
# Parameters for stitching .insv with v360 (X3/X4/X5: two 3840x3840 HEVC tracks, track 0 = rear lens,
# track 1 = front). ih_fov: the stored usable disc measures ~186-194° according to other people's
# tests; 193 by default.
INSV = {"fov": 193.0, "order": "10", "rot_front": 0, "rot_back": 0}


def path(p):
    return Path(os.path.expanduser(str(p)))


def log(msg):
    print(msg, flush=True)


# ------------------------------------------------------------ ffmpeg / proxies

def probe(src):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=index,codec_type,width,height,r_frame_rate:format=duration", "-of", "json", str(src)],
                       capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    videos = [s for s in d["streams"] if s["codec_type"] == "video" and s.get("width")]
    num, den = videos[0].get("r_frame_rate", "30/1").split("/")
    return {"videos": videos, "audio": any(s["codec_type"] == "audio" for s in d["streams"]),
            "fps": float(num) / float(den), "dur": float(d["format"].get("duration", 0))}


def is_dual_fisheye(src):
    return path(src).suffix.lower() in (".insv", ".lrv")


def insv_filter(info, width, fps, cfg):
    """The ffmpeg filter that joins the .insv's two lenses and turns them into an equirect with v360."""
    rot = {0: "", 90: "transpose=1,", 180: "hflip,vflip,", 270: "transpose=2,"}
    fov = cfg["fov"]
    v360 = (f"v360=input=dfisheye:output=e:ih_fov={fov}:iv_fov={fov}:w={width}:h={width // 2}"
            f":interp=cubic")
    if len(info["videos"]) >= 2:
        # Two tracks (X3/X4/X5 at 5.7K+): v360 expects [front | back] side by side
        front, back = ("1", "0") if cfg["order"] == "10" else ("0", "1")
        return (f"[0:v:{front}]{rot[cfg['rot_front']]}null[f];[0:v:{back}]{rot[cfg['rot_back']]}null[b];"
                f"[f][b]hstack=inputs=2:shortest=1,{v360},fps={fps}[v]")
    # One track with both circles side by side (LRV, older models)
    if cfg["order"] == "10":  # back | front -> the halves get swapped
        return (f"[0:v:0]split[a][c];[a]crop=iw/2:ih:iw/2:0[f];[c]crop=iw/2:ih:0:0[b];"
                f"[f][b]hstack,{v360},fps={fps}[v]")
    return f"[0:v:0]{v360},fps={fps}[v]"


# The proxy is only ever read for sheets, tracking and reframing at 1080: crf 16 made it larger
# than the 8K original (~160 Mbps), so ten clips ate 5 GB. 20 is visually identical for that job.
PROXY_CRF = int(os.environ.get("REEL_FORGE_PROXY_CRF", "20"))

# Levelling from the image alone needs evidence. These two guards exist because `level: "auto"`
# with `stab: "no"` used to rotate a horizon by 34° on the strength of two readings.
MIN_LEVEL_SAMPLES = 3
MAX_VISUAL_TILT = 25.0


def proxy_path(src, width):
    return PROXIES / f"{path(src).stem}_{width}.mp4"


def make_proxy(src, width=3840, fps=FPS, insv_cfg=None, force=False, crf=PROXY_CRF):
    """Brings the 360 down to a `width` x `width/2` equirect at `fps` (h264). Running v360 over 8K
    frame by frame is glacial; everything else works on this proxy."""
    src = path(src)
    out = proxy_path(src, width)
    if out.exists() and not force and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    PROXIES.mkdir(parents=True, exist_ok=True)
    info = probe(src)
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-stats", "-y"]
    if is_dual_fisheye(src):
        cmd += ["-hwaccel", "videotoolbox", "-i", str(src), "-filter_complex",
                insv_filter(info, width, fps, {**INSV, **(insv_cfg or {})}), "-map", "[v]"]
    else:
        cmd += ["-i", str(src), "-vf", f"scale={width}:{width // 2}:flags=area,fps={fps}", "-map", "0:v:0"]
    if info["audio"]:
        cmd += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-g", "30", str(out)]
    t0 = time.time()
    log(f"proxy: {src.name} -> {out.name}")
    subprocess.run(cmd, check=True)
    log(f"proxy ready in {time.time() - t0:.1f} s ({info['dur']:.1f} s of video)")
    return out


class Reader:
    """Reads frames from the proxy through an ffmpeg pipe, starting at frame `f0`."""

    def __init__(self, proxy, f0=0, fps=FPS, size=None, grey=False):
        info = probe(proxy)
        v = info["videos"][0]
        self.w, self.h = size or (v["width"], v["height"])
        self.channels = 1 if grey else 3
        vf = [f"scale={self.w}:{self.h}:flags=area"] if size else []
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{f0 / fps:.4f}", "-i", str(proxy)]
        cmd += (["-vf", ",".join(vf)] if vf else []) + ["-f", "rawvideo", "-pix_fmt", "gray" if grey else "rgb24", "-"]
        # stderr silenced: closing the pipe halfway makes ffmpeg complain ("Error muxing a packet")
        self.p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 8)
        self.i = f0 - 1
        self.last = None

    def read(self):
        n = self.w * self.h * self.channels
        raw = self.p.stdout.read(n)
        if len(raw) < n:
            return None
        self.i += 1
        shape = (self.h, self.w) if self.channels == 1 else (self.h, self.w, 3)
        self.last = np.frombuffer(raw, np.uint8).reshape(shape)
        return self.last

    def frame(self, idx):
        """Advances to frame idx (forward only). At the end of the clip it repeats the last one."""
        while self.i < idx:
            if self.read() is None:
                break
        return self.last

    def close(self):
        self.p.stdout.close()
        self.p.kill()


# ------------------------------------------------------------ geometry

def rot_yaw(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rot_pitch(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, s], [0, -s, c]])


def rot_roll(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]])


def camera_rotation(yaw, pitch, roll=0.0):
    """The camera -> world matrix. Axes: x right, y up, z forward."""
    return rot_yaw(math.radians(yaw)) @ rot_pitch(math.radians(pitch)) @ rot_roll(math.radians(roll))


def rodrigues(v):
    return cv2.Rodrigues(np.asarray(v, np.float64).reshape(3, 1))[0]


def rot_vector(R):
    return cv2.Rodrigues(np.asarray(R, np.float64))[0].ravel()


def orthonormal(R):
    u, _, vt = np.linalg.svd(R)
    return u @ vt


def rotation_between(a, b):
    """The minimal rotation that takes vector a to b."""
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    axis = np.cross(a, b)
    s = np.linalg.norm(axis)
    if s < 1e-9:
        return np.eye(3)
    return rodrigues(axis / s * math.atan2(s, float(np.dot(a, b))))


def dir_to_angles(v):
    """A (world) vector -> (yaw, pitch) in degrees."""
    v = v / np.linalg.norm(v)
    return math.degrees(math.atan2(v[0], v[2])), math.degrees(math.asin(np.clip(v[1], -1, 1)))


def angles_to_dir(yaw, pitch):
    y, p = math.radians(yaw), math.radians(pitch)
    return np.array([math.cos(p) * math.sin(y), math.sin(p), math.cos(p) * math.cos(y)])


def max_fov(d):
    """The largest horizontal fov representable with projection d (rectilinear < 180°)."""
    return 2 * math.degrees(math.acos(-d)) - 12


def auto_d(fov):
    return float(np.clip((fov - 90) / 110, 0, 1))


@lru_cache(maxsize=6)
def rays(w, h, fov, d):
    """Camera rays (h, w, 3) for the general perspective: the projection centre sits at distance d
    behind the sphere's centre (d=0 gnomonic, d=1 stereographic). r = (d+1) sin θ / (d + cos θ)."""
    fov = min(fov, max_fov(d))
    half = math.radians(fov) / 2
    r_edge = (d + 1) * math.sin(half) / (d + math.cos(half))
    x = ((np.arange(w, dtype=np.float32) + 0.5) / w * 2 - 1) * r_edge
    y = ((0.5 - (np.arange(h, dtype=np.float32) + 0.5) / h) * 2) * r_edge * h / w
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


def remap_tables(M, w, h, fov, d, src_w, src_h):
    """Remap tables: output frame -> source equirect pixel. M = correction @ camera.
    The rays get rotated at half resolution and the (smooth) vector field gets scaled up with
    linear interpolation: the same result to the eye and ~2.5x faster. arctan2/arcsin do run at
    full resolution."""
    if w >= 400 and h >= 400:
        ry = rays(w // 2, h // 2, round(fov, 3), round(d, 4))
        v = cv2.resize(ry @ M.T.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    else:
        v = rays(w, h, round(fov, 3), round(d, 4)) @ M.T.astype(np.float32)
    x, y, z = v[..., 0], v[..., 1], v[..., 2]
    lon = np.arctan2(x, z)
    lat = np.arctan2(y, np.hypot(x, z))
    mx = (lon * np.float32(1 / (2 * np.pi)) + np.float32(0.5)) * np.float32(src_w) - np.float32(0.5)
    my = np.clip((np.float32(0.5) - lat * np.float32(1 / np.pi)) * np.float32(src_h) - np.float32(0.5), 0, src_h - 1)
    return mx, my


def view(eq, C, yaw, pitch, roll=0.0, fov=90.0, d=0.0, w=W, h=H, interp=cv2.INTER_LINEAR):
    """Renders a virtual camera over the equirect `eq`. C: the correction (virtual world -> source)."""
    M = C @ camera_rotation(yaw, pitch, roll)
    mx, my = remap_tables(M, w, h, fov, d, eq.shape[1], eq.shape[0])
    return cv2.remap(eq, mx, my, interp, borderMode=cv2.BORDER_WRAP)


# ------------------------------------------------------------ orientation: stabilization and levelling

def _pixels_to_vectors(pts, w, h):
    lon = ((pts[:, 0] + 0.5) / w - 0.5) * 2 * np.pi
    lat = (0.5 - (pts[:, 1] + 0.5) / h) * np.pi
    return np.stack([np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon)], 1)


def kabsch(a, b):
    """The R that minimizes |b - R a| (rows = vectors)."""
    u, _, vt = np.linalg.svd(a.T @ b)
    s = np.diag([1, 1, np.sign(np.linalg.det(vt.T @ u.T))])
    return vt.T @ s @ u.T


def ransac_rotation(a, b, threshold_deg=0.45, iters=150, rng=None):
    """The rotation between two equirect frames from tracked points, robust to people moving."""
    rng = rng or np.random.default_rng(0)
    if len(a) < 8:
        return np.eye(3), 0
    cos_t = math.cos(math.radians(threshold_deg))
    best, best_n = None, -1
    for _ in range(iters):
        idx = rng.choice(len(a), 3, replace=False)
        R = kabsch(a[idx], b[idx])
        n = int((((a @ R.T) * b).sum(1) > cos_t).sum())
        if n > best_n:
            best, best_n = R, n
    inliers = ((a @ best.T) * b).sum(1) > cos_t
    if inliers.sum() >= 6:
        best = kabsch(a[inliers], b[inliers])
    return best, int(inliers.sum())


def visual_rotations(proxy, lat_min=-20, lat_max=70, width=1024):
    """ΔR between consecutive frames (b = ΔR a) with corners + LK optical flow over the reduced
    equirect. The nadir (selfie stick, bike, the person themselves) and the poles get ignored."""
    reader = Reader(proxy, 0, size=(width, width // 2), grey=True)
    w, h = reader.w, reader.h
    row = np.arange(h)
    lat = (0.5 - (row + 0.5) / h) * 180
    mask = np.zeros((h, w), np.uint8)
    mask[(lat > lat_min) & (lat < lat_max), 16:w - 16] = 255
    prev = reader.read()
    deltas, inliers = [], []
    rng = np.random.default_rng(1)
    while True:
        cur = reader.read()
        if cur is None:
            break
        p0 = cv2.goodFeaturesToTrack(prev, 700, 0.01, 8, mask=mask)
        R, n = np.eye(3), 0
        if p0 is not None and len(p0) > 10:
            p1, st, _ = cv2.calcOpticalFlowPyrLK(prev, cur, p0, None, winSize=(21, 21), maxLevel=3)
            ok = st.ravel() == 1
            a = _pixels_to_vectors(p0[ok, 0], w, h)
            b = _pixels_to_vectors(p1[ok, 0], w, h)
            R, n = ransac_rotation(a, b, rng=rng)
        deltas.append(R)
        inliers.append(n)
        prev = cur
    reader.close()
    deltas, inliers = np.array(deltas), np.array(inliers)
    # A scene cut (an already edited clip) or a broken frame: almost no point matches. There is no
    # real rotation there.
    cuts = np.where(inliers < max(15, 0.12 * np.median(inliers)))[0] + 1
    deltas[cuts - 1] = np.eye(3)
    return deltas, inliers, cuts


def integrate(deltas):
    """O_t (frame t's source -> the reference = frame 0): O_{t+1} = O_t ΔR^T."""
    O = [np.eye(3)]
    for R in deltas:
        O.append(orthonormal(O[-1] @ R.T))
    return np.array(O)


def shots(n, cuts):
    """[(start, end)] of each shot between cuts."""
    b = [0] + [int(c) for c in cuts if 0 < c < n] + [n]
    return [(b[i], b[i + 1]) for i in range(len(b) - 1) if b[i + 1] > b[i]]


def read_imu(src):
    """The .insv's gyroscope (°/s) and accelerometer (m/s²) via telemetry-parser (AdrianEddy, supports X5)."""
    import telemetry_parser
    tp = telemetry_parser.Parser(str(src))
    imu = tp.normalized_imu()
    if not imu:
        raise RuntimeError("The file carries no readable IMU")
    t = np.array([s["timestamp_ms"] for s in imu]) / 1000.0
    g = np.array([s["gyro"] for s in imu], np.float64)
    a = np.array([s.get("accl") or [0, 0, 0] for s in imu], np.float64)
    return {"t": t, "gyro": g, "accl": a, "camera": tp.camera, "model": tp.model}


def _gyro_rotvec_per_frame(imu, n, fps, offset=0.0):
    """Integrates the gyro (IMU) over each frame interval -> a rotvec in radians (n-1, 3)."""
    t, g = imu["t"] + offset, np.radians(imu["gyro"])
    edges = np.arange(n) / fps
    cumulative = np.concatenate([[[0.0, 0.0, 0.0]], np.cumsum((g[1:] + g[:-1]) / 2 * np.diff(t)[:, None], 0)])
    return np.diff(np.stack([np.interp(edges, t, cumulative[:, j]) for j in range(3)], 1), axis=0)


def calibrate_imu(imu, deltas, fps):
    """Finds the IMU -> equirect rotation (and the time offset) by comparing the gyro against the
    rotation measured in the image: rotvec(ΔR) ≈ -M ω dt. That way we don't depend on the IMU's
    factory orientation."""
    visual = -np.array([rot_vector(R) for R in deltas])
    n = len(deltas) + 1
    best = None
    for offset in np.arange(-0.3, 0.301, 0.02):
        gy = _gyro_rotvec_per_frame(imu, n, fps, offset)
        moving = (np.linalg.norm(visual, axis=1) > math.radians(0.3)) & (np.linalg.norm(gy, axis=1) > 1e-4)
        if moving.sum() < 20:
            continue
        M = kabsch(gy[moving], visual[moving])
        err = float(np.median(np.linalg.norm(gy[moving] @ M.T - visual[moving], axis=1)))
        if best is None or err < best[2]:
            best = (M, offset, err, int(moving.sum()))
    if best is None:
        raise RuntimeError("The camera barely moves: the IMU can't be calibrated against the image")
    return best


def gyro_orientation(imu, M, offset, n, fps, gain=0.02):
    """O_t by integrating the gyroscope (already in equirect axes) with a tilt correction from the
    accelerometer (a Mahony-style complementary filter). Returns O and the 'up' vector in the
    reference frame."""
    rv = _gyro_rotvec_per_frame(imu, n, fps, offset) @ M.T
    t_frames = np.arange(n) / fps
    acc = np.stack([np.interp(t_frames, imu["t"] + offset, imu["accl"][:, j]) for j in range(3)], 1) @ M.T
    # Gravity: at rest the accelerometer reads +g upward. If most of it points down, flip it.
    if np.median(acc[:, 1]) < 0:
        acc = -acc
    norm = np.linalg.norm(acc, axis=1)
    still = np.abs(norm - 9.81) < 1.5
    first_second = slice(0, max(5, int(fps)))
    up_ref = acc[first_second][still[first_second]].mean(0) if still[first_second].any() else acc[0]
    up_ref = up_ref / np.linalg.norm(up_ref)
    O = [np.eye(3)]
    for i in range(n - 1):
        R = orthonormal(O[-1] @ rodrigues(rv[i]))
        if still[i + 1]:
            measured = R @ (acc[i + 1] / norm[i + 1])
            axis = np.cross(measured, up_ref)
            R = orthonormal(rodrigues(axis * gain) @ R)
        O.append(R)
    return np.array(O), up_ref


def _segments(grey):
    try:
        lsd = cv2.createLineSegmentDetector()
        seg = lsd.detect(grey)[0]
    except Exception:
        seg = cv2.ximgproc.createFastLineDetector().detect(grey)
    return np.zeros((0, 4)) if seg is None else seg.reshape(-1, 4)


def up_from_verticals(eq, C=np.eye(3), size=640, rng=None):
    """Estimates the 'up' direction (in the correction C's coordinates) from the vanishing point of
    the vertical lines (poles, buildings, trees), across 8 views of 90°. Returns (vector,
    n_segments) or None."""
    rng = rng or np.random.default_rng(2)
    normals, weights = [], []
    r_edge = math.tan(math.radians(45))
    for yaw in range(0, 360, 45):
        Rv = C @ camera_rotation(yaw, 0)
        img = cv2.cvtColor(cv2.remap(eq, *remap_tables(Rv, size, size, 90, 0, eq.shape[1], eq.shape[0]),
                                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP), cv2.COLOR_RGB2GRAY)
        for x1, y1, x2, y2 in _segments(img):
            length = math.hypot(x2 - x1, y2 - y1)
            if length < size * 0.06:
                continue
            ang = abs(math.degrees(math.atan2(x2 - x1, y2 - y1)))
            if min(ang, 180 - ang) > 40:  # near-vertical only
                continue
            p = []
            for x, y in ((x1, y1), (x2, y2)):
                c = np.array([((x + 0.5) / size * 2 - 1) * r_edge, (0.5 - (y + 0.5) / size) * 2 * r_edge, 1.0])
                p.append(Rv @ (c / np.linalg.norm(c)))
            n = np.cross(p[0], p[1])
            normals.append(n / np.linalg.norm(n))
            weights.append(length)
    if len(normals) < 12:
        return None
    N, wts = np.array(normals), np.array(weights)
    best, best_score = None, -1
    sin_t = math.sin(math.radians(1.2))
    for _ in range(400):
        i, j = rng.choice(len(N), 2, replace=False)
        u = np.cross(N[i], N[j])
        if np.linalg.norm(u) < 0.2:
            continue
        u /= np.linalg.norm(u)
        u *= np.sign(u[1]) or 1
        if u[1] < math.cos(math.radians(40)):
            continue
        s = wts[np.abs(N @ u) < sin_t].sum()
        if s > best_score:
            best, best_score = u, s
    if best is None:
        return None
    inliers = np.abs(N @ best) < sin_t
    if inliers.sum() < 12:  # with fewer matching segments the reading is noise (landscapes with no verticals)
        return None
    A = (N[inliers] * wts[inliers, None]).T @ N[inliers]
    u = np.linalg.eigh(A)[1][:, 0]
    u *= np.sign(u[1])
    return u, int(inliers.sum())


def smooth_series(x, sigma):
    if sigma <= 0 or len(x) < 3:
        return x
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    xp = np.pad(x, (r, r), mode="edge")
    return np.convolve(xp, k, mode="valid")


class Orientation:
    """The per-frame correction C_t (levelled virtual world -> frame t's source) for a proxy.

    stab: no | visual | gyro | auto (gyro if there is an .insv with an IMU, otherwise visual)
    mode: heading = fixed horizon with the front smoothly following where the camera travels
          (FlowState-style); lock = a fixed direction in the world (the keys' yaw is absolute)
    level: auto (the accelerometer if there is a gyro; otherwise vertical lines every 2 s, per shot)
           | gyro | no | [pitch, roll] by hand
    Everything is computed once per proxy (the whole clip) and cached next to it.
    """

    def __init__(self, src, proxy, stab="no", mode="heading", level="auto", heading_smooth=1.2, fps=FPS):
        self.fps = fps
        info = probe(proxy)
        self.n = max(1, round(info["dur"] * fps))
        self.O = np.repeat(np.eye(3)[None], self.n, 0)
        self.cuts = np.array([], int)
        up = None
        if stab in ("visual", "gyro", "auto"):
            O, up, self.cuts = self._stabilize(src, proxy, stab)
            m = min(len(O), self.n)
            self.O[:m] = O[:m]
        # Levelling: L_t (reference -> levelled world), per frame
        self.L = np.repeat(np.eye(3)[None], self.n, 0)
        if isinstance(level, (list, tuple)):
            self.L[:] = rot_roll(math.radians(level[1])) @ rot_pitch(math.radians(level[0]))
        elif level in ("gyro", "auto") and up is not None:
            self.L[:] = rotation_between(up, np.array([0.0, 1.0, 0.0]))
            log("level: accelerometer")
        elif level == "auto":
            cache = proxy.with_suffix(f".level-{stab}.npy")
            if cache.exists() and cache.stat().st_mtime >= proxy.stat().st_mtime:
                self.L = np.load(cache)
            else:
                self.L = self._visual_level(proxy)
                np.save(cache, self.L)
        # Smoothed heading, reset on every shot
        self.heading = None
        if stab != "no" and mode == "heading":
            front = np.einsum("nij,njk,k->ni", self.L, self.O, np.array([0.0, 0.0, 1.0]))
            h = np.arctan2(front[:, 0], front[:, 2])
            self.heading = np.zeros(self.n)
            for a, b in shots(self.n, self.cuts):
                hu = np.unwrap(h[a:b])
                self.heading[a:b] = smooth_series(hu, heading_smooth * fps) - hu[0]

    def _stabilize(self, src, proxy, stab):
        cache = proxy.with_suffix(f".orient-{stab}.npz")
        if cache.exists() and cache.stat().st_mtime >= proxy.stat().st_mtime:
            z = np.load(cache, allow_pickle=True)
            if "cuts" in z.files:  # old caches without cuts get recomputed
                log(f"orientation (cached): {z['origin']}")
                return z["O"], (z["up"] if z["up"].size else None), z["cuts"]
        t0 = time.time()
        deltas, inl, cuts = visual_rotations(proxy)
        log(f"visual stab: {len(deltas)} pairs in {time.time() - t0:.1f} s (median {int(np.median(inl))} "
            f"good points, {len(cuts)} scene cuts at {[round(c / self.fps, 1) for c in cuts]} s)")
        O, up, origin = integrate(deltas), None, "visual"
        if stab in ("gyro", "auto") and is_dual_fisheye(src):
            try:
                imu = read_imu(src)
                M, off, err, n_moving = calibrate_imu(imu, deltas, self.fps)
                O, up = gyro_orientation(imu, M, off, len(O), self.fps)
                origin = f"gyro (offset {off:+.2f} s, error {math.degrees(err):.2f}°/frame, {n_moving} frames)"
            except Exception as e:  # noqa: BLE001
                log(f"gyro unavailable ({e}); keeping the visual stabilization")
                if stab == "gyro":
                    raise
        np.savez(cache, O=O, up=up if up is not None else np.array([]), origin=origin, cuts=cuts)
        log(f"orientation: {origin}")
        return O, up, cuts

    def _visual_level(self, proxy, every_s=2.0):
        """'Up' from the vertical vanishing point every `every_s` seconds (in reference
        coordinates), filtered per shot and interpolated. It corrects the camera's tilt and the
        visual stabilization's drift."""
        t0 = time.time()
        reader = Reader(proxy, 0, size=(2048, 1024))
        L = np.repeat(np.eye(3)[None], self.n, 0)
        step = max(1, int(every_s * self.fps))
        total, tilts, unlevelled = 0, [], []
        for a, b in shots(self.n, self.cuts):
            idxs = sorted(set(list(range(a + 2, b, step)) + [max(a, b - 3)]))
            samples = []
            for idx in idxs:
                eq = reader.frame(idx)
                if eq is None:
                    break
                r = up_from_verticals(eq, self.O[idx].T)
                if r:
                    samples.append((idx, r[0]))
            total += len(samples)
            # Two readings over three seconds are noise, not a horizon: acting on them rotated a
            # river scene by 34°. Below MIN_LEVEL_SAMPLES the shot is left as it comes.
            if len(samples) < MIN_LEVEL_SAMPLES:
                unlevelled.append(f"{a / self.fps:.1f}-{b / self.fps:.1f} s")
                continue
            ts = np.array([m[0] for m in samples], float)
            us = np.array([m[1] for m in samples])
            shot_tilt = np.median([math.degrees(math.acos(np.clip(u[1] / np.linalg.norm(u), -1, 1)))
                                   for u in us])
            # A horizon that far off is nearly always a misread of the vertical lines. The gyro
            # settles it; guessing from the image does not.
            if shot_tilt > MAX_VISUAL_TILT:
                unlevelled.append(f"{a / self.fps:.1f}-{b / self.fps:.1f} s (read {shot_tilt:.0f}°)")
                continue
            if len(us) >= 3:  # a 3-point running median to drop odd readings
                us = np.array([np.median(us[max(0, i - 1):i + 2], 0) for i in range(len(us))])
            for i in range(a, b):
                u = np.array([np.interp(i, ts, us[:, j]) for j in range(3)])
                L[i] = rotation_between(u / np.linalg.norm(u), np.array([0.0, 1.0, 0.0]))
            tilts += [math.degrees(math.acos(np.clip(u[1] / np.linalg.norm(u), -1, 1))) for u in us]
        reader.close()
        if not tilts:
            log(f"level: {total} vertical-line readings, none of them usable; leaving it as it comes")
        else:
            log(f"level: {total} vertical-line readings in {time.time() - t0:.1f} s, "
                f"tilt corrected by {np.median(tilts):.1f}° (max {max(tilts):.1f}°)")
        if unlevelled:
            log(f"level: no reliable vertical lines in {unlevelled}; left as it comes. "
                "Re-run with --stab gyro (the .insv carries an IMU) or fix it with --level pitch,roll")
        return L

    def C(self, idx):
        idx = int(np.clip(idx, 0, self.n - 1))
        C = self.O[idx].T @ self.L[idx].T
        if self.heading is not None:
            C = C @ rot_yaw(self.heading[idx])
        return C


# ------------------------------------------------------------ virtual camera (keyframes)

def ease(name, u):
    u = min(1.0, max(0.0, u))
    if name == "linear":
        return u
    if name == "in":
        return u ** 3
    if name == "out":
        return 1 - (1 - u) ** 3
    if name == "whip":  # almost all the travel happens in the middle of the interval
        k = 6.0
        return 0.5 * (1 + math.tanh(k * (u - 0.5)) / math.tanh(k / 2))
    if name == "cut":
        return 1.0 if u >= 1 else 0.0
    return u * u * u * (u * (6 * u - 15) + 10)  # smooth (smootherstep)


FIELDS = ("yaw", "pitch", "roll", "fov", "d")


def prepare_keys(keys):
    """Sorts, inherits missing fields and resolves 'planet' and automatic 'd'."""
    keys = sorted([dict(k) for k in keys], key=lambda k: k["t"])
    prev = {"yaw": 0.0, "pitch": 0.0, "roll": 0.0, "fov": 80.0}
    out = []
    for k in keys:
        base = dict(prev)
        if k.get("planet"):
            base.update(PLANET)
        elif "d" not in k and prev.get("_planet"):
            base.pop("d", None)  # coming out of the planet, d goes back to automatic
        for c in FIELDS:
            if c in k:
                base[c] = float(k[c])
        inherits_d = prev.get("_d_fixed", False) and not prev.get("_planet")
        base["_d_fixed"] = "d" in k or bool(k.get("planet")) or inherits_d
        if not base["_d_fixed"]:
            base["d"] = auto_d(base["fov"])
        base["_planet"] = bool(k.get("planet"))
        base.update({"t": float(k["t"]), "ease": k.get("ease", "smooth"), "punch": float(k.get("punch", 0))})
        out.append(base)
        prev = base
    return out


def _catmull(p0, p1, p2, p3, u):
    return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * u ** 3)


def camera_at(keys, t):
    if t <= keys[0]["t"]:
        cam = {c: keys[0][c] for c in FIELDS}
    elif t >= keys[-1]["t"]:
        cam = {c: keys[-1][c] for c in FIELDS}
    else:
        i = max(j for j in range(len(keys)) if keys[j]["t"] <= t)
        a, b = keys[i], keys[i + 1]
        u = (t - a["t"]) / max(1e-6, b["t"] - a["t"])
        if b["ease"] == "spline":
            p0, p3 = keys[max(0, i - 1)], keys[min(len(keys) - 1, i + 2)]
            cam = {c: _catmull(p0[c], a[c], b[c], p3[c], u) for c in FIELDS}
        else:
            e = ease(b["ease"], u)
            cam = {c: a[c] + (b[c] - a[c]) * e for c in FIELDS}
    # punch: the fov snaps closed on arriving at the key and settles in ~0.25 s
    for k in keys:
        if k["punch"] and k["t"] <= t < k["t"] + 0.25:
            e = (t - k["t"]) / 0.25
            cam["fov"] *= 1 - k["punch"] * (1 - e) ** 3
    cam["fov"] = min(cam["fov"], max_fov(cam["d"]))
    return cam


def _angle_between(c0, c1):
    f0 = camera_rotation(c0["yaw"], c0["pitch"]) @ np.array([0, 0, 1.0])
    f1 = camera_rotation(c1["yaw"], c1["pitch"]) @ np.array([0, 0, 1.0])
    turn = math.degrees(math.acos(np.clip(f0 @ f1, -1, 1)))
    return turn + abs(c1["roll"] - c0["roll"]) * 0.5 + abs(c1["fov"] - c0["fov"]) * 0.3


def render_frame(eq, C, keys, t, fps, w, h, shutter=0.35, interp=cv2.INTER_LINEAR):
    """One frame; if the camera is turning fast, sub-frames get averaged (rotational motion blur)."""
    cam = camera_at(keys, t)
    if shutter > 0:
        dt = shutter / fps
        c0, c1 = camera_at(keys, t - dt / 2), camera_at(keys, t + dt / 2)
        degrees = _angle_between(c0, c1)
        # one sub-frame per ~0.5° of turn during the shutter; the step in pixels stays small
        n = int(np.clip(math.ceil(degrees / 0.5), 1, 24)) if degrees > 1.0 else 1
        if n > 1:
            # the sub-frames render at half resolution: the smear hides the difference and it costs 1/4
            wm, hm = w // 2, h // 2
            acc = np.zeros((hm, wm, 3), np.float32)
            for j in range(n):
                cj = camera_at(keys, t + (j / (n - 1) - 0.5) * dt)
                acc += view(eq, C, cj["yaw"], cj["pitch"], cj["roll"], cj["fov"], cj["d"], wm, hm, interp)
            return cv2.resize((acc / n).astype(np.uint8), (w, h), interpolation=cv2.INTER_CUBIC)
    return view(eq, C, cam["yaw"], cam["pitch"], cam["roll"], cam["fov"], cam["d"], w, h, interp)


# ------------------------------------------------------------ render

def _load_spec(spec):
    if isinstance(spec, (str, Path)):
        spec = json.load(open(path(spec)))
    return dict(spec)


def _prepare(spec):
    src = path(spec["src"])
    proxy = make_proxy(src, spec.get("proxy_width", 3840))
    level = spec.get("level", "auto")
    orientation = Orientation(src, proxy, spec.get("stab", "no"), spec.get("mode", "heading"), level,
                              spec.get("heading_smooth", 1.2))
    return src, proxy, orientation


def frames(spec, n=None, fps=FPS, w=W, h=H, start=None):
    """A generator of reframed RGB frames (render.py uses it for "r360" segments)."""
    spec = _load_spec(spec)
    src, proxy, orientation = _prepare(spec)
    keys = prepare_keys(spec["keys"])
    start = spec.get("start", 0.0) if start is None else start
    speed = spec.get("speed", 1.0)
    n = n or round(spec.get("dur", keys[-1]["t"]) * fps)
    f0 = round(start * FPS)
    reader = Reader(proxy, f0)
    interp = cv2.INTER_CUBIC if spec.get("quality") == "high" else cv2.INTER_LINEAR
    shutter = spec.get("blur", 0.35)
    threads = spec.get("threads", min(8, os.cpu_count() or 4))
    # Frames are read in order and rendered in parallel (numpy and cv2 release the GIL)
    with ThreadPoolExecutor(threads) as ex:
        queue = deque()
        try:
            for i in range(n):
                t = i / fps
                idx = f0 + int(round(t * speed * FPS))
                eq = reader.frame(idx)
                if eq is None:
                    raise RuntimeError(f"No frames in {proxy.name} from {start}s")
                queue.append(ex.submit(render_frame, eq, orientation.C(idx), keys, t, fps, w, h, shutter, interp))
                if len(queue) >= threads * 2:
                    yield queue.popleft().result()
            while queue:
                yield queue.popleft().result()
        finally:
            reader.close()


def render(spec):
    spec = _load_spec(spec)
    t0 = time.time()
    src, proxy, orientation = _prepare(spec)
    t_prep = time.time() - t0
    keys = prepare_keys(spec["keys"])
    fps = spec.get("fps", FPS)
    dur = spec.get("dur", keys[-1]["t"])
    n = round(dur * fps)
    out = path(spec.get("out", OUTPUT / f"{src.stem}_9x16.mp4"))
    out.parent.mkdir(parents=True, exist_ok=True)
    w, h = spec.get("w", W), spec.get("h", H)
    start, speed = spec.get("start", 0.0), spec.get("speed", 1.0)
    info = probe(proxy)
    with_audio = spec.get("audio", True) and info["audio"] and speed == 1
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", str(fps), "-i", "-"]
    if with_audio:
        cmd += ["-ss", str(start), "-t", str(dur), "-i", str(proxy), "-map", "0:v", "-map", "1:a",
                "-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(out)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t1 = time.time()
    for i, fr in enumerate(frames(spec, n, fps, w, h)):
        enc.stdin.write(np.ascontiguousarray(fr).tobytes())
        if i % 60 == 0:
            log(f"  frame {i}/{n}")
    enc.stdin.close()
    enc.wait()
    t_render = time.time() - t1
    res = {"out": str(out), "dur": dur, "frames": n, "prep_s": round(t_prep, 1), "render_s": round(t_render, 1),
           "render_fps": round(n / max(t_render, 1e-6), 1)}
    log(json.dumps(res, ensure_ascii=False))
    return res


# ------------------------------------------------------------ contact sheets

def _label_font(size):
    """The labels' font. Without LABEL_FONT (or if it isn't variable) it falls back to PIL's, which
    is legible but ugly."""
    try:
        f = ImageFont.truetype(str(LABEL_FONT), size)
    except Exception:
        return ImageFont.load_default()
    try:
        f.set_variation_by_axes([700])   # bold weight if the font is variable
    except Exception:
        pass
    return f


def _label(d, xy, text, f):
    bb = d.textbbox(xy, text, font=f)
    d.rectangle([bb[0] - 5, bb[1] - 3, bb[2] + 5, bb[3] + 3], fill=(0, 0, 0))
    d.text(xy, text, font=f, fill=(255, 255, 255))


VIEWS = {
    "cube": [("front", 0, 0), ("right", 90, 0), ("back", 180, 0), ("left", -90, 0),
             ("up", 0, 90), ("down", 0, -90)],
    "ring8": [(f"yaw {y}", y, -10) for y in (0, 45, 90, 135, 180, -135, -90, -45)],
}


def sheets(src, start=0.0, dur=None, n=6, per_sheet=3, views="cube", stab="no", mode="heading", level="auto",
           people=False, out_dir=None):
    """Contact sheets: per instant, the equirect with a yaw/pitch grid and 6 (cube) or 8 (ring)
    views, so you can decide where to point. With people=True it marks the detected people with
    their yaw/pitch."""
    src = path(src)
    proxy = make_proxy(src)
    orientation = Orientation(src, proxy, stab, mode, level)
    dur = dur or (orientation.n / FPS - start)
    out_dir = path(out_dir or OUTPUT / f"sheets_{src.stem}")
    out_dir.mkdir(parents=True, exist_ok=True)
    times = np.linspace(start, start + dur - 0.1, n)
    listing = VIEWS[views]
    EW, EH, VT = 900, 450, 225
    cols = 3 if views == "cube" else 4
    view_rows = math.ceil(len(listing) / cols)
    row_h = max(EH, view_rows * VT) + 44
    width = EW + cols * VT + 30
    f_small, f_big = _label_font(17), _label_font(24)
    detector = Detector() if people else None
    out_paths = []
    for h0 in range(0, n, per_sheet):
        group = times[h0:h0 + per_sheet]
        sheet = Image.new("RGB", (width, row_h * len(group)), (24, 24, 24))
        d = ImageDraw.Draw(sheet)
        for r, t in enumerate(group):
            idx = round(t * FPS)
            reader = Reader(proxy, idx)
            eq = reader.read()
            reader.close()
            C = orientation.C(idx)
            y0 = r * row_h
            _label(d, (10, y0 + 8), f"t = {t:.1f} s", f_big)
            # the equirect already corrected (levelling/stabilization) so the yaws match the render
            flat = equirect_view(eq, C, EW, EH)
            sheet.paste(Image.fromarray(flat), (0, y0 + 44))
            for yaw in range(-180, 181, 45):
                x = int((yaw / 360 + 0.5) * EW)
                d.line([(x, y0 + 44), (x, y0 + 44 + EH)], fill=(255, 255, 0) if yaw == 0 else (200, 200, 200), width=1)
                _label(d, (min(x + 3, EW - 40), y0 + 48), str(yaw), f_small)
            for pitch in (-45, 0, 45):
                y = int(y0 + 44 + (0.5 - pitch / 180) * EH)
                d.line([(0, y), (EW, y)], fill=(160, 160, 160), width=1)
                _label(d, (4, y + 2), f"{pitch}", f_small)
            if detector:
                for p in detector.people_360(eq, C):
                    x = int((((p["yaw"] + 180) % 360) / 360) * EW)
                    y = int(y0 + 44 + (0.5 - p["pitch"] / 180) * EH)
                    s = max(8, int(p["height"] / 180 * EH / 2))
                    d.rectangle([x - s // 2, y - s, x + s // 2, y + s], outline=(255, 60, 60), width=3)
                    _label(d, (x - 30, y + s + 2), f"{p['yaw']:.0f},{p['pitch']:.0f}", f_small)
            for k, (name, yaw, pitch) in enumerate(listing):
                im = view(eq, C, yaw, pitch, 0, 100, 0, VT, VT)
                x = EW + 10 + (k % cols) * (VT + 5)
                y = y0 + 44 + (k // cols) * (VT + 5)
                sheet.paste(Image.fromarray(im), (x, y))
                _label(d, (x + 6, y + 6), f"{name} ({yaw},{pitch})", f_small)
        sheet_path = out_dir / f"sheet_{h0 // per_sheet + 1:02d}.jpg"
        sheet.save(sheet_path, quality=88)
        out_paths.append(str(sheet_path))
    log(json.dumps({"sheets": out_paths}, ensure_ascii=False))
    return out_paths


def equirect_view(eq, C, w, h):
    """Re-projects the whole equirect with correction C (to see the horizon already levelled)."""
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


# ------------------------------------------------------------ people detection and following

class Detector:
    """People with MediaPipe ObjectDetector (EfficientDet-Lite0, 14 MB, CPU) over perspective views."""

    # a ring at the horizon plus a ring looking down (selfie stick: the person lands at -30..-60°)
    VIEWS = [(y, 0) for y in range(0, 360, 60)] + [(y, -50) for y in (0, 90, 180, 270)]

    def __init__(self, threshold=0.35, size=512, fov=100):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        if not PEOPLE_MODEL.exists():
            PEOPLE_MODEL.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["curl", "-sL", "-o", str(PEOPLE_MODEL), MODEL_URL], check=True)
        self.mp = mp
        op = vision.ObjectDetectorOptions(base_options=BaseOptions(model_asset_path=str(PEOPLE_MODEL)),
                                          running_mode=vision.RunningMode.IMAGE, max_results=12,
                                          score_threshold=threshold, category_allowlist=["person"])
        self.det = vision.ObjectDetector.create_from_options(op)
        self.size, self.fov = size, fov

    def people_360(self, eq, C=np.eye(3)):
        """A list of {yaw, pitch, height (°), score} in the virtual world (the same system as the keys)."""
        size, fov = self.size, self.fov
        r_edge = math.tan(math.radians(fov / 2))
        found = []
        for yaw, pitch in self.VIEWS:
            Rv = camera_rotation(yaw, pitch)
            img = np.ascontiguousarray(view(eq, C, yaw, pitch, 0, fov, 0, size, size))
            res = self.det.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=img))
            for dt in res.detections:
                b = dt.bounding_box
                if b.height < size * 0.06:
                    continue
                cx, cy = b.origin_x + b.width / 2, b.origin_y + b.height / 2
                at_edge = min(b.origin_x, b.origin_y, size - b.origin_x - b.width, size - b.origin_y - b.height) < 4
                rays_ = []
                for x, y in ((cx, cy), (cx, b.origin_y), (cx, b.origin_y + b.height)):
                    c = np.array([((x + 0.5) / size * 2 - 1) * r_edge, (0.5 - (y + 0.5) / size) * 2 * r_edge, 1.0])
                    rays_.append(Rv @ (c / np.linalg.norm(c)))
                yw, pt = dir_to_angles(rays_[0])
                height = math.degrees(math.acos(np.clip(rays_[1] @ rays_[2], -1, 1)))
                found.append({"yaw": yw, "pitch": pt, "height": height, "score": dt.categories[0].score,
                              "dir": rays_[0], "at_edge": at_edge})
        # drop duplicates from overlapping views: keep the one that doesn't touch the edge / the tallest
        found.sort(key=lambda p: (p["at_edge"], -p["height"]))
        unique = []
        for p in found:
            if all(math.degrees(math.acos(np.clip(p["dir"] @ q["dir"], -1, 1))) > 0.5 * max(p["height"], q["height"])
                   for q in unique):
                unique.append(p)
        return unique


class OneEuro:
    """A One-Euro filter (Casiez 2012): smooths heavily when things move slowly and responds when they don't."""

    def __init__(self, min_cutoff=0.4, beta=0.02, d_cutoff=1.0):
        self.mc, self.beta, self.dc = min_cutoff, beta, d_cutoff
        self.x = self.dx = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1 / (2 * math.pi * cutoff)
        return 1 / (1 + tau / dt)

    def __call__(self, x, dt):
        if self.x is None:
            self.x, self.dx = x, 0.0
            return x
        dx = (x - self.x) / dt
        a_d = self._alpha(self.dc, dt)
        self.dx = a_d * dx + (1 - a_d) * self.dx
        cutoff = self.mc + self.beta * abs(self.dx)
        a = self._alpha(cutoff, dt)
        self.x = a * x + (1 - a) * self.x
        return self.x


def _angular_distance(a, b):
    return math.degrees(math.acos(np.clip(angles_to_dir(a[0], a[1]) @ angles_to_dir(b[0], b[1]), -1, 1)))


def follow(src, start=0.0, dur=10.0, kind="selfie", target=None, hz=6.0, stab="no", stab_mode="heading",
           level="auto", fixed_fov=None, out_keys=None):
    """Follows the person: detects every 1/hz s, associates with the target, smooths with One-Euro
    and writes keys. selfie mode: the person centred, zoom based on their size. third mode: the
    'invisible selfie stick' third-person look: you look at the person from above, with them in the
    lower third and a wide angle."""
    src = path(src)
    proxy = make_proxy(src)
    orientation = Orientation(src, proxy, stab, stab_mode, level)
    det = Detector()
    reader = Reader(proxy, round(start * FPS))
    step = 1 / hz
    t0 = time.time()
    track, last, lost = [], None, 0.0
    t = 0.0
    while t < dur:
        idx = round((start + t) * FPS)
        eq = reader.frame(idx)
        if eq is None:
            break
        people = det.people_360(eq, orientation.C(idx))
        chosen = None
        if people:
            if last is None:
                if target:
                    chosen = min(people, key=lambda p: _angular_distance((p["yaw"], p["pitch"]), target))
                else:
                    chosen = max(people, key=lambda p: p["height"])
            else:
                limit = 20 + 60 * (step + lost)
                near = [p for p in people if _angular_distance((p["yaw"], p["pitch"]), last[:2]) < limit]
                if near:
                    chosen = min(near, key=lambda p: _angular_distance((p["yaw"], p["pitch"]), last[:2])
                                 + 0.3 * abs(p["height"] - last[2]))
                elif lost > 1.5:  # lost them: re-latch onto the largest person
                    chosen = max(people, key=lambda p: p["height"])
        if chosen:
            yw = chosen["yaw"]
            if last is not None:  # unwrap the yaw against the previous one
                yw = last[0] + ((yw - last[0] + 180) % 360 - 180)
            last = (yw, chosen["pitch"], chosen["height"])
            track.append((t, *last))
            lost = 0.0
        else:
            lost += step
        t += step
    reader.close()
    log(f"follow: {len(track)} detections in {time.time() - t0:.1f} s")
    if not track:
        raise RuntimeError("I found no people in the clip")
    # One-Euro smoothing over the direction VECTOR (not over yaw/pitch): near the nadir, where a
    # person with a selfie stick ends up, a small step changes the yaw enormously and filtering in
    # angles gives jerks.
    slow = kind == "third"
    filters = [OneEuro(0.2 if slow else 0.35, 0.3 if slow else 0.6) for _ in range(3)]
    f_height = OneEuro(0.15, 0.0)
    keys, t_prev, yaw_prev = [], None, None
    for t, yw, pt, height in track:
        dt = step if t_prev is None else max(1e-3, t - t_prev)
        t_prev = t
        v = angles_to_dir(yw, pt)
        v = np.array([f(float(c), dt) for f, c in zip(filters, v)])
        yw, pt = dir_to_angles(v)
        if yaw_prev is not None:
            yw = yaw_prev + ((yw - yaw_prev + 180) % 360 - 180)
        yaw_prev = yw
        height = f_height(height, dt)
        if kind == "third":
            fov = fixed_fov or 105.0
            vfov = _vfov(fov)
            pitch = pt + vfov * 0.2  # the person in the lower third, looking ahead
        else:
            # the person fills ~45 % of the height; vfov >= 80 (hfov ~50) because with a 4K proxy
            # any more zoom looks soft
            vfov = float(np.clip(height / 0.45, 80, 115))
            fov = fixed_fov or _hfov(vfov)
            pitch = pt + height * 0.08
        keys.append({"t": round(t, 3), "yaw": round(yw, 2), "pitch": round(float(np.clip(pitch, -85, 60)), 2),
                     "fov": round(fov, 2), "ease": "spline"})
    if keys[0]["t"] > 0:
        keys.insert(0, {**keys[0], "t": 0.0})
    spec = {"src": str(src), "start": start, "dur": dur, "stab": stab, "mode": stab_mode, "level": level,
            "keys": keys}
    out_keys = path(out_keys or OUTPUT / f"follow_{src.stem}.json")
    out_keys.parent.mkdir(parents=True, exist_ok=True)
    json.dump(spec, open(out_keys, "w"), indent=1, ensure_ascii=False)
    log(json.dumps({"keys": str(out_keys), "n_keys": len(keys)}, ensure_ascii=False))
    return spec, out_keys


def _vfov(hfov, aspect=H / W):
    return math.degrees(2 * math.atan(math.tan(math.radians(min(hfov, 170)) / 2) * aspect))


def _hfov(vfov, aspect=H / W):
    return math.degrees(2 * math.atan(math.tan(math.radians(vfov) / 2) / aspect))


# ------------------------------------------------------------ tiny planet

def planet_spec(src, start=0.0, dur=6.0, spin=40.0, to_normal=None, end_yaw=0.0, end_fov=80.0):
    """A tiny planet spinning `spin` degrees; with to_normal=s it ends by unrolling into a normal view."""
    keys = [{"t": 0, "planet": True, "yaw": 0.0, "ease": "linear"}]
    if to_normal:
        t_exit = max(0.5, dur - to_normal)
        keys.append({"t": t_exit, "planet": True, "yaw": spin, "ease": "linear"})
        keys.append({"t": dur, "yaw": end_yaw, "pitch": 0, "fov": end_fov, "ease": "smooth"})
    else:
        keys.append({"t": dur, "planet": True, "yaw": spin, "ease": "linear"})
    return {"src": str(src), "start": start, "dur": dur, "keys": keys,
            "out": str(OUTPUT / f"planet_{path(src).stem}.mp4")}


# ------------------------------------------------------------ CLI

def _level_arg(s):
    if s in ("auto", "no", "gyro"):
        return s
    p, r = (float(x) for x in s.split(","))
    return [p, r]


def main():
    ap = argparse.ArgumentParser(description="360 reframing -> 9:16")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("src")
        p.add_argument("--start", type=float, default=0.0)
        p.add_argument("--dur", type=float)
        p.add_argument("--stab", default="no", choices=["no", "visual", "gyro", "auto"])
        p.add_argument("--mode", default="heading", choices=["heading", "lock"])
        p.add_argument("--level", default="auto", type=_level_arg, help="auto | no | gyro | pitch,roll")

    p = sub.add_parser("proxy")
    p.add_argument("src")
    p.add_argument("--width", type=int, default=3840)
    p.add_argument("--fov", type=float, default=INSV["fov"], help="the .insv stitch's ih_fov/iv_fov")
    p.add_argument("--order", default=INSV["order"], help="10 = track 1 is the front lens (X5), 01 = track 0 is")
    p.add_argument("--rot-front", type=int, default=0)
    p.add_argument("--rot-back", type=int, default=0)
    p.add_argument("--crf", type=int, default=PROXY_CRF,
                   help=f"x264 quality of the proxy, lower = bigger (default {PROXY_CRF})")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("sheets")
    common(p)
    p.add_argument("--n", type=int, default=6)
    p.add_argument("--per-sheet", type=int, default=3)
    p.add_argument("--views", default="cube", choices=list(VIEWS))
    p.add_argument("--people", action="store_true")
    p.add_argument("--out")

    p = sub.add_parser("render")
    p.add_argument("--keys", required=True)
    p.add_argument("--out")

    p = sub.add_parser("planet")
    common(p)
    p.add_argument("--spin", type=float, default=40)
    p.add_argument("--to-normal", type=float)
    p.add_argument("--end-yaw", type=float, default=0)
    p.add_argument("--out")

    p = sub.add_parser("follow")
    common(p)
    p.add_argument("--type", default="selfie", choices=["selfie", "third"])
    p.add_argument("--target", help="the approximate yaw,pitch of the person to follow (see sheets)")
    p.add_argument("--hz", type=float, default=6)
    p.add_argument("--fov", type=float)
    p.add_argument("--render", action="store_true")
    p.add_argument("--keys-out", help="where to write the generated keys.json")
    p.add_argument("--out", help="with --render, the rendered MP4 (the keys go to --keys-out)")

    p = sub.add_parser("telemetry")
    p.add_argument("src")

    a = ap.parse_args()
    if a.cmd == "proxy":
        make_proxy(a.src, a.width, crf=a.crf, insv_cfg={"fov": a.fov, "order": a.order, "rot_front": a.rot_front,
                                             "rot_back": a.rot_back}, force=a.force)
    elif a.cmd == "sheets":
        sheets(a.src, a.start, a.dur, a.n, a.per_sheet, a.views, a.stab, a.mode, a.level, a.people, a.out)
    elif a.cmd == "render":
        spec = _load_spec(a.keys)
        if a.out:
            spec["out"] = a.out
        render(spec)
    elif a.cmd == "planet":
        spec = planet_spec(a.src, a.start, a.dur or 6, a.spin, a.to_normal, a.end_yaw)
        spec.update({"stab": a.stab, "mode": a.mode, "level": a.level})
        if a.out:
            spec["out"] = a.out
        render(spec)
    elif a.cmd == "follow":
        target = tuple(float(x) for x in a.target.split(",")) if a.target else None
        if target and len(target) == 1:
            target = (target[0], 0.0)
        spec, keys_path = follow(a.src, a.start, a.dur or 10, a.type, target, a.hz, a.stab, a.mode, a.level,
                                 a.fov, a.keys_out)
        if a.render:
            spec["out"] = a.out or str(keys_path.with_suffix(".mp4"))
            render(spec)
    elif a.cmd == "telemetry":
        imu = read_imu(path(a.src))
        t, g = imu["t"], imu["gyro"]
        print(json.dumps({"camera": imu["camera"], "model": imu["model"], "samples": len(t),
                          "hz": round((len(t) - 1) / max(1e-6, t[-1] - t[0]), 1),
                          "dur_s": round(float(t[-1] - t[0]), 2),
                          "gyro_max_dps": np.abs(g).max(0).round(1).tolist(),
                          "accl_mean": imu["accl"].mean(0).round(2).tolist()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
