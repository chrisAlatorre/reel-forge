# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["piper-tts"]
# ///
"""Narration with a LOCAL neural voice and clean speaker treatment.

Every voice here is synthetic and freely licensed (Apache-2.0 / MIT). Never clone a real
person's voice: don't pass somebody's audio as a reference without their explicit written
permission.

Usage:
  uv run voice.py lines.json out_folder --engine piper --language en   # Piper, voice picked by language
  uv run voice.py lines.json out_folder --voice en_US-ryan-high        # Piper, voice named outright
  uv run voice.py lines.json out_folder --preset tiktok    # the flat "video app TTS" timbre (SPANISH ONLY)
  uv run voice.py lines.json out_folder --engine qwen [--voice narrator|narrator-f]  # RECOMMENDED
  uv run voice.py lines.json out_folder --engine voxcpm --voice narrator             # alternative, 48 kHz
  uv run voice.py --create-voice NAME --description "Mexican narrator..." [--seed 11] # designs a new voice

lines.json: ["sentence 1", "sentence 2", ...]. It writes l0.wav, l1.wav... and durations.json.
That contract (lN.wav + durations.json) is what narrate.py and the editing engine consume.

WHICH ENGINE SHOULD READ THIS AT ALL is not decided here: `resolve_voice.py` decides, and for a
Spanish run with CapCut installed the answer is the app's Valentino at 1.4x, not this script. Every
voice below is the FALLBACK for that case — it is local, reproducible and freely licensed, and it
does not sound like the trend, so when it narrates a Spanish variant the delivery has to say so.
This script prints that sentence itself.

--engine qwen = Qwen3-TTS 1.7B (Apache-2.0) on MLX: it clones a SYNTHETIC voice designed with
Qwen3-TTS VoiceDesign ($REEL_FORGE_CACHE/voices/designed/<voice>.wav + .json with the reference
text). It is nobody's real voice. MLX = Apple Silicon. On another platform use piper
(cross-platform) or the official PyTorch repos.
--engine voxcpm = VoxCPM2 (Apache-2.0) with the same reference. Both run in a separate
environment with mlx-audio (created automatically by `uv run --with mlx-audio`). The first run
downloads the model (~4 GB) from Hugging Face.

Default FX: piper -> "announcer" (historical); qwen/voxcpm -> "clean" (dry, no echo, gentle
high-pass, -16 LUFS). Use "clean": the "announcer" preset's echo makes the voice sound far from
the mic.

--slow on qwen/voxcpm = a duration factor via rubberband (1.1 = 10 % more relaxed). It introduces
artifacts (estimated PESQ 4.3 -> 2.3 at 1.08): better to leave it at 1.0 and pause with commas
and periods in the script.

Piper voices live in $REEL_FORGE_CACHE/voices/ (models from huggingface.co/rhasspy/piper-voices,
MIT). Each language has its own voice pack: download the one matching the run's language tag.

--preset tiktok is **Spanish only**: es_ES-davefx-medium with Latin American phonemes (seseo, espeak es-419),
length_scale 1.2, +1 semitone WITHOUT preserving formants (rubberband; or ffmpeg asetrate+atempo
if it isn't installed) and clean FX. It imitates the TIMBRE of the generic TTS in video apps (a
synthetic voice, not a person): similar, not identical. The individual parameters (--pitch,
--seseo, --fx) override the preset.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from resolve_voice import VALENTINO, is_spanish, local_disclosure
except ImportError:      # this file still has to work on its own, copied out of the plugin
    VALENTINO, is_spanish, local_disclosure = "Valentino", (lambda t: False), None

CACHE = Path(os.path.expanduser(os.environ.get("REEL_FORGE_CACHE", "~/.cache/reel-forge")))
VOICES = CACHE / "voices"          # Piper .onnx models
DESIGNED = VOICES / "designed"     # synthetic voices designed with VoiceDesign (.wav + .json)
BUNDLED = Path(__file__).resolve().parents[1] / "designed"   # recipes the plugin ships (no audio)
MLX_AUDIO = "mlx-audio==0.5.5"
MODELS = {"qwen": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16", "voxcpm": "mlx-community/VoxCPM2-bf16",
          "design": "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16"}

# Piper models live in one Hugging Face repo, laid out <family>/<locale>/<name>/<quality>/.
PIPER_REPO = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# One default piper voice per language the plugin ships text for. The key is matched against
# --language and against the run's language tag, case-insensitively, so "en", "en-US" and
# "English" all land on the same voice. Any other voice is used by passing its id to --voice.
PIPER_BY_LANGUAGE = {
    "en": "en_US-ryan-high", "english": "en_US-ryan-high",
    "es": "es_MX-claude-high", "spanish": "es_MX-claude-high", "español": "es_MX-claude-high",
    "pt": "pt_BR-faber-medium", "portuguese": "pt_BR-faber-medium",
    "fr": "fr_FR-siwis-medium", "french": "fr_FR-siwis-medium",
    "de": "de_DE-thorsten-high", "german": "de_DE-thorsten-high",
    "it": "it_IT-paola-medium", "italian": "it_IT-paola-medium",
}


def piper_voice_for(language):
    """'en', 'en-US', 'English' -> a piper voice id. None when the language is unknown."""
    if not language:
        return None
    key = str(language).strip().lower().replace("_", "-")
    return (PIPER_BY_LANGUAGE.get(key)
            or PIPER_BY_LANGUAGE.get(key.split("-")[0])
            or None)


def ensure_piper_voice(name):
    """Downloads <name>.onnx and <name>.onnx.json into the cache the first time. Returns the
    path of the .onnx. Piper needs BOTH files: the .json alone is what the old code tripped on."""
    import urllib.error
    import urllib.request
    model = VOICES / f"{name}.onnx"
    if model.exists() and model.with_suffix(".onnx.json").exists():
        return model
    try:
        locale, speaker, quality = name.split("-", 2)
        family = locale.split("_")[0]
    except ValueError:
        raise SystemExit(f"'{name}' is not a piper voice id. They look like en_US-ryan-high.")
    VOICES.mkdir(parents=True, exist_ok=True)
    base = f"{PIPER_REPO}/{family}/{locale}/{speaker}/{quality}/{name}"
    for suffix in (".onnx", ".onnx.json"):
        target = VOICES / f"{name}{suffix}"
        if target.exists():
            continue
        url = f"{base}{suffix}"
        print(f"downloading {name}{suffix}…", file=sys.stderr, flush=True)
        partial = target.with_suffix(target.suffix + ".part")
        try:
            urllib.request.urlretrieve(url, partial)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as err:
            partial.unlink(missing_ok=True)
            raise SystemExit(
                f"I couldn't download the piper voice '{name}' ({err}).\n"
                f"  {url}\n"
                f"Download both files by hand into {VOICES}, or pick another voice with --voice.")
        partial.replace(target)
    return model
# The sentence a designed voice reads to become a reference. It is deliberately IN the voice's
# language (a reference read in another language drags a foreign accent into every line after it),
# so this default pairs with REF_LANGUAGE. For a voice in another language, pass --language and
# --ref-text with a sentence of similar length and register.
REF_TEXT = ("Welcome to this trip. Today we are walking through markets, temples and beaches, and I am going to tell "
            "you everything nobody says before you land. Settle in, this one is good.")
REF_LANGUAGE = "English"
# Trims silence from both edges (the gap between lines is set by render.py)
TRIM = ("areverse,silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.08,areverse,"
        "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05")
FX = {
    # Piper's historical chain. CAREFUL: the aecho adds room and the voice sounds "far from the mic".
    # For new voices, use "clean".
    "announcer": ("highpass=f=70,equalizer=f=160:t=q:w=1:g=3,equalizer=f=3500:t=q:w=1.5:g=2,"
                  "acompressor=threshold=-20dB:ratio=3:attack=5:release=120,aecho=0.8:0.5:35:0.12,loudnorm=I=-16:TP=-1.5"),
    # App TTS: dry, no room and no bass lift (the bright EQ and the compression lowered the similarity)
    "tiktok": "highpass=f=80,loudnorm=I=-16:TP=-1.5",
    # A close, dry voice: silence trimmed, gentle high-pass and a 2-pass (linear) loudnorm to -16 LUFS
    "clean": f"{TRIM},highpass=f=60",
}
PRESETS = {"tiktok": dict(voice="es_ES-davefx-medium", slow=1.2, pitch=1.0, seseo=True, fx="tiktok")}


def shift_pitch(src: Path, dst: Path, semitones: float):
    """Raises/lowers the pitch, moving the formants too (that is how the tiktok preset was measured)."""
    if shutil.which("rubberband"):
        subprocess.run(["rubberband", "-q", "-3", "-p", str(semitones), str(src), str(dst)], check=True)
        return
    k = 2 ** (semitones / 12)
    with wave.open(str(src)) as w:
        sr = w.getframerate()
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-af",
                    f"asetrate={sr * k:.0f},aresample={sr},atempo={1 / k:.6f}", str(dst)], check=True)


def stretch(src: Path, dst: Path, factor: float):
    """Changes the duration without touching the pitch (rubberband -t = duration factor; atempo otherwise)."""
    if shutil.which("rubberband"):
        subprocess.run(["rubberband", "-q", "-3", "-t", str(factor), str(src), str(dst)], check=True)
    else:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-af", f"atempo={1 / factor:.6f}",
                        str(dst)], check=True)


def loudnorm_2pass(src: Path, dst: Path, pre: str):
    """A two-pass loudnorm (linear where possible) to -16 LUFS, -1.5 dBTP peak, 48 kHz mono."""
    ln = "loudnorm=I=-16:TP=-1.5:LRA=11"
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(src), "-af", f"{pre},{ln}:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True, check=True)
    txt = r.stderr
    m = json.loads(txt[txt.rindex("{"):txt.rindex("}") + 1])
    measured = (f"{ln}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
                f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-af", f"{pre},{measured}",
                    "-ar", "48000", "-ac", "1", str(dst)], check=True)


def post(raw: Path, final: Path, fx: str):
    if fx == "clean":
        loudnorm_2pass(raw, final, FX["clean"])
    else:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(raw), "-af", FX[fx],
                        "-ar", "48000", str(final)], check=True)


def duration(f: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True)
    return round(float(r.stdout), 3)


def in_mlx():
    """Relaunches this script with mlx-audio if it isn't installed (the environment is cached by uv)."""
    try:
        import mlx_audio  # noqa: F401
    except ImportError:
        if os.environ.get("VOICE_MLX_REEXEC"):
            sys.exit("Couldn't load mlx-audio")
        cmd = ["uv", "run", "--quiet", "--no-project", "--python", "3.12", "--with", MLX_AUDIO,
               "python", __file__, *sys.argv[1:]]
        os.execvpe("uv", cmd, {**os.environ, "VOICE_MLX_REEXEC": "1"})


