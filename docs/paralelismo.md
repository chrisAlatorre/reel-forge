# Cuántos agentes lanzar (y qué no se paraleliza)

La regla que resume todo lo demás:

> **Paraleliza MIRAR. Serializa TOCAR.**

Mirar material —fotos, tiras de cuadros, hojas de anillo, transcripciones— es donde está el trabajo de
verdad y donde N agentes rinden casi N veces. Tocar cosas —una app de escritorio, la biblioteca de
fotos, el mismo archivo de salida— no se paraleliza: se estorba.

## Cuántos agentes de contexto

| Archivos a catalogar | Agentes en paralelo | Cómo se reparte |
|---|---|---|
| menos de 200 | **3** | por día o por lugar |
| 200 a 1000 | **6** (8 si hay más de 10 días) | un agente por día, o por lote de ~150 archivos |
| más de 1000 | **10** (tope práctico) | criba barata primero; luego un agente por lote de ~150 de lo que sobrevivió |

Encima de eso, siempre:

- **1 agente por clip 360.** Un clip equirectangular de 20 s da tres o cuatro encuadres distintos y
  necesita sus propias hojas de anillo. Mezclarlo con el lote de fotos del día hace que el agente
  saque un solo encuadre y se le pase el resto.
- **1 agente de tendencias**, con búsqueda web, corriendo en paralelo a todo lo demás. No depende del
  catálogo ni el catálogo de él, así que no tiene por qué esperar turno.
- **2 agentes constructores por concepto**, con las variantes repartidas.
- **1 agente revisor por concepto**, distinto de los constructores.

Nunca más agentes que unidades de material: un agente con medio día de fotos no tiene con qué comparar
y repite lo que ya dijo el de al lado.

### Los dos topes que de verdad mandan

1. **El cap de la herramienta Workflow: `min(16, CPUs − 2)` agentes simultáneos.** Puedes pasarle 40
   lotes a `pipeline()` sin problema; los que sobran esperan turno. Lo que no puedes es *forzar* más
   concurrencia de la que hay.
2. **La máquina.** Arriba de ~10 agentes activos que además invocan `ffmpeg`, los renders empiezan a
   tardar minutos y todo se siente atascado. `ffmpeg` ya usa varios núcleos por su cuenta: cuatro
   renders simultáneos no tardan un cuarto, tardan casi lo mismo que en serie y además dejan la
   máquina inservible para lo demás.

## Qué paraleliza bien

| Trabajo | Unidad | Por qué escala |
|---|---|---|
| Ver fotos | un día, o un lote de ~150 | independientes entre sí; el agente solo lee y describe |
| Ver videos | un lote de ~4 videos | cada video son ~15 llamadas a herramientas; con más de 4-5 el agente se queda sin contexto y empieza a describir de memoria |
| Ver clips 360 | un clip | cada clip pide sus propias hojas y sus propias keys |
| Investigar tendencias | 1 agente | no depende de nada, arranca primero y se recoge al final |
| Construir variantes | 2 por concepto | dos agentes independientes **divergen**; uno solo con cuatro variantes se copia a sí mismo |
| Revisar | 1 por concepto | tiene que ver todas las variantes juntas, así que es uno, pero los conceptos se revisan en paralelo entre ellos |

## Qué NO se paraleliza

- **Manejar una app de escritorio a clics.** La voz de narrador de CapCut (`skills/voces/scripts/capcut_voz.py`,
  **solo macOS**) se genera moviendo una sola ventana: se fija su posición, se hace clic en
  coordenadas y se espera el archivo. Dos agentes haciéndolo a la vez se roban el foco y los clics caen
  en la ventana del otro. **Va en serie, un agente, una tanda.** Además la app se cansa: un proyecto con
  ~100 generaciones encima deja de escribir audio sin dar ningún error; toca crear proyecto nuevo y
  seguir. Si eso pasa, entrega el video sin voz y el `guion-voz.md` al lado.
