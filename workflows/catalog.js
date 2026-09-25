// Material catalog — reel-forge
//
// Splits photos, videos and 360 clips across N parallel agents and returns a catalog of
// moments (`catalog.json`), which is the contract the concepts get written against and the
// variants get built from.
//
// Run with Claude Code's Workflow tool:
//   Workflow({ scriptPath: "<plugin>/workflows/catalog.js", args: { ... } })
//
// args (everything optional except the material):
//   project         name of the working folder, e.g. "summer-coast"
//   root            project root (default: ~/Movies/reel-forge on macOS, ~/Videos/... on Linux,
//                   %USERPROFILE%\Videos\reel-forge on Windows; REEL_FORGE_HOME wins if set)
//   days            [{ date: "2026-04-11", place: "Coast", files: ["/path/IMG_0001.HEIC", ...] }]
//   videos          [{ path: "/path/VID_0007.MOV", dur_s: 41 }]  (or just the path as a string)
//   clips360        [{ path: "/path/VID_0012.insv", dur_s: 28 }]
//   photoAgents     force the number of photo agents (otherwise computed, see below)
//   videosPerAgent  default 4
//   clipsPerAgent   default 1
//   verify          default true: a second pass over the video and 360 ranges
//   trends          default true: 1 agent with web search, in parallel with everything else
//   fresh           default false. true ignores the run ledger and catalogs everything again.
//   platform        "tiktok" | "reels" | "shorts"  (default "tiktok")
//   lang            BCP-47 tag for the ON-SCREEN TEXT and the narration, and the market the trend
//                   research targets: "es-MX", "en-US", "pt-BR"… (default "en")
//   subject         how to refer to the person in the material, with no proper names ("the user")
//
// RESUMING. Two mechanisms, and they stack:
//   1. In the same session, Workflow({ scriptPath, resumeFromRunId: "<runId>" }) replays the
//      unchanged prefix of agent() calls from cache.
//   2. From a cold start — the laptop slept, the session died, days went by — the run ledger on
//      disk is what survives. Every agent owns `workspace/run/<unit>.json` and rewrites it as it
//      goes; the first phase of this script reads those files and skips whatever is already done.
//      Nothing gets cataloged twice, and a run that lost seven agents to a sleeping machine picks
//      up exactly where they fell.

export const meta = {
  name: 'reel-forge-catalog',
  description: 'Catalogs photos, videos and 360 clips with several parallel agents and assembles catalog.json',
  whenToUse: "reel-forge's context phase: there is raw material and you need to know what moment is in each file and each video range, before deciding on concepts.",
  phases: [
    { title: 'Resume', detail: 'reads the run ledger and skips the batches already finished on disk' },
    { title: 'Photos', detail: 'one agent per day or per batch; contact sheets and face crops' },
    { title: 'Videos', detail: 'one agent per video batch: frame strip and audio, ranges with a start and an end' },
    { title: '360', detail: 'one agent per equirectangular clip: ring sheets and usable directions' },
    { title: 'Trends', detail: '1 agent with web search, runs in parallel with everything else' },
    { title: 'Verify', detail: 'a second pass over the video and 360 ranges, looking at the real window' },
    { title: 'Checkpoint', detail: 'folds the unit files into workspace/run.json' },
    { title: 'Merge', detail: 'merges the batches, drops duplicates and says what was left uncovered' },
  ],
}

// ─────────────────────────────────────────────────────────────── inputs

const A = args || {}
const PROJECT = A.project || 'project'
// Project root. macOS ~/Movies/reel-forge, Linux ~/Videos/reel-forge, Windows
// %USERPROFILE%\Videos\reel-forge, and REEL_FORGE_HOME wins if it is set.
// Pass it already resolved in args.root.
const ROOT = A.root || '~/Movies/reel-forge'
const WORKSPACE = `${ROOT}/${PROJECT}/workspace`
const LEDGER = `${WORKSPACE}/run.json`
const UNITS = `${WORKSPACE}/run`
const SCHEMAS = '$CLAUDE_PLUGIN_ROOT/schemas'
const REFS = '$CLAUDE_PLUGIN_ROOT/skills/reel-forge/references'
// The run ledger has no schema file of its own: its shape is written out in the orchestrator skill.
const LEDGER_DOC = '$CLAUDE_PLUGIN_ROOT/skills/reel-forge/SKILL.md, section "Resuming a run"'
const PLATFORM = A.platform || 'tiktok'
const LANG = A.lang || 'en'
const SUBJECT = A.subject || 'the user'

