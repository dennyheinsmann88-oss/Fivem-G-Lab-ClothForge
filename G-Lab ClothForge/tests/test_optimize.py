"""Tests fürs Verkleinern der Texturen (Mip-Stufen weglassen, Grafik-Teil neu packen).

opt_small.ytd / opt_emb.ydd wurden mit CodeWalker.Core erzeugt; opt_reference.json ist CodeWalkers Auslesung.
Beim Entwickeln wurde zusätzlich mit CodeWalker geprüft, dass die neue Stufe 0 pixelgenau der alten Stufe 1 entspricht.
"""

import json
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glab_cloth import builder  # noqa: E402
from glab_cloth.optimize import (_flags_count, _mip_sizes, analyze, assign_graphics, estimate,  # noqa: E402
                                 optimize_folder, scan_folder, shrink)
from glab_cloth.resource import Resource, read_ydd, read_ytd  # noqa: E402
from glab_cloth.ymt import _flags_size  # noqa: E402

DATA = Path(__file__).parent / "data" / "preview"
REF = json.loads((DATA / "opt_reference.json").read_text())
LIMIT = {"diffuse": 128, "normal": 128, "specular": 128}


def _mips(tex_info, res):
    sizes = _mip_sizes(tex_info.stride, tex_info.height, tex_info.levels)
    start = res.offset(tex_info.data_ptr)
    return res.data[start:start + sum(sizes)], sizes


class ShrinkTest(unittest.TestCase):
    def check(self, name, kind):
        data = (DATA / name).read_bytes()
        before = analyze(data, kind)
        new, changes = shrink(data, kind, LIMIT)
        self.assertIsNotNone(new)
        after = analyze(new, kind)
        self.assertLess(after.physical, before.physical)
        self.assertEqual(after.physical, estimate(before, LIMIT))

        old_res, new_res = Resource(data), Resource(new)
        reference = {t["name"]: t for t in REF[name]["0"]}
        for old, cur in zip(before.textures, after.textures):
            ref = reference[old.name]
            self.assertEqual((old.width, old.height, old.levels), (ref["width"], ref["height"], ref["levels"]))
            k = 0
            while max(old.width, old.height) >> k > 128:
                k += 1
            self.assertEqual((cur.width, cur.height, cur.levels), (old.width >> k, old.height >> k, old.levels - k))
            old_bytes, sizes = _mips(old, old_res)
            new_bytes, _ = _mips(cur, new_res)
            self.assertEqual(new_bytes, old_bytes[sum(sizes[:k]):])  # neue Stufe 0 = alte Stufe k

        # Seitenzahl im PagesInfo-Block passt zu den neuen Flags
        _, _, _, gfx_flags = struct.unpack_from("<IiII", new)
        pages_ptr, = struct.unpack_from("<Q", new_res.data, 0x08)
        self.assertEqual(new_res.data[new_res.offset(pages_ptr) + 9], _flags_count(gfx_flags & 0x0FFFFFFF))
        return data, new, changes

    def test_ytd(self):
        _, new, changes = self.check("opt_small.ytd", "ytd")
        self.assertEqual(len(changes), 2)  # tiny_s (64 px) bleibt
        self.assertEqual([t.width for t in read_ytd(new)], [64, 128, 128])

    def test_ydd_embedded_texture_model_unchanged(self):
        data, new, _ = self.check("opt_emb.ydd", "ydd")
        a, b = read_ydd(data)[0], read_ydd(new)[0]
        self.assertEqual([[g.positions for g in m] for m in a.best_lod()], [[g.positions for g in m] for m in b.best_lod()])

    def test_uncompressed_without_mips_is_resampled(self):
        data = (DATA / "opt_raw.ytd").read_bytes()  # 256×128 A8R8G8B8, nur eine Stufe (mit CodeWalker erzeugt)
        old = analyze(data, "ytd").textures[0]
        self.assertEqual((old.format, old.levels), ("A8R8G8B8", 1))
        new, changes = shrink(data, "ytd", {"normal": 64, "diffuse": 64, "specular": 64})
        self.assertIn("herunterrechnet", changes[0])
        cur = analyze(new, "ytd").textures[0]
        self.assertEqual((cur.width, cur.height, cur.levels, cur.stride), (64, 32, 1, 256))
        src = Resource(data).bytes(old.data_ptr, old.stride * old.height)
        expect = b"".join(src[(y * 4 * 256 + x * 4) * 4:(y * 4 * 256 + x * 4) * 4 + 4] for y in range(32) for x in range(64))
        self.assertEqual(Resource(new).bytes(cur.data_ptr, 64 * 32 * 4), expect)

    def test_nothing_to_do(self):
        new, _ = shrink((DATA / "opt_small.ytd").read_bytes(), "ytd", {"diffuse": 4096, "normal": 4096, "specular": 4096})
        self.assertIsNone(new)

    def test_graphics_pages_fit(self):
        lengths = [5_000_000, 1_300_000, 700_000, 90_000, 4_096, 300]
        positions, flags = assign_graphics(lengths)
        self.assertGreaterEqual(_flags_size(flags), max(p + n for p, n in zip(positions, lengths)))
        spans = sorted(zip(positions, lengths))
        for (p1, n1), (p2, _) in zip(spans, spans[1:]):
            self.assertLessEqual(p1 + n1, p2)  # keine Überlappung


