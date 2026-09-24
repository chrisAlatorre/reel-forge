# Agentes: cuántos, qué les das y qué te devuelven

## Cuántos

| Fase | Agentes | Regla |
|---|---|---|
| Contexto, menos de 200 archivos | **3** | uno por día o por lugar |
| Contexto, 200-1000 | **6** (8 si hay más de 10 días) | uno por día, o por lote de ~150 archivos |
| Contexto, más de 1000 | **10** | criba barata primero; luego lotes de ~150 de lo que quedó |
| Material 360 | **1 por clip** | cada clip equirectangular es su propio trabajo |
| Tendencias | **1-3** | con búsqueda web, en paralelo a la fase de contexto: formatos / sonidos / nicho |
| Conceptos | **4-8 directores** | uno por ángulo, en paralelo; no se ven entre sí |
| Selección | **1 editor en jefe** | siempre uno: es el único que ve todas las propuestas juntas |
| Construcción | **2 por concepto** | dos variantes distintas del mismo concepto |
| Revisión | **1 por concepto** | distinto de los constructores; revisa las dos variantes juntas |

Tope práctico: **~10 agentes a la vez**. Con más, los renders empiezan a tardar minutos y no es culpa
del código. Si tienes 4 conceptos, lanza la construcción en dos oleadas de 4 agentes.

## Contrato general

Todo agente recibe, sin excepción:

1. La ruta de su lote o su concepto y **la lista exacta de archivos o ids** con los que trabaja.
2. Las reglas de selección (cópialas del SKILL, no lo mandes a leerlas).
3. El formato de salida exacto (el de `catalogo.md` para los agentes de contexto, el spec del motor para los constructores).
4. La ruta de **su** archivo de salida, distinta de la de los demás.
5. Qué no puede hacer: no renderiza nadie más, no toca `comun/`, no borra nada, no publica nada.

Y devuelve, en su mensaje final: la ruta de su archivo, cuántos elementos catalogó o cuántos cortes
armó, y **las tres cosas que más le llamaron la atención** (eso es lo que te sirve para los conceptos).

## Agente de contexto

Encargo:

> Cataloga los N archivos de la lista adjunta. Para cada uno: sácale miniatura o tira de cuadros,
> **míralo**, y escribe una entrada según el formato de `catalogo.md`. En videos, parte en TRAMOS con
> inicio y fin; el archivo completo nunca se usa. Aplica las reglas de descarte (marca `usar: false`
> con motivo, no borres nada). Para las tomas donde aparezca el sujeto, saca también recortes de cara y
> revisa la ráfaga completa antes de quedarte con una. Escribe `taller/catalogo/catalogo-<lote>.json`.
> No renderices ni edites nada.

Lo que sale mal si no lo dices:
- Cataloga por nombre de archivo sin abrir la imagen. → Exige el campo `hoja` con la referencia.
- Devuelve el video entero como un tramo. → Exige mínimo 2 tramos por video de más de 15 s, o un motivo.
- Inventa el formato. → Pásale el JSON de ejemplo completo.

## Agente 360

Uno por clip. Recibe la ruta del `.insv` o del equirectangular y devuelve un tramo catalogado **por
dirección**: yaw, pitch, fov y qué hay ahí. Ver `video360.md`. No renderiza el video final: deja
`keys.json` listos y una nota de qué hay en cada dirección.

## Agente de tendencias

Ver `tendencias.md`. Devuelve `taller/tendencias/tendencias.json` con formatos, sonidos con BPM
medido, ganchos y voces, **cada uno con fuente y fecha**. Si no encontró fuente, no lo pone.

## Directores creativos (4-8, en paralelo)

Cada uno recibe el catálogo unido, las tendencias y **un ángulo asignado por ti**. Devuelve
`conceptos/<slug>.json` con **un solo concepto**, no tres a medias.

> Propón UN concepto para un vertical de <plataforma>, desde este ángulo: **<ángulo>**. Usa solo ids
> que existan en el catálogo; inventar un recurso invalida tu concepto entero. Entrega: gancho del
> primer segundo, estructura segundo a segundo con los ids de cada corte, duración objetivo, si corta
> al beat o al sonido real, si lleva narración, la proporción de cortes con y sin el sujeto, y 3-4
> variantes del mismo concepto. Escribe `conceptos/<slug>.json`.

