---
name: reel-forge
description: Turns the user's photo and video library into vertical 9:16 TikToks/Reels/Shorts, with trend research, a catalog of the material built by parallel agents, automatic editing and several variants per concept. Use it when they ask for a TikTok, a reel, a short, a recap or summary of a trip, party or event, a photo dump, editing 360 material, adding narration or trending music to their photos and videos, or several video proposals from their material.
---

# reel-forge

Turns a folder or library of photos and videos into several vertical videos ready to upload.
Everything runs locally: the material never leaves the machine.

**You orchestrate.** Your job is to understand the material for real, decide on concepts, split the
work across agents and review what comes back. The scripts of each plugin skill
(`${CLAUDE_PLUGIN_ROOT}/skills/<skill>/scripts/`) do the heavy lifting.

## The flow

| # | Phase | Who | Output |
|---|---|---|---|
| 1 | Scope | you, with the user | which material, which platform, which language, what can't appear |
| 2 | Inventory | you | file list with date, type, duration, favorite |
| 3 | Cheap sift | you or 1 agent | drops screenshots, documents, blurry shots, duplicates |
| 4 | Context | N `photo-curator`, `clip-analyst`, `360-scout` | `catalog.json`: every photo and every video **range**, described |
| 5 | Trends | 1-3 `trend-researcher` (web search) | formats, sounds with BPM, hooks, current voices, for the output language's market |
| 6 | Concepts | 4-8 `creative-director` + 1 `chief-editor` | 3-4 different concepts, each with its hook and structure |
| 7 | Build | 2 `video-builder` per concept | 2 variants per concept, rendered |
| 8 | Review | 1 `critic-reviewer` per concept | technical and content checklist, corrections applied |
| 9 | Delivery | you | versioned folder, one README per concept, light copies |

The detail of each phase is in `references/`. Read them when you reach the phase, not all at once:

| File | What for |
|---|---|
| `references/libraries.md` | where the material comes from on macOS, Linux and Windows |
| `references/selection.md` | **the selection rules**, contact sheets, frame strips |
| `references/catalog.md` | the format of `catalog.json` (the contract between agents) |
| `references/agents.md` | how many agents, what you hand each one, what it returns |
| `references/trends.md` | how to research trends without inventing them |
| `references/concepts.md` | how a concept and its variants are put together |
| `references/editing.md` | the engine, effects, text and the mistakes that already cost dearly |
| `references/audio.md` | music, diegetic sound, narration and voices |
| `references/video360.md` | 360 material (Insta360 and similar) to 9:16 |
| `references/delivery.md` | folders, versions, README and final verification |

## Output language

Two different things, and they must not be confused:

- **The language you speak to the user in**: whatever they are writing in. Never ask about it.
- **The output language**: the language of the on-screen text, the captions and the narration of the
  video. That one is explicit and it also decides which market the trend research targets and which
  voices are offered.

Resolve the output language in this order, before anything else:

1. `--lang <tag>` in the command's arguments.
2. The `REEL_FORGE_LANG` environment variable.
3. The `"lang"` field in `~/.config/reel-forge/config.json`.
4. Nothing set → **ask once**, inside the grouped question of phase 1, and **save the answer** into
   `~/.config/reel-forge/config.json` (create the file if needed, preserving any other keys). After
   that it is never asked again.

Use a BCP-47 tag: `en`, `es`, or with a region where the region matters — `es-MX`, `en-US`, `pt-BR`.
The region is not decoration: `es-MX` and `es-ES` are different trend markets with different sounds,
and so are `en-US` and `en-GB`. If the user gives a bare language, keep it bare rather than inventing
a region.

Hand that tag to every agent that produces or consumes copy: `trend-researcher` (it picks the market),
`creative-director` (hooks and on-screen text), `video-builder` (captions, script, hashtags),
`critic-reviewer` (it verifies the language is right and consistent) and the voices skill (it filters
the voice list). What never follows the language: file names, JSON keys, and this documentation.

## When you ask and when you decide alone

**Ask once, at the start, and all together** (phase 1). No drip-feeding questions:

