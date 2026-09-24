// Catálogo del material — reel-forge
//
// Reparte fotos, videos y clips 360 entre N agentes en paralelo y devuelve un catálogo
// de momentos (`catalogo.json`), que es el contrato con el que después se escriben los
// conceptos y se construyen las variantes.
//
// Se corre con la herramienta Workflow de Claude Code:
//   Workflow({ scriptPath: "<plugin>/workflows/catalogo.js", args: { ... } })
//
// args (todo opcional menos el material):
//   proyecto        nombre de la carpeta de trabajo, p. ej. "verano-costa"
//   raiz            raíz de proyectos (default: ~/Movies/reel-forge en macOS, ~/Videos/... en Linux)
//   dias            [{ fecha: "2026-04-11", lugar: "Costa", archivos: ["/ruta/IMG_0001.HEIC", ...] }]
//   videos          [{ ruta: "/ruta/VID_0007.MOV", dur_s: 41 }]  (o solo la ruta como texto)
//   clips360        [{ ruta: "/ruta/VID_0012.insv", dur_s: 28 }]
//   agentes_fotos   fuerza el número de agentes de fotos (si no, se calcula, ver abajo)
//   videos_por_agente   default 4
//   clips_por_agente    default 1
//   verificar       default true: segunda pasada sobre los tramos de video y 360
//   tendencias      default true: 1 agente con búsqueda web, en paralelo a todo lo demás
//   plataforma      "tiktok" | "reels" | "shorts"  (default "tiktok")
//   idioma          idioma de los textos en pantalla (default "es")
//   sujeto          cómo referirse a la persona del material, sin nombres propios ("el usuario")
//
// Cada agente escribe su parte en disco ANTES de contestar
// (taller/catalogo/catalogo-<lote>.json). Si el workflow se interrumpe, la siguiente
// corrida la reaprovecha en vez de volver a mirar el mismo material. Para retomar sin
// perder ni eso: Workflow({ scriptPath, resumeFromRunId: "<runId>" }).

export const meta = {
  name: 'reel-forge-catalogo',
  description: 'Cataloga fotos, videos y clips 360 con varios agentes en paralelo y arma catalogo.json',
  whenToUse: 'Fase de contexto de reel-forge: hay material crudo y hace falta saber qué momento hay en cada archivo y en cada tramo de video, antes de decidir conceptos.',
  phases: [
    { title: 'Fotos', detail: 'un agente por día o por lote; hojas de contacto y recortes de cara' },
    { title: 'Videos', detail: 'un agente por lote de videos: tira de cuadros y audio, tramos con inicio y fin' },
    { title: '360', detail: 'un agente por clip equirectangular: hojas de anillo y direcciones útiles' },
    { title: 'Tendencias', detail: '1 agente con búsqueda web, corre en paralelo a todo lo demás' },
    { title: 'Verificar', detail: 'segunda pasada sobre los tramos de video y 360, mirando la ventana real' },
    { title: 'Unir', detail: 'junta los lotes, quita duplicados y dice qué quedó sin cubrir' },
  ],
}

// ─────────────────────────────────────────────────────────── entradas

const A = args || {}
const PROYECTO = A.proyecto || 'proyecto'
// Raíz de proyectos. En macOS ~/Movies/reel-forge, en Linux ~/Videos/reel-forge, y manda
// la variable de entorno REEL_FORGE_HOME si está puesta. Pásala en args.raiz ya resuelta.
const RAIZ = A.raiz || '~/Movies/reel-forge'
const TALLER = `${RAIZ}/${PROYECTO}/taller`
const PLATAFORMA = A.plataforma || 'tiktok'
const IDIOMA = A.idioma || 'es'
const SUJETO = A.sujeto || 'el usuario'

const dias = A.dias || []
const videos = (A.videos || []).map((v) => (typeof v === 'string' ? { ruta: v } : v))
const clips360 = (A.clips360 || []).map((v) => (typeof v === 'string' ? { ruta: v } : v))

if (!dias.length && !videos.length && !clips360.length) {
  throw new Error('catalogo.js: pásale material en args.dias / args.videos / args.clips360')
}

const totalFotos = dias.reduce((n, d) => n + (d.archivos || []).length, 0)

