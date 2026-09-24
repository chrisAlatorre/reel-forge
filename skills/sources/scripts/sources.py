# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "pillow-heif"]
# ///
"""reel-forge's shared library for reading material sources.

Two sources, one single item shape:

- `apple_photos`: reads the macOS Photos app database READ-ONLY (`mode=ro&immutable=1`).
  It never writes anything and never touches the library.
- `folder`: walks an ordinary folder (any operating system) and pulls dates and GPS from EXIF.

Every function returns dictionaries with the same keys (see `empty_item`), so that
`inventory.py` and `validate_dates.py` treat both sources identically.

It isn't imported directly: the scripts next to it do
`sys.path.insert(0, str(Path(__file__).parent))` and then `import sources`.
"""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Core Data counts seconds from 1 January 2001 UTC, not from 1970.
COREDATA_EPOCH = 978307200

# Extensions we consider usable material.
EXT_PHOTO = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".dng", ".webp", ".avif"}
EXT_VIDEO = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".hevc"}
EXT_360 = {".insv", ".insp", ".vr", ".360"}
EXT_ALL = EXT_PHOTO | EXT_VIDEO | EXT_360

# `placeType` codes inside Photos' reverse-geocoding plist.
# These are the ones verified against real libraries; the rest are ignored.
PLACE_TYPE = {
    1: "country",
    2: "state",
    3: "region",
    4: "city",
    5: "district",
    6: "neighbourhood",
    14: "postal_code",
}

# Default path of the Photos library on macOS. Change it with REEL_FORGE_LIBRARY.
DEFAULT_LIBRARY = "~/Pictures/Photos Library.photoslibrary"
ENV_LIBRARY = "REEL_FORGE_LIBRARY"
# The user's material folders, separated by ':' (or ';' on Windows).
ENV_SOURCES = "REEL_FORGE_SOURCES"


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def from_coredata(value, offset_s=None):
    """Converts a Core Data timestamp into a datetime.

    `value` is the instant in UTC. If `offset_s` is passed (the asset's `ZTIMEZONEOFFSET`), it
    returns the **wall-clock time of the place** where the photo was taken, which is the one
    the user remembers. Without an offset, it returns UTC.
    """
    if value is None:
        return None
    try:
        base = datetime.fromtimestamp(float(value) + COREDATA_EPOCH, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None
    if offset_s is None:
        return base
    return base.astimezone(timezone(timedelta(seconds=int(offset_s))))


def iso(dt):
    return dt.isoformat(timespec="seconds") if dt else None


def parse_date(text, end_of_day=False):
    """Accepts 2026-08-01, 2026-08-01T14:30 or 2026-08-01 14:30."""
    if not text:
        return None
    t = text.strip().replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(t, fmt)
            if fmt == "%Y-%m-%d" and end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"I couldn't read the date '{text}'. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM")


def naive(dt):
    """Strips the time zone while keeping the wall-clock time, so dates from different sources
    can be compared without an offset inventing hours of difference."""
    return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt


# ---------------------------------------------------------------------------
# The item shape
# ---------------------------------------------------------------------------


def empty_item():
    """The keys every item carries, whatever it came from."""
    return {
        "id": None,              # Photos uuid, or a relative path inside a folder
        "source": None,          # "apple-photos" | "folder"
        "name": None,            # original file name
        "type": None,            # "photo" | "video" | "360"
        "date": None,            # ISO, the place's wall-clock time when it is known
        "date_utc": None,        # ISO in UTC, or None if it can't be known
        "date_origin": None,     # "exif" | "photos-db" | "file-name" | "mtime" | None
        "tz": None,              # "America/Mexico_City", "GMT+0800", ...
        "lat": None,
        "lon": None,
        "place": None,           # "City, Country", already resolved (Apple Photos only)
        "place_detail": None,    # dict with country/state/city/neighbourhood
        "favorite": False,
        "faces": 0,
        "people": [],            # names confirmed in Photos
        "width": None,
        "height": None,
        "duration_s": None,
        "bytes": None,
        "local": None,           # True if the original is on disk
        "path": None,            # path of the original if it is local
        "thumbnail": None,       # path of the already generated thumbnail (Apple Photos)
        "hidden": False,
        "screenshot": False,
    }


def classify_ext(ext):
    ext = ext.lower()
    if ext in EXT_360:
        return "360"
    if ext in EXT_VIDEO:
        return "video"
    if ext in EXT_PHOTO:
        return "photo"
    return None


