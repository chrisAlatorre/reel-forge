---
description: Convierte fotos y videos del usuario en TikToks/Reels verticales, de punta a punta - detecta fuentes, valida metadatos, investiga tendencias, analiza el material con agentes en paralelo y entrega varios conceptos con variantes.
argument-hint: "[tema o descripción libre] [--auto] [--rapido] [--fechas AAAA-MM-DD..AAAA-MM-DD] [--lugar \"Ciudad\"] [--sin-tendencias]"
---

# /reel — recap vertical de punta a punta

Argumentos recibidos: `$ARGUMENTS`

Tu trabajo es entregar **varios conceptos de video vertical 1080x1920, con variantes cada uno**, a partir del material que el usuario ya tiene. Eres **autónomo por defecto**: investigas, decides y renderizas. Preguntas solo lo imprescindible, agrupado, **una sola vez**.

## Banderas

| Bandera | Efecto |
|---|---|
| `--auto` | Cero preguntas. Asumes todo con las reglas de "Cuando no puedas preguntar" y avisas al final qué asumiste. |
| `--rapido` | Menos agentes (ver tabla de escalado), 2 conceptos x 2 variantes, sin investigación profunda de tendencias. |
| `--fechas A..B` | Rango de fechas ya dado; no lo preguntas. |
| `--lugar "X"` | Lugar o lugares ya dados; no los preguntas. |
| `--sin-tendencias` | Te saltas el paso 4 y usas los formatos base de `referencias/conceptos.md`. |
| `--fuente RUTA` | Fuerza una carpeta o biblioteca concreta y omite la detección. |

Todo lo demás en `$ARGUMENTS` es el **tema** en lenguaje natural ("viaje a la playa", "un día en la oficina", "mi perro", "la cosecha").

## Skills y agentes

Skills del plugin (se invocan como `reel-forge:<nombre>`):

| Skill | Para qué |
|---|---|
| `reel-forge` | El orquestador: las reglas de selección, el reparto de agentes y el detalle de cada fase en `referencias/` |
| `fuentes-material` | Detectar e inventariar bibliotecas y carpetas, leer metadatos y validar fechas |
| `motor-video` | El motor: spec JSON → MP4 9:16, efectos, textos, looks, música y mezcla |
| `video-360` | Reencuadre de material 360 (Insta360 y similares) a 9:16 |
| `voces` | Narración con TTS local y la voz de CapCut |

No hay skill de tendencias ni de retoque de fotos: las tendencias las investiga el agente
`investigador-tendencias` (detalle en `skills/reel-forge/referencias/tendencias.md`) y el plugin **no
retoca personas** — el único tratamiento de imagen es el `look` del render.

Agentes que lanzas en paralelo (`reel-forge:<nombre>`):

| Agente | Qué hace | Cuándo |
|---|---|---|
| `curador-fotos` | Revisa un lote de fotos: descarta gestos a medias, ojos cerrados, repetidas, tickets y capturas; marca las buenas con calidad de 1 a 10 | Paso 5, 1 por día o por lote de ~150 |
| `analista-video` | Ve un video en tiras de cuadros, transcribe y devuelve tramos con `inicio_s`/`fin_s` | Paso 5, 1 por video (o por 3-4 cortos) |
| `explorador-360` | Saca encuadres 9:16 de un equirectangular: hojas, yaw/pitch y keys verificadas con render | Paso 5, 1 por clip 360 |
| `investigador-tendencias` | Busca en la web formatos y sonidos del momento para el tema, con fuente y fecha | Paso 4, 1-3 agentes |
| `director-creativo` | Propone **un** concepto desde un ángulo asignado, con estructura segundo a segundo | Paso 6, 4-8 en paralelo |
| `editor-en-jefe` | Lee todos los conceptos juntos, elige buscando variedad y dice qué ajustar | Paso 6, siempre 1 |
| `constructor-video` | Construye una variante: escribe `build.py` y el spec, renderiza y revisa su tira de cuadros | Paso 7, 2 por concepto |
| `revisor-critico` | Compara las variantes del concepto entre sí, verifica con mediciones y **corrige** re-renderizando | Paso 8, 1 por concepto |

Con material abundante, los pasos 5, 7 y 8 se pueden correr con los workflows del plugin, que guardan
en disco lo que devuelve cada agente y permiten retomar una corrida interrumpida:
`workflows/catalogo.js` (paso 5) y `workflows/construir.js` (pasos 7 y 8).

### Escalado de agentes

Cuenta el material **después** de filtrar por fechas y lugares:

