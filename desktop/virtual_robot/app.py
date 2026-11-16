"""Ventanas del robot virtual: la cara (la pantalla del robot, 2:1, sin bordes, siempre encima) y el panel de depuración.

La cara se controla con mensajes con forma de protocolo (robot.handle(msg) en ui/robot.js). En la fase 2 los manda
el panel de depuración; en la fase 3 los mandará el enlace con el cerebro.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import webview

from . import settings, win32

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"
UI = Path(__file__).resolve().parent / "ui"
FACE_TITLE = "Robot virtual"
DEBUG_TITLE = "Robot virtual: depuración"


def _brain_faces():
    """server/brain/faces.py (solo biblioteca estándar): mismos packs y misma validación que el cerebro."""
    import sys
    if str(SERVER) not in sys.path:
        sys.path.insert(0, str(SERVER))
    from brain import faces
    return faces


def active_pack_id() -> str:
    """El pack elegido en el dashboard (server/settings.json), o el de Rocky."""
    try:
        data = json.loads((SERVER / "settings.json").read_text(encoding="utf-8"))
        return str(data.get("face", {}).get("pack") or "rocky")
    except (OSError, ValueError, AttributeError):
        return "rocky"


class FaceWindow:
    def __init__(self, state: settings.WindowState, start_asleep: bool = False) -> None:
        self.state = state
        self.start_asleep = start_asleep     # con cerebro arranca dormida, como la placa, hasta que él diga
        self.hwnd = 0
        self.ready = threading.Event()       # la ventana existe
        self.loaded = threading.Event()      # robot.js ya pinta la cara y acepta mensajes
        self._pending: list[dict] = []
        self._pending_lock = threading.Lock()
        faces = _brain_faces()
        x, y, size = settings.place(state, win32.monitors(), win32.work_area())
        self.size = size
        self._place = (x, y)
        self.window = webview.create_window(
            FACE_TITLE, url=str(UI / "face.html"), js_api=_FaceApi(self, faces),
            width=size, height=settings.height_for(size), x=x, y=y, frameless=True, easy_drag=False, on_top=True,
            resizable=False, background_color="#000000",
            min_size=(settings.MIN_SIZE, settings.height_for(settings.MIN_SIZE)))
        self.window.events.shown += self._on_shown

    def _on_shown(self) -> None:
        for _ in range(50):                    # el HWND aparece un instante después del evento
            self.hwnd = win32.find_window(FACE_TITLE)
            if self.hwnd:
                break
            time.sleep(0.05)
        win32.round_corners(self.hwnd)
        x, y = self._place
        win32.set_window_rect(self.hwnd, x, y, self.size, settings.height_for(self.size))   # exacto (ver win32)
        self.ready.set()
        threading.Thread(target=self._remember_position, daemon=True).start()

    def resize(self, size: int, final: bool) -> int:
        size = max(settings.MIN_SIZE, min(settings.MAX_SIZE, int(size)))
        win32.set_window_rect(self.hwnd, None, None, size, settings.height_for(size))
        self.size = size
        return size

    def _remember_position(self) -> None:
        """Guarda posición y tamaño cuando cambian (cada segundo como mucho)."""
        last = None
        while True:
            time.sleep(1.0)
            if not self.hwnd:
                continue
            x, y, w, h = win32.window_rect(self.hwnd)
            if w <= 0:
                continue
            now = (x, y, w)
            if now != last:
                last = now
                self.state.x, self.state.y, self.state.size = now
                try:
                    settings.save(self.state)
                except OSError as e:
                    print(f"(no pude guardar la posición de la ventana: {e})")

    def send(self, msg: dict) -> None:
        """Un mensaje con forma de protocolo para la cara (desde cualquier hilo). Los que llegan antes de que la
        cara cargue se guardan y se entregan después, en orden."""
        with self._pending_lock:
            if not self.loaded.is_set():
                self._pending.append(msg)
                return
        self.window.evaluate_js(f"robot.handle({json.dumps(msg)})")

    def on_loaded(self) -> None:
        with self._pending_lock:
            pending, self._pending = self._pending, []
            self.loaded.set()
        for msg in pending:
            self.window.evaluate_js(f"robot.handle({json.dumps(msg)})")

    def state_js(self) -> dict | None:
        return self.window.evaluate_js("window.robot && robot.sim ? robot.state() : null")


class _FaceApi:
    """Lo que ui/robot.js puede pedir a Python."""

    def __init__(self, owner: FaceWindow, faces) -> None:
        self._owner, self._faces = owner, faces

    def init(self) -> dict:
        _, rocky = self._faces.load_or_default("rocky")
        _, pack = self._faces.load_or_default(active_pack_id())
        return {"emotions": self._faces.EMOTIONS, "fallback": rocky, "pack": pack, "asleep": self._owner.start_asleep}

    def loaded(self) -> bool:
        threading.Thread(target=self._owner.on_loaded, daemon=True).start()   # no bloquear el hilo de JS
        return True

    def resize(self, size: int, final: bool = False) -> int:
        return self._owner.resize(size, final)


class _DebugApi:
    """Lo que ui/debug.html puede pedir a Python: mandar mensajes a la cara y leer packs."""

    def __init__(self, face: FaceWindow, faces, link=None) -> None:
        self._face, self._faces, self._link = face, faces, link

    def info(self) -> dict:
        packs = [{"id": p["id"], "name": p.get("pack", {}).get("name", p["id"])}
                 for p in self._faces.list_packs() if "pack" in p]
        return {"emotions": self._faces.EMOTIONS, "packs": packs, "active": active_pack_id()}

    def send(self, msg: dict) -> bool:
        if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
            return False
        self._face.send(msg)
        return True

    def use_pack(self, pack_id: str) -> bool:
        _, pack = self._faces.load_or_default(pack_id)
        self._face.send(self._faces.robot_message(pack, save=False))
        return True

    def state(self) -> dict | None:
        s = self._face.state_js()
        if s is not None:
            s["link"] = self._link.status if self._link is not None else "sin enlace (--no-brain)"
            s["speaking"] = bool(self._link and self._link.speaker.speaking)
            s["mic"] = bool(self._link and self._link.mic.wanted and not self._link.speaker.speaking)
        return s


def run(debug: bool, brain: bool = True) -> None:
    win32.make_dpi_aware()
    face = FaceWindow(settings.load(), start_asleep=brain)
    link = None
    if brain:
        from .link import BrainLink
        link = BrainLink(face.send)
        link.start()
    if debug:
        webview.create_window(DEBUG_TITLE, url=str(UI / "debug.html"), js_api=_DebugApi(face, _brain_faces(), link),
                              width=480, height=800, min_size=(400, 500))
    webview.start(private_mode=True)
