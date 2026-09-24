# Formato del guion de narración

Un guion de voz de reel-forge es texto plano: **una línea por frase, empezando por el segundo en que
entra**. Nada más. Lo consume `skills/voces/scripts/narrar.py`, que genera un WAV por línea y los
pega sobre un video **ya renderizado**, sin volver a codificar la imagen.

El archivo puede llamarse `guion-voz.md` o `guion-voz.txt` y se entrega **junto al MP4**, aunque la
variante ya lleve la voz puesta: así el usuario puede regenerarla con otra voz o corregir una frase
sin rehacer el video.

## El formato

```
2.0   Llegamos de noche y no se veía nada.
6.4   A las seis de la mañana entendimos por qué todo el mundo viene aquí.
11.8  Tres días después seguíamos sin bajar de la montaña.
17.2  Guárdate la ruta: la parte dos ya está grabada.
```

- **Primera columna: el segundo** en que empieza a hablar, con punto decimal. Separador: dos espacios
  o un tabulador.
- **Segunda columna: la frase**, tal cual se va a oír. Sin comillas, sin acotaciones, sin nombre de
  personaje.
- Las líneas van **en orden** y **no se encabalgan**: cada frase tiene que caber antes de la siguiente.
- Todo lo que vaya después de una línea que diga `Notas:` son comentarios y **no se sintetiza**.

### Variantes que el parser también entiende

Salen solas cuando el guion lo escribe otro agente o se copia de una hoja. Sirven, pero para escribir
de cero usa la de arriba:

```
[3.2] Y aquí sigue.
7.0 s | 2.4 s | La tercera línea.
~11.4 s   Con tilde de aproximado y columna de duración.
```

### Qué ignora el parser

| Se ignora | Por qué |
|---|---|
| Líneas vacías, `---`, `===` y encabezados `#` | son estructura del markdown, no guion |
| Líneas que empiezan con `-`, `*` o `\|` | viñetas y tablas: **no pongas ahí las frases** |
| Todo lo que sigue a `Notas:` | comentarios para el humano |
| Todo lo que sigue a `Opcional` | una línea "opcional" suele solaparse con una obligatoria y taparla; si la quieres, dale su segundo y súbela a la tabla |
| Frases de menos de 8 caracteres o sin letras | restos de columnas de duración |
| Líneas que empiezan con `línea`, `dura`, `entra`, `video` | encabezados de tabla |

Antes de generar nada, comprueba cómo quedó el parseo:

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/voces/scripts/narrar.py" guion-voz.md --solo-parse
```

Imprime el JSON de `[{t, texto}]` que va a sintetizar. Si falta una frase o sobra un comentario, se ve
ahí y no después de esperar el render.

## Ejemplo completo

```markdown
# Guion — "Día uno" variante B (video de 22.9 s)

0.35   Nadie te cuenta cómo es el primer día.
6.20   A las seis de la mañana la plaza está vacía, y eso dura veinte minutos.
12.10  Para el mediodía ya no cabía un alma.
18.60  Guárdate la ruta: la parte dos ya está grabada.

Notas:
- 0.35 entra sobre el gancho, antes del primer corte.
- 6.20 cae en el segmento del mapa, que dura 5 s: cabe una frase larga.
- La de 12.10 tiene que terminar antes de 15.2, cuando entra el texto en amarillo.
```

## Cómo lo consume `narrar.py`

```bash
# Voz local (default: Qwen3-TTS en MLX, Apple Silicon)
uv run "$CLAUDE_PLUGIN_ROOT/skills/voces/scripts/narrar.py" \
    guion-voz.md dia-uno-B.mp4 dia-uno-B-narrado.mp4

# Con WAVs ya generados (no vuelve a sintetizar)
uv run .../narrar.py guion-voz.md dia-uno-B.mp4 dia-uno-B-narrado.mp4 --gen voces-dia-uno-B/

# Voz de la app de escritorio — SOLO macOS, maneja CapCut a clics
uv run .../narrar.py guion-voz.md dia-uno-B.mp4 dia-uno-B-narrado.mp4 --motor capcut
```

Lo que hace, en orden:

1. **Parsea** el guion (las reglas de arriba).
2. **Sintetiza** cada frase, si no existen ya los WAVs. Escribe `lineas.json` y llama a `voz.py`
   (local) o a `capcut_voz.py` (macOS). Ambos dejan el mismo contrato en la carpeta:
   **`l0.wav`, `l1.wav`… más `duraciones.json`**, a 48 kHz, con los silencios recortados y
   normalizados a −16 LUFS.
3. **Mezcla** cada WAV sobre el video en el segundo de su línea, conserva el audio original del MP4
   y copia el stream de video sin recodificar.

Ese mismo contrato (`lN.wav` + `duraciones.json`) es el que consume el motor de edición: si prefieres
que la voz entre en el render en vez de pegarla después, pon cada WAV como una pista de `audio` del
spec con su `at` igual al segundo de su línea (ver `ejemplos/spec-ejemplo.json`).

- **Si falta `duraciones.json`, la carpeta está incompleta**: el sintetizador se cortó a media tanda.
  Vuelve a correrlo; los `lN.wav` que ya existen no se regeneran.
- **`--volumen`** sube o baja la voz sobre el audio del video. Si quieres que la música baje debajo de
  la voz, eso se hace al renderizar el video, no aquí.

## Escribir el guion

- **Los segundos salen del spec, no del oído.** Suma la rejilla de segmentos (`beats` × 60/bpm, o
  `dur`) y coloca cada frase dentro del segmento al que se refiere. Una frase que habla de una toma
  que ya pasó se siente desincronizada aunque el audio esté perfecto.
- **Primero escribe, luego mide.** Genera los WAVs, lee `duraciones.json` y comprueba que
  `t[i] + duracion[i] < t[i+1]`. Una frase que pisa a la siguiente se oye como dos voces encimadas.
- **Pausas con puntuación, no estirando el audio.** Comas y puntos. No uses `--lento`: el estiramiento
  mete artefactos audibles.
- **Números con letra**: "veinte minutos", no "20 min". Los sintetizadores leen mal las abreviaturas
  y las cifras largas.
- **Frases cortas**, de 6 a 14 palabras. Una frase larga sale monótona y no deja dónde cortar.
- **Nada de voces de personas reales.** Las voces del plugin son sintéticas y con licencia libre.
  No clones a nadie, ni por referencia de audio, ni describiéndolo en el diseño de voz.

## Límites honestos

| Motor | Dónde corre |
|---|---|
| `qwen` / `voxcpm` (default, recomendado) | **Apple Silicon** (usan MLX) |
| `piper` | multiplataforma |
| `capcut` | **solo macOS**: maneja la app de escritorio a clics, y la app puede cambiar de sitio los botones |

Si ninguno aplica en la máquina del usuario, **entrega el video sin voz y el `guion-voz.md` al lado**:
con los segundos ya calculados, él puede ponerle la voz en la app que quiera.
