---
description: Researches the current format, sound and editing trends on the web for a given topic and language market, measures the BPM of the candidate songs, and leaves a reusable report.
argument-hint: "<topic> [--lang es-MX|en-US|...] [--platform tiktok|reels|shorts] [--fast] [--out PATH]"
---

# /reel-trends — what is working right now

Arguments received: `$ARGUMENTS`

Topic (the first thing in `$ARGUMENTS` that isn't a flag): travel, a day at work, pets, countryside,
food, sport, fitness, cars, music, whatever.

| Flag | Effect |
|---|---|
| `--lang TAG` | Language **and market** of the research (`es-MX`, `en-US`, `pt-BR`…). Default: `$REEL_FORGE_LANG`, then `"lang"` in `~/.config/reel-forge/config.json`, then the language the user is writing in. |
| `--platform` | A single platform; by default it looks at vertical video in general |
| `--fast` | 1 agent, formats and 3 sounds, BPM measured only for the main one |
| `--out PATH` | Where to leave the report (default: `<root>/trends/<topic>-<date>.md`, where `<root>` is `$REEL_FORGE_HOME`, or `~/Movies/reel-forge` on macOS, `~/Videos/reel-forge` on Linux, `%USERPROFILE%\Videos\reel-forge` on Windows) |

It can run on its own, or `/reel` calls it in step 4.

## The market follows the language

`--lang` is not cosmetic: it picks **which market you research**. Spanish-language TikTok in Mexico
and English-language TikTok in the US have different sound charts, different hooks and different
caption styles; a report built for the wrong one produces a video that reads as imported.

- Take the region from the tag (`es-MX` → Mexico, `en-US` → United States, `pt-BR` → Brazil). If the
  tag has no region (`en`, `es`), say in the report that you researched the language broadly and note
  which region most of your sources came from.
- Search **in that language**, not in English about that language. A Spanish search returns the
  creators that a Spanish-speaking audience actually watches.
- Song charts are per country: query the music store API with that region code.
- The report's first line states the market you targeted. If you had to fall back to a nearby market
  because there were no sources, say which one and why.

## Skills and agents

- Main skill: `reel-forge:reel-forge`; the guide for this phase is
  `skills/reel-forge/references/trends.md`. There is no skill called `trends`.
- Consumers of the result: `reel-forge:video-engine` (formats, text styles) and `reel-forge:voices`
  (narration styles).
- Agent: `trend-researcher`, with web search access.

### Scaling

| Mode | Agents | Split |
|---|---|---|
| `--fast` | 1 | everything together |
| normal | 2 | (a) formats and editing, (b) sounds and voices |
| broad topic or several platforms | 3 | (c) splits off concrete references: accounts and videos doing it well |

More than 3 agents here is useless: the sources start repeating and the report fills up with the same
thing said three times.

## What the report has to bring back

### 1. Formats
The ones that work **for that topic**, not in general. For each: what it consists of, typical
duration, what the hook is and why it retains. Examples of the kind of thing you're looking for:
first-person walkthrough with few long shots, a "things nobody tells you about X" list, expectation
versus reality, a beat-cut montage, documentary narration, a photo carousel.

### 2. Sounds
For each candidate: **title, artist, release date, whether it is trending in the requested market,
and measured BPM**.

- BPM is **measured**, not estimated: download a legal preview of the audio (the music store's public
  search API gives a 30 s clip) and analyze it with an audio-analysis library.
- Note the cut length the BPM implies: at 120 BPM, 2 beats are 1.0 s.
- **Mark which ones are copyrighted.** The plugin's rule: the song is **not embedded** in the file
  that gets uploaded; it goes on in the app at publish time, where it also counts toward the trend.
  It is only embedded in the `-preview` copy, for review.
- Store previews last ~30 s. For a longer video you need a looped bed with a cross-fade, or the ending
  goes silent.
- Royalty-free music: last resort. It sounds generic and almost always demands credit.

### 3. Editing and text
What is being used and **what already looks dated**. What gives away a template-made video today:
long cross-fades, wipes, sparkles, the same air whoosh on every cut, neon subtitles with a thick
outline, emoji on every line. Also note the text sizes and positions that are working and each app's
current safe area.

### 4. Voice and narration
If the topic gets narrated, what the current style is (the app's synthetic voice, the creator's own
narration, no voice and only natural sound) and what is burned out. Generation details in
`/reel-voice`.

### 5. Hashtags and description
3-5 hashtags: two broad, two topical, one niche — **in the researched language**. No blocks of twenty.

### 6. References
3-5 concrete videos or accounts doing that format well, with what each one has that's worth copying.
Link and the date you saw it.

## Rules

- **Never invent a "trending" song, a BPM or a view count.** If you couldn't verify it, write "not
  verified" and move on. One invented fact here ruins the whole video later.
- Everything carries a **lookup date and a source**. Trends expire in weeks: a two-month-old report
  gets re-run, not reused.
- Distinguish what you saw with your own eyes from what a "10 trends of the year" article says, which
  is usually recycled.
- If opening videos makes the platform start blocking requests, slow down and work with fewer
  samples. Don't push it.
- Use no unofficial endpoints and nothing that requires the user's session.

## Delivery

A `.md` with the six sections, plus a closing block of **three concrete recommendations** for the
material at hand: which format, with which sound, and why. Also state the market and language at the
top. If `/reel` called you, return the report's path as well so the builders can read it.
