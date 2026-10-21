"""Erzeugt die binaere Ped-YMT (CPedVariationInfo, RSC7-Meta) fuer eine Addon-Kleidung.

Das Layout folgt CodeWalker (MetaBuilder + ResourceBuilder) bzw. grzyClothTool,
deren Ausgabe vom Spiel und von FiveM gelesen wird.
"""

import struct
import zlib
from dataclasses import dataclass

from . import meta_tables as mt

RSC7_MAGIC = 0x37435352
RESOURCE_VERSION = 2
SYSTEM_BASE = 0x50000000
MAX_BLOCK_LENGTH = 0x4000
PAGES_INFO_LENGTH = 20 + 256 * 16


@dataclass
class YmtDrawable:
    is_prop: bool
    type_index: int    # Komponente 0-11 bzw. Prop-Anker 0-12
    number: int        # Drawable-Nummer innerhalb des Typs (0-255)
    texture_count: int
    skin: bool = False   # "_r"-Drawable (Hautfarbe, Texturen "_whi")
    cloth: bool = False  # hat .yld (Cloth-Physik)


def joaat(text):
    h = 0
    for c in text.encode("utf-8"):
        h = (h + c) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    h = (h + (h << 15)) & 0xFFFFFFFF
    return h


def _pad16(data):
    rem = len(data) % 16
    return data + b"\0" * (16 - rem) if rem else data


class _MetaBuilder:
    def __init__(self):
        self.blocks = []  # [struct_hash, [items], total_size]

    def ensure_block(self, type_hash):
        for i, b in enumerate(self.blocks):
            if b[0] == type_hash and b[2] < MAX_BLOCK_LENGTH:
                return i
        self.blocks.append([type_hash, [], 0])
        return len(self.blocks) - 1

    def add_array(self, type_hash, data, count):
        """Haengt ein Array an und liefert die 16-Byte Array_Structure (Pointer, Count, Count, 0)."""
        if count == 0:
            return bytes(16)
        idx = self.ensure_block(type_hash)
        block = self.blocks[idx]
        offset = block[2]
        data = _pad16(data)
        block[1].append(data)
        block[2] += len(data)
        pointer = ((idx + 1) & 0xFFF) + ((offset & 0xFFFFF) << 12)
        return struct.pack("<QHHI", pointer, count, count, 0)

    def add_item(self, type_hash, data):
        idx = self.ensure_block(type_hash)
        block = self.blocks[idx]
        data = _pad16(data)
        block[1].append(data)
        block[2] += len(data)


def _texture_data(d):
    tex_id = 1 if d.skin else 0
    return b"".join(struct.pack("<BBB", tex_id, 255, 0) for _ in range(d.texture_count))


def _prop_texture_data(d):
    return b"".join(struct.pack("<iiBBBB", 0, 0, t, 0, 0, 255) for t in range(d.texture_count))