1. Which material and from which period (folder, dates, event).
2. Do they appear in the video? How much? (default: half the cuts or fewer).
3. Is there anyone who must not appear? Minors?
4. Platform and duration (default: vertical TikTok/Reels, 20-40 s).
5. Output language and whether they want narration — unless the language is already resolved by flag,
   env var or config.
6. Anything that must not show up? (places, work, people, topics).

If they don't answer or say "you decide", use the defaults and **tell them which ones you took**, in
one line.

**Decide alone, without asking:** the concepts, the music, the shot order, the exact duration, the
effects, how many agents to launch, what to drop from the material per the rules below, and any
verifiable fact (place names, prices, dates) — research those, don't ask and don't invent.

**Stop and ask before:** publishing or uploading anything, deleting originals, spending money, using
one of their accounts, driving a third-party app by clicks, or including an identifiable minor, medical
material, documents or anything that looks sensitive.

## Selection rules

These rules aren't aesthetic: **they came out of production**, from videos that had to be redone
because they were wrong. Always apply them; the user can override any of them, and then they win.

1. **The subject can't be the whole video.** The verbatim feedback behind this rule: *"it's cringe that
   you're in all of them"*. Mix landscape, architecture, food, people, animals and shots with nobody in
   them. **The subject in half the cuts or fewer** (14-35 % worked well), unless they ask otherwise.
   Count the cuts by hand at the end and put it in the README.
2. **When the subject appears, prefer the library's favorites.** What they already starred is what they
   think they look good in. B-roll (landscape, food, animals) has no such restriction. If there aren't
   enough favorites, widen to the neighbouring shots by date and time (±10 min).
3. **No forced poses and no half-formed expressions.** Drop anyone turning away, adjusting themselves,
   mouth open mid-word, or in a pose a photographer directed (arms wide, hand to the camera).
   **Review the full burst**: two or three photos later there is almost always the good one of the same
   scene. Look at **the face** in a crop, not just the framing — at thumbnail size a grimace doesn't show.
4. **Drop by default** (overridable by the user): receipts, tickets, proofs of purchase, screenshots,
   documents, screens with work or code, blurry or underexposed photos, near-identical duplicates,
   identifiable minors as protagonists, and anything sensitive (documents with personal data, licence
   plates, addresses, banking screens). When you drop something under this rule, note it in the catalog
   with the reason: the user may want it back.
5. **Actually look at the material.** Contact sheets for photos, frame strips for video, face crops for
   expressions. **Never choose by file name, by date or at random.** An agent that didn't look at the
   image produces editing that doesn't land.
6. **Videos have good parts and filler.** Catalog **ranges with a start and an end**, not whole files. A
   40 s clip usually holds 3-6 usable seconds. The catalog stores `start_s` and `end_s`, and whoever
   builds **cannot step outside that window** without pulling a strip and looking again.
7. **The second with the good image is not the second with the good audio.** If you use a clip's sound,
   separate the image source from the audio source and look at the frame of the entry point before
   pinning it.

## Splitting work across agents

The context agents are the bottleneck and where most of the value is. Scale like this:

| Files to catalog | Parallel context agents | How it's split |
|---|---|---|
| under 200 | **3** | by day or by place |
| 200 to 1000 | **6** (up to 8 if there are more than 10 days) | one agent per day or per batch of ~150 files |
| over 1000 | **10** (practical cap) | cheap sift first, then one agent per batch of ~150 of what survived |

On top of that, always:

- **1 agent per 360 clip**, separately. An equirectangular clip yields several framings and needs its
  own ring sheets; don't mix it into that day's photo batch.
- **1 to 3 trend agents** (`trend-researcher`), with web search access, in parallel with phase 4: one
  for formats and hooks, one for sounds with BPM, one for the niche or the destination. All of them get
  the output language tag, because that's what picks the market.
- **4 to 8 `creative-director`** in phase 6, each with **a different, explicit angle** that you assign
  (narrated documentary, pure natural sound, guide with prices, visual gag, POV, list with a payoff).
  They can't see each other: the variety comes from the angles you hand out.
- **1 `chief-editor`, always one.** It's the only one that sees every proposal at once; two of them
  contradict each other and the variety is lost.
