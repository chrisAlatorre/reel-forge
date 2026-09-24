---
name: motor-video
description: Motor de render de reel-forge. Convierte un spec JSON en un video vertical 9:16 (1080x1920) listo para TikTok, Reels o Shorts, con fotos, clips, reencuadres 360 y mapas animados; textos con zona segura, looks de color, grano de película y mezcla de audio. Úsala cuando haya que renderizar, ajustar o depurar un video del plugin.
---

# Motor de video (spec JSON → 9:16)

Todo corre local. La entrada es un archivo JSON; la salida, un MP4 de 1080x1920.
El motor arma cada cuadro en numpy y lo codifica con ffmpeg: no depende de ningún
editor ni servicio.

```bash
R=${CLAUDE_PLUGIN_ROOT}/skills/motor-video/scripts/render.py
uv run "$R" mi-spec.json
uv run "$R" mi-spec.json --out ~/Videos/otra-ruta.mp4
```

Hay un spec de ejemplo comentado, con todos los tipos de segmento y todos los estilos de
texto, en **`ejemplos/spec-ejemplo.json`** del plugin. Es JSON válido: el motor ignora las
claves que empiezan con guion bajo, así que los comentarios se pueden dejar en los specs de
trabajo.

Archivos:

| Archivo | Qué hace |
|---|---|
| `scripts/render.py` | Motor: lee el spec, arma los cuadros, mezcla el audio, codifica. |
| `scripts/efectos.py` | Segmentación de personas, texto detrás del sujeto, presentación de personaje, mapa de ruta. |
| `scripts/config.py` | Lienzo, zona segura y rutas configurables por variables de entorno. |
| `scripts/tipografias.py` | Baja tipografías, mapa base y modelo de segmentación. |

## Requisitos

- `ffmpeg` y `ffprobe` en el PATH (`brew install ffmpeg`, `apt install ffmpeg`).
- `uv` para correr los scripts: la cabecera `# /// script` declara las dependencias
  (numpy, opencv, pillow, pillow-heif y, solo si se usan, mediapipe y telemetry-parser).
- **Multiplataforma**, con dos salvedades de macOS:
  - Las tipografías de repuesto para tailandés y CJK que trae `config.py` por default son rutas
    de macOS. En Linux o Windows instala Noto (`Noto Sans Thai`, `Noto Sans CJK`) y apúntalas con
    `REEL_FORGE_FONT_THAI` / `REEL_FORGE_FONT_CJK`.
  - Los alfabetos con marcas combinadas (tailandés, árabe, índicos) necesitan **libfribidi**
    para que Pillow use raqm. En macOS con Homebrew el motor se re-ejecuta solo con el
    `DYLD_FALLBACK_LIBRARY_PATH` correcto; en Linux basta con tener `libfribidi` instalada.
    Sin ella, las marcas de vocal salen como círculos punteados.

## Primer arranque: recursos

```
uv run "${CLAUDE_PLUGIN_ROOT}/skills/motor-video/scripts/tipografias.py" --todo
```

Baja a `$REEL_FORGE_CACHE` (default `~/.cache/reel-forge`):

- **Montserrat** (sans variable) e **Instrument Serif** (itálica), del repositorio oficial de Google Fonts.
- `ne_50m_land.geojson` de **Natural Earth** (dominio público), para el segmento `map`.
- `selfie_multiclass.tflite` de **MediaPipe** (Apache-2.0), para `behind` y `cutout`.

### Licencia de las tipografías (importante)

Montserrat e Instrument Serif están bajo **SIL Open Font License 1.1 (OFL)**: uso libre,
también comercial, e incrustación en videos sin problema. La OFL exige conservar el aviso de
licencia y prohíbe vender las fuentes por separado. Por eso **el repo no incluye los .ttf**:
`tipografias.py` los baja junto con su `OFL-*.txt`, que hay que dejar al lado de los archivos.
Si prefieres otra tipografía, apúntala con `REEL_FORGE_FONT_SANS` / `REEL_FORGE_FONT_SERIF`
(cualquier `.ttf`/`.otf`; si la sans es variable, el motor le pide peso 700/850).

## Configuración (variables de entorno)

