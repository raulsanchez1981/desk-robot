"""El robot virtual: la ventana de la cara, el enlace con el cerebro, el cerebro mismo, la bandeja y los atajos.

La cara (la pantalla del robot, 2:1, sin bordes, siempre encima) se controla con mensajes con forma de protocolo
(robot.handle(msg) en ui/robot.js). Los manda el enlace con el cerebro (link.py) y, para probar, el panel de
depuración. El Controller une lo demás: interruptores de micro y cámara, dormir, mostrar/ocultar y salir.
"""

from __future__ import annotations

import json
import threading
import time
import webbrowser
from pathlib import Path

import webview

from . import autostart, brain_process, settings, win32

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
    def __init__(self, state: settings.WindowState, start_asleep: bool = False, tool_window: bool = False) -> None:
        self.state = state
        self.start_asleep = start_asleep     # con cerebro arranca dormida, como la placa, hasta que él diga
        self.tool_window = tool_window       # fuera de la barra de tareas (la app vive en la bandeja)
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
        if self.tool_window:
            win32.hide_from_taskbar(self.hwnd)
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
        self._seen, self._seen_at = None, 0.0

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
            s["mic"] = bool(self._link and self._link.mic.wanted and self._link.mic.enabled
                            and not self._link.speaker.speaking)
            s["camera"] = self._link.camera.status if self._link is not None else "-"
            s["seen"] = self._what_the_brain_sees()
        return s

    def _what_the_brain_sees(self) -> str:
        """Lo que la percepción del cerebro nota en la webcam (su /status), como mucho una vez por segundo."""
        if self._link is None or not self._link.connected:
            return "-"
        if time.time() - self._seen_at > 1.0:
            self._seen_at = time.time()
            try:
                n = brain_process.status(timeout=0.5).get("notices") or {}
            except OSError:
                n = {}
            if not n.get("live"):
                self._seen = "nada (sin imagen o percepción apagada)"
            elif not n.get("people"):
                self._seen = "nadie" + (" · saludo" if n.get("waving") else "")
            else:
                f = n.get("face") or {}
                bits = [f"{n['people']} persona(s)"] + [w for k, w in (("smiling", "sonríe"), ("looking", "te mira"),
                                                                      ("eyes_closed", "ojos cerrados")) if f.get(k)]
                self._seen = " · ".join(bits + (["saludo"] if n.get("waving") else []))
        return self._seen