const days = A.days || []
const videos = (A.videos || []).map((v) => (typeof v === 'string' ? { path: v } : v))
const clips360 = (A.clips360 || []).map((v) => (typeof v === 'string' ? { path: v } : v))

if (!days.length && !videos.length && !clips360.length) {
  throw new Error('catalog.js: pass it material in args.days / args.videos / args.clips360')
}

const totalPhotos = days.reduce((n, d) => n + (d.files || []).length, 0)

// ──────────────────────────────────────────────────────── how many agents
//
// PHOTOS. The table comes from the `reel-forge` skill (the "Splitting work across agents"
// section) and from what a laptop can take before renders start taking minutes:
//
//   under 200 files → 3 agents
//   200 to 1000     → 6, and 8 if the trip covers more than 10 days
//   over 1000       → 10 (practical cap; a cheap sift first is worth it)
//
// On top of that, never more agents than days: an agent with half a day of material has
// nothing to compare against and repeats what the one next to it already said.
function photoAgentsFor(nFiles, nDays) {
  if (nFiles < 200) return 3
  if (nFiles <= 1000) return nDays > 10 ? 8 : 6
  return 10
}

const AG_PHOTOS = Math.max(1, Math.min(A.photoAgents || photoAgentsFor(totalPhotos, days.length), days.length || 1))

// VIDEOS. Actually watching a video is ~15 tool calls (frame strip, crops, transcription,
// checking a second). Past 4-5 videos the agent runs out of context and starts describing
// from memory, which is exactly what is useless.
const VIDEOS_PER_AGENT = A.videosPerAgent || 4

// 360. An equirectangular clip yields several different framings and needs its own ring
// sheets: it is worth a whole agent, even if it only runs 20 seconds.
const CLIPS_PER_AGENT = A.clipsPerAgent || 1

const FRESH = A.fresh === true
const VERIFY = A.verify !== false

// ───────────────────────────────────────────────────────────── utilities

// Splits a list into `n` parts as evenly as possible, preserving order.
function split(list, n) {
  const parts = []
  const base = Math.floor(list.length / n)
  let extra = list.length % n
  let i = 0
  for (let k = 0; k < n && i < list.length; k++) {
    const size = base + (extra > 0 ? 1 : 0)
    if (extra > 0) extra--
    parts.push(list.slice(i, i + size))
    i += size
  }
  return parts
}

// Cuts a list into fixed-size chunks.
function chunks(list, size) {
  const out = []
  for (let i = 0; i < list.length; i += size) out.push(list.slice(i, i + size))
  return out
}

// ───────────────────────────────────────────────────────────── schemas
//
// These are the shapes the agents RETURN to this script: a report of what they wrote, not the
// content. The content's contract lives in `schemas/` and the agent writes it to disk; passing a
// whole catalog back through a structured output would only copy the same thing twice.

const BATCH_REPORT = {
  type: 'object',
  properties: {
    batch: { type: 'string' },
    file: { type: 'string', description: 'absolute path of the catalog-<batch>.json you wrote' },
    moments: { type: 'integer', description: 'how many moments the file carries' },
    dropped: { type: 'integer', description: 'how many pieces you threw out, each with its reason inside the file' },
    best: { type: 'array', items: { type: 'string' }, description: 'ids that can open a video (hook 5)' },
    with_subject: { type: 'integer', description: 'how many moments carry the subject' },
    reused: { type: 'boolean', description: 'true if the file was already on disk from an earlier run and you did not look at the material again' },
    gaps: { type: 'array', items: { type: 'string' }, description: 'what this batch could not cover' },
    summary: { type: 'string', description: 'two or three lines on what is in this batch' },
  },
  required: ['batch', 'file', 'moments', 'summary'],
}

