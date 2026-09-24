# Reference: the macOS Photos app database

Everything here is verified against a real macOS 26 (Tahoe) library, Photos schema 2025-2026. Apple
changes column names between major versions, so **before trusting a column, check it**:

```bash
LIB=~/Pictures/Photos\ Library.photoslibrary
sqlite3 "file:$LIB/database/Photos.sqlite?immutable=1" "PRAGMA table_info(ZASSET);"
```

Never open the database without `mode=ro&immutable=1`. Never write to it.

## Dates: the Core Data epoch

Every date column is **seconds since 1 January 2001 UTC**, not since 1970. The difference is
`978307200`.

```sql
SELECT datetime(ZDATECREATED + 978307200, 'unixepoch') AS utc FROM ZASSET LIMIT 1;
```

The wall-clock time of the place where the photo was taken is that plus `ZTIMEZONEOFFSET` (in seconds,
from `ZADDITIONALASSETATTRIBUTES`):

```sql
SELECT datetime(a.ZDATECREATED + 978307200 + COALESCE(aa.ZTIMEZONEOFFSET, 0), 'unixepoch')
         AS local_time,
       aa.ZTIMEZONENAME
FROM ZASSET a
LEFT JOIN ZADDITIONALASSETATTRIBUTES aa ON aa.ZASSET = a.Z_PK
LIMIT 5;
```

That distinction genuinely matters: between two distant time zones there are 12-15 hours of difference,
enough to make a photo from day 2 show up as day 1 on screen.

## `ZASSET`: one row per photo or video

| Column | What it carries |
|---|---|
| `Z_PK` | internal key; the one the other tables use |
| `ZUUID` | the identifier osxphotos understands and the one that names the thumbnails |
| `ZDATECREATED` | capture date, Core Data epoch, in UTC |
| `ZMODIFICATIONDATE`, `ZADDEDDATE` | modification and import dates |
| `ZKIND` | `0` photo, `1` video |
| `ZFAVORITE` | `1` if starred as a favorite |
| `ZHIDDEN` | `1` if it's in the Hidden album |
| `ZTRASHEDSTATE` | `0` normal, `1` in the trash. **Always filter on `= 0`** |
| `ZLATITUDE`, `ZLONGITUDE` | GPS. With no location it stores `-180.0`, not `NULL` |
| `ZWIDTH`, `ZHEIGHT`, `ZORIENTATION` | dimensions and rotation |
| `ZDURATION` | video length in seconds (`0` on photos) |
| `ZDIRECTORY`, `ZFILENAME` | where the original sits inside `<lib>/originals/` |
| `ZISDETECTEDSCREENSHOT` | `1` if Photos thinks it's a screenshot |
| `ZAVALANCHEUUID` | groups the photos of a **burst**: same value = same burst |
| `ZOVERALLAESTHETICSCORE`, `ZCURATIONSCORE`, `ZICONICSCORE` | scores Photos computes. Useful as a tiebreaker, never as the sole criterion |

`ZAVALANCHEUUID` is gold when choosing material: when a shot is mid-gesture, there is almost always a
better one in the same burst.

```sql
-- The burst siblings of an asset
SELECT ZUUID, datetime(ZDATECREATED + 978307200, 'unixepoch')
FROM ZASSET
WHERE ZAVALANCHEUUID = (SELECT ZAVALANCHEUUID FROM ZASSET WHERE ZUUID = ?)
  AND ZTRASHEDSTATE = 0
ORDER BY ZDATECREATED;
```

## `ZADDITIONALASSETATTRIBUTES`

Joined on `ZADDITIONALASSETATTRIBUTES.ZASSET = ZASSET.Z_PK`.

