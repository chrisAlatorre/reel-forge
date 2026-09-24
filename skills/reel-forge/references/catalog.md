# The catalog

It's the contract between the context agents and the builders. If every agent invents its own format,
phase 7 collapses. Hand this whole file to every context agent.

Each agent writes **its own** `workspace/catalog/catalog-<batch>.json`. You merge them into
`workspace/catalog/catalog.json` (concatenate `items`, check there are no duplicate `id`s).

## Format

```json
{
  "batch": "day-03-city",
  "agent": "context-3",
  "reviewed": "2026-09-23",
  "items": [
    {
      "id": "d03-014",
      "path": "~/Pictures/trip/IMG_0142.jpg",
      "type": "photo",
      "date": "2026-08-04T17:22:10",
      "place": "central market",
      "favorite": true,
      "subject": true,
      "use": true,
      "what_it_is": "Him facing camera eating at a stall, side afternoon light, smoke behind. Natural smile, eyes open.",
      "quality": 4,
      "hook": 3,
      "sheet": "workspace/sheets/day-03/sheet-01.jpg#14",
      "notes": "Burst of 5; this is the 3rd and the only one without a blink.",
      "tags": ["food", "people", "street"]
    },
    {
      "id": "d03-021",
      "path": "~/Pictures/trip/VID_0155.mp4",
      "type": "video",
      "date": "2026-08-04T18:03:00",
      "duration_s": 42.0,
      "fps": 60,
      "ranges": [
        {
          "start_s": 3.2, "end_s": 7.4, "use": true, "subject": false,
          "what_it_is": "Shot of the wok, big flare-up at 5.1 s. Static camera.",
          "quality": 5, "hook": 5,
          "audio": "loud steady sizzling; works as diegetic sound",
          "tags": ["food", "fire"]
        },
        {
          "start_s": 0.0, "end_s": 3.2, "use": false,
          "reason": "camera hunting for the framing, you can see the ground"
        }
      ]
    },
    {
      "id": "d03-030",
      "path": "~/Pictures/trip/IMG_0170.png",
      "type": "photo",
      "use": false,
      "reason": "screenshot"
    }
  ]
}
```

## Fields

| Field | Required | What it is |
|---|---|---|
| `id` | yes | unique across the whole project. Batch prefix + number. |
| `path` | yes | relative to `~` or to the project root. **Never an absolute path carrying a user name.** |
| `type` | yes | `photo`, `video`, `video360`, `live` |
| `date` | yes if it exists | ISO 8601 from the metadata, not from the filesystem |
| `use` | yes | `false` + `reason` for everything dropped. Nothing gets deleted. |
| `subject` | yes | `true` if the video's main person appears |
| `favorite` | if the library provides it | starred as a favorite |
| `what_it_is` | yes, if `use` | **what you saw**, in one or two sentences: what's there, what light, what expression, what moves |
| `quality` | yes, if `use` | 1-5 technical: focus, exposure, framing, stability |
| `hook` | yes, if `use` | 1-5 how much it stops the thumb. A 5 is a candidate for the first cut. |
| `ranges` | on videos | list of windows; the whole file is **not** used |
| `audio` | if applicable | what you hear in that range and whether it's usable |
| `sheet` | yes, if `use` | which contact sheet it came from and with what number (that's how it gets audited) |
| `tags` | yes, if `use` | the vocabulary below |

`what_it_is` is written in English, like the rest of the catalog: it's a working contract, not copy.
The on-screen text of the video follows the output language and lives in the concept, not here.

## Tag vocabulary

Use it verbatim; the builders filter on these words.

`landscape` `city` `architecture` `interior` `food` `drink` `people` `friends` `animals` `water`
`night` `sunset` `transport` `market` `nature` `detail` `motion` `empty` `sky`
`crowd` `religious` `art` `sport` `weather`

`empty` = nobody in frame. It's the most useful tag for meeting the subject quota: tag generously.

## Rules for whoever writes the catalog

- **Describe what you saw, not what you assume.** "A temple" is useless; "gilded façade backlit, people
  seen from behind in the lower third" is.
- A high `hook` only for something that genuinely stops you: a close animal, fire, a view opening up, a
  face reacting. Most material is a 2 or a 3.
- If you're unsure about a file, `use: false` with reason `"needs review"` and move on. Don't guess.
- A video's ranges don't overlap and are ordered by `start_s`.
- If a range is shorter than 0.8 s, it can't carry a caption or a stamp: it can't be read.

## Rules for whoever reads the catalog

- **You cannot step outside `start_s`/`end_s`.** If you need to, pull a strip of that zone, look at it,
  and update the catalog with the new range. Never silently.
- Don't use an `id` with `use: false` without saying so in your notes.
- Two cuts with the same `id` in one video: only if they sit far apart in the edit and look different.
