"""El modo español (brain/language.py): frases sin tildes, palabra de activación y lo que config aplica.

config se importa una sola vez por proceso, así que lo que depende de ROBOT_LANGUAGE se prueba en un subproceso con
la variable puesta. Sin red ni modelos.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from brain import language

SERVER = Path(__file__).resolve().parent.parent


def _config_in(lang: str) -> dict:
    code = (
        "import json; from brain import config, ears, personality\n"
        "print(json.dumps({'lang': config.LANGUAGE, 'stt': config.STT_MODEL, 'stt_lang': config.STT_LANGUAGE,"
        # con el personaje que esté activo en settings.json (Rocky, Jarvis...), no siempre Rocky
        " 'culture': config.TTS_CULTURE, 'name': config.ROBOT_NAME, 'rocky': config.CHARACTER is None,"
        " 'wake': ears.strip_wake_word(f'Oye, {config.ROBOT_NAME}, ¿qué hora es?'),"
        " 'woke_en': ears.strip_wake_word(f'Hey {config.ROBOT_NAME}, what time is it?')[0],"
        " 'sleep': any(p in ears.normalize(f'Buenas noches, {config.ROBOT_NAME}') for p in config.SLEEP_PHRASES),"
        " 'camera': any(f' {w} ' in ' ' + ears.normalize('¿Qué ves ahí?') + ' ' for w in config.CAMERA_WORDS),"
        " 'spanish_rules': 'ALWAYS answer in Spanish' in personality.SYSTEM_PROMPT,"
        " 'wake_line': personality.LINES['wake']}))"
    )
    env = {**os.environ, "ROBOT_LANGUAGE": lang, "PYTHONIOENCODING": "utf-8"}
    out = subprocess.run([sys.executable, "-c", code], cwd=SERVER, env=env, capture_output=True, text=True,
                         encoding="utf-8", timeout=60, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


class FoldTest(unittest.TestCase):
    def test_strips_accents_and_case(self):
        self.assertEqual(language.fold("Adiós, ROCKY, ¿Mañana?"), "adios, rocky, ¿manana?")

    def test_wake_phrases_need_a_greeting(self):
        phrases = language.es_wake_phrases("Rocky")
        self.assertIn("oye rocky", phrases)
        self.assertIn("hola roqui", phrases)
        self.assertNotIn("rocky", phrases)

    def test_wake_phrases_follow_the_name(self):
        self.assertIn("oye juniper", language.es_wake_phrases("Juniper"))


class ConfigTest(unittest.TestCase):
    def test_spanish(self):
        c = _config_in("es")
        self.assertEqual((c["lang"], c["stt"], c["stt_lang"], c["culture"]), ("es", "small", "es", "es-ES"))
        self.assertEqual(c["wake"], [True, "¿qué hora es?"])
        self.assertTrue(c["sleep"])
        self.assertTrue(c["camera"])
        self.assertTrue(c["spanish_rules"])
        if c["rocky"]:
            self.assertEqual(c["wake_line"], "¿Pregunta?")

    def test_english_is_unchanged(self):
        c = _config_in("en")
        self.assertEqual((c["lang"], c["stt"], c["stt_lang"], c["culture"]), ("en", "base.en", "en", "en-US"))
        self.assertTrue(c["woke_en"])
        self.assertFalse(c["spanish_rules"])
        if c["rocky"]:
            self.assertEqual(c["wake_line"], "Question?")

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(_config_in("fr")["lang"], "en")


if __name__ == "__main__":
    unittest.main()
