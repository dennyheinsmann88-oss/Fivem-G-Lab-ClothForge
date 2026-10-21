"""Findet defekte .ydd/.ytd/.yld, bevor FiveM daran abstürzt.

Beim Laden „repariert“ das Spiel jeden Zeiger in der Datei (Fixup): er muss in den System-Teil (0x5…) oder in den
Grafik-Teil (0x6…) zeigen, sonst bricht FiveM mit „Invalid fixup, address is neither virtual nor physical“ ab.
Hier werden dieselben Strukturen abgelaufen wie in CodeWalker (Drawable.cs / Texture.cs) und alle Zeiger geprüft.
"""

import struct
import zlib

from .resource import GRAPHICS_BASE, SYSTEM_BASE
from .ymt import RSC7_MAGIC, _flags_size

MAX_PROBLEMS = 5


class _Checker:
    def __init__(self, data):
        self.problems = []
        magic, self.version, sys_flags, gfx_flags = struct.unpack_from("<IiII", data)
        if magic != RSC7_MAGIC:
            raise ValueError("keine GTA-V-Ressource (RSC7) – evtl. GTA V Enhanced, verschlüsselt oder beschädigt")
        self.sys_size, self.gfx_size = _flags_size(sys_flags), _flags_size(gfx_flags)
        try:
            self.data = zlib.decompress(data[16:], -15)
        except zlib.error as exc:
            raise ValueError(f"lässt sich nicht entpacken ({exc}) – Datei unvollständig oder beschädigt") from exc
        if len(self.data) < self.sys_size:
            raise ValueError("Datei ist kürzer als ihr Kopf angibt – unvollständig")

    def bad(self, text):
        if len(self.problems) < MAX_PROBLEMS:
            self.problems.append(text)

    def ptr(self, value, what, length=0, graphics=False):
        """True, wenn der Zeiger gesetzt und gültig ist (dann darf man ihm folgen)."""
        if value == 0:
            return False
        base, off = value & 0xF0000000, value & 0x0FFFFFFF
        if base not in (SYSTEM_BASE, GRAPHICS_BASE):
            self.bad(f"{what}: ungültiger Zeiger {value:#x} (weder virtuell noch physisch – FiveM stürzt ab)")
            return False
        size = self.sys_size if base == SYSTEM_BASE else self.gfx_size
        if off + length > size:
            self.bad(f"{what}: Zeiger {value:#x} zeigt hinter das Dateiende")
            return False
        if graphics and base != GRAPHICS_BASE or not graphics and base != SYSTEM_BASE:
            self.bad(f"{what}: Zeiger {value:#x} zeigt in den falschen Speicherbereich")
            return False
        return True

    def at(self, value):
        return (value & 0x0FFFFFFF) + (self.sys_size if value & 0xF0000000 == GRAPHICS_BASE else 0)

    def read(self, value, fmt, rel=0):
        return struct.unpack_from("<" + fmt, self.data, self.at(value) + rel)

    def string(self, value, what):
        if self.ptr(value, what, 1) and self.data.find(b"\0", self.at(value), self.sys_size) < 0:
            self.bad(f"{what}: Text ohne Ende")

    def pointers(self, value, count, what):
        if count and self.ptr(value, what, count * 8):
            return list(self.read(value, f"{count}Q"))
        return []

    # ---------- Strukturen ----------

    def file_base(self, p, what):
        self.ptr(self.read(p, "Q", 0x08)[0], f"{what} (Seiten-Info)", 20)

    def texture_dict(self, p, what):
        self.file_base(p, what)
        hashes, hcount = self.read(p, "QH", 0x20)
        self.ptr(hashes, f"{what} Namensliste", hcount * 4)
        textures, count = self.read(p, "QH", 0x30)
        for i, tp in enumerate(self.pointers(textures, count, f"{what} Texturliste")):
            if not self.ptr(tp, f"{what} Textur {i}", 0x90):
                continue
            name, = self.read(tp, "Q", 0x28)
            self.string(name, f"{what} Textur {i} Name")
            _, height, _, stride, _, _, levels = self.read(tp, "HHHHIBB", 0x50)
            data, = self.read(tp, "Q", 0x70)
            length, size = 0, stride * height
            for _ in range(max(levels, 1)):
                length += size
                size //= 4
            self.ptr(data, f"{what} Textur {i} Pixeldaten", length, graphics=True)

    def shader_group(self, p, what):
        tex_dict, shaders, count = self.read(p, "QQH", 0x08)
        if self.ptr(tex_dict, f"{what} eingebettete Texturen", 0x40):
            self.texture_dict(tex_dict, f"{what} eingebettete Texturen")
        for i, sp in enumerate(self.pointers(shaders, count, f"{what} Shaderliste")):
            if not self.ptr(sp, f"{what} Shader {i}", 0x30):
                continue
            params, = self.read(sp, "Q", 0x00)
            pcount, = self.read(sp, "B", 0x10)
            if not pcount or not self.ptr(params, f"{what} Shader {i} Parameter", pcount * 16):
                continue
            for k in range(pcount):
                data_type, _, _, data = self.read(params, "BBHxxxxQ", k * 16)
                if data_type == 0:
                    if self.ptr(data, f"{what} Shader {i} Textur-Parameter", 0x50):
                        self.string(self.read(data, "Q", 0x28)[0], f"{what} Shader {i} Texturname")
                else:
                    self.ptr(data, f"{what} Shader {i} Wert", 16 * max(data_type, 1))

    def geometry(self, gp, what):
        vb, = self.read(gp, "Q", 0x18)
        ib, = self.read(gp, "Q", 0x38)
        bone_ids, = self.read(gp, "Q", 0x68)
        bone_count, = self.read(gp, "H", 0x72)
        self.ptr(bone_ids, f"{what} Knochen-IDs", bone_count * 2)
        # 0x78 (VertexDataPointer) wird auf dem PC nicht benutzt – alte Exporter schreiben dort Speicheradressen
        # ihres eigenen Prozesses hinein, das Spiel ignoriert es. Darum hier nicht prüfen.
        if self.ptr(vb, f"{what} Vertex-Buffer", 0x80):
            stride, = self.read(vb, "H", 0x08)
            data1, count = self.read(vb, "QI", 0x10)
            data2, = self.read(vb, "Q", 0x20)
            info, = self.read(vb, "Q", 0x30)
            self.ptr(data1, f"{what} Vertexdaten", stride * count)
            self.ptr(data2, f"{what} Vertexdaten 2", stride * count)
            self.ptr(info, f"{what} Vertex-Layout", 16)
        if self.ptr(ib, f"{what} Index-Buffer", 0x60):
            count, = self.read(ib, "I", 0x08)
            self.ptr(self.read(ib, "Q", 0x10)[0], f"{what} Indizes", count * 2)

    def models(self, header, what):
        if not self.ptr(header, what, 16):
            return
        pointer, count, capacity = self.read(header, "QHH")
        for i, mp in enumerate(self.pointers(pointer, max(count, capacity), f"{what} Liste")):
            if not self.ptr(mp, f"{what} Modell {i}", 0x30):
                continue
            geoms, gcount = self.read(mp, "QH", 0x08)
            bounds, mapping = self.read(mp, "QQ", 0x18)
            self.ptr(bounds, f"{what} Modell {i} Bounds", 32 * (gcount + 1 if gcount > 1 else gcount))
            self.ptr(mapping, f"{what} Modell {i} Shader-Zuordnung", gcount * 2)
            for k, gp in enumerate(self.pointers(geoms, gcount, f"{what} Modell {i} Geometrien")):
                if self.ptr(gp, f"{what} Modell {i} Geometrie {k}", 0x98):
                    self.geometry(gp, f"{what} Modell {i} Geometrie {k}")

    def skeleton(self, p, what):
        tags, tag_cap = self.read(p, "QH", 0x10)
        bones, inv, trans, parents, children = self.read(p, "QQQQQ", 0x20)
        bone_count, child_count = self.read(p, "HH", 0x5E)
        for i, tp in enumerate(self.pointers(tags, tag_cap, f"{what} Bone-Tags")):
            depth = 0
            while self.ptr(tp, f"{what} Bone-Tag {i}", 16) and depth < 64:
                tp, = self.read(tp, "Q", 0x08)
                depth += 1
        if self.ptr(bones, f"{what} Knochen", bone_count * 80):
            for i in range(bone_count):
                self.string(self.read(bones, "Q", i * 80 + 0x38)[0], f"{what} Knochen {i} Name")
        self.ptr(inv, f"{what} Matrizen (invers)", bone_count * 64)
        self.ptr(trans, f"{what} Matrizen", bone_count * 64)
        self.ptr(parents, f"{what} Eltern", bone_count * 2)
        self.ptr(children, f"{what} Kinder", child_count * 2)

    def drawable(self, p, what):
        self.ptr(self.read(p, "Q", 0x08)[0], f"{what} (Seiten-Info)", 20)
        group, skeleton = self.read(p, "QQ", 0x10)
        if self.ptr(group, f"{what} Shader-Gruppe", 0x40):
            self.shader_group(group, f"{what}")
        if self.ptr(skeleton, f"{what} Skelett", 0x70):
            self.skeleton(skeleton, f"{what} Skelett")
        lods = self.read(p, "QQQQ", 0x50)
        for name, header in zip(("High", "Med", "Low", "VLow"), lods):
            self.models(header, f"{what} LOD {name}")
        joints, = self.read(p, "Q", 0x90)
        if self.ptr(joints, f"{what} Gelenke", 0x40):
            j_rot, j_trans = self.read(joints, "QQ", 0x10)
            self.ptr(j_rot, f"{what} Gelenk-Limits")
            self.ptr(j_trans, f"{what} Gelenk-Limits")
        all_models, = self.read(p, "Q", 0xA0)
        self.ptr(all_models, f"{what} Modell-Block")
        self.string(self.read(p, "Q", 0xA8)[0], f"{what} Name")
        lights, lcount = self.read(p, "QH", 0xB0)
        self.ptr(lights, f"{what} Lichter", lcount * 0xA8)
        unk, bound = self.read(p, "QQ", 0xC0)
        self.ptr(unk, f"{what} Zusatzdaten")
        self.ptr(bound, f"{what} Kollision")

    def drawable_dict(self):
        root = SYSTEM_BASE
        self.file_base(root, "Datei")
        hashes, hcount = self.read(root, "QH", 0x20)
        self.ptr(hashes, "Namensliste", hcount * 4)
        drawables, count = self.read(root, "QH", 0x30)
        for i, dp in enumerate(self.pointers(drawables, count, "Drawable-Liste")):
            if self.ptr(dp, f"Drawable {i}", 0xD0):
                self.drawable(dp, f"Drawable {i}")


def check(data, kind):
    """Liste der gefundenen Probleme (leer = in Ordnung). kind: 'ydd', 'ytd' oder 'yld'."""
    try:
        c = _Checker(data)
    except (ValueError, struct.error) as exc:
        return [str(exc)]
    try:
        if kind == "ydd":
            c.drawable_dict()
        elif kind == "ytd":
            c.texture_dict(SYSTEM_BASE, "Textur-Datei")
        else:
            c.file_base(SYSTEM_BASE, "Datei")
    except struct.error:
        c.bad("Daten sind abgeschnitten oder ein Zeiger zeigt auf Unsinn")
    return c.problems


def check_file(path):
    kind = path.suffix.lower().lstrip(".")
    if kind not in ("ydd", "ytd", "yld"):
        return []
    try:
        return check(path.read_bytes(), kind)
    except OSError as exc:
        return [f"nicht lesbar: {exc}"]
