# Agents: how many, what you give them and what they return

## How many

| Phase | Agents | Rule |
|---|---|---|
| Context, under 200 files | **3** | one per day or per place |
| Context, 200-1000 | **6** (8 if more than 10 days) | one per day, or per batch of ~150 files |
| Context, over 1000 | **10** | cheap sift first; then batches of ~150 of what's left |
| 360 material | **1 per clip** | every equirectangular clip is its own job |
| Trends | **1-3** | with web search, in parallel with the context phase: formats / sounds / niche |
| Concepts | **4-8 directors** | one per angle, in parallel; they can't see each other |
| Selection | **1 chief editor** | always one: the only one who sees every proposal together |
| Build | **2 per concept** | two different variants of the same concept |
| Review | **1 per concept** | different from the builders; reviews both variants together |

Practical cap: **~10 agents at a time**. Beyond that, renders start taking minutes and it isn't the
code's fault. With 4 concepts, launch the build in two waves of 4 agents.

## General contract

Every agent receives, without exception:

1. The path of its batch or its concept and **the exact list of files or ids** it works with.
2. The selection rules (copy them from the SKILL; don't send it off to read them).
3. The **output language tag** if it produces or verifies copy (directors, builders, reviewer, trends).
4. The exact output format (the one in `catalog.md` for context agents, the engine spec for builders).
5. The path of **its** output file, different from everyone else's.
6. What it may not do: nobody else renders, nobody touches `common/`, nobody deletes anything, nobody
   publishes anything.

And it returns, in its final message: the path of its file, how many items it cataloged or how many cuts
it assembled, and **the three things that struck it most** (that's what you use for the concepts).

## Context agent

The brief:

> Catalog the N files in the attached list. For each one: pull a thumbnail or frame strip, **look at
> it**, and write an entry in the format of `catalog.md`. For videos, split into RANGES with a start and
> an end; the whole file is never used. Apply the drop rules (mark `use: false` with a reason, don't
> delete anything). For shots where the subject appears, also pull face crops and review the full burst
> before keeping one. Write `workspace/catalog/catalog-<batch>.json`. Don't render or edit anything.

What goes wrong if you don't say it:
- It catalogs by file name without opening the image. → Require the `sheet` field with the reference.
- It returns the whole video as one range. → Require at least 2 ranges per video over 15 s, or a reason.
- It invents the format. → Hand it the full example JSON.

## 360 agent

One per clip. Receives the path of the `.insv` or the equirectangular and returns a range cataloged **by
direction**: yaw, pitch, fov and what's there. See `video360.md`. It doesn't render the final video: it
leaves `keys.json` ready plus a note on what's in each direction.

## Trend agent

See `trends.md`. Returns `workspace/trends/trends.json` with formats, sounds with measured BPM, hooks
and voices, **each with a source and a date**, and the `market` field stating which language and region
it researched. If it found no source, it doesn't include the item.

## Creative directors (4-8, in parallel)

Each receives the merged catalog, the trends, the output language and **an angle you assign**. It
returns `concepts/<slug>.json` with **one single concept**, not three half ones.

> Propose ONE concept for a <platform> vertical, from this angle: **<angle>**. On-screen text and
> narration in <language tag>. Use only ids that exist in the catalog; inventing a resource invalidates
> your whole concept. Deliver: the first-second hook, a second-by-second structure with the ids of each
> cut, the target duration, whether it cuts to the beat or to natural sound, whether it carries
> narration, the ratio of cuts with and without the subject, and 3-4 variants of the same concept.
> Write `concepts/<slug>.json`.

Angles that split well (one per director, never repeated): narrated documentary · pure natural sound ·
guide with prices · visual gag · POV · list with a payoff · block counter · one long take · before and
after.

**The variety comes from the angles you hand out, not from asking them for "something different".**
Eight directors with no assigned angle return eight photo dumps.

## Chief editor (1, always one)

Reads **every** concept and the catalog, and decides what gets built.

> Read all the `concepts/*.json` and the catalog. Pick the 3 that differ most from each other and that
> can genuinely be built with the material available. Drop the repeats and the weak ones, and say why.
> For each chosen one, write the **required fixes** to apply before building it. Flag as a serious
> defect any concept that uses an id that isn't in the catalog. Write `selection.json`.

Two chief editors contradict each other and you lose exactly what this step is for. You confirm its
selection in one line before the rendering starts.

## Builder agents (2 per concept)

Each one receives: the full concept (hook, structure, duration, tone), the merged catalog, the output
language, the `common/` folder already prepared and **its letter** (A or B) with the variant it owns.

> Build variant <A|B> of concept "<name>". Use only catalog ids and **respect the `start_s`/`end_s`
> windows**. On-screen text and narration in <language tag>. Write
> `concepts/<concept>/<letter>/build.py` to generate the spec and render: the `build.py` has to rebuild
> everything from scratch, with no dependency on temporaries. Count the cuts where the subject appears
> and put it in your notes. Don't touch `common/` or the other builder's folder.

How the variants split (pick two that read differently):
- silent with diegetic sound / narrated
- long (30-40 s) / short (15 s)
- beat-cut photo dump / few long shots
- pure b-roll / the subject as a character

The shared work (9:16 crops, looped music bed, light copies) goes in `common/` and you or a single agent
does it. When each builder did it on its own, one used the raw 30 s preview and the last seconds of its
35 s video came out silent without anything warning.

## Reviewer agent (1 per concept)

It built neither variant. It receives both, the concept, the output language and the checklist from
`delivery.md`.

> Review both variants of concept "<name>". Pull an `fps=2,tile=12x6` strip of each and look at them.
> Run the technical checks from the checklist. **Compare the same frame between the two variants**: if
> the hook looks different, say which one is wrong. Check that every caption and narration line is in
> <language tag>, correctly spelled. Count the cuts with the subject by hand. Return a list of concrete
> corrections, each with the exact second and marking which ones **block** delivery. What blocks, you
> fix yourself: the correction goes inside the variant's `build.py` and you re-render. In
> `workflows/build.js` that is the **Fix** stage, which is only paid for if something is marked
> `blocks`.

What the reviewer has found in production, which is why it exists:
- a `look` that washed out the hook in 2 of 4 deliveries, because nobody compared across variants
- captions with hand-written `\n` that dropped an orphan word once the size went down
- a stamp on screen for 0.39 s, illegible
- a post-processing script with no execute permission that nobody was calling, so the audio kept
  clipping
- two cuts from the same clip 4° apart, which read as an editing mistake

## Hygiene

- **One agent, one output file.** Two agents writing the same file overwrite each other silently.
- Nobody deletes original material. Nobody publishes. Nobody spends money.
- If an agent fails halfway, its output file must not exist: that's the "redo this batch" signal. Have
  it write the JSON **at the end**, not incrementally.
- Read the results before moving to the next phase. A bad catalog gets multiplied by 4 concepts.
