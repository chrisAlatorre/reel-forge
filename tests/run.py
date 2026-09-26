# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["numpy<2.3", "opencv-python"]
# ///
"""Regression tests for the bugs that shipped with every automatic check green.

    uv run tests/run.py            # all of them, ~30 s, needs ffmpeg
    uv run tests/run.py -k facts   # only the ones whose name contains "facts"

Every fixture is synthetic — ffmpeg test patterns and made-up sentences — so this folder can live in a
public repository: no photo, no voice and no fact about anybody. Each test is named after the failure
it pins down, and each one failed before the fix it guards.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "skills/video-engine/scripts"
SOURCES = ROOT / "skills/sources/scripts"
sys.path[:0] = [str(ENGINE), str(SOURCES)]

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def ff(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", *map(str, args)], check=True)


def uv(*args, env=None, cwd=None):
    return subprocess.run(["uv", "run", *map(str, args)], capture_output=True, text=True,
                          env={**os.environ, **(env or {})}, cwd=cwd)


# --------------------------------------------------------------------------- start_s

@test
def verify_reads_start_s_not_zero(tmp):
    """voice-script lines carry `start_s`; verify.py read `t`/`at`, put every line at 0 and then
    measured the same window over and over."""
    import verify
    f = tmp / "vs.json"
    f.write_text(json.dumps({"lines": [{"start_s": 0.0, "text": "uno dos tres"},
                                       {"start_s": 2.5, "text": "cuatro cinco"},
                                       {"t": 5.0, "text": "legacy key still read"}]}))
    got = [t for t, _ in verify.parse_script(f)]
    assert got == [0.0, 2.5, 5.0], got


@test
def transcribe_reads_start_s_not_zero(tmp):
    """Same contract, same bug, in the aligner: every subtitle piled up in the first seconds."""
    import transcribe
    f = tmp / "vs.json"
    f.write_text(json.dumps({"lang": "es", "lines": [{"start_s": 1.25, "text": "hola"},
                                                     {"start_s": 4.0, "text": "adios"}]}))
    lines, _ = transcribe.read_script(f)
    assert [round(l["t"], 2) for l in lines] == [1.25, 4.0], lines


# --------------------------------------------------------------------------- rotation

@test
def framecheck_reads_rotated_phone_video_upright(tmp):
    """A phone stores 9:16 as a 16:9 stream plus a rotation flag. OpenCV ignored the flag, so the
    check measured the middle of a sideways frame and found no people in a shot full of them."""
    import framecheck
    src = tmp / "rot.mov"
    ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=10:duration=1",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", tmp / "flat.mov")
    ff("-display_rotation", "90", "-i", tmp / "flat.mov", "-c", "copy", src)
    img = framecheck.to_bgr(src, 0.2)
    h, w = img.shape[:2]
    assert h > w, f"read as {w}x{h}: the rotation flag was ignored"


@test
def a_selfie_is_not_an_obstruction_but_backs_of_heads_are(tmp):
    """The first version called a selfie with a friend "someone blocking the shot". What blocks is
    bodies with their backs to the lens — the boat window: 0.50 of the bottom third, no face."""
    import framecheck
    base = {"crossing_lines": [], "haze": 0.2, "contrast": 60, "clear_band": 1.0,
            "foreground_people": []}
    boat = {**base, "people_by_third": {"top": 0, "middle": 0.0, "bottom": 0.50}, "faces": []}
    selfie = {**base, "people_by_third": {"top": 0, "middle": 0.05, "bottom": 0.45},
              "faces": [{"cy": 0.62, "height_share": 0.25}, {"cy": 0.66, "height_share": 0.22}]}
    assert framecheck.obstructions_of(boat) == ["foreground_people"]
    assert framecheck.obstructions_of(selfie) == []


# --------------------------------------------------------------------------- the grid

def _variant(tmp, cfg):
    import variant
    f = tmp / "variant.json"
    f.write_text(json.dumps(cfg))
    return variant.Variant(f)


def _stills(tmp, n):
    out = []
    for i in range(n):
        p = tmp / f"s{i}.jpg"
        ff("-f", "lavfi", "-i", f"color=c=0x{(i * 40) % 255:02x}6080:size=320x568", "-frames:v", "1", p)
        out.append(str(p))
    return out


@test
def beat_grid_lands_every_cut_on_a_beat(tmp):
    """The engine had supported a beat grid all along and no builder used it: cuts sat on round
    seconds and the song was pasted on top in the app."""
    s = _stills(tmp, 3)
    v = _variant(tmp, {"name": "t", "delivery": str(tmp / "out"),
                       "music": {"bpm": 120, "beat0": 0.5},
                       "shots": [{"src": s[0], "beats": 2}, {"src": s[1], "beats": 4},
                                 {"src": s[2], "beats": 3}]})
    g = v.grid()
    assert [r["t1"] for r in g] == [1.5, 3.5, 5.0], g        # 0.5 + 2×0.5, then +4, then +3 beats
    assert all(float(r["beat"]).is_integer() for r in g)


@test
def narrated_cut_is_pushed_to_the_next_half_beat(tmp):
    """With a voice the line sets the length; the cut still has to land on the rhythm."""
    s = _stills(tmp, 2)
    v = _variant(tmp, {"name": "t", "delivery": str(tmp / "out"),
                       "music": {"bpm": 120, "beat0": 0.0},
                       "voice": {"script": "x.json", "lead": 0.1, "tail": 0.2, "close_hold": 0.5},
                       "shots": [{"src": s[0], "line": 0}, {"src": s[1], "line": 1}]})
    g = v.grid({"l0": 1.1, "l1": 1.0})
    # shot 0: 0 + 1.1 + 0.2 = 1.3 → next quarter-second (half of a 0.5 s beat) = 1.5
    # shot 1: 1.5 + 0.1 + 1.0 + 0.5 = 3.1 → 3.25
    assert [r["t1"] for r in g] == [1.5, 3.25], g
    assert g[1]["voice_at"] == 1.6


@test
def seconds_grid_when_there_is_no_song(tmp):
    s = _stills(tmp, 2)
    v = _variant(tmp, {"name": "t", "delivery": str(tmp / "out"),
                       "shots": [{"src": s[0], "dur": 1.2}, {"src": s[1], "dur": 2.3}]})
    assert [r["t1"] for r in v.grid()] == [1.2, 3.5]


# --------------------------------------------------------------------------- the lock

@test
def two_builds_of_one_variant_cannot_run_at_once(tmp):
    """Three copies of one build ran at once and deleted each other's intermediate files mid-render."""
    s = _stills(tmp, 1)
    cfg = tmp / "variant.json"
    cfg.write_text(json.dumps({"name": "t", "delivery": str(tmp / "out"),
                               "shots": [{"src": s[0], "dur": 1.0}]}))
    holder = subprocess.Popen([sys.executable, "-c", f"""
import fcntl, time
f = open({str(tmp / '.build.lock')!r}, 'a+')
fcntl.flock(f, fcntl.LOCK_EX)
f.write('pid test'); f.flush()
time.sleep(20)
"""])
    try:
        time.sleep(1.0)
        r = uv(ENGINE / "variant.py", cfg, "--plan")
        assert r.returncode == 3, (r.returncode, r.stderr[-300:])
    finally:
        holder.kill()


