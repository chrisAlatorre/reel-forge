# Publishing and receiving updates

How a new version of Reel Forge gets out, and what someone who installed it last month has to do to
get it. Everything below was checked against Claude Code 2.1.281.

For installing it the first time, see [`installation.md`](installation.md). For what changed between
versions, see [`CHANGELOG.md`](../CHANGELOG.md).

---

## The short version

**You (the author):**

```bash
# 1. bump the version
$EDITOR .claude-plugin/plugin.json      # "version": "0.2.0" -> "0.3.0"

# 2. write the entry
$EDITOR CHANGELOG.md

# 3. validate before anyone else sees it
claude plugin validate . --strict

# 4. publish
git commit -am "0.3.0: <one line>"
git tag -a v0.3.0 -m "0.3.0"
git push origin main --follow-tags
```

**Them (someone who already installed it):**

```bash
claude plugin marketplace update reel-forge   # re-read the catalog from the repo
claude plugin update reel-forge               # install the version the catalog declares
```

Then restart Claude Code, or run `/reload-plugins` in an open session.

---

## What actually controls an update

One field: **`version` in `.claude-plugin/plugin.json`**.

Claude Code resolves a plugin's version in this order:

1. `version` in `.claude-plugin/plugin.json` — wins if present.
2. `version` in the marketplace entry for the plugin.
3. The source itself: a git tag, or the commit SHA of a branch, for a plugin with no version field.

Reel Forge sets the field, so **nothing else matters for update detection**. The git tag is for humans
and for `git describe`; Claude Code does not read it as long as `plugin.json` carries a version.

The consequence, verified on a real install:

| You did | Their `claude plugin update reel-forge` says | Their copy |
|---|---|---|
| Changed files, left `version` alone | `reel-forge is already at the latest version (0.2.0).` | stale, silently |
| Changed files, bumped to `0.2.1` | `Plugin "reel-forge" updated from 0.2.0 to 0.2.1. Restart to apply changes.` | new |

**So: bump the version on every change you want anyone to receive.** A doc-only fix still needs a patch
bump, or it never leaves your machine.

---

## Are users told there is a new version?

Partly. Do not count on it.

- **No push notification, no banner mid-session.** Claude Code never interrupts a session to announce a
  plugin release.
- **Auto-update is off by default for third-party marketplaces**, including this one. Anthropic's own
  marketplaces and marketplaces added from claude.ai default to on; `reel-forge` does not. A user turns
  it on in `/plugin` → **Marketplaces** → select `reel-forge` → **Enable auto-update**, or an admin sets
  `"autoUpdate": true` on the `extraKnownMarketplaces` entry in managed settings.
- **With auto-update on**, Claude Code refreshes the marketplace and updates installed plugins in the
  background after the session starts, with a random delay of up to ten minutes. The session keeps
  running the version it launched with; a notification asks the user to run `/reload-plugins`, or the
  new version loads next launch.
- **With auto-update off** (the default here), the user finds out when they open `/plugin`, which flags
  an installed plugin that has a newer version in the catalog, or when they run
  `claude plugin update` themselves. Someone who never opens that screen can sit on an old version
  indefinitely.
- **A named install refreshes the marketplace first.** `claude plugin install reel-forge@reel-forge`
  re-reads the catalog before looking the plugin up, even with auto-update off. `claude plugin update`
  does not refresh a git marketplace, which is why the two-command sequence above starts with
  `marketplace update`.

