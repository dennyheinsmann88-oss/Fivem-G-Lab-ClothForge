"""Aufteilen einer Resource nach Kategorie: eigene Resource pro Typ, Nummern (IDs) bleiben gleich."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glab_cloth import builder  # noqa: E402
from glab_cloth.preview import build_catalog  # noqa: E402
from test_cloth_tool import _touch  # noqa: E402

QUIET = {"log": lambda m: None}


def _pack(root):
    files = ["female/jbib_000_u.ydd", "female/jbib_diff_000_a_uni.ytd", "female/jbib_001_u.ydd",
             "female/jbib_diff_001_a_uni.ytd", "female/lowr_000_u.ydd", "female/lowr_diff_000_a_uni.ytd",
             "female/hair_000_u.ydd", "female/hair_diff_000_a_uni.ytd", "male/p_head_000.ydd",
             "male/p_head_diff_000_a.ytd",
             "mp_f_freemode_01/uppr_015_r.ydd"]  # Ersatz (Original-Ordner)
    for f in files:
        _touch(root / f)


def _numbers(report):
    return sorted((d.gender, d.type_name, d.number) for d in report.drawables)


class SplitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        _pack(self.dir / "pack")
        self.out = self.dir / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def test_split_build(self):
        report = builder.build([self.dir / "pack"], self.out, "kleidung", "kl", split=True, **QUIET)
        self.assertEqual(report.errors, [])
        group = self.out / "[kleidung]"
        names = sorted(p.name for p in report.outputs)
        self.assertEqual(names, ["kleidung_ersatz", "kleidung_hair", "kleidung_jbib", "kleidung_lowr", "kleidung_p_head"])
        self.assertTrue((group / "kleidung_jbib" / "stream" / "mp_f_freemode_01_kl_jbib.ymt").is_file())
        self.assertTrue((group / "kleidung_jbib" / "stream" / "female" / "jbib" /
                         "mp_f_freemode_01_kl_jbib^jbib_001_u.ydd").is_file())
        self.assertTrue((group / "kleidung_p_head" / "stream" / "mp_m_freemode_01_kl_p_head.ymt").is_file())
        self.assertIn("ensure kleidung_jbib", (group / "ensure.cfg").read_text())
        self.assertEqual(builder.read_group(group), {"name": "kleidung", "dlc": "kl"})
        # 3D-Vorschau kann den ganzen Ordner lesen und kennt die Resource jedes Teils
        items = build_catalog(group)
        self.assertEqual(len(items), 6)
        self.assertTrue(all(i.resource.parent == group for i in items))

        # Anhängen: neues Oberteil landet in kleidung_jbib, alte Nummern bleiben
        _touch(self.dir / "neu" / "female" / "jbib_000_u.ydd")
        _touch(self.dir / "neu" / "female" / "jbib_diff_000_a_uni.ytd")
        report = builder.build([self.dir / "neu"], self.out, "kleidung", "kl", split=True, append=True, **QUIET)
        self.assertEqual(report.errors, [])
        self.assertEqual([d.number for d in report.drawables if d.type_name == "jbib"], [0, 1, 2])

    def test_convert_existing_resource_keeps_ids(self):
        single = builder.build([self.dir / "pack"], self.out, "kleidung", "kl", **QUIET)
        before = _numbers(single)
        report = builder.build([], self.out, "kleidung", "kl", split=True, append=True, **QUIET)
        self.assertEqual(report.errors, [])
        self.assertEqual(_numbers(report), before)
        self.assertFalse((self.out / "kleidung").exists())  # alte Resource weggeräumt …
        self.assertTrue(any((self.out / "_original").iterdir()))  # … aber gesichert
        self.assertTrue((self.out / "[kleidung]" / "kleidung_ersatz" / "stream" / "replacements").is_dir())


if __name__ == "__main__":
    unittest.main()
