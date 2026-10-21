"""Sammelt Kleidungsdateien aus beliebigen Ordnern und baut daraus eine FiveM-Addon-Resource."""

import csv
import hashlib
import json
import re
import shutil
import tempfile
import time
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import naming, validate
from .optimize import FIVEM_WARN_MIB, file_kind, optimize_bytes
from .ymt import YmtDrawable, build_ymt

MAX_DRAWABLES_PER_DLC = 256  # Drawable-Nummer ist im YMT ein Byte (000-255)
MAX_TEXTURES = 26            # a-z
MARKER = "G_Lab_ClothTool"
ASSETS = Path(__file__).parent / "assets"
PLACEHOLDER_YDD = ASSETS / "placeholder.ydd"   # unsichtbares Mini-Teil, hält eine Nummer frei
PLACEHOLDER_YTD = ASSETS / "placeholder.ytd"
GENDER_LABELS = {"m": "male", "f": "female"}
_TEX_RACE_PRIORITY = ["uni", "whi", "bla", "chi", "lat", "ara", "bal", "jam", "kor", "ita", "pak"]


@dataclass
class Drawable:
    gender: str
    is_prop: bool
    type_name: str
    race: str
    ydd: Path
    textures: list
    yld: Path | None
    source: Path
    sort_key: tuple = ()
    dlc: str = ""
    number: int = -1
    placeholder: bool = False   # Platzhalter für ein gelöschtes Teil
    existing: bool = False      # stammt aus der Resource, an die angehängt wird
    defects: list = field(default_factory=list)        # Probleme in der .ydd (würde FiveM abstürzen lassen)
    bad_textures: dict = field(default_factory=dict)   # Index -> Probleme der .ytd

    @property
    def type_index(self):
        return naming.PROPS.index(self.type_name) if self.is_prop else naming.COMPONENTS.index(self.type_name)

    def output_names(self):
        letters = [chr(ord("a") + i) for i in range(len(self.textures))]
        return naming.output_names(self.gender, self.dlc, self.is_prop, self.type_name, self.number, self.race, letters)


@dataclass
class Report:
    drawables: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    dlcs: list = field(default_factory=list)
    replacements: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    output: Path | None = None
    outputs: list = field(default_factory=list)   # bei aufgeteilter Resource: alle Teil-Resourcen


def _natural(text):
    return tuple(int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(text).lower()))


def _file_hash(paths):
    h = hashlib.sha1()
    for p in paths:
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


_placeholder_hashes = {}


