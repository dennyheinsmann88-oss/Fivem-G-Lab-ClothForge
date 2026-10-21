"""Löschen von Teilen/Texturen in einer fertigen Resource – ohne dass sich Nummern (IDs) verschieben.

Ein gelöschtes Addon-Teil wird durch einen unsichtbaren Platzhalter ersetzt, eine gelöschte Textur durch eine
Platzhalter-Textur. Nur das jeweils letzte Teil bzw. die letzte Textur wird ganz entfernt. Gelöschte Dateien
wandern nach  <resources>/_geloescht/<resource>/<zeit>/  und lassen sich mit undo() zurückholen.
"""

import re
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import naming
from .builder import (PLACEHOLDER_YDD, PLACEHOLDER_YTD, Drawable, _is_own_resource, _natural, is_placeholder,
                      write_metadata)

_RE_DLC = re.compile(r"^mp_(?P<g>[mf])_freemode_01_(?:p_)?(?P<dlc>.+)$")


class EditError(ValueError):
    pass


@dataclass
class Change:
    message: str
    moved: list = field(default_factory=list)    # (ursprünglicher Pfad, Pfad im Papierkorb)
    created: list = field(default_factory=list)  # neu angelegte Platzhalter


def _addon_files(resource):
    """Alle Addon-Dateien der Resource, gruppiert: (dlc, gender, is_prop, type, number) -> ClothFiles."""
    groups = defaultdict(list)
    for path in sorted((resource / "stream").rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".ydd", ".ytd", ".yld") or naming.is_replacement(path):
            continue
        cf = naming.parse(path, resource)
        m = _RE_DLC.match(cf.prefix) if cf and cf.prefix else None
        if not m:
            continue
        cf.gender = m["g"]
        groups[(m["dlc"], m["g"], cf.is_prop, cf.type_name, cf.number)].append(cf)
    return groups


def resource_drawables(resource):
    """Liest die Drawables einer fertigen Resource mit ihren Nummern aus den Dateinamen und prüft die Lücken."""
    resource = Path(resource)
    drawables = []
    numbers = defaultdict(list)
    for (dlc, gender, is_prop, type_name, number), files in _addon_files(resource).items():
        ydd = next((f for f in files if f.kind == "ydd"), None)
        if ydd is None:
            continue
        textures = sorted((f for f in files if f.kind == "ytd"), key=lambda f: f.letter)
        letters = [f.letter for f in textures]
        if letters != [chr(ord("a") + i) for i in range(len(letters))] or not letters:
            raise EditError(f"{ydd.path.name}: Texturen {''.join(letters) or '–'} sind nicht lückenlos (a, b, c …)")
        yld = next((f for f in files if f.kind == "yld"), None)
        d = Drawable(gender, is_prop, type_name, ydd.race, ydd.path, [t.path for t in textures],
                     yld.path if yld else None, resource, dlc=dlc, number=number,
                     placeholder=is_placeholder(ydd.path), existing=True)
        drawables.append(d)
        numbers[(dlc, gender, is_prop, type_name)].append(number)
    for (dlc, gender, is_prop, type_name), nums in numbers.items():
        if sorted(nums) != list(range(len(nums))):
            raise EditError(f"{dlc} {type_name}: Nummern sind nicht lückenlos – Resource bitte einmal neu bauen")
    drawables.sort(key=lambda d: (_natural(d.dlc), d.gender, d.is_prop, d.type_index, d.number))
    dlcs = sorted({d.dlc for d in drawables}, key=_natural)
    return drawables, dlcs


def rebuild_metadata(resource):
    """YMT/meta/fxmanifest neu schreiben, ohne Dateien zu kopieren."""
    drawables, dlcs = resource_drawables(resource)
    write_metadata(Path(resource), drawables, dlcs)
    return drawables


def _check(resource, path):
    resource, path = Path(resource).resolve(), Path(path).resolve()
    if not _is_own_resource(resource):
        raise EditError("Löschen geht nur in Resourcen, die mit diesem Tool gebaut wurden")
    if resource not in path.parents or not path.is_file():
        raise EditError("Datei gehört nicht zur Resource")
    return resource, path


def _trash(resource, change, paths):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = resource.parent / "_geloescht" / resource.name / stamp
    n = 1
    while base.exists():
        n += 1
        base = resource.parent / "_geloescht" / resource.name / f"{stamp}-{n}"
    for path in paths:
        dest = base / path.relative_to(resource)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), dest)
        change.moved.append((path, dest))