# ---------------------------------------------------------------------------
# Apple Photos (macOS only)
# ---------------------------------------------------------------------------


class LibraryUnavailable(RuntimeError):
    pass


def library_path(path=None):
    return Path(path or os.environ.get(ENV_LIBRARY) or DEFAULT_LIBRARY).expanduser()


def env_sources():
    """Folders the user configured in REEL_FORGE_SOURCES."""
    raw = os.environ.get(ENV_SOURCES, "")
    sep = ";" if os.name == "nt" else ":"
    return [t.strip() for t in raw.split(sep) if t.strip()]


def open_library(path=None, copy=False):
    """Opens `Photos.sqlite` read-only.

    - By default it uses `mode=ro&immutable=1`: SQLite doesn't even open the file for writing
      and **doesn't read the WAL**. Damaging the library is impossible, at the cost of changes
      from the last few minutes (photos just imported, favorites just starred) possibly not
      showing up.
    - With `copy=True`, `Photos.sqlite`, `-wal` and `-shm` get copied to a temporary folder and
      that copy is opened with `mode=ro`. There you do see everything up to date, but the
      database can be several GB.

    Returns `(connection, library_path, temp_folder_or_None)`.
    """
    lib = library_path(path)
    db = lib / "database" / "Photos.sqlite"
    if not db.exists():
        raise LibraryUnavailable(
            f"I couldn't find {db}.\n"
            "On macOS the normal path is ~/Pictures/Photos Library.photoslibrary.\n"
            f"If yours is somewhere else, export {ENV_LIBRARY} with its path.\n"
            "Outside macOS this source doesn't exist: use a folder."
        )

    temp = None
    if copy:
        temp = Path(tempfile.mkdtemp(prefix="reel-forge-library-"))
        for suffix in ("", "-wal", "-shm"):
            origin = Path(str(db) + suffix)
            if origin.exists():
                shutil.copy2(origin, temp / origin.name)
        target = temp / db.name
        uri = f"file:{target}?mode=ro"
    else:
        uri = f"file:{db}?mode=ro&immutable=1"

    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as e:
        raise LibraryUnavailable(
            f"I couldn't open the Photos database ({e}).\n"
            "It is almost always a permission: the Terminal (or whatever process runs this) needs\n"
            "Full Disk Access in System Settings → Privacy & Security."
        ) from e
    con.row_factory = sqlite3.Row
    return con, lib, temp


def _column_exists(con, table, column):
    return any(f["name"] == column for f in con.execute(f"PRAGMA table_info({table})"))


def decode_place(blob):
    """Pulls the place names out of the `ZREVERSELOCATIONDATA` blob.

    It is an NSKeyedArchiver plist holding a `PLRevGeoLocationInfo`. Inside there is a list of
    `PLRevGeoMapItemAdditionalPlaceInfo`, each with `name` and `placeType` (1 country, 2 state,
    4 city, 6 neighbourhood, 14 postal code).
    """
    if not blob:
        return None
    try:
        plist = plistlib.loads(blob)
        objects = plist["$objects"]
    except Exception:
        return None

    def deref(value):
        """The archive's fields are UIDs pointing at another `$objects` entry. `name` points at
        a string and `placeType` at an integer."""
        if hasattr(value, "data"):
            try:
                value = objects[value.data]
            except IndexError:
                return None
        return None if value == "$null" else value

    detail = {}
    for obj in objects:
        if not isinstance(obj, dict) or "placeType" not in obj or "name" not in obj:
            continue
        kind = PLACE_TYPE.get(deref(obj["placeType"]))
        name = deref(obj["name"])
        if not isinstance(name, str):
            name = None
        # The largest `area` wins: there are duplicate entries (a state abbreviation, a country
        # code) that come through with area 0.
        if kind and name:
            area = obj.get("area") or 0
            if kind not in detail or area > detail[kind][1]:
                detail[kind] = (name, area)

    detail = {k: v[0] for k, v in detail.items()}
    if not detail:
        return None
    parts = [detail.get("city") or detail.get("neighbourhood"), detail.get("country")]
    detail["text"] = ", ".join(p for p in parts if p) or None
    return detail


def _thumbnail_paths(lib, uuid):
    """Thumbnails Photos already generated. They're enough for contact sheets and for checking
    faces without downloading a single original from iCloud."""
    if not uuid:
        return []
    initial = uuid[0].upper()
    base = lib / "resources" / "derivatives"
    candidates = [
        base / initial / f"{uuid}_1_105_c.jpeg",     # the big one (~1200 px)
        base / initial / f"{uuid}_1_102_o.jpeg",
        base / "masters" / initial / f"{uuid}_4_5005_c.jpeg",
        base / initial / f"{uuid}.THM",              # a video's cover frame
    ]
    return [c for c in candidates if c.exists()]


