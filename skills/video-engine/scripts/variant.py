# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Builds ONE variant from a declarative variant.json. The shared builder.

Every variant used to get its own ~400-line build.py, copied from the last one and adapted, and every
copy got something different wrong: one forgot `--update` on the export and aborted on a rebuild,
one never ran the gate, one shipped a 76 MB preview over a 30 MB ceiling, one laid its cuts in round
seconds when the engine had supported a beat grid all along. The part that is the same for every
variant lives here, once. What a builder agent writes is only what is particular to its variant: the
shots, the words, the song.

    uv run variant.py variant.json            # everything: voice, grid, audio, spec, render, gate
    uv run variant.py variant.json --plan     # print the grid and stop (seconds, and beats)
    uv run variant.py variant.json --spec     # stop after writing spec.json
    uv run variant.py variant.json --force    # rebuild even if the delivery is up to date

variant.json (paths relative to its own folder; `~` and `$VARS` expand):

    {
      "name": "harbour-walk-C",                  # delivery basename
      "delivery": "~/Movies/Reel Forge/<project>/v2/harbour-walk",
      "project": "~/Movies/Reel Forge/<project>", # optional: enables the facts check
      "progress": "../../../run/harbour-walk-C.json",   # optional: the unit's progress file
      "format": "9x16", "fps": 30, "crf": 22, "look": "clean", "grain": 0.006,
      "loop": false,                             # true: the last shot lands on the first frame
      "music": {"src": "trends/song.wav", "bpm": 69.84, "beat0": 1.138},  # preview bed + grid
      "grid": "auto",                            # auto = beats when music has a bpm, else seconds
      "voice": {"script": "voice-script.json", "engine": "auto", "language": "es-MX"},
      "shots": [
        {"src": "common/wall.mov", "start": 0.0, "beats": 2},          # 1st shot also eats beat0
        {"src": "common/train.mov", "start": 0.4, "beats": 6, "audio": {"lufs": -19}},
        {"src": "common/river.jpg", "beats": 6, "focus": [0.5, 0.52],
         "audio": {"from": "common/wall.mov", "start": 5.2, "lufs": -27, "filter": "lowpass=f=1000"}},
        {"src": "common/boat.mov", "start": 2.4, "beats": 6},
        {"src": "common/boat.jpg", "beats": 4, "audio": {"continue": true}},
        {"loop_to_first": true, "beats": 2}                             # the seamless loop
      ],
      "captions": [{"seg": 0, "lead": 0.0, "text": "The wall runs\\ninto the sea"}]
    }

A shot carries any engine segment key (kb, punch, focus, flash, speed, says, fit, subs, drift,
behind, cutout, map, end, tail, still...) and they pass straight to the spec. A Live Photo is a clip:

        {"src": "common/live/UUID.live.mov", "start": 0.0, "end": 2.1, "speed": 0.7, "dur": 3.4,
         "tail": "still", "still": "common/photos/UUID.jpg"}

  its movement (inside the window live.py measured), then the sharp still for the rest of the shot,
  with the Live's own sound under the movement. The builder adds:

  beats / dur     how long it holds. In a beat grid, `beats`; the FIRST shot also absorbs `beat0`,
                  the song's intro before its first hit, so the first cut lands on the beat.
  line            narrated: the index of the voice line spoken over this shot. Its length then
                  comes from the voice (lead + line + tail) and, in a beat grid, the cut is pushed
                  to the next half-beat so it still lands on the rhythm.
  audio           natural sound: {"lufs": -18} (its own track), {"from": SRC, "start": S} (a photo
                  borrowing its scene's ambience), {"continue": true} (the previous piece keeps
                  playing — a boat that should not cut mid-pass), or false (silence).
  loop_to_first   the last shot is the first clip reversed, trimmed so its last frame IS the
                  video's first frame; fades go to 0 and the gate measures the seam.

Defaults that used to be each builder's to remember, and were forgotten:
  * a caption on the first shot with lead <= 0.05 is `instant` (on screen from frame 1);
  * the concept's folder holds ONLY the upload-ready file (upload.py's profile); the preview, the
    light copy, the reports, the timeline and the voice-script go to its resources/ folder;
  * the preview and the light copy are re-encoded at 720p, so they fit their ceilings;
  * narration is Valentino when the language is Spanish and CapCut answers; otherwise the local
    voice, and the reason goes into the result so the README can say it;
  * the project's facts are checked against every line and caption BEFORE anything is rendered;
  * the finished file goes through verify.py and through framecheck.py, cut by cut;
  * one build per variant at a time (a lock), and an up-to-date delivery is not rebuilt.

