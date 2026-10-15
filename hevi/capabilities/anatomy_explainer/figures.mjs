import * as k from "../../../third_party/anatomy/kit/iso-kit.mjs";
import * as G from "../../../third_party/anatomy/kit/lathe.mjs";
import * as A from "../../../third_party/anatomy/kit/audit.mjs";
import { writeFileSync, mkdirSync } from "node:fs";

const FLOOR = { o: [0, 0, 0], a: [0, 0, 1], u: [1, 0, 0], v: [0, 1, 0] };

export const TITLES = {
  windmill: "小风车",
  waterwheel: "小水车",
  soap_pump: "洗手液",
  clock_gear: "小闹钟",
};

function prismPart(name, piece, color, F, poly, s0, s1, meta = {}, style = {}) {
  const shape = A.prism(F, poly, s0, s1, { name, owner: piece, ...meta });
  return {
    name, piece, color,
    shapes: [shape],
    render: (P) => k.solidSvg(G.prismOf(F, poly, s0, s1, P), { tone: "hi", ...style }),
  };
}

function lathePart(name, piece, color, F, profile, meta = {}, style = {}, opts = {}) {
  const shape = A.solid(F, profile, { name, owner: piece, ...meta });
  return {
    name, piece, color,
    shapes: [shape],
    render: (P) => k.solidSvg(G.solidOf(profile, F, P, opts), { tone: "hi", ...style }),
  };
}

function ringPart(name, piece, color, F, s0, s1, rIn, rOut, meta = {}, style = {}) {
  const shape = A.ring(F, s0, s1, rIn, rOut, { name, owner: piece, ...meta });
  return {
    name, piece, color,
    shapes: [shape],
    render: (P) => k.solidSvg(G.ringBand(s0, s1, rIn, rOut, F, P, {}), { tone: "hi", ...style }),
  };
}

function cylPart(name, piece, color, cx, cy, r, z, h, meta = {}, style = {}, steps = 36, bevel = 0) {
  const shape = A.cylinder(cx, cy, r, z, h, { name, owner: piece, ...meta });
  return {
    name, piece, color,
    shapes: [shape],
    render: (P) => k.solidSvg(k.cylinder(cx, cy, r, z, h, P, steps, bevel), { tone: "hi", ...style }),
  };
}

function slabPart(name, piece, color, plan, z, h, meta = {}, style = {}, steps = 8, bevel = 0) {
  const shape = A.slab(plan, z, h, { name, owner: piece, ...meta }, steps);
  return {
    name, piece, color,
    shapes: [shape],
    render: (P) => k.solidSvg(k.slabOf(plan, z, h, P, steps, bevel), { tone: "hi", ...style }),
  };
}

function detail(name, piece, svgGen) {
  return { name, piece, color: "line", shapes: [], render: svgGen };
}

function windmillParts() {
  const parts = [];
  const towerTop = 58;
  parts.push(slabPart("stand.base", "stand", "gray", { x: -72, y: -72, w: 144, d: 144, r: 14 }, -10, 10, { ground: true }, { tone: "mid" }, 8, 1.6));
  parts.push(lathePart("tower", "tower", "yellow", FLOOR, [[0, 15], [6, 13], [towerTop - 4, 9], [towerTop, 9]], {}, { tone: "hi" }, { bevel: 0.4 }));
  parts.push(cylPart("hub", "tower", "orange", 0, 0, 10, towerTop, 6, {}, { tone: "mid" }, 32, 0.6));
  const R = 52;
  const arms = [
    { x0: 10, y0: -7, x1: R, y1: 7 },
    { x0: -7, y0: 10, x1: 7, y1: R },
    { x0: -R, y0: -7, x1: -10, y1: 7 },
    { x0: -7, y0: -R, x1: 7, y1: -10 },
  ];
  arms.forEach((a, i) => {
    parts.push(prismPart(`blade${i}`, "rotor", i === 0 ? "red" : "blue", FLOOR, [
      [a.x0, a.y0], [a.x1, a.y0], [a.x1, a.y1], [a.x0, a.y1],
    ], towerTop + 1, towerTop + 5, {}, { tone: "hi" }));
  });
  parts.push(detail("tower.seam", "tower", (P) => k.lineSvg(k.ring(0, 0, 14.2, 16, P, 40), { tone: "faint" })));
  return parts;
}

