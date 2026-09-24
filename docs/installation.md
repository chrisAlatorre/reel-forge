# Installation

Reel Forge needs three mandatory things: **Claude Code**, **ffmpeg** and **uv**. Everything else is
optional and depends on your operating system.

## Summary

| Step | Required | macOS | Linux | Windows |
|---|---|---|---|---|
| Claude Code | Yes | Yes | Yes | Yes (WSL recommended) |
| `ffmpeg` | Yes | Homebrew | package manager | winget |
| `uv` | Yes | Homebrew or script | script | winget or script |
| `osxphotos` (only to download iCloud originals) | No | Yes | N/A | N/A |
| CapCut (the app's voice) | No | Yes | No | No |
| Insta360 Studio (360) | No | Yes | No | Yes (no automation) |

---

## 1. Claude Code

If you don't have it yet:

```bash
npm install -g @anthropic-ai/claude-code
```

Check:

```bash
claude --version
```

## 2. Install the plugin

Inside Claude Code:

```text
/plugin marketplace add chrisAlatorre/reel-forge
/plugin install reel-forge@reel-forge
```

Or from the terminal, the same two steps. **`claude plugin install` installs from an already registered
marketplace; it does not accept a direct git URL**, which is why `marketplace add` comes first:

```bash
claude plugin marketplace add chrisAlatorre/reel-forge
claude plugin install reel-forge@reel-forge
```

Check that it installed:

```bash
claude plugin list                  # reel-forge@reel-forge · enabled
claude plugin details reel-forge    # 9 skills, 8 agents and the token cost
```

or, inside Claude Code, `/plugin`: `reel-forge` should show up installed and enabled, and `/reel` should
autocomplete.

### Scopes

| Scope | Command | Where it lands |
|---|---|---|
| User (default) | `claude plugin install reel-forge@reel-forge -s user` | `~/.claude/settings.json`, in all your projects |
| Project | `claude plugin install reel-forge@reel-forge -s project` | `.claude/settings.json`, shared through git |
| Local | `claude plugin install reel-forge@reel-forge -s local` | `.claude/settings.local.json`, not versioned |

## 3. Updating

```bash
claude plugin marketplace update reel-forge    # pull the new manifest
claude plugin update reel-forge                # install the new version
```

How it works, so nothing is a surprise (publishing a version, rather than receiving one, is in
[`updating.md`](updating.md)):

- **Claude Code checks the marketplace when it starts** and flags an installed plugin that has a newer
  version in the `/plugin` screen. It does **not** update on its own: you decide when.
- `claude plugin marketplace update <name>` re-reads `.claude-plugin/marketplace.json` from the repo;
  `claude plugin update <name>` installs the version the manifest declares. With no argument,
  `claude plugin update` updates everything you have installed.
- The version is `version` in `.claude-plugin/plugin.json`. **Bump it on every change you want people to
  receive**: if it doesn't change, an installed copy has no reason to refresh.
- **Changes take effect when Claude Code restarts.** Skills, agents and commands are loaded at startup.
- Your configuration (`~/.config/reel-forge/config.json`, `voice.json`) and your projects are outside the
  plugin, so an update never touches them.
- If an update renames or removes something, [`CHANGELOG.md`](../CHANGELOG.md) says so, and the plugin
  says it out loud at the start of a run when it reads a config file written by an older version.

For local development the repo is its own marketplace, so it gets registered by path:

```bash
git clone https://github.com/chrisAlatorre/reel-forge.git
claude plugin marketplace add ./reel-forge
claude plugin install reel-forge@reel-forge
```

Before installing, or after touching any skill or agent:

```bash
claude plugin validate ./reel-forge --strict
```

`--strict` turns warnings into errors; that's what you want in CI. Watch out for one trap: **every `.md`
inside `agents/` gets loaded as an agent**, so a README in there fails validation. That's why the agent
documentation lives in `docs/agents.md`.

To test without touching your own configuration, use a separate config directory and delete it
afterwards:

```bash
export CLAUDE_CONFIG_DIR=$(mktemp -d)
claude plugin marketplace add ./reel-forge && claude plugin install reel-forge@reel-forge
claude plugin details reel-forge
rm -rf "$CLAUDE_CONFIG_DIR" && unset CLAUDE_CONFIG_DIR
```

---

## 4. Per-OS dependencies

### macOS

```bash
# Homebrew, if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Required
brew install ffmpeg uv

# Optional: for scripts with vowel marks (Thai, Arabic, Hindi)
brew install fribidi harfbuzz

# Optional: only to DOWNLOAD iCloud originals out of Apple Photos.
# Reading the library (inventory, faces, thumbnails) needs nothing extra.
uv tool install osxphotos
```

If you use Thai or Arabic text and you get dotted circles, run the scripts with:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run <script>
```

(Pillow loads `libfribidi` at runtime and `dyld` only reads the path at process start.)

**System permissions.** The first time you read Apple Photos or drive an app, macOS will ask for:

| Permission | Where it's granted | What for |
|---|---|---|
| Photos | Privacy & Security → Photos | Inventory, favorites, faces, places |
| Full Disk Access | Privacy & Security → Full Disk Access | The Photos database and thumbnails |
| Automation | Privacy & Security → Automation | Driving CapCut or Insta360 Studio |
| Accessibility | Privacy & Security → Accessibility | Clicks in CapCut or Insta360 Studio |

Grant them to the terminal you run Claude Code from (Terminal, iTerm, whichever), not to Claude Code
separately.

### Linux

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y ffmpeg fonts-dejavu

# Fedora
sudo dnf install -y ffmpeg dejavu-sans-fonts

# Arch
sudo pacman -S ffmpeg ttf-dejavu

# uv (any distribution)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

There is no Apple Photos, no CapCut and no Insta360 Studio. The path is:

- **Material**: a folder. `export REEL_FORGE_SOURCES="$HOME/Videos/my-trip"`.
- **Metadata**: EXIF (date, GPS) plus the plugin's own face detection. No favorite flag.
- **Voice**: local TTS, or deliver without voice and add it later in the phone app.
- **360**: approximate `.insv` stitching with `ffmpeg`; for final quality you need a machine with
  Insta360 Studio (macOS or Windows) and to export the flat 360 from there.

### Windows

Recommended: **WSL2 with Ubuntu**, following the Linux steps. Rendering in WSL is just as fast and it
avoids path and font problems.

Native, if you prefer:

```powershell
winget install Gyan.FFmpeg
winget install astral-sh.uv
```

Insta360 Studio exists for Windows, but the plugin **does not automate it**: export the flat 360 to MP4
yourself and hand it over as a normal video.

---

## 5. Verifying each dependency

Run this and compare with what's expected:

```bash
# ffmpeg: should print a version and carry libx264 and libfreetype
ffmpeg -version | head -1
ffmpeg -hide_banner -buildconf | grep -E "libx264|libfreetype|libfribidi" || echo "MISSING CODECS"

# ffprobe (ships with ffmpeg): needed for measuring and checking
ffprobe -version | head -1

# uv
uv --version

# The Python uv will use (3.10 to 3.12)
uv run --python 3.12 python -c "import sys; print(sys.version)"

# Free space (8 GB recommended)
df -h ~ | tail -1
```

An end-to-end render test (creates a 2-second video and deletes it):

```bash
ffmpeg -f lavfi -i color=c=black:s=1080x1920:d=2 -f lavfi -i sine=f=440:d=2 \
  -c:v libx264 -crf 23 -pix_fmt yuv420p -c:a aac -shortest /tmp/reel-forge-test.mp4 \
  && ffprobe -v error -show_entries stream=codec_type,width,height /tmp/reel-forge-test.mp4 \
  && rm /tmp/reel-forge-test.mp4 && echo "RENDER OK"
```

macOS only, if you're going to use Apple Photos:

```bash
# Should print a summary of your library. It reads the database directly: no osxphotos needed.
# $CLAUDE_PLUGIN_ROOT is set inside Claude Code; from a plain shell, use the plugin's folder.
uv run "$CLAUDE_PLUGIN_ROOT/skills/sources/scripts/inventory.py" --source photos --summary | head -3
```

If it says it can't open the database, **Full Disk Access** is missing for your terminal.

---

## 6. Configuration

Optional. Useful if you always work with the same material or you want to move the folders. The full
list of variables and the config file are in [`configuration.md`](configuration.md). The short version:

```bash
export REEL_FORGE_LANG="en-US"
export REEL_FORGE_SOURCES="$HOME/Pictures/material:$HOME/Videos/material"
export REEL_FORGE_HOME="$HOME/Movies/reel-forge"
```

or in `~/.config/reel-forge/config.json`, which wins over automatic detection:

```json
{
  "lang": "en-US",
  "sources": ["~/Pictures/material", "~/Videos/material"],
  "home": "~/Movies/reel-forge",
  "platform": "tiktok"
}
```

The first run downloads each script's Python dependencies (`uv` does it by itself, a few minutes) and, if
you ask for narration, the voice model (~4 GB, once). They live in uv's cache and in
`REEL_FORGE_CACHE`.

---

## 7. Common problems

| Symptom | Cause | Fix |
|---|---|---|
| `/reel` doesn't appear | The plugin isn't enabled | `/plugin`, enable `reel-forge` and restart Claude Code |
| `/reel` appears but behaves like the old version | Claude Code loaded the previous copy | `claude plugin update reel-forge` and restart Claude Code |
| `ffmpeg: command not found` | Not on the PATH | Reinstall with the package manager and open a new terminal |
| `unknown encoder 'libx264'` | A minimal ffmpeg, no codecs | Install the full build (Homebrew, `winget Gyan.FFmpeg`) |
| Thai or Arabic text with dotted circles | Pillow is missing `libfribidi` | Install it and use `DYLD_FALLBACK_LIBRARY_PATH` on macOS |
| Chinese characters as boxes | The font has no ideographs | Use a system CJK font or install `noto-fonts-cjk` |
| `osxphotos` can't open the library | Full Disk Access missing | Grant it to your terminal and restart it |
| Very slow renders or a stuck machine | Too many agents in parallel | Ask Claude to drop to 3 agents, or build fewer concepts per round |
| The originals come out blurry | They're in iCloud and the thumbnail got used | Authorize the download, or download the chosen material first |
| The disk filled up | Proxies and intermediate frames | Delete the project's `workspace/`; it rebuilds from the scripts |
| A video goes silent at the end | The song is shorter than the video | Known case: the reviewer catches it; ask for the music bed to be rebuilt as a loop |
| The voice speaks the wrong language | A pinned voice from a previous language | `/reel-voice --lang <tag>` and pick again |