def to_wav(results, dst: Path):
    import numpy as np
    from mlx_audio.audio_io import write as audio_write
    audio = np.concatenate([np.array(x.audio).reshape(-1) for x in results])
    audio_write(str(dst), audio, results[0].sample_rate)


def create_voice(name: str, description: str, seed: int, language: str, ref_text: str):
    """Designs a new synthetic voice with Qwen3-TTS VoiceDesign and saves it as a reference."""
    in_mlx()
    import mlx.core as mx
    import numpy as np
    from mlx_audio.tts.utils import load_model
    DESIGNED.mkdir(parents=True, exist_ok=True)
    m = load_model(MODELS["design"])
    mx.random.seed(seed)
    np.random.seed(seed)
    raw = DESIGNED / f"{name}.raw.wav"
    to_wav(list(m.generate_voice_design(text=ref_text, language=language, instruct=description)), raw)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(raw), "-af", "highpass=f=60,loudnorm=I=-16:TP=-1.5",
                    "-ar", "24000", "-ac", "1", str(DESIGNED / f"{name}.wav")], check=True)
    raw.unlink()
    json.dump({"text": ref_text, "description": description, "seed": seed, "language": language,
               "model": MODELS["design"],
               "license": "Synthetic voice created with Qwen3-TTS VoiceDesign (Apache-2.0). It is no real person's voice."},
              open(DESIGNED / f"{name}.json", "w"), ensure_ascii=False, indent=1)
    print(DESIGNED / f"{name}.wav")