function waterwheelParts() {
  const parts = [];
  const AXLE_Z = 42;
  const WHEEL_R = 26;
  parts.push(slabPart("stand.base", "stand", "gray", { x: -78, y: -64, w: 156, d: 128, r: 14 }, -10, 10, { ground: true }, { tone: "mid" }, 8, 1.6));
  parts.push(prismPart("stand.postA", "stand", "yellow", FLOOR, [[-7, 30], [7, 30], [7, 38], [-7, 38]], 0, AXLE_Z - 6, {}, { tone: "mid" }));
  parts.push(prismPart("stand.postB", "stand", "yellow", FLOOR, [[-7, -38], [7, -38], [7, -30], [-7, -30]], 0, AXLE_Z - 6, {}, { tone: "mid" }));
  parts.push(prismPart("axle", "wheel", "orange", FLOOR, [[-5.5, -34], [5.5, -34], [5.5, 34], [-5.5, 34]], 36, 48, {}, { tone: "mid" }));
  const Fy = G.frameOf([0, 0, AXLE_Z], [0, 1, 0], [1, 0, 0], [0, 0, 1]);
  parts.push(ringPart("wheel.disc", "wheel", "blue", Fy, -2.5, 2.5, 7, WHEEL_R, {}, { tone: "hi" }));
  const N = 8;
  for (let i = 0; i < N; i++) {
    const th = (i / N) * Math.PI * 2;
    const radial = [Math.cos(th), 0, Math.sin(th)];
    const tangential = [-Math.sin(th), 0, Math.cos(th)];
    const C = [WHEEL_R * radial[0], 0, AXLE_Z + WHEEL_R * radial[2]];
    const F = G.frameOf(C, [0, 1, 0], radial, tangential);
    parts.push(prismPart(`paddle${i}`, "wheel", i % 2 ? "green" : "cyan", F, [[0, -10], [13, -10], [13, 10], [0, 10]], -2.5, 2.5, {}, { tone: "hi" }));
  }
  parts.push(detail("wheel.seam", "wheel", (P) => k.lineSvg(k.ring(0, 0, WHEEL_R + 0.5, AXLE_Z, P, 48), { tone: "faint" })));
  return parts;
}

function soapPumpParts() {
  const parts = [];
  const BOTTLE_TOP = 62;
  const NECK_TOP = 88;
  const STEM_BOTTOM = 76;
  const STEM_TOP = 98;
  parts.push(slabPart("stand.base", "stand", "gray", { x: -58, y: -58, w: 116, d: 116, r: 14 }, -10, 10, { ground: true }, { tone: "mid" }, 8, 1.6));
  parts.push(slabPart("bottle", "bottle", "green", { x: -34, y: -34, w: 68, d: 68, r: 16 }, 0, BOTTLE_TOP, {}, { tone: "hi" }, 8, 2.0));
  parts.push(ringPart("neck", "bottle", "yellow", FLOOR, BOTTLE_TOP, NECK_TOP, 6.05, 12, {}, { tone: "mid" }));
  parts.push(cylPart("stem", "pump", "red", 0, 0, 6, STEM_BOTTOM, STEM_TOP - STEM_BOTTOM, {}, { tone: "mid" }, 28, 0.5));
  parts.push(prismPart("nozzle", "pump", "red", FLOOR, [[6, -5], [40, -5], [40, 5], [6, 5]], 90, 98, {}, { tone: "hi" }));
  parts.push(prismPart("cap", "pump", "orange", FLOOR, [[-12, -12], [12, -12], [12, 12], [-12, 12]], 98, 104, {}, { tone: "mid" }));
  parts.push(detail("bottle.label", "bottle", (P) => k.lineSvg(k.planOutline({ x: -26, y: -26, w: 52, d: 52, r: 12 }, 22, P, 8), { tone: "faint" })));
  return parts;
}