| Variable | Default | Para qué |
|---|---|---|
| `REEL_FORGE_CACHE` | `~/.cache/reel-forge` | Raíz de los recursos que se bajan solos |
| `REEL_FORGE_FONTS` | `$REEL_FORGE_CACHE/fonts` | Tipografías |
| `REEL_FORGE_ASSETS` | `$REEL_FORGE_CACHE/assets` | Mapa base, efectos de sonido |
| `REEL_FORGE_MODELS` | `$REEL_FORGE_CACHE/models` | Modelo de segmentación |
| `REEL_FORGE_HOME` | `~/Movies/reel-forge` (o `~/Videos/...`) | Raíz de los proyectos |
| `REEL_FORGE_SALIDA` | `$REEL_FORGE_HOME` | Base de los `out` relativos del spec |
| `REEL_FORGE_FONT_SANS` / `_SERIF` | Montserrat / Instrument Serif | Cambiar de tipografía |
| `REEL_FORGE_FONT_THAI` / `_CJK` | autodetección | Alfabetos que la sans no cubre |
| `REEL_FORGE_360_SCRIPTS` | skill hermano `video-360` | De dónde importar `reencuadre360.py` |

Un `"out"` relativo (`"viaje/dia-uno-A.mp4"`) cuelga de `REEL_FORGE_SALIDA`; uno absoluto, con `~`
o con `$VARIABLE` se respeta tal cual. Lo mismo aplica a los `src`: un spec puede escribir
`"$REEL_FORGE_ASSETS/sfx/obturador.mp3"` y el motor lo expande.

---

## El spec JSON, completo

```jsonc
{
  "out": "proyecto/video.mp4",   // relativo a REEL_FORGE_SALIDA, o absoluta / con ~ / con $VAR
  "fps": 30,                     // default 30
  "crf": 22,                     // calidad x264: 22 ≈ 6 Mbps. Default 22
  "look": "film",                // "film" | "teal" | "clean"
  "grain": 0.008,                // grano de película; el motor lo topa en 0.012
  "fade_out": 0.4,               // segundos de fundido a negro al final (0 = corte seco)
  "audio_fade_out": 1.2,         // salida del audio; 0 en videos pensados para loop
  "bpm": 123.0,                  // si algún segmento usa "beats"
  "beat0": 0.0,                  // segundo en el que cae el primer beat

  "segments": [ /* ver abajo */ ],
  "captions": [ /* ver abajo */ ],
  "audio": [ /* pistas que SÍ van en la versión limpia */ ],
  "preview_audio": { /* canción con copyright, solo para revisar */ }
}
```

El motor escribe **dos archivos** cuando hay `preview_audio`:
`video.mp4` (limpio, el que se sube) y `video-preview.mp4` (con la canción, solo para ver).

### Segmentos

Cada segmento aporta **solo imagen**. Su duración se declara con `dur` (segundos) o con
`beats` (requiere `bpm`). Los tiempos se calculan sobre una rejilla absoluta, así que los
cortes no acumulan desfase aunque haya 40 segmentos.

**Cuatro tipos de fuente:**

```jsonc
// 1. Foto (jpg, png, heic — HEIC funciona por pillow-heif; ffmpeg NO abre HEIC)
{"src": "~/fotos/templo.jpg", "beats": 2, "focus": [0.5, 0.4], "kb": 0.06, "punch": 0.10}

// 2. Clip de video (mov, mp4, m4v, mkv). HDR se convierte solo a SDR.
{"src": "~/videos/rio.mov", "dur": 2.4, "start": 12.0, "speed": 0.5, "focus": [0.62, 0.5]}

// 3. Clip 360 reencuadrado con cámara virtual (requiere el motor 360 del plugin)
{"src": "VID_0012.insv", "dur": 4, "start": 12, "r360": "keys.json"}
{"src": "VID_0012.insv", "dur": 4, "r360": {"keys": [...], "estab": "gyro"}}

// 4. Mapa animado de ruta (sin src)
{"map": {"bbox": [-10.0, 20.0, 35.0, 52.0],
         "stops": [[-9.14, 38.72, "Lisboa"], [-3.70, 40.42, "Madrid"], [12.50, 41.90, "Roma"]]},
 "dur": 5}
```

**Modificadores comunes** (todos opcionales):

