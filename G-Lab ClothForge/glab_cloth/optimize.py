"""Prüft und verkleinert Texturen in .ytd/.ydd (eingebettete Texturen) – ohne neu zu komprimieren.

GTA-Texturen enthalten ihre Mipmaps (4096 → 2048 → 1024 …). Zum Verkleinern werden die größten Stufen
weggelassen; die nächste Stufe ist schon fertig komprimiert. Nur die Texturdaten liegen im Grafik-Teil der
Ressource: dieser Teil wird neu gepackt (Seiten-Layout wie CodeWalker ResourceBuilder.AssignPositions),
im System-Teil werden nur Größe/Mipmap-Anzahl/Daten-Pointer der Texturen und die Seitenzahl angepasst.
"""

import struct
import zlib
from dataclasses import dataclass, field

from .resource import GRAPHICS_BASE, SYSTEM_BASE, TEXTURE_FORMATS, Resource, ResourceError
from .ymt import RSC7_MAGIC, _flags_size

FIVEM_WARN_MIB = 16          # ab hier meldet FiveM "uses X MiB of physical memory"
DEFAULT_LIMITS = {"diffuse": 1024, "normal": 1024, "specular": 1024}
KIND_LABELS = {"diffuse": "Textur", "normal": "Normal-Map", "specular": "Spiegelung"}

_USAGE_KIND = {20: "diffuse", 18: "diffuse", 19: "diffuse", 16: "diffuse", 22: "normal", 23: "specular"}


@dataclass
class TextureInfo:
    name: str
    width: int
    height: int
    format: str
    levels: int
    kind: str          # diffuse / normal / specular
    struct_ptr: int    # Adresse der Texture-Struktur (System-Teil)
    data_ptr: int
    stride: int

    @property
    def label(self):
        return f"{self.width}×{self.height} {self.format} ({KIND_LABELS[self.kind]})"


@dataclass
class FileInfo:
    physical: int                      # Grafik-Speicher in Bytes (das meldet FiveM)
    virtual: int
    textures: list = field(default_factory=list)

    @property
    def physical_mib(self):
        return self.physical / (1024 * 1024)

    @property
    def largest(self):
        return max(self.textures, key=lambda t: t.width * t.height, default=None)


def _kind(name, usage):
    if usage in _USAGE_KIND:
        return _USAGE_KIND[usage]
    n = name.lower()
    if n.endswith(("_n", "_nrm", "_normal")) or "normal" in n or "_n_" in n:
        return "normal"
    if n.endswith(("_s", "_spec", "_specular")) or "spec" in n or "_s_" in n:
        return "specular"
    return "diffuse"


def _dict_textures(res, dict_ptr):
    pointer, count = res.read(dict_ptr, "QH", 0x30)
    result = []
    for tp in res.pointer_list(pointer, count):
        name_ptr, = res.read(tp, "Q", 0x28)
        usage, = res.read(tp, "I", 0x40)
        width, height, _, stride, fmt, _, levels = res.read(tp, "HHHHIBB", 0x50)
        data_ptr, = res.read(tp, "Q", 0x70)
        if not data_ptr:
            continue
        name = res.string(name_ptr) if name_ptr else ""
        result.append(TextureInfo(name, width, height, TEXTURE_FORMATS.get(fmt, f"{fmt:#x}"), levels,
                                  _kind(name, usage & 0x1F), tp, data_ptr, stride))
    return result


def _textures(res, kind):
    if kind == "ytd":
        return _dict_textures(res, SYSTEM_BASE)
    textures = []
    drawables_ptr, count = res.read(SYSTEM_BASE, "QH", 0x30)
    for dp in res.pointer_list(drawables_ptr, count):
        group = res.u64(dp, 0x10)
        tex_dict = res.u64(group, 0x08) if group else 0
        if tex_dict:
            textures += _dict_textures(res, tex_dict)
    return textures


def header_info(data):
    """Nur den Dateikopf lesen: (physical, virtual) in Bytes – sehr schnell."""
    magic, _, sys_flags, gfx_flags = struct.unpack_from("<IiII", data)
    if magic != RSC7_MAGIC:
        raise ResourceError("keine GTA-V-Ressource (RSC7)")
    return _flags_size(gfx_flags), _flags_size(sys_flags)


