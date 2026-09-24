# Arquitectura

Cómo va el material desde tu biblioteca hasta los videos entregados, y cómo se decide cuántos agentes
corren en paralelo.

## Principios

1. **Contexto antes que edición.** Nunca se edita sobre una lista de archivos. Primero se cataloga qué
   pasa dentro de cada foto y de cada video, con segundos exactos.
2. **Lo pesado no entra al contexto.** Los agentes ven miniaturas, hojas de contacto, tiras de cuadros
   y transcripciones, no los originales de 4K.
3. **Paralelo donde no hay dependencia.** El catálogo y la investigación de tendencias corren al mismo
   tiempo; las dos variantes de un concepto también.
4. **Un solo motor de render.** Todas las variantes salen del mismo script (`skills/motor-video`). Si
   un concepto necesita algo distinto, se arregla el motor, no se copia.
5. **Todo se reconstruye desde un script.** Cada variante deja su `build.py`, no solo su `spec.json`:
   un spec que apunta a un temporal borrado es irreproducible.
6. **Nada se entrega sin revisar.** Cada concepto pasa por un revisor que compara sus dos variantes.

## Flujo completo

```text
┌─ FUENTES ──────────────────────────────────────────────────────────────────┐
│  Apple Photos (macOS)   Carpetas locales   Insta360 .insv   Audio externo   │
└───────────┬────────────────────┬──────────────┬────────────────┬───────────┘
            └────────────────────┴──────┬───────┴────────────────┘
                                        v
                          ┌─────────────────────────────┐
                          │ 1. ALCANCE                  │  hilo principal
                          │ una sola tanda de preguntas:│  /reel
                          │ material, quién sale,       │
                          │ plataforma, idioma, vetos   │
                          └──────────────┬──────────────┘
                                         v
                          ┌─────────────────────────────┐
                          │ 2. INVENTARIO               │  skill: fuentes-material
                          │ archivos, fecha real, tipo, │  /reel-fuentes
                          │ duración, favorito, local   │  sin agentes
                          │ o en la nube                │
                          └──────────────┬──────────────┘
                                         v
                          ┌─────────────────────────────┐
                          │ 3. CRIBA BARATA             │  hilo principal o 1 agente
                          │ fuera capturas, documentos, │  antes de gastar agentes
                          │ tickets, borrosas, duplica- │
                          │ dos + proxys y miniaturas   │
                          └──────────────┬──────────────┘
                                         v
        ┌────────────────────────────────┴───────────────────────────────┐
        v                                                                v
┌───────────────────────────────────────┐              ┌──────────────────────────────┐
│ 4. CATÁLOGO   (N agentes en paralelo) │              │ 5. TENDENCIAS  (1-3 agentes) │
│ workflow: workflows/catalogo.js       │              │ agente: investigador-        │
│                                       │              │         tendencias           │
│  curador-fotos   -> lote de fotos:    │              │  - formatos y ganchos        │
│    hoja de contacto + recorte de cara │              │  - sonidos con BPM MEDIDO    │
│  analista-video  -> lote de videos:   │              │  - estilos de narración      │
│    tira de cuadros + audio -> TRAMOS  │              │  - todo con fuente y fecha   │
│  explorador-360  -> 1 clip: hojas de  │              │                              │
│    anillo, direcciones, keys.json     │              │ -> taller/tendencias/        │
│                                       │              │       tendencias.json        │
│ -> taller/catalogo/catalogo-<lote>.js │              └───────────────┬──────────────┘
└───────────────────┬───────────────────┘                              │
                    v                                                  │
      ┌───────────────────────────────┐                                │
      │ 4b. VERIFICAR Y UNIR          │                                │
      │ segunda pasada sobre los      │                                │
      │ tramos (¿la ventana real      │                                │
      │ muestra lo que dice?), quita  │                                │
      │ duplicados -> catalogo.json   │                                │
      └───────────────┬───────────────┘                                │
                      └──────────────────┬─────────────────────────────┘
                                         v
                        ┌───────────────────────────────┐
                        │ 6. CONCEPTOS                  │
                        │ director-creativo x4-8, en    │
                        │ paralelo: cada uno UN concepto│
                        │ desde su ángulo, con gancho y │
                        │ estructura segundo a segundo  │
                        │             │                 │
                        │             v                 │
                        │ editor-en-jefe x1: elige los  │
                        │ mejores buscando variedad y   │
                        │ dice qué ajustar -> seleccion │
                        │ (aquí confirmas tú)           │
                        └───────────────┬───────────────┘
                                        v
        ┌───────────────────────────────┼───────────────────────────────┐
        v                               v                               v
┌──────────────────┐          ┌──────────────────┐          ┌──────────────────┐
│ CONCEPTO 1       │          │ CONCEPTO 2       │          │ CONCEPTO 3       │
│  comun/  (cama   │          │  comun/          │          │  comun/          │
│  de música, re-  │          │                  │          │                  │
│  cortes 9:16)    │          │                  │          │                  │
│ ┌──────┐┌──────┐ │          │ ┌──────┐┌──────┐ │          │ ┌──────┐┌──────┐ │
│ │  A   ││  B   │ │          │ │  A   ││  B   │ │          │ │  A   ││  B   │ │
│ └──┬───┘└──┬───┘ │          │ └──┬───┘└──┬───┘ │          │ └──┬───┘└──┬───┘ │
└────┼───────┼─────┘          └────┼───────┼─────┘          └────┼───────┼─────┘
     │       │                     │       │                     │       │
     └───────┴─────────────────────┴───────┴─────────────────────┴───────┘
                                        │   7. CONSTRUCCIÓN  (workflows/construir.js)
                                        │   constructor-video x2 por concepto
                                        │   build.py -> spec.json -> render 1080x1920
                                        v
                        ┌───────────────────────────────┐
                        │ 8. REVISIÓN                   │  revisor-critico,
                        │ mira cuadros y escucha:       │  1 por concepto, ve
                        │ negros, huecos de audio, pico │  todas sus variantes
                        │ menor a -0.5 dBTP, audio tan  │  juntas antes de cerrar
                        │ largo como el video, textos   │
                        │ encimados, datos equivocados, │
                        │ cortes contados               │
                        │ -> corrige re-renderizando    │
                        └───────────────┬───────────────┘
                                        │ lo que no pasa, regresa a 7
                                        v
                        ┌───────────────────────────────┐
                        │ 9. ENTREGA                    │
                        │ entregas/v1/<concepto>/       │
                        │  <concepto>-A.mp4   (limpio)  │
                        │  ...-A-preview.mp4  (canción) │
                        │  ...-A-para-ver.mp4 (720p)    │
                        │  README.md por concepto       │
                        │ v2 nunca sobrescribe v1       │
                        └───────────────────────────────┘
```