def _place(change, asset, dest):
    shutil.copyfile(asset, dest)  # copyfile: neue Änderungszeit, damit Vorschau-Caches neu laden
    change.created.append(dest)


def delete_drawable(resource, ydd_path):
    resource, path = _check(resource, ydd_path)
    if naming.is_replacement(path):
        cf = naming.parse(path, resource)
        siblings = [p for p in path.parent.iterdir() if p.is_file() and (p == path or (
            cf and (c := naming.parse(p, resource)) and (c.prefix, c.type_name, c.number) == (cf.prefix, cf.type_name, cf.number)))]
        change = Change(f"Ersatz {path.name} entfernt – im Spiel ist wieder das Original zu sehen")
        _trash(resource, change, siblings)
        rebuild_metadata(resource)
        return change

    groups = _addon_files(resource)
    key = next((k for k, files in groups.items() if any(f.path.resolve() == path for f in files)), None)
    if key is None or not any(f.kind == "ydd" and f.path.resolve() == path for f in groups[key]):
        raise EditError("Teil nicht gefunden")
    dlc, gender, is_prop, type_name, number = key
    same_type = sorted((k for k in groups if k[1:4] == (gender, is_prop, type_name)), key=lambda k: (_natural(k[0]), k[4]))
    is_last = same_type[-1] == key
    files = [f.path for f in groups[key]]
    label = f"{naming.COMPONENT_LABELS[type_name]} {number:03d} ({dlc})"

    if is_placeholder(path) and not is_last:
        raise EditError(f"{label} ist schon ein Platzhalter")
    if is_last:
        change = Change(f"{label} gelöscht (letztes Teil, keine IDs verschoben)")
        _trash(resource, change, files)
    else:
        change = Change(f"{label} gelöscht – Platzhalter eingesetzt, alle IDs bleiben gleich")
        race = next(f.race for f in groups[key] if f.kind == "ydd")
        _trash(resource, change, files)
        ydd_name, ytd_names, _ = naming.output_names(gender, dlc, is_prop, type_name, number, race, ["a"])
        _place(change, PLACEHOLDER_YDD, path.parent / ydd_name)
        _place(change, PLACEHOLDER_YTD, path.parent / ytd_names[0])
    rebuild_metadata(resource)
    return change


def delete_texture(resource, ytd_path):
    resource, path = _check(resource, ytd_path)
    if naming.is_replacement(path):
        change = Change(f"Ersatz-Textur {path.name} entfernt")
        _trash(resource, change, [path])
        rebuild_metadata(resource)
        return change

    cf = naming.parse(path, resource)
    if cf is None or cf.kind != "ytd":
        raise EditError("keine Textur")
    groups = _addon_files(resource)
    key = next((k for k, files in groups.items() if any(f.path.resolve() == path for f in files)), None)
    letters = sorted(f.letter for f in groups.get(key, []) if f.kind == "ytd")
    if len(letters) <= 1:
        raise EditError("Das ist die einzige Textur – lösche stattdessen das ganze Teil")
    label = f"Textur {cf.letter} von {naming.COMPONENT_LABELS[cf.type_name]} {cf.number:03d}"
    if is_placeholder(path, PLACEHOLDER_YTD) and cf.letter != letters[-1]:
        raise EditError(f"{label} ist schon ein Platzhalter")
    if cf.letter == letters[-1]:
        change = Change(f"{label} gelöscht (letzte Textur)")
        _trash(resource, change, [path])
    else:
        change = Change(f"{label} gelöscht – Platzhalter-Textur eingesetzt, die anderen Texturen bleiben gleich")
        _trash(resource, change, [path])
        _place(change, PLACEHOLDER_YTD, path)
    rebuild_metadata(resource)
    return change


def undo(resource, change):
    """Macht eine Löschung rückgängig."""
    resource = Path(resource).resolve()
    for path in change.created:
        if path.exists():
            path.unlink()
    for original, trashed in reversed(change.moved):
        if trashed.exists():
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(trashed), original)
    if change.moved:
        folder = change.moved[0][1]
        stamp_dir = next((p for p in folder.parents if p.parent.name == resource.name), None)
        if stamp_dir and stamp_dir.exists() and not any(f.is_file() for f in stamp_dir.rglob("*")):
            shutil.rmtree(stamp_dir)
    rebuild_metadata(resource)
