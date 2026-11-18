"""brain/identity.py sin modelos: comparación, altas (sin contaminar), notas, privados en memory.py y bajas."""

import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from brain import identity, memory


def vec(seed: int, noise: float = 0.0, base: int | None = None) -> np.ndarray:
    """Una huella: la de `seed`, o la de `base` con un poco de ruido (otra foto de la misma cara)."""
    v = np.random.default_rng(seed if base is None else base).normal(size=128)
    if noise:
        v = v + np.random.default_rng(seed + 1000).normal(scale=noise, size=128)
    return identity.unit(v)


class FakeEyes:
    def __init__(self):
        self.jpeg, self.frame_at = b"jpeg", time.time()


class IdentityTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "identity.json"
        self.mem = Path(self.dir.name) / "memory.json"
        self.idn = identity.Identity(FakeEyes(), self.path)
        self.idn.ready = True
        self.idn._frame_at = time.time()
        self.addCleanup(setattr, memory, "audience", memory.audience)
        self.addCleanup(setattr, memory, "extra_prompt", memory.extra_prompt)

    def enroll(self, name, kind, vecs, before=()):
        self.idn._recent[kind].clear()   # quien estaba delante en el alta anterior ya se fue
        for v in before:
            self.idn._sighting(kind, [(v, 0.1)], time.time())
        out = self.idn.remember_face({"name": name, "kind": kind})
        for v in vecs:
            self.idn._enrolling["last"] = 0   # sin esperar SAMPLE_SPACING
            self.idn._sighting(kind, [(v, 0.1)], time.time())
        self.idn._enrolling["until"] = 0
        self.idn._finish_enrolment(time.time())
        return out

    def test_match(self):
        gallery = {"Raúl": [vec(1)], "Ana": [vec(2)]}
        self.assertEqual(identity.recognize(vec(0, 0.3, base=1), gallery, "person"), "Raúl")
        self.assertIsNone(identity.recognize(vec(3), gallery, "person"))
        self.assertIsNone(identity.recognize(vec(1), {}, "person"))
        # gatos: hace falta parecido alto y ganar con margen
        self.assertIsNone(identity.recognize(vec(1), {"Luna": [vec(1)], "Mia": [vec(1)]}, "cat"))
        self.assertEqual(identity.recognize(vec(5, 0.1, base=1), {"Luna": [vec(1)], "Mia": [vec(2)]}, "cat"), "Luna")

    def test_enroll_recognize_and_persist(self):
        out = self.enroll("Raúl", "person", [vec(s, 0.2, base=1) for s in range(10, 14)])
        self.assertIn("Learning Raúl", out)
        self.assertEqual(len(identity.load(self.path)["people"]["Raúl"]), 4)
        self.idn._sighting("person", [(vec(20, 0.3, base=1), 0.2), (vec(9), 0.05)], time.time())
        self.idn._sighting("person", [(vec(21, 0.3, base=1), 0.2), (vec(9), 0.05)], time.time())
        w = self.idn.who()
        self.assertEqual((w["people"], w["unknown_people"]), (["Raúl"], 1))
        self.assertIn("Raúl (closest", self.idn.describe())
        self.assertIn("one person whose face you don't know", self.idn.describe())
        again = identity.Identity(FakeEyes(), self.path)
        self.assertEqual(list(again.data["people"]), ["Raúl"])

    def test_samples_from_before_the_request_must_match(self):
        # lo que había delante antes de pedirlo era otro: no entra en el alta
        self.enroll("Luna", "cat", [vec(s, 0.1, base=1) for s in range(30, 34)], before=[vec(2), vec(3)])
        saved = np.asarray(identity.load(self.path)["cats"]["Luna"])
        self.assertEqual(len(saved), 4)
        self.assertTrue(all(float(s @ vec(1)) > 0.9 for s in saved))

    def test_refuses_a_face_that_is_someone_else(self):
        self.enroll("Raúl", "person", [vec(s, 0.2, base=1) for s in range(10, 14)])
        self.idn._sighting("person", [(vec(40, 0.2, base=1), 0.2)], time.time())
        out = self.idn.remember_face({"name": "Pepe"})
        self.assertIn("already looks like Raúl", out)
        self.assertNotIn("Pepe", self.idn.data["people"])

    def test_nothing_clear_learns_nothing(self):
        self.enroll("Ana", "person", [vec(50)])
        self.assertNotIn("Ana", identity.load(self.path)["people"])

    def test_no_picture_or_no_name(self):
        self.assertIn("say whose", self.idn.remember_face({"name": " "}))
        self.idn.eyes.frame_at = time.time() - 10
        self.assertIn("no picture", self.idn.remember_face({"name": "Ana"}))

    def test_one_frame_unknowns_are_ignored(self):
        self.idn._sighting("cat", [(vec(60), 0.1)], time.time())
        self.idn._sighting("cat", [], time.time())
        self.assertEqual(self.idn.who()["unknown_cats"], 0)
        self.assertEqual(self.idn.describe(), "")

    def test_no_live_picture_no_note(self):
        self.enroll("Raúl", "person", [vec(s, 0.2, base=1) for s in range(10, 14)])
        self.idn._sighting("person", [(vec(20, 0.3, base=1), 0.2)], time.time())
        self.idn._frame_at = time.time() - 10
        self.assertEqual(self.idn.describe(), "")

    def test_private_memories_only_with_their_owner_in_view(self):
        memory.remember({"fact": "Ana odia el brócoli.", "about": "Ana", "private": True}, self.mem)
        memory.remember({"fact": "Raúl tiene tres gatas.", "about": "Raúl"}, self.mem)
        memory.audience, memory.extra_prompt = self.idn.audience, self.idn.prompt_block
        self.assertIn("brócoli", memory.prompt_block(self.mem))   # nadie dado de alta: como antes
        self.enroll("Raúl", "person", [vec(s, 0.2, base=1) for s in range(10, 14)])
        self.enroll("Ana", "person", [vec(s, 0.2, base=2) for s in range(10, 14)])
        self.idn._sighting("person", [(vec(70, 0.3, base=1), 0.2)], time.time())
        block = memory.prompt_block(self.mem)
        self.assertNotIn("brócoli", block)
        self.assertIn("tres gatas", block)
        self.assertIn("You know by sight: people: Raúl, Ana", block)
        self.idn._sighting("person", [(vec(71, 0.3, base=2), 0.2)], time.time())
        self.assertIn("brócoli", memory.prompt_block(self.mem))

    def test_forget(self):
        self.enroll("Raúl", "person", [vec(s, 0.2, base=1) for s in range(10, 14)])
        self.enroll("Luna", "cat", [vec(s, 0.1, base=2) for s in range(10, 14)])
        self.assertIn("nothing forgotten", self.idn.forget_face({"name": "Pepe"}))
        self.assertIn("Raúl", self.idn.forget_face({"name": "raul"}))
        self.assertEqual(identity.load(self.path)["people"], {})
        self.idn.forget_face({"name": "all"})
        self.assertEqual(identity.load(self.path), {"version": 1, "people": {}, "cats": {}})


if __name__ == "__main__":
    unittest.main()
