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
| 6 | Concepts | 4-8 `creative-director` + 1 `chief-editor` | several different concepts, each with its hook and structure |
| 7 | Story | 1 `story-doctor` per concept | `story/<concept>.json`: the arc (promise, development, close) and **the seconds each variant needs**, defended in beats. Its blocking fixes are binding |
| 8 | Common | 1 agent per concept | `common/`: exported originals, prepared stills, 360 renders, music bed |
| 9 | Build | **1 `video-builder` per variant** | one rendered variant per agent, verified |
| 10 | Arc + Review | 1 `story-doctor` + 1 `critic-reviewer` per concept | does it develop and land / is it well made; corrections applied |
| 11 | Delivery | you | versioned folder, one README per concept, light copies |

Every phase writes its progress to `workspace/run.json` as it goes, and every agent writes its output
to disk the moment it has it. That is what makes an interrupted run resumable — see
**Resuming a run** below.

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

## The files agents write: one shape each

Every file that gets handed between phases has **one** schema, in `schemas/`, and the agent that writes
it reads that schema first. This is not bureaucracy: a batch in an invented format has to be cataloged
again from zero, and several narrated videos have already shipped **with no voice at all** because each
agent wrote the script in its own layout and the parser silently skipped every line.

The index of contracts, who writes each one and where the prose that explains how to fill it in lives is
`schemas/README.md`. Every agent **validates its own file before answering**:

```bash
uv run "$CLAUDE_PLUGIN_ROOT/schemas/validate.py" <file> --type <contract>
```

and whoever collects it validates again before spending the next phase on it — a bad catalog gets
multiplied by four concepts.

The run ledger (below) is the one file with no schema of its own yet; its shape is written out here.

When you hand an agent a job, hand it the **path of the schema**, not a copy of the format. Copies
drift; the one that drifts is the one that produces the batch you have to redo.

## Resuming a run

A round of 29 agents lost 7 of them because the machine went to sleep mid-run, and their work was gone.
Nothing about that is unusual — a laptop closes, a session dies, a render runs past the patience of
whoever launched it. So the flow is built to be **picked up, never restarted**.

The prevention — keeping the machine awake for an unattended round — is in `docs/parallelism.md`. This
is the recovery, for when it happens anyway.

**The ledger.** `workspace/run.json` holds the run: which phases are done, which units (batches,
concepts, variants) are done, and the path of every artifact. Beside it, `workspace/run/<unit>.json`
holds one file per agent, and **nobody writes another agent's file** — two writers on one file lose each
other's updates in silence.

```json
{
  "project": "summer-coast", "lang": "en-US", "version": "v1",
  "phases": {
    "catalog": {"state": "done", "artifact": "workspace/catalog/catalog.json"},
    "build":   {"state": "running"}
  },
  "units": [
    {"id": "photos-3", "kind": "catalog-batch", "state": "done",
     "artifact": "workspace/catalog/catalog-photos-3.json", "updated_at": "2026-04-19T11:04:22-06:00"},
    {"id": "c-map-lied-B", "kind": "variant", "state": "running", "step": "rendering segment 4 of 9",
     "steps_left": ["mix", "verify", "copy out"], "artifact": "",
     "updated_at": "2026-04-19T11:19:40-06:00"}
  ]
}
```

`state` is `pending`, `running`, `done` or `failed`. A unit file is the same object, on its own. Times
are ISO 8601 with a zone, so a stale `updated_at` is readable at a glance.

**Disk wins over the ledger.** A finished `catalog-photos-3.json` means that batch is done even if the
ledger never got updated; a ledger entry with no file behind it is not done. Check the files, then trust
them.

**The rules every agent follows** (they are in the workflow prompts, and you repeat them when you launch
an agent by hand):

1. Write your progress file the moment you start, and rewrite it after every step. **Never go more than
   ~2 minutes without writing something.** A unit file whose timestamp stopped moving is how the next
   run knows where you died.
2. Write to a temporary and rename it into place. A half-written JSON read back is worse than no JSON.
3. **Split long jobs into steps under ~2 minutes and save each one.** A 360 proxy is built in chunks
   with `-ss`/`-t` and concatenated; sheets are one call per instant; narration is one line at a time
   (`l0.wav`, `l1.wav`…) with `durations.json` written **last**, so a folder with WAVs and no
   `durations.json` means "cut off, regenerate only what is missing"; a long render is done in segments.
   One twelve-minute call that gets killed leaves nothing; twelve one-minute calls leave eleven.
