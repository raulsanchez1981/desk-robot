"""Las órdenes de la página de recuerdos: memory.console e Identity.console."""

import tempfile
import time
import unittest
from pathlib import Path

from brain import identity, memory
from test_identity import FakeEyes, vec


class MemoryConsoleTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "memory.json"

    def test_add_edit_delete(self):
        r = memory.console("memory_add", {"text": "Raúl tiene tres gatas.", "about": "Raúl"}, self.path)
        self.assertEqual([f["text"] for f in r["facts"]], ["Raúl tiene tres gatas."])
        self.assertEqual(r["max"], memory.MAX_FACTS)
        fid = r["facts"][0]["id"]
        r = memory.console("memory_edit", {"id": fid, "text": "Raúl tiene cuatro gatas.", "about": "",
                                           "date": "2026-12-20", "private": True}, self.path)
        f = r["facts"][0]
        self.assertEqual((f["text"], f["about"], f["date"], f["private"]),
                         ("Raúl tiene cuatro gatas.", None, "2026-12-20", True))
        memory.console("memory_edit", {"id": fid, "date": "nunca"}, self.path)
        self.assertIsNone(memory.load(self.path)["facts"][0]["date"])
        self.assertEqual(memory.console("memory_delete", {"id": fid}, self.path)["facts"], [])

    def test_refusals(self):
        with self.assertRaises(ValueError):
            memory.console("memory_add", {"text": " "}, self.path)
        memory.console("memory_add", {"text": "Algo que dura."}, self.path)
        with self.assertRaises(ValueError):
            memory.console("memory_edit", {"id": 1, "text": ""}, self.path)
        with self.assertRaises(ValueError):
            memory.console("memory_edit", {"id": 99, "text": "otro"}, self.path)
        with self.assertRaises(ValueError):
            memory.console("memory_delete", {"id": 99}, self.path)
        with self.assertRaises(ValueError):
            memory.console("memory_nope", {}, self.path)
        self.assertEqual(len(memory.console("memory_list", {}, self.path)["facts"]), 1)


class FacesConsoleTest(unittest.TestCase):
    def test_list_learn_forget(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        idn = identity.Identity(FakeEyes(), Path(d.name) / "identity.json")
        idn.ready = True
        idn._frame_at = time.time()
        r = idn.console("faces_list", {})
        self.assertEqual(r["known"], {"people": {}, "cats": {}})
        self.assertIsNone(r["learning"])
        r = idn.console("faces_learn", {"name": "Luna", "kind": "cat"})
        self.assertEqual((r["learning"]["name"], r["learning"]["kind"]), ("Luna", "cat"))
        for s in range(3):
            idn._enrolling["last"] = 0
            idn._sighting("cat", [(vec(s, 0.1, base=1), 0.1)], time.time())
        idn._enrolling["until"] = 0
        idn._finish_enrolment(time.time())
        self.assertEqual(idn.console("faces_list", {})["known"]["cats"], {"Luna": 3})
        with self.assertRaises(ValueError):
            idn.console("faces_learn", {"name": ""})
        with self.assertRaises(ValueError):
            idn.console("faces_forget", {"name": "Pepe"})
        self.assertEqual(idn.console("faces_forget", {"name": "luna"})["known"]["cats"], {})


if __name__ == "__main__":
    unittest.main()