- **Exportar de la biblioteca de fotos del sistema.** En macOS la descarga de originales desde iCloud
  la serializa el propio sistema; varios procesos a la vez no bajan más rápido, solo fallan más. Haz la
  exportación **una vez, antes**, y deja los archivos ya en `taller/material/` para que los agentes
  solo lean del disco.
- **Renders pesados.** Ver arriba: `ffmpeg` ya es paralelo por dentro.
- **Lo común de un concepto.** Los recortes a 9:16, los pre-renders y la cama de música se hacen **una
  vez** en `conceptos/<id>/comun/`, no dentro de cada constructor. Cuando cada agente lo hizo por su
  cuenta, uno usó el preview crudo de la canción y los últimos 6 segundos de su video salieron mudos
  sin que nada fallara.
- **Escribir el mismo archivo.** Un agente, un lote, un archivo de salida (`catalogo-<lote>.json`).
  Dos agentes sobre el mismo JSON se pisan y el error aparece días después, cuando falta medio día.
- **Decidir.** Los conceptos, el orden de las tomas y qué se entrega no se reparten: eso lo decides tú
  leyendo lo que devolvieron los agentes. Un comité de agentes produce cuatro videos que se parecen.

## Guarda todo en disco, siempre

Una corrida de catálogo con 10 agentes son 20-40 minutos de trabajo. Si se interrumpe —el usuario
cancela, se cae un agente, se acaba la batería— **lo que no esté en disco se perdió**.

- **Cada agente escribe su resultado ANTES de contestar.** Los prompts de
  `workflows/catalogo.js` lo exigen: `taller/catalogo/catalogo-<lote>.json`. Y si ese archivo ya existe
  y está completo, el agente lo lee y lo devuelve en vez de volver a mirar todo. La segunda corrida
  cuesta casi nada.
- **`taller/` es reconstruible; `entregas/` no se toca.** Cada variante deja un `build.py` que
  regenera su spec y sus pre-renders desde cero. Nunca dejes un `spec.json` que apunte a un temporal
  que ya borraste: al limpiar temporales, ese spec queda irreproducible.
- **Retomar la corrida entera:** la herramienta Workflow devuelve un `runId`. Con
  `Workflow({ scriptPath, resumeFromRunId: "<runId>" })` el prefijo que no cambió vuelve de caché al
  instante y solo se re-ejecuta de la primera llamada modificada en adelante. Mismo script y mismos
  `args` = todo en caché.
- **Nada de topes silenciosos.** Si una corrida recorta cobertura (se cayeron dos lotes, se saltó la
  verificación, se quedaron fuera 300 archivos), dilo con `log()` y en el resumen final. Un recorte que
  no se anuncia se lee como "lo revisé todo".

## Cómo se ve esto en los workflows

- **`workflows/catalogo.js`** usa `pipeline()`, no `parallel()`: cada lote pasa a su verificación en
  cuanto termina, sin esperar a los demás. La única barrera es al final, para unir y quitar duplicados,
  que es lo único que necesita todos los lotes a la vez. El agente de tendencias se lanza **sin
  `await`** al principio y se recoge al final, así corre de fondo durante todo el catálogo.
- **`workflows/construir.js`** también corre los conceptos en `pipeline()`. La barrera que sí hace
  falta —los dos constructores de un concepto tienen que acabar antes de que su revisor los compare—
  se resuelve con un `parallel()` **dentro** de la etapa, así que solo bloquea a ese concepto. La
  etapa de corrección solo gasta agentes si el revisor encontró algo que bloquea.

## Señales de que te pasaste de agentes

- Dos lotes devuelven la misma descripción con otras palabras → los lotes eran demasiado chicos.
- Un agente devuelve momentos genéricos ("paisaje bonito", "él sonriendo") → no miró; tenía demasiado
  material o demasiado poco contexto.
- Los renders que tardaban 40 s tardan 4 minutos → hay demasiado `ffmpeg` compitiendo. Baja la tanda.
- El catálogo tiene 600 momentos → nadie cribó. Menos agentes y reglas de descarte más duras rinden
  más que más agentes.
