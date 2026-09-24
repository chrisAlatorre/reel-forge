---
name: voces
description: Narración y voz en off para videos verticales con TTS local y libre (Qwen3-TTS, VoxCPM, Piper), diseño de voces sintéticas por descripción, tratamiento de locutor y mezcla de la narración sobre un video ya renderizado. Úsala cuando pidan voz en off, narración, voz de TikTok, TTS, doblaje o ponerle voz a un video.
---

# Voces y narración

Dos caminos, y conviene entender por qué son dos:

| Camino | Qué es | Cuándo |
|---|---|---|
| **Local** (`scripts/voz.py`) | modelos con pesos abiertos, corren en la máquina, licencia clara | **el default, siempre** |
| **App** (`scripts/capcut_voz.py`) | maneja CapCut a clics para sacar una voz de su catálogo | solo si el concepto pide esa voz viral exacta |

El primero es reproducible, multiplataforma y de uso comercial claro. El segundo depende de una
interfaz que puede cambiar mañana.

Las dos rutas dejan **el mismo contrato**: `l0.wav, l1.wav…` + `duraciones.json` en una carpeta,
48 kHz mono, −16 LUFS. Cualquier cosa que consuma narración (el motor de edición, `narrar.py`)
funciona igual con las dos.

## Lo que está prohibido

No es una recomendación de estilo, es la línea que no se cruza:

- **No clonar la voz de una persona real.** Ni actores, ni creadores, ni famosos, ni un amigo, ni el
  propio usuario a partir de un audio que no sea suyo y actual. Los modelos de aquí clonan a partir
  de una referencia: esa referencia tiene que ser una voz **sintética diseñada** (ver abajo) o un
  audio del que el usuario tenga permiso explícito.
- **No describir a una persona real** al diseñar una voz ("como el narrador de tal documental",
  "voz de fulano"). Describe timbre, edad, acento y ritmo, nunca a alguien.
- **No usar APIs no oficiales que pidan la sesión del usuario.** El endpoint de TTS de TikTok con
  `session id` y los envoltorios tipo `edge-tts` entran aquí: son servicios internos, violan los
  términos, pueden tumbar la cuenta y se rompen sin aviso. Si hace falta un servicio de pago, que el
  usuario abra su cuenta y su API key.
- **No incrustar voces con licencia dudosa en algo con marca o presupuesto.** Para eso, un servicio
  comercial con licencia escrita.

Si el usuario insiste en clonar a alguien, explícale el problema una vez y ofrécele diseñar una voz
sintética con un timbre parecido. No lo hagas.

## Camino local

```bash
V=${CLAUDE_PLUGIN_ROOT}/skills/voces/scripts/voz.py

echo '["Primera frase.", "Segunda frase."]' > lineas.json
uv run $V lineas.json voces/ --motor qwen --voz narrador
```

Sale `voces/l0.wav`, `voces/l1.wav` y `voces/duraciones.json`.

### Motores

| Motor | Modelo | Licencia | Plataforma | Notas |
|---|---|---|---|---|
| `qwen` | Qwen3-TTS 12Hz 1.7B | Apache-2.0 | MLX = **Apple Silicon** | el mejor medido; ~3-5 s por línea |
| `voxcpm` | VoxCPM2 | Apache-2.0 | MLX = **Apple Silicon** | 48 kHz nativo; en voz femenina a veces cecea |
| `piper` | Piper | MIT | cualquiera | rápido, ligero, calidad menor; el camino fuera de Mac |

`qwen` y `voxcpm` corren en un entorno aparte con `mlx-audio`: el script se relanza solo con
`uv run --with mlx-audio`. La primera vez bajan ~4 GB de Hugging Face.

**Fuera de Apple Silicon**, usa `--motor piper` (voces de `huggingface.co/rhasspy/piper-voices`, MIT,
se guardan en `$REEL_FORGE_CACHE/voces/`) o corre Qwen3-TTS/VoxCPM con sus repos oficiales en
PyTorch. No prometas MLX en Linux ni en Windows.

Métricas medidas (UTMOSv2 / WER con whisper large-v3, español):

| Voz | UTMOS | WER |
|---|---|---|
| qwen, narrador | 3.64 | 0 % |
| qwen, narradora | 3.82 | 0 % |
| voxcpm, narrador | 3.69 | — |
| piper | 2.58 | — |

