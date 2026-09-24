# De dónde sale el material

El objetivo de esta fase es una lista de archivos con: ruta, fecha y hora de captura, tipo, duración,
si está marcado como favorito, y una miniatura local para poder mirarlo sin bajar el original.

## Carpeta suelta (cualquier sistema) — el camino por defecto

Funciona siempre y es el que debes usar salvo que el usuario diga otra cosa.

```bash
uv run "$CLAUDE_PLUGIN_ROOT/skills/fuentes-material/scripts/inventario.py" ~/Pictures/viaje --salida taller/catalogo/inventario.json
```

Saca fecha de captura de los metadatos (EXIF `DateTimeOriginal`, y para video `creation_time` de
ffprobe). **La fecha del sistema de archivos miente**: copiar una carpeta la reescribe toda al mismo día.

Si no hay metadatos de fecha, usa el nombre del archivo como pista (`IMG_20240115_180230`,
`PXL_20240115_...`, `VID_...`) y **dilo**: un recap ordenado con fechas inventadas se nota.

## App Fotos de Apple — **solo macOS**

Da lo que una carpeta no da: favoritas, personas detectadas, ráfagas agrupadas y miniaturas locales
de material que vive en iCloud.

- Herramienta: [`osxphotos`](https://github.com/RhetTbull/osxphotos), se instala con `uv tool install osxphotos`.
- **Las miniaturas locales (`path_derivatives`) bastan para las hojas de contacto.** No bajes nada
  todavía: en una biblioteca grande son decenas de GB.
- Baja solo lo elegido, al final de la fase de conceptos:
  `osxphotos export <destino> --uuid-from-file elegidas.txt --download-missing --use-photokit`
- Campos que importan: `favorite`, `date`, `persons`, `burst`, `screenshot`, `ismissing`.
- **Nunca escribas en la biblioteca de Fotos.** Solo lectura y exportación a una carpeta aparte.
- Las caras y los identificadores internos son datos personales: úsalos en el taller y **no los
  copies a los README ni a los nombres de archivo de la entrega**.

Las ráfagas y las tomas vecinas se localizan por tiempo: para cada candidata, trae todo lo que esté a
±10 minutos. Ahí está la foto buena (regla 3 de selección).

## Otras bibliotecas

- **Google Photos:** no hay API buena para esto. Pídele al usuario que use Google Takeout y trate la
  carpeta resultante como una carpeta suelta; el JSON que viene al lado de cada archivo trae la fecha
  real y si estaba marcado como favorito.
- **Android / DCIM:** carpeta suelta. Los nombres `PXL_`/`VID_` ya traen fecha y hora.
- **Cámara 360 (Insta360 y similares):** ver `video360.md`. Los `.insv` se catalogan aparte, con un
  agente por clip.

## Criba barata (fase 3)

Antes de gastar agentes mirando imágenes, quita lo obvio con reglas, sin mirar:

- capturas de pantalla (bandera de la biblioteca, o relación de aspecto exacta de la pantalla)
- archivos de menos de ~150 KB o con lado menor a 640 px
- videos de menos de 1 s
- duplicados exactos (hash) y casi exactos (hash perceptual, distancia ≤ 4)
- fotos muy oscuras o quemadas (histograma: más del 70 % de los píxeles bajo 25 o sobre 230)
- fotos borrosas (varianza del laplaciano por debajo del percentil 10 del lote, **relativo al lote**:
  un umbral fijo tira tomas nocturnas que sí sirven)

Todo lo cribado va a una lista con su motivo, no a la basura. El usuario puede pedir algo de vuelta.

## Privacidad

- El material no sale de la máquina. Nada de subirlo a servicios externos para "analizarlo".
- Las rutas, los identificadores de biblioteca y los nombres de personas se quedan en `taller/`.
- Si detectas documentos, pantallas con trabajo, matrículas, direcciones o menores identificables,
  descártalo y dilo en una línea. No lo describas en detalle en el README.
