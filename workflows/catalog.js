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
//   platform        "tiktok" | "reels" | "shorts"  (default "tiktok")
//   lang            BCP-47 tag for the ON-SCREEN TEXT and the narration, and the market the trend
//                   research targets: "es-MX", "en-US", "pt-BR"… (default "en")
//   subject         how to refer to the person in the material, with no proper names ("the user")
//
// Every agent writes its part to disk BEFORE answering
// (workspace/catalog/catalog-<batch>.json). If the workflow gets interrupted, the next run
// reuses it instead of looking at the same material again. To resume without even losing that:
// Workflow({ scriptPath, resumeFromRunId: "<runId>" }).

export const meta = {
  name: 'reel-forge-catalog',
  description: 'Catalogs photos, videos and 360 clips with several parallel agents and assembles catalog.json',
  whenToUse: "reel-forge's context phase: there is raw material and you need to know what moment is in each file and each video range, before deciding on concepts.",
  phases: [
    { title: 'Photos', detail: 'one agent per day or per batch; contact sheets and face crops' },
    { title: 'Videos', detail: 'one agent per video batch: frame strip and audio, ranges with a start and an end' },
    { title: '360', detail: 'one agent per equirectangular clip: ring sheets and usable directions' },
    { title: 'Trends', detail: '1 agent with web search, runs in parallel with everything else' },
    { title: 'Verify', detail: 'a second pass over the video and 360 ranges, looking at the real window' },
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

const MOMENT = {
  type: 'object',
  properties: {
    id: { type: 'string', description: 'a short unique identifier, e.g. "d3-07" or "v2-11"' },
    source: { type: 'string', description: 'absolute path of the file' },
    type: { type: 'string', enum: ['photo', 'video', '360'] },
    start_s: { type: 'number', description: 'video/360 only: the second the usable range starts' },
    end_s: { type: 'number', description: 'video/360 only: the second it stops being usable' },
    description: { type: 'string', description: 'what you see, in one concrete sentence' },
    hook: { type: 'integer', description: '1 filler, 5 works as the video’s first frame' },
    subject_present: { type: 'boolean' },
    favorite: { type: 'boolean', description: 'starred as a favorite in the library' },
    audio: { type: 'string', description: 'what you hear; "" if there is none or it is useless' },
    framing: { type: 'string', description: 'vertical | horizontal | square, and the 0-1 focus point if horizontal' },
    notes: { type: 'string', description: 'what whoever builds needs to know so they do not get it wrong' },
  },
  required: ['id', 'source', 'type', 'description', 'hook', 'subject_present'],
}

const BATCH = {
  type: 'object',
  properties: {
    batch: { type: 'string' },
    file: { type: 'string', description: 'path of the catalog-<batch>.json you wrote' },
    moments: { type: 'array', items: MOMENT },
    dropped: {
      type: 'array',
      description: 'what you threw out and why: the user may want it back',
      items: {
        type: 'object',
        properties: { source: { type: 'string' }, reason: { type: 'string' } },
        required: ['source', 'reason'],
      },
    },
    summary: { type: 'string', description: 'two or three lines on what is in this batch' },
  },
  required: ['batch', 'moments', 'summary'],
}

const TRENDS = {
  type: 'object',
  properties: {
    market: { type: 'string', description: 'the language and region you researched, e.g. "es-MX"' },
    formats: { type: 'array', items: { type: 'string' } },
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
    best: { type: 'array', items: { type: 'string' }, description: 'ids with hook 5, candidates for the first frame' },
    gaps: { type: 'array', items: { type: 'string' }, description: 'what is missing: an uncovered day, a clip with unreviewed audio…' },
    summary: { type: 'string' },
  },
  required: ['file', 'total', 'summary'],
}

// ──────────────────────────────────────────────────────────── the contract

// This goes in EVERY prompt: an agent that improvises the format forces the batch to be redone.
const CONTRACT = `
You are a reel-forge context agent. Your job is to LOOK at the material and describe it, not edit it.

Rules that are not negotiable (they are in the \`reel-forge\` skill, sections "Selection rules" and "Splitting work across agents"):
- Actually look at the image. Never catalog by file name, by date or at random.
- Videos are cataloged as RANGES with \`start_s\` and \`end_s\`, not as whole files. A 40 s clip usually
  holds 3-6 usable seconds; the rest is filler and does not go in the catalog.
- The second with the good image is not the second with the good audio: if a range is worth it for what
  you hear, say so in \`audio\` and leave \`start_s\`/\`end_s\` on the range where the IMAGE works.
- Drop half-formed expressions, forced poses, blurry shots, near-identical duplicates, screenshots,
  documents, receipts, screens with work on them and anything sensitive. Note every drop with its reason
  in \`dropped\`.
- When ${SUBJECT} appears, look at their FACE in a crop, not just the framing: at thumbnail size a
  grimace does not show. Review the full burst, there is almost always a better take of the same scene.
- Platform: ${PLATFORM}, vertical 9:16 format. Output language for the on-screen text: ${LANG}.
  Your catalog is written in English; the language tag is there so you can flag copy that appears in the
  footage itself (a sign, a menu) and might need translating on screen.

Before answering, WRITE your result to disk:
  ${WORKSPACE}/catalog/catalog-<batch>.json
One agent, one batch, one file: if two write the same one, they overwrite each other. If that file
ALREADY exists and is complete (same batch, same files), read it and return it as is instead of looking
at everything again.
`.trim()

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

// ───────────────────────────────────────────────────────────── prompts

function catalogPrompt(batch) {
  if (batch.kind === 'photos') {
    return `${CONTRACT}

BATCH ${batch.id} — photos from: ${batch.days.map((d) => `${d.date || 'no date'} ${d.place || ''}`).join(' · ')}

Files (${batch.files.length}):
${batch.files.map((f) => `- ${f}`).join('\n')}

How:
1. A contact sheet with numbered thumbnails of the WHOLE batch, and LOOK at it. Suggested:
   the plugin's sheets script (skill \`sources\`):
   uv run "$CLAUDE_PLUGIN_ROOT/skills/sources/scripts/sheets.py" contact <list.json> --out <folder>
2. For the candidates, a face crop to check the expression (same script, \`faces\` subcommand).
3. One moment per photo that survives, with its focus point if the photo is horizontal
   (in 9:16 a landscape photo gets cropped: say in \`framing\` where the subject is, 0-1 in x and y).
4. Write ${WORKSPACE}/catalog/catalog-${batch.id}.json and return it.`
  }

  if (batch.kind === 'video') {
    return `${CONTRACT}

BATCH ${batch.id} — videos:
${batch.files.map((v) => `- ${v.path}${v.dur_s ? ` (${v.dur_s} s)` : ''}`).join('\n')}

How:
1. A frame strip of each video, and LOOK at it:
   ffmpeg -i <video> -vf "fps=1,scale=216:384,tile=8x4" -frames:v 1 <sheet>.jpg
   (for long clips drop to fps=0.5; to find an exact instant, go up to fps=4 in that window).
2. If it has speech or usable sound, transcribe it with timestamps. Timings done "by ear" drift by
   several seconds: measure, do not estimate.
3. One moment per usable RANGE, with real \`start_s\` and \`end_s\`. Before pinning the start, pull the
   exact frame of that second and look at it: that is where everybody gets it wrong.
4. Note in \`notes\` whether the clip is 60 fps (real slow motion is available) and whether it is
   horizontal.
5. Write ${WORKSPACE}/catalog/catalog-${batch.id}.json and return it.`
  }

  return `${CONTRACT}

BATCH ${batch.id} — 360 clips (equirectangular):
${batch.files.map((v) => `- ${v.path}${v.dur_s ? ` (${v.dur_s} s)` : ''}`).join('\n')}

How (read the plugin's \`video-360\` skill first):
1. An equirectangular proxy and ring sheets at several instants. Without looking at them you cannot
   write keys.
2. One moment per useful DIRECTION (yaw/pitch/fov), not one per clip: the same clip gives you the
   subject, the landscape and the bow. Put it in \`notes\` with the degrees.
3. Two framings of the same clip at similar yaw read as the same shot repeated: separate them by at
   least 90° or change the subject, and say so in \`notes\`.
4. If the person filming is within 2-3 m of the lens, note in \`notes\` that a tiny planet does NOT go
   there: the stereographic projection deforms their face in any direction. Propose a rectilinear push
   instead.
5. Write ${WORKSPACE}/catalog/catalog-${batch.id}.json and return it.`
}

function verifyPrompt(batch, res) {
  const sample = res.moments.slice(0, 40)
  return `Verification of reel-forge batch ${batch.id}. Do NOT re-catalog: check what was already said.

What the agent that looked at it returned:
${sample.map((m) => `- ${m.id} · ${m.source} · ${m.start_s ?? '?'}-${m.end_s ?? '?'} s · ${m.description}`).join('\n')}
${res.moments.length > sample.length ? `\n(+${res.moments.length - sample.length} more moments in ${WORKSPACE}/catalog/catalog-${batch.id}.json: review them there)` : ''}

For EACH range, pull a 4 fps strip of its real window (\`-ss start_s -t (end_s - start_s)\`) and look at it:
- Does it show what the description says, or is there a drift of several seconds?
- Are there scene cuts, a hand over the lens, a stranger's face against the lens?
- Does the range hold the ~0.8 s minimum on screen?
Fix \`start_s\`/\`end_s\` and \`description\` where needed, throw out what does not exist (into \`dropped\`,
with the reason), and REWRITE ${WORKSPACE}/catalog/catalog-${batch.id}.json with the corrected version.
Return the complete, corrected batch, in the same format.`
}

// ───────────────────────────────────────────────────────────── the run

log(`Material: ${totalPhotos} photos across ${days.length} days, ${videos.length} videos, ${clips360.length} 360 clips`)
log(`Batches: ${AG_PHOTOS} photo, ${chunks(videos, VIDEOS_PER_AGENT).length} video, ${clips360.length ? chunks(clips360, CLIPS_PER_AGENT).length : 0} of 360`)
log(`Output language: ${LANG} · platform: ${PLATFORM}`)

// Trends starts NOW and gets collected at the end: it does not depend on the catalog and the catalog
// does not depend on it, so it has no reason to queue behind anybody.
const pendingTrends = A.trends === false ? null : agent(
  `Research what is working RIGHT NOW on vertical ${PLATFORM} for personal travel/event video,
in the market of the language ${LANG}. The region matters: ${LANG} means that country's charts, hooks
and caption styles, not a generic global view. Search IN that language, not in English about it, and
query the music store with that region code.
Use web search. Return the market you targeted, the formats, the sounds with their measured or cited
BPM, the first-second hooks (written as they would appear on screen, in ${LANG}) and what looks dated.
Every sound with its source and its date: NEVER invent "trending" songs and never assume a BPM. If you
cannot find the fact, leave the field empty and say so.`,
  { label: 'Trends', phase: 'Trends', schema: TRENDS },
)

const VERIFY = A.verify !== false

phase('Photos')

// pipeline, not parallel: each batch moves to its verification as soon as it finishes, without waiting
// for the others. Day 1's photo batch has no reason to wait for somebody to finish transcribing a video.
const cataloged = await pipeline(
  batches,
  (_prev, batch) => agent(catalogPrompt(batch), { label: batch.label, phase: batch.phase, schema: BATCH }),
  (res, batch) => {
    if (!res || !res.moments.length) return res
    // Only video and 360 get verified: the expensive mistake is the time window, and photos have none.
    if (!VERIFY || batch.kind === 'photos') return res
    return agent(verifyPrompt(batch, res), { label: `Verify ${batch.id}`, phase: 'Verify', schema: BATCH })
  },
)

const ok = cataloged.filter(Boolean)
const lost = batches.filter((_, i) => !cataloged[i]).map((b) => b.id)
if (lost.length) log(`Batches with no result (they have to be redone): ${lost.join(', ')}`)

// Here a barrier genuinely is needed: merging and deduplicating needs ALL the batches at once.
phase('Merge')

const moments = ok.flatMap((r) => r.moments)
const dropped = ok.flatMap((r) => r.dropped || [])
const seen = new Set()
const unique = moments.filter((m) => {
  const key = `${m.source}|${m.start_s ?? ''}|${m.end_s ?? ''}`
  if (seen.has(key)) return false
  seen.add(key)
  return true
})
log(`${unique.length} moments (${moments.length - unique.length} duplicates removed), ${dropped.length} drops`)

const trends = pendingTrends ? await pendingTrends : null

const merged = await agent(
  `Close the reel-forge catalog for project "${PROJECT}".

The batches are in ${WORKSPACE}/catalog/catalog-*.json (${ok.length} files, ${unique.length} unique
moments with the exact duplicates already removed). Your job:
1. Merge them into ${WORKSPACE}/catalog/catalog.json, sorted by date and time.
2. Remove the duplicates the path filter did not catch: two photos from the same burst with the same
   description are one moment; keep the better one and note the other in \`dropped\`.
3. Mark the candidates for the first frame (hook 5) and count how many moments carry the subject.
4. Say what is MISSING (\`gaps\`): an uncovered day, a clip whose audio was never reviewed, a stretch of
   the trip with no b-roll, a batch that returned nothing. That is what goes to the next round.
Do not invent moments that are not in the batches.

Batches that returned nothing: ${lost.length ? lost.join(', ') : 'none'}.`,
  { label: 'Merge catalog', phase: 'Merge', schema: MERGED },
)

return {
  project: PROJECT,
  workspace: WORKSPACE,
  lang: LANG,
  catalog: merged,
  moments: unique,
  dropped,
  trends,
  failed_batches: lost,
}
