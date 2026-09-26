# Configuration

Everything here is optional. The plugin detects what it can and asks for the rest once. This page is the
single source of truth for the environment variables and the config file: if a variable isn't listed
here, it doesn't exist.

## The config file

`~/.config/reel-forge/config.json`. It wins over automatic detection and is where the plugin remembers
what you answered.

```json
{
  "lang": "en-US",
  "sources": ["~/Pictures/material", "~/Videos/material"],
  "home": "~/Movies/Reel Forge",
  "platform": "tiktok"
}
```

| Key | What it does |
|---|---|
| `lang` | Output language of the on-screen text and the narration (BCP-47). Written the first time you answer the question. |
| `sources` | Folders with your material. Same meaning as `REEL_FORGE_SOURCES`. |
| `home` | Project root. Same meaning as `REEL_FORGE_HOME`. |
| `platform` | `tiktok`, `reels` or `shorts`. Only changes defaults, never the render. |

### The rest of the folder

`config.json` is what you answered once. Three other files in the same folder are written by the
plugin as it goes, and they are the only things it keeps between runs:

| File | Written by | What it holds |
|---|---|---|
| `voice.json` | `/reel-voice` | the chosen narration voice |
| `preferences.json` | `preferences.py` | what you have corrected: rules, how much you want to appear, voices, language, formats that worked |
| `history.json` | `history.py` | which variant you published and the numbers you reported for it |

