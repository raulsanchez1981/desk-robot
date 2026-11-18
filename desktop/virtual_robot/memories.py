"""La ventana de recuerdos: lo que el robot recuerda y a quién conoce de vista, para verlo, cambiarlo y borrarlo.

Todo pasa por la API local del cerebro (server/brain/memory.py e identity.py: POST /api/memory_* y /api/faces_*),
porque el cerebro tiene las caras en memoria y es quien escribe los ficheros. Sin cerebro, la página lo dice.
"""

from __future__ import annotations

import json
import re

from . import brain_process

TITLE = "Robot virtual: recuerdos"


class MemoryApi:
    """Lo que ui/memories.html puede pedir a Python. Cada método devuelve {"ok": ...} o {"error": "..."}."""

    def __init__(self, api=brain_process.api) -> None:
        self._api = api

    def _call(self, action: str, payload: dict | None = None) -> dict:
        try:
            return self._api(action, payload or {}, timeout=4.0)
        except OSError as e:
            msg = str(e)
            if not msg.startswith("HTTP "):   # no contesta: cerebro parado o arrancando
                return {"error": "El cerebro no está en marcha.", "offline": True}
            detail = msg.split(": ", 1)[-1]   # brain_process.api: "HTTP 400: {"error": "..."}"
            try:
                return {"error": _spanish(str(json.loads(detail).get("error") or detail))}
            except (ValueError, AttributeError):
                return {"error": _spanish(detail)}

    def snapshot(self) -> dict:
        """Recuerdos y caras de una vez (la página lo pide cada pocos segundos)."""
        mem = self._call("memory_list")
        if not mem.get("ok"):
            return mem
        faces = self._call("faces_list")   # (su respuesta trae su propio "error": el del reconocimiento, a menudo "")
        return {"ok": True, "facts": mem.get("facts", []), "max": mem.get("max"),
                "faces": faces if faces.get("ok") else None, "faces_error": None if faces.get("ok") else faces.get("error")}

    def add(self, fact: dict) -> dict:
        return self._call("memory_add", _fields(fact))

    def edit(self, fid: int, fact: dict) -> dict:
        return self._call("memory_edit", {"id": int(fid), **_fields(fact)})

    def delete(self, fid: int) -> dict:
        return self._call("memory_delete", {"id": int(fid)})

    def learn_face(self, name: str, kind: str) -> dict:
        return self._call("faces_learn", {"name": str(name), "kind": "cat" if kind == "cat" else "person"})

    def forget_face(self, name: str) -> dict:
        return self._call("faces_forget", {"name": str(name)})


# Los textos del cerebro son para el modelo (en inglés); en la página van en español.
_SPANISH = [
    (re.compile(r"no picture"), "La cámara no da imagen ahora mismo."),
    (re.compile(r"already looks like (.+?)\."), r"Esa cara ya parece de \1. Si no es, olvida a \1 primero."),
    (re.compile(r"say whose"), "Escribe un nombre."),
    (re.compile(r"don't know anyone called"), "No conoce a nadie con ese nombre."),
    (re.compile(r"can't learn faces right now|isn't running"), "El reconocimiento de caras no está en marcha."),
    (re.compile(r"You already know (\d+)"), r"Ya conoce a \1; olvida a alguien antes."),
    (re.compile(r"can't be empty|fact was empty"), "El recuerdo está vacío."),
    (re.compile(r"Memory is full \((\d+)"), r"La memoria está llena (\1 recuerdos): borra alguno antes."),
    (re.compile(r"no such memory|no memory #"), "Ese recuerdo ya no existe."),
]


def _spanish(msg: str) -> str:
    for pattern, text in _SPANISH:
        m = pattern.search(msg)
        if m:
            return m.expand(text)
    return msg


def _fields(fact: dict) -> dict:
    fact = fact if isinstance(fact, dict) else {}
    return {"text": str(fact.get("text") or ""), "about": str(fact.get("about") or ""),
            "date": str(fact.get("date") or ""), "private": bool(fact.get("private"))}
