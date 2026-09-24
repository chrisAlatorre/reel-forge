# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "pillow-heif"]
# ///
"""Biblioteca común de reel-forge para leer fuentes de material.

Dos fuentes, una sola forma de item:

- `apple_photos`: lee la base de la app Fotos de macOS en SOLO LECTURA
  (`mode=ro&immutable=1`). Nunca escribe nada, nunca toca la biblioteca.
- `carpeta`: recorre una carpeta normal (cualquier sistema operativo) y saca
  fechas y GPS del EXIF.

Todas las funciones devuelven diccionarios con las mismas llaves (ver `Item`),
para que `inventario.py` y `validar_fechas.py` traten igual las dos fuentes.

No se importa directo: los scripts de al lado hacen
`sys.path.insert(0, str(Path(__file__).parent))` y luego `import fuentes`.
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
# Constantes
# ---------------------------------------------------------------------------

# Core Data cuenta segundos desde el 1 de enero de 2001 UTC, no desde 1970.
EPOCA_COREDATA = 978307200

# Extensiones que consideramos material aprovechable.
EXT_FOTO = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".dng", ".webp", ".avif"}
EXT_VIDEO = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".hevc"}
EXT_360 = {".insv", ".insp", ".vr", ".360"}
EXT_TODAS = EXT_FOTO | EXT_VIDEO | EXT_360

# Códigos de `placeType` dentro del plist de geocodificación inversa de Fotos.
# Los verificados en bibliotecas reales son estos; los demás se ignoran.
TIPO_LUGAR = {
    1: "pais",
    2: "estado",
    3: "region",
    4: "ciudad",
    5: "distrito",
    6: "colonia",
    14: "codigo_postal",
}

# Ruta por defecto de la biblioteca de Fotos en macOS. Se cambia con
# REEL_FORGE_FOTOTECA (el nombre canónico del plugin) o con
# REEL_FORGE_PHOTOS_LIBRARY, que algunos comandos usan.
BIBLIOTECA_DEFAULT = "~/Pictures/Photos Library.photoslibrary"
ENV_BIBLIOTECA = ("REEL_FORGE_FOTOTECA", "REEL_FORGE_PHOTOS_LIBRARY")
# Carpetas de material del usuario, separadas por ':' (o ';' en Windows).
ENV_FUENTES = "REEL_FORGE_FUENTES"


# ---------------------------------------------------------------------------
# Utilidades de fecha
# ---------------------------------------------------------------------------


def desde_coredata(valor, offset_s=None):
    """Convierte un timestamp de Core Data a datetime.

    `valor` es el instante en UTC. Si se pasa `offset_s` (el `ZTIMEZONEOFFSET`
    del asset), regresa la **hora de pared del lugar** donde se tomó la foto,
    que es la que el usuario recuerda. Sin offset, regresa UTC.
    """
    if valor is None:
        return None
    try:
        base = datetime.fromtimestamp(float(valor) + EPOCA_COREDATA, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None
    if offset_s is None:
        return base
    return base.astimezone(timezone(timedelta(seconds=int(offset_s))))


def iso(dt):
    return dt.isoformat(timespec="seconds") if dt else None


def parsear_fecha(texto, fin_de_dia=False):
    """Acepta 2026-08-01, 2026-08-01T14:30 o 2026-08-01 14:30."""
    if not texto:
        return None
    t = texto.strip().replace(" ", "T")
    for formato in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(t, formato)
            if formato == "%Y-%m-%d" and fin_de_dia:
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"No entendí la fecha '{texto}'. Usa AAAA-MM-DD o AAAA-MM-DDTHH:MM")


def sin_tz(dt):
    """Quita la zona horaria conservando la hora de pared, para poder comparar
    fechas de fuentes distintas sin que un offset invente horas de diferencia."""
    return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt


# ---------------------------------------------------------------------------
# Forma del item
# ---------------------------------------------------------------------------


def item_vacio():
    """Llaves que todo item trae, venga de donde venga."""
    return {
        "id": None,              # uuid de Fotos o ruta relativa en una carpeta
        "fuente": None,          # "apple-photos" | "carpeta"
        "nombre": None,          # nombre de archivo original
        "tipo": None,            # "foto" | "video" | "360"
        "fecha": None,           # ISO, hora de pared del lugar cuando se sabe
        "fecha_utc": None,       # ISO en UTC, o None si no se puede saber
        "origen_fecha": None,    # "exif" | "photos-db" | "nombre-archivo" | "mtime" | None
        "zona": None,            # "America/Mexico_City", "GMT+0800", ...
        "lat": None,
        "lon": None,
        "lugar": None,           # "Ciudad, País" ya resuelto (solo Apple Photos)
        "lugar_detalle": None,   # dict con pais/estado/ciudad/colonia
        "favorito": False,
        "caras": 0,
        "personas": [],          # nombres confirmados en Fotos
        "ancho": None,
        "alto": None,
        "duracion_s": None,
        "bytes": None,
        "local": None,           # True si el original está en disco
        "ruta": None,            # ruta del original si es local
        "miniatura": None,       # ruta de la miniatura ya generada (Apple Photos)
        "oculto": False,
        "captura_pantalla": False,
    }


def clasificar_ext(ext):
    ext = ext.lower()
    if ext in EXT_360:
        return "360"
    if ext in EXT_VIDEO:
        return "video"
    if ext in EXT_FOTO:
        return "foto"
    return None


# ---------------------------------------------------------------------------
# Apple Photos (solo macOS)
# ---------------------------------------------------------------------------


class FototecaNoDisponible(RuntimeError):
    pass


def ruta_biblioteca(ruta=None):
    r = ruta
    for nombre in ENV_BIBLIOTECA:
        r = r or os.environ.get(nombre)
    return Path(r or BIBLIOTECA_DEFAULT).expanduser()


def fuentes_del_entorno():
    """Carpetas que el usuario configuró en REEL_FORGE_FUENTES."""
    crudo = os.environ.get(ENV_FUENTES, "")
    sep = ";" if os.name == "nt" else ":"
    return [t.strip() for t in crudo.split(sep) if t.strip()]


def abrir_fototeca(ruta=None, copiar=False):
    """Abre `Photos.sqlite` en solo lectura.

    - Por defecto usa `mode=ro&immutable=1`: SQLite ni siquiera abre el archivo
      para escritura y **no lee el WAL**. Es imposible dañar la biblioteca, a
      cambio de que los cambios de los últimos minutos (fotos recién importadas,
      favoritas recién marcadas) pueden no aparecer.
    - Con `copiar=True` se copian `Photos.sqlite`, `-wal` y `-shm` a una carpeta
      temporal y se abre esa copia con `mode=ro`. Ahí sí se ve todo al día, pero
      la base pesa varios GB.

    Devuelve `(conexion, ruta_biblioteca, carpeta_temporal_o_None)`.
    """
    lib = ruta_biblioteca(ruta)
    db = lib / "database" / "Photos.sqlite"
    if not db.exists():
        raise FototecaNoDisponible(
            f"No encontré {db}.\n"
            "En macOS la ruta normal es ~/Pictures/Photos Library.photoslibrary.\n"
            "Si la tuya está en otro lado, exporta REEL_FORGE_FOTOTECA con su ruta.\n"
            "Fuera de macOS esta fuente no existe: usa una carpeta."
        )

    temporal = None
    if copiar:
        temporal = Path(tempfile.mkdtemp(prefix="reel-forge-fototeca-"))
        for sufijo in ("", "-wal", "-shm"):
            origen = Path(str(db) + sufijo)
            if origen.exists():
                shutil.copy2(origen, temporal / origen.name)
        destino = temporal / db.name
        uri = f"file:{destino}?mode=ro"
    else:
        uri = f"file:{db}?mode=ro&immutable=1"

    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as e:
        raise FototecaNoDisponible(
            f"No pude abrir la base de Fotos ({e}).\n"
            "Casi siempre es permiso: la Terminal (o el proceso que corre esto) necesita\n"
            "Acceso total al disco en Ajustes del sistema → Privacidad y seguridad."
        ) from e
    con.row_factory = sqlite3.Row
    return con, lib, temporal


def _columna_existe(con, tabla, columna):
    return any(f["name"] == columna for f in con.execute(f"PRAGMA table_info({tabla})"))


def decodificar_lugar(blob):
    """Saca los nombres de lugar del blob `ZREVERSELOCATIONDATA`.

    Es un plist de NSKeyedArchiver con un `PLRevGeoLocationInfo`. Adentro trae
    una lista de `PLRevGeoMapItemAdditionalPlaceInfo`, cada uno con `name` y
    `placeType` (1 país, 2 estado, 4 ciudad, 6 colonia, 14 CP).
    """
    if not blob:
        return None
    try:
        plist = plistlib.loads(blob)
        objetos = plist["$objects"]
    except Exception:
        return None

    def deref(valor):
        """Los campos del archivo son UIDs que apuntan a otra entrada de
        `$objects`. `name` apunta a una cadena y `placeType` a un entero."""
        if hasattr(valor, "data"):
            try:
                valor = objetos[valor.data]
            except IndexError:
                return None
        return None if valor == "$null" else valor

    detalle = {}
    for obj in objetos:
        if not isinstance(obj, dict) or "placeType" not in obj or "name" not in obj:
            continue
        tipo = TIPO_LUGAR.get(deref(obj["placeType"]))
        nombre = deref(obj["name"])
        if not isinstance(nombre, str):
            nombre = None
        # El de mayor `area` gana: hay entradas duplicadas (abreviatura de estado,
        # código de país) que vienen con area 0.
        if tipo and nombre:
            area = obj.get("area") or 0
            if tipo not in detalle or area > detalle[tipo][1]:
                detalle[tipo] = (nombre, area)

    detalle = {k: v[0] for k, v in detalle.items()}
    if not detalle:
        return None
    partes = [detalle.get("ciudad") or detalle.get("colonia"), detalle.get("pais")]
    detalle["texto"] = ", ".join(p for p in partes if p) or None
    return detalle


def _rutas_miniatura(lib, uuid):
    """Miniaturas ya generadas por Fotos. Sirven para hojas de contacto y para
    revisar caras sin bajar un solo original de iCloud."""
    if not uuid:
        return []
    inicial = uuid[0].upper()
    base = lib / "resources" / "derivatives"
    candidatas = [
        base / inicial / f"{uuid}_1_105_c.jpeg",     # la grande (~1200 px)
        base / inicial / f"{uuid}_1_102_o.jpeg",
        base / "masters" / inicial / f"{uuid}_4_5005_c.jpeg",
        base / inicial / f"{uuid}.THM",              # cuadro de portada de video
    ]
    return [c for c in candidatas if c.exists()]


def leer_apple_photos(desde=None, hasta=None, ruta_lib=None, copiar=False,
                      incluir_ocultas=False, incluir_capturas=True,
                      solo_favoritas=False, persona=None):
    """Lee assets de la app Fotos. Devuelve (lista_de_items, metadatos)."""
    con, lib, temporal = abrir_fototeca(ruta_lib, copiar=copiar)
    try:
        tiene_torso = _columna_existe(con, "ZDETECTEDFACE", "ZPERSONFORFACE")
        col_persona = "ZPERSONFORFACE" if tiene_torso else "ZPERSON"

        where = ["a.ZTRASHEDSTATE = 0"]
        params = []
        if not incluir_ocultas:
            where.append("COALESCE(a.ZHIDDEN, 0) = 0")
        if solo_favoritas:
            where.append("a.ZFAVORITE = 1")
        if desde:
            where.append("a.ZDATECREATED >= ?")
            params.append(desde.timestamp() - EPOCA_COREDATA)
        if hasta:
            where.append("a.ZDATECREATED <= ?")
            params.append(hasta.timestamp() - EPOCA_COREDATA)

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
        filas = con.execute(sql, params).fetchall()

        pks = [f["Z_PK"] for f in filas]
        caras = _caras_por_asset(con, pks, col_persona)
        locales = _originales_locales(con, pks)

        if persona:
            pks_persona = _assets_de_persona(con, persona, col_persona)
            filas = [f for f in filas if f["Z_PK"] in pks_persona]

        items = []
        cache_lugar = {}
        for f in filas:
            ext = Path(f["ZFILENAME"] or "").suffix
            tipo = clasificar_ext(ext) or ("video" if f["ZKIND"] == 1 else "foto")
            captura = bool(f["ZISDETECTEDSCREENSHOT"])
            if captura and not incluir_capturas:
                continue

            offset = f["ZTIMEZONEOFFSET"]
            fecha_local = desde_coredata(f["ZDATECREATED"], offset)
            fecha_utc = desde_coredata(f["ZDATECREATED"])

            blob = f["ZREVERSELOCATIONDATA"]
            # Muchos assets del mismo lugar traen el mismo blob: se cachea por
            # hash para no parsear 5000 plists iguales.
            clave = hashlib.blake2b(blob, digest_size=16).digest() if blob else None
            if clave is not None and clave not in cache_lugar:
                cache_lugar[clave] = decodificar_lugar(blob)
            detalle = cache_lugar.get(clave)

            lat, lon = f["ZLATITUDE"], f["ZLONGITUDE"]
            # Fotos guarda -180/-180 cuando no hay ubicación.
            if lat is None or lat <= -180 or (lat == 0 and lon == 0):
                lat = lon = None

            info_caras = caras.get(f["Z_PK"], {"n": 0, "personas": []})
            local, bytes_orig = locales.get(f["Z_PK"], (False, None))
            uuid = f["ZUUID"]
            miniaturas = _rutas_miniatura(lib, uuid)

            ruta_original = None
            if f["ZDIRECTORY"] and f["ZFILENAME"]:
                p = lib / "originals" / f["ZDIRECTORY"] / f["ZFILENAME"]
                ruta_original = str(p) if p.exists() else None

            it = item_vacio()
            it.update({
                "id": uuid,
                "fuente": "apple-photos",
                "nombre": f["ZORIGINALFILENAME"] or f["ZFILENAME"],
                "tipo": tipo,
                "fecha": iso(fecha_local),
                "fecha_utc": iso(fecha_utc),
                "origen_fecha": "photos-db",
                "zona": f["ZTIMEZONENAME"],
                "lat": lat,
                "lon": lon,
                "lugar": (detalle or {}).get("texto"),
                "lugar_detalle": detalle,
                "favorito": bool(f["ZFAVORITE"]),
                "caras": info_caras["n"],
                "personas": info_caras["personas"],
                "ancho": f["ZWIDTH"],
                "alto": f["ZHEIGHT"],
                "duracion_s": round(f["ZDURATION"], 2) if f["ZDURATION"] else None,
                "bytes": int(f["ZORIGINALFILESIZE"]) if f["ZORIGINALFILESIZE"] else bytes_orig,
                "local": local or ruta_original is not None,
                "ruta": ruta_original,
                "miniatura": str(miniaturas[0]) if miniaturas else None,
                "oculto": bool(f["ZHIDDEN"]),
                "captura_pantalla": captura,
            })
            items.append(it)

        meta = {
            "tipo": "apple-photos",
            "biblioteca": str(lib),
            "modo_lectura": "copia temporal (mode=ro)" if copiar else "mode=ro&immutable=1",
            "aviso_wal": None if copiar else (
                "Con immutable=1 no se lee el WAL: los cambios de los últimos minutos "
                "pueden faltar. Usa --copiar-base si acabas de importar o marcar favoritas."
            ),
        }
        return items, meta
    finally:
        con.close()
        if temporal:
            shutil.rmtree(temporal, ignore_errors=True)


def _caras_por_asset(con, pks, col_persona):
    """Cuántas caras trae cada asset y qué personas ya tienen nombre.

    `ZDETECTEDFACE` guarda el centro de cada cara en coordenadas normalizadas
    0..1 con `ZCENTERX` / `ZCENTERY` y el tamaño en `ZSIZE`. **`ZCENTERY` viene
    invertida** (0 abajo, 1 arriba): para recortar sobre una imagen hay que usar
    `y = (1 - ZCENTERY) * alto`.
    """
    resultado = {}
    if not pks:
        return resultado
    for lote in _en_lotes(pks, 900):
        marcas = ",".join("?" * len(lote))
        sql = f"""
            SELECT d.ZASSETFORFACE AS asset, COUNT(*) AS n,
                   GROUP_CONCAT(DISTINCT p.ZFULLNAME) AS nombres
            FROM ZDETECTEDFACE d
            LEFT JOIN ZPERSON p ON p.Z_PK = d.{col_persona}
            WHERE d.ZASSETFORFACE IN ({marcas})
              AND COALESCE(d.ZISINTRASH, 0) = 0
            GROUP BY d.ZASSETFORFACE
        """
        for fila in con.execute(sql, lote):
            nombres = [n for n in (fila["nombres"] or "").split(",") if n]
            resultado[fila["asset"]] = {"n": fila["n"], "personas": sorted(set(nombres))}
    return resultado


def _assets_de_persona(con, nombre, col_persona):
    sql = f"""
        SELECT DISTINCT d.ZASSETFORFACE AS asset
        FROM ZDETECTEDFACE d
        JOIN ZPERSON p ON p.Z_PK = d.{col_persona}
        WHERE (p.ZFULLNAME = ? OR p.ZDISPLAYNAME = ?)
    """
    return {f["asset"] for f in con.execute(sql, (nombre, nombre))}


def _originales_locales(con, pks):
    """`ZINTERNALRESOURCE` dice qué versiones están en disco.

    `ZRESOURCETYPE = 0` es el original; `ZLOCALAVAILABILITY = 1` significa que
    está bajado. Todo lo demás vive solo en iCloud y hay que descargarlo.
    """
    resultado = {}
    if not pks:
        return resultado
    for lote in _en_lotes(pks, 900):
        marcas = ",".join("?" * len(lote))
        sql = f"""
            SELECT ZASSET AS asset,
                   MAX(CASE WHEN ZLOCALAVAILABILITY = 1 THEN 1 ELSE 0 END) AS local,
                   MAX(ZDATALENGTH) AS bytes
            FROM ZINTERNALRESOURCE
            WHERE ZASSET IN ({marcas}) AND ZRESOURCETYPE = 0
            GROUP BY ZASSET
        """
        for fila in con.execute(sql, lote):
            resultado[fila["asset"]] = (bool(fila["local"]), fila["bytes"])
    return resultado


def _en_lotes(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def personas_de_la_biblioteca(ruta_lib=None, copiar=False, minimo=1):
    """Lista de personas nombradas, de más a menos fotos. Útil para que el
    usuario diga a quién seguir sin tener que adivinar el nombre exacto."""
    con, _lib, temporal = abrir_fototeca(ruta_lib, copiar=copiar)
    try:
        col = "ZPERSONFORFACE" if _columna_existe(con, "ZDETECTEDFACE", "ZPERSONFORFACE") else "ZPERSON"
        sql = f"""
            SELECT p.Z_PK, COALESCE(p.ZFULLNAME, p.ZDISPLAYNAME) AS nombre,
                   COUNT(DISTINCT d.ZASSETFORFACE) AS n
            FROM ZPERSON p
            JOIN ZDETECTEDFACE d ON d.{col} = p.Z_PK
            WHERE COALESCE(p.ZFULLNAME, p.ZDISPLAYNAME) IS NOT NULL
            GROUP BY p.Z_PK HAVING n >= ?
            ORDER BY n DESC
        """
        return [{"pk": f["Z_PK"], "nombre": f["nombre"], "fotos": f["n"]}
                for f in con.execute(sql, (minimo,))]
    finally:
        con.close()
        if temporal:
            shutil.rmtree(temporal, ignore_errors=True)


# ---------------------------------------------------------------------------
# Carpetas normales (cualquier sistema operativo)
# ---------------------------------------------------------------------------


def _exif_pillow(ruta):
    """Fecha, tamaño y GPS con Pillow. Funciona para JPEG, PNG, TIFF y HEIC
    (con pillow-heif registrado). No lee video."""
    try:
        from PIL import Image, ExifTags
    except ImportError:
        return {}
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass

    datos = {}
    try:
        with Image.open(ruta) as img:
            datos["ancho"], datos["alto"] = img.size
            exif = img.getexif()
            if not exif:
                return datos
            plano = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
            ifd = exif.get_ifd(0x8769)  # ExifIFD
            plano.update({ExifTags.TAGS.get(k, k): v for k, v in ifd.items()})
            for llave in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                if plano.get(llave):
                    try:
                        datos["fecha"] = datetime.strptime(str(plano[llave]), "%Y:%m:%d %H:%M:%S")
                        datos["origen_fecha"] = "exif"
                        break
                    except ValueError:
                        continue
            gps = exif.get_ifd(0x8825)
            if gps:
                datos.update(_gps_pillow(gps))
    except Exception:
        return datos
    return datos


def _gps_pillow(gps):
    from PIL import ExifTags
    g = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps.items()}

    def grados(valor, ref, negativos):
        try:
            d, m, s = (float(x) for x in valor)
        except (TypeError, ValueError):
            return None
        dec = d + m / 60 + s / 3600
        return -dec if str(ref).upper() in negativos else dec

    lat = grados(g.get("GPSLatitude"), g.get("GPSLatitudeRef"), {"S"})
    lon = grados(g.get("GPSLongitude"), g.get("GPSLongitudeRef"), {"W"})
    if lat is None or lon is None:
        return {}
    return {"lat": round(lat, 6), "lon": round(lon, 6)}


def _ffprobe(ruta):
    """Duración, tamaño, fecha de creación y GPS de un video. Necesita ffprobe
    (viene con ffmpeg). Si no está instalado, devuelve {} sin quejarse."""
    if not shutil.which("ffprobe"):
        return {}
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", str(ruta)]
    try:
        salida = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        info = json.loads(salida.stdout or "{}")
    except Exception:
        return {}

    datos = {}
    fmt = info.get("format", {})
    if fmt.get("duration"):
        try:
            datos["duracion_s"] = round(float(fmt["duration"]), 2)
        except ValueError:
            pass
    etiquetas = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    for llave in ("creation_time", "com.apple.quicktime.creationdate", "date"):
        if etiquetas.get(llave):
            try:
                datos["fecha"] = datetime.fromisoformat(
                    str(etiquetas[llave]).replace("Z", "+00:00"))
                datos["origen_fecha"] = "exif"
                break
            except ValueError:
                continue
    # Apple guarda el GPS como "+19.4326-099.1332/"
    crudo = etiquetas.get("com.apple.quicktime.location.iso6709") or etiquetas.get("location")
    if crudo:
        datos.update(_iso6709(str(crudo)))
    for st in info.get("streams", []):
        if st.get("codec_type") == "video":
            datos.setdefault("ancho", st.get("width"))
            datos.setdefault("alto", st.get("height"))
            break
    return datos


def _iso6709(texto):
    import re
    m = re.match(r"([+-]\d+\.?\d*)([+-]\d+\.?\d*)", texto.strip())
    if not m:
        return {}
    return {"lat": float(m.group(1)), "lon": float(m.group(2))}


def _exiftool(ruta):
    """Último recurso: exiftool lee formatos raros (.insv, .dng, .360). Opcional."""
    if not shutil.which("exiftool"):
        return {}
    cmd = ["exiftool", "-j", "-n", "-DateTimeOriginal", "-CreateDate",
           "-GPSLatitude", "-GPSLongitude", "-ImageWidth", "-ImageHeight",
           "-Duration", str(ruta)]
    try:
        salida = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        crudo = json.loads(salida.stdout or "[]")
    except Exception:
        return {}
    if not crudo:
        return {}
    d = crudo[0]
    datos = {}
    for llave in ("DateTimeOriginal", "CreateDate"):
        if d.get(llave):
            try:
                datos["fecha"] = datetime.strptime(str(d[llave])[:19], "%Y:%m:%d %H:%M:%S")
                datos["origen_fecha"] = "exif"
                break
            except ValueError:
                continue
    if d.get("GPSLatitude") is not None and d.get("GPSLongitude") is not None:
        datos["lat"], datos["lon"] = float(d["GPSLatitude"]), float(d["GPSLongitude"])
    for origen, destino in (("ImageWidth", "ancho"), ("ImageHeight", "alto"), ("Duration", "duracion_s")):
        if d.get(origen):
            datos[destino] = d[origen]
    return datos


def _fecha_del_nombre(nombre):
    """Muchas cámaras ponen la fecha en el nombre: IMG_20260815_143012.jpg,
    VID_20260819_160250_00_141.insv, PXL_20260815_203012345.jpg, 2026-08-15 14.30.12.jpg.
    Es la última red de seguridad cuando no hay EXIF."""
    import re
    patrones = [
        (r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})[-_ T]?(\d{2})[-_.:]?(\d{2})[-_.:]?(\d{2})", 6),
        (r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", 3),
    ]
    for patron, grupos in patrones:
        m = re.search(patron, nombre)
        if not m:
            continue
        try:
            partes = [int(x) for x in m.groups()[:grupos]]
            if grupos == 3:
                partes += [12, 0, 0]
            return datetime(*partes)
        except ValueError:
            continue
    return None


def leer_carpeta(raiz, desde=None, hasta=None, recursivo=True, usar_exiftool=False):
    """Recorre una carpeta y arma los items. Devuelve (items, metadatos)."""
    raiz = Path(raiz).expanduser().resolve()
    if not raiz.is_dir():
        raise FileNotFoundError(f"No existe la carpeta {raiz}")

    patron = "**/*" if recursivo else "*"
    items, saltados = [], 0
    for ruta in sorted(raiz.glob(patron)):
        if not ruta.is_file() or ruta.name.startswith("."):
            continue
        tipo = clasificar_ext(ruta.suffix)
        if tipo is None:
            saltados += 1
            continue

        if tipo in ("video", "360"):
            datos = _ffprobe(ruta)
            if not datos.get("fecha") or usar_exiftool:
                datos = {**_exiftool(ruta), **datos}
        else:
            datos = _exif_pillow(ruta)
            if not datos.get("fecha") and usar_exiftool:
                datos = {**_exiftool(ruta), **datos}

        fecha = datos.get("fecha")
        origen = datos.get("origen_fecha")
        if not fecha:
            fecha = _fecha_del_nombre(ruta.name)
            origen = "nombre-archivo" if fecha else None
        if not fecha:
            # mtime es lo menos confiable: una copia con `cp` lo reescribe.
            fecha = datetime.fromtimestamp(ruta.stat().st_mtime)
            origen = "mtime"

        if desde and sin_tz(fecha) < sin_tz(desde):
            continue
        if hasta and sin_tz(fecha) > sin_tz(hasta):
            continue

        it = item_vacio()
        it.update({
            "id": str(ruta.relative_to(raiz)),
            "fuente": "carpeta",
            "nombre": ruta.name,
            "tipo": tipo,
            "fecha": iso(fecha),
            "fecha_utc": iso(fecha) if fecha.tzinfo else None,
            "origen_fecha": origen,
            "lat": datos.get("lat"),
            "lon": datos.get("lon"),
            "ancho": datos.get("ancho"),
            "alto": datos.get("alto"),
            "duracion_s": datos.get("duracion_s"),
            "bytes": ruta.stat().st_size,
            "local": True,
            "ruta": str(ruta),
        })
        items.append(it)

    items.sort(key=lambda x: x["fecha"] or "")
    meta = {
        "tipo": "carpeta",
        "raiz": str(raiz),
        "archivos_ignorados": saltados,
        "herramientas": {
            "ffprobe": bool(shutil.which("ffprobe")),
            "exiftool": bool(shutil.which("exiftool")),
        },
    }
    return items, meta


# ---------------------------------------------------------------------------
# Sesiones, lugares y sospechas de fecha
# ---------------------------------------------------------------------------


def _dt(item):
    f = item.get("fecha")
    if not f:
        return None
    try:
        return sin_tz(datetime.fromisoformat(f))
    except ValueError:
        return None


def agrupar_sesiones(items, hueco_min=90):
    """Parte la lista en sesiones: cada hueco de más de `hueco_min` minutos
    abre una sesión nueva. Es la unidad natural para contar "momentos" de un
    viaje sin depender de los días del calendario."""
    con_fecha = sorted([i for i in items if _dt(i)], key=_dt)
    sesiones, actual = [], []
    limite = timedelta(minutes=hueco_min)

    for it in con_fecha:
        if actual and _dt(it) - _dt(actual[-1]) > limite:
            sesiones.append(actual)
            actual = []
        actual.append(it)
    if actual:
        sesiones.append(actual)

    salida = []
    for n, grupo in enumerate(sesiones, 1):
        lugares = _conteo(g.get("lugar") for g in grupo)
        salida.append({
            "sesion": n,
            "inicio": grupo[0]["fecha"],
            "fin": grupo[-1]["fecha"],
            "duracion_min": round((_dt(grupo[-1]) - _dt(grupo[0])).total_seconds() / 60, 1),
            "n": len(grupo),
            "fotos": sum(1 for g in grupo if g["tipo"] == "foto"),
            "videos": sum(1 for g in grupo if g["tipo"] in ("video", "360")),
            "favoritas": sum(1 for g in grupo if g["favorito"]),
            "con_caras": sum(1 for g in grupo if g["caras"]),
            "lugar": lugares[0][0] if lugares else None,
            "ids": [g["id"] for g in grupo],
        })
    return salida


def _conteo(valores):
    from collections import Counter
    c = Counter(v for v in valores if v)
    return c.most_common()


def resumen_lugares(items):
    from collections import defaultdict
    por_lugar = defaultdict(list)
    for it in items:
        if it.get("lugar"):
            por_lugar[it["lugar"]].append(it)
    salida = []
    for lugar, grupo in por_lugar.items():
        fechas = sorted(f for f in (g["fecha"] for g in grupo) if f)
        salida.append({
            "lugar": lugar,
            "n": len(grupo),
            "primera": fechas[0] if fechas else None,
            "ultima": fechas[-1] if fechas else None,
        })
    salida.sort(key=lambda x: -x["n"])
    return salida


def _plural(n, singular, plural):
    return f"{n} {singular}" if n == 1 else f"{n} {plural}"


def detectar_sospechas(items, anio_minimo=2000, dias_lejos=180, hueco_min=90):
    """Encuentra fechas rotas y las agrupa en casos que el usuario pueda
    confirmar de un jalón. Devuelve una lista de casos, cada uno con su
    corrección propuesta.

    Casos que detecta:
      - `sin_fecha`: no hay EXIF ni nada de dónde sacarla.
      - `fecha_imposible`: año anterior a `anio_minimo` o en el futuro. Es el
        clásico de la cámara externa (GoPro, Insta360, réflex) que perdió la
        pila y arrancó en 1970 o 2014.
      - `lote_lejano`: un grupo de archivos cuya fecha se aleja más de
        `dias_lejos` de la mediana del material, pero que entre ellos son
        coherentes. Casi siempre es una sola cámara mal puesta.
      - `solo_mtime`: la fecha viene de la fecha de modificación del archivo,
        que se reescribe al copiar. No es confiable.
      - `desfase_horario`: un grupo con fecha del mismo día que el resto pero
        corrido un número casi entero de horas. Zona horaria mal puesta.
    """
    ahora = datetime.now()
    con_fecha = [i for i in items if _dt(i)]
    casos = []

    sin_fecha = [i for i in items if not _dt(i) or i.get("origen_fecha") is None]
    if sin_fecha:
        casos.append({
            "caso": "sin_fecha",
            "n": len(sin_fecha),
            "ids": [i["id"] for i in sin_fecha],
            "ejemplos": [i["nombre"] for i in sin_fecha[:5]],
            "mensaje": _plural(len(sin_fecha), "archivo sin fecha", "archivos sin fecha") + " de captura.",
            "propuesta": {"accion": "asignar_fecha", "valor": None},
        })

    solo_mtime = [i for i in items if i.get("origen_fecha") == "mtime"]
    if solo_mtime:
        casos.append({
            "caso": "solo_mtime",
            "n": len(solo_mtime),
            "ids": [i["id"] for i in solo_mtime],
            "ejemplos": [i["nombre"] for i in solo_mtime[:5]],
            "mensaje": (_plural(len(solo_mtime), "archivo solo tiene", "archivos solo tienen") +
                        " la fecha de modificación del sistema, que cambia al copiarlos. "
                        "Puede estar mal."),
            "propuesta": {"accion": "revisar", "valor": None},
        })

    imposibles = [i for i in con_fecha
                  if _dt(i).year < anio_minimo or _dt(i) > ahora + timedelta(days=1)]
    if imposibles:
        anios = sorted({_dt(i).year for i in imposibles})
        casos.append({
            "caso": "fecha_imposible",
            "n": len(imposibles),
            "ids": [i["id"] for i in imposibles],
            "ejemplos": [f"{i['nombre']} → {i['fecha']}" for i in imposibles[:5]],
            "anios": anios,
            "mensaje": (_plural(len(imposibles), "archivo", "archivos") + " con fecha "
                        f"imposible (años {', '.join(str(a) for a in anios)}). "
                        "Típico de una cámara externa sin pila de reloj."),
            "propuesta": {"accion": "asignar_fecha", "valor": None},
        })

    # Lotes lejanos: se agrupan las fechas en racimos y se compara cada racimo
    # contra la mediana general.
    restantes = [i for i in con_fecha if i not in imposibles]
    if len(restantes) >= 4:
        fechas = sorted(_dt(i) for i in restantes)
        mediana = fechas[len(fechas) // 2]
        racimos = _racimos_por_dia(restantes, dias_lejos)
        for racimo in racimos:
            centro = sorted(_dt(i) for i in racimo)[len(racimo) // 2]
            delta_dias = (centro - mediana).days
            if abs(delta_dias) <= dias_lejos or len(racimo) == len(restantes):
                continue
            # Los vecinos por orden de nombre dan la fecha correcta probable.
            casos.append({
                "caso": "lote_lejano",
                "n": len(racimo),
                "ids": [i["id"] for i in racimo],
                "ejemplos": [f"{i['nombre']} → {i['fecha']}" for i in racimo[:5]],
                "mensaje": (_plural(len(racimo), "archivo dice", "archivos dicen") +
                            f" {centro.date()} pero el resto del lote está en "
                            f"{mediana.date()} ({abs(delta_dias)} días de diferencia)."),
                "propuesta": {
                    "accion": "offset_dias",
                    "valor": -delta_dias,
                    "equivalente": f"mover el grupo {-delta_dias:+d} días",
                },
            })

    # Desfase horario: grupos del mismo día corridos horas enteras.
    desfase = _detectar_desfase_horario(restantes, hueco_min)
    if desfase:
        casos.append(desfase)

    return casos


def _racimos_por_dia(items, dias_lejos):
    """Agrupa por huecos grandes en la línea de tiempo (en días)."""
    ordenados = sorted(items, key=_dt)
    racimos, actual = [], []
    for it in ordenados:
        if actual and (_dt(it) - _dt(actual[-1])).days > max(3, dias_lejos // 6):
            racimos.append(actual)
            actual = []
        actual.append(it)
    if actual:
        racimos.append(actual)
    return racimos


def _detectar_desfase_horario(items, hueco_min):
    """Si hay dos cámaras distintas (por prefijo de nombre) grabando el mismo
    día pero con horas corridas un número casi entero, lo reporta."""
    from collections import defaultdict
    import re
    por_camara = defaultdict(list)
    for it in items:
        nombre = it.get("nombre") or ""
        prefijo = re.match(r"[A-Za-z]+", nombre)
        # Sin prefijo de letras (20260809_204501.MOV) se agrupa por longitud del
        # nombre, que también distingue una cámara de otra.
        clave = prefijo.group(0).upper() if prefijo else f"num{len(nombre)}"
        por_camara[clave].append(it)
    if len(por_camara) < 2:
        return None

    def etiqueta(clave, grupo):
        ejemplo = grupo[0].get("nombre") or clave
        return f"{clave}*" if clave[0].isalpha() else f"tipo «{ejemplo}»"

    grupos = sorted(por_camara.items(), key=lambda kv: -len(kv[1]))
    ref_clave, ref = grupos[0]
    ref_nombre = etiqueta(ref_clave, ref)
    for clave, grupo in grupos[1:]:
        nombre = etiqueta(clave, grupo)
        if len(grupo) < 3:
            continue
        # Se comparan los días cubiertos: si coinciden, se mide la diferencia
        # entre la hora mediana de cada cámara.
        dias_ref = {_dt(i).date() for i in ref}
        dias_g = {_dt(i).date() for i in grupo}
        if not dias_ref & dias_g:
            continue
        hora = lambda lista: sorted(_dt(i).hour + _dt(i).minute / 60 for i in lista)[len(lista) // 2]  # noqa: E731
        delta = hora(grupo) - hora(ref)
        if abs(delta) < 2 or abs(delta - round(delta)) > 0.35:
            continue
        return {
            "caso": "desfase_horario",
            "n": len(grupo),
            "ids": [i["id"] for i in grupo],
            "ejemplos": [f"{i['nombre']} → {i['fecha']}" for i in grupo[:5]],
            "mensaje": (f"Los archivos {nombre} van ~{round(delta)} h corridos respecto a "
                        f"los {ref_nombre} del mismo día. Suele ser la zona horaria de la "
                        "cámara."),
            "propuesta": {
                "accion": "offset_horas",
                "valor": -round(delta),
                "equivalente": f"mover el grupo {-round(delta):+d} h",
            },
        }
    return None
