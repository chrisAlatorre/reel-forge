# Instalación

Reel Forge necesita tres cosas obligatorias: **Claude Code**, **ffmpeg** y **uv**. Todo lo demás es
opcional y cambia según tu sistema operativo.

## Resumen

| Paso | Obligatorio | macOS | Linux | Windows |
|---|---|---|---|---|
| Claude Code | Sí | Sí | Sí | Sí (WSL recomendado) |
| `ffmpeg` | Sí | Homebrew | gestor de paquetes | winget |
| `uv` | Sí | Homebrew o script | script | winget o script |
| `osxphotos` (Apple Photos) | No | Sí | No aplica | No aplica |
| CapCut (voz de la app) | No | Sí | No | No |
| Insta360 Studio (360) | No | Sí | No | Sí (sin automatización) |

---

## 1. Claude Code

Si aún no lo tienes:

```bash
npm install -g @anthropic-ai/claude-code
```

Verifica:

```bash
claude --version
```

## 2. Instalar el plugin

Dentro de Claude Code:

```text
/plugin marketplace add chrisAlatorre/reel-forge
/plugin install reel-forge@reel-forge
```

O desde la terminal, los mismos dos pasos. **`claude plugin install` instala desde un marketplace ya
dado de alta; no acepta una URL de git directa**, por eso el `marketplace add` va primero:

```bash
claude plugin marketplace add chrisAlatorre/reel-forge
claude plugin install reel-forge@reel-forge
```

Verifica que quedó instalado:

```bash
claude plugin list                  # reel-forge@reel-forge · enabled
claude plugin details reel-forge    # 9 skills, 8 agentes y el costo en tokens
```

o, dentro de Claude Code, `/plugin`: debe aparecer `reel-forge` instalado y habilitado, y `/reel`
debe autocompletar.

### Alcances

| Alcance | Comando | Dónde queda |
|---|---|---|
| Usuario (default) | `claude plugin install reel-forge@reel-forge -s user` | `~/.claude/settings.json`, en todos tus proyectos |
| Proyecto | `claude plugin install reel-forge@reel-forge -s project` | `.claude/settings.json`, se comparte por git |
| Local | `claude plugin install reel-forge@reel-forge -s local` | `.claude/settings.local.json`, no se versiona |

### Desarrollo local

El repo es su propio marketplace, así que se da de alta por ruta:

```bash
git clone https://github.com/chrisAlatorre/reel-forge.git
claude plugin marketplace add ./reel-forge
claude plugin install reel-forge@reel-forge
```

Antes de instalar, o después de tocar cualquier skill o agente:

```bash
claude plugin validate ./reel-forge --strict
```

`--strict` convierte los avisos en errores; es lo que conviene en CI. Ojo con una trampa: **todo `.md`
dentro de `agents/` se carga como un agente**, así que un README ahí falla la validación. Por eso la
documentación de los agentes vive en `docs/agentes.md`.

Para probar sin tocar tu configuración, usa un directorio de configuración aparte y bórralo al final:

```bash
export CLAUDE_CONFIG_DIR=$(mktemp -d)
claude plugin marketplace add ./reel-forge && claude plugin install reel-forge@reel-forge
claude plugin details reel-forge
rm -rf "$CLAUDE_CONFIG_DIR" && unset CLAUDE_CONFIG_DIR
```

Los cambios en `skills/`, `agents/` y `commands/` se toman al reiniciar Claude Code.

---

## 3. Dependencias por sistema operativo

### macOS

```bash
# Homebrew, si no lo tienes
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Obligatorias
brew install ffmpeg uv

# Opcional: para textos con marcas de vocal (tailandés, árabe, hindi)
brew install fribidi harfbuzz

# Opcional: leer tu biblioteca de Apple Photos
uv tool install osxphotos
```

Si usas textos en tailandés o árabe y salen círculos punteados, corre los scripts con:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run <script>
```

(Pillow carga `libfribidi` en tiempo de ejecución y `dyld` solo lee la ruta al arrancar.)

**Permisos del sistema.** La primera vez que leas Apple Photos o manejes una app, macOS va a pedir:

| Permiso | Dónde se concede | Para qué |
|---|---|---|
| Fotos | Privacidad y seguridad → Fotos | Inventario, favoritas, caras, lugares |
| Acceso a disco completo | Privacidad y seguridad → Acceso a disco completo | Base de datos y miniaturas de Fotos |
| Automatización | Privacidad y seguridad → Automatización | Manejar CapCut o Insta360 Studio |
| Accesibilidad | Privacidad y seguridad → Accesibilidad | Clics en CapCut o Insta360 Studio |

Concédeselos a la terminal desde la que corres Claude Code (Terminal, iTerm o la que uses), no a
Claude Code por separado.

### Linux

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y ffmpeg fonts-dejavu

# Fedora
sudo dnf install -y ffmpeg dejavu-sans-fonts

# Arch
sudo pacman -S ffmpeg ttf-dejavu

# uv (cualquier distribución)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

No hay Apple Photos, CapCut ni Insta360 Studio. El camino es:

- **Material**: una carpeta. `export REEL_FORGE_LIBRARY="$HOME/Videos/mi-viaje"`.
- **Metadatos**: EXIF (fecha, GPS) más detección propia de caras. No hay marca de favorita.
- **Voz**: TTS local, o entregar sin voz y ponérsela después en la app del teléfono.
- **360**: stitch aproximado de `.insv` con `ffmpeg`; para calidad final necesitas una máquina con
  Insta360 Studio (macOS o Windows) y exportar de ahí el 360 plano.

### Windows

Recomendado: **WSL2 con Ubuntu** y seguir los pasos de Linux. El render en WSL es igual de rápido y
evita problemas de rutas y fuentes.

Nativo, si prefieres:

```powershell
winget install Gyan.FFmpeg
winget install astral-sh.uv
```

Insta360 Studio existe para Windows, pero el plugin **no lo automatiza**: exporta tú el 360 plano a
MP4 y pásaselo como un video normal.

---

## 4. Verificar cada dependencia

Corre esto y compara con lo esperado:

```bash
# ffmpeg: debe imprimir versión y traer libx264 y libfreetype
ffmpeg -version | head -1
ffmpeg -hide_banner -buildconf | grep -E "libx264|libfreetype|libfribidi" || echo "FALTAN CODECS"