| Column | What it carries |
|---|---|
| `ZTIMEZONEOFFSET` | seconds from UTC at capture time |
| `ZTIMEZONENAME` | `"America/Mexico_City"`, `"GMT+0800"`… |
| `ZORIGINALFILENAME` | the name it left the camera with |
| `ZORIGINALFILESIZE` | bytes of the original; useful for estimating the download |
| `ZORIGINALWIDTH`, `ZORIGINALHEIGHT` | dimensions before editing |
| `ZEXIFTIMESTAMPSTRING` | the date exactly as it came in the EXIF, as text |
| `ZREVERSELOCATIONDATA` | blob with the place names (see below) |

### `ZREVERSELOCATIONDATA`: getting the place names out

It's an `NSKeyedArchiver` binary plist holding a `PLRevGeoLocationInfo`. Inside, `$objects` carries a
list of `PLRevGeoMapItemAdditionalPlaceInfo`, each with `name`, `placeType` and `area`.

**The trap:** `name` and `placeType` are not values, they're `UID`s pointing at another `$objects` entry.
You have to dereference them or nothing comes out.

Verified `placeType` codes:

| Code | What it is |
|---|---|
| 1 | country |
| 2 | state / region |
| 3 | region |
| 4 | city |
| 5 | district |
| 6 | neighbourhood |
| 14 | postal code |

Duplicate entries come through with `area = 0` (the state abbreviation, the two-letter country code).
Keep the one with the largest `area` per type.

`sources.decode_place()` already does all of this and returns
`{"country": ..., "state": ..., "city": ..., "neighbourhood": ..., "text": "City, Country"}`.

Careful: the names come back **in the language of the place**. A photo in China returns
`北京市, 中国`, not "Beijing, China". If you're going to put the place on screen, translate it into the
output language or ask the user how they want it.

## `ZDETECTEDFACE` and `ZPERSON`: faces and people

`ZDETECTEDFACE` is one row per detected face.

| Column | What it carries |
|---|---|
| `ZASSETFORFACE` | points at `ZASSET.Z_PK` |
| `ZPERSONFORFACE` | points at `ZPERSON.Z_PK` (in older schemas it was called `ZPERSON`) |
| `ZCENTERX`, `ZCENTERY` | face centre, normalized 0..1. **`ZCENTERY` is inverted** |
| `ZSIZE` | face size, normalized against the long side |
| `ZQUALITY`, `ZQUALITYMEASURE` | detection quality |
| `ZBLURSCORE` | how motion-blurred it is |
| `ZHASSMILE`, `ZSMILETYPE` | whether they're smiling |
| `ZISLEFTEYECLOSED`, `ZISRIGHTEYECLOSED` | closed eyes |
| `ZEYESSTATE`, `ZGAZETYPE`, `ZPOSEYAW`, `ZROLL` | gaze direction and head turn |
| `ZFACEEXPRESSIONTYPE` | expression type |
| `ZISINTRASH` | `1` if the face no longer counts |

**The face crop**, which is the operation used most when choosing material:

```python
x = ZCENTERX * width
y = (1 - ZCENTERY) * height     # inverted: 0 at the bottom, 1 at the top
side = ZSIZE * max(width, height)
box = (x - side, y - side, x + side, y + side)   # with a 2x margin, the head fits
```

If you get the feet instead of the face, you forgot to invert `ZCENTERY`.

`ZHASSMILE`, `ZISLEFTEYECLOSED` and `ZBLURSCORE` are good for **pre-selecting**, but not for deciding:
you have to look at the crop. Photos marks plenty of half-formed gestures as a smile.

### People

`ZPERSON` stores the people the user has named. `ZFULLNAME` is the full name, `ZDISPLAYNAME` the short
one; unnamed people have both as `NULL`.

```sql
-- Named people, most to fewest photos
SELECT COALESCE(p.ZFULLNAME, p.ZDISPLAYNAME) AS name,
       COUNT(DISTINCT d.ZASSETFORFACE) AS photos
FROM ZPERSON p
JOIN ZDETECTEDFACE d ON d.ZPERSONFORFACE = p.Z_PK
WHERE COALESCE(p.ZFULLNAME, p.ZDISPLAYNAME) IS NOT NULL
GROUP BY p.Z_PK
ORDER BY photos DESC;
```