function clockGearParts() {
  const parts = [];
  const CASE_TOP = 50;
  const GEAR_Z = CASE_TOP;
  const GEAR_H = 8;
  const MAIN = [-18, 0];
  const SUB = [22, 10];
  const MAIN_R = 18;
  const SUB_R = 11;
  parts.push(slabPart("stand.base", "stand", "gray", { x: -70, y: -70, w: 140, d: 140, r: 14 }, -10, 10, { ground: true }, { tone: "mid" }, 8, 1.6));
  parts.push(slabPart("clock.case", "clock", "yellow", { x: -46, y: -46, w: 92, d: 92, r: 18 }, 0, CASE_TOP, {}, { tone: "hi" }, 8, 2.0));
  parts.push(detail("clock.face", "clock", (P) => k.lineSvg(k.ring(0, 0, 30, CASE_TOP + 0.2, P, 56), { tone: "faint" })));
  parts.push(detail("clock.ticks", "clock", (P) => {
    const ticks = [];
    for (let i = 0; i < 12; i++) {
      const a = (i / 12) * Math.PI * 2;
      ticks.push(k.lineOnTop([26 * Math.cos(a), 26 * Math.sin(a)], [30 * Math.cos(a), 30 * Math.sin(a)], CASE_TOP + 0.3, P));
    }
    return k.lineSvg(ticks.join(""), { tone: "faint" });
  }));
  parts.push(cylPart("gearMain", "gearMain", "red", MAIN[0], MAIN[1], MAIN_R, GEAR_Z, GEAR_H, {}, { tone: "mid" }, 40, 0.6));
  parts.push(cylPart("gearMainHub", "gearMain", "orange", MAIN[0], MAIN[1], 5, GEAR_Z + GEAR_H, 5, {}, { tone: "hi" }, 24));
  parts.push(cylPart("gearSub", "gearSub", "blue", SUB[0], SUB[1], SUB_R, GEAR_Z, GEAR_H, {}, { tone: "mid" }, 32, 0.6));
  parts.push(cylPart("gearSubHub", "gearSub", "orange", SUB[0], SUB[1], 4, GEAR_Z + GEAR_H, 5, {}, { tone: "hi" }, 20));
  for (let i = 0; i < 8; i++) {
    const a = (i / 8) * Math.PI * 2;
    const x = MAIN[0] + Math.cos(a) * (MAIN_R + 4);
    const y = MAIN[1] + Math.sin(a) * (MAIN_R + 4);
    parts.push(prismPart(`toothA${i}`, "gearMain", "red", FLOOR, [[x - 4, y - 4], [x + 4, y - 4], [x + 4, y + 4], [x - 4, y + 4]], GEAR_Z, GEAR_Z + GEAR_H, {}, { tone: "mid" }));
  }
  for (let i = 0; i < 6; i++) {
    const a = (i / 6) * Math.PI * 2;
    const x = SUB[0] + Math.cos(a) * (SUB_R + 4);
    const y = SUB[1] + Math.sin(a) * (SUB_R + 4);
    parts.push(prismPart(`toothB${i}`, "gearSub", "blue", FLOOR, [[x - 4, y - 4], [x + 4, y - 4], [x + 4, y + 4], [x - 4, y + 4]], GEAR_Z, GEAR_Z + GEAR_H, {}, { tone: "mid" }));
  }
  return parts;
}

const BUILDERS = {
  windmill: windmillParts,
  waterwheel: waterwheelParts,
  soap_pump: soapPumpParts,
  clock_gear: clockGearParts,
};

