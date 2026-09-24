---
description: Inventaria y diagnostica las fuentes de fotos y video disponibles - cuántas piezas hay, de qué fechas, si los originales están locales o en la nube, y qué problemas de metadatos traen.
argument-hint: "[--fechas AAAA-MM-DD..AAAA-MM-DD] [--fuente RUTA] [--detalle] [--json]"
---

# /reel-fuentes — qué material hay y en qué estado

Argumentos recibidos: `$ARGUMENTS`

Comando de **diagnóstico, solo lectura**. No edita, no exporta, no baja nada de la nube y no toca EXIF. Sirve para saber con qué se cuenta antes de correr `/reel`, y para entender por qué algo no aparece.

| Bandera | Efecto |
|---|---|
| `--fechas A..B` | Limita el inventario a ese rango |
| `--fuente RUTA` | Solo esa carpeta o biblioteca |
| `--detalle` | Además del resumen, lista por día con cámara y conteo |
| `--json` | Deja el inventario en `inventario.json` además del resumen en pantalla |

## Skills y agentes

- Skill principal: `reel-forge:fuentes-material` (detección, lectura de metadatos, conteos). El trabajo lo hacen `scripts/inventario.py` y `scripts/validar_fechas.py`.
- Apoyo: `reel-forge:video-360` solo para identificar material 360 (`.insv`, `.insp`, equirectangulares 2:1) y saber si está local o en la nube de la cámara.
- **Agentes: normalmente ninguno.** Es un comando rápido y secuencial. Escala así:

| Situación | Agentes |
|---|---|
| Menos de 4 fuentes, cualquier tamaño | 0 — hazlo directo |
| 4+ fuentes, o volúmenes externos lentos | 1 agente por fuente, máximo 4, cada uno devuelve su bloque del inventario |
| Biblioteca de más de ~50 000 piezas | 1 agente extra solo para el barrido de metadatos por año |

Nunca más de 5 agentes aquí: leer metadatos es I/O, y más procesos en paralelo lo hacen más lento, no más rápido.

## Qué revisar

### 1. Biblioteca nativa del sistema
- **macOS (Apple Photos):** con `osxphotos` (`uv tool install osxphotos`). Da conteos, fechas, favoritos, personas y si el original está descargado o solo en la nube, sin abrir la app. Biblioteca por defecto en `~/Pictures/Photos Library.photoslibrary`, o la que diga `REEL_FORGE_PHOTOS_LIBRARY`. **Solo macOS.**
- **Sin macOS o sin osxphotos:** no hay biblioteca nativa que inventariar. Dilo claro y sigue con carpetas. No inventes un equivalente.

### 2. Carpetas
Revisa las que existan y reporta cada una por separado:
`~/Pictures`, `~/Movies` o `~/Videos`, `~/Desktop`, `~/Downloads`, más cualquier volumen externo montado que tenga `DCIM/`.

### 3. Cámaras 360, de acción y drones
- **360:** archivos `.insv` / `.insp`. Si la app de escritorio de la cámara está instalada (**macOS o Windows**), parte del material puede estar **solo en la nube del fabricante** y verse como miniatura sin original. Repórtalo como "en nube, hay que bajar" y estima el peso: son archivos grandes.
- **Acción:** `GX######.MP4`, `GOPR####.MP4`, más los `.LRV`/`.THM` que los acompañan (esos no sirven para editar, no los cuentes como material).
- **Drone:** `DJI_####.MP4`, y los `_D` suelen ser perfil plano tipo D-Log, que necesita graduación antes de usarse.

### 4. Configuración
`~/.config/reel-forge/config.json` si existe, y las variables `REEL_FORGE_FUENTES`, `REEL_FORGE_SALIDA`, `REEL_FORGE_TALLER`. Lo que digan manda sobre la detección automática.

## Qué reportar

Una tabla por fuente:

| Fuente | Fotos | Videos | Rango de fechas | Originales | Peso |
|---|---|---|---|---|---|
| Biblioteca del sistema | 12 480 | 640 | 2019-03 → hoy | 2 100 solo en nube | ~310 GB |
| ~/Pictures/camara | 820 | 0 | 2024-06 → 2024-09 | locales | 9 GB |
| Volumen externo (DCIM) | 0 | 37 | 2024-08 | locales | 61 GB |

Y debajo, un bloque de **diagnóstico** con lo que vaya a estorbar:

- **Fechas sospechosas:** grupos con fecha de fábrica (1970, 2000-01-01) o años fuera del resto. Di cuántos son, de qué cámara y cuál parece la fecha real por cercanía con material bien fechado.
- **Sin ubicación:** cuántos y de qué cámara. Se puede inferir después por cercanía temporal.
- **Sin EXIF:** archivos que pasaron por mensajería; solo tienen fecha de sistema de archivos, que no es confiable.
- **Desfase de zona horaria:** cuando la hora del nombre del archivo y la de la biblioteca no coinciden. Puede correr un día entero.
- **Duplicados y ráfagas:** cuántos grupos, para que la curaduría después escoja una por grupo.
- **Formatos que necesitan conversión:** HEIC (muchas herramientas de video no lo abren directo), HDR de teléfono, D-Log del drone, `.insv` del 360.
- **Espacio en disco libre.** Regla: por debajo de ~20 GB hay que trabajar con proxys; por debajo de ~5 GB no se puede bajar nada de la nube.

Cierra con una recomendación de dos o tres líneas: qué rango tiene material suficiente para un video, qué habría que bajar o corregir antes, y si conviene correr `/reel` tal cual o con `--fuente`.

## Lo que este comando NO hace

- No baja originales de ninguna nube (eso lo hace `/reel`, y solo de lo elegido).
- No corrige fechas ni escribe EXIF.
- No mira las fotos una por una: eso es curaduría, y va en `/reel`.
- No abre las apps de las cámaras. Si hace falta, lo dice y espera a que el usuario decida.
