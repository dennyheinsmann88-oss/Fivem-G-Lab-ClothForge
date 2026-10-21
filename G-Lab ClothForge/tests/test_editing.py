"""Tests für das Löschen mit Platzhaltern (IDs bleiben stabil) und das Nachfüllen beim Anhängen."""

import json
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glab_cloth import builder, editing  # noqa: E402
from glab_cloth.builder import PLACEHOLDER_YTD, is_placeholder  # noqa: E402
from glab_cloth.preview import PreviewServer  # noqa: E402

DATA = Path(__file__).parent / "data" / "preview"


def _pack(folder, count, textures=3, tag=""):
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        ydd = folder / f"jbib_{i:03d}_u.ydd"
        ydd.write_bytes((DATA / "jbib_000_u.ydd").read_bytes() + f"{tag}{i}".encode())  # jedes Teil anders
        for letter in "abc"[:textures]:
            shutil.copy(DATA / "jbib_diff_000_a_uni.ytd", folder / f"jbib_diff_{i:03d}_{letter}_uni.ytd")


class EditingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        _pack(self.dir / "pack" / "female", 3)
        report = builder.build([self.dir / "pack"], self.dir / "out", "res", "res", log=lambda m: None)
        self.assertEqual(report.errors, [])
        self.res = self.dir / "out" / "res"
        self.jbib = self.res / "stream" / "female" / "jbib"

    def tearDown(self):
        self.tmp.cleanup()

    def ydd(self, n):
        return self.jbib / f"mp_f_freemode_01_res^jbib_{n:03d}_u.ydd"

    def ytd(self, n, letter):
        return self.jbib / f"mp_f_freemode_01_res^jbib_diff_{n:03d}_{letter}_uni.ytd"

    def numbers(self):
        drawables, _ = editing.resource_drawables(self.res)
        return [(d.number, d.placeholder, len(d.textures)) for d in drawables]

    def test_delete_middle_keeps_ids_and_undo_restores(self):
        original = self.ydd(1).read_bytes()
        change = editing.delete_drawable(self.res, self.ydd(1))
        self.assertTrue(is_placeholder(self.ydd(1)))
        self.assertTrue(is_placeholder(self.ytd(1, "a"), PLACEHOLDER_YTD))
        self.assertFalse(self.ytd(1, "b").exists())
        self.assertEqual(self.numbers(), [(0, False, 3), (1, True, 1), (2, False, 3)])
        trash = self.dir / "out" / "_geloescht" / "res"
        self.assertEqual(len(list(trash.rglob("*.ydd"))), 1)

        editing.undo(self.res, change)
        self.assertEqual(self.ydd(1).read_bytes(), original)
        self.assertEqual(self.numbers(), [(0, False, 3), (1, False, 3), (2, False, 3)])
        self.assertFalse(any(trash.rglob("*.ydd")))

    def test_delete_last_removes_completely(self):
        editing.delete_drawable(self.res, self.ydd(2))
        self.assertFalse(self.ydd(2).exists())
        self.assertEqual(self.numbers(), [(0, False, 3), (1, False, 3)])

    def test_delete_texture(self):
        editing.delete_texture(self.res, self.ytd(0, "b"))
        self.assertTrue(is_placeholder(self.ytd(0, "b"), PLACEHOLDER_YTD))
        editing.delete_texture(self.res, self.ytd(0, "c"))  # letzte Textur: ganz weg
        self.assertFalse(self.ytd(0, "c").exists())
        self.assertEqual(self.numbers()[0], (0, False, 2))
        editing.delete_texture(self.res, self.ytd(0, "b"))  # jetzt die letzte -> darf weg
        with self.assertRaises(editing.EditError):
            editing.delete_texture(self.res, self.ytd(0, "a"))  # einzige Textur

    def test_append_fills_placeholder(self):
        editing.delete_drawable(self.res, self.ydd(1))
        _pack(self.dir / "neu" / "female", 2, textures=1, tag="neu")
        report = builder.build([self.dir / "neu"], self.dir / "out", "res", "res", append=True, log=lambda m: None)
        self.assertEqual(report.errors, [])
        self.assertEqual(self.numbers(), [(0, False, 3), (1, False, 1), (2, False, 3), (3, False, 1)])
        self.assertFalse(is_placeholder(self.ydd(1)))

    def test_preview_api_delete_requires_header(self):
        server = PreviewServer()
        server.set_folders(self.res, None)
        url = server.start()
        try:
            item = next(i for i in server.items if i.number == 1)
            body = json.dumps({"id": item.id}).encode()
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(urllib.request.Request(url + "api/delete", body, method="POST"))
            self.assertEqual(ctx.exception.code, 403)
            req = urllib.request.Request(url + "api/delete", body, {"X-ClothTool": "1"}, method="POST")
            result = json.loads(urllib.request.urlopen(req).read())
            self.assertTrue(result["canUndo"])
            self.assertTrue(next(i for i in server.items if i.number == 1).placeholder)
            req = urllib.request.Request(url + "api/undo", b"{}", {"X-ClothTool": "1"}, method="POST")
            urllib.request.urlopen(req).read()
            self.assertFalse(next(i for i in server.items if i.number == 1).placeholder)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
