"""El cerebro (server/, python -m brain.main) como proceso hijo del robot virtual, y su API local.

Si ya hay un cerebro escuchando en el puerto 8765 (arrancado a mano o desde el launcher del dashboard), se usa ese y
no se arranca otro. El hijo recibe stdin en un pipe abierto (con EOF el cerebro se apaga, main.py console_loop) y
se cierra con su propio "quit". Su salida va a %APPDATA%\\desk-robot-virtual\\brain.log con cualquier clave o token
enmascarado, y las últimas líneas quedan en memoria para el panel.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

from .settings import config_dir

SERVER = Path(__file__).resolve().parents[2] / "server"
BRAIN_PORT, API_PORT = 8765, 8767
# Claves de API (sk-..., sk-ant-...), tokens hex largos y cualquier KEY=valor / TOKEN=valor.
_SECRET = re.compile(r"sk-[A-Za-z0-9_-]{8,}|\b[0-9a-f]{32,}\b|((?:KEY|TOKEN|SECRET)\w*\s*[=:]\s*)\S+", re.IGNORECASE)


def redact(line: str) -> str:
    return _SECRET.sub(lambda m: (m.group(1) + "***") if m.group(1) else "***", line)


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def brain_python() -> Path:
    for cand in (SERVER / ".venv" / "Scripts" / "python.exe", SERVER / ".venv" / "bin" / "python"):
        if cand.exists():
            return cand
    raise FileNotFoundError(f"no encuentro el venv del cerebro en {SERVER / '.venv'}")


class BrainProcess:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.external = False
        self.warning = ""
        self.lines: deque[str] = deque(maxlen=300)
        self.log_path = config_dir() / "brain.log"

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> str:
        """Arranca el cerebro salvo que ya haya uno. Devuelve qué ha pasado, para el log."""
        if self.running:
            return "el cerebro ya está en marcha"
        if port_open(BRAIN_PORT):
            self.external = True
            return "uso el cerebro que ya estaba en marcha"
        self.warning = ""
        if port_open(API_PORT):
            # Un cerebro a medio cerrar: su WebSocket ya no escucha pero su página/API (8767) sí. El nuevo no podrá
            # abrir 8767 y las órdenes (dormir...) irían al viejo, que ya no tiene bucle ("Event loop is closed").
            self.warning = (f"el puerto {API_PORT} lo tiene otro proceso (¿un cerebro colgado de antes?): ciérralo; "
                            f"mientras tanto dormir/despertar solo afecta a la cara")
        self.external = False
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        self.proc = subprocess.Popen(
            [str(brain_python()), "-u", "-m", "brain.main"], cwd=SERVER, env=env, text=True, encoding="utf-8",
            errors="replace", bufsize=1, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True, name="brain-log").start()
        return "cerebro arrancado"

    def _pump(self, proc: subprocess.Popen) -> None:
        with open(self.log_path, "a", encoding="utf-8") as log:
            log.write(f"\n── {time.strftime('%Y-%m-%d %H:%M:%S')} cerebro arrancado por el robot virtual ──\n")
            for line in proc.stdout:
                line = redact(line.rstrip())
                if "inference_feedback_manager" in line:   # ruido de MediaPipe
                    continue
                self.lines.append(line)
                log.write(line + "\n")
                log.flush()
            log.write(f"── cerebro terminado (código {proc.wait()}) ──\n")

    def command(self, line: str) -> bool:
        """Una línea para la consola del cerebro (ask, say, emo...). Solo si lo arrancamos nosotros."""
        if not self.running:
            return False
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()
        return True

    def stop(self, timeout: float = 8.0) -> None:
        if not self.running:
            return
        proc = self.proc
        try:
            self.command("quit")
            proc.wait(timeout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            proc.terminate()
            try:
                proc.wait(3)
            except subprocess.TimeoutExpired:
                proc.kill()

    def restart(self) -> str:
        if self.external:
            return "el cerebro no lo arranqué yo: reinícialo donde lo arrancaste"
        self.stop()
        return self.start()


def api(action: str, payload: dict | None = None, timeout: float = 5.0) -> dict:
    """Un control de la API local del cerebro (eyes.py: POST /api/<acción> con X-Rocky-Console)."""
    req = urllib.request.Request(f"http://127.0.0.1:{API_PORT}/api/{action}", data=json.dumps(payload or {}).encode(),
                                 headers={"Content-Type": "application/json", "X-Rocky-Console": "1"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:   # el cerebro explica el error en el cuerpo
        detail = e.read().decode("utf-8", "replace")[:300]
        raise OSError(f"HTTP {e.code}: {detail}") from None


def status(timeout: float = 2.0) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{API_PORT}/status", timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


LAUNCHER_PORT = 8766


class LauncherProcess:
    """El dashboard de Casey (server/launcher.py, puerto 8766): ajustes, personalidades, packs de caras y la vista en
    directo. No arranca ningún cerebro por su cuenta; al nuestro lo ve como "externo" (lo muestra y lo controla, pero
    no lo para ni reinicia). Si ya hay un launcher abierto, se usa ese."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.log_path = config_dir() / "launcher.log"

    @property
    def available(self) -> bool:
        return port_open(LAUNCHER_PORT)

    def start(self) -> str:
        if self.proc is not None and self.proc.poll() is None:
            return "el panel ya está en marcha"
        if port_open(LAUNCHER_PORT):
            return "uso el panel que ya estaba abierto"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k != "ROCKY_START_BRAIN"}   # el cerebro lo lleva la app
        env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen(
            [str(brain_python()), "-u", "launcher.py"], cwd=SERVER, env=env, text=True, encoding="utf-8",
            errors="replace", stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True, name="launcher-log").start()
        return f"panel en http://localhost:{LAUNCHER_PORT}/"

    def _pump(self, proc: subprocess.Popen) -> None:
        with open(self.log_path, "a", encoding="utf-8") as log:
            log.write(f"\n── {time.strftime('%Y-%m-%d %H:%M:%S')} panel arrancado por el robot virtual ──\n")
            for line in proc.stdout:
                log.write(redact(line.rstrip()) + "\n")
                log.flush()

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