Exit codes: 0 delivered and the gate passed · 1 the gate failed (the files are there, the result says
why) · 2 bad variant.json · 3 another build of this variant is running · 4 a line contradicts the
project's facts (nothing rendered).
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[2]
RENDER = HERE / "render.py"
VERIFY = HERE / "verify.py"
TRANSCRIBE = HERE / "transcribe.py"
FRAMECHECK = PLUGIN / "skills/sources/scripts/framecheck.py"
UPLOAD = HERE / "upload.py"
RESOURCES = "resources"          # same name as config.RESOURCES; config is not imported here
FORMAT_SIZES = {"9x16": (1080, 1920), "4x5": (1080, 1350), "1x1": (1080, 1080), "16x9": (1920, 1080)}
FACTS = PLUGIN / "skills/sources/scripts/facts.py"
VOICES = PLUGIN / "skills/voices/scripts"

DEFAULT_LUFS = -18.0
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".avif"}


class Bad(SystemExit):
    def __init__(self, msg):
        super().__init__(f"variant: {msg}")
        self.code = 2


# --------------------------------------------------------------------------- small helpers

def log(msg):
    print(f"· {msg}", flush=True)


def run(cmd, **kw):
    kw.setdefault("check", True)
    shown = " ".join(shlex.quote(str(c)) for c in cmd)
    print(f"  $ {shown[:200]}", flush=True)
    return subprocess.run([str(c) for c in cmd], **kw)


def ff(*args):
    return run(["ffmpeg", "-nostdin", "-y", "-v", "error", *args], capture_output=True, text=True)