def analyze(data, kind):
    """Speicherbedarf + Texturen einer .ydd/.ytd (kind = 'ydd' oder 'ytd')."""
    physical, virtual = header_info(data)
    res = Resource(data)
    return FileInfo(physical, virtual, _textures(res, kind))


def _mip_sizes(stride, height, levels):
    """Wie CodeWalker TextureData: Stufe 0 = stride*height, jede weitere ein Viertel."""
    sizes, length = [], stride * height
    for _ in range(levels):
        sizes.append(length)
        length //= 4
    return sizes


# Unkomprimierte Formate: Bytes pro Pixel (lassen sich ohne Mipmaps direkt herunterrechnen)
UNCOMPRESSED_BPP = {"A8R8G8B8": 4, "X8R8G8B8": 4, "A8B8G8R8": 4, "A1R5G5B5": 2, "A8": 1, "L8": 1,
                    "A16B16G16R16": 8}


def _needed(tex, limits):
    limit = limits.get(tex.kind, 1024)
    k = 0
    while max(tex.width, tex.height) >> k > limit:
        k += 1
    return k


def texture_plan(tex, limits):
    """('mips', k): k größte Mip-Stufen weglassen · ('resample', k): Bild um 2^k herunterrechnen
    (nur unkomprimiert, ohne Mipmaps) · ('keep', 0)."""
    k = _needed(tex, limits)
    if not k:
        return "keep", 0
    if tex.levels > 1:
        return "mips", min(k, tex.levels - 1)
    if tex.format in UNCOMPRESSED_BPP and tex.stride >= tex.width * UNCOMPRESSED_BPP[tex.format]:
        return "resample", k
    return "keep", 0


def drop_levels(tex, limits):
    """Um wie viele Halbierungen die Textur kleiner wird (0 = nichts zu tun)."""
    return texture_plan(tex, limits)[1]


def _resample(raw, tex, k):
    """Unkomprimiertes Bild um den Faktor 2^k verkleinern (jedes 2^k-te Pixel, sehr schnell)."""
    bpp = UNCOMPRESSED_BPP[tex.format]
    step = 1 << k
    new_w, new_h = max(tex.width >> k, 1), max(tex.height >> k, 1)
    code = {1: "B", 2: "H", 4: "I", 8: "Q"}[bpp]
    view = memoryview(raw)
    out = bytearray()
    for y in range(new_h):
        start = y * step * tex.stride
        out += view[start:start + tex.width * bpp].cast(code)[::step][:new_w].tobytes()
    return bytes(out), new_w * bpp


def _new_length(tex, limits):
    mode, k = texture_plan(tex, limits)
    if mode == "resample":
        return max(tex.width >> k, 1) * UNCOMPRESSED_BPP[tex.format] * max(tex.height >> k, 1)
    return sum(_mip_sizes(tex.stride, tex.height, tex.levels)[k:])


# ---------- Grafik-Teil neu packen (Port von CodeWalker ResourceBuilder.AssignPositions, Grafik-Seiten) ----------

def _page_flags(page_counts, base_shift):
    v = base_shift & 0xF
    v += (page_counts[0] & 0x1) << 4
    v += (page_counts[1] & 0x3) << 5
    v += (page_counts[2] & 0xF) << 7
    v += (page_counts[3] & 0x3F) << 11
    v += (page_counts[4] & 0x7F) << 17
    v += (page_counts[5] & 0x1) << 24
    v += (page_counts[6] & 0x1) << 25
    v += (page_counts[7] & 0x1) << 26
    v += (page_counts[8] & 0x1) << 27
    return v


def _flags_count(v):
    return (((v >> 4) & 1) + ((v >> 5) & 3) + ((v >> 7) & 0xF) + ((v >> 11) & 0x3F) + ((v >> 17) & 0x7F)
            + ((v >> 24) & 1) + ((v >> 25) & 1) + ((v >> 26) & 1) + ((v >> 27) & 1))