export const MOTION = {
  windmill: { rotor: { kind: "rotate", axis: [0, 0, 1], at: [0, 0, 61], speed: 0.35 } },
  waterwheel: { wheel: { kind: "rotate", axis: [0, 1, 0], at: [0, 0, 42], speed: 0.25 } },
  soap_pump: { pump: { kind: "slide", dir: [0, 0, -1], amp: 14, freq: 0.5 } },
  clock_gear: {
    gearMain: { kind: "rotate", axis: [0, 0, 1], at: [-18, 0, 54], speed: 0.3 },
    gearSub: { kind: "rotate", axis: [0, 0, 1], at: [22, 10, 54], speed: -0.6 },
  },
};

function boundsOfShapes(shapes) {
  let min = [Infinity, Infinity, Infinity];
  let max = [-Infinity, -Infinity, -Infinity];
  for (const s of shapes) {
    const b = A.boundsOf(s);
    for (let i = 0; i < 3; i++) {
      min[i] = Math.min(min[i], b.min[i]);
      max[i] = Math.max(max[i], b.max[i]);
    }
  }
  return { min, max };
}

export function buildFigure(objectName, aspect = "16:9", seed = 42) {
  if (!BUILDERS[objectName]) throw new Error(`Unknown anatomy object: ${objectName}`);
  const width = aspect === "9:16" ? 1080 : 1920;
  const height = aspect === "9:16" ? 1920 : 1080;
  const parts = BUILDERS[objectName]();

  if (process.env.HEVI_ANATOMY_AUDIT_INJECT === "clip") {
    // Inject a bad solid that causes a support failure or penetration
    parts.push(prismPart("bad_floating_part", "bad", "red", FLOOR, [[0,0],[20,0],[20,20],[0,20]], 200, 220, {}, { tone: "hi" }));
  }

  const solids = parts.flatMap((p) => p.shapes);
  const bb = boundsOfShapes(solids);
  const corners = [];
  for (const x of [bb.min[0], bb.max[0]]) for (const y of [bb.min[1], bb.max[1]]) for (const z of [bb.min[2], bb.max[2]]) corners.push([x, y, z]);
  const pad = 150;
  const P = k.fitProjection(corners, width, height, { pad, azimuth: 45, elevation: 30 });
  const cam = A.cameraBasis(P);
  const V = cam.V;

  for (const p of parts) {
    if (!p.shapes.length) {
      p.at = [0, 0, 0];
      p.key = 0;
      continue;
    }
    const b = boundsOfShapes(p.shapes);
    let best = null;
    let bestK = -Infinity;
    for (const x of [b.min[0], b.max[0]]) for (const y of [b.min[1], b.max[1]]) for (const z of [b.min[2], b.max[2]]) {
      const kk = x * V[0] + y * V[1] + z * V[2];
      if (kk > bestK) { bestK = kk; best = [x, y, z]; }
    }
    p.at = best;
    if (p.name === "axle") {
      p.at = best.map((v, i) => v - 1.0 * V[i]);
    }
    p.key = p.at[0] * V[0] + p.at[1] * V[1] + p.at[2] * V[2];
    p.bb = b;
  }
  parts.sort((a, b) => a.key - b.key || (a.name < b.name ? -1 : 1));

  const motion = MOTION[objectName] || {};
  for (const p of parts) {
    p.svg = p.render(P);
  }

  const bodyParts = [];
  for (const p of parts) {
    const inner = `<g class="${colorClass(p.color)}">${p.svg}</g>`;
    if (p.shapes.length && motion[p.piece]) {
      bodyParts.push(`<g data-part="${p.piece}">${inner}</g>`);
    } else {
      bodyParts.push(inner);
    }
  }

  return { objectName, aspect, seed, width, height, pad, P, V, parts, solids, bbox: bb, body: bodyParts.join(""), motion };
}

