# El catálogo

Es el contrato entre los agentes de contexto y los constructores. Si cada agente inventa su formato,
la fase 7 se cae. Dale este archivo completo a cada agente de contexto.

Cada agente escribe **su propio** `taller/catalogo/catalogo-<lote>.json`. Tú los unes en
`taller/catalogo/catalogo.json` (concatenar `items`, verificar que no haya `id` repetido).

## Formato

```json
{
  "lote": "dia-03-ciudad",
  "agente": "contexto-3",
  "revisado": "2026-09-23",
  "items": [
    {
      "id": "d03-014",
      "ruta": "~/Pictures/viaje/IMG_0142.jpg",
      "tipo": "foto",
      "fecha": "2026-08-04T17:22:10",
      "lugar": "mercado central",
      "favorito": true,
      "sujeto": true,
      "usar": true,
      "que_es": "Él de frente comiendo en un puesto, luz de tarde lateral, humo detrás. Sonrisa natural, ojos abiertos.",
      "calidad": 4,
      "gancho": 3,
      "hoja": "taller/hojas/dia-03/hoja-01.jpg#14",
      "notas": "Ráfaga de 5; esta es la 3ª y la única sin parpadeo.",
      "etiquetas": ["comida", "gente", "calle"]
    },
    {
      "id": "d03-021",
      "ruta": "~/Pictures/viaje/VID_0155.mp4",
      "tipo": "video",
      "fecha": "2026-08-04T18:03:00",
      "duracion_s": 42.0,
      "fps": 60,
      "tramos": [
        {
          "inicio_s": 3.2, "fin_s": 7.4, "usar": true, "sujeto": false,
          "que_es": "Plano del wok, llamarada grande en 5.1 s. Cámara fija.",
          "calidad": 5, "gancho": 5,
          "audio": "chisporroteo fuerte y constante; sirve como sonido diegético",
          "etiquetas": ["comida", "fuego"]
        },
        {
          "inicio_s": 0.0, "fin_s": 3.2, "usar": false,
          "motivo": "cámara buscando encuadre, se ve el suelo"
        }
      ]
    },
    {
      "id": "d03-030",
      "ruta": "~/Pictures/viaje/IMG_0170.png",
      "tipo": "foto",
      "usar": false,
      "motivo": "captura de pantalla"
    }
  ]
}
```

## Campos

| Campo | Obligatorio | Qué es |
|---|---|---|
| `id` | sí | único en todo el proyecto. Prefijo del lote + número. |
| `ruta` | sí | relativa a `~` o a la raíz del proyecto. **Nunca una ruta absoluta con el nombre del usuario.** |
| `tipo` | sí | `foto`, `video`, `video360`, `live` |
| `fecha` | sí si existe | ISO 8601 de los metadatos, no del sistema de archivos |
| `usar` | sí | `false` + `motivo` para todo lo descartado. Nada se borra. |
| `sujeto` | sí | `true` si aparece la persona principal del video |
| `favorito` | si la biblioteca lo da | marcado como favorito |
| `que_es` | sí, si `usar` | **lo que viste**, en una o dos frases: qué hay, qué luz, qué expresión, qué se mueve |
| `calidad` | sí, si `usar` | 1-5 técnica: foco, exposición, encuadre, estabilidad |
| `gancho` | sí, si `usar` | 1-5 cuánto detiene el dedo. Un 5 es candidato a primer corte. |
| `tramos` | en videos | lista de ventanas; el archivo completo **no** se usa |
| `audio` | si aplica | qué se oye en ese tramo y si sirve |
| `hoja` | sí, si `usar` | de qué hoja de contacto salió y con qué número (así se audita) |
| `etiquetas` | sí, si `usar` | vocabulario de abajo |

## Vocabulario de etiquetas

Úsalo tal cual; los constructores filtran por estas palabras.

`paisaje` `ciudad` `arquitectura` `interior` `comida` `bebida` `gente` `amigos` `animales` `agua`
`noche` `atardecer` `transporte` `mercado` `naturaleza` `detalle` `movimiento` `vacio` `cielo`
`multitud` `religioso` `arte` `deporte` `clima`

`vacio` = no hay nadie en cuadro. Es la etiqueta más útil para cumplir la cuota del sujeto: marca
generosamente.

## Reglas para quien escribe el catálogo

- **Describe lo que viste, no lo que supones.** "Un templo" no sirve; "fachada dorada a contraluz, gente
  de espaldas en el tercio inferior" sí.
- `gancho` alto solo para algo que de verdad detiene: un animal cerca, fuego, una vista que se abre, una
  cara reaccionando. La mayoría del material es 2 o 3.
- Si no estás seguro de un archivo, `usar: false` con motivo `"por revisar"` y sigue. No adivines.
- Los tramos de un video no se traslapan y van ordenados por `inicio_s`.
- Si un tramo dura menos de 0.8 s, no sirve para un corte con texto o sello encima: no se alcanza a leer.

## Reglas para quien lee el catálogo

- **No puedes salirte de `inicio_s`/`fin_s`.** Si lo necesitas, saca una tira de esa zona, míralo y
  actualiza el catálogo con el tramo nuevo. Nunca en silencio.
- No uses un `id` que tenga `usar: false` sin decirlo en tus notas.
- Dos cortes con el mismo `id` en el mismo video: solo si están lejos en el montaje y se ven distintos.