def is_placeholder(path, asset=PLACEHOLDER_YDD):
    """True, wenn die Datei der mitgelieferte Platzhalter ist (Größe + Inhalt)."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size != asset.stat().st_size:
        return False
    if asset not in _placeholder_hashes:
        _placeholder_hashes[asset] = _file_hash([asset])
    return _file_hash([path]) == _placeholder_hashes[asset]


def _pick_texture(files, report):
    """Pro Buchstabe nur eine Textur – bevorzugt _uni, dann _whi."""
    if len(files) == 1:
        return files[0].path
    files = sorted(files, key=lambda f: _TEX_RACE_PRIORITY.index(f.race) if f.race in _TEX_RACE_PRIORITY else 99)
    report.warnings.append(f"Mehrere Texturen für Buchstabe '{files[0].letter}', nehme {files[0].path.name} "
                           f"(ignoriert: {', '.join(f.path.name for f in files[1:])})")
    return files[0].path


def _add_replacement(path, report, replacements, name=None, subdir=""):
    name = name or path.name
    key = name.lower()
    if key in replacements:
        if _file_hash([path]) != _file_hash([replacements[key][0]]):
            report.warnings.append(f"Mehrere Varianten für {name} – nehme {replacements[key][0]}, ignoriert: {path} "
                                   "(andere Variante gewünscht? Nur deren Ordner hinzufügen)")
        return False
    replacements[key] = (path, f"{subdir}/{name}" if subdir else name)
    return True


ARCHIVES = (".zip", ".oiv")           # werden automatisch entpackt (.oiv = OpenIV-Paket, ist ein Zip)
UNSUPPORTED_ARCHIVES = (".rar", ".7z", ".rpf")


def _collect_files(root, extract_dir, report):
    """Alle Dateien unter root, Zip/OIV-Archive werden (auch verschachtelt) entpackt.

    Liefert [(datei, basisordner)] – basisordner ist root bzw. der Entpack-Ordner des Archivs.
    """
    result = []
    pending = [root]
    while pending:
        base = pending.pop(0)
        for path in sorted(base.rglob("*"), key=_natural):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in ARCHIVES and extract_dir is not None:
                target = Path(extract_dir) / f"{len(list(Path(extract_dir).iterdir()))}_{path.stem}"
                try:
                    with zipfile.ZipFile(path) as z:
                        z.extractall(target)
                except (zipfile.BadZipFile, OSError) as exc:
                    report.warnings.append(f"Archiv konnte nicht entpackt werden: {path} ({exc})")
                    continue
                pending.append(target)
            elif suffix in UNSUPPORTED_ARCHIVES:
                report.warnings.append(f"{path.name}: {suffix}-Dateien kann das Tool nicht öffnen – bitte vorher "
                                       "entpacken (.rar/.7z mit 7-Zip, .rpf mit OpenIV)")
            else:
                result.append((path, base))
    return result


def _pack_gender(files):
    """Geschlecht, wenn alle erkennbaren Dateien eines Packs dasselbe haben (z.B. nur mp_fm_skin_f_*)."""
    genders = set()
    for path, base in files:
        m = re.match(r"mp_fm_skin_([mf])_", path.name.lower())
        if m:
            genders.add(m.group(1))
        elif path.suffix.lower() in (".ydd", ".ytd", ".yld"):
            cf = naming.parse(path, base)
            if cf and cf.gender:
                genders.add(cf.gender)
    return genders.pop() if len(genders) == 1 else None


def scan(inputs, default_gender=None, report=None, keep_unknown=False, replace_inputs=(), extract_dir=None):
    """Durchsucht die Eingabeordner und gibt die gefundenen Drawables (in stabiler Reihenfolge) zurück.

    Jede Datei wird automatisch als Addon (bekommt neue Nummer) oder Ersatz einer Original-Datei
    (behält Nummer) eingeordnet; Ordner aus replace_inputs zählen immer als Ersatz.
    Ersatzdateien landen in report.replacements als (quelle, pfad unter stream/replacements).
    """
    report = report or Report()
    drawables = []
    seen = {}
    replacements = {}

    all_inputs = [(Path(r), True) for r in replace_inputs] + [(Path(r), False) for r in inputs]
    for input_index, (root, force_replace) in enumerate(all_inputs):
        if not root.is_dir():
            report.errors.append(f"Ordner nicht gefunden: {root}")
            continue
        files = _collect_files(root, extract_dir, report)
        ymt_names = {p.stem.lower() for p, _ in files if p.suffix.lower() == ".ymt"}

        input_gender = default_gender or _pack_gender(files)
        inferred_used = False
        ydds, textures, ylds = {}, defaultdict(lambda: defaultdict(list)), {}
        for path, base in files:
            if path.suffix.lower() not in (".ydd", ".ytd", ".yld"):
                continue
            if naming.is_replacement(path):
                rel = path.relative_to(base).parts
                subdir = "/".join(rel[rel.index("replacements") + 1:-1]) if "replacements" in rel else ""
                _add_replacement(path, report, replacements, subdir=subdir)
                continue
            cf = naming.parse(path, base)
            if cf is None:
                if keep_unknown:
                    _add_replacement(path, report, replacements)
                else:
                    report.warnings.append(f"Name nicht erkannt, übersprungen: {path} "
                                           "(mit 'Nicht erkannte Dateien unverändert übernehmen' mitstreamen)")
                continue

            prefix = naming.original_prefix(cf, base, ymt_names)
            if prefix is None and force_replace:
                inferred_used |= cf.gender is None
                cf.gender = cf.gender or input_gender
                if cf.gender is None and not cf.prefix:
                    report.errors.append(f"Geschlecht unbekannt (Ordner 'male'/'female' oder Standard-Geschlecht "
                                         f"setzen): {path}")
                    continue
                name = naming.replacement_name(cf)
            elif prefix is not None:
                name = naming.replacement_name(cf, prefix)
            else:
                name = None
            if name is not None:
                gender = name[3] if name.startswith("mp_") else cf.gender
                subdir = f"{GENDER_LABELS[gender]}/{cf.type_name}" if gender in GENDER_LABELS else ""
                _add_replacement(path, report, replacements, name, subdir)
                continue

            if cf.gender is None:
                inferred_used = True
                cf.gender = input_gender
            if cf.gender is None:
                report.errors.append(f"Geschlecht unbekannt (Ordner 'male'/'female' oder Standard-Geschlecht setzen): {path}")
                continue
            key = (path.parent, cf.prefix, cf.gender, cf.is_prop, cf.type_name, cf.number)
            if cf.kind == "ydd":
                if cf.alt:
                    report.warnings.append(f"First-Person-Variante wird nicht unterstützt, übersprungen: {path.name}")
                    continue
                ydds[key] = cf
            elif cf.kind == "ytd":
                textures[key][cf.letter].append(cf)
            else:
                ylds[key] = cf

        if inferred_used and input_gender and not default_gender:
            report.notes.append(f"{root.name}: Dateien ohne erkennbares Geschlecht als {GENDER_LABELS[input_gender]} "
                                "behandelt (der Rest des Packs ist eindeutig)")

        # Texturen, die in einem anderen Unterordner liegen als ihr Drawable
        loose = defaultdict(list)
        for key in textures:
            if key not in ydds:
                loose[key[1:]].append(key)
        used_tex_keys = set()

        for key, cf in ydds.items():
            tex_key = key
            if key not in textures:
                candidates = loose.get(key[1:], [])
                if len(candidates) == 1:
                    tex_key = candidates[0]
            letters = textures.get(tex_key)
            if not letters:
                # Ohne Texturen kann es kein Addon sein: ersetzt das Original-Modell und nutzt dessen Texturen
                name = naming.replacement_name(cf)
                if _add_replacement(cf.path, report, replacements, name, f"{GENDER_LABELS[cf.gender]}/{cf.type_name}"):
                    report.notes.append(f"{cf.path.name}: keine eigenen Texturen → als Ersatz eingeordnet "
                                        f"(nutzt die Original-Texturen): {name}")
                if key in ylds:
                    _add_replacement(ylds[key].path, report, replacements, naming.replacement_name(ylds[key]),
                                     f"{GENDER_LABELS[cf.gender]}/{cf.type_name}")
                continue
            used_tex_keys.add(tex_key)

            tex_paths = [_pick_texture(letters[letter], report) for letter in sorted(letters)]
            expected = [chr(ord("a") + i) for i in range(len(letters))]
            if sorted(letters) != expected:
                report.warnings.append(f"{cf.path.name}: Textur-Buchstaben {''.join(sorted(letters))} "
                                       f"werden zu {''.join(expected)} umbenannt")
            if len(tex_paths) > MAX_TEXTURES:
                report.warnings.append(f"{cf.path.name}: mehr als {MAX_TEXTURES} Texturen, Rest ignoriert")
                tex_paths = tex_paths[:MAX_TEXTURES]

            yld = ylds.get(key)
            d = Drawable(cf.gender, cf.is_prop, cf.type_name, cf.race, cf.path, tex_paths,
                         yld.path if yld else None, root,
                         (input_index, _natural(cf.prefix), _natural(cf.path.parent), cf.number))

            d.placeholder = is_placeholder(d.ydd)
            if not d.placeholder:
                d.defects = validate.check_file(d.ydd)
                d.bad_textures = {i: p for i, t in enumerate(d.textures) if (p := validate.check_file(t))}
                if d.yld and validate.check_file(d.yld):
                    report.warnings.append(f"DEFEKT, Cloth-Physik weggelassen: {d.yld} ({validate.check_file(d.yld)[0]})")
                    d.yld = None
            if d.placeholder:  # Platzhalter sind absichtlich gleich – nie als Duplikat aussortieren
                drawables.append(d)
                continue
            digest = (d.gender, d.is_prop, d.type_name, _file_hash([d.ydd] + d.textures))
            if digest in seen:
                report.warnings.append(f"Duplikat übersprungen: {cf.path} (gleich wie {seen[digest]})")
                continue
            seen[digest] = cf.path
            drawables.append(d)

        for key in textures:
            if key not in ydds and key not in used_tex_keys:
                files = [f.path.name for fs in textures[key].values() for f in fs]
                report.warnings.append(f"Texturen ohne passendes Drawable: {', '.join(files)}")

    drawables.sort(key=lambda d: d.sort_key)
    report.replacements = sorted(replacements.values(), key=lambda r: _natural(r[1]))
    return drawables, report


def _drop_defects(drawables, report):
    """Defekte Dateien kommen nicht auf den Server: neue werden weggelassen, schon vorhandene (beim Anhängen)
    durch Platzhalter ersetzt, damit sich keine Nummern verschieben."""
    keep = []
    for d in drawables:
        if d.defects:
            reason = d.defects[0]
            if d.existing:
                report.warnings.append(f"DEFEKT, durch Platzhalter ersetzt: {d.ydd} ({reason})")
                d.ydd, d.textures, d.yld, d.placeholder, d.bad_textures = PLACEHOLDER_YDD, [PLACEHOLDER_YTD], None, True, {}
                d.race = "u"
                keep.append(d)
            else:
                report.warnings.append(f"DEFEKT, nicht übernommen: {d.ydd} ({reason})")
            continue
        if d.bad_textures:
            for i, problems in sorted(d.bad_textures.items()):
                action = "durch Platzhalter-Textur ersetzt" if d.existing else "nicht übernommen"
                report.warnings.append(f"DEFEKTE Textur, {action}: {d.textures[i]} ({problems[0]})")
            if d.existing:
                d.textures = [PLACEHOLDER_YTD if i in d.bad_textures else t for i, t in enumerate(d.textures)]
            else:
                d.textures = [t for i, t in enumerate(d.textures) if i not in d.bad_textures]
                if not d.textures:
                    report.warnings.append(f"Keine gültige Textur übrig, nicht übernommen: {d.ydd}")
                    continue
            d.bad_textures = {}
        keep.append(d)
    drawables[:] = keep
    good = []
    for src, rel in report.replacements:
        problems = validate.check_file(Path(src))
        if problems:
            report.warnings.append(f"DEFEKT, Ersatzdatei nicht übernommen: {src} ({problems[0]})")
        else:
            good.append((src, rel))
    report.replacements = good


def assign_numbers(drawables, dlc):
    """Nummeriert pro Geschlecht/Typ fortlaufend; ab 256 Stück wird ein weiteres DLC angelegt.

    Neue Teile füllen zuerst die Platzhalter der bestehenden Resource (gleiche Nummer, nichts verschiebt
    sich), der Rest wird hinten angehängt. Platzhalter ganz am Ende fallen weg. Die Liste wird angepasst.
    """
    groups = defaultdict(list)
    for d in drawables:
        groups[(d.gender, d.is_prop, d.type_name)].append(d)
    result, dlcs = [], []
    for items in groups.values():
        existing = [d for d in items if d.existing]
        new = [d for d in items if not d.existing]
        for i, d in enumerate(existing):
            if d.placeholder and new and not new[0].placeholder:
                existing[i] = new.pop(0)
        ordered = existing + new
        while ordered and ordered[-1].placeholder:
            ordered.pop()
        for index, d in enumerate(ordered):
            chunk = index // MAX_DRAWABLES_PER_DLC
            d.dlc = dlc if chunk == 0 else f"{dlc}_{chunk + 1}"
            d.number = index % MAX_DRAWABLES_PER_DLC
            if d.dlc not in dlcs:
                dlcs.append(d.dlc)
        result += ordered
    drawables[:] = result
    return sorted(dlcs, key=_natural)


def _meta_xml(gender, dlc):
    ped = naming.PED_NAMES[gender]
    character = "SCR_CHAR_MULTIPLAYER" if gender == "m" else "SCR_CHAR_MULTIPLAYER_F"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<ShopPedApparel>\n"
        f"    <pedName>{ped}</pedName>\n"
        f"    <dlcName>{dlc}</dlcName>\n"
        f"    <fullDlcName>{ped}_{dlc}</fullDlcName>\n"
        f"    <eCharacter>{character}</eCharacter>\n"
        f"    <creatureMetaData>mp_creaturemetadata_{gender}_{dlc}</creatureMetaData>\n"
        "    <pedOutfits>\n    </pedOutfits>\n"
        "    <pedComponents>\n    </pedComponents>\n"
        "    <pedProps>\n    </pedProps>\n"
        "</ShopPedApparel>\n"
    )


def _fxmanifest(meta_files):
    text = (
        f"-- Generiert mit {MARKER}\n\n"
        "fx_version 'cerulean'\n"
        "game 'gta5'\n"
        f"author '{MARKER}'\n"
    )
    if meta_files:
        files = ",\n".join(f"    '{m}'" for m in meta_files)
        data = "\n".join(f"data_file 'SHOP_PED_APPAREL_META_FILE' '{m}'" for m in meta_files)
        text += f"\nfiles {{\n{files}\n}}\n\n{data}\n"
    return text


def resource_dlc(resource):
    """Grund-DLC-Name einer mit diesem Tool gebauten Resource (aus den .meta-Dateien), sonst None."""
    names = [m.group(1) for p in Path(resource).glob("mp_?_freemode_01_*.meta")
             if (m := re.match(r"mp_[mf]_freemode_01_(.+)\.meta$", p.name))]
    return min(names, key=len) if names else None


def _is_own_resource(path):
    manifest = path / "fxmanifest.lua"
    return manifest.is_file() and MARKER in manifest.read_text(encoding="utf-8", errors="ignore")


def build(inputs, output_dir, resource_name, dlc, default_gender=None, append=False, dry_run=False, log=print,
          keep_unknown=False, replace_inputs=(), optimize=None, split=False):
    """Kompletter Ablauf: scannen, nummerieren, Resource schreiben. Gibt einen Report zurück.

    optimize: None oder Limits wie {"diffuse": 1024, "normal": 1024, "specular": 1024} – Texturen werden
    beim Kopieren auf diese Größe verkleinert.
    split: pro Kategorie eine eigene Resource in einem Ordner [resource_name] (IDs bleiben gleich).
    """
    with tempfile.TemporaryDirectory(prefix="glab_cloth_") as extract_dir:
        return _build(inputs, output_dir, resource_name, dlc, default_gender, append, dry_run, log,
                      keep_unknown, replace_inputs, extract_dir, optimize, split)


class _Copier:
    """Kopiert Dateien in die Resource und verkleinert dabei optional die Texturen."""

    def __init__(self, limits, report):
        self.limits, self.report = limits, report
        self.before = self.after = self.changed = 0
        self.too_big = []

    def copy(self, src, dest):
        kind = file_kind(Path(dest))
        if not self.limits or not kind:
            shutil.copy2(src, dest)
            return
        data = Path(src).read_bytes()
        new, before, after, notes = optimize_bytes(data, kind, self.limits)
        self.before += before
        self.after += after
        if new is data:
            shutil.copy2(src, dest)
        else:
            Path(dest).write_bytes(new)
            self.changed += 1
        for note in notes:
            self.report.notes.append(f"{Path(dest).name}: {note}")
        if after > FIVEM_WARN_MIB * 1024 * 1024:
            self.too_big.append(f"{Path(dest).name} ({after / 1048576:.1f} MiB)")

    def summary(self):
        if not self.limits:
            return
        mib = 1024 * 1024
        self.report.notes.append(f"Texturen verkleinert: {self.changed} Dateien, Grafikspeicher "
                                 f"{self.before / mib:.0f} → {self.after / mib:.0f} MiB")
        for name in self.too_big:
            self.report.warnings.append(f"Immer noch über {FIVEM_WARN_MIB} MiB (FiveM-Warnung): {name}")


GROUP_INFO = "cloth_tool.json"  # liegt im [gruppen]-Ordner einer aufgeteilten Resource


def split_names(resource_name):
    """Ordner und Resource-Namen beim Aufteilen nach Kategorie."""
    return f"[{resource_name}]", lambda part: f"{resource_name}_{part}"


def read_group(folder):
    """Infos einer aufgeteilten Resource ({"name", "dlc"}) oder None."""
    try:
        return json.loads((Path(folder) / GROUP_INFO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _own_children(folder):
    return [p for p in sorted(Path(folder).iterdir()) if p.is_dir() and _is_own_resource(p)] if Path(folder).is_dir() else []


def _archive(path, output_dir, report, why):
    """Alte Resource aus dem Weg räumen (nicht löschen): nach _original/ verschieben."""
    dest = output_dir / "_original" / f"{path.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), dest)
    report.notes.append(f"{why}: {path.name} → {dest}")


def _build(inputs, output_dir, resource_name, dlc, default_gender, append, dry_run, log,
           keep_unknown, replace_inputs, extract_dir, optimize=None, split=False):
    report = Report()
    if not re.fullmatch(r"[a-z0-9_]{1,32}", dlc):
        report.errors.append("DLC-Name: nur Kleinbuchstaben, Zahlen und _ (max. 32 Zeichen)")
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", resource_name):
        report.errors.append("Resource-Name: nur Buchstaben, Zahlen, _ und -")
    if report.errors:
        return report

    output_dir = Path(output_dir)
    target = output_dir / resource_name
    group_name, part_name = split_names(resource_name)
    group_dir = output_dir / group_name
    if target.exists() and any(target.iterdir()) and not _is_own_resource(target):
        report.errors.append(f"{target} existiert schon und wurde nicht von diesem Tool erstellt – "
                             "bitte anderen Resource-Namen oder Ausgabeordner wählen")
        return report

    inputs = [Path(p) for p in inputs]
    replace_inputs = [Path(p) for p in replace_inputs]
    for p in inputs + replace_inputs:
        for t in (target, group_dir):
            if p.resolve() == t.resolve() or t.resolve() in p.resolve().parents:
                report.errors.append("Der Eingabeordner darf nicht die Ziel-Resource sein (dafür 'Anhängen' nutzen)")
                return report

    existing = []
    if append:
        existing = [r for r in [target] + _own_children(group_dir) if r.exists() and _is_own_resource(r)]
        for r in existing:
            log(f"Bestehende Resource wird übernommen: {r}")
        inputs = existing + inputs

    drawables, report = scan(inputs, default_gender, report, keep_unknown, replace_inputs, extract_dir)
    if report.errors:
        return report
    if not drawables and not report.replacements:
        report.errors.append("Keine Kleidung gefunden")
        return report

    resolved = [r.resolve() for r in existing]
    for d in drawables:
        d.existing = any(r in d.ydd.resolve().parents for r in resolved)
    _drop_defects(drawables, report)
    filled = sum(d.placeholder for d in drawables)
    if split:
        by_type = defaultdict(list)
        for d in drawables:
            by_type[(d.is_prop, d.type_index, d.type_name)].append(d)
        drawables[:] = []
        report.dlcs = []
        for (_, _, type_name), group in sorted(by_type.items()):
            report.dlcs += assign_numbers(group, f"{dlc}_{type_name}")
            drawables += group
    else:
        report.dlcs = assign_numbers(drawables, dlc)
    filled -= sum(d.placeholder for d in drawables)
    if filled:
        report.notes.append(f"{filled} Platzhalter mit neuen Teilen gefüllt bzw. am Ende entfernt")
    report.drawables = drawables
    if dry_run:
        return report

    copier = _Copier(optimize, report)
    if optimize:
        log("Texturen werden beim Kopieren verkleinert …")
    if not split:
        _write_resource(output_dir, resource_name, drawables, report.replacements, report.dlcs, copier, log)
        copier.summary()
        report.output = target
        for old in _own_children(group_dir) if append else []:
            _archive(old, output_dir, report, "Aufgeteilte Resource zusammengeführt, alte Teil-Resource verschoben")
        return report

    group_dir.mkdir(parents=True, exist_ok=True)
    written = []
    types = sorted({(d.is_prop, d.type_index, d.type_name) for d in drawables})
    for _, _, type_name in types:
        group = [d for d in drawables if d.type_name == type_name]
        dlcs = sorted({d.dlc for d in group}, key=_natural)
        written.append(_write_resource(group_dir, part_name(type_name), group, [], dlcs, copier, log))
    if report.replacements:
        written.append(_write_resource(group_dir, part_name("ersatz"), [], report.replacements, [], copier, log))
    copier.summary()
    for old in _own_children(group_dir):
        if old not in written:
            _archive(old, output_dir, report, "Kategorie ist leer, alte Teil-Resource verschoben")
    if target.exists() and _is_own_resource(target):
        if append:
            _archive(target, output_dir, report, "Alte (nicht aufgeteilte) Resource verschoben, damit nichts doppelt lädt")
        else:
            report.warnings.append(f"Die alte Resource {target.name} gibt es noch – aus der server.cfg nehmen bzw. "
                                   "löschen, sonst wird die Kleidung doppelt geladen (oder mit „Anhängen“ bauen)")
    (group_dir / GROUP_INFO).write_text(json.dumps({"name": resource_name, "dlc": dlc}, indent=2), encoding="utf-8")
    (group_dir / "ensure.cfg").write_text(
        f"# {MARKER}: alle Teile von {resource_name} (an der Stelle der alten Resource in die server.cfg)\n"
        + "".join(f"ensure {p.name}\n" for p in written), encoding="utf-8")
    report.outputs = written
    report.output = group_dir
    return report


def _write_resource(output_dir, name, drawables, replacements, dlcs, copier, log):
    """Eine Resource komplett in einen temporären Ordner schreiben und dann austauschen."""
    target = output_dir / name
    if target.exists() and any(target.iterdir()) and not _is_own_resource(target):
        raise ValueError(f"{target} existiert schon und wurde nicht von diesem Tool erstellt")
    tmp = output_dir / f".{name}_tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    stream = tmp / "stream"
    multi = len(dlcs) > 1
    for i, d in enumerate(drawables, 1):
        folder = stream / (d.dlc if multi else "") / GENDER_LABELS[d.gender] / d.type_name
        folder.mkdir(parents=True, exist_ok=True)
        ydd_name, ytd_names, yld_name = d.output_names()
        copier.copy(d.ydd, folder / ydd_name)
        for src, ytd_name in zip(d.textures, ytd_names):
            copier.copy(src, folder / ytd_name)
        if d.yld and yld_name:
            shutil.copy2(d.yld, folder / yld_name)
        if i % 100 == 0:
            log(f"  {name}: {i}/{len(drawables)} Drawables kopiert ...")
    for src, rel in replacements:
        dest = stream / "replacements" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        copier.copy(src, dest)
    tmp.mkdir(parents=True, exist_ok=True)
    write_metadata(tmp, drawables, dlcs)
    if target.exists():
        shutil.rmtree(target)
    tmp.rename(target)
    return target


def write_metadata(resource, drawables, dlcs):
    """Schreibt YMTs, .meta, fxmanifest.lua und clothing_mapping.csv für die (fertig nummerierten) Drawables."""
    stream = resource / "stream"
    stream.mkdir(parents=True, exist_ok=True)
    for old in list(stream.glob("*.ymt")) + list(resource.glob("mp_?_freemode_01_*.meta")):
        old.unlink()
    meta_files = []
    for dlc_name in dlcs:
        for gender in ("m", "f"):
            group = [d for d in drawables if d.dlc == dlc_name and d.gender == gender]
            if not group:
                continue
            ped = naming.PED_NAMES[gender]
            ymt = build_ymt([YmtDrawable(d.is_prop, d.type_index, d.number, len(d.textures),
                                         d.race == "r", d.yld is not None) for d in group], dlc_name)
            (stream / f"{ped}_{dlc_name}.ymt").write_bytes(ymt)
            meta = f"{ped}_{dlc_name}.meta"
            (resource / meta).write_text(_meta_xml(gender, dlc_name), encoding="utf-8")
            meta_files.append(meta)
    (resource / "fxmanifest.lua").write_text(_fxmanifest(meta_files), encoding="utf-8")
    mapping = resource / "clothing_mapping.csv"
    if drawables:
        _write_mapping(mapping, drawables)
    elif mapping.exists():
        mapping.unlink()


def _write_mapping(path, drawables):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Geschlecht", "Typ", "Kategorie", "DLC", "Nummer", "Texturen", "Neue Datei", "Quelle"])
        for d in sorted(drawables, key=lambda d: (d.dlc, d.gender, d.is_prop, d.type_index, d.number)):
            w.writerow([GENDER_LABELS[d.gender], d.type_name, naming.COMPONENT_LABELS[d.type_name], d.dlc,
                        f"{d.number:03d}", len(d.textures), d.output_names()[0],
                        "Platzhalter (gelöscht)" if d.placeholder else d.ydd])


def summary(report):
    """Kurze Übersicht: Anzahl pro DLC / Geschlecht / Typ."""
    counts = defaultdict(int)
    for d in report.drawables:
        counts[(d.dlc, d.gender, d.is_prop, d.type_index, d.type_name)] += 1
    lines = []
    for (dlc, gender, _, _, type_name), n in sorted(counts.items(), key=lambda x: (_natural(x[0][0]),) + x[0][1:]):
        lines.append(f"  {dlc:<16} {GENDER_LABELS[gender]:<7} {type_name:<12} "
                     f"{naming.COMPONENT_LABELS[type_name]:<20} {n:>4}")
    return "\n".join(lines)
