# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["piper-tts"]
# ///
"""Narración con voz neuronal LOCAL y tratamiento limpio de locutor.

Todas las voces de aquí son sintéticas y libres (Apache-2.0 / MIT). Nunca clones la voz de una
persona real: no pases como referencia el audio de alguien sin su permiso explícito por escrito.

Uso:  uv run voz.py lineas.json carpeta_salida [--voz es_MX-claude-high] [--lento 1.08]      # Piper (histórico)
      uv run voz.py lineas.json carpeta_salida --preset tiktok   # timbre tipo "TTS de app de video"
      uv run voz.py lineas.json carpeta_salida --motor qwen [--voz narrador|narradora]   # RECOMENDADO (sep 2026)
      uv run voz.py lineas.json carpeta_salida --motor voxcpm --voz narrador             # alternativa, 48 kHz
      uv run voz.py --crear-voz nombre --descripcion "Narrador mexicano..." [--semilla 11]  # diseña una voz nueva
lineas.json: ["frase 1", "frase 2", ...]. Escribe l0.wav, l1.wav... y duraciones.json.
Ese contrato (lN.wav + duraciones.json) es el que consumen narrar.py y el motor de edición.

--motor qwen = Qwen3-TTS 1.7B (Apache-2.0) en MLX: clona una voz SINTÉTICA diseñada con Qwen3-TTS VoiceDesign
($REEL_FORGE_CACHE/voces/disenadas/<voz>.wav + .json con el texto de la referencia). No es la voz de nadie real.
MLX = Apple Silicon. En otra plataforma usa piper (multiplataforma) o los repos oficiales con PyTorch.
--motor voxcpm = VoxCPM2 (Apache-2.0) con la misma referencia. Ambos corren en un entorno aparte con mlx-audio
(se crea solo con `uv run --with mlx-audio`). La primera vez bajan el modelo (~4 GB) de Hugging Face.
FX por defecto: piper → "locutor" (histórico); qwen/voxcpm → "limpio" (seco, sin eco, highpass suave, -16 LUFS).
Usa "limpio": el eco del preset "locutor" hace que la voz suene lejos del micrófono.
--lento en qwen/voxcpm = factor de duración con rubberband (1.1 = 10 % más pausado). Mete artefactos (PESQ estimado
4.3 → 2.3 con 1.08): mejor dejarlo en 1.0 y pausar con comas o puntos en el guion.
Voces Piper en $REEL_FORGE_CACHE/voces/ (modelos de huggingface.co/rhasspy/piper-voices, MIT).

--preset tiktok = es_ES-davefx-medium con fonemas latinos (seseo, espeak es-419), length_scale 1.2,
+1 semitono SIN preservar formantes (rubberband; si no está, ffmpeg asetrate+atempo) y FX limpio.
Imita el TIMBRE del TTS genérico de las apps de video (una voz sintética, no una persona): parecida,
no idéntica. Los parámetros sueltos (--tono, --seseo, --fx) sobrescriben el preset.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

CACHE = Path(os.path.expanduser(os.environ.get("REEL_FORGE_CACHE", "~/.cache/reel-forge")))
VOCES = CACHE / "voces"            # modelos .onnx de Piper
DISENADAS = VOCES / "disenadas"    # voces sintéticas diseñadas con VoiceDesign (.wav + .json)
MLX_AUDIO = "mlx-audio==0.5.5"
MODELOS = {"qwen": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16", "voxcpm": "mlx-community/VoxCPM2-bf16",
           "diseno": "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16"}
TEXTO_REF = ("Bienvenidos a este viaje. Hoy vamos a recorrer mercados, templos y playas, y les voy a contar todo lo que "
             "nadie te dice antes de llegar. Prepárense, porque va a estar bueno.")
# Recorta silencio de las orillas (lo que sobra entre líneas lo pone render.py)
RECORTE = ("areverse,silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.08,areverse,"
           "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05")
FX = {
    # Histórico de Piper. OJO: el aecho le mete sala y la voz suena "lejos del micro". Para voces nuevas usa "limpio".
    "locutor": ("highpass=f=70,equalizer=f=160:t=q:w=1:g=3,equalizer=f=3500:t=q:w=1.5:g=2,"
                "acompressor=threshold=-20dB:ratio=3:attack=5:release=120,aecho=0.8:0.5:35:0.12,loudnorm=I=-16:TP=-1.5"),
    # TTS de app: seco, sin sala ni realce de graves (el EQ brillante y la compresión bajaron la similitud)
    "tiktok": "highpass=f=80,loudnorm=I=-16:TP=-1.5",
    # Voz cercana y seca: recorte de silencios, highpass suave y loudnorm de 2 pasadas (lineal) a -16 LUFS
    "limpio": f"{RECORTE},highpass=f=60",
}
PRESETS = {"tiktok": dict(voz="es_ES-davefx-medium", lento=1.2, tono=1.0, seseo=True, fx="tiktok")}


def cambia_tono(src: Path, dst: Path, semitonos: float):
    """Sube/baja el tono moviendo también los formantes (así se midió el preset tiktok)."""
    if shutil.which("rubberband"):
        subprocess.run(["rubberband", "-q", "-3", "-p", str(semitonos), str(src), str(dst)], check=True)
        return
    k = 2 ** (semitonos / 12)
    with wave.open(str(src)) as w:
        sr = w.getframerate()
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-af",
                    f"asetrate={sr * k:.0f},aresample={sr},atempo={1 / k:.6f}", str(dst)], check=True)


def alarga(src: Path, dst: Path, factor: float):
    """Cambia la duración sin tocar el tono (rubberband -t = factor de duración; si no está, atempo)."""
    if shutil.which("rubberband"):
        subprocess.run(["rubberband", "-q", "-3", "-t", str(factor), str(src), str(dst)], check=True)
    else:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-af", f"atempo={1 / factor:.6f}",
                        str(dst)], check=True)


def loudnorm_2p(src: Path, dst: Path, pre: str):
    """loudnorm de dos pasadas (lineal cuando se puede) a -16 LUFS, pico -1.5 dBTP, 48 kHz mono."""
    ln = "loudnorm=I=-16:TP=-1.5:LRA=11"
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(src), "-af", f"{pre},{ln}:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True, check=True)
    txt = r.stderr
    m = json.loads(txt[txt.rindex("{"):txt.rindex("}") + 1])
    medido = (f"{ln}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
              f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-af", f"{pre},{medido}",
                    "-ar", "48000", "-ac", "1", str(dst)], check=True)


def post(crudo: Path, final: Path, fx: str):
    if fx == "limpio":
        loudnorm_2p(crudo, final, FX["limpio"])
    else:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(crudo), "-af", FX[fx],
                        "-ar", "48000", str(final)], check=True)


def duracion(f: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True)
    return round(float(r.stdout), 3)


def en_mlx():
    """Relanza este script con mlx-audio si no está instalado (entorno cacheado por uv)."""
    try:
        import mlx_audio  # noqa: F401
    except ImportError:
        if os.environ.get("VOZ_MLX_REEXEC"):
            sys.exit("No se pudo cargar mlx-audio")
        cmd = ["uv", "run", "--quiet", "--no-project", "--python", "3.12", "--with", MLX_AUDIO,
               "python", __file__, *sys.argv[1:]]
        os.execvpe("uv", cmd, {**os.environ, "VOZ_MLX_REEXEC": "1"})


def a_wav(resultados, dst: Path):
    import numpy as np
    from mlx_audio.audio_io import write as audio_write
    audio = np.concatenate([np.array(x.audio).reshape(-1) for x in resultados])
    audio_write(str(dst), audio, resultados[0].sample_rate)


def crear_voz(nombre: str, descripcion: str, semilla: int):
    """Diseña una voz sintética nueva con Qwen3-TTS VoiceDesign y la guarda como referencia."""
    en_mlx()
    import mlx.core as mx
    import numpy as np
    from mlx_audio.tts.utils import load_model
    DISENADAS.mkdir(parents=True, exist_ok=True)
    m = load_model(MODELOS["diseno"])
    mx.random.seed(semilla)
    np.random.seed(semilla)
    crudo = DISENADAS / f"{nombre}.crudo.wav"
    a_wav(list(m.generate_voice_design(text=TEXTO_REF, language="Spanish", instruct=descripcion)), crudo)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(crudo), "-af", "highpass=f=60,loudnorm=I=-16:TP=-1.5",
                    "-ar", "24000", "-ac", "1", str(DISENADAS / f"{nombre}.wav")], check=True)
    crudo.unlink()
    json.dump({"texto": TEXTO_REF, "descripcion": descripcion, "semilla": semilla, "modelo": MODELOS["diseno"],
               "licencia": "Voz sintética creada con Qwen3-TTS VoiceDesign (Apache-2.0). No es la voz de ninguna persona real."},
              open(DISENADAS / f"{nombre}.json", "w"), ensure_ascii=False, indent=1)
    print(DISENADAS / f"{nombre}.wav")


def sintetiza_mlx(motor: str, lineas: list, out: Path, voz: str, lento: float, fx: str, semilla: int):
    en_mlx()
    import mlx.core as mx
    import numpy as np
    from mlx_audio.tts.utils import load_model
    ref = Path(voz) if voz.endswith(".wav") else DISENADAS / f"{voz}.wav"
    meta = ref.with_suffix(".json")
    if not ref.exists() or not meta.exists():
        sys.exit(f"No encuentro {ref} y su .json (texto de la referencia). Voces: "
                 f"{sorted(p.stem for p in DISENADAS.glob('*.wav'))}")
    ref_text = json.load(open(meta))["texto"]
    m = load_model(MODELOS[motor])
    dur = {}
    for i, texto in enumerate(lineas):
        mx.random.seed(semilla + i)
        np.random.seed(semilla + i)
        if motor == "qwen":
            res = list(m.generate(text=texto, ref_audio=str(ref), ref_text=ref_text, lang_code="spanish"))
        else:
            res = list(m.generate(text=texto, ref_audio=str(ref), prompt_audio=str(ref), prompt_text=ref_text,
                                  inference_timesteps=20))
        crudo = out / f"l{i}.crudo.wav"
        a_wav(res, crudo)
        if lento and lento != 1.0:
            estirado = out / f"l{i}.lento.wav"
            alarga(crudo, estirado, lento)
            crudo.unlink()
            crudo = estirado
        final = out / f"l{i}.wav"
        post(crudo, final, fx)
        crudo.unlink()
        dur[f"l{i}"] = duracion(final)
        print(f"l{i} {dur[f'l{i}']}s", flush=True)
    return dur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lineas", nargs="?")
    ap.add_argument("salida", nargs="?")
    ap.add_argument("--motor", choices=["piper", "qwen", "voxcpm"], default="piper")
    ap.add_argument("--preset", choices=sorted(PRESETS))
    ap.add_argument("--voz", help="piper: nombre del modelo; qwen/voxcpm: narrador | narradora | ruta.wav (con .json al lado)")
    ap.add_argument("--lento", type=float, help="piper: length_scale (default 1.08); qwen/voxcpm: factor de duración (default 1.0)")
    ap.add_argument("--tono", type=float, help="semitonos (+ agudo), mueve formantes; default 0 (solo piper)")
    ap.add_argument("--seseo", action=argparse.BooleanOptionalAction, default=None,
                    help="fonemas de español latino (espeak es-419) aunque la voz sea es_ES (solo piper)")
    ap.add_argument("--fx", choices=sorted(FX))
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--crear-voz", metavar="NOMBRE")
    ap.add_argument("--descripcion", help="con --crear-voz: descripción de la voz (mejor en español: evita acento gringo)")
    a = ap.parse_args()
    if a.crear_voz:
        if not a.descripcion:
            ap.error("--crear-voz requiere --descripcion")
        return crear_voz(a.crear_voz, a.descripcion, a.semilla)
    if not (a.lineas and a.salida):
        ap.error("faltan lineas.json y carpeta_salida")
    out = Path(a.salida)
    out.mkdir(parents=True, exist_ok=True)
    lineas = json.load(open(a.lineas))
    if a.motor != "piper":
        dur = sintetiza_mlx(a.motor, lineas, out, a.voz or "narrador", a.lento or 1.0, a.fx or "limpio", a.semilla)
        json.dump(dur, open(out / "duraciones.json", "w"), indent=1)
        print(json.dumps(dur))
        return
    base = dict(voz="es_MX-claude-high", lento=1.08, tono=0.0, seseo=False, fx="locutor")
    base.update(PRESETS.get(a.preset, {}))
    for k in base:
        if getattr(a, k) is not None:
            base[k] = getattr(a, k)
    from piper import PiperVoice
    from piper.config import SynthesisConfig
    voz = PiperVoice.load(str(VOCES / f"{base['voz']}.onnx"))
    if base["seseo"]:
        voz.config.espeak_voice = "es-419"
    dur = {}
    for i, texto in enumerate(lineas):
        crudo = out / f"l{i}.crudo.wav"
        with wave.open(str(crudo), "wb") as w:
            voz.synthesize_wav(texto, w, syn_config=SynthesisConfig(length_scale=base["lento"]))
        if base["tono"]:
            tonado = out / f"l{i}.tono.wav"
            cambia_tono(crudo, tonado, base["tono"])
            crudo.unlink()
            crudo = tonado
        final = out / f"l{i}.wav"
        post(crudo, final, base["fx"])
        crudo.unlink()
        dur[f"l{i}"] = duracion(final)
    json.dump(dur, open(out / "duraciones.json", "w"), indent=1)
    print(json.dumps(dur))


if __name__ == "__main__":
    main()
