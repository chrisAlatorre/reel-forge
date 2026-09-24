# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "pillow-heif"]
# ///
"""Reporte de metadatos para que el usuario confirme antes de editar.

Detecta fotos sin fecha, con fecha imposible, lotes corridos y desfases de
zona horaria; y escribe un plan de correcciones en JSON.

**Nunca modifica archivos ni la biblioteca de Fotos.** Las correcciones viven
en un archivo aparte (`correcciones.json`) que el resto de reel-forge lee para
ordenar el material. Si de plano quieres reescribir el EXIF de archivos en una
carpeta, existe `--aplicar-exiftool`, que pide confirmación y solo toca copias
de una carpeta normal, jamás la app Fotos.

Ejemplos:

    # Reporte en pantalla + plan editable
    uv run validar_fechas.py --desde 2026-08-01 --hasta 2026-08-20 \\
        --plan correcciones.json

    # Aceptar las propuestas automáticas de un caso concreto
    uv run validar_fechas.py --plan correcciones.json --aceptar lote_lejano

    # Poner a mano la fecha de un grupo sin fecha
    uv run validar_fechas.py --plan correcciones.json \\
        --caso sin_fecha --fecha 2026-08-14T09:00

    # Corregir el reloj de una cámara: mover todo lo de una carpeta +7 h
    uv run validar_fechas.py --fuente carpeta:~/Pictures/Insta360 \\
        --plan correcciones.json --caso todos --offset-horas 7
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fuentes  # noqa: E402
import inventario  # noqa: E402


# ---------------------------------------------------------------------------
# Reporte
# ---------------------------------------------------------------------------

TITULOS = {
    "sin_fecha": "Sin fecha de captura",
    "fecha_imposible": "Fecha imposible",
    "lote_lejano": "Lote con fecha lejana al resto",
    "solo_mtime": "Fecha tomada del sistema de archivos",
    "desfase_horario": "Desfase de zona horaria",
}

QUE_HACER = {
    "sin_fecha": (
        "Sin fecha no se pueden ordenar ni agrupar en sesiones. Decide una fecha\n"
        "  aproximada (sirve el día del viaje) o déjalos fuera del proyecto."),
    "fecha_imposible": (
        "Casi siempre es una cámara externa que perdió la hora. Si el resto del\n"
        "  lote está bien, lo correcto es mover ese grupo al día real."),
    "lote_lejano": (
        "Entre ellos son coherentes, así que un offset parejo los acomoda. Revisa\n"
        "  que el orden dentro del grupo tenga sentido antes de aceptar."),
    "solo_mtime": (
        "La fecha de modificación se reescribe al copiar archivos. Si el material\n"
        "  pasó por una tarjeta SD o un disco externo, probablemente está mal."),
    "desfase_horario": (
        "Dos cámaras del mismo día con horas corridas. Si vas a intercalar sus\n"
        "  tomas en un mismo video, hay que emparejarlas o el montaje sale revuelto."),
}


def reporte_texto(casos, resumen, plan=None):
    lineas = []
    c, r = resumen["conteos"], resumen["rango_real"]
    lineas.append("REPORTE DE METADATOS")
    lineas.append("=" * 60)
    lineas.append(f"{c['total']} archivos · {r['primera']} → {r['ultima']} ({r['dias']} días)")
    lineas.append(f"GPS {resumen['gps']['pct']}% · caras {resumen['caras']['pct']}% · "
                  f"{resumen['sesiones']['total']} sesiones")
    if resumen["lugares"]:
        lineas.append("Lugares: " + " · ".join(
            f"{l['lugar']} ({l['n']})" for l in resumen["lugares"][:8]))
    lineas.append("")

    if not casos:
        lineas.append("Sin problemas de fecha. El material se puede ordenar tal cual.")
        return "\n".join(lineas)

    plural = "cosa que hay" if len(casos) == 1 else "cosas que hay"
    lineas.append(f"{len(casos)} {plural} que confirmar:")
    lineas.append("")
    ya_cubiertos = set()
    for c in (plan or {}).get("correcciones", []):
        ya_cubiertos.update(c["ids"])

    for n, caso in enumerate(casos, 1):
        resuelto = " [ya confirmado en el plan]" if set(caso["ids"]) <= ya_cubiertos else ""
        cuantos = "1 archivo" if caso["n"] == 1 else f"{caso['n']} archivos"
        lineas.append(f"[{n}] {TITULOS.get(caso['caso'], caso['caso'])}  ({cuantos}){resuelto}")
        lineas.append(f"  {caso['mensaje']}")
        for ej in caso["ejemplos"]:
            lineas.append(f"    - {ej}")
        if caso["n"] > len(caso["ejemplos"]):
            lineas.append(f"    … y {caso['n'] - len(caso['ejemplos'])} más")
        p = caso.get("propuesta") or {}
        if p.get("equivalente"):
            lineas.append(f"  Propuesta: {p['equivalente']}")
        elif p.get("accion") == "asignar_fecha":
            lineas.append("  Propuesta: asignarles una fecha a mano (no se puede adivinar)")
        lineas.append(f"  Qué significa: {QUE_HACER.get(caso['caso'], '')}")
        if not resuelto:
            lineas.append(f"  Aceptar: --caso {caso['caso']} --aceptar")
        lineas.append("")

    lineas.append("Nada se modifica hasta que confirmes. Las correcciones quedan en el")
    lineas.append("plan JSON; los archivos originales y la app Fotos no se tocan.")
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Plan de correcciones
# ---------------------------------------------------------------------------


def cargar_plan(ruta):
    p = Path(ruta).expanduser()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"version": 1, "creado": datetime.now().astimezone().isoformat(timespec="seconds"),
            "correcciones": []}


def guardar_plan(plan, ruta):
    p = Path(ruta).expanduser()
    plan["actualizado"] = datetime.now().astimezone().isoformat(timespec="seconds")
    p.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def agregar_correccion(plan, ids, accion, valor, nota):
    plan["correcciones"] = [c for c in plan["correcciones"]
                            if not set(c["ids"]) & set(ids)]
    plan["correcciones"].append({
        "ids": ids, "accion": accion, "valor": valor, "nota": nota,
        "confirmado": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    return plan


def aplicar_plan(items, plan):
    """Devuelve los items con la fecha ya corregida, sin tocar nada en disco."""
    por_id = {i["id"]: i for i in items}
    for c in plan.get("correcciones", []):
        for id_ in c["ids"]:
            it = por_id.get(id_)
            if not it:
                continue
            nueva = _nueva_fecha(it, c["accion"], c["valor"])
            if nueva:
                it["fecha_original"] = it["fecha"]
                it["fecha"] = fuentes.iso(nueva)
                it["origen_fecha"] = "corregida"
    return items


def _nueva_fecha(item, accion, valor):
    actual = None
    if item.get("fecha"):
        try:
            actual = datetime.fromisoformat(item["fecha"])
        except ValueError:
            actual = None
    if accion == "asignar_fecha":
        return datetime.fromisoformat(valor) if valor else None
    if accion == "offset_horas" and actual:
        return actual + timedelta(hours=float(valor))
    if accion == "offset_dias" and actual:
        return actual + timedelta(days=float(valor))
    if accion == "offset_minutos" and actual:
        return actual + timedelta(minutes=float(valor))
    return None


# ---------------------------------------------------------------------------
# Escritura opcional de EXIF (solo carpetas)
# ---------------------------------------------------------------------------


def aplicar_exiftool(items, plan, confirmar):
    """Reescribe DateTimeOriginal con exiftool. Solo items de fuente 'carpeta'.

    exiftool deja un `_original` de respaldo junto a cada archivo, así que se
    puede deshacer. Los items de Apple Photos se saltan siempre: para cambiar
    una fecha ahí, el usuario lo hace en la app (Imagen → Ajustar fecha y hora).
    """
    import shutil
    import subprocess

    if not shutil.which("exiftool"):
        return {"ok": False, "razon": "exiftool no está instalado (brew install exiftool)"}

    aplicar = aplicar_plan([dict(i) for i in items], plan)
    objetivos = [i for i in aplicar
                 if i.get("origen_fecha") == "corregida" and i["fuente"] == "carpeta" and i["ruta"]]
    saltados = [i for i in aplicar
                if i.get("origen_fecha") == "corregida" and i["fuente"] != "carpeta"]

    if not objetivos:
        return {"ok": False, "razon": "No hay archivos de carpeta con corrección pendiente",
                "saltados_apple_photos": len(saltados)}
    if not confirmar:
        return {"ok": False, "razon": f"Faltó --si: reescribiría {len(objetivos)} archivos",
                "archivos": [i["ruta"] for i in objetivos[:10]],
                "saltados_apple_photos": len(saltados)}

    hechos, errores = 0, []
    for it in objetivos:
        fecha = datetime.fromisoformat(it["fecha"]).strftime("%Y:%m:%d %H:%M:%S")
        cmd = ["exiftool", f"-DateTimeOriginal={fecha}", f"-CreateDate={fecha}", it["ruta"]]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            hechos += 1
        else:
            errores.append({"ruta": it["ruta"], "error": r.stderr.strip()[:200]})
    return {"ok": True, "reescritos": hechos, "errores": errores,
            "saltados_apple_photos": len(saltados),
            "respaldo": "exiftool dejó un archivo _original junto a cada uno"}


# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Valida fechas y arma un plan de correcciones que el usuario confirma.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--desde")
    ap.add_argument("--hasta")
    ap.add_argument("--fuente", action="append")
    ap.add_argument("--plan", default="correcciones.json",
                    help="Archivo del plan (se crea o se actualiza)")
    ap.add_argument("--json", action="store_true", help="Salida en JSON en vez de texto")

    g = ap.add_argument_group("Confirmar una corrección")
    g.add_argument("--caso", help="Nombre del caso a corregir, o 'todos'")
    g.add_argument("--aceptar", action="store_true", help="Acepta la propuesta automática del caso")
    g.add_argument("--fecha", help="Asigna esta fecha a todo el caso (AAAA-MM-DDTHH:MM)")
    g.add_argument("--offset-horas", type=float)
    g.add_argument("--offset-dias", type=float)
    g.add_argument("--offset-minutos", type=float)
    g.add_argument("--descartar", action="store_true",
                   help="Marca el caso como revisado sin corregir nada")

    g2 = ap.add_argument_group("Escribir EXIF (solo carpetas, opcional)")
    g2.add_argument("--aplicar-exiftool", action="store_true")
    g2.add_argument("--si", action="store_true", help="Confirma la escritura con exiftool")

    # Opciones que inventario.py también entiende, para que las fuentes se lean igual.
    ap.add_argument("--copiar-base", action="store_true")
    ap.add_argument("--incluir-ocultas", action="store_true")
    ap.add_argument("--sin-capturas", action="store_true")
    ap.add_argument("--solo-favoritas", action="store_true")
    ap.add_argument("--persona")
    ap.add_argument("--sin-recursion", action="store_true")
    ap.add_argument("--exiftool", action="store_true")
    ap.add_argument("--hueco-min", type=int, default=90)
    ap.add_argument("--anio-minimo", type=int, default=2000)
    ap.add_argument("--dias-lejos", type=int, default=180)
    ap.add_argument("--top-lugares", type=int, default=20)
    ap.add_argument("--incluir-items", action="store_true")
    ap.add_argument("--sesiones-completas", action="store_true", default=True)

    args = ap.parse_args()
    resumen, items = inventario.construir(args)
    casos = resumen["sospechas_fecha"]
    plan = cargar_plan(args.plan)

    # Confirmación de un caso
    if args.caso:
        if args.caso == "todos":
            ids = [i["id"] for i in items]
            propuesta = None
        else:
            elegidos = [c for c in casos if c["caso"] == args.caso]
            if not elegidos:
                print(f"No hay ningún caso '{args.caso}' en este material.", file=sys.stderr)
                sys.exit(1)
            ids = [i for c in elegidos for i in c["ids"]]
            propuesta = elegidos[0].get("propuesta")

        if args.descartar:
            plan.setdefault("descartados", []).append(
                {"caso": args.caso, "n": len(ids),
                 "cuando": datetime.now().astimezone().isoformat(timespec="seconds")})
            accion = valor = None
        elif args.fecha:
            accion, valor = "asignar_fecha", args.fecha
        elif args.offset_horas is not None:
            accion, valor = "offset_horas", args.offset_horas
        elif args.offset_dias is not None:
            accion, valor = "offset_dias", args.offset_dias
        elif args.offset_minutos is not None:
            accion, valor = "offset_minutos", args.offset_minutos
        elif args.aceptar and propuesta and propuesta.get("accion", "").startswith("offset"):
            accion, valor = propuesta["accion"], propuesta["valor"]
        else:
            print("Dime qué hacer: --aceptar, --fecha, --offset-horas, --offset-dias "
                  "o --descartar.", file=sys.stderr)
            sys.exit(1)

        if accion:
            plan = agregar_correccion(plan, ids, accion, valor, f"caso {args.caso}")
        ruta = guardar_plan(plan, args.plan)
        cuantos = "1 archivo" if len(ids) == 1 else f"{len(ids)} archivos"
        print(f"Plan actualizado: {ruta} ({cuantos}, acción: {accion or 'descartar'})")
        return

    if args.aplicar_exiftool:
        resultado = aplicar_exiftool(items, plan, args.si)
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return

    if args.json:
        print(json.dumps({"resumen": resumen, "casos": casos, "plan": plan},
                         ensure_ascii=False, indent=2))
    else:
        print(reporte_texto(casos, resumen, plan))
        if plan.get("correcciones"):
            n = len(plan["correcciones"])
            print(f"\nPlan vigente ({args.plan}): {n} "
                  f"{'corrección confirmada' if n == 1 else 'correcciones confirmadas'}.")


if __name__ == "__main__":
    main()