const TRENDS = {
  type: 'object',
  properties: {
    file: { type: 'string', description: 'path of the trends.json you wrote' },
    market: { type: 'string', description: 'the language and region you researched, e.g. "es-MX"' },
    formats: {
      type: 'array',
      items: { type: 'string' },
      description: 'Each one with the length it actually runs in that market and how it closes, e.g. "narrated guide, 45-60 s, closes on the price card". A format with no duration is half an answer.',
    },
    sounds: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' }, artist: { type: 'string' },
          bpm: { type: 'number' }, source: { type: 'string', description: 'where the fact came from, with a date' },
        },
        required: ['title', 'source'],
      },
    },
    hooks: { type: 'array', items: { type: 'string' } },
    avoid: { type: 'array', items: { type: 'string' } },
  },
  required: ['market', 'formats', 'sounds'],
}

const MERGED = {
  type: 'object',
  properties: {
    file: { type: 'string', description: 'path of catalog.json' },
    total: { type: 'integer' },
    with_subject: { type: 'integer' },
    duplicates_removed: { type: 'integer' },
    best: { type: 'array', items: { type: 'string' }, description: 'ids with hook 5, candidates for the first frame' },
    gaps: { type: 'array', items: { type: 'string' }, description: 'what is missing: an uncovered day, a clip with unreviewed audio…' },
    summary: { type: 'string' },
  },
  required: ['file', 'total', 'summary'],
}

const LEDGER_SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string', description: 'path of the run.json you read or created' },
    units: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          state: { type: 'string', enum: ['pending', 'running', 'done', 'failed'] },
          artifact: { type: 'string', description: 'path of the finished file, or "" if there is none' },
          note: { type: 'string' },
        },
        required: ['id', 'state'],
      },
    },
    summary: { type: 'string' },
  },
  required: ['units', 'summary'],
}

const CHECKPOINT = {
  type: 'object',
  properties: {
    file: { type: 'string' },
    done: { type: 'integer' },
    pending: { type: 'integer' },
    failed: { type: 'array', items: { type: 'string' } },
  },
  required: ['file', 'done'],
}

// ──────────────────────────────────────────────────────────── the contract
//
// This goes in EVERY prompt. It says what the agent's job is and WHERE the rules live; it does not
// copy the rules in. Repeating a contract in six prompts means six copies to keep in sync, and the
// one that drifts is the one that produces the batch you have to redo.

const CONTRACT = `
You are a reel-forge context agent. Your job is to LOOK at the material and describe it, not edit it.

Read before you start, and follow them as written:
- ${REFS}/selection.md — what gets dropped and why, how to look (contact sheets, face crops, bursts).
- ${REFS}/catalog.md — how a moment is described.
- ${SCHEMAS}/catalog-item.schema.json — the exact shape of the file you write. It is the contract every
  later phase reads. Do not improvise fields and do not rename them: a batch in its own invented
  format has to be cataloged again from zero.
- Videos are cataloged as RANGES with \`start_s\` and \`end_s\`, never as whole files.

Platform: ${PLATFORM}, vertical 9:16. Output language for the on-screen text: ${LANG}. Your catalog is
written in English; the language tag is there so you can flag copy that appears in the footage itself
(a sign, a menu) and might need translating on screen. The main person is referred to as ${SUBJECT},
with no proper names anywhere in the file.
`.trim()