export function auditFigure(figure) {
  const R = A.recorder(figure.P, { order: [] });
  for (const p of figure.parts) {
    if (!p.shapes.length) continue;
    R.put({ name: p.name, at: p.at, move: [0, 0, 0], shapes: p.shapes, svg: p.svg, piece: p.piece });
    for (const s of p.shapes) R.solid(s);
  }
  const allow = [["axle", "wheel.disc"], ["gearSub", "toothB2"], ["stem", "neck"]];
  const result = A.audit(R, figure.P, { allow });
  const failures = A.failures(result);
  return { failures, report: A.report(result), result };
}

const COLOR_CSS = `
  .c-red { --anatomy-paper:#ef4444; --anatomy-top:#fca5a5; --anatomy-shade-0:#b91c1c; --anatomy-shade-1:#dc2626; --anatomy-shade-2:#ef4444; --anatomy-shade-3:#f87171; }
  .c-orange { --anatomy-paper:#f97316; --anatomy-top:#fdba74; --anatomy-shade-0:#c2410c; --anatomy-shade-1:#ea580c; --anatomy-shade-2:#f97316; --anatomy-shade-3:#fb923c; }
  .c-yellow { --anatomy-paper:#eab308; --anatomy-top:#fde047; --anatomy-shade-0:#a16207; --anatomy-shade-1:#ca8a04; --anatomy-shade-2:#eab308; --anatomy-shade-3:#facc15; }
  .c-green { --anatomy-paper:#22c55e; --anatomy-top:#86efac; --anatomy-shade-0:#15803d; --anatomy-shade-1:#16a34a; --anatomy-shade-2:#22c55e; --anatomy-shade-3:#4ade80; }
  .c-cyan { --anatomy-paper:#06b6d4; --anatomy-top:#67e8f9; --anatomy-shade-0:#0e7490; --anatomy-shade-1:#0891b2; --anatomy-shade-2:#06b6d4; --anatomy-shade-3:#22d3ee; }
  .c-blue { --anatomy-paper:#3b82f6; --anatomy-top:#93c5fd; --anatomy-shade-0:#1d4ed8; --anatomy-shade-1:#2563eb; --anatomy-shade-2:#3b82f6; --anatomy-shade-3:#60a5fa; }
  .c-purple { --anatomy-paper:#a855f7; --anatomy-top:#d8b4fe; --anatomy-shade-0:#7e22ce; --anatomy-shade-1:#9333ea; --anatomy-shade-2:#a855f7; --anatomy-shade-3:#c084fc; }
  .c-gray { --anatomy-paper:#64748b; --anatomy-top:#cbd5e1; --anatomy-shade-0:#334155; --anatomy-shade-1:#475569; --anatomy-shade-2:#64748b; --anatomy-shade-3:#94a3b8; }
  .c-line { --anatomy-lo:#475569; --anatomy-mid:#334155; }
`;

function colorClass(color) {
  return `c-${color}`;
}

