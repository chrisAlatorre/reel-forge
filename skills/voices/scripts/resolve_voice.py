# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Decides WHICH voice narrates a run, and says why.

Every narrated variant used to pick its engine by whatever the caller happened to type, so the
same batch shipped some videos in the viral app voice and others in a local one, with nothing on
the delivery saying which was which. This module is the single answer to "who reads this", and it
returns the reason together with the choice so the delivery can repeat it.

    uv run resolve_voice.py --lang es-MX                 # what would narrate right now, and why
    uv run resolve_voice.py --lang en-US --json          # the same, as JSON for another script
    uv run resolve_voice.py --lang es --local-only       # skip the app path entirely
    uv run resolve_voice.py --estimate-file script.json  # how long that narration runs, in seconds

THE ORDER, AND IT IS NOT NEGOTIABLE
-----------------------------------
1. **What the user asked for**, on the command line or pinned in `~/.config/reel-forge/voice.json`.
   A pinned voice that does not speak the run's language is NOT used silently: it is reported and
   the resolution carries on, because a Spanish voice reading English copy is the first thing
   anybody notices.
2. **CapCut's Valentino at 1.4x** when the output language is Spanish and CapCut is installed.
   That is the voice the Spanish-speaking side of the platform actually sounds like, and matching
   it is the difference between a video that reads as native and one that reads as a robot.
3. **A local engine as a fallback** (`qwen` on Apple Silicon, `piper` anywhere else). It works, it
   is freely licensed and it is reproducible — and it does NOT sound like the trend, so whenever
   this branch wins the variant's README has to say so. `disclose` carries the sentence.

