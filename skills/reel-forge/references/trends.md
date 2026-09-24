# Researching trends

Without this you get a generic recap: photos in order, a centred title and royalty-free music. That
video has been made and the verdict was *"very generic"*.

**Never invent a song, a format or a "trending" sound.** Everything carries a source and a date. Trends
expire in weeks: a three-month-old data point is useless, and one from the model's training data even
more so.

Launch it as **an agent with web search**, in parallel with the context phase. It returns
`workspace/trends/trends.json`.

## The market follows the output language

The agent gets the language tag (`es-MX`, `en-US`, `pt-BR`…) and researches **that market**. This is
not a detail: Spanish-language TikTok in Mexico and English-language TikTok in the US have different
sound charts, different hooks and different caption styles. A report built for the wrong market produces
a video that reads as imported.

- The region comes from the tag. Query the music store with that country code.
- **Search in the target language**, not in English about that language: that's what surfaces the
  creators the audience actually watches.
- If the tag has no region, research the language broadly and note which region most sources came from.
- The report states the market in its first field. If you had to fall back to a nearby market, say which
  one and why.

## What it has to bring back

```json
{
  "date": "2026-09-23",
  "platform": "tiktok",
  "market": "es-MX",
  "formats": [
    {"name": "narrated storytime", "duration_s": [21, 40], "why": "...", "source": "url", "seen": "2026-09-22"}
  ],
  "sounds": [
    {"title": "...", "artist": "...", "bpm": 123.0, "measured_with": "librosa over a 30 s preview", "source": "url"}
  ],
  "hooks": ["first-second lines that keep repeating, with an example, in the market's language"],
  "voices": [{"name": "...", "how_to_get_it": "...", "license": "..."}],
  "avoid": ["things that already read as dated"]
}
```

## How to search

- Watch 10-15 real videos from the niche (travel, food, event) published **in the last few weeks** and
  note what repeats: duration, where the text sits, when the first cut lands, whether there's a voice.
- Look for the concrete: "small fixed hook text at the top in 6 of 15", "a burst of 0.2-0.4 s cuts
  before the end", "day and city tag with a pin". That's actionable.
- Field notes: a video player won't load if the browser window is hidden, and pulling many videos in a
  row from the same site usually ends in a temporary block. Go slow and save what you find as you find
  it.

## BPM: measure it, don't look it up

Written-down BPM values are wrong half the time (double or half). Measure it:

1. Download the public 30 s preview from the music store's catalog
   (`https://itunes.apple.com/search?term=<song>&entity=song&country=<region>` → the `previewUrl`
   field). It's public, needs no key, and it's a preview: **it never gets embedded in anything that
   gets published**.
2. `librosa.beat.beat_track` over that preview, and **confirm by counting**: if it says 70 and it sounds
   fast, it's 140.
3. Save the measured BPM and what you measured it with.

The BPM gives you the cut grid: at 120 BPM a beat is 0.5 s, cuts every 2 beats = 1.0 s. Ranges that
work: 85-95 for something ceremonial or documentary, 120-140 for a photo dump, 150-165 for a fast burst.

## Music and rights

- **Don't embed copyrighted music in the version that gets uploaded.** The render produces two files:
  `x.mp4` clean (no song) and `x-preview.mp4` with the song **just so the user can watch it**. The
  official sound gets added in the app, which also makes the video count toward that trend.
- The store preview is **30 s**. On a 34 s video the music simply ends and nothing warns you. Past ~29 s
  build a looped bed: `acrossfade=d=1.5` between the preview and a shifted copy, `atrim` to the exact
  length, and normalize (`loudnorm I=-22`, a bed sitting under the natural audio). Verify with
  `ffprobe -select_streams a:0 -show_entries stream=duration`: it has to be exactly the video's length.
- Royalty-free music only as a last resort: it demands credit and it feels generic.
- **The bed is made by the common builder, not by each builder.**

## Style that works (and what doesn't any more)

This comes from production, not from search; use it as a baseline and let the agent update it.

**Works**
- A hook in the first second: the strongest shot first. Most people leave before 3 s.
- A mini hook every 3-5 s: something that changes (a hard cut, a caption, a sound, a reveal).
- Hard cuts on the beat with a **punch-in** (a zoom that settles in ~0.2 s).
- Real slow motion from clips shot at 60 fps (speed 0.5), not interpolated.
- A 2-3 frame white flash, and only at the strong moment.
- Text: sparse, short, well centred, outside the interface zones.
- Duration: 21-40 s retains better than 60. A single beautiful shot, 8-11 s, also works.
- 3 to 5 tags, including one niche tag in the output language.

**Not any more**
- Cross-fades, wipes, sparkles: "little transitions from a 15-year-old editor".
- RGB glitch, the same whoosh on every cut, neon subtitles with emoji, thick outlines with "every word
  in yellow".
- More than two effects on a single cut.
- A centred title over the first photo and nothing else.
