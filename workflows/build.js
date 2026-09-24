// Building concepts — reel-forge
//
// Takes already decided concepts and builds each one with 2 builder agents (the variants split
// between them) plus a reviewer that sees ALL the variants together.
//
// Run with Claude Code's Workflow tool:
//   Workflow({ scriptPath: "<plugin>/workflows/build.js", args: { ... } })
//
// args:
//   concepts              [{ id, title, hook, structure, duration_s, music, narration,
//                            variants: [{ letter: "A", what: "silent, 35 s" }, ...],
//                            moments: ["d3-07", "v2-11", ...] }]     ← catalog ids
//   project, root         where the project lives (see catalog.js)
//   version               delivery round, default "v1" (the previous one is never overwritten)
//   agentsPerConcept      default 2
//   variantsPerConcept    default 2 (one per builder)
//   reviewer              default true
//   fix                   default true: if the reviewer finds something blocking, it gets fixed
//   engine                render engine command (default: the video-engine skill's)
//   catalog               path of catalog.json (default: <workspace>/catalog/catalog.json)
//   trends                path of trends.json, if the trends phase left one
//   platform, lang, subject
//
// Same as catalog.js: every agent leaves its work on disk (build.py, spec.json, notes.md) before
// answering, so an interruption doesn't throw away the render. To resume the whole run:
// Workflow({ scriptPath, resumeFromRunId: "<runId>" }).

export const meta = {
  name: 'reel-forge-build',
  description: 'Builds each concept with 2 agents (variants split between them) and a reviewer that compares them',
  whenToUse: 'The catalog, the trends and the concepts are decided, and it is time to render each concept’s variants.',
  phases: [
    { title: 'Common', detail: 'one agent per concept prepares the shared work: crops, music bed, originals' },
    { title: 'Build', detail: '2 agents per concept, each with its own variants' },
    { title: 'Review', detail: '1 reviewer per concept: sees every variant together and compares the same frame' },
    { title: 'Fix', detail: 'only if the reviewer found something that blocks delivery' },
  ],
}

// ─────────────────────────────────────────────────────────────── inputs

const A = args || {}
const concepts = A.concepts || []
if (!concepts.length) throw new Error('build.js: pass it args.concepts')

const PROJECT = A.project || 'project'
// macOS ~/Movies/reel-forge, Linux ~/Videos/reel-forge, Windows %USERPROFILE%\Videos\reel-forge;
// REEL_FORGE_HOME wins if it is set. Pass it already resolved in args.root.
const ROOT = A.root || '~/Movies/reel-forge'
const VERSION = A.version || 'v1'
const WORKSPACE = `${ROOT}/${PROJECT}/workspace`
const DELIVERIES = `${ROOT}/${PROJECT}/deliveries/${VERSION}`
const CATALOG = A.catalog || `${WORKSPACE}/catalog/catalog.json`
const TRENDS = A.trends || `${WORKSPACE}/trends/trends.json`
const PLATFORM = A.platform || 'tiktok'
const LANG = A.lang || 'en'
const SUBJECT = A.subject || 'the user'

// The render engine lives in the plugin's `video-engine` skill. If the file is named differently in
// your installation, pass it in args.engine instead of touching this script.
const ENGINE = A.engine || 'uv run "$CLAUDE_PLUGIN_ROOT/skills/video-engine/scripts/render.py"'

// ────────────────────────────────────────────────── how many agents
//
// BUILDERS PER CONCEPT: 2, and that is deliberate.
//   1 agent with 4 variants copies itself: it changes the copy and keeps the same edit.
//   2 independent agents genuinely diverge (that is where the proposals that do not look alike come from).
//   3 or more and they each start redoing the shared work (crops, music bed) and saturating the machine:
//   Workflow's concurrency cap is min(16, CPUs - 2) and one ffmpeg render already uses several cores.
const AG_PER_CONCEPT = Math.max(1, A.agentsPerConcept || 2)

// VARIANTS: one per builder by default. Each variant is a spec + a render + a review, several minutes
// of machine time; more than 2 per agent and the last render ships without anyone having looked at it.
const VAR_PER_CONCEPT = Math.max(1, A.variantsPerConcept || AG_PER_CONCEPT)

const REVIEWER = A.reviewer !== false
const FIX = A.fix !== false