// The progress protocol. This is the part that survives a sleeping laptop, and it is why every agent
// owns exactly one progress file that nobody else writes.
function progress(id, artifact) {
  return `
PROGRESS PROTOCOL — not optional. A round of this plugin lost seven agents because the machine went
to sleep mid-run and none of them had left a trace of where they were.

- Your unit id is \`${id}\`. Your progress file is \`${UNITS}/${id}.json\` and **nobody else writes it**.
  Its shape is the \`unit\` object described in ${LEDGER_DOC}.
- Write it the moment you start (\`"state": "running"\`, the step you are on, the list of steps left),
  and rewrite it every time you finish a step. **Never go more than ~2 minutes without rewriting it.**
  A unit file whose timestamp stopped moving is how the next run knows where you died.
- Write to \`<file>.tmp\` and rename it into place, so a half-written file is never read back.
- **Split long work into steps that finish in under ~2 minutes** and save what each one produced:
  a proxy built in chunks with \`-ss\`/\`-t\` and concatenated, a sheet per instant, a transcription per
  section. A single 12-minute ffmpeg call that gets killed leaves nothing behind; twelve one-minute
  calls leave eleven.
- Partial results go in \`${artifact}.partial.json\`, which you extend as you go. **Your real output
  file, \`${artifact}\`, is written once and complete**, by renaming the partial into place when you
  are done: from then on, its existence means "this batch is finished" and nothing re-does it.
- Last step, always: set \`"state": "done"\` in your progress file with the artifact's path. Never
  report a result you have not written to disk.

If \`${artifact}\` already exists and covers exactly this batch, read it, return its numbers with
\`"reused": true\` and stop. Do not look at the material again.
If \`${artifact}.partial.json\` exists, carry on from where it stops instead of starting over.
`.trim()
}

// ──────────────────────────────────────────────────────────── the batches

const batches = []

split(days, AG_PHOTOS).forEach((group, i) => {
  const files = group.flatMap((d) => d.files || [])
  if (!files.length) return
  batches.push({
    kind: 'photos',
    id: `photos-${i + 1}`,
    phase: 'Photos',
    label: `Photos ${group.map((d) => d.date || d.place || '?').join(', ')}`,
    days: group,
    files,
  })
})

chunks(videos, VIDEOS_PER_AGENT).forEach((group, i) => {
  batches.push({
    kind: 'video',
    id: `video-${i + 1}`,
    phase: 'Videos',
    label: `Videos ${i + 1} (${group.length})`,
    files: group,
  })
})

chunks(clips360, CLIPS_PER_AGENT).forEach((group, i) => {
  batches.push({
    kind: '360',
    id: `c360-${i + 1}`,
    phase: '360',
    label: `360 ${group.map((c) => c.path.split('/').pop()).join(', ')}`,
    files: group,
  })
})

function artifactOf(batch) {
  return `${WORKSPACE}/catalog/catalog-${batch.id}.json`
}

// ───────────────────────────────────────────────────────────── prompts

function catalogPrompt(batch) {
  const head = `${CONTRACT}\n\n${progress(batch.id, artifactOf(batch))}`

  if (batch.kind === 'photos') {
    return `${head}

BATCH ${batch.id} — photos from: ${batch.days.map((d) => `${d.date || 'no date'} ${d.place || ''}`).join(' · ')}

Files (${batch.files.length}):
${batch.files.map((f) => `- ${f}`).join('\n')}

Steps (each one short enough to finish inside the 2-minute rule, and each one saved before the next):
1. Contact sheets with numbered thumbnails covering the WHOLE batch, ~30 per sheet, and LOOK at them:
   uv run "$CLAUDE_PLUGIN_ROOT/skills/sources/scripts/sheets.py" contact <list.json> --out <folder>
2. Face crops for the candidates, to check the expression (same script, \`faces\` subcommand).
3. One moment per photo that survives, appended to the partial as you go, with its focus point if the
   photo is horizontal (in 9:16 a landscape photo gets cropped: say in \`framing\` where the subject is).
4. Rename the partial to ${artifactOf(batch)} and return its numbers.`
  }

  if (batch.kind === 'video') {
    return `${head}

BATCH ${batch.id} — videos:
${batch.files.map((v) => `- ${v.path}${v.dur_s ? ` (${v.dur_s} s)` : ''}`).join('\n')}

Steps, one video at a time, saving the partial after each video so a kill never costs more than one:
1. A frame strip of the video, and LOOK at it:
   ffmpeg -i <video> -vf "fps=1,scale=216:384,tile=8x4" -frames:v 1 <sheet>.jpg
   (for long clips drop to fps=0.5; to find an exact instant, go up to fps=4 in that window). A clip
   over ~4 minutes gets its strip in sections, not in one call.
2. If it has speech or usable sound, transcribe it with timestamps, section by section. Timings done
   "by ear" drift by several seconds: measure, do not estimate.
3. One moment per usable RANGE, with real \`start_s\` and \`end_s\`. Before pinning the start, pull the
   exact frame of that second and look at it: that is where everybody gets it wrong.
4. Note in \`notes\` whether the clip is 60 fps (real slow motion is available) and whether it is
   horizontal.
5. Rename the partial to ${artifactOf(batch)} and return its numbers.`
  }

  return `${head}

BATCH ${batch.id} — 360 clips (equirectangular):
${batch.files.map((v) => `- ${v.path}${v.dur_s ? ` (${v.dur_s} s)` : ''}`).join('\n')}

Read ${REFS}/video360.md first: what a planet does to a face at a metre, where the stitch seam is and
why two reframes at similar yaw read as the same shot are all in there.

360 is the longest job in the plugin and the one that most often dies mute. Steps, each saved:
1. The proxy, **built in chunks** (\`-ss\`/\`-t\` of ~60 s, concatenated at the end) with the chunk
   number written into your progress file. A single call over a 5-minute clip runs past ten minutes
   and leaves nothing if it is killed.
2. Ring sheets at several instants, one call per instant, and LOOK at them with Read.
3. One moment per useful DIRECTION (yaw/pitch/fov), not one per clip: the same clip gives you the
   subject, the landscape and the horizon with nobody in it. Append each one to the partial.
4. Test renders of 2-4 s per framing, one at a time; a reframe with no rendered test that you looked
   at does not get delivered.
5. Rename the partial to ${artifactOf(batch)} and return its numbers.`
}

