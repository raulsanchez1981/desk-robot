"""Librería de personajes: cada uno en desktop/characters/<id>/package.json, con su personalidad, voz y cara.

    {
      "id": "jarvis", "name": "Jarvis", "description": "...",
      "face": "visor",                  un pack de caras del cerebro (server/faces/<id>.json o custom/<id>)
      "builtin": true,                  solo Rocky: su personalidad vive en server/brain/personality.py
      "character": {...},               la ficha que entiende el cerebro (brain/characters.py): nombre (= palabra de
                                        activación), voice_id de Fish, prompt, examples, lines, wake_words
      "es": {"examples", "lines", "wake_words"}   lo que cambia con ROBOT_LANGUAGE=es
    }

Activar un personaje = instalar su ficha en server/characters/<id>.json y elegirlo junto con su cara en
server/settings.json, con las funciones del propio cerebro (misma validación que el dashboard). El cerebro lo lee
al arrancar, así que después hay que reiniciarlo (app.Controller.switch_character lo hace).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "desktop" / "characters"
SERVER = ROOT / "server"


def _brain():
    if str(SERVER) not in sys.path:
        sys.path.insert(0, str(SERVER))
    from brain import characters, faces, settings   # solo biblioteca estándar
    return characters, faces, settings


def language() -> str:
    """ROBOT_LANGUAGE de server/.env (o del entorno), como lo lee brain/config.py."""
    if os.environ.get("ROBOT_LANGUAGE"):
        return os.environ["ROBOT_LANGUAGE"].strip().lower()
    try:
        for line in (SERVER / ".env").read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("ROBOT_LANGUAGE="):
                return line.split("=", 1)[1].strip().strip("'\"").lower() or "en"
    except OSError:
        pass
    return "en"


def load_package(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("id") != path.parent.name:
        raise ValueError(f"{path}: el id debe coincidir con la carpeta ({path.parent.name})")
    if not data.get("builtin") and not isinstance(data.get("character"), dict):
        raise ValueError(f"{path}: falta \"character\"")
    return data


def packages() -> list[dict]:
    """Todos los paquetes válidos, Rocky primero. Los rotos se saltan con un aviso."""
    out = []
    for path in sorted(LIBRARY.glob("*/package.json")):
        try:
            out.append(load_package(path))
        except (OSError, ValueError) as e:
            print(f"personaje {path.parent.name}: {e}")
    out.sort(key=lambda p: (p["id"] != "rocky", p["name"].lower()))
    return out


def character_for(pkg: dict, lang: str) -> dict:
    """La ficha para el cerebro, con lo del idioma encima."""
    ch = dict(pkg["character"])
    extra = pkg.get(lang) or {}
    for key in ("examples", "lines", "prompt"):
        if extra.get(key):
            ch[key] = extra[key]
    if extra.get("wake_words"):
        ch["wake_words"] = list(extra["wake_words"]) + list(ch.get("wake_words") or [])
    return ch


def active_id() -> str:
    _, _, settings = _brain()
    return settings.load()["character"]["id"]


def activate(pkg_id: str, lang: str | None = None) -> dict:
    """Instala y elige el personaje y su cara. Devuelve el paquete. Lanza ValueError si algo no es válido."""
    characters, faces, settings = _brain()
    pkg = next((p for p in packages() if p["id"] == pkg_id), None)
    if pkg is None:
        raise ValueError(f"no hay ningún personaje \"{pkg_id}\" en {LIBRARY}")
    face = pkg.get("face") or faces.DEFAULT_PACK
    faces.load(face)                                    # ValueError/OSError si el pack no existe
    if pkg.get("builtin"):
        cid = characters.DEFAULT
    else:
        cid = characters.save(character_for(pkg, lang or language()), pkg["id"])
    settings.update({"character": {"id": cid}, "face": {"pack": face}})
    return pkg
