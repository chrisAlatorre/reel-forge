# Referencia: la base de la app Fotos de macOS

Todo lo de aquí está verificado contra una biblioteca real de macOS 26 (Tahoe),
esquema de Photos 2025-2026. Apple cambia nombres de columnas entre versiones
mayores, así que **antes de confiar en una columna, revísala**:

```bash
LIB=~/Pictures/Photos\ Library.photoslibrary
sqlite3 "file:$LIB/database/Photos.sqlite?immutable=1" "PRAGMA table_info(ZASSET);"
```

Nunca abras la base sin `mode=ro&immutable=1`. Nunca escribas en ella.

## Fechas: epoch de Core Data

Todas las columnas de fecha son **segundos desde el 1 de enero de 2001 UTC**,
no desde 1970. La diferencia es `978307200`.

```sql
SELECT datetime(ZDATECREATED + 978307200, 'unixepoch') AS utc FROM ZASSET LIMIT 1;
```

La hora de pared del lugar donde se tomó la foto es esa más `ZTIMEZONEOFFSET`
(en segundos, de `ZADDITIONALASSETATTRIBUTES`):

```sql
SELECT datetime(a.ZDATECREATED + 978307200 + COALESCE(aa.ZTIMEZONEOFFSET, 0), 'unixepoch')
         AS hora_local,
       aa.ZTIMEZONENAME
FROM ZASSET a
LEFT JOIN ZADDITIONALASSETATTRIBUTES aa ON aa.ZASSET = a.Z_PK
LIMIT 5;
```

Esa distinción importa de verdad: entre dos husos lejanos hay 12-15 horas de
diferencia, suficiente para que una foto del día 2 aparezca como del día 1 en
pantalla.

## `ZASSET`: una fila por foto o video

| Columna | Qué trae |
|---|---|
| `Z_PK` | llave interna; es la que usan las otras tablas |
| `ZUUID` | el identificador que entiende osxphotos y el que nombra las miniaturas |
| `ZDATECREATED` | fecha de captura, epoch Core Data, en UTC |
| `ZMODIFICATIONDATE`, `ZADDEDDATE` | modificación y fecha de importación |
| `ZKIND` | `0` foto, `1` video |
| `ZFAVORITE` | `1` si está marcada como favorita |
| `ZHIDDEN` | `1` si está en el álbum Oculto |
| `ZTRASHEDSTATE` | `0` normal, `1` en papelera. **Filtra siempre por `= 0`** |
| `ZLATITUDE`, `ZLONGITUDE` | GPS. Sin ubicación guarda `-180.0`, no `NULL` |
| `ZWIDTH`, `ZHEIGHT`, `ZORIENTATION` | dimensiones y rotación |
| `ZDURATION` | segundos de video (`0` en fotos) |
| `ZDIRECTORY`, `ZFILENAME` | ubicación del original dentro de `<lib>/originals/` |
| `ZISDETECTEDSCREENSHOT` | `1` si Fotos cree que es captura de pantalla |
| `ZAVALANCHEUUID` | agrupa las fotos de una **ráfaga**: mismo valor = misma ráfaga |
| `ZOVERALLAESTHETICSCORE`, `ZCURATIONSCORE`, `ZICONICSCORE` | puntajes que calcula Fotos. Útiles como desempate, nunca como criterio único |

`ZAVALANCHEUUID` vale oro al escoger material: cuando una toma está a medio
gesto, casi siempre hay una mejor en la misma ráfaga.

```sql
-- Las hermanas de ráfaga de un asset
SELECT ZUUID, datetime(ZDATECREATED + 978307200, 'unixepoch')
FROM ZASSET
WHERE ZAVALANCHEUUID = (SELECT ZAVALANCHEUUID FROM ZASSET WHERE ZUUID = ?)
  AND ZTRASHEDSTATE = 0
ORDER BY ZDATECREATED;
```

## `ZADDITIONALASSETATTRIBUTES`

Se une por `ZADDITIONALASSETATTRIBUTES.ZASSET = ZASSET.Z_PK`.