# --------------------------------------------------------------------------- facts

@test
def facts_catch_the_sentence_the_user_already_rejected(tmp):
    """A trip told as a solo trip, when a friend was in half the shots. The user caught it once."""
    project = tmp / "proj"
    project.mkdir()
    r = uv(SOURCES / "facts.py", "--project", project, "add",
           "He travelled with a friend until the last country.", "--about", "people",
           "--forbid", r"\b(llegu[ée]|viaj[ée])\b[^.!?]{0,40}\bsol[oa]\b", "--allow-if", "Oporto")
    assert r.returncode == 0, r.stderr
    script = tmp / "vs.json"
    script.write_text(json.dumps({"lines": [{"text": "Llegué solo a Lisboa."},
                                            {"text": "En Oporto viajé solo, por fin."},
                                            {"text": "Llegamos a Lisboa sin conocer a nadie."}]}))
    r = uv(SOURCES / "facts.py", "--project", project, "check", script, "--json")
    rep = json.loads(r.stdout)
    assert r.returncode == 1
    assert [c["text"] for c in rep["contradictions"]] == ["Llegué solo a Lisboa."], rep


@test
def a_trip_fact_is_refused_as_a_global_preference(tmp):
    """Filed as a preference, 'the friend travelled along until the last city' would be applied to the
    next trip, where nobody was along."""
    env = {"REEL_FORGE_CONFIG_DIR": str(tmp / "cfg")}
    bad = uv(SOURCES / "preferences.py", "add-rule",
             "Never call the trip solo: the friend travelled along until the last city.",
             "--kind", "never", "--topic", "person", env=env)
    ok = uv(SOURCES / "preferences.py", "add-rule", "don't show the subject in every cut",
            "--kind", "never", "--topic", "person", env=env)
    assert bad.returncode == 2 and "facts.py" in bad.stderr, bad.stderr
    assert ok.returncode == 0, ok.stderr


