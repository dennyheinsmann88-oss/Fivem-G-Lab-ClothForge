"""Kommandozeile: python cloth_tool.py <eingabe...> -o <ausgabe> -n <resource> [optionen]"""

import argparse
import sys
from pathlib import Path

from . import __version__
from .builder import build, summary


def print_report(report, log=print):
    for n in report.notes:
        log(f"INFO:    {n}")
    for w in report.warnings:
        log(f"WARNUNG: {w}")
    for e in report.errors:
        log(f"FEHLER:  {e}")
    if report.drawables:
        log(f"\n{len(report.drawables)} Addon-Drawables (neue Teile, neu nummeriert):")
        log(summary(report))
    if report.replacements and not report.errors:
        log(f"\n{len(report.replacements)} Ersatzdateien (ersetzen Original-GTA-Dateien, stream/replacements):")
        for src, rel in report.replacements:
            log(f"  {rel}" if Path(rel).name == src.name else f"  {rel}   <- {src.name}")
    if report.outputs:
        log(f"\nFertig: {report.output}  ({len(report.outputs)} Resourcen, eine pro Kategorie)")
        log("In der server.cfg an der Stelle der alten Resource eintragen (steht auch in ensure.cfg):")
        for out in report.outputs:
            log(f"  ensure {out.name}")
    elif report.output:
        log(f"\nFertig: {report.output}")
        log(f"In der server.cfg eintragen:  ensure {report.output.name}")


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        from .gui import run_gui
        run_gui()
        return 0

    p = argparse.ArgumentParser(prog="cloth_tool", description="Baut aus Kleidungs-Dateien eine FiveM-Addon-Resource.")
    p.add_argument("inputs", nargs="*", help="Ordner mit .ydd/.ytd/.yld (z.B. entpackte Packs)")
    p.add_argument("-r", "--replace", action="append", default=[], metavar="ORDNER",
                   help="Ordner, dessen Dateien Original-GTA-Kleidung ersetzen (Nummern bleiben, mehrfach möglich)")
    p.add_argument("-o", "--output", required=True, help="Ausgabeordner (z.B. dein resources-Ordner)")
    p.add_argument("-n", "--name", required=True, help="Name der Resource, z.B. glab_clothes")
    p.add_argument("-d", "--dlc", help="DLC-Name in den Dateinamen (Standard: Resource-Name klein)")
    p.add_argument("-g", "--gender", choices=["m", "f"], help="Geschlecht, wenn es nicht erkennbar ist")
    p.add_argument("-a", "--append", action="store_true", help="An bestehende Resource anhängen statt neu bauen")
    p.add_argument("-k", "--keep-unknown", action="store_true",
                   help="Nicht erkannte .ydd/.ytd/.yld unverändert mitstreamen (Ersatzdateien)")
    p.add_argument("--optimize", type=int, nargs="?", const=1024, metavar="PX",
                   help="Texturen beim Bauen verkleinern (Standard max. 1024 px)")
    p.add_argument("--split", action="store_true", help="pro Kategorie eine eigene Resource (Ordner [name])")
    p.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nichts schreiben")
    p.add_argument("--version", action="version", version=__version__)
    if argv and argv[0] == "preview":
        return preview_main(argv[1:])
    if argv and argv[0] == "optimize":
        return optimize_main(argv[1:])
    args = p.parse_args(argv)
    if not args.inputs and not args.replace and not args.append:
        p.error("mindestens einen Eingabe-Ordner oder --replace angeben")

    dlc = args.dlc or args.name.lower().replace("-", "_")
    report = build(args.inputs, args.output, args.name, dlc, args.gender, args.append, args.dry_run,
                   keep_unknown=args.keep_unknown, replace_inputs=args.replace,
                   optimize={k: args.optimize for k in ("diffuse", "normal", "specular")} if args.optimize else None,
                   split=args.split)
    print_report(report)
    return 1 if report.errors else 0


def preview_main(argv):
    """python cloth_tool.py preview <resource> [--base <grundkörper>]"""
    import time
    import webbrowser

    from .preview import PreviewServer

    p = argparse.ArgumentParser(prog="cloth_tool preview", description="3D-Vorschau im Browser")
    p.add_argument("resource", nargs="?", help="fertige Resource (Ordner mit fxmanifest.lua)")
    p.add_argument("-b", "--base", help="Ordner mit dem Grundkörper (aus OpenIV exportiert)")
    p.add_argument("-g", "--gender", choices=["m", "f"], help="Geschlecht des Grundkörper-Ordners")
    p.add_argument("--port", type=int, default=0)
    args = p.parse_args(argv)
    if not args.resource and not args.base:
        p.error("Resource und/oder --base angeben")
    server = PreviewServer()
    server.set_folders(args.resource, args.base, args.gender)
    url = server.start(args.port)
    print(f"{len(server.items)} Teile gefunden. Vorschau: {url}  (Beenden mit Strg+C)")
    webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
    return 0


def optimize_main(argv):
    """python cloth_tool.py optimize <ordner> [--max 1024] [--apply]"""
    from .optimize import FIVEM_WARN_MIB, optimize_folder, scan_folder

    p = argparse.ArgumentParser(prog="cloth_tool optimize", description="Texturgrößen prüfen und verkleinern")
    p.add_argument("folder")
    p.add_argument("--max", type=int, default=1024, help="maximale Texturgröße in Pixeln (Standard 1024)")
    p.add_argument("--apply", action="store_true", help="wirklich verkleinern (Originale nach _original)")
    args = p.parse_args(argv)
    limits = {k: args.max for k in ("diffuse", "normal", "specular")}
    if args.apply:
        changed, before, after, backup = optimize_folder(args.folder, limits)
        print(f"{changed} Dateien verkleinert: {before / 1048576:.0f} → {after / 1048576:.0f} MiB"
              + (f", Originale in {backup}" if backup else ""))
    rows = scan_folder(args.folder, limits)
    for r in sorted(rows, key=lambda r: (not r.defects, -(r.info.physical if r.info else 0))):
        if r.defects:
            print(f"DEFEKT        {r.path.name}: {r.defects[0]}")
            continue
        if r.info is None:
            print(f"  ??  {r.path.name}: {r.error}")
            continue
        flag = "!!" if r.info.physical > FIVEM_WARN_MIB * 1048576 else "  "
        largest = r.info.largest.label if r.info.largest else "-"
        print(f"{flag} {r.info.physical / 1048576:6.1f} MiB -> {r.estimate / 1048576:6.1f} MiB  {r.path.name}  [{largest}]")
    return 0
