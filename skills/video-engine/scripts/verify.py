# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Checks a rendered MP4 before it is delivered. Nothing ships without passing this.

    uv run verify.py VIDEO.mp4
    uv run verify.py VIDEO.mp4 --script voice-script.json    # + "is the voice audible?"
    uv run verify.py VIDEO.mp4 --spec spec.json              # + "does it last what the spec says?"
    uv run verify.py VIDEO.mp4 --json report.json            # the same report, into a file

It prints a JSON with pass / warn / fail / skip per criterion and exits 1 if anything failed, so a
build script can stop on it. A `warn` never stops the build: it is something to look at, not a
broken file. It needs only `ffmpeg` and `ffprobe`.

Next to the MP4 the engine leaves `VIDEO.timeline.json` (what it burned in and where every cut
fell). The checks that judge text and the ending read it on their own; `--timeline` points at
another one and `--no-timeline` ignores it.

Criteria:

| key | fails when |
|---|---|
| `audio_track`  | there is no audio stream, or there is more than one |
| `duration`     | the audio does not last as long as the picture, or neither matches the expected length |
| `black_frames` | a black stretch outside the final fade (a badly placed cut, a missing source) |
| `silence`      | an audio hole longer than `--max-silence` outside the tail |
| `peak`         | the true peak goes above -0.5 dBTP |
| `voice_audible`| in a narrated stretch the voice band does not rise over the background (needs `--script`) |
| `text_sync`    | burned-in text drifts more than `--text-tolerance` (0.25 s) from the voice saying it |
| `text_cut`     | *warns*: text with no voice behind it stays on screen after its shot is gone |
| `voice_image`  | the voice names something (a segment's `says`) while another shot is on screen |
| `ending`       | *warns*: it ends on a dry cut — picture still moving, sound at full level, no fade, no closer, last shot under 0.6 s |
| `preview_size` | the review copy weighs more than `--max-preview-mb` |

`voice_audible` is the one that catches the failure nobody sees in a frame strip: a video delivered
with the narration buried under the clip's own audio. It measures the 300-3000 Hz band inside each
line's window and compares it with the same band in the stretches where nobody is speaking.

`text_sync` catches the other invisible one: subtitles timed by hand. Half a second of drift reads
as a dubbed video and no frame strip shows it, because every frame on its own looks right. The fix
is not to retype seconds: generate the narration, align it (`transcribe.py --align`) and let the
spec's `sync` take the times from the voice itself.

`voice_image` is the other half of the same contract: a segment declares what the voice names
while it is on screen (`"says": "la catedral"`) and the check reads the narration's own word times
to confirm the picture was there when the word was said.

`ending` is the "it cuts off too soon" the videos were getting: the last shot lasts a blink, there
is no fade and nothing closes the idea, so the video stops instead of ending. Two of its symptoms
are measured off the file itself and need no timeline — how much the picture is still moving in the
last half second against the video's own average, and whether the sound came down at all before the
last frame — so the check works on any MP4, including one somebody else rendered.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# The voice band, with steep enough slopes: with a single 2-pole filter a music bed leaks so
# much low end into the measurement that a buried voice still looks fine.
VOICE_BAND = ("highpass=f=300:poles=2", "highpass=f=300:poles=2",
              "lowpass=f=3000:poles=2", "lowpass=f=3000:poles=2")


# ------------------------------------------------------------ ffmpeg helpers

def ffprobe_json(*args):
    r = subprocess.run(["ffprobe", "-v", "error", *args, "-of", "json"], capture_output=True, text=True)
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def ffmpeg_stderr(video, filters, kind="a"):
    """Runs a detection filter and returns what it wrote to stderr. `kind`: 'a' audio, 'v' picture."""
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "info", "-i", str(video),
                        "-af" if kind == "a" else "-vf", filters, "-f", "null", "-"],
                       capture_output=True, text=True)
    return r.stderr


def level_db(video, t0, t1):
    """Mean level of the voice band (300-3000 Hz) in [t0, t1], in dB. None if it cannot measure."""
    if t1 - t0 <= 0.05:
        return None
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "info", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}",
                        "-i", str(video), "-af", ",".join(VOICE_BAND) + ",volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", r.stderr)
    return float(m.group(1)) if m else None