## Qué pasa en cada fase

### 1. Alcance
Una sola tanda de preguntas, al principio: qué material y de qué periodo, si la persona aparece y
cuánto, si hay gente que no deba salir, plataforma y duración, idioma y narración, y qué no debe
aparecer. Con `--auto` se toman los defaults y se avisa cuáles fueron.

### 2. Inventario
Recorre las fuentes y produce la lista de archivos con fecha real de captura (la del nombre miente
cuando cruzas husos horarios), tipo, duración, marca de favorito y si el original está en disco o solo
en la nube. Rápido y sin tocar los archivos. Se puede correr solo, con `/reel-fuentes`.

### 3. Criba barata
Descarta lo que nunca va a servir antes de repartir trabajo: capturas, documentos, tickets, pantallas,
borrosas y duplicados casi idénticos. Lo descartado se anota con motivo, no se borra. Aquí también se
generan las miniaturas y los proxys que van a ver los agentes.

### 4. Catálogo
La fase que escala. Cada agente recibe un lote y el contrato completo, y devuelve **momentos**, no
archivos: `(id, inicio_s, fin_s, qué se ve, qué se oye, calidad, quién sale)`. Los lotes no se
traslapan y cada agente escribe su propio archivo en disco **antes** de contestar, para que una
interrupción no obligue a mirar el mismo material otra vez.

Una **segunda pasada** verifica los tramos de video y 360 mirando la ventana real: un tramo mal
anotado mete en el montaje una toma que no es la que dice el catálogo. Al final se unen los lotes, se
quitan duplicados y se reporta qué quedó sin cubrir.

