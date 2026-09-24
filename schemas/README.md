# Contracts

Everything that travels between reel-forge agents is **JSON with a schema in this folder**. Not free
text, not a table in a chat message, not "roughly this shape".

This is the source of truth for the *fields*: their names, their types and what is required. The prose
that explains **how to fill them in well** lives in the skill references and links back here:

| Contract | Schema | Who writes it | How to fill it |
|---|---|---|---|
| Catalog item (batch file) | [`catalog-item.schema.json`](catalog-item.schema.json) | `photo-curator`, `clip-analyst`, `360-scout` | [`references/catalog.md`](../skills/reel-forge/references/catalog.md) |
| Concept | [`concept.schema.json`](concept.schema.json) | `creative-director` | [`references/concepts.md`](../skills/reel-forge/references/concepts.md) |
| Variant build result | [`variant-build-result.schema.json`](variant-build-result.schema.json) | `video-builder` | [`references/agents.md`](../skills/reel-forge/references/agents.md) |
| Review result | [`review-result.schema.json`](review-result.schema.json) | `critic-reviewer` | [`references/agents.md`](../skills/reel-forge/references/agents.md) |
| Voice script | [`voice-script.schema.json`](voice-script.schema.json) | `video-builder` (narrated variants) | [`references/audio.md`](../skills/reel-forge/references/audio.md) |
| Story review | [`story-review.schema.json`](story-review.schema.json) | `story-doctor` (both passes) | [`agents/story-doctor.md`](../agents/story-doctor.md) |

Every schema is self-contained (no cross-file `$ref`) and every field carries a `description`: handing
an agent the schema file **is** handing it the contract.

## Validating

```bash
uv run "$CLAUDE_PLUGIN_ROOT/schemas/validate.py" <file> --type <contract>
uv run "$CLAUDE_PLUGIN_ROOT/schemas/validate.py" <file>            # the type is guessed from the name
```

An agent validates its own output **before answering**. Whoever collects it validates again before
spending the next phase on it: a bad catalog gets multiplied by four concepts.

```bash
# the whole batch file, or a single item, or a list of items
uv run .../validate.py workspace/catalog/catalog-day-03.json --type catalog-item

# and, for anything that cites catalog ids, check they exist and are not dropped
uv run .../validate.py concepts/empty-square.json --type concept --catalog workspace/catalog/catalog.json
```

Exit code `0` complies, `1` does not, `2` could not be read. On top of the schema it checks the few
things JSON Schema cannot say: duplicate ids, windows that end before they start or overlap, narration
lines out of order or stepping on each other, a subject count over the ceiling the concept declared,
a real peak above −0.5 dBTP, audio shorter than the video.

**And it checks the arc**, which is where "the video cuts off too soon" is caught before anything is
rendered: development beats out of order or more than 5 s apart with no `mini_hook` across the gap,
two beats that raise the same thing, a promise paid in the first third or after the last frame, a
`structure` whose roles do not run hook → development → turn → close, a last block that is not the
close, a close under 1.2 s, a narrated concept where no cut says what the voice names, and variants
that all land within 4 s of each other while one of them claims to differ in duration.

## Conventions shared by every contract

- **Ids** are lowercase, `[a-z0-9_-]`, unique across the project. Convention:
  `d03-014` a photo of day 3, `d03-021a` the first usable window of a clip of day 3, and the same
  with `b`, `c`… for the other windows of that same file. A 360 framing is another window: `d03-030a`,
  `d03-030b`, separated by at least 90° of yaw.
- **Seconds** are numbers with 2 decimals. Inside an item they are relative to the start of its source
  file; inside a concept, a build result or a voice script, to the start of the video.
- **Paths** are relative to the project folder or start with `~`. A path carrying somebody's home
  directory is rejected by the schema.
- **Ratings are 1 to 5**: `quality` (focus, exposure, framing, stability) and `hook` (how much it stops
  the thumb). Most material is a 2 or a 3.
- **The files are written in English** — keys, descriptions and notes. Only the fields that end up on
  screen or spoken (`text`, `hook.text`) go in the run's output language, and every contract that
  carries copy also carries its `lang` tag.
- **Nothing is invented.** Material that does not exist goes in `missing`, `gaps` or `warnings`. An id
  that is not in the catalog invalidates the file that cites it.
- **Nothing is deleted.** Material that is dropped stays in the catalog with `use: false` and a
  `reason`: the user may want it back.
- **Write the file before answering.** The JSON on disk is the result; the chat message is a summary of
  it. If an agent dies halfway, the missing file is the signal to redo that batch — which is why it gets
  written complete, at the end, never incrementally.
