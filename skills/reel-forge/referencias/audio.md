# Audio: música, sonido real y narración

El audio es la mitad del video y es donde más fallas pasan desapercibidas: un hueco, un pico de
volumen o una pista duplicada no hacen fallar nada, solo salen mal.

## Regla base

**El motor no arrastra el audio de los clips.** Los segmentos aportan solo imagen. Todo el sonido
—diegético, música, voz— se arma aparte y entra como pistas de `audio` en el spec.

## Sonido diegético (el audio real de las tomas)

Receta probada, en un solo script que genera un WAV continuo y se mete como una sola pista en `at: 0`:

1. Una lista de piezas: `(t_salida, fuente, inicio, duracion, ganancia)`.
2. Cada pieza: `atrim` + `asetpts` + fades de 50 ms en los extremos + `adelay` al segundo que le toca.
3. Todo a `amix` con `normalize=0`.
4. Al final `loudnorm I=-16` y un limitador.

Detalles que importan:

- **Las fotos no traen audio.** Cúbrelas con el ambiente del clip de esa misma escena, o entran mudas y
  se oye el bache. Truco limpio: los cortes contiguos que comparten fuente se agrupan en **una sola
  pieza que sigue corriendo**, y así las fotos heredan el ambiente del clip vecino.
- **Volumen por corte, no automático.** Normaliza cada pieza a su propio objetivo en LUFS (mide con
  `loudnorm print_format=json`, aplica con `volume=NdB`) y deja la mezcla final en -14 LUFS. Así puedes
  diseñar una caída (una escena a -10 y la siguiente a -26) a propósito.
- Tomas casi mudas (un pasillo, un animal respirando): `dynaudnorm=f=180:g=21:p=0.62` antes de subirlas,
  si no la pista suena rota.
- **J-cut de verdad:** para que el audio entre antes que la imagen sin perder el sincronismo de labios,
  adelanta también el punto de entrada de la fuente, no solo corras la pista.

Verificación obligatoria:

```bash
ffmpeg -i salida.mp4 -af "silencedetect=n=-45dB:d=0.25" -f null -    # huecos
ffmpeg -i salida.mp4 -af "loudnorm=print_format=summary" -f null -   # pico bajo -0.5 dBTP
ffprobe -v error -select_streams a -show_entries stream=index,codec_type -of csv salida.mp4  # una sola pista
```

## Encontrar el segundo exacto

- Los tiempos que anota el catálogo se corren varios segundos. Para clavar una frase o un golpe,
  **transcribe** el audio con marcas por palabra (un modelo de transcripción local basta) o saca un
  perfil de volumen por 0.2 s en la banda de voz (300-3000 Hz).
- Para gritos, fiesta o multitud, la transcripción falla: usa los **onsets** en esa misma banda
  (fuerza de onset + selección de picos) y **valida con una tira a 4 fps** quién sale en cuadro.
- **El segundo del audio bueno no es el segundo de la imagen buena.** En un clip real los tres gritos
  estaban en 47.6 / 49.1 / 50.5 s, pero ahí la cámara apuntaba a una pared: la imagen buena estaba en
  22.4 s. Separa la fuente de imagen de la de audio y **mira el cuadro** del punto de entrada.

## Música

- **No incrustes música con copyright en lo que se va a subir.** Dos archivos: `x.mp4` limpio y
  `x-preview.mp4` con la canción, solo para que el usuario la oiga. El sonido oficial se agrega en la app.
- Preview público de 30 s para medir BPM y para el preview. Ver `tendencias.md`.
- **Videos de más de ~29 s necesitan una cama con loop**, o la música se acaba y el final queda mudo sin
  que nada avise. `acrossfade=d=1.5` entre el preview y una copia desplazada, `atrim` al largo exacto,
  `loudnorm I=-22` (cama, bajo el audio real que va a -16) y ganancia 1.0 sobre la cama normalizada —
  con ganancia 0.30 sobre el preview crudo la música es inaudible.
- La cama se hace **una vez, en `comun/`**.
- En loops, pon la salida de audio en 0: el fundido de salida por defecto rompe el loop.

## Efectos de sonido

Ambientes y golpes ligeros: ambiente a 0.2-0.3 según la escena, obturador en fotos y congelados, pop
suave al entrar un texto, un riser antes de una revelación y un remate seco solo para el chiste.
Usa SFX con licencia libre y **guarda la licencia** junto a los archivos. Nunca el mismo golpe en cada
corte: se vuelve ruido.

## Narración

Cuándo: en el formato documental/storytime y en las listas. En un photo dump estorba.

**El TTS genérico y con eco suena a "micrófono chafa y lejos del micro" y fue rechazado en producción.**
Usa una voz neuronal moderna, seca, sin eco añadido:

- `scripts/voz.py` genera `l0.wav, l1.wav… + duraciones.json` (48 kHz, silencios recortados, filtro
  pasa-altos suave, normalización de dos pasadas a -16 LUFS). Ese es **el contrato**: cualquier otra
  fuente de voz tiene que entregar lo mismo para que el motor la consuma sin cambios.
- Usa un modelo con licencia de uso comercial clara y voces **sintéticas diseñadas**, no clonadas.
- **Nunca clones la voz de una persona real** (actores, famosos, la voz de la plataforma). Ni la
  describas para que el modelo la imite.
- Escribe la descripción de una voz nueva **en el idioma objetivo**: pedirla en inglés mete acento
  extranjero. Prueba 3-4 semillas y quédate con la mejor.
- No estires la voz para hacerla más lenta: mete artefactos. Para pausas, usa comas y puntos en el
  guion. Los números, con letra.
- Si el usuario quiere calidad de servicio comercial, hace falta su cuenta y su llave: pídeselo, no lo
  des de alta tú.

### Voz de narrador viral de una app de edición — **solo macOS, y frágil**

Algunas apps de escritorio escriben el WAV de su "texto a voz" **directo en la carpeta del proyecto**,
antes de exportar nada. Si el concepto pide esa voz exacta y el plugin trae el script de
automatización correspondiente, maneja la app a clics y deja el mismo contrato
(`l0.wav… + duraciones.json`). Lo que hay que saber:

- **Es automatización por coordenadas de pantalla.** No hay API. Cualquier actualización de la app
  mueve los botones y hay que recalibrar. Trátalo como un camino opcional, nunca como dependencia.
- **Un proyecto muy usado deja de generar**, en silencio: sale el diálogo, se cierra y no aparece
  archivo. Una tanda larga, un proyecto nuevo. Si empieza a fallar, crea otro y sigue.
- Nunca escribas texto simulando teclas: se comen espacios y acentos. Copia al portapapeles y pega.
- La velocidad del trend se aplica **fuera** de la app, con `atempo` (mantiene el tono).
- **Camino alternativo, y el que debes preferir:** genera con el TTS local del plugin. Si ni eso se
  puede, entrega el video **sin voz** más un `guion-voz.txt` con el segundo de entrada de cada línea,
  para que el usuario la ponga en la app con dos toques.

### Pegar la narración a un video ya renderizado

`scripts/narrar.py` lee un `guion-voz.txt` (`<segundo>  <texto>` por línea), genera o toma los WAV y
los mezcla sobre el MP4:

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/voces/scripts/narrar.py" guion-voz.txt video.mp4 video-narrado.mp4
```

Trampa real: en el `amix` **no uses `duration=first`**. Si el video viene sin pista de audio, la primera
entrada es la primera línea de voz y la mezcla se corta a los 3 s. Toma la más larga y recórtala al
largo del video.
