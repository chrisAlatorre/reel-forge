---
description: Configures and tests the narration voices (CapCut's Valentino for Spanish and the local ones), generates a comparable sample with each, filters them by the output language and saves the user's favorite.
argument-hint: "[--lang es-MX|en-US|...] [--test \"sample text\"] [--local-only] [--create-voice NAME] [--pin <voice>]"
---

# /reel-voice — pick and test the narration voice

Arguments received: `$ARGUMENTS`

Sets up the voice every narrated video will use. Run it once after installing the plugin, and again
when the user stops liking how it sounds.

| Flag | Effect |
|---|---|
| `--lang TAG` | Language of the voice (`es-MX`, `en-US`, `pt-BR`…). Default: `$REEL_FORGE_LANG`, then `"lang"` in `~/.config/reel-forge/config.json`, then ask. |
| `--test "text"` | Sample sentence (default: a recap-style line of ~12 words, **in the chosen language**) |
| `--local-only` | Skips voices that depend on a desktop app |
| `--create-voice NAME` | Designs a new synthetic voice from a description (see below) |
| `--pin <voice>` | Saves that voice as the favorite without re-testing everything |

## What already gets chosen without asking

Before testing anything, print what would narrate **right now** and why:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/skills/voices/scripts/resolve_voice.py" --lang <tag>
```

That resolver is the one every narrated run uses, and its order is:

1. what the user asks for, or what this command pinned in `~/.config/reel-forge/voice.json`;
2. **CapCut's Valentino at 1.4x**, when the output language is Spanish and CapCut is installed;
3. a local engine (`qwen` on Apple Silicon, `piper` elsewhere), as a **fallback that gets disclosed**.

So for Spanish this command is not choosing from zero: it is asking whether the user wants something
other than Valentino. Say that in one line, and if they pin a local voice, tell them plainly that
every Spanish variant will then carry the "narrated with the local voice" line in its README.

## The language comes first

Resolve the language **before** listing anything, because it decides which voices are even candidates.
Order: `--lang` → `$REEL_FORGE_LANG` → `"lang"` in `~/.config/reel-forge/config.json` → ask once and
save the answer to that file.

Then **filter the catalog**: only offer voices that actually speak that language and region. A voice
trained on Iberian Spanish reading a Mexican script is immediately noticeable, and so is a US voice
reading British copy. If there is no voice for the exact region, offer the closest one and say plainly
that the accent won't match.

Everything you generate — the sample sentence, the description used to design a voice, the script the
user will eventually record — is in that language. A sample in a language the user isn't shipping in
tells them nothing.

## Skills and agents

- Main skill: `reel-forge:voices` (resolution, engines, generation, audio treatment). Scripts:
  `${CLAUDE_PLUGIN_ROOT}/skills/voices/scripts/resolve_voice.py` (who reads it, and why),
  `voice.py`, `capcut_voice.py`, `wordmarks.py` (word marks for the subtitles), `sound_map.py`
  (spoken viral audios) and `narrate.py`.
- Consumer: `reel-forge:video-engine`, which drops the narration in as an audio track of the spec; or
  `narrate.py`, which glues it onto an already rendered MP4.
- **Agents: 0 in the normal case.** Generation is local and sequential, and automating a desktop app
  **cannot be parallelized**: there is only one window.

| Situation | Agents |
|---|---|
| Testing up to 6 voices | 0 |
| More than 6 voices or several heavy engines | 1 agent per local engine, max 3, each generating its own samples |
| Desktop-app voices | Always 0. One session, in series. |

## Step 1 — Detect what's available

1. **Local neural TTS engines.** The default option: they run on the machine, send the text to no
   service and cost nothing. Use only models with a **commercial-use license** (Apache-2.0, MIT and
   similar); there are good models whose weights forbid commercial use, and those are out. The first
   run downloads several GB and takes a while; after that it's seconds per line.
2. **The system voice.** On **macOS** there is the `say` command, which is instant but sounds like a
   screen reader: fine for blocking out timings, not for publishing. On other systems, don't assume an
   equivalent exists.
3. **CapCut voices** (the desktop app, **macOS** for this plugin's automation). That's where the
   narrator voices heard on the platform live, **Valentino** among them, and for Spanish that is the
   default rather than one option among many. **It depends on a GUI app: it only works if it's
   installed, and only by driving clicks** —
   `uv run "${CLAUDE_PLUGIN_ROOT}/skills/voices/scripts/capcut_voice.py" --preflight` says in one
   pass whether this machine can do it at all. Fallback if it can't: a local voice (disclosed in the
   variant's README), or having the user add text-to-speech inside the phone app at publish time.
4. **Commercial TTS services.** Mention them as an option if the user wants studio quality with a
   clear license, but **they require the user to create the account and the key**. Never ask for a key
   here and never store one.

Report what you found, what's missing, and how big the download would be. State for each engine which
languages it covers, so it's obvious why some were filtered out.

## Step 2 — Generate the comparison

With the same sentence, generate **one file per voice**. Never a single audio file with all of them
glued together: that can't be compared and you can't replay just one.

Name the files so they explain themselves: `01-narrator-local.wav`, `02-narrator-f-local.wav`,
`03-capcut-narrator.wav`.

Identical treatment for all of them, or the comparison is worthless:

- 48 kHz, mono.
- Silence trimmed at the head and tail.
- Gentle high-pass to remove rumble.
- Loudness normalized to the same target, in two passes.
- **No echo, no reverb.** Added echo makes any voice sound like "a cheap mic, far from the mic".

If the user wants a sped-up narration style, apply the speed change **outside** the engine, with a
pitch-preserving filter. Stretching or compressing inside the generator introduces artifacts.

## Step 3 — Measure (optional but fast)

When there are more than three candidates, rank them before the user listens:

- **Perceived quality**: a speech-quality estimation model (automatic MOS) gives a number that is
  comparable across voices.
- **Intelligibility**: transcribe the generated audio and compare it with the original text. A voice
  that swallows words or invents others is out, however pretty it sounds.

Present the sorted table and send the files anyway: the user's ear beats any metric.

## Step 4 — Pick and save

Send the samples and a short table: voice, engine, language, license, whether it depends on an app,
time per line. Ask **one single thing**: which one they want.

Save the choice to `~/.config/reel-forge/voice.json`:

```json
{
  "engine": "capcut",
  "voice": "Valentino",
  "lang": "es-MX",
  "speed": 1.4,
  "fx": "clean",
  "chosen_on": "2026-01-15"
}
```

`engine` is `capcut`, `qwen`, `voxcpm` or `piper` (`local` is still read, and means whichever local
engine this machine runs). `lang` matters: a pinned voice whose language does not match a later run
is **not** used silently — the resolver reports it and carries on down the list.

From then on, everything `/reel` narrates uses that voice without asking again. If a later run uses a
different `--lang` than the one saved here, say so in one line and offer to pick a voice for the new
language rather than silently reading the script with the wrong accent.

## Creating a new voice (`--create-voice`)

Some local engines design a voice from a text description and a seed, without cloning anyone.

- Write the description **in the language of the voice**. An English description for a Spanish voice
  usually comes out with a foreign accent.
- Try 3-4 seeds and keep the best by measurement, not by hunch.
- Save a `.json` next to the voice with the description text, the seed and the model's license, so it
  can be reproduced.

## Hard rules

- **Do not clone a real person's voice** (actors, presenters, celebrities, acquaintances) or describe
  one so the model imitates it. Not even for testing.
- **Do not use any platform's unofficial endpoints**, least of all with the user's session. If they
  want an app's voice, they add it inside that app at publish time.
- No flat, generic synthetic voice: if the only available option sounds like a screen reader, say so
  and deliver the video **without voice** plus a script with timings, so the user can add the voice in
  the app.
- Commercial service keys belong to the user: never requested, never stored, never printed.

## Automating a desktop app (the Spanish default, and it is still fragile)

Valentino comes from CapCut, so for Spanish this is the normal path, not an exotic one — which makes
its failure modes everybody's problem, not just the curious user's. What has to be respected:

- The buttons **move between app versions**. Before a batch, calibrate against the real window instead
  of trusting saved coordinates.
- A heavily reused project can stop generating audio **without erroring**: the dialog appears, closes,
  and no file shows up. Rule: **one long batch, one new project**; if it starts failing, create
  another and carry on.
- To tell whether the problem is the app or the clicks, check the project file: if the text reached
  the project, the clicks were fine and the failure is the app's.
- Many of these apps **write the audio into the project folder as soon as they generate it**, so
  nothing needs exporting: just copy the file and convert it.
- It needs the screen unlocked and the window visible. **It does not work in a remote session or with
  the display off**, and the first time the OS may ask for automation permissions that can only be
  granted in front of the machine.
- **It never fails in silence.** `capcut_voice.py` reads the project's own `draft_info.json` to tell
  "the clicks landed wrong" (exit 3, recalibrate) from "the project is saturated" (exit 4, it already
  retried with a new one) from "this machine is missing something" (exit 5). Anything other than 0
  means nothing usable came out, what was generated stays on disk, and a re-run resumes.

## Delivery

The sample files, the comparison table, the chosen voice written into the config, and one line saying
what was saved. If an engine couldn't be tested, say why and what it would take to test it. If the
user ends up pinning a local voice for Spanish, say once that every variant will carry the
"narrated with the local voice, not with Valentino" line in its README — that is the point of the
line, and it is not negotiable afterwards.
