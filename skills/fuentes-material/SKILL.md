---
name: fuentes-material
description: Encuentra, inventaría y valida el material (fotos y videos) del que va a salir el reel. Lee la app Fotos de macOS en solo lectura, carpetas normales en cualquier sistema y material de cámaras 360. Úsala al principio de cualquier proyecto de reel-forge, antes de investigar tendencias o editar nada.
---

# Fuentes de material y metadatos

Esta skill responde tres preguntas, en este orden:

1. **¿Qué hay?** Cuántas fotos y videos, de qué fechas, de qué lugares, con quién.
2. **¿Los metadatos sirven?** Si las fechas están rotas, todo lo demás (agrupar
   por sesiones, ordenar la historia, poner un lugar en pantalla) sale mal.
3. **¿Qué hay que bajar?** Cuánto pesa y qué está solo en la nube.

Nunca escribe en la biblioteca de Fotos ni modifica archivos originales.

## Lo primero

```bash
cd skills/fuentes-material/scripts
uv run inventario.py --desde 2026-08-01 --hasta 2026-08-20 --resumen -o inventario.json
uv run validar_fechas.py --desde 2026-08-01 --hasta 2026-08-20 --plan correcciones.json
```

El primero dice qué hay. El segundo saca el reporte de lo que el usuario tiene
que confirmar. **No sigas al resto del pipeline hasta que las fechas estén
resueltas**: si un lote dice 2014 y el viaje fue en 2026, la línea de tiempo del
video va a salir revuelta y no se nota hasta el render.

`uv run` instala las dependencias solo (Pillow y pillow-heif, unos 30 MB la
primera vez). Los scripts viven en `scripts/` y comparten `fuentes.py`.

## Las fuentes

| Fuente | Cómo se pide | Dónde corre | Qué saca |
|---|---|---|---|
| App Fotos de macOS | `--fuente fotos` (default) | **solo macOS** | fechas con zona horaria, GPS ya convertido a nombres de lugar, favoritas, caras y personas con nombre, miniaturas locales, si el original está bajado |
| Carpeta normal | `--fuente carpeta:~/Pictures/Viaje` | cualquier sistema | fecha y GPS del EXIF, duración y tamaño, todo local |
| Cámara 360 | ver la sección de abajo | mixto | lo que se pueda; parte necesita al usuario |

Sin `--fuente`, en macOS se usa la app Fotos, más las carpetas que estén en
`REEL_FORGE_FUENTES` (separadas por `:`). Fuera de macOS solo esas carpetas, y si
no hay ninguna configurada el script lo dice en vez de adivinar.

Se pueden combinar, y `--fuente` es repetible:

```bash
uv run inventario.py --desde 2026-08-01 --hasta 2026-08-20 \
  --fuente fotos \
  --fuente carpeta:~/Pictures/Insta360 \
  --resumen -o inventario.json
```

---

## Apple Photos (macOS)

### Se lee la base, en solo lectura

La app Fotos guarda todo en `~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite`
(si el usuario la tiene en otro lado, se le pasa `--fuente fotos:/ruta/lib.photoslibrary`
o se exporta `REEL_FORGE_FOTOTECA`; también se acepta `REEL_FORGE_PHOTOS_LIBRARY`, que
algunos comandos del plugin usan).

Se abre así, y solo así:

```python
sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
```

- `mode=ro`: SQLite ni siquiera pide permiso de escritura.
- `immutable=1`: promete que nadie la está cambiando, así que SQLite **no lee el
  WAL ni crea archivos de bloqueo**. Es la única combinación con la que es
  imposible dañar la biblioteca aunque la app Fotos esté abierta.

El precio de `immutable=1` es que los cambios de los últimos minutos (una foto
recién importada, una favorita recién marcada) pueden no verse todavía, porque
viven en `Photos.sqlite-wal`. Cuando eso importa, `--copiar-base` copia
`Photos.sqlite` + `-wal` + `-shm` a una carpeta temporal y lee la copia: al día,
pero la base puede pesar varios GB.

### Permisos

La primera lectura falla con `unable to open database file` si el proceso no
tiene **Acceso total al disco**:

