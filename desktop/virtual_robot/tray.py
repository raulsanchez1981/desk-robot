"""Icono en la bandeja del sistema (pystray) con el menú del robot virtual."""

from __future__ import annotations

import threading
from collections.abc import Callable

import pystray
from PIL import Image, ImageDraw


def icon_image(mic_on: bool = True, cam_on: bool = True, size: int = 64) -> Image.Image:
    """Los dos ojos en blanco sobre negro; un punto rojo en la esquina si el micro o la cámara están apagados."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64
    d.rounded_rectangle((2 * s, 12 * s, 62 * s, 52 * s), radius=8 * s, fill=(0, 0, 0, 255),
                        outline=(255, 255, 255, 255), width=max(1, int(2 * s)))
    for cx in (21, 43):
        d.rounded_rectangle(((cx - 8) * s, 22 * s, (cx + 8) * s, 42 * s), radius=6 * s, fill=(255, 255, 255, 255))
    if not (mic_on and cam_on):
        d.ellipse((44 * s, 0, 64 * s, 20 * s), fill=(230, 40, 40, 255), outline=(0, 0, 0, 255), width=max(1, int(2 * s)))
    return img


class Tray:
    def __init__(self, app) -> None:
        """app: el Controller de app.py (toggle_*, show/hide, quit... y el estado para las marcas del menú)."""
        self.app = app
        item = pystray.MenuItem
        self.icon = pystray.Icon("desk-robot-virtual", icon_image(), "Robot virtual", menu=pystray.Menu(
            item("Mostrar la cara", self._do(app.toggle_visible), checked=lambda _: app.visible, default=True),
            pystray.Menu.SEPARATOR,
            item(f"Micro  ({app.HOTKEYS['mic']})", self._do(app.toggle_mic), checked=lambda _: app.mic_on),
            item(f"Cámara  ({app.HOTKEYS['cam']})", self._do(app.toggle_cam), checked=lambda _: app.cam_on),
            item(lambda _: f"{'Despertar' if app.asleep else 'Dormir'}  ({app.HOTKEYS['sleep']})",
                 self._do(app.toggle_sleep)),
            pystray.Menu.SEPARATOR,
            item("Personaje", pystray.Menu(*[
                item(p["name"], self._do(lambda pid=p["id"]: app.switch_character(pid)),
                     checked=lambda _, pid=p["id"]: app.active_character() == pid, radio=True)
                for p in app.characters()])),
            pystray.Menu.SEPARATOR,
            item("Panel de depuración", self._do(app.open_debug)),
            item("Ajustes y panel web", self._do(app.open_web)),
            item("Reiniciar el cerebro", self._do(app.restart_brain)),
            item("Arrancar con Windows", self._do(app.toggle_autostart), checked=lambda _: app.autostart),
            pystray.Menu.SEPARATOR,
            item("Salir", self._do(app.quit)),
        ))

    @staticmethod
    def _do(fn: Callable[[], None]):
        # pystray llama desde su hilo; lo que tarde (HTTP al cerebro, pararlo) va aparte para no congelar el menú
        return lambda icon, item: threading.Thread(target=fn, daemon=True).start()

    def start(self) -> None:
        threading.Thread(target=self.icon.run, daemon=True, name="tray").start()

    def refresh(self) -> None:
        self.icon.icon = icon_image(self.app.mic_on, self.app.cam_on)
        self.icon.title = "Robot virtual" + ("" if self.app.mic_on else " · micro apagado") + \
            ("" if self.app.cam_on else " · cámara apagada")
        self.icon.update_menu()

    def notify(self, text: str) -> None:
        try:
            self.icon.notify(text, "Robot virtual")
        except Exception:   # noqa: BLE001 - las notificaciones son un extra
            pass

    def stop(self) -> None:
        self.icon.stop()
