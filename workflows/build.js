// Building concepts — reel-forge
//
// Takes already decided concepts and builds each one: ONE agent prepares the shared material, ONE
// agent per variant builds it, and one reviewer per concept sees every variant together.
//
// Run with Claude Code's Workflow tool:
//   Workflow({ scriptPath: "<plugin>/workflows/build.js", args: { ... } })
//
// args:
//   concepts              [{ id, title, hook, promise, close, structure, duration_s, music, narration,
//                            variants: [{ letter: "A", what: "silent, 35 s", duration_s: 35 }, ...],
//                            moments: ["d3-07", "v2-11", ...] }]     ← catalog ids
//   plugin_root           the plugin's install path, resolved — REQUIRED in practice: $CLAUDE_PLUGIN_ROOT is not
//                         set in the shell the agents run their commands in
//   project, root         where the project lives (see catalog.js)
//   project_dir           the folder holding workspace/ and facts.json (default <root>/<project>)
//   workspace, deliveries override the two folders, for a project that predates the layout
//   version               delivery round, default "v1" (the previous one is never overwritten)
//   variantsPerConcept    default 2, used only when a concept arrives with no variants written
//   storyDoctor           default true: the story-doctor passes, before building and after rendering
//   reviewer              default true
//   fix                   default true: if the reviewer finds something blocking, it gets fixed
//   fresh                 default false. true ignores the run ledger and rebuilds everything.
//   engine                render engine command (default: the video-engine skill's)
//   verifier              delivery verifier command (default: the video-engine skill's verify.py)
//   catalog               path of catalog.json (default: <workspace>/catalog/catalog.json)
//   trends                path of trends.json, if the trends phase left one
//   platform, lang, subject
//
// ONE AGENT PER VARIANT. This used to be two agents that split the variants between them, and the
// variants were what got lost: a builder that dies takes its whole half of the concept with it, and
// two agents on the same concept both re-export the same originals. Now the shared work happens ONCE,
// before anybody builds, in `workspace/concepts/<slug>/common/`, and each variant is an independent
// agent with its own folder, its own progress file and its own delivery.
//
// THE STORY-DOCTOR RUNS TWICE, and what it says is binding. The feedback that put it here, verbatim:
// *"something is being developed and it gets cut too soon"*. Videos were coming out as a hook plus a
// handful of shots, all of them 15-30 s because that was the template, ending mid-motion. So:
//   · before anything is built, it reads the concept and fixes the arc — hook, promise, development, turn, close
//     — and sets the duration EACH VARIANT needs from its own beats, not from a house default;
//   · after everything is rendered, it watches the variants and says which ones stop instead of ending.
// Its `blocks` go into the same Fix stage as the reviewer's.
//
// RESUMING. Same two mechanisms as catalog.js:
//   1. Same session: Workflow({ scriptPath, resumeFromRunId: "<runId>" }).
//   2. Cold start: the run ledger on disk. Every agent owns `workspace/run/<unit>.json`; the first
//      phase reads them and skips the variants that are already rendered and verified. A concept
//      whose A is delivered and whose B died only rebuilds B.

export const meta = {
  name: 'reel-forge-build',
  description: 'Prepares the shared material once per concept, builds one agent per variant and reviews them together',
  whenToUse: 'The catalog, the trends and the concepts are decided, and it is time to render each concept’s variants.',
  phases: [
    { title: 'Resume', detail: 'reads the run ledger and skips the variants already delivered' },
    { title: 'Story', detail: '1 story-doctor per concept BEFORE building: the arc, the close and the duration each variant needs' },
    { title: 'Common', detail: 'ONE agent per concept prepares what every variant shares: originals, crops, 360 renders, music bed' },
    { title: 'Build', detail: 'one agent per variant, each with its own folder and its own progress file' },
    { title: 'Arc', detail: '1 story-doctor per concept AFTER rendering: does it develop, does it land, does the duration fit' },
    { title: 'Review', detail: '1 reviewer per concept: sees every variant together and compares the same frame' },
    { title: 'Fix', detail: 'only if the story-doctor or the reviewer found something that blocks delivery' },
    { title: 'Checkpoint', detail: 'folds the unit files into workspace/run.json' },
  ],
}

// ─────────────────────────────────────────────────────────────── inputs

const A = args || {}
// Where the plugin is installed. `$CLAUDE_PLUGIN_ROOT` is NOT set in the shell an agent runs its
// commands in — a run that relied on it sent every agent to `/skills/...`. The caller passes the
// resolved path (the orchestrator knows it); the literal stays only as a last resort.
const PLUGIN_ROOT = A.plugin_root || '$CLAUDE_PLUGIN_ROOT'

const concepts = A.concepts || []
if (!concepts.length) throw new Error('build.js: pass it args.concepts')

const PROJECT = A.project || 'project'
// macOS ~/Movies/Reel Forge, Linux ~/Videos/Reel Forge, Windows %USERPROFILE%\Videos\Reel Forge;
// REEL_FORGE_HOME wins if it is set. Pass it already resolved in args.root.
const ROOT = A.root || '~/Movies/Reel Forge'
const VERSION = A.version || 'v1'
// The project folder holds workspace/ and facts.json. A project that predates the standard layout
// passes its own folders; otherwise they hang off <root>/<project>/ (REEL_FORGE_WORKSPACE and
// REEL_FORGE_OUTPUT, resolved by the caller, arrive the same way).
const PROJECT_DIR = A.project_dir || `${ROOT}/${PROJECT}`
const WORKSPACE = A.workspace || `${PROJECT_DIR}/workspace`
// A round is a folder straight under the project: <project>/v1, <project>/v2… each with one folder
// per concept. No "deliveries/" level in between.
const DELIVERIES = A.deliveries || `${PROJECT_DIR}/${VERSION}`
const LEDGER = `${WORKSPACE}/run.json`
const UNITS = `${WORKSPACE}/run`
const SCHEMAS = `${PLUGIN_ROOT}/schemas`
const REFS = `${PLUGIN_ROOT}/skills/reel-forge/references`
// The run ledger has no schema file of its own: its shape is written out in the orchestrator skill.
const LEDGER_DOC = `${PLUGIN_ROOT}/skills/reel-forge/SKILL.md, section "Resuming a run"`
const CATALOG = A.catalog || `${WORKSPACE}/catalog/catalog.json`
const TRENDS = A.trends || `${WORKSPACE}/trends/trends.json`
const PLATFORM = A.platform || 'tiktok'
const LANG = A.lang || 'en'
const SUBJECT = A.subject || 'the user'

// The render engine and the delivery verifier both live in the plugin's `video-engine` skill. If they
// are named differently in your installation, pass them in args instead of touching this script.
const ENGINE = A.engine || `uv run "${PLUGIN_ROOT}/skills/video-engine/scripts/render.py"`
const VERIFIER = A.verifier || `uv run "${PLUGIN_ROOT}/skills/video-engine/scripts/verify.py"`

// VARIANTS. One agent each. Used only to invent letters when a concept arrives without them.
const VAR_PER_CONCEPT = Math.max(1, A.variantsPerConcept || 2)

const REVIEWER = A.reviewer !== false
const STORY_DOCTOR = A.storyDoctor !== false
const FIX = A.fix !== false
const FRESH = A.fresh === true

