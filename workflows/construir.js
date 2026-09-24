// Construcción de conceptos — reel-forge
//
// Toma conceptos ya decididos y construye cada uno con 2 agentes constructores
// (las variantes repartidas entre ellos) más un revisor que ve TODAS las variantes juntas.
//
// Se corre con la herramienta Workflow de Claude Code:
//   Workflow({ scriptPath: "<plugin>/workflows/construir.js", args: { ... } })
//
// args:
//   conceptos               [{ id, titulo, gancho, estructura, duracion_s, musica, narracion,
//                              variantes: [{ letra: "A", que: "muda, 35 s" }, ...],
//                              momentos: ["d3-07", "v2-11", ...] }]     ← ids del catálogo
//   proyecto, raiz          dónde vive el proyecto (ver catalogo.js)
//   version                 tanda de entrega, default "v1" (nunca se sobrescribe la anterior)
//   agentes_por_concepto    default 2
//   variantes_por_concepto  default 2 (una por constructor)
//   revisor                 default true
//   arreglar                default true: si el revisor encuentra algo que bloquea, se corrige
//   motor                   comando del motor de render (default: el de la skill motor-video)
//   catalogo                ruta de catalogo.json (default: <taller>/catalogo/catalogo.json)
//   tendencias              ruta de tendencias.json, si la fase de tendencias la dejó
//   plataforma, idioma, sujeto
//
// Igual que en catalogo.js: cada agente deja su trabajo en disco (build.py, spec.json, notas.md)
// antes de contestar, así una interrupción no tira el render. Para retomar la corrida entera:
// Workflow({ scriptPath, resumeFromRunId: "<runId>" }).

export const meta = {
  name: 'reel-forge-construir',
  description: 'Construye cada concepto con 2 agentes (variantes repartidas) y un revisor que las compara',
  whenToUse: 'Ya hay catálogo, tendencias y conceptos decididos, y toca renderizar las variantes de cada concepto.',
  phases: [
    { title: 'Común', detail: 'un agente por concepto prepara lo compartido: recortes, cama de música, originales' },
    { title: 'Armar', detail: '2 agentes por concepto, cada uno con sus variantes' },
    { title: 'Revisar', detail: '1 revisor por concepto: ve todas las variantes juntas y compara el mismo cuadro' },
    { title: 'Corregir', detail: 'solo si el revisor encontró algo que bloquea la entrega' },
  ],
}

// ─────────────────────────────────────────────────────────── entradas

const A = args || {}
const conceptos = A.conceptos || []
if (!conceptos.length) throw new Error('construir.js: pásale args.conceptos')

const PROYECTO = A.proyecto || 'proyecto'
const RAIZ = A.raiz || '~/Movies/reel-forge' // en Linux ~/Videos/reel-forge; manda REEL_FORGE_HOME
const VERSION = A.version || 'v1'
const TALLER = `${RAIZ}/${PROYECTO}/taller`
const ENTREGAS = `${RAIZ}/${PROYECTO}/entregas/${VERSION}`
const CATALOGO = A.catalogo || `${TALLER}/catalogo/catalogo.json`
const TENDENCIAS = A.tendencias || `${TALLER}/tendencias/tendencias.json`
const PLATAFORMA = A.plataforma || 'tiktok'
const IDIOMA = A.idioma || 'es'
const SUJETO = A.sujeto || 'el usuario'

// El motor de render vive en la skill `motor-video` del plugin. Si el archivo se llama
// distinto en tu instalación, pásalo en args.motor en vez de tocar este script.
const MOTOR = A.motor || 'uv run "$CLAUDE_PLUGIN_ROOT/skills/motor-video/scripts/render.py"'

// ───────────────────────────────────────────────── cuántos agentes
//
// CONSTRUCTORES POR CONCEPTO: 2, y es a propósito.
//   1 agente con 4 variantes se copia a sí mismo: cambia el texto y deja el mismo montaje.
//   2 agentes independientes divergen de verdad (es de donde salen las propuestas que no se parecen).
//   3 o más y empiezan a rehacer cada uno lo común (recortes, cama de música) y a saturar la máquina:
//   el cap de concurrencia de Workflow es min(16, CPUs - 2) y un render con ffmpeg ya usa varios núcleos.
const AG_POR_CONCEPTO = Math.max(1, A.agentes_por_concepto || 2)