4. Partial work goes in `<artifact>.partial.json`. **The real artifact is written once and complete**,
   by renaming the partial into place — so its existence always means "this is finished".
5. An artifact that already exists and covers the same input is read back, not rebuilt.

**How you resume.** In the same session, the workflows replay from cache:

```
Workflow({ scriptPath: "<plugin>/workflows/catalog.js", resumeFromRunId: "<runId>" })
```

From a cold start — a new session, the next morning — just run the same thing again, or
`/reel --resume`: the first phase of each workflow reads the ledger and the files on disk and skips
everything already finished. Pass `fresh: true` (or `/reel --fresh`) only when you actually want the
material looked at again.

**Tell the user what was picked up.** One line: what was reused, what is being redone, what is still
missing. A resume that silently skips a broken batch looks exactly like a resume that worked.

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
4. Platform, and whether they want anything in particular about length (default: vertical
   TikTok/Reels, and **each concept sets its own duration from its own story** — see below).
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

## The arc, and how long a video runs

The feedback that produced this section, verbatim: *"something is being developed and it gets cut too
soon"* — and *"almost all of them last less than 30 seconds"*. Both are the same defect seen from two
sides: videos built as a hook plus a handful of shots, cut when the template said to cut.

**Every concept declares an arc and every second of its structure belongs to a stage of it**: hook →
promise → development → turn → close. The stages, the five closes that work and what makes a close fail
are in `references/concepts.md`, and the concept schema requires them. What matters at this level:

| Stage | What goes wrong when it is missing |
|---|---|
| **Hook** | it looks good but promises nothing, so there is nothing to pay off |
| **Promise** | the debt is never named, and no second in the video settles it |
| **Development** | four shots of the same idea: the middle where nothing happens |
| **Turn** | past ~35 s, nothing stops being what it looked like and the video flattens |
| **Close** | there isn't one: the file just ends, mid-movement, mid-word |

A close under ~0.8 s of settled picture reads as the file running out. A close that needs more time is
extended **with material** — hold the shot, add the missing beat — never by freezing the last frame.

**The duration comes from the story, not from a house default.** Every concept carries a
`duration_rationale` that counts it in beats — *hook 3 + three proofs of 7 + turn 4 + close 3 = 31 s* —
and the number is argued from there: more story than time and it goes up, padding and it goes down. A
visual gag is 8-12 s; a list with five points is 40-60 s; a narrated piece can earn 60-90 s if every
beat pays for itself. All of those are correct, and a round where everything comes out between 15 and
30 s is the template talking.

- **Spread the durations across a round.** When the material allows it, at least one short concept and
  at least one that runs long. Variants of the same concept that all land within a few seconds of each
  other are one variant with three names.
- **A short variant is not the long one truncated.** It keeps the whole arc and loses development
  beats, never the close.
- **`duration` is a legitimate variant axis** (`differs_in: "duration"`), and that is where a real
  difference in length belongs — not in cutting the close to hit a number.

**The `story-doctor` is who guarantees this**, and it runs twice: over the concept before anything is
built (it sets the arc and the seconds each variant needs, and those fixes are binding), and over the
rendered variants before delivery (does it develop, does it land, does the length fit). What it marks
as blocking is fixed or the variant is not delivered. The detail is in `references/agents.md`.

## Narration and on-screen text

**The default voice, when a variant carries narration and the output language is Spanish, is CapCut's
Valentino** — the viral one. That is what the user asked for and it is the reference sound of the
format:

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/voices/scripts/narrate.py" voice-script.json \
    --engine capcut --voice "Valentino" --speed 1.4