// ────────────────────────────────────────────────── how many agents
//
// The concepts run through a pipeline, so these agents are NOT all alive at once; even so it is worth
// knowing the theoretical peak, because Workflow's concurrency cap is min(16, CPUs - 2) and one ffmpeg
// render already uses several cores.
function variantsOf(concept) {
  if (concept.variants && concept.variants.length) return concept.variants
  const letters = 'ABCDEFGH'.split('')
  return Array.from({ length: VAR_PER_CONCEPT }, (_, i) => ({ letter: letters[i], what: '' }))
}

const PEAK = concepts.reduce((n, c) => n + variantsOf(c).length, 0)
if (PEAK > 10) log(`${concepts.length} concepts, ${PEAK} variants = ${PEAK} builder agents in total. They are NOT all alive at once: the pipeline advances one concept at a time and the cap is min(16, CPUs - 2). A round this size is normal; what matters is that every agent keeps writing its progress file, because that is what a resume reads.`)

// ────────────────────────────────────────────────────── paths and ids

// The user's layout: <videos>/Reel Forge/<project>/<version>/<concept>/ holds ONLY the upload-ready
// files, and everything it took to make them — the README, the previews, the reports, the voice
// scripts, the shared material and each variant's build folder — lives in <concept>/resources/.
function deliveryDir(concept) { return `${DELIVERIES}/${concept.id}` }
function resourcesDir(concept) { return `${deliveryDir(concept)}/resources` }
function conceptDir(concept) { return resourcesDir(concept) }
function commonDir(concept) { return `${resourcesDir(concept)}/common` }
function variantDir(concept, v) { return `${resourcesDir(concept)}/${v.letter}` }
function deliveryFile(concept, v) { return `${deliveryDir(concept)}/${concept.id}-${v.letter}.mp4` }
function unitId(concept, v) { return `${concept.id}-${v.letter}` }
// The story-doctor's two passes, each its own unit and its own file on disk, so a resume can tell
// "the arc was never fixed" from "the arc was fixed and the build died". The paths are the ones
// `agents/story-doctor.md` declares: one file per pass, per concept.
function storyFile(concept) { return `${WORKSPACE}/story/${concept.id}.json` }
function arcFile(concept) { return `${WORKSPACE}/story/${concept.id}-post.json` }

// ────────────────────────────────────────────────────── schemas
//
// What the agents RETURN here is a report: paths, counts and verdicts. The contents of the files they
// write are governed by `schemas/`, which they read. A contract written down twice drifts.

const VARIANT = {
  type: 'object',
  properties: {
    letter: { type: 'string' },
    spec: { type: 'string', description: 'path of the spec.json' },
    builder: { type: 'string', description: 'path of the variant.json that regenerates everything from scratch (through variant.py)' },
    mp4: { type: 'string', description: 'path of the clean render, no copyrighted music' },
    preview: { type: 'string', description: 'path of the -preview.mp4 with the song, or "" if there is none' },
    light: { type: 'string', description: 'path of the 720p -light.mp4, or ""' },
    duration_s: { type: 'number' },
    duration_why: { type: 'string', description: 'the beats that add up to that length, and what you changed from the number you were given, if anything' },
    closes_on: { type: 'string', description: 'the last shot and how long it holds. "it fades out on the empty overlook, 1.2 s" — not "the last clip"' },
    cuts: { type: 'integer' },
    cuts_with_subject: { type: 'integer' },
    moments: { type: 'array', items: { type: 'string' }, description: 'catalog ids you used' },
    narrated: { type: 'boolean', description: 'true if the variant carries narration, whether or not the voice is baked in' },
    voice_script: { type: 'string', description: 'path of the voice-script.json if it is narrated, or ""' },
    voice: { type: 'string', description: 'the voice that actually spoke it. If it is not the default for the output language, say which it is here and why in `notes` — the README repeats it.' },
    voice_in_video: { type: 'boolean', description: 'true if the voice is actually audible in the mp4; false means the script ships alongside it' },
    timeline: { type: 'string', description: 'path of the <video>.timeline.json copied out beside the MP4. Without it the gate skips the text and ending checks.' },
    verify_report: { type: 'string', description: 'path of the verify.py report' },
    verify_skipped: { type: 'array', items: { type: 'string' }, description: 'criteria the gate reported as `skip` rather than `pass`. A skip is not a pass: say which ones and why.' },
    verify_pass: { type: 'boolean', description: 'true only if verify.py exited clean on the delivered file' },
    deliverable: { type: 'boolean', description: 'false if it could not be made to pass; then `notes` says why' },
    reused: { type: 'boolean', description: 'true if it was already delivered and verified in an earlier run' },
    notes: { type: 'string', description: 'decisions you took and what did not come out the way you wanted' },
  },
  required: ['letter', 'spec', 'mp4', 'duration_s', 'cuts', 'cuts_with_subject', 'verify_pass', 'deliverable'],
}

// The story-doctor's first pass. It does not return the concept back: it returns what has to change
// about it, and the seconds each variant needs. The builders receive this verbatim.
const FIX_ITEM = {
  type: 'object',
  description: 'One correction, as the story-doctor writes them: `what` is the instruction, `why` is the defect it repairs.',
  properties: {
    what: { type: 'string', description: 'the instruction a builder can apply: which shot, which second, how long it holds' },
    why: { type: 'string', description: 'the defect it repairs' },
    where: { type: 'string', description: 'the second or the range, when it is about one' },
    level: { type: 'string', enum: ['blocks', 'optional'], description: '`blocks` only for the promise left unpaid, the missing close and a broken arc' },
    variant: { type: 'string', description: 'the letter this fix belongs to, when it is not the whole concept' },
  },
  required: ['what', 'why', 'level'],
}

// The story-doctor's first pass. It does not return the concept back: it returns what has to change
// about it, and the seconds each variant needs. The builders receive this verbatim. The field names
// are the ones `agents/story-doctor.md` writes — this schema follows that agent, not the other way
// round.
const STORY = {
  type: 'object',
  properties: {
    pass: { type: 'string', enum: ['pre'] },
    concept: { type: 'string' },
    file: { type: 'string', description: 'path of the story file you wrote' },
    verdict: { type: 'string', enum: ['ship', 'rework', 'reject'], description: 'reject = the arc cannot be closed with the material that exists' },
    arc: {
      type: 'object',
      description: 'The five questions, answered with seconds and quotes. Same shape the agent writes to disk.',
      properties: {
        hook_promises: { type: 'object', description: 'ok + the promise written as the viewer would say it' },
        promise_paid_off: { type: 'object', description: 'ok + the second it is paid off at, or why it never is' },
        development: { type: 'object', description: 'ok, how many beats, the largest gap between them, and the ones that add nothing' },
        close: { type: 'object', description: 'ok, which kind of close, and why it lands — or why it only stops' },
      },
      required: ['hook_promises', 'promise_paid_off', 'development', 'close'],
    },
    duration: {
      type: 'object',
      description: 'The concept-level verdict on length. `in_beats` is what makes it defensible: "hook 3 + three proofs of 7 + close 4".',
      properties: {
        declared_s: { type: 'number' },
        recommended_s: { type: 'number' },
        in_beats: { type: 'string' },
        cut: { type: 'array', items: { type: 'object' }, description: 'stretches that hold one idea too long, each with the seconds it saves' },
        lengthen: { type: 'array', items: { type: 'object' }, description: 'beats that are starved, each with the catalog ids that would feed them' },
      },
      required: ['recommended_s', 'in_beats'],
    },
    per_variant: {
      type: 'array',
      description: 'The seconds EACH variant needs, worked out from its own beats. They must not all be the same number: a round where every variant lands between 20 and 30 s is the template talking, not the stories. A short variant keeps the whole arc and loses middle beats, never the close.',
      items: {
        type: 'object',
        properties: {
          letter: { type: 'string' },
          recommended_s: { type: 'number' },
          in_beats: { type: 'string', description: 'the beats that add up to that number' },
          keeps: { type: 'string', description: 'what this variant keeps and what it drops, relative to the full arc' },
        },
        required: ['letter', 'recommended_s', 'in_beats'],
      },
    },
    fixes: { type: 'array', items: FIX_ITEM, description: 'Binding. Every builder applies the `blocks` ones before rendering.' },
    notes: { type: 'string' },
  },
  required: ['concept', 'verdict', 'arc', 'duration', 'per_variant', 'fixes'],
}