def assign_graphics(lengths):
    """Positionen der Blöcke im Grafik-Teil + Seiten-Flags. lengths: Länge je Block (Reihenfolge beliebig)."""
    if not lengths:
        return [], 0
    pad = lambda p: (16 - p % 16) % 16  # noqa: E731
    largest = max(lengths)
    start_page = 0x2000
    total = 0
    for length in lengths:
        total += length
        total += pad(total)
    while start_page < largest:
        start_page *= 2
    mult = 1
    while True:
        order = sorted(range(len(lengths)), key=lambda i: -lengths[i])  # stabil wie List.Sort? siehe unten
        remaining = list(order)
        positions = [0] * len(lengths)
        pos = 0
        page_size = start_page
        page_start = 0
        page_space = start_page
        remainder = total
        page_count = 1
        counts = [0] * 9
        index = 0
        target = max(65536 * mult, start_page >> 2)
        min_page = max(512 * mult, min(target, start_page) >> 4)
        shift, base = 0, 512
        while base < min_page:
            shift += 1
            base *= 2
            if shift >= 0xF:
                break
        base_max, test = base << 8, start_page
        while test < base_max:
            index += 1
            test *= 2
        counts[index] = 1
        while True:
            pick = next((i for i in remaining if lengths[i] <= page_space), None)
            if pick is not None:
                remaining.remove(pick)
                positions[pick] = pos
                old = pos
                pos += lengths[pick]
                pos += pad(pos)
                used = pos - old
                page_space -= used
                remainder -= used
            elif remaining:
                page_start += page_size
                pos = page_start
                biggest = lengths[remaining[0]]
                while biggest <= page_size >> 1:
                    if page_size <= min_page or index >= 8:
                        break
                    if page_size <= target and remainder >= page_size - min_page:
                        break
                    page_size >>= 1
                    index += 1
                page_space = page_size
                counts[index] += 1
                page_count += 1
            else:
                break
        flags = _page_flags(counts, shift)
        if page_count == _flags_count(flags) and _flags_size(flags) >= pos:
            return positions, flags
        start_page *= 2
        mult *= 2


