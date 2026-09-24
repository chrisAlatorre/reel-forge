# Material 360 a 9:16

Un clip equirectangular no es una toma: son muchas. De un solo archivo salen el gancho, el b-roll y el
cierre. Por eso va **un agente por clip**.

Motor: `scripts/reencuadre360.py` (cámara virtual con keyframes sobre el equirectangular). En el spec,
un segmento con `"r360": "keys.json"` se renderiza con ese motor y luego pasa por el look, los textos y
el audio del motor 2D.

## Flujo

1. **Proxy.** Convierte el archivo original a un equirectangular manejable (3840x1920 a 30 fps). Se
   hace solo la primera vez que corres cualquier comando sobre ese clip.
2. **Hojas.** `hojas VID --n 6 [--vistas anillo8] [--personas]`: el equirectangular nivelado, una
   rejilla de yaw/pitch y 6 u 8 vistas del anillo, con las personas marcadas con su `yaw,pitch`.
   **Míralas antes de escribir una sola key.**
3. **Keys.** Escribe `keys.json` y renderiza: `render --keys keys.json`.
4. **Atajos.** `planeta` (tiny planet que se desenrolla) y `seguir` (sigue a una persona y genera keys
   suavizadas que puedes editar a mano).

## Keys

- `yaw` 0 = al frente, + a la derecha. **No se envuelve:** para ir de 170 a -170 por el camino corto se
  escribe 190. `pitch` + hacia arriba. `fov` es horizontal.
- `ease` dice cómo se **llega** a esa key: suave, lineal, entrada, salida, whip, corte o spline.
  Los campos que faltan se heredan de la key anterior.
- Un `whip` de 0.3-0.4 s entre dos direcciones: el desenfoque de movimiento se calcula solo según la
  velocidad. Un cierre de `fov` de golpe al llegar remata bien.
- Estabilización: visual (flujo óptico) o por giroscopio si el archivo trae telemetría. Modo "rumbo"
  deja el horizonte fijo y el frente sigue hacia donde avanza; "bloqueo" fija la dirección en el mundo.
- El nivelado automático necesita verticales (postes, edificios, árboles). En paisaje abierto no las
  encuentra: lo avisa y deja esa toma sin nivelar.

## Lo que se aprendió a golpes

- **Tiny planet: NO si quien graba va pegado al lente.** Con la cámara a un metro de una cara, el
  estereográfico la deforma en cualquier orientación: arriba sale achatada, abajo estirada por media
  pantalla. Rotar el planeta no lo arregla, porque el sujeto que quieres arriba y quien graba están a
  ~166° y solo puedes elegir a uno. **Cámbialo por un empuje rectilíneo** (`fov` de ~124 a ~70, `pitch`
  de +12 a -3, yaw hacia el sujeto): misma sensación de revelado y ninguna cara deformada. El planeta
  se reserva para clips donde nadie esté a menos de 2-3 m del lente.
- **Aterriza en el sujeto de la escena, no en quien graba.** Quien lleva el palo está siempre a ~180° y
  a un metro: el ojo de pez le deforma la cara y casi siempre lo agarra a media palabra. Saca una hoja
  de anillo de los instantes finales, localiza al sujeto por yaw y manda ahí la última key.
- **Un tiny planet más abierto queda mejor:** con un `fov` de 200 el sujeto llena el borde; con 235 el
  planeta queda chico y no corta cabezas ni sombreros.
- **La costura del stitch parte lo que pase cerca de ±90° de yaw.** Antes de aterrizar un whip en una
  dirección, saca un render fijo de 2 s a 6 fps hacia allá y mira desde qué instante el sujeto ya salió
  de la costura. Cae ahí.
- **Dos reencuadres del mismo clip con yaw parecido se leen como la misma toma.** Separa al menos 90°
  de yaw o cambia de sujeto.
- **Si el concepto pide un encuadre que el render 360 no da**, no rehagas las keys: pre-renderiza ese
  pedazo con un zoom animado en ffmpeg (`zoompan`, no `crop` variable) y úsalo como clip normal.
- El texto del remate va **en el segundo en que aterriza** la cámara, no al principio del clip: si no,
  se queda encima del planeta girando.

## Cómo cataloga el agente 360

En vez de tramos de tiempo, tramos **de dirección**: por cada ventana de tiempo, qué hay en cada yaw.

```json
{
  "id": "v360-04",
  "ruta": "~/Videos/360/clip04.insv",
  "tipo": "video360",
  "duracion_s": 29.0,
  "ventanas": [
    {"inicio_s": 0.0, "fin_s": 2.0, "nota": "la única ventana limpia: mira al lente, nadie cruza"},
    {"inicio_s": 2.4, "fin_s": 6.5, "nota": "alguien pasa en primer plano y ocupa media pantalla"},
    {"inicio_s": 6.6, "fin_s": 29.0, "nota": "voltea y se queda de perfil, mirando fuera de cuadro"}
  ],
  "direcciones": [
    {"yaw": -180, "yaw_fin": -120, "que_es": "él y sus acompañantes", "sujeto": true},
    {"yaw": -30, "yaw_fin": 90, "que_es": "río y ribera, nadie en cuadro", "etiquetas": ["vacio", "agua"]},
    {"yaw": 126, "yaw_fin": 160, "que_es": "la proa bajando el río: el mejor b-roll, cero caras"}
  ],
  "pitch_obligatorio": 15,
  "nota": "con pitch más bajo, una rodilla ocupa el tercio inferior en todos los cuadros"
}
```

## Límites honestos

- **Formatos propietarios:** los archivos nativos de las cámaras 360 (por ejemplo `.insv`) son dos
  pistas de ojo de pez más telemetría. El unido que hace el motor trata cada lente como ojo de pez
  ideal, así que **la costura en objetos cercanos no queda como la del software del fabricante**. Para
  calidad final, exporta el 360 plano desde el software oficial (con su estabilización y su horizonte
  ya aplicados) y reencuádralo aquí con la estabilización apagada.
- El software del fabricante es **solo macOS/Windows** y hay que manejarlo a mano.
- La estabilización visual es solo de rotación (no corrige obturador rodante ni paralaje) y deriva
  lento en yaw; en modo "rumbo" no se nota.
- Con un proxy de 3840, una ventana de 70° usa ~750 px de fuente: para punch-ins fuertes genera el
  proxy más ancho.
- El palo o soporte **no se borra**: en tiny planet queda en el centro.
- La salida del motor 360 es 1080x1920 y el motor 2D trabaja a 1350x2400, así que todo clip 360 se
  re-escala un 25 % al entrar al spec. Se nota poco, pero en cortes cerrados conviene un proxy más ancho.
- Cámara lenta: el proxy es de 30 fps. Para medio velocidad con material de 60 fps, genera el proxy a 60.
