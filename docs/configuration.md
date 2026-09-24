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
  "home": "~/Movies/reel-forge",
  "platform": "tiktok"
}
```

| Key | What it does |
|---|---|
| `lang` | Output language of the on-screen text and the narration (BCP-47). Written the first time you answer the question. |
| `sources` | Folders with your material. Same meaning as `REEL_FORGE_SOURCES`. |
| `home` | Project root. Same meaning as `REEL_FORGE_HOME`. |
| `platform` | `tiktok`, `reels` or `shorts`. Only changes defaults, never the render. |

The chosen narration voice lives separately, in `~/.config/reel-forge/voice.json`, because `/reel-voice`
writes it on its own.

## Environment variables

Every variable starts with `REEL_FORGE_`. An environment variable wins over the config file; a command
flag wins over both.

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
| `REEL_FORGE_HOME` | macOS `~/Movies/reel-forge` · Linux `~/Videos/reel-forge` · Windows `%USERPROFILE%\Videos\reel-forge` | Project root |
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
| `REEL_FORGE_CASCADE` | the one bundled with OpenCV | Path of an alternative face-detection XML for `sheets.py faces` |
| `REEL_FORGE_PROXY_CRF` | `20` | x264 quality of the 360 equirect proxy. Lower is bigger: at `16` the proxy came out larger than the 8K original. `--crf` on `reframe360.py proxy` overrides it. |
| `REEL_FORGE_CAPCUT_VOICE` | a generic description | The name of the CapCut voice, only used in messages and diagnostics |
| `CAPCUT_DRAFTS` | `~/Movies/CapCut/User Data/Projects/com.lveditor.draft` | CapCut's drafts folder (macOS) |
| `OSXPHOTOS` | found on the PATH | Path of the `osxphotos` binary |

## Example

In `~/.zshrc` or `~/.bashrc`:

```bash
export REEL_FORGE_LANG="en-US"
export REEL_FORGE_SOURCES="$HOME/Pictures/material:$HOME/Videos/material"
export REEL_FORGE_HOME="$HOME/Movies/reel-forge"
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
