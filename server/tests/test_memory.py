"""brain/memory.py: guardar, no duplicar, olvidar por número o por texto, fechas y el bloque del prompt."""

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from brain import memory


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "memory.json"
        self.addCleanup(self.dir.cleanup)

    def facts(self):
        return memory.load(self.path)["facts"]

    def test_remember_and_no_duplicates(self):
        out = memory.remember({"fact": "Raúl tiene tres gatas.", "about": "Raúl"}, self.path, date(2026, 11, 16))
        self.assertIn("#1", out)
        memory.remember({"fact": "raul tiene tres gatas"}, self.path)          # mismo dato, sin tildes ni punto
        self.assertEqual(len(self.facts()), 1)
        self.assertEqual(self.facts()[0]["saved"], "2026-11-16")
        self.assertEqual(self.facts()[0]["about"], "Raúl")

    def test_dates_are_checked(self):
        memory.remember({"fact": "Vacaciones.", "date": "2026-12-16"}, self.path)
        memory.remember({"fact": "Algo raro.", "date": "dentro de un mes"}, self.path)
        dates = [f["date"] for f in self.facts()]
        self.assertEqual(dates, ["2026-12-16", None])

    def test_forget_by_number_and_by_words(self):
        memory.remember({"fact": "Raúl tiene una hija."}, self.path)
        memory.remember({"fact": "Raúl se va de vacaciones a Asturias."}, self.path)
        memory.remember({"fact": "A Raúl le gusta el café solo."}, self.path)
        self.assertIn("hija", memory.forget({"fact": "#1"}, self.path))
        self.assertIn("Asturias", memory.forget({"fact": "vacaciones"}, self.path))
        self.assertEqual([f["text"] for f in self.facts()], ["A Raúl le gusta el café solo."])
        self.assertIn("nothing forgotten", memory.forget({"fact": "perros"}, self.path))

    def test_empty_and_broken_file(self):
        self.assertIn("Nothing saved", memory.remember({"fact": " "}, self.path))
        self.path.write_text("{roto", encoding="utf-8")
        self.assertEqual(memory.load(self.path)["facts"], [])

    def test_prompt_block(self):
        self.assertIn("(nothing yet)", memory.prompt_block(self.path))
        memory.remember({"fact": "Vacaciones en Asturias.", "about": "Raúl", "date": "2026-12-16", "private": True},
                        self.path)
        block = memory.prompt_block(self.path)
        self.assertIn("#1 Vacaciones en Asturias. (about Raúl, date 2026-12-16, private)", block)
        self.assertIn("Never save passwords", block)
        self.assertIn("your human is Raúl", memory.prompt_block(self.path, human="Raúl"))
        self.assertIn("mi humano", memory.prompt_block(self.path, human="friend"))

    def test_saving_out_loud_is_not_spoken(self):
        from brain import thinking
        self.assertTrue(thinking._REASONING.search("I should save this with an absolute date."))
        self.assertTrue(thinking._REASONING.search("One month from 2026-11-16 is 2026-12-16."))
        self.assertFalse(thinking._REASONING.search("Asombroso, tres gatas."))
        self.assertFalse(thinking._REASONING.search("Faltan 30 días, el 16 de diciembre."))

    def test_now_note(self):
        self.assertEqual(memory.now_note(datetime(2026, 11, 16, 21, 5)), "(Now: Monday 2026-11-16 21:05.)")


if __name__ == "__main__":
    unittest.main()
