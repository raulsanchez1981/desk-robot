"""Atajos de teclado globales con RegisterHotKey (Win32), en un hilo con su propio bucle de mensajes."""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
_MODS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT}


def parse(combo: str) -> tuple[int, int]:
    """"Ctrl+Alt+M" -> (modificadores, código de tecla virtual)."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError("atajo vacío")
    *mods, key = parts
    mask = 0
    for m in mods:
        if m not in _MODS:
            raise ValueError(f"modificador desconocido: {m}")
        mask |= _MODS[m]
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError(f"tecla no soportada: {key}")
    return mask | MOD_NOREPEAT, vk


class Hotkeys:
    def __init__(self, bindings: dict[str, Callable[[], None]]) -> None:
        self.bindings = bindings          # "Ctrl+Alt+M" -> función
        self.failed: list[str] = []       # los que otra aplicación ya tenía
        self._thread_id = 0

    def start(self) -> None:
        ready = threading.Event()
        threading.Thread(target=self._run, args=(ready,), daemon=True, name="hotkeys").start()
        ready.wait(2)

    def _run(self, ready: threading.Event) -> None:
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        actions: dict[int, Callable[[], None]] = {}
        for i, (combo, fn) in enumerate(self.bindings.items(), start=1):
            mods, vk = parse(combo)
            if user32.RegisterHotKey(None, i, mods, vk):
                actions[i] = fn
            else:
                self.failed.append(combo)
        ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in actions:
                try:
                    actions[msg.wParam]()
                except Exception as e:   # noqa: BLE001 - un atajo roto no tumba los demás
                    print(f"atajo: {e!r}")
        for i in actions:
            user32.UnregisterHotKey(None, i)

    def stop(self) -> None:
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
