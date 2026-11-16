"""Ajustes del robot virtual que no son del cerebro: dónde está la ventana y cuánto mide.

Se guardan en %APPDATA%\\desk-robot-virtual\\config.json (fuera del repo). Nunca contienen secretos.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

MIN_SIZE, MAX_SIZE, DEFAULT_SIZE = 160, 1400, 320   # ancho; el alto es la mitad (2:1)
MARGIN = 24   # separación de la esquina de la pantalla en la primera ejecución


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "desk-robot-virtual"


@dataclass
class WindowState:
    x: int | None = None
    y: int | None = None
    size: int = DEFAULT_SIZE      # ancho de la ventana; el alto es size // 2, como la pantalla de 128x64

    def clamped_size(self) -> int:
        return max(MIN_SIZE, min(MAX_SIZE, int(self.size)))


def height_for(width: int) -> int:
    return width // 2


def load(path: Path | None = None) -> WindowState:
    path = path or config_dir() / "config.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8")).get("window", {})
        state = WindowState(x=raw.get("x"), y=raw.get("y"), size=raw.get("size", DEFAULT_SIZE))
        if not all(isinstance(v, int) or v is None for v in (state.x, state.y)) or not isinstance(state.size, int):
            return WindowState()
        return state
    except (OSError, ValueError, AttributeError):
        return WindowState()


def save(state: WindowState, path: Path | None = None) -> None:
    path = path or config_dir() / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data["window"] = asdict(state)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


# Atajos globales (se pueden cambiar en config.json, clave "hotkeys"). Ctrl+Alt+M lo usa a menudo otra aplicación.
DEFAULT_HOTKEYS = {"mic": "Ctrl+Alt+Shift+M", "cam": "Ctrl+Alt+C", "sleep": "Ctrl+Alt+S"}


def load_hotkeys(path: Path | None = None) -> dict[str, str]:
    """Los atajos de config.json sobre los de por defecto; se escriben ahí la primera vez para que se vean."""
    path = path or config_dir() / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    saved = data.get("hotkeys") if isinstance(data.get("hotkeys"), dict) else {}
    keys = {k: str(saved.get(k) or v) for k, v in DEFAULT_HOTKEYS.items()}
    if saved != keys:
        data["hotkeys"] = keys
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass
    return keys


def load_echo_tail(default: float, path: Path | None = None) -> float:
    """"echo_tail_s" de config.json (0-2 s), para altavoces con más retardo; si no, el de por defecto."""
    path = path or config_dir() / "config.json"
    try:
        v = json.loads(path.read_text(encoding="utf-8")).get("echo_tail_s")
        return float(v) if isinstance(v, (int, float)) and 0 <= v <= 2 else default
    except (OSError, ValueError, AttributeError):
        return default


def place(state: WindowState, monitors: list[tuple[int, int, int, int]],
          work_area: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """(x, y, ancho) donde abrir la ventana: la posición guardada si sigue viéndose entera en algún monitor
    (rectángulos left, top, right, bottom); si no (primera vez, monitor desconectado), abajo a la derecha del área
    de trabajo del monitor principal."""
    size = state.clamped_size()
    height = height_for(size)
    if state.x is not None and state.y is not None:
        for left, top, right, bottom in monitors:
            if left <= state.x and top <= state.y and state.x + size <= right and state.y + height <= bottom:
                return state.x, state.y, size
    left, top, right, bottom = work_area
    return right - size - MARGIN, bottom - height - MARGIN, size
