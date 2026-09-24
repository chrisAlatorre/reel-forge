---
name: reel-forge
description: Convierte la biblioteca de fotos y videos del usuario en TikToks/Reels/Shorts verticales 9:16, con investigación de tendencias, catálogo del material con agentes en paralelo, edición automática y varias variantes por concepto. Úsala cuando pida un TikTok, un reel, un short, un recap o resumen de un viaje, fiesta o evento, un photo dump, editar material 360, ponerle narración o música en tendencia a sus fotos y videos, o varias propuestas de video a partir de su material.
---

# reel-forge

Convierte una carpeta o biblioteca de fotos y videos en varios videos verticales listos para subir.
Todo corre local: el material no sale de la máquina.

**Tú orquestas.** Tu trabajo es entender el material de verdad, decidir conceptos, repartir el trabajo
entre agentes y revisar lo que regresan. Los scripts de cada skill del plugin
(`${CLAUDE_PLUGIN_ROOT}/skills/<skill>/scripts/`) hacen el trabajo pesado.

## El flujo

| # | Fase | Quién | Sale |
|---|---|---|---|
| 1 | Alcance | tú, con el usuario | qué material, qué plataforma, qué no puede salir |
| 2 | Inventario | tú | lista de archivos con fecha, tipo, duración, favorito |
| 3 | Criba barata | tú o 1 agente | descarta capturas, documentos, borrosas, duplicados |
| 4 | Contexto | N `curador-fotos`, `analista-video`, `explorador-360` | `catalogo.json`: cada foto y cada **tramo** de video, descrito |
| 5 | Tendencias | 1-3 `investigador-tendencias` (búsqueda web) | formatos, sonidos con BPM, ganchos, voces del momento |
| 6 | Conceptos | 4-8 `director-creativo` + 1 `editor-en-jefe` | 3-4 conceptos distintos, cada uno con su gancho y su estructura |
| 7 | Construcción | 2 `constructor-video` por concepto | 2 variantes por concepto, renderizadas |
| 8 | Revisión | 1 `revisor-critico` por concepto | checklist técnico y de contenido, correcciones aplicadas |
| 9 | Entrega | tú | carpeta versionada, un README por concepto, copias ligeras |

Detalle de cada fase en `referencias/`. Léelas cuando llegues a la fase, no todas de golpe:

| Archivo | Para qué |
|---|---|
| `referencias/bibliotecas.md` | de dónde sale el material en macOS, Linux y Windows |
| `referencias/seleccion.md` | **las reglas de selección**, hojas de contacto, tiras de cuadros |
| `referencias/catalogo.md` | el formato de `catalogo.json` (contrato entre agentes) |
| `referencias/agentes.md` | cuántos agentes, qué le pasas a cada uno, qué te devuelve |
| `referencias/tendencias.md` | cómo investigar tendencias sin inventarlas |
| `referencias/conceptos.md` | cómo se arma un concepto y sus variantes |
| `referencias/edicion.md` | el motor, efectos, textos y errores que ya costaron caro |
| `referencias/audio.md` | música, sonido diegético, narración y voces |
| `referencias/video360.md` | material 360 (Insta360 y similares) a 9:16 |
| `referencias/entrega.md` | carpetas, versiones, README y verificación final |

## Cuándo preguntas y cuándo decides solo

**Pregunta una sola vez, al principio, y todo junto** (fase 1). Nada de ir preguntando de a poco:

1. Qué material y de qué periodo (carpeta, fechas, evento).
2. ¿Aparece él o ella en el video? ¿Cuánto? (default: en la mitad de los cortes o menos).
3. ¿Hay personas que no quieran salir? ¿Menores?
4. Plataforma y duración (default: TikTok/Reels vertical, 20-40 s).
5. Idioma de los textos y si quiere narración.
6. ¿Algo que no deba aparecer? (lugares, trabajo, gente, temas).

Si no contesta o dice "tú decide", usa los defaults y **avísale cuáles tomaste**, en una línea.

**Decide solo, sin preguntar:** los conceptos, la música, el orden de las tomas, la duración exacta,
los efectos, cuántos agentes lanzar, qué descartar del material según las reglas de abajo, y los datos
verificables (nombres de lugares, precios, fechas) — investígalos, no los preguntes ni los inventes.

**Detente y pregunta antes de:** publicar o subir algo, borrar originales, gastar dinero, usar una
cuenta suya, manejar una app de terceros a clics, o incluir a un menor identificable, material médico,
documentos o cualquier cosa que se vea sensible.

