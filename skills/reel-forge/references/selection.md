# Selecting material

The seven rules are in the SKILL. This is **how they get honoured**, which is where things go wrong.

## Actually looking at the material

### Contact sheets (photos)

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/sources/scripts/sheets.py" contact list.json \
    --cols 6 --out workspace/sheets/day-03
```

- **Numbered** thumbnails, 24 to 36 per sheet. More than that and you can't tell a grimace apart.
- Open them with the image-reading tool and **describe them one by one**. An agent that returns a
  catalog without having read a single image is obvious: it describes by file name.
- The sheet numbering has to map to a stable identifier in the catalog. If the agent says "number 14",
  there has to be a 14.

### Face crops (expressions)

The step that has saved the most videos. In a 180 px thumbnail you can't see that somebody is mid-word.

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/sources/scripts/sheets.py" faces list.json \
    --out workspace/sheets/faces-day-03
```

- Detects faces and builds a sheet of crops only, keyed to the same numbers as the contact sheet.
- On macOS, if the material comes from Apple Photos, the faces are already detected in the library and
  using those boxes is faster and more reliable.
- What you're looking for: open eyes, mouth closed or genuinely smiling, gaze pointing somewhere
  coherent. What you drop: turning away, blinking, mouth mid-word, hand adjusting hair or clothes.

### Bursts and neighbours

For every candidate where the subject appears, pull **all** the takes within ±10 min and look at them
together. The good photo is almost never the first of the sequence: it's usually two or three later.

### Frame strips (video)

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/sources/scripts/sheets.py" strip clip.mp4 \
    --fps 1 --cols 8 --out workspace/sheets/
```

or directly:

```bash
ffmpeg -i clip.mp4 -vf "fps=1,scale=216:384,tile=8x4" -frames:v 1 strip.jpg
```

- 1 frame per second to catalog, 4 fps to find the exact instant of a cut.
- A clip longer than 2 minutes: first 1 frame every 3 s to locate the zones, then 1 fps only there.
- If the clip has audio that matters (shouting, a line, water, laughter), also pull a volume profile or
  transcribe it — see `audio.md`.

## Catalog ranges, not files

A 40 s video holds 3-6 good seconds. The catalog stores windows with `start_s` and `end_s` plus a
description of what happens inside that exact window. Format in `catalog.md`.

**The window is binding.** Two builders took a clip outside its cataloged window (catalog said 0-4 s;
one used 4.0-5.7, the other 7.2-8.4) and instead of the subject you got strangers' faces against the
lens. If you need to step outside the window, pull a strip of that zone and look at what's there first.

How to split a clip into ranges:
1. A 1 fps strip of the whole clip.
2. Mark the changes: change of framing, of subject, of light, the camera settling, the moment something
   happens.
3. One range per thing that happens, with ~0.3 s of padding inside each end.
4. Drop the filler (camera hunting, hands, ground, black screen) explicitly: catalog it as a range with
   `use: false` and a reason, so nobody rediscovers it.

## Default drops

Overridable: if the user says they want the receipt because the price is the joke of the video, it's in.

| What | Why |
|---|---|
| receipts, tickets, proofs of purchase | personal data and they add nothing visually |
| screenshots, documents, screens with work or code | they leak information and break the tone |
| blurry, underexposed, blown out | they don't read on a phone |
| near-identical duplicates | two nearly identical cuts read as an editing mistake |
| identifiable minors as protagonists | a minor isn't published without explicit permission |
| licence plates, addresses, cards, banking screens | sensitive |

In the catalog: `"use": false, "reason": "screenshot"`. Nothing gets deleted.

## Subject quota

- Default: **the subject in half the cuts or fewer**. What worked in production was 14-35 %.
- The rest: landscape, architecture, food, people (locals, friends, the group), animals and shots with
  nobody in them.
- The subject with friends counts as the subject. Shots of other people only: yes, in moderation, and
  only if they add something (a scene, not a portrait of someone else).
- **Count the cuts by hand at the end** and write the number in the README: "21 cuts, the subject in 3
  (14 %)".

## When the subject appears

- Only library favorites (macOS: `favorite`; in a plain folder, ask or use the list they give you).
- If there aren't enough favorites, widen to the neighbours by time, not to anything at all.
- Visible face, decent light, natural pose. No photographer-directed poses.
- In clips, the subject in close-up comes out better as a photo than as video: use video for action and
  landscape.
- The plugin **does not retouch people**. The only thing applied is the render's `look`, evenly across
  the whole variant. See `editing.md`.

## Verifying what goes on screen

- Every date and every place that appears in a caption is verified against the file's metadata.
- **Watch out for time zones:** an exported file name usually carries the local time of the place where
  it was taken, and the library database carries the home one. With 12-14 h of difference, a whole day
  slips in. The metadata's capture date wins, not the name.
- Prices, opening hours, official names: research them with a source and a date. Don't ask the user
  things they won't remember, and don't invent them.
