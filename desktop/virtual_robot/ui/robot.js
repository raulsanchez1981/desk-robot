// El robot virtual en la ventana: cara (FaceKit, la copia del firmware), cuello simulado, reloj al dormir.
//
// Se controla con robot.handle(msg), donde msg tiene la misma forma que los mensajes del cerebro al robot
// (docs/protocol.md): emotion, pan, tilt, motion, asleep, face, mouth, settings, volume, glance... Así, el panel de
// depuración (fase 2) y el enlace con el cerebro (fase 3) usan el mismo camino.
"use strict";

// ── Cuello: copia del perfil de movimiento del firmware (ServoNeck::update; server/brain/tracker.py Motion) ──
class Motion {
  constructor(speed, accel) { this.speed = speed; this.accel = accel; this.pos = this.target = this.vel = 0; this.t = 0; }
  setTarget(deg) { this.target = deg; }
  advance(now) {                       // now en segundos
    const DT = 0.02;
    if (!this.t) this.t = now;
    if (now - this.t > 3) { this.pos = this.target; this.vel = 0; this.t = now - DT; }   // mucho rato quieto: ya llegó
    while (this.t + DT <= now) {
      this.t += DT;
      const diff = this.target - this.pos;
      if (Math.abs(diff) > 0.05 || Math.abs(this.vel) > 0.5) {
        const h = this.accel * DT * 0.5;
        const want = Math.min(this.speed, Math.sqrt(h * h + 2 * this.accel * Math.abs(diff)) - h) * (diff > 0 ? 1 : -1);
        this.vel += Math.max(-this.accel * DT, Math.min(this.accel * DT, want - this.vel));
        const step = this.vel * DT;
        if ((diff > 0 && step >= diff) || (diff < 0 && step <= diff) || (Math.abs(diff) < 0.05 && Math.abs(this.vel) < 3)) {
          this.pos = this.target; this.vel = 0;
        } else this.pos += step;
      }
    }
    return this.pos;
  }
}

const LIMITS = { pan: [-95, 95], tilt: [-85, 85] };                 // firmware config.h PAN/TILT_MIN/MAX_DEG
const SPEED = { pan: [150, 450], tilt: [160, 600] };                // PAN/TILT_MAX_SPEED, *_ACCEL
const SLEEP_FACE_MS = 5000;                                          // cara de sueño, luego el reloj (main.cpp)
const MOUTH_TIMEOUT_MS = 300;                                        // nivel de boca caducado (main.cpp)
const FRAME_MS = 33;                                                 // 30 fps, como face.cpp

const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
const $ = id => document.getElementById(id);