const COMMON = {
  type: 'object',
  properties: {
    folder: { type: 'string' },
    resources: { type: 'string', description: 'path of the RESOURCES.json describing what is in the folder' },
    count: { type: 'integer', description: 'how many resources you left ready' },
    music_bed: { type: 'string', description: 'path of the already looped and normalized music bed, or ""' },
    missing: { type: 'array', items: { type: 'string' }, description: 'what the concept asks for that the material cannot give' },
    notes: { type: 'string' },
  },
  required: ['folder', 'resources', 'count'],
}

const PROBLEM = {
  type: 'object',
  properties: {
    variant: { type: 'string' },
    severity: { type: 'string', enum: ['blocks', 'important', 'minor'] },
    what: { type: 'string' },
    where: { type: 'string', description: 'the second or the range where it shows' },
    how_to_fix: { type: 'string' },
  },
  required: ['variant', 'severity', 'what', 'how_to_fix'],
}

// The story-doctor's second pass, on the rendered files. Same `problems` shape as the reviewer's, so
// both feed the one Fix stage without any translation in between.
const ARC_REVIEW = {
  type: 'object',
  properties: {
    pass: { type: 'string', enum: ['post'] },
    concept: { type: 'string' },
    file: { type: 'string', description: 'path of the post-pass file you wrote' },
    per_variant: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          letter: { type: 'string' },
          duration_s: { type: 'number' },
          develops: { type: 'boolean', description: 'every beat adds something and none of them repeats the one before' },
          lands: { type: 'boolean', description: 'it ENDS: the promise is paid and it closes on a settled shot, not mid-pan, mid-word or mid-gesture' },
          duration_fits: { type: 'boolean', description: 'the length matches the story it is telling, neither padded nor truncated' },
          verdict: { type: 'string', enum: ['ship', 'rework', 'reject'] },
          ends_on: { type: 'string', description: 'what the last frame actually is, from looking at the last 0.6 s frame by frame' },
          fixes: { type: 'array', items: FIX_ITEM, description: 'each one applicable to this variant’s variant.json' },
        },
        required: ['letter', 'develops', 'lands', 'duration_fits', 'verdict'],
      },
    },
    spread: { type: 'string', description: 'how the durations spread across the variants, and whether they all came out the same length anyway' },
    summary: { type: 'string' },
  },
  required: ['concept', 'per_variant', 'summary'],
}

const REVIEW = {
  type: 'object',
  properties: {
    approved: { type: 'array', items: { type: 'string' }, description: 'letters that pass verify.py and that you would publish' },
    not_deliverable: { type: 'array', items: { type: 'string' }, description: 'letters that cannot be fixed with the material available' },
    problems: { type: 'array', items: PROBLEM },
    comparison: { type: 'string', description: 'what changes between variants and which one you recommend' },
    readme: { type: 'string', description: 'path of the concept’s README.md' },
  },
  required: ['approved', 'problems', 'comparison'],
}

const LEDGER_SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string' },
    units: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          state: { type: 'string', enum: ['pending', 'running', 'done', 'failed'] },
          artifact: { type: 'string' },
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
    delivered: { type: 'integer' },
    pending: { type: 'integer' },
    not_deliverable: { type: 'array', items: { type: 'string' } },
  },
  required: ['file', 'delivered'],
}

// ─────────────────────────────────────────────────────────── prompts

// The progress protocol. One unit, one file, nobody else writing it. This is what survives the laptop
// closing mid-render.
function progress(id, artifact) {
  return `
PROGRESS PROTOCOL — not optional. A round of this plugin lost seven agents because the machine went to
sleep mid-run and none of them had left a trace of where they were.

- Your unit id is \`${id}\`. Your progress file is \`${UNITS}/${id}.json\` and **nobody else writes it**.
  Its shape is the \`unit\` object described in ${LEDGER_DOC}.
- Write it the moment you start (\`"state": "running"\`, the step you are on, the steps left), and
  rewrite it after every step. **Never go more than ~2 minutes without rewriting it.**
- Write to \`<file>.tmp\` and rename it into place: a half-written file must never be read back.
- **Split long work into steps that finish in under ~2 minutes**, and save what each one produced so a
  re-run never repeats it:
  · pre-renders and 360 reframes: one segment per call, each written to its own file in the folder;
  · narration: one line at a time (\`l0.wav\`, \`l1.wav\`…), and \`durations.json\` written LAST — a
    folder with WAVs and no \`durations.json\` means the batch was cut off and only the missing lines
    get regenerated;
  · the final render: if it runs past a couple of minutes, render in segments and concatenate.
- **Write every output as soon as you have it.** A render that exists on disk is a render that does not
  get redone; a render that only exists in your head dies with you.
- Last step, always: \`"state": "done"\` with the artifact's path.

If \`${artifact}\` already exists, verified and complete, read it back and stop instead of rebuilding.
`.trim()
}