def synthesize_mlx(engine: str, lines: list, out: Path, voice: str, slow: float, fx: str, seed: int, lang_code: str):
    in_mlx()
    import mlx.core as mx
    import numpy as np
    from mlx_audio.tts.utils import load_model
    ref = Path(voice) if voice.endswith(".wav") else DESIGNED / f"{voice}.wav"
    meta = ref.with_suffix(".json")
    recipe = BUNDLED / f"{voice}.json"
    if not voice.endswith(".wav") and not ref.exists() and recipe.exists():
        # a voice the plugin ships as a recipe (the Spanish fallback): designed once, then cached
        r = json.loads(recipe.read_text())
        print(f"designing the bundled voice {voice!r} (first use on this machine)…", flush=True)
        create_voice(voice, r["description"], int(r["seed"]), r["language"], r["text"])
    if not ref.exists() or not meta.exists():
        sys.exit(f"I can't find {ref} and its .json (the reference text). Voices: "
                 f"{sorted(p.stem for p in DESIGNED.glob('*.wav'))}")
    info = json.load(open(meta))
    ref_text = info["text"]
    # The voice's own language wins: reading an English script with a Spanish reference, or the
    # other way round, is the first thing anybody notices.
    code = lang_code or info.get("language") or REF_LANGUAGE
    m = load_model(MODELS[engine])
    durations = {}
    for i, text in enumerate(lines):
        mx.random.seed(seed + i)
        np.random.seed(seed + i)
        if engine == "qwen":
            res = list(m.generate(text=text, ref_audio=str(ref), ref_text=ref_text, lang_code=code.lower()))
        else:
            res = list(m.generate(text=text, ref_audio=str(ref), prompt_audio=str(ref), prompt_text=ref_text,
                                  inference_timesteps=20))
        raw = out / f"l{i}.raw.wav"
        to_wav(res, raw)
        if slow and slow != 1.0:
            stretched = out / f"l{i}.slow.wav"
            stretch(raw, stretched, slow)
            raw.unlink()
            raw = stretched
        final = out / f"l{i}.wav"
        post(raw, final, fx)
        raw.unlink()
        durations[f"l{i}"] = duration(final)
        print(f"l{i} {durations[f'l{i}']}s", flush=True)
    return durations