// ─────────────────────────────────────────────────── cuántos agentes
//
// FOTOS. La tabla sale de la skill `reel-forge` (sección "Reparto entre agentes") y de
// lo que aguanta una laptop sin que los renders empiecen a tardar minutos:
//
//   menos de 200 archivos → 3 agentes
//   200 a 1000            → 6, y 8 si el viaje tiene más de 10 días
//   más de 1000           → 10 (tope práctico; antes conviene una criba barata)
//
// Encima de eso, nunca más agentes que días: un agente con medio día de material
// no tiene con qué comparar y repite lo que ya dijo el de al lado.
function agentesDeFotos(nArchivos, nDias) {
  if (nArchivos < 200) return 3
  if (nArchivos <= 1000) return nDias > 10 ? 8 : 6
  return 10
}

const AG_FOTOS = Math.max(1, Math.min(A.agentes_fotos || agentesDeFotos(totalFotos, dias.length), dias.length || 1))

// VIDEOS. Ver un video de verdad son ~15 llamadas a herramientas (tira de cuadros,
// recortes, transcripción, comprobar un segundo). Con más de 4-5 videos el agente se
// queda sin contexto y empieza a describir de memoria, que es justo lo que no sirve.
const VIDEOS_POR_AGENTE = A.videos_por_agente || 4

// 360. Un clip equirectangular da varios encuadres distintos y necesita sus propias
// hojas de anillo: vale un agente entero, aunque dure 20 segundos.
const CLIPS_POR_AGENTE = A.clips_por_agente || 1

// ────────────────────────────────────────────────────────── utilidades

// Reparte una lista en `n` partes lo más parejas posible, respetando el orden.
function repartir(lista, n) {
  const partes = []
  const base = Math.floor(lista.length / n)
  let extra = lista.length % n
  let i = 0
  for (let k = 0; k < n && i < lista.length; k++) {
    const tam = base + (extra > 0 ? 1 : 0)
    if (extra > 0) extra--
    partes.push(lista.slice(i, i + tam))
    i += tam
  }
  return partes
}

// Corta una lista en trozos de tamaño fijo.
function trozos(lista, tam) {
  const out = []
  for (let i = 0; i < lista.length; i += tam) out.push(lista.slice(i, i + tam))
  return out
}

// ──────────────────────────────────────────────────────────── esquemas

const MOMENTO = {
  type: 'object',
  properties: {
    id: { type: 'string', description: 'identificador corto y único, p. ej. "d3-07" o "v2-11"' },
    fuente: { type: 'string', description: 'ruta absoluta del archivo' },
    tipo: { type: 'string', enum: ['foto', 'video', '360'] },
    inicio_s: { type: 'number', description: 'solo video/360: segundo donde empieza el tramo usable' },
    fin_s: { type: 'number', description: 'solo video/360: segundo donde deja de servir' },
    descripcion: { type: 'string', description: 'qué se ve, en una frase concreta' },
    gancho: { type: 'integer', description: '1 relleno, 5 sirve de primer cuadro del video' },
    sale_el_sujeto: { type: 'boolean' },
    favorita: { type: 'boolean', description: 'marcada como favorita en la biblioteca' },
    audio: { type: 'string', description: 'qué se oye; "" si no sirve o no hay' },
    encuadre: { type: 'string', description: 'vertical | horizontal | cuadrado, y el punto de foco 0-1 si es horizontal' },
    notas: { type: 'string', description: 'lo que quien construya necesita saber para no equivocarse' },
  },
  required: ['id', 'fuente', 'tipo', 'descripcion', 'gancho', 'sale_el_sujeto'],
}

const LOTE = {
  type: 'object',
  properties: {
    lote: { type: 'string' },
    archivo: { type: 'string', description: 'ruta del catalogo-<lote>.json que escribiste' },
    momentos: { type: 'array', items: MOMENTO },
    descartes: {
      type: 'array',
      description: 'lo que tiraste y por qué: el usuario puede querer recuperarlo',
      items: {
        type: 'object',
        properties: { fuente: { type: 'string' }, motivo: { type: 'string' } },
        required: ['fuente', 'motivo'],
      },
    },
    resumen: { type: 'string', description: 'dos o tres líneas sobre qué hay en este lote' },
  },
  required: ['lote', 'momentos', 'resumen'],
}

