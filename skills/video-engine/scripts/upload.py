# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""The upload-ready encode: the one file that goes to TikTok / Reels / Shorts.

    uv run upload.py MASTER.mp4 OUT.mp4
    uv run upload.py MASTER.mp4 OUT.mp4 --fps 60      # only when the master really is 60 fps

Every platform re-encodes what it receives. What we control is what it starts from, and the rule
that matters is the one every guide agrees on: hand it a clean, high-bitrate, standard file and it
has less to destroy. So this is not "compress it small", it is "make it exactly what the platform's
own encoder expects, at the top of its useful range":

| | | why |
|---|---|---|
| Container, codec | MP4, H.264 High, `yuv420p` | the recommended pair in TikTok's own posting docs; H.265 and 10-bit get converted, badly |
| Size | 1080x1920 | anything larger is downscaled by the platform; smaller is upscaled and soft |
| Frame rate | constant, the master's (30 by default) | variable rate is resampled and stutters; don't invent 60 from 30 |
| Bitrate | quality-driven (CRF 17), capped at 14 Mbps | guides converge on 8-15 Mbps for 1080p30; above ~15 the platform throws it away, below ~6 its re-encode stacks on your artefacts |
| Keyframes | every 2 s, closed GOP | clean seeking, and the re-encode starts from whole frames |
| Colour | BT.709, limited range, **tagged** | an untagged file gets guessed at, and the guess shifts skin tones |
| Audio | AAC-LC, 48 kHz, stereo, 256 kbps | ≥192 kbps survives the platform's re-encode |
| Layout | `+faststart` | the upload starts processing before the last byte arrives |

What this cannot do is the app's side: **turn on "Upload in HD" / "Allow high-quality uploads"
when posting.** Without it the app compresses on the phone before sending, whatever the file.
The publishing notes say it every time.

Sources (Sep 2026): puritano.com/post/tiktok-video-specs · shortsync.app/guides/tiktok-video-
quality-settings · recapo.ai/blog/best-video-format-and-settings-for-tiktok · TikTok Content Posting
API docs (MP4 + H.264, 23-60 fps).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROFILE = {
    "width": 1080, "height": 1920, "crf": 17, "maxrate": "14M", "bufsize": "28M",
    "profile": "high", "level": "4.1", "gop_s": 2, "audio_bitrate": "256k", "audio_rate": 48000,
}


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,width,height,r_frame_rate:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True)
    return json.loads(r.stdout or "{}")


def encode(src, dst, fps=None, size=None):
    info = probe(src)
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    if fps is None:
        num, _, den = (v.get("r_frame_rate") or "30/1").partition("/")
        fps = round(float(num) / float(den or 1)) or 30
    w, h = size or (PROFILE["width"], PROFILE["height"])
    if (v.get("width"), v.get("height")) != (w, h):
        vf = f"scale={w}:{h}:flags=lanczos:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
    else:
        vf = "null"
    # setparams tags every frame; the -color_* output flags alone left the primaries and the transfer
    # untagged with libx264 (only the matrix got written), which is exactly the guess we avoid
    vf += ",format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src),
           "-vf", vf, "-r", str(fps), "-fps_mode", "cfr",
           "-c:v", "libx264", "-preset", "slow", "-crf", str(PROFILE["crf"]),
           "-maxrate", PROFILE["maxrate"], "-bufsize", PROFILE["bufsize"],
           "-profile:v", PROFILE["profile"], "-level", PROFILE["level"],
           "-g", str(int(fps * PROFILE["gop_s"])), "-keyint_min", str(int(fps * PROFILE["gop_s"])),
           "-sc_threshold", "0", "-flags", "+cgop",
           "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
           "-color_range", "tv"]
    if has_audio:
        cmd += ["-c:a", "aac", "-b:a", PROFILE["audio_bitrate"], "-ar", str(PROFILE["audio_rate"]),
                "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", str(dst)]
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True)
    return dst


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--fps", type=int, help="force a frame rate (default: the master's)")
    ap.add_argument("--size", help="WxH for the non-9:16 formats (default 1080x1920)")
    a = ap.parse_args()
    size = tuple(int(x) for x in a.size.lower().split("x")) if a.size else None
    encode(a.src, a.dst, a.fps, size)
    print(a.dst)


if __name__ == "__main__":
    main()
