# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "pillow-heif", "opencv-contrib-python<5", "numpy<2.3"]
# ///
"""Who is in the photos, without the Photos app.

`sources.py` gets faces and names from the macOS Photos library. Outside macOS -- and inside it,
when the user never named anybody -- that information doesn't exist, and "the shots where the
subject appears" has to be worked out from the images themselves.

Three steps, each its own command:

    uv run people.py models --download                       # once: ~39 MB of face models
    uv run people.py detect list.json --out workspace/people/faces.json
    uv run people.py cluster workspace/people/faces.json --out workspace/people/clusters.json \\
        --sheets workspace/people/sheets                     # one sheet per person, to look at
    uv run people.py match  workspace/people/faces.json --reference ref1.jpg --reference ref2.jpg \\
        --out workspace/people/subject.json
    uv run people.py pick   workspace/people/subject.json --out chosen.txt   # feeds export.py --ids

`list.json` is whatever `sheets.py` accepts, including `inventory.py`'s output, and the numbering
matches `sheets.py contact` over the same list, so "number 14" means the same thing in both.

**The two paths are different jobs.** `cluster` answers "how many different people are in this
material and which is the one that keeps showing up"; `match` answers "which shots is *this*
person in", and needs 2-3 reference photos of them (a clear, front-lit, face-visible shot each).
When the user can point at reference photos, `match` is far more accurate -- use it.

Privacy: face embeddings are biometric data. They are written to the workspace passed in `--out`,
never to `~/.config/reel-forge/`, and they never leave the machine. Delete the workspace and
nothing is left. Do not copy them into a delivery, a README or a file name.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sheets  # noqa: E402  (shared: list loading, image opening, sheet cells)

ENV_MODELS = "REEL_FORGE_MODELS"
ENV_CACHE = "REEL_FORGE_CACHE"
ENV_YUNET = "REEL_FORGE_YUNET"
ENV_SFACE = "REEL_FORGE_SFACE"

# OpenCV Zoo, Apache-2.0, ~230 KB and ~39 MB. They are the two models OpenCV itself ships in its
# model zoo for this, they run on the CPU in milliseconds, and nothing is sent anywhere.
MODELS = {
    "yunet": (
        "face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
        "face_detection_yunet_2023mar.onnx",
        "detection (boxes + the 5 landmarks the recogniser needs)",
    ),
    "sface": (
        "face_recognition_sface_2021dec.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/"
        "face_recognition_sface_2021dec.onnx",
        "recognition (the 128-number embedding that makes grouping possible)",
    ),
}

# SFace's own recommendation for cosine similarity: above this, same person. It is a starting
# point, not a law -- sunglasses, a beard or a 3 % of the frame face all move it.
SAME_PERSON = 0.363

# Anything smaller than this fraction of the frame is a passer-by, not a subject.
MIN_FACE_PCT = 0.15

DETECT_SIDE = 1600      # images get scaled to this before detection: enough, and fast


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def models_dir() -> Path:
    if os.environ.get(ENV_MODELS):
        return Path(os.environ[ENV_MODELS]).expanduser()
    cache = os.environ.get(ENV_CACHE) or "~/.cache/reel-forge"
    return Path(cache).expanduser() / "models"


def model_path(name: str) -> Path:
    env = {"yunet": ENV_YUNET, "sface": ENV_SFACE}[name]
    if os.environ.get(env):
        return Path(os.environ[env]).expanduser()
    return models_dir() / MODELS[name][0]


# --------------------------------------------------------------------------- backends

class NoModel(RuntimeError):
    pass


def yunet(score: float = 0.6):
    import cv2
    path = model_path("yunet")
    if not path.exists():
        raise NoModel(
            f"The detection model isn't there ({path}).\n"
            "  uv run people.py models --download        # ~230 KB, once\n"
            f"or point ${ENV_YUNET} at a copy you already have.")
    return cv2.FaceDetectorYN.create(str(path), "", (320, 320),
                                     score_threshold=score, nms_threshold=0.3, top_k=2000)


def sface():
    import cv2
    path = model_path("sface")
    if not path.exists():
        raise NoModel(
            f"The recognition model isn't there ({path}).\n"
            "  uv run people.py models --download        # ~37 MB, once\n"
            f"or point ${ENV_SFACE} at a copy you already have.\n"
            "Without it faces can be found but not told apart, so `cluster` and `match` "
            "have nothing to work with.")
    return cv2.FaceRecognizerSF.create(str(path), "")


def mediapipe_detector():
    try:
        import mediapipe as mp
    except ImportError as e:
        raise NoModel(
            "MediaPipe isn't installed. Run this script as\n"
            "  uv run --with mediapipe people.py detect ...\n"
            "It detects faces well, but it gives no embedding: `cluster` and `match` still "
            "need the OpenCV models.") from e
    return mp.solutions.face_detection.FaceDetection(model_selection=1,
                                                     min_detection_confidence=0.5)


def pick_backend(name: str) -> str:
    if name != "auto":
        return name
    if model_path("yunet").exists():
        return "yunet"
    try:
        import mediapipe  # noqa: F401
        return "mediapipe"
    except ImportError:
        return "haar"


# --------------------------------------------------------------------------- detection

def to_bgr(img, max_side=DETECT_SIDE):
    """PIL RGB -> (BGR array for OpenCV, scale back to the original size)."""
    import cv2
    import numpy as np

    small = img.copy()
    if max(small.size) > max_side:
        small.thumbnail((max_side, max_side), sheets.Image.LANCZOS)
    scale = img.width / small.width
    return cv2.cvtColor(np.array(small), cv2.COLOR_RGB2BGR), scale


def detect_one(img, backend: str, det, rec, score: float):
    """Every face in one image: box in the ORIGINAL coordinates, plus its embedding if possible."""
    import numpy as np

    bgr, scale = to_bgr(img)
    height, width = bgr.shape[:2]
    out = []

    if backend == "yunet":
        det.setInputSize((width, height))
        _, faces = det.detect(bgr)
        for row in (faces if faces is not None else []):
            x, y, w, h = (float(v) for v in row[:4])
            face = {
                "box": [int(x * scale), int(y * scale), int(w * scale), int(h * scale)],
                "score": round(float(row[-1]), 3),
            }
            if rec is not None:
                aligned = rec.alignCrop(bgr, row)
                vector = np.asarray(rec.feature(aligned)).flatten().astype(float)
                norm = float(np.linalg.norm(vector))
                if norm:
                    face["embedding"] = [round(v, 5) for v in (vector / norm)]
            out.append(face)

    elif backend == "mediapipe":
        import cv2
        result = det.process(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        for found in (result.detections or []):
            b = found.location_data.relative_bounding_box
            out.append({
                "box": [int(b.xmin * width * scale), int(b.ymin * height * scale),
                        int(b.width * width * scale), int(b.height * height * scale)],
                "score": round(float(found.score[0]), 3),
            })

    else:  # haar
        for x, y, w, h in sheets.faces_in(img, det):
            out.append({"box": [int(x), int(y), int(w), int(h)], "score": None})

    frame = float(img.width * img.height)
    for face in out:
        _x, _y, w, h = face["box"]
        face["area_pct"] = round(100.0 * w * h / frame, 2)
    return out


def cmd_detect(args) -> int:
    items = sheets.load_items(args.inputs)
    if not items:
        print("No usable image in what was passed.", file=sys.stderr)
        return 1

    backend = pick_backend(args.backend)
    rec = None
    if backend == "yunet":
        det = yunet(args.score)
        if not args.no_embeddings:
            rec = sface()
    elif backend == "mediapipe":
        det = mediapipe_detector()
    else:
        det = sheets.detector()

    print(f"detection: {backend}" + ("  + sface embeddings" if rec is not None else
                                     "  (no embeddings: cluster/match won't run)"))
    faces, no_face = [], []
    for n, item in enumerate(items, 1):
        img = sheets.open_image(item["used"])
        if img is None:
            continue
        found = [f for f in detect_one(img, backend, det, rec, args.score)
                 if f["area_pct"] >= args.min_area]
        if not found:
            no_face.append({"n": n, "id": item["id"], "path": item["path"]})
            continue
        for k, face in enumerate(found):
            face.update({"face": f"{item['id']}#{k}", "n": n, "id": item["id"],
                         "path": item["path"], "used": item["used"]})
            faces.append(face)
        if n % 50 == 0:
            print(f"  {n}/{len(items)}…")

    data = {
        "generated": now(),
        "backend": backend,
        "embeddings": rec is not None,
        "min_area_pct": args.min_area,
        "items": len(items),
        "with_faces": len(items) - len(no_face),
        "faces": faces,
        "no_face": no_face,
    }
    write(args.out, data)
    print(f"  {len(faces)} face(s) in {data['with_faces']} of {len(items)} item(s) -> {args.out}")
    if rec is None:
        print("  no embeddings: run `models --download` and detect again to be able to group them.")
    return 0


# --------------------------------------------------------------------------- grouping

def vectors(faces: list[dict]):
    import numpy as np
    return np.array([f["embedding"] for f in faces], dtype=float)


def cluster_faces(faces: list[dict], threshold: float) -> list[list[int]]:
    """Average-link agglomerative grouping over cosine similarity.

    The embeddings arrive already normalized, so the similarity is a dot product. Average link
    (not single link) because single link chains: two people who each half-resemble a third end
    up in one group. The between-group similarity is kept in a matrix and updated on each merge
    (Lance-Williams), so 1,500 faces take seconds instead of minutes.
    """
    import numpy as np

    sim = vectors(faces) @ vectors(faces).T
    n = len(faces)
    np.fill_diagonal(sim, -np.inf)
    groups: list[list[int] | None] = [[i] for i in range(n)]
    sizes = np.ones(n)
    alive = np.ones(n, dtype=bool)

    while alive.sum() > 1:
        flat = int(np.argmax(sim))
        a, b = divmod(flat, n)
        if sim[a, b] <= threshold:
            break
        # b folds into a; a's similarity to everyone else becomes the size-weighted average.
        merged = (sizes[a] * sim[a] + sizes[b] * sim[b]) / (sizes[a] + sizes[b])
        sim[a] = merged
        sim[:, a] = merged
        sim[a, a] = -np.inf
        sim[b, :] = -np.inf
        sim[:, b] = -np.inf
        groups[a] = groups[a] + groups[b]   # type: ignore[operator]
        groups[b] = None
        sizes[a] += sizes[b]
        alive[b] = False

    return sorted((g for g in groups if g), key=len, reverse=True)


def cmd_cluster(args) -> int:
    data = read(args.faces)
    faces = [f for f in data["faces"] if "embedding" in f]
    if not faces:
        print("Those faces carry no embedding: re-run `detect` with the yunet backend "
              "(`people.py models --download`).", file=sys.stderr)
        return 1
    if len(faces) > args.max_faces:
        print(f"{len(faces)} faces is beyond what this grouping handles comfortably "
              f"(it compares every pair). Narrow the list down -- a day, a session, the "
              f"favourites -- or raise --max-faces and be patient.", file=sys.stderr)
        return 1

    groups = cluster_faces(faces, args.threshold)
    clusters = []
    for k, index in enumerate(groups, 1):
        members = [faces[i] for i in index]
        if len(members) < args.min_size:
            continue
        members.sort(key=lambda f: (f.get("area_pct") or 0, f.get("score") or 0), reverse=True)
        # ids and paths in the same order: an id alone is not enough to find the file again
        # when the list came from a plain folder, where ids are just positions.
        by_id = {f["id"]: f.get("path") for f in members}
        item_ids = sorted(by_id)
        clusters.append({
            "cluster": f"c-{k:02d}",
            "faces": len(members),
            "items": item_ids,
            "paths": [by_id[i] for i in item_ids],
            "best": [{"n": f["n"], "id": f["id"], "path": f.get("path"),
                      "area_pct": f["area_pct"]} for f in members[:6]],
            "members": [f["face"] for f in members],
        })

    report = {
        "generated": now(),
        "threshold": args.threshold,
        "min_size": args.min_size,
        "clusters": clusters,
        "loose_faces": sum(1 for g in groups if len(g) < args.min_size),
    }
    if args.sheets:
        report["sheets"] = cluster_sheets(clusters, faces, Path(args.sheets).expanduser(),
                                          args.cols, args.padding)
    write(args.out, report)

    print(f"{len(clusters)} group(s) over {len(faces)} face(s), threshold {args.threshold}")
    for c in clusters:
        print(f"  {c['cluster']}  {c['faces']:>4} face(s) in {len(c['items'])} item(s)"
              f"   e.g. numbers " + ", ".join(str(b["n"]) for b in c["best"][:4]))
    print("\nThe biggest group is usually the user, but only usually. Show them the sheets "
          "and ask which group is the subject -- don't decide it on your own.")
    return 0


def cluster_sheets(clusters, faces, out: Path, cols: int, padding: float) -> list[str]:
    """One sheet of face crops per group: this is what the user actually looks at to say
    'that one is me'. Numbers match `sheets.py contact` over the same list."""
    out.mkdir(parents=True, exist_ok=True)
    by_key = {f["face"]: f for f in faces}
    font = sheets.typeface(16)
    made = []
    for cluster in clusters:
        cells = []
        for key in cluster["members"][:cols * 4]:
            face = by_key[key]
            img = sheets.open_image(face["used"])
            if img is None:
                continue
            x, y, w, h = face["box"]
            d = int(max(w, h) * padding)
            cx, cy = x + w // 2, y + h // 2
            crop = img.crop((max(0, cx - d), max(0, cy - d),
                             min(img.width, cx + d), min(img.height, cy + d)))
            cells.append(sheets.cell(crop, face["n"], Path(face["path"]).name, font))
        if not cells:
            continue
        width = min(cols, len(cells))
        rows = (len(cells) + width - 1) // width
        page = sheets.Image.new("RGB", (width * sheets.CELL, rows * (sheets.CELL + sheets.BAR)),
                                (18, 18, 18))
        for k, c in enumerate(cells):
            page.paste(c, ((k % width) * sheets.CELL, (k // width) * (sheets.CELL + sheets.BAR)))
        target = out / f"{cluster['cluster']}.jpg"
        page.save(target, quality=90)
        made.append(str(target))
        print(f"  {target}")
    return made


# --------------------------------------------------------------------------- match

def reference_vector(paths: list[str], det, rec):
    """The average of the references' embeddings: 2-3 photos beat 1 by a wide margin.

    Only the largest face in each reference is taken -- a reference photo with the subject and
    three friends would otherwise poison the average.
    """
    import numpy as np

    vecs, used = [], []
    for raw in paths:
        p = sheets.expand(raw)
        img = sheets.open_image(str(p))
        if img is None:
            continue
        found = [f for f in detect_one(img, "yunet", det, rec, 0.6) if "embedding" in f]
        if not found:
            print(f"  no face found in the reference {p.name}; skipped.", file=sys.stderr)
            continue
        found.sort(key=lambda f: f["area_pct"], reverse=True)
        vecs.append(np.array(found[0]["embedding"], dtype=float))
        used.append(p.name)
    if not vecs:
        return None, []
    mean = np.mean(vecs, axis=0)
    norm = float(np.linalg.norm(mean))
    return (mean / norm if norm else mean), used


def cmd_match(args) -> int:
    import numpy as np

    data = read(args.faces)
    faces = [f for f in data["faces"] if "embedding" in f]
    if not faces:
        print("Those faces carry no embedding: re-run `detect` with the yunet backend.",
              file=sys.stderr)
        return 1

    det, rec = yunet(), sface()
    ref, used = reference_vector(args.reference, det, rec)
    if ref is None:
        print("None of the references had a usable face. Pick front-lit shots where the face "
              "is large and unobstructed.", file=sys.stderr)
        return 1
    if len(used) < 2:
        print("  only one usable reference: the match will be noticeably shakier. "
              "Two or three, from different days, is the difference.", file=sys.stderr)

    scores: dict[str, dict] = {}
    for face in faces:
        value = float(np.array(face["embedding"], dtype=float) @ ref)
        current = scores.get(face["id"])
        if current is None or value > current["similarity"]:
            scores[face["id"]] = {"id": face["id"], "n": face["n"], "path": face["path"],
                                  "similarity": round(value, 4), "area_pct": face["area_pct"]}

    hits = sorted((s for s in scores.values() if s["similarity"] >= args.threshold),
                  key=lambda s: -s["similarity"])
    near = sorted((s for s in scores.values()
                   if args.threshold - 0.08 <= s["similarity"] < args.threshold),
                  key=lambda s: -s["similarity"])

    report = {
        "generated": now(),
        "references": used,
        "threshold": args.threshold,
        "scored_items": len(scores),
        "matches": hits,
        "borderline": near,
        "note": "The borderline ones are the ones to show the user: that band is where the "
                "profile shots, the sunglasses and the sibling live.",
    }
    write(args.out, report)
    print(f"{len(hits)} item(s) at or above {args.threshold}, {len(near)} borderline, "
          f"out of {len(scores)} with a face -> {args.out}")
    if hits:
        print("  best: " + ", ".join(f"#{h['n']} ({h['similarity']})" for h in hits[:6]))
    return 0


# --------------------------------------------------------------------------- pick

UUID = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
                  r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")


def cmd_pick(args) -> int:
    data = read(args.report)
    rows: list[tuple[str, str | None]] = []      # (id, path)
    if "matches" in data:
        rows = [(m["id"], m.get("path")) for m in data["matches"]
                if m["similarity"] >= (args.min_score or 0)]
        if args.borderline:
            rows += [(m["id"], m.get("path")) for m in data.get("borderline", [])]
    elif "clusters" in data:
        if not args.cluster:
            print("That file holds groups: say which one, --cluster c-01.", file=sys.stderr)
            return 1
        for cluster in data["clusters"]:
            if cluster["cluster"] == args.cluster:
                paths = cluster.get("paths") or [None] * len(cluster["items"])
                rows = list(zip(cluster["items"], paths))
                break
        else:
            print(f"There is no group {args.cluster}.", file=sys.stderr)
            return 1
    else:
        print("That file is neither a `match` report nor a `cluster` one.", file=sys.stderr)
        return 1

    # Which of the two the next step wants depends on where the material came from, so the id
    # decides: a Photos uuid feeds `export.py --export --ids`, and anything else is a position
    # or a relative name that only means something next to its path. Writing `p-006` into a
    # list, as this used to, produces a file nothing downstream can resolve.
    uuids = [i for i, _ in rows if UUID.match(str(i))]
    mode = args.write or ("ids" if rows and len(uuids) == len(rows) else "paths")
    if mode == "paths":
        lines = [pth or str(i) for i, pth in rows]
        missing = [i for i, pth in rows if not pth]
        if missing:
            print(f"  {len(missing)} entr(y/ies) carry no path (an older report): "
                  "re-run `detect` and `cluster` to get them.", file=sys.stderr)
    else:
        lines = [str(i) for i, _ in rows]

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = list(dict.fromkeys(lines))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    all_uuids = bool(rows) and len(uuids) == len(rows)
    kind = "path" if mode == "paths" else "uuid" if all_uuids else "id"
    print(f"{len(lines)} {kind}(s) -> {out}")
    if mode == "ids" and all_uuids:
        print("  Apple Photos uuids: feed them to `export.py --export --ids`.")
    elif mode == "ids":
        print("  Careful: these are not Photos uuids, so `export.py --ids` will find nothing. "
              "They are positions in the list this report was built from. Drop --write ids to "
              "get the file paths instead.", file=sys.stderr)
    else:
        print("  These came from a folder, so they are file paths, not Photos uuids: copy them "
              "straight (`xargs -a` / `cp`). `export.py --ids` only understands uuids.")
    return 0


# --------------------------------------------------------------------------- models

def cmd_models(args) -> int:
    folder = models_dir()
    print(f"models folder: {folder}   (${ENV_MODELS} overrides it)")
    missing = []
    for name, (filename, url, what) in MODELS.items():
        p = model_path(name)
        if p.exists():
            print(f"  [ok]      {name:<6} {what}\n            {p} "
                  f"({p.stat().st_size / 1e6:.1f} MB)")
        else:
            missing.append((name, url, p))
            print(f"  [missing] {name:<6} {what}\n            {p}")
    try:
        import mediapipe  # noqa: F401
        print("  [ok]      mediapipe  installed (detection only, no embeddings)")
    except ImportError:
        print("  [absent]  mediapipe  optional; `uv run --with mediapipe people.py detect …`")
    print("  [ok]      haar       always available with OpenCV (detection only, weakest)")

    if missing and not args.download:
        print("\n  uv run people.py models --download")
        return 1
    for name, url, target in missing:
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"\ndownloading {name}…\n  {url}")
        try:
            tmp = target.with_suffix(".part")
            with urllib.request.urlopen(url, timeout=60) as response, \
                    open(tmp, "wb") as fh:
                fh.write(response.read())
            os.replace(tmp, target)
            print(f"  -> {target} ({target.stat().st_size / 1e6:.1f} MB)")
        except Exception as e:  # network, proxy, a moved file in the zoo
            print(f"  failed: {e}\n"
                  f"  Download it by hand into {target.parent} or point ${ENV_YUNET}/"
                  f"${ENV_SFACE} at a copy.", file=sys.stderr)
            return 1
    return 0


# --------------------------------------------------------------------------- io + cli

def read(path: str) -> dict:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def write(path: str, data: dict) -> None:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="people.py",
        description="Face detection, grouping and subject matching that work without Apple Photos.")
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("models", help="what is installed, and download what isn't")
    s.add_argument("--download", action="store_true")
    s.set_defaults(func=cmd_models)

    s = sub.add_parser("detect", help="find the faces in a list of items")
    s.add_argument("inputs", nargs="+", help="list.json, a folder, or loose paths")
    s.add_argument("--out", default="workspace/people/faces.json")
    s.add_argument("--backend", choices=["auto", "yunet", "mediapipe", "haar"], default="auto")
    s.add_argument("--score", type=float, default=0.6, help="minimum detection confidence")
    s.add_argument("--min-area", type=float, default=MIN_FACE_PCT,
                   help="ignore faces below this %% of the frame (default: %(default)s)")
    s.add_argument("--no-embeddings", action="store_true",
                   help="boxes only, no biometric vector")
    s.set_defaults(func=cmd_detect)

    s = sub.add_parser("cluster", help="group the faces by who they look like")
    s.add_argument("faces")
    s.add_argument("--out", default="workspace/people/clusters.json")
    s.add_argument("--threshold", type=float, default=SAME_PERSON,
                   help="cosine similarity to call it the same person (default: %(default)s)")
    s.add_argument("--min-size", type=int, default=3, help="groups smaller than this are noise")
    s.add_argument("--max-faces", type=int, default=1500)
    s.add_argument("--sheets", help="folder for one face sheet per group")
    s.add_argument("--cols", type=int, default=6)
    s.add_argument("--padding", type=float, default=1.1)
    s.set_defaults(func=cmd_cluster)

    s = sub.add_parser("match", help="find the shots with THIS person, from reference photos")
    s.add_argument("faces")
    s.add_argument("--reference", action="append", required=True,
                   help="a photo of the subject; repeat it, 2-3 is the sweet spot")
    s.add_argument("--out", default="workspace/people/subject.json")
    s.add_argument("--threshold", type=float, default=SAME_PERSON)
    s.set_defaults(func=cmd_match)

    s = sub.add_parser("pick", help="turn a report into an id list for export.py")
    s.add_argument("report")
    s.add_argument("--out", default="chosen.txt")
    s.add_argument("--cluster", help="which group, when the report is a `cluster` one")
    s.add_argument("--min-score", type=float, help="raise the bar on a `match` report")
    s.add_argument("--borderline", action="store_true", help="include the borderline matches")
    s.add_argument("--write", choices=("ids", "paths"),
                   help="force what gets written; by default uuids when they are uuids, "
                        "file paths otherwise")
    s.set_defaults(func=cmd_pick)

    args = ap.parse_args()
    try:
        return args.func(args)
    except NoModel as e:
        print(str(e), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
