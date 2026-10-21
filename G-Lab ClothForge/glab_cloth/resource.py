"""Liest GTA-V-Ressourcen (.ydd Modelle, .ytd Texturen) für die 3D-Vorschau.

Layout nach CodeWalker (Drawable.cs / Texture.cs). Unterstützt das PC-Format (RSC7), das auch FiveM nutzt.
"""

import struct
import zlib
from dataclasses import dataclass, field

from .ymt import RSC7_MAGIC, _flags_size

SYSTEM_BASE = 0x50000000
GRAPHICS_BASE = 0x60000000

# VertexComponentType -> (Größe in Bytes, struct-Format oder None)
_COMPONENT = {0: (0, None), 1: (4, "2e"), 2: (4, "f"), 3: (8, "4e"), 4: (0, None), 5: (8, "2f"), 6: (12, "3f"),
              7: (16, "4f"), 8: (4, "4B"), 9: (4, "4B"), 10: (4, "I")}
POSITION, TEXCOORD0 = 0, 6

TEXTURE_FORMATS = {21: "A8R8G8B8", 22: "X8R8G8B8", 25: "A1R5G5B5", 28: "A8", 32: "A8B8G8R8", 36: "A16B16G16R16",
                   50: "L8",
                   0x31545844: "DXT1", 0x33545844: "DXT3", 0x35545844: "DXT5",
                   0x31495441: "ATI1", 0x32495441: "ATI2", 0x20374342: "BC7"}


class ResourceError(ValueError):
    pass


class Resource:
    """Entpackte RSC7-Datei mit Zugriff über die virtuellen Adressen (0x5... System, 0x6... Grafik)."""

    def __init__(self, data):
        if len(data) < 16:
            raise ResourceError("Datei zu klein")
        magic, self.version, sys_flags, gfx_flags = struct.unpack_from("<IiII", data)
        if magic != RSC7_MAGIC:
            raise ResourceError("keine GTA-V-Ressource (RSC7) – evtl. GTA V Enhanced oder verschlüsselt")
        self.system_size = _flags_size(sys_flags)
        try:
            body = zlib.decompress(data[16:], -15)
        except zlib.error as exc:
            raise ResourceError(f"Entpacken fehlgeschlagen: {exc}") from exc
        self.data = body

    def offset(self, pointer):
        base = pointer & 0xF0000000
        if base == SYSTEM_BASE:
            return pointer & 0x0FFFFFFF
        if base == GRAPHICS_BASE:
            return self.system_size + (pointer & 0x0FFFFFFF)
        raise ResourceError(f"ungültiger Pointer {pointer:#x}")

    def read(self, pointer, fmt, rel=0):
        return struct.unpack_from("<" + fmt, self.data, self.offset(pointer) + rel)

    def u64(self, pointer, rel):
        return self.read(pointer, "Q", rel)[0]

    def bytes(self, pointer, length):
        o = self.offset(pointer)
        if o + length > len(self.data):
            raise ResourceError("Daten außerhalb der Datei")
        return self.data[o:o + length]

    def string(self, pointer):
        o = self.offset(pointer)
        end = self.data.index(b"\0", o)
        return self.data[o:end].decode("ascii", errors="replace")

    def pointer_list(self, pointer, count):
        return [p for p in struct.unpack_from(f"<{count}Q", self.data, self.offset(pointer)) if p] if count else []


@dataclass
class Geometry:
    shader: int
    vertex_count: int
    positions: list            # flach: x, y, z, ...
    uvs: list                  # flach: u, v, ... (leer, wenn keine TexCoord0)
    indices: list


@dataclass
class Drawable:
    name: str
    lods: dict = field(default_factory=dict)   # "high"/"med"/"low"/"vlow" -> [[Geometry, ...] je Modell]
    textures: list = field(default_factory=list)  # Texturnamen je Shader (z.B. DiffuseSampler)

    def best_lod(self):
        for name in ("high", "med", "low", "vlow"):
            if self.lods.get(name):
                return self.lods[name]
        return []


