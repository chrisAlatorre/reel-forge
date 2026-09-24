---
description: Configura y prueba las voces de narración disponibles (locales y las de CapCut), genera una muestra comparable con cada una y deja guardada la preferida del usuario.
argument-hint: "[--probar \"texto de prueba\"] [--solo-locales] [--idioma es-MX] [--crear-voz nombre] [--fijar <voz>]"
---

# /reel-voz — elegir y probar la voz de narración

Argumentos recibidos: `$ARGUMENTS`

Deja lista la voz que van a usar todos los videos narrados. Se corre una vez al instalar el plugin, y otra vez cuando al usuario deje de gustarle cómo suena.

| Bandera | Efecto |
|---|---|
| `--probar "texto"` | Frase de prueba (default: una frase del estilo de un recap, ~12 palabras) |
| `--solo-locales` | Omite las voces que dependen de una app de escritorio |
| `--idioma` | Idioma y variante, p. ej. `es-MX`, `es-ES`, `en-US` |
| `--crear-voz nombre` | Diseña una voz sintética nueva por descripción (ver abajo) |
| `--fijar <voz>` | Guarda esa voz como preferida sin volver a probar todas |

## Skills y agentes

- Skill principal: `reel-forge:voces` (motores, generación, tratamiento del audio). Scripts: `skills/voces/scripts/voz.py`, `capcut_voz.py` y `narrar.py`.
- Consumidor: `reel-forge:motor-video`, que mete la narración como pista de audio del spec; o `narrar.py`, que la pega sobre un MP4 ya renderizado.
- **Agentes: 0 en el caso normal.** La generación es local y secuencial, y la automatización de una app de escritorio **no se puede paralelizar**: es una sola ventana.

| Situación | Agentes |
|---|---|
| Probar hasta 6 voces | 0 |
| Más de 6 voces o varios motores pesados | 1 agente por motor local, máximo 3, cada uno genera sus muestras |
| Voces de app de escritorio | Siempre 0. Una sola sesión, en serie. |

## Paso 1 — Detectar qué hay

1. **Motores locales de TTS neuronal.** Son la opción por defecto: corren en la máquina, no mandan el texto a ningún servicio y no cuestan. Usa solo modelos con **licencia de uso comercial** (Apache-2.0, MIT y similares); hay modelos buenos con pesos que prohíben el uso comercial y ésos quedan fuera. La primera vez bajan varios GB y tardan; después son segundos por línea.
2. **Voz del sistema.** En **macOS** existe el comando `say`, que es instantáneo pero suena a lector de pantalla: sirve para maquetar tiempos, no para publicar. En otros sistemas no asumas que existe un equivalente.
3. **Voces de CapCut** (la aplicación de escritorio, **macOS o Windows**). Ahí viven las voces de narrador que se oyen en la plataforma. **Esto depende de una app con interfaz gráfica: solo funciona si está instalada y solo se maneja a clics.** Camino alternativo si no está: una voz local, o que el usuario ponga el texto a voz dentro de la app del teléfono al publicar.
4. **Servicios comerciales de TTS.** Se mencionan como opción si el usuario quiere calidad de estudio con licencia clara, pero **requieren que él cree la cuenta y la clave**. Nunca se le pide una clave aquí ni se guarda ninguna.

Reporta qué encontraste y qué falta instalar, con el tamaño de lo que habría que bajar.

## Paso 2 — Generar la comparación

Con la misma frase, genera **un archivo por voz**. Nunca un solo audio con todas pegadas: así no se puede comparar ni volver a escuchar una sola.

Nombra los archivos para que se entiendan solos: `01-narrador-local.wav`, `02-narradora-local.wav`, `03-capcut-narrador.wav`.

Tratamiento igual para todas, o la comparación no vale:

- 48 kHz, mono.
- Recorte de silencios al principio y al final.
- Filtro paso alto suave para quitar el retumbe.
- Normalización de sonoridad al mismo objetivo, en dos pasadas.
- **Sin eco ni reverberación.** Un eco añadido hace que cualquier voz suene a "micrófono barato y lejos del micrófono".

Si el usuario quiere un estilo de narración acelerado, aplica el cambio de velocidad **fuera** del motor, con un filtro que conserve el tono. Estirar o comprimir dentro del generador mete artefactos.

## Paso 3 — Medir (opcional pero rápido)

Cuando haya más de tres candidatas, ordénalas antes de que el usuario escuche:

- **Calidad percibida**: un modelo de estimación de calidad de voz (tipo MOS automático) da un número comparable entre voces.
- **Inteligibilidad**: transcribe el audio generado y compáralo con el texto original. Si una voz se come palabras o se inventa otras, sale de la lista aunque suene bonito.

Presenta la tabla ordenada y manda igual los archivos: el oído del usuario manda sobre cualquier métrica.

## Paso 4 — Elegir y guardar

Manda las muestras y una tabla corta: voz, motor, licencia, si depende de una app, tiempo por línea. Pregunta **una sola cosa**: cuál quiere.

Guarda la elección en `~/.config/reel-forge/voz.json`:

```json
{
  "motor": "local",
  "voz": "narrador",
  "idioma": "es-MX",
  "velocidad": 1.0,
  "fx": "limpio",
  "elegida_el": "2026-01-15"
}
```

A partir de ahí, todo lo que narre `/reel` usa esa voz sin volver a preguntar.

## Crear una voz nueva (`--crear-voz`)

Algunos motores locales diseñan una voz a partir de una descripción de texto y una semilla, sin clonar a nadie.

- Escribe la descripción **en el idioma de la voz**. Una descripción en inglés para una voz en español suele salir con acento extranjero.
- Prueba 3-4 semillas y quédate con la mejor por medición, no por corazonada.
- Guarda junto a la voz un `.json` con el texto de la descripción, la semilla y la licencia del modelo, para poder reproducirla.

## Reglas duras

- **No clonar la voz de una persona real** (actores, locutores, famosos, conocidos) ni describirla para imitarla. Ni para pruebas.
- **No usar endpoints no oficiales de ninguna plataforma**, y menos con la sesión del usuario. Si quiere la voz de una app, la pone dentro de esa app al publicar.
- Nada de voz sintética plana y genérica: si la única opción disponible suena a lector de pantalla, dilo y entrega el video **sin voz** más un guion con los segundos, para que el usuario le ponga la voz en la app.
- Las claves de servicios comerciales son del usuario: ni se piden, ni se guardan, ni se imprimen.

## Automatizar una app de escritorio (solo si hay que usar sus voces)

Es frágil por naturaleza. Lo que hay que respetar:

- Los botones **se mueven entre versiones de la app**. Antes de una tanda, calibra sobre la ventana real en vez de confiar en coordenadas guardadas.
- Un proyecto muy reusado puede dejar de generar audio **sin dar error**: sale el diálogo, se cierra y no aparece archivo. Regla: **una tanda larga, un proyecto nuevo**; si empieza a fallar, se crea otro y se sigue.
- Para saber si el problema es de la app o de los clics, revisa el archivo de proyecto: si el texto llegó al proyecto, los clics estuvieron bien y la falla es de la app.
- Muchas de estas apps **escriben el audio en la carpeta del proyecto en cuanto lo generan**, así que no hace falta exportar nada: basta copiar el archivo y convertirlo.
- Requiere que la pantalla esté desbloqueada y la ventana visible. **En una sesión remota o con la pantalla apagada no funciona**, y la primera vez el sistema puede pedir permisos de automatización que solo se aceptan frente a la máquina.

## Entrega

Los archivos de muestra, la tabla comparativa, la voz elegida escrita en la configuración y una línea diciendo qué se guardó. Si algún motor no se pudo probar, di por qué y qué haría falta para probarlo.