// What everyone on this concept shares. It says where the rules are; it does not copy them in.
// `story` is the story-doctor's first pass, when it ran: its fixes are binding, so they DO get copied
// in — they are specific to this concept and they exist nowhere else.
function contract(concept, story) {
  return `
You are a reel-forge build agent on concept "${concept.id}" — ${concept.title}.

Hook (first seconds): ${concept.hook || '(decide it yourself and justify it)'}
Promise: ${concept.promise || '(the debt the hook takes on, and the second it is paid off at)'}
Structure: ${concept.structure || '(decide it yourself; every block carries its `role`)'}
Close: ${concept.close || '(plan it: the shot it closes on, its `kind`, and the last caption)'}
Length the concept argues for: ${concept.duration_s ? `${concept.duration_s} s` : '(from the beats)'}${concept.duration_rationale ? ` — ${concept.duration_rationale}` : ''}
Platform: ${PLATFORM} 9:16 · Output language: ${LANG}
${concept.music ? `Music: ${concept.music}` : ''}
${concept.narration ? `Narration: ${concept.narration}` : ''}
${concept.moments && concept.moments.length ? `Catalog moments assigned: ${concept.moments.join(', ')}` : ''}

${story ? `THE STORY-DOCTOR ALREADY PASSED OVER THIS CONCEPT (${storyFile(concept)}). Its verdict is
${story.verdict}, and its fixes are binding — read the file, it has the seconds and the ids.
${story.duration ? `- Length it defends, in beats: ${story.duration.recommended_s} s — ${story.duration.in_beats}` : ''}
${(story.fixes || []).filter((f) => f.level === 'blocks').length
  ? `- Apply BEFORE rendering:${story.fixes.filter((f) => f.level === 'blocks').map((f) => `\n  · ${f.what}  (${f.why})`).join('')}`
  : '- Nothing it marked as blocking.'}
${(story.fixes || []).filter((f) => f.level !== 'blocks').length
  ? `- Worth doing if the material allows:${story.fixes.filter((f) => f.level !== 'blocks').map((f) => `\n  · ${f.what}`).join('')}`
  : ''}
${story.notes ? `- It also noted: ${story.notes}` : ''}` : `No story-doctor pass ran on this concept: hold
yourself to the arc anyway — hook, promise, development, turn, close — and write in your notes what
each stage is and which seconds it gets.`}

THE ARC IS WHAT YOU ARE BUILDING. The feedback behind it, verbatim: *"something is being developed and
it gets cut too soon"*. A video that stops is not a video that ends. The stages, the five closes that
work and what makes a close fail are in ${REFS}/concepts.md — read that section before writing the
segment grid; it is not repeated here. Three things are yours at render time:
- **The promise is paid on screen**, at the second the concept says, not implied.
- **No beat repeats the one before it.** If two do, drop one and give the seconds to a beat that lands.
- **The close holds.** Never a cut in the middle of a movement, a word or a gesture, and never the last
  frame stretched. The engine's rule of thumb is 0.8-1.5 s of settled picture plus a \`fade_out\` of
  0.3-0.5; the gate's \`ending\` check warns when the file just stops.

THE DURATION COMES FROM THE STORY, not from a house default: the concept's \`duration_rationale\`
counts it in beats (*hook 3 + three proofs of 7 + turn 4 + close 3*) and the number is argued from
there. If there is more story than time it goes UP; if there is padding it goes DOWN. Every delivery
coming out between 15 and 30 s is the template talking. **A shorter variant is not the long one
truncated**: it keeps the whole arc and loses development beats, never the close.

Read before you touch anything, and follow them as written — they are not summarized here on purpose,
because a contract copied into six prompts is a contract that drifts:
- ${REFS}/editing.md — the engine, the spec, the effects, the safe area and the mistakes that already
  cost a re-render.
- ${REFS}/audio.md — diegetic sound, the music bed, per-cut volume, narration.
- ${REFS}/delivery.md — what a delivery consists of, the arc and sync checks, and the gate it has to pass.
- ${REFS}/video360.md — only if the concept uses 360 material.
- ${REFS}/editing.md and ${PLUGIN_ROOT}/examples/spec-example.json — the render spec.
- ${SCHEMAS}/voice-script.schema.json — the exact shape of a narration script. **There is one format
  and it is this one.** Several narrated videos have already shipped with no voice because each agent
  invented its own script layout and the parser silently skipped every line.
- ${SCHEMAS}/variant-build-result.schema.json — what you write to \`result.json\` before answering, and
  validate: \`uv run "${PLUGIN_ROOT}/schemas/validate.py" result.json --type variant-build-result\`.

**What is TRUE about this project** — who was there, where, when — is not in the catalog. It is in
the project's facts, which the user confirmed, and nothing you write may contradict them:
\`uv run "${PLUGIN_ROOT}/skills/sources/scripts/facts.py" --project ${PROJECT_DIR} brief\`
Run it before you write a single line. The builder checks every line and caption against them before
it renders anything, and stops if one contradicts them.

Fixed facts for this concept:
- **Every path here can contain spaces** (the default home is ".../Reel Forge/<project title>/"): quote
  every path in every shell command, always.
- The concept's folder ${deliveryDir(concept)}/ holds ONLY the upload-ready videos. Everything else —
  README, previews, light copies, reports, voice scripts, the shared material, each variant's build —
  goes in ${resourcesDir(concept)}/. Never leave another file loose next to the videos.
- Catalog: ${CATALOG} · Trends: ${TRENDS} · Common folder: ${commonDir(concept)}
- Render: ${ENGINE} <spec.json>
- Verify a delivery: ${VERIFIER} <file.mp4>
- **Every caption, stamp, narration line and hashtag goes in ${LANG}.** Not the file names, not the
  JSON keys. If a line stops working once translated (a pun, a rhyme with the beat), rewrite it so it
  lands in ${LANG} and say so in your notes.
- **Do not step outside a moment's \`start_s\`/\`end_s\` window.** If you need another one, pull the
  frame strip of the new window and LOOK at it first.
- ${SUBJECT} cannot appear in every cut: stay inside the concept's own \`subject_quota\` (${REFS}/concepts.md
  has the ceilings per kind). Count the cuts by hand.
- **Nobody redoes the shared work.** The originals, the crops, the 360 renders and the music bed are
  already in the common folder, made once. Do not re-export and do not touch another variant's folder.
`.trim()
}

// Narration and on-screen text. Two rules that only make sense together: the voice is generated FIRST
// and the text is derived FROM it. Written once here and used by the build prompt.
function voiceAndText(concept) {
  const spanish = /^es(-|$)/i.test(LANG)
  return `
THE VOICE. ${spanish
    ? `The output language is ${LANG}, so the **default voice is CapCut's Valentino** — the one the trend
uses. Generate with it:
  uv run "${PLUGIN_ROOT}/skills/voices/scripts/narrate.py" voice-script.json --engine capcut --voice "Valentino" --speed 1.4
Check it is actually available first (\`capcut_voice.py --preflight\`): it is macOS-only, it drives the
app by clicks and a saturated project stops producing WAVs in silence. **The local engines (qwen,
voxcpm, piper) are the BACKUP**, not the default: if you fall back to one, say which voice you used and
why Valentino was not available, in \`notes\` — and the concept's README says it in its own line. A
variant that quietly ships with a local voice leaves the user unable to tell why it does not sound like
the trend.`
    : `The output language is ${LANG}: use the voice the \`voices\` skill offers for that language and
region (CapCut's Valentino is the default only for Spanish output). Say in \`notes\` which voice you
used.`}

THE TEXT IS SYNCED TO WHAT IS HEARD AND WHAT IS SEEN. Tolerance: 0.25 s, and the gate measures it.
The engine already has the mechanism — ${REFS}/editing.md and the video-engine skill, section "Text that
stays in sync". **Never type a subtitle's seconds by hand**: they match on the first render and drift on
the next change of duration.

1. **Over narration → \`sync\`.** Generate the voice first, then align it and let the spec take the times
   from the voice itself:
     uv run "${PLUGIN_ROOT}/skills/video-engine/scripts/transcribe.py" --align <voice folder>/ --script voice-script.json
   writes \`alignment.json\`, and the spec carries \`"sync": {"from": "<voice folder>/alignment.json", ...}\`.
   Regenerate the alignment whenever the narration is regenerated: another take, another rhythm, and a
   stale alignment is subtitles from the previous version.
2. **Over a clip whose own audio is heard → \`subs\`** in that segment, from its transcript. Only if that
   audio is actually heard in the final mix and adds something.
3. **With no audio behind it → \`seg\`**: the text belongs to its cut and leaves with it.
4. **The other direction, which is the one nobody checks:** when the voice names something concrete — a
   place, a dish, a price, a person — declare it on the segment that shows it: \`"says": "the cathedral"\`.
   The gate reads the narration's own word times and confirms the picture was there when the word was
   said. Naming one thing over a picture of another is what makes a video feel assembled instead of told.
`.trim()
}

