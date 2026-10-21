"""Erkennt GTA-Kleidungsdateien (.ydd / .ytd / .yld) anhand ihres Namens und Pfads."""

import re
from dataclasses import dataclass
from pathlib import Path

COMPONENTS = ["head", "berd", "hair", "uppr", "lowr", "hand", "feet", "teef", "accs", "task", "decl", "jbib"]
PROPS = ["p_head", "p_eyes", "p_ears", "p_mouth", "p_lhand", "p_rhand", "p_lwrist", "p_rwrist",
         "p_hip", "p_lfoot", "p_rfoot", "p_ph_l_hand", "p_ph_r_hand"]

# Anzeigenamen (z.B. fuer den Report)
COMPONENT_LABELS = {
    "head": "Kopf", "berd": "Masken", "hair": "Haare", "uppr": "Arme/Torso", "lowr": "Hosen",
    "hand": "Taschen/Fallschirm", "feet": "Schuhe", "teef": "Accessoires", "accs": "Unterhemden",
    "task": "Westen", "decl": "Decals", "jbib": "Oberteile",
    "p_head": "Hüte", "p_eyes": "Brillen", "p_ears": "Ohrringe", "p_mouth": "Mund",
    "p_lhand": "Linke Hand", "p_rhand": "Rechte Hand", "p_lwrist": "Uhren", "p_rwrist": "Armbänder",
    "p_hip": "Hüfte", "p_lfoot": "Linker Fuß", "p_rfoot": "Rechter Fuß",
    "p_ph_l_hand": "Linke Hand (PH)", "p_ph_r_hand": "Rechte Hand (PH)",
}

PED_NAMES = {"m": "mp_m_freemode_01", "f": "mp_f_freemode_01"}

_COMP = "|".join(COMPONENTS)
_PROP = "|".join(p[2:] for p in PROPS)

_RE_COMP_YDD = re.compile(rf"^(?P<type>{_COMP})_(?P<id>\d{{3,}})_(?P<race>[ur])(?P<alt>_\d+)?\.ydd$")
_RE_COMP_YLD = re.compile(rf"^(?P<type>{_COMP})_(?P<id>\d{{3,}})_(?P<race>[ur])\.yld$")
_RE_COMP_YTD = re.compile(rf"^(?P<type>{_COMP})_diff_(?P<id>\d{{3,}})_(?P<letter>[a-z])_(?P<race>[a-z]{{3}})\.ytd$")
_RE_PROP_YDD = re.compile(rf"^(?P<type>p_(?:{_PROP}))_(?P<id>\d{{3,}})(?P<alt>_\d+)?\.ydd$")
_RE_PROP_YTD = re.compile(rf"^(?P<type>p_(?:{_PROP}))_diff_(?P<id>\d{{3,}})_(?P<letter>[a-z])(?:_[a-z]{{3}})?\.ytd$")

_RE_PED_PREFIX = re.compile(r"mp_(?P<g>[mf])_freemode_01")

# Dateien, die Original-GTA-Dateien ersetzen (z.B. EUP-Hauttexturen) – Name muss bleiben
_RE_REPLACEMENT = re.compile(r"^mp_fm_skin_.*\.ytd$")

_MALE_WORDS = {"male", "males", "men", "man", "m", "herren", "herr", "mann", "maenner", "männer",
               "maennlich", "männlich", "boy", "boys", "mp_m_freemode_01"}
_FEMALE_WORDS = {"female", "females", "women", "woman", "w", "f", "damen", "dame", "frau", "frauen",
                 "weiblich", "girl", "girls", "mp_f_freemode_01"}


@dataclass
class ClothFile:
    path: Path
    kind: str          # "ydd", "ytd", "yld"
    is_prop: bool
    type_name: str     # z.B. "jbib" oder "p_head"
    number: int        # Original-Nummer im Pack
    prefix: str        # alles vor dem "^" (z.B. "mp_m_freemode_01_mypack"), sonst ""
    gender: str | None  # "m", "f" oder None (unbekannt)
    race: str = "u"    # Drawable: "u"/"r", Textur: "uni"/"whi"/...
    letter: str = ""   # Textur-Buchstabe a-z
    alt: str = ""      # z.B. "_1" fuer First-Person-Varianten

    @property
    def type_index(self):
        return PROPS.index(self.type_name) if self.is_prop else COMPONENTS.index(self.type_name)


def gender_from_path(path, root):
    """Sucht im Dateinamen-Prefix und in den Ordnernamen nach dem Geschlecht."""
    name = path.name.lower()
    m = _RE_PED_PREFIX.search(name.split("^")[0]) if "^" in name else None
    if m:
        return m.group("g")
    try:
        parts = path.parent.relative_to(root).parts
    except ValueError:
        parts = path.parent.parts
    for part in reversed(parts):
        part = part.lower()
        m = _RE_PED_PREFIX.search(part)
        if m:
            return m.group("g")
        words = set(re.split(r"[^a-z0-9äöü]+", part))
        is_male, is_female = bool(words & _MALE_WORDS), bool(words & _FEMALE_WORDS)
        if is_male != is_female:
            return "m" if is_male else "f"
    return None


