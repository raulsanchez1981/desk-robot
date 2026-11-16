"""Fase 4 sin ventanas: atajos, enmascarado de secretos, atajos configurables e icono de bandeja."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from virtual_robot import brain_process, hotkeys, settings  # noqa: E402
from virtual_robot.tray import icon_image  # noqa: E402


class ParseTest(unittest.TestCase):
    def test_combos(self):
        self.assertEqual(hotkeys.parse("Ctrl+Alt+S"),
                         (hotkeys.MOD_CONTROL | hotkeys.MOD_ALT | hotkeys.MOD_NOREPEAT, ord("S")))
        mods, vk = hotkeys.parse("ctrl + alt + shift + m")
        self.assertTrue(mods & hotkeys.MOD_SHIFT)
        self.assertEqual(vk, ord("M"))
        self.assertEqual(hotkeys.parse("Ctrl+F9")[1], 0x78)

    def test_rejects_nonsense(self):
        for bad in ("", "Ctrl+Alt+", "Hyper+M", "Ctrl+Escape"):
            with self.assertRaises(ValueError, msg=bad):
                hotkeys.parse(bad)


class RedactTest(unittest.TestCase):
    def test_hides_keys_and_tokens(self):
        line = "key sk-ant-api03-AbCdEf123456 token 0123456789abcdef0123456789abcdef ROBOT_TOKEN=supersecreto"
        out = brain_process.redact(line)
        for secret in ("sk-ant-api03-AbCdEf123456", "0123456789abcdef0123456789abcdef", "supersecreto"):
            self.assertNotIn(secret, out)
        self.assertIn("ROBOT_TOKEN=***", out)

    def test_leaves_normal_lines(self):
        line = "Rocky [happy]: Sí sí sí. timing 1.23s · robot connected! (fw virtual-0.1.0, 127.0.0.1)"
        self.assertEqual(brain_process.redact(line), line)


class HotkeySettingsTest(unittest.TestCase):
    def test_defaults_written_once_and_overrides_kept(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            self.assertEqual(settings.load_hotkeys(path), settings.DEFAULT_HOTKEYS)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["hotkeys"]["mic"] = "Ctrl+Alt+K"
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(settings.load_hotkeys(path)["mic"], "Ctrl+Alt+K")
            self.assertEqual(settings.load_hotkeys(path)["sleep"], settings.DEFAULT_HOTKEYS["sleep"])


class EchoTailTest(unittest.TestCase):
    def test_config_value_or_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            self.assertEqual(settings.load_echo_tail(0.35, path), 0.35)
            path.write_text('{"echo_tail_s": 0.6}', encoding="utf-8")
            self.assertEqual(settings.load_echo_tail(0.35, path), 0.6)
            path.write_text('{"echo_tail_s": 99}', encoding="utf-8")
            self.assertEqual(settings.load_echo_tail(0.35, path), 0.35)


class IconTest(unittest.TestCase):
    def test_red_dot_only_when_something_is_off(self):
        corner = (54, 10)
        self.assertNotEqual(icon_image(True, True).getpixel(corner)[:3], (230, 40, 40))
        self.assertEqual(icon_image(False, True).getpixel(corner)[:3], (230, 40, 40))
        self.assertEqual(icon_image(True, False).getpixel(corner)[:3], (230, 40, 40))


if __name__ == "__main__":
    unittest.main()