| Columna | Qué trae |
|---|---|
| `ZTIMEZONEOFFSET` | segundos respecto a UTC en el momento de la captura |
| `ZTIMEZONENAME` | `"America/Mexico_City"`, `"GMT+0800"`… |
| `ZORIGINALFILENAME` | el nombre con el que salió de la cámara |
| `ZORIGINALFILESIZE` | bytes del original; sirve para estimar la descarga |
| `ZORIGINALWIDTH`, `ZORIGINALHEIGHT` | dimensiones antes de editar |
| `ZEXIFTIMESTAMPSTRING` | la fecha tal cual venía en el EXIF, como texto |
| `ZREVERSELOCATIONDATA` | blob con los nombres de lugar (ver abajo) |

### `ZREVERSELOCATIONDATA`: sacar los nombres de lugar

Es un plist binario de `NSKeyedArchiver` con un `PLRevGeoLocationInfo`. Dentro,
`$objects` trae una lista de `PLRevGeoMapItemAdditionalPlaceInfo`, cada uno con
`name`, `placeType` y `area`.

**La trampa:** `name` y `placeType` no son valores, son `UID` que apuntan a otra
entrada de `$objects`. Hay que dereferenciarlos o no sale nada.

Códigos de `placeType` verificados:

| Código | Qué es |
|---|---|
| 1 | país |
| 2 | estado / entidad |
| 3 | región |
| 4 | ciudad |
| 5 | distrito |
| 6 | colonia / barrio |
| 14 | código postal |

Vienen entradas duplicadas con `area = 0` (la abreviatura del estado, el código
de país de dos letras). Quédate con la de mayor `area` por cada tipo.

`fuentes.decodificar_lugar()` ya hace todo esto y devuelve
`{"pais": ..., "estado": ..., "ciudad": ..., "colonia": ..., "texto": "Ciudad, País"}`.

Ojo: los nombres vienen **en el idioma del lugar**. Una foto en China devuelve
`北京市, 中国`, no "Pekín, China". Si vas a poner el lugar en pantalla, tradúcelo
o pregúntale al usuario cómo lo quiere.

## `ZDETECTEDFACE` y `ZPERSON`: caras y personas

`ZDETECTEDFACE` es una fila por cara detectada.

| Columna | Qué trae |
|---|---|
| `ZASSETFORFACE` | apunta a `ZASSET.Z_PK` |
| `ZPERSONFORFACE` | apunta a `ZPERSON.Z_PK` (en esquemas viejos se llamaba `ZPERSON`) |
| `ZCENTERX`, `ZCENTERY` | centro de la cara, normalizado 0..1. **`ZCENTERY` va invertida** |
| `ZSIZE` | tamaño de la cara, normalizado contra el lado largo |
| `ZQUALITY`, `ZQUALITYMEASURE` | calidad de la detección |
| `ZBLURSCORE` | qué tan movida está |
| `ZHASSMILE`, `ZSMILETYPE` | si está sonriendo |
| `ZISLEFTEYECLOSED`, `ZISRIGHTEYECLOSED` | ojos cerrados |
| `ZEYESSTATE`, `ZGAZETYPE`, `ZPOSEYAW`, `ZROLL` | dirección de la mirada y giro de la cabeza |
| `ZFACEEXPRESSIONTYPE` | tipo de expresión |
| `ZISINTRASH` | `1` si la cara ya no cuenta |

**El recorte de cara**, que es la operación que más se usa al escoger material:

```python
x = ZCENTERX * ancho
y = (1 - ZCENTERY) * alto      # invertida: 0 abajo, 1 arriba
lado = ZSIZE * max(ancho, alto)
caja = (x - lado, y - lado, x + lado, y + lado)   # con margen 2x, cabe la cabeza
```

Si te sale el pie en vez de la cara, olvidaste invertir `ZCENTERY`.

`ZHASSMILE`, `ZISLEFTEYECLOSED` y `ZBLURSCORE` sirven para **preseleccionar**,
pero no para decidir: hay que mirar el recorte. Fotos marca como sonrisa muchos
gestos a medias.

### Personas

`ZPERSON` guarda las personas que el usuario nombró. `ZFULLNAME` es el nombre
completo, `ZDISPLAYNAME` el corto; las personas sin nombrar tienen ambos en
`NULL`.

```sql
-- Personas nombradas, de más a menos fotos
SELECT COALESCE(p.ZFULLNAME, p.ZDISPLAYNAME) AS nombre,
       COUNT(DISTINCT d.ZASSETFORFACE) AS fotos
FROM ZPERSON p
JOIN ZDETECTEDFACE d ON d.ZPERSONFORFACE = p.Z_PK
WHERE COALESCE(p.ZFULLNAME, p.ZDISPLAYNAME) IS NOT NULL
GROUP BY p.Z_PK
ORDER BY fotos DESC;
```