// VARIANTES: por default una por constructor. Cada variante es spec + render + revisión, varios
// minutos de máquina; más de 2 por agente y el último render sale sin que nadie lo haya mirado.
const VAR_POR_CONCEPTO = Math.max(1, A.variantes_por_concepto || AG_POR_CONCEPTO)

const REVISOR = A.revisor !== false
const ARREGLAR = A.arreglar !== false

// Los conceptos corren en pipeline, así que estos agentes NO están todos vivos a la vez;
// aun así conviene saber el pico teórico para no pedir 8 conceptos en una sola corrida.
const PICO = conceptos.length * AG_POR_CONCEPTO
if (PICO > 10) log(`Aviso: ${conceptos.length} conceptos × ${AG_POR_CONCEPTO} constructores = ${PICO} agentes. Arriba de ~10 simultáneos la máquina se satura; el pipeline los encola, pero considera partir la tanda.`)

// ────────────────────────────────────────────────────── esquemas

const VARIANTE = {
  type: 'object',
  properties: {
    letra: { type: 'string' },
    spec: { type: 'string', description: 'ruta del spec.json' },
    armador: { type: 'string', description: 'ruta del build.py que regenera todo desde cero' },
    mp4: { type: 'string', description: 'ruta del render limpio, sin música con copyright' },
    preview: { type: 'string', description: 'ruta del -preview.mp4 con la canción, o "" si no hay' },
    duracion_s: { type: 'number' },
    cortes: { type: 'integer' },
    cortes_con_sujeto: { type: 'integer' },
    momentos: { type: 'array', items: { type: 'string' }, description: 'ids del catálogo que usaste' },
    guion_voz: { type: 'string', description: 'ruta del guion-voz.md si va narrada, o ""' },
    notas: { type: 'string', description: 'decisiones que tomaste y lo que no salió como querías' },
  },
  required: ['letra', 'spec', 'mp4', 'duracion_s', 'cortes', 'cortes_con_sujeto'],
}

const COMUN = {
  type: 'object',
  properties: {
    carpeta: { type: 'string' },
    recursos: {
      type: 'array',
      description: 'lo que dejaste listo para las dos variantes',
      items: {
        type: 'object',
        properties: { ruta: { type: 'string' }, que: { type: 'string' } },
        required: ['ruta', 'que'],
      },
    },
    cama_audio: { type: 'string', description: 'ruta de la cama de música ya loopeada y normalizada, o ""' },
    notas: { type: 'string' },
  },
  required: ['carpeta', 'recursos'],
}

const PROBLEMA = {
  type: 'object',
  properties: {
    variante: { type: 'string' },
    gravedad: { type: 'string', enum: ['bloquea', 'importante', 'menor'] },
    que: { type: 'string' },
    donde: { type: 'string', description: 'segundo o rango donde se ve' },
    como_arreglar: { type: 'string' },
  },
  required: ['variante', 'gravedad', 'que', 'como_arreglar'],
}

const REVISION = {
  type: 'object',
  properties: {
    aprobadas: { type: 'array', items: { type: 'string' } },
    problemas: { type: 'array', items: PROBLEMA },
    comparacion: { type: 'string', description: 'qué cambia entre variantes y cuál recomiendas' },
    readme: { type: 'string', description: 'ruta del README.md del concepto' },
  },
  required: ['aprobadas', 'problemas', 'comparacion'],
}

// ──────────────────────────────────────────────── reparto de variantes

// Si el concepto no trae variantes escritas, se inventan letras y se deja que el constructor
// decida el eje (mudo/narrado, largo/corto, b-roll/sujeto). Lo que NO se deja al azar es el
// reparto: round-robin, para que si un constructor se cae no se pierda una mitad contigua
// del abanico (con A,B a uno y C,D al otro, perder al segundo te deja sin las dos cortas).
function variantesDe(concepto) {
  if (concepto.variantes && concepto.variantes.length) return concepto.variantes
  const letras = 'ABCDEFGH'.split('')
  return Array.from({ length: VAR_POR_CONCEPTO }, (_, i) => ({ letra: letras[i], que: '' }))
}

