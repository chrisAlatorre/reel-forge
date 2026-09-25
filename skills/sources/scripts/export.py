# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Exports only the chosen files from the macOS Photos app, with osxphotos.

reel-forge's idea is to download nothing until it's decided what gets used: first everything is
reviewed with the **local thumbnails** (`--thumbnails`), and only at the end are the originals of
the chosen material downloaded (`--export`).

Requires macOS and osxphotos. Installation:

    uv tool install osxphotos
    # lands in ~/.local/bin/osxphotos

The first time, macOS asks for permission: the terminal needs **Full Disk Access**
(System Settings → Privacy & Security → Full Disk Access). If you are connected remotely and
can't accept that dialog, there is no way around it: somebody has to accept it physically on the
Mac.

Examples:

    # Copy the thumbnails of a list of uuids into a folder, for reviewing
    uv run export.py --thumbnails --ids chosen.txt --dest ./contacts

    # Download the originals of those same uuids
    uv run export.py --export --ids chosen.txt --dest ./originals

    # See what it would do, without downloading anything
    uv run export.py --export --ids chosen.txt --dest ./originals --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sources  # noqa: E402


def find_osxphotos():
    for candidate in (os.environ.get("OSXPHOTOS"), shutil.which("osxphotos"),
                      str(Path.home() / ".local/bin/osxphotos")):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def read_ids(path):
    """Accepts a .txt with one uuid per line or a .json with a list of ids (or an inventory with
    `items`)."""
    p = Path(path).expanduser()
    text = p.read_text(encoding="utf-8")
    if p.suffix == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("ids") or [i["id"] for i in data.get("items", [])]
        return [str(x) for x in data]
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


def copy_thumbnails(ids, dest, lib_path=None, dry_run=False):
    """Copies the thumbnails Photos already has on disk. It downloads nothing from iCloud and
    doesn't need osxphotos: they are JPEG files inside the library."""
    lib = sources.library_path(lib_path)
    dest = Path(dest).expanduser()
    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)
    copied, missing = [], []
    for n, uuid in enumerate(ids, 1):
        paths = sources._thumbnail_paths(lib, uuid)
        if not paths:
            missing.append(uuid)
            continue
        origin = max(paths, key=lambda r: r.stat().st_size)
        out = dest / f"{n:04d}_{uuid}{origin.suffix}"
        if not dry_run:
            shutil.copy2(origin, out)
        copied.append(str(out))
    key = "would_copy" if dry_run else "copied"
    return {key: len(copied), "dry_run": dry_run, "missing": missing, "dest": str(dest),
            "note": ("Thumbnails are around 1200 px on the long side. They are for choosing and "
                     "for checking faces, not for the final render.")}


def export_originals(ids, dest, lib_path=None, dry_run=False, extra=None):
    """Calls osxphotos export with the list of uuids."""
    binary = find_osxphotos()
    if not binary:
        return {"ok": False,
                "reason": "I couldn't find osxphotos. Install it with: uv tool install osxphotos"}

    dest = Path(dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    listing = dest / "_uuids.txt"
    listing.write_text("\n".join(ids) + "\n", encoding="utf-8")

    cmd = [
        binary, "export", str(dest),
        "--uuid-from-file", str(listing),
        "--download-missing",     # pulls from iCloud whatever isn't on disk
        "--use-photokit",         # the only reliable way to download from iCloud
        "--skip-original-if-edited",
        "--export-by-date",       # YYYY/MM/DD folders
        "--report", str(dest / "_report.csv"),
        "--retry", "3",
    ]
    if lib_path:
        cmd += ["--library", str(Path(lib_path).expanduser())]
    if dry_run:
        cmd.append("--dry-run")
    cmd += extra or []

    code, stalled = run_watched(cmd, dest)
    fallback = None
    if stalled and "--use-photokit" in cmd:
        # PhotoKit needs the Photos permission for the process that runs it. When nobody granted it
        # — an agent in the background, a shell the user never approved — osxphotos does not fail:
        # it waits for a dialog nobody sees, at 0 % CPU, forever. That is what this catches.
        fallback = ("PhotoKit stalled (no output and no new file for "
                    f"{STALL_S} s): most likely this process has no Photos permission. Retried "
                    "without --use-photokit; files that live only in iCloud may be missing — grant "
                    "Photos access to the terminal in System Settings > Privacy to get them.")
        print(f"export: {fallback}", file=sys.stderr, flush=True)
        cmd = [c for c in cmd if c != "--use-photokit"]
        code, stalled = run_watched(cmd, dest)
    return {
        "ok": code == 0 and not stalled,
        "command": " ".join(cmd),
        "dest": str(dest),
        "report": str(dest / "_report.csv"),
        "n_uuids": len(ids),
        "fallback": fallback,
        "note": ("--use-photokit is what makes macOS genuinely ask iCloud for the photo. Without "
                 "it, files that only exist in the cloud come out empty or don't come out at all. "
                 "With a lot of files this is slow: it's the network, not the CPU."),
    }


STALL_S = 120


def run_watched(cmd, dest):
    """Runs osxphotos and kills it if it goes quiet: no line of output and no new file in
    STALL_S seconds. Returns (exit code, stalled?). Slow is fine; silent and idle is not."""
    import threading
    proc = subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL)
    last = [time.time()]

    def pump():
        for line in proc.stdout:
            last[0] = time.time()
            print(line, end="", flush=True)

    threading.Thread(target=pump, daemon=True).start()
    seen = -1
    while proc.poll() is None:
        time.sleep(5)
        n = sum(1 for _ in Path(dest).rglob("*") if _.is_file())
        if n != seen:
            seen, last[0] = n, time.time()
        if time.time() - last[0] > STALL_S:
            proc.kill()
            proc.wait()
            return proc.returncode, True
    return proc.returncode, False


def main():
    ap = argparse.ArgumentParser(
        description="Local thumbnails or a selective export from the Photos app (macOS).",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--thumbnails", action="store_true",
                      help="Copies the already existing thumbnails (fast, no network)")
    mode.add_argument("--export", action="store_true",
                      help="Downloads the originals with osxphotos (can take a while)")
    ap.add_argument("--ids", required=True, help="A .txt or .json file with the uuids")
    ap.add_argument("--dest", required=True)
    ap.add_argument("--library", help="Path of the .photoslibrary if it isn't the default one")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--extra", nargs=argparse.REMAINDER,
                    help="Everything after this gets passed straight to osxphotos")
    args = ap.parse_args()

    if sys.platform != "darwin":
        print("This only runs on macOS: the Photos app doesn't exist on other systems.\n"
              "Use an ordinary folder as the source.", file=sys.stderr)
        sys.exit(2)

    ids = read_ids(args.ids)
    if not ids:
        print("The list of ids is empty.", file=sys.stderr)
        sys.exit(1)

    if args.thumbnails:
        result = copy_thumbnails(ids, args.dest, args.library, dry_run=args.dry_run)
    else:
        result = export_originals(ids, args.dest, args.library,
                                  dry_run=args.dry_run, extra=args.extra)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
