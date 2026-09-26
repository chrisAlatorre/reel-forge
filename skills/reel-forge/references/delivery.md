# Delivery and verification

## Structure

```
<root>/<project title>/v1/<concept>/
  <concept>-A.mp4              UPLOAD-READY: upload.py's profile, NO copyrighted music, passed the gate
  <concept>-B.mp4              …one per variant, and NOTHING else loose in this folder
  resources/
    README.md                  one per concept, every variant inside
    <concept>-A-preview.mp4    with the song, just so they can hear it (720p)
    <concept>-A-light.mp4      720p, for sending over chat
    <concept>-A.timeline.json  what the render burned in and where every cut fell — the gate reads it
    <concept>-A-verify.json    the gate's report for the upload file
    <concept>-A-framecheck.json  <concept>-A-publish.md  <concept>-A-voice-script.json
    common/  A/  B/            the shared material and each variant's build (variant.json, spec, voice)
```

The user asked for it in these words: open a concept's folder and see **only the videos, ready to
upload**. Everything else — even the README — is in `resources/`. The `timeline.json` stays with the
build: `verify.py` looks for it beside the video **and** in `resources/`, so the text, voice-over-image
and ending checks still run — a skipped check looks exactly like a passed one.

**The upload file is its own encode** (`upload.py`), not the render: 1080x1920, H.264 High, 30 fps
constant, BT.709 tagged, CRF 17 capped at 14 Mbps, 2 s closed GOP, AAC-LC 48 kHz 256 kbps,
`+faststart`. Every platform re-encodes; what we control is handing it a clean standard file at the
top of its useful range. The README always tells the user to turn on **"Upload in HD" / "Allow
high-quality uploads"** when posting — without it the app compresses on the phone first, whatever the
file.

Root: `REEL_FORGE_HOME` if set; otherwise the user's videos folder + `Reel Forge` (macOS
`~/Movies/Reel Forge`, Windows `%USERPROFILE%\Videos\Reel Forge`, Linux `$XDG_VIDEOS_DIR/Reel Forge`).

- **One round, one version.** Changes come out as a full `v2`. `v1` is never touched.
- **One README per concept**, with every variant inside. Not one per agent.
- The project's `workspace/` can be deleted and rebuilt — but deleting it also throws away `workspace/run.json`, the ledger an interrupted run resumes from.
  Say so before wiping it.

## The gate: nothing ships unverified

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/video-engine/scripts/verify.py" <file.mp4> \
    --spec spec.json [--script voice-script.json] --json <file>-verify.json
```

**Run it with everything it can check, never bare.** Each flag buys a check nobody can do by looking at
a frame strip: `--spec` that the render lasts what it was supposed to, `--script` that the voice rises
over the clip's own audio. `text_sync`, `voice_image` and `ending` come from the `<video>.timeline.json`
sidecar and need no flag — but they need the file: **a `skip` in the report is not a `pass`**, and the
difference is a caption that lands versus one that feels a beat late.

Run twice, by two different agents:

1. **The builder**, on its own variant, before copying anything into the delivery folder. It fixes
   inside `variant.json` and re-renders; it never patches the MP4.
2. **The reviewer**, again, on every file that is actually in the delivery folder. It takes nobody's
   word for it, the builder's included. The report is saved next to the file.

If a variant cannot be made to pass with the material that exists, it is **not delivered**. It is marked
non-deliverable, and the concept's README says so, in its own line, with what was missing and what it
would take. A delivery folder that quietly contains a file nobody checked is the worst outcome available
here; a stated limit is worth more.

**Narration counts as delivered only if it can be heard.** Either the voice is audible in the MP4, or
the `voice-script.json` ships beside it, is written in the one format
(`schemas/voice-script.schema.json`), proves it parses —

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/voices/scripts/narrate.py" voice-script.json --parse-only
```

— with the **same number of lines** that were written, and is named in the README. Narrated videos have
already gone out silent because the script was written in a shape the parser skips and nobody checked.

## The concept's README

Written **in the output language** — it's what the user reads before posting. The structure stays the
same in any language:

```markdown
# <concept name>

**Hook:** what you see and what you read in the first second.
**Promise:** what you're telling the viewer.

| Variant | Duration | Why that long | What makes it different | Voice | File | Verified |
|---|---|---|---|---|---|---|
| A | 47 s | 6 beats + a 3 s close | natural sound, no music | — | concept-A.mp4 | yes |
| B | 14 s | hook, two beats and the payoff | narrated, cut to the beat | Valentino (CapCut) | concept-B.mp4 | yes |

**The duration column is not decoration**: it is what shows the length came from the story and not from
a template. If two variants run the same length, one of them is redundant and the README says so.
**The voice column** names the voice of every narrated variant; when it is not the default for the
output language, the "Not delivered" section — or a line of its own — says why.

## Not delivered
(Only if something didn't make it. One line each, and never left out.)
- **C (short version):** doesn't pass verification — the payoff range runs 1.4 s and the concept needs
  3 s. It would take another shot of that scene, which isn't in the catalog.

## To post it
- Official sound: "<title>" by <artist> (<bpm> BPM, measured). The clean MP4 ships without music: add
  it in the app.
- Suggested tags: #… (3-5, one niche)
- Suggested description: one line.
- If it's narrated and shipped without voice: `voice-script.json` carries each line's entry second, and
  it's already been checked that it parses.
- If it shipped with a **backup voice** (a local engine instead of the default for the language): say
  which one and why the default wasn't available — CapCut not installed, the preflight failed, the
  project saturated. Otherwise the user can't tell why it doesn't sound like the trend.

## Material
- 21 cuts. The subject appears in 3 (14 %).
- Catalog ids used: d03-014, d03-021#1, v360-04…
- Deliberately dropped: … (and why)

## Checked
- [x] `verify.py` clean on every delivered file, with `--spec` and `--script`, and with `text_sync`,
      `voice_image` and `ending` reporting `pass` rather than `skip` (reports next to them)
- [x] each variant opens, develops and **lands**: nothing ends on a cut
- [x] captions on screen while the word is said, and what a line names is what's on screen
- [x] text legible and outside the button zone
- [x] dates and places verified against the metadata
- [x] same-frame comparison between the variants
- [x] narration audible, or the script ships alongside and parses; the voice used is named

## If you want changes
What to touch and where: `workspace/concepts/<concept>/A/variant.json`.
```

No personal paths and no library identifiers in the README. Catalog ids, yes.

## Review checklist (run by the reviewer agent)

**Technical.** `verify.py` runs these for you and is what decides whether the file ships. Reach for the
raw commands when you need to see *where* something is, or to check a file the verifier doesn't cover
(a pre-render, an intermediate):

```bash
ffmpeg -i v.mp4 -vf "blackdetect=d=0.08:pix_th=0.12" -f null -        # black frames
ffmpeg -i v.mp4 -af "silencedetect=n=-45dB:d=0.25" -f null -          # audio gaps
ffmpeg -i v.mp4 -af "loudnorm=print_format=summary" -f null -         # peak below -0.5 dBTP
ffprobe -v error -select_streams a -show_entries stream=index,codec_type -of csv v.mp4  # ONE track
ffprobe -v error -select_streams a:0 -show_entries stream=duration -of csv v.mp4        # = video length
ffmpeg -i v.mp4 -vf "fps=2,scale=216:384,tile=12x6" -frames:v 1 strip.jpg               # and LOOK at it
```

**The arc** — no command detects any of this, and it is what the last round was sent back for:

- [ ] The first second stops the thumb, **and the promise is legible in the first seconds**.
- [ ] The promise is **paid off**, at a real second in the last third.
- [ ] Every beat of the middle adds something. Name the second where it stalls, if it does.
- [ ] **It ends, it doesn't stop.** The close is one of the five that work (`concepts.md`), on a settled
      shot of 0.8-1.5 s with a fade, never a cut mid-movement, mid-word or mid-gesture. The gate's
      `ending` check warns about this; the warning is not decoration.
- [ ] The length fits what it is telling: nothing padded, and nothing truncated to hit a number.
- [ ] Across the round, the durations spread. Variants that all came out the same length are one
      variant with several names.

**Text against sound and picture** — spot-check three captions per variant, with the audio playing:

- [ ] The caption is on screen while that word is being said (0.25 s of tolerance).
- [ ] When a line names something concrete — a place, a dish, a price, a person — that is what's on
      screen right then.
- [ ] With no narration: each text block starts and ends with its own cut.
- [ ] No subtitle has its seconds typed by hand: `sync` over narration (with a fresh `alignment.json`),
      `subs` over a clip's own audio, `seg` when there is neither.

**Content** — no command detects this either, you have to look:

- [ ] There's a mini hook every 3-5 s.
- [ ] Count the cuts with the subject by hand, against the concept's own `subject_quota`.
- [ ] No face mid-word, no odd expression, no forced pose.
- [ ] Two consecutive cuts don't look alike (same scene, same framing, same colour).
- [ ] No caption covers a face or lands in the button strip.
- [ ] No caption drops an orphan word onto its own line.
- [ ] No stamp lasts less than ~0.8 s.
- [ ] Every date, place, price and name is verified.
- [ ] Every caption and narration line is in the requested output language, spelled correctly, with no
      mixing.
- [ ] No document, work screen, licence plate or identifiable minor slipped in.
- [ ] **Compare the same frame between A and B**: if the look or the crop changes the hook, one of them
      is wrong.
- [ ] `variant.py variant.json` rebuilds the variant from scratch, with no deleted temporaries.

## How you hand it to the user

- Send the light copies (`-light`), not the 1080p ones: almost every chat app has a size limit.
- **One file per option when they're tests** (three voices, for example): don't glue them into one audio.
- A short message: what each concept is in one line, how the variants differ, and what decision you need
  from them.
- Say what you couldn't do and why. A stated limit is worth more than a delivery that looks complete.

## When they ask for changes

1. Note the feedback in one line, with a date, in the concept's README. Anything that is a stable
   preference (how much they want to appear, what music they like, which effects they hate) goes where
   the plugin stores preferences, not into one round's README.
2. Produce a full `v2`. Don't overwrite `v1`.
3. If the change is about judgement (not about one cut), check whether a selection rule needs adjusting
   for this user and write it down.