const TENDENCIAS = {
  type: 'object',
  properties: {
    formatos: { type: 'array', items: { type: 'string' } },
    sonidos: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          titulo: { type: 'string' }, artista: { type: 'string' },
          bpm: { type: 'number' }, fuente: { type: 'string', description: 'de dónde salió el dato, con fecha' },
        },
        required: ['titulo', 'fuente'],
      },
    },
    ganchos: { type: 'array', items: { type: 'string' } },
    evitar: { type: 'array', items: { type: 'string' } },
  },
  required: ['formatos', 'sonidos'],
}

const UNION = {
  type: 'object',
  properties: {
    archivo: { type: 'string', description: 'ruta de catalogo.json' },
    total: { type: 'integer' },
    con_sujeto: { type: 'integer' },
    mejores: { type: 'array', items: { type: 'string' }, description: 'ids con gancho 5, candidatos a primer cuadro' },
    huecos: { type: 'array', items: { type: 'string' }, description: 'qué falta: un día sin cubrir, un clip sin audio revisado…' },
    resumen: { type: 'string' },
  },
  required: ['archivo', 'total', 'resumen'],
}

// ──────────────────────────────────────────────────────── el contrato

// Esto va en TODOS los prompts: un agente que improvisa el formato obliga a rehacer el lote.
const CONTRATO = `
Eres un agente de contexto de reel-forge. Tu trabajo es MIRAR el material y describirlo, no editarlo.

Reglas que no se negocian (están en la skill \`reel-forge\`, secciones "Reglas de selección" y "Reparto entre agentes"):
- Mira la imagen de verdad. Nunca catalogues por nombre de archivo, por fecha ni al azar.
- Los videos se catalogan por TRAMOS con \`inicio_s\` y \`fin_s\`, no por archivo completo. Un clip de 40 s
  suele traer 3-6 s usables; el resto es relleno y no va al catálogo.
- El segundo de la imagen buena no es el segundo del audio bueno: si un tramo sirve por lo que se oye,
  dilo en \`audio\` y deja \`inicio_s\`/\`fin_s\` en el tramo donde la IMAGEN sirve.
- Descarta gestos a medias, poses forzadas, tomas borrosas, duplicados casi idénticos, capturas de
  pantalla, documentos, tickets, pantallas con trabajo y cualquier cosa sensible. Anota cada descarte
  con su motivo en \`descartes\`.
- Cuando aparece ${SUJETO}, mírale la CARA en un recorte, no solo el encuadre: a tamaño miniatura una
  mueca no se ve. Revisa la ráfaga completa, casi siempre hay una toma mejor de la misma escena.
- Plataforma: ${PLATAFORMA}, formato vertical 9:16. Idioma de los textos: ${IDIOMA}.

Antes de contestar, ESCRIBE tu resultado en disco:
  ${TALLER}/catalogo/catalogo-<lote>.json
Un agente, un lote, un archivo: si escriben dos en el mismo, se pisan. Si ese archivo YA existe y está
completo (mismo lote, mismos archivos), léelo y devuélvelo tal cual en vez de volver a mirar todo.
`.trim()

// ─────────────────────────────────────────────────────────── los lotes

const lotes = []

repartir(dias, AG_FOTOS).forEach((grupo, i) => {
  const archivos = grupo.flatMap((d) => d.archivos || [])
  if (!archivos.length) return
  lotes.push({
    clase: 'fotos',
    id: `fotos-${i + 1}`,
    fase: 'Fotos',
    etiqueta: `Fotos ${grupo.map((d) => d.fecha || d.lugar || '?').join(', ')}`,
    dias: grupo,
    archivos,
  })
})

trozos(videos, VIDEOS_POR_AGENTE).forEach((grupo, i) => {
  lotes.push({
    clase: 'video',
    id: `video-${i + 1}`,
    fase: 'Videos',
    etiqueta: `Videos ${i + 1} (${grupo.length})`,
    archivos: grupo,
  })
})

trozos(clips360, CLIPS_POR_AGENTE).forEach((grupo, i) => {
  lotes.push({
    clase: '360',
    id: `c360-${i + 1}`,
    fase: '360',
    etiqueta: `360 ${grupo.map((c) => c.ruta.split('/').pop()).join(', ')}`,
    archivos: grupo,
  })
})

// ─────────────────────────────────────────────────────────── prompts

