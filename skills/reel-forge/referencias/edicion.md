# Edición: el motor, los efectos y lo que ya costó caro

Motor: `skills/motor-video/scripts/render.py`. Lee un spec JSON y renderiza un vertical 1080x1920. Necesita `ffmpeg` en
el PATH. Funciona en macOS, Linux y Windows.

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/motor-video/scripts/render.py" spec.json
```

**Un solo motor: el del plugin.** Si un proyecto guardó su propia copia del script, compárala antes de
renderizar: el mismo spec con dos versiones distintas del motor da resultados diferentes y ese bug
tarda horas en encontrarse.

## Spec

```json
{
  "out": "~/Videos/reel-forge/proyecto/entregas/v1/concepto/concepto-A.mp4",
  "crf": 22,
  "look": "film|teal|clean",
  "grain": 0.008,
  "bpm": 123.0, "beat0": 0.0,
  "fade_out": 0.4,
  "audio_fade_out": 1.2,
  "preview_audio": {"src": "comun/cancion.m4a", "offset": 0.0, "gain": 1.0},
  "audio": [{"src": "comun/audio_real.wav", "at": 0.0, "gain": 1.0}],
  "segments": [
    {"src": "comun/f01.jpg", "beats": 2, "focus": [0.5, 0.4], "kb": 0.06, "punch": 0.10},
    {"src": "comun/c03.mp4", "dur": 2.4, "start": 3.0, "speed": 0.5, "flash": true}
  ],
  "captions": [
    {"t0": 0.0, "t1": 2.0, "text": "nadie te dice esto", "style": "clean", "pos": "upper"}
  ]
}
```

- `focus`: el punto (0-1) que queda al centro al recortar a 9:16.
- `kb`: zoom lento durante el segmento. `punch`: zoom de golpe que se asienta en ~0.2 s.
- `speed 0.5` sobre material de 60 fps da cámara lenta real, sin interpolar.
- `beats` en vez de `dur` cuando el spec trae `bpm`.
- El motor trabaja internamente con un margen de 1.25 (1350x2400) para poder hacer zoom sin perder
  nitidez. Cualquier pedazo que pre-renderices con ffmpeg **entrégalo ya a 1350x2400**, si no se
  re-escala al entrar.

### `crf`

El default histórico (`crf 18`) daba ~11 Mbps: 35 s pesaban 50-80 MB, mucho más de lo que sobrevive a
la subida y demasiado para mandarlo por chat. **Usa `"crf": 22`** en las entregas de 1080p (35 s ≈ 27 MB,
sin diferencia visible). Las copias ligeras van a 720p y crf 24 (4-11 MB).

### `grain`

Un grano de 0.03 a media resolución "se nota muchísimo". El grano va fino, a resolución completa y solo
en luminancia: **`grain` ≤ 0.008**. El motor lo tope en 0.012.

## Encuadre a 9:16

- **No uses fondo borroso como default.** Una foto horizontal metida en letterbox entre dos bandas
  borrosas queda chica, y dos así seguidas se leen como la misma toma repetida. Usa `focus` con el
  punto del sujeto y que llene el cuadro. El fondo borroso es solo para lo que de verdad no se puede
  recortar.
- Revisa que el recorte no corte cabezas ni deje a alguien pegado al borde.

## Textos

- **Zona segura 9:16:** 150 px arriba, **480 px abajo** (ahí viven los botones y la descripción de la
  app) y 180 px a la derecha. Un chip "abajo del todo" lo tapa la interfaz.
- Centrados de verdad: al centro de la pantalla, con margen simétrico.
- Estilos: `clean` (minimalismo, el default para subtítulos), `serif` (estética "chic"), `box` (el
  rótulo clásico con fondo), `bold` (contorno grueso — evítalo, se lee viejo).
- **Texto sobre una cara en primer plano: súbelo.** La posición baja cae a ~0.69 de altura, que en un
  vertical es justo la boca. Cambiar el `focus` no lo arregla si la foto original es apaisada.
- **El salto de línea a mano no basta.** El motor envuelve por ancho *dentro* de cada renglón, así que
  a tamaño 56-58 caben ~22 caracteres por línea y a 62-72 menos. Textos que ya traían `\n` seguían
  soltando una palabra huérfana. **Cada vez que cambies el tamaño, mira el cuadro renderizado y cuenta
  los renglones.** Una palabra sola en su renglón sobre un cuadro congelado se ve mal.
- **Alfabetos no latinos:** una fuente latina no trae ideogramas ni alfabetos índicos (salen cuadritos), y sin
  la librería de composición compleja las marcas de vocal salen como círculos punteados. El motor
  cambia de fuente cuando detecta esos alfabetos; si aun así falla, genera el texto como PNG con una
  fuente del sistema que sí los traiga y superponlo después del render, copiando el audio.

## Efectos

| Efecto | Cuándo | Cuidado |
|---|---|---|
| `punch` | casi cualquier corte al beat | 0.08-0.15; más se siente brusco |
| `flash` | solo en el momento fuerte | 2-3 cuadros, una vez por video |
| `stutter: 6` | caminar, POV | se cansa rápido |
| texto detrás del sujeto | 1-2 veces por video | **solo** si la cabeza o el torso tapa parte del texto: elige una toma donde salga grande y pon el texto a la altura de la cabeza |
| recorte con contorno + congelado | presentación de personaje | las fichas tienen que hablar **del sujeto recortado**, no de lo que hay al lado |
| mapa de ruta | recap de viaje | etiquetas sin encimarse (8 posiciones alrededor del punto, línea guía si queda lejos); el mapa se extiende en latitud para que en 9:16 se vea la ruta completa desde el inicio |

**Máximo 2 efectos por corte.** Evita: glitch RGB, fundidos largos, el mismo whoosh en cada corte,
subtítulos neón con emojis.

La segmentación de persona (para el texto detrás y el recorte) usa un modelo local. Si aparecen
recuadros negros, es un NaN en la máscara: vuelve a correr ese segmento o quítale el efecto.

## Lo que el motor NO hace

- **No rota.** Para una micro-rotación de entrada, pre-renderiza el pedazo con ffmpeg a 1350x2400 y
  mételo como clip normal. Recorta con margen (1440x2560 → 1350x2400) para que las esquinas vacías de
  la rotación no se vean nunca.
- **No hace zoom animado con `crop` de tamaño variable** — ffmpeg evalúa esas expresiones una sola vez.
  Usa `zoompan`, con salida a 1350x2400 y `fps=30`.
- **No abre HEIC en ffmpeg.** Pasa la foto por la librería de imagen a JPG antes de tocarla con ffmpeg.
- **No toma el audio de los clips.** Ver `audio.md`: el sonido diegético se arma aparte y entra como
  una sola pista.

## Retoque de personas: no está en el plugin

**reel-forge no retoca caras ni cuerpos.** No hay script de retoque y no se pretende que lo haya: lo
único que modifica la imagen es el `look` del render, que va parejo en toda la variante.

Si el usuario lo pide, dilo así y dale las dos salidas honestas:

1. **Elegir mejor**, que es lo que de verdad cambia el resultado: favoritas, ráfaga completa, recortes
   de cara para descartar gestos a medias. Ver `seleccion.md`.
2. **Retocar él la foto** en la app que ya use y meter el archivo retocado al catálogo como una toma
   más.

Y si algún día se agrega, que sea con estas reglas, que salieron de un "esto fue too much":

- Cara y ojeras sí; cuerpo, muy poco. Nada de brazos inflados.
- Silueta pareja, **nunca forma de reloj de arena**.
- **El fondo manda:** si hay postes, columnas, marcos, barandales u horizonte pegados a un brazo o al
  torso, el retoque va muy leve o no va. Una columna chueca delata todo.
- Desplazamiento máximo respecto al ancho de hombros: 2-5 % está bien, arriba de ~7 % ya se ve editado.
- Con varias personas, comprueba que el esqueleto detectado es el del sujeto antes de tocar nada.
- Los clips nunca. Para el sujeto en primer plano, foto; los clips, para acción y paisaje.

## Errores que ya pasaron (no los repitas)

- **Usar un tramo fuera de su ventana catalogada.** Salieron caras de desconocidas pegadas al lente.
- **Dos cortes casi iguales del mismo clip.** Dos reencuadres a 4° de diferencia se leyeron como error
  de montaje. Separa el ángulo o cambia de sujeto.
- **Fecha equivocada en pantalla** por confundir la hora del lugar con la de casa: 14 h de diferencia
  se comen un día entero. Manda la fecha de captura de los metadatos.
- **Un sello de 0.39 s.** Invisible. Mínimo ~0.8 s y entra con el corte.
- **Borrar los pre-renders sin que el armador los regenere.** Los specs apuntaban a temporales y el
  proyecto quedó irreproducible. Reconstruye siempre desde `build.py`, nunca desde el spec suelto.
- **Un script de apoyo sin permiso de ejecución** que nadie llamaba: el preview volvía a salir saturado
  en cada reconstrucción. Si un paso corrige algo, va dentro del script que renderiza, no en el README.
- **En zsh, `$VAR[a1]` dentro de un `filter_complex` se come la etiqueta** (zsh lo lee como índice de
  arreglo). El resultado: un mp4 con dos pistas de audio y ningún error. Usa siempre `${VAR}[a1]` y
  comprueba con `ffprobe -show_entries stream=index,codec_type`.