### 5. Tendencias
Corre en paralelo con la fase 4 porque no depende de ella. Devuelve formatos vigentes con su
estructura, sonidos con BPM medido sobre el preview real (no supuesto) y notas de estilo, cada cosa
con fuente y fecha. Lo que no tenga fuente, no entra. Con `--sin-tendencias` se salta y los conceptos
usan los formatos base del skill.

### 6. Conceptos
Dos pasos. Primero, de 4 a 8 `director-creativo` en paralelo, cada uno con el catálogo completo, las
tendencias y **un ángulo distinto**: uno al beat, uno narrado, uno de pocas tomas largas, uno de
lista. Cada director devuelve un solo concepto, con gancho de primer segundo, estructura segundo a
segundo, los momentos que usa por id y la proporción de cortes con y sin el sujeto.

Después, un `editor-en-jefe` los lee todos juntos y elige: descarta los repetidos y los débiles, se
queda con los que se diferencian de verdad y dice exactamente qué ajustar en cada uno antes de
construirlo. Es el único punto donde alguien ve todas las propuestas a la vez, y por eso es el que
garantiza la variedad. Tú confirmas su selección antes de que empiece el render.

### 7. Construcción
Dos `constructor-video` por concepto (los reparte `workflows/construir.js`), con la misma escaleta y
libertad de ejecución. Lo común (cama de música,
recortes a 9:16, copias ligeras) se prepara **una vez** en `comun/`; cuando cada agente lo hizo por su
cuenta, uno usó la pista cruda y los últimos segundos de su video salieron mudos. Cada agente escribe
su `build.py`, que tiene que regenerarlo todo desde cero.

### 8. Revisión
Un `revisor-critico` por concepto, distinto de quienes lo construyeron, con todas las variantes del
concepto delante para compararlas **juntas**: así aparece lo que no se ve dentro de una sola (el mismo cuadro con
distinto tratamiento, un `look` que lava el gancho, la misma toma repetida en dos cortes). Checklist
medible: `blackdetect`, `silencedetect`, loudness y pico real, duración de la pista de audio contra la
del video, tamaño del archivo, una tira de cuadros mirada de verdad y el conteo a mano de los cortes
en los que sale la persona principal. El revisor no solo reporta: **corrige y vuelve a renderizar**.

### 9. Entrega
Por variante: el MP4 limpio de 1080x1920 sin música con copyright, el `-preview` con la canción solo
para escucharla, y una copia de 720p para mandar por chat. Un solo README por concepto, con qué es
cada variante, qué sonido ponerle en la app, los hashtags sugeridos y el guion con segundos si va
narrada. Cada tanda es una versión nueva: `v2` no toca `v1`.

## Cómo se decide el número de agentes

### Catálogo de fotos (fase 4)

| Archivos | Agentes | Cómo se reparten |
|---|---|---|
| Menos de 200 | **3** | Uno por día o por lugar |
| 200 a 1000 | **6** (8 si el periodo tiene más de 10 días) | Uno por día, o por lote de ~150 archivos |
| Más de 1000 | **10** | Criba barata primero; luego lotes de ~150 de lo que quedó |

Encima de esa tabla, **nunca más agentes que días**: un agente con medio día de material no tiene con
qué comparar y repite lo que ya dijo el de al lado.

### Catálogo de video y 360

| Material | Agentes | Por qué |
|---|---|---|
| Videos | **1 por cada 4** (configurable) | Ver un video de verdad son ~15 llamadas a herramientas (tira de cuadros, recortes, transcripción, comprobar un segundo). Con más de 4-5, el agente se queda sin contexto y empieza a describir de memoria |
| Clips 360 | **1 por clip** | Cada equirectangular da varios encuadres distintos y necesita sus propias hojas de anillo. Vale un agente entero aunque dure 20 segundos |

### Tendencias
**1** por default, en paralelo a todo lo demás. Hasta **3** cuando conviene separar por tema
(formatos, sonidos, nicho) para que un agente no contamine al otro.