Ángulos que se reparten bien (uno por director, nunca repetido): documental narrado · puro sonido
real · guía con precios · gag visual · POV · lista con remate · contador de bloques · una sola toma
larga · antes y después.

**La variedad sale de los ángulos que repartas, no de pedirles "algo distinto".** Ocho directores sin
ángulo asignado devuelven ocho photo dumps.

## Editor en jefe (1, siempre uno)

Lee **todos** los conceptos y el catálogo, y decide qué se construye.

> Lee todos los `conceptos/*.json` y el catálogo. Elige los 3 que más se diferencien entre sí y que
> de verdad se puedan construir con el material que hay. Descarta los repetidos y los débiles, y di
> por qué. Por cada elegido, escribe los **ajustes obligatorios** antes de construirlo. Marca como
> defecto grave cualquier concepto que use un id que no está en el catálogo. Escribe `seleccion.json`.

Dos editores en jefe se contradicen y se pierde justo lo que este paso aporta. Su selección la
confirmas tú en una línea antes de que empiece el render.

## Agentes constructores (2 por concepto)

Cada uno recibe: el concepto completo (gancho, estructura, duración, tono), el catálogo unido, la
carpeta `comun/` ya preparada y **su letra** (A o B) con la variante que le toca.

> Arma la variante <A|B> del concepto "<nombre>". Usa solo ids del catálogo y **respeta las ventanas
> `inicio_s`/`fin_s`**. Escribe `conceptos/<concepto>/<letra>/build.py` que genere el spec y renderice:
> el `build.py` tiene que reconstruirlo todo desde cero, sin depender de temporales. Cuenta los cortes
> donde sale el sujeto y ponlo en tus notas. No toques `comun/` ni la carpeta del otro constructor.

Cómo se reparten las variantes (elige dos que se lean distinto):
- muda con sonido diegético / narrada
- larga (30-40 s) / corta (15 s)
- foto dump al beat / pocas tomas largas
- una de b-roll puro / una con el sujeto como personaje

Lo común (recortes a 9:16, cama de música con loop, copias ligeras) va en `comun/` y lo haces tú o un
solo agente. Cuando cada constructor lo hizo por su cuenta, uno usó el preview crudo de 30 s y los
últimos segundos de su video de 35 s salieron mudos sin que nada avisara.

## Agente revisor (1 por concepto)

No construyó ninguna de las dos variantes. Recibe las dos, el concepto y el checklist de `entrega.md`.

> Revisa las dos variantes del concepto "<nombre>". Saca una tira `fps=2,tile=12x6` de cada una y
> míralas. Corre las verificaciones técnicas del checklist. **Compara el mismo cuadro entre las dos
> variantes**: si el gancho se ve distinto, di cuál está mal. Cuenta a mano los cortes con el sujeto.
> Devuelve una lista de correcciones concretas, cada una con el segundo exacto y marcando cuáles
> **bloquean** la entrega. Lo que bloquea lo arreglas tú: la corrección va dentro del `build.py` de la
> variante y vuelves a renderizar. En `workflows/construir.js` eso es la etapa **Corregir**, que solo
> se paga si hay algo marcado como `bloquea`.

Lo que el revisor ha encontrado en producción y por eso existe:
- un `look` que lavaba el gancho en 2 de 4 entregas, porque nadie comparó entre variantes
- textos con `\n` a mano que al bajar el tamaño soltaban una palabra huérfana
- un sello de 0.39 s en pantalla, ilegible
- un script de post-proceso sin permiso de ejecución, que nadie llamaba, y el audio salía saturado
- dos cortes del mismo clip a 4° de diferencia, que se leían como error de montaje

## Higiene

- **Un agente, un archivo de salida.** Dos agentes escribiendo el mismo archivo se pisan en silencio.
- Nadie borra material original. Nadie publica. Nadie gasta dinero.
- Si un agente falla a medias, su archivo de salida no debe existir: esa es la señal de "rehacer este
  lote". Que escriba el JSON **al final**, no incrementalmente.
- Lee los resultados antes de pasar a la siguiente fase. Un catálogo malo se multiplica por 4 conceptos.
