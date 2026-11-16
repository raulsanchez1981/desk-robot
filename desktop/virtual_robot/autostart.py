"""Arrancar con Windows: una entrada en HKCU\\...\\Run que abre el robot virtual sin consola (pythonw)."""

from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "DeskRobotVirtual"
DESKTOP = Path(__file__).resolve().parents[1]


def command() -> str:
    """pythonw del venv del cerebro + desktop/run_virtual_robot.pyw (no depende del directorio de trabajo)."""
    venv = DESKTOP.parent / "server" / ".venv" / "Scripts"
    pythonw = venv / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" "{DESKTOP / "run_virtual_robot.pyw"}"'


def enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, NAME)
            return bool(value)
    except OSError:
        return False


def set_enabled(on: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, NAME)
            except FileNotFoundError:
                pass