`resolve_voice()` returns a dict; nothing here generates audio. `voice.py` and `capcut_voice.py`
are the ones that do, and `narrate.py` calls this to know which of the two to run.
"""
from __future__ import annotations

import argparse
import json
import os
import platform as _platform
import re
import sys
from pathlib import Path

# One folder holds every per-user file (`config.json`, `voice.json`, `preferences.json`,
# `history.json`) and one variable moves it. `REEL_FORGE_CONFIG` is read as the old spelling so a
# machine that already exported it keeps working.
CONFIG_DIR = Path(os.path.expanduser(
    os.environ.get("REEL_FORGE_CONFIG_DIR") or os.environ.get("REEL_FORGE_CONFIG")
    or "~/.config/reel-forge"))
CONFIG = CONFIG_DIR / "config.json"
PINNED = CONFIG_DIR / "voice.json"
# CapCut's viral narrator voice for Spanish, and the pace the trend reads at. The speed is applied
# OUTSIDE the app with atempo, which preserves pitch (see capcut_voice.py).
VALENTINO = os.environ.get("REEL_FORGE_CAPCUT_VOICE", "Valentino")
VALENTINO_SPEED = 1.4
CAPCUT_APPS = ("/Applications/CapCut.app", "~/Applications/CapCut.app")
LOCAL_ENGINES = ("qwen", "voxcpm", "piper")
APP_ENGINES = ("capcut",)
ENGINES = (*LOCAL_ENGINES, *APP_ENGINES, "none")
# Words per second of finished narration, measured on this plugin's own voices at speed 1.0.
# Only used by estimate_s(), which exists so a concept can choose its length from its story
# instead of from a template.
WORDS_PER_S = {"es": 2.6, "en": 2.8, "pt": 2.6, "fr": 2.7, "de": 2.4, "it": 2.7}
DEFAULT_WPS = 2.6
# A sentence boundary buys a breath. Without counting them, a twelve-sentence script is estimated
# as if it were read in one gulp.
BREATH_S = 0.28


def lang_of(tag) -> str:
    """'es-MX', 'es_419', 'Spanish' -> 'es'. Unknown text comes back as its own lowercase self."""
    if not tag:
        return ""
    key = str(tag).strip().lower().replace("_", "-")
    named = {"spanish": "es", "español": "es", "espanol": "es", "castellano": "es",
             "english": "en", "inglés": "en", "ingles": "en",
             "portuguese": "pt", "português": "pt", "portugues": "pt",
             "french": "fr", "francés": "fr", "german": "de", "alemán": "de",
             "italian": "it", "italiano": "it"}
    if key in named:
        return named[key]
    return key.split("-")[0]


def is_spanish(tag) -> bool:
    return lang_of(tag) == "es"


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def run_language(explicit=None) -> str:
    """--lang -> $REEL_FORGE_LANG -> config.json. Empty when nothing says, and that is reported."""
    return (explicit or os.environ.get("REEL_FORGE_LANG")
            or read_json(CONFIG).get("lang") or "").strip()


def capcut_installed(system=None) -> bool:
    """CapCut desktop, on a machine that can actually be driven by clicks (macOS)."""
    if (system or sys.platform) != "darwin":
        return False
    return any(Path(os.path.expanduser(p)).exists() for p in CAPCUT_APPS)


def apple_silicon() -> bool:
    return sys.platform == "darwin" and _platform.machine() in ("arm64", "aarch64")


def local_engine() -> str:
    """The best local engine this machine can actually run. MLX is Apple Silicon only."""
    return "qwen" if apple_silicon() else "piper"


def local_disclosure(engine: str, why: str = "") -> str:
    """The sentence a variant's README carries when a local voice read a Spanish narration.

    It exists as a function because it has to read the same whoever prints it: the resolver when it
    falls back, and `voice.py` when it is called straight. A delivery that quietly swaps the trend
    voice for a local one is the delivery nobody can tell apart afterwards.
    """
    tail = f": {why}" if why else ""
    return (f"Narrated with the local voice ({engine}), not with {VALENTINO}{tail}. "
            "The trend voice can be added in the app at publish time.")


def pinned_choice() -> dict:
    """What /reel-voice saved, normalised. `engine: "local"` is what older files wrote."""
    p = read_json(PINNED)
    if not p:
        return {}
    engine = (p.get("engine") or "").strip().lower()
    if engine in ("local", "", "auto"):
        engine = local_engine()
    if engine == "app":
        engine = "capcut"
    out = {"engine": engine, "voice": p.get("voice"), "lang": p.get("lang"),
           "speed": p.get("speed"), "fx": p.get("fx"), "chosen_on": p.get("chosen_on")}
    return {k: v for k, v in out.items() if v not in (None, "")}


def resolve_voice(lang=None, engine=None, voice=None, speed=None, local_only=False,
                  use_pinned=True, capcut_available=None):
    """Which engine and which voice narrate this run, and why.

    Nothing here touches the disk beyond the two config files, and nothing is synthesized: the
    caller takes `engine` and hands the lines to `capcut_voice.py` or to `voice.py`.

    Returns a dict with:
      engine      one of qwen | voxcpm | piper | capcut
      voice       the voice name for that engine (None = the engine's own default)
      speed       1.4 on the CapCut path (the trend's pace), 1.0 on the local ones
      language    the run's output language tag, as resolved
      source      "requested" | "pinned" | "capcut-valentino" | "local-fallback"
      reason      one sentence, for the log and for the delivery message
      fallback    True when the trend voice was wanted and could not be used
      disclose    the sentence the variant's README has to carry, or None
      warnings    everything the caller should repeat out loud
    """
    warnings = []
    language = run_language(lang)
    if not language:
        warnings.append("no output language is set (--lang, $REEL_FORGE_LANG or \"lang\" in "
                        f"{CONFIG}). The voice was picked as if it were not Spanish; set the "
                        "language and resolve again if that is wrong.")
    spanish = is_spanish(language)
    capcut_ok = capcut_installed() if capcut_available is None else bool(capcut_available)

    # 1. What the user asked for, right now.
    if engine:
        engine = engine.strip().lower()
        if engine not in ENGINES:
            raise ValueError(f"unknown engine {engine!r}; it is one of {', '.join(ENGINES)}")
        if engine == "capcut" and not capcut_ok:
            warnings.append("--engine capcut was asked for, but CapCut is not installed on this "
                            "machine (or this is not macOS). It will fail at the first click.")
        return {"engine": engine, "voice": voice,
                "speed": float(speed if speed is not None else
                               (VALENTINO_SPEED if engine == "capcut" else 1.0)),
                "language": language, "source": "requested",
                "reason": f"asked for explicitly: {engine}" + (f" / {voice}" if voice else ""),
                "fallback": False, "disclose": None, "warnings": warnings}

    # 1b. What the user pinned with /reel-voice, as long as it speaks this run's language.
    if use_pinned:
        pin = pinned_choice()
        if pin.get("engine"):
            pin_lang = pin.get("lang")
            if language and pin_lang and lang_of(pin_lang) != lang_of(language):
                warnings.append(
                    f"the pinned voice in {PINNED} is for {pin_lang} and this run is in {language}, "
                    "so it was NOT used. Run /reel-voice --lang "
                    f"{language} to pin one for this language.")
            elif pin["engine"] == "capcut" and not capcut_ok:
                warnings.append(f"the pinned voice in {PINNED} needs CapCut and it is not installed "
                                "here; carrying on down the list.")
            elif local_only and pin["engine"] in APP_ENGINES:
                warnings.append(f"the pinned voice in {PINNED} is an app voice and --local-only was "
                                "given; carrying on down the list.")
            else:
                return {"engine": pin["engine"], "voice": voice or pin.get("voice"),
                        "speed": float(speed if speed is not None else pin.get("speed") or
                                       (VALENTINO_SPEED if pin["engine"] == "capcut" else 1.0)),
                        "language": language or pin_lang or "", "source": "pinned",
                        "reason": f"the voice pinned in {PINNED}"
                                  + (f" on {pin['chosen_on']}" if pin.get("chosen_on") else ""),
                        "fallback": False, "disclose": None, "warnings": warnings}

    # 2. The default for Spanish: CapCut's Valentino at 1.4x.
    if spanish and capcut_ok and not local_only:
        return {"engine": "capcut", "voice": VALENTINO, "speed": float(speed or VALENTINO_SPEED),
                "language": language, "source": "capcut-valentino",
                "reason": f"Spanish output and CapCut is installed, so the default is {VALENTINO} "
                          f"at {float(speed or VALENTINO_SPEED)}x: it is the voice this side of the "
                          "platform actually sounds like",
                "fallback": False, "disclose": None, "warnings": warnings}

    # 3. A local engine, and it is said out loud.
    chosen = local_engine()
    if spanish:
        # For Spanish the default is Valentino, so ANY local voice is a fallback — including the
        # one asked for with --local-only. The variant's README has to say which voice read it:
        # a delivery that quietly swaps the trend voice for a local one is the delivery nobody
        # can tell apart afterwards.
        why = ("--local-only was given" if local_only else
               "CapCut is not installed on this machine" if not capcut_ok else
               "the app path is unavailable")
        warnings.append(f"the Spanish default is {VALENTINO} from CapCut, but {why}. Narrating with "
                        f"the local engine {chosen}, which does NOT sound like the trend.")
        disclose = local_disclosure(chosen, why)
        reason = f"fallback to the local engine {chosen}: {why}"
        fallback = True
    else:
        disclose = None
        reason = (f"local engine {chosen} ("
                  + ("--local-only" if local_only else
                     f"no app voice applies to {language or 'this language'}") + ")")
        fallback = False
    return {"engine": chosen, "voice": voice, "speed": float(speed or 1.0), "language": language,
            "source": "local-fallback", "reason": reason, "fallback": fallback,
            "disclose": disclose, "warnings": warnings}


def estimate_s(text, lang=None, speed=1.0) -> float:
    """Roughly how long that text takes to read aloud, in seconds.

    It exists so the LENGTH OF A VIDEO CAN COME FROM ITS STORY. A concept that needs a setup, a
    turn and a landing is not a 15 s video because the template said 15 s: write the narration,
    estimate it here, and let the edit be as long as the story is. It is an estimate — once the
    WAVs exist, `durations.json` is the truth.
    """
    if isinstance(text, (list, tuple)):
        text = " ".join(str(t) for t in text)
    words = len(re.findall(r"[^\s]+", str(text)))
    sentences = len(re.findall(r"[.!?…]+", str(text))) or 1
    wps = WORDS_PER_S.get(lang_of(lang), DEFAULT_WPS) * max(0.25, float(speed or 1.0))
    return round(words / wps + sentences * BREATH_S, 2)


def lines_of(path: Path):
    """The spoken text of a voice-script (JSON contract) or of a plain lines.json list."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(doc, list):
        return [str(x) for x in doc], None
    lines = [ln.get("text", "") for ln in doc.get("lines", []) if isinstance(ln, dict)]
    return lines, doc.get("lang")


def main():
    ap = argparse.ArgumentParser(description="Which voice narrates this run, and why")
    ap.add_argument("--lang", help="the run's output language (default: $REEL_FORGE_LANG, then config.json)")
    ap.add_argument("--engine", choices=list(ENGINES), help="force an engine (it still explains itself)")
    ap.add_argument("--voice", help="force a voice name for that engine")
    ap.add_argument("--speed", type=float, help=f"playback speed (CapCut's default is {VALENTINO_SPEED})")
    ap.add_argument("--local-only", action="store_true", help="never the app path")
    ap.add_argument("--no-pinned", action="store_true", help=f"ignore {PINNED}")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--estimate-file", metavar="SCRIPT.json",
                    help="a voice-script (or a lines.json list): print how long it runs and exit")
    ap.add_argument("--estimate-text", metavar="TEXT", help="the same, for one piece of text")
    a = ap.parse_args()

    if a.estimate_file or a.estimate_text:
        if a.estimate_file:
            f = Path(a.estimate_file)
            if not f.exists():
                sys.exit(f"resolve_voice: {f} does not exist")
            lines, doc_lang = lines_of(f)
        else:
            lines, doc_lang = [a.estimate_text], None
        lang = a.lang or doc_lang or run_language()
        speed = a.speed if a.speed is not None else 1.0
        per = [estimate_s(x, lang, speed) for x in lines]
        total = round(sum(per), 2)
        if a.json:
            print(json.dumps({"lines": len(lines), "per_line_s": per, "total_s": total,
                              "lang": lang, "speed": speed}, ensure_ascii=False))
        else:
            for i, (x, d) in enumerate(zip(lines, per)):
                print(f"  l{i} ~{d:>5.2f}s  {str(x)[:64]}")
            print(f"\n~{total} s of narration ({len(lines)} line(s), {lang or 'unknown language'}, "
                  f"speed {speed}). Estimate only: durations.json is the truth once the WAVs exist.\n"
                  "Let the edit be this long. A story that needs 45 s is not a 20 s video.")
        return

    try:
        r = resolve_voice(lang=a.lang, engine=a.engine, voice=a.voice, speed=a.speed,
                          local_only=a.local_only, use_pinned=not a.no_pinned)
    except ValueError as e:
        sys.exit(f"resolve_voice: {e}")
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    print(f"engine: {r['engine']}  ·  voice: {r['voice'] or '(the engine default)'}  ·  "
          f"speed: {r['speed']}  ·  language: {r['language'] or '(unset)'}")
    print(f"why: {r['reason']}")
    for w in r["warnings"]:
        print(f"  WARNING: {w}")
    if r["disclose"]:
        print(f"  README line for the variant: {r['disclose']}")


if __name__ == "__main__":
    main()
