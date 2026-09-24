---
description: Investiga en la web las tendencias actuales de formato, sonido y edición para un tema dado, mide el BPM de las canciones candidatas y deja un reporte reutilizable.
argument-hint: "<tema> [--pais MX] [--plataforma tiktok|reels|shorts] [--rapido] [--salida RUTA]"
---

# /reel-tendencias — qué está funcionando ahora

Argumentos recibidos: `$ARGUMENTS`

Tema (lo primero de `$ARGUMENTS` que no sea bandera): viajes, día en el trabajo, mascotas, campo, comida, deporte, fitness, autos, música, lo que sea.

| Bandera | Efecto |
|---|---|
| `--pais XX` | País para las listas de tendencia (default: el de la configuración regional del sistema) |
| `--plataforma` | Una sola plataforma; por defecto revisa vertical en general |
| `--rapido` | 1 agente, formatos y 3 sonidos, sin medir BPM salvo del principal |
| `--salida RUTA` | Dónde dejar el reporte (default: `~/Videos/reel-forge/tendencias/<tema>-<fecha>.md`) |

Se puede correr solo, o lo llama `/reel` en su paso 4.

## Skills y agentes

- Skill principal: `reel-forge:reel-forge`; la guía de esta fase es `skills/reel-forge/referencias/tendencias.md`. No hay una skill llamada `tendencias`.
- Consume el resultado: `reel-forge:motor-video` (formatos, estilos de texto) y `reel-forge:voces` (estilos de narración).
- Agente: `investigador-tendencias`, con acceso a búsqueda web.

### Escalado

| Modo | Agentes | Reparto |
|---|---|---|
| `--rapido` | 1 | todo junto |
| normal | 2 | (a) formatos y edición, (b) sonidos y voces |
| tema amplio o varias plataformas | 3 | se separa (c) referencias concretas: cuentas y videos que lo están haciendo bien |

Más de 3 agentes aquí no sirve: las fuentes se repiten y el reporte se llena de lo mismo dicho tres veces.

## Qué tiene que traer el reporte

### 1. Formatos
Los que funcionan **para ese tema**, no en general. Por cada uno: en qué consiste, duración típica, cuál es el gancho y por qué retiene. Ejemplos del tipo de cosa que se busca: recorrido en primera persona con pocas tomas largas, lista de "cosas que nadie te dice de X", expectativa contra realidad, montaje al beat, narrado tipo documental, carrusel de fotos.

### 2. Sonidos
Por cada candidato: **título, artista, fecha de salida, si está en tendencia en el país pedido y BPM medido**.

- El BPM se **mide**, no se estima: se baja una vista previa legal del audio (la API pública de búsqueda de la tienda de música da un fragmento de 30 s) y se analiza con una librería de análisis de audio.
- Anota el corte que sale del BPM: a 120 BPM, cada 2 tiempos son 1.0 s.
- **Marca cuáles tienen copyright.** La regla del plugin: la canción **no se incrusta** en el archivo que se sube; se pone en la app al publicar, donde además cuenta para la tendencia. Solo se incrusta en la copia `-preview` para revisar.
- Las vistas previas de las tiendas duran ~30 s. Para un video más largo hay que hacer una cama con bucle y transición cruzada, o el final sale mudo.
- Música libre de derechos: última opción. Suena genérica y casi siempre exige crédito.

### 3. Edición y texto
Qué se está usando y **qué ya se ve viejo**. Lo que hoy delata un video hecho con plantilla: fundidos cruzados largos, barridos, destellos, el mismo golpe de aire en cada corte, subtítulos de neón con contorno grueso, emojis en cada línea. Anota también los tamaños y posiciones de texto que están funcionando y la zona segura vigente de cada app.

### 4. Voz y narración
Si el tema se narra, cuál es el estilo del momento (voz sintética de la app, narración propia, sin voz y solo sonido real) y qué está quemado. Detalles de generación en `/reel-voz`.

### 5. Hashtags y descripción
3-5 hashtags: dos amplios, dos del tema, uno de nicho en el idioma del usuario. Nada de bloques de veinte.

### 6. Referencias
3-5 videos o cuentas concretas que estén haciendo bien ese formato, con qué tiene cada uno que valga la pena copiar. Enlace y fecha en que lo viste.

## Reglas

- **Nunca inventes una canción "en tendencia", un BPM ni un número de vistas.** Si no lo pudiste verificar, escribe "no verificado" y sigue. Un dato inventado aquí arruina el video entero más adelante.
- Todo lleva **fecha de consulta y fuente**. Las tendencias caducan en semanas: un reporte de hace dos meses se vuelve a correr, no se reutiliza.
- Distingue lo que viste con tus propios ojos de lo que dice un artículo de "las 10 tendencias de este año", que suele ser refrito.
- Si al abrir videos la plataforma empieza a bloquear las peticiones, baja el ritmo y trabaja con menos muestras. No insistas.
- No uses endpoints no oficiales ni nada que pida la sesión del usuario.

## Entrega

Un `.md` con las seis secciones, más un bloque final de **tres recomendaciones concretas** para el material que se tenga a la mano: qué formato, con qué sonido y por qué. Si lo llamó `/reel`, devuelve además la ruta del reporte para que los armadores lo lean.
