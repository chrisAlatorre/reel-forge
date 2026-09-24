---
name: video-360
description: Convierte material 360 (Insta360 X3/X4/X5 u otro equirectangular 2:1) en tomas verticales 9:16 con una cámara virtual por keyframes. Úsala cuando haya archivos .insv o videos 360, o cuando pidan tiny planet, whip-pan, reencuadre 360, seguimiento de una persona o estabilizar material esférico.
---

# Video 360 → 9:16

Un video 360 no se "recorta": se **reencuadra**. Una toma esférica de 20 segundos da tres o cuatro
planos distintos según a dónde apuntes la cámara virtual, y esa cámara puede moverse sola (paneos,
whip-pans, tiny planet que se desenrolla) sin que nadie haya movido la cámara real.

Motor: `${CLAUDE_PLUGIN_ROOT}/skills/video-360/scripts/reencuadre360.py`. Corre con `uv run` y no
necesita servicios externos: ffmpeg, OpenCV, Pillow, MediaPipe y `telemetry-parser`.

**Salida fija de 1080x1920.** Está en `W, H` arriba del script. Si tu motor de edición trabaja a más
resolución (por ejemplo 1350x2400 para dejar margen de reencuadre), el clip se re-escala al entrar y
pierde definición: para cortes cerrados usa además un proxy más ancho (abajo).

## Regla de oro

**Mira antes de escribir keys.** Nadie acierta un yaw de memoria. El ciclo siempre es:
hoja de contacto → localizar al sujeto en grados → escribir `keys.json` → render corto → mirar el
resultado. Saltarte la hoja cuesta más tiempo del que ahorra.

## Carpetas

Se configuran con variables de entorno; si no, usa los defaults:

| Variable | Default | Qué guarda |
|---|---|---|
| `REEL_FORGE_360` | `~/reel-forge/360` | originales, `proxys/` y `salidas/` |
| `REEL_FORGE_CACHE` | `~/.cache/reel-forge` | modelo de detección de personas (se baja solo) |
| `REEL_FORGE_FUENTE` | `$REEL_FORGE_CACHE/fonts/Montserrat[wght].ttf` | ttf para las etiquetas de las hojas; la baja `motor-video/scripts/tipografias.py` (opcional) |

## Flujo

```bash
S=${CLAUDE_PLUGIN_ROOT}/skills/video-360/scripts/reencuadre360.py

uv run $S proxy VID.insv                      # 1. equirect 3840x1920 a 30 fps
uv run $S hojas VID --n 6 --vistas anillo8 --personas   # 2. mira a dónde apuntar
$EDITOR keys.json                             # 3. escribe el movimiento de cámara
uv run $S render --keys keys.json             # 4. render 1080x1920
```

El proxy se crea solo la primera vez que cualquier comando toca ese archivo; no hace falta llamarlo
aparte salvo que quieras otro ancho o arreglar el stitch.

Atajos para no escribir keys a mano:

```bash
uv run $S planeta VID --dur 6 --giro 40 --a-normal 2    # tiny planet que se desenrolla
uv run $S seguir  VID --dur 10 --tipo selfie|tercera --objetivo=YAW,PITCH --render
uv run $S telemetria VID.insv                           # qué trae el giroscopio
```

`seguir` deja un `keys.json` con `ease: "spline"` ya suavizado: es un punto de partida editable, no
la entrega final.

## Hojas de contacto

`hojas` produce, por cada instante muestreado: el equirect completo con una rejilla de yaw/pitch
encima, y al lado 6 vistas (`--vistas cubo`: frente, derecha, atrás, izquierda, arriba, abajo) u 8
(`--vistas anillo8`: un anillo cada 45° con la vista un poco hacia abajo).

- `--n 6` instantes es suficiente para un clip de 20-30 s. Sube a 10-12 si la escena cambia mucho.
- `--personas` corre un detector y escribe sobre cada persona su `yaw,pitch`. Eso es lo que copias
  directo a las keys.
- `anillo8` es mejor para **encontrar** cosas (barre el horizonte completo); `cubo` para revisar
  cielo y nadir.

Cuesta ~10 s por hoja con detección de personas.

## Keys: la cámara virtual

`keys.json`:

