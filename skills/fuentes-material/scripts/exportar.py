# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Exporta de la app Fotos de macOS solo los archivos elegidos, con osxphotos.

La idea de reel-forge es no bajar nada hasta que ya se decidió qué se usa:
primero se revisa todo con las **miniaturas locales** (`--miniaturas`), y al
final se bajan los originales de los elegidos (`--exportar`).

Requiere macOS y osxphotos. Instalación:

    uv tool install osxphotos
    # queda en ~/.local/bin/osxphotos

La primera vez macOS pide permiso: hay que darle **Acceso total al disco** a la
terminal (Ajustes del sistema → Privacidad y seguridad → Acceso total al disco).
Si estás conectado en remoto y no puedes aceptar ese diálogo, no hay vuelta:
alguien tiene que aceptarlo físicamente en la Mac.

Ejemplos:

    # Copiar las miniaturas de una lista de uuids a una carpeta, para revisarlas
    uv run exportar.py --miniaturas --ids elegidos.txt --destino ./contactos

    # Bajar los originales de esos mismos uuids
    uv run exportar.py --exportar --ids elegidos.txt --destino ./originales

    # Ver qué haría, sin bajar nada
    uv run exportar.py --exportar --ids elegidos.txt --destino ./originales --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fuentes  # noqa: E402


def buscar_osxphotos():
    for candidato in (os.environ.get("OSXPHOTOS"), shutil.which("osxphotos"),
                      str(Path.home() / ".local/bin/osxphotos")):
        if candidato and Path(candidato).exists():
            return candidato
    return None


def leer_ids(ruta):
    """Acepta un .txt con un uuid por línea o un .json con una lista de ids
    (o un inventario con `items`)."""
    p = Path(ruta).expanduser()
    texto = p.read_text(encoding="utf-8")
    if p.suffix == ".json":
        datos = json.loads(texto)
        if isinstance(datos, dict):
            datos = datos.get("ids") or [i["id"] for i in datos.get("items", [])]
        return [str(x) for x in datos]
    return [l.strip() for l in texto.splitlines() if l.strip() and not l.startswith("#")]


def copiar_miniaturas(ids, destino, ruta_lib=None):
    """Copia las miniaturas que Fotos ya tiene en disco. No baja nada de iCloud
    y no necesita osxphotos: son archivos JPEG dentro de la biblioteca."""
    lib = fuentes.ruta_biblioteca(ruta_lib)
    destino = Path(destino).expanduser()
    destino.mkdir(parents=True, exist_ok=True)
    copiadas, faltantes = [], []
    for n, uuid in enumerate(ids, 1):
        rutas = fuentes._rutas_miniatura(lib, uuid)
        if not rutas:
            faltantes.append(uuid)
            continue
        origen = max(rutas, key=lambda r: r.stat().st_size)
        salida = destino / f"{n:04d}_{uuid}{origen.suffix}"
        shutil.copy2(origen, salida)
        copiadas.append(str(salida))
    return {"copiadas": len(copiadas), "faltantes": faltantes, "destino": str(destino),
            "nota": ("Las miniaturas rondan los 1200 px del lado largo. Sirven para elegir "
                     "y para revisar caras, no para el render final.")}


def exportar_originales(ids, destino, ruta_lib=None, dry_run=False, extra=None):
    """Llama a osxphotos export con la lista de uuids."""
    binario = buscar_osxphotos()
    if not binario:
        return {"ok": False,
                "razon": "No encontré osxphotos. Instálalo con: uv tool install osxphotos"}

    destino = Path(destino).expanduser()
    destino.mkdir(parents=True, exist_ok=True)
    lista = destino / "_uuids.txt"
    lista.write_text("\n".join(ids) + "\n", encoding="utf-8")

    cmd = [
        binario, "export", str(destino),
        "--uuid-from-file", str(lista),
        "--download-missing",     # baja de iCloud lo que no está en disco
        "--use-photokit",         # la única forma confiable de bajar de iCloud
        "--skip-original-if-edited",
        "--export-by-date",       # carpetas AAAA/MM/DD
        "--report", str(destino / "_reporte.csv"),
        "--retry", "3",
    ]
    if ruta_lib:
        cmd += ["--library", str(Path(ruta_lib).expanduser())]
    if dry_run:
        cmd.append("--dry-run")
    cmd += extra or []

    proceso = subprocess.run(cmd, text=True)
    return {
        "ok": proceso.returncode == 0,
        "comando": " ".join(cmd),
        "destino": str(destino),
        "reporte": str(destino / "_reporte.csv"),
        "n_uuids": len(ids),
        "nota": ("--use-photokit hace que macOS pida la foto a iCloud de verdad. Sin él, "
                 "los archivos que solo están en la nube salen vacíos o no salen. "
                 "Con muchos archivos esto tarda: es red, no CPU."),
    }


def main():
    ap = argparse.ArgumentParser(
        description="Miniaturas locales o exportación selectiva desde la app Fotos (macOS).",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    modo = ap.add_mutually_exclusive_group(required=True)
    modo.add_argument("--miniaturas", action="store_true",
                      help="Copia las miniaturas ya existentes (rápido, sin red)")
    modo.add_argument("--exportar", action="store_true",
                      help="Baja los originales con osxphotos (puede tardar)")
    ap.add_argument("--ids", required=True, help="Archivo .txt o .json con los uuids")
    ap.add_argument("--destino", required=True)
    ap.add_argument("--biblioteca", help="Ruta de la .photoslibrary si no es la default")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--extra", nargs=argparse.REMAINDER,
                    help="Todo lo que siga se le pasa tal cual a osxphotos")
    args = ap.parse_args()

    if sys.platform != "darwin":
        print("Esto solo corre en macOS: la app Fotos no existe en otros sistemas.\n"
              "Usa una carpeta normal como fuente.", file=sys.stderr)
        sys.exit(2)

    ids = leer_ids(args.ids)
    if not ids:
        print("La lista de ids está vacía.", file=sys.stderr)
        sys.exit(1)

    if args.miniaturas:
        resultado = copiar_miniaturas(ids, args.destino, args.biblioteca)
    else:
        resultado = exportar_originales(ids, args.destino, args.biblioteca,
                                        dry_run=args.dry_run, extra=args.extra)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