> Ajustes del sistema → Privacidad y seguridad → Acceso total al disco → agregar
> la app desde donde corres esto (Terminal, iTerm, Claude Code, VS Code…) y
> **reiniciarla**.

macOS no muestra un diálogo que se pueda aceptar desde una sesión remota: si el
usuario está en el teléfono, alguien tiene que aceptarlo físicamente en la Mac.
Díselo en vez de reintentar.

### Tablas que importan

| Tabla | Para qué |
|---|---|
| `ZASSET` | una fila por foto o video: fecha, GPS, tamaño, duración, favorita, oculta, en papelera |
| `ZADDITIONALASSETATTRIBUTES` | zona horaria, nombre de archivo original, tamaño en bytes, geocodificación inversa |
| `ZDETECTEDFACE` | cada cara detectada, con su posición y calidad |
| `ZPERSON` | las personas que el usuario ya nombró |
| `ZINTERNALRESOURCE` | qué versiones están bajadas y cuáles solo viven en iCloud |

Los detalles de columnas, trampas y consultas de ejemplo están en
[`referencia-photos.md`](referencia-photos.md). Lo que hay que tener presente
siempre:

- **Las fechas son de Core Data**: segundos desde el 1 de enero de 2001 UTC.
  `datetime(ZDATECREATED + 978307200, 'unixepoch')` da UTC. La hora de pared del
  lugar (la que el usuario recuerda) es esa más `ZTIMEZONEOFFSET`. Si pones una
  fecha en pantalla en el video, usa la hora local del lugar, no UTC: entre
  dos husos lejanos (p. ej. América y Asia) hay 12-15 horas y ahí se cuela un
  día entero.
- **`ZFAVORITE = 1`** marca las favoritas. Es la señal más barata y más honesta
  de qué le gustó al usuario: cuando hay que escoger tomas donde él sale, empezar
  por ahí y luego ampliar a lo que esté a ±10 minutos.
- **`ZDETECTEDFACE.ZCENTERY` viene invertida** (0 abajo, 1 arriba). Para recortar
  una cara sobre una imagen de alto `H`:
  `y = (1 - ZCENTERY) * H`, `x = ZCENTERX * W`, lado = `ZSIZE * max(W, H)`.
  Si lo haces al derecho, los recortes salen del pie en vez de la cara.
- **`ZTRASHEDSTATE = 0`** siempre, o acabas metiendo fotos que el usuario ya borró.

### Miniaturas: revisar sin bajar nada

Fotos ya generó una miniatura de cada asset y está en disco aunque el original
esté solo en iCloud:

```
<biblioteca>/resources/derivatives/<primera letra del UUID>/<UUID>_1_105_c.jpeg
```

Son de ~1200 px del lado largo: alcanzan de sobra para hojas de contacto, para
mirar expresiones y para recortar caras. Los videos dejan un `.THM` con el cuadro
de portada.

```bash
uv run exportar.py --miniaturas --ids elegidos.txt --destino ./contactos
```

**Este es el camino correcto:** revisar todo con miniaturas, decidir, y hasta
entonces bajar los originales de los elegidos. Bajar primero y decidir después
puede significar 100 GB de red para usar 30 archivos.

### Bajar los originales elegidos