// The concepts run through a pipeline, so these agents are NOT all alive at once; even so it is worth
// knowing the theoretical peak so you do not ask for 8 concepts in a single run.
const PEAK = concepts.length * AG_PER_CONCEPT
if (PEAK > 10) log(`Warning: ${concepts.length} concepts × ${AG_PER_CONCEPT} builders = ${PEAK} agents. Past ~10 simultaneous the machine saturates; the pipeline queues them, but consider splitting the round.`)

// ────────────────────────────────────────────────────── schemas

const VARIANT = {
  type: 'object',
  properties: {
    letter: { type: 'string' },
    spec: { type: 'string', description: 'path of the spec.json' },
    builder: { type: 'string', description: 'path of the build.py that regenerates everything from scratch' },
    mp4: { type: 'string', description: 'path of the clean render, no copyrighted music' },
    preview: { type: 'string', description: 'path of the -preview.mp4 with the song, or "" if there is none' },
    duration_s: { type: 'number' },
    cuts: { type: 'integer' },
    cuts_with_subject: { type: 'integer' },
    moments: { type: 'array', items: { type: 'string' }, description: 'catalog ids you used' },
    voice_script: { type: 'string', description: 'path of voice-script.md if it is narrated, or ""' },
    notes: { type: 'string', description: 'decisions you took and what did not come out the way you wanted' },
  },
  required: ['letter', 'spec', 'mp4', 'duration_s', 'cuts', 'cuts_with_subject'],
}

