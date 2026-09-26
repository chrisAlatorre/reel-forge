# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Do the variants of one concept actually look different? Measured, pair by pair.

    uv run compare_variants.py <concept folder>           # the rendered variants loose in it: BEST
    uv run compare_variants.py A.mp4 C.mp4                  # what a viewer sees, cut by cut
    uv run compare_variants.py A/spec.json C/spec.json      # before rendering, by file and moment

The feedback this exists for, verbatim: *"for each concept you made two variants, but they looked
the same, I saw no difference between them"*. It was true, and it came in two shapes:

  * **The axis was invisible.** "Same cuts, other song" is not a variant of a delivery whose clean
    file carries no song: the two uploads are the same video, byte for byte in what you see.
  * **The axis was too small.** "The same thing minus two shots" reads as the same video. Nobody
    watching them one after the other says "that's the short one".

So a pair passes only if a viewer would notice at least one of these, and each is measured:

| axis | counts as different when |
|---|---|
| the shots | fewer than 60 % of the shots are shared (by source and window) |
| the hook | the first shot is a different source, or the same source at another moment |
| the close | the last shot differs the same way |
| the voice | one is narrated and the other is not |
| the length | never on its own: "the same minus two shots" is what was watched twice and called identical |

Music is deliberately NOT an axis: the clean files never carry it.

Exit 0 when every pair differs on something a viewer sees or hears; exit 1 with the pairs that do
not, and what they share.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def shots(spec):
    out = []
    for s in spec.get("segments", []):
        # by the file and the moment, never by `_id`: builders label segments freely ("hook-v11-03"
        # in one variant, "v11-03" in the other), which made identical variants look 0 % alike
        src = Path(str(s.get("src", "map"))).name
        # the loop's reversed tail is the opening clip: count it as the first shot's source
        start = round(float(s.get("start", 0) or 0), 1)
        out.append((src, start))
    return out


def durations(spec):
    return sum(float(s.get("dur", 0) or 0) for s in spec.get("segments", []))


def narrated(spec):
    return bool(spec.get("sync")) or any("voice" in str(a.get("src", "")) for a in spec.get("audio", []))


def same_shot(a, b):
    return a[0] == b[0] and abs(a[1] - b[1]) < 1.0


def compare(name_a, a, name_b, b):
    sa, sb = shots(a), shots(b)
    shared = sum(1 for x in sa if any(same_shot(x, y) for y in sb))
    share = shared / max(1, min(len(sa), len(sb)))
    da, db = durations(a), durations(b)
    ratio = min(da, db) / max(da, db) if max(da, db) else 1.0
    axes = []
    if share < 0.60:
        axes.append(f"shots ({share:.0%} shared)")
    if sa and sb and not same_shot(sa[0], sb[0]):
        axes.append("hook")
    if sa and sb and not same_shot(sa[-1], sb[-1]):
        axes.append("close")
    if narrated(a) != narrated(b):
        axes.append("voice")
    # Length alone does NOT make a variant: "the same video minus two shots" is exactly what the
    # user watched twice and called identical (86 % shared, 74 % of the length). It is reported, and
    # it only counts next to one of the axes above.
    length = f"length ({min(da, db):.1f} vs {max(da, db):.1f} s)" if ratio <= 0.75 else None
    return {"pair": f"{name_a} vs {name_b}", "shared_shots": round(share, 2),
            "length_ratio": round(ratio, 2), "differs_on": axes + ([length] if length and axes else []),
            "ok": bool(axes)}


# ------------------------------------------------------------------ what a viewer SEES

def _timeline_of(video: Path):
    for c in (video.with_name(video.stem + ".timeline.json"),
              video.parent / "resources" / (video.stem + ".timeline.json")):
        if c.exists():
            return json.loads(c.read_text())
    return None


def _thumb(video: Path, t: float) -> bytes:
    import subprocess
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=48:86,format=gray", "-f", "rawvideo", "-"],
                       capture_output=True)
    return r.stdout


