# Agentes de reel-forge

> Los archivos de los agentes viven en `agents/`. Este documento está en `docs/` a propósito: todo
> `.md` dentro de `agents/` se carga como un agente, y un README ahí rompe la validación del plugin.

Ocho subagentes que convierten una biblioteca de fotos y videos en varios TikToks/Reels verticales. Cada uno hace una sola cosa, recibe y entrega **JSON**, y se puede lanzar muchas veces en paralelo.

Al instalar el plugin se invocan con el nombre del plugin por delante: `reel-forge:curador-fotos`, `reel-forge:analista-video`, etc.

## El flujo

```
      material                  catálogo                 ideas                  archivos
 ┌──────────────────┐     ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
 │ curador-fotos    │     │                  │   │ director-creativo│   │ constructor-video│
 │ analista-video   │ ──► │  catalogo/*.json │──►│   (xN paralelo)  │──►│   (xN paralelo)  │
 │ explorador-360   │     │                  │   └────────┬─────────┘   └────────┬─────────┘
 └──────────────────┘     └──────────────────┘            │                      │
 ┌──────────────────┐                                     ▼                      ▼
 │ investigador-    │ ──► investigacion/*.json    ┌──────────────────┐   ┌──────────────────┐
 │ tendencias (xN)  │                             │ editor-en-jefe   │   │ revisor-critico  │
 └──────────────────┘                             │  seleccion.json  │   │ (1 por concepto) │
                                                  └──────────────────┘   └──────────────────┘
```

Las tres etapas de material y la investigación corren **al mismo tiempo**. Lo demás es secuencial: no se proponen conceptos sin catálogo, no se construye sin selección, no se entrega sin revisión.

## Cuándo usar cada uno

| Agente | Úsalo para | Entrega | Instancias |
|---|---|---|---|
| `curador-fotos` | Elegir qué fotos sirven de un lote o una fecha. Arranca por favoritas y aledañas, valida expresiones y descarta basura | `catalogo/fotos-<lote>.json` | 1 por día o por ~150 fotos |
| `analista-video` | Saber qué segundos de un clip sirven y cuáles son relleno | `catalogo/video-<nombre>.json` | 1 por video (o por 3-4 videos cortos) |
| `explorador-360` | Sacar encuadres 9:16 de un equirectangular: hojas, yaw/pitch del sujeto, keys y pruebas | `catalogo/360-<nombre>.json` + pruebas MP4 | 1 por archivo 360 |
| `investigador-tendencias` | Saber qué formatos, ganchos y sonidos están funcionando **hoy** para el tema | `investigacion/tendencias-<tema>.json` | 1 por tema (formatos / sonidos / nicho) |
| `director-creativo` | Proponer **un** concepto fuerte con estructura segundo a segundo y 3-4 variantes | `conceptos/<slug>.json` | 4-8, cada una con un ángulo distinto |
| `editor-en-jefe` | Elegir qué se construye, cuidando variedad, y decir qué ajustar | `seleccion.json` | 1, siempre |
| `constructor-video` | Renderizar las variantes, exportar limpia + preview y escribir el README | MP4 + `build.py` + `spec.json` + `README.md` | **2 por concepto**, una variante cada uno |
| `revisor-critico` | Encontrar fallas concretas y **corregirlas re-renderizando** | `revision-<concepto>.json` + MP4 corregido | **1 por concepto**, ve todas sus variantes juntas |

## Cómo escalar el número de instancias

La regla general: **paraleliza lo que solo mira, serializa lo que decide.**

- **Catálogo (curador, analista, explorador).** Divide por unidad natural: un día de fotos, un video, un archivo 360. Con material de un viaje largo es normal lanzar 10-20 instancias. Empieza con 4-6 a la vez y sube si la máquina aguanta: el render y `ffmpeg` son lo que pesa, y varias sesiones compitiendo hacen que una foto que tarda 3 s tarde minutos.
- **Tendencias.** 2 o 3 instancias: una de formatos y ganchos, una de sonidos con BPM, una del nicho o el destino. Más que eso se repite.
- **Directores.** Aquí está el rendimiento del flujo: **lanza de 4 a 8, cada uno con un ángulo distinto y explícito** (documental narrado, puro sonido real, guía con precios, gag visual, POV, lista con remate, contador de bloques). No se ven entre sí: la variedad viene de los ángulos que les asignes, no de pedirles "algo distinto".
- **Editor en jefe: siempre uno.** Es el único que ve el conjunto. Dos editores en jefe se contradicen y se pierde la variedad.
- **Constructores: dos por concepto**, una variante cada uno. Uno solo con cuatro variantes se copia a sí mismo: cambia el texto y deja el mismo montaje. Dos independientes divergen de verdad. Con más variantes, reparte de a dos, pero **fija en común el look, la cama de música y los recortes a 9:16** y que todos escriban en el mismo README. El error clásico es que un constructor deja un `look` que el otro ya había descartado, y el gancho sale lavado en la mitad de las entregas.
- **Revisores: uno por concepto**, siempre, incluso cuando "se ve bien", y nunca uno de los que construyeron. Tiene que ver **todas las variantes juntas**: lo que más ha aparecido (un `look` que lava el gancho, la misma toma en dos variantes) solo se ve comparando. Corrige lo que bloquea; si un arreglo cambia la idea, sube al editor en jefe.

