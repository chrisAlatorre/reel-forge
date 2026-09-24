# Reel Forge

Plugin de [Claude Code](https://claude.com/claude-code) que convierte tu biblioteca de fotos y videos
en TikToks/Reels/Shorts verticales (1080x1920). Todo corre local: el material no sale de tu máquina.

No es un exportador de plantillas. El plugin **mira tu material** cuadro por cuadro, lo cataloga con
varios agentes en paralelo, investiga qué formatos y sonidos están funcionando ahora, propone
conceptos distintos entre sí y renderiza **dos variantes de cada concepto** para que compares.

## Qué hace

1. **Fuentes.** Encuentra tu material: Apple Photos en macOS, o cualquier carpeta en cualquier sistema.
   Reporta cuántas piezas hay, de qué fechas, y si los originales están en disco o solo en la nube.
2. **Criba barata.** Descarta capturas, documentos, tickets, borrosas y duplicados antes de gastar
   agentes en ellos.
3. **Catálogo con agentes en paralelo.** Cada agente recibe un lote, **lo mira de verdad** (hojas de
   contacto, tiras de cuadros, recortes de cara, transcripción del audio) y devuelve *momentos*: de
   un video de 40 s salen 3-6 s usables, con inicio y fin en segundos.
4. **Tendencias.** Un agente investiga en la web formatos, ganchos, estilos y sonidos con **BPM
   medido**, cada cosa con su fuente y su fecha. Nunca inventa canciones "en tendencia".
5. **Conceptos.** Varios directores creativos proponen, cada uno desde su ángulo, un concepto con
   gancho y estructura segundo a segundo; un editor en jefe elige los mejores buscando variedad y
   dice qué ajustar antes de construirlos.
6. **Construcción.** Dos constructores por concepto arman dos variantes distintas: spec JSON → render
   9:16 con cortes al beat, punch-ins, textos en zona segura, mezcla de audio y narración opcional.
7. **Revisión.** Un revisor por concepto, que ve sus variantes juntas, busca fallas concretas —cuadros negros, huecos de audio,
   textos encimados, datos equivocados, material repetido— y las corrige re-renderizando.
8. **Entrega.** Versión limpia de 1080p (sin música con copyright), un preview con la canción solo
   para que la escuches, una copia de 720p para el teléfono y un README por concepto.

## Demo en 5 pasos

```text
# 1. Instala el plugin (dentro de Claude Code)
/plugin marketplace add chrisAlatorre/reel-forge
/plugin install reel-forge@reel-forge
```

```bash
# 2. Verifica las dos dependencias obligatorias
ffmpeg -version | head -1 && uv --version
```

```text
# 3. Mira qué material tienes y en qué estado
/reel-fuentes --fechas 2026-04-10..2026-04-18

# 4. Arranca el flujo completo
/reel el fin de semana en la costa, 30 segundos, con narración

# 5. Claude pregunta una sola vez (material, si sales tú, plataforma, idioma),
#    cataloga, propone conceptos y te entrega dos variantes de cada uno en
#    ~/Movies/reel-forge/<proyecto>/entregas/v1/   (macOS; ~/Videos/... en Linux)
```

Si tu material no está en Apple Photos, dilo en lenguaje natural (`/reel algo con los videos de
~/Videos/costa`) o fíjalo de una vez:

```bash
export REEL_FORGE_FUENTES="$HOME/Pictures/costa:$HOME/Videos/costa"
```

## Requisitos

| Requisito | Para qué | Obligatorio |
|---|---|---|
| Claude Code | Ejecuta el plugin | Sí |
| `ffmpeg` y `ffprobe` (con `libx264` y `libfreetype`) | Todo el render, el análisis y la verificación | Sí |
| [`uv`](https://docs.astral.sh/uv/) | Corre los scripts de Python; instala sus dependencias solo | Sí |
| Python 3.10-3.12 | Lo baja `uv` si no lo tienes | Sí (vía `uv`) |
| Material en una carpeta | Fuente universal, cualquier sistema operativo | Una de las dos |
| macOS + Apple Photos + [`osxphotos`](https://github.com/RhetTbull/osxphotos) | Leer tu biblioteca de Fotos: favoritas, caras, lugares, miniaturas locales | Una de las dos |
| ~20 GB libres de disco | Proxys, cuadros y modelos descargados | Recomendado |
| CapCut (macOS) | Voz de narración de la app, generada a clics | Opcional |
| Insta360 Studio (macOS, Windows) | Stitch de calidad de archivos `.insv` | Opcional |
| Modelo TTS local (se baja solo, ~4 GB) | Narración sin servicios de paga | Opcional |

**Lo que solo existe en macOS:** leer Apple Photos con `osxphotos`, la voz del sistema (`say`),
manejar CapCut a clics y automatizar Insta360 Studio. En Linux y Windows el plugin funciona completo
con el **camino alternativo**: material desde carpeta, metadatos por EXIF, fuentes empaquetadas y
narración con el TTS local (o entrega sin voz, para ponérsela en la app del teléfono).
Detalles en [`docs/instalacion.md`](docs/instalacion.md).

## Instalación

El repo es a la vez el plugin y su marketplace, así que la instalación son dos pasos: dar de alta el
marketplace y luego instalar el plugin.

Dentro de Claude Code:

```text
/plugin marketplace add chrisAlatorre/reel-forge
/plugin install reel-forge@reel-forge
```

Desde la terminal, lo mismo:

```bash
claude plugin marketplace add chrisAlatorre/reel-forge
claude plugin install reel-forge@reel-forge
```

Para desarrollarlo en local, el marketplace es la carpeta clonada:

```bash
git clone https://github.com/chrisAlatorre/reel-forge.git
claude plugin marketplace add ./reel-forge          # ruta local, no repo remoto
claude plugin install reel-forge@reel-forge
```

Comprueba que quedó bien:

```bash
claude plugin validate ./reel-forge --strict   # manifiestos, skills y agentes
claude plugin list                             # reel-forge@reel-forge, enabled
claude plugin details reel-forge               # 9 skills, 8 agentes
```

`claude plugin install` acepta `-s user` (default, todos tus proyectos), `-s project` (compartido por
git) y `-s local` (solo esta máquina). Pasos por sistema operativo y verificación de cada dependencia
en [`docs/instalacion.md`](docs/instalacion.md).

## Uso

```text
/reel <lo que quieres>
```

Ejemplos:

```text
/reel un recap del fin de semana en la playa, 25 segundos, sin voz
/reel algo gracioso con los videos del perro de ~/Videos/max
/reel el viaje de junio --auto --fechas 2026-06-03..2026-06-12
```

El comando pregunta **una sola vez, al principio y todo junto**: qué material, si apareces tú y
cuánto, si hay personas que no deban salir, plataforma y duración, idioma y si quieres narración, y
qué no debe aparecer. Con `--auto` toma los defaults y te dice cuáles tomó. Con `--rapido` baja la
resolución del análisis para entregar antes.

| Comando | Qué hace |
|---|---|
| `/reel` | Flujo completo, de fuentes a entrega |
| `/reel-fuentes` | Inventaria y diagnostica el material disponible, sin editar nada |
| `/reel-tendencias <tema>` | Investiga formatos y sonidos vigentes y mide el BPM de los candidatos |
| `/reel-voz` | Configura y prueba las voces de narración, y fija tu preferida |

## Mapa de skills y agentes

**Skills** (`skills/`): conocimiento que Claude carga cuando le toca esa fase.

| Skill | Para qué |
|---|---|
| `reel-forge` | Orquestador: el flujo de 9 fases, las reglas de selección y dónde se guarda todo. Su detalle está en `skills/reel-forge/referencias/` |
| `fuentes-material` | Encontrar e inventariar material (Apple Photos u otra carpeta), metadatos y miniaturas |
| `motor-video` | Motor de render: spec JSON → 1080x1920, efectos, textos y zona segura |
| `video-360` | Reencuadre de equirectangulares y `.insv` a 9:16 con cámara virtual y keyframes |
| `voces` | Narración: TTS local, voz de CapCut y cómo pegarla a un video ya renderizado |

**Agentes** (`agents/`): subagentes que corren en paralelo, cada uno con su propio contexto.

| Agente | Cuántos | Qué hace |
|---|---|---|
| `curador-fotos` | 1 por día o por ~150 fotos | Revisa un lote de fotos y devuelve los momentos que sirven, con calidad de 1 a 10 |
| `analista-video` | 1 por video (o por 3-4 cortos) | Ve el video en tiras de cuadros, transcribe y devuelve tramos con inicio y fin |
| `explorador-360` | 1 por clip | Encuentra los encuadres útiles por yaw/pitch y deja las keys de cámara listas |
| `investigador-tendencias` | 1-3 | Busca formatos, ganchos y sonidos vigentes, y cita fuente y fecha |
| `director-creativo` | 4-8 | Cada uno propone **un** concepto fuerte desde un ángulo distinto, con estructura segundo a segundo |
| `editor-en-jefe` | 1 | Elige los mejores conceptos buscando variedad, descarta los repetidos y dice qué ajustar |
| `constructor-video` | 2 por concepto | Escribe el armador y el spec de su variante, la renderiza y deja el README de entrega del concepto |
| `revisor-critico` | 1 por concepto | Compara las variantes entre sí, busca fallas concretas mirando cuadros y escuchando, y las **corrige** re-renderizando |

Al instalar el plugin se invocan con el nombre del plugin por delante: `reel-forge:curador-fotos`,
`reel-forge:director-creativo`, etc. El detalle de cada uno está en `docs/agentes.md`.

**Workflows** (`workflows/`): `catalogo.js` reparte fotos, videos y clips 360 entre N agentes;
`construir.js` construye cada concepto con sus constructores y su revisor. Los dos guardan en disco lo
que cada agente devuelve antes de seguir, así que una corrida interrumpida se retoma sin repetir
trabajo.

El **número de agentes** sale de cuánto material hay y de cuánto tiempo tienes; la tabla y sus topes
están en [`docs/arquitectura.md`](docs/arquitectura.md).

## Limitaciones honestas

- **No sube nada ni publica.** El plugin entrega archivos; subirlos lo haces tú.
- **La música con copyright no se incrusta.** La versión limpia sale sin canción y aparte se genera un
  `-preview` solo para que la escuches. En la app le pones el sonido oficial, y así además cuenta para
  la tendencia.
- **Apple Photos solo en macOS.** En otros sistemas pierdes favoritas, caras y lugares de la base de
  Fotos; el plugin cae a EXIF y a detección propia, que es más pobre.
- **Los originales en iCloud hay que bajarlos.** Con la biblioteca optimizada solo tienes miniaturas:
  se cataloga con ellas y se baja en alta únicamente lo elegido, y eso tarda.
- **CapCut e Insta360 Studio se manejan a clics.** Son apps de terceros, sin API: una actualización
  puede romper el flujo. Siempre hay camino alternativo sin ellas.
- **El stitch de `.insv` sin Insta360 Studio es aproximado.** La costura en objetos cercanos no queda
  igual; para calidad final exporta el 360 plano desde Studio y reencuádralo aquí.
- **El render es local y tarda.** Un video de 30 s puede tomar de 3 a 10 minutos contando proxys,
  análisis y verificación.
- **La voz sintética suena a voz sintética.** El TTS local rinde bien en español neutro, pero para una
  voz realmente buena necesitas un servicio de paga con tu propia cuenta.
- **Alfabetos no latinos necesitan fuentes del sistema.** Tailandés, chino y árabe requieren fuentes
  con esos glifos y, para las marcas de vocal, Pillow compilado con raqm.
- **Las tendencias caducan.** Lo que se investigue hoy puede no servir en un mes: se vuelven a buscar
  en cada corrida, no se guardan como verdad.
- **No clona voces de personas reales** ni genera material que suplante a nadie.

## Qué necesita permiso tuyo

| Permiso | Cuándo se pide | Para qué | Si lo niegas |
|---|---|---|---|
| Fotos (macOS: *Privacidad y seguridad → Fotos*) | Al leer la biblioteca con `osxphotos` | Inventario, favoritas, caras, lugares | Usa una carpeta con tus archivos |
| Acceso a disco completo (macOS) | Al leer la base de datos y las miniaturas de Fotos | Hojas de contacto sin bajar originales | Exporta tú el material a una carpeta |
| Descarga desde iCloud | Al bajar los originales de lo elegido | Renderizar en alta resolución | Se renderiza con miniaturas, con menos calidad |
| Automatización y Accesibilidad (macOS) | Al manejar CapCut o Insta360 Studio | Voz de narración y stitch 360 | TTS local o entrega sin voz; 360 con stitch aproximado |
| Acceso a la red | Al investigar tendencias y bajar previews de 30 s | Formatos, sonidos y BPM reales | Le dices tú el formato y la música (`--sin-tendencias`) |
| Escritura en la carpeta de salida | Al catalogar y renderizar | Guardar taller, proxys y entregas | Nada corre |
| Ejecutar `ffmpeg`, `uv` y los scripts del plugin | En cada fase | Todo el procesamiento | Nada corre |

El plugin **no** pide contraseñas, tokens ni cuentas. Todo el procesamiento de imagen, video y audio
es local; lo único que sale a internet son las búsquedas de tendencias y los previews de 30 s.

Antes de publicar o borrar cualquier cosa, el plugin se detiene y te pregunta.

## Documentación

- [`docs/arquitectura.md`](docs/arquitectura.md) — el flujo completo de las 9 fases y qué se pasa entre ellas.
- [`docs/paralelismo.md`](docs/paralelismo.md) — cuántos agentes lanzar y qué **no** se paraleliza.
- [`docs/agentes.md`](docs/agentes.md) — los ocho agentes, sus contratos y cómo escalar cada uno.
- [`docs/instalacion.md`](docs/instalacion.md) — instalación por sistema operativo y verificación.
- [`docs/estado.md`](docs/estado.md) — qué está probado de verdad, qué es teórico y qué sigue.
- `skills/reel-forge/referencias/` — el detalle de cada fase, que Claude lee cuando llega a ella.

## Licencia

MIT. Ver [`LICENSE`](LICENSE).

**El repo no distribuye fuentes, música ni efectos de sonido.** Las tipografías (Montserrat e
Instrument Serif, SIL OFL 1.1), el mapa base (Natural Earth, dominio público) y el modelo de
segmentación (Apache-2.0) los baja `skills/motor-video/scripts/tipografias.py` a
`$REEL_FORGE_CACHE`, cada uno con su licencia al lado. Los efectos de sonido los pones tú en
`$REEL_FORGE_ASSETS/sfx/`.