All three are yours: `0600`, in a `0700` folder, never uploaded, never synced. Deleting one only
costs the plugin its memory of that subject. `preferences.py` refuses to store paths, file names,
library UUIDs, email addresses, phone numbers or anything credential-shaped, so those files stay
small, readable and safe to look at. The full story is in the
[`sources` skill](../skills/sources/SKILL.md#preferences-that-learn).

Face embeddings are **not** kept here: they are biometric data and they stay in the project's
`workspace/`, which can be deleted at any time.

### Facts belong to the project, not to you

One more file, and deliberately **not** in this folder:

| File | Written by | What it holds |
|---|---|---|
| `<project>/facts.json` | `facts.py` | what is TRUE about one project: who was there, where, when — and the phrasings that would contradict it |

A preference is true on every project ("don't put me in every shot"). A fact is true on one ("my
friend travelled with me until the last city"). Stored with the preferences, a fact leaks into the next
project as if it were true there, which is why `preferences.py add-rule` refuses sentences that read
like events and points at `facts.py`. The file sits beside the project's `workspace/`, not inside
it: the workspace is disposable, what the user told us is not. `0600`, never uploaded, and under the
same privacy guard (no paths, identifiers or credentials) — though, unlike a preference, a fact may
name people and places, because it never leaves the project folder.

### What `preferences.json` holds

One file, written only by `preferences.py`, read at the start of every run by `preferences.py brief`.

| Key | Values | What it decides |
|---|---|---|
| `language` | BCP-47 (`es-MX`, `en-US`) | the language of the narration and the on-screen text |
| `presence` | `none` `rare` `low` `medium` `high` | how often the subject is on screen |
| `voice` | free text | **the default narration voice.** Any other voice has to be named and justified in the variant's README |
| `length` | `short` `medium` `long` `dynamic` | `dynamic` means the concept decides how long the video runs |
| `pace` | `slow` `medium` `fast` | how fast the cuts come |
| `captions` | `on` `off` `sparse` | on-screen text |
| `narration` | `on` `off` `sometimes` | whether there is a voice at all |
| `voices.preferred` / `voices.rejected` | lists | voices that worked and voices that did not |
| `formats.worked` / `formats.failed` | lists | by hand, or from `history.py bias --apply` |
| `music.preferred` / `music.rejected` | lists | sounds to reach for and sounds to drop |
| `rules` | `add-rule` / `rm-rule` | everything else, one sentence each, `avoid` `never` `prefer` `always` |

The plugin writes here **only** in four moments: the first run's language answer, the first run's
voice choice, the instant the user corrects something, and `history.py bias --apply` once there are
enough published posts to have a verdict. It never writes a preference it merely inferred. The full
rules are in the [`sources` skill](../skills/sources/SKILL.md#the-four-moments-the-orchestrator-writes-here).

### An example of what a filled file looks like

A user who says, over a couple of runs, "use that TikTok voice, the CapCut one", "don't put me in
every shot", "when I do appear, only use the ones I starred", "no posed shots", "nothing with
receipts or work screens on it", and "some of these should be longer" ends up with this, and it takes
six commands:

```bash
S="$CLAUDE_PLUGIN_ROOT/skills/sources/scripts"
uv run "$S/preferences.py" set voice "CapCut Valentino"
uv run "$S/preferences.py" set length dynamic
uv run "$S/preferences.py" set presence low
uv run "$S/preferences.py" add-rule "don't show the subject in every cut" --kind never --topic person
uv run "$S/preferences.py" add-rule "shots of the subject come from their favourites only" \
    --kind always --topic person
uv run "$S/preferences.py" add-rule "no posed or forced-looking shots" --kind never --topic pose
uv run "$S/preferences.py" add-rule "no receipts, screenshots or work screens" --kind never --topic topic
```

and `preferences.py brief`, which goes into every agent that decides anything, then prints:

```
Viewer preferences: presence=low
Default narration voice: CapCut Valentino. Use it whenever the video is narrated and the language
matches; if you use another one, say which and why in the variant README.
Length: the concept decides. Do not cut a story short to hit a template length, and do not pad a
short idea to fill one.
Never do this (the user said so):
- don't show the subject in every cut
- no posed or forced-looking shots
- no receipts, screenshots or work screens
Do this when you can:
- shots of the subject come from their favourites only
```

Those are one person's answers, not defaults: the file starts empty on a new machine and fills up
from what its user actually says. Nothing in it is a path, a file name or an identifier —
`preferences.py` refuses those, which is why the example is phrased as rules an editor can apply to
any photo.

### What `history.json` holds

One entry per published video: the project it came from, which variant, the platform, the format, the
duration, the hook, **how it closed** (`payoff`, `callback`, `reveal`, `punchline`, `open-loop`,
`abrupt`), the voice, the sound, and whatever numbers the user later reports. `history.py bias` turns
those into weights per format, per length band and per close, which is how a run knows both what to
propose and how long this account's videos actually want to be. Nothing is scraped: the numbers are
the ones the user says out loud.

## Environment variables

Every variable starts with `REEL_FORGE_`. An environment variable wins over the config file; a command
flag wins over both.

### Where the settings live

| Variable | Default | What it does |
|---|---|---|
| `REEL_FORGE_CONFIG_DIR` | `~/.config/reel-forge` | The folder holding every per-user file: `config.json`, `voice.json`, `preferences.json` and `history.json`. Useful for a second profile, or for trying things without touching your real preferences. `REEL_FORGE_CONFIG` is read as an older spelling of the same thing. |

### Language

| Variable | Default | What it does |
|---|---|---|
| `REEL_FORGE_LANG` | asked the first time | Output language of the on-screen text and the narration, and the market the trend research targets. BCP-47: `en`, `es`, `es-MX`, `en-US`, `pt-BR`. |

The region is not decoration: `es-MX` and `es-ES` are different trend markets with different sounds, and
so are `en-US` and `en-GB`. The `--lang` flag on `/reel`, `/reel-trends` and `/reel-voice` overrides it
for one run.

### Where the material is

| Variable | Default | What it does |
|---|---|---|
| `REEL_FORGE_SOURCES` | auto-detected | Folders with your material, separated by `:` (`;` on Windows) |
| `REEL_FORGE_LIBRARY` | `~/Pictures/Photos Library.photoslibrary` | Path of the Apple Photos library (macOS only) |

### Where things get written

| Variable | Default | What it does |
|---|---|---|
| `REEL_FORGE_HOME` | macOS `~/Movies/Reel Forge` · Linux `~/Videos/Reel Forge` · Windows `%USERPROFILE%\Videos\Reel Forge` | Project root |
| `REEL_FORGE_WORKSPACE` | `$REEL_FORGE_HOME/<project>/workspace` | Intermediate work: proxies, sheets, catalog. Can be deleted and rebuilt. |
| `REEL_FORGE_OUTPUT` | `$REEL_FORGE_HOME/<project>/deliveries` | The finished videos. Also the base for the relative `out` paths in a render spec. |
| `REEL_FORGE_360` | `$REEL_FORGE_HOME/360` | 360 originals, proxies and output |
| `REEL_FORGE_CACHE` | `~/.cache/reel-forge` | Models, fonts and downloaded assets |

### Assets and typefaces

| Variable | Default | What it does |
|---|---|---|
| `REEL_FORGE_FONTS` | `$REEL_FORGE_CACHE/fonts` | Where the typefaces get downloaded |
| `REEL_FORGE_ASSETS` | `$REEL_FORGE_CACHE/assets` | Base map and sound effects (`$REEL_FORGE_ASSETS/sfx/`) |
| `REEL_FORGE_MODELS` | `$REEL_FORGE_CACHE/models` | Segmentation model |
| `REEL_FORGE_FONT_SANS` | Montserrat variable | The render's sans typeface |
| `REEL_FORGE_FONT_SERIF` | Instrument Serif italic | The render's serif typeface |
| `REEL_FORGE_FONT_THAI` | auto-detected | A `.ttf`/`.ttc` covering Thai |
| `REEL_FORGE_FONT_CJK` | auto-detected | A `.ttf`/`.ttc` covering Chinese/Japanese/Korean |
| `REEL_FORGE_LABEL_FONT` | `$REEL_FORGE_FONTS/Montserrat[wght].ttf` | The `.ttf` used for the labels on 360 contact sheets |

### Odds and ends

| Variable | Default | What it does |
|---|---|---|
| `REEL_FORGE_360_SCRIPTS` | the sibling `video-360` skill | Where the render engine imports `reframe360.py` from |
| `REEL_FORGE_PHOTO_SCRIPTS` | unset | An optional external photo engine. If it is there, the person mask gets constrained with its Pose silhouette so the model doesn't take animal fur for human hair. Without it the mask still works. |
| `REEL_FORGE_CASCADE` | the one bundled with OpenCV | Path of an alternative face-detection XML for `sheets.py faces` and for `people.py --backend haar` |
| `REEL_FORGE_YUNET` | `$REEL_FORGE_MODELS/face_detection_yunet_2023mar.onnx` | Face-detection model for `people.py`. Point it at your own copy on a machine with no network. |
| `REEL_FORGE_SFACE` | `$REEL_FORGE_MODELS/face_recognition_sface_2021dec.onnx` | Face-recognition model for `people.py`: without it faces can be found but not grouped or matched. |
| `REEL_FORGE_PROXY_CRF` | `20` | x264 quality of the 360 equirect proxy. Lower is bigger: at `16` the proxy came out larger than the 8K original. `--crf` on `reframe360.py proxy` overrides it. |
| `REEL_FORGE_CAPCUT_VOICE` | a generic description | The name of the CapCut voice, only used in messages and diagnostics. It does not choose the voice: which voice a run narrates with comes from `voice` in `preferences.json`, and inside CapCut the voice is picked by a calibrated click. |
| `CAPCUT_DRAFTS` | `~/Movies/CapCut/User Data/Projects/com.lveditor.draft` | CapCut's drafts folder (macOS) |
| `OSXPHOTOS` | found on the PATH | Path of the `osxphotos` binary |

## Example

In `~/.zshrc` or `~/.bashrc`:

```bash
export REEL_FORGE_LANG="en-US"
export REEL_FORGE_SOURCES="$HOME/Pictures/material:$HOME/Videos/material"
export REEL_FORGE_HOME="$HOME/Movies/Reel Forge"
```

## Precedence, in one line

Command flag → environment variable → `~/.config/reel-forge/config.json` → automatic detection → ask.

## Renamed in 0.2.0

Version 0.2.0 unified the variable names, which used to be a mix of two languages. The old names are
**no longer read**; if you had any of them exported, rename them:

| Old | New |
|---|---|
| `REEL_FORGE_FUENTES` | `REEL_FORGE_SOURCES` |
| `REEL_FORGE_FOTOTECA`, `REEL_FORGE_PHOTOS_LIBRARY` | `REEL_FORGE_LIBRARY` |
| `REEL_FORGE_SALIDA` | `REEL_FORGE_OUTPUT` |
| `REEL_FORGE_TALLER` | `REEL_FORGE_WORKSPACE` |
| `REEL_FORGE_FUENTE` | `REEL_FORGE_LABEL_FONT` |
| `REEL_FORGE_CASCADA` | `REEL_FORGE_CASCADE` |
| `REEL_FORGE_CAPCUT_VOZ` | `REEL_FORGE_CAPCUT_VOICE` |
| `REELFORGE_*` (the underscore-less alias) | removed; use `REEL_FORGE_*` |

`REEL_FORGE_FUENTES` (material folders) and `REEL_FORGE_FUENTE` (a font file) were one letter apart and
meant completely different things, which is exactly the kind of thing this rename fixes.