```json
{
  "src": "~/reel-forge/360/VID.insv",
  "out": "~/reel-forge/360/salidas/toma-1.mp4",
  "inicio": 12.0, "dur": 12, "fps": 30, "velocidad": 1.0, "audio": true,
  "estab": "visual", "modo": "rumbo", "nivel": "auto", "desenfoque": 0.35,
  "keys": [
    {"t": 0,    "planeta": true, "yaw": 0},
    {"t": 2.5,  "planeta": true, "yaw": 60},
    {"t": 4.0,  "yaw": 90, "pitch": 0, "fov": 80, "ease": "suave"},
    {"t": 7.0,  "yaw": 130, "punch": 0.25},
    {"t": 7.35, "yaw": 300, "ease": "whip"},
    {"t": 10,   "yaw": 310, "fov": 70}
  ]
}
```

Todo en grados. Los campos que falten en una key **se heredan de la anterior**.

| Campo | Qué es |
|---|---|
| `yaw` | 0 = frente del equirect, + a la derecha, 180 = atrás |
| `pitch` | + mira arriba, −90 = nadir (mirando al suelo) |
| `roll` | + inclina en sentido horario |
| `fov` | campo de visión **horizontal** del cuadro de salida |
| `d` | proyección: 0 rectilínea, 1 estereográfica. Si no lo pones, se calcula del `fov` |
| `ease` | cómo se **llega** a esa key |
| `punch` | cierra el `fov` de golpe al llegar (0.2 = 20 %) |

**El yaw no se envuelve.** Para ir de 170 a −170 por el camino corto escribe **190**, no −170. Si no,
la cámara da la vuelta larga. Este es el error número uno.

`ease`: `lineal`, `suave`, `entrada`, `salida`, `whip`, `corte`, `spline`.

### Whip-pan

Dos keys separadas 0.3-0.4 s entre direcciones distintas, con `"ease": "whip"`. El motion blur se
calcula solo según la velocidad angular: `"desenfoque": 0.35` (default, ligero), 0.5 se nota más.

Es el efecto que mejor vende el 360: pareces tener dos cámaras. Pero **antes de aterrizar un whip,
comprueba qué hay en el destino en ese segundo exacto**, con un render fijo de 2 s a `fps: 6`
apuntando allí. Un sujeto que en el segundo 24.4 está partido por la costura, en el 24.95 ya salió
entero.

### Tiny planet

`{"planeta": true}` equivale a `pitch −90, fov 200, d 1`. Con `yaw` el planeta gira.

Si la key siguiente es una vista normal con `ease: "suave"`, el planeta **se desenrolla** en ~2 s.
Es el reveal clásico y funciona muy bien como apertura.

Ajustes que resuelven los problemas típicos:

- **El planeta corta la cabeza o el sombrero del sujeto:** sube el `fov` a 235. El planeta queda más
  chico y cabe completo.
- **Quien graba sale enorme y deformado en la orilla:** el nadir puro pone a quien sostiene la cámara
  en el borde del estereográfico, achatado. Usa `"planeta": true, "pitch": -60, "fov": 220` con el
  `yaw` en su dirección: sale chico y de pie sobre el planeta. Si la cámara va muy pegada,
  `pitch -45, fov 260`.
- **Si quien graba está a menos de 2-3 m del lente, no uses tiny planet en ese clip.** Rotarlo no
  ayuda: quien graba y el sujeto suelen estar a ~166° uno del otro, así que solo puedes salvar a uno,
  y el otro queda estirado por media pantalla. Cambia el planeta por un **empuje rectilíneo**
  (`yaw 296→346`, `pitch 12→−3`, `fov 124→70`): da la misma sensación de revelado sin deformar caras.
- **Aterriza en el sujeto de la escena, no en quien graba.** Quien sostiene la cámara está siempre a
  un brazo del lente: el fisheye le deforma la cara y casi siempre lo agarra a medio gesto. Saca una
  hoja `anillo8` de los instantes finales, localiza al sujeto real por yaw y manda ahí la última key.
- **Loop:** el planeta final tiene que usar la misma geometría y el mismo sentido de giro que el
  inicial.
- El texto del remate va **en el segundo en que aterriza** el desenrollado, no antes: si no, queda
  encima del planeta girando.

### Encuadre en contrapicado

