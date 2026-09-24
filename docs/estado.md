# Estado del plugin

Qué está **probado de verdad** en una máquina, qué está escrito pero **sin verificar**, y qué falta.
Fecha de la revisión: **2026-09-23**. Entorno: macOS 15 (Apple Silicon), Claude Code 2.1.281,
Python 3.12 vía `uv`, ffmpeg 8.x de Homebrew.

Este documento se actualiza cuando algo cambia de columna. Si dice "probado", es porque se corrió.

---

## Probado de verdad

### El plugin carga

```bash
claude plugin validate . --strict                       # manifiestos + skills + agentes: pasa
claude plugin marketplace add ./reel-forge
claude plugin install reel-forge@reel-forge
claude plugin details reel-forge
```

`details` reporta **9 skills** (las 5 de `skills/` más los 4 comandos de `commands/`, que se cargan
como skills) y **8 agentes**, con ~1.3k tokens siempre presentes. La prueba se hizo con
`CLAUDE_CONFIG_DIR` apuntando a un directorio temporal, que se borró después: **la configuración real
del usuario no se tocó**. El procedimiento exacto está en [`instalacion.md`](instalacion.md).

### El motor de render

Dos renders reales, verificados con `ffprobe` y mirando tiras de cuadros:

| Prueba | Resultado |
|---|---|
| Fotos + clip de video, Ken Burns (`kb`) y punch-in | MP4 1080x1920, 30 fps, 117 cuadros, 3.90 s |
| Textos (`captions`) con acentos, look `film`, grano | los textos salen legibles y dentro de la zona segura |

Lo que eso cubre: lectura del spec, segmentos de foto y de video, `start`/`dur`, `look`, `grain`,
`crf`, tipografías y el `out` relativo a `$REEL_FORGE_SALIDA`.

### Las tipografías

`uv run skills/motor-video/scripts/tipografias.py` baja Montserrat e Instrument Serif con sus
`OFL-*.txt` a `$REEL_FORGE_CACHE/fonts`. Probado con la caché en un directorio temporal.

### `hojas.py` (escrito en esta pasada)

Faltaba: tres documentos lo llamaban y el archivo no existía. Ahora está en
`skills/fuentes-material/scripts/hojas.py` y los tres subcomandos corrieron:

| Subcomando | Prueba | Resultado |
|---|---|---|
| `contacto` | 8 fotos, `--cols 4` | una hoja con miniaturas numeradas y su `indice.json` |
| `caras` | un retrato real | detecta la cara, la recorta y arma la hoja; sin cara, lo reporta y no truena |
| `tira` | clip de 12 s, `--fps 1 --cols 4 --filas 2` | dos tiras, cada una con sus segundos en el índice |

### `inventario.py`

Corrida real sobre una carpeta: cuenta, agrupa en sesiones, resume y avisa de las fechas que solo
vienen del sistema de archivos. Escribe el JSON que consume el resto del flujo.

### Todos los scripts compilan y responden `--help`

13 archivos `.py` pasan `python3 -m py_compile`. Responden `--help` bajo `uv run`:
`render.py`, `tipografias.py`, `reencuadre360.py`, `voz.py`, `narrar.py`, `capcut_voz.py`,
`inventario.py`, `validar_fechas.py`, `exportar.py` y `hojas.py`. `config.py`, `efectos.py` y
`fuentes.py` son módulos: no se ejecutan solos, y los importan los de arriba.

### Los workflows, contra el contrato de la herramienta

`workflows/catalogo.js` y `construir.js` cumplen la forma que pide Workflow: `export const meta`
literal al principio, cuerpo con `phase()`/`agent()`/`parallel()`/`pipeline()`/`log()`, `return` al
final, y **ningún** `Date.now()`, `Math.random()`, `new Date()` ni acceso a Node, que son los errores
que rompen el `resume`. Todas las fases que usan están declaradas en `meta.phases`.

---

## Escrito pero sin verificar

Nada de esto está roto que se sepa: simplemente **no se corrió**, casi siempre porque hacía falta
material, hardware o una app que no había en la máquina de la revisión.