class Controller:
    """Une la cara, el enlace, el cerebro, la bandeja y los atajos."""

    def __init__(self, debug: bool, brain: bool) -> None:
        self.HOTKEYS = settings.load_hotkeys()
        self.mic_on = True
        self.cam_on = True
        self.visible = True
        self.quitting = False
        self.autostart = autostart.enabled()
        self._local_asleep = brain           # sin cerebro, dormir es solo cosa de la cara
        self.face = FaceWindow(settings.load(), start_asleep=brain, tool_window=True)
        self.face.window.events.closing += self._on_closing
        self.brain = brain_process.BrainProcess() if brain else None
        self.link = None
        if brain:
            from .link import BrainLink
            self.link = BrainLink(self.face.send)
        self.debug_window = None
        self._want_debug = debug
        self.tray = None
        self.hotkeys = None

    # ── arranque y salida ───────────────────────────────────────────────────────────────────────────────────────
    def run(self) -> None:
        webview.start(self._started, private_mode=True)

    def _started(self) -> None:
        """Ya hay bucle de ventanas: lo demás arranca aquí (hilo aparte de pywebview)."""
        from .hotkeys import Hotkeys
        from .tray import Tray
        if self.brain is not None:
            print(f"robot virtual: {self.brain.start()}")
            if self.brain.warning:
                print(f"robot virtual: {self.brain.warning}")
        if self.link is not None:
            self.link.start()
        self.tray = Tray(self)
        self.tray.start()
        if self.brain is not None and self.brain.warning:
            self.tray.notify(self.brain.warning)
        self.hotkeys = Hotkeys({self.HOTKEYS["mic"]: self.toggle_mic, self.HOTKEYS["cam"]: self.toggle_cam,
                                self.HOTKEYS["sleep"]: self.toggle_sleep})
        self.hotkeys.start()
        if self.hotkeys.failed:
            text = (f"Otra aplicación ya usa {', '.join(self.hotkeys.failed)}. Cámbialo en "
                    f"{settings.config_dir() / 'config.json'} (clave \"hotkeys\").")
            print(f"robot virtual: {text}")
            self.tray.notify(text)
        self.face.loaded.wait(20)
        self._indicators()
        if self._want_debug:
            self.open_debug()

    def _on_closing(self):
        if self.quitting:
            return True
        threading.Thread(target=self.hide, daemon=True).start()   # Alt+F4 la oculta; Salir está en la bandeja
        return False

    def quit(self) -> None:
        if self.quitting:
            return
        self.quitting = True
        print("robot virtual: saliendo")
        if self.hotkeys is not None:
            self.hotkeys.stop()
        if self.link is not None:
            self.link.stop()
        if self.brain is not None:
            self.brain.stop()
        if self.tray is not None:
            self.tray.stop()
        for w in (self.debug_window, self.face.window):
            if w is not None:
                try:
                    w.destroy()
                except Exception:   # noqa: BLE001 - ya cerrada
                    pass

    # ── interruptores ───────────────────────────────────────────────────────────────────────────────────────────
    def toggle_mic(self) -> None:
        self.mic_on = not self.mic_on
        if self.link is not None:
            self.link.mic.enabled = self.mic_on
        print(f"robot virtual: micro {'encendido' if self.mic_on else 'apagado'}")
        self._indicators()

    def toggle_cam(self) -> None:
        self.cam_on = not self.cam_on
        if self.link is not None:
            self.link.camera_enabled = self.cam_on    # la webcam llega en la fase 5
        print(f"robot virtual: cámara {'encendida' if self.cam_on else 'apagada'}")
        self._indicators()

    @property
    def asleep(self) -> bool:
        s = self.face.state_js() if self.face.loaded.is_set() else None
        return bool(s["asleep"]) if s else self._local_asleep

    def toggle_sleep(self) -> None:
        """Dormir o despertar a Rocky. Con cerebro, se lo pide a él (cabeza al centro, reloj; "oye Rocky" lo
        despierta); sin cerebro, solo la cara."""
        on = not self.asleep
        if self.link is not None and self.link.connected:
            try:
                brain_process.api("sleep", {"on": on})
                return
            except OSError as e:
                print(f"robot virtual: el cerebro no contesta a dormir ({e}); duermo solo la cara")
        self._local_asleep = on
        self.face.send({"type": "asleep", "on": on})
        if self.tray is not None:
            self.tray.refresh()

    def _indicators(self) -> None:
        self.face.send({"type": "_indicators", "mic": self.mic_on, "cam": self.cam_on})
        if self.tray is not None:
            self.tray.refresh()

    # ── ventanas ────────────────────────────────────────────────────────────────────────────────────────────────
    def toggle_visible(self) -> None:
        self.hide() if self.visible else self.show()

    def hide(self) -> None:
        self.face.window.hide()
        self.visible = False
        if self.tray is not None:
            self.tray.refresh()

    def show(self) -> None:
        self.face.window.show()
        self.visible = True
        if self.tray is not None:
            self.tray.refresh()

    def open_debug(self) -> None:
        if self.debug_window is not None:
            try:
                self.debug_window.show()
                return
            except Exception:   # noqa: BLE001 - la cerró el usuario
                self.debug_window = None
        w = webview.create_window(DEBUG_TITLE, url=str(UI / "debug.html"),
                                  js_api=_DebugApi(self.face, _brain_faces(), self.link),
                                  width=480, height=820, min_size=(400, 500))
        w.events.closed += lambda: setattr(self, "debug_window", None)
        self.debug_window = w

    def open_web(self) -> None:
        webbrowser.open(f"http://localhost:{brain_process.API_PORT}/")

    def restart_brain(self) -> None:
        if self.brain is not None:
            print(f"robot virtual: {self.brain.restart()}")

    def toggle_autostart(self) -> None:
        try:
            autostart.set_enabled(not self.autostart)
            self.autostart = autostart.enabled()
        except OSError as e:
            print(f"robot virtual: no pude cambiar el arranque con Windows ({e})")
        if self.tray is not None:
            self.tray.refresh()


def run(debug: bool, brain: bool = True) -> None:
    win32.make_dpi_aware()
    if not win32.single_instance("DeskRobotVirtual"):
        print("robot virtual: ya hay uno abierto (mira la bandeja del sistema)")
        return
    Controller(debug, brain).run()