export function generateFigureHtml(objectName, aspect, seed, outPath) {
  const fig = buildFigure(objectName, aspect, seed);
  const { width, height } = fig;
  const isPortrait = aspect === "9:16";
  const titleText = TITLES[objectName] || "小机器";

  const html = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>${titleText}</title>
<style>
  html, body { margin:0; padding:0; width:${width}px; height:${height}px; background:#dbeafe; overflow:hidden;
    font-family: system-ui, -apple-system, "Noto Sans CJK SC", sans-serif; }
  .title-label { position:absolute; top:${isPortrait ? "120px" : "52px"}; left:50%; transform:translateX(-50%);
    font-size:${isPortrait ? "76px" : "68px"}; font-weight:800; color:#ffffff; background:#dc2626;
    padding:14px 46px; border-radius:40px; box-shadow:0 10px 24px rgba(0,0,0,.25); letter-spacing:4px; z-index:10; }
  svg { position:absolute; top:0; left:0; width:${width}px; height:${height}px; z-index:1; }
  ${COLOR_CSS}
  ${k.ISO_CSS}
</style>
</head>
<body>
  <div class="title-label" data-readout>${titleText}</div>
  <svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg">
    <rect width="${width}" height="${height}" fill="#dbeafe"/>
    ${fig.body}
  </svg>
<script>
(function(){
  var P = ${JSON.stringify(fig.P)};
  var MOTION = ${JSON.stringify(fig.motion)};
  function cam(p){
    var a = p.azimuth * Math.PI / 180, e = p.elevation * Math.PI / 180;
    return { sinA: Math.sin(a), cosA: Math.cos(a), sinE: Math.sin(e), cosE: Math.cos(e), k: p.scale * Math.sqrt(1.6) };
  }
  function screenOf(p, q){
    var c = cam(p);
    return [ p.origin[0] + (q[0]*c.sinA - q[1]*c.cosA) * c.k,
             p.origin[1] + ((q[0]*c.cosA + q[1]*c.sinA) * c.sinE - q[2]*c.cosE) * c.k ];
  }
  function basis(axis){
    if (Math.abs(axis[2]) > 0.9) return [[1,0,0],[0,1,0]];
    if (Math.abs(axis[1]) > 0.9) return [[1,0,0],[0,0,1]];
    return [[0,1,0],[0,0,1]];
  }
  function rotMatrix(p, axis, theta){
    var b = basis(axis);
    var s1 = screenOf(p, b[0]), s2 = screenOf(p, b[1]);
    var o = screenOf(p, [0,0,0]);
    var a11 = s1[0]-o[0], a21 = s1[1]-o[1], a12 = s2[0]-o[0], a22 = s2[1]-o[1];
    var det = a11*a22 - a12*a21;
    var ct = Math.cos(theta), st = Math.sin(theta);
    var r11 = ct, r12 = -st, r21 = st, r22 = ct;
    var i11 = a22/det, i12 = -a12/det, i21 = -a21/det, i22 = a11/det;
    var m11 = (a11*r11 + a12*r21)*i11 + (a11*r12 + a12*r22)*i21;
    var m12 = (a11*r11 + a12*r21)*i12 + (a11*r12 + a12*r22)*i22;
    var m21 = (a21*r11 + a22*r21)*i11 + (a21*r12 + a22*r22)*i21;
    var m22 = (a21*r11 + a22*r21)*i12 + (a21*r12 + a22*r22)*i22;
    return [m11, m21, m12, m22];
  }
  function axisVector(p, v){
    var o = screenOf(p, [0,0,0]), q = screenOf(p, v);
    return [q[0]-o[0], q[1]-o[1]];
  }
  window.__heviSeek = function(t){
    for (var name in MOTION){
      var g = MOTION[name];
      var els = document.querySelectorAll('[data-part="' + name + '"]');
      if (!els.length) continue;
      if (g.kind === "rotate"){
        var M = rotMatrix(P, g.axis, t * g.speed * Math.PI * 2);
        var c = screenOf(P, g.at);
        var e = c[0] - M[0]*c[0] - M[2]*c[1];
        var f = c[1] - M[1]*c[0] - M[3]*c[1];
        var tr = "matrix(" + M[0] + " " + M[1] + " " + M[2] + " " + M[3] + " " + e + " " + f + ")";
        for (var i = 0; i < els.length; i++) els[i].setAttribute("transform", tr);
      } else if (g.kind === "slide"){
        var s = Math.sin(t * Math.PI * 2 * g.freq);
        var d = axisVector(P, [g.dir[0]*g.amp*s, g.dir[1]*g.amp*s, g.dir[2]*g.amp*s]);
        var tr2 = "translate(" + d[0] + " " + d[1] + ")";
        for (var j = 0; j < els.length; j++) els[j].setAttribute("transform", tr2);
      }
    }
  };
  window.__heviSeek(0);
})();
</script>
</body>
</html>`;

  const dir = outPath.split("/").slice(0, -1).join("/");
  if (dir) mkdirSync(dir, { recursive: true });
  writeFileSync(outPath, html, "utf-8");
  return outPath;
}