```
lotes_fotos  = techo(n_fotos / 150)      # o uno por día, lo que dé más lotes
lotes_clips  = techo(n_clips / 4)
lotes_360    = n_clips_360               # siempre uno por clip
agentes_catalogo = min(lotes_fotos + lotes_clips + lotes_360, TOPE)
```

| Modo | TOPE catálogo | Tendencias | Directores | Construcción |
|---|---|---|---|---|
| normal | 10 | 2 | 4-8 + 1 editor en jefe | 3 conceptos x 2 constructores |
| `--rapido` | 4 | 0-1 | 3 + 1 editor en jefe | 2 conceptos x 2 constructores |
| menos de 30 piezas | 2 | 1 | 3 + 1 editor en jefe | 2 conceptos x 2 constructores |

**Tope práctico: ~10 agentes a la vez.** La máquina además está decodificando video, y `ffmpeg` ya usa
varios núcleos por su cuenta: más agentes no van más rápido, van más lento. Con 4 conceptos, la
construcción va en dos oleadas. Si un lote tarda más de ~10 min, córtalo en dos en vez de esperar.
La tabla completa y sus porqués están en `docs/paralelismo.md`.

---

## Paso 1 — Detectar fuentes (automático, sin preguntar todavía)

Corre la detección **antes** de hablar con el usuario, para que las preguntas ya lleven opciones reales.

Invoca `reel-forge:fuentes-material` (o, si no está disponible, haz la detección a mano con lo de abajo) y busca:

1. **Biblioteca nativa del sistema**
   - **macOS:** Apple Photos. Requiere `osxphotos` (`uv tool install osxphotos`). La biblioteca vive normalmente en `~/Pictures/Photos Library.photoslibrary`, o donde apunte `REEL_FORGE_PHOTOS_LIBRARY`. **Esto es exclusivo de macOS.**
   - **Otros sistemas / sin osxphotos:** no hay biblioteca nativa que leer. Camino alternativo: carpetas con EXIF (punto 2). Dilo explícitamente, no lo simules.
2. **Carpetas** — revisa las que existan: `~/Pictures`, `~/Movies` (o `~/Videos`), `~/Desktop`, `~/Downloads`, y cualquier volumen montado con `DCIM/` (tarjetas SD, teléfono conectado).
3. **Nube o app de cámaras 360** — Insta360 Studio y similares (**app de escritorio, macOS o Windows**). En macOS, las miniaturas de la nube suelen estar bajo `~/Library/Application Support/Insta360/`; los originales `.insv` hay que bajarlos desde la app. Alternativa sin la app: archivos `.insv`/`.insp` ya copiados a disco, que la skill `reel-forge:video-360` puede procesar directo.
4. **Cámaras de acción y drones** — patrones de nombre: `GX######.MP4`, `GOPR####` (GoPro), `DJI_####` (drone), `DJI_*_D.MP4` (D-Log). Busca en carpetas y volúmenes del punto 2.
5. **Configuración del usuario** — si existe `~/.config/reel-forge/config.json`, sus rutas mandan sobre todo lo anterior. Variables de entorno: `REEL_FORGE_FUENTES` (lista separada por `:`), `REEL_FORGE_SALIDA`, `REEL_FORGE_TALLER`.

Salida de este paso: una tabla corta con fuente, cantidad de fotos/videos, rango de fechas y si los originales están **locales o en nube** (los de nube hay que bajarlos y eso tarda).

## Paso 2 — Las preguntas (máximo 4, en UN solo mensaje)

Si hay `--auto`, sáltate esto entero. Si no, manda **un** mensaje con lo que falte, ya con opciones numeradas para que conteste con números:

1. **Fuentes** — "Encontré A, B y C. ¿Uso las tres o solo alguna?" (si solo hay una fuente, no preguntes: úsala).
2. **Rango de fechas y/o lugares** — propón tú los candidatos que viste: "el material se agrupa en tres bloques: 3-9 de marzo, 14 de abril y 2-6 de junio. ¿Cuál?". Si `--fechas` o `--lugar` vinieron en los argumentos, no preguntes.
3. **Tema y tendencias** — "¿Investigo tendencias actuales? ¿De qué tema: viajes, día en el trabajo, mascotas, campo, comida, deporte, otro?". Si el tema ya venía en `$ARGUMENTS`, solo confirma el tema dentro de otra pregunta, no gastes una entera.
4. **Incoherencias de metadatos** — solo si el paso 3 encontró algo (ver abajo). Se pregunta junto con las demás, no después.

