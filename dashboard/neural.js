/* ============================================================
   Neural Network Core — animated canvas centrepiece.
   Additive-blended node field with travelling energy pulses,
   a bright nucleus and rotating HUD rings.
   State palette matches jarbai/ui/reactor.py.
   ============================================================ */
(function (global) {
  "use strict";

  var STATES = {
    idle:      { color: [34, 211, 238],  alt: [167, 139, 250], spin: 0.045, speed: 0.55, amp: 0.10, rate: 0.55, label: "ONLINE" },
    listening: { color: [34, 211, 238],  alt: [125, 227, 243], spin: 0.130, speed: 1.60, amp: 0.26, rate: 2.20, label: "LISTENING" },
    thinking:  { color: [167, 139, 250], alt: [34, 211, 238],  spin: 0.320, speed: 2.00, amp: 0.30, rate: 3.20, label: "PROCESSING" },
    speaking:  { color: [251, 191, 36],  alt: [255, 232, 150], spin: 0.075, speed: 1.20, amp: 0.34, rate: 1.60, label: "SPEAKING" },
    error:     { color: [239, 68, 68],   alt: [255, 140, 140], spin: 0.020, speed: 3.00, amp: 0.38, rate: 0.80, label: "FAULT" }
  };

  var NODES = 220;
  var SPOKES = 18;
  var NEIGHBOURS = 3;
  var MAX_PULSES = 46;
  var TAU = Math.PI * 2;

  function lerp(a, b, t) { return a + (b - a) * t; }

  /* radial-gradient sprite used for every glowing dot (cheap additive bloom) */
  function makeSprite(rgb, size) {
    var c = document.createElement("canvas");
    c.width = c.height = size;
    var g = c.getContext("2d");
    var h = size / 2;
    var grad = g.createRadialGradient(h, h, 0, h, h, h);
    var col = rgb[0] + "," + rgb[1] + "," + rgb[2];
    grad.addColorStop(0.00, "rgba(255,255,255,0.95)");
    grad.addColorStop(0.18, "rgba(" + col + ",0.85)");
    grad.addColorStop(0.45, "rgba(" + col + ",0.28)");
    grad.addColorStop(1.00, "rgba(" + col + ",0)");
    g.fillStyle = grad;
    g.fillRect(0, 0, size, size);
    return c;
  }

  function NeuralCore(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.dpr = Math.min(global.devicePixelRatio || 1, 2);

    this.state = "idle";
    this.cfg = STATES.idle;
    this.rgb = STATES.idle.color.slice();
    this.rgbAlt = STATES.idle.alt.slice();
    this.spin = STATES.idle.spin;
    this.speed = STATES.idle.speed;
    this.amp = STATES.idle.amp;
    this.rate = STATES.idle.rate;

    this.level = 0;        // live audio level 0..1
    this.load = 0;         // CPU load 0..1 — drives field activity
    this.intensity = 0;    // smoothed excitement

    this.rot = 0;
    this.t = 0;
    this.waves = [];       // shockwaves
    this.particles = [];
    this.pulses = [];

    this.spriteKey = "";
    this.sprite = null;
    this.spriteAlt = null;

    this.W = this.H = this.cx = this.cy = this.R = 0;

    this.build();
    this.resize();
    this._boundFrame = this.frame.bind(this);
    this.last = 0;
    requestAnimationFrame(this._boundFrame);
  }

  /* ---------------------------------------------------------- geometry */
  NeuralCore.prototype.build = function () {
    var i, j;
    var nodes = [];

    // node 0 IS the nucleus — inner nodes wire straight back to it, which is
    // what produces the radial energy filaments around the bright centre
    nodes.push({ a: 0, r: 0, bx: 0, by: 0, ph: 0, sz: 1.7, alt: false, deg: 0, x: 0, y: 0 });

    for (i = 1; i < NODES; i++) {
      // pow < 1 biases nodes toward the centre → dense luminous core
      var rr = Math.pow(Math.random(), 0.62);
      var ang = Math.random() * TAU;
      nodes.push({
        a: ang,
        r: rr,
        bx: Math.cos(ang) * rr,      // base cartesian (unit circle)
        by: Math.sin(ang) * rr,
        ph: Math.random() * TAU,
        sz: 0.45 + Math.random() * 0.75 + (1 - rr) * 0.5,
        alt: Math.random() < 0.17,
        deg: 0,
        x: 0, y: 0
      });
    }

    // k-nearest-neighbour edges on the static base layout
    var edges = [];
    var seen = {};
    for (i = 0; i < NODES; i++) {
      var best = [];
      for (j = 0; j < NODES; j++) {
        if (i === j) continue;
        var dx = nodes[i].bx - nodes[j].bx;
        var dy = nodes[i].by - nodes[j].by;
        var d = dx * dx + dy * dy;
        best.push([d, j]);
      }
      best.sort(function (a, b) { return a[0] - b[0]; });
      for (var k = 0; k < NEIGHBOURS; k++) {
        var o = best[k][1];
        var key = i < o ? i + ":" + o : o + ":" + i;
        if (seen[key]) continue;
        seen[key] = 1;
        var len = Math.sqrt(best[k][0]);
        nodes[i].deg++;
        nodes[o].deg++;
        edges.push({
          a: i,
          b: o,
          len: len,
          // shorter + more central edges glow brighter
          w: Math.max(0.06, (1 - len * 2.6) * (1 - (nodes[i].r + nodes[o].r) * 0.32))
        });
      }
    }

    // One filament per angular sector, each aiming at a different radius
    // (golden-ratio spread) so the nucleus throws out energy lines of varied
    // length instead of a wheel of identical spokes.
    var pick = new Array(SPOKES);
    var bestD = new Array(SPOKES);
    for (i = 1; i < NODES; i++) {
      var nd = nodes[i];
      if (nd.r < 0.10 || nd.r > 0.62) continue;
      var s = Math.floor((((nd.a % TAU) + TAU) % TAU) / TAU * SPOKES) % SPOKES;
      var target = 0.16 + 0.34 * ((s * 0.618) % 1);
      var dist = Math.abs(nd.r - target);
      if (bestD[s] == null || dist < bestD[s]) { bestD[s] = dist; pick[s] = i; }
    }
    for (i = 0; i < SPOKES; i++) {
      var si = pick[i];
      if (si == null || seen["0:" + si]) continue;
      seen["0:" + si] = 1;
      nodes[0].deg++;
      nodes[si].deg++;
      edges.push({ a: 0, b: si, len: nodes[si].r, w: 0.95 });
    }

    // bucket edges by brightness so each frame strokes 4 paths, not 500
    this.buckets = [[], [], [], []];
    for (i = 0; i < edges.length; i++) {
      var b = Math.min(3, Math.floor(edges[i].w * 5));
      edges[i].bucket = b;
      this.buckets[b].push(edges[i]);
    }

    this.nodes = nodes;
    this.edges = edges;
  };

  NeuralCore.prototype.resize = function () {
    var stage = this.canvas.parentElement;
    var rect = stage.getBoundingClientRect();
    var side = Math.max(240, Math.min(rect.width, rect.height));

    this.canvas.style.width = side + "px";
    this.canvas.style.height = side + "px";
    this.canvas.width = Math.round(side * this.dpr);
    this.canvas.height = Math.round(side * this.dpr);

    this.W = side;
    this.H = side;
    this.cx = side / 2;
    this.cy = side / 2;
    this.R = side * 0.335;

    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);

    var s = Math.max(28, Math.round(side * 0.075));
    if (s !== this.spriteSize) { this.spriteSize = s; this.spriteKey = ""; }
  };

  /* ---------------------------------------------------------- controls */
  NeuralCore.prototype.setState = function (name) {
    if (!STATES[name]) name = "idle";
    this.state = name;
    this.cfg = STATES[name];
    if (name !== "idle") this.surge(name === "error" ? 0.7 : 0.45);
    return this.cfg.label;
  };

  NeuralCore.prototype.setLevel = function (v) {
    this.level = Math.max(0, Math.min(1, v));
  };

  NeuralCore.prototype.setLoad = function (v) {
    this.load = Math.max(0, Math.min(1, v));
  };

  /* expanding shockwave + burst of pulses */
  NeuralCore.prototype.surge = function (strength) {
    strength = strength == null ? 0.6 : strength;
    this.waves.push({ r: this.R * 0.05, a: 0.55 * strength + 0.25, v: 1 });
    var n = Math.round(14 * strength);
    for (var i = 0; i < n; i++) this.spawnPulse();
    for (var p = 0; p < 26 * strength; p++) this.spawnParticle();
  };

  NeuralCore.prototype.spawnPulse = function () {
    if (this.pulses.length >= MAX_PULSES) return;
    var e = this.edges[(Math.random() * this.edges.length) | 0];
    this.pulses.push({
      e: e,
      t: 0,
      v: 0.35 + Math.random() * 0.75,
      dir: Math.random() < 0.5 ? 1 : -1,
      alt: Math.random() < 0.25
    });
  };

  NeuralCore.prototype.spawnParticle = function () {
    var a = Math.random() * TAU;
    this.particles.push({
      a: a,
      r: this.R * (0.02 + Math.random() * 0.1),
      v: this.R * (0.06 + Math.random() * 0.22),
      life: 1,
      sz: 0.5 + Math.random()
    });
  };

  /* ---------------------------------------------------------- frame */
  NeuralCore.prototype.frame = function (now) {
    var dt = this.last ? Math.min((now - this.last) / 1000, 0.05) : 0.016;
    this.last = now;
    this.t += dt;

    // ease every animated quantity toward the current state's target
    var c = this.cfg, e = 1 - Math.pow(0.001, dt);
    for (var i = 0; i < 3; i++) {
      this.rgb[i] = lerp(this.rgb[i], c.color[i], e);
      this.rgbAlt[i] = lerp(this.rgbAlt[i], c.alt[i], e);
    }
    this.spin = lerp(this.spin, c.spin, e);
    this.speed = lerp(this.speed, c.speed, e);
    this.amp = lerp(this.amp, c.amp, e);
    this.rate = lerp(this.rate, c.rate, e);

    var want = this.level * 0.75 + this.load * 0.35 + (this.state === "idle" ? 0 : 0.25);
    this.intensity = lerp(this.intensity, Math.min(1, want), 1 - Math.pow(0.02, dt));

    this.rot += this.spin * dt;

    this.refreshSprites();
    this.draw(dt);

    requestAnimationFrame(this._boundFrame);
  };

  NeuralCore.prototype.refreshSprites = function () {
    var key = (this.rgb[0] | 0) + "," + (this.rgb[1] | 0) + "," + (this.rgb[2] | 0) + "|" +
              (this.rgbAlt[0] | 0) + "," + (this.rgbAlt[1] | 0) + "," + (this.rgbAlt[2] | 0);
    if (key === this.spriteKey) return;
    this.spriteKey = key;
    this.sprite = makeSprite([this.rgb[0] | 0, this.rgb[1] | 0, this.rgb[2] | 0], this.spriteSize);
    this.spriteAlt = makeSprite([this.rgbAlt[0] | 0, this.rgbAlt[1] | 0, this.rgbAlt[2] | 0], this.spriteSize);
  };

  NeuralCore.prototype.draw = function (dt) {
    var ctx = this.ctx;
    var cx = this.cx, cy = this.cy, R = this.R, t = this.t;
    var n, i, p, e;
    var col = (this.rgb[0] | 0) + "," + (this.rgb[1] | 0) + "," + (this.rgb[2] | 0);
    var breathe = 1 + Math.sin(t * this.speed) * 0.02 + this.intensity * 0.05;

    ctx.clearRect(0, 0, this.W, this.H);
    ctx.globalCompositeOperation = "lighter";

    /* ── node positions ── */
    var cos = Math.cos(this.rot), sin = Math.sin(this.rot);
    for (i = 0; i < this.nodes.length; i++) {
      n = this.nodes[i];
      var wob = 1 + Math.sin(t * this.speed + n.ph) * this.amp * 0.05;
      var bx = n.bx * R * breathe * wob;
      var by = n.by * R * breathe * wob;
      n.x = cx + bx * cos - by * sin + Math.sin(t * 0.8 + n.ph) * R * 0.012;
      n.y = cy + bx * sin + by * cos + Math.cos(t * 0.7 + n.ph * 1.4) * R * 0.012;
    }

    /* ── edges (4 brightness buckets → 4 stroke calls) ── */
    ctx.lineCap = "round";
    for (var b = 0; b < 4; b++) {
      var list = this.buckets[b];
      if (!list.length) continue;
      ctx.beginPath();
      for (i = 0; i < list.length; i++) {
        e = list[i];
        var na = this.nodes[e.a], nb = this.nodes[e.b];
        ctx.moveTo(na.x, na.y);
        ctx.lineTo(nb.x, nb.y);
      }
      var a = (0.075 + b * 0.070) * (0.72 + this.intensity * 0.6);
      ctx.strokeStyle = "rgba(" + col + "," + a.toFixed(3) + ")";
      ctx.lineWidth = 0.45 + b * 0.22;
      ctx.stroke();
    }

    /* ── travelling energy pulses ── */
    var spawn = this.rate * (0.6 + this.intensity * 1.8) * dt * 12;
    while (spawn-- > 0) if (Math.random() < 0.55) this.spawnPulse();

    var sprite = this.sprite, spriteAlt = this.spriteAlt, ss = this.spriteSize;
    for (i = this.pulses.length - 1; i >= 0; i--) {
      p = this.pulses[i];
      p.t += p.v * dt;
      if (p.t >= 1) { this.pulses.splice(i, 1); continue; }
      var pa = this.nodes[p.e.a], pb = this.nodes[p.e.b];
      var f = p.dir > 0 ? p.t : 1 - p.t;
      var px = lerp(pa.x, pb.x, f);
      var py = lerp(pa.y, pb.y, f);
      // fade in and out along the edge
      var fade = Math.sin(p.t * Math.PI);
      var tail = 0.14 * p.dir;
      var tx = lerp(pa.x, pb.x, Math.max(0, Math.min(1, f - tail)));
      var ty = lerp(pa.y, pb.y, Math.max(0, Math.min(1, f - tail)));

      ctx.globalAlpha = fade * 0.5;
      ctx.strokeStyle = "rgba(" + col + ",0.9)";
      ctx.lineWidth = 1.1;
      ctx.beginPath();
      ctx.moveTo(tx, ty);
      ctx.lineTo(px, py);
      ctx.stroke();

      ctx.globalAlpha = fade * 0.85;
      var sz = ss * 0.42;
      ctx.drawImage(p.alt ? spriteAlt : sprite, px - sz / 2, py - sz / 2, sz, sz);
    }
    ctx.globalAlpha = 1;

    /* ── nodes ── */
    for (i = 0; i < this.nodes.length; i++) {
      n = this.nodes[i];
      var glow = 0.30 + n.deg * 0.035 + (1 - n.r) * 0.32 + this.intensity * 0.22;
      var twk = 0.85 + Math.sin(t * 2.1 + n.ph * 3) * 0.15;
      var size = ss * (0.30 + n.sz * 0.20) * (1 + this.intensity * 0.18);
      ctx.globalAlpha = Math.min(1, glow * twk);
      ctx.drawImage(n.alt ? spriteAlt : sprite, n.x - size / 2, n.y - size / 2, size, size);
    }
    ctx.globalAlpha = 1;

    /* ── particles drifting outward ── */
    for (i = this.particles.length - 1; i >= 0; i--) {
      p = this.particles[i];
      p.r += p.v * dt;
      p.life -= dt * 0.55;
      if (p.life <= 0 || p.r > R * 1.25) { this.particles.splice(i, 1); continue; }
      var qx = cx + Math.cos(p.a + this.rot) * p.r;
      var qy = cy + Math.sin(p.a + this.rot) * p.r;
      ctx.globalAlpha = p.life * 0.7;
      var psz = ss * 0.18 * p.sz;
      ctx.drawImage(sprite, qx - psz / 2, qy - psz / 2, psz, psz);
    }
    ctx.globalAlpha = 1;
    if (Math.random() < this.intensity * 0.6 + 0.08) this.spawnParticle();

    /* ── nucleus ── */
    var pulse = 1 + Math.sin(t * this.speed * 1.6) * 0.07 + this.intensity * 0.22;
    this.orb(cx, cy, R * 0.66 * pulse, 0.15 + this.intensity * 0.10, col);
    this.orb(cx, cy, R * 0.32 * pulse, 0.30 + this.intensity * 0.16, col);
    this.orb(cx, cy, R * 0.14 * pulse, 0.62, "255,255,255");
    ctx.fillStyle = "rgba(255,255,255," + (0.75 + this.intensity * 0.25).toFixed(2) + ")";
    ctx.beginPath();
    ctx.arc(cx, cy, R * 0.022 * pulse, 0, TAU);
    ctx.fill();

    /* ── shockwaves ── */
    for (i = this.waves.length - 1; i >= 0; i--) {
      var w = this.waves[i];
      w.r += R * 1.5 * dt * w.v;
      w.a -= dt * 0.75;
      if (w.a <= 0 || w.r > R * 1.5) { this.waves.splice(i, 1); continue; }
      ctx.strokeStyle = "rgba(" + col + "," + w.a.toFixed(3) + ")";
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.arc(cx, cy, w.r, 0, TAU);
      ctx.stroke();
    }

    this.rings(ctx, cx, cy, R, t, col);
    ctx.globalCompositeOperation = "source-over";
  };

  NeuralCore.prototype.orb = function (x, y, r, a, col) {
    var ctx = this.ctx;
    var g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, "rgba(" + col + "," + a.toFixed(3) + ")");
    g.addColorStop(0.5, "rgba(" + col + "," + (a * 0.32).toFixed(3) + ")");
    g.addColorStop(1, "rgba(" + col + ",0)");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, TAU);
    ctx.fill();
  };

  /* ---------------------------------------------------------- HUD rings */
  NeuralCore.prototype.rings = function (ctx, cx, cy, R, t, col) {
    var i, a0;
    var hot = 0.55 + this.intensity * 0.45;

    // 1 — hairline containment ring
    ctx.strokeStyle = "rgba(" + col + ",0.20)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(cx, cy, R * 1.05, 0, TAU);
    ctx.stroke();

    // 2 — heavy rotating arc segments
    ctx.strokeStyle = "rgba(" + col + "," + (0.55 * hot).toFixed(3) + ")";
    ctx.lineWidth = 3.2;
    ctx.lineCap = "butt";
    for (i = 0; i < 3; i++) {
      a0 = t * 0.28 + (i * TAU) / 3;
      ctx.beginPath();
      ctx.arc(cx, cy, R * 1.13, a0, a0 + 0.62);
      ctx.stroke();
    }

    // 3 — counter-rotating tick ladder
    ctx.strokeStyle = "rgba(" + col + ",0.30)";
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    for (i = 0; i < 64; i++) {
      a0 = -t * 0.16 + (i * TAU) / 64;
      var long = i % 8 === 0;
      var r1 = R * 1.19;
      var r2 = R * (long ? 1.245 : 1.222);
      ctx.moveTo(cx + Math.cos(a0) * r1, cy + Math.sin(a0) * r1);
      ctx.lineTo(cx + Math.cos(a0) * r2, cy + Math.sin(a0) * r2);
    }
    ctx.stroke();

    // 4 — long outer arcs
    ctx.strokeStyle = "rgba(" + col + "," + (0.34 * hot).toFixed(3) + ")";
    ctx.lineWidth = 1.6;
    for (i = 0; i < 2; i++) {
      a0 = -t * 0.11 + i * Math.PI;
      ctx.beginPath();
      ctx.arc(cx, cy, R * 1.30, a0, a0 + 1.25);
      ctx.stroke();
    }

    // 5 — orbiting markers
    ctx.fillStyle = "rgba(" + col + "," + (0.75 * hot).toFixed(3) + ")";
    for (i = 0; i < 4; i++) {
      a0 = t * 0.2 + (i * TAU) / 4;
      ctx.beginPath();
      ctx.arc(cx + Math.cos(a0) * R * 1.30, cy + Math.sin(a0) * R * 1.30, 2, 0, TAU);
      ctx.fill();
    }

    ctx.lineCap = "round";
  };

  global.NeuralCore = NeuralCore;
})(window);
