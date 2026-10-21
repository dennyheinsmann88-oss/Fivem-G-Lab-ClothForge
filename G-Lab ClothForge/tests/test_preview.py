"""Tests für das Lesen von .ydd/.ytd und den Vorschau-Server.

Die Testdateien in tests/data/preview wurden mit CodeWalker.Core erzeugt, die .json daneben ist
CodeWalkers eigene Auslesung derselben Datei (Positionen, UVs, Indizes, Texturpixel).
"""

import base64
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glab_cloth.preview import PreviewServer, build_catalog  # noqa: E402
from glab_cloth.resource import read_ydd, read_ytd  # noqa: E402

DATA = Path(__file__).parent / "data" / "preview"
WEB = Path(__file__).resolve().parents[1] / "glab_cloth" / "preview_web"


def _close(a, b):
    return len(a) == len(b) and all(abs(x - y) < 1e-3 for x, y in zip(a, b))


class ReadTest(unittest.TestCase):
    def test_ydd_matches_codewalker(self):
        for name in ("jbib_000_u.ydd", "p_head_000.ydd"):
            reference = json.loads((DATA / f"{name}.json").read_text())
            drawables = read_ydd((DATA / name).read_bytes())
            self.assertEqual(len(drawables), len(reference))
            for ref, d in zip(reference, drawables):
                self.assertEqual(d.name, ref["name"])
                self.assertEqual(d.textures, ref["shaders"])
                for lod in ("high", "med", "low", "vlow"):
                    ref_models = ref["lods"].get(lod, [])
                    self.assertEqual(len(d.lods[lod]), len(ref_models), f"{name} {lod}")
                    for ref_geoms, geoms in zip(ref_models, d.lods[lod]):
                        for rg, g in zip(ref_geoms, geoms):
                            self.assertTrue(_close(g.positions, rg["positions"]))
                            self.assertTrue(_close(g.uvs, rg["uvs"]))
                            self.assertEqual(g.indices, rg["indices"])

    def test_ytd_matches_codewalker(self):
        for name in ("jbib_diff_000_a_uni.ytd", "p_head_diff_000_a.ytd", "multi.ytd"):
            reference = json.loads((DATA / f"{name}.json").read_text())
            textures = read_ytd((DATA / name).read_bytes())
            self.assertEqual([(t.name, t.width, t.height) for t in textures],
                             [(r["name"], r["width"], r["height"]) for r in reference])

    @unittest.skipUnless(shutil.which("node"), "node nicht installiert")
    def test_browser_texture_decoder_matches_codewalker(self):
        cases = []
        for name in ("jbib_diff_000_a_uni.ytd", "p_head_diff_000_a.ytd", "multi.ytd"):
            reference = json.loads((DATA / f"{name}.json").read_text())
            for ref, t in zip(reference, read_ytd((DATA / name).read_bytes())):
                cases.append({"format": t.format, "w": t.width, "h": t.height,
                              "data": base64.b64encode(t.data).decode(), "ref": ref["pixels"]})
        script = f"""
import {{ decodeTexture }} from {json.dumps((WEB / 'textures.js').as_uri())};
let worst = 0;
for (const c of {json.dumps(cases)}) {{
  const out = decodeTexture(c.format, c.w, c.h, Buffer.from(c.data, "base64")).rgba;
  const px = Buffer.from(c.ref, "base64");  // CodeWalker liefert BGRA
  for (let p = 0; p < c.w * c.h; p++) {{
    const exp = [px[p * 4 + 2], px[p * 4 + 1], px[p * 4], px[p * 4 + 3]];
    for (let k = 0; k < 4; k++) worst = Math.max(worst, Math.abs(exp[k] - out[p * 4 + k]));
  }}
}}
console.log(worst);
"""
        out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
        self.assertLessEqual(int(out.stdout.strip()), 2)  # nur Rundungsunterschiede


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        base = self.dir / "base" / "mp_f_freemode_01"
        base.mkdir(parents=True)
        shutil.copy(DATA / "jbib_000_u.ydd", base / "uppr_015_r.ydd")
        shutil.copy(DATA / "jbib_diff_000_a_uni.ytd", base / "uppr_diff_015_a_whi.ytd")
        shutil.copy(DATA / "jbib_000_u.ydd", base / "lowr_000_r.ydd")
        shutil.copy(DATA / "jbib_diff_000_a_uni.ytd", base / "lowr_diff_000_a_whi.ytd")
        stream = self.dir / "res" / "stream"
        addon = stream / "female" / "jbib"
        addon.mkdir(parents=True)
        shutil.copy(DATA / "jbib_000_u.ydd", addon / "mp_f_freemode_01_glab^jbib_000_u.ydd")
        for letter in "ab":
            shutil.copy(DATA / "jbib_diff_000_a_uni.ytd", addon / f"mp_f_freemode_01_glab^jbib_diff_000_{letter}_uni.ytd")
        repl = stream / "replacements" / "female" / "uppr"
        repl.mkdir(parents=True)
        shutil.copy(DATA / "p_head_000.ydd", repl / "mp_f_freemode_01^uppr_015_r.ydd")  # Body-Mod ohne Texturen

    def tearDown(self):
        self.tmp.cleanup()

    def test_catalog_combines_base_addon_and_replacement(self):
        items = build_catalog(self.dir / "res", self.dir / "base")
        summary = sorted((i.source, i.type_name, i.number, i.dlc, tuple(sorted(i.textures))) for i in items)
        self.assertEqual(summary, [
            ("addon", "jbib", 0, "glab", ("a", "b")),
            ("basis", "lowr", 0, "", ("a",)),
            ("ersatz", "uppr", 15, "", ("a",)),  # ersetzt die Basis und nutzt ihre Textur
        ])

    def test_server_endpoints(self):
        server = PreviewServer()
        server.set_folders(self.dir / "res", self.dir / "base")
        url = server.start()
        try:
            def get(path):
                with urllib.request.urlopen(url + path) as r:
                    return r.read()
            catalog = json.loads(get("api/catalog"))
            addon = next(i for i in catalog["items"] if i["source"] == "addon")
            model = json.loads(get(f"api/model?id={addon['id']}"))
            self.assertEqual(len(model["geometries"]), 2)
            texture = json.loads(get(f"api/texture?id={addon['id']}&letter=b"))
            self.assertEqual((texture["format"], texture["width"]), ("DXT1", 64))
            self.assertIn(b"importmap", get(""))
            self.assertTrue(get("vendor/three.module.min.js"))
            with self.assertRaises(urllib.error.HTTPError):
                get("../preview.py")
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