| Qué | Por qué no se probó | Cómo se probaría |
|---|---|---|
| **Los workflows corriendo** | La sesión de revisión no tenía la herramienta Workflow disponible | `Workflow({ scriptPath: "<plugin>/workflows/catalogo.js", args: {...} })` con 10-20 archivos de prueba |
| **Los 8 agentes** | Ningún agente se invocó: sus prompts y contratos son texto revisado, no ejecutado | Una corrida completa de `/reel` sobre una carpeta chica |
| **Apple Photos / `osxphotos`** | Necesita una biblioteca de Fotos real y el permiso de Acceso total al disco | `inventario.py --fuente fotos --resumen` en una Mac con biblioteca |
| **`exportar.py`** | Lo mismo: macOS + `osxphotos` + permisos | `--miniaturas --ids ... --dry-run` primero |
| **`validar_fechas.py` funcionando** | Solo se probó `--help`; hace falta material con fechas rotas de verdad | Una carpeta de cámara externa con el reloj mal |
| **Todo el 360** | No había ningún `.insv` ni equirectangular 2:1 a mano | `proxy` → `hojas` → `render` sobre un clip de prueba |
| **Generar voz (`voz.py`)** | Los motores `qwen`/`voxcpm` bajan ~4 GB y **solo corren en Apple Silicon con MLX** | `voz.py lineas.json salida --motor qwen`; `piper` es el camino multiplataforma |
| **`narrar.py` mezclando** | Depende de que existan los WAV del paso anterior | `--solo-parse` primero, luego la mezcla |
| **`capcut_voz.py`** | Necesita CapCut instalado y permisos de Accesibilidad; se maneja a clics | `--calibrar`, luego `--preparar` |
| **`efectos.py`** | Ningún spec de prueba usó `behind`, `cutout` ni `map`: eso carga MediaPipe y el mapa | Un spec con esos segmentos, tras `tipografias.py --todo` |
| **`preview_audio` y la cama de música** | Hace falta un preview de 30 s de una canción | Un spec con `preview_audio` y un `.m4a` cualquiera |
| **Linux y Windows** | La revisión fue en macOS | `render.py` y `hojas.py` son los dos que más importan ahí |

---

## Lo que se arregló en esta pasada

Varios agentes escribieron el repo en paralelo y las partes no coincidían. Lo corregido:

- **Nombres de skills y agentes inventados.** `commands/reel.md` mandaba a skills (`fuentes`,
  `analisis`, `tendencias`, `edicion`, `fotos`, `camara360`, `voz`) y agentes (`curador-material`,
  `catalogador-clips`, `armador-variante`, `revisor-entrega`) que no existen. Los otros tres comandos
  tenían el mismo problema. Ahora todas las referencias `reel-forge:<algo>` resuelven a una skill o a
  un agente real.
- **Rutas de scripts rotas.** Todo apuntaba a `${CLAUDE_PLUGIN_ROOT}/scripts/*.py`, que no existe:
  los scripts viven dentro de cada skill. También `tiktok.py` (el nombre viejo del motor, hoy
  `render.py`) y `docs/360.md` y `docs/biblioteca.md`, que no existen.
- **`hojas.py` no existía.** Tres documentos lo llamaban. Escrito y probado.
- **Retoque de fotos fantasma.** Cuatro documentos ofrecían `analizar.py` y `editar.py`, que no se
  portaron. El plugin **no retoca personas**; ahora lo dice así y explica la alternativa.
- **Cuántos agentes.** El repo decía a la vez "1 constructor por concepto" y "2", "1 revisor por
  variante" y "1 por concepto". Canon: **2 constructores por concepto, 1 revisor por concepto** que
  ve todas las variantes juntas y corrige lo que bloquea.
- **La fase de conceptos.** `SKILL.md`, `referencias/agentes.md` y `commands/reel.md` la ponían en el
  hilo principal e ignoraban a `director-creativo` y `editor-en-jefe`, que sí existen como agentes.
  Ahora los tres describen los dos pasos.
- **`agents/README.md` se cargaba como un agente** y hacía fallar `claude plugin validate --strict`.
  Movido a `docs/agentes.md`.
- **Comandos de instalación que no existen.** `claude plugin install <url-de-git>` no es válido:
  primero va `claude plugin marketplace add`. Corregido en el README y en `instalacion.md`.