## Reglas de selección

Estas reglas no son estéticas: **salieron de producción**, de videos que se rehicieron porque estaban
mal. Aplícalas siempre; el usuario puede refutar cualquiera de ellas y entonces manda él.

1. **El sujeto no puede ser todo el video.** Feedback textual que motivó esta regla: *"me da cringe que
   salgas en todas"*. Mezcla paisaje, arquitectura, comida, gente, animales y tomas donde no hay nadie.
   **El sujeto en la mitad de los cortes o menos** (14-35 % funcionó bien), salvo que él pida lo contrario.
   Cuenta los cortes a mano al final y ponlo en el README.
2. **Cuando aparezca el sujeto, prefiere las favoritas de la biblioteca.** Lo que él ya marcó como
   favorito es lo que él cree que le sale bien. El b-roll (paisaje, comida, animales) no tiene esa
   restricción. Si no hay favoritas suficientes, amplía a las tomas vecinas por fecha y hora (±10 min).
3. **Nada de poses forzadas ni gestos a medias.** Descarta a alguien volteando, acomodándose, con la
   boca abierta a medio hablar o con la pose que le indicó un fotógrafo (brazos abiertos, mano a la
   cámara). **Revisa la ráfaga completa**: dos o tres fotos después casi siempre está la buena de la
   misma escena. Mira **la cara** en un recorte, no solo el encuadre — a este nivel de miniatura una
   mueca no se ve.
4. **Descarta por defecto** (refutable por el usuario): tickets, recibos, boletos, comprobantes,
   capturas de pantalla, documentos, pantallas con trabajo o código, fotos borrosas o subexpuestas,
   duplicados casi idénticos, menores identificables como protagonistas y cualquier cosa sensible
   (documentos con datos, matrículas, direcciones, pantallas de banca). Cuando descartes algo por esta
   regla, anótalo en el catálogo con el motivo: el usuario puede querer recuperarlo.
5. **Ve el material de verdad.** Hojas de contacto para fotos, tiras de cuadros para video, recortes de
   cara para expresiones. **Nunca elijas por nombre de archivo, por fecha ni al azar.** Un agente que
   no miró la imagen produce montaje que no pega.
6. **Los videos tienen partes buenas y relleno.** Cataloga **tramos con inicio y fin**, no archivos
   completos. Un clip de 40 s suele traer 3-6 s usables. El catálogo guarda `inicio_s` y `fin_s`, y
   quien construye **no puede salirse de esa ventana** sin sacar una tira y volver a mirar.
7. **El segundo de la imagen buena no es el segundo del audio bueno.** Si usas el sonido de un clip,
   separa la fuente de imagen de la de audio y mira el cuadro del punto de entrada antes de fijarlo.

## Reparto entre agentes

Los agentes de contexto son el cuello de botella y lo que más valor aporta. Escala así:

| Archivos a catalogar | Agentes de contexto en paralelo | Cómo se reparte |
|---|---|---|
| menos de 200 | **3** | por día o por lugar |
| 200 a 1000 | **6** (hasta 8 si hay más de 10 días) | un agente por día o por lote de ~150 archivos |
| más de 1000 | **10** (tope práctico) | criba barata primero, luego un agente por lote de ~150 de lo que sobrevivió |

Además, siempre:

- **1 agente por cada clip 360**, aparte. Un clip equirectangular da varios encuadres y necesita sus
  propias hojas de anillo; no lo mezcles con el lote de fotos de ese día.
- **1 a 3 agentes de tendencias** (`investigador-tendencias`), con acceso a búsqueda web, en paralelo
  a la fase 4: uno de formatos y ganchos, uno de sonidos con BPM, uno del nicho o el destino.
- **4 a 8 `director-creativo`** en la fase 6, cada uno con **un ángulo distinto y explícito** que tú le
  asignas (documental narrado, puro sonido real, guía con precios, gag visual, POV, lista con remate).
  No se ven entre sí: la variedad sale de los ángulos que repartas.
- **1 `editor-en-jefe`, siempre uno.** Es el único que ve todas las propuestas juntas; dos se
  contradicen y se pierde la variedad.
- **2 `constructor-video` por concepto.** Cada uno hace una variante distinta del mismo concepto
  (por ejemplo A muda y B narrada, o A de 35 s y B de 15 s). Dos agentes, dos variantes, mismo concepto.