Cuando dupliques instancias de cualquier agente, pásale en la invocación: **qué lote o ángulo le toca**, **dónde escribe** y **qué ids ya están ocupados**. Si dos escriben el mismo archivo, se pierde trabajo.

## Contratos entre agentes

- **Ids de recursos:** `f-###` foto, `v-<clip>-<letra>` tramo de video, `r-<clip>-<letra>` reencuadre 360. Un concepto solo usa ids que existen en el catálogo.
- **Tiempos** en segundos con 2 decimales. Los de un tramo son relativos al inicio de su archivo; los de las keys 360, relativos al inicio del tramo.
- **Calidad y potencial** en enteros del 1 al 10, con el criterio escrito en cada agente.
- **Rutas** con `~` o relativas a la carpeta de trabajo. Nunca rutas absolutas del equipo de nadie.
- **Nadie inventa material.** Si falta algo, va en `faltantes`, `pendientes` o `no_encontrado`.
- Cada agente escribe su JSON **y** responde un resumen corto en texto: quien lo invocó lee el resumen, el siguiente agente lee el JSON.

## Lo que el plugin les presta

Los agentes llaman a los scripts del plugin con `${CLAUDE_PLUGIN_ROOT}`, que Claude Code sustituye al cargarlos:

| Ruta | Para qué |
|---|---|
| `${CLAUDE_PLUGIN_ROOT}/skills/motor-video/scripts/render.py` | Motor de render: spec JSON → MP4 1080x1920 |
| `${CLAUDE_PLUGIN_ROOT}/skills/video-360/scripts/reencuadre360.py` | Proxy, hojas de perspectivas, keys y render de 360 |
| `${CLAUDE_PLUGIN_ROOT}/skills/fuentes-material/scripts/inventario.py` | Inventario de fotos y videos (Apple Photos o carpeta) |
| `${CLAUDE_PLUGIN_ROOT}/skills/fuentes-material/scripts/hojas.py` | Hojas de contacto, recortes de cara y tiras de cuadros |
| `${CLAUDE_PLUGIN_ROOT}/skills/voces/scripts/voz.py` · `narrar.py` | Narración con TTS local y mezcla sobre un MP4 ya renderizado |
| `${CLAUDE_PLUGIN_ROOT}/skills/*/SKILL.md` | Las guías largas: `motor-video`, `video-360`, `voces`, `fuentes-material` |
| `${CLAUDE_PLUGIN_ROOT}/skills/reel-forge/referencias/` | El detalle de cada fase del flujo |
| `${CLAUDE_PLUGIN_ROOT}/ejemplos/spec-ejemplo.json` | Spec del motor comentado, JSON válido |

Si alguno de esos archivos se renombra, actualiza esta tabla y los agentes que lo mencionan.

## Dependencias del sistema (dilo, no las supongas)

- **Apple Photos / `osxphotos` / la base con las caras detectadas: solo macOS.** En cualquier otro sistema, el camino es una carpeta de archivos con fechas de EXIF y una lista de favoritas.
- **Insta360 Studio** (macOS/Windows) da el mejor stitch del 360. Sin él, el plugin hace un stitch aproximado con `ffmpeg v360` y la costura se nota en objetos cercanos.
- **CapCut** para la voz de narración de la app: solo macOS/Windows con la app instalada. Sin ella, la variante se entrega sin voz más un `guion-voz.txt` con los segundos.
- **`say` de macOS** no se usa como voz final; el TTS local del plugin es multiplataforma.
- `ffmpeg`, `ffprobe` y `uv` hacen falta siempre.

Cuando un agente dependa de algo que no está, lo reporta en `advertencias` o `dependencias_del_sistema` y sigue por el camino alternativo. Ninguno debe fingir que hizo algo que no pudo hacer.
