"""Altavoz (sin tarjeta de sonido: se llama al callback a mano) y lectura del token."""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from virtual_robot import audio  # noqa: E402
from virtual_robot.link import read_token  # noqa: E402


def _drive(sp: audio.Speaker, seconds: float) -> None:
    """Hace de tarjeta de sonido: pide bloques de 20 ms al ritmo real."""
    out = np.zeros((320, 1), dtype=np.int16)
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        sp._callback(out, 320, None, None)
        time.sleep(0.02)


class SpeakerTest(unittest.TestCase):
    def setUp(self):
        self.done, self.mouth = [], []
        self.sp = audio.Speaker(on_done=self.done.append, on_mouth=self.mouth.append)
        self.sp.latency = 0.0
        threading.Thread(target=self.sp._watch, daemon=True).start()

    def test_speak_done_once_after_the_audio(self):
        self.sp.begin()
        self.sp.feed(b"\x10\x00" * 1600 * 3)       # 0,3 s
        self.sp.end()
        _drive(self.sp, 0.8)
        self.assertEqual(len(self.done), 1, "speak_done exactamente una vez")
        self.assertEqual(self.done[0]["type"], "speak_done")
        self.assertFalse(self.sp.speaking)
        self.assertEqual(self.mouth[-1], -1, "la boca se cierra al acabar")

    def test_waits_for_head_start_before_playing(self):
        self.sp.begin()
        self.sp.feed(b"\x00\x00" * 1600)           # 0,1 s < colchón de 0,2 s
        _drive(self.sp, 0.1)
        self.assertFalse(self.sp._started)
        self.sp.feed(b"\x00\x00" * 1600 * 2)
        _drive(self.sp, 0.05)
        self.assertTrue(self.sp._started)

    def test_no_speak_done_until_speak_end(self):
        self.sp.begin()
        self.sp.feed(b"\x00\x00" * 1600 * 3)
        _drive(self.sp, 0.6)                       # se queda sin audio pero no ha llegado speak_end
        self.assertEqual(self.done, [])
        self.assertTrue(self.sp.speaking)
        self.sp.end()
        _drive(self.sp, 0.2)
        self.assertEqual(len(self.done), 1)

    def test_mic_stays_quiet_after_speaking(self):
        frames = []
        mic = audio.Mic(on_frame=frames.append, speaker=self.sp)
        mic.wanted = True
        block = np.zeros((audio.MIC_FRAME, 1), dtype=np.int16)
        self.sp.begin()
        mic._callback(block, audio.MIC_FRAME, None, None)
        self.assertEqual(frames, [], "callado mientras habla")
        self.sp.feed(b"\x00\x00" * 1600); self.sp.end()
        _drive(self.sp, 0.3)
        mic._callback(block, audio.MIC_FRAME, None, None)
        self.assertEqual(frames, [], "callado durante la cola de eco")
        time.sleep(audio.ECHO_TAIL_S + 0.05)
        mic._callback(block, audio.MIC_FRAME, None, None)
        self.assertEqual(len(frames), 1)


class TokenTest(unittest.TestCase):
    def test_reads_env_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("# ROBOT_TOKEN=comentado\nOTRA=1\nROBOT_TOKEN='abcdef0123456789'\n", encoding="utf-8")
            self.assertEqual(read_token(p), "abcdef0123456789")

    def test_missing_file(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ROBOT_TOKEN", None)
            self.assertEqual(read_token(Path("no-existe.env")), "")


if __name__ == "__main__":
    unittest.main()
