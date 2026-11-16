"""La cámara con una webcam falsa: stream, foto nítida, espejo, fps según el estado e interruptor."""

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from virtual_robot import camera  # noqa: E402


class FakeCap:
    """1280x720 a ~30 fps; la mitad izquierda blanca y la derecha negra, para ver el espejo."""

    def __init__(self):
        self.released = False
        self.frame = np.zeros((720, 1280, 3), np.uint8)
        self.frame[:, :640] = 255

    def read(self):
        time.sleep(1 / 30)
        return True, self.frame.copy()

    def release(self):
        self.released = True


class CameraTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.speaking = self.asleep = False
        self.cap = FakeCap()

        def fake_open(cam, _cv2):
            cam._cap, cam.index, cam.status = self.cap, 0, "webcam 0 encendida"
            return True

        patcher = mock.patch.object(camera.Camera, "_open", fake_open)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cam = camera.Camera(self.sent.append, speaking=lambda: self.speaking, asleep=lambda: self.asleep)
        self.addCleanup(lambda: self.cam.set_enabled(False))

    def frames(self, kind: bytes):
        return [f for f in list(self.sent) if f[:1] == kind]

    def test_stream_rate_size_and_mirror(self):
        self.cam.set_stream(True, 10, "vga")
        time.sleep(1.2)
        stream = self.frames(b"\x02")
        self.assertTrue(9 <= len(stream) <= 14, len(stream))
        img = cv2.imdecode(np.frombuffer(stream[-1][1:], np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(img.shape[1], 640)
        self.assertLess(img[:, :100].mean(), 30, "espejada: lo blanco pasa a la derecha")
        self.assertGreater(img[:, -100:].mean(), 225)

    def test_slower_while_speaking_or_asleep(self):
        self.asleep = True
        self.cam.set_stream(True, 10, "qvga")
        time.sleep(1.2)
        self.assertLessEqual(len(self.frames(b"\x02")), 8)
        img = cv2.imdecode(np.frombuffer(self.frames(b"\x02")[-1][1:], np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(img.shape[1], 320)

    def test_snapshot_is_sharp(self):
        self.cam.set_stream(True, 10, "vga")
        time.sleep(0.3)
        self.cam.snapshot("xga")
        time.sleep(0.3)
        snaps = self.frames(b"\x03")
        self.assertEqual(len(snaps), 1)
        img = cv2.imdecode(np.frombuffer(snaps[0][1:], np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(img.shape[1], 1024)

    def test_switch_off_releases_the_webcam(self):
        self.cam.set_stream(True, 10, "vga")
        time.sleep(0.3)
        self.cam.set_enabled(False)
        time.sleep(0.3)
        self.assertTrue(self.cap.released)
        n = len(self.frames(b"\x02"))
        time.sleep(0.5)
        self.assertEqual(len(self.frames(b"\x02")), n, "apagada no manda nada")

    def test_no_stream_until_asked(self):
        time.sleep(0.4)
        self.assertEqual(self.sent, [])
        self.assertIn("en espera", self.cam.status)


if __name__ == "__main__":
    unittest.main()