def read_apple_photos(date_from=None, date_to=None, lib_path=None, copy=False,
                      include_hidden=False, include_screenshots=True,
                      favorites_only=False, person=None):
    """Reads assets from the Photos app. Returns (item_list, metadata)."""
    con, lib, temp = open_library(lib_path, copy=copy)
    try:
        has_new_column = _column_exists(con, "ZDETECTEDFACE", "ZPERSONFORFACE")
        person_col = "ZPERSONFORFACE" if has_new_column else "ZPERSON"

        where = ["a.ZTRASHEDSTATE = 0"]
        params = []
        if not include_hidden:
            where.append("COALESCE(a.ZHIDDEN, 0) = 0")
        if favorites_only:
            where.append("a.ZFAVORITE = 1")
        if date_from:
            where.append("a.ZDATECREATED >= ?")
            params.append(date_from.timestamp() - COREDATA_EPOCH)
        if date_to:
            where.append("a.ZDATECREATED <= ?")
            params.append(date_to.timestamp() - COREDATA_EPOCH)

        sql = f"""
            SELECT a.Z_PK, a.ZUUID, a.ZDATECREATED, a.ZKIND, a.ZFAVORITE, a.ZHIDDEN,
                   a.ZLATITUDE, a.ZLONGITUDE, a.ZWIDTH, a.ZHEIGHT, a.ZDURATION,
                   a.ZDIRECTORY, a.ZFILENAME, a.ZISDETECTEDSCREENSHOT,
                   aa.ZTIMEZONEOFFSET, aa.ZTIMEZONENAME, aa.ZORIGINALFILENAME,
                   aa.ZORIGINALFILESIZE, aa.ZREVERSELOCATIONDATA
            FROM ZASSET a
            LEFT JOIN ZADDITIONALASSETATTRIBUTES aa ON aa.ZASSET = a.Z_PK
            WHERE {' AND '.join(where)}
            ORDER BY a.ZDATECREATED
        """
        rows = con.execute(sql, params).fetchall()

        pks = [f["Z_PK"] for f in rows]
        faces = _faces_per_asset(con, pks, person_col)
        local = _local_originals(con, pks)

        if person:
            person_pks = _assets_of_person(con, person, person_col)
            rows = [f for f in rows if f["Z_PK"] in person_pks]

        items = []
        place_cache = {}
        for f in rows:
            ext = Path(f["ZFILENAME"] or "").suffix
            kind = classify_ext(ext) or ("video" if f["ZKIND"] == 1 else "photo")
            screenshot = bool(f["ZISDETECTEDSCREENSHOT"])
            if screenshot and not include_screenshots:
                continue

            offset = f["ZTIMEZONEOFFSET"]
            local_date = from_coredata(f["ZDATECREATED"], offset)
            utc_date = from_coredata(f["ZDATECREATED"])

            blob = f["ZREVERSELOCATIONDATA"]
            # Many assets from the same place carry the same blob: cache it by hash so we don't
            # parse 5000 identical plists.
            key = hashlib.blake2b(blob, digest_size=16).digest() if blob else None
            if key is not None and key not in place_cache:
                place_cache[key] = decode_place(blob)
            detail = place_cache.get(key)

            lat, lon = f["ZLATITUDE"], f["ZLONGITUDE"]
            # Photos stores -180/-180 when there is no location.
            if lat is None or lat <= -180 or (lat == 0 and lon == 0):
                lat = lon = None

            face_info = faces.get(f["Z_PK"], {"n": 0, "people": []})
            is_local, original_bytes = local.get(f["Z_PK"], (False, None))
            uuid = f["ZUUID"]
            thumbnails = _thumbnail_paths(lib, uuid)

            original_path = None
            if f["ZDIRECTORY"] and f["ZFILENAME"]:
                p = lib / "originals" / f["ZDIRECTORY"] / f["ZFILENAME"]
                original_path = str(p) if p.exists() else None

            it = empty_item()
            it.update({
                "id": uuid,
                "source": "apple-photos",
                "name": f["ZORIGINALFILENAME"] or f["ZFILENAME"],
                "type": kind,
                "date": iso(local_date),
                "date_utc": iso(utc_date),
                "date_origin": "photos-db",
                "tz": f["ZTIMEZONENAME"],
                "lat": lat,
                "lon": lon,
                "place": (detail or {}).get("text"),
                "place_detail": detail,
                "favorite": bool(f["ZFAVORITE"]),
                "faces": face_info["n"],
                "people": face_info["people"],
                "width": f["ZWIDTH"],
                "height": f["ZHEIGHT"],
                "duration_s": round(f["ZDURATION"], 2) if f["ZDURATION"] else None,
                "bytes": int(f["ZORIGINALFILESIZE"]) if f["ZORIGINALFILESIZE"] else original_bytes,
                "local": is_local or original_path is not None,
                "path": original_path,
                "thumbnail": str(thumbnails[0]) if thumbnails else None,
                "hidden": bool(f["ZHIDDEN"]),
                "screenshot": screenshot,
            })
            items.append(it)

        meta = {
            "type": "apple-photos",
            "library": str(lib),
            "read_mode": "temporary copy (mode=ro)" if copy else "mode=ro&immutable=1",
            "wal_warning": None if copy else (
                "With immutable=1 the WAL isn't read: changes from the last few minutes may be "
                "missing. Use --copy-db if you just imported or starred something."
            ),
        }
        return items, meta
    finally:
        con.close()
        if temp:
            shutil.rmtree(temp, ignore_errors=True)


