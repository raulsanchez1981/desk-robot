"""Ajustes del robot virtual que no son del cerebro: dónde está la ventana y cuánto mide.

Se guardan en %APPDATA%\\desk-robot-virtual\\config.json (fuera del repo). Nunca contienen secretos.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

MIN_SIZE, MAX_SIZE, DEFAULT_SIZE = 120, 900, 240
MARGIN = 24   # separación de la esquina de la pantalla en la primera ejecución


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "desk-robot-virtual"


@dataclass
class WindowState:
    x: int | None = None
    y: int | None = None
    size: int = DEFAULT_SIZE

    def clamped_size(self) -> int:
        return max(MIN_SIZE, min(MAX_SIZE, int(self.size)))


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


def place(state: WindowState, monitors: list[tuple[int, int, int, int]],
          work_area: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """(x, y, tamaño) donde abrir la ventana: la posición guardada si sigue viéndose entera en algún monitor
    (rectángulos left, top, right, bottom); si no (primera vez, monitor desconectado), abajo a la derecha del área
    de trabajo del monitor principal."""
    size = state.clamped_size()
    if state.x is not None and state.y is not None:
        for left, top, right, bottom in monitors:
            if left <= state.x and top <= state.y and state.x + size <= right and state.y + size <= bottom:
                return state.x, state.y, size
    left, top, right, bottom = work_area
    return right - size - MARGIN, bottom - size - MARGIN, size