function promptCatalogar(lote) {
  if (lote.clase === 'fotos') {
    return `${CONTRATO}

LOTE ${lote.id} — fotos de: ${lote.dias.map((d) => `${d.fecha || 's/f'} ${d.lugar || ''}`).join(' · ')}

Archivos (${lote.archivos.length}):
${lote.archivos.map((f) => `- ${f}`).join('\n')}

Cómo:
1. Hoja de contacto con miniaturas numeradas de TODO el lote y MÍRALA. Sugerido:
   ffmpeg -i <foto> -vf scale=216:-1 ... o el script de hojas del plugin (skill \`fuentes-material\`).
2. De las candidatas, recorte de cara para revisar la expresión.
3. Un momento por foto que sobreviva, con su punto de foco si la foto es horizontal
   (en 9:16 una foto apaisada se recorta: di en \`encuadre\` dónde está el sujeto, 0-1 en x y en y).
4. Escribe ${TALLER}/catalogo/catalogo-${lote.id}.json y devuélvelo.`
  }

  if (lote.clase === 'video') {
    return `${CONTRATO}

LOTE ${lote.id} — videos:
${lote.archivos.map((v) => `- ${v.ruta}${v.dur_s ? ` (${v.dur_s} s)` : ''}`).join('\n')}

Cómo:
1. Tira de cuadros de cada video y MÍRALA:
   ffmpeg -i <video> -vf "fps=1,scale=216:384,tile=8x4" -frames:v 1 <hoja>.jpg
   (para clips largos baja a fps=0.5; para buscar un instante exacto sube a fps=4 en la ventana).
2. Si tiene voz o sonido que sirva, transcríbelo con marcas de tiempo. Los tiempos "de oído" se
   corren varios segundos: mide, no estimes.
3. Un momento por TRAMO usable, con \`inicio_s\` y \`fin_s\` reales. Antes de fijar el inicio, saca el
   cuadro exacto de ese segundo y míralo: es donde más se equivoca todo el mundo.
4. Marca en \`notas\` si el clip es de 60 fps (sirve para cámara lenta real) y si está en horizontal.
5. Escribe ${TALLER}/catalogo/catalogo-${lote.id}.json y devuélvelo.`
  }

  return `${CONTRATO}

LOTE ${lote.id} — clips 360 (equirectangulares):
${lote.archivos.map((v) => `- ${v.ruta}${v.dur_s ? ` (${v.dur_s} s)` : ''}`).join('\n')}

Cómo (lee antes la skill \`video-360\` del plugin):
1. Proxy equirectangular y hojas de anillo de varios instantes. Sin mirarlas no se pueden escribir keys.
2. Un momento por DIRECCIÓN útil (yaw/pitch/fov), no uno por clip: un mismo clip da el sujeto, el
   paisaje y la proa. Ponlo en \`notas\` con los grados.
3. Dos encuadres del mismo clip con yaw parecido se leen como la misma toma repetida: separa al menos
   90° o cambia de sujeto, y dilo en \`notas\`.
4. Si quien graba va a menos de 2-3 m del lente, marca en \`notas\` que ahí NO va tiny planet: el
   estereográfico le deforma la cara en cualquier dirección. En ese caso propone un empuje rectilíneo.
5. Escribe ${TALLER}/catalogo/catalogo-${lote.id}.json y devuélvelo.`
}

function promptVerificar(lote, res) {
  const muestra = res.momentos.slice(0, 40)
  return `Verificación del lote ${lote.id} de reel-forge. NO recatalogues: comprueba lo que ya se dijo.

Lo que devolvió el agente que lo miró:
${muestra.map((m) => `- ${m.id} · ${m.fuente} · ${m.inicio_s ?? '?'}-${m.fin_s ?? '?'} s · ${m.descripcion}`).join('\n')}
${res.momentos.length > muestra.length ? `\n(+${res.momentos.length - muestra.length} momentos más en ${TALLER}/catalogo/catalogo-${lote.id}.json: revísalos ahí)` : ''}

Para CADA tramo saca una tira a 4 fps de su ventana real (\`-ss inicio_s -t (fin_s - inicio_s)\`) y mírala:
- ¿Se ve lo que dice la descripción, o hay un desfase de segundos?
- ¿Hay cortes de escena, una mano tapando el lente, una cara de desconocido pegada al lente?
- ¿El tramo aguanta el mínimo de ~0.8 s en pantalla?
Corrige \`inicio_s\`/\`fin_s\` y \`descripcion\` donde haga falta, tira lo que no exista (a \`descartes\`,
con el motivo), y REESCRIBE ${TALLER}/catalogo/catalogo-${lote.id}.json con la versión corregida.
Devuelve el lote completo y corregido, en el mismo formato.`
}