El `Z_PK` de una persona es estable dentro de una biblioteca pero **no significa
nada en otra**. Nunca lo dejes escrito en el código: búscalo por nombre en cada
corrida.

## `ZINTERNALRESOURCE`: qué está bajado y qué está en iCloud

| Columna | Qué trae |
|---|---|
| `ZASSET` | apunta a `ZASSET.Z_PK` |
| `ZRESOURCETYPE` | `0` es el original; los demás son versiones derivadas |
| `ZLOCALAVAILABILITY` | `1` está en disco; cualquier otro valor, solo en iCloud |
| `ZDATALENGTH` | bytes de esa versión |

```sql
-- Cuánto habría que bajar de un rango de fechas
SELECT COUNT(*) AS faltantes,
       ROUND(SUM(r.ZDATALENGTH) / 1073741824.0, 2) AS gb
FROM ZASSET a
JOIN ZINTERNALRESOURCE r ON r.ZASSET = a.Z_PK AND r.ZRESOURCETYPE = 0
WHERE a.ZTRASHEDSTATE = 0
  AND r.ZLOCALAVAILABILITY <> 1
  AND a.ZDATECREATED BETWEEN
        (strftime('%s','2026-08-01') - 978307200) AND
        (strftime('%s','2026-08-21') - 978307200);
```

## Miniaturas en disco

```
<biblioteca>/resources/derivatives/<primera letra del UUID>/
    <UUID>_1_105_c.jpeg     ← la grande, ~1200 px del lado largo
    <UUID>_1_102_o.jpeg     ← una chica
    <UUID>.THM              ← cuadro de portada de un video
<biblioteca>/resources/derivatives/masters/<letra>/
    <UUID>_4_5005_c.jpeg    ← previsualización, suele ser aún más chica
```

Existen aunque el original esté solo en iCloud. Son el camino para revisar cientos
de fotos sin gastar red. `fuentes._rutas_miniatura()` las busca en ese orden.

Los originales que sí están bajados viven en:

```
<biblioteca>/originals/<ZASSET.ZDIRECTORY>/<ZASSET.ZFILENAME>
```

## Consulta de arranque

Copia y pega esto para ver de un jalón qué hay en un rango:

```bash
LIB=~/Pictures/Photos\ Library.photoslibrary
sqlite3 "file:$LIB/database/Photos.sqlite?immutable=1" <<'SQL'
.mode column
.headers on
SELECT date(a.ZDATECREATED + 978307200 + COALESCE(aa.ZTIMEZONEOFFSET,0), 'unixepoch') AS dia,
       COUNT(*) AS n,
       SUM(a.ZKIND = 1) AS videos,
       SUM(a.ZFAVORITE = 1) AS favoritas
FROM ZASSET a
LEFT JOIN ZADDITIONALASSETATTRIBUTES aa ON aa.ZASSET = a.Z_PK
WHERE a.ZTRASHEDSTATE = 0
  AND COALESCE(a.ZHIDDEN, 0) = 0
  AND a.ZDATECREATED BETWEEN
        (strftime('%s','2026-08-01') - 978307200) AND
        (strftime('%s','2026-08-21') - 978307200)
GROUP BY dia
ORDER BY dia;
SQL
```

## Cosas que cambian entre versiones de macOS

Si algo truena después de una actualización, empieza por aquí:

- `ZDETECTEDFACE.ZPERSONFORFACE` se llamó `ZPERSON` en esquemas anteriores.
  `fuentes.py` detecta cuál existe con `PRAGMA table_info`.
- `ZASSET.ZTRASHEDSTATE` y `ZASSET.ZHIDDEN` han cambiado de nombre; verifica
  antes de asumir.
- Las rutas de `resources/derivatives/` y los sufijos `_1_105_c` han variado
  entre versiones mayores. Busca el archivo, no lo des por hecho.
- Cuando algo se pone difícil, **osxphotos ya resolvió estas diferencias**:
  `osxphotos query --json` es más lento pero mucho más estable que leer la base
  a mano. Para inventarios grandes conviene la base; para casos raros, osxphotos.