def _faces_per_asset(con, pks, person_col):
    """How many faces each asset carries and which people already have a name.

    `ZDETECTEDFACE` stores each face's centre in normalized 0..1 coordinates with `ZCENTERX` /
    `ZCENTERY` and the size in `ZSIZE`. **`ZCENTERY` is inverted** (0 at the bottom, 1 at the
    top): to crop over an image you have to use `y = (1 - ZCENTERY) * height`.
    """
    result = {}
    if not pks:
        return result
    for batch in _in_batches(pks, 900):
        marks = ",".join("?" * len(batch))
        sql = f"""
            SELECT d.ZASSETFORFACE AS asset, COUNT(*) AS n,
                   GROUP_CONCAT(DISTINCT p.ZFULLNAME) AS names
            FROM ZDETECTEDFACE d
            LEFT JOIN ZPERSON p ON p.Z_PK = d.{person_col}
            WHERE d.ZASSETFORFACE IN ({marks})
              AND COALESCE(d.ZISINTRASH, 0) = 0
            GROUP BY d.ZASSETFORFACE
        """
        for row in con.execute(sql, batch):
            names = [n for n in (row["names"] or "").split(",") if n]
            result[row["asset"]] = {"n": row["n"], "people": sorted(set(names))}
    return result


def _assets_of_person(con, name, person_col):
    sql = f"""
        SELECT DISTINCT d.ZASSETFORFACE AS asset
        FROM ZDETECTEDFACE d
        JOIN ZPERSON p ON p.Z_PK = d.{person_col}
        WHERE (p.ZFULLNAME = ? OR p.ZDISPLAYNAME = ?)
    """
    return {f["asset"] for f in con.execute(sql, (name, name))}


def _local_originals(con, pks):
    """`ZINTERNALRESOURCE` says which versions are on disk.

    `ZRESOURCETYPE = 0` is the original; `ZLOCALAVAILABILITY = 1` means it is downloaded.
    Everything else lives only in iCloud and has to be fetched.
    """
    result = {}
    if not pks:
        return result
    for batch in _in_batches(pks, 900):
        marks = ",".join("?" * len(batch))
        sql = f"""
            SELECT ZASSET AS asset,
                   MAX(CASE WHEN ZLOCALAVAILABILITY = 1 THEN 1 ELSE 0 END) AS local,
                   MAX(ZDATALENGTH) AS bytes
            FROM ZINTERNALRESOURCE
            WHERE ZASSET IN ({marks}) AND ZRESOURCETYPE = 0
            GROUP BY ZASSET
        """
        for row in con.execute(sql, batch):
            result[row["asset"]] = (bool(row["local"]), row["bytes"])
    return result