// ───────────────────────────────────────────────────────────── el run

log(`Material: ${totalFotos} fotos en ${dias.length} días, ${videos.length} videos, ${clips360.length} clips 360`)
log(`Lotes: ${AG_FOTOS} de fotos, ${trozos(videos, VIDEOS_POR_AGENTE).length} de video, ${clips360.length ? trozos(clips360, CLIPS_POR_AGENTE).length : 0} de 360`)

// Tendencias arranca YA y se recoge al final: no depende del catálogo ni el catálogo de ella,
// así que no tiene por qué esperar turno detrás de nadie.
const pendienteTendencias = A.tendencias === false ? null : agent(
  `Investiga qué está funcionando AHORA en ${PLATAFORMA} vertical para video de viaje/evento personal.
Usa búsqueda web. Devuelve formatos, sonidos con su BPM medido o citado, ganchos de primer segundo y
qué se ve viejo. Cada sonido con la fuente y su fecha: NUNCA inventes canciones "en tendencia" ni
supongas un BPM. Si no encuentras el dato, deja el campo vacío y dilo.`,
  { label: 'Tendencias', phase: 'Tendencias', schema: TENDENCIAS },
)

const VERIFICAR = A.verificar !== false

phase('Fotos')

// pipeline, no parallel: cada lote pasa a su verificación en cuanto termina, sin esperar a los demás.
// El lote de fotos del día 1 no tiene por qué esperar a que alguien acabe de transcribir un video.
const catalogados = await pipeline(
  lotes,
  (_prev, lote) => agent(promptCatalogar(lote), { label: lote.etiqueta, phase: lote.fase, schema: LOTE }),
  (res, lote) => {
    if (!res || !res.momentos.length) return res
    // Solo video y 360 se verifican: el error caro es la ventana de tiempo, y las fotos no tienen.
    if (!VERIFICAR || lote.clase === 'fotos') return res
    return agent(promptVerificar(lote, res), { label: `Verificar ${lote.id}`, phase: 'Verificar', schema: LOTE })
  },
)

const ok = catalogados.filter(Boolean)
const perdidos = lotes.filter((_, i) => !catalogados[i]).map((l) => l.id)
if (perdidos.length) log(`Lotes sin resultado (hay que repetirlos): ${perdidos.join(', ')}`)

// Aquí sí hace falta barrera: unir y quitar duplicados necesita TODOS los lotes a la vez.
phase('Unir')

const momentos = ok.flatMap((r) => r.momentos)
const descartes = ok.flatMap((r) => r.descartes || [])
const vistos = new Set()
const unicos = momentos.filter((m) => {
  const clave = `${m.fuente}|${m.inicio_s ?? ''}|${m.fin_s ?? ''}`
  if (vistos.has(clave)) return false
  vistos.add(clave)
  return true
})
log(`${unicos.length} momentos (${momentos.length - unicos.length} duplicados fuera), ${descartes.length} descartes`)

const tendencias = pendienteTendencias ? await pendienteTendencias : null

const union = await agent(
  `Cierra el catálogo de reel-forge del proyecto "${PROYECTO}".

Los lotes están en ${TALLER}/catalogo/catalogo-*.json (${ok.length} archivos, ${unicos.length} momentos
únicos ya sin duplicados exactos). Tu trabajo:
1. Únelos en ${TALLER}/catalogo/catalogo.json, ordenados por fecha y hora.
2. Quita los duplicados que el filtro por ruta no cazó: dos fotos de la misma ráfaga con la misma
   descripción son una sola; quédate con la mejor y anota la otra en \`descartes\`.
3. Marca los candidatos a primer cuadro (gancho 5) y cuenta cuántos momentos traen al sujeto.
4. Di qué FALTA (\`huecos\`): un día sin cubrir, un clip sin audio revisado, una parte del viaje sin
   b-roll, un lote que no devolvió nada. Eso es lo que se manda a la siguiente ronda.
No inventes momentos que no estén en los lotes.

Lotes que no devolvieron nada: ${perdidos.length ? perdidos.join(', ') : 'ninguno'}.`,
  { label: 'Unir catálogo', phase: 'Unir', schema: UNION },
)

return {
  proyecto: PROYECTO,
  taller: TALLER,
  catalogo: union,
  momentos: unicos,
  descartes,
  tendencias,
  lotes_fallidos: perdidos,
}