### Conceptos
**4-8 directores creativos** en paralelo, uno por ángulo: menos de 4 y todas las propuestas se
parecen; más de 8 y el editor en jefe pasa más tiempo descartando que eligiendo. Después, **1 editor
en jefe**, siempre uno solo, porque su trabajo es justamente ver todo junto.

### Construcción
**2 por concepto, siempre.** Es lo que te permite comparar: con una sola variante opinas en abstracto;
con tres o más, ya no las revisas. Las dos se eligen para que se lean distinto (muda con sonido
diegético contra narrada, larga contra corta, orden cronológico contra orden por energía).

### Revisión
**1 por concepto**, distinto de quienes lo construyeron, con todas sus variantes delante. Mide y mira
cuadros, que es barato, pero también corrige: si tiene que re-renderizar, cuenta como un render más en el presupuesto de la máquina.

### Topes y ajustes

- **Tope práctico: ~10 agentes a la vez.** Con más, los renders empiezan a tardar minutos y no es
  culpa del código, sino del disco y del CPU. Con 4 conceptos, la construcción va en dos oleadas.
- **Poco tiempo** (`--rapido`): se sube al tope de agentes y se bajan la resolución de las tiras de
  cuadros y la calidad de la transcripción.
- **Sin prisa:** lotes más chicos (~100 archivos) para una revisión más fina.
- **Material en la nube:** el límite lo pone la red. Se cataloga con miniaturas, se bajan solo los
  originales elegidos y en una sola tanda, después de la curaduría.
- **Máquina modesta** (menos de 8 GB de RAM libres o menos de 4 núcleos): tope de 3 agentes, porque el
  preprocesado con `ffmpeg` compite con ellos.
- **Poco disco** (menos de ~20 GB libres): proxys de baja resolución y aviso explícito.
- **Un agente se atora:** no se le espera indefinidamente. Se sigue con lo que hay y se anota en el
  README qué quedó sin catalogar.

### Resumen

| Fase | Agentes | Regla |
|---|---|---|
| Alcance, inventario, criba | 0 | Hilo principal |
| Catálogo de fotos | 3-10 | Tabla por número de archivos, nunca más que días |
| Catálogo de video | 1 por cada 4 videos | Contexto por agente, no número de archivos |
| Catálogo 360 | 1 por clip | Cada clip es su propio trabajo |
| Tendencias | 1-3 | En paralelo al catálogo |
| Conceptos | 4-8 directores + 1 editor en jefe | Un ángulo por director; el editor elige y pide ajustes |
| Construcción | 2 por concepto | En oleadas si son más de ~8 agentes |
| Revisión | 1 por concepto | Ve todas las variantes del concepto y las compara entre sí |

## Qué se pasa entre fases

| Artefacto | Quién lo escribe | Quién lo lee |
|---|---|---|
| Inventario de fuentes | Fase 2 | Fases 3 y 4 |
| `taller/hojas/` (contactos, tiras, recortes de cara) | Fase 3 | Agentes de catálogo |
| `taller/catalogo/catalogo-<lote>.json` | Cada agente de catálogo | Fase 4b |
| `taller/catalogo/catalogo.json` | Fase 4b | Fases 6 y 7 |
| `taller/tendencias/tendencias.json` | Investigador de tendencias | Fase 6 |
| `keys.json` por clip 360 | `explorador-360` | Constructores |
| Conceptos propuestos y `seleccion.json` | Directores y editor en jefe | Constructores |
| `taller/conceptos/<concepto>/comun/` | Hilo principal | Los dos constructores |
| `taller/conceptos/<concepto>/<A\|B>/build.py` y `spec.json` | Constructor | Motor de render y revisor |
| `entregas/v1/<concepto>/` | Fase 9 | Tú |

Todo vive en la carpeta de trabajo del proyecto, nunca en el repo del plugin:

| Sistema | Raíz (configurable con `REEL_FORGE_HOME`) |
|---|---|
| macOS | `~/Movies/reel-forge/<proyecto>/` |
| Linux | `~/Videos/reel-forge/<proyecto>/` |
| Windows | `%USERPROFILE%\Videos\reel-forge\<proyecto>\` |

`taller/` se puede borrar completo: se reconstruye desde los scripts. `entregas/` no.
