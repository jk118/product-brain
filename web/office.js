// The 2D office: two organic, triangle-paneled buildings seen from above, with each agent as a character.
// Everything is SVG. Animations are tweens driven by one requestAnimationFrame loop.

const NS = "http://www.w3.org/2000/svg";
const SQ3 = Math.sqrt(3) / 2;

function el(tag, attrs = {}, parent) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
}
const lerp = (a, b, k) => a + (b - a) * k;
const ease = k => (k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2);

function seeded(seed) {
  let s = seed % 2147483647 || 1;
  return () => (s = (s * 16807) % 2147483647) / 2147483647;
}

// Closed Catmull-Rom curve through the points, as cubic Beziers.
function smooth(pts) {
  const n = pts.length;
  let d = `M${pts[0]}`;
  for (let i = 0; i < n; i++) {
    const [p0, p1, p2, p3] = [pts[(i - 1 + n) % n], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${c1} ${c2} ${p2}`;
  }
  return d + "Z";
}
function inside(pts, x, y) {
  let hit = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}
function shrink(pts, k) {
  const cx = pts.reduce((a, p) => a + p[0], 0) / pts.length, cy = pts.reduce((a, p) => a + p[1], 0) / pts.length;
  return pts.map(([x, y]) => [cx + (x - cx) * k, cy + (y - cy) * k]);
}
function bbox(pts) {
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  return { x: Math.min(...xs) - 40, y: Math.min(...ys) - 40, x2: Math.max(...xs) + 40, y2: Math.max(...ys) + 40 };
}
// Triangular tessellation covering a box: calls fn(pointsString, row, col).
function triangles(b, s, fn) {
  const h = s * SQ3;
  for (let r = 0, y = b.y; y < b.y2; r++, y += h) {
    const off = (r % 2) * (s / 2);
    for (let c = 0, x = b.x - s + off; x < b.x2; c++, x += s) {
      fn(`${x},${y + h} ${x + s / 2},${y} ${x + s},${y + h}`, r, c * 2);
      fn(`${x + s / 2},${y} ${x + s * 1.5},${y} ${x + s},${y + h}`, r, c * 2 + 1);
    }
  }
}

// ---- layout (viewBox 0 0 1200 800) -----------------------------------------
const MAIN = [[150, 360], [330, 272], [560, 240], [652, 330], [640, 520], [470, 640], [300, 652], [160, 560]];
const ARENA = [[720, 140], [900, 95], [1060, 130], [1090, 280], [960, 370], [790, 340], [710, 250]];
export const SPOTS = {
  home: { support: [258, 478], writer: [372, 352], analyst: [552, 458], curator: [470, 532], judge: [898, 170] },
  vault: { support: [326, 458], writer: [452, 380], analyst: [492, 458] },
  arena: { support: [850, 212], writer: [898, 222], analyst: [946, 212] },
  inbox: [384, 574], vaultCenter: [410, 450], wall: [492, 315],
  bridge: [[606, 292], [722, 246]],
  podium: { brain: [822, 262], naive: [898, 280], no_memory: [976, 260] },
};
const ROOMS = [
  { x: 205, y: 408, w: 108, h: 96, label: "Support desk" },
  { x: 318, y: 312, w: 104, h: 58, label: "Release studio" },
  { x: 500, y: 398, w: 102, h: 86, label: "Analytics lab" },
  { x: 330, y: 560, w: 100, h: 34, label: "Inbox" },
];
export const CAST = {
  support: { name: "Support", letter: "S", color: "#8f80f2", skin: "#e8c39e" },
  writer: { name: "Writer", letter: "W", color: "#e87ba4", skin: "#a8724c" },
  analyst: { name: "Analyst", letter: "A", color: "#eda100", skin: "#d9a777" },
  curator: { name: "Curator", letter: "C", color: "#3987e5", skin: "#7a4a2e" },
  judge: { name: "Judge", letter: "J", color: "#cfcac0", skin: "#f0d2b4" },
};

export function createOffice(svg, { onSelect } = {}) {
  svg.innerHTML = "";
  const defs = el("defs", {}, svg);
  const L = {};
  for (const k of ["ground", "base", "rooms", "roof", "props", "items", "chars", "fx"]) L[k] = el("g", { class: `layer-${k}` }, svg);

  // gradients
  const glow = el("radialGradient", { id: "vaultGlow" }, defs);
  el("stop", { offset: "0%", "stop-color": "#3987e5", "stop-opacity": "0.55" }, glow);
  el("stop", { offset: "100%", "stop-color": "#3987e5", "stop-opacity": "0" }, glow);

  drawGround(L.ground);
  for (const [id, pts, seed] of [["main", MAIN, 7], ["arena", ARENA, 11]]) {
    const d = smooth(pts);
    el("path", { d, class: "bshadow", transform: "translate(12,16)" }, L.base);
    el("path", { d, class: "floor" }, L.base);
    drawRoof(L.roof, defs, id, pts, seed);
  }
  // glass bridge between buildings
  const [b1, b2] = SPOTS.bridge;
  el("line", { x1: b1[0], y1: b1[1], x2: b2[0], y2: b2[1], class: "bridge" }, L.base);
  el("line", { x1: b1[0], y1: b1[1], x2: b2[0], y2: b2[1], class: "bridge-glass" }, L.base);

  for (const r of ROOMS) {
    el("rect", { x: r.x, y: r.y, width: r.w, height: r.h, rx: 10, class: "room" }, L.rooms);
    el("text", { x: r.x + 9, y: r.y + 15, class: "roomlabel" }, L.rooms).textContent = r.label.toUpperCase();
  }
  drawFurniture(L.rooms);

  const vault = drawVault(L.props, defs);
  const wall = drawWall(L.props);
  const inbox = drawInbox(L.props);
  const arena = drawArena(L.props);

  // ---- characters ----
  const chars = {};
  for (const [key, info] of Object.entries(CAST)) {
    const g = el("g", { class: "char", tabindex: 0, role: "button", "aria-label": `${info.name} agent` }, L.chars);
    el("ellipse", { cx: 0, cy: 15, rx: 11, ry: 4, class: "shadow" }, g);
    const bob = el("g", {}, g);
    el("rect", { x: -10, y: -3, width: 20, height: 18, rx: 8, style: `fill:${info.color}` }, bob);
    el("circle", { cx: 0, cy: -11, r: 8, style: `fill:${info.skin}` }, bob);
    el("path", { d: "M-8,-12 a8,8 0 0 1 16,0 q-8,-4 -16,0z", class: "hair" }, bob);
    el("text", { x: 0, y: 10, class: "badge" }, bob).textContent = info.letter;
    el("text", { x: 0, y: 31, class: "nametag" }, g).textContent = info.name;
    const ring = el("circle", { cx: 0, cy: 2, r: 20, class: "selring" }, g);
    g.insertBefore(ring, g.firstChild);
    const ch = { key, g, bob, x: 0, y: 0, bubble: null };
    g.addEventListener("click", () => onSelect?.(key));
    g.addEventListener("keydown", e => (e.key === "Enter" || e.key === " ") && onSelect?.(key));
    chars[key] = ch;
  }
  const place = ch => ch.g.setAttribute("transform", `translate(${ch.x.toFixed(1)},${ch.y.toFixed(1)})`);

  // ---- animation engine ----
  let speed = 1;
  const tweens = new Set(), timers = new Set();
  function tween(ms, step, done) {
    const t = { start: performance.now(), ms: Math.max(1, ms / speed), step, done };
    tweens.add(t);
    return t;
  }
  (function frame(now) {
    for (const t of [...tweens]) {
      const k = Math.max(0, Math.min(1, (now - t.start) / t.ms)); // frame time can precede a tween's start
      t.step(k);
      if (k >= 1) { tweens.delete(t); t.done?.(); }
    }
    requestAnimationFrame(frame);
  })(performance.now());

  function schedule(ms, fn) {
    const id = setTimeout(() => { timers.delete(id); fn(); }, ms / speed);
    timers.add(id);
  }
  function cancel() {
    timers.forEach(clearTimeout);
    timers.clear();
    tweens.clear();
    L.items.innerHTML = "";
    Object.values(chars).forEach(ch => { ch.bubble?.remove(); ch.bubble = null; ch.bob.removeAttribute("transform"); });
  }
  function home() {
    for (const [k, ch] of Object.entries(chars)) {
      [ch.x, ch.y] = SPOTS.home[k];
      place(ch);
    }
  }

  function walk(key, to, ms = 900) {
    const ch = chars[key];
    const [fx, fy] = [ch.x, ch.y];
    // cross the bridge when going between buildings
    const path = [];
    const inMain = inside(MAIN, fx, fy), toMain = inside(MAIN, to[0], to[1]);
    if (inMain && !toMain) path.push(SPOTS.bridge[0], SPOTS.bridge[1]);
    if (!inMain && toMain) path.push(SPOTS.bridge[1], SPOTS.bridge[0]);
    path.push(to);
    const legs = [];
    let prev = [fx, fy];
    for (const p of path) { legs.push([prev, p]); prev = p; }
    const total = legs.reduce((a, [a1, a2]) => a + Math.hypot(a2[0] - a1[0], a2[1] - a1[1]), 0) || 1;
    const run = i => {
      if (i >= legs.length) { ch.bob.removeAttribute("transform"); return; }
      const [a, b] = legs[i];
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const dur = (ms * len) / total;
      tween(dur, k => {
        const e = ease(k);
        ch.x = lerp(a[0], b[0], e); ch.y = lerp(a[1], b[1], e);
        ch.bob.setAttribute("transform", `translate(0,${(-Math.abs(Math.sin((k * dur) / 85)) * 2.5).toFixed(2)})`);
        place(ch);
      }, () => run(i + 1));
    };
    run(0);
  }

  function say(key, text, ms = 1600, tone = "") {
    const ch = chars[key];
    ch.bubble?.remove();
    const g = el("g", { class: `bubble ${tone}`, transform: "translate(0,-30)" }, ch.g);
    const t = el("text", { x: 0, y: -9 }, g);
    t.textContent = text.length > 46 ? text.slice(0, 45) + "…" : text;
    const w = Math.max(40, t.getComputedTextLength() + 18);
    const r = el("rect", { x: -w / 2, y: -25, width: w, height: 24, rx: 9 }, g);
    el("path", { d: "M-5,-1.5 L0,6 L5,-1.5Z" }, g);
    g.insertBefore(r, t);
    ch.bubble = g;
    tween(220, k => g.setAttribute("opacity", k));
    schedule(ms, () => {
      if (ch.bubble !== g) return;
      tween(250, k => g.setAttribute("opacity", 1 - k), () => { g.remove(); if (ch.bubble === g) ch.bubble = null; });
    });
  }

  function fly(from, to, kind = "mail", ms = 700) {
    const g = el("g", { class: `token ${kind}` }, L.items);
    if (kind === "mail") {
      el("rect", { x: -6, y: -4, width: 12, height: 8, rx: 1.5 }, g);
      el("path", { d: "M-6,-4 L0,1 L6,-4" }, g);
    } else {
      el("rect", { x: -4.5, y: -6, width: 9, height: 12, rx: 1.5 }, g);
      el("line", { x1: -2.5, y1: -2, x2: 2.5, y2: -2 }, g);
      el("line", { x1: -2.5, y1: 1, x2: 2.5, y2: 1 }, g);
    }
    const lift = -40 - Math.random() * 30;
    tween(ms, k => {
      const e = ease(k);
      const x = lerp(from[0], to[0], e), y = lerp(from[1], to[1], e) + Math.sin(Math.PI * k) * lift;
      g.setAttribute("transform", `translate(${x},${y})`);
    }, () => g.remove());
  }

  function pos(key) { return [chars[key].x, chars[key].y]; }

  function select(key) {
    Object.entries(chars).forEach(([k, ch]) => ch.g.classList.toggle("selected", k === key));
  }

  return {
    cancel, home, walk, say, fly, schedule, pos, select,
    setSpeed: k => { speed = k; },
    pulseVault: kind => vault.pulse(kind, tween),
    updateVault: vault.update, updateWall: wall.update, updateInbox: inbox.update, updateArena: arena.update,
    flashPodium: arena.flash,
  };
}

// ---- static scenery ---------------------------------------------------------
function drawGround(g) {
  el("rect", { x: -50, y: -50, width: 1300, height: 900, class: "terrain" }, g);
  const r = seeded(42);
  // neighbouring low warehouses
  for (const [x, y, w, h] of [[30, 60, 150, 70], [210, 40, 120, 60], [40, 160, 110, 80], [360, 70, 140, 66],
    [1040, 430, 140, 110], [1080, 600, 110, 90], [40, 690, 120, 80], [540, 20, 120, 50]]) {
    el("rect", { x, y, width: w, height: h, rx: 3, class: "warehouse" }, g);
    el("rect", { x: x + 8, y: y + 8, width: w - 16, height: h - 16, rx: 2, class: "warehouse-roof" }, g);
  }
  // roads
  const roads = [
    { d: "M560,820 L770,560 Q820,500 900,470 L1230,380", w: 74 },
    { d: "M-30,600 Q140,700 330,830", w: 46 },
    { d: "M-30,250 Q300,170 660,92 T1230,40", w: 40 },
  ];
  for (const rd of roads) {
    el("path", { d: rd.d, class: "road", "stroke-width": rd.w }, g);
    el("path", { d: rd.d, class: "lane" }, g);
  }
  // parking lots with cars
  for (const [x0, y0, cols, rows] of [[900, 470, 7, 4], [210, 700, 8, 3], [700, 640, 5, 3]]) {
    el("rect", { x: x0 - 8, y: y0 - 8, width: cols * 18 + 10, height: rows * 30 + 6, rx: 4, class: "lot" }, g);
    for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++) {
      if (r() < 0.25) continue;
      const hue = ["#9aa3ad", "#5b6470", "#c9ccd1", "#3d4652", "#7d2f2f", "#2f4f7d"][Math.floor(r() * 6)];
      el("rect", { x: x0 + i * 18, y: y0 + j * 30, width: 9, height: 17, rx: 2.5, style: `fill:${hue}` }, g);
    }
  }
  // trees, kept off the buildings and roads' centre lines
  for (let i = 0; i < 170; i++) {
    const x = r() * 1200, y = r() * 800;
    if (inside(shrink(MAIN, 1.08), x, y) || inside(shrink(ARENA, 1.1), x, y)) continue;
    if (Math.abs(y - (820 - (x - 560) * 1.24)) < 50 && x > 560 && x < 770) continue;
    const rad = 5 + r() * 7;
    el("circle", { cx: x + 2, cy: y + 3, r: rad, class: "tree-shadow" }, g);
    el("circle", { cx: x, cy: y, r: rad, class: r() < 0.5 ? "tree" : "tree alt" }, g);
  }
  // lawn wrapping the main building
  el("path", { d: smooth(shrink(MAIN, 1.12)), class: "lawn" }, g);
  el("path", { d: smooth(shrink(ARENA, 1.12)), class: "lawn" }, g);
}

function drawRoof(layer, defs, id, pts, seed) {
  const path = smooth(pts), inner = smooth(shrink(pts, 0.85));
  const clip = el("clipPath", { id: `${id}-clip` }, defs);
  el("path", { d: path }, clip);
  const mask = el("mask", { id: `${id}-ring` }, defs);
  el("path", { d: path, fill: "white" }, mask);
  el("path", { d: inner, fill: "black" }, mask);
  const g = el("g", { "clip-path": `url(#${id}-clip)` }, layer);
  const ring = el("g", { mask: `url(#${id}-ring)` }, g);
  const glass = el("g", { class: "glass" }, g);
  const r = seeded(seed);
  triangles(bbox(pts), 30, pts => {
    el("polygon", { points: pts, class: r() < 0.58 ? "panel dark" : "panel light" }, ring);
    el("polygon", { points: pts }, glass);
  });
  el("path", { d: inner, class: "inner-rim" }, layer);
  el("path", { d: path, class: "rim" }, layer);
}

function drawFurniture(g) {
  const desks = [[216, 432], [262, 432], [216, 486], [332, 336], [522, 424], [560, 424], [522, 462]];
  for (const [x, y] of desks) {
    el("rect", { x, y, width: 34, height: 16, rx: 3, class: "desk" }, g);
    el("rect", { x: x + 10, y: y + 2, width: 14, height: 4, rx: 1, class: "monitor" }, g);
  }
  // plants
  for (const [x, y] of [[300, 416], [596, 476], [326, 364], [470, 588]]) el("circle", { cx: x, cy: y, r: 5, class: "plant" }, g);
}

function drawVault(layer, defs) {
  const [cx, cy] = SPOTS.vaultCenter;
  const g = el("g", { class: "vault", transform: `translate(${cx},${cy})` }, layer);
  const halo = el("circle", { r: 92, fill: "url(#vaultGlow)", class: "halo" }, g);
  // skylight mesh above the vault, like the glass centre of the roof
  const clip = el("clipPath", { id: "skylight" }, defs);
  el("circle", { r: 70 }, clip);
  const mesh = el("g", { "clip-path": "url(#skylight)", class: "mesh" }, g);
  triangles({ x: -80, y: -80, x2: 80, y2: 80 }, 13, pts => el("polygon", { points: pts }, mesh));
  el("circle", { r: 70, class: "vault-rim" }, g);
  el("circle", { r: 40, class: "vault-core" }, g);
  const tiles = el("g", {}, g);
  el("text", { y: -4, class: "vault-title" }, g).textContent = "PRODUCT BRAIN";
  const size = el("text", { y: 12, class: "vault-size" }, g);
  return {
    update(nFeatures, tokens) {
      size.textContent = `${nFeatures} entries · ${tokens.toLocaleString()} tok`;
      tiles.innerHTML = "";
      const n = Math.min(nFeatures, 16);
      for (let i = 0; i < n; i++) {
        const a = (i / Math.max(n, 1)) * Math.PI * 2 - Math.PI / 2;
        el("rect", { x: Math.cos(a) * 55 - 5, y: Math.sin(a) * 55 - 5, width: 10, height: 10, rx: 2.5, class: "tile" }, tiles);
      }
    },
    pulse(kind, tween) {
      halo.classList.remove("ok", "bad");
      halo.classList.add(kind === "bad" ? "bad" : "ok");
      tween(900, k => halo.setAttribute("r", 92 + Math.sin(k * Math.PI) * 18), () => halo.classList.remove("ok", "bad"));
    },
  };
}

function drawWall(layer) {
  const [x, y] = [430, 298];
  const g = el("g", { class: "wall" }, layer);
  el("rect", { x, y, width: 128, height: 32, rx: 4, class: "wall-board" }, g);
  const notes = el("g", {}, g);
  const label = el("text", { x: x + 64, y: y + 44, class: "wall-label" }, g);
  const r = seeded(5);
  const slots = Array.from({ length: 75 }, (_, i) => ({
    x: x + 4 + (i % 15) * 8 + r() * 2, y: y + 3 + Math.floor(i / 15) * 5.5 + r() * 1.5, rot: (r() - 0.5) * 30,
  }));
  return {
    update(count, frac, tokens) {
      notes.innerHTML = "";
      const n = Math.round(Math.min(1, frac) * slots.length);
      for (let i = 0; i < n; i++) {
        const s = slots[i];
        el("rect", { x: s.x, y: s.y, width: 7, height: 6, rx: 0.8, class: "note", transform: `rotate(${s.rot.toFixed(1)} ${s.x + 3.5} ${s.y + 3})` }, notes);
      }
      // overflow pile once the board is full
      for (let i = 0; i < Math.max(0, Math.round((frac - 0.75) * 40)); i++) {
        const px = x + 128 + r() * 18, py = y + 8 + r() * 26;
        el("rect", { x: px, y: py, width: 7, height: 6, class: "note", transform: `rotate(${(r() * 90).toFixed(0)} ${px} ${py})` }, notes);
      }
      label.textContent = `NAIVE NOTES · ${count} · ${tokens.toLocaleString()} tok`;
    },
  };
}

function drawInbox(layer) {
  const [x, y] = SPOTS.inbox;
  const g = el("g", { class: "inbox" }, layer);
  el("rect", { x: x - 16, y: y - 4, width: 32, height: 14, rx: 3, class: "tray" }, g);
  const count = el("text", { x: x + 24, y: y + 8, class: "inbox-count" }, g);
  el("text", { x, y: y + 34, class: "caption" }, g).textContent = "no-memory team sees only recent inbox events";
  return { update(n) { count.textContent = `${n} today`; } };
}

function drawArena(layer) {
  const g = el("g", { class: "arena" }, layer);
  el("text", { x: 898, y: 140, class: "roomlabel center" }, g).textContent = "CHECKPOINT ARENA";
  el("rect", { x: 872, y: 150, width: 52, height: 10, rx: 3, class: "bench" }, g);
  const pods = {};
  const names = { brain: "Product Brain", naive: "Naive memory", no_memory: "No memory" };
  for (const [team, [x, y]] of Object.entries(SPOTS.podium)) {
    const p = el("g", { class: `podium ${team}`, transform: `translate(${x},${y})` }, g);
    el("circle", { r: 27, class: "pod" }, p);
    const acc = el("text", { y: 1, class: "pod-acc" }, p);
    const stale = el("text", { y: 13, class: "pod-stale" }, p);
    el("text", { y: 40, class: "pod-name" }, p).textContent = names[team];
    pods[team] = { p, acc, stale };
  }
  return {
    update(scores) {
      for (const [team, pd] of Object.entries(pods)) {
        const s = scores?.[team];
        pd.acc.textContent = s ? `${Math.round(s.accuracy * 100)}%` : "–";
        pd.stale.textContent = s ? `${Math.round(s.stale_rate * 100)}% stale` : "";
      }
    },
    flash() {
      Object.values(pods).forEach(pd => { pd.p.classList.remove("flash"); void pd.p.getBBox(); pd.p.classList.add("flash"); });
    },
  };
}