# ------------------------------------------------------------ the voice script

def parse_script(path):
    """[(second, text)] from a voice script: the JSON contract, or the old plain text."""
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    if str(path).lower().endswith(".json") or raw.lstrip().startswith("{"):
        # The `voice-script` contract (schemas/voice-script.schema.json) calls the second
        # **`start_s`**; `t`/`at` are what the older hand-written scripts used. Reading only `t`
        # put every line at 0, and `voice_audible` then measured the same window 22 times and
        # called a perfectly audible narration weak (caught 24 sep 2026).
        data = json.loads(raw)
        lines = data.get("lines", data) if isinstance(data, dict) else data
        def second(ln):
            for k in ("start_s", "t", "at"):
                if ln.get(k) is not None:
                    return float(ln[k])
            return 0.0
        return [(second(ln), str(ln["text"]).strip())
                for ln in lines if isinstance(ln, dict) and str(ln.get("text", "")).strip()]
    for candidate in (os.environ.get("REEL_FORGE_VOICE_SCRIPTS"),
                      Path(__file__).resolve().parent.parent.parent / "voices" / "scripts"):
        narrate = Path(candidate) / "narrate.py" if candidate else None
        if narrate and narrate.exists():
            sys.path.insert(0, str(narrate.parent))
            try:
                import narrate  # noqa: F401
                return narrate.parse(path)
            except Exception:
                break
    # Fallback, so verifying never depends on another skill being installed: "<second>  <sentence>".
    lines = []
    for ln in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        if re.match(r"[#\s]*(notes?|notas?|optional|opcional)\b", ln, re.I):
            break
        m = re.match(r"\s*(?:\[\s*)?~?\s*(\d+(?:\.\d+)?)\s*(?:\])?\s*(?:s\b)?\s*\|?\s+(.+)$", ln)
        if m and len(m.group(2).strip(" |")) >= 8:
            lines.append((float(m.group(1)), m.group(2).strip(" |")))
    return lines


def load_timeline(video, given, enabled=True):
    """The `VIDEO.timeline.json` the engine leaves: shots, burned-in text and voice windows."""
    if not enabled:
        return None
    path = Path(given) if given else video.with_name(video.stem + ".timeline.json")
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) and data.get("shots") is not None else None


def timeline_from_spec(spec_path):
    """A timeline worked out from the spec, for a render older than the sidecar.

    It carries the cuts and the captions the spec spells out; it does NOT carry what the engine
    expands on its own (`words`, `subs`, `sync`), so the text checks see less than with the real
    timeline. Better than nothing, and it says so in the report.
    """
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    beat = 60 / spec["bpm"] if spec.get("bpm") else None
    t, shots = float(spec.get("beat0", 0.0)), []
    for i, s in enumerate(spec.get("segments", [])):
        if "beats" in s:
            if beat is None:
                return None
            d = s["beats"] * beat
        elif "dur" in s:
            d = float(s["dur"])
        else:
            return None
        shots.append({"i": i, "t0": round(t, 3), "t1": round(t + d, 3), "dur": round(d, 3),
                      "src": Path(str(s.get("src", ""))).name or ("map" if "map" in s else "")})
        t += d
    caps = []
    for c in spec.get("captions", []):
        t0, t1 = c.get("t0"), c.get("t1")
        if c.get("seg") is not None:
            seg = c["seg"]
            i, j = (seg, seg) if isinstance(seg, int) else (seg[0], seg[-1])
            t0 = shots[i]["t0"] + float(c.get("lead", 0.0))
            t1 = shots[j]["t1"] + float(c.get("tail", 0.0))
        if t0 is None or t1 is None:
            continue
        caps.append({"t0": float(t0), "t1": float(t1), "text": c.get("text", ""),
                     "pos": c.get("pos", "low"),
                     "source": "cut" if c.get("seg") is not None else "spec"})
    return {"schema": "render-timeline/spec", "partial": True, "duration": round(t, 3),
            "fade_out": float(spec.get("fade_out", 0) or 0),
            "audio_fade_out": float(spec.get("audio_fade_out", 1.2) or 0),
            "shots": shots, "captions": caps, "voice": []}