function reusePrompt(batch) {
  return `Batch ${batch.id} of the reel-forge catalog was already finished in an earlier run.

Read ${artifactOf(batch)} and return its numbers: how many moments, how many drops, which ids can open
a video, how many carry the subject. Set \`"reused": true\`.

Do NOT re-catalog and do NOT open the material. The one thing worth checking is that the file parses
and covers the ${batch.files.length} files of this batch; if it does not, say so in \`gaps\` and return
\`"moments": 0\` so the run knows the batch has to be redone.`
}

function verifyPrompt(batch) {
  return `Verification of reel-forge batch ${batch.id}. Do NOT re-catalog: check what was already said.

The batch is in ${artifactOf(batch)}. Its shape is in ${SCHEMAS}/catalog-item.schema.json.

${progress(`${batch.id}-verify`, artifactOf(batch))}

For EACH range, pull a 4 fps strip of its real window (\`-ss start_s -t (end_s - start_s)\`) and look
at it, a few ranges at a time, saving your progress between groups:
- Does it show what the description says, or is there a drift of several seconds?
- Are there scene cuts, a hand over the lens, a stranger's face against the lens?
- Does the range hold the ~0.8 s minimum on screen?
Fix \`start_s\`/\`end_s\` and \`description\` where needed, throw out what does not exist (into the file's
drop list, with the reason) and REWRITE ${artifactOf(batch)} with the corrected version, through the
temporary-and-rename move. Return the corrected numbers.`
}

// ───────────────────────────────────────────────────────────── the run

log(`Material: ${totalPhotos} photos across ${days.length} days, ${videos.length} videos, ${clips360.length} 360 clips`)
log(`Batches: ${AG_PHOTOS} photo, ${chunks(videos, VIDEOS_PER_AGENT).length} video, ${clips360.length ? chunks(clips360, CLIPS_PER_AGENT).length : 0} of 360`)
log(`Output language: ${LANG} · platform: ${PLATFORM}`)

// ── Resume. First thing, before spending a single agent on material: what is already on disk?
// The script itself cannot read files, so one cheap agent reads the ledger and reports back.
phase('Resume')

