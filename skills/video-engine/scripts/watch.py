# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = [
#   "numpy<2.3", "opencv-python",
#   "faster-whisper>=1.1", "av<19",
#   "pyobjc-framework-Vision; sys_platform == 'darwin'",
# ]
# ///
"""Watch a whole video, 0 to 100 %, the way a scoring agent needs it — not a strip of five frames.

    uv run watch.py VIDEO.mp4 [VIDEO2.mp4 ...]            # writes VIDEO.watch/ next to each one
    uv run watch.py VIDEO.mp4 --out refs/ --step 0.5       # frame every 0.5 s (default: by length)
    uv run watch.py VIDEO.mp4 --no-asr                     # skip the transcript

A frame strip answers "what does it look like"; a rubric asks "what happens at second 7, and does
the ending pay off the first second". That needs every second in front of the reader, the words
that are said, the words that are written, and where every cut falls. This writes all of it:

  VIDEO.watch/
    sheet-01.jpg …     every sampled frame from 0.00 s to the LAST frame, 4 x 3 per sheet, each
                       labelled with its time. Coverage is checked: the last tile is the last frame.
    watch.json         duration, cuts and shot lengths, pace per third, transcript (word-level
                       segments), on-screen text over time, loudness, speech share, first-second
                       and last-second facts
    WATCH.md           the same, readable, with the sheets listed in order

Used for two jobs: scoring reference videos from the platform against `references/rubric.md`, and
scoring our own renders with the SAME rubric (critic-reviewer, story-doctor). Same instrument for
both, or the comparison means nothing.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration:stream=codec_type,width,height,avg_frame_rate",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True)
    d = json.loads(out.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
    num, den = (v.get("avg_frame_rate") or "30/1").split("/")
    return {"duration": float(d["format"]["duration"]), "width": v.get("width"),
            "height": v.get("height"), "fps": float(num) / float(den or 1) if float(den or 1) else 30.0,
            "audio": any(s["codec_type"] == "audio" for s in d["streams"])}


def default_step(dur: float) -> float:
    return 0.5 if dur <= 35 else 1.0 if dur <= 100 else 2.0


def cuts(path: Path, thresh: float = 0.30) -> list[float]:
    """Hard cuts, from ffmpeg's scene score. Dissolves and whip-pans score lower; that is fine —
    a rubric counts what the eye reads as a new shot."""
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-vf",
                        f"select='gt(scene,{thresh})',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [round(float(m), 2) for m in re.findall(r"pts_time:([\d.]+)", r.stderr)]


def frames(path: Path, times: list[float]) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    out = []
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, img = cap.read()
        if not ok:                                   # past the last decodable frame: take the last one
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, cap.get(cv2.CAP_PROP_FRAME_COUNT) - 2))
            ok, img = cap.read()
        out.append(img if ok else np.zeros((1920, 1080, 3), np.uint8))
    cap.release()
    return out


def sheets(imgs, times, outdir: Path, cols=4, rows=3, w=300) -> list[str]:
    names = []
    per = cols * rows
    for s in range(math.ceil(len(imgs) / per)):
        tiles = []
        for img, t in list(zip(imgs, times))[s * per:(s + 1) * per]:
            h = int(img.shape[0] * w / img.shape[1])
            tile = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
            cv2.rectangle(tile, (0, 0), (84, 26), (0, 0, 0), -1)
            cv2.putText(tile, f"{t:6.2f}s", (4, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
            tiles.append(tile)
        h = max(t.shape[0] for t in tiles)
        tiles = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, 0, cv2.BORDER_CONSTANT) for t in tiles]
        while len(tiles) % cols:
            tiles.append(np.zeros_like(tiles[0]))
        grid = np.vstack([np.hstack(tiles[r * cols:(r + 1) * cols]) for r in range(len(tiles) // cols)])
        name = f"sheet-{s + 1:02d}.jpg"
        cv2.imwrite(str(outdir / name), grid, [cv2.IMWRITE_JPEG_QUALITY, 82])
        names.append(name)
    return names


def ocr(img) -> list[str]:
    try:
        import Vision
        from Foundation import NSData
    except ImportError:
        return []
    ok, png = cv2.imencode(".png", cv2.resize(img, (720, int(img.shape[0] * 720 / img.shape[1]))))
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(
        NSData.dataWithBytes_length_(png.tobytes(), len(png)), None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(0)
    if not handler.performRequests_error_([req], None)[0]:
        return []
    return [str(o.topCandidates_(1)[0].string()).strip() for o in (req.results() or [])
            if o.topCandidates_(1) and o.topCandidates_(1)[0].confidence() > 0.5]


def text_track(imgs, times) -> list[dict]:
    """On-screen text over time, merged while it stays the same."""
    track = []
    for img, t in zip(imgs, times):
        txt = " / ".join(x for x in ocr(img) if len(x) > 1)
        if track and track[-1]["text"] == txt:
            track[-1]["to"] = t
        else:
            track.append({"from": t, "to": t, "text": txt})
    return [x for x in track if x["text"]]


def loudness(path: Path) -> dict:
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-af",
                        "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    lra = re.findall(r"LRA:\s+([\d.]+) LU", r.stderr)
    return {"integrated_lufs": float(i[-1]) if i else None, "lra": float(lra[-1]) if lra else None}


def transcript(path: Path) -> dict:
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segs, info = model.transcribe(str(path), vad_filter=True, word_timestamps=False)
    out = [{"from": round(s.start, 2), "to": round(s.end, 2), "text": s.text.strip()}
           for s in segs if s.text.strip() and s.no_speech_prob < 0.6]
    return {"language": info.language, "segments": out}


def watch(path: Path, outdir: Path, step: float | None, asr: bool) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    p = probe(path)
    dur = p["duration"]
    step = step or default_step(dur)
    last = max(0.0, dur - 1.0 / (p["fps"] or 30))
    times = [round(i * step, 2) for i in range(int(last / step) + 1)]
    if last - times[-1] > 0.05:
        times.append(round(last, 2))                 # coverage: the final frame is always a tile
    cs = cuts(path)
    bounds = [0.0] + cs + [dur]
    # Fast montages cut faster than any grid: every shot gets at least one tile, its middle.
    mids = [round((a + b) / 2, 2) for a, b in zip(bounds, bounds[1:])
            if not any(a <= t < b for t in times)]
    times = sorted(set(times + [min(m, last) for m in mids]))
    imgs = frames(path, times)
    names = sheets(imgs, times, outdir)
    shots = [round(b - a, 2) for a, b in zip(bounds, bounds[1:]) if b - a > 0.04]
    thirds = [sum(1 for c in cs if dur * i / 3 <= c < dur * (i + 1) / 3) for i in range(3)]
    tx = transcript(path) if asr and p["audio"] else {"language": None, "segments": []}
    speech = sum(s["to"] - s["from"] for s in tx["segments"])
    text = text_track(imgs, times)
    first_text = next((x["text"] for x in text if x["from"] <= 1.0), "")
    res = {
        "file": str(path), "duration_s": round(dur, 2), "size": [p["width"], p["height"]],
        "coverage": {"step_s": step, "frames": len(times), "first": times[0], "last": times[-1],
                     "complete": times[0] == 0 and dur - times[-1] <= step},
        "sheets": names,
        "cuts": cs, "shots": len(shots),
        "shot_len": {"mean": round(float(np.mean(shots)), 2) if shots else dur,
                     "median": round(float(np.median(shots)), 2) if shots else dur,
                     "first": shots[0] if shots else dur, "longest": max(shots) if shots else dur},
        "cuts_per_third": thirds,
        "first_cut_s": cs[0] if cs else None,
        "text_on_screen": text,
        "text_in_first_second": first_text,
        "speech": {"language": tx["language"], "seconds": round(speech, 1),
                   "share": round(speech / dur, 2) if dur else 0, "starts_at": tx["segments"][0]["from"] if tx["segments"] else None},
        "transcript": tx["segments"],
        "loudness": loudness(path) if p["audio"] else None,
    }
    (outdir / "watch.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    md = [f"# {path.name}", "",
          f"- {res['duration_s']} s, {res['shots']} shots, mean shot {res['shot_len']['mean']} s "
          f"(first {res['shot_len']['first']} s), cuts per third {thirds}",
          f"- coverage: {len(times)} frames every {step} s, {times[0]} → {times[-1]} s "
          f"({'complete' if res['coverage']['complete'] else 'INCOMPLETE'})",
          f"- speech: {res['speech']['seconds']} s ({res['speech']['share']:.0%}), "
          f"starts at {res['speech']['starts_at']} s; loudness {res['loudness']}",
          f"- text in the first second: {first_text or '—'}", "", "## Sheets, in order", ""]
    md += [f"- {n}" for n in names]
    md += ["", "## Said", ""] + [f"- {s['from']:.1f}–{s['to']:.1f}: {s['text']}" for s in tx["segments"]]
    md += ["", "## Written on screen", ""] + [f"- {x['from']:.1f}–{x['to']:.1f}: {x['text']}" for x in text]
    (outdir / "WATCH.md").write_text("\n".join(md) + "\n")
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("videos", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, help="parent folder for the <name>.watch/ folders")
    ap.add_argument("--step", type=float, help="seconds between frames (default: 0.5 / 1 / 2 by length)")
    ap.add_argument("--no-asr", action="store_true")
    a = ap.parse_args()
    for v in a.videos:
        out = (a.out or v.parent) / (v.stem + ".watch")
        r = watch(v, out, a.step, not a.no_asr)
        print(f"{v.name}: {r['duration_s']} s, {r['coverage']['frames']} frames "
              f"({'complete' if r['coverage']['complete'] else 'INCOMPLETE'}), {r['shots']} shots → {out}")


if __name__ == "__main__":
    sys.exit(main())