| Clave | Default | Qué hace |
|---|---|---|
| `dur` / `beats` | — | Duración. Uno de los dos, obligatorio. |
| `start` | 0 | Segundo de entrada dentro del clip fuente. |
| `speed` | 1 | `0.5` = cámara lenta. Con material de 60 fps es lenta **real**, sin interpolar. |
| `focus` | `[0.5, 0.5]` | Punto (0-1) que queda al centro al recortar a 9:16. La clave para fotos apaisadas. |
| `fit` | cubrir | `"blur"` encaja la imagen completa entre dos bandas desenfocadas de sí misma. |
| `kb` | 0.05 | Ken Burns: zoom lento y continuo durante el segmento. |
| `punch` | 0 | Zoom de golpe al entrar que se asienta en ~0.22 s. `0.08`-`0.12` es lo natural. |
| `drift` | `[0, 0]` | Desplazamiento lateral/vertical del encuadre a lo largo del segmento. |
| `stutter` | — | Entero: repite cada cuadro N veces. `6` = efecto de pocos fps al caminar. |
| `freeze` | false | Congela el primer cuadro todo el segmento (para `cutout`). |
| `flash` | false | Flash blanco de 3 cuadros al entrar. Solo en el drop, una vez por video. |
| `behind` | — | Texto gigante **detrás del sujeto** (ver abajo). |
| `cutout` | — | Presentación de personaje con recorte (ver abajo). |

**`behind` — texto detrás del sujeto**

```jsonc
"behind": {"text": "VERANO", "size": 250, "y": 0.16, "style": "bold", "at": 0.0,
           "color": [255, 255, 255]}
```

Recorta a la persona y la vuelve a pegar encima del texto. **Solo se lee como efecto si la
cabeza o el torso tapan parte del texto**: elige una foto donde el sujeto salga grande y pon
`y` a la altura de su cabeza. Máximo una o dos veces por video. El tamaño baja solo hasta
que el texto quepa a lo ancho.

**`cutout` — presentación de personaje**

```jsonc
{"src": "foto.jpg", "dur": 2.6, "freeze": true,
 "cutout": {"y": 0.62, "lines": ["28 años", "3 países en 20 días", "0 planes"]}}
```

Congela el cuadro, apaga y desenfoca el fondo, recorta al sujeto con contorno blanco y hace
entrar fichas escalonadas. Las fichas tienen que hablar **del sujeto recortado**, no de lo que
está detrás. Va bien con un obturador y pops.

Tanto `behind` como `cutout` usan MediaPipe selfie multiclass. Si el skill de fotos está
disponible, la máscara se acota con la silueta de Pose para que el modelo no confunda pelaje
de animal con pelo humano. Si aparecen recuadros negros en el video, es NaN en la máscara.

### Captions (textos)

```jsonc
{"t0": 0.0, "t1": 2.4, "text": "cosas que nadie\nte dice de esto",
 "style": "clean", "pos": "low", "size": 58, "color": [255, 212, 0],
 "pop": true, "words": false, "dx": 0, "dy": -128}
```

- `t0` / `t1` son tiempo **global** del video, no del segmento.
- `words: true` parte el texto en grupos de hasta 3 palabras con tiempo proporcional a las
  letras: el subtítulo karaoke que se usa sobre narración.
- `pop` (default `true`): entra con un micro-rebote de 0.12 s.
- `dx` / `dy` corren la pieza en píxeles. `dy` negativo sirve para poner una línea chica
  (un precio) **encima** de otro texto, porque abajo está la zona de botones.

**Estilos:**

| `style` | Tamaño default | Cuándo usarlo |
|---|---|---|
| `clean` | 64 | Default. Sans blanca con sombra suave, sin contorno grueso. Subtítulos y hooks. |
| `serif` | 96 | Instrument Serif itálica con halo. Estética "chic", POV cinematográfico, cierres. |
| `yellow` | 96 | Amarillo grueso con sombra. Palabra clave: un lugar, un precio, un número. |
| `box` | 58 | Caja redondeada tipo "texto clásico" de TikTok. `color` cambia el fondo y la tinta se elige sola por luminancia. Es el único que envuelve bien textos largos. |
| `pin` | 46 | Etiqueta de lugar con pin rojo ("Día 4 · Pekín"). **No envuelve**: una sola línea corta. |
| `bold` | 74 | Sans con contorno negro grueso. Legible sobre cualquier cosa, pero se lee a editor de hace años: evítalo. |

**Posiciones** (`pos`):

| `pos` | Dónde cae |
|---|---|
| `top` | Arriba, dentro de la zona segura. Hook fijo. |
| `topleft` | Arriba a la izquierda, pegado al margen. Para `pin`. |
| `upper` | ~30 % de altura. **La salida cuando el texto tapa una cara.** |
| `center` | Centro de pantalla, un poco arriba. |
| `low` | Abajo, arriba de la zona de botones. Default. |
| `lowleft` / `lowright` | Abajo a la izquierda/derecha. Sellos y tags de esquina. |