const ledger = FRESH ? null : await agent(
  `Read the reel-forge run ledger for project "${PROJECT}" and report what is already finished.

1. Read ${LEDGER} if it exists, and every file in ${UNITS}/.
2. Read the actual contents of ${WORKSPACE}/catalog/ . **The files on disk win over the ledger**: a
   complete \`catalog-<batch>.json\` means that batch is done even if the ledger never got updated,
   and a ledger entry with no file behind it is not done.
3. These are the batches this run is about to launch:
${batches.map((b) => `   - ${b.id} → ${artifactOf(b)} (${b.files.length} files)`).join('\n')}
4. Return one unit per batch id, \`"state": "done"\` only if its file exists, parses against
   ${SCHEMAS}/catalog-item.schema.json and covers that batch's files. Anything half-written, missing or
   covering a different file list is \`"pending"\`.
5. Also return a unit \`trends\` (done only if ${WORKSPACE}/trends/trends.json exists and parses) and
   a unit \`merge\` (done only if ${WORKSPACE}/catalog/catalog.json exists and parses).
6. Write or update ${LEDGER} with what you found, following the shape in ${LEDGER_DOC}, through a
   temporary and a rename.

Do not catalog anything and do not open any photo or video. This is bookkeeping only.`,
  { label: 'Read the ledger', phase: 'Resume', schema: LEDGER_SCHEMA, effort: 'low' },
)

const doneUnits = new Set(
  ((ledger && ledger.units) || []).filter((u) => u.state === 'done').map((u) => u.id),
)
if (doneUnits.size) log(`Resuming: ${doneUnits.size} unit(s) already finished on disk — ${[...doneUnits].join(', ')}`)
else if (!FRESH) log('Nothing on disk yet: full run')

// Trends starts NOW and gets collected at the end: it does not depend on the catalog and the catalog
// does not depend on it, so it has no reason to queue behind anybody.
const pendingTrends = (A.trends === false || doneUnits.has('trends')) ? null : agent(
  `Research what is working RIGHT NOW on vertical ${PLATFORM} for personal travel/event video,
in the market of the language ${LANG}. The region matters: ${LANG} means that country's charts, hooks
and caption styles, not a generic global view. Search IN that language, not in English about it, and
query the music store with that region code.

The method, the sourcing rules and what counts as a measured BPM are in ${REFS}/trends.md. Read it.
Write ${WORKSPACE}/trends/trends.json in the shape ${REFS}/trends.md describes, and follow the progress
protocol for unit \`trends\`:

${progress('trends', `${WORKSPACE}/trends/trends.json`)}

For every format, bring back **the length it actually runs** and how it ends — the durations that are
working right now in that market, cited, not assumed. This round's concepts set their own duration from
their own story, and this is the evidence they weigh it against: a market where the format that works is
a 50-second narrated piece is not one where everything should come out at 25 s.

Return the market you targeted, the formats with their real durations, the sounds with their measured or
cited BPM, the first-second hooks (written as they would appear on screen, in ${LANG}) and what looks
dated — including endings that read as dated, since how a video lands is part of the format. Every
sound with its source and its date: NEVER invent "trending" songs and never assume a BPM. If you
cannot find the fact, leave the field empty and say so.`,
  { label: 'Trends', phase: 'Trends', schema: TRENDS },
)

phase('Photos')

// pipeline, not parallel: each batch moves to its verification as soon as it finishes, without waiting
// for the others. Day 1's photo batch has no reason to wait for somebody to finish transcribing a video.
const cataloged = await pipeline(
  batches,

  (_prev, batch) => (
    doneUnits.has(batch.id)
      // Already on disk. One cheap agent reads it back instead of an expensive one looking again.
      ? agent(reusePrompt(batch), { label: `Reuse ${batch.id}`, phase: batch.phase, schema: BATCH_REPORT, effort: 'low' })
      : agent(catalogPrompt(batch), { label: batch.label, phase: batch.phase, schema: BATCH_REPORT })
  ),

  (res, batch) => {
    if (!res || !res.moments) return res
    // Only video and 360 get verified: the expensive mistake is the time window, and photos have none.
    // A batch read back from disk was already verified in the run that produced it.
    if (!VERIFY || batch.kind === 'photos' || res.reused) return res
    return agent(verifyPrompt(batch), { label: `Verify ${batch.id}`, phase: 'Verify', schema: BATCH_REPORT })
  },
)

const ok = cataloged.filter(Boolean)
const lost = batches.filter((_, i) => !cataloged[i] || !cataloged[i].moments).map((b) => b.id)
if (lost.length) log(`Batches with no result (they have to be redone; the run ledger keeps them pending): ${lost.join(', ')}`)

