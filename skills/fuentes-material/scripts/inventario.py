# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "pillow-heif"]
# ///
"""Inventario de material para reel-forge.

Dado un rango de fechas y una o varias fuentes, saca un JSON con lo que hay:
conteos, rango real, lugares, GPS, caras, sesiones, sospechas de fecha, tamaño
estimado de descarga y si los originales están en disco.

No descarga, no exporta y no modifica nada. Es la foto del terreno antes de
decidir qué material se usa.

Ejemplos:

    # Todo lo de un viaje que está en la app Fotos de macOS
    uv run inventario.py --desde 2026-08-01 --hasta 2026-08-20

    # Una carpeta de tarjeta SD, sin tocar Fotos
    uv run inventario.py --fuente carpeta:~/Pictures/Viaje --desde 2026-08-01

    # Las dos fuentes juntas, resumen legible además del JSON
    uv run inventario.py --fuente fotos --fuente carpeta:~/Movies/360 \\
        --desde 2026-08-01 --hasta 2026-08-20 --resumen -o inventario.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fuentes  # noqa: E402

GB = 1024 ** 3
MB = 1024 ** 2


def parsear_fuente(texto):
    """'fotos' | 'fotos:/ruta/lib.photoslibrary' | 'carpeta:~/Pictures/Viaje'"""
    if ":" not in texto:
        clase, arg = texto, None
    else:
        clase, arg = texto.split(":", 1)
    clase = clase.lower()
    if clase in ("fotos", "apple-photos", "photos"):
        return ("apple-photos", arg)
    if clase in ("carpeta", "folder", "dir"):
        if not arg:
            raise ValueError("La fuente 'carpeta' necesita ruta: --fuente carpeta:~/Pictures/Viaje")
        return ("carpeta", arg)
    raise ValueError(f"Fuente desconocida '{texto}'. Usa 'fotos' o 'carpeta:RUTA'.")


def fuentes_por_default():
    """Sin --fuente: la app Fotos en macOS, más las carpetas de REEL_FORGE_FUENTES."""
    lista = ["fotos"] if sys.platform == "darwin" else []
    lista += [f"carpeta:{c}" for c in fuentes.fuentes_del_entorno()]
    if not lista:
        raise SystemExit(
            "No hay ninguna fuente. Fuera de macOS no existe la app Fotos:\n"
            "  --fuente carpeta:RUTA   o   export REEL_FORGE_FUENTES=/ruta/a/tu/material")
    return lista


def pct(parte, total):
    return round(100 * parte / total, 1) if total else 0.0


def construir(args):
    desde = fuentes.parsear_fecha(args.desde)
    hasta = fuentes.parsear_fecha(args.hasta, fin_de_dia=True)

    todos, metas, avisos = [], [], []
    for texto in args.fuente or fuentes_por_default():
        clase, arg = parsear_fuente(texto)
        try:
            if clase == "apple-photos":
                items, meta = fuentes.leer_apple_photos(
                    desde=desde, hasta=hasta, ruta_lib=arg, copiar=args.copiar_base,
                    incluir_ocultas=args.incluir_ocultas,
                    incluir_capturas=not args.sin_capturas,
                    solo_favoritas=args.solo_favoritas,
                    persona=args.persona,
                )
            else:
                items, meta = fuentes.leer_carpeta(
                    arg, desde=desde, hasta=hasta,
                    recursivo=not args.sin_recursion, usar_exiftool=args.exiftool)
            if meta.get("aviso_wal"):
                avisos.append(meta["aviso_wal"])
            meta["items"] = len(items)
            metas.append(meta)
            todos.extend(items)
        except fuentes.FototecaNoDisponible as e:
            metas.append({"tipo": clase, "error": str(e), "items": 0})
            avisos.append(f"Fuente '{texto}' no disponible: {e.args[0].splitlines()[0]}")
        except (FileNotFoundError, ValueError) as e:
            metas.append({"tipo": clase, "error": str(e), "items": 0})
            avisos.append(f"Fuente '{texto}': {e}")

    total = len(todos)
    fechas = sorted(f for f in (i["fecha"] for i in todos) if f)
    con_gps = [i for i in todos if i["lat"] is not None]
    con_caras = [i for i in todos if i["caras"]]
    videos = [i for i in todos if i["tipo"] in ("video", "360")]
    faltantes = [i for i in todos if i["local"] is False]

    # Tamaño: lo que ya sabemos por metadatos; para lo que no trae tamaño se usa
    # un promedio por tipo, marcado como estimación.
    bytes_conocidos = sum(i["bytes"] or 0 for i in faltantes)
    sin_tamano = [i for i in faltantes if not i["bytes"]]
    promedio = {"foto": 4 * MB, "video": 90 * MB, "360": 400 * MB}
    bytes_estimados = bytes_conocidos + sum(promedio.get(i["tipo"], 4 * MB) for i in sin_tamano)

    personas = {}
    for i in todos:
        for p in i["personas"]:
            personas[p] = personas.get(p, 0) + 1

    sesiones = fuentes.agrupar_sesiones(todos, hueco_min=args.hueco_min)
    sospechas = fuentes.detectar_sospechas(
        todos, anio_minimo=args.anio_minimo, dias_lejos=args.dias_lejos,
        hueco_min=args.hueco_min)

    salida = {
        "generado": datetime.now().astimezone().isoformat(timespec="seconds"),
        "rango_pedido": {"desde": args.desde, "hasta": args.hasta},
        "fuentes": metas,
        "conteos": {
            "total": total,
            "fotos": sum(1 for i in todos if i["tipo"] == "foto"),
            "videos": sum(1 for i in todos if i["tipo"] == "video"),
            "material_360": sum(1 for i in todos if i["tipo"] == "360"),
            "favoritas": sum(1 for i in todos if i["favorito"]),
            "capturas_pantalla": sum(1 for i in todos if i["captura_pantalla"]),
        },
        "rango_real": {
            "primera": fechas[0] if fechas else None,
            "ultima": fechas[-1] if fechas else None,
            "dias": _dias(fechas),
        },
        "gps": {
            "con_gps": len(con_gps),
            "pct": pct(len(con_gps), total),
            "sin_gps": total - len(con_gps),
        },
        "lugares": fuentes.resumen_lugares(todos)[:args.top_lugares],
        "caras": {
            "con_caras": len(con_caras),
            "pct": pct(len(con_caras), total),
            "personas": [{"nombre": n, "fotos": c}
                         for n, c in sorted(personas.items(), key=lambda kv: -kv[1])],
        },
        "video": {
            "clips": len(videos),
            "duracion_total_s": round(sum(i["duracion_s"] or 0 for i in videos), 1),
            "duracion_total_min": round(sum(i["duracion_s"] or 0 for i in videos) / 60, 1),
        },
        "sesiones": {
            "hueco_min": args.hueco_min,
            "total": len(sesiones),
            "lista": sesiones if args.sesiones_completas else [
                {k: v for k, v in s.items() if k != "ids"} for s in sesiones],
        },
        "sospechas_fecha": sospechas,
        "descarga": {
            "originales_locales": sum(1 for i in todos if i["local"]),
            "faltantes": len(faltantes),
            "bytes_estimados": bytes_estimados,
            "gb_estimados": round(bytes_estimados / GB, 2),
            "exactitud": ("exacta" if not sin_tamano else
                          f"aproximada ({len(sin_tamano)} sin tamaño en la base)"),
            "con_miniatura_local": sum(1 for i in todos if i["miniatura"]),
        },
        "avisos": avisos,
    }

    if args.incluir_items:
        salida["items"] = todos
    return salida, todos


def _dias(fechas):
    if not fechas:
        return 0
    a = datetime.fromisoformat(fechas[0])
    b = datetime.fromisoformat(fechas[-1])
    return (fuentes.sin_tz(b) - fuentes.sin_tz(a)).days + 1


def imprimir_resumen(d):
    c, r = d["conteos"], d["rango_real"]
    print(f"\n{c['total']} archivos entre {r['primera']} y {r['ultima']} ({r['dias']} días)")
    print(f"  {c['fotos']} fotos · {c['videos']} videos · {c['material_360']} en 360 · "
          f"{c['favoritas']} favoritas · {c['capturas_pantalla']} capturas de pantalla")
    print(f"  GPS: {d['gps']['pct']}%   ·   caras: {d['caras']['pct']}%   ·   "
          f"video: {d['video']['duracion_total_min']} min")
    if d["lugares"]:
        print("  Lugares: " + " · ".join(f"{l['lugar']} ({l['n']})" for l in d["lugares"][:6]))
    if d["caras"]["personas"]:
        print("  Personas: " + " · ".join(
            f"{p['nombre']} ({p['fotos']})" for p in d["caras"]["personas"][:6]))
    print(f"  Sesiones: {d['sesiones']['total']} (huecos de más de {d['sesiones']['hueco_min']} min)")
    dl = d["descarga"]
    print(f"  Descarga: {dl['faltantes']} originales en la nube ≈ {dl['gb_estimados']} GB "
          f"({dl['exactitud']}); {dl['con_miniatura_local']} ya tienen miniatura local")
    if d["sospechas_fecha"]:
        print("\n  Fechas que hay que confirmar:")
        for s in d["sospechas_fecha"]:
            print(f"    · {s['mensaje']}")
        print("  Corre validar_fechas.py para el reporte completo.")
    for aviso in d["avisos"]:
        print(f"  ! {aviso}")
    print()


def main():
    ap = argparse.ArgumentParser(
        description="Inventario de fotos y videos por rango de fechas y fuente.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--desde", help="AAAA-MM-DD (o con hora: AAAA-MM-DDTHH:MM)")
    ap.add_argument("--hasta", help="AAAA-MM-DD, inclusive")
    ap.add_argument("--fuente", action="append",
                    help="'fotos', 'fotos:/ruta/lib.photoslibrary' o 'carpeta:RUTA'. "
                         "Repetible. Default: fotos")
    ap.add_argument("-o", "--salida", help="Archivo JSON de salida (default: stdout)")
    ap.add_argument("--resumen", action="store_true", help="Además, un resumen legible")
    ap.add_argument("--incluir-items", action="store_true",
                    help="Mete la lista completa de archivos en el JSON (pesa)")
    ap.add_argument("--sesiones-completas", action="store_true",
                    help="Incluye los ids de cada sesión")
    ap.add_argument("--hueco-min", type=int, default=90,
                    help="Minutos de hueco que abren una sesión nueva (default: 90)")
    ap.add_argument("--top-lugares", type=int, default=20)
    ap.add_argument("--anio-minimo", type=int, default=2000,
                    help="Por debajo de este año la fecha se marca como imposible")
    ap.add_argument("--dias-lejos", type=int, default=180,
                    help="Días de distancia a la mediana para marcar un lote como sospechoso")

    g = ap.add_argument_group("Apple Photos")
    g.add_argument("--copiar-base", action="store_true",
                   help="Copia Photos.sqlite + WAL a temporal antes de leer (más lento, al día)")
    g.add_argument("--incluir-ocultas", action="store_true")
    g.add_argument("--sin-capturas", action="store_true", help="Excluye capturas de pantalla")
    g.add_argument("--solo-favoritas", action="store_true")
    g.add_argument("--persona", help="Solo assets donde Fotos reconoció a esta persona")

    g2 = ap.add_argument_group("Carpetas")
    g2.add_argument("--sin-recursion", action="store_true")
    g2.add_argument("--exiftool", action="store_true",
                    help="Usa exiftool como respaldo cuando no hay EXIF legible")

    args = ap.parse_args()
    datos, _ = construir(args)

    texto = json.dumps(datos, ensure_ascii=False, indent=2)
    if args.salida:
        Path(args.salida).expanduser().write_text(texto, encoding="utf-8")
        print(f"Escrito: {args.salida}", file=sys.stderr)
    else:
        print(texto)
    if args.resumen:
        imprimir_resumen(datos)


if __name__ == "__main__":
    main()
