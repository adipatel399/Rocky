/* ROCKY — an original stylized Eridian, drawn to match the real Rocky:
   a domed, cracked rock carapace crouching on five chunky jointed legs (knees
   up, feet splayed down), brown rock with glowing teal accents and carved
   Eridian runes. He floats and sways in space, "dances", and raises a front
   leg to fist-bump. Reacts to state: idle / listening / thinking / speaking.
   (Fan interpretation built from the book's description, not movie art.) */
"use strict";

const RockyChar = (() => {
  let state = "idle", level = 0;
  const insts = [];
  let last = performance.now(), t = 0;

  const ROCK_L = "#b07a4f", ROCK_M = "#7a4a2b", ROCK_D = "#3d2313", OUTLINE = "#160c05";
  const TEAL = [63, 214, 194];

  // per-state feel
  const MODE = {
    idle:      { sway: 0.05, bob: 0.05, dance: 0.10, freq: 1.2, glow: 0.35, raise: 0.65 },
    listening: { sway: 0.03, bob: 0.04, dance: 0.06, freq: 1.6, glow: 0.85, raise: 0.55 },
    thinking:  { sway: 0.09, bob: 0.07, dance: 0.28, freq: 3.0, glow: 0.5,  raise: 0.5  },
    speaking:  { sway: 0.08, bob: 0.10, dance: 0.50, freq: 4.4, glow: 0.6,  raise: 1.0  },
  };
  const cur = { sway: 0.05, bob: 0.05, dance: 0.10, freq: 1.2, glow: 0.35, raise: 0.65 };

  // Five limbs (Eridian anatomy), coords in creature units. hip = attach point
  // on the body, knee = the bent joint (out & up), foot = planted below. Two
  // legs are drawn behind the body; the front-left limb is the raised
  // two-finger "rock on" arm from the reference art.
  const LEGS = [
    { hip: [-0.35, 0.55], knee: [-0.55, 1.20], foot: [-0.42, 2.00], back: true,  phase: 2.1 },
    { hip: [ 0.45, 0.50], knee: [ 0.72, 1.16], foot: [ 0.60, 2.02], back: true,  phase: 3.5 },
    { hip: [-1.02, 0.12], knee: [-1.52, 0.80], foot: [-1.18, 1.86], back: false, phase: 0.6 },
    { hip: [ 1.05, 0.02], knee: [ 1.56, 0.70], foot: [ 1.40, 1.80], back: false, phase: 4.7 },
    { hip: [-1.10, -0.34], knee: [-1.48, -0.98], foot: [-1.24, -1.78], back: false, phase: 0, arm: true },
  ];

  function setState(s) { if (MODE[s]) state = s; }
  function setLevel(v) { level = v; }
  function create(canvas, opts = {}) {
    const inst = {
      canvas, ctx: canvas.getContext("2d"), mini: !!opts.mini, spin: !!opts.spin,
      // interaction state
      userRot: 0, spinVel: 0, dragging: false, lastX: 0, moved: 0,
      lean: { x: 0, y: 0 }, target: { x: 0, y: 0 }, poke: 0,
    };
    insts.push(inst);
    if (opts.interactive) attachInteraction(inst);
    return inst;
  }

  // ---- playful mouse/touch interaction (drag to spin, lean to cursor, poke) --
  function attachInteraction(inst) {
    const el = inst.canvas.parentElement || inst.canvas;
    const rel = (e) => {
      const r = inst.canvas.getBoundingClientRect();
      return { x: (e.clientX - r.left) / r.width - 0.5,
               y: (e.clientY - r.top) / r.height - 0.5 };
    };
    el.addEventListener("pointerdown", (e) => {
      inst.dragging = true; inst.moved = 0; inst.lastX = e.clientX;
      el.classList.add("dragging");
      el.setPointerCapture && el.setPointerCapture(e.pointerId);
    });
    el.addEventListener("pointermove", (e) => {
      const p = rel(e);
      inst.target.x = Math.max(-0.5, Math.min(0.5, p.x));   // lean toward cursor
      inst.target.y = Math.max(-0.5, Math.min(0.5, p.y));
      if (inst.dragging) {
        const dx = e.clientX - inst.lastX; inst.lastX = e.clientX;
        inst.moved += Math.abs(dx);
        inst.userRot += dx * 0.012;
        inst.spinVel = dx * 0.9;   // fling momentum
      }
    });
    const end = (e) => {
      if (!inst.dragging) return;
      inst.dragging = false; el.classList.remove("dragging");
      if (inst.moved < 4) inst.poke = 1;   // a click, not a drag → he bounces
    };
    el.addEventListener("pointerup", end);
    el.addEventListener("pointercancel", end);
    el.addEventListener("pointerleave", () => { inst.target.x = 0; inst.target.y = 0; });
  }

  function loop(now) {
    const dt = Math.min((now - last) / 1000, 0.05); last = now; t += dt;
    const m = MODE[state] || MODE.idle;
    for (const k in cur) cur[k] += (m[k] - cur[k]) * Math.min(dt * 3, 1);
    for (const inst of insts) {
      // spin momentum with friction
      inst.userRot += inst.spinVel * dt;
      inst.spinVel *= Math.pow(0.06, dt);       // decays to rest
      if (Math.abs(inst.spinVel) < 0.01) inst.spinVel = 0;
      // ease lean toward cursor target
      inst.lean.x += (inst.target.x - inst.lean.x) * Math.min(dt * 8, 1);
      inst.lean.y += (inst.target.y - inst.lean.y) * Math.min(dt * 8, 1);
      // poke bounce decays
      if (inst.poke > 0) inst.poke = Math.max(0, inst.poke - dt * 2.2);
      draw(inst);
    }
    requestAnimationFrame(loop);
  }

  function teal(a) { return `rgba(${TEAL[0]},${TEAL[1]},${TEAL[2]},${a})`; }

  function draw(inst) {
    const { ctx, canvas } = inst;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h || w > 5000 || h > 5000) return;
    if (canvas.width !== w * dpr) { canvas.width = w * dpr; canvas.height = h * dpr; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const U = Math.min(w, h) * (inst.mini ? 0.22 : 0.20);   // creature unit
    const bob = Math.sin(t * cur.freq) * U * cur.bob;
    const sway = Math.sin(t * cur.freq * 0.5) * cur.sway;
    // playful: lean toward the cursor + bounce when poked
    const pokeK = inst.poke > 0 ? Math.sin(inst.poke * Math.PI) : 0;
    const leanX = (inst.lean.x || 0) * U * 0.9;
    const leanY = (inst.lean.y || 0) * U * 0.6 - pokeK * U * 0.35;
    const cx = w / 2 + leanX, cy = h / 2 + bob + leanY;

    // sonar rings when listening (he sees by sound)
    if (state === "listening" && !inst.mini) {
      const p = (t * 0.6) % 1;
      for (let k = 0; k < 3; k++) {
        const pr = (p + k / 3) % 1;
        ctx.beginPath(); ctx.arc(cx, cy, U * (0.9 + pr * 2.4), 0, Math.PI * 2);
        ctx.strokeStyle = teal(0.3 * (1 - pr)); ctx.lineWidth = 1.4; ctx.stroke();
      }
    }
    // warm/teal halo
    const halo = ctx.createRadialGradient(cx, cy, 0, cx, cy, U * 3);
    halo.addColorStop(0, teal(0.05 + cur.glow * 0.12));
    halo.addColorStop(1, "transparent");
    ctx.fillStyle = halo;
    ctx.beginPath(); ctx.arc(cx, cy, U * 3, 0, Math.PI * 2); ctx.fill();

    ctx.save(); ctx.translate(cx, cy);
    if (pokeK) ctx.scale(1 + pokeK * 0.14, 1 + pokeK * 0.14);   // bounce on poke
    // gentle upright float (not a full tumble) so his pose stays readable
    if (inst.spin) ctx.rotate(Math.sin(t * 0.5) * 0.13);
    ctx.rotate((inst.userRot || 0) + sway + (inst.lean.x || 0) * 0.35);
    ctx.translate(0, -U * 0.45);           // sit the body + planted feet centered

    // back leg first
    LEGS.filter(l => l.back).forEach(l => drawLeg(ctx, l, U));
    // body
    drawBody(ctx, U);
    // front / side legs over the body
    LEGS.filter(l => !l.back).forEach(l => drawLeg(ctx, l, U));

    ctx.restore();
  }

  function limb(ctx, a, b, wA, wB) {
    // tapered outlined rock limb from a (width wA) to b (width wB)
    const ang = Math.atan2(b[1] - a[1], b[0] - a[0]) + Math.PI / 2;
    const dx = Math.cos(ang), dy = Math.sin(ang);
    const p = [
      [a[0] + dx * wA, a[1] + dy * wA], [a[0] - dx * wA, a[1] - dy * wA],
      [b[0] - dx * wB, b[1] - dy * wB], [b[0] + dx * wB, b[1] + dy * wB],
    ];
    ctx.beginPath();
    ctx.moveTo(p[0][0], p[0][1]);
    for (let i = 1; i < 4; i++) ctx.lineTo(p[i][0], p[i][1]);
    ctx.closePath();
    const g = ctx.createLinearGradient(a[0], a[1], b[0], b[1]);
    g.addColorStop(0, ROCK_L); g.addColorStop(1, ROCK_M);
    ctx.fillStyle = g; ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = OUTLINE; ctx.stroke();
  }

  function joint(ctx, p, r, glowA) {
    ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, Math.PI * 2);
    ctx.fillStyle = ROCK_M; ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = OUTLINE; ctx.stroke();
    if (glowA > 0.02) {
      ctx.beginPath(); ctx.arc(p[0], p[1], r * 0.5, 0, Math.PI * 2);
      ctx.fillStyle = teal(0.5 + glowA * 0.4); ctx.fill();
    }
  }

  function drawLeg(ctx, l, U) {
    const swing = Math.sin(t * cur.freq + l.phase) * cur.dance * 0.5;
    const hip = [l.hip[0] * U, l.hip[1] * U];
    let knee = [l.knee[0] * U, (l.knee[1] + swing * 0.3) * U];
    let foot = [l.foot[0] * U, (l.foot[1] + swing * 0.5) * U];

    if (l.arm) {
      // celebratory "rock on" raise: lift the elbow + hand higher with `raise`
      const r = cur.raise * (0.78 + 0.22 * Math.sin(t * cur.freq));
      knee = [l.knee[0] * U, (l.knee[1] * (0.6 + 0.4 * r)) * U];
      foot = [(l.foot[0] + r * 0.06) * U, (l.foot[1] * (0.55 + 0.45 * r)) * U];
    }

    limb(ctx, hip, knee, U * 0.24, U * 0.17);   // thigh / upper arm
    limb(ctx, knee, foot, U * 0.17, U * 0.11);  // shin / forearm
    joint(ctx, hip, U * 0.13, cur.glow * 0.3);
    joint(ctx, knee, U * 0.15, cur.glow * 0.5);

    if (l.arm) drawHand(ctx, knee, foot, U);
    else drawFoot(ctx, knee, foot, U);

    // a teal mineral speck + faint carved lines on the lower segment
    const mx = (knee[0] + foot[0]) / 2, my = (knee[1] + foot[1]) / 2;
    const gg = ctx.createRadialGradient(mx, my, 0, mx, my, U * 0.14);
    gg.addColorStop(0, teal(0.4 + cur.glow * 0.4)); gg.addColorStop(1, "transparent");
    ctx.fillStyle = gg;
    ctx.beginPath(); ctx.arc(mx, my, U * 0.14, 0, Math.PI * 2); ctx.fill();
  }

  // planted foot: three short blunt toes
  function drawFoot(ctx, knee, foot, U) {
    const ang = Math.atan2(foot[1] - knee[1], foot[0] - knee[0]);
    for (let k = -1; k <= 1; k++) {
      const a = ang + k * 0.34;
      limb(ctx, foot, [foot[0] + Math.cos(a) * U * 0.26, foot[1] + Math.sin(a) * U * 0.26],
           U * 0.09, U * 0.035);
    }
    joint(ctx, foot, U * 0.08, 0);
  }

  // raised hand: two fingers spread in a V ("rock on" / peace)
  function drawHand(ctx, elbow, hand, U) {
    const ang = Math.atan2(hand[1] - elbow[1], hand[0] - elbow[0]);
    [-0.34, 0.30].forEach(off => {
      const a = ang + off;
      limb(ctx, hand, [hand[0] + Math.cos(a) * U * 0.52, hand[1] + Math.sin(a) * U * 0.52],
           U * 0.10, U * 0.05);
    });
    joint(ctx, hand, U * 0.10, cur.glow * 0.4);
  }

  function runes(ctx, a, b, U) {
    const ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
    const perp = ang + Math.PI / 2;
    for (let i = 1; i <= 3; i++) {
      const f = i / 4;
      const px = a[0] + (b[0] - a[0]) * f, py = a[1] + (b[1] - a[1]) * f;
      const rw = U * 0.08;
      ctx.beginPath();
      ctx.moveTo(px - Math.cos(perp) * rw, py - Math.sin(perp) * rw);
      ctx.lineTo(px + Math.cos(perp) * rw, py + Math.sin(perp) * rw);
      ctx.lineWidth = 1.4;
      ctx.strokeStyle = i === 2 ? teal(0.5 + cur.glow * 0.4) : "rgba(30,16,8,.55)";
      ctx.stroke();
    }
  }

  function pentagon(r, cy0, squash) {
    const p = [];
    for (let i = 0; i < 5; i++) {
      const a = -Math.PI / 2 + i * (Math.PI * 2 / 5);
      p.push([Math.cos(a) * r, cy0 + Math.sin(a) * r * (squash || 1)]);
    }
    return p;
  }
  function tracePath(ctx, pts) {
    ctx.beginPath();
    pts.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]));
    ctx.closePath();
  }

  function drawBody(ctx, U) {
    // Inverted-triangle rock carapace: wide jagged top ("shoulders"), narrowing
    // to a rounded point at the bottom — matching the reference art.
    ctx.save();
    ctx.lineJoin = "round";
    const P = [
      [-1.30, -0.48], [-0.78, -0.70], [-0.18, -0.56], [0.42, -0.74],
      [1.02, -0.60], [1.34, -0.44],                     // jagged top ridge
      [1.18, 0.22], [0.72, 0.70], [0.16, 1.18],         // right shoulder → point
      [-0.42, 0.68], [-1.06, 0.16],                     // bottom point → left
    ].map(p => [p[0] * U, p[1] * U]);
    tracePath(ctx, P);
    const g = ctx.createRadialGradient(-U * 0.35, -U * 0.5, U * 0.1, 0, 0, U * 1.7);
    g.addColorStop(0, ROCK_L); g.addColorStop(0.6, ROCK_M); g.addColorStop(1, ROCK_D);
    ctx.fillStyle = g; ctx.fill();
    ctx.lineWidth = 3.4; ctx.strokeStyle = OUTLINE; ctx.stroke();

    ctx.clip();  // everything below stays inside the shell

    // cracks (the plated-rock look)
    ctx.strokeStyle = "rgba(24,12,5,.55)"; ctx.lineWidth = 1.8;
    [[[-0.95, -0.15], [-0.15, -0.10], [0.55, -0.28]],
     [[0.10, -0.55], [0.02, 0.12], [0.16, 0.95]],
     [[-0.55, 0.48], [0.18, 0.32], [0.85, 0.42]],
     [[0.68, -0.42], [1.02, -0.10]],
     [[-0.85, 0.05], [-0.30, -0.05]]].forEach(cr => {
      ctx.beginPath();
      cr.forEach((p, i) => { const x = p[0] * U, y = p[1] * U; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
    });

    // two clusters of small dark breathing holes (front-lower body)
    ctx.fillStyle = "rgba(18,9,3,.85)";
    [[-0.42, 0.18], [0.40, 0.30]].forEach((c, ci) => {
      for (let i = 0; i < 8; i++) {
        const a = i * (Math.PI * 2 / 8);
        const rr = (i % 2 ? 0.06 : 0.12) * U;
        const x = c[0] * U + Math.cos(a) * rr;
        const y = c[1] * U + Math.sin(a) * rr * 0.8;
        ctx.beginPath(); ctx.arc(x, y, U * 0.028, 0, Math.PI * 2); ctx.fill();
      }
      ctx.beginPath(); ctx.arc(c[0] * U, c[1] * U, U * 0.03, 0, Math.PI * 2); ctx.fill();
    });

    // green/teal mineral blobs (the glowing veins)
    [[-1.02, -0.08, 0.14], [0.98, -0.22, 0.17], [0.55, 0.52, 0.11],
     [-0.22, 0.72, 0.10], [-0.7, 0.4, 0.08]].forEach(b => {
      const x = b[0] * U, y = b[1] * U, r = b[2] * U;
      ctx.beginPath(); ctx.ellipse(x, y, r, r * 0.82, 0.5, 0, Math.PI * 2);
      ctx.fillStyle = teal(0.55 + cur.glow * 0.35); ctx.fill();
      const gg = ctx.createRadialGradient(x, y, 0, x, y, r * 2.2);
      gg.addColorStop(0, teal(0.25)); gg.addColorStop(1, "transparent");
      ctx.fillStyle = gg;
      ctx.beginPath(); ctx.arc(x, y, r * 2.2, 0, Math.PI * 2); ctx.fill();
    });

    ctx.restore();
  }

  requestAnimationFrame(loop);
  return { create, setState, setLevel };
})();