def scene_cuts(video, threshold=0.35):
    """Cut times read off the picture, for when there is no timeline and no spec."""
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "info", "-i", str(video), "-vf",
                        f"select='gt(scene,{threshold})',metadata=print:file=-", "-an",
                        "-f", "null", "-"], capture_output=True, text=True)
    times = {round(float(m.group(1)), 3)
             for m in re.finditer(r"pts_time:(\d+(?:\.\d+)?)", r.stdout + r.stderr)}
    return sorted(times)


def tail_profile(video, v_dur, tail_s=0.5, fade_hint=0.0):
    """How the picture behaves at the end: is it still moving, and does it fade out.

    Returns `{"motion": ratio, "fade_s": seconds}` — or None when it cannot be measured.
    `fade_hint` is the fade the timeline declares, which wins over the measured one.

    `motion` is mean(frame-to-frame difference over the last `tail_s` of PICTURE) divided by the
    median of the same measurement over the body of the video. A shot that settles before the end
    comes back well under 1; one that stops mid-pan or mid-gesture comes back well over it. That
    ratio is the measurement behind "it got cut off", and it needs no timeline, no spec and no
    script, so it works on any MP4 — including one rendered before the sidecar existed.

    `fade_s` is how long the closing fade to black runs, read off the picture's own brightness.
    It matters twice: a fade is itself a way of landing, and the fade's frames are the biggest
    frame-to-frame differences in the file, so measuring motion through one reports every faded
    video as if it had been cut off. The fade is taken out before the motion is measured.

    One decode: `signalstats` gives the brightness (YAVG), `scdet` the difference (mafd), and the
    picture is scaled down first — neither number's ratio changes and it runs several times faster.
    """
    if v_dur <= tail_s * 2:
        return None
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(video), "-an", "-vf",
                        "scale=216:-2,signalstats,scdet=t=100,metadata=print:file=-",
                        "-f", "null", "-"], capture_output=True, text=True)
    frames, t, y = [], None, None
    for line in (r.stdout + r.stderr).splitlines():
        m = re.search(r"pts_time:(\d+(?:\.\d+)?)", line)
        if m:
            t, y = float(m.group(1)), None
            continue
        m = re.search(r"lavfi\.signalstats\.YAVG=(\d+(?:\.\d+)?)", line)
        if m:
            y = float(m.group(1))
            continue
        m = re.search(r"lavfi\.scd\.mafd=(\d+(?:\.\d+)?)", line)
        if m and t is not None:
            frames.append((t, float(m.group(1)), y))
    if len(frames) < 12:
        return None

    # The fade: the trailing run of frames whose brightness keeps dropping and ends well under the
    # video's own. A cut to black lands here too, and it is a landing just the same.
    lit = sorted(y for _t, _d, y in frames if y is not None)
    fade_from, fade_s = None, 0.0
    if lit:
        typical = lit[len(lit) // 2]
        run, prev = [], None
        # Walked backwards, a fade gets BRIGHTER frame by frame until it is back at the video's own
        # level. Anything that gets darker on the way back is not the fade any more.
        for t_, _d, y in reversed(frames):
            if y is None or (prev is not None and y < prev - 1.0):
                break
            run.append((t_, y))
            prev = y
            if y >= typical * 0.85:
                break
        # It only counts as a fade if it actually got dark and did not eat the whole video.
        if run and run[0][1] < max(2.0, typical * 0.5) and (v_dur - run[-1][0]) < min(3.0, v_dur / 3):
            fade_from = run[-1][0]
            fade_s = round(v_dur - fade_from, 3)
    fade_s = round(max(fade_s, float(fade_hint or 0.0)), 3)

    # Half a fade left inside the window would swamp the motion it is supposed to measure, and the
    # brightness walk tends to stop a few frames short on a shot that is itself moving, so the
    # window closes a little before the fade does.
    settled_end = (v_dur - fade_s - 0.1) if fade_s > 0.05 else v_dur
    body = sorted(d for t_, d, _y in frames if 0.5 < t_ < settled_end - tail_s - 0.1)
    tail = [d for t_, d, _y in frames if settled_end - tail_s <= t_ < settled_end]
    if not body or not tail:
        return {"motion": None, "fade_s": fade_s}
    median = body[len(body) // 2]
    if median < 0.05:          # an almost still video: the ratio would explode on sensor noise
        return {"motion": None, "fade_s": fade_s}
    return {"motion": (sum(tail) / len(tail)) / median, "fade_s": fade_s}


def mean_db(video, t0, t1):
    """Mean level of the whole band in [t0, t1], in dB. None if it cannot measure."""
    if t1 - t0 <= 0.05:
        return None
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "info", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}",
                        "-i", str(video), "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", r.stderr)
    return float(m.group(1)) if m else None