Because of this, **the release notes have to reach people out of band**: the GitHub release for the tag,
the repo's README, wherever the plugin is announced. The plugin itself can only tell them at run time —
see [Announcing a breaking change from inside the plugin](#announcing-a-breaking-change-from-inside-the-plugin).

---

## Versioning

[Semantic versioning](https://semver.org), read against what a user of this plugin can notice:

| Bump | When | Examples in this plugin |
|---|---|---|
| **Major** (`1.0.0`) | Something they have breaks and they have to act | An environment variable is removed or renamed; a command or flag disappears; the JSON spec drops a key the engine used to read; the project folder layout changes |
| **Minor** (`0.3.0`) | New capability, old setups keep working | A new command, agent or skill; a new spec key; a new flag with a backward-compatible default; a new optional dependency |
| **Patch** (`0.2.1`) | Nothing new to learn | A bug fix, a prompt that was producing bad output, a typo, a doc correction, a tightened validation |

While the plugin is `0.x`, the middle number carries the breaking changes — `0.2.0` was breaking, and it
said so at the top of its changelog entry. That is the normal `0.x` convention, but it is only a
convention: **say "Breaking" in the changelog entry**, do not expect the number to communicate it.

Keep the plugin manifest and the git tag in the same shape: manifest `0.3.0`, tag `v0.3.0`. The `v` in
the tag is a git habit; the manifest never carries it.

### Pre-releases

`0.3.0-rc.1` is a valid version string, and a tester can install it by pointing a marketplace at the
branch:

```bash
claude plugin marketplace add https://github.com/chrisAlatorre/reel-forge.git#release/0.3.0
```

Keep pre-release commits off `main` until they ship, because a git marketplace added the plain way
tracks the repository's default branch.

---

## The changelog

[`CHANGELOG.md`](../CHANGELOG.md) follows [Keep a Changelog](https://keepachangelog.com): newest version
first, one `##` heading per version, grouped under `### Added` / `### Changed` / `### Fixed` /
`### Removed`.

Rules that matter for this plugin specifically:

- **A rename or a removal always gets an entry, with the old name and the new one side by side.** The
  `0.2.0` entry is the model: it links to the table in
  [`configuration.md`](configuration.md#renamed-in-020) that maps every old environment variable to its
  replacement.
- **Write it for someone who has a working setup**, not for someone reading the repo. "Renamed
  `REEL_FORGE_TALLER` to `REEL_FORGE_WORKSPACE`, export the new name" beats "renamed variables for
  consistency".
- **Write the entry in the same commit as the version bump.** A changelog written a week later is a
  changelog written from the diff, and it misses the part that actually breaks people.
- Do not list refactors nobody can observe. The changelog is the contract, not the commit log.

---

## Release checklist

```bash
# the plugin still loads and every component resolves
claude plugin validate . --strict

# the manifest version is the one you mean to ship
grep '"version"' .claude-plugin/plugin.json

# the changelog has an entry for it
head -20 CHANGELOG.md

# a clean install of this exact tree works, without touching your own config
export CLAUDE_CONFIG_DIR=$(mktemp -d)
claude plugin marketplace add ./ && claude plugin install reel-forge@reel-forge
claude plugin details reel-forge          # 9 skills, 9 agents
rm -rf "$CLAUDE_CONFIG_DIR" && unset CLAUDE_CONFIG_DIR
```

`--strict` turns warnings into errors, which is what you want here and in CI. One trap it catches:
**every `.md` under `agents/` is loaded as an agent**, so a README dropped in that directory fails
validation. That is why the agent documentation lives in [`agents.md`](agents.md).

Then tag and push. If the repository is private, the people who install it need read access to it — see
[Private repositories](#private-repositories).

---

## What a user's machine does with the new version

Worth knowing when you are debugging "it says it updated but it behaves the same".

- **Installed plugins are copied**, not referenced. Each resolved version lands in its own directory
  under `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`. After an update, the old directory
  stays behind, marked orphaned, and is swept about 14 days later so sessions that already loaded it
  keep working.
- **The running session keeps the old copy.** The update message says `Restart to apply changes` and
  means it. `/reload-plugins` picks up skills, agents, commands and hooks in an open session; a full
  restart is the reliable path.
- **Their configuration is outside the plugin.** `~/.config/reel-forge/config.json`, the pinned voice,
  and every project under `REEL_FORGE_HOME` live outside the cache directory, so an update never touches
  them. Downloaded fonts, the map and the segmentation model live in `REEL_FORGE_CACHE`
  (`~/.cache/reel-forge`) and survive too.
- **Nothing re-downloads on update.** `uv` resolves each script's dependencies from its own cache.

### Forcing it

In order, least to most invasive:

```bash
claude plugin marketplace update reel-forge     # the catalog was stale
claude plugin update reel-forge                 # normal path
claude plugin uninstall reel-forge@reel-forge && claude plugin install reel-forge@reel-forge
rm -rf ~/.claude/plugins/cache                  # last resort: nukes every plugin's cache
```

The last one is the documented fix for plugin skills that refuse to appear at all. After it, restart
Claude Code and reinstall.

---

## Private repositories

The repository is private today, which changes one thing: **Claude Code clones it over SSH**, as
`git@github.com:chrisAlatorre/reel-forge.git`, when you add it by `owner/repo` shorthand. A `gh auth
login` token is not enough on its own — whoever installs it needs an SSH key on their GitHub account
with read access to the repo.

```bash
claude plugin marketplace add chrisAlatorre/reel-forge
claude plugin install reel-forge@reel-forge
```

If they have no SSH key, they can clone it however they like and add the clone as a local marketplace:

```bash
git clone https://github.com/chrisAlatorre/reel-forge.git
claude plugin marketplace add ./reel-forge
claude plugin install reel-forge@reel-forge
```

That trades the update path for a `git pull`: see below.

---

## Working on the plugin while it is installed

Two different setups, and they behave differently:

**Marketplace install, including from a local directory.** The plugin is copied into the version cache
at install time. Editing the working tree changes nothing until you bump `version` and run
`claude plugin update reel-forge`. This is the honest way to test what a user will get, and the reason
`0.2.0` in the cache does not move when you save a file.

**`--plugin-dir`, for iterating.** The plugin loads in place from the directory you point at, with no
version and no cache copy, and a local copy takes precedence over an installed plugin of the same name
for that session:

```bash
claude --plugin-dir /path/to/reel-forge
```

Then `/reload-plugins` after each edit. No version bump, no install step. Use this while writing, and
the marketplace install to verify the release.

**A clone added as a local marketplace** updates with `git pull` plus the usual two commands — the pull
brings the new `plugin.json`, and `claude plugin update` copies it into the cache.

---

## Announcing a breaking change from inside the plugin

Since Claude Code will not announce a release, the plugin does it at run time. This is already the rule
in the skills and it survives each release:

- When a command reads a `~/.config/reel-forge/config.json` written by an older version — an unknown
  key, a renamed field — it says so in the first message of the run and states what it assumed.
- When a removed environment variable is still exported in the environment, say which one and what
  replaced it, and point at the table in [`configuration.md`](configuration.md#renamed-in-020).
- Never silently migrate a user's config file. Print the change, apply it, and name the file you touched.

When a release removes something, add the corresponding check in the same commit as the removal. A
deprecation notice written one version later never runs on the machine that needed it.