function storyPrompt(concept) {
  const variants = variantsOf(concept)
  return `${contract(concept, null)}

${progress(`${concept.id}-story`, storyFile(concept))}

You are the **story-doctor**, PRE pass: you are the first one to touch this concept and nothing gets
built until you have passed over it. Your method — the five questions, what counts as a close, and how
a duration is defended in beats — is your own agent definition; it is not repeated here. What this run
adds to it:

- The concept is "${concept.id}", the catalog is ${CATALOG} and the trends, if there are any, ${TRENDS}.
- **Every variant gets its own number of seconds**, in \`per_variant\`, worked out from its own beats:
  ${variants.map((v) => `${v.letter}${v.what ? ` (${v.what})` : ''}`).join(', ')}. Two variants with the
  same recommended length are one variant with two names. And each variant has to be a video a viewer
  can tell apart — another hook, another close, the voice on or off, or mostly other shots
  (\`differs_in\`); if the concept's variants only change the length or the song, fix that here, at
  \`level: "blocks"\`, naming the shot each one should open or close on. A short variant keeps the whole arc and
  loses middle beats, never the close.
- **Write the fixes as instructions a builder can apply** ("open on <id> instead of <id>", "the close is
  <id>, held 2 s, with the line <text>"), each with its \`level\`. \`blocks\` is binding: the builders
  apply those before rendering anything, and the run treats them as done.
- Every id you name **exists in the catalog**. If the shot the arc needs is not in the material, that is
  \`verdict: "reject"\` and you say which shot is missing — five agents rendering around a hole is what
  this pass exists to prevent.
- On-screen copy you propose goes in ${LANG}; the file itself is written in English.

Write ${storyFile(concept)} through a temporary and a rename before you answer. Do not render, do not
export, do not edit anybody's \`variant.json\`.`
}

function commonPrompt(concept, story) {
  const variants = variantsOf(concept)
  return `${contract(concept, story)}

${progress(`${concept.id}-common`, `${commonDir(concept)}/RESOURCES.json`)}

You prepare the SHARED material for this concept, in ${commonDir(concept)}/ , **before any variant is
built**. ${variants.length} agents are waiting on you, one per variant (${variants.map((v) => v.letter).join(', ')}),
and none of them may export, reframe or normalize anything you were supposed to leave ready.

Leave ready and verified, each one saved as you finish it:
1. The originals of the assigned moments, exported from the library into the common folder — at the
   resolution the render needs, converted to a format ffmpeg opens.
2. The prepared stills and pre-renders every variant shares: the 9:16 crops with their focus point, and
   any move the engine cannot do by itself (a rotation on entry, an animated zoom), pre-rendered at
   1350x2400. One call per piece, so a kill costs one piece.
3. The 360 reframes the concept needs, rendered from the keys \`360-scout\` left behind — one framing
   per call. These are the longest job here: write each one to its own file and record it in your
   progress before starting the next.
4. The music bed: if the video runs longer than the song's preview (~30 s), build the loop and
   normalize it, per ${REFS}/audio.md. A 35 s video with the raw preview goes silent at the end and
   nobody notices until the user watches it.
5. \`RESOURCES.json\` in the common folder, saying what each file is, which catalog id it came from and
   what it is for, so no builder has to guess. Write it last, when everything it lists exists.

If the concept asks for something the material cannot give, put it in \`missing\` rather than
improvising a substitute: the builders need to know before they plan around it.
Do not build any variant and do not write into any variant's folder. That is the next step.`
}

function buildPrompt(concept, common, v, story) {
  const plan = story && (story.per_variant || []).find((p) => p.letter === v.letter)
  const mine = story ? (story.fixes || []).filter((f) => f.level === 'blocks' && (!f.variant || f.variant === v.letter)) : []
  return `${contract(concept, story)}

${voiceAndText(concept)}

${progress(unitId(concept, v), deliveryFile(concept, v))}

You build **variant ${v.letter}, and only variant ${v.letter}**: ${v.what || '(the axis is yours to pick; it must be noticeably different from the other variants of this concept — duration, with or without voice, hook order, music versus natural sound)'}

${mine.length ? `The story-doctor's blocking fixes that are yours to apply:${mine.map((f) => `\n  · ${f.what}`).join('')}\n` : ''}
Length of THIS variant: ${plan
    ? `**${plan.recommended_s} s**, set by the story-doctor — ${plan.in_beats}${plan.keeps ? `. It keeps: ${plan.keeps}` : ''}. Land inside ±10 % of it.
   If while building you find the story needs more or fewer seconds, change it and **write down why**;
   what you may not do is pad it with a beat that adds nothing, or cut the close to hit a number.`
    : v.duration_s
      ? `**${v.duration_s} s**, from the concept. Land inside ±10 %, and say in \`notes\` if the story needed another length.`
      : `you work it out from the beats (see THE ARC above) and you write in \`notes\` how you got to
   the number. Do not default to 20-30 s because that is what the last round did.`}

The shared material is already in ${commonDir(concept)}/ ${common && common.count ? `(${common.count} resources, listed in ${common.resources})` : '(read RESOURCES.json before assuming anything is missing)'}.
${common && common.music_bed ? `Music bed, already looped and normalized: ${common.music_bed}` : ''}
${common && common.missing && common.missing.length ? `What the common step could NOT provide: ${common.missing.join('; ')}` : ''}

Your folder is ${variantDir(concept, v)}/ and nothing outside it is yours to write, except your own
files in the delivery folder.

The order of the steps is not decoration: **the voice comes before the text**, because the text is
derived from it. Each step is short enough to finish inside the 2-minute rule and is saved before the
next one starts.

1. **You do not write a build script.** Write \`variant.json\` in your folder and run the shared
   builder, which does the rest the same way for every variant:
   \`uv run "${PLUGIN_ROOT}/skills/video-engine/scripts/variant.py" variant.json --plan\` first
   (it prints every cut in seconds AND in beats — look at it), then without \`--plan\`. Its shape is in
   the docstring of that file (\`sed -n 1,80p\`). Lay the shots out as the arc, hook to close. When
   the concept has a song with a BPM, every shot holds a whole number of \`beats\` — the builder lands
   every cut on the beat and the first shot absorbs the song's intro; that is the default and it is
   the point. Name the sound under each shot (\`audio\`: its own track, \`from\` a scene's clip for a
   photo, or \`continue\`). Write \`"project": "${PROJECT_DIR}"\` so the facts get checked.
2. **If the variant is narrated**, write \`voice-script.json\` in the one format
   (${SCHEMAS}/voice-script.schema.json), prove it parses
   (\`uv run "${PLUGIN_ROOT}/skills/voices/scripts/narrate.py" voice-script.json --parse-only\`
   prints as many lines as you wrote), and give each narrated shot its \`line\`. The builder generates
   the voice (the default one THE VOICE section names; the local one if it is not available, with the
   reason recorded), aligns it word by word, and takes the captions from it — nobody types seconds.
3. **What the builder does, in order**: voice, grid, alignment, natural sound, the preview's music
   bed, **the project's facts against every line and caption BEFORE anything renders** (exit 4: a line
   contradicts what the user told us — rewrite the line), render, the 720p copies, the gate
   (\`verify.py\` with \`--spec\` and \`--script\`), and \`framecheck.py\` over every rendered cut. It
   writes the upload-ready file to ${deliveryDir(concept)}/ and every sidecar to ${resourcesDir(concept)}/, and \`build.json\` in your
   folder. It holds a lock (exit 3 means another build of your letter is running) and skips a delivery
   that is already up to date.
4. Pull an \`fps=2,tile=12x6\` strip of the result and **look at it with Read**: captions readable and
   wrapped where you meant, landing on the word being said, nothing covering a face, no crop cutting off
   a head, dates and places correct. Look at the **last** second especially: it has to end, not stop.
5. **Exit 1 is the gate failing**: the verify JSON beside the MP4 says why; fix it in \`variant.json\`
   and run it again, never by patching the MP4. **\`framecheck_flagged\` in \`build.json\`** means a
   cut has something between the lens and the subject: replace or reframe it, or argue for it in
   \`notes\`. If it cannot be made to pass with the material that exists, set \`deliverable: false\`,
   leave \`verify_pass: false\` and explain in \`notes\` — an unverified file is never quietly
   delivered.
6. Anything the builder cannot express (a pre-render, an effect it lacks) is done in \`common/\` and a
   shot points at the file. Do not fork the builder.
7. Write \`result.json\` in your folder against ${SCHEMAS}/variant-build-result.schema.json, validate it
   and only then answer.

If the machine has no usable voice engine at all, ship the variant without voice, keep
\`voice-script.json\` next to the MP4, set \`voice_in_video: false\` and say so — a narrated variant
delivered mute with nothing said about it is a defect.

Do not write the concept's README: the reviewer writes one for all the variants.`
}