- **2 `video-builder` per concept.** Each one makes a different variant of the same concept (for
  example A silent and B narrated, or A at 35 s and B at 15 s). Two agents, two variants, one concept.
- **1 `critic-reviewer` per concept**, different from the builders, reviewing **both variants
  together**, comparing the same frame between them and fixing what blocks.

Splitting rules:

- Don't go beyond ~10 simultaneous agents: the machine saturates and the renders start taking minutes.
- **One agent, one batch, one output file.** Each writes its own `catalog-<batch>.json` and you merge
  them. Two agents writing the same file overwrite each other.
- **Give every agent the whole contract**: the selection rules above, the catalog format, the output
  language tag and the exact file list for its batch. An agent that improvises the format forces you to
  redo it.
- **Shared work goes in the common builder, not in each agent.** The music bed, the 9:16 crops and the
  light copies are done once in `common/`. When each agent did it on its own, one used the raw track and
  the last 6 s of its video came out silent.
- **Verify across variants, not just within each one.** A builder left a `look` that washed out the hook
  in two of four deliveries because nobody compared the same frame between variants.

Ready-made prompts and exact contracts in `references/agents.md`.

With a lot of material, phases 4 and 7-8 can be run with the plugin's workflows, which write what each
agent returns to disk and let an interrupted run resume:
`${CLAUDE_PLUGIN_ROOT}/workflows/catalog.js` (phases 4 and 5) and
`${CLAUDE_PLUGIN_ROOT}/workflows/build.js` (phases 7 and 8).

## Where everything is stored

The project root is `REEL_FORGE_HOME` if it is set; otherwise it depends on the OS:

| System | Root |
|---|---|
| macOS | `~/Movies/reel-forge` |
| Linux | `~/Videos/reel-forge` |
| Windows | `%USERPROFILE%\Videos\reel-forge` |

```
<root>/<project>/
  workspace/                  # the messy work: can be deleted and rebuilt  ($REEL_FORGE_WORKSPACE)
    material/                 # exports, proxies, 9:16 crops
    sheets/                   # contact sheets, frame strips, face crops
    catalog/                  # catalog-<batch>.json and the merged catalog.json
    trends/                   # trends.json and the audio previews
    concepts/<concept>/
      common/                 # shared by the variants: crops, music bed
      A/  B/                  # one builder per letter: build.py, spec.json, notes
  deliveries/                 # ($REEL_FORGE_OUTPUT)
    v1/<concept>/
      README.md               # one per concept, with both variants inside
      <concept>-A.mp4         # 1080x1920, crf 22, no copyrighted music
      <concept>-A-preview.mp4 # with the song, review only
      <concept>-A-light.mp4   # 720p, for sending over chat
      voice-script.txt        # if the variant is narrated
    v2/...                    # next round: v1 is never overwritten
```

`REEL_FORGE_WORKSPACE` and `REEL_FORGE_OUTPUT` override the `workspace/` and `deliveries/` paths when
they are set; otherwise they hang off `<root>/<project>/`.

- **One round, one version.** When the user asks for changes, a full `v2` comes out; `v1` is untouched.
  That way they can compare and go back.
- **`workspace/` is rebuilt from the scripts.** Never leave a `spec.json` that depends on a temporary
  file you already deleted: the builder (`build.py`) has to be able to regenerate everything from zero.
- **One README per concept**, with both variants. Not one per agent.

## Dependencies and honest limits

- **Cross-platform:** the render engine, the contact sheets, the catalog and the 360 work on any system
  with Python and `ffmpeg` on the PATH.
- **macOS only:** reading Apple Photos (favorites, faces, dates, thumbnails; no extra tool, `osxphotos`
  is only for downloading iCloud originals), the `say`
  system voice, and driving CapCut by clicks for the viral narrator voice. On Linux and Windows the
  material comes in from a folder and narration uses the plugin's local TTS. Anything that depends on
  macOS is marked as such in every reference; **never assume it: check the OS first**.
- **No inventing.** No "trending" songs, no prices, no dates, no place names. If you haven't verified it
  against the library or against a dated source, it doesn't go on screen.