def _in_batches(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def library_people(lib_path=None, copy=False, minimum=1):
    """The list of named people, most to fewest photos. Useful so the user can say who to follow
    without having to guess the exact name."""
    con, _lib, temp = open_library(lib_path, copy=copy)
    try:
        col = "ZPERSONFORFACE" if _column_exists(con, "ZDETECTEDFACE", "ZPERSONFORFACE") else "ZPERSON"
        sql = f"""
            SELECT p.Z_PK, COALESCE(p.ZFULLNAME, p.ZDISPLAYNAME) AS name,
                   COUNT(DISTINCT d.ZASSETFORFACE) AS n
            FROM ZPERSON p
            JOIN ZDETECTEDFACE d ON d.{col} = p.Z_PK
            WHERE COALESCE(p.ZFULLNAME, p.ZDISPLAYNAME) IS NOT NULL
            GROUP BY p.Z_PK HAVING n >= ?
            ORDER BY n DESC
        """
        return [{"pk": f["Z_PK"], "name": f["name"], "photos": f["n"]}
                for f in con.execute(sql, (minimum,))]
    finally:
        con.close()
        if temp:
            shutil.rmtree(temp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Ordinary folders (any operating system)
# ---------------------------------------------------------------------------


def _exif_pillow(path):
    """Date, size and GPS with Pillow. Works for JPEG, PNG, TIFF and HEIC (with pillow-heif
    registered). It doesn't read video."""
    try:
        from PIL import Image, ExifTags
    except ImportError:
        return {}
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass

    data = {}
    try:
        with Image.open(path) as img:
            data["width"], data["height"] = img.size
            exif = img.getexif()
            if not exif:
                return data
            flat = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
            ifd = exif.get_ifd(0x8769)  # ExifIFD
            flat.update({ExifTags.TAGS.get(k, k): v for k, v in ifd.items()})
            offsets = ("OffsetTimeOriginal", "OffsetTimeDigitized", "OffsetTime")
            for key, off_key in zip(("DateTimeOriginal", "DateTimeDigitized", "DateTime"), offsets):
                if flat.get(key):
                    try:
                        dt = datetime.strptime(str(flat[key]), "%Y:%m:%d %H:%M:%S")
                    except ValueError:
                        continue
                    # EXIF keeps the offset in a separate tag; without it the date is a bare
                    # wall clock and cannot be compared with a video's.
                    tz = _exif_offset(flat.get(off_key) or flat.get("OffsetTime"))
                    data["date"] = dt.replace(tzinfo=tz) if tz else dt
                    data["date_origin"] = "exif"
                    break
            gps = exif.get_ifd(0x8825)
            if gps:
                data.update(_gps_pillow(gps))
    except Exception:
        return data
    return data


def _exif_offset(text):
    """'+08:00' / '-0600' -> a tzinfo. Returns None when the tag is missing or unreadable."""
    if not text:
        return None
    t = str(text).strip().replace(":", "")
    if len(t) == 5 and t[0] in "+-" and t[1:].isdigit():
        sign = -1 if t[0] == "-" else 1
        return timezone(sign * timedelta(hours=int(t[1:3]), minutes=int(t[3:5])))
    return None


def _gps_pillow(gps):
    from PIL import ExifTags
    g = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps.items()}

    def degrees(value, ref, negatives):
        try:
            d, m, s = (float(x) for x in value)
        except (TypeError, ValueError):
            return None
        dec = d + m / 60 + s / 3600
        return -dec if str(ref).upper() in negatives else dec

    lat = degrees(g.get("GPSLatitude"), g.get("GPSLatitudeRef"), {"S"})
    lon = degrees(g.get("GPSLongitude"), g.get("GPSLongitudeRef"), {"W"})
    if lat is None or lon is None:
        return {}
    return {"lat": round(lat, 6), "lon": round(lon, 6)}


def _ffprobe(path):
    """Duration, size, creation date and GPS of a video. Needs ffprobe (ships with ffmpeg). If
    it isn't installed, it returns {} without complaining."""
    if not shutil.which("ffprobe"):
        return {}
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        info = json.loads(out.stdout or "{}")
    except Exception:
        return {}

    data = {}
    fmt = info.get("format", {})
    if fmt.get("duration"):
        try:
            data["duration_s"] = round(float(fmt["duration"]), 2)
        except ValueError:
            pass
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    # Order matters: Apple's `creationdate` carries the local wall clock plus its offset,
    # while `creation_time` is the same instant in UTC. Reading UTC first makes an iPhone clip
    # look hours away from a photo taken beside it.
    for key in ("com.apple.quicktime.creationdate", "creation_time", "date"):
        if tags.get(key):
            try:
                data["date"] = datetime.fromisoformat(str(tags[key]).replace("Z", "+00:00"))
                data["date_origin"] = "exif"
                break
            except ValueError:
                continue
    # Apple stores GPS as "+19.4326-099.1332/"
    raw = tags.get("com.apple.quicktime.location.iso6709") or tags.get("location")
    if raw:
        data.update(_iso6709(str(raw)))
    for st in info.get("streams", []):
        if st.get("codec_type") == "video":
            data.setdefault("width", st.get("width"))
            data.setdefault("height", st.get("height"))
            break
    return data


def _iso6709(text):
    import re
    m = re.match(r"([+-]\d+\.?\d*)([+-]\d+\.?\d*)", text.strip())
    if not m:
        return {}
    return {"lat": float(m.group(1)), "lon": float(m.group(2))}


def _exiftool(path):
    """Last resort: exiftool reads odd formats (.insv, .dng, .360). Optional."""
    if not shutil.which("exiftool"):
        return {}
    cmd = ["exiftool", "-j", "-n", "-DateTimeOriginal", "-CreateDate",
           "-GPSLatitude", "-GPSLongitude", "-ImageWidth", "-ImageHeight",
           "-Duration", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        raw = json.loads(out.stdout or "[]")
    except Exception:
        return {}
    if not raw:
        return {}
    d = raw[0]
    data = {}
    for key in ("DateTimeOriginal", "CreateDate"):
        if d.get(key):
            try:
                data["date"] = datetime.strptime(str(d[key])[:19], "%Y:%m:%d %H:%M:%S")
                data["date_origin"] = "exif"
                break
            except ValueError:
                continue
    if d.get("GPSLatitude") is not None and d.get("GPSLongitude") is not None:
        data["lat"], data["lon"] = float(d["GPSLatitude"]), float(d["GPSLongitude"])
    for src_key, dst_key in (("ImageWidth", "width"), ("ImageHeight", "height"), ("Duration", "duration_s")):
        if d.get(src_key):
            data[dst_key] = d[src_key]
    return data


def _date_from_name(name):
    """Many cameras put the date in the file name: IMG_20260815_143012.jpg,
    VID_20240115_180230_00_012.insv, PXL_20260815_203012345.jpg, 2026-08-15 14.30.12.jpg.
    It's the last safety net when there is no EXIF."""
    import re
    patterns = [
        (r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})[-_ T]?(\d{2})[-_.:]?(\d{2})[-_.:]?(\d{2})", 6),
        (r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", 3),
    ]
    for pattern, groups in patterns:
        m = re.search(pattern, name)
        if not m:
            continue
        try:
            parts = [int(x) for x in m.groups()[:groups]]
            if groups == 3:
                parts += [12, 0, 0]
            return datetime(*parts)
        except ValueError:
            continue
    return None


def read_folder(root, date_from=None, date_to=None, recursive=True, use_exiftool=False):
    """Walks a folder and builds the items. Returns (items, metadata)."""
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"The folder {root} doesn't exist")

    pattern = "**/*" if recursive else "*"
    items, skipped = [], 0
    for path in sorted(root.glob(pattern)):
        if not path.is_file() or path.name.startswith("."):
            continue
        kind = classify_ext(path.suffix)
        if kind is None:
            skipped += 1
            continue

        if kind in ("video", "360"):
            data = _ffprobe(path)
            if not data.get("date") or use_exiftool:
                data = {**_exiftool(path), **data}
        else:
            data = _exif_pillow(path)
            if not data.get("date") and use_exiftool:
                data = {**_exiftool(path), **data}

        date = data.get("date")
        origin = data.get("date_origin")
        if not date:
            date = _date_from_name(path.name)
            origin = "file-name" if date else None
        if not date:
            # mtime is the least trustworthy: a copy with `cp` rewrites it.
            date = datetime.fromtimestamp(path.stat().st_mtime)
            origin = "mtime"

        if date_from and naive(date) < naive(date_from):
            continue
        if date_to and naive(date) > naive(date_to):
            continue

        it = empty_item()
        it.update({
            "id": str(path.relative_to(root)),
            "source": "folder",
            "name": path.name,
            "type": kind,
            "date": iso(date),
            "date_utc": iso(date.astimezone(timezone.utc)) if date.tzinfo else None,
            "date_origin": origin,
            "lat": data.get("lat"),
            "lon": data.get("lon"),
            "width": data.get("width"),
            "height": data.get("height"),
            "duration_s": data.get("duration_s"),
            "bytes": path.stat().st_size,
            "local": True,
            "path": str(path),
        })
        items.append(it)

    # Sorting the ISO strings would put "…T19:57:37" after "…T03:21:46+00:00" by text alone;
    # compare the actual wall clock instead.
    items.sort(key=lambda x: naive(datetime.fromisoformat(x["date"])) if x["date"] else datetime.min)
    meta = {
        "type": "folder",
        "root": str(root),
        "ignored_files": skipped,
        "tools": {
            "ffprobe": bool(shutil.which("ffprobe")),
            "exiftool": bool(shutil.which("exiftool")),
        },
    }
    return items, meta


# ---------------------------------------------------------------------------
# Sessions, places and date suspicions
# ---------------------------------------------------------------------------


def _dt(item):
    f = item.get("date")
    if not f:
        return None
    try:
        return naive(datetime.fromisoformat(f))
    except ValueError:
        return None


def group_sessions(items, gap_min=90):
    """Splits the list into sessions: every gap longer than `gap_min` minutes opens a new one.
    It's the natural unit for counting a trip's "moments" without depending on calendar days."""
    dated = sorted([i for i in items if _dt(i)], key=_dt)
    sessions, current = [], []
    limit = timedelta(minutes=gap_min)

    for it in dated:
        if current and _dt(it) - _dt(current[-1]) > limit:
            sessions.append(current)
            current = []
        current.append(it)
    if current:
        sessions.append(current)

    out = []
    for n, group in enumerate(sessions, 1):
        places = _counts(g.get("place") for g in group)
        out.append({
            "session": n,
            "start": group[0]["date"],
            "end": group[-1]["date"],
            "duration_min": round((_dt(group[-1]) - _dt(group[0])).total_seconds() / 60, 1),
            "n": len(group),
            "photos": sum(1 for g in group if g["type"] == "photo"),
            "videos": sum(1 for g in group if g["type"] in ("video", "360")),
            "favorites": sum(1 for g in group if g["favorite"]),
            "with_faces": sum(1 for g in group if g["faces"]),
            "place": places[0][0] if places else None,
            "ids": [g["id"] for g in group],
        })
    return out


def _counts(values):
    from collections import Counter
    c = Counter(v for v in values if v)
    return c.most_common()


def place_summary(items):
    from collections import defaultdict
    by_place = defaultdict(list)
    for it in items:
        if it.get("place"):
            by_place[it["place"]].append(it)
    out = []
    for place, group in by_place.items():
        dates = sorted(f for f in (g["date"] for g in group) if f)
        out.append({
            "place": place,
            "n": len(group),
            "first": dates[0] if dates else None,
            "last": dates[-1] if dates else None,
        })
    out.sort(key=lambda x: -x["n"])
    return out


def _plural(n, singular, plural):
    return f"{n} {singular}" if n == 1 else f"{n} {plural}"


def detect_suspicions(items, min_year=2000, far_days=180, gap_min=90):
    """Finds broken dates and groups them into cases the user can confirm in one go. Returns a
    list of cases, each with its proposed correction.

    The cases it detects:
      - `no_date`: there is no EXIF and nothing else to get it from.
      - `impossible_date`: a year before `min_year` or in the future. The classic external
        camera (GoPro, Insta360, DSLR) that lost its clock battery and started at 1970 or 2014.
      - `distant_batch`: a group of files whose date sits more than `far_days` away from the
        material's median, but which are coherent among themselves. Almost always a single
        badly set camera.
      - `mtime_only`: the date comes from the file's modification time, which gets rewritten on
        copy. Not trustworthy.
      - `time_offset`: a group dated the same day as the rest but shifted by an almost whole
        number of hours. A badly set time zone.
    """
    now = datetime.now()
    dated = [i for i in items if _dt(i)]
    cases = []

    no_date = [i for i in items if not _dt(i) or i.get("date_origin") is None]
    if no_date:
        cases.append({
            "case": "no_date",
            "n": len(no_date),
            "ids": [i["id"] for i in no_date],
            "examples": [i["name"] for i in no_date[:5]],
            "message": _plural(len(no_date), "file has", "files have") + " no capture date.",
            "proposal": {"action": "assign_date", "value": None},
        })

    mtime_only = [i for i in items if i.get("date_origin") == "mtime"]
    if mtime_only:
        cases.append({
            "case": "mtime_only",
            "n": len(mtime_only),
            "ids": [i["id"] for i in mtime_only],
            "examples": [i["name"] for i in mtime_only[:5]],
            "message": (_plural(len(mtime_only), "file only has", "files only have") +
                        " the filesystem modification date, which changes when they get copied. "
                        "It may be wrong."),
            "proposal": {"action": "review", "value": None},
        })

    impossible = [i for i in dated
                  if _dt(i).year < min_year or _dt(i) > now + timedelta(days=1)]
    if impossible:
        years = sorted({_dt(i).year for i in impossible})
        cases.append({
            "case": "impossible_date",
            "n": len(impossible),
            "ids": [i["id"] for i in impossible],
            "examples": [f"{i['name']} → {i['date']}" for i in impossible[:5]],
            "years": years,
            "message": (_plural(len(impossible), "file", "files") + " with an impossible "
                        f"date (years {', '.join(str(a) for a in years)}). "
                        "Typical of an external camera with a dead clock battery."),
            "proposal": {"action": "assign_date", "value": None},
        })

    # Distant batches: the dates get clustered and each cluster is compared against the overall
    # median.
    rest = [i for i in dated if i not in impossible]
    if len(rest) >= 4:
        dates = sorted(_dt(i) for i in rest)
        median = dates[len(dates) // 2]
        clusters = _clusters_by_day(rest, far_days)
        for cluster in clusters:
            centre = sorted(_dt(i) for i in cluster)[len(cluster) // 2]
            delta_days = (centre - median).days
            if abs(delta_days) <= far_days or len(cluster) == len(rest):
                continue
            cases.append({
                "case": "distant_batch",
                "n": len(cluster),
                "ids": [i["id"] for i in cluster],
                "examples": [f"{i['name']} → {i['date']}" for i in cluster[:5]],
                "message": (_plural(len(cluster), "file says", "files say") +
                            f" {centre.date()} but the rest of the batch is around "
                            f"{median.date()} ({abs(delta_days)} days apart)."),
                "proposal": {
                    "action": "offset_days",
                    "value": -delta_days,
                    "equivalent": f"shift the group {-delta_days:+d} days",
                },
            })

    # Time offset: groups from the same day shifted by whole hours.
    offset = _detect_time_offset(rest, gap_min)
    if offset:
        cases.append(offset)

    return cases


def _clusters_by_day(items, far_days):
    """Groups by large gaps in the timeline (in days)."""
    ordered = sorted(items, key=_dt)
    clusters, current = [], []
    for it in ordered:
        if current and (_dt(it) - _dt(current[-1])).days > max(3, far_days // 6):
            clusters.append(current)
            current = []
        current.append(it)
    if current:
        clusters.append(current)
    return clusters


def _detect_time_offset(items, gap_min):
    """If there are two different cameras (by name prefix) shooting the same day but with their
    clocks shifted by an almost whole number of hours, it reports it."""
    from collections import defaultdict
    import re
    by_camera = defaultdict(list)
    named = {}
    for it in items:
        name = it.get("name") or ""
        stem = name.rsplit(".", 1)[0]
        # The camera marker is the first run of letters ANYWHERE in the stem, not only at the
        # start: `20260731_112146_IMG_4934.MOV` and `IMG_4934.MOV` are the same camera, and
        # keying on the name's length would instead split them by extension (.MOV vs .HEIC).
        mark = re.search(r"[A-Za-z]+", stem)
        if mark:
            key = mark.group(0).upper()
            named[key] = True
        else:
            # Only truly nameless files (20260809_204501.MOV) fall back to a shape key.
            key = f"digits{len(stem)}"
        by_camera[key].append(it)
    if len(by_camera) < 2:
        return None

    def label(key, group):
        example = group[0].get("name") or key
        return f"{key}* files" if key in named else f"files like «{example}»"

    groups = sorted(by_camera.items(), key=lambda kv: -len(kv[1]))
    ref_key, ref = groups[0]
    ref_label = label(ref_key, ref)
    for key, group in groups[1:]:
        name = label(key, group)
        if len(group) < 3:
            continue
        # The covered days get compared: if they overlap, we measure the difference between each
        # camera's median hour.
        ref_days = {_dt(i).date() for i in ref}
        group_days = {_dt(i).date() for i in group}
        if not ref_days & group_days:
            continue
        hour = lambda lst: sorted(_dt(i).hour + _dt(i).minute / 60 for i in lst)[len(lst) // 2]  # noqa: E731
        delta = hour(group) - hour(ref)
        if abs(delta) < 2 or abs(delta - round(delta)) > 0.35:
            continue
        return {
            "case": "time_offset",
            "n": len(group),
            "ids": [i["id"] for i in group],
            "examples": [f"{i['name']} → {i['date']}" for i in group[:5]],
            "message": (f"The {name} run ~{round(delta):+d} h against the {ref_label} "
                        "from the same day. Usually the camera's time zone."),
            "proposal": {
                "action": "offset_hours",
                "value": -round(delta),
                "equivalent": f"shift the group {-round(delta):+d} h",
            },
        }
    return None