class ValidateTest(unittest.TestCase):
    def test_unused_vertex_data_field_is_not_a_defect(self):
        """Feld 0x78 der Geometrie enthält bei alten Exportern Müll – das Spiel ignoriert es (kein Fehlalarm)."""
        import zlib
        from glab_cloth.validate import check
        data = (DATA / "jbib_000_u.ydd").read_bytes()
        res = Resource(data)
        body = bytearray(res.data)
        dp, = struct.unpack_from("<Q", body, res.offset(struct.unpack_from("<Q", body, 0x30)[0]))
        lst, = struct.unpack_from("<Q", body, res.offset(struct.unpack_from("<Q", body, res.offset(dp) + 0x50)[0]))
        model, = struct.unpack_from("<Q", body, res.offset(lst))
        geoms, = struct.unpack_from("<Q", body, res.offset(model) + 8)
        gp, = struct.unpack_from("<Q", body, res.offset(geoms))
        struct.pack_into("<Q", body, res.offset(gp) + 0x78, 0x0690526C)
        comp = zlib.compressobj(6, zlib.DEFLATED, -15)
        broken_field = data[:16] + comp.compress(bytes(body)) + comp.flush()
        self.assertEqual(check(broken_field, "ydd"), [])
        struct.pack_into("<Q", body, res.offset(gp) + 0x18, 0x0690526C)  # Vertex-Buffer dagegen schon
        comp = zlib.compressobj(6, zlib.DEFLATED, -15)
        self.assertTrue(check(data[:16] + comp.compress(bytes(body)) + comp.flush(), "ydd"))


class IntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        pack = self.dir / "pack" / "female"
        pack.mkdir(parents=True)
        shutil.copy(DATA / "opt_emb.ydd", pack / "jbib_000_u.ydd")
        shutil.copy(DATA / "opt_small.ytd", pack / "jbib_diff_000_a_uni.ytd")

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_with_optimize(self):
        report = builder.build([self.dir / "pack"], self.dir / "out", "res", "res", optimize=LIMIT, log=lambda m: None)
        self.assertEqual(report.errors, [])
        self.assertTrue(any("Texturen verkleinert: 2 Dateien" in n for n in report.notes))
        rows = scan_folder(self.dir / "out" / "res", LIMIT)
        self.assertTrue(rows and all(r.estimate == r.info.physical for r in rows))  # nichts mehr zu tun

    def test_optimize_folder_keeps_backup(self):
        folder = self.dir / "pack"
        original = (folder / "female" / "jbib_000_u.ydd").read_bytes()
        changed, before, after, backup = optimize_folder(folder, LIMIT, log=lambda m: None)
        self.assertEqual(changed, 2)
        self.assertLess(after, before)
        self.assertEqual((backup / "female" / "jbib_000_u.ydd").read_bytes(), original)
        self.assertTrue(str(backup).startswith(str(self.dir / "_original" / "pack")))


if __name__ == "__main__":
    unittest.main()