- **OpenCV 5 rompe los scripts.** Salió en 2026 y quitó los clasificadores de `cv2.data`. Los tres
  scripts que usan OpenCV ahora piden `opencv-contrib-python<5` en su cabecera `# /// script`.
- **Rutas y assets que no cuadraban:** el default de `REEL_FORGE_FUENTE` apuntaba a un `assets/` que
  no existe (ahora usa la fuente que baja `tipografias.py`), el spec de ejemplo usaba
  `~/.reel-forge/assets/` en vez de `$REEL_FORGE_ASSETS`, y el README daba a entender que el repo
  distribuye fuentes y efectos de sonido, cosa que no hace.
- **Datos personales.** Ver abajo.

### Datos personales encontrados y sustituidos

El repo es de uso general y no debe traer nada de quien lo escribió. Se encontró y se quitó:

| Dónde | Qué era | Ahora |
|---|---|---|
| `LICENSE` | nombre y apellido reales en el copyright | `reel-forge contributors` |
| `.claude-plugin/plugin.json` | `author.name` con nombre real | `reel-forge contributors` |
| `.claude-plugin/marketplace.json` | `owner.name` con nombre real | `reel-forge contributors` |
| `skills/fuentes-material/SKILL.md` | "entre Guadalajara y Asia hay 14 horas" | "entre dos husos lejanos hay 12-15 horas" |
| `skills/fuentes-material/referencia-photos.md` | "un viaje de México a Asia" | "entre dos husos lejanos" |
| `skills/voces/scripts/capcut_voz.py` | el nombre propio de una voz del catálogo, fijo en el código | `$REEL_FORGE_CAPCUT_VOZ`, con un texto genérico por default |
| `skills/video-360/scripts/reencuadre360.py` | el modelo exacto de cámara del autor | `Insta360 X3/X4/X5 o cualquier equirectangular 2:1` |

Verificado después del cambio: no queda ninguna coincidencia de nombres propios, rutas `/Users/...`,
UUID de biblioteca ni referencias a viajes o equipos concretos. Las rutas de ejemplo son todas
relativas al home (`~/Pictures/viaje`, `~/Movies/reel-forge`) o variables de entorno.

---

## Siguientes pasos, en orden

1. **Una corrida completa de punta a punta** con 30-50 archivos propios y `/reel --auto`. Es la única
   forma de saber si los prompts de los agentes producen lo que dicen sus contratos. Todo lo demás de
   esta lista sale de ahí.
2. **Probar los dos workflows** con la herramienta Workflow, incluido el `resume`: interrumpir a
   propósito una corrida de `catalogo.js` y relanzarla con `resumeFromRunId` para comprobar que no se
   repite el trabajo.
3. **Decidir si los workflows deben usar los agentes del plugin.** Hoy llaman a `agent()` con el
   prompt completo embebido, así que `agents/*.md` y los prompts de `workflows/*.js` describen el
   mismo trabajo en dos lugares. O los workflows pasan `agentType`, o los prompts se recortan a lo que
   el workflow añade. Mientras tanto, **cualquier cambio en un contrato hay que hacerlo en los dos**.
4. **El camino 360, completo**, con un `.insv` real: `proxy`, `hojas`, `keys.json`, `render`. Es la
   parte con más código y cero verificación.
5. **Un spec de prueba que ejercite `efectos.py`** (`behind`, `cutout`, `map`), después de
   `tipografias.py --todo`. Es donde entran MediaPipe y el mapa, las dos dependencias pesadas.
6. **Probar en Linux.** `render.py` y `hojas.py` primero; las tipografías de repuesto para tailandés y
   CJK están escritas para macOS y ahí hay que apuntar `REEL_FORGE_FONT_THAI` y `REEL_FORGE_FONT_CJK`.
7. **Antes de publicar:** ~~cambiar `OWNER` por el usuario real de GitHub~~ (hecho),
   `docs/instalacion.md` y `plugin.json`, y decidir si `version` sube a `0.1.0` definitiva o a `0.2.0`.
8. **Añadir evals** (`claude plugin eval`) con dos o tres casos: que `/reel-fuentes` no invente
   material, que un concepto no use ids fuera del catálogo, y que el investigador de tendencias no se
   invente una canción. Son los tres fallos que más caro salen.