A person's `Z_PK` is stable within a library but **means nothing in another one**. Never hard-code it:
look it up by name on every run.

## `ZINTERNALRESOURCE`: what's downloaded and what's in iCloud

| Column | What it carries |
|---|---|
| `ZASSET` | points at `ZASSET.Z_PK` |
| `ZRESOURCETYPE` | `0` is the original; the rest are derived versions |
| `ZLOCALAVAILABILITY` | `1` it's on disk; any other value, iCloud only |
| `ZDATALENGTH` | bytes of that version |

```sql
-- How much would have to be downloaded for a date range
SELECT COUNT(*) AS missing,
       ROUND(SUM(r.ZDATALENGTH) / 1073741824.0, 2) AS gb
FROM ZASSET a
JOIN ZINTERNALRESOURCE r ON r.ZASSET = a.Z_PK AND r.ZRESOURCETYPE = 0
WHERE a.ZTRASHEDSTATE = 0
  AND r.ZLOCALAVAILABILITY <> 1
  AND a.ZDATECREATED BETWEEN
        (strftime('%s','2026-08-01') - 978307200) AND
        (strftime('%s','2026-08-21') - 978307200);
```

## Thumbnails on disk

```
<library>/resources/derivatives/<first letter of the UUID>/
    <UUID>_1_105_c.jpeg     ← the big one, ~1200 px on the long side
    <UUID>_1_102_o.jpeg     ← a small one
    <UUID>.THM              ← a video's cover frame
<library>/resources/derivatives/masters/<letter>/
    <UUID>_4_5005_c.jpeg    ← a preview, usually even smaller
```

They exist even when the original is iCloud-only. They're the way to review hundreds of photos without
spending network. `sources._thumbnail_paths()` looks for them in that order.

Originals that are actually downloaded live at:

```
<library>/originals/<ZASSET.ZDIRECTORY>/<ZASSET.ZFILENAME>
```

## Starter query

Copy and paste this to see at a glance what's in a range:

```bash
LIB=~/Pictures/Photos\ Library.photoslibrary
sqlite3 "file:$LIB/database/Photos.sqlite?immutable=1" <<'SQL'
.mode column
.headers on
SELECT date(a.ZDATECREATED + 978307200 + COALESCE(aa.ZTIMEZONEOFFSET,0), 'unixepoch') AS day,
       COUNT(*) AS n,
       SUM(a.ZKIND = 1) AS videos,
       SUM(a.ZFAVORITE = 1) AS favorites
FROM ZASSET a
LEFT JOIN ZADDITIONALASSETATTRIBUTES aa ON aa.ZASSET = a.Z_PK
WHERE a.ZTRASHEDSTATE = 0
  AND COALESCE(a.ZHIDDEN, 0) = 0
  AND a.ZDATECREATED BETWEEN
        (strftime('%s','2026-08-01') - 978307200) AND
        (strftime('%s','2026-08-21') - 978307200)
GROUP BY day
ORDER BY day;
SQL
```

## Things that change between macOS versions

If something breaks after an update, start here:

- `ZDETECTEDFACE.ZPERSONFORFACE` was called `ZPERSON` in earlier schemas. `sources.py` detects which one
  exists with `PRAGMA table_info`.
- `ZASSET.ZTRASHEDSTATE` and `ZASSET.ZHIDDEN` have changed names; verify before assuming.
- The `resources/derivatives/` paths and the `_1_105_c` suffixes have varied between major versions.
  Search for the file, don't assume it.
- When something gets hard, **osxphotos has already solved these differences**: `osxphotos query --json`
  is slower but far more stable than reading the database by hand. For large inventories the database is
  better; for odd cases, osxphotos.