def spec_duration(spec_path):
    """The length the spec says, from the segment grid. None if it cannot be worked out."""
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    beat = 60 / spec["bpm"] if spec.get("bpm") else None
    t = float(spec.get("beat0", 0.0))
    for s in spec.get("segments", []):
        if "beats" in s:
            if beat is None:
                return None
            t += s["beats"] * beat
        elif "dur" in s:
            t += float(s["dur"])
        else:
            return None
    return t


# ------------------------------------------------------------ the checks

def check(report, key, ok, detail):
    report[key] = {"status": "pass" if ok else "fail", "detail": detail}
    return ok


def warn(report, key, ok, detail):
    """Like `check`, but it does not stop a build: something to look at, not a broken file."""
    report[key] = {"status": "pass" if ok else "warn", "detail": detail}
    return ok


def skip(report, key, why):
    report[key] = {"status": "skip", "detail": why}


def _words(text):
    """A caption reduced to what can be compared with a script line."""
    return re.sub(r"[^\w\s']+", " ", str(text).lower(), flags=re.UNICODE).split()


def find_phrase(words, phrase):
    """(t0, t1) of the phrase inside the narration's words, or None if it is never said."""
    want = _words(phrase)
    if not want or not words:
        return None
    have = [_words(w.get("text", "")) for w in words]
    flat = [(tok, i) for i, toks in enumerate(have) for tok in toks]
    for k in range(len(flat) - len(want) + 1):
        if [t for t, _i in flat[k:k + len(want)]] == want:
            first, last = flat[k][1], flat[k + len(want) - 1][1]
            return float(words[first]["t0"]), float(words[last]["t1"])
    return None


def line_openers(lines, captions):
    """Pairs every script line with the caption that opens it, matching by text.

    Only for renders with no timeline: when there is one, each caption already carries the second
    the voice says it (`audio_t0`) and nothing has to be guessed.
    """
    pairs = []
    for t, text in lines:
        head = _words(text)
        if not head:
            continue
        opener = None
        for c in sorted(captions, key=lambda x: x["t0"]):
            cw = _words(c.get("text", ""))
            if cw and cw == head[:len(cw)]:
                opener = c
                break
        if opener:
            pairs.append((t, opener))
    return pairs