- **1 `revisor-critico` por concepto**, distinto de los constructores, que revisa **las dos variantes
  juntas**, compara un mismo cuadro entre ellas y corrige lo que bloquea.

Reglas del reparto:

- No pases de ~10 agentes simultáneos: la máquina se satura y los renders empiezan a tardar minutos.
- **Un agente, un lote, un archivo de salida.** Cada uno escribe su propio `catalogo-<lote>.json` y tú
  los unes. Dos agentes escribiendo el mismo archivo se pisan.
- **Dale a cada agente el contrato entero**: las reglas de selección de arriba, el formato del catálogo
  y la lista exacta de archivos de su lote. Un agente que improvisa el formato te obliga a rehacerlo.
- **Lo común va en el armador común, no en cada agente.** La cama de música, los recortes a 9:16 y las
  copias ligeras se hacen una vez en `comun/`. Cuando cada agente lo hizo por su cuenta, uno usó la
  pista cruda y los últimos 6 s de su video salieron mudos.
- **Verifica entre variantes, no solo dentro de cada una.** Un constructor dejó un `look` que lavaba el
  gancho en dos de cuatro entregas porque nadie comparó el mismo cuadro entre variantes.

Prompts listos y contratos exactos en `referencias/agentes.md`.

Con mucho material, las fases 4 y 7-8 se pueden correr con los workflows del plugin, que guardan en
disco lo que devuelve cada agente y dejan retomar una corrida interrumpida:
`${CLAUDE_PLUGIN_ROOT}/workflows/catalogo.js` (fase 4 y 5) y
`${CLAUDE_PLUGIN_ROOT}/workflows/construir.js` (fases 7 y 8).

## Dónde se guarda todo

Raíz por sistema (configurable con la variable de entorno `REEL_FORGE_HOME`):

| Sistema | Raíz |
|---|---|
| macOS | `~/Movies/reel-forge` |
| Linux | `~/Videos/reel-forge` |
| Windows | `%USERPROFILE%\Videos\reel-forge` |

```
<raiz>/<proyecto>/
  taller/                     # trabajo sucio: se puede borrar y reconstruir
    material/                 # exportados, proxies, recortes a 9:16
    hojas/                    # hojas de contacto, tiras de cuadros, recortes de cara
    catalogo/                 # catalogo-<lote>.json y el catalogo.json unido
    tendencias/               # tendencias.json y los previews de audio
    conceptos/<concepto>/
      comun/                  # lo compartido por las variantes: recortes, cama de música
      A/  B/                  # un constructor por letra: build.py, spec.json, notas
  entregas/
    v1/<concepto>/
      README.md               # uno por concepto, con las dos variantes dentro
      <concepto>-A.mp4        # 1080x1920, crf 22, sin música con copyright
      <concepto>-A-preview.mp4  # con la canción, solo para que la vea
      <concepto>-A-para-ver.mp4 # 720p, para mandarla por chat
      guion-voz.txt           # si la variante va narrada
    v2/...                    # tanda siguiente: nunca se sobrescribe v1
```

- **Una tanda, una versión.** Cuando el usuario pide cambios, sale `v2` completa; `v1` no se toca. Así
  puede comparar y volver atrás.
- **`taller/` se reconstruye desde los scripts.** Nunca dejes un `spec.json` que dependa de un archivo
  temporal que ya borraste: el armador (`build.py`) tiene que poder regenerarlo todo desde cero.
- **Un solo README por concepto**, con las dos variantes. No uno por agente.

## Dependencias y límites honestos

- **Multiplataforma:** el motor de render, las hojas de contacto, el catálogo y el 360 corren en
  cualquier sistema con Python y `ffmpeg` en el PATH.
- **Solo macOS:** leer la app Fotos de Apple con `osxphotos` (favoritas, caras, fechas, miniaturas),
  la voz del sistema `say` y manejar CapCut a clics para la voz de narrador viral. En Linux y Windows
  el material entra por carpeta y la narración se hace con el TTS local del plugin. Lo que dependa de
  macOS está marcado como tal en cada referencia; **nunca lo des por hecho: comprueba el sistema antes**.
- **Nada de inventar.** Ni canciones "en tendencia", ni precios, ni fechas, ni nombres de lugares.
  Si no lo verificaste contra la biblioteca o contra una fuente con fecha, no va en pantalla.