Reglas: nada de preguntas de estilo, duración, música o formato — eso lo decides tú y lo presentas como conceptos distintos. No preguntes dos veces. Si el usuario contesta a medias, asume el resto y sigue.

**Cuando no puedas preguntar** (`--auto`, o el usuario no responde): usa todas las fuentes locales, toma el bloque de fechas más grande y reciente, tema = el más obvio por lugares y contenido, tendencias = sí.

## Paso 3 — Validar metadatos y avisar de incoherencias

Antes de analizar nada, revisa fecha, hora y ubicación de cada pieza (`exiftool`, `ffprobe`, o los campos de la biblioteca). Busca específicamente:

- **Fecha imposible o de fábrica**: 1970, 2000-01-01, o años antes del resto del lote. Típico de cámara externa (acción, 360, drone, réflex) a la que nunca le pusieron la hora. Se detecta porque un grupo entero de archivos comparte un desfase constante.
- **Desfase de zona horaria**: la hora del nombre del archivo no coincide con la hora de la biblioteca. Puede meter un día entero de diferencia y hacer que un texto en pantalla diga la fecha equivocada. Compara siempre contra el resto del material del mismo día.
- **Sin ubicación**: cámaras externas casi nunca traen GPS. Se puede inferir por cercanía temporal con una foto del teléfono que sí la tenga (±30 min).
- **Sin EXIF**: archivos que pasaron por WhatsApp o mensajería. Solo queda la fecha del sistema de archivos, que no es confiable.
- **Duplicados y ráfagas**: agrúpalos; la ráfaga se trata como una sola escena de la que se escoge la mejor toma.

Cuando encuentres algo, **avísalo en la pregunta agrupada del paso 2** con números concretos y una propuesta:

> Encontré 48 archivos de una cámara externa fechados en 2015; por cercanía deberían ser del 14-16 de abril (desfase de −9 años 1 mes 3 días). ¿Los corrijo con ese desfase, uso otra fecha o los dejo fuera?

Si el usuario acepta corregir, **no toques los originales**: escribe la corrección en un manifiesto del proyecto (`fechas.json` en la carpeta de taller) y que todo el resto del flujo lea de ahí. Solo si el usuario lo pide explícitamente se reescribe EXIF, y siempre sobre copias.

Con `--auto`: aplica el desfase inferido cuando la evidencia sea fuerte (grupo completo con desfase constante y solapamiento claro con material fechado bien); si no, deja esas piezas fuera y repórtalo.

## Paso 4 — Tendencias (en paralelo con el paso 5)

Salvo `--sin-tendencias`, lanza `investigador-tendencias` (1-3 agentes según el escalado) con el tema confirmado. Lo que tiene que volver, con fecha y fuente:

- Formatos vigentes para ese tema y su duración óptima.
- Sonidos concretos: título, artista, **BPM medido** (no estimado), y si están en tendencia en el país del usuario.
- Estilos de texto y de narración que están funcionando, y los que ya se ven viejos.

**Nunca inventes canciones "en tendencia" ni BPM.** Si el agente no lo pudo medir, el concepto va sin corte al beat. Detalle completo en `/reel-tendencias`.

## Paso 5 — Análisis del material (agentes en paralelo)

Reparte el material según la fórmula de escalado.

- `curador-fotos` por lotes de fotos: devuelve, por foto, si sirve y por qué no si no sirve (gesto a medias, ojos cerrados, cara cortada, movida, repetida). Con ráfagas, elige **una** y descarta el resto.
- `analista-video` por lotes de clips: tira de cuadros + transcripción del audio, y devuelve momentos con `inicio_s`, `fin_s`, qué pasa, qué se oye y qué tan fuerte es como gancho. Un clip largo casi siempre tiene 10 s buenos y el resto relleno; el catálogo es lo que evita usar el pedazo malo.
- Material 360: el catálogo va por **dirección** (yaw/pitch), no solo por tiempo — el mismo segundo tiene varias tomas posibles. Lo hace `explorador-360`, uno por clip. Ver `reel-forge:video-360`.

Todos los agentes escriben a un catálogo común en la carpeta de taller. **La ventana `inicio_s`/`fin_s` del catálogo manda**: quien la ignore acaba usando un cuadro que no es el que se catalogó.

## Paso 6 — Conceptos (directores + editor en jefe)

Dos pasos, y el orden importa.

**6a. Directores.** Lanza de **4 a 8 `director-creativo` en paralelo**, cada uno con el catálogo
completo, las tendencias y **un ángulo distinto y explícito** que tú le asignas: documental narrado,
puro sonido real, guía con precios, gag visual, POV, lista con remate, contador de bloques. No se ven
entre sí: la variedad sale de los ángulos que repartas, no de pedirles "algo distinto". Cada uno
devuelve **un solo concepto** con:

- Gancho del primer segundo (la toma más fuerte va primero).
- Estructura segundo a segundo, con un mini gancho cada 3-5 s.
- Duración objetivo y si corta al beat o al sonido real.
- Si lleva narración, música, o solo audio diegético.
- Qué momentos del catálogo usa, **por id**, y la proporción de cortes con y sin el sujeto.

**6b. Editor en jefe.** Un solo `editor-en-jefe` los lee todos juntos y elige **3** (2 con `--rapido`)
buscando variedad real, descarta los repetidos y los débiles, y dice exactamente qué ajustar en cada
uno antes de construirlo. Es el único punto del flujo donde alguien ve todas las propuestas a la vez;
dos editores en jefe se contradicen y se pierde la variedad.

Un concepto que use un id que no existe en el catálogo es un defecto grave: no se construye.

Tú confirmas la selección en una línea y sigues. **No le pidas al usuario que elija concepto**: elegir
es mucho más fácil viendo los videos.

## Paso 7 — Variantes

Por concepto, **2 variantes** con un `constructor-video` cada una. Las variantes cambian algo que se note: duración, con o sin voz, orden del gancho, música contra sonido real. Cada constructor:

1. Escribe su `build.py`, que genera el spec JSON y renderiza con el motor de `reel-forge:motor-video`
   (`uv run "$CLAUDE_PLUGIN_ROOT/skills/motor-video/scripts/render.py" spec.json`). El `build.py` tiene
   que reconstruirlo todo desde cero, sin depender de temporales.
2. Saca su propia tira de cuadros y **la mira**: texto legible, que no tape caras, recortes que no corten cabezas, datos y fechas correctos.
3. Deja el proyecto reproducible: un script que reconstruye todo desde cero, no un spec suelto que apunta a temporales.

Reglas transversales que todo constructor respeta:

- **Que no salga la misma persona en todos los cortes.** Mezcla paisaje, detalle, comida, gente, momentos sin nadie. Un video donde el autor sale en cada corte se lee como narcisista.
- Zona segura vertical: 150 px arriba, 480 px abajo (ahí van los botones de la app), 180 px a la derecha.
- Cortes secos con punch-in. Nada de fundidos cruzados, barridos ni glitch RGB.
- Grano casi invisible.
- **Música con copyright: nunca incrustada en la versión para subir.** Se entregan dos archivos: el limpio y uno `-preview` con la canción solo para revisar. La canción real se pone en la app, que además hace que cuente para la tendencia.
- Ningún texto con dato (fecha, lugar, precio) que no hayas verificado contra los metadatos o contra una fuente.

## Paso 8 — Verificar y entregar

Un `revisor-critico` por concepto compara **entre** variantes, no solo dentro de cada una: mismo cuadro con distinto tratamiento, `look` distinto por descuido, la misma toma repetida en dos cortes. Checklist técnico:

- Cuadros negros, silencios largos y picos de audio (el pico final debe quedar por debajo de −0.5 dBTP).
- La pista de audio dura exactamente lo que dura el video (si la canción se acaba antes, los últimos segundos salen mudos y nada avisa).
- Una tira de cuadros por variante, mirada de verdad.
- Cuenta a mano en cuántos cortes sale la persona principal.

Entrega en `~/Videos/reel-forge/<proyecto>/` (o `REEL_FORGE_SALIDA`):

- MP4 1080x1920 limpios, con compresión suficiente para que pesen menos de ~30 MB.
- Copias ligeras de 720p para mandar por mensajería.
- Un solo `README.md` por proyecto: qué es cada variante, qué sonido ponerle en la app, los hashtags sugeridos (3-5) y, si hay narración sin voz incrustada, el guion con los segundos.

Cierra con un resumen de 5-8 líneas: qué conceptos hay, en qué se diferencian, qué asumiste y qué falta por decidir. Nada de relleno.

## Si algo falla

- **No hay material en el rango**: dilo y propón el rango contiguo que sí tiene material. No amplíes por tu cuenta sin avisar.
- **Originales en la nube**: baja solo los elegidos, después de la curaduría, nunca toda la biblioteca.
- **Poco espacio en disco**: `/reel-fuentes` lo reporta. Si hay menos de ~20 GB libres, trabaja con proxys de baja resolución y avisa.
- **Un agente se atora**: no lo esperes indefinidamente. Sigue con lo que hay y anota en el README qué quedó sin catalogar.
