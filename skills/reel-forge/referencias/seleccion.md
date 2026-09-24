# Selección de material

Las siete reglas están en el SKILL. Aquí va **cómo se cumplen**, que es donde se falla.

## Ver de verdad el material

### Hojas de contacto (fotos)

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/fuentes-material/scripts/hojas.py" contacto lista.json --cols 6 --salida taller/hojas/dia-03
```

- Miniaturas **numeradas**, 24 a 36 por hoja. Más de eso y no distingues una mueca.
- Ábrelas con la herramienta de lectura de imágenes y **descríbelas una por una**. Un agente que
  devuelve un catálogo sin haber leído ninguna imagen se nota: describe por nombre de archivo.
- La numeración de la hoja tiene que mapear a un identificador estable en el catálogo. Si el agente
  dice "la 14", tiene que haber una 14.

### Recortes de cara (expresiones)

El paso que más videos ha salvado. En una miniatura de 180 px no ves que alguien está a media palabra.

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/fuentes-material/scripts/hojas.py" caras lista.json --salida taller/hojas/caras-dia-03
```

- Detecta caras y hace una hoja solo con los recortes, al mismo número de la hoja de contacto.
- En macOS, si el material viene de la app Fotos, las caras ya están detectadas en la biblioteca y sale
  más rápido y más fiable usar esas cajas.
- Qué buscas: ojos abiertos, boca cerrada o sonriendo de verdad, mirada a algún lado coherente. Qué
  descartas: volteando, parpadeo, boca a media palabra, mano acomodándose el pelo o la ropa.

### Ráfagas y vecinas

Para cada candidata donde salga el sujeto, trae **todas** las tomas a ±10 min y míralas juntas.
La foto buena casi nunca es la primera de la secuencia: suele estar dos o tres después.

### Tiras de cuadros (video)

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/fuentes-material/scripts/hojas.py" tira clip.mp4 --fps 1 --cols 8 --salida taller/hojas/
```

o directo:

```bash
ffmpeg -i clip.mp4 -vf "fps=1,scale=216:384,tile=8x4" -frames:v 1 tira.jpg
```

- 1 cuadro por segundo para catalogar, 4 fps para encontrar el instante exacto de un corte.
- Un clip de más de 2 minutos: primero 1 cuadro cada 3 s para ubicar las zonas, luego a 1 fps solo ahí.
- Si el clip tiene audio que importa (gritos, una frase, agua, risas), saca también un perfil de
  volumen o transcríbelo — ver `audio.md`.

## Catalogar tramos, no archivos

Un video de 40 s trae 3-6 s buenos. El catálogo guarda ventanas con `inicio_s` y `fin_s` y una
descripción de lo que pasa en esa ventana exacta. Formato en `catalogo.md`.

**La ventana manda.** Dos constructores tomaron un clip fuera de su ventana catalogada (catálogo 0-4 s;
uno usó 4.0-5.7, otro 7.2-8.4) y en vez del sujeto salieron caras de desconocidas pegadas al lente.
Si necesitas salirte de la ventana, saca una tira de esa zona y mira qué hay antes de usarla.

Cómo partir un clip en tramos:
1. Tira a 1 fps de todo el clip.
2. Marca los cambios: cambio de encuadre, de sujeto, de luz, la cámara que se estabiliza, el momento
   en que pasa algo.
3. Un tramo por cada cosa que pasa, con margen de ~0.3 s por dentro en cada extremo.
4. Descarta el relleno (cámara buscando, manos, suelo, pantalla negra) explícitamente: catalógalo como
   tramo `usar: false` con motivo, para que nadie lo redescubra.

## Descartes por defecto

Refutables: si el usuario dice que quiere el ticket porque el precio es el chiste del video, va.

| Qué | Por qué |
|---|---|
| tickets, recibos, boletos, comprobantes | datos personales y no aportan imagen |
| capturas de pantalla, documentos, pantallas con trabajo o código | filtran información y rompen el tono |
| borrosas, subexpuestas, quemadas | no se leen en un teléfono |
| duplicados casi idénticos | dos cortes casi iguales se leen como error de montaje |
| menores identificables como protagonistas | no se publica a un menor sin permiso explícito |
| matrículas, direcciones, tarjetas, pantallas de banca | sensible |

En el catálogo: `"usar": false, "motivo": "captura de pantalla"`. Nada se borra.

## Cuota del sujeto

- Default: **el sujeto en la mitad de los cortes o menos**. En producción lo que gustó fue 14-35 %.
- El resto: paisaje, arquitectura, comida, gente (local, amigos, el grupo), animales y tomas sin nadie.
- El sujeto con amigos cuenta como sujeto. Tomas solo de otras personas: sí, con moderación, y
  solo si aportan (una escena, no un retrato de alguien más).
- **Cuenta los cortes a mano al final** y escribe el número en el README: "21 cortes, el sujeto en 3 (14 %)".

## Cuando el sujeto sale

- Solo favoritas de la biblioteca (macOS: `favorite`; en carpeta suelta, pregunta o usa la lista que él dé).
- Si no hay suficientes favoritas: amplía a las vecinas por tiempo, no a cualquier cosa.
- Cara visible, luz decente, pose natural. Nada de poses dirigidas por un fotógrafo.
- En clips, el sujeto en primer plano sale mejor en foto que en video: el video úsalo para acción y paisaje.
- El plugin **no retoca personas**. Lo único que se aplica es el `look` del render, parejo para toda la variante. Ver `edicion.md`.

## Verificar lo que vas a poner en pantalla

- Toda fecha y todo lugar que aparezca en un texto se verifica contra los metadatos del archivo.
- **Ojo con las zonas horarias:** el nombre del archivo exportado suele traer la hora del lugar donde se
  tomó, y la base de datos de la biblioteca la de casa. Con 12-14 h de diferencia se cuela un día entero.
  Manda la fecha de captura de los metadatos, no el nombre.
- Precios, horarios, nombres oficiales: investígalos con fuente y fecha. No preguntes al usuario cosas
  que él no va a recordar, y no las inventes.