const reused = ok.filter((r) => r.reused).length
if (reused) log(`${reused} batch(es) reused from disk without re-cataloging`)

// ── Checkpoint. The unit files are the truth; this folds them into one ledger the orchestrator (and
// the next run, and the user) can read at a glance.
phase('Checkpoint')

await agent(
  `Update the reel-forge run ledger for project "${PROJECT}".

Read every file in ${UNITS}/ and the contents of ${WORKSPACE}/catalog/, and rewrite ${LEDGER} to match
what is actually on disk, following the shape in ${LEDGER_DOC}. Use a temporary and a rename.

What this run just did:
${batches.map((b, i) => `- ${b.id}: ${cataloged[i] && cataloged[i].moments ? `done → ${artifactOf(b)}` : 'NOT finished'}`).join('\n')}

Mark the phase \`catalog\` as \`running\` (the merge has not happened yet). Do not change anything
outside the ledger, do not delete any catalog file, and do not catalog anything yourself.`,
  { label: 'Checkpoint', phase: 'Checkpoint', schema: CHECKPOINT, effort: 'low' },
)

// Here a barrier genuinely is needed: merging and deduplicating needs ALL the batches at once.
phase('Merge')

const trends = pendingTrends ? await pendingTrends : null

const merged = await agent(
  `Close the reel-forge catalog for project "${PROJECT}".

The batches are the \`catalog-*.json\` files in ${WORKSPACE}/catalog/ (${ok.length} finished this run,
${ok.reduce((n, r) => n + (r.moments || 0), 0)} moments between them). Their shape, and the shape of
the merged file, are in ${SCHEMAS}/catalog-item.schema.json.

${progress('merge', `${WORKSPACE}/catalog/catalog.json`)}

Your job:
1. Merge every batch file into ${WORKSPACE}/catalog/catalog.json, sorted by date and time. Read them
   from disk; do not trust any summary, including this one.
2. Remove duplicates: the same source with the same window is one moment, and two photos from the same
   burst with the same description are one moment — keep the better one and note the other as dropped.
3. Mark the candidates for the first frame (hook 5) and count how many moments carry the subject.
4. Say what is MISSING (\`gaps\`): an uncovered day, a clip whose audio was never reviewed, a stretch
   of the trip with no b-roll, a batch that returned nothing. That is what goes to the next round.
5. **Judge the rectangle, not just the moment.** The curators described what was HAPPENING; run the
   frame check over the merged catalog, in one process, so it measures what the 9:16 crop will show:

   uv run "$CLAUDE_PLUGIN_ROOT/skills/sources/scripts/framecheck.py" \\
       --catalog ${WORKSPACE}/catalog/catalog.json --apply

   \`--apply\` writes \`obstructions\` back only for the unambiguous case — bodies near the lens under
   the subject — and caps that item's \`quality\` at 2 with the reason in \`notes\`. Everything else
   it saw (a lone window edge, veiling glare) is in \`catalog.framecheck.json\` beside it, for the
   directors to weigh. It prints what it flagged; report that list. A catalog once said "passenger
   heads in the foreground" in plain words, still rated the clip 4, and the clip shipped.
6. Validate the merged file: \`uv run ${SCHEMAS}/validate.py ${WORKSPACE}/catalog/catalog.json --type catalog-item\`.
7. Update ${LEDGER}: phase \`catalog\` → \`done\`, with \`${WORKSPACE}/catalog/catalog.json\` as its
   artifact.
Do not invent moments that are not in the batches.

Batches that returned nothing and are still pending in the ledger: ${lost.length ? lost.join(', ') : 'none'}.`,
  { label: 'Merge catalog', phase: 'Merge', schema: MERGED },
)

return {
  project: PROJECT,
  workspace: WORKSPACE,
  ledger: LEDGER,
  lang: LANG,
  catalog: merged,
  batches: ok,
  reused_batches: reused,
  trends,
  failed_batches: lost,
  resume_hint: lost.length
    ? `Re-run this same workflow to pick up ${lost.join(', ')}: everything finished is read back from disk instead of being cataloged again.`
    : 'Nothing pending.',
}