Con [osxphotos](https://github.com/RhetTbull/osxphotos):

```bash
uv tool install osxphotos          # queda en ~/.local/bin/osxphotos
osxphotos --version
```

Y para exportar solo lo elegido:

```bash
uv run exportar.py --exportar --ids elegidos.txt --destino ./originales --dry-run
uv run exportar.py --exportar --ids elegidos.txt --destino ./originales
```

que por debajo corre:

```bash
osxphotos export ./originales \
  --uuid-from-file elegidos.txt \
  --download-missing --use-photokit \
  --skip-original-if-edited --export-by-date \
  --report ./originales/_reporte.csv --retry 3
```

- `--uuid-from-file`: un UUID por línea. Es lo que hace que baje 30 archivos y
  no la biblioteca entera.
- `--download-missing --use-photokit`: sin esto, los archivos que solo están en
  iCloud se exportan vacíos o no se exportan. PhotoKit es lo único que de verdad
  le pide el archivo a iCloud, y solo funciona en macOS.
- `--dry-run` primero, siempre: dice cuántos faltan (`missing: N`) sin usar red.
- Esto tarda por la red, no por el CPU. Con cientos de videos, avísale al usuario
  antes de arrancar.

Ojo: **el nombre del archivo exportado trae la hora del lugar** donde se tomó, y
la base guarda el instante en UTC. No mezcles las dos al nombrar carpetas.

---

## Carpetas normales (cualquier sistema operativo)

```bash
uv run inventario.py --fuente carpeta:~/Pictures/Viaje --desde 2026-08-01 --resumen
```

Recorre recursivamente (`--sin-recursion` para solo el primer nivel), ignora
archivos ocultos y lo que no sea foto ni video, y saca metadatos con lo que haya
instalado:

| Herramienta | Para qué | Si no está |
|---|---|---|
| Pillow + pillow-heif | EXIF de JPEG, PNG, TIFF, HEIC | se instalan solas con `uv run` |
| `ffprobe` (viene con ffmpeg) | duración, resolución, fecha y GPS de video | `brew install ffmpeg` · sin él no hay duración de video |
| `exiftool` | formatos raros: `.insv`, `.dng`, `.360` | `brew install exiftool` · se activa con `--exiftool` |

El orden con el que busca la fecha, de más a menos confiable:

1. `DateTimeOriginal` del EXIF (o `creation_time` / `com.apple.quicktime.creationdate` en video).
2. La fecha dentro del **nombre del archivo**: `IMG_20260815_143012.jpg`,
   `PXL_20260815_203012345.jpg`, `VID_20260819_160250_00_141.insv`, `2026-08-15 14.30.12.jpg`.
3. El `mtime` del archivo. **Este se marca como sospechoso**, porque copiar con
   `cp` o bajar de un disco externo lo reescribe.

El GPS sale del EXIF (`GPSLatitude`/`GPSLongitude`) o del `ISO6709` de Apple en
los `.mov`. En carpetas **no hay nombres de lugar**: el nombre bonito
("Oaxaca, México") solo lo trae la app Fotos, que ya hizo la geocodificación
inversa. Si el material es de carpeta y necesitas nombres, hay que geocodificar
aparte o preguntarle al usuario.

---

## Cámaras 360 y otras nubes

Lo que sí se puede automatizar y lo que no, dicho sin adornos.

### Insta360 (Studio, macOS y Windows)

| Cosa | ¿Automatizable? |
|---|---|
| Listar los `.insv` que ya están en disco | **Sí.** Son archivos normales: `--fuente carpeta:~/Movies/Insta360`. `exiftool` les saca fecha y a veces GPS. |
| Ver qué hay en la nube sin bajarlo | **A medias.** Studio deja miniaturas equirectangulares (2:1) en su carpeta de soporte; sirven para elegir. En macOS: `~/Library/Application Support/Insta360/Insta360 Studio/account_info/thumbnail/cloud_cache/`. Esa ruta cambia entre versiones: verifícala antes de confiar en ella. |
| Bajar de la nube | **No.** No hay API pública ni CLI. El usuario tiene que abrir Studio y bajarlos, o conectar la cámara por cable. |
| Coser (stitch) y exportar plano | **No desde consola.** Studio no trae CLI. La alternativa libre es [insv-stitch](https://github.com/BenjaminHenriksson/insv-stitch); el stitch que hace ffmpeg con `v360` trata cada lente como ojo de pez ideal y la costura se nota en objetos cercanos. |

En la práctica: **pídele al usuario que exporte de Studio lo que quiera usar**
(360 plano, con el horizonte ya nivelado) a una carpeta, y a partir de ahí todo
es una carpeta normal. Un `.insv` pesa mucho; no lo bajes "por si acaso".

### Google Photos, iCloud web, Dropbox y demás

- **Google Photos**: la API de Library ya no deja leer la biblioteca completa de
  un usuario desde una app de terceros. El camino real es **Google Takeout**, que
  el usuario pide y descarga él mismo; sale un ZIP con los archivos y un `.json`
  por foto con fecha y GPS. Una vez descomprimido es una carpeta normal.
- **iCloud en web**: no hay API. En macOS lo correcto es la app Fotos (arriba).
- **Dropbox, Drive, un disco externo**: si están montados, son carpetas normales.
  Ojo con las carpetas "solo en la nube" (Drive File Stream, iCloud Drive con
  "Optimizar almacenamiento"): el archivo parece existir pero leer su EXIF
  dispara una descarga. Cuando notes que un escaneo va lentísimo, es eso.

Regla general: si la fuente no se puede leer sin pasar por su app, di qué tiene
que hacer el usuario, en un paso concreto, en vez de inventar un rodeo frágil.

---

## Validación de metadatos

Esta es la parte que más problemas evita. `validar_fechas.py` busca cinco cosas:

| Caso | Qué es | Propuesta |
|---|---|---|
| `sin_fecha` | No hay EXIF, ni fecha en el nombre, ni nada | Asignar una a mano |
| `fecha_imposible` | Año anterior a 2000 (`--anio-minimo`) o en el futuro | Mover el grupo al día real |
| `lote_lejano` | Un grupo coherente entre sí pero a más de 180 días (`--dias-lejos`) de la mediana del material | Offset parejo en días, ya calculado |
| `solo_mtime` | La fecha viene del sistema de archivos, que se reescribe al copiar | Revisar |
| `desfase_horario` | Dos cámaras del mismo día con horas corridas un número casi entero | Offset en horas, ya calculado |

El caso clásico es la cámara externa (GoPro, Insta360, réflex) que perdió la pila
del reloj y arrancó en 2014 o en 1970: sus archivos son coherentes entre ellos,
solo están corridos en bloque.

### Cómo se ve el reporte

```
REPORTE DE METADATOS
============================================================
1 284 archivos · 2026-08-01T09:12:03-05:00 → 2026-08-14T22:41:19-05:00 (14 días)
GPS 91.4% · caras 38.2% · 27 sesiones
Lugares: Oaxaca de Juárez, México (412) · Puerto Escondido, México (338) · Hierve el Agua, México (96)

2 cosas que hay que confirmar:

[1] Fecha imposible  (120 archivos)
  120 archivos con fecha imposible (años 2014). Típico de una cámara externa sin pila de reloj.
    - GOPR0142.MP4 → 2014-01-01T00:04:11
    - GOPR0143.MP4 → 2014-01-01T00:07:52
    - GOPR0144.MP4 → 2014-01-01T00:11:30
    … y 117 más
  Propuesta: asignarles una fecha a mano (no se puede adivinar)
  Qué significa: Casi siempre es una cámara externa que perdió la hora. Si el resto del
  lote está bien, lo correcto es mover ese grupo al día real.
  Aceptar: --caso fecha_imposible --aceptar

[2] Desfase de zona horaria  (63 archivos)
  Los archivos DJI* van ~-5 h corridos respecto a los IMG* del mismo día. Suele ser la
  zona horaria de la cámara.
    - DJI_0031.JPG → 2026-08-06T04:22:10-05:00
    - DJI_0032.JPG → 2026-08-06T04:23:44-05:00
  Propuesta: mover el grupo +5 h
  Qué significa: Dos cámaras del mismo día con horas corridas. Si vas a intercalar sus
  tomas en un mismo video, hay que emparejarlas o el montaje sale revuelto.
  Aceptar: --caso desfase_horario --aceptar

Nada se modifica hasta que confirmes. Las correcciones quedan en el
plan JSON; los archivos originales y la app Fotos no se tocan.
```

**Enséñale este reporte al usuario y espera su respuesta.** No aceptes
propuestas por él: un offset mal puesto reordena el video entero.

### Confirmar

```bash
# aceptar el offset que el script calculó
uv run validar_fechas.py --plan correcciones.json --caso desfase_horario --aceptar

# poner una fecha a mano a todo un caso
uv run validar_fechas.py --plan correcciones.json --caso fecha_imposible --fecha 2026-08-06T10:00

# o un offset propio
uv run validar_fechas.py --plan correcciones.json --caso lote_lejano --offset-dias 4380
uv run validar_fechas.py --plan correcciones.json --caso desfase_horario --offset-horas 5

# marcarlo como revisado sin corregir
uv run validar_fechas.py --plan correcciones.json --caso solo_mtime --descartar
```

Todo queda en `correcciones.json`, que se ve así:

```json
{
  "version": 1,
  "creado": "2026-08-22T18:04:11-05:00",
  "correcciones": [
    {
      "ids": ["GOPR0142.MP4", "GOPR0143.MP4"],
      "accion": "offset_dias",
      "valor": 4600,
      "nota": "caso fecha_imposible",
      "confirmado": "2026-08-22T18:05:02-05:00"
    }
  ]
}
```

Los demás pasos de reel-forge leen ese archivo con
`validar_fechas.aplicar_plan(items, plan)` y trabajan con las fechas ya
corregidas. **Los archivos originales y la app Fotos no cambian.**

Si de plano hay que reescribir el EXIF de los archivos de una carpeta:

```bash
uv run validar_fechas.py --fuente carpeta:~/Pictures/Viaje \
  --plan correcciones.json --aplicar-exiftool          # muestra qué haría
uv run validar_fechas.py --fuente carpeta:~/Pictures/Viaje \
  --plan correcciones.json --aplicar-exiftool --si     # lo hace
```

Solo toca archivos de fuente `carpeta`, nunca la app Fotos, y exiftool deja un
`_original` de respaldo junto a cada archivo. Para cambiar una fecha dentro de
Fotos, el usuario lo hace en la app: seleccionar → **Imagen → Ajustar fecha y hora**.

### Sesiones

Un hueco de más de 90 minutos abre una "sesión" nueva (`--hueco-min`). Es la
unidad natural de un viaje: una comida, una caminata, un atardecer. Sirve mucho
más que los días del calendario para armar la estructura del reel, porque un día
con 400 fotos son en realidad seis momentos distintos.

---

## `inventario.py`: el JSON

```bash
uv run inventario.py --desde 2026-08-01 --hasta 2026-08-14 \
  --fuente fotos --fuente carpeta:~/Pictures/GoPro \
  --resumen -o inventario.json
```

Salida (recortada, con datos de ejemplo):

```json
{
  "generado": "2026-08-22T18:02:44-05:00",
  "rango_pedido": { "desde": "2026-08-01", "hasta": "2026-08-14" },
  "fuentes": [
    {
      "tipo": "apple-photos",
      "biblioteca": "~/Pictures/Photos Library.photoslibrary",
      "modo_lectura": "mode=ro&immutable=1",
      "aviso_wal": "Con immutable=1 no se lee el WAL: los cambios de los últimos minutos pueden faltar. Usa --copiar-base si acabas de importar o marcar favoritas.",
      "items": 1164
    },
    {
      "tipo": "carpeta",
      "raiz": "~/Pictures/GoPro",
      "archivos_ignorados": 3,
      "herramientas": { "ffprobe": true, "exiftool": true },
      "items": 120
    }
  ],
  "conteos": {
    "total": 1284,
    "fotos": 1041,
    "videos": 231,
    "material_360": 12,
    "favoritas": 143,
    "capturas_pantalla": 8
  },
  "rango_real": {
    "primera": "2026-08-01T09:12:03-05:00",
    "ultima": "2026-08-14T22:41:19-05:00",
    "dias": 14
  },
  "gps": { "con_gps": 1174, "pct": 91.4, "sin_gps": 110 },
  "lugares": [
    { "lugar": "Oaxaca de Juárez, México", "n": 412,
      "primera": "2026-08-01T09:12:03-05:00", "ultima": "2026-08-05T23:10:44-05:00" },
    { "lugar": "Puerto Escondido, México", "n": 338,
      "primera": "2026-08-06T07:41:12-05:00", "ultima": "2026-08-11T19:55:01-05:00" }
  ],
  "caras": {
    "con_caras": 490, "pct": 38.2,
    "personas": [
      { "nombre": "Ana Reyes", "fotos": 212 },
      { "nombre": "Luis Mena", "fotos": 87 }
    ]
  },
  "video": { "clips": 243, "duracion_total_s": 8742.6, "duracion_total_min": 145.7 },
  "sesiones": {
    "hueco_min": 90,
    "total": 27,
    "lista": [
      { "sesion": 1, "inicio": "2026-08-01T09:12:03-05:00", "fin": "2026-08-01T11:48:20-05:00",
        "duracion_min": 156.3, "n": 74, "fotos": 68, "videos": 6, "favoritas": 9,
        "con_caras": 31, "lugar": "Oaxaca de Juárez, México" }
    ]
  },
  "sospechas_fecha": [
    {
      "caso": "fecha_imposible",
      "n": 120,
      "ids": ["GOPR0142.MP4", "GOPR0143.MP4"],
      "ejemplos": ["GOPR0142.MP4 → 2014-01-01T00:04:11"],
      "anios": [2014],
      "mensaje": "120 archivos con fecha imposible (años 2014). Típico de una cámara externa sin pila de reloj.",
      "propuesta": { "accion": "asignar_fecha", "valor": null }
    }
  ],
  "descarga": {
    "originales_locales": 402,
    "faltantes": 882,
    "bytes_estimados": 41234567890,
    "gb_estimados": 38.4,
    "exactitud": "exacta",
    "con_miniatura_local": 1150
  },
  "avisos": []
}
```

Notas sobre el JSON:

- `rango_real` puede no coincidir con `rango_pedido`: ahí ya se ve si el usuario
  se equivocó de fechas.
- `descarga.exactitud` dice `"exacta"` cuando todos los tamaños salieron de la
  base, o `"aproximada (N sin tamaño en la base)"` cuando hubo que estimar
  (4 MB por foto, 90 MB por video, 400 MB por archivo 360).
- `con_miniatura_local` es cuántos se pueden revisar **sin bajar nada**. Si ese
  número es alto, empieza por ahí.
- Con `--incluir-items` se agrega la lista completa de archivos. Pesa, pero es lo
  que consume el siguiente paso del pipeline.
- `--sesiones-completas` agrega los ids de cada sesión.

### Banderas que vas a usar seguido

```bash
--solo-favoritas          # solo ZFAVORITE=1: lo que al usuario ya le gustó
--persona "Ana Reyes"     # solo donde Fotos reconoció a esa persona
--sin-capturas            # fuera las capturas de pantalla
--incluir-ocultas         # incluye el álbum Oculto (por default no)
--copiar-base             # lee la copia con WAL: al día, más lento
--hueco-min 45            # sesiones más finas
--exiftool                # respaldo para formatos raros en carpetas
```

Para saber a quién se puede filtrar:

```bash
uv run python -c "import fuentes, json; print(json.dumps(fuentes.personas_de_la_biblioteca(minimo=20), ensure_ascii=False, indent=2))"
```

---

## Qué entregarle al usuario

Después de correr las dos herramientas, dile en pocas líneas:

1. Cuánto material hay y de qué días y lugares.
2. Cuántas sesiones salieron (eso adelanta cuántos momentos distintos hay).
3. **Lo que necesita confirmar**, con el reporte de fechas tal cual.
4. Cuántos GB habría que bajar si se usara todo, y que lo normal es revisar con
   miniaturas y bajar solo lo elegido.

No arranques la investigación de tendencias ni la edición hasta que conteste lo
de las fechas.

## Límites honestos

- **La app Fotos solo existe en macOS.** En Linux o Windows esta skill funciona
  únicamente con carpetas: sin favoritas, sin personas con nombre, sin nombres de
  lugar y sin miniaturas gratis.
- **Sin Acceso total al disco no hay nada que hacer**, y ese permiso se acepta a
  mano en la Mac.
- **Los nombres de lugar solo salen de Apple Photos.** En carpetas hay
  coordenadas, no nombres.
- **Las miniaturas no sirven para el render final**: son ~1200 px. Sirven para
  elegir.
- **`--download-missing` necesita red y paciencia**, y `--use-photokit` solo
  funciona en macOS.
- **Insta360 y Google Photos no tienen forma pública de bajar en bloque.** Ahí el
  usuario tiene que hacer su parte.