# ffprobe (viene con ffmpeg): hace falta para medir y revisar
ffprobe -version | head -1

# uv
uv --version

# Python que va a usar uv (3.10 a 3.12)
uv run --python 3.12 python -c "import sys; print(sys.version)"

# Espacio libre (se recomiendan 8 GB)
df -h ~ | tail -1
```

Prueba de render de punta a punta (crea un video de 2 segundos y lo borra):

```bash
ffmpeg -f lavfi -i color=c=black:s=1080x1920:d=2 -f lavfi -i sine=f=440:d=2 \
  -c:v libx264 -crf 23 -pix_fmt yuv420p -c:a aac -shortest /tmp/reel-forge-prueba.mp4 \
  && ffprobe -v error -show_entries stream=codec_type,width,height /tmp/reel-forge-prueba.mp4 \
  && rm /tmp/reel-forge-prueba.mp4 && echo "RENDER OK"
```

Solo en macOS, si vas a usar Apple Photos:

```bash
# Debe imprimir el número de fotos de tu biblioteca
osxphotos query --count
```

Si dice que no puede abrir la base de datos, falta el permiso de **Acceso a disco completo**.

---

## 5. Configuración

Opcional. Sirve si siempre trabajas con el mismo material o quieres mover las carpetas.

| Variable | Qué hace | Default |
|---|---|---|
| `REEL_FORGE_FUENTES` | Carpetas con tu material, separadas por `:` | Se detectan solas |
| `REEL_FORGE_FOTOTECA` | Ruta de la biblioteca de Apple Photos (solo macOS) | `~/Pictures/Photos Library.photoslibrary` |
| `REEL_FORGE_HOME` | Raíz de los proyectos | `~/Movies/reel-forge` (macOS), `~/Videos/reel-forge` (Linux y Windows) |
| `REEL_FORGE_SALIDA` | Dónde quedan las entregas | `<raíz>/<proyecto>/entregas` |
| `REEL_FORGE_TALLER` | Dónde queda el trabajo intermedio | `<raíz>/<proyecto>/taller` |
| `REEL_FORGE_CACHE` | Modelos y cachés que se bajan solos | `~/.cache/reel-forge` |
| `REEL_FORGE_360` | Raíz del material 360 (originales, proxys y salidas) | `~/reel-forge/360` |
| `REEL_FORGE_FUENTE` | `.ttf` para las etiquetas de las hojas de contacto | La fuente empaquetada en el plugin |

> Ojo: `REEL_FORGE_FUENTES` (carpetas de material) y `REEL_FORGE_FUENTE` (archivo de tipografía) se
> parecen pero no son lo mismo. Los comandos también mencionan `REEL_FORGE_PHOTOS_LIBRARY` para la
> biblioteca de Fotos; si cambias esa ruta, exporta las dos hasta que se unifiquen.

En `~/.zshrc` o `~/.bashrc`:

```bash
export REEL_FORGE_FUENTES="$HOME/Pictures/material:$HOME/Videos/material"
export REEL_FORGE_HOME="$HOME/Movies/reel-forge"
```

También puedes dejarlo en `~/.config/reel-forge/config.json`, que manda sobre la detección automática:

```json
{
  "fuentes": ["~/Pictures/material", "~/Videos/material"],
  "salida": "~/Movies/reel-forge",
  "plataforma": "tiktok",
  "idioma": "es"
}
```

La primera corrida baja las dependencias de Python de cada script (`uv` lo hace solo, unos minutos) y,
si pides narración, el modelo de voz (~4 GB, una sola vez). Quedan en la caché de `uv` y en
`REEL_FORGE_CACHE`.

---

## 6. Problemas comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `/reel` no aparece | El plugin no quedó habilitado | `/plugin`, habilita `reel-forge` y reinicia Claude Code |
| `ffmpeg: command not found` | No está en el PATH | Reinstala con el gestor de paquetes y abre una terminal nueva |
| `unknown encoder 'libx264'` | ffmpeg mínimo, sin codecs | Instala la compilación completa (Homebrew, `winget Gyan.FFmpeg`) |
| Texto en tailandés o árabe con círculos punteados | Falta `libfribidi` para Pillow | Instálalo y usa `DYLD_FALLBACK_LIBRARY_PATH` en macOS |
| Caracteres chinos en cuadritos | La fuente no trae ideogramas | Usa una fuente CJK del sistema o instala `noto-fonts-cjk` |
| `osxphotos` no abre la biblioteca | Falta Acceso a disco completo | Concédeselo a tu terminal y reiníciala |
| Renders muy lentos o el equipo trabado | Demasiados agentes en paralelo | Pídele a Claude que baje a 3 agentes, o construye menos conceptos por tanda |
| Los originales salen borrosos | Están en iCloud y se usó la miniatura | Autoriza la descarga o baja antes el material elegido |
| Se llenó el disco | Proxys y cuadros intermedios | Borra `taller/` del proyecto; se reconstruye desde los scripts |
| Un video sale mudo al final | La canción dura menos que el video | Es un caso conocido: el revisor lo detecta; pide que rehaga la cama de música con loop |