def probe(path, entries, stream=None):
    cmd = ["ffprobe", "-v", "error"]
    if stream:
        cmd += ["-select_streams", stream]
    cmd += ["-show_entries", entries, "-of", "json", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def duration(path) -> float:
    d = probe(path, "format=duration").get("format", {}).get("duration")
    return float(d) if d else 0.0


def has_audio(path) -> bool:
    return bool(probe(path, "stream=index", "a").get("streams"))


def is_photo(path) -> bool:
    return Path(path).suffix.lower() in PHOTO_EXT


def lufs_of(path):
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "info", "-i", str(path), "-af",
                        "loudnorm=print_format=json", "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r'"input_i"\s*:\s*"(-?\d+(?:\.\d+)?)"', r.stderr)
    try:
        v = float(m[-1]) if m else None
    except ValueError:
        v = None
    return v if v is not None and v > -70 else None


def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------- the variant

class Variant:
    def __init__(self, cfg_path: Path):
        self.cfg_path = cfg_path.resolve()
        self.dir = self.cfg_path.parent
        try:
            self.cfg = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise Bad(f"{cfg_path} is not valid JSON: {e}")
        c = self.cfg
        for k in ("name", "delivery", "shots"):
            if k not in c:
                raise Bad(f"variant.json needs `{k}`")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", c["name"]):
            raise Bad("`name` is a file basename: letters, digits, dot, dash, underscore")
        if not c["shots"]:
            raise Bad("`shots` is empty")
        self.name = c["name"]
        self.delivery = self.path(c["delivery"])        # the concept's folder: upload-ready files only
        self.res = self.delivery / RESOURCES             # everything else a person does not upload
        self.tmp = self.dir / "tmp"
        self.voice_dir = self.dir / "voice"
        self.out = self.delivery / f"{self.name}.mp4"            # the upload-ready encode
        self.master = self.res / f"{self.name}.render.mp4"        # what the engine renders
        self.music = c.get("music") or {}
        bpm = self.music.get("bpm")
        grid = c.get("grid", "auto")
        if grid not in ("auto", "beats", "seconds"):
            raise Bad("`grid` is auto, beats or seconds")
        self.beats_mode = (grid == "beats") or (grid == "auto" and bool(bpm))
        if self.beats_mode and not bpm:
            raise Bad("a beat grid needs `music.bpm`")
        self.beat = 60.0 / float(bpm) if bpm else None
        self.beat0 = float(self.music.get("beat0", 0.0)) if bpm else 0.0
        self.voice_cfg = c.get("voice") or None
        self.loop = bool(c.get("loop"))
        self.warnings: list[str] = []
        self.shots = [dict(s) for s in c["shots"]]
        for i, s in enumerate(self.shots):
            if s.get("loop_to_first"):
                if i != len(self.shots) - 1:
                    raise Bad("`loop_to_first` only goes on the LAST shot")
                self.loop = True
                continue
            if "src" not in s and "map" not in s:
                raise Bad(f"shot {i} has no `src`")
            if "src" in s:
                s["src"] = str(self.path(s["src"]))
                if not Path(s["src"]).exists():
                    raise Bad(f"shot {i}: {s['src']} does not exist")
            if s.get("still"):
                s["still"] = str(self.path(s["still"]))
                if not Path(s["still"]).exists():
                    raise Bad(f"shot {i}: its still {s['still']} does not exist")

    def path(self, p) -> Path:
        p = os.path.expandvars(os.path.expanduser(str(p)))
        q = Path(p)
        return q if q.is_absolute() else (self.dir / q).resolve()

    # ------------------------------------------------------------------ progress and lock

    def progress(self, step, **extra):
        p = self.cfg.get("progress")
        if not p:
            return
        d = {"unit": self.cfg.get("unit", self.name), "status": "running", "step": step,
             "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")}
        d.update(extra)
        atomic_json(self.path(p), d)

    def lock(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lockf = open(self.dir / ".build.lock", "a+")
        try:
            fcntl.flock(self._lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lockf.seek(0)
            who = self._lockf.read().strip() or "another process"
            print(f"variant: {self.name} is already being built ({who}). Two builds of one variant "
                  "overwrite each other's files mid-render — wait for it, or kill it first.",
                  file=sys.stderr)
            sys.exit(3)
        self._lockf.seek(0)
        self._lockf.truncate()
        self._lockf.write(f"pid {os.getpid()} since {time.strftime('%H:%M:%S')}")
        self._lockf.flush()

    def fingerprint(self) -> str:
        h = hashlib.sha256(self.cfg_path.read_bytes())
        if self.voice_cfg and self.voice_cfg.get("script"):
            vs = self.path(self.voice_cfg["script"])
            if vs.exists():
                h.update(vs.read_bytes())
        h.update(Path(__file__).read_bytes())
        return h.hexdigest()[:16]

    def up_to_date(self) -> bool:
        res = self.dir / "build.json"
        if not (res.exists() and self.out.exists()):
            return False
        try:
            r = json.loads(res.read_text())
        except json.JSONDecodeError:
            return False
        return r.get("fingerprint") == self.fingerprint() and r.get("gate_ok") is True

    # ------------------------------------------------------------------ voice

    def lines(self):
        if not self.voice_cfg:
            return None
        vs = self.path(self.voice_cfg["script"])
        if not vs.exists():
            raise Bad(f"voice script {vs} does not exist")
        data = json.loads(vs.read_text(encoding="utf-8"))
        lines = data.get("lines") if isinstance(data, dict) else data
        if not lines:
            raise Bad(f"{vs} has no lines")
        return data, [(l["text"] if isinstance(l, dict) else str(l)).strip() for l in lines]

    def make_voice(self, texts):
        """l{i}.wav + durations.json in voice/. CapCut's voice first when it is the resolved
        default; the local engine otherwise, capped so no line outruns the gate's window."""
        v = self.voice_cfg
        dfile = self.voice_dir / "durations.json"
        info_f = self.voice_dir / "engine.json"
        if dfile.exists() and info_f.exists():
            return json.loads(dfile.read_text()), json.loads(info_f.read_text())
        self.voice_dir.mkdir(parents=True, exist_ok=True)
        lines_f = self.tmp / "lines.json"
        self.tmp.mkdir(parents=True, exist_ok=True)
        lines_f.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
        lang = v.get("language") or self.cfg.get("language") or "es-MX"
        engine = v.get("engine", "auto")
        why = None
        if engine == "auto":
            r = subprocess.run(["uv", "run", VOICES / "resolve_voice.py", "--lang", lang, "--json"],
                               capture_output=True, text=True)
            try:
                res = json.loads(r.stdout)
            except json.JSONDecodeError:
                res = {"engine": "qwen", "reason": "resolve_voice.py gave no answer"}
            engine = res.get("engine", "qwen")
            v = {**{"voice": res.get("voice"), "speed": res.get("speed")}, **{k: x for k, x in v.items() if x is not None}}
        refused = self.dir / ".capcut-refused"
        if engine == "capcut":
            if refused.exists() and not v.get("retry_capcut"):
                why = refused.read_text().strip()
            else:
                r = run(["uv", "run", VOICES / "capcut_voice.py", lines_f, self.voice_dir,
                         "--speed", str(v.get("speed") or 1.4), "--voice", v.get("voice") or "Valentino"],
                        check=False, capture_output=True, text=True)
                if dfile.exists():
                    info = {"engine": "capcut", "voice": v.get("voice") or "Valentino",
                            "speed": v.get("speed") or 1.4, "fallback": False, "disclose": None}
                    atomic_json(info_f, info)
                    return json.loads(dfile.read_text()), info
                tail = (r.stdout + r.stderr).strip().splitlines()
                why = next((t for t in reversed(tail) if "Diagnosis" in t or "CapCut" in t),
                           tail[-1] if tail else f"capcut_voice.py exit {r.returncode}")
                refused.write_text(why[:400])
            log(f"CapCut did not narrate ({why[:120]}); local voice instead")
        # the local engine
        raw = self.dir / "voice-raw"
        local = v.get("local_voice") or ("narrador-mx" if lang.startswith("es") else None)
        cmd = ["uv", "run", VOICES / "voice.py", lines_f, raw, "--engine", v.get("local_engine", "qwen")]
        if local:
            cmd += ["--voice", local]
        if lang.startswith("es"):
            cmd += ["--language", "Spanish", "--preset", "tiktok"]
        if not (raw / "durations.json").exists():
            run(cmd)
        speed = float(v.get("local_speed", 1.15))
        cap = float(v.get("line_cap", 2.4))
        durs = {}
        for i in range(len(texts)):
            src, dst = raw / f"l{i}.wav", self.voice_dir / f"l{i}.wav"
            tempo = speed * max(1.0, duration(src) / speed / cap)
            ff("-i", src, "-af", f"atempo={tempo:.4f},loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", dst)
            durs[f"l{i}"] = round(duration(dst), 3)
        atomic_json(dfile, durs)
        # the engine's real name (qwen, voxcpm, piper): "local" is not in voice-script.schema.json,
        # and writing it made every narrated delivery fail its own contract on each rebuild
        info = {"engine": v.get("local_engine", "qwen"), "voice": local, "speed": speed, "fallback": True,
                "disclose": ("Narrated with the local voice, not with CapCut's Valentino"
                             + (f": {why}" if why else ".") +
                             " The trend voice can be swapped in without re-rendering: every line "
                             "and its second are in the voice-script.")}
        atomic_json(info_f, info)
        return durs, info

    # ------------------------------------------------------------------ the grid

    def snap(self, t, unit):
        """First grid point at or after t, on the absolute grid anchored at beat0."""
        n = math.ceil((t - self.beat0) / unit - 1e-6)
        return self.beat0 + n * unit

    def grid(self, durs=None):
        """[{i, t0, t1, voice_at, voice_dur}] — cut times on an ABSOLUTE grid, never accumulated."""
        v = self.voice_cfg or {}
        lead0, lead, tail = 0.0, float(v.get("lead", 0.14)), float(v.get("tail", 0.30))
        hold = float(v.get("close_hold", 0.95))
        half = (self.beat / 2) if self.beats_mode else None
        out, t = [], 0.0
        for i, s in enumerate(self.shots):
            last = i == len(self.shots) - 1
            vd = None
            if s.get("line") is not None:
                if durs is None:
                    raise Bad(f"shot {i} carries `line` but there is no voice")
                vd = float(durs[f"l{s['line']}"])
                need = (lead0 if i == 0 else lead) + vd + (hold if last else tail)
                if self.beats_mode:
                    t1 = self.snap(t + need, half)
                else:
                    t1 = t + need
            elif self.beats_mode:
                if "beats" not in s:
                    raise Bad(f"shot {i} needs `beats` in a beat grid (or `line` if narrated)")
                b = float(s["beats"])
                if i == 0:
                    t1 = self.beat0 + b * self.beat
                else:
                    t1 = self.snap(t, self.beat) + b * self.beat
            else:
                if "dur" not in s:
                    raise Bad(f"shot {i} needs `dur` in a seconds grid")
                t1 = t + float(s["dur"])
            row = {"i": i, "t0": round(t, 4), "t1": round(t1, 4), "dur": round(t1 - t, 4)}
            if vd is not None:
                row["voice_at"] = round(t + (lead0 if i == 0 else lead), 4)
                row["voice_dur"] = vd
                row["line"] = s["line"]
            if self.beats_mode:
                row["beat"] = round((t1 - self.beat0) / self.beat, 2)
            out.append(row)
            t = t1
        return out

    def plan(self, g):
        total = g[-1]["t1"]
        print(f"{self.name}: {len(g)} shots, {total:.3f} s" +
              (f", {self.music.get('bpm')} BPM, beat {self.beat:.5f} s, anchor {self.beat0} s"
               if self.beats_mode else ", seconds grid"))
        for r in g:
            b = f"  → beat {r['beat']:g}" if "beat" in r else ""
            vl = f"  line {r['line']} at {r['voice_at']:.2f} ({r['voice_dur']:.2f} s)" if "line" in r else ""
            src = Path(self.shots[r['i']].get("src", "loop→first")).name
            print(f"  {r['i']:2}  {r['t0']:7.3f} → {r['t1']:7.3f}  ({r['dur']:.2f}){b}{vl}   {src}")
        # a narrated gap longer than the gate's silence floor, with nothing natural under it
        return total

    # ------------------------------------------------------------------ the loop shot

    def loop_shot(self, g):
        first = self.shots[0]
        if is_photo(first["src"]):
            raise Bad("`loop_to_first` needs the FIRST shot to be a video clip")
        if float(first.get("speed", 1)) != 1:
            raise Bad("`loop_to_first` needs the first shot at speed 1")
        if first.get("kb") or first.get("punch"):
            self.warnings.append("the first shot moves (kb/punch): the loop seam cannot meet exactly")
        d = g[-1]["dur"]
        length = d + 0.25
        s0 = float(first.get("start", 0.0))
        rev = self.tmp / "loop-reversed.mp4"
        if not rev.exists():
            self.tmp.mkdir(parents=True, exist_ok=True)
            ff("-ss", f"{s0:.3f}", "-t", f"{length:.3f}", "-i", first["src"], "-vf", "reverse", "-an",
               "-c:v", "libx264", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p", rev)
        return {"src": str(rev), "start": round(duration(rev) - d, 3), "kb": 0.0}

    # ------------------------------------------------------------------ natural sound

    def natural_audio(self, g, total):
        nat = self.cfg.get("natural") or {}
        overlap, fade = float(nat.get("overlap", 0.15)), float(nat.get("fade", 0.06))
        pieces = []                       # (t0, t1, src, start, lufs, filter, speed)
        for r in g:
            s = self.shots[r["i"]]
            a = s.get("audio", {})
            if a is False:
                continue
            if isinstance(a, dict) and a.get("continue") and pieces:
                pieces[-1][1] = r["t1"]
                continue
            if s.get("loop_to_first"):
                first = self.shots[0]
                src, start = first["src"], float(first.get("start", 0.0))
                spd = 1.0
            elif isinstance(a, dict) and a.get("from"):
                src, start, spd = str(self.path(a["from"])), float(a.get("start", 0.0)), 1.0
            else:
                src, start = s.get("src"), float(s.get("start", 0.0))
                spd = float(s.get("speed", 1) or 1)
                if s.get("end") is not None:
                    # the picture stops at `end` (a Live Photo's phone going down); its sound does
                    # too, or the shot plays the rustle of the pocket under the still
                    t_end = r["t0"] + (float(s["end"]) - start) / spd
                    if t_end < r["t1"] - 0.05:
                        pieces.append([r["t0"], max(r["t0"] + 0.2, t_end), src, start,
                                       float(a.get("lufs", DEFAULT_LUFS)) if isinstance(a, dict) else DEFAULT_LUFS,
                                       a.get("filter") if isinstance(a, dict) else None, spd])
                        if not has_audio(src):
                            pieces.pop()
                        continue
            if not src or is_photo(src) or not has_audio(src):
                if not (isinstance(a, dict) and a.get("from")):
                    self.warnings.append(f"shot {r['i']} has no sound under it (a photo with no "
                                         "`audio.from`): the gate may call that a hole")
                continue
            lufs = float(a.get("lufs", DEFAULT_LUFS)) if isinstance(a, dict) else DEFAULT_LUFS
            pieces.append([r["t0"], r["t1"], src, start, lufs,
                           a.get("filter") if isinstance(a, dict) else None, spd])
        if not pieces:
            return None
        self.tmp.mkdir(parents=True, exist_ok=True)
        ins, filt, labels = [], [], []
        for k, (t0, t1, src, start, lufs, extra, spd) in enumerate(pieces):
            last = k == len(pieces) - 1
            d = (t1 - t0) + (0.0 if last else overlap)
            raw = self.tmp / f"nat{k:02d}.wav"
            af = ["aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"]
            if 0.5 <= spd <= 2 and spd != 1:
                af.append(f"atempo={spd}")
            if extra:
                af.append(extra)
            af.append("dynaudnorm=f=180:g=21:p=0.62")
            ff("-ss", f"{start:.3f}", "-t", f"{d * spd:.3f}", "-i", src, "-map", "0:a:0",
               "-af", ",".join(af), raw)
            cur = lufs_of(raw)
            gain = max(-30.0, min(30.0, (lufs - cur) if cur is not None else 0.0))
            ins += ["-i", str(raw)]
            fo = 0.0 if (last and self.loop) else fade
            filt.append(f"[{k}:a]volume={gain:.2f}dB,afade=t=in:st=0:d={fade}"
                        + (f",afade=t=out:st={max(0.0, d - fo):.3f}:d={fo}" if fo else "")
                        + f",adelay={int(t0 * 1000)}|{int(t0 * 1000)}[a{k}]")
            labels.append(f"[a{k}]")
        out = self.tmp / "natural.wav"
        filt.append("".join(labels) + f"amix=inputs={len(pieces)}:normalize=0:dropout_transition=0,"
                    f"apad=whole_dur={total:.3f},atrim=0:{total:.3f},"
                    f"loudnorm=I={nat.get('lufs', -16)}:TP=-2.0:LRA=11,alimiter=limit=0.85:level=false[m]")
        ff(*ins, "-filter_complex", ";".join(filt), "-map", "[m]", "-ar", "48000", "-ac", "2", out)
        return out

    def music_bed(self, total):
        """The song under the -preview only, looped on a whole number of bars from beat0 so the second
        pass stays on the same grid. The clean MP4 never carries it."""
        src = self.music.get("src")
        if not src:
            return None
        src = self.path(src)
        if not src.exists():
            self.warnings.append(f"music {src} not found: the preview goes out without it")
            return None
        out = self.tmp / "bed.wav"
        d = duration(src)
        if self.beat:
            bars = max(1, int((d - self.beat0) // (4 * self.beat)))
            seg = (self.beat0, self.beat0 + bars * 4 * self.beat)
        else:
            seg = (0.0, d)
        reps = max(1, math.ceil(total / (seg[1] - seg[0])) + 1)
        parts = [f"[0:a]atrim=0:{seg[1]:.3f},asetpts=N/SR/TB[p0]"]
        for k in range(1, reps):
            parts.append(f"[0:a]atrim={seg[0]:.3f}:{seg[1]:.3f},asetpts=N/SR/TB[p{k}]")
        parts.append("".join(f"[p{k}]" for k in range(reps)) + f"concat=n={reps}:v=0:a=1,"
                     f"atrim=0:{total:.3f},asetpts=N/SR/TB,"
                     f"loudnorm=I={self.music.get('lufs', -22)}:TP=-2:LRA=11[o]")
        ff("-i", src, "-filter_complex", ";".join(parts), "-map", "[o]", "-ar", "48000", "-ac", "2", out)
        return out

    # ------------------------------------------------------------------ spec

    def spec(self, g, total, natural, bed, voice_info, durs):
        segs = []
        for r in g:
            s = self.shots[r["i"]]
            if s.get("loop_to_first"):
                seg = self.loop_shot(g)
            else:
                seg = {k: val for k, val in s.items()
                       if k not in ("beats", "dur", "line", "audio", "loop_to_first", "note", "id")}
            seg["dur"] = round(r["dur"], 6)
            if s.get("id"):
                seg["_id"] = s["id"]
            segs.append(seg)
        caps = []
        for c in self.cfg.get("captions", []):
            c = dict(c)
            if c.get("seg") == 0 and float(c.get("lead", 0.15)) <= 0.05 and "instant" not in c:
                c["instant"] = True          # the hook is on screen from frame 1
            caps.append(c)
        spec = {"out": str(self.master), "format": self.cfg.get("format", "9x16"),
                "fps": self.cfg.get("fps", 30), "crf": self.cfg.get("crf", 22),
                "look": self.cfg.get("look", "clean"), "grain": self.cfg.get("grain", 0.006),
                "loop": self.loop,
                "fade_out": 0.0 if self.loop else self.cfg.get("fade_out", 0.45),
                "audio_fade_out": 0.0 if self.loop else self.cfg.get("audio_fade_out", 1.2),
                "duck": bool(self.voice_cfg),
                "segments": segs, "captions": caps, "audio": []}
        if self.music.get("bpm"):
            spec["bpm"] = self.music["bpm"]
        if natural:
            spec["audio"].append({"src": str(natural), "at": 0.0, "gain": 1.0, "role": "bed"})
        if durs is not None:
            gain = float(self.voice_cfg.get("gain", 1.3))
            for r in g:
                if "line" in r:
                    spec["audio"].append({"src": str(self.voice_dir / f"l{r['line']}.wav"),
                                          "at": r["voice_at"], "gain": gain})
            sy = {"from": str(self.voice_dir / "alignment.json"), "style": "clean", "pos": "low", "size": 52}
            sy.update(self.voice_cfg.get("sync", {}))
            spec["sync"] = sy
        if bed:
            spec["preview_audio"] = {"src": str(bed), "offset": 0.0, "gain": 1.0}
        for extra in ("map_style", "stamp", "title"):
            if extra in self.cfg:
                spec[extra] = self.cfg[extra]
        return spec

    # ------------------------------------------------------------------ outputs

    def light(self, src, dst):
        ff("-i", src, "-vf", "scale=720:-2", "-c:v", "libx264", "-crf", "26", "-preset", "slow",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dst)

    def framecheck(self, g):
        """Every cut of the RENDERED file, in one process. A report for the critic, not a gate."""
        cat = self.tmp / "cuts.json"
        items = [{"id": f"cut-{r['i']:02d}", "path": str(self.out), "type": "video",
                  "start_s": round(r["t0"] + 0.15, 3), "end_s": round(max(r["t0"] + 0.2, r["t1"] - 0.15), 3)}
                 for r in g]
        atomic_json(cat, {"batch": self.name, "items": items})
        side = self.res / f"{self.name}-framecheck.json"
        r = run(["uv", "run", FRAMECHECK, "--catalog", cat, "--root", "/", "--json", side],
                check=False, capture_output=True, text=True)
        try:
            ids = json.loads(r.stdout).get("flagged_ids", {})
        except json.JSONDecodeError:
            ids = {}
        # A lone straight edge is a judgement (a train window can be the shot); it stays in the
        # sidecar. What is flagged is what blocks: bystanders, dirty glass.
        flagged = {k: v for k, v in ids.items() if set(v) - {"frame"}}
        return side, flagged

    def publish_notes(self, g, total, voice_info, gate_ok, flagged):
        lines = [f"# {self.name}", "", f"- Length: {total:.2f} s, {len(g)} cuts.",
                 f"- Upload `{self.out.name}` (the file loose in the concept's folder): 1080x1920, H.264 "
                 "High, BT.709, ~14 Mbps cap, AAC 256 kbps. **Turn on \"Upload in HD\" / \"Allow "
                 "high-quality uploads\" when posting**, or the app compresses it on the phone first."]
        if self.beats_mode:
            lines += [f"- Cuts on the beat of **{Path(str(self.music.get('src', ''))).stem}** "
                      f"({self.music.get('bpm')} BPM; first hit at {self.beat0:.3f} s).",
                      "- **When publishing, add the official sound WITHOUT trimming it — from its "
                      "second 0.** The grid is anchored to the song's first hit; start the sound "
                      "anywhere else and every cut lands off the beat."]
        if self.loop:
            lines.append("- It closes in a loop: the last frame is the first. Let it repeat.")
        if voice_info:
            lines.append(f"- Voice: {voice_info.get('engine')} / {voice_info.get('voice')}.")
            if voice_info.get("disclose"):
                lines.append(f"- {voice_info['disclose']}")
        lines.append(f"- Gate: {'passed' if gate_ok else 'FAILED — see the verify JSON'}.")
        if flagged:
            lines.append("- framecheck flagged cuts for a second look: " +
                         ", ".join(f"{k} ({', '.join(v)})" for k, v in flagged.items()))
        if self.warnings:
            lines += ["", "Warnings:"] + [f"- {w}" for w in self.warnings]
        p = self.res / f"{self.name}-publish.md"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return p


# --------------------------------------------------------------------------- the build

def build(v: Variant, a):
    v.lock()
    if v.up_to_date() and not a.force and not (a.plan or a.spec):
        print(f"{v.name}: the delivery is up to date and passed the gate — nothing to do "
              "(--force rebuilds it).")
        return 0
    v.tmp.mkdir(parents=True, exist_ok=True)
    v.delivery.mkdir(parents=True, exist_ok=True)
    v.res.mkdir(parents=True, exist_ok=True)
    v.progress("start")

    durs = voice_info = vs_data = None
    lines = v.lines()
    if lines and not a.plan:
        vs_data, texts = lines
        v.progress("voice")
        log("voice")
        durs, voice_info = v.make_voice(texts)
    elif lines:
        vs_data, texts = lines
        # a plan without generating anything: estimate each line from its words
        durs = {f"l{i}": round(0.33 * len(t.split()) + 0.2, 2) for i, t in enumerate(texts)}

    g = v.grid(durs)
    total = v.plan(g)
    if a.plan:
        if lines:
            print("  (line lengths ESTIMATED from word count: generate the voice for the real grid)")
        return 0

    # the voice-script that ships carries the real seconds
    if vs_data is not None:
        at = {r["line"]: r for r in g if "line" in r}
        items = vs_data["lines"] if isinstance(vs_data, dict) else vs_data
        for i, ln in enumerate(items):
            if isinstance(ln, dict) and i in at:
                ln["start_s"] = at[i]["voice_at"]
                ln["duration_hint_s"] = at[i]["voice_dur"]
                ln["wav"] = f"l{i}.wav"
        if isinstance(vs_data, dict):
            vs_data["video_duration_s"] = round(total, 3)
            if voice_info:
                vs_data["engine"] = voice_info.get("engine")
                vs_data["voice"] = voice_info.get("voice")
        atomic_json(v.path(v.voice_cfg["script"]), vs_data)
        # word-by-word alignment: the captions come from the voice, never from typed seconds
        v.progress("align")
        align_in = v.tmp / "align-lines.json"
        atomic_json(align_in, {"lang": (v.voice_cfg.get("language") or "es")[:2],
                               "lines": [{"start_s": r["voice_at"], "text": texts[r["line"]],
                                          "file": f"l{r['line']}.wav"} for r in g if "line" in r]})
        run(["uv", "run", TRANSCRIBE, "--align", v.voice_dir, "--script", align_in,
             "--language", (v.voice_cfg.get("language") or "es")[:2]])

    v.progress("audio")
    log("natural sound")
    natural = v.natural_audio(g, total)
    log("music bed (preview only)")
    bed = v.music_bed(total)
    spec = v.spec(g, total, natural, bed, voice_info, durs)
    spec_f = v.dir / "spec.json"
    atomic_json(spec_f, spec)

    # the facts, before a single frame is rendered
    project = v.cfg.get("project") or os.environ.get("REEL_FORGE_PROJECT")
    if project and (v.path(project) / "facts.json").exists():
        v.progress("facts")
        files = [spec_f] + ([v.path(v.voice_cfg["script"])] if v.voice_cfg else [])
        r = run(["uv", "run", FACTS, "--project", v.path(project), "check", *files], check=False)
        if r.returncode == 1:
            v.progress("facts", status="failed")
            print(f"variant: {v.name} says something the project's facts deny. Nothing was rendered: "
                  "rewrite the line, not the fact.", file=sys.stderr)
            return 4
    if a.spec:
        print(f"spec written: {spec_f}")
        return 0

    v.progress("render")
    log("render")
    run(["uv", "run", RENDER, spec_f])

    v.progress("upload")
    log("upload-ready encode")
    # The engine renders a master into resources/; the file that goes to the platform is re-encoded
    # to the upload profile (upload.py) and is the ONLY thing left loose in the concept's folder.
    size = FORMAT_SIZES.get(v.cfg.get("format", "9x16"))
    run(["uv", "run", UPLOAD, v.master, v.out] + (["--size", f"{size[0]}x{size[1]}"] if size else []))
    timeline = v.res / f"{v.name}.timeline.json"
    rendered_tl = v.master.with_name(v.master.stem + ".timeline.json")
    if rendered_tl.exists():
        rendered_tl.replace(timeline)

    v.progress("copies")
    log("light copy and preview, into resources/")
    v.light(v.out, v.res / f"{v.name}-light.mp4")
    rendered_prev = v.master.with_name(v.master.stem + "-preview.mp4")
    prev = v.res / f"{v.name}-preview.mp4"
    if rendered_prev.exists():
        v.light(rendered_prev, prev)
        rendered_prev.unlink()
    v.master.unlink(missing_ok=True)              # reproducible from variant.json; 50-80 MB each
    if vs_data is not None:
        shutil.copy2(v.path(v.voice_cfg["script"]), v.res / f"{v.name}-voice-script.json")

    v.progress("gate")
    log("gate, on the file that ships")
    vcmd = ["uv", "run", VERIFY, v.out, "--spec", spec_f, "--timeline", timeline,
            "--json", v.res / f"{v.name}-verify.json"]
    if prev.exists():
        vcmd += ["--preview", prev]
    if vs_data is not None:
        vcmd += ["--script", v.path(v.voice_cfg["script"])]
    gate_ok = run(vcmd, check=False, capture_output=True, text=True).returncode == 0

    flagged = {}
    if not a.no_framecheck:
        v.progress("framecheck")
        log("framecheck, cut by cut")
        _, flagged = v.framecheck(g)

    notes = v.publish_notes(g, total, voice_info, gate_ok, flagged)
    result = {"name": v.name, "file": str(v.out), "duration_s": round(total, 3), "cuts": len(g),
              "grid": "beats" if v.beats_mode else "seconds", "loop": v.loop,
              "voice": voice_info, "gate_ok": gate_ok, "framecheck_flagged": flagged,
              "warnings": v.warnings, "publish_notes": str(notes), "fingerprint": v.fingerprint(),
              "built_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")}
    atomic_json(v.dir / "build.json", result)
    v.progress("done", status="done" if gate_ok else "failed", duration_s=round(total, 3))
    print(f"\n{v.out}  ({total:.2f} s) — gate {'passed' if gate_ok else 'FAILED'}"
          + (f", framecheck flagged {len(flagged)} cut(s)" if flagged else ""))
    return 0 if gate_ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("variant")
    ap.add_argument("--plan", action="store_true", help="print the grid and stop")
    ap.add_argument("--spec", action="store_true", help="stop after writing spec.json")
    ap.add_argument("--force", action="store_true", help="rebuild even if up to date")
    ap.add_argument("--no-framecheck", dest="no_framecheck", action="store_true")
    a = ap.parse_args()
    try:
        v = Variant(Path(a.variant))
        sys.exit(build(v, a))
    except Bad as e:
        print(e.args[0] if e.args else "variant: bad variant.json", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