# --------------------------------------------------------------------------- the loop seam

@test
def loop_seam_is_high_when_the_last_frame_is_the_first(tmp):
    """A looping video used to fail `ending` for having no fade. The seam is what matters."""
    import verify
    ff("-f", "lavfi", "-i", "testsrc2=size=320x568:rate=30:duration=1", "-pix_fmt", "yuv420p",
       tmp / "a.mp4")
    ff("-i", tmp / "a.mp4", "-vf", "reverse", tmp / "b.mp4")
    ff("-i", tmp / "a.mp4", "-i", tmp / "b.mp4", "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]",
       "-map", "[v]", "-pix_fmt", "yuv420p", tmp / "loop.mp4")
    ff("-f", "lavfi", "-i", "testsrc2=size=320x568:rate=30:duration=2", "-vf", "hue=h=120",
       "-pix_fmt", "yuv420p", tmp / "other.mp4")
    ff("-i", tmp / "a.mp4", "-i", tmp / "other.mp4", "-filter_complex",
       "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-pix_fmt", "yuv420p", tmp / "noloop.mp4")
    good = verify.loop_seam(tmp / "loop.mp4", 2.0)
    bad = verify.loop_seam(tmp / "noloop.mp4", 3.0)
    assert good is not None and good > 25, good
    assert bad is not None and bad < good - 5, (good, bad)


# --------------------------------------------------------------------------- export

@test
def a_silent_idle_export_is_killed_not_waited_on_forever(tmp):
    """osxphotos --use-photokit without the Photos permission does not fail: it waits for a dialog
    nobody sees, at 0 % CPU, forever. An export run by an agent sat there for six minutes."""
    import export
    export.STALL_S = 4
    t0 = time.time()
    code, stalled = export.run_watched(["sleep", "60"], tmp)
    assert stalled and time.time() - t0 < 20, (code, stalled, time.time() - t0)
    code, stalled = export.run_watched(["sh", "-c", "for i in 1 2 3; do echo x; sleep 1; done"], tmp)
    assert not stalled and code == 0


# --------------------------------------------------------------------------- layout and upload

@test
def upload_file_is_the_platform_profile(tmp):
    """The file that goes to the platform: H.264 High, yuv420p, BT.709 TAGGED, 1080x1920, constant
    30 fps, AAC 48 kHz. An untagged file gets its colours guessed at by the platform."""
    import upload
    ff("-f", "lavfi", "-i", "testsrc2=size=1350x2400:rate=30:duration=2", "-f", "lavfi", "-i",
       "sine=frequency=440:duration=2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv444p",
       "-c:a", "aac", tmp / "master.mp4")
    upload.encode(tmp / "master.mp4", tmp / "up.mp4")
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_name,profile,pix_fmt,width,height,r_frame_rate,color_primaries,"
                        "color_transfer,color_space,sample_rate", "-of", "json", str(tmp / "up.mp4")],
                       capture_output=True, text=True)
    st = {s["codec_name"]: s for s in json.loads(r.stdout)["streams"]}
    v, a = st["h264"], st["aac"]
    assert (v["width"], v["height"]) == (1080, 1920) and v["pix_fmt"] == "yuv420p", v
    assert v["profile"] == "High" and v["r_frame_rate"] == "30/1", v
    assert v.get("color_primaries") == "bt709" and v.get("color_space") == "bt709", v
    assert a["sample_rate"] == "48000", a