Con la cámara a la altura de la rodilla o del pecho, la vista normal (`pitch +20..+30`) sale en
contrapicado: manos y rodillas enormes. Queda mejor un **medio planeta**:
`{"yaw": <sujeto>, "pitch": -12, "fov": 150}` → `{"pitch": -4, "fov": 138}`. El sujeto sale de cuerpo
entero, con el entorno alrededor, y la cara queda en el tercio de arriba.

## Estabilización y nivel

En el spec, no en las keys:

| Campo | Valores | Qué hace |
|---|---|---|
| `estab` | `no`, `visual`, `gyro`, `auto` | de dónde sale la orientación cuadro a cuadro |
| `modo` | `rumbo`, `bloqueo` | `rumbo` deja el horizonte fijo y el frente sigue hacia donde avanzas (tipo FlowState); `bloqueo` fija la dirección en el mundo |
| `nivel` | `auto`, `no`, `gyro`, `[pitch, roll]` | endereza el horizonte |

- **`visual`**: flujo óptico + RANSAC entre cuadros, detecta cortes de escena. Funciona con cualquier
  equirect, venga de donde venga. Es solo de rotación: no corrige rolling shutter ni paralaje, y
  deriva despacio en yaw (en modo `rumbo` no se nota).
- **`gyro`/`auto`**: solo con `.insv`, que trae la IMU. La rotación IMU→imagen **se autocalibra**
  contra la rotación visual (Kabsch + búsqueda de desfase de ±0.3 s), así que no depende de la matriz
  de fábrica, que cambia entre cámaras.
- **`nivel: "auto"`** usa el acelerómetro si hay giroscopio y, si no, el punto de fuga de las líneas
  verticales cada 2 s. Necesita verticales reales (postes, edificios, árboles). En paisaje abierto
  (mar, montaña) no las encuentra: lo avisa y deja esa toma sin nivelar. Ahí usa el gyro del `.insv`
  o pon los grados a mano con `"nivel": [pitch, roll]`.

El resultado se cachea junto al proxy (`.orient-*.npz`, `.nivel-*.npy`): se calcula una vez por clip.

## Seguir a una persona

```bash
uv run $S seguir VID --inicio 0 --dur 12 --tipo selfie --objetivo 90,-20 --hz 6 --render
```

Detecta personas con MediaPipe (`efficientdet_lite0`, se baja solo a la caché), muestrea a `--hz`,
suaviza el vector 3D con un filtro One-Euro y escribe keys `spline`.

- `--tipo selfie`: encuadre cerrado sobre la persona. `--tipo tercera`: plano más abierto, la persona
  descentrada.
- `--objetivo YAW,PITCH` le dice a quién seguir cuando hay varias personas. Sácalo de la hoja con
  `--personas`.
- Cerca del nadir (una persona sosteniendo la cámara en un bastón) su yaw cambia rapidísimo. El
  suavizado ayuda, pero si la persona rodea la cámara, la vista gira con ella. Ahí revisa las keys a
  mano.
- Cuesta ~2.3 s por segundo de clip con 10 vistas por muestra.

## El formato .insv

Un `.insv` de X3/X4/X5 **no es un video esférico**: es el material crudo de las dos lentes.

- **Dos pistas HEVC de 3840x3840**, una por lente, cada una con un círculo fisheye de ~193° (el disco
  útil guardado mide entre ~186° y ~194° según el modelo).
- En el X5, **pista 0 = lente trasera, pista 1 = frontal**.
- Audio AAC.
- Un **trailer** al final del archivo con la telemetría (giroscopio y acelerómetro) y la calibración
  de fábrica de esa cámara concreta.
- Los modelos viejos y los `.lrv` (proxy de baja resolución que la cámara graba al lado) pueden traer
  los dos círculos lado a lado en una sola pista.

El script lo pasa a equirect con ffmpeg:

```
[0:v:1]null[f];[0:v:0]null[b];[f][b]hstack=inputs=2:shortest=1,
v360=input=dfisheye:output=e:ih_fov=193:iv_fov=193:w=3840:h=1920:interp=cubic
```

O sea: las dos lentes lado a lado (**frente primero**) y `v360` en modo dual-fisheye.

Si el resultado sale al revés, girado o con la costura rara, ajusta el stitch y rehazlo:

```bash
uv run $S proxy VID.insv --orden 01 --rot-frente 90 --rot-atras 270 --fov 190 --forzar
```

La telemetría se lee con [telemetry-parser](https://github.com/AdrianEddy/telemetry-parser)
(`uv run $S telemetria VID.insv` imprime modelo, frecuencia y rangos).

### Cuándo NO usar este stitch

`v360` trata cada lente como un fisheye ideal y **no aplica la calibración de la cámara**: en objetos
cercanos a la costura (alguien pasando a un metro, un animal pegado al lente) la unión se nota, y a
veces parte al sujeto en dos.

Para una entrega final con material cercano a la costura, el mejor camino es:

1. Exportar el **360 plano (equirectangular)** desde **Insta360 Studio** (solo macOS y Windows), con
   FlowState y el horizonte ya aplicados.
2. Reencuadrar ese MP4 aquí con `"estab": "no"` y `"nivel": "no"` (ya vienen hechos).

El script acepta cualquier equirect 2:1, no solo `.insv`.

Alternativa sin Studio: [insv-stitch](https://github.com/BenjaminHenriksson/insv-stitch) (MIT), que
sí usa el modelo MEI con la calibración que viene en el archivo.

## Proxies y resolución

Todo el trabajo (hojas, estabilización, seguimiento, render) va sobre un proxy equirect a 30 fps,
porque correr `v360` sobre 8K cuadro por cuadro es lentísimo.

- Default: `--ancho 3840` (3840x1920). Con ese proxy, una ventana de `fov` 70° usa ~750 px de fuente,
  así que un 1080 de salida ya viene inflado.
- **Zoom fuerte (`fov` < ~50) se ve suave.** Para punch-ins cerrados: `proxy --ancho 5760`.
- **Cámara lenta:** el proxy es de 30 fps. Para `"velocidad": 0.5` con clips de 60 fps hay que crear
  el proxy a 60 (constante `FPS` en el script).
- El proxy se reusa mientras sea más nuevo que el original; `--forzar` lo rehace.

## Tiempos de referencia

Medidos en un MacBook Pro M3 Max. Son órdenes de magnitud, no promesas.

| Paso | Tiempo |
|---|---|
| Proxy de 8K a 3840 (20.8 s de video) | 9.9 s |
| Render 1080x1920 con planeta, pan y whip (12 s) | 6.5 s (~55 fps) |
| Estabilización visual (29 s, 873 pares) | 9 s, una vez por proxy y luego en caché |
| Nivel por líneas verticales (clip de 29 s) | 7-8 s |
| `seguir` a 6 Hz con 10 vistas por muestra | ~2.3 s por segundo de clip |
| Hoja de 3 instantes con detección de personas | ~10 s |

El proxy usa `-hwaccel videotoolbox`, que es **macOS**. En Linux o Windows funciona igual sin esa
bandera, solo más lento; quítala del comando si da error.

## Limitaciones que hay que decirle al usuario

- **La costura del stitch se ve** en objetos cercanos, alrededor de yaw ±90 con el stitch de `v360`.
  Para tomas donde eso importa, exporta desde Studio.
- **El bastón de selfie no se borra.** Studio lo quita; `v360` no. En tiny planet queda en el centro
  del planeta, donde se nota menos, pero está.
- **El nadir es el punto débil.** Justo debajo de la cámara está el bastón, la mano o el suelo
  pegado. Evita keys con `pitch` entre −70 y −85 salvo que sea un tiny planet a propósito.
- La estabilización visual es **solo rotación**: no arregla el temblor de caminar (traslación) ni el
  rolling shutter.
- El nivel automático **no funciona en paisaje abierto**: sin verticales, no hay referencia.
- La salida está fija en 1080x1920.

## Errores frecuentes, en orden

1. Escribir el yaw envuelto (−170 en vez de 190) y que la cámara dé la vuelta larga.
2. Aterrizar un whip o un desenrollado en quien sostiene la cámara.
3. Montar las keys sin haber mirado una hoja de contacto.
4. Punch-in cerrado con el proxy de 3840 (se ve suave).
5. Dejar un tiny planet en un clip donde quien graba va pegado al lente.
6. Poner el texto del remate antes de que aterrice el desenrollado.