function repartoRoundRobin(variantes, nAgentes) {
  const equipos = Array.from({ length: Math.min(nAgentes, variantes.length) }, () => [])
  variantes.forEach((v, i) => equipos[i % equipos.length].push(v))
  return equipos
}

// ────────────────────────────────────────────────────────── prompts

function contrato(concepto) {
  return `
Eres un agente constructor de reel-forge. Construyes variantes de UN concepto, ya decidido.

CONCEPTO "${concepto.id}" — ${concepto.titulo}
Gancho (primer segundo): ${concepto.gancho || '(decídelo tú y justifícalo)'}
Estructura: ${concepto.estructura || '(decídela tú)'}
Duración objetivo: ${concepto.duracion_s || 30} s · Plataforma: ${PLATAFORMA} 9:16 · Idioma: ${IDIOMA}
${concepto.musica ? `Música: ${concepto.musica}` : ''}
${concepto.narracion ? `Narración: ${concepto.narracion}` : ''}
${concepto.momentos && concepto.momentos.length ? `Momentos asignados del catálogo: ${concepto.momentos.join(', ')}` : ''}

Contratos y límites (están en la skill \`reel-forge\` y en las de \`motor-video\`, \`voces\` y \`video-360\`):
- Catálogo: ${CATALOGO}. Tendencias: ${TENDENCIAS}.
- **No te salgas de la ventana \`inicio_s\`/\`fin_s\` de un momento.** Si necesitas otra, saca la tira de
  cuadros de la ventana nueva y MÍRALA antes de usarla; si no, sales con la cara de un desconocido
  pegada al lente en vez de lo que decía el catálogo.
- ${SUJETO} no puede salir en todos los cortes: la mitad o menos (14-35 % es lo que ha funcionado).
  Cuenta los cortes a mano y ponlo en \`cortes\` y \`cortes_con_sujeto\`.
- Lo COMÚN ya está hecho en la carpeta común del concepto (recortes a 9:16, cama de música, originales
  exportados). Úsalo, no lo rehagas: cuando cada agente lo hizo por su cuenta, uno usó la pista cruda
  y los últimos segundos de su video salieron mudos.
- Todo reproducible: deja un \`build.py\` que regenere el spec y los pre-renders desde cero. Nunca
  dejes un spec que apunte a un temporal que ya borraste.
- Render: ${MOTOR} <spec.json>. Ejemplo comentado del formato del spec en
  \`$CLAUDE_PLUGIN_ROOT/ejemplos/spec-ejemplo.json\`; pon \`"crf": 22\` en las entregas de 1080p.
- Verifica ANTES de contestar: \`blackdetect\`, \`silencedetect=n=-45dB:d=0.25\`,
  \`loudnorm=print_format=summary\` (pico por debajo de -0.5 dBTP) y una tira \`fps=2,tile=12x6\` del
  render. Mira los cuadros de cada texto: el motor envuelve por ancho, el \`\\n\` a mano no basta y una
  palabra huérfana se ve fatal en un cuadro congelado.
`.trim()
}

function promptComun(concepto) {
  return `Prepara lo COMÚN del concepto "${concepto.id}" (${concepto.titulo}) de reel-forge, antes de que
entren los constructores. Carpeta: ${TALLER}/conceptos/${concepto.id}/comun/

${contrato(concepto)}

Deja listo y verificado:
1. Los originales de los momentos asignados, exportados de la biblioteca a la carpeta común.
2. Los recortes a 9:16 y los pre-renders que las variantes vayan a compartir (un zoom, una rotación de
   entrada: el motor no rota, eso se pre-renderiza aparte).
3. La cama de música: si el video dura más que el preview de la canción (~30 s), arma el loop con
   \`acrossfade\` y normalízalo. Un video de 35 s con el preview crudo se queda mudo al final y nadie
   lo nota hasta que el usuario lo ve.
4. Un \`RECURSOS.json\` con qué es cada archivo, para que los constructores no adivinen.
No armes ninguna variante: eso es el paso siguiente.`
}

