"""La ventana de recuerdos: el puente MemoryApi con la API del cerebro (falsa)."""

import unittest

from virtual_robot.memories import MemoryApi


class FakeBrain:
    def __init__(self, fail: dict | None = None):
        self.calls, self.fail = [], fail or {}

    def __call__(self, action, payload, timeout=5.0):
        self.calls.append((action, payload))
        if action in self.fail:
            raise self.fail[action]
        if action == "memory_list":
            return {"ok": True, "facts": [{"id": 1, "text": "Raúl tiene tres gatas."}], "max": 300}
        if action == "faces_list":
            return {"ok": True, "error": "", "known": {"people": {"Raúl": 9}, "cats": {}}}
        return {"ok": True}


class MemoryApiTest(unittest.TestCase):
    def test_snapshot(self):
        r = MemoryApi(FakeBrain()).snapshot()
        self.assertEqual(r["facts"][0]["text"], "Raúl tiene tres gatas.")
        self.assertEqual(r["faces"]["known"]["people"], {"Raúl": 9})

    def test_brain_off(self):
        r = MemoryApi(FakeBrain({"memory_list": OSError("[WinError 10061] refused")})).snapshot()
        self.assertTrue(r["offline"])
        self.assertIn("no está en marcha", r["error"])

    def test_faces_off_still_shows_memories(self):
        r = MemoryApi(FakeBrain({"faces_list": OSError('HTTP 400: {"error": "face recognition isn\'t running"}')})).snapshot()
        self.assertEqual(len(r["facts"]), 1)
        self.assertIsNone(r["faces"])
        self.assertEqual(r["faces_error"], "El reconocimiento de caras no está en marcha.")

    def test_calls_and_fields(self):
        brain = FakeBrain({"memory_delete": OSError('HTTP 400: {"error": "no such memory"}')})
        api = MemoryApi(brain)
        api.add({"text": "Ana cumple el 3 de mayo.", "about": "Ana", "date": "2027-05-03", "private": 0})
        api.edit("4", {"text": "x"})
        self.assertEqual(api.delete(9), {"error": "Ese recuerdo ya no existe."})
        api.learn_face("Luna", "cat")
        api.forget_face("Luna")
        self.assertEqual(brain.calls[0], ("memory_add", {"text": "Ana cumple el 3 de mayo.", "about": "Ana",
                                                         "date": "2027-05-03", "private": False}))
        self.assertEqual(brain.calls[1], ("memory_edit", {"id": 4, "text": "x", "about": "", "date": "",
                                                          "private": False}))
        self.assertEqual(brain.calls[3], ("faces_learn", {"name": "Luna", "kind": "cat"}))
        self.assertEqual(brain.calls[4], ("faces_forget", {"name": "Luna"}))

    def test_errors_in_spanish(self):
        msg = 'HTTP 400: {"error": "Nothing learned: that face already looks like Raúl. If it is not Raúl..."}'
        r = MemoryApi(FakeBrain({"faces_learn": OSError(msg)})).learn_face("Pepe", "person")
        self.assertEqual(r["error"], "Esa cara ya parece de Raúl. Si no es, olvida a Raúl primero.")


if __name__ == "__main__":
    unittest.main()
