"""Los paquetes de personaje: válidos para el cerebro en los dos idiomas y con una cara que existe."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from virtual_robot import characters  # noqa: E402

brain_characters, brain_faces, _ = characters._brain()


class PackagesTest(unittest.TestCase):
    def test_rocky_first_and_jarvis_present(self):
        ids = [p["id"] for p in characters.packages()]
        self.assertEqual(ids[0], "rocky")
        self.assertIn("jarvis", ids)

    def test_every_package_is_valid_for_the_brain(self):
        for pkg in characters.packages():
            with self.subTest(pkg=pkg["id"]):
                brain_faces.load(pkg.get("face") or "rocky")          # la cara existe y es válida
                if pkg.get("builtin"):
                    continue
                for lang in ("en", "es"):
                    ch = brain_characters.clean(characters.character_for(pkg, lang))
                    self.assertEqual(ch["name"], pkg["name"])

    def test_spanish_overrides(self):
        jarvis = next(p for p in characters.packages() if p["id"] == "jarvis")
        es = brain_characters.clean(characters.character_for(jarvis, "es"))
        en = brain_characters.clean(characters.character_for(jarvis, "en"))
        self.assertEqual(es["lines"]["wake"], "¿Sí, señor?")
        self.assertEqual(en["lines"]["wake"], "Yes, sir?")
        self.assertIn("oye jarvis", es["wake_words"])
        self.assertIn("hey jarvis", es["wake_words"])          # las inglesas siguen valiendo
        self.assertNotIn("oye jarvis", en["wake_words"])

    def test_broken_package_is_rejected(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "otro" / "package.json"
            p.parent.mkdir()
            p.write_text(json.dumps({"id": "distinto", "name": "X"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                characters.load_package(p)


if __name__ == "__main__":
    unittest.main()