@test
def a_concept_folder_holds_only_the_upload_ready_videos(tmp):
    """The user's rule: open a concept's folder and see only videos you can upload — no README, no
    preview, no JSON. Everything else in resources/. Built on a path WITH SPACES, like the default."""
    base = tmp / "Reel Forge" / "Viaje de prueba" / "v1" / "mi-concepto"
    build = base / "resources" / "A"
    build.mkdir(parents=True)
    s = _stills(tmp, 2)
    ff("-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=3", "-f", "lavfi", "-i",
       "sine=frequency=330:duration=3", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
       "-c:a", "aac", tmp / "clip.mp4")
    (build / "variant.json").write_text(json.dumps({
        "name": "mi-concepto-A", "delivery": str(base),
        "shots": [{"src": str(tmp / "clip.mp4"), "start": 0.0, "dur": 2.0, "kb": 0.0},
                  {"src": s[0], "dur": 1.5, "audio": {"from": str(tmp / "clip.mp4"), "start": 0.5}},
                  {"src": s[1], "dur": 1.5, "audio": {"continue": True}}],
        "captions": [{"seg": 0, "lead": 0.0, "text": "Prueba", "style": "clean", "pos": "low"}]}))
    r = uv(ENGINE / "variant.py", build / "variant.json", "--no-framecheck")
    loose = sorted(p.name for p in base.iterdir() if p.is_file())
    assert loose == ["mi-concepto-A.mp4"], (loose, r.stdout[-400:], r.stderr[-400:])
    res = {p.name for p in (base / "resources").iterdir()}
    for f in ("mi-concepto-A-light.mp4", "mi-concepto-A.timeline.json", "mi-concepto-A-verify.json",
              "mi-concepto-A-publish.md"):
        assert f in res, (f, sorted(res))
    assert r.returncode == 0, r.stdout[-600:]


@test
def two_variants_a_viewer_cannot_tell_apart_fail(tmp):
    """A whole round shipped as five pairs of the same video: "same cuts, other song" and "the same
    minus two shots". What counts is a different hook, close, voice or most of the shots."""
    def spec(srcs, voiced=False):
        d = {"segments": [{"src": f"/m/{x}.jpg", "dur": 2.0} for x in srcs], "audio": []}
        if voiced:
            d["sync"] = {"from": "voice/alignment.json"}
        return d
    base = ["a", "b", "c", "d", "e", "f"]
    cases = {"same": spec(base), "shorter": spec(["a", "b", "c", "f"]),
             "newhook": spec(["x"] + base[1:]), "voiced": spec(base, voiced=True)}
    for name, d in cases.items():
        (tmp / f"{name}.json").write_text(json.dumps(d))
    (tmp / "base.json").write_text(json.dumps(spec(base)))
    def run(other):
        return uv(ENGINE / "compare_variants.py", tmp / "base.json", tmp / f"{other}.json").returncode
    assert run("same") == 1 and run("shorter") == 1, "identical or merely shorter must fail"
    assert run("newhook") == 0 and run("voiced") == 0, "another hook or the voice must pass"


@test
def projects_live_in_the_videos_folder_under_reel_forge(tmp):
    import config
    assert config.APP_FOLDER == "Reel Forge"
    if not os.environ.get("REEL_FORGE_HOME"):
        assert config.HOME.name == "Reel Forge" and config.HOME.parent.name in ("Movies", "Videos"), config.HOME


# --------------------------------------------------------------------------- runner

def main():
    only = sys.argv[sys.argv.index("-k") + 1] if "-k" in sys.argv else None
    todo = [t for t in TESTS if not only or only in t.__name__]
    failed = 0
    for t in todo:
        with tempfile.TemporaryDirectory() as d:
            t0 = time.time()
            try:
                t(Path(d))
                print(f"  ✓ {t.__name__}  ({time.time() - t0:.1f} s)")
            except Exception as e:
                failed += 1
                print(f"  ✗ {t.__name__}: {e}")
                traceback.print_exc(limit=2)
    print(f"\n{len(todo) - failed}/{len(todo)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
