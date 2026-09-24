# Investigar tendencias

Sin esto sale un recap genérico: fotos en orden, un título centrado y música libre de derechos. Ese
video ya se hizo y el veredicto fue *"muy genérico"*.

**Nunca inventes una canción, un formato o un sonido "en tendencia".** Todo lleva fuente y fecha.
Las tendencias caducan en semanas: un dato de hace tres meses ya no sirve, y uno del entrenamiento
del modelo menos.

Lánzalo como **un agente con búsqueda web**, en paralelo a la fase de contexto. Devuelve
`taller/tendencias/tendencias.json`.

## Qué tiene que traer

```json
{
  "fecha": "2026-09-23",
  "plataforma": "tiktok",
  "region": "MX",
  "formatos": [
    {"nombre": "storytime narrado", "duracion_s": [21, 40], "por_que": "...", "fuente": "url", "visto": "2026-09-22"}
  ],
  "sonidos": [
    {"titulo": "...", "artista": "...", "bpm": 123.0, "medido_con": "librosa sobre preview de 30 s", "fuente": "url"}
  ],
  "ganchos": ["frases de primer segundo que se repiten, con ejemplo"],
  "voces": [{"nombre": "...", "como_se_consigue": "...", "licencia": "..."}],
  "evitar": ["cosas que ya se leen como viejas"]
}
```

## Cómo se busca

- Ve 10-15 videos reales del nicho (viaje, comida, evento) publicados **en las últimas semanas** y
  anota lo que se repite: duración, dónde va el texto, cuándo entra el primer corte, si hay voz.
- Fíjate en lo concreto: "texto de gancho chico y fijo arriba en 6 de 15", "ráfaga de cortes de
  0.2-0.4 s antes del final", "etiqueta de día y ciudad con pin". Eso es accionable.
- Notas de campo: un reproductor de video no carga si la ventana del navegador está oculta, y sacar
  muchos videos seguidos del mismo sitio suele terminar en bloqueo temporal. Ve despacio y guarda lo
  que encuentres conforme lo encuentras.

## BPM: medirlo, no buscarlo

Los BPM que aparecen escritos por ahí están mal la mitad de las veces (doble o mitad). Mídelo:

1. Baja el preview público de 30 s del catálogo de la tienda de música
   (`https://itunes.apple.com/search?term=<canción>&entity=song&country=<pais>` → campo `previewUrl`).
   Es público, sin llave, y es un preview: **no se incrusta en nada que se publique**.
2. `librosa.beat.beat_track` sobre el preview, y **confirma contando**: si da 70 y suena rápido, es 140.
3. Guarda el BPM medido y con qué lo mediste.

Con el BPM sale la rejilla de cortes: a 120 BPM un beat son 0.5 s, cortes cada 2 beats = 1.0 s.
Rangos que funcionan: 85-95 para algo ceremonial o de "documental", 120-140 para un photo dump,
150-165 para ráfaga rápida.

## Música y derechos

- **No incrustes música con copyright en la versión que se va a subir.** El render saca dos archivos:
  `x.mp4` limpio (sin canción) y `x-preview.mp4` con la canción **solo para que el usuario la vea**.
  En la app se agrega el sonido oficial, que además hace que el video cuente para esa tendencia.
- El preview de la tienda dura **30 s**. En un video de 34 s la música simplemente se acaba y nadie
  avisa. Para más de ~29 s arma una cama con loop: `acrossfade=d=1.5` entre el preview y una copia
  desplazada, `atrim` al largo exacto y normaliza (`loudnorm I=-22`, que es cama bajo el audio real).
  Verifica con `ffprobe -select_streams a:0 -show_entries stream=duration`: tiene que dar exactamente
  el largo del video.
- Música libre de derechos solo como último recurso: exige crédito y se siente genérica.
- **La cama la hace el armador común, no cada constructor.**

## Estilo que funciona (y lo que ya no)

Esto viene de producción, no de la búsqueda; úsalo como base y deja que el agente lo actualice.

**Funciona**
- Gancho en el primer segundo: la toma más fuerte primero. La mayoría de la gente se va antes de 3 s.
- Un mini gancho cada 3-5 s: algo que cambie (un corte duro, un texto, un sonido, una revelación).
- Cortes secos al beat con **punch-in** (un zoom que se asienta en ~0.2 s).
- Cámara lenta real de clips grabados a 60 fps (velocidad 0.5), no interpolada.
- Flash blanco de 2-3 cuadros, y solo en el momento fuerte.
- Textos: pocos, cortos, bien centrados, fuera de las zonas de interfaz.
- Duración: 21-40 s retiene mejor que 60. Una toma bonita sola, 8-11 s, también funciona.
- 3 a 5 etiquetas, incluida una de nicho en el idioma del usuario.

**Ya no**
- Fundidos cruzados, barridos, estrellas: "transicioncitas de editor de hace 15 años".
- Glitch RGB, el mismo whoosh en cada corte, subtítulos de neón con emojis, contorno grueso estilo
  "cada palabra en amarillo".
- Más de dos efectos en un mismo corte.
- Un título centrado sobre la primera foto y ya.