function reusePrompt(concept, v) {
  return `Variant ${v.letter} of reel-forge concept "${concept.id}" was already built and verified in an
earlier run. Do NOT rebuild it.

1. Check ${deliveryFile(concept, v)} exists, and re-run the gate on it: ${VERIFIER} ${deliveryFile(concept, v)}
2. Read ${variantDir(concept, v)}/notes.md and its spec for the counts (duration, cuts, cuts with the
   subject, whether it is narrated and whether the voice is audible).
3. Return the report with \`"reused": true\`.

If the file is missing or the gate fails, return \`"deliverable": false\` with the reason: the run will
treat the variant as pending instead of shipping something nobody checked.`
}

function arcPrompt(concept, variants, story) {
  return `You are the **story-doctor**, POST pass, on the rendered variants of reel-forge concept
"${concept.id}" (${concept.title}). The critic-reviewer is checking the craft at the same time; you are
checking whether these are **finished videos**. Your method — the strip, the last four seconds, the last
0.6 s frame by frame, and what an ending that stops looks like — is your own agent definition and is not
repeated here.

${progress(`${concept.id}-arc`, arcFile(concept))}

Variants:
${variants.map((v) => `- ${v.letter}: ${v.mp4} — ${v.duration_s} s, ${v.cuts} cuts${v.narrated ? ', narrated' : ''}`).join('\n')}
${story ? `What you asked for before it was built: ${storyFile(concept)}${story.duration ? ` (you defended ${story.duration.recommended_s} s — ${story.duration.in_beats})` : ''}.` : ''}

What this run adds to your method:

- Answer **per variant**, with \`lands\`, \`develops\` and \`duration_fits\` as booleans you can defend,
  and \`ends_on\` saying what the last frame actually is. A variant that ends on a cut with motion still
  in it gets a fix at \`level: "blocks"\` — that is the defect this whole round was sent back for.
- **Compare the set as a viewer would**:
  \`uv run "${PLUGIN_ROOT}/skills/video-engine/scripts/compare_variants.py" "${deliveryDir(concept)}"\`
  measures the rendered variants frame by frame. A pair that fails it — same hook, same close, same
  voice, most shots alike — is a fix at \`level: "blocks"\`: a round once shipped five such pairs and
  the user watched each twice and saw the same video. The fix names what that variant should open or
  close on instead. Length alone is not a difference; another song is not either (the uploads carry
  none).
- Each fix is applicable to that variant's \`variant.json\`: which shot, which second, how long it holds.
  A close that has to be extended is extended **with material**, never by freezing the last frame.
- Do not re-render anything and do not edit anybody's \`variant.json\`: the Fix stage applies what you and
  the reviewer found, in one pass, so two agents never correct the same variant in opposite directions.

Write ${arcFile(concept)} through a temporary and a rename before you answer.`
}

function reviewPrompt(concept, variants) {
  return `Review ALL the variants of reel-forge concept "${concept.id}" (${concept.title}).
Each was built by a different agent, so the typical mistake is not inside one variant but BETWEEN them.

${progress(`${concept.id}-review`, `${resourcesDir(concept)}/README.md`)}

Variants:
${variants.map((v) => `- ${v.letter}: ${v.mp4} (${v.duration_s} s${v.duration_why ? ` — ${v.duration_why}` : ''}, ${v.cuts} cuts, ${v.cuts_with_subject} with the subject, verify ${v.verify_pass ? 'passed' : 'FAILED'}${(v.verify_skipped || []).length ? ` with ${v.verify_skipped.join(', ')} SKIPPED` : ''}${v.narrated ? `, narrated with ${v.voice || 'an unnamed voice'} — voice in the file: ${v.voice_in_video ? 'yes' : 'NO'}` : ''})\n  spec: ${v.spec}`).join('\n')}

The checklist is in ${REFS}/delivery.md — run it as written, do not re-derive it. Write your findings to
${conceptDir(concept)}/review.json against ${SCHEMAS}/review-result.schema.json and validate it before
answering. On top of the checklist, the five things that only exist at this level:

1. **Compare the SAME frame between variants.** One builder left a \`look\` that washed out the hook in
   two of four deliveries and nobody saw it, because everyone only reviewed their own.
2. **Re-run the gate yourself on every delivered file**, with everything it can check:
   \`${VERIFIER} <file.mp4> --spec <its spec.json> [--script voice-script.json]\` — with the
   \`<file>.timeline.json\` sidecar in place, or the text and ending checks silently skip.
   Take nobody's word for it, the builder's included. A variant that does not pass is not delivered:
   either you fix it (inside its \`variant.json\`, then re-render) or you mark it \`not_deliverable\` and
   **say so in the concept's README**, with what was missing. A file that quietly ships unverified is
   the worst outcome available here.
3. **Narration.** For every variant marked narrated: the voice has to be audible in the MP4, or the
   \`voice-script.json\` has to be next to it, parse cleanly
   (\`narrate.py voice-script.json --parse-only\`, same number of lines as the script) and be named in
   the README. Narrated videos have already shipped silent because the script was written in a shape
   the parser skips. **Say which voice was used**, and if it is not the default one for ${LANG}, the
   README says so in its own line.
4. **Text against sound and picture.** The gate measures it (\`text_sync\`, \`voice_image\`); you confirm
   it by ear on three captions per variant, because a skipped check looks exactly like a passed one.
   Check the report says \`pass\`, not \`skip\`: a missing timeline sidecar skips them both. Text that
   drifts is the defect the viewer feels without being able to name it.
5. That two variants do not read the same: if they use the same shots in the same order with different
   copy, one is redundant and you say which. Two variants that also came out the same length are one
   variant.

Write ONE README.md for the concept in ${resourcesDir(concept)}/ (never loose in the concept's folder: that one holds only the upload-ready videos), in ${LANG}, following the structure in
${REFS}/delivery.md: the variants with **their duration and why it is that length**, what changes
between them, which one you recommend, the cut counts, which voice each narrated variant used, the
verification result of each one and, plainly, anything that could not be delivered and why. Not one
README per agent.

Mark \`severity: "blocks"\` only on what makes delivery impossible.`
}