### Zona segura 9:16

El lienzo es 1080x1920, pero la interfaz de TikTok come los bordes:

```
top    150 px   buscador y avisos
bottom 480 px   nombre de usuario, descripción, barra de sonido
right  180 px   columna de like / comentar / compartir
left    60 px   margen de respiro
```

Los textos centrados usan un **margen simétrico de 150 px** a cada lado y se centran en
`W/2`, no en la zona segura: centrar en la zona segura (60 izquierda contra 180 derecha)
deja todo visiblemente cargado a la izquierda. El ancho útil para envolver es
**780 px**: a `size` 56-58 caben unos 22 caracteres por línea; a 62-72, menos.

---

## Looks de color y grano

| `look` | Qué hace | Cuándo |
|---|---|---|
| `film` | Negros levantados, luces cálidas, sombras verde-azul, saturación 0.92, viñeta 0.28. | Viaje, nostalgia, cuerpo de video. |
| `teal` | Teal & orange, saturación 1.05, viñeta 0.30. | Acción, noche, ciudad. |
| `clean` | Sin corrección de curvas, viñeta 0.12. | Blancos, templos claros, comida, nieve. |

`film` **apaga los blancos**: un templo blanco o una pared clara salen grises. Si el hook
depende de ese blanco, usa `clean` en todo el video — y si varias personas arman variantes
del mismo concepto, compara el mismo cuadro entre variantes, no solo dentro de cada una.

**Grano.** `grain` se aplica fino, **a resolución completa y solo en luminancia**, con menos
intensidad en negros y blancos. Generarlo a media resolución y escalarlo se ve sucio, como
ruido de compresión. Rango útil: **0.004 - 0.008**; el motor topa en 0.012 y `0.03` es
inmirable.

---

## Audio

El motor **no arrastra el audio de los clips**. Los segmentos aportan solo imagen: todo lo
que se oye sale de las pistas de `audio` del spec.

```jsonc
"audio": [
  {"src": "narracion.wav", "at": 0.0,  "gain": 1.0},
  {"src": "ambiente.mp3",  "at": 2.5,  "gain": 0.25, "dur": 8.0, "offset": 12.0},
  {"src": "sfx/whoosh.mp3","at": 4.2,  "gain": 0.6}
]
```

| Clave | Qué hace |
|---|---|
| `src` | Cualquier formato que lea ffmpeg. |
| `at` | Segundo del video en el que entra. |
| `gain` | Multiplicador lineal (`1.0` = tal cual). |
| `dur` | Recorta la pista a N segundos, con 0.3 s de entrada y 0.5 s de salida. |
| `offset` | Segundo desde el que se toma la fuente. |

**Cómo se mezcla, y por qué en dos pasos.** Primero se mezclan todas las pistas a un WAV
(`amix normalize=0` → `apad whole_dur` → `atrim` al largo exacto) y después ese WAV se pega
al video con `-c:v copy`. **Una sola llamada de ffmpeg con muchas pistas más el video se
queda colgada sin error** (pasó con 19 pistas). No lo juntes en un solo comando.

Detalles que ya costaron caros:

- Al final de la cadena va siempre un **limitador** (`alimiter=limit=0.89`). La suma de la
  canción del preview con el audio real llegó a **+5.8 dBTP** sin que nada avisara.
- `aresample=async=1:first_pts=0` es obligatorio: si **ninguna** pista arranca en `at: 0`,
  la mezcla sale con pts inicial igual al primer `adelay` y el `atrim` recorta el audio.
  Un video de 34.3 s se quedó con 9.6 s de audio por eso.
- `"audio_fade_out": 0` en los videos pensados para loop; el default de 1.2 s rompe la costura.
- Para sonido diegético (voces, agua, ambiente de una fiesta) arma **un solo WAV continuo**
  aparte: cada pedazo con `atrim` + `asetpts` + fades de 50 ms + `adelay`, todo a
  `amix normalize=0` y al final `loudnorm I=-16` y limitador. Mételo como una única pista en
  `at: 0`. Las fotos no traen audio: cúbrelas con el ambiente del clip de esa misma escena,
  o entran mudas.
- Normaliza **pieza por pieza** a su propio objetivo LUFS (`loudnorm print_format=json` para
  medir, `volume=NdB` para aplicar) y deja la mezcla final en -14 LUFS. Así puedes diseñar
  una caída de volumen a propósito sin que el video brinque por accidente. Las tomas casi
  mudas necesitan `dynaudnorm=f=180:g=21:p=0.62` antes de subirlas, o la pista suena rota.
