"""Idioma en el que habla y escucha el robot: inglés (el original) o español.

Se elige con ROBOT_LANGUAGE en server/.env ("en" por defecto, "es" para español). config.py aplica lo de aquí al
arrancar; ears.py, mouth.py y personality.py lo leen de config. Todo lo que depende del idioma está en este fichero:
el modelo de reconocimiento de voz, la palabra de activación, las frases que el cerebro entiende sin preguntar al
modelo, la voz de reserva de Windows y lo que se añade a la personalidad. Standard library only.
"""

from __future__ import annotations

import unicodedata

SUPPORTED = ("en", "es")


def fold(text: str) -> str:
    """Minúsculas y sin tildes: "Adiós, ROCKY" -> "adios, rocky". Así las frases se comparan sin depender de cómo
    las acentúe el reconocimiento de voz."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


# ── Español ──────────────────────────────────────────────────────────────────────────────────────────────────────

# faster-whisper multilingüe (base.en solo entiende inglés). "small" acierta bastante más que "base" en español a
# cambio de ~1 s más por frase en CPU; cámbialo a "base" (revisión ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66) si va
# lento. La revisión fija el commit de Hugging Face (Systran/faster-whisper-small) que se descarga.
ES_STT_MODEL = "small"
ES_STT_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
ES_TTS_CULTURE = "es-ES"    # voz de reserva de Windows (Helena); en inglés, en-US (Zira)


def es_wake_phrases(name: str) -> list[str]:
    """Cómo suele transcribir Whisper "oye <nombre>" en español. Siempre hace falta el saludo delante, como en
    inglés: el nombre a secas no lo despierta."""
    n = fold(name)
    names = {n}
    if n == "rocky":
        names |= {"roki", "roky", "roqui", "rocki", "rocky's"}
    greetings = ("hola", "oye", "oiga", "hey", "ey", "eh", "ei")
    return [f"{g} {x}" for g in greetings for x in sorted(names)]


def es_sleep_phrases(name: str) -> list[str]:
    n = fold(name)
    # Frases enteras que solo se dicen para mandarlo a dormir ("a dormir" a secas salta con "voy a dormir poco").
    return [f"{n} duerme", f"{n} a dormir", f"{n} vete a dormir", "vete a dormir", "buenas noches",
            "deja de escuchar"]


ES_TRACK_ON = ["sigueme", "mirame", "no me pierdas de vista", "sigue mi cara", "vigilame"]
ES_TRACK_OFF = ["deja de seguirme", "deja de mirarme", "para de seguirme", "deja de vigilarme"]
ES_FOCUS_STOP = ["para la concentracion", "termina la concentracion", "acaba la concentracion", "fin de la concentracion",
                 "deja la concentracion", "para el modo concentracion", "quita el modo concentracion",
                 "termina el modo concentracion"]
# Preguntas sobre lo que ve (frases enteras, como en config.CAMERA_WORDS). Sin tildes: se comparan con fold().
ES_CAMERA_WORDS = [
    "que ves", "que puedes ver", "puedes ver", "me ves", "lo ves", "que estas viendo", "que estas mirando",
    "que es esto", "que es eso", "que notas", "notas algo",
    "mira esto", "mira eso", "mira aqui", "mira alli", "mira a", "mira hacia", "echa un vistazo", "mira alrededor",
    "que tengo en la mano", "que llevo", "que llevo puesto", "como me ves", "como estoy", "cuantos dedos",
    "de que color es", "de que color", "quien es este", "quien es esta", "quien es ese", "quien es esa",
    "quien hay", "quien esta conmigo", "me reconoces", "reconoces esto", "describe lo que", "describeme",
    "describe esto", "describe eso", "tu camara", "la camara", "una foto", "delante de ti", "detras de ti",
    "en mi mesa", "en la mesa", "en la habitacion", "en la pizarra", "en la pantalla", "en mi pantalla",
    "lee esto", "lee eso", "puedes leer",
]

# Lo que se añade a cualquier personalidad (Rocky o una del dashboard): hablar en español.
ES_REPLY_RULES = """
Language (this overrides any language habit above):
- Your human speaks Spanish (Spain) and you ALWAYS answer in Spanish, even if the examples above are in English. \
Use natural Spain Spanish ("vale", "tú", "ordenador", "móvil"), never Latin American forms like "computadora" or \
"celular".
- Keep the emotion tag in English inside the square brackets, exactly as listed, then the Spanish words: \
"[happy] ¡Funciona!".
- Write numbers and units so they read aloud well in Spanish ("tres coma cinco voltios" is fine, "3,5 V" too).
"""

# Rocky en español: sus muletillas, como en la traducción del libro (cámbialas a tu gusto).
ES_ROCKY_RULES = """
How Rocky's quirks sound in Spanish:
- He drops articles and conjugates loosely: "Humano necesitar dormir." "Arreglar luego, fácil." "Es bueno."
- "Pregunta:" before he asks something and "Respuesta:" before he answers, at least some of the time.
- "¡Asombroso!" is his favourite word. "¡Choca mi puño!" when something goes well. "Mal, mal, mal" when it \
does not. "No" for no. "Sí sí sí" when he agrees strongly.

Example replies in Spanish (prefer these to the English ones):
[surprised] ¡Asombroso! Placa nueva. Pregunta, {human}: ¿es para mí?
[thinking] Respuesta: error significa número de pin mal. Revisa config, arreglo fácil.
[sad] ¿{human} despierto desde las cinco? No bueno. Mis servos descansan más. Ve a dormir.
[happy] Sí sí sí. Funciona. ¡Choca mi puño!
[thinking] Pregunta: ¿qué es "fin de semana"? Humanos paran de trabajar porque... ¿sol dice? Asombroso.
[neutral] No sé. Enséñame foto, miro más cerca.
"""

ES_ROCKY_LINES = {
    "wake": "¿Pregunta?",
    "sleep": "Yo duermo. Tú vigilas. Despiértame cuando encuentres bug.",
    "track_on": "Sí sí sí. Ojos en {human}.",
    "track_off": "Vale. Ojos libres.",
}