def main():
    ap = argparse.ArgumentParser(description="Verifies a render before delivering it")
    ap.add_argument("video")
    ap.add_argument("--script", help="the voice-script of the narration (to check the voice is audible)")
    ap.add_argument("--spec", help="the spec it was rendered from (to check the length)")
    ap.add_argument("--duration", type=float, help="the expected length in seconds")
    ap.add_argument("--preview", help="the review copy; by default <video>-preview.mp4 if it exists")
    ap.add_argument("--tolerance", type=float, default=0.25, help="seconds of slack on the length")
    ap.add_argument("--max-silence", type=float, default=0.6, help="the longest acceptable audio hole")
    ap.add_argument("--peak", type=float, default=-0.5, help="the true-peak ceiling in dBTP")
    ap.add_argument("--voice-margin", type=float, default=4.0,
                    help="dB the voice band has to rise over the background while someone speaks")
    ap.add_argument("--timeline", help="the render's timeline; by default <video>.timeline.json")
    ap.add_argument("--no-timeline", action="store_true", help="ignore the timeline sidecar")
    ap.add_argument("--text-tolerance", type=float, default=0.25,
                    help="seconds of drift allowed between the burned-in text and the voice")
    ap.add_argument("--cut-tolerance", type=float, default=0.35,
                    help="seconds a text with no voice behind it may hold past its cut")
    ap.add_argument("--min-last-shot", type=float, default=0.6,
                    help="a last shot shorter than this reads as a video that got cut off")
    ap.add_argument("--closer-window", type=float, default=1.2,
                    help="seconds at the end where something on screen should close the idea")
    ap.add_argument("--max-end-motion", type=float, default=1.8,
                    help="how much motion the last half second may hold, as a multiple of the "
                         "video's own average: over it, the picture was still moving when it stopped")
    ap.add_argument("--min-end-taper", type=float, default=6.0,
                    help="dB the sound has to come down by on the last 0.3 s; under it nothing "
                         "tapered and the audio was cut at full level")
    ap.add_argument("--max-mb", type=float, default=120.0, help="ceiling for the delivered file")
    ap.add_argument("--max-preview-mb", type=float, default=30.0, help="ceiling for the review copy")
    ap.add_argument("--json", dest="json_out", help="write the report to this file as well")
    a = ap.parse_args()

    video = Path(os.path.expandvars(os.path.expanduser(a.video))).resolve()
    if not video.exists():
        sys.exit(f"missing file: {video}")

    probe = ffprobe_json("-show_entries", "stream=index,codec_type,duration,width,height:format=duration,size",
                         str(video))
    streams = probe.get("streams", [])
    fmt = probe.get("format", {})
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    container = float(fmt.get("duration") or 0)

    def stream_dur(s):
        try:
            return float(s.get("duration"))
        except (TypeError, ValueError):
            return container

    v_dur = stream_dur(video_streams[0]) if video_streams else 0.0
    a_dur = stream_dur(audio_streams[0]) if audio_streams else 0.0
    size_mb = float(fmt.get("size") or video.stat().st_size) / 1e6

    report = {}

    # 1. audio present, and exactly one track (two tracks is the classic zsh `$VAR[a1]` bug)
    check(report, "audio_track", len(audio_streams) == 1 and a_dur > 0,
          f"{len(audio_streams)} audio track(s), {a_dur:.2f} s" if audio_streams else "NO audio track")

    # 2. length: the audio has to last as long as the picture, and both what was asked for
    expected = a.duration if a.duration else (spec_duration(a.spec) if a.spec else None)
    detail = f"picture {v_dur:.2f} s, audio {a_dur:.2f} s"
    ok = abs(v_dur - a_dur) <= max(a.tolerance, 0.3) if audio_streams else False
    if expected:
        detail += f", expected {expected:.2f} s"
        ok = ok and abs(v_dur - expected) <= a.tolerance
    check(report, "duration", ok, detail)

    # 3. black frames, ignoring the final fade
    tail = max(0.0, v_dur - 1.0)
    blacks = [(float(m.group(1)), float(m.group(2))) for m in
              re.finditer(r"black_start:(\d+(?:\.\d+)?) black_end:(\d+(?:\.\d+)?)",
                          ffmpeg_stderr(video, "blackdetect=d=0.08:pix_th=0.12", "v"))]
    bad_black = [w for w in blacks if w[0] < tail]
    check(report, "black_frames", not bad_black,
          "no black frames" if not bad_black else
          "black at " + ", ".join(f"{s:.2f}-{e:.2f} s" for s, e in bad_black[:5]))

    # 4. audio holes, ignoring the tail (audio_fade_out) and a loop's own silence at the end
    if audio_streams:
        # silencedetect writes silence_start / silence_end on separate lines, and the last silence
        # can have no end (it runs to the end of the file): pair them in order, not with one regex.
        gaps, open_start = [], None
        for m in re.finditer(r"silence_(start|end):\s*(-?\d+(?:\.\d+)?)",
                             ffmpeg_stderr(video, f"silencedetect=n=-45dB:d={a.max_silence}")):
            if m.group(1) == "start":
                open_start = max(0.0, float(m.group(2)))
            elif open_start is not None:
                s0, s1 = open_start, float(m.group(2))
                open_start = None
                if s1 - s0 >= a.max_silence and s0 < tail:
                    gaps.append((s0, s1))
        if open_start is not None and open_start < tail:
            gaps.append((open_start, v_dur))
        check(report, "silence", not gaps,
              "no holes" if not gaps else
              "silence at " + ", ".join(f"{s:.2f}-{e:.2f} s" for s, e in gaps[:5]))
    else:
        skip(report, "silence", "there is no audio to measure")

    # 5. true peak
    if audio_streams:
        err = ffmpeg_stderr(video, "loudnorm=print_format=json")
        m = re.search(r'"input_tp"\s*:\s*"?(-?[\d.]+|-inf)"?', err)
        lufs = re.search(r'"input_i"\s*:\s*"?(-?[\d.]+|-inf)"?', err)
        if m and m.group(1) != "-inf":
            tp = float(m.group(1))
            check(report, "peak", tp <= a.peak,
                  f"true peak {tp:+.2f} dBTP (ceiling {a.peak:+.2f})" +
                  (f", integrated {lufs.group(1)} LUFS" if lufs else ""))
        else:
            skip(report, "peak", "ffmpeg did not report the peak")
    else:
        skip(report, "peak", "there is no audio to measure")

    # 6. the voice above the background, stretch by stretch
    if not a.script:
        skip(report, "voice_audible", "no --script: a narrated video has to be verified with it")
    elif not audio_streams:
        skip(report, "voice_audible", "there is no audio")
    else:
        lines = parse_script(a.script)
        if not lines:
            skip(report, "voice_audible", f"no lines parsed out of {a.script}")
        else:
            windows = []
            for i, (t, _text) in enumerate(lines):
                end = min(lines[i + 1][0] - 0.2, t + 2.5) if i + 1 < len(lines) else t + 2.5
                windows.append((t + 0.15, min(v_dur, max(t + 0.6, end))))
            # background = the stretches where nobody is speaking, away from the ramps
            gaps, cursor = [], 0.0
            for s0, s1 in windows:
                if s0 - cursor > 1.0:
                    gaps.append((cursor + 0.4, s0 - 0.4))
                cursor = max(cursor, s1)
            if v_dur - cursor > 1.0:
                gaps.append((cursor + 0.4, v_dur - 0.4))
            gaps = sorted(gaps, key=lambda g: g[1] - g[0], reverse=True)[:6]
            floor = sorted(x for x in (level_db(video, *g) for g in gaps) if x is not None)
            background = floor[len(floor) // 2] if floor else None
            weak = []
            for (s0, s1), (t, text) in zip(windows, lines):
                lv = level_db(video, s0, s1)
                if lv is None:
                    continue
                if lv < -45:
                    weak.append(f"{t:.2f}s silent ({lv:.1f} dB)")
                elif background is not None and lv - background < a.voice_margin:
                    weak.append(f"{t:.2f}s only {lv - background:+.1f} dB over the background")
            base = f"background {background:.1f} dB, " if background is not None else "no background to compare, "
            check(report, "voice_audible", not weak,
                  base + ("every line rises over it" if not weak else "; ".join(weak[:5])))

    # 7. the text: tied to the voice that says it, and to the shot it belongs to
    timeline = load_timeline(video, a.timeline, not a.no_timeline)
    if timeline is None and a.spec:
        timeline = timeline_from_spec(a.spec)
    captions = sorted(timeline.get("captions", []), key=lambda c: c["t0"]) if timeline else []
    shots = (timeline or {}).get("shots") or []
    partial = " (from the spec: it does not see `words`, `subs` or `sync`)" if timeline and timeline.get("partial") else ""

    synced = [c for c in captions if c.get("audio_t0") is not None]
    drifts = [(c, c["t0"] - float(c["audio_t0"])) for c in synced]
    narrated = bool((timeline or {}).get("voice")) or bool((timeline or {}).get("partial") and a.script)
    if not drifts and a.script and narrated:
        # Text typed by hand over a narration: nothing anchors it, so fall back to matching each
        # spoken line against the caption that opens it. It is coarser than the alignment and it is
        # exactly the case `sync` exists to remove.
        spec_text = [c for c in captions if c.get("source") in (None, "spec", "cut")]
        drifts = [(c, c["t0"] - t) for t, c in line_openers(parse_script(a.script), spec_text)]
    if drifts:
        off = [f"'{str(c.get('text', ''))[:24]}' {d:+.2f} s" for c, d in drifts
               if abs(d) > a.text_tolerance]
        worst = max(abs(d) for _c, d in drifts)
        check(report, "text_sync", not off,
              f"{len(drifts)} caption(s) against the voice, worst drift {worst:.2f} s "
              f"(ceiling {a.text_tolerance:.2f}){partial}" + ("; " + "; ".join(off[:5]) if off else ""))
    elif not captions:
        skip(report, "text_sync", "no timeline or spec with text: run it with --spec, or re-render "
                                  "so the engine leaves VIDEO.timeline.json")
    elif narrated:
        skip(report, "text_sync", "there is a narration but no text taken from it: if any caption "
                                  "repeats what the voice says, it has to come from `sync`")
    else:
        skip(report, "text_sync", "no narration behind the text: nothing to sync it against")

    boundaries = [s["t1"] for s in shots[:-1]]
    if captions and boundaries:
        # Text with a voice behind it follows the voice and may cross cuts. Text with none belongs
        # to its shot: if the shot is gone and the text is still there, it is floating.
        survivors = []
        for c in captions:
            # Text with audio behind it (the narration, or the clip's own voice) follows the audio.
            if c.get("audio_t0") is not None or c.get("source") not in (None, "spec"):
                continue
            crossed = [b for b in boundaries if c["t0"] + 0.15 < b < c["t1"] - 0.15]
            if crossed and (c["t1"] - crossed[0]) > a.cut_tolerance:
                survivors.append(f"'{str(c.get('text', ''))[:24]}' holds {c['t1'] - crossed[0]:.2f} s "
                                 f"past the cut at {crossed[0]:.2f} s")
        warn(report, "text_cut", not survivors,
             f"{len(captions)} caption(s) against {len(boundaries) + 1} shot(s){partial}" +
             ("" if not survivors else "; " + "; ".join(survivors[:5])))
    else:
        skip(report, "text_cut", "no timeline with shots and text")

    # 8. what the voice names has to be on screen while it names it
    promises = [(s, phrase) for s in shots
                for phrase in ([s["says"]] if isinstance(s.get("says"), str) else s.get("says") or [])]
    if not promises:
        skip(report, "voice_image", "no segment declares `says`: nothing promised, nothing to check")
    elif not (timeline or {}).get("words"):
        skip(report, "voice_image", "the timeline carries no narration words (render it with `sync`)")
    else:
        broken = []
        for shot, phrase in promises:
            win = find_phrase(timeline["words"], phrase)
            if win is None:
                broken.append(f"the voice never says '{phrase}' (shot {shot['i']})")
            elif win[1] < shot["t0"] - a.text_tolerance or win[0] > shot["t1"] + a.text_tolerance:
                broken.append(f"'{phrase}' is said at {win[0]:.2f}-{win[1]:.2f} s and its shot "
                              f"({shot['i']}) is on screen {shot['t0']:.2f}-{shot['t1']:.2f} s")
        check(report, "voice_image", not broken,
              f"{len(promises)} promise(s) checked against the voice, tolerance "
              f"{a.text_tolerance:.2f} s" + ("" if not broken else "; " + "; ".join(broken[:5])))

    # 9. the ending: does it end, or does it just stop?
    if shots:
        last_dur, last_t0 = shots[-1]["dur"], shots[-1]["t0"]
    else:
        cuts_seen = [c for c in scene_cuts(video) if c < v_dur - 0.05]
        last_t0 = cuts_seen[-1] if cuts_seen else None
        last_dur = (v_dur - last_t0) if last_t0 is not None else None
    closer = any(c["t1"] >= v_dur - a.closer_window for c in captions) if captions else None
    voice_tail = max([w[1] for w in (timeline or {}).get("voice", [])], default=None)

    # The measurements that need nothing but the file, so the check also works on a render whose
    # timeline was never kept: is the picture still moving, does it fade, did the sound taper.
    profile = tail_profile(video, v_dur, fade_hint=(timeline or {}).get("fade_out", 0)) or {}
    motion = profile.get("motion")
    faded = ((timeline["fade_out"] > 0.05) if timeline else
             (profile.get("fade_s", 0) > 0.08 or any(e >= v_dur - 0.15 for _s, e in blacks)))
    a_body = mean_db(video, 0.5, max(1.0, v_dur - 1.0)) if audio_streams else None
    a_tail = mean_db(video, max(0.0, v_dur - 0.3), v_dur) if audio_streams else None
    taper = (a_body - a_tail) if (a_body is not None and a_tail is not None) else None
    still_moving = motion is not None and motion >= a.max_end_motion
    flat_out = taper is not None and taper < a.min_end_taper

    symptoms = []
    if last_dur is not None and last_dur < a.min_last_shot:
        symptoms.append(f"the last shot lasts {last_dur:.2f} s (under {a.min_last_shot:g})")
    if still_moving:
        symptoms.append(f"the picture is still moving when it stops ({motion:.1f}x the video's own "
                        f"motion; ceiling {a.max_end_motion:g})")
    if flat_out:
        symptoms.append(f"the sound is at full level on the last frame (it only drops {taper:.1f} dB, "
                        f"and {a.min_end_taper:g} is the floor)")
    if not faded:
        symptoms.append("no fade at the end")
    if closer is False:
        symptoms.append(f"nothing on screen closes it in the last {a.closer_window:g} s")
    if voice_tail is not None and voice_tail > v_dur - 0.15:
        symptoms.append(f"the voice is still speaking at {voice_tail:.2f} s of {v_dur:.2f}")
    # One symptom on its own is a style choice (a hard cut into a loop is deliberate). Two together
    # is the video "getting cut off": the idea had not landed when the picture stopped. A picture
    # caught mid-motion is the one symptom that reads that way on its own, whatever else is right.
    bad = (len(symptoms) >= 2
           or still_moving
           or (last_dur is not None and last_dur < a.min_last_shot and not faded))
    if last_dur is None and not captions:
        skip(report, "ending", "I cannot tell where the last shot starts")
    else:
        # The two numbers travel with the verdict either way: the story-doctor argues about the
        # ending with them, and "it lands" is worth more when it says what was measured.
        measured = ", ".join(x for x in (
            f"end motion {motion:.1f}x" if motion is not None else None,
            f"sound down {taper:.1f} dB" if taper is not None else None) if x)
        if bad:
            detail = ("it ends on a dry cut: " + ", ".join(symptoms) +
                      (f", from {last_t0:.2f} s" if last_t0 is not None else ""))
        elif symptoms:
            detail = "it lands, but look at it: " + ", ".join(symptoms)
        else:
            detail = ("it lands: last shot " + (f"{last_dur:.2f} s" if last_dur is not None else "?") +
                      (", with a fade" if faded else ""))
        warn(report, "ending", not bad, detail + (f" [{measured}]" if measured else ""))

    # 10. weight: the delivery and the review copy
    preview = Path(a.preview) if a.preview else video.with_name(video.stem + "-preview.mp4")
    if preview.exists():
        p_mb = preview.stat().st_size / 1e6
        check(report, "preview_size", p_mb <= a.max_preview_mb,
              f"{preview.name}: {p_mb:.1f} MB (ceiling {a.max_preview_mb:g})")
    else:
        skip(report, "preview_size", "there is no review copy next to the video")
    check(report, "file_size", size_mb <= a.max_mb, f"{size_mb:.1f} MB (ceiling {a.max_mb:g})")

    failed = [k for k, v in report.items() if v["status"] == "fail"]
    warned = [k for k, v in report.items() if v["status"] == "warn"]
    out = {"file": str(video),
           "size": f"{video_streams[0].get('width')}x{video_streams[0].get('height')}" if video_streams else None,
           "duration": round(v_dur, 2), "ok": not failed, "failed": failed, "warnings": warned,
           "checks": report}
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if a.json_out:
        Path(a.json_out).write_text(text, encoding="utf-8")
    print(text)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
