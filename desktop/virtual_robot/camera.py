"""La webcam del PC haciendo de la cámara del robot (firmware/src/camera.cpp).

El cerebro pide un stream (`stream {on, fps, size}`) y fotos nítidas (`snapshot {size}`). Se le mandan como la placa:
frames 0x02 con un JPEG cada 1/fps (8 fps mientras habla, 5 dormido, como main.cpp) y 0x03 con la foto nítida.

- Se captura a 1280x720 (en esta webcam, 10 fps por DirectShow): el stream va reducido a 640 px de ancho (320 en
  "qvga") y la foto nítida es el frame entero, sin reabrir la cámara.
- Cada imagen va espejada: el cerebro la espeja otra vez (CAMERA_MIRROR, pensado para el sensor del robot) y queda
  como se ve de verdad. El giro (CAMERA_ROTATE) se pone a 0 al conectar (link.py).
- La cámara solo está abierta mientras el cerebro quiere imagen y el interruptor está encendido; apagada se libera
  (se apaga su luz).
- Elige sola la primera cámara que no dé imagen negra (las cámaras virtuales sin fuente salen negras); el índice se
  puede fijar con "camera_index" en %APPDATA%\\desk-robot-virtual\\config.json.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable

from .settings import config_dir

CAPTURE_W, CAPTURE_H = 1280, 720
STREAM_W = {"qvga": 320, "vga": 640}
SNAPSHOT_W = {"vga": 640, "svga": 800, "xga": 1024, "sxga": 1280, "uxga": 1600}
TALKING_FPS, ASLEEP_FPS = 8.0, 5.0       # main.cpp: TALKING_FRAME_MS 125, ASLEEP_FRAME_MS 200
BLACK = 5.0                              # brillo medio por debajo del cual la imagen se considera negra


def _cv2():
    import cv2
    return cv2


def configured_index() -> int | None:
    try:
        v = json.loads((config_dir() / "config.json").read_text(encoding="utf-8")).get("camera_index")
        return v if isinstance(v, int) and v >= 0 else None
    except (OSError, ValueError, AttributeError):
        return None


def find_camera(max_index: int = 4) -> int | None:
    """La primera cámara que da imagen que no es negra."""
    cv2 = _cv2()
    for idx in range(max_index):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        try:
            if not cap.isOpened():
                continue
            for _ in range(5):             # las primeras pueden salir oscuras mientras ajusta la exposición
                ok, frame = cap.read()
                if ok and frame is not None and float(frame.mean()) > BLACK:
                    return idx
        finally:
            cap.release()
    return None


class Camera:
    def __init__(self, send: Callable[[bytes], None], speaking: Callable[[], bool] = lambda: False,
                 asleep: Callable[[], bool] = lambda: False) -> None:
        """send(frame): un frame binario ya con su byte de tipo (0x02 stream, 0x03 foto nítida)."""
        self.send, self.speaking, self.asleep = send, speaking, asleep
        self.enabled = True              # interruptor del usuario
        self.wanted = False              # el cerebro pidió stream
        self.fps, self.size = 10.0, "vga"
        self.index: int | None = None
        self.status = "apagada"
        self._cap = None
        self._frame = None               # último frame (BGR) y cuándo llegó
        self._frame_at = 0.0
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._snapshot_size: str | None = None
        threading.Thread(target=self._run, daemon=True, name="camera").start()

    # ── órdenes (desde el enlace) ───────────────────────────────────────────────────────────────────────────────
    def set_stream(self, on: bool, fps: float | None = None, size: str | None = None) -> None:
        self.wanted = bool(on)
        if isinstance(fps, (int, float)) and fps > 0:
            self.fps = min(30.0, float(fps))
        if size in STREAM_W:
            self.size = size
        self._wake.set()

    def snapshot(self, size: str | None) -> None:
        self._snapshot_size = size if size in SNAPSHOT_W else "xga"
        self._wake.set()

    def set_enabled(self, on: bool) -> None:
        self.enabled = bool(on)
        self._wake.set()

    @property
    def active(self) -> bool:
        return self.enabled and self.wanted

    # ── el hilo de la cámara ────────────────────────────────────────────────────────────────────────────────────
    def _run(self) -> None:
        cv2 = None
        last_sent = 0.0
        while True:
            if not self.active:
                self._close()
                self.status = "apagada (interruptor)" if not self.enabled else "en espera (el cerebro no pide imagen)"
                self._wake.wait(1.0)
                self._wake.clear()
                continue
            if self._cap is None:
                cv2 = cv2 or _cv2()
                if not self._open(cv2):
                    self._wake.wait(10.0)    # sin cámara: reintento cada 10 s
                    self._wake.clear()
                    continue
            ok, frame = self._cap.read()     # a la velocidad de la cámara (~10 fps a 1280x720)
            if not ok or frame is None:
                self.status = "sin imagen: la reabro"
                self._close()
                continue
            frame = cv2.flip(frame, 1)       # el cerebro la vuelve a espejar (ver arriba)
            with self._lock:
                self._frame, self._frame_at = frame, time.time()
            if self._snapshot_size:
                size, self._snapshot_size = self._snapshot_size, None
                self._send_jpeg(cv2, b"\x03", frame, SNAPSHOT_W[size], quality=90)
            fps = self.fps
            if self.speaking():
                fps = min(fps, TALKING_FPS)
            elif self.asleep():
                fps = min(fps, ASLEEP_FPS)
            now = time.monotonic()
            if now - last_sent >= 1.0 / fps - 0.01:
                last_sent = now
                self._send_jpeg(cv2, b"\x02", frame, STREAM_W[self.size], quality=80)

    def _open(self, cv2) -> bool:
        idx = configured_index()
        if idx is None:
            idx = self.index if self.index is not None else find_camera()
        if idx is None:
            self.status = "no encuentro ninguna webcam con imagen"
            return False
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_H)
        if not cap.isOpened():
            cap.release()
            self.status = f"no puedo abrir la webcam {idx} (¿la usa otra aplicación?)"
            return False
        self._cap, self.index = cap, idx
        self.status = f"webcam {idx} encendida"
        print(f"robot virtual: {self.status}")
        return True

    def _close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            with self._lock:
                self._frame = None
            print("robot virtual: webcam apagada")

    def _send_jpeg(self, cv2, kind: bytes, frame, width: int, quality: int) -> None:
        h, w = frame.shape[:2]
        if w > width:
            frame = cv2.resize(frame, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok:
            self.send(kind + jpg.tobytes())
