// GENERADO por desktop/tools/sync_facekit.py desde server/brain/dashboard.html (sha256 d90df4341c78221a).
// No editar a mano: vuelve a ejecutar el script tras actualizar desde upstream.
const FaceKit = (() => {
  const W = 128, H = 64;
  const EYE_KEYS = ["w", "h", "rt", "rb", "st", "sb", "lid", "cheek", "dx", "dy"];
  const EYE_DEF = { w: 34, h: 34, rt: 12, rb: 12, st: 0, sb: 0, lid: 0, cheek: 0, dx: 0, dy: 0 };
  const LIMITS = { w: [4, 120], h: [2, 64], rt: [0, 32], rb: [0, 32], st: [-30, 30], sb: [-30, 30],
                   lid: [0, 40], cheek: [0, 40], dx: [-30, 30], dy: [-30, 30] };
  const BANG = ["###", "###", "###", "###", "###", "###", "###", "...", "###", "###"];
  const QUESTION = [".#####.", "##...##", "##...##", ".....##", "....##.", "...##..", "..##...", "..##...", ".......", "..##...", "..##..."];
  const HEART = [".##.##.", "#######", "#######", ".#####.", "..###..", "...#..."];
  const clamp = (x, lo, hi) => x < lo ? lo : x > hi ? hi : x;       // as Arduino's constrain()
  const rnd = (a, b) => a + Math.floor(Math.random() * (b - a));   // as Arduino's random(a, b)
  const approach = (c, t, f) => c + (t - c) * f;
  const fl = Math.floor;
  let fallback = null;   // Rocky's pack, resolved: what the robot uses for anything a pack leaves out

  function readEye(o, base) {
    const e = { ...base };
    if (o) for (const k of EYE_KEYS) if (typeof o[k] === "number") e[k] = clamp(o[k], LIMITS[k][0], LIMITS[k][1]);
    return e;
  }
  // A pack file -> what the drawing code uses (Face::applyPackJson).
  function resolve(p, emotions) {
    const fb = fallback;
    const r = {
      name: p.name || "unnamed", gap: clamp(p.gap ?? 16, 0, 60), y: clamp(p.y ?? 0, -20, 20),
      cyclops: !!p.cyclops, outline: !!p.outline, glint: p.glint !== false,
      mouth: p.mouth === "always" ? 1 : p.mouth === "never" ? 2 : 0,
      asleep: readEye(p.asleep, fb ? fb.asleep : { ...EYE_DEF, w: 30, h: 3, rt: 1, rb: 1 }), looks: {},
    };
    for (const name of emotions) {
      const e = p.emotions && p.emotions[name];
      if (!e) {
        r.looks[name] = fb && fb.looks[name] ? fb.looks[name]
          : { l: { ...EYE_DEF }, r: { ...EYE_DEF }, gazeX: 0, gazeY: 0, pop: 0.12, smile: 0, fx: new Set() };
        continue;
      }
      const l = readEye(e, EYE_DEF);
      r.looks[name] = {
        l, r: readEye(e.right, l), pop: clamp(e.pop ?? 0.12, 0, 0.6), smile: clamp(e.smile ?? 0, -6, 6),
        gazeX: clamp((e.gaze || [])[0] ?? 0, -20, 20), gazeY: clamp((e.gaze || [])[1] ?? 0, -20, 20),
        fx: new Set(e.fx || []),
      };
    }
    return r;
  }

  function morph(c, t, f) { for (const k of EYE_KEYS) c[k] = approach(c[k], t[k], f); }

  function inEye(g, x, y) {
    if (x < g.left || x >= g.right || y < g.top || y >= g.bot) return false;
    const u = (x - g.cx) / (g.w * 0.5) * g.inner;
    const topCut = g.st >= 0 ? g.st * (u + 1) * 0.5 : -g.st * (1 - u) * 0.5;
    const botCut = g.sb >= 0 ? g.sb * (u + 1) * 0.5 : -g.sb * (1 - u) * 0.5;
    const hh = g.bot - g.top;
    const yy = y - topCut * (g.bot - y) / hh + botCut * (y - g.top) / hh;
    if (yy < g.top + g.lid || yy >= g.bot) return false;
    if (yy < g.top + g.rt) {
      const qx = clamp(x, g.left + g.rt, g.right - g.rt), dx = x - qx, dy = yy - (g.top + g.rt);
      if (dx * dx + dy * dy > g.rt * g.rt) return false;
    }
    if (yy > g.bot - g.rb) {
      const qx = clamp(x, g.left + g.rb, g.right - g.rb), dx = x - qx, dy = yy - (g.bot - g.rb);
      if (dx * dx + dy * dy > g.rb * g.rb) return false;
    }
    if (g.cheek > 0.5) {
      const rr = g.w, ccy = g.bot + rr - g.cheek, dx = x - g.cx, dy = y - ccy;
      if (dx * dx + dy * dy < rr * rr) return false;
    }
    return true;
  }

  class Sim {
    constructor(pack, emotion = "neutral", now = performance.now()) {
      this.pack = pack; this.buf = new Uint8Array(W * H);
      this.emotion = null; this.idle = true; this.still = false; this.asleep = false;
      this.talking = false; this.mouthLevel = 0; this.mouth = 0;
      this.blink = 0; this.blinkClosing = false;
      this.gazeX = 0; this.gazeY = 0; this.gtx = 0; this.gty = 0;
      this.pupilX = 0; this.pupilY = 0; this.ptx = 0; this.pty = 0; this.nextPupil = now + rnd(300, 1500);
      this.pop = 0; this.squint = 0; this.tearY = -1; this.thinkDots = 0; this.jitter = 0;
      this.hearts = [0, 1, 2].map(() => ({ alive: false, x: 0, y: 0, age: 0 })); this.heartSide = false;
      this.zeds = [0, 1, 2].map(() => ({ alive: false, x: 0, y: 0, age: 0 }));
      this.breath = 0; this.twitch = 0; this.frame = 0;
      this.nextBlink = now + rnd(800, 4000); this.nextSaccade = now + rnd(500, 2500); this.nextSquint = now + rnd(4000, 12000);
      this.nextTear = 0; this.nextDot = 0; this.nextHeart = 0; this.nextZed = now + 800; this.nextTwitch = now + rnd(5000, 9000);
      this.since = now;
      this.setEmotion(emotion, now);
      const look = pack.looks[emotion];
      this.curL = { ...look.l }; this.curR = { ...look.r }; this.smile = look.smile; this.pop = 0;
    }
    setPack(pack, now = performance.now()) {
      this.pack = pack;
      const e = this.emotion; this.emotion = null; this.setEmotion(e, now);
      if (this.still) this.setStill(e, now);
    }
    setEmotion(e, now = performance.now()) {
      if (e !== this.emotion) {
        this.pop = 1; this.since = now; this.tearY = -1; this.nextTear = now + 1500; this.thinkDots = 0;
        for (const h of this.hearts) h.alive = false;
        this.nextHeart = now + 200;
      }
      this.emotion = e;
      const look = this.pack.looks[e];
      this.gtx = look.gazeX; this.gty = look.gazeY;
    }
    setAsleep(on, now = performance.now()) {
      if (on === this.asleep) return;
      this.asleep = on;
      if (on) {
        for (const z of this.zeds) z.alive = false;
        this.nextZed = now + 800; this.nextTwitch = now + rnd(5000, 9000); this.gtx = this.gty = 0;
      } else { this.pop = 1; this.blink = 0; this.setEmotion(this.emotion, now); }
    }
    // Face::setStill: the emotion settled, no blinks, glances or flourishes.
    setStill(e, now = performance.now()) {
      this.still = true; this.asleep = false; this.setEmotion(e, now);
      const look = this.pack.looks[e];
      this.curL = { ...look.l }; this.curR = { ...look.r }; this.smile = look.smile;
      this.blink = 0; this.blinkClosing = false; this.pop = this.squint = this.twitch = 0;
      this.gazeX = this.gtx; this.gazeY = this.gty; this.mouth = 0; this.talking = false; this.jitter = 0;
      this.pupilX = this.pupilY = this.ptx = this.pty = 0;
    }

    step(now) {
      this.frame++;
      if (this.still) return;
      const look = this.pack.looks[this.emotion], P = this.pack;
      const f = this.asleep ? 0.12 : 0.25;
      morph(this.curL, this.asleep ? P.asleep : look.l, f);
      morph(this.curR, this.asleep ? P.asleep : look.r, f);
      this.smile = approach(this.smile, this.asleep ? 0 : look.smile, f);
      this.pop *= 0.82; this.squint *= 0.85;

      if (this.asleep) {
        this.breath += 0.035; this.blink = 0; this.blinkClosing = false; this.twitch *= 0.8;
        if (now >= this.nextTwitch) { this.twitch = 1; this.nextTwitch = now + rnd(6000, 12000); }
        if (now >= this.nextZed) {
          for (const z of this.zeds) {
            if (!z.alive) {
              z.alive = true; z.age = 0;
              z.x = Math.min(P.cyclops ? W / 2 + this.curL.w / 2 + 2 : W / 2 + P.gap / 2 + this.curL.w + 2, 108);
              z.y = H / 2 - 6;
              break;
            }
          }
          this.nextZed = now + rnd(1100, 1700);
        }
        for (const z of this.zeds) {
          if (!z.alive) continue;
          z.age += 0.012; z.y -= 0.32; z.x += 0.22;
          if (z.age >= 1 || z.y < -12) z.alive = false;
        }
        this.gazeX = approach(this.gazeX, 0, 0.2); this.gazeY = approach(this.gazeY, 0, 0.2);
        this.mouth = approach(this.mouth, 0, 0.3);
        return;
      }

      if (this.blinkClosing) {
        this.blink += 0.45;
        if (this.blink >= 1) { this.blink = 1; this.blinkClosing = false; }
      } else if (this.blink > 0) this.blink = Math.max(0, this.blink - 0.28);

      if (this.idle) {
        if (now >= this.nextBlink) {
          this.blinkClosing = true; this.nextBlink = now + rnd(2200, 6000);
          if (rnd(0, 100) < 20) this.nextBlink = now + 400;
        }
        const looksSomewhere = look.gazeX !== 0 || look.gazeY !== 0;
        if (now >= this.nextSaccade && !looksSomewhere) {
          this.gtx = rnd(-8, 9); this.gty = rnd(-4, 5);
          if (rnd(0, 100) < 40) this.gtx = this.gty = 0;
          this.nextSaccade = now + rnd(1200, 4000);
        }
        if (now >= this.nextPupil) {   // the pupils look at something new (Face::stepAnimation)
          if (rnd(0, 100) < 35) { this.ptx = rnd(-25, 26) / 100; this.pty = rnd(-20, 21) / 100; }
          else { this.ptx = rnd(-90, 91) / 100; this.pty = rnd(-60, 61) / 100; }
          this.nextPupil = now + rnd(600, 2600);
        }
        if (now >= this.nextSquint && this.emotion === "neutral") { this.squint = 1; this.nextSquint = now + rnd(8000, 16000); }
      }

      if (look.fx.has("tear")) {
        if (this.tearY < 0 && now >= this.nextTear) this.tearY = 0;
        if (this.tearY >= 0) {
          this.tearY += 0.7;
          if (this.tearY > H) { this.tearY = -1; this.nextTear = now + rnd(2500, 5000); }
        }
      }
      if (look.fx.has("dots") && now >= this.nextDot) { this.thinkDots = (this.thinkDots + 1) % 4; this.nextDot = now + 420; }
      if (look.fx.has("hearts") && now >= this.nextHeart) {
        for (const h of this.hearts) {
          if (!h.alive) {
            h.alive = true; h.age = 0; this.heartSide = !this.heartSide;
            h.x = this.heartSide ? W / 2 + P.gap / 2 + this.curR.w + 2 : W / 2 - P.gap / 2 - this.curL.w - 9;
            if (P.cyclops) h.x = this.heartSide ? W / 2 + this.curL.w / 2 + 3 : W / 2 - this.curL.w / 2 - 10;
            h.y = H / 2 + 6;
            break;
          }
        }
        this.nextHeart = now + rnd(600, 1000);
      }
      for (const h of this.hearts) {
        if (!h.alive) continue;
        h.age += 0.015; h.y -= 0.45;
        if (h.age >= 1 || h.y < -6) h.alive = false;
      }
      this.jitter = (look.fx.has("shake") && this.frame % 3 === 0) ? rnd(-1, 2) : 0;

      const mouthGoal = this.talking ? clamp(0.15 + this.mouthLevel * 4, 0.15, 1) : 0;
      this.mouth = approach(this.mouth, mouthGoal, this.talking ? 0.5 : 0.3);
      this.gazeX = approach(this.gazeX, this.gtx, 0.35); this.gazeY = approach(this.gazeY, this.gty, 0.35);
      this.pupilX = approach(this.pupilX, this.ptx, 0.5); this.pupilY = approach(this.pupilY, this.pty, 0.5);
    }

    // ── pixels ──
    dot(x, y, c) { if (x >= 0 && y >= 0 && x < W && y < H) this.buf[y * W + x] = c; }
    rect(x, y, w, h, c) { for (let j = 0; j < h; ++j) for (let i = 0; i < w; ++i) this.dot(x + i, y + j, c); }
    roundBox(x, y, w, h, r, c) {
      r = Math.min(r, Math.min(w, h) * 0.5);
      for (let j = 0; j < h; ++j) for (let i = 0; i < w; ++i) {
        const px = i + 0.5, py = j + 0.5, qx = clamp(px, r, w - r), qy = clamp(py, r, h - r);
        if ((px - qx) * (px - qx) + (py - qy) * (py - qy) <= r * r) this.dot(x + i, y + j, c);
      }
    }
    line(x0, y0, x1, y1) {
      const dx = Math.abs(x1 - x0), sx = x0 < x1 ? 1 : -1, dy = -Math.abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
      let err = dx + dy;
      for (;;) {
        this.dot(x0, y0, 1);
        if (x0 === x1 && y0 === y1) break;
        const e2 = 2 * err;
        if (e2 >= dy) { err += dy; x0 += sx; }
        if (e2 <= dx) { err += dx; y0 += sy; }
      }
    }
    disc(cx, cy, r) { for (let j = -r; j <= r; ++j) for (let i = -r; i <= r; ++i) if (i * i + j * j <= r * r + r) this.dot(cx + i, cy + j, 1); }
    glyph(rows, x, y) { rows.forEach((row, j) => { for (let i = 0; i < row.length; ++i) if (row[i] === "#") this.dot(x + i, y + j, 1); }); }

    drawEye(e, cx, cy, inner, hScale) {
      const P = this.pack, w = e.w;
      let h = e.h * hScale * (1 - this.blink);
      if (h < 2) h = 2;
      const g = { cx: cx - inner * e.dx, w, st: e.st, sb: e.sb, lid: e.lid, cheek: e.cheek, inner };
      const ecy = cy + e.dy;
      g.left = g.cx - w * 0.5; g.right = g.cx + w * 0.5; g.top = ecy - h * 0.5; g.bot = ecy + h * 0.5;
      g.rt = Math.max(0, Math.min(e.rt, Math.min(w, h) * 0.5)); g.rb = Math.max(0, Math.min(e.rb, Math.min(w, h) * 0.5));
      const x0 = fl(g.left), x1 = Math.ceil(g.right), y0 = fl(g.top), y1 = Math.ceil(g.bot);
      for (let y = y0; y < y1; ++y) for (let x = x0; x < x1; ++x) {
        const px = x + 0.5, py = y + 0.5;
        let on = inEye(g, px, py);
        if (on && P.outline) on = !(inEye(g, px - 2, py) && inEye(g, px + 2, py) && inEye(g, px, py - 2) && inEye(g, px, py + 2));
        if (on) this.dot(x, y, 1);
      }
      if (P.glint && h > 12 && !this.asleep) this.drawPupil(g, x0, x1, y0, y1);
    }
    // Pupil: a dark disc (lit in outline packs) with a highlight, in the part of the eye that shows (Face::drawEye).
    drawPupil(g, x0, x1, y0, y1) {
      const P = this.pack, r = clamp(g.w * 0.14, 3, 6);
      let top = -1, bot = -1;
      for (let y = y0; y < y1; ++y) if (inEye(g, g.cx, y + 0.5)) { if (top < 0) top = y; bot = y; }
      if (top < 0) return;
      const vcy = (top + bot + 1) * 0.5;
      let left = -1, right = -1;
      for (let x = x0; x < x1; ++x) if (inEye(g, x + 0.5, vcy)) { if (left < 0) left = x; right = x; }
      if (left < 0) return;
      const vcx = (left + right + 1) * 0.5;
      const roomX = Math.max(0, (right - left + 1) * 0.5 - r - 2), roomY = Math.max(0, (bot - top + 1) * 0.5 - r - 1.5);
      const px = clamp(this.pupilX + this.gazeX / 12, -1, 1), py = clamp(this.pupilY + this.gazeY / 8, -1, 1);
      const pcx = vcx + px * roomX, pcy = vcy + py * roomY, ink = P.outline ? 1 : 0, ri = Math.ceil(r);
      for (let y = fl(pcy) - ri; y <= fl(pcy) + ri; ++y) for (let x = fl(pcx) - ri; x <= fl(pcx) + ri; ++x) {
        const dx = x + 0.5 - pcx, dy = y + 0.5 - pcy;
        if (dx * dx + dy * dy <= r * r && inEye(g, x + 0.5, y + 0.5)) this.dot(x, y, ink);
      }
      if (!P.outline && r >= 4) {
        const hx = fl(pcx - r * 0.5), hy = fl(pcy - r * 0.55);
        if (inEye(g, hx + 0.5, hy + 0.5)) this.rect(hx, hy, 2, 2, 1);
      }
    }
    drawMouth(cx, cy) {
      const P = this.pack, my0 = fl(cy + this.curL.h * 0.5);
      if (this.mouth >= 0.05 && P.mouth !== 2) {
        const mh = 2 + fl(this.mouth * 9), mw = 20 + fl(this.mouth * 8);
        let my = my0 + 4;
        if (my + mh > H - 1) my = H - 1 - mh;
        this.roundBox(cx - Math.trunc(mw / 2), my, mw, mh, Math.min(Math.trunc(mh / 2), 4), 1);
        if (mh > 6) this.roundBox(cx - Math.trunc(mw / 2) + 3, my + 2, mw - 6, mh - 4, 2, 0);
      } else if (P.mouth === 1) {
        const mw = 14, my = Math.min(my0 + 6, H - 4);
        for (let i = 0; i <= mw; ++i) {
          const t = (i - mw * 0.5) / (mw * 0.5), yy = fl(my + this.smile * (1 - t * t) + 0.5);
          this.dot(cx - mw / 2 + i, yy, 1); this.dot(cx - mw / 2 + i, yy + 1, 1);
        }
      }
    }
    drawFlourishes(leftOuter, rightOuter, eyeTop, eyeBottom, now) {
      const fx = this.pack.looks[this.emotion].fx, since = now - this.since;
      const lo = fl(leftOuter), ro = fl(rightOuter);
      if (fx.has("pop") && since < 900) this.glyph(BANG, 116, 4);
      if (fx.has("blush")) for (let i = 0; i < 2; ++i) {
        const lx = lo - 8 + i * 3, rx = ro + 3 + i * 3;
        this.line(lx, eyeBottom + 1, lx + 3, eyeBottom - 3); this.line(rx, eyeBottom + 1, rx + 3, eyeBottom - 3);
      }
      if (fx.has("tear") && this.tearY >= 0) {
        const tx = ro - 3, ty = eyeBottom + fl(this.tearY);
        this.disc(tx, ty, 2); this.line(tx, ty - 5, tx, ty - 2);
      }
      if (fx.has("dots")) for (let i = 0; i < this.thinkDots; ++i) this.disc(W - 26 + i * 8, 9, 2);
      if (fx.has("steam") && fl(this.frame / 6) % 2 === 0) {
        this.line(lo - 4, eyeTop - 4, lo - 2, eyeTop - 9); this.line(ro + 4, eyeTop - 4, ro + 2, eyeTop - 9);
      }
      if (fx.has("hearts")) for (const h of this.hearts) {
        if (!h.alive || (h.age > 0.8 && this.frame % 2 === 0)) continue;
        this.glyph(HEART, fl(h.x), fl(h.y));
      }
      if (fx.has("question")) this.glyph(QUESTION, 112, 3 + fl(Math.sin(this.frame * 0.15) * 2));
      if (fx.has("sparkle")) {
        const a = fl(this.frame / 5) % 2 === 0;
        const pts = [a ? lo - 6 : lo - 5, a ? eyeTop + 3 : eyeBottom - 5, a ? ro + 6 : ro + 5, a ? eyeBottom - 4 : eyeTop + 2];
        for (let k = 0; k < 2; ++k) {
          const x = pts[k * 2], y = pts[k * 2 + 1];
          this.line(x - 2, y, x + 2, y); this.line(x, y - 2, x, y + 2);
        }
      }
    }
    drawZeds() {
      for (const z of this.zeds) {
        if (!z.alive || (z.age > 0.8 && this.frame % 2 === 0)) continue;
        const s = z.age < 0.33 ? 4 : z.age < 0.66 ? 6 : 8, x = fl(z.x), y = fl(z.y) - s;
        if (x < 0 || x >= W - 4 || y < 0) continue;
        for (let b = 0; b < (s >= 8 ? 2 : 1); ++b) {
          this.line(x + b, y, x + s + b, y); this.line(x + s + b, y, x + b, y + s); this.line(x + b, y + s, x + s + b, y + s);
        }
      }
    }
    render(now = performance.now()) {
      this.buf.fill(0);
      const P = this.pack, look = P.looks[this.emotion], lively = !this.still && !this.asleep;
      let bob = this.asleep ? Math.sin(this.breath) * 2 : -this.mouth * 2;
      if (lively && look.fx.has("bounce")) bob -= Math.abs(Math.sin(this.frame * 0.18)) * 3;
      const sway = (lively && look.fx.has("wobble")) ? Math.sin(this.frame * 0.08) * 3 : 0;
      let cy = H / 2 + P.y + this.gazeY + bob;
      if (this.talking) cy -= 2;
      const gx = this.gazeX + this.jitter + sway;
      let hScale = 1 + this.pop * look.pop;
      hScale *= 1 - this.squint * 0.4;
      if (this.asleep) hScale += this.twitch * 2.5;
      let leftOuter, rightOuter;
      if (P.cyclops) {
        const cx = W / 2 + gx;
        this.drawEye(this.curL, cx, cy, 1, hScale);
        leftOuter = cx - this.curL.dx - this.curL.w / 2; rightOuter = cx - this.curL.dx + this.curL.w / 2;
      } else {
        const lcx = W / 2 - P.gap / 2 - this.curL.w / 2 + gx, rcx = W / 2 + P.gap / 2 + this.curR.w / 2 + gx;
        this.drawEye(this.curL, lcx, cy, 1, hScale); this.drawEye(this.curR, rcx, cy, -1, hScale);
        leftOuter = lcx - this.curL.dx - this.curL.w / 2; rightOuter = rcx + this.curR.dx + this.curR.w / 2;
      }
      const eyeTop = fl(cy - this.curL.h * hScale / 2), eyeBottom = fl(cy + this.curL.h * hScale / 2);
      if (this.asleep) this.drawZeds();
      else {
        if (!this.still) this.drawFlourishes(leftOuter, rightOuter, eyeTop, eyeBottom, now);
        this.drawMouth(W / 2 + fl(this.gazeX * 0.5), fl(cy));
      }
      return this.buf;
    }
  }

  // Paint a frame onto a 128x64 canvas, lit pixels in the OLED's amber.
  function paint(canvas, buf) {
    const ctx = canvas._ctx || (canvas._ctx = canvas.getContext("2d"));
    const img = canvas._img || (canvas._img = ctx.createImageData(W, H));
    const d = img.data;
    for (let i = 0; i < W * H; ++i) {
      const on = buf[i], o = i * 4;
      d[o] = on ? 242 : 10; d[o + 1] = on ? 180 : 13; d[o + 2] = on ? 92 : 20; d[o + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  }
  function still(pack, emotion) { const s = new Sim(pack, emotion); s.setStill(emotion); return s.render(); }

  return { W, H, EYE_KEYS, EYE_DEF, LIMITS, resolve, Sim, paint, still,
           setFallback(p) { fallback = p; } };
})();
