"""Abre el robot virtual sin consola (lo usa el arranque con Windows: autostart.py).

Doble clic con el pythonw del venv del cerebro, o: server\.venv\Scripts\pythonw.exe desktop\run_virtual_robot.pyw
La salida va a %APPDATA%\desk-robot-virtual\app.log.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from virtual_robot.__main__ import main  # noqa: E402

main()