def _build_variation_info(mb, drawables, dlc_name):
    comps = sorted((d for d in drawables if not d.is_prop), key=lambda d: (d.type_index, d.number))
    props = sorted((d for d in drawables if d.is_prop), key=lambda d: (d.type_index, d.number))

    avail = [255] * 12
    used_types = sorted({d.type_index for d in comps})
    for n, t in enumerate(used_types):
        avail[t] = n

    component_data = []
    for t in used_types:
        group = [d for d in comps if d.type_index == t]
        drawbl = b""
        for d in group:
            tex_arr = mb.add_array(mt.CPV_TEXTURE_DATA, _texture_data(d), d.texture_count)
            cloth = struct.pack("<B", 1 if d.cloth else 0) + bytes(23)
            drawbl += struct.pack("<BBHI", 17 if d.skin else 1, 0, 0, 0) + tex_arr + cloth
        arr = mb.add_array(mt.CPV_DRAWBL_DATA, drawbl, len(group))
        num_tex = sum(d.texture_count for d in group) & 0xFF
        component_data.append(struct.pack("<BBHI", num_tex, 0, 0, 0) + arr)
    comp_arr = mb.add_array(mt.CPV_COMPONENT_DATA, b"".join(component_data), len(component_data))

    none_hash = joaat("none")
    infos = b""
    for d in comps:
        infos += struct.pack("<II", none_hash, none_hash) + bytes(20)  # audio, audio2, expressionMods[5]
        infos += struct.pack("<IiiHHBBH", 0, 0, 0, 0, 0, d.type_index, d.number, 0)  # vfxComps = PV_COMP_HEAD
    info_arr = mb.add_array(mt.CCOMPONENT_INFO, infos, len(comps))

    prop_meta = b""
    for d in props:
        tex_arr = mb.add_array(mt.CPED_PROP_TEX_DATA, _prop_texture_data(d), d.texture_count)
        prop_meta += struct.pack("<I", none_hash) + bytes(20) + tex_arr
        prop_meta += struct.pack("<IIHBBBBH", 0, 0, 0, d.type_index, d.number, 0, 0, 0)
    prop_meta_arr = mb.add_array(mt.CPED_PROP_META_DATA, prop_meta, len(props))

    anchors = b""
    anchor_types = sorted({d.type_index for d in props})
    for t in anchor_types:
        counts = bytes(d.texture_count for d in props if d.type_index == t)
        anchors += mb.add_array(mt.TYPE_BYTE, counts, len(counts)) + struct.pack("<iI", t, 0)
    anchor_arr = mb.add_array(mt.CANCHOR_PROPS, anchors, len(anchor_types))

    prop_info = struct.pack("<BBHI", len(props) & 0xFF, 0, 0, 0) + prop_meta_arr + anchor_arr

    root = struct.pack("<BBBB", 1, 1, 0, 0) + bytes(avail)
    root += comp_arr + bytes(16) + info_arr + prop_info  # aSelectionSets bleibt leer
    root += struct.pack("<II", joaat(dlc_name), 0)
    return root


def _page_flags(page_count, page_size):
    """RpfResourceFileEntry.GetFlagsFromBlocks aus CodeWalker."""
    shift = 0
    size = page_size
    if page_count > 0:
        while size > 0x200:
            shift += 1
            size >>= 1
    f = 0
    f |= (page_count & 1) << 27
    f |= ((page_count >> 1) & 1) << 26
    f |= ((page_count >> 2) & 1) << 25
    f |= ((page_count >> 3) & 1) << 24
    f |= ((page_count >> 4) & 0x7F) << 17
    f |= shift & 0xF
    return f


def _flags_page_count(f):
    return (((f >> 4) & 1) + ((f >> 5) & 3) + ((f >> 7) & 0xF) + ((f >> 11) & 0x3F)
            + ((f >> 17) & 0x7F) + ((f >> 24) & 1) + ((f >> 25) & 1) + ((f >> 26) & 1) + ((f >> 27) & 1))


def _flags_size(f):
    base = 0x200 << (f & 0xF)
    mult = (((f >> 27) & 1) + (((f >> 26) & 1) << 1) + (((f >> 25) & 1) << 2) + (((f >> 24) & 1) << 3)
            + (((f >> 17) & 0x7F) << 4) + (((f >> 11) & 0x3F) << 5) + (((f >> 7) & 0xF) << 6)
            + (((f >> 5) & 3) << 7) + (((f >> 4) & 1) << 8))
    return base * mult


def _assign_positions(lengths):
    """Naives Meta-Packing (ResourceBuilder.AssignPositionsForMeta)."""
    page_size = 0x2000
    while page_size < max(lengths):
        page_size *= 2
    while True:
        pages = 0
        pos = 0
        positions = []
        for length in lengths:
            if pages * page_size - pos < length + 16:
                pages += 1
                pos = page_size * (pages - 1)
            positions.append(pos)
            pos += length
            pos += (16 - pos % 16) % 16
        if pages < 128:
            return positions, _page_flags(pages, page_size)
        page_size *= 2