function fixPrompt(concept, problems) {
  return `Fix what is blocking delivery of reel-forge concept "${concept.id}". Do not redesign: correct
exactly this and re-render the affected variants.

${progress(`${concept.id}-fix`, `${resourcesDir(concept)}/README.md`)}

${problems.map((p) => `- [${p.variant}] ${p.what}${p.where ? ` (${p.where})` : ''}\n  Fix proposed by ${p.from || 'the reviewer'}: ${p.how_to_fix}`).join('\n')}

Rules:
- The correction goes INSIDE the variant's \`variant.json\`, not by hand on the MP4.
- One fix at a time, re-render, measure again. Two fixes at once hide which one failed.
- **A close that has to be extended is extended with material, not with a freeze**: hold the closing
  shot, or add the beat the story-doctor named. Stretching the last frame reads as a bug.
- **If the narration changes, the alignment is regenerated** (\`transcribe.py --align\`) before
  re-rendering: a stale \`alignment.json\` gives subtitles timed to a voice that no longer exists.
- **Re-run the gate on every variant you touched**, with \`--spec\` and, when it is narrated,
  \`--script\`, and with the timeline sidecar beside the MP4. A fixed variant that does not pass is not
  fixed, and one whose checks came back \`skip\` was not checked.
- If a fix needs material that does not exist, do not invent it: return the variant with
  \`deliverable: false\` and the reason, and update the concept's README to say so.
- Update the concept's README with what was corrected.
Return the corrected variants, with their new paths, counts and verify results.`
}

// ───────────────────────────────────────────────────────────── the run

log(`${concepts.length} concepts · ${PEAK} variants, one agent each · delivery ${VERSION} · language ${LANG}`)

// ── Resume. Before building anything: what already exists, rendered and verified?
phase('Resume')

const allVariants = concepts.flatMap((c) => variantsOf(c).map((v) => ({ concept: c, v })))

const ledger = FRESH ? null : await agent(
  `Read the reel-forge run ledger for project "${PROJECT}" and report what is already delivered.

1. Read ${LEDGER} if it exists, and every file in ${UNITS}/.
2. Read what is actually in ${DELIVERIES}/ and in ${WORKSPACE}/concepts/. **Disk wins over the
   ledger**: a delivered MP4 that passes the gate is done even if the ledger never got updated, and a
   ledger entry with no file behind it is not done.
3. For each of these units, return its state:
${concepts.map((c) => `   - ${c.id}-story → ${storyFile(c)}`).join('\n')}
${concepts.map((c) => `   - ${c.id}-common → ${commonDir(c)}/RESOURCES.json`).join('\n')}
${allVariants.map(({ concept, v }) => `   - ${unitId(concept, v)} → ${deliveryFile(concept, v)}`).join('\n')}
4. A variant counts as \`done\` ONLY if its MP4 exists AND \`${VERIFIER} <file>\` passes on it. Run the
   verifier; do not assume. A file that exists but fails the gate is \`pending\`, because it cannot be
   delivered as it stands.
5. Update ${LEDGER} with what you found, following the shape in ${LEDGER_DOC}, through a temporary and
   a rename.

Do not build, render or fix anything. This is bookkeeping only.`,
  { label: 'Read the ledger', phase: 'Resume', schema: LEDGER_SCHEMA, effort: 'low' },
)

const doneUnits = new Set(
  ((ledger && ledger.units) || []).filter((u) => u.state === 'done').map((u) => u.id),
)
if (doneUnits.size) log(`Resuming: ${doneUnits.size} unit(s) already finished on disk — ${[...doneUnits].join(', ')}`)

phase('Story')

// pipeline: each concept advances on its own. Concept 1 can be in review while concept 3 is still
// exporting originals; a barrier between phases would leave the fast builders waiting.
// The one barrier that genuinely is needed is local to a concept: its variants have to finish before
// its reviewer can compare them, and that is a parallel() INSIDE a stage, not between stages.
const results = await pipeline(
  concepts,

  // 1. The story-doctor, BEFORE anything is exported or rendered. It is the cheapest agent in the
  //    pipeline and the one that decides whether the other five were worth launching: a concept with
  //    no close produces four variants that all stop instead of ending.
  //    It always returns an object, never null: a story-doctor that dies must not take the concept
  //    with it — the builders can still build, they just build without its notes and say so.
  async (_prev, concept) => {
    if (!STORY_DOCTOR) return { story: null }
    const story = await (doneUnits.has(`${concept.id}-story`)
      ? agent(
        `The story-doctor already passed over reel-forge concept "${concept.id}" in an earlier run.
Read ${storyFile(concept)} and return exactly what it says: the arc, the duration of each variant with
the beats behind it, and the fixes with their levels. Do NOT re-plan the concept and do not change any
number — the variants already built used these. If the file is missing or does not parse, say so with
\`verdict: "rework"\` and empty \`fixes\`, and the run will redo the pass.`,
        { label: `Reuse story ${concept.id}`, phase: 'Story', schema: STORY, effort: 'low' },
      )
      : agent(storyPrompt(concept), { label: `Story ${concept.id}`, phase: 'Story', schema: STORY }))
    if (!story) log(`${concept.id}: the story-doctor returned nothing. The variants get built without its arc notes — re-run to get the pass done before delivering.`)
    return { story }
  },

  // 2. The shared work, ONCE per concept, before anybody builds.
  async ({ story }, concept) => {
    if (story && (story.verdict === 'reject' || story.verdict === 'rework')) {
      log(`${concept.id}: story-doctor verdict "${story.verdict}" — ${story.notes || `see ${storyFile(concept)}`}. It gets built with its fixes applied, but a "reject" means the payoff is not in the material: expect it to come back as not deliverable rather than as a good video.`)
    }
    const common = doneUnits.has(`${concept.id}-common`)
      ? await agent(
        `The shared material for reel-forge concept "${concept.id}" was already prepared in an earlier
run, in ${commonDir(concept)}/ . Read its RESOURCES.json, check that every file it lists still exists,
and return the report. Do not re-export, re-render or normalize anything. If files are missing, list
them in \`missing\` so the builders know.`,
        { label: `Reuse common ${concept.id}`, phase: 'Common', schema: COMMON, effort: 'low' },
      )
      : await agent(commonPrompt(concept, story), { label: `Common ${concept.id}`, phase: 'Common', schema: COMMON })
    return { story, common }
  },

  // 3. One agent per variant, all of them in parallel, each owning one letter.
  async ({ story, common }, concept) => {
    const mine = variantsOf(concept)
    const built = await parallel(mine.map((v) => () => agent(
      doneUnits.has(unitId(concept, v)) ? reusePrompt(concept, v) : buildPrompt(concept, common, v, story),
      {
        label: `${concept.id} ${v.letter}${doneUnits.has(unitId(concept, v)) ? ' (reused)' : ''}`,
        phase: 'Build',
        schema: VARIANT,
      },
    )))
    const variants = built.filter(Boolean)
    const fallen = mine.filter((_, i) => !built[i]).map((v) => v.letter)
    if (fallen.length) log(`${concept.id}: no result for variant(s) ${fallen.join(', ')} — re-run to pick them up; everything delivered is reused from disk`)
    if (!variants.length) throw new Error(`${concept.id}: not a single variant got built`)
    return { story, common, variants, fallen }
  },

  // 4. Two reviews of the same set, at once and independent: the story-doctor asks whether these are
  //    finished videos, the reviewer whether they are well made. They look for different defects, and
  //    running them in sequence only made the concept wait.
  async (built, concept) => {
    const [arc, review] = await parallel([
      () => (STORY_DOCTOR
        ? agent(arcPrompt(concept, built.variants, built.story), {
          label: `Arc ${concept.id}`, phase: 'Arc', schema: ARC_REVIEW,
        })
        : null),
      () => (REVIEWER
        ? agent(reviewPrompt(concept, built.variants), {
          label: `Review ${concept.id}`, phase: 'Review', schema: REVIEW,
        })
        : null),
    ])
    const stops = ((arc && arc.per_variant) || []).filter((pv) => pv.lands === false).map((pv) => pv.letter)
    if (stops.length) log(`${concept.id}: variant(s) ${stops.join(', ')} stop instead of ending — that is what the Fix stage is for`)
    return { ...built, arc, review }
  },

  // 5. Fixing. Paid for only when something blocks — and a variant that fails the gate always blocks.
  async (reviewed, concept) => {
    const fromReview = ((reviewed.review && reviewed.review.problems) || [])
      .filter((p) => p.severity === 'blocks')
      .map((p) => ({ ...p, from: 'the reviewer' }))
    // The story-doctor writes `fixes` per variant, with `what` as the instruction and `why` as the
    // defect. Translated here into the one shape the Fix stage reads, so the agent never has to know
    // about this script's internals.
    const fromArc = ((reviewed.arc && reviewed.arc.per_variant) || []).flatMap((pv) =>
      (pv.fixes || [])
        .filter((f) => f.level === 'blocks')
        .map((f) => ({
          variant: f.variant || pv.letter,
          severity: 'blocks',
          what: f.why || f.what,
          where: f.where || (pv.duration_s ? `ends at ${pv.duration_s} s${pv.ends_on ? ` on ${pv.ends_on}` : ''}` : ''),
          how_to_fix: f.what,
          from: 'the story-doctor',
        })))
    const failedGate = reviewed.variants
      .filter((v) => !v.verify_pass && v.deliverable !== false)
      .map((v) => ({
        variant: v.letter,
        severity: 'blocks',
        what: 'it does not pass the delivery gate (verify.py)',
        where: v.verify_report || v.mp4,
        how_to_fix: 'read the verifier report, fix it inside variant.json, re-render and re-run the gate',
        from: 'the gate',
      }))
    const blockers = [...fromArc, ...fromReview, ...failedGate]

    if (!FIX || !blockers.length) {
      return { concept: concept.id, title: concept.title, ...reviewed, fixed: false }
    }
    log(`${concept.id}: ${blockers.length} blocking problem(s), fixing`)
    const repair = await agent(fixPrompt(concept, blockers), {
      label: `Fix ${concept.id}`, phase: 'Fix',
      schema: { type: 'object', properties: { variants: { type: 'array', items: VARIANT }, what_changed: { type: 'string' } }, required: ['variants'] },
    })
    return {
      concept: concept.id, title: concept.title, ...reviewed,
      variants: (repair && repair.variants.length) ? repair.variants : reviewed.variants,
      fixed: true, what_changed: repair && repair.what_changed,
    }
  },
)

