# The catalog

It's the contract between the context agents and the builders. If every agent invents its own format,
the build phase collapses.

**The format is a schema, not a description:** `$CLAUDE_PLUGIN_ROOT/schemas/catalog-item.schema.json`.
Hand that file to every context agent along with this one, and have it validate before answering:

```bash
uv run "$CLAUDE_PLUGIN_ROOT/schemas/validate.py" workspace/catalog/catalog-day-03.json --type catalog-item
```

Each agent writes **its own** `workspace/catalog/catalog-<batch>.json`. You merge them into
`workspace/catalog/catalog.json` — same shape, `batch: "merged"` — and validate the result.

## What an item is

**One item is one moment, not one file.** A photo is an item. Each usable window of a video is its own
item, with its own id, its own `start_s`/`end_s` and its own description. Each usable framing of a 360
clip is its own item too, with its `direction`. A 40 s clip that yields three good windows is three
items; the filler in between is another item with `use: false`.

That is what lets a concept say "cut 4 is `d03-021a`" without anybody having to guess which second of
which file that means.

```json
{
  "batch": "day-03-city",
  "agent": "photo-curator",
  "summary": "Market day: food stalls, one strong fire moment, one clean portrait.",
  "struck_me": ["the wok flare-up", "the empty square at dawn", "the dog under the table"],
  "items": [
    {
      "id": "d03-014",
      "path": "~/Pictures/trip/IMG_0142.jpg",
      "type": "photo",
      "date": "2026-08-04T17:22:10",
      "place": "central market",
      "favorite": true,
      "subject_present": true,
      "description": "Facing camera eating at a stall, side afternoon light, smoke behind. Natural smile, eyes open.",
      "quality": 4,
      "hook": 3,
      "sheet": "workspace/sheets/day-03/sheet-01.jpg#14",
      "tags": ["food", "people", "market"],
      "notes": "Burst of 5; this is the 3rd and the only one without a blink."
    },
    {
      "id": "d03-021a",
      "path": "~/Pictures/trip/VID_0155.mp4",
      "type": "video",
      "start_s": 3.2, "end_s": 7.4, "duration_s": 42.0, "fps": 60,
      "subject_present": false,
      "description": "The wok, big flare-up at 5.1 s. Static camera.",
      "quality": 5, "hook": 5,
      "audio": "loud steady sizzling; works as diegetic sound",
      "sheet": "workspace/sheets/day-03/strip-155.jpg",
      "tags": ["food", "motion"]
    },
    {
      "id": "d03-021z",
      "path": "~/Pictures/trip/VID_0155.mp4",
      "type": "video",
      "start_s": 0.0, "end_s": 3.2,
      "use": false,
      "reason": "camera hunting for the framing, you can see the ground"
    }
  ]
}
```

Field by field — names, types, what is required — in the schema. What the schema can't tell you:

- `description` is **what you saw**, in one or two sentences: what's there, what light, what expression,
  what moves. "A temple" is useless; "gilded façade backlit, people seen from behind in the lower third"
  is. Written in English, like the rest of the file: it's a working contract, not copy. The on-screen
  text of the video follows the output language and lives in the concept, not here.
- `hook` is a 5 only for something that genuinely stops you: a close animal, fire, a view opening up, a
  face reacting. Most material is a 2 or a 3.
- `sheet` is what makes the catalog auditable: which contact sheet or strip you read it off, with its
  number. An agent that catalogs by file name is obvious precisely because it can't fill this in.
- `audio` describes what you hear **in that window**, and whether it's usable.
- `use: false` + `reason` for everything dropped. Nothing gets deleted, and nothing gets dropped
  silently: the user may want the receipt back because the price is the joke of the video. There is no
  separate list of drops — a dropped item is an item, in the same `items` array, so nobody has to merge
  two lists to know what happened to a file.

## Tag vocabulary

The schema enforces it, because the builders filter on these exact words:

`landscape` `city` `architecture` `interior` `food` `drink` `people` `friends` `animals` `water`
`night` `sunset` `transport` `market` `nature` `detail` `motion` `empty` `sky`
`crowd` `religious` `art` `sport` `weather`

`empty` = nobody in frame. It's the most useful tag for meeting a concept's subject quota
(see `concepts.md`): tag generously.

## Rules for whoever writes the catalog

- **Describe what you saw, not what you assume.** How you actually look at it — contact sheets, face
  crops, frame strips — is in `selection.md`.
- If you're unsure about a file, `use: false` with reason `"needs review"` and move on. Don't guess.
- A video's windows don't overlap and are ordered by `start_s` (the validator checks both).
- A window shorter than 0.8 s can't carry a caption or a stamp: it can't be read.
- Two framings of the same 360 clip closer than 90° of yaw read as the same shot repeated.

## Rules for whoever reads the catalog

- **You cannot step outside `start_s`/`end_s`.** If you need to, pull a strip of that zone, look at it,
  and update the catalog with the new window. Never silently: the build result has an `out_of_window`
  field for exactly this.
- Don't use an id with `use: false` without saying so in your notes.
- The same id in two cuts of one video: only if they sit far apart in the edit and look different.