def build_ymt(drawables, dlc_name):
    """Liefert die fertige .ymt (bytes) fuer eine Ped-Variante (ein Geschlecht)."""
    mb = _MetaBuilder()
    mb.ensure_block(mt.CPED_VARIATION_INFO)  # Root-Block muss Block 1 sein
    mb.add_item(mt.CPED_VARIATION_INFO, _build_variation_info(mb, drawables, dlc_name))

    data_blocks = [(h, b"".join(items)) for h, items, size in mb.blocks if size > 0]
    name = dlc_name.encode("ascii") + b"\0"

    # Reihenfolge wie CodeWalker (Tiefensuche ueber die Referenzen)
    lengths = [112, PAGES_INFO_LENGTH, 32 * len(mt.STRUCTS)]
    lengths += [16 * len(s[4]) for s in mt.STRUCTS]
    lengths += [24 * len(mt.ENUMS)]
    lengths += [8 * len(e[2]) for e in mt.ENUMS]
    lengths += [16 * len(data_blocks)]
    lengths += [len(d) for _, d in data_blocks]
    lengths += [len(name)]

    positions, sys_flags = _assign_positions(lengths)
    ptr = [SYSTEM_BASE + p for p in positions]
    n_struct, n_enum = len(mt.STRUCTS), len(mt.ENUMS)
    i_pages, i_structs = 1, 2
    i_struct_entries = 3
    i_enums = i_struct_entries + n_struct
    i_enum_entries = i_enums + 1
    i_blocks = i_enum_entries + n_enum
    i_block_data = i_blocks + 1
    i_name = i_block_data + len(data_blocks)

    chunks = [None] * len(lengths)
    chunks[0] = struct.pack(
        "<IIQiHBBiiqqqqqhhhh", 0x405BC808, 1, ptr[i_pages], 0x50524430, 0x0079, 0, 0, 0, 1,
        ptr[i_structs], ptr[i_enums], ptr[i_blocks], ptr[i_name], 0,
        n_struct, n_enum, len(data_blocks), 0) + bytes(32)
    chunks[i_pages] = struct.pack("<IIBBHII", 0, 0, _flags_page_count(sys_flags), 0, 0, 0, 0) + bytes(4096)
    chunks[i_structs] = b"".join(
        struct.pack("<IIIIqihh", s[0], s[1], s[2], 0, ptr[i_struct_entries + i], s[3], 0, len(s[4]))
        for i, s in enumerate(mt.STRUCTS))
    for i, s in enumerate(mt.STRUCTS):
        chunks[i_struct_entries + i] = b"".join(struct.pack("<IiBBhI", *e) for e in s[4])
    chunks[i_enums] = b"".join(
        struct.pack("<IIqii", e[0], e[1], ptr[i_enum_entries + i], len(e[2]), 0)
        for i, e in enumerate(mt.ENUMS))
    for i, e in enumerate(mt.ENUMS):
        chunks[i_enum_entries + i] = b"".join(struct.pack("<Ii", *x) for x in e[2])
    chunks[i_blocks] = b"".join(
        struct.pack("<Iiq", h, len(d), ptr[i_block_data + i]) for i, (h, d) in enumerate(data_blocks))
    for i, (_, d) in enumerate(data_blocks):
        chunks[i_block_data + i] = d
    chunks[i_name] = name

    system = bytearray(_flags_size(sys_flags))
    for pos, chunk, length in zip(positions, chunks, lengths):
        assert len(chunk) == length
        system[pos:pos + length] = chunk

    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    payload = comp.compress(bytes(system)) + comp.flush()
    header = struct.pack("<IiII", RSC7_MAGIC, RESOURCE_VERSION, sys_flags, (RESOURCE_VERSION & 0xF) << 28)
    return header + payload


def read_system_data(ymt_bytes):
    """Entpackt eine YMT (fuer Tests / Diagnose): liefert (version, sys_flags, gfx_flags, daten)."""
    magic, version, sys_flags, gfx_flags = struct.unpack_from("<IiII", ymt_bytes)
    if magic != RSC7_MAGIC:
        raise ValueError("keine RSC7-Datei")
    return version, sys_flags, gfx_flags, zlib.decompress(ymt_bytes[16:], -15)