const robot = {
  sim: null, emotions: [], packs: {},
  neck: { pan: new Motion(...SPEED.pan), tilt: new Motion(...SPEED.tilt) },
  asleep: false, asleepAt: 0, h24: true,
  mouthLevel: -1, mouthAt: 0,
  listeners: [],

  async start() {
    const init = await waitForApi().then(api => api.init());
    this.emotions = init.emotions;
    if (init.fallback) FaceKit.setFallback(FaceKit.resolve(init.fallback, this.emotions));
    this.sim = new FaceKit.Sim(FaceKit.resolve(init.pack, this.emotions), "neutral");
    if (init.asleep) this.handle({ type: "asleep", on: true });
    setInterval(() => this.frame(), FRAME_MS);
    setInterval(() => this.tickClock(), 1000);
    this.tickClock();
    setupGrip();
  },

  handle(msg) {
    if (!msg || typeof msg !== "object") return;
    switch (msg.type) {
      case "emotion":
        if (this.emotions.includes(msg.name)) this.sim.setEmotion(msg.name);
        break;
      case "pan": case "tilt": {
        const deg = Number(msg.deg);
        if (Number.isFinite(deg)) this.neck[msg.type].setTarget(clamp(deg, ...LIMITS[msg.type]));
        break;
      }
      case "motion": {                                               // límites del cuello durante los bailes
        const m = this.neck[msg.axis];
        if (m && msg.speed > 0 && msg.accel > 0) { m.speed = msg.speed; m.accel = msg.accel; }
        else if (m) { [m.speed, m.accel] = SPEED[msg.axis]; }
        break;
      }
      case "asleep":
        this.asleep = !!msg.on;
        this.asleepAt = performance.now();
        this.sim.setAsleep(this.asleep);
        if (this.asleep) { this.neck.pan.setTarget(0); this.neck.tilt.setTarget(0); }  // cabeza a casa al dormir
        else document.body.classList.remove("clock");
        break;
      case "face":
        if (msg.pack) this.sim.setPack(FaceKit.resolve(msg.pack, this.emotions));
        break;
      case "mouth":                                                  // nivel RMS de la voz, -1 = ha terminado
        this.mouthLevel = Number(msg.level);
        this.mouthAt = performance.now();
        break;
      case "settings":
        if (typeof msg.h24 === "boolean") this.h24 = msg.h24;
        break;
      default:                                                       // volume, glance, mic, stream...: no afectan a la cara
        break;
    }
    for (const fn of this.listeners) fn(msg);
  },

  // Estado para el panel de depuración.
  state() {
    return { emotion: this.sim.emotion, asleep: this.asleep, pan: this.neck.pan.pos, tilt: this.neck.tilt.pos,
             talking: this.sim.talking };
  },

  frame() {
    const now = performance.now();
    const talking = this.mouthLevel >= 0 && now - this.mouthAt < MOUTH_TIMEOUT_MS;
    this.sim.talking = talking;
    this.sim.mouthLevel = talking ? this.mouthLevel : 0;
    this.sim.step(now);
    FaceKit.paint($("face"), this.sim.render(now));
    if (this.asleep && now - this.asleepAt >= SLEEP_FACE_MS) document.body.classList.add("clock");
    const pan = this.neck.pan.advance(now / 1000), tilt = this.neck.tilt.advance(now / 1000);
    // pan + = derecha del robot = tu izquierda mirándole; tilt + = arriba.
    const px = -pan / LIMITS.pan[1], ty = tilt / LIMITS.tilt[1];
    $("plate").style.transform =
      `translateX(${px * 14}%) translateY(${-ty * 16}%) rotateY(${-pan * 0.45}deg) rotateX(${tilt * 0.45}deg)`;
  },

  tickClock() {
    const d = new Date();
    const h = this.h24 ? d.getHours() : ((d.getHours() + 11) % 12) + 1;
    const time = `${String(h).padStart(this.h24 ? 2 : 1, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    document.querySelector("#clock .time").textContent = time;
    document.querySelector("#clock .date").textContent =
      d.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" });
  },
};

// pywebview inyecta window.pywebview.api cuando está listo.
function waitForApi() {
  return new Promise(resolve => {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.init) return resolve(window.pywebview.api);
    window.addEventListener("pywebviewready", () => resolve(window.pywebview.api), { once: true });
  });
}

// Redimensionar desde el asa: siempre cuadrada; Python mueve la ventana de verdad.
function setupGrip() {
  const grip = $("grip");
  let start = null, pending = null, busy = false;
  grip.addEventListener("pointerdown", e => {
    e.preventDefault(); e.stopPropagation();
    grip.setPointerCapture(e.pointerId);
    start = { x: e.screenX, y: e.screenY, size: Math.max(window.innerWidth, window.innerHeight) };
  });
  grip.addEventListener("pointermove", e => {
    if (!start) return;
    pending = Math.round(start.size + Math.max(e.screenX - start.x, e.screenY - start.y));
    if (!busy) flush();
  });
  const end = e => { if (start) { start = null; if (pending) flush(true); } };
  grip.addEventListener("pointerup", end);
  grip.addEventListener("pointercancel", end);
  async function flush(final = false) {
    if (pending == null) return;
    busy = true;
    const size = pending; pending = null;
    try { await window.pywebview.api.resize(size, final); } finally { busy = false; }
    if (pending != null) flush(final);
  }
}

window.robot = robot;
robot.start();