def _read_geometry(res, gp, shader):
    vb_ptr, ib_ptr = res.u64(gp, 0x18), res.u64(gp, 0x38)
    if not vb_ptr or not ib_ptr:
        return None
    stride, = res.read(vb_ptr, "H", 0x08)
    data1, count = res.read(vb_ptr, "QI", 0x10)
    data2, = res.read(vb_ptr, "Q", 0x20)
    info, = res.read(vb_ptr, "Q", 0x30)
    flags, decl_stride, _, _, types = res.read(info, "IHBBQ")
    stride = stride or decl_stride

    fmt, offset, uv_type = [], 0, None
    for k in range(16):
        if not (flags >> k) & 1:
            continue
        ctype = (types >> (k * 4)) & 0xF
        size, code = _COMPONENT.get(ctype, (0, None))
        if k == POSITION and code == "3f":
            fmt.append("3f")
        elif k == TEXCOORD0 and code in ("2e", "2f"):
            fmt.append(code)
            uv_type = code
        elif size:
            fmt.append(f"{size}x")
        offset += size
    if offset > stride:
        raise ResourceError("Vertex-Layout passt nicht zum Stride")
    if offset < stride:
        fmt.append(f"{stride - offset}x")
    if flags & 1 == 0:
        return None
    vertex_struct = struct.Struct("<" + "".join(fmt))

    raw = res.bytes(data1 or data2, stride * count)
    positions, uvs = [], []
    for values in vertex_struct.iter_unpack(raw):
        positions.extend(values[:3])
        if uv_type:
            uvs.extend(values[3:5])

    index_count, = res.read(ib_ptr, "I", 0x08)
    index_ptr, = res.read(ib_ptr, "Q", 0x10)
    indices = list(struct.unpack_from(f"<{index_count}H", res.bytes(index_ptr, index_count * 2)))
    return Geometry(shader, count, positions, uvs, indices)


def _read_models(res, list_ptr):
    if not list_ptr:
        return []
    models = []
    pointer, count = res.read(list_ptr, "QH")
    for mp in res.pointer_list(pointer, count):
        geom_ptr, geom_count = res.read(mp, "QH", 0x08)
        mapping_ptr, = res.read(mp, "Q", 0x20)
        shaders = res.read(mapping_ptr, f"{geom_count}H") if mapping_ptr and geom_count else (0,) * geom_count
        geoms = []
        for i, gp in enumerate(res.pointer_list(geom_ptr, geom_count)):
            g = _read_geometry(res, gp, shaders[i] if i < len(shaders) else 0)
            if g:
                geoms.append(g)
        models.append(geoms)
    return models


def _read_shader_textures(res, group_ptr):
    """Pro Shader die Namen der Textur-Parameter (z.B. ['jbib_diff_000_a_uni', 'jbib_normal_000'])."""
    if not group_ptr:
        return []
    shaders_ptr, shaders_count = res.read(group_ptr, "QH", 0x10)
    result = []
    for sp in res.pointer_list(shaders_ptr, shaders_count):
        params_ptr, = res.read(sp, "Q", 0x00)
        count, = res.read(sp, "B", 0x10)
        names = []
        for i in range(count):
            data_type, _, _, data_ptr = res.read(params_ptr, "BBHxxxxQ", i * 16)
            if data_type == 0 and data_ptr:
                name_ptr, = res.read(data_ptr, "Q", 0x28)
                if name_ptr:
                    names.append(res.string(name_ptr))
        result.append(names)
    return result


def read_ydd(data):
    """Liest alle Drawables einer .ydd-Datei."""
    res = Resource(data)
    drawables_ptr, count = res.read(SYSTEM_BASE, "QH", 0x30)
    result = []
    for dp in res.pointer_list(drawables_ptr, count):
        name_ptr, = res.read(dp, "Q", 0xA8)
        d = Drawable(res.string(name_ptr) if name_ptr else "")
        try:
            d.textures = _read_shader_textures(res, res.u64(dp, 0x10))
        except (ResourceError, struct.error, ValueError):
            d.textures = []
        for i, lod in enumerate(("high", "med", "low", "vlow")):
            d.lods[lod] = _read_models(res, res.u64(dp, 0x50 + i * 8))
        result.append(d)
    return result


@dataclass
class Texture:
    name: str
    width: int
    height: int
    format: str
    levels: int
    data: bytes  # nur Mip 0


def read_ytd(data):
    """Liest alle Texturen einer .ytd-Datei (jeweils die größte Mip-Stufe)."""
    res = Resource(data)
    pointer, count = res.read(SYSTEM_BASE, "QH", 0x30)
    textures = []
    for tp in res.pointer_list(pointer, count):
        name_ptr, = res.read(tp, "Q", 0x28)
        width, height, _, stride, fmt, _, levels = res.read(tp, "HHHHIBB", 0x50)
        data_ptr, = res.read(tp, "Q", 0x70)
        fmt_name = TEXTURE_FORMATS.get(fmt, f"unbekannt ({fmt:#x})")
        textures.append(Texture(res.string(name_ptr) if name_ptr else "", width, height, fmt_name, levels,
                                res.bytes(data_ptr, stride * height) if data_ptr else b""))
    return textures