function promptArmar(concepto, comun, misVariantes, iAgente) {
  return `${contrato(concepto)}

Eres el constructor ${iAgente + 1} de este concepto. Te tocan estas variantes:
${misVariantes.map((v) => `- ${v.letra}: ${v.que || '(el eje lo eliges tú; que NO se parezca a las del otro constructor)'}`).join('\n')}

Lo común ya está en ${TALLER}/conceptos/${concepto.id}/comun/ ${comun && comun.carpeta ? `(${comun.recursos.length} recursos, ver RECURSOS.json)` : '(revisa qué hay antes de rehacer nada)'}.
${comun && comun.cama_audio ? `Cama de música ya loopeada: ${comun.cama_audio}` : ''}

Por cada variante que te toca:
1. Carpeta propia: ${TALLER}/conceptos/${concepto.id}/<LETRA>/ con \`build.py\`, \`spec.json\` y \`notas.md\`.
2. Renderiza y verifica (la lista de comprobaciones está arriba).
3. Copia la entrega a ${ENTREGAS}/${concepto.id}/ como \`${concepto.id}-<LETRA>.mp4\`, más el
   \`-preview.mp4\` si lleva canción y una copia ligera \`-para-ver.mp4\` a 720p para mandar por chat.
4. Si la variante va narrada, deja el \`guion-voz.md\` junto al MP4 (formato en
   \`$CLAUDE_PLUGIN_ROOT/ejemplos/guion-voz.md\`).
No escribas el README del concepto: ese lo hace el revisor, uno solo para todas las variantes.`
}

function promptRevisar(concepto, variantes) {
  return `Revisa TODAS las variantes del concepto "${concepto.id}" (${concepto.titulo}) de reel-forge.
Las armaron ${AG_POR_CONCEPTO} agentes distintos, así que el error típico no está dentro de una
variante sino ENTRE ellas.

Variantes:
${variantes.map((v) => `- ${v.letra}: ${v.mp4} (${v.duracion_s} s, ${v.cortes} cortes, ${v.cortes_con_sujeto} con el sujeto)\n  spec: ${v.spec}`).join('\n')}

Qué revisar:
1. **Compara el MISMO cuadro entre variantes.** Un constructor dejó un \`look\` que lavaba el gancho en
   dos de cuatro entregas y nadie lo vio porque cada quien revisó solo lo suyo.
2. Que no repitan la misma toma con otro texto: si dos variantes se leen igual, una sobra.
3. Técnico, con comandos, sin creerle a nadie: \`blackdetect\`, \`silencedetect=n=-45dB:d=0.25\`,
   \`loudnorm=print_format=summary\` (pico bajo -0.5 dBTP), duración real del audio igual a la del video
   (\`ffprobe -select_streams a:0 -show_entries stream=duration\`), tira \`fps=2,tile=12x6\` de cada una.
4. Textos: legibles, dentro de la zona segura, sin tapar caras, sin palabra huérfana, datos correctos
   (fechas, lugares y precios verificados contra el catálogo o contra una fuente con fecha).
5. Los cortes con ${SUJETO}: cuéntalos tú, no confíes en lo que reportó el constructor.
6. Que cada \`build.py\` vuelva a generar su spec desde cero.

Escribe UN solo README.md para el concepto en ${ENTREGAS}/${concepto.id}/, con las variantes dentro,
qué cambia entre ellas, cuál recomiendas y el conteo de cortes. Nada de un README por agente.
Marca \`gravedad: "bloquea"\` solo en lo que impide entregar.`
}

function promptCorregir(concepto, problemas) {
  return `Arregla lo que bloquea la entrega del concepto "${concepto.id}" de reel-forge. No rediseñes:
corrige exactamente esto y vuelve a renderizar las variantes afectadas.

${problemas.map((p) => `- [${p.variante}] ${p.que}${p.donde ? ` (${p.donde})` : ''}\n  Arreglo propuesto por el revisor: ${p.como_arreglar}`).join('\n')}

Reglas:
- La corrección va DENTRO del \`build.py\` de la variante, no a mano sobre el MP4. Si un paso arregla
  algo que el motor hace mal, tiene que quedar encadenado en el script: un \`.sh\` suelto sin
  \`chmod +x\` ya dejó pasar un preview saturado sin que nadie se enterara.
- Vuelve a correr las comprobaciones y actualiza el README del concepto.
- Devuelve las variantes corregidas, con sus rutas y conteos nuevos.`
}