const COMMON = {
  type: 'object',
  properties: {
    folder: { type: 'string' },
    resources: {
      type: 'array',
      description: 'what you left ready for both variants',
      items: {
        type: 'object',
        properties: { path: { type: 'string' }, what: { type: 'string' } },
        required: ['path', 'what'],
      },
    },
    music_bed: { type: 'string', description: 'path of the already looped and normalized music bed, or ""' },
    notes: { type: 'string' },
  },
  required: ['folder', 'resources'],
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

const REVIEW = {
  type: 'object',
  properties: {
    approved: { type: 'array', items: { type: 'string' } },
    problems: { type: 'array', items: PROBLEM },
    comparison: { type: 'string', description: 'what changes between variants and which one you recommend' },
    readme: { type: 'string', description: 'path of the concept’s README.md' },
  },
  required: ['approved', 'problems', 'comparison'],
}

// ──────────────────────────────────────────────── splitting the variants

// If the concept carries no written variants, letters get invented and the builder decides the axis
// (silent/narrated, long/short, b-roll/subject). What is NOT left to chance is the split: round-robin,
// so that if one builder crashes you do not lose a contiguous half of the range (with A,B on one and
// C,D on the other, losing the second one leaves you with no short variant at all).
function variantsOf(concept) {
  if (concept.variants && concept.variants.length) return concept.variants
  const letters = 'ABCDEFGH'.split('')
  return Array.from({ length: VAR_PER_CONCEPT }, (_, i) => ({ letter: letters[i], what: '' }))
}

function roundRobin(variants, nAgents) {
  const teams = Array.from({ length: Math.min(nAgents, variants.length) }, () => [])
  variants.forEach((v, i) => teams[i % teams.length].push(v))
  return teams
}

// ─────────────────────────────────────────────────────────── prompts

function contract(concept) {
  return `
You are a reel-forge builder agent. You build variants of ONE concept, already decided.

CONCEPT "${concept.id}" — ${concept.title}
Hook (first second): ${concept.hook || '(decide it yourself and justify it)'}
Structure: ${concept.structure || '(decide it yourself)'}
Target duration: ${concept.duration_s || 30} s · Platform: ${PLATFORM} 9:16 · Output language: ${LANG}
${concept.music ? `Music: ${concept.music}` : ''}
${concept.narration ? `Narration: ${concept.narration}` : ''}
${concept.moments && concept.moments.length ? `Catalog moments assigned: ${concept.moments.join(', ')}` : ''}

Contracts and limits (they are in the \`reel-forge\` skill and in the \`video-engine\`, \`voices\` and
\`video-360\` ones):
- Catalog: ${CATALOG}. Trends: ${TRENDS}.
- **Every caption, stamp, narration line and hashtag goes in ${LANG}.** Not the file names and not the
  JSON keys. If a line stops working once translated (a pun, a rhyme with the beat), rewrite it so it
  lands in ${LANG} and say so in your notes.
- **Do not step outside a moment's \`start_s\`/\`end_s\` window.** If you need another one, pull the frame
  strip of the new window and LOOK at it before using it; otherwise you end up with a stranger's face
  against the lens instead of what the catalog promised.
- ${SUBJECT} cannot appear in every cut: half or fewer (14-35 % is what has worked). Count the cuts by
  hand and put it in \`cuts\` and \`cuts_with_subject\`.
- The SHARED work is already done in the concept's common folder (9:16 crops, music bed, exported
  originals). Use it, do not redo it: when each agent did it on its own, one used the raw track and the
  last seconds of its video came out silent.
- Everything reproducible: leave a \`build.py\` that regenerates the spec and the pre-renders from
  scratch. Never leave a spec pointing at a temporary you already deleted.
- Render: ${ENGINE} <spec.json>. A commented example of the spec format is in
  \`$CLAUDE_PLUGIN_ROOT/examples/spec-example.json\`; use \`"crf": 22\` for 1080p deliveries.
- Verify BEFORE answering: \`blackdetect\`, \`silencedetect=n=-45dB:d=0.25\`,
  \`loudnorm=print_format=summary\` (peak below -0.5 dBTP) and an \`fps=2,tile=12x6\` strip of the render.
  Look at the frames of every caption: the engine wraps by width, a hand-written \`\\n\` is not enough and
  an orphan word looks terrible on a frozen frame.
`.trim()
}

function commonPrompt(concept) {
  return `Prepare the SHARED work for reel-forge concept "${concept.id}" (${concept.title}), before the
builders come in. Folder: ${WORKSPACE}/concepts/${concept.id}/common/

${contract(concept)}

Leave ready and verified:
1. The originals of the assigned moments, exported from the library into the common folder.
2. The 9:16 crops and the pre-renders the variants are going to share (a zoom, a rotation on entry: the
   engine does not rotate, that gets pre-rendered separately).
3. The music bed: if the video runs longer than the song's preview (~30 s), build the loop with
   \`acrossfade\` and normalize it. A 35 s video with the raw preview goes silent at the end and nobody
   notices until the user watches it.
4. A \`RESOURCES.json\` saying what each file is, so the builders do not have to guess.
Do not build any variant: that is the next step.`
}

function buildPrompt(concept, common, myVariants, iAgent) {
  return `${contract(concept)}

You are builder ${iAgent + 1} on this concept. These variants are yours:
${myVariants.map((v) => `- ${v.letter}: ${v.what || '(the axis is yours to pick; make sure it does NOT resemble the other builder’s)'}`).join('\n')}

The shared work is already in ${WORKSPACE}/concepts/${concept.id}/common/ ${common && common.folder ? `(${common.resources.length} resources, see RESOURCES.json)` : '(check what is there before redoing anything)'}.
${common && common.music_bed ? `Music bed, already looped: ${common.music_bed}` : ''}

For each variant you own:
1. Its own folder: ${WORKSPACE}/concepts/${concept.id}/<LETTER>/ with \`build.py\`, \`spec.json\` and \`notes.md\`.
2. Render and verify (the checklist is above).
3. Copy the delivery to ${DELIVERIES}/${concept.id}/ as \`${concept.id}-<LETTER>.mp4\`, plus the
   \`-preview.mp4\` if it carries a song and a light \`-light.mp4\` at 720p for sending over chat.
4. If the variant is narrated, leave the \`voice-script.md\` next to the MP4 (format in
   \`$CLAUDE_PLUGIN_ROOT/examples/voice-script.md\`), written in ${LANG}.
Do not write the concept's README: the reviewer does that, one for all the variants.`
}

function reviewPrompt(concept, variants) {
  return `Review ALL the variants of reel-forge concept "${concept.id}" (${concept.title}).
They were built by ${AG_PER_CONCEPT} different agents, so the typical mistake is not inside one variant
but BETWEEN them.

Variants:
${variants.map((v) => `- ${v.letter}: ${v.mp4} (${v.duration_s} s, ${v.cuts} cuts, ${v.cuts_with_subject} with the subject)\n  spec: ${v.spec}`).join('\n')}

What to review:
1. **Compare the SAME frame between variants.** One builder left a \`look\` that washed out the hook in
   two of four deliveries and nobody saw it because everyone only reviewed their own.
2. That they do not repeat the same shot with different copy: if two variants read the same, one is
   redundant.
3. Technical, with commands, taking nobody's word for it: \`blackdetect\`,
   \`silencedetect=n=-45dB:d=0.25\`, \`loudnorm=print_format=summary\` (peak below -0.5 dBTP), the audio's
   real duration equal to the video's (\`ffprobe -select_streams a:0 -show_entries stream=duration\`), and
   an \`fps=2,tile=12x6\` strip of each one.
4. Text: legible, inside the safe area, not covering faces, no orphan word, correct facts (dates, places
   and prices verified against the catalog or a dated source), and **every line in ${LANG}**, correctly
   spelled, with no mixing of languages. Copy in the wrong language is a blocker.
5. The cuts with ${SUBJECT}: count them yourself, do not trust what the builder reported.
6. That every \`build.py\` regenerates its spec from scratch.

Write ONE single README.md for the concept in ${DELIVERIES}/${concept.id}/, in ${LANG}, with the variants
inside, what changes between them, which one you recommend and the cut counts. Not one README per agent.
Mark \`severity: "blocks"\` only on what makes delivery impossible.`
}

function fixPrompt(concept, problems) {
  return `Fix what is blocking delivery of reel-forge concept "${concept.id}". Do not redesign: correct
exactly this and re-render the affected variants.

${problems.map((p) => `- [${p.variant}] ${p.what}${p.where ? ` (${p.where})` : ''}\n  Fix proposed by the reviewer: ${p.how_to_fix}`).join('\n')}

Rules:
- The correction goes INSIDE the variant's \`build.py\`, not by hand on the MP4. If a step fixes
  something the engine gets wrong, it has to be chained into the script: a loose \`.sh\` with no
  \`chmod +x\` already let a clipped preview through without anyone noticing.
- Re-run the checks and update the concept's README.
- Return the corrected variants, with their new paths and counts.`
}

// ───────────────────────────────────────────────────────────── the run

log(`${concepts.length} concepts · ${AG_PER_CONCEPT} builders and ${REVIEWER ? 1 : 0} reviewer per concept · delivery ${VERSION} · language ${LANG}`)

phase('Common')

// pipeline: each concept advances on its own. Concept 1 can be in review while concept 3 is still
// exporting originals; a barrier between phases would leave the fast builders waiting.
// The barriers that genuinely are needed are local to one concept: a concept's builders have to finish
// before its reviewer can compare them, and that gets solved with a parallel() INSIDE the stage, not
// between stages.
const results = await pipeline(
  concepts,

  // 1. The shared work, once per concept.
  (_prev, concept) => agent(commonPrompt(concept), {
    label: `Common ${concept.id}`, phase: 'Common', schema: COMMON,
  }),

  // 2. The builders, in parallel with each other.
  async (common, concept) => {
    const teams = roundRobin(variantsOf(concept), AG_PER_CONCEPT)
    const rounds = await parallel(teams.map((mine, i) => () => agent(
      buildPrompt(concept, common, mine, i),
      {
        label: `${concept.id} ${mine.map((v) => v.letter).join('+')}`,
        phase: 'Build',
        schema: { type: 'object', properties: { variants: { type: 'array', items: VARIANT } }, required: ['variants'] },
      },
    )))
    const variants = rounds.filter(Boolean).flatMap((t) => t.variants)
    const fallen = teams.filter((_, i) => !rounds[i]).flatMap((t) => t.map((v) => v.letter))
    if (fallen.length) log(`${concept.id}: no result for variants ${fallen.join(', ')} — they have to be redone`)
    if (!variants.length) throw new Error(`${concept.id}: not a single variant got built`)
    return { common, variants, fallen }
  },

  // 3. One reviewer per concept, with EVERY variant in front of it.
  async (built, concept) => {
    if (!REVIEWER) return { ...built, review: null }
    const review = await agent(reviewPrompt(concept, built.variants), {
      label: `Review ${concept.id}`, phase: 'Review', schema: REVIEW,
    })
    return { ...built, review }
  },

  // 4. Fixing, only if something blocks. A clean concept does not pay for this stage.
  async (reviewed, concept) => {
    const blockers = ((reviewed.review && reviewed.review.problems) || []).filter((p) => p.severity === 'blocks')
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

return {
  project: PROJECT,
  deliveries: DELIVERIES,
  lang: LANG,
  concepts: ok,
  failed_concepts: failed,
  total_variants: ok.reduce((n, c) => n + c.variants.length, 0),
}