- Verifica huecos con `silencedetect=n=-45dB:d=0.25` y que el audio dure exactamente lo que
  el video con `ffprobe -select_streams a:0 -show_entries stream=duration`.

### Música

```jsonc
"preview_audio": {"src": "cancion.m4a", "offset": 0.0, "gain": 1.0}
```

`preview_audio` genera **`video-preview.mp4`** aparte. La versión limpia **nunca** lleva la
canción: en la app se le pone el sonido oficial, que además cuenta para la tendencia.

Para cortar al beat, mide el BPM del audio (por ejemplo con `librosa.beat.beat_track`) y usa
`bpm` + `beats` en los segmentos. **Los previews de las tiendas de música duran 30 s**: en un
video de 34 s la música simplemente se acaba y los últimos segundos quedan mudos sin que el
render avise. Para más de ~29 s arma primero una cama con loop (`acrossfade=d=1.5` entre el
preview y una copia suya desplazada, `atrim` al largo que necesites, `loudnorm I=-22`) y
pásala con `gain 1.0`; bajar el `gain` sobre el preview crudo la vuelve inaudible.

---

## Mapa animado de ruta

```jsonc
{"map": {"bbox": [lon0, lon1, lat0, lat1],
         "stops": [[lon, lat, "Ciudad"], [lon, lat, "Ciudad"]],
         "geojson": "ruta/opcional.geojson"},
 "dur": 5}
```

Mapa estilo papel en proyección Mercator con **la misma escala en x y en y** (con escalas
distintas el mundo sale estirado). La ruta se dibuja punteada mientras un avión la recorre;
la cámara arranca mostrando el trayecto completo y termina acercándose a la última parada.

Dos cosas resueltas que conviene no romper:

- **Extensión automática de latitud.** En 9:16 el mapa tiene que ser al menos tan alto como
  `ancho × 16/9`. Si el `bbox` es más chaparro, el motor extiende la latitud de forma
  simétrica **en espacio de Mercator** (no en grados) para que la ruta completa quepa desde
  el primer cuadro.
- **Etiquetas que no se encimen.** Cada etiqueta prueba 8 posiciones alrededor de su punto, a
  tres radios distintos, y se queda con la primera libre; si termina lejos del punto, se
  dibuja una línea guía. Las que caerían fuera de la zona segura se descartan, y las paradas
  fuera de cuadro no llevan etiqueta. Aun así, con paradas a menos de ~50 km entre sí, revisa
  el cuadro: pueden quedar apiladas. Si estorban, quita una parada o parte la ruta en dos
  segmentos de mapa.

Los mapas siempre se renderizan con look `clean` y sin grano, aunque el video use otro look.

---

## Verificar antes de entregar

Ningún render se entrega sin mirarlo. Comandos que atrapan casi todo:

```bash
# tira de cuadros: lo primero, siempre
ffmpeg -v error -i video.mp4 -vf "fps=2,scale=216:384,tile=12x6" tira.png

# cuadros negros, huecos de audio y picos
ffmpeg -v error -i video.mp4 -vf blackdetect=d=0.08:pix_th=0.12 -f null -
ffmpeg -v error -i video.mp4 -af silencedetect=n=-45dB:d=0.25 -f null -
ffmpeg -v error -i video.mp4 -af loudnorm=print_format=summary -f null -   # pico bajo -0.5 dBTP

# el audio tiene que durar exactamente lo que el video, y haber UNA sola pista
ffprobe -v error -show_entries stream=index,codec_type,duration -of compact video.mp4
```

En la tira revisa: que el texto se lea, que no tape ninguna cara, que ningún recorte corte
cabezas, que los datos en pantalla sean ciertos y que los textos largos no suelten palabras
huérfanas.

---

## Errores ya cometidos, no los repitas

1. **Centrar el texto en la zona segura en vez de en la pantalla.** La zona segura es
   asimétrica (60 px a la izquierda, 180 a la derecha por la columna de botones). Centrar en
   ella deja todos los textos visiblemente cargados a la izquierda. Se centra en `W/2` con
   margen simétrico de 150 px.
2. **Tapar la cara del sujeto con el texto.** `pos: "low"` cae a ~0.69 de altura, que en un
   primer plano vertical es justo la boca. Cambiar el `focus` no lo arregla si la foto original
   es apaisada, porque el recorte ya toma toda la altura: sube el texto a `pos: "upper"` y
   busca pared vacía. Revísalo en la tira, no de memoria.
