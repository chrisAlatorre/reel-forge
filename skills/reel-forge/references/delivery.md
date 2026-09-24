# Delivery and verification

## Structure

```
<root>/<project>/deliveries/v1/<concept>/
  README.md
  <concept>-A.mp4              1080x1920, crf 22, NO copyrighted music
  <concept>-A-preview.mp4      with the song, just so they can hear it
  <concept>-A-light.mp4        720p, crf 24, 4-11 MB, for sending over chat
  <concept>-B.mp4  ...
  voice-script.txt             if any variant is narrated
```

Root: `REEL_FORGE_HOME` if set; otherwise macOS `~/Movies/reel-forge`, Linux `~/Videos/reel-forge`,
Windows `%USERPROFILE%\Videos\reel-forge`. `REEL_FORGE_OUTPUT` overrides the `deliveries/` path.

- **One round, one version.** Changes come out as a full `v2`. `v1` is never touched.
- **One README per concept**, with both variants inside. Not one per agent.
- The workspace (`workspace/`) can be deleted entirely and rebuilt by running the `build.py` scripts.

## The concept's README

Written **in the output language** — it's what the user reads before posting. The structure stays the
same in any language:

```markdown
# <concept name>

**Hook:** what you see and what you read in the first second.
**Promise:** what you're telling the viewer.

| Variant | Duration | What makes it different | File |
|---|---|---|---|
| A | 34 s | natural sound, no music | concept-A.mp4 |
| B | 15 s | narrated, cut to the beat | concept-B.mp4 |

## To post it
- Official sound: "<title>" by <artist> (<bpm> BPM, measured). The clean MP4 ships without music: add
  it in the app.
- Suggested tags: #… (3-5, one niche)
- Suggested description: one line.
- If it's narrated and shipped without voice: `voice-script.txt` carries each line's entry second.

## Material
- 21 cuts. The subject appears in 3 (14 %).
- Catalog ids used: d03-014, d03-021#1, v360-04…
- Deliberately dropped: … (and why)

## Checked
- [x] no black frames, no audio gaps, peak below -0.5 dBTP
- [x] text legible and outside the button zone
- [x] dates and places verified against the metadata
- [x] same-frame comparison between A and B

## If you want changes
What to touch and where: `workspace/concepts/<concept>/A/build.py`.
```

No personal paths and no library identifiers in the README. Catalog ids, yes.

## Review checklist (run by the reviewer agent)

**Technical**

```bash
ffmpeg -i v.mp4 -vf "blackdetect=d=0.08:pix_th=0.12" -f null -        # black frames
ffmpeg -i v.mp4 -af "silencedetect=n=-45dB:d=0.25" -f null -          # audio gaps
ffmpeg -i v.mp4 -af "loudnorm=print_format=summary" -f null -         # peak below -0.5 dBTP
ffprobe -v error -select_streams a -show_entries stream=index,codec_type -of csv v.mp4  # ONE track
ffprobe -v error -select_streams a:0 -show_entries stream=duration -of csv v.mp4        # = video length
ffmpeg -i v.mp4 -vf "fps=2,scale=216:384,tile=12x6" -frames:v 1 strip.jpg               # and LOOK at it
```

**Content** — no command detects this, you have to look:

- [ ] The first second stops the thumb.
- [ ] There's a mini hook every 3-5 s.
- [ ] Count the cuts with the subject by hand: half or fewer?
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
- [ ] The `build.py` rebuilds the variant from scratch, with no deleted temporaries.

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