```

It is macOS-only and driven by clicks, so it gets checked before a batch (`capcut_voice.py
--preflight`). **The local engines (`qwen`, `voxcpm`, `piper`) are the backup**, not the default: when
one of them is used, the variant's README says so in its own line, with why Valentino was not available.
A delivery that quietly swaps the voice leaves the user unable to tell why it does not sound like the
trend. For any other output language, the voice comes from the `voices` skill's catalog for that
language and region, and the README still says which one.

**The text is synced to what is heard and to what is seen.** Tolerance: 0.25 s, checked by the gate.

1. **With narration, the voice is generated first and the text comes out of it**: `transcribe.py
   --align` over the generated WAVs writes `alignment.json`, and the spec's `sync` takes the times from
   the voice itself, word by word. Regenerate the alignment whenever the narration is regenerated.
2. **Over a clip whose own audio is heard**, the text comes from that clip's transcript (`subs`), and
   only if the audio is actually heard in the final mix.
3. **With no audio behind it**, the text belongs to its cut (`seg`) and leaves with it. Nothing under
   0.8 s.
4. **The other direction, which is the one nobody checks:** when the voice names something concrete — a
   place, a dish, a price, a person — the segment that shows it declares it (`"says": "…"`), and the
   gate confirms the picture was there when the word was said.

**Nobody types a subtitle's second by hand.** They match on the first render and drift on the next
change of duration, and no frame strip shows it. The mechanism is the engine's; it is written out in
`references/editing.md` and in the `video-engine` skill.

## Selection rules

These rules aren't aesthetic: **they came out of production**, from videos that had to be redone
because they were wrong. Always apply them; the user can override any of them, and then they win.

1. **The subject can't be the whole video.** The verbatim feedback behind this rule: *"it's cringe that
   you're in all of them"*. Mix landscape, architecture, food, people, animals and shots with nobody in
   them. **The ceiling is declared by each concept** in its `subject_quota` (the table of ceilings per
   kind of concept is in `references/concepts.md`; half the cuts or fewer is the usual shape, and
   14-35 % is what has worked); the reviewer checks the built variants against that number, not against
   a fixed one. Count the cuts by hand at the end and put it in the README.
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
- **1 `story-doctor` per concept, twice.** Before anything is built, over the concept: the arc and the
  seconds each variant needs, and **its fixes are binding**. After everything is rendered, over the
  variants: does it develop, does it land, does the length fit. It is the cheapest agent in the round
  and the one that decides whether the other five were worth launching — a concept with no close
  produces five variants that all stop instead of ending.
- **1 agent for the common folder, per concept, before anybody builds.** It exports the originals,
  prepares the stills and the pre-renders, renders the 360 framings and builds the music bed, once, in
  `workspace/concepts/<slug>/common/`.
- **1 `video-builder` per variant.** Not two agents splitting the variants between them: one agent, one
  letter, one folder, one delivery. When a builder owned half a concept, losing it lost that whole half,
  and two builders on the same concept re-exported the same originals twice.
- **1 `critic-reviewer` per concept**, different from the builders, reviewing **every variant
  together**, comparing the same frame between them and fixing what blocks. It runs at the same time as
  the story-doctor's second pass and they look for different things: craft versus story. Their blockers
  are fixed together, in one pass over the variant's `build.py`.

**How many variants per concept.** Two is the floor, not the rule: a concept with three genuinely
different axes (sound, duration, cutting) earns three, and a round meant for comparison can ask for
five. What is not allowed is five variants that differ only in the copy — one axis each, and their
durations spread. The letters are `A`…`H`, one folder and one agent each.

Splitting rules:

- Don't go beyond ~10 simultaneous agents: the machine saturates and the renders start taking minutes.
- **One agent, one unit, one output file, one progress file.** Two agents writing the same file
  overwrite each other in silence.
- **Give every agent the whole contract**: the selection rules above, the **path of the schema** it
  writes against, the output language tag and the exact file list or letter it owns. What already lives
  in `references/` and `schemas/` you point at; what is specific to this job you spell out.
- **Shared work is prepared before the builders, never inside them.** The music bed, the 9:16 crops, the
  exported originals and the 360 renders are done once in `common/`. When each agent did it on its own,
  one used the raw track and the last 6 s of its video came out silent.
- **Verify across variants, not just within each one.** A builder left a `look` that washed out the hook
  in two of four deliveries because nobody compared the same frame between variants.
- **Nothing is delivered that has not passed the gate.** See **Verified delivery** below.

Ready-made prompts and exact contracts in `references/agents.md`.

With a lot of material, phases 4-5 and 7-10 can be run with the plugin's workflows, which read the run
ledger first, skip whatever is already finished on disk and write their progress as they go:
`${CLAUDE_PLUGIN_ROOT}/workflows/catalog.js` (phases 4 and 5) and
`${CLAUDE_PLUGIN_ROOT}/workflows/build.js` (phases 7 to 10: story, common, build, arc, review, fix).

A big round — ten concepts, five variants each — is **not** fifty agents at once: the workflow advances
one concept at a time and its own cap is `min(16, CPUs - 2)`. What makes it survivable is the progress
protocol, not a smaller number.

## Verified delivery

**No video reaches the delivery folder without passing `verify.py`**, the engine's checker:

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/video-engine/scripts/verify.py" <file.mp4> \
    --spec spec.json --script voice-script.json --json <file>-verify.json
```