3. **Grano a media resolución.** Se ve sucio, como ruido de compresión. Fino, a resolución
   completa, solo en luminancia y `grain ≤ 0.008`.
4. **Los previews de música de 30 s en videos más largos.** La canción se acaba sola y el
   final queda mudo sin ningún aviso. Arma la cama con loop antes de renderizar.
5. **Música con copyright incrustada en la versión final.** Solo en el `-preview`. La limpia
   se sube y el sonido oficial se pone en la app.
6. **No verificar con tiras de cuadros.** Todo lo de esta lista se detecta en una tira de
   `fps=2`. Sin tira no hay entrega.
7. **Confiar en el `\n` a mano.** El motor envuelve por ancho **dentro de cada renglón**, así
   que un `\n` no garantiza el corte: si el renglón no cabe, se parte igual y suelta una
   palabra huérfana, que en un cuadro congelado se ve fatal. Y cada vez que bajes el `size`,
   vuelve a mirar el cuadro: un texto que partía bien a 62 px suelta la última palabra a 54.
8. **`fit: "blur"` para fotos apaisadas.** Las deja chicas, en letterbox, entre dos bandas
   borrosas; dos seguidas se leen como la misma toma repetida. Usa `focus` sobre el sujeto y
   que la foto llene el cuadro. `blur` solo para material que de verdad no se puede recortar.
9. **Sellos o tags de menos de ~0.8 s.** No se alcanzan a leer. Los tags de esquina entran
   **con el corte**, no a media toma.
10. **Poner en pantalla una fecha o un lugar sin verificarlo.** El nombre del archivo trae la
    hora del lugar donde se tomó y la base de datos de la biblioteca la del huso local: entre
    las dos se cuela un día entero. Verifica contra los metadatos, no contra el nombre.
11. **Suponer que el segundo del audio bueno es el segundo de la imagen buena.** El pico de
    audio (un grito, una risa) suele caer cuando la cámara apunta a otro lado. Separa el clip
    de imagen del de audio y **mira el cuadro** del `start` antes de fijarlo.
12. **`look: "film"` sobre blancos.** Deja grises los templos y las paredes claras. Si el hook
    depende del blanco, todo el video va en `clean`.
13. **Dejar el `crf` por default alto.** `crf 18` da ~11-19 Mbps: 35 s pesan 50-80 MB, más de
    lo que aguanta cualquier envío y mucho más de lo que la app conserva. `crf 22` deja esos
    35 s en ~27 MB sin diferencia visible; las copias para revisar, a 720p y `crf 24`.
14. **Dos reencuadres del mismo clip 360 con yaw parecido** se leen como un error de montaje:
    misma composición, mismo fondo. Sepáralos al menos 90° de yaw o cambia de sujeto.
15. **Borrar los pre-renders sin que el armador los regenere.** Si el spec apunta a un MP4
    temporal y lo limpias, el JSON queda irreproducible. Reconstruye siempre desde el script
    que arma el spec, nunca desde el spec suelto.
16. **Parchar a mano lo que el motor hace mal.** Si un paso corrige algo (normalizar el
    preview, poner subtítulos CJK encima), va dentro del script que renderiza, no en el README:
    a la siguiente reconstrucción el error vuelve sin avisar.

## Límites conocidos

- **No rota la imagen.** Para una micro-rotación de entrada, pre-renderiza el pedazo con
  ffmpeg a **1350x2400** (= 1080x1920 × `MARGEN` 1.25) y mételo como un clip normal.
- **No hace zoom animado dentro de ffmpeg por ti.** Si necesitas un encuadre que el material
  no tiene, pre-renderízalo con `zoompan` (no con `crop`: ffmpeg evalúa `w`/`h` una sola vez)
  y salida a 1350x2400 para que el motor no lo vuelva a escalar.
- **ffmpeg no abre HEIC.** Las fotos del iPhone las carga Pillow; si necesitas pasarlas por un
  filtro de ffmpeg, conviértelas a JPG antes.
- **CJK dentro del render depende de la fuente de repuesto.** Si no hay ninguna instalada,
  salen cuadritos: instálala y apúntala con `REEL_FORGE_FONT_CJK`, o pon los ideogramas como
  PNG encima del MP4 ya renderizado con `overlay=enable='between(t,a,b)'`, copiando el audio.
- **Los segmentos `r360` necesitan el motor 360 del plugin** (la skill `video-360`). Sin él, el motor lo dice y se detiene en vez de renderizar algo distinto.