def _alike(a: bytes, b: bytes) -> bool:
    if not a or not b or len(a) != len(b):
        return False
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a) < 22


def seen_shots(video: Path):
    """One small grey frame from the middle of every cut. Names lie (the same photo as a .jpg in
    one variant and as a pre-rendered push clip in the other); pixels do not."""
    tl = _timeline_of(video)
    if not tl or not tl.get("shots"):
        return None, None
    frames = [_thumb(video, (s["t0"] + s["t1"]) / 2) for s in tl["shots"]]
    return frames, float(tl.get("duration") or tl["shots"][-1]["t1"])


def compare_seen(name_a, fa, da, voiced_a, name_b, fb, db, voiced_b):
    shared = sum(1 for x in fa if any(_alike(x, y) for y in fb))
    share = shared / max(1, min(len(fa), len(fb)))
    ratio = min(da, db) / max(da, db) if max(da, db) else 1.0
    axes = []
    if share < 0.60:
        axes.append(f"shots ({share:.0%} look the same)")
    if not _alike(fa[0], fb[0]):
        axes.append("hook")
    if not _alike(fa[-1], fb[-1]):
        axes.append("close")
    if voiced_a != voiced_b:
        axes.append("voice")
    length = f"length ({min(da, db):.1f} vs {max(da, db):.1f} s)" if ratio <= 0.75 else None
    return {"pair": f"{name_a} vs {name_b}", "shared_shots": round(share, 2),
            "length_ratio": round(ratio, 2), "differs_on": axes + ([length] if length and axes else []),
            "ok": bool(axes)}


def _voiced(video: Path):
    tl = _timeline_of(video) or {}
    return bool(tl.get("voice"))


def find_specs(paths):
    out = []
    for p in map(Path, paths):
        if p.is_dir():
            out += sorted(p.glob("[A-H]/spec.json"))
        else:
            out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args()
    videos = []
    for p in map(Path, a.specs):
        if p.is_dir() and any(p.glob("*.mp4")):
            videos += sorted(x for x in p.glob("*.mp4") if not x.stem.endswith(("-light", "-preview")))
        elif p.suffix.lower() == ".mp4":
            videos.append(p)
    if len(videos) >= 2:
        # the rendered files: compare what a viewer sees, cut by cut
        loaded = []
        for v in videos:
            frames, dur = seen_shots(v)
            if frames is None:
                sys.exit(f"compare_variants: {v} has no timeline sidecar (beside it or in resources/)")
            loaded.append((v.stem, frames, dur, _voiced(v)))
        pairs = [compare_seen(n1, f1, d1, v1, n2, f2, d2, v2)
                 for i, (n1, f1, d1, v1) in enumerate(loaded) for (n2, f2, d2, v2) in loaded[i + 1:]]
        names = [x[0] for x in loaded]
    else:
        files = find_specs(a.specs)
        if len(files) < 2:
            sys.exit("compare_variants: give two rendered variants, two specs, or a concept folder")
        loaded = [(f.parent.name if f.name == "spec.json" else f.stem, json.loads(f.read_text())) for f in files]
        pairs = [compare(n1, s1, n2, s2) for i, (n1, s1) in enumerate(loaded) for (n2, s2) in loaded[i + 1:]]
        names = [n for n, _ in loaded]
    report = {"variants": names, "pairs": pairs, "ok": all(p["ok"] for p in pairs)}
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if a.json_out:
        Path(a.json_out).write_text(text, encoding="utf-8")
    print(text)
    for p in pairs:
        if not p["ok"]:
            print(f"\n✗ {p['pair']}: a viewer would see the same video — {p['shared_shots']:.0%} of the "
                  f"shots shared, same hook, same close, same voice, lengths {p['length_ratio']:.0%} "
                  "apart. Change the hook, the close, the voice, or at least 40 % of the shots.",
                  file=sys.stderr)
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