It exits non-zero if anything failed, so a build script can stop on it. **Run it with everything it can
check**, never bare: `--script` catches a voice buried under the clip's own audio and `--spec` a render
that does not last what it was supposed to. The text and ending checks (`text_sync`, `voice_image`,
`ending`) read the `<video>.timeline.json` the engine leaves beside the render — **copy that sidecar out
with the MP4**, because without it they come back `skip`, and a `skip` looks exactly like a `pass`.

- The builder runs it on its own variant and keeps fixing — **inside `build.py`, then re-render**, never
  by patching the MP4 — until it passes.
- The reviewer runs it again on every delivered file. It takes nobody's word for it, the builder's
  included.
- If a variant cannot be made to pass with the material that exists, it is **not delivered**: it is
  marked non-deliverable and **the concept's README says so, plainly, with what was missing**. A stated
  limit is worth more than a file nobody checked.
- **Narration is only delivered if it can be heard.** Pass `--script`: that is the check nobody can do
  by looking at a frame strip — whether the voice actually rises over the clip's own audio, instead of
  the clip having to be turned down by hand afterwards. If the machine has no usable voice engine, the
  variant ships without voice, the `voice-script.json` ships beside it, and the README says so. What is
  not allowed is a narrated variant delivered mute with nothing said about it.
- **A video that stops instead of ending does not ship either.** That verdict comes from the
  `story-doctor`'s second pass, not from the gate: the gate only warns. Marked
  `blocks`, it is fixed like any other blocker — inside `build.py`, then re-render.

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
    run.json                  # THE LEDGER: phases, units, artifacts. Read it before starting anything
    run/<unit>.json           # one progress file per agent; nobody writes anybody else's
    material/                 # exports, proxies, 9:16 crops
    sheets/                   # contact sheets, frame strips, face crops
    catalog/                  # catalog-<batch>.json and the merged catalog.json
    trends/                   # trends.json and the audio previews
    story/                    # the story-doctor: <concept>.json (before building, binding) and
                              # <concept>-post.json (over the rendered variants)
    concepts/<concept>/
      review.json             # the critic-reviewer's findings
      common/                 # prepared ONCE, before the builders: originals, stills, 360 renders,
                              # music bed, RESOURCES.json
      A/  B/  C/              # one agent per letter: build.py, spec.json, voice-script.json,
                              # voice/ (l0.wav…, alignment.json), result.json, notes.md
  deliveries/                 # ($REEL_FORGE_OUTPUT)
    v1/<concept>/
      README.md               # one per concept, with every variant inside
      <concept>-A.mp4         # 1080x1920, crf 22, no copyrighted music — verified before it lands here
      <concept>-A-preview.mp4 # with the song, review only
      <concept>-A-light.mp4   # 720p, for sending over chat
      voice-script.json         # if the variant is narrated — the one format, in schemas/
    v2/...                    # next round: v1 is never overwritten
```

`REEL_FORGE_WORKSPACE` and `REEL_FORGE_OUTPUT` override the `workspace/` and `deliveries/` paths when
they are set; otherwise they hang off `<root>/<project>/`.

- **One round, one version.** When the user asks for changes, a full `v2` comes out; `v1` is untouched.
  That way they can compare and go back.
- **`workspace/` is rebuilt from the scripts.** Never leave a `spec.json` that depends on a temporary
  file you already deleted: the builder (`build.py`) has to be able to regenerate everything from zero.
- **One README per concept**, with every variant. Not one per agent.
- **`run.json` is not disposable.** If `workspace/` gets wiped, the next run starts from zero — which is
  correct, but say so before wiping it.

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