// ───────────────────────────────────────────────────────────── el run

log(`${conceptos.length} conceptos · ${AG_POR_CONCEPTO} constructores y ${REVISOR ? 1 : 0} revisor por concepto · entrega ${VERSION}`)

phase('Común')

// pipeline: cada concepto avanza por su cuenta. El concepto 1 puede estar en revisión mientras el 3
// sigue exportando originales; una barrera entre fases dejaría a los constructores rápidos esperando.
// Las barreras que sí hacen falta son locales a un concepto: los constructores de un concepto tienen
// que terminar antes de que su revisor pueda compararlos, y eso se resuelve con parallel() DENTRO
// de la etapa, no entre etapas.
const resultados = await pipeline(
  conceptos,

  // 1. Lo compartido, una vez por concepto.
  (_prev, concepto) => agent(promptComun(concepto), {
    label: `Común ${concepto.id}`, phase: 'Común', schema: COMUN,
  }),

  // 2. Los constructores, en paralelo entre ellos.
  async (comun, concepto) => {
    const equipos = repartoRoundRobin(variantesDe(concepto), AG_POR_CONCEPTO)
    const tandas = await parallel(equipos.map((mias, i) => () => agent(
      promptArmar(concepto, comun, mias, i),
      {
        label: `${concepto.id} ${mias.map((v) => v.letra).join('+')}`,
        phase: 'Armar',
        schema: { type: 'object', properties: { variantes: { type: 'array', items: VARIANTE } }, required: ['variantes'] },
      },
    )))
    const variantes = tandas.filter(Boolean).flatMap((t) => t.variantes)
    const caidos = equipos.filter((_, i) => !tandas[i]).flatMap((e) => e.map((v) => v.letra))
    if (caidos.length) log(`${concepto.id}: sin resultado las variantes ${caidos.join(', ')} — hay que repetirlas`)
    if (!variantes.length) throw new Error(`${concepto.id}: ninguna variante se armó`)
    return { comun, variantes, caidos }
  },

  // 3. Un revisor por concepto, con TODAS las variantes delante.
  async (armado, concepto) => {
    if (!REVISOR) return { ...armado, revision: null }
    const revision = await agent(promptRevisar(concepto, armado.variantes), {
      label: `Revisar ${concepto.id}`, phase: 'Revisar', schema: REVISION,
    })
    return { ...armado, revision }
  },

  // 4. Corrección, solo si algo bloquea. Un concepto limpio no paga esta etapa.
  async (revisado, concepto) => {
    const bloqueantes = ((revisado.revision && revisado.revision.problemas) || []).filter((p) => p.gravedad === 'bloquea')
    if (!ARREGLAR || !bloqueantes.length) {
      return { concepto: concepto.id, titulo: concepto.titulo, ...revisado, corregido: false }
    }
    log(`${concepto.id}: ${bloqueantes.length} problema(s) que bloquean, corrigiendo`)
    const arreglo = await agent(promptCorregir(concepto, bloqueantes), {
      label: `Corregir ${concepto.id}`, phase: 'Corregir',
      schema: { type: 'object', properties: { variantes: { type: 'array', items: VARIANTE }, que_cambio: { type: 'string' } }, required: ['variantes'] },
    })
    return {
      concepto: concepto.id, titulo: concepto.titulo, ...revisado,
      variantes: (arreglo && arreglo.variantes.length) ? arreglo.variantes : revisado.variantes,
      corregido: true, que_cambio: arreglo && arreglo.que_cambio,
    }
  },
)

const ok = resultados.filter(Boolean)
const fallidos = conceptos.filter((_, i) => !resultados[i]).map((c) => c.id)
if (fallidos.length) log(`Conceptos sin entrega: ${fallidos.join(', ')}`)

return {
  proyecto: PROYECTO,
  entregas: ENTREGAS,
  conceptos: ok,
  conceptos_fallidos: fallidos,
  total_variantes: ok.reduce((n, c) => n + c.variantes.length, 0),
}