Descartados y por qué: Chatterbox (MIT, bueno pero habla rápido e inventa palabras en la voz
femenina), ZONOS2 (la voz cambia entre líneas), F5-TTS / Fish / OpenAudio / Voxtral / Higgs / OmniVoice
(pesos **no comerciales**). `say` de macOS y las voces del sistema suenan a robot de 2010: no.

### Diseñar una voz por descripción

Qwen3-TTS VoiceDesign genera una voz **que no existe** a partir de una descripción en texto. Esa voz
se guarda como referencia (`.wav` + `.json` con el texto leído, la descripción, la semilla y la
licencia) y luego los motores la clonan línea por línea.

```bash
uv run $V --crear-voz narrador \
  --descripcion "Hablante nativo de español de México, hombre de unos 40 años, voz grave y cálida de barítono, ritmo pausado, tono de documental, sin acento extranjero" \
  --semilla 11
```

Lo que de verdad importa al escribir la descripción:

- **Escríbela en el idioma de la voz.** Una descripción en inglés para una voz en español sale con
  acento gringo: en las pruebas, hasta un 20 % de fonemas ingleses en voces femeninas.
- Di **de dónde es** el hablante ("nativo de español de México"), no solo el idioma.
- Describe **timbre, edad, registro y ritmo**. Nunca a una persona concreta.
- **Prueba 3 o 4 semillas** (`--semilla`) y quédate con la que suene mejor. La misma descripción con
  otra semilla da otra voz.
- Guarda la referencia: mientras el `.wav` y su `.json` estén ahí, todos los videos del proyecto
  suenan a la misma persona.

### Escribir para que se oiga bien

- **Nada de `--lento`.** Estirar el audio mete artefactos (en una prueba, PESQ estimado de 4.3 a 2.3
  con un factor de 1.08). Para pausar, **puntúa**: comas, puntos y frases cortas.
- **Números con letra.** "veintitrés grados", no "23°".
- Una idea por línea. Las líneas son las unidades que después se colocan en la línea de tiempo.
- Siglas y nombres raros: escríbelos como se pronuncian.

## Tratamiento de locutor

La cadena que se aplica a cada línea (preset `limpio`, el default de los motores nuevos):

1. **Recorte de silencios** en las dos orillas (`silenceremove` con `areverse`). El espacio entre
   líneas lo pone el montaje, no el WAV.
2. **Highpass a 60 Hz**: quita retumbo sin adelgazar la voz.
3. **loudnorm de dos pasadas, lineal, a −16 LUFS / −1.5 dBTP**, 48 kHz mono. Dos pasadas: primero se
   mide con `print_format=json`, después se aplica con los valores medidos. Una sola pasada bombea.

Y lo que **no** lleva:

> **Sin reverb. Nunca.** El preset histórico traía un `aecho=0.8:0.5:35:0.12` para "darle cuerpo" y el
> resultado fue exactamente el contrario: la voz sonaba **lejos del micrófono, como micrófono barato**.
> Una voz en off de TikTok tiene que sonar pegada al oído. Nada de sala, nada de eco, nada de
> "ambiencia". Si suena seca, está bien.

La compresión y el EQ, con moderación: en las pruebas de imitación de timbre, subir brillo y meter
compresión **bajaron** el parecido y no mejoraron la inteligibilidad. El preset `locutor`
(highpass 70 + realce de 160 Hz y 3.5 kHz + compresor 3:1 + eco) sigue en el script solo por
compatibilidad histórica. **Usa `limpio`.**

Presets disponibles con `--fx`: `limpio` (default y recomendado), `tiktok` (seco, para imitar el
timbre plano del TTS de las apps), `locutor` (histórico, con eco: no lo uses).

## Camino CapCut (solo macOS)

**Qué es.** Las voces del catálogo de CapCut son de ByteDance y solo existen dentro de la app: no hay
API pública. `scripts/capcut_voz.py` automatiza la aplicación de escritorio — pega cada línea en un
clip de texto, elige la voz y pulsa "Generar contenido de voz" — y recoge el WAV.

**Por qué funciona sin exportar nada.** CapCut escribe el audio del texto a voz directo en la carpeta
del proyecto, antes de cualquier exportación:

```
~/Movies/CapCut/User Data/Projects/com.lveditor.draft/<MM>/<DD>/textReading/<hash>.wav
```

(hay una copia en `.../User Data/Cache/ttsTemp/`). Es un MP3 de 128 kbps dentro de un archivo `.wav`,
44.1 kHz mono. Basta copiarlo y pasarlo por ffmpeg: nada de exportar el video, nada de marca de agua.
La carpeta se puede mover con `$CAPCUT_DRAFTS`.

### Cómo se usa

```bash
C=${CLAUDE_PLUGIN_ROOT}/skills/voces/scripts/capcut_voz.py

uv run $C --preparar                  # imprime los pasos manuales y coloca la ventana
uv run $C lineas.json voces/ --velocidad 1.4 --voz "Nombre de la voz"   # --voz solo etiqueta los avisos
uv run $C --calibrar                  # captura con las coordenadas actuales
```

Preparación manual, **una vez por tanda** (~1 minuto):

1. **Proyecto NUEVO** (Archivo → Nuevo proyecto). No hace falta meter ningún video.
2. Texto → Agregar texto → botón `+` de "Texto predeterminado".
3. Panel derecho, pestaña **Texto**: pega la primera frase con **Cmd+V**.
4. Pestaña **Texto a voz** → chip de categoría → clic en la voz → **Generar contenido de voz**. Tiene
   que aparecer una pista de audio con el nombre de la voz.
5. Arrastra la separación entre el reproductor y la línea de tiempo hasta que el botón "Generar
   contenido de voz" quede donde dice `P['generar']` (compruébalo con `--calibrar`).

Después, el script hace el ciclo completo por línea: sube la línea de tiempo → selecciona el clip de
texto → pega → pestaña Texto a voz → chip → clic en la voz → Generar → espera el WAV → lo convierte.
~25 s por línea. **Reanuda solo**: si `lN.wav` ya existe se lo salta.

Ojo: **la voz la elige la coordenada del clic**, no `--voz`. Ese parámetro solo sirve para que los
avisos y el diagnóstico digan el nombre correcto. Para cambiar de voz, recalibra `P['voz']` (y
`P['chip_narracion']` si está en otra categoría) con `--calibrar`.

La velocidad se aplica **fuera** de CapCut con `atempo` (mantiene el tono). `1.4` es el ritmo del
trend de narración documental.

### Reglas que cuestan sangre

- **Un proyecto nuevo por tanda.** Un proyecto con ~110 regeneraciones encima deja de escribir WAVs:
  sale el diálogo "Generando la voz…", se cierra y no aparece archivo, **sin ningún mensaje de error**.
  Las voces gratuitas seguían funcionando en ese mismo proyecto, así que parece un tope por proyecto
  de las voces premium. Un proyecto nuevo generó a la primera.
- **Nunca escribas con `osascript ... keystroke`**: CapCut se come los espacios y los acentos
  ("Cadaverano,unejemplar…"). Siempre `pbcopy` + Cmd+V.
- **Todo va por clic a coordenada.** No hay API ni árbol de accesibilidad útil. El script fija la
  ventana en `(0, 33)` con tamaño `1728x999` por AppleScript antes de cada pasada. Con otra pantalla
  o versión, `--calibrar` deja una captura y las coordenadas del diccionario `P`.
- **Cuidado con el Dock:** un clic cerca del borde inferior saca otra app al frente.
- **El panel de voces se redibuja** (a veces una columna, a veces cuadrícula) y vuelve arriba al
  reentrar. Por eso el ciclo pulsa siempre el chip de categoría antes de buscar la voz: deja la lista
  en un sitio conocido.
- **El botón Generar se deshabilita** cuando el clip ya tiene voz; se reactiva al volver a hacer clic
  sobre la voz en el catálogo.
- **Cada generación añade una pista de audio nueva** (las versiones recientes quitaron la casilla
  "Actualizar la voz según el guion"). Por eso el script hace mucho scroll hacia arriba antes de cada
  clic: con 20 pistas, poco scroll deja el clic en una pista de audio y el texto se pega en el sitio
  equivocado.

### Cuando no sale audio

El script lee `draft_info.json` del proyecto y distingue los dos fallos sin adivinar:

- **el texto NO llegó al clip** → los clics caen mal: `--calibrar` y ajusta `P`.
- **el texto sí llegó pero ninguna pista usa esa voz** → el clic en la cuadrícula cayó fuera.
- **el texto llegó y la voz es la correcta, pero no hay WAV** → el proyecto está quemado: crea uno
  nuevo. Para confirmarlo, aplica a mano una voz gratuita: si esa sí genera, el tope es de las
  premium.

Plan B si la interfaz cambió de sitio los botones: pega **todo el guion de una** (una línea por
párrafo), genera una sola vez y corta por silencios.

```bash
uv run $C lineas.json voces/ --cortar ".../textReading/<el wav>.wav" --umbral -38dB --minimo 0.45
```

Imprime cuántos trozos detectó para compararlos con el número de líneas.

### Advertencia que hay que decirle al usuario

Este camino **depende de la interfaz de CapCut y se va a romper**. Ya pasó una vez a mitad de una
tanda, en silencio. Depende también de que esa voz siga en el catálogo de su país. Si se rompe y no
hay tiempo de recalibrar, entrega el video **sin voz** más un `guion-voz.txt` con los segundos, y que
el usuario la ponga en la app. Para todo lo demás: `voz.py --motor qwen`.

## Pegar la narración a un video ya renderizado

`scripts/narrar.py` toma un guion con tiempos y un MP4 terminado y mezcla la voz encima **sin
re-renderizar el video** (`-c:v copy`).

```bash
N=${CLAUDE_PLUGIN_ROOT}/skills/voces/scripts/narrar.py

uv run $N guion.txt video.mp4 video-narrado.mp4                  # voz local (qwen)
uv run $N guion.txt video.mp4 video-narrado.mp4 --motor capcut   # voz de la app (macOS)
uv run $N guion.txt video.mp4 video-narrado.mp4 --gen voces/     # WAVs ya generados
uv run $N guion.txt --solo-parse                                 # revisa el parseo antes de generar
```

Formato del guion: una línea por intervención, empezando por el segundo en que entra. El parser
aguanta las variantes que salen de un guion escrito a mano o por otro agente:

```
0.5   Aquí empieza todo.
[3.2] Y aquí sigue.
7.0 s | 2.4 s | La tercera línea.
~9.8 s  La cuarta.
```

Reglas del parser:

- **Se corta al llegar a un encabezado `Notas` o `Opcional`.** Lo de abajo son comentarios, no
  líneas. Sin esto, un comentario como "…de 15.8 a 16.9 s, si la metes antes…" entra como narración.
  Un bloque marcado "opcional" suele solaparse con una línea obligatoria y taparla entera: si de
  verdad la quieres, muévela a la tabla con su segundo.
- Se ignoran separadores, encabezados markdown y las líneas sin texto real.
- Se limpian las columnas de duración sobrantes.

**Corre siempre `--solo-parse` primero** y mira la lista que imprime. Es un segundo y evita generar
veinte líneas de basura.

Detalles de la mezcla:

- El audio original del video **se conserva**; la voz se suma encima con `adelay` + `amix`. Si quieres
  que la música baje bajo la voz, hazlo al renderizar el video, no aquí.
- **Si el video viene sin pista de audio, la mezcla sigue durando lo que el video.** Con
  `amix duration=first` la primera entrada sería la primera línea de voz y la mezcla se cortaba al
  acabarla (a los 3 s de un video de 35 s, sin que nada avisara). Se usa `duration=longest` y un
  `atrim` a la duración exacta del video.
- Al final, `alimiter=limit=0.95`: la voz encima del audio original se pasa de pico con facilidad.
- `--volumen` ajusta la ganancia de la voz. `--gen` reusa una carpeta ya generada; si falta
  `duraciones.json`, la considera incompleta y la vuelve a generar (reanudando).

## Errores frecuentes

1. Meter reverb "para darle cuerpo": suena lejos del micro.
2. Estirar el audio con `--lento` en vez de puntuar el guion.
3. Escribir la descripción de la voz en inglés y sacar una voz en español con acento gringo.
4. Números en dígitos: el TTS los lee mal o se los salta.
5. Reusar el mismo proyecto de CapCut toda la semana hasta que deja de generar, en silencio.
6. Pasar el guion completo a `narrar.py` con las notas al final y narrarlas.
7. Dar por hecho que MLX corre en Linux.
