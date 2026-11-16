"""Micro y altavoz del PC haciendo de los del robot (firmware/src/mic.cpp y speaker.cpp).

Micro: 16 kHz mono s16le en trozos de 30 ms (480 muestras), lo que manda la placa en los frames 0x01.
Altavoz: la voz llega del cerebro en frames 0x01 entre speak_begin y speak_end; empieza a sonar con 200 ms de
colchón y, cuando ha salido entera por el altavoz (más la latencia del dispositivo y una cola por la reverberación de
la sala), se avisa con speak_done.

Anti-eco, como la placa: mientras suena la voz (y ECHO_TAIL_S después) el micro no se manda. El cerebro además no
escucha desde que empieza a hablar hasta que recibe speak_done.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

import numpy as np

RATE = 16_000
MIC_FRAME = 480                 # muestras: 30 ms, como mic.cpp
HEAD_START_S = 0.2              # colchón antes de empezar a sonar (speak_begin con bytes 0)
# Tras la última muestra audible la sala aún suena: micro cortado este rato más. Medido el 2026-11-16 con altavoces
# USB y el micro de la webcam: el eco se apaga antes de speak_done y el altavoz tarda ~0,12 s más de lo que
# declara, así que 0,35 s sobra. Con Bluetooth (más retardo) súbelo con "echo_tail_s" en config.json.
ECHO_TAIL_S = 0.35
MOUTH_EVERY_S = 0.04            # nivel de boca 25 veces por segundo, como el mensaje "mouth"


class Speaker:
    """Reproduce la voz del cerebro y dice cuándo ha terminado de sonar de verdad."""

    def __init__(self, on_done: Callable[[dict], None], on_mouth: Callable[[float], None]) -> None:
        self.on_done, self.on_mouth = on_done, on_mouth
        self.volume = 0.7
        self.echo_tail = ECHO_TAIL_S
        self._lock = threading.Lock()
        self._buf = bytearray()
        self._active = False        # entre speak_begin y el final audible
        self._playing = False       # ya pasó el colchón
        self._started = False       # esta respuesta ya empezó a sonar (arranca una sola vez)
        self._ended = False         # llegó speak_end
        self._drained_at = 0.0      # cuándo se entregó la última muestra al dispositivo
        self._began_at = self._started_at = 0.0
        self._underruns = 0
        self._levels: deque[tuple[float, float]] = deque()   # (cuándo se oirá, nivel RMS)
        self.quiet_until = 0.0      # hasta cuándo el micro debe seguir callado
        self._stream = None
        self.latency = 0.0

    def start(self) -> None:
        import sounddevice as sd
        self._stream = sd.OutputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=320,
                                       callback=self._callback)
        self._stream.start()
        self.latency = float(self._stream.latency or 0.0)
        threading.Thread(target=self._watch, daemon=True, name="speaker-watch").start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()

    @property
    def speaking(self) -> bool:
        return self._active

    def begin(self) -> None:
        with self._lock:
            self._buf.clear()
            self._active, self._playing, self._ended, self._started = True, False, False, False
            self._began_at, self._underruns = time.monotonic(), 0
            self.quiet_until = float("inf")

    def feed(self, pcm: bytes) -> None:
        with self._lock:
            if self._active:
                self._buf += pcm

    def end(self) -> None:
        with self._lock:
            self._ended = True

    def _callback(self, outdata, frames, _time, _status) -> None:
        need = frames * 2
        with self._lock:
            if self._active and not self._started and (len(self._buf) >= HEAD_START_S * RATE * 2 or self._ended):
                self._playing = self._started = True
                self._started_at = time.monotonic()
            if not self._playing:
                outdata[:] = 0
                return
            chunk = bytes(self._buf[:need])
            del self._buf[:need]
            if len(chunk) < need:
                if self._ended:
                    self._playing = False
                    self._drained_at = time.monotonic()
                else:
                    self._underruns += 1      # la voz llega más lenta de lo que suena: hueco de silencio
                chunk += b"\x00" * (need - len(chunk))
        samples = np.frombuffer(chunk, dtype=np.int16)
        level = float(np.sqrt(np.mean((samples.astype(np.float32) / 32768.0) ** 2)))
        self._levels.append((time.monotonic() + self.latency, level))
        outdata[:, 0] = (samples.astype(np.float32) * self.volume).astype(np.int16)

    def _watch(self) -> None:
        """Mueve la boca al ritmo de lo que suena y avisa speak_done al acabar."""
        mouth_open = False
        while True:
            time.sleep(MOUTH_EVERY_S)
            now = time.monotonic()
            level = None
            while self._levels and self._levels[0][0] <= now:
                level = self._levels.popleft()[1]
            if level is not None and self._active:
                self.on_mouth(level)
                mouth_open = True
            with self._lock:
                finished = self._active and self._ended and not self._playing and self._drained_at \
                    and not self._buf and now >= self._drained_at + self.latency
                if finished:
                    self._active = False
                    self.quiet_until = now + self.echo_tail
                    wait_ms = int(max(0.0, self._started_at - self._began_at) * 1000)   # colchón, como la placa
                    underruns, self._drained_at = self._underruns, 0.0
            if finished:
                if mouth_open:
                    self.on_mouth(-1)
                    mouth_open = False
                self.on_done({"type": "speak_done", "dry_ms": underruns * 20, "wait_ms": wait_ms,
                              "next_ms": int(HEAD_START_S * 1000)})


class Mic:
    """El micro del PC en trozos de 30 ms. Callado mientras habla el robot (y un poco después)."""

    def __init__(self, on_frame: Callable[[bytes], None], speaker: Speaker) -> None:
        self.on_frame, self.speaker = on_frame, speaker
        self.wanted = False      # el cerebro pidió el micro (mensaje "mic")
        self.enabled = True      # interruptor del usuario (fase 4)
        self._stream = None
        self.device_name = ""

    def start(self) -> None:
        import sounddevice as sd
        self._stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=MIC_FRAME,
                                      callback=self._callback)
        self._stream.start()
        try:
            self.device_name = sd.query_devices(kind="input")["name"]
        except Exception:   # noqa: BLE001 - solo para el log
            self.device_name = "?"

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()

    def _callback(self, indata, frames, _time, _status) -> None:
        if not (self.wanted and self.enabled) or self.speaker.speaking or time.monotonic() < self.speaker.quiet_until:
            return
        if frames == MIC_FRAME:
            self.on_frame(indata[:, 0].tobytes())