def main():
    ap = argparse.ArgumentParser(description="Local neural TTS for reel-forge narration")
    ap.add_argument("lines", nargs="?", help="JSON file with the list of sentences")
    ap.add_argument("out", nargs="?", help="output folder for l0.wav, l1.wav… and durations.json")
    ap.add_argument("--engine", choices=["piper", "qwen", "voxcpm"], default="piper")
    ap.add_argument("--preset", choices=sorted(PRESETS))
    ap.add_argument("--voice", help="piper: the model name; qwen/voxcpm: narrator | narrator-f | path.wav (with a .json beside it)")
    ap.add_argument("--language", help="the voice's language, e.g. Spanish, English (qwen/voxcpm; default: the reference's)")
    ap.add_argument("--slow", type=float, help="piper: length_scale (default 1.08); qwen/voxcpm: duration factor (default 1.0)")
    ap.add_argument("--pitch", type=float, help="semitones (+ higher), moves the formants; default 0 (piper only)")
    ap.add_argument("--seseo", action=argparse.BooleanOptionalAction, default=None,
                    help="Latin American Spanish phonemes (espeak es-419) even if the voice is es_ES (piper only)")
    ap.add_argument("--fx", choices=sorted(FX))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--create-voice", metavar="NAME")
    ap.add_argument("--description", help="with --create-voice: the voice description (write it in the voice's language: it avoids a foreign accent)")
    ap.add_argument("--ref-text", help="with --create-voice: the reference sentence the designed voice reads")
    a = ap.parse_args()
    if a.create_voice:
        if not a.description:
            ap.error("--create-voice requires --description")
        return create_voice(a.create_voice, a.description, a.seed,
                            a.language or REF_LANGUAGE, a.ref_text or REF_TEXT)
    if not (a.lines and a.out):
        ap.error("lines.json and the output folder are missing")
    # Generating a Spanish narration locally is a fallback, never the default, and the variant has
    # to carry the reason. Printed here so it appears even when this script is called directly.
    language = a.language or os.environ.get("REEL_FORGE_LANG")
    if local_disclosure and is_spanish(language):
        print("note: " + local_disclosure(a.engine, "this run asked for the local path")
              + f"\n      (the default for Spanish is {VALENTINO} from CapCut: capcut_voice.py)",
              file=sys.stderr)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    lines = json.load(open(a.lines))
    if a.engine != "piper":
        durations = synthesize_mlx(a.engine, lines, out, a.voice or "narrator", a.slow or 1.0,
                                   a.fx or "clean", a.seed, a.language)
        json.dump(durations, open(out / "durations.json", "w"), indent=1)
        print(json.dumps(durations))
        return
    # The voice follows the language unless --voice names one outright, so a run in English
    # cannot end up narrated by the Spanish default.
    default_voice = piper_voice_for(a.language) or piper_voice_for(os.environ.get("REEL_FORGE_LANG"))
    base = dict(voice=default_voice or "en_US-ryan-high", slow=1.08, pitch=0.0,
                seseo=False, fx="announcer")
    base.update(PRESETS.get(a.preset, {}))
    for k in base:
        if getattr(a, k, None) is not None:
            base[k] = getattr(a, k)
    if a.preset == "tiktok" and a.language and piper_voice_for(a.language) != PIPER_BY_LANGUAGE["es"]:
        print(f"warning: --preset tiktok is a Spanish voice; --language {a.language} is ignored by it. "
              "Drop the preset, or pass --voice for a voice in your language.", file=sys.stderr)
    if a.language and not a.voice and not a.preset and not default_voice:
        raise SystemExit(
            f"I have no piper voice for '{a.language}'. Known: "
            f"{', '.join(sorted(set(PIPER_BY_LANGUAGE.values())))}.\n"
            "Pass one with --voice, or use --engine qwen, which takes any language.")
    from piper import PiperVoice
    from piper.config import SynthesisConfig
    voice = PiperVoice.load(str(ensure_piper_voice(base["voice"])))
    if base["seseo"]:
        voice.config.espeak_voice = "es-419"
    durations = {}
    for i, text in enumerate(lines):
        raw = out / f"l{i}.raw.wav"
        with wave.open(str(raw), "wb") as w:
            voice.synthesize_wav(text, w, syn_config=SynthesisConfig(length_scale=base["slow"]))
        if base["pitch"]:
            pitched = out / f"l{i}.pitch.wav"
            shift_pitch(raw, pitched, base["pitch"])
            raw.unlink()
            raw = pitched
        final = out / f"l{i}.wav"
        post(raw, final, base["fx"])
        raw.unlink()
        durations[f"l{i}"] = duration(final)
    json.dump(durations, open(out / "durations.json", "w"), indent=1)
    print(json.dumps(durations))


if __name__ == "__main__":
    main()
