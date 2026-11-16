"""El enlace con el cerebro: hace lo mismo que firmware/src/link.cpp (docs/protocol.md).

Se conecta a ws://127.0.0.1:8765, se presenta con un `hello` que lleva ROBOT_TOKEN (leído de server/.env y nunca
impreso), reenvía a la cara los mensajes del cerebro, toca su voz, le manda el micro y un `state` cada 5 s. Si el
cerebro no está o se cae, la cara se duerme (como la placa) y se reintenta cada 3 s.

Corre en su propio hilo con su propio bucle asyncio; la ventana vive en el hilo principal (pywebview).
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import websockets

from .audio import Mic, Speaker
from .camera import Camera

FW = "virtual-0.1.0"
RETRY_S = 3.0
STATE_EVERY_S = 5.0
ENV_FILE = Path(__file__).resolve().parents[2] / "server" / ".env"


def read_token(path: Path = ENV_FILE) -> str:
    """ROBOT_TOKEN de server/.env, como lo lee brain/config.py (lo exportado en el entorno gana)."""
    import os
    if os.environ.get("ROBOT_TOKEN"):
        return os.environ["ROBOT_TOKEN"]
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith("ROBOT_TOKEN=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return ""


class BrainLink:
    def __init__(self, to_face: Callable[[dict], None], url: str = "ws://127.0.0.1:8765") -> None:
        self.to_face, self.url = to_face, url
        self.connected = False
        self._stopping = False
        self.asleep = True           # lo último que dijo el cerebro (la cámara va a 5 fps dormido, como la placa)
        self.status = "arrancando"
        self.pan, self.emotion = 0.0, "neutral"
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None
        self._outbox: asyncio.Queue | None = None
        self.speaker = Speaker(on_done=self._send_json_threadsafe, on_mouth=self._mouth)
        from .audio import ECHO_TAIL_S
        from .settings import load_echo_tail
        self.speaker.echo_tail = load_echo_tail(ECHO_TAIL_S)
        self.mic = Mic(on_frame=self._send_mic_threadsafe, speaker=self.speaker)
        self.camera = Camera(send=self._enqueue, speaking=lambda: self.speaker.speaking, asleep=lambda: self.asleep)

    @property
    def camera_enabled(self) -> bool:
        return self.camera.enabled

    @camera_enabled.setter
    def camera_enabled(self, on: bool) -> None:
        self.camera.set_enabled(on)

    # ── arranque ────────────────────────────────────────────────────────────────────────────────────────────────
    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="brain-link").start()

    def stop(self) -> None:
        """Cierra la conexión y el audio (al salir de la app)."""
        self._stopping = True
        self.camera.set_enabled(False)
        if self._loop is not None and self._ws is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop).result(timeout=2)
            except Exception:   # noqa: BLE001 - ya estaba cerrada
                pass
        for part in (self.mic, self.speaker):
            try:
                part.stop()
            except Exception:   # noqa: BLE001
                pass

    def _run(self) -> None:
        try:
            self.speaker.start()
            self.mic.start()
            print(f"robot virtual: micro \"{self.mic.device_name}\", altavoz por defecto "
                  f"(latencia {self.speaker.latency * 1000:.0f} ms)")
        except Exception as e:   # noqa: BLE001 - sin audio la cara sigue funcionando
            print(f"robot virtual: sin audio ({e})")
        asyncio.run(self._main())

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._outbox = asyncio.Queue()
        token = read_token()
        if len(token) < 16:
            self.status = "falta ROBOT_TOKEN en server/.env"
            print(f"robot virtual: {self.status}")
            return
        warned = False
        while not self._stopping:
            try:
                async with websockets.connect(self.url, max_size=1024 * 1024, open_timeout=5) as ws:
                    await ws.send(json.dumps({"type": "hello", "who": "virtual-robot", "fw": FW, "token": token,
                                              "boot": "app start", "up_s": int(time.monotonic())}))
                    self._outbox = asyncio.Queue()          # nada viejo de una conexión anterior
                    self._ws, self.connected, warned = ws, True, False
                    self.status = "conectado"
                    print("robot virtual: conectado al cerebro")
                    threading.Thread(target=self._upright_camera, daemon=True).start()
                    tasks = [asyncio.create_task(c) for c in (self._receive(ws), self._send(ws), self._heartbeat(ws))]
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for t in pending:
                        t.cancel()
                    for t in done:
                        if t.exception() and not isinstance(t.exception(), websockets.ConnectionClosed):
                            print(f"robot virtual: error en el enlace: {t.exception()!r}")
            except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as e:
                if not warned and not self._stopping:
                    print(f"robot virtual: sin cerebro en {self.url} ({type(e).__name__}); reintento cada "
                          f"{RETRY_S:.0f} s")
                    warned = True
            finally:
                if self.connected:
                    print("robot virtual: desconectado del cerebro")
                self._ws, self.connected = None, False
                self.status = "sin cerebro"
                self.mic.wanted = False
                self.camera.set_stream(False)
                self.to_face({"type": "asleep", "on": True})   # como la placa sin cerebro: a dormir
            await asyncio.sleep(RETRY_S)

    # ── del cerebro ─────────────────────────────────────────────────────────────────────────────────────────────
    async def _receive(self, ws) -> None:
        async for message in ws:
            if isinstance(message, bytes):
                if message[:1] == b"\x01" and len(message) > 1:
                    self.speaker.feed(message[1:])
                continue
            try:
                msg = json.loads(message)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict):
                self._handle(msg)

    def _handle(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "speak_begin":
            self.speaker.begin()
        elif kind == "speak_end":
            self.speaker.end()
        elif kind == "mic":
            self.mic.wanted = bool(msg.get("on"))
        elif kind == "volume" and isinstance(msg.get("level"), (int, float)):
            self.speaker.volume = max(0.0, min(1.0, float(msg["level"])))
        elif kind == "stream":
            self.camera.set_stream(bool(msg.get("on")), msg.get("fps"), msg.get("size"))
        elif kind == "snapshot":
            self.camera.snapshot(msg.get("size"))
        else:
            if kind == "asleep":
                self.asleep = bool(msg.get("on"))
            if kind == "emotion":
                self.emotion = msg.get("name", self.emotion)
            elif kind == "pan" and isinstance(msg.get("deg"), (int, float)):
                self.pan = float(msg["deg"])
            self.to_face(msg)   # emotion, pan, tilt, motion, asleep, face, mouth, settings, glance...

    # ── al cerebro ──────────────────────────────────────────────────────────────────────────────────────────────
    async def _send(self, ws) -> None:
        while True:
            item = await self._outbox.get()
            await ws.send(item)

    async def _heartbeat(self, ws) -> None:
        while True:
            await asyncio.sleep(STATE_EVERY_S)
            await ws.send(json.dumps({"type": "state", "pan": round(self.pan, 1), "emotion": self.emotion}))

    def _send_json_threadsafe(self, msg: dict) -> None:
        self._enqueue(json.dumps(msg))

    def _send_mic_threadsafe(self, pcm: bytes) -> None:
        self._enqueue(b"\x01" + pcm)

    def _enqueue(self, item) -> None:
        if self.connected and self._loop is not None:
            self._loop.call_soon_threadsafe(self._outbox.put_nowait, item)

    def _upright_camera(self) -> None:
        """El cerebro gira cada imagen CAMERA_ROTATE grados (270 para la cámara de lado del robot V2); la webcam
        ya viene derecha. Se pone a 0 por su API (queda guardado en server/settings.json)."""
        from . import brain_process
        for _ in range(20):                  # la API (8767) puede tardar un poco más que el WebSocket
            try:
                rotate = brain_process.status().get("camera_rotate")
                if rotate not in (0, None):
                    brain_process.api("camera_rotate", {"deg": 0})
                    print(f"robot virtual: giro de cámara del cerebro {rotate}° -> 0° (la webcam ya viene derecha)")
                return
            except OSError:
                time.sleep(1)

    def _mouth(self, level: float) -> None:
        self.to_face({"type": "mouth", "level": round(level, 3)})
