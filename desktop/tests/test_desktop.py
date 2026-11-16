"""Tests del robot virtual que no necesitan ventanas: copia de FaceKit y dónde se abre la ventana.

    cd desktop && ..\\server\\.venv\\Scripts\\python -m unittest discover -s tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import sync_facekit  # noqa: E402
from virtual_robot import settings  # noqa: E402


class FaceKitSyncTest(unittest.TestCase):
    def test_copy_matches_dashboard(self):
        self.assertEqual(sync_facekit.current(), sync_facekit.expected(),
                         "facekit.js no coincide con dashboard.html: ejecuta python desktop/tools/sync_facekit.py")

    def test_extract_needs_the_block(self):
        with self.assertRaises(ValueError):
            sync_facekit.extract("<html>sin caras</html>")


MONITORS = [(0, 0, 5120, 1440), (1316, 1440, 3023, 2507)]   # los dos monitores de este PC
WORK = (0, 0, 5120, 1400)


class PlaceTest(unittest.TestCase):
    def test_first_run_goes_bottom_right(self):
        self.assertEqual(settings.place(settings.WindowState(), MONITORS, WORK),
                         (5120 - 240 - settings.MARGIN, 1400 - 240 - settings.MARGIN, 240))

    def test_saved_position_on_second_monitor(self):
        self.assertEqual(settings.place(settings.WindowState(2000, 1600, 300), MONITORS, WORK), (2000, 1600, 300))

    def test_off_screen_position_resets(self):
        x, y, size = settings.place(settings.WindowState(9000, 9000, 300), MONITORS, WORK)
        self.assertEqual((x, y), (5120 - 300 - settings.MARGIN, 1400 - 300 - settings.MARGIN))

    def test_straddling_monitors_resets(self):
        x, _, _ = settings.place(settings.WindowState(5000, 100, 300), MONITORS, WORK)
        self.assertNotEqual(x, 5000)

    def test_size_is_clamped(self):
        self.assertEqual(settings.place(settings.WindowState(10, 10, 5), MONITORS, WORK)[2], settings.MIN_SIZE)
        self.assertEqual(settings.WindowState(size=99999).clamped_size(), settings.MAX_SIZE)


class SaveLoadTest(unittest.TestCase):
    def test_round_trip_keeps_other_keys(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text('{"otra": 1}', encoding="utf-8")
            settings.save(settings.WindowState(10, 20, 300), path)
            self.assertEqual(settings.load(path), settings.WindowState(10, 20, 300))
            self.assertIn('"otra": 1', path.read_text(encoding="utf-8"))

    def test_broken_file_gives_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text("{roto", encoding="utf-8")
            self.assertEqual(settings.load(path), settings.WindowState())


if __name__ == "__main__":
    unittest.main()
