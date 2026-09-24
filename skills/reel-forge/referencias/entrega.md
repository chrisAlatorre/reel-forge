# Entrega y verificación

## Estructura

```
<raiz>/<proyecto>/entregas/v1/<concepto>/
  README.md
  <concepto>-A.mp4              1080x1920, crf 22, SIN música con copyright
  <concepto>-A-preview.mp4      con la canción, solo para que la oiga
  <concepto>-A-para-ver.mp4     720p, crf 24, 4-11 MB, para mandarla por chat
  <concepto>-B.mp4  ...
  guion-voz.txt                 si alguna variante va narrada
```

Raíz por sistema: macOS `~/Movies/reel-forge`, Linux `~/Videos/reel-forge`,
Windows `%USERPROFILE%\Videos\reel-forge`. Se puede cambiar con `REEL_FORGE_HOME`.

- **Una tanda, una versión.** Los cambios salen en `v2` completa. `v1` no se toca nunca.
- **Un solo README por concepto**, con las dos variantes dentro. No uno por agente.
- El taller (`taller/`) se puede borrar entero y reconstruir corriendo los `build.py`.

## El README del concepto

```markdown
# <nombre del concepto>

**Gancho:** qué se ve y qué se lee en el primer segundo.
**Promesa:** qué le dices al espectador.

| Variante | Duración | Qué la hace distinta | Archivo |
|---|---|---|---|
| A | 34 s | sonido real, sin música | concepto-A.mp4 |
| B | 15 s | narrada, cortada al beat | concepto-B.mp4 |

## Para subirlo
- Sonido oficial: "<título>" de <artista> (<bpm> BPM medidos). El MP4 limpio va sin música: agrégala en la app.
- Etiquetas sugeridas: #… (3-5, una de nicho)
- Descripción sugerida: una línea.
- Si va narrada y se entregó sin voz: `guion-voz.txt` trae el segundo de entrada de cada línea.

## Material
- 21 cortes. El sujeto aparece en 3 (14 %).
- Ids del catálogo usados: d03-014, d03-021#1, v360-04…
- Descartados a propósito: … (y por qué)

## Verificado
- [x] sin negros, sin huecos de audio, pico bajo -0.5 dBTP
- [x] textos legibles y fuera de la zona de botones
- [x] fechas y lugares comprobados contra los metadatos
- [x] misma comparación de cuadro entre A y B

## Si quieres cambios
Qué tocar y dónde: `taller/conceptos/<concepto>/A/build.py`.
```

Nada de rutas personales ni identificadores de biblioteca en el README. Ids del catálogo, sí.

## Checklist de revisión (lo corre el agente revisor)

**Técnico**

```bash
ffmpeg -i v.mp4 -vf "blackdetect=d=0.08:pix_th=0.12" -f null -        # cuadros negros
ffmpeg -i v.mp4 -af "silencedetect=n=-45dB:d=0.25" -f null -          # huecos de audio
ffmpeg -i v.mp4 -af "loudnorm=print_format=summary" -f null -         # pico bajo -0.5 dBTP
ffprobe -v error -select_streams a -show_entries stream=index,codec_type -of csv v.mp4  # UNA pista
ffprobe -v error -select_streams a:0 -show_entries stream=duration -of csv v.mp4        # = largo del video
ffmpeg -i v.mp4 -vf "fps=2,scale=216:384,tile=12x6" -frames:v 1 tira.jpg                # y MÍRALA
```

**De contenido** — esto no lo detecta ningún comando, hay que mirar:

- [ ] El primer segundo detiene el dedo.
- [ ] Hay un mini gancho cada 3-5 s.
- [ ] Cuenta a mano los cortes con el sujeto: ¿la mitad o menos?
- [ ] Ninguna cara a media palabra, ningún gesto raro, ninguna pose forzada.
- [ ] Dos cortes seguidos no se parecen (misma escena, mismo encuadre, mismo color).
- [ ] Ningún texto tapa una cara ni cae en la franja de botones.
- [ ] Ningún texto suelta una palabra huérfana en su renglón.
- [ ] Ningún sello dura menos de ~0.8 s.
- [ ] Cada fecha, lugar, precio y nombre está verificado.
- [ ] No se coló un documento, una pantalla con trabajo, una matrícula ni un menor identificable.
- [ ] **Compara el mismo cuadro entre A y B**: si el look o el recorte cambian el gancho, una está mal.
- [ ] El `build.py` reconstruye la variante desde cero, sin temporales borrados.

## Cómo se lo entregas al usuario

- Mándale las copias ligeras (`-para-ver`), no las de 1080p: hay límites de tamaño en casi cualquier chat.
- **Un archivo por opción cuando sean pruebas** (por ejemplo, tres voces): no las pegues en un solo audio.
- Un mensaje corto: qué es cada concepto en una línea, en qué se diferencian las variantes, y qué
  decisión necesitas de él.
- Di lo que no pudiste hacer y por qué. Un límite dicho vale más que una entrega que parece completa.

## Cuando pida cambios

1. Anota el feedback en una línea, con fecha, en el README del concepto. Lo que sea una preferencia
   estable (cuánto quiere salir, qué música le gusta, qué efectos odia) va al lugar donde el plugin
   guarda preferencias, no en el README de una tanda.
2. Saca `v2` completa. No sobrescribas `v1`.
3. Si el cambio es de criterio (no de un corte), revisa si alguna regla de selección hay que ajustar
   para este usuario y déjalo escrito.