const ok = results.filter(Boolean)
const failed = concepts.filter((_, i) => !results[i]).map((c) => c.id)
if (failed.length) log(`Concepts with no delivery: ${failed.join(', ')}`)

// Nothing ships that did not pass the gate. This is counted here, not asserted by an agent.
const delivered = ok.flatMap((c) => c.variants.filter((v) => v.verify_pass && v.deliverable !== false).map((v) => `${c.concept}-${v.letter}`))
const blocked = ok.flatMap((c) => c.variants.filter((v) => !v.verify_pass || v.deliverable === false).map((v) => `${c.concept}-${v.letter}`))
if (blocked.length) log(`NOT delivered (did not pass verify.py): ${blocked.join(', ')} — each one is stated in its concept's README`)

// A gate that skipped its text and ending checks is not a gate that passed them. This is the one
// failure mode that looks identical to success in a report nobody reads line by line.
const skipped = ok.flatMap((c) => c.variants.filter((v) => (v.verify_skipped || []).length).map((v) => `${c.concept}-${v.letter} (${v.verify_skipped.join(', ')})`))
if (skipped.length) log(`Gate checks SKIPPED, not passed: ${skipped.join(' · ')} — usually a missing <video>.timeline.json beside the MP4. Fix the sidecar and re-run the gate before calling any of these delivered.`)

// The durations of the round, together. The whole point of letting the story set the length is that
// they should NOT all come out the same; if they did, it is worth saying out loud rather than
// discovering it when the user watches four videos that feel identical.
const durations = ok.flatMap((c) => c.variants.map((v) => v.duration_s)).filter((d) => typeof d === 'number')
if (durations.length > 1) {
  const lo = Math.min(...durations)
  const hi = Math.max(...durations)
  log(`Durations: ${lo.toFixed(1)}-${hi.toFixed(1)} s across ${durations.length} variants` +
      (hi - lo < 10 ? ' — everything landed inside a 10 s band. That is the template talking, not the stories: worth a round where the long concepts are allowed to run long.' : ''))
}

phase('Checkpoint')

await agent(
  `Update the reel-forge run ledger for project "${PROJECT}", delivery ${VERSION}.

Read every file in ${UNITS}/ and what is actually in ${DELIVERIES}/, and rewrite ${LEDGER} to match
disk, following the shape in ${LEDGER_DOC}. Use a temporary and a rename.

Delivered and verified this run: ${delivered.length ? delivered.join(', ') : 'none'}.
Built but NOT deliverable: ${blocked.length ? blocked.join(', ') : 'none'}.
Concepts with nothing delivered: ${failed.length ? failed.join(', ') : 'none'}.

Mark the phase \`build\` as \`done\` only if every variant of every concept is delivered and verified;
otherwise leave it \`running\` with the pending units listed, so the next run picks up exactly those.
Each concept also has a \`<id>-story\` unit (its \`story.json\`, the arc and the per-variant durations)
and a \`<id>-arc\` unit (the post-render pass): mark them \`done\` only where the file exists on disk, so
a re-run does not re-plan an arc the delivered variants were already built from.
Check, too, that every concept with a blocked variant has it written in its README — if one does not,
say so in the summary. Do not render or fix anything yourself.`,
  { label: 'Checkpoint', phase: 'Checkpoint', schema: CHECKPOINT, effort: 'low' },
)

return {
  project: PROJECT,
  deliveries: DELIVERIES,
  ledger: LEDGER,
  lang: LANG,
  concepts: ok,
  failed_concepts: failed,
  delivered,
  not_deliverable: blocked,
  total_variants: ok.reduce((n, c) => n + c.variants.length, 0),
  durations_s: durations.length ? { min: Math.min(...durations), max: Math.max(...durations), all: durations } : null,
  gate_checks_skipped: skipped,
  resume_hint: (failed.length || blocked.length)
    ? 'Re-run this same workflow to pick up what is pending: every variant already delivered and verified is read back from disk instead of being rebuilt.'
    : 'Nothing pending.',
}
