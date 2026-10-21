"""Tests:  python -m unittest discover -s tests   (im Ordner G_Lab_ClothTool)"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glab_cloth import builder, naming  # noqa: E402
from glab_cloth.ymt import YmtDrawable, build_ymt, read_system_data  # noqa: E402

DATA = Path(__file__).parent / "data"


class YmtTest(unittest.TestCase):
    def test_matches_codewalker_reference(self):
        # Referenz erzeugt mit CodeWalker.Core (MetaBuilder/ResourceBuilder) nach grzyClothTool-Logik
        drawables = [
            YmtDrawable(False, 3, 0, 1, skin=True),
            YmtDrawable(False, 4, 0, 3, cloth=True),
            YmtDrawable(False, 4, 1, 1),
            YmtDrawable(False, 11, 0, 26),
            YmtDrawable(False, 11, 1, 2),
            YmtDrawable(True, 0, 0, 2),
            YmtDrawable(True, 0, 1, 1),
            YmtDrawable(True, 6, 0, 4),
        ]
        ours = read_system_data(build_ymt(drawables, "testdlc"))
        reference = read_system_data((DATA / "codewalker_reference.ymt").read_bytes())
        self.assertEqual(ours, reference)


class NamingTest(unittest.TestCase):
    def test_parse_variants(self):
        root = Path("/packs")
        cf = naming.parse(root / "x" / "mp_f_freemode_01_cool^JBIB_012_U.ydd", root)
        self.assertEqual((cf.kind, cf.type_name, cf.number, cf.gender, cf.race), ("ydd", "jbib", 12, "f", "u"))
        cf = naming.parse(root / "Herren" / "lowr_diff_003_b_uni.ytd", root)
        self.assertEqual((cf.kind, cf.letter, cf.gender), ("ytd", "b", "m"))
        cf = naming.parse(root / "female" / "p_eyes_diff_001_c.ytd", root)
        self.assertEqual((cf.is_prop, cf.type_name, cf.letter, cf.gender), (True, "p_eyes", "c", "f"))
        self.assertIsNone(naming.parse(root / "hoodie.ydd", root))
        self.assertIsNone(naming.parse(root / "unknown" / "jbib_000_u.ydd", root).gender)

    def test_output_names(self):
        ydd, ytds, yld = naming.output_names("m", "glab", False, "uppr", 7, "r", ["a", "b"])
        self.assertEqual(ydd, "mp_m_freemode_01_glab^uppr_007_r.ydd")
        self.assertEqual(ytds, ["mp_m_freemode_01_glab^uppr_diff_007_a_whi.ytd",
                                "mp_m_freemode_01_glab^uppr_diff_007_b_whi.ytd"])
        self.assertEqual(yld, "mp_m_freemode_01_glab^uppr_007_r.yld")
        ydd, ytds, _ = naming.output_names("f", "glab", True, "p_head", 0, "u", ["a"])
        self.assertEqual((ydd, ytds), ("mp_f_freemode_01_p_glab^p_head_000.ydd",
                                       ["mp_f_freemode_01_p_glab^p_head_diff_000_a.ytd"]))


_VALID = {".ydd": DATA / "preview" / "jbib_000_u.ydd", ".ytd": DATA / "preview" / "jbib_diff_000_a_uni.ytd",
          ".yld": DATA / "preview" / "jbib_diff_000_a_uni.ytd"}


def _touch(path):
    """Gültige GTA-Datei (mit CodeWalker erzeugt) + zufällige Bytes am Ende, damit jede Datei anders ist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    base = _VALID.get(path.suffix.lower())
    path.write_bytes((base.read_bytes() if base else b"") + os.urandom(32))


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_and_append(self):
        pack = self.dir / "pack" / "male"
        for name in ["jbib_000_u.ydd", "jbib_diff_000_a_uni.ytd", "jbib_diff_000_b_uni.ytd",
                     "jbib_005_u.ydd", "jbib_diff_005_a_uni.ytd", "p_head_002.ydd", "p_head_diff_002_a.ytd"]:
            _touch(pack / name)
        out = self.dir / "out"
        report = builder.build([self.dir / "pack"], out, "glab_clothes", "glab", log=lambda m: None)
        self.assertEqual(report.errors, [])
        stream = out / "glab_clothes" / "stream"
        self.assertTrue((stream / "male" / "jbib" / "mp_m_freemode_01_glab^jbib_001_u.ydd").is_file())
        self.assertTrue((stream / "male" / "p_head" / "mp_m_freemode_01_p_glab^p_head_000.ydd").is_file())
        self.assertTrue((stream / "mp_m_freemode_01_glab.ymt").is_file())
        self.assertIn("SHOP_PED_APPAREL_META_FILE", (out / "glab_clothes" / "fxmanifest.lua").read_text())

        more = self.dir / "more" / "male"
        _touch(more / "jbib_000_u.ydd")
        _touch(more / "jbib_diff_000_a_uni.ytd")
        report = builder.build([self.dir / "more", self.dir / "pack"], out, "glab_clothes", "glab",
                               append=True, log=lambda m: None)
        self.assertEqual(report.errors, [])
        jbibs = sorted(d.number for d in report.drawables if d.type_name == "jbib")
        self.assertEqual(jbibs, [0, 1, 2])  # alte Nummern bleiben, Duplikate aus "pack" werden erkannt
        self.assertEqual(sum("Duplikat" in w for w in report.warnings), 3)

    def test_replacement_files_are_kept(self):
        for race in ("whi", "bla"):
            _touch(self.dir / "eup" / f"mp_fm_skin_f_up_{race}.ytd")
        _touch(self.dir / "eup" / "something_else.ydd")
        out = self.dir / "out"
        report = builder.build([self.dir / "eup"], out, "eup", "eup", log=lambda m: None)
        self.assertEqual(report.errors, [])
        repl = out / "eup" / "stream" / "replacements"
        self.assertTrue((repl / "mp_fm_skin_f_up_whi.ytd").is_file())
        self.assertFalse((repl / "something_else.ydd").exists())

        report = builder.build([], out, "eup", "eup", append=True, keep_unknown=True, log=lambda m: None)
        self.assertEqual(len(report.replacements), 2)  # bleiben beim Anhängen erhalten

    def test_replace_mode_keeps_numbers(self):
        mod = self.dir / "nude" / "mp_f_freemode_01"
        for name in ["uppr_015_r.ydd", "uppr_diff_015_a_whi.ytd", "p_head_003.ydd"]:
            _touch(mod / name)
        _touch(self.dir / "nude" / "mp_f_freemode_01^jbib_015_u.ydd")
        out = self.dir / "out"
        report = builder.build([], out, "nude", "nude", default_gender="f", replace_inputs=[self.dir / "nude"],
                               log=lambda m: None)
        self.assertEqual(report.errors, [])
        repl = out / "nude" / "stream" / "replacements" / "female"
        self.assertTrue((repl / "uppr" / "mp_f_freemode_01^uppr_015_r.ydd").is_file())
        self.assertTrue((repl / "uppr" / "mp_f_freemode_01^uppr_diff_015_a_whi.ytd").is_file())
        self.assertTrue((repl / "p_head" / "mp_f_freemode_01_p^p_head_003.ydd").is_file())
        self.assertTrue((repl / "jbib" / "mp_f_freemode_01^jbib_015_u.ydd").is_file())
        self.assertFalse(list((out / "nude" / "stream").glob("*.ymt")))  # Ersatz braucht keine YMT

    def test_auto_detects_addon_and_replacement(self):
        import zipfile
        mods = self.dir / "Mods"
        mods.mkdir()
        with zipfile.ZipFile(mods / "body.zip", "w") as z:
            z.writestr("fast install/mp_f_freemode_01/uppr_015_r.ydd", _VALID[".ydd"].read_bytes())
            z.writestr("fast install/mp_f_freemode_01/uppr_diff_015_a_whi.ytd", _VALID[".ytd"].read_bytes())
        _touch(mods / "hoodies" / "female" / "jbib_000_u.ydd")
        _touch(mods / "hoodies" / "female" / "jbib_diff_000_a_uni.ytd")
        _touch(mods / "eup" / "mp_f_freemode_01_mp_f_eup^jbib_000_u.ydd")       # bringt eigene YMT mit -> Addon
        _touch(mods / "eup" / "mp_f_freemode_01_mp_f_eup^jbib_diff_000_a_uni.ytd")
        _touch(mods / "eup" / "mp_f_freemode_01_mp_f_eup.ymt")
        _touch(mods / "retex" / "mp_f_freemode_01_mp_f_bikerdlc_01^jbib_003_u.ydd")  # ohne YMT -> Ersatz
        report = builder.build([mods], self.dir / "out", "alles", "alles", log=lambda m: None)
        self.assertEqual(report.errors, [])
        self.assertEqual(len(report.drawables), 2)
        names = sorted(rel.rpartition("/")[2] for _, rel in report.replacements)
        self.assertEqual(names, ["mp_f_freemode_01^uppr_015_r.ydd", "mp_f_freemode_01^uppr_diff_015_a_whi.ytd",
                                 "mp_f_freemode_01_mp_f_bikerdlc_01^jbib_003_u.ydd"])

    def test_drawable_without_textures_replaces_original(self):
        body = self.dir / "realnakedbody"
        _touch(body / "textures" / "mp_fm_skin_f_up_whi.ytd")   # Pack ist eindeutig weiblich
        _touch(body / "fast install" / "uppr_013_r.ydd")
        _touch(body / "ordered by sizes" / "big" / "uppr_013_r.ydd")
        report = builder.build([body], self.dir / "out", "body", "body", log=lambda m: None)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.drawables, [])
        rels = {rel: src for src, rel in report.replacements}
        self.assertEqual(rels["female/uppr/mp_f_freemode_01^uppr_013_r.ydd"], body / "fast install" / "uppr_013_r.ydd")
        self.assertTrue(any("Mehrere Varianten" in w for w in report.warnings))

    def test_defective_files_are_not_copied(self):
        pack = self.dir / "pack" / "female"
        _touch(pack / "jbib_000_u.ydd")
        _touch(pack / "jbib_diff_000_a_uni.ytd")
        (pack / "jbib_001_u.ydd").write_bytes(os.urandom(64))   # kaputt
        _touch(pack / "jbib_diff_001_a_uni.ytd")
        _touch(pack / "jbib_002_u.ydd")
        _touch(pack / "jbib_diff_002_a_uni.ytd")
        (pack / "jbib_diff_002_b_uni.ytd").write_bytes(b"RSC7" + os.urandom(60))  # kaputte Textur
        out = self.dir / "out"
        report = builder.build([self.dir / "pack"], out, "res", "res", log=lambda m: None)
        self.assertEqual(report.errors, [])
        self.assertEqual(len(report.drawables), 2)
        self.assertEqual(sum("DEFEKT" in w for w in report.warnings), 2)
        jbib = out / "res" / "stream" / "female" / "jbib"
        self.assertEqual(sorted(p.name.split("^")[1] for p in jbib.iterdir()),
                         ["jbib_000_u.ydd", "jbib_001_u.ydd", "jbib_diff_000_a_uni.ytd", "jbib_diff_001_a_uni.ytd"])

        # schon in der Resource und defekt -> Platzhalter statt Lücke
        (jbib / "mp_f_freemode_01_res^jbib_000_u.ydd").write_bytes(os.urandom(64))
        report = builder.build([], out, "res", "res", append=True, log=lambda m: None)
        self.assertEqual([(d.number, d.placeholder) for d in report.drawables], [(0, True), (1, False)])

    def test_split_after_256(self):
        drawables = [builder.Drawable("m", False, "jbib", "u", Path(f"{i}.ydd"), [Path("a.ytd")], None, Path("."))
                     for i in range(300)]
        dlcs = builder.assign_numbers(drawables, "glab")
        self.assertEqual(dlcs, ["glab", "glab_2"])
        self.assertEqual((drawables[255].dlc, drawables[255].number), ("glab", 255))
        self.assertEqual((drawables[256].dlc, drawables[256].number), ("glab_2", 0))

    def test_refuses_foreign_folder(self):
        (self.dir / "out" / "fremd").mkdir(parents=True)
        (self.dir / "out" / "fremd" / "fxmanifest.lua").write_text("fx_version 'cerulean'")
        _touch(self.dir / "pack" / "male" / "jbib_000_u.ydd")
        report = builder.build([self.dir / "pack"], self.dir / "out", "fremd", "glab", log=lambda m: None)
        self.assertTrue(report.errors)
        self.assertTrue((self.dir / "out" / "fremd" / "fxmanifest.lua").is_file())


if __name__ == "__main__":
    unittest.main()