def is_replacement(path):
    """Ersatzdatei, die unverändert gestreamt werden muss (eigene oder bereits übernommene)."""
    parts = [p.lower() for p in path.parts[:-1]]
    in_folder = any(a == "stream" and b == "replacements" for a, b in zip(parts, parts[1:]))
    return in_folder or bool(_RE_REPLACEMENT.match(path.name.lower()))


# Original-Ordner/-Prefix: mp_f_freemode_01, mp_f_freemode_01_p, mp_f_freemode_01_mp_f_bikerdlc_01, ...
_RE_BASE_PREFIX = re.compile(r"^mp_(?P<g>[mf])_freemode_01(?:_p)?(?:_(?P<dlc>mp_[mf]_[a-z0-9_]+))?$")


def _ped_prefix(gender, is_prop, dlc=None):
    return PED_NAMES[gender] + ("_p" if is_prop else "") + (f"_{dlc}" if dlc else "")


def original_prefix(cf, root, ymt_names=frozenset()):
    """Prefix der Original-GTA-Datei, die diese Datei ersetzt – oder None, wenn es ein Addon ist.

    Ersatz ist, was wie eine Original-Datei heißt (mp_f_freemode_01^...) oder in einem Original-Ordner
    liegt (OpenIV-Export). Rockstar-DLC-Namen (mp_f_freemode_01_mp_f_...) zählen nur als Ersatz,
    wenn das Pack keine eigene .ymt dafür mitbringt – sonst ist es ein fertiges Addon-Pack.
    """
    candidates = [cf.prefix] if cf.prefix else []
    if not cf.prefix:
        try:
            parents = cf.path.parent.relative_to(root).parts
        except ValueError:
            parents = ()
        candidates = [p.lower() for p in reversed(parents)][:1]
    for candidate in candidates:
        m = _RE_BASE_PREFIX.match(candidate)
        if not m:
            continue
        dlc = m["dlc"]
        if dlc and f"{PED_NAMES[m['g']]}_{dlc}" in ymt_names:
            return None
        return _ped_prefix(m["g"], cf.is_prop, dlc)
    return None


def replacement_name(cf, prefix=None):
    """Streaming-Name, der die Original-Datei im Spiel ersetzt (Nummer und Buchstabe bleiben)."""
    base = cf.path.name.lower().rpartition("^")[2]
    if prefix is None:
        if cf.prefix:
            return f"{cf.prefix}^{base}"
        prefix = _ped_prefix(cf.gender, cf.is_prop)
    return f"{prefix}^{base}"


def parse(path, root):
    """Liefert ein ClothFile oder None, wenn der Name nicht erkannt wird."""
    name = path.name.lower()
    prefix, _, base = name.rpartition("^")
    gender = gender_from_path(path, root)

    m = _RE_COMP_YDD.match(base)
    if m:
        return ClothFile(path, "ydd", False, m["type"], int(m["id"]), prefix, gender, m["race"], alt=m["alt"] or "")
    m = _RE_COMP_YTD.match(base)
    if m:
        return ClothFile(path, "ytd", False, m["type"], int(m["id"]), prefix, gender, m["race"], m["letter"])
    m = _RE_COMP_YLD.match(base)
    if m:
        return ClothFile(path, "yld", False, m["type"], int(m["id"]), prefix, gender, m["race"])
    m = _RE_PROP_YDD.match(base)
    if m:
        return ClothFile(path, "ydd", True, m["type"], int(m["id"]), prefix, gender, alt=m["alt"] or "")
    m = _RE_PROP_YTD.match(base)
    if m:
        return ClothFile(path, "ytd", True, m["type"], int(m["id"]), prefix, gender, letter=m["letter"])
    return None


def output_names(gender, dlc, is_prop, type_name, number, race, letters):
    """Dateinamen im Addon-Format: (ydd, [ytd je Buchstabe], yld)."""
    ped = PED_NAMES[gender]
    if is_prop:
        prefix = f"{ped}_p_{dlc}^"
        ydd = f"{prefix}{type_name}_{number:03d}.ydd"
        ytds = [f"{prefix}{type_name}_diff_{number:03d}_{letter}.ytd" for letter in letters]
        return ydd, ytds, None
    prefix = f"{ped}_{dlc}^"
    base = f"{prefix}{type_name}_{number:03d}_{race}"
    tex_race = "whi" if race == "r" else "uni"
    ytds = [f"{prefix}{type_name}_diff_{number:03d}_{letter}_{tex_race}.ytd" for letter in letters]
    return base + ".ydd", ytds, base + ".yld"