def shrink(data, kind, limits=None):
    """Verkleinert alle zu großen Texturen. Gibt (neue Datei-Bytes, Liste der Änderungen) zurück – oder
    (None, Gründe), wenn nichts zu tun ist bzw. die Datei nicht sicher bearbeitet werden kann."""
    limits = limits or DEFAULT_LIMITS
    magic, version, sys_flags, gfx_flags = struct.unpack_from("<IiII", data)
    if magic != RSC7_MAGIC:
        raise ResourceError("keine GTA-V-Ressource (RSC7)")
    res = Resource(data)
    textures = _textures(res, kind)
    plan = [(t, *texture_plan(t, limits)) for t in textures]
    notes = [f"{t.name}: {t.width}×{t.height} {t.format} ohne kleinere Stufen – übersprungen"
             for t, mode, k in plan if mode == "keep" and _needed(t, limits)]
    if not any(k for _, _, k in plan):
        return None, notes
    if len({t.data_ptr for t in textures}) != len(textures):
        return None, notes + ["mehrere Texturen teilen sich dieselben Daten – zur Sicherheit nicht verändert"]

    system = bytearray(res.data[:res.system_size])
    gfx_size = len(res.data) - res.system_size

    # Sicherheitsnetz: jeder Pointer in den Grafik-Teil muss zu einer bekannten Textur gehören
    known = {t.data_ptr for t in textures}
    for (value,) in struct.iter_unpack("<Q", bytes(system[:len(system) // 8 * 8])):
        if GRAPHICS_BASE <= value < GRAPHICS_BASE + gfx_size and value not in known:
            return None, notes + ["unbekannte Grafik-Daten in der Datei – zur Sicherheit nicht verändert"]

    blocks, strides, changes = [], [], []
    for t, mode, k in plan:
        sizes = _mip_sizes(t.stride, t.height, t.levels)
        start = res.offset(t.data_ptr)
        full = res.data[start:start + sum(sizes)]
        if mode == "resample":
            block, stride = _resample(full, t, k)
        else:
            block, stride = full[sum(sizes[:k]):], max(t.stride >> k, 1)
        blocks.append(block)
        strides.append(stride)
        if k:
            how = " (herunterrechnet)" if mode == "resample" else ""
            changes.append(f"{t.name}: {t.width}×{t.height} → {max(t.width >> k, 1)}×{max(t.height >> k, 1)}{how}")
    positions, new_flags = assign_graphics([len(b) for b in blocks])

    gfx = bytearray(_flags_size(new_flags))
    for (t, mode, k), block, stride, pos in zip(plan, blocks, strides, positions):
        gfx[pos:pos + len(block)] = block
        o = res.offset(t.struct_ptr)
        if k:
            struct.pack_into("<HH", system, o + 0x50, max(t.width >> k, 1), max(t.height >> k, 1))
            struct.pack_into("<H", system, o + 0x56, stride)
            system[o + 0x5D] = 1 if mode == "resample" else t.levels - k
        struct.pack_into("<Q", system, o + 0x70, GRAPHICS_BASE + pos)

    pages_ptr, = struct.unpack_from("<Q", system, 0x08)  # ResourceFileBase.FilePagesInfoPointer
    if pages_ptr:
        system[res.offset(pages_ptr) + 9] = _flags_count(new_flags)  # GraphicsPagesCount

    gfx_version = version & 0xF
    header = struct.pack("<IiII", RSC7_MAGIC, version, sys_flags, new_flags + (gfx_version << 28))
    comp = zlib.compressobj(6, zlib.DEFLATED, -15)
    return header + comp.compress(bytes(system) + bytes(gfx)) + comp.flush(), changes + notes


def estimate(info, limits=None):
    """Voraussichtlicher Grafik-Speicher nach dem Verkleinern (Bytes), ohne etwas zu schreiben."""
    limits = limits or DEFAULT_LIMITS
    lengths = [_new_length(t, limits) for t in info.textures]
    if not any(drop_levels(t, limits) for t in info.textures):
        return info.physical
    _, flags = assign_graphics(lengths)
    return _flags_size(flags)


def file_kind(path):
    return path.suffix.lower().lstrip(".") if path.suffix.lower() in (".ydd", ".ytd") else None


def optimize_bytes(data, kind, limits):
    """Für den Build: verkleinerte Bytes oder die Original-Bytes. Gibt (bytes, vorher, nachher, hinweise)."""
    before, _ = header_info(data)
    try:
        new, notes = shrink(data, kind, limits)
    except (ResourceError, struct.error, ValueError, IndexError) as exc:
        return data, before, before, [f"nicht lesbar ({exc}) – unverändert übernommen"]
    if new is None:
        return data, before, before, notes
    after, _ = header_info(new)
    return new, before, after, notes


@dataclass
class Row:
    path: object
    info: FileInfo | None
    estimate: int
    error: str = ""
    defects: list = field(default_factory=list)   # würde FiveM abstürzen lassen


def scan_folder(folder, limits=None, progress=None):
    """Alle .ydd/.ytd unter folder prüfen (Ordner _original/_geloescht werden übersprungen)."""
    from pathlib import Path
    folder = Path(folder)
    from .validate import check
    files = [p for p in sorted(folder.rglob("*")) if p.is_file() and file_kind(p)
             and not {"_original", "_geloescht"} & set(p.relative_to(folder).parts)]
    rows = []
    for n, path in enumerate(files, 1):
        try:
            data = path.read_bytes()
        except OSError as exc:
            rows.append(Row(path, None, 0, str(exc), [str(exc)]))
            continue
        defects = check(data, file_kind(path))
        try:
            info = analyze(data, file_kind(path))
            rows.append(Row(path, info, info.physical if defects else estimate(info, limits), defects=defects))
        except (ResourceError, struct.error, ValueError, IndexError) as exc:
            rows.append(Row(path, None, 0, str(exc), defects or [str(exc)]))
        if progress and n % 25 == 0:
            progress(n, len(files))
    return rows


def optimize_folder(folder, limits=None, log=print):
    """Verkleinert alle zu großen Texturen direkt im Ordner. Originale kommen nach
    <übergeordneter Ordner>/_original/<ordnername>/<zeit>/ . Gibt (geänderte Dateien, vorher, nachher) zurück."""
    import shutil
    import time
    from pathlib import Path
    folder = Path(folder)
    backup = folder.parent / "_original" / folder.name / time.strftime("%Y%m%d-%H%M%S")
    changed = before_total = after_total = 0
    rows = scan_folder(folder, limits)
    todo = [r for r in rows if r.info and not r.defects and r.estimate < r.info.physical]
    for n, row in enumerate(todo, 1):
        data = row.path.read_bytes()
        new, before, after, notes = optimize_bytes(data, file_kind(row.path), limits or DEFAULT_LIMITS)
        if new is data:
            continue
        dest = backup / row.path.relative_to(folder)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(row.path, dest)
        row.path.write_bytes(new)
        changed += 1
        before_total += before
        after_total += after
        log(f"  {row.path.name}: {before / 1048576:.1f} → {after / 1048576:.1f} MiB")
        if n % 20 == 0:
            log(f"  … {n}/{len(todo)}")
    return changed, before_total, after_total, backup if changed else None
