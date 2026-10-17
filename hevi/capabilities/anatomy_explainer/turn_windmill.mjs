/**
 * Hevi 3D mode (mode=3d) reference figure: a windmill whose rotor is a real
 * turning group.
 *
 * This is the Hevi-side scene that proves the vendored 3D kit
 * (`third_party/anatomy/kit/turn*.mjs`) end to end:
 *
 *  - every part is recorded with its true shape, so `kit/audit.mjs` and the
 *    orbit audit in `kit/turn-audit.mjs` can measure it;
 *  - the rotor is one `turn` group, so every frame is the kit's own picture at
 *    P'(theta) and `scripts/turn-check.mjs --fidelity` can compare it against
 *    the kit builders;
 *  - the page mounts `TURN.mount(...)` and exposes `window.__isoTurn`, so
 *    `scripts/drive.mjs` can turn it to an exact angle and shoot a frame.
 *
 * Run it directly to write the page:
 *   node turn_windmill.mjs [--aspect 16:9|9:16] [--theme dark|light] [--out file.html]
 *
 * `--audit` adds the kit's own geometry + orbit audits (slow: the orbit sweep
 * is the proof, `--quick` under-samples it for a smoke run).
 */
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import * as k from "../../../third_party/anatomy/kit/iso-kit.mjs";
import * as G from "../../../third_party/anatomy/kit/lathe.mjs";
import * as A from "../../../third_party/anatomy/kit/audit.mjs";
import { turning } from "../../../third_party/anatomy/kit/turn-build.mjs";
import * as TA from "../../../third_party/anatomy/kit/turn-audit.mjs";
import { turnScript, glScript } from "../../../third_party/anatomy/scripts/inline-kit.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const value = (flag, fallback) => {
  const at = argv.indexOf(flag);
  return at >= 0 ? argv[at + 1] : fallback;
};
const ASPECT = value("--aspect", "16:9");
if (ASPECT !== "16:9" && ASPECT !== "9:16") throw new Error(`turn_windmill: --aspect must be 16:9 or 9:16, got ${ASPECT}`);
const THEME = value("--theme", "light");
if (THEME !== "dark" && THEME !== "light") throw new Error(`turn_windmill: --theme must be dark or light, got ${THEME}`);
const OUT = value("--out", null);

const PORTRAIT = ASPECT === "9:16";
const WIDTH = PORTRAIT ? 720 : 1280;
const HEIGHT = PORTRAIT ? 1280 : 720;
const AZIMUTH = 45;
const ELEVATION = 30;

const VERT = (x, y) => G.frameOf([x, y, 0], [0, 0, 1], [1, 0, 0], [0, 1, 0]);
const S = (paths, style) => k.solidSvg(paths, style);
const L = (d, style) => k.lineSvg(d, style);
const D = (points, style) => k.dotsSvg(points, style);

// ── the machine, in world units (z up, base plate top at z = 0) ──────────────
const BASE = { x: -74, y: -56, w: 148, d: 112, r: 10 };
const BASE_H = 12;
const FOOT_H = 4;
const FOOT_R = 6;
const TOWER_Z0 = 0;
const TOWER_Z1 = 62;
const TOWER_R0 = 15;
const TOWER_R1 = 8.6;
const CAP_H = 1.6;
const HUB_Z = TOWER_Z1 + CAP_H;
const HUB_H = 8;
const HUB_R = 11;
const BLADE_ROOT = HUB_R;
const BLADE_TIP = 52;
const BLADE_HALF = 4;
const BLADE_Z0 = HUB_Z + 2;
const BLADE_Z1 = HUB_Z + HUB_H - 2;

// Every extreme of the machine, so the fit holds the rotor at any angle: the
// base plate's corners, the hub, and the four blade tips (they sit on the
// diagonals, which is the screen's vertical at azimuth 45).
const FIT = [...k.boxCorners(BASE, -BASE_H - FOOT_H, 0), [0, 0, HUB_Z + HUB_H + 4]];
for (let i = 0; i < 4; i++) {
  const th = (i / 4) * Math.PI * 2 + Math.PI / 4;
  for (const [r, z] of [[BLADE_TIP, BLADE_Z0], [BLADE_TIP, BLADE_Z1]]) FIT.push([Math.cos(th) * r, Math.sin(th) * r, z]);
}
const P = k.fitProjection(FIT, WIDTH, HEIGHT, { pad: PORTRAIT ? 40 : 26, azimuth: AZIMUTH, elevation: ELEVATION });
const at = (p) => k.iso(p, P);

export const R = A.recorder(P);
const put = (item) => R.put({ ...item, shapes: item.shapes.map((shape) => R.solid(Object.assign(shape, { name: shape.name ?? item.name }))) });

export const T = turning(P, { recorder: R });
const rotor = T.group("rotor", { turn: { pivot: [0, 0] } });
const back = T.layer("back");
const mid = T.layer("mid");
T.stack(["back", "mid"]);

// ── static: feet, base plate, screws, tower, cap ─────────────────────────────
function stand() {
  for (const [x, y] of k.corners(BASE, 22)) {
    const svg = S(k.cylinder(x, y, FOOT_R, -BASE_H - FOOT_H, FOOT_H, P, 24), { tone: "lo" });
    put({ name: `stand.foot.${x}.${y}`, layer: "back", at: [x, y, -BASE_H - FOOT_H], svg, shapes: [A.cylinder(x, y, FOOT_R, -BASE_H - FOOT_H, FOOT_H, { ground: true })] });
  }
  const screws = k.corners(BASE, 9);
  const svg =
    S(k.slabOf(BASE, -BASE_H, BASE_H, P, 8, 1.6), { tone: "mid", inner: L(k.sideSeam(BASE, -BASE_H + 4, P, 8), { tone: "faint" }) }) +
    L(screws.map(([x, y]) => k.ring(x, y, 2.4, 0, P, 18)).join(""), { tone: "lo" }) +
    D(screws.map(([x, y]) => at([x, y, 0])), { size: 0.5 });
  put({ name: "stand.base", layer: "back", at: [0, 0, -BASE_H], bias: 4, svg, shapes: [A.slab(BASE, -BASE_H, BASE_H, { ground: true })] });
  // a ruler strip along the near edge: ticks hang from the strip's own line,
  // so every tick end lands on something (`references/verify.md`, line ends)
  // A ruler strip on the near edge of the plate: the strip's own line is the
  // root of every tick, so no tick end floats (`references/verify.md`).
  const edge = BASE.y + BASE.d / 2 - 9;
  const from = BASE.x + 16;
  const to = BASE.x + BASE.w - 16;
  const toScreen = (p) => at(p).map((v) => v.toFixed(2));
  const line = (a, b) => `M${toScreen(a)}L${toScreen(b)}`;
  const ticks = [line([from, edge - 0.5, 0], [to, edge - 0.5, 0])];
  for (let i = 0; i <= 16; i++) {
    const x = from + ((to - from) * i) / 16;
    const len = i % 4 === 0 ? 4.2 : 2.4;
    ticks.push(line([x, edge - 0.5, 0], [x, edge - 0.5 + len, 0]));
  }
  put({
    name: "stand.ruler",
    layer: "back",
    at: [0, edge, 0],
    bias: 6,
    svg: L(ticks.join(""), { tone: "lo" }) + D([at([from, edge - 0.5, 0]), at([to, edge - 0.5, 0])], { size: 0.5 }),
    shapes: [],
  });
}

function tower() {
  const profile = [[TOWER_Z0, TOWER_R0], [TOWER_Z0 + 4, TOWER_R0 - 1.2], [TOWER_Z1 - 6, TOWER_R1 + 0.6], [TOWER_Z1, TOWER_R1]];
  const svg = S(G.solidOf(profile, VERT(0, 0), P, { bevel: 0.4 }), { tone: "hi" }) + L(k.ring(0, 0, TOWER_R1 + 0.2, TOWER_Z1 - 6, P, 40), { tone: "faint" });
  put({ name: "tower", layer: "back", at: [0, 0, TOWER_Z0], svg, shapes: [A.solid(VERT(0, 0), profile)] });
  const capSvg = S(k.cylinder(0, 0, TOWER_R1 + 0.9, TOWER_Z1, CAP_H, P, 36, 0.4), { tone: "mid" }) + D([at([0, 0, TOWER_Z1 + CAP_H])], { size: 0.6 });
  put({ name: "tower.cap", layer: "back", at: [0, 0, TOWER_Z1], svg: capSvg, shapes: [A.cylinder(0, 0, TOWER_R1 + 0.9, TOWER_Z1, CAP_H)] });
  // a bolt ring on the cap's rim: dots only, the cap is the shape
  const bolts = [];
  for (let i = 0; i < 6; i++) {
    const a = (i / 6) * Math.PI * 2;
    bolts.push(at([Math.cos(a) * (TOWER_R1 + 0.2), Math.sin(a) * (TOWER_R1 + 0.2), TOWER_Z1 + CAP_H]));
  }
  put({ name: "tower.bolts", layer: "back", at: [0, 0, TOWER_Z1 + CAP_H], svg: D(bolts, { size: 0.45 }), shapes: [] });
}

// ── live: hub and four blades on the rotor group ─────────────────────────────
function rotorParts() {
  T.round({
    name: "hub",
    group: rotor,
    layer: "mid",
    F: VERT(0, 0),
    s0: HUB_Z,
    s1: HUB_Z + HUB_H,
    r: HUB_R,
    tone: "mid",
    crease: "lo",
    material: "chrome",
    details: { seams: [HUB_Z + 2.6], bolts: [{ s: HUB_Z + HUB_H, r: HUB_R - 2.6, count: 6, size: 0.5, phase: 0.3 }] },
  });
  for (let i = 0; i < 4; i++) {
    const th = (i / 4) * Math.PI * 2 + Math.PI / 4;
    const u = [Math.cos(th), Math.sin(th), 0];
    const v = [-Math.sin(th), Math.cos(th), 0];
    const F = { o: [0, 0, 0], a: [0, 0, 1], u, v };
    T.prism({
      name: `blade${i}`,
      group: rotor,
      layer: "mid",
      F,
      polygon: [[BLADE_ROOT, -BLADE_HALF], [BLADE_TIP - 7, -BLADE_HALF * 0.62], [BLADE_TIP, 0], [BLADE_TIP - 7, BLADE_HALF * 0.62], [BLADE_ROOT, BLADE_HALF]],
      s0: BLADE_Z0,
      s1: BLADE_Z1,
      tone: "hi",
      crease: "lo",
      bevel: 0.5,
      material: i % 2 ? "steel" : "brass",
      details: { seams: [BLADE_Z0 + 0.9, BLADE_Z1 - 0.9] },
    });
  }
}

stand();
tower();
rotorParts();

const poses = () => Array.from({ length: 360 }, (_, i) => ({ rotor: i }));
// `--verify` records the built shapes for `scripts/turn-check.mjs --order`,
// which paints the recorded shapes in a WebGL z-buffer and compares them with
// the live layers' DOM order.
const VERIFY = argv.includes("--verify");
const out = T.build({ statics: R.items, poses, verify: VERIFY });
A.settle(R, P);

if (argv.includes("--audit")) {
  A.auditOrExit(R, P);
  TA.orbitOrExit(T, R, P, { sweep: { at: (x) => ({ rotor: x }), from: 0, to: 360, frame: 1 }, quick: argv.includes("--quick") });
}

// ── page ─────────────────────────────────────────────────────────────────────
const layerOf = (name) => R.items.filter((item) => item.layer === name).sort((a, b) => a.key - b.key).map((item) => item.svg);
const halo = `<path class="iso-halo" d="${k.haloOf(BASE, -BASE_H - FOOT_H, BASE_H, P)}"/>`;
// The first SVG is in flow: it gives the stage its height. Every later layer is
// `.iso-layer` (absolute, inset 0), so the live layer sits exactly on top.
const backSvg = k.figureSvg({ width: WIDTH, height: HEIGHT, label: "Windmill: a tower on a base plate, with a four-blade rotor on top", body: [halo, ...layerOf("back")] });
const stage = `<div class="iso-stage iso-turn wm-stage" tabindex="0" role="slider" aria-label="Windmill: drag or use the arrow keys to turn the rotor" aria-valuemin="0" aria-valuemax="360" aria-valuenow="0" aria-valuetext="rotor at 0 degrees">${backSvg}${out.layerSvg("mid", { width: WIDTH, height: HEIGHT })}</div>`;

const DATA = { turn: out.data };
const LIVE = `
const DATA = ${JSON.stringify(DATA)};
const stage = document.querySelector(".wm-stage");
const readout = document.querySelector("[data-readout]");
const describe = (value) => {
  const shown = Math.round((((Number(value) % 360) + 360) % 360) * 10) / 10;
  stage.setAttribute("aria-valuenow", String(Math.round(shown)));
  stage.setAttribute("aria-valuetext", "rotor at " + shown + " degrees");
  const text = "rotor " + shown + "\\u00b0";
  if (readout.textContent !== text) readout.textContent = text;
};
const controller = TURN.mount(stage, DATA.turn, { onFrame: (turned) => describe(turned.values.rotor ?? 0) });
// window.__isoTurn is installed by TURN.mount; scripts/drive.mjs drives it with
// the "turn" action.  Wrap its set once so the readout and aria value follow.
const kitSet = window.__isoTurn.set;
window.__isoTurn.set = (next) => {
  const stats = kitSet(next);
  describe(window.__isoTurn.get().rotor ?? 0);
  return stats;
};
window.__heviSeek = (degrees) => controller.set({ rotor: Number(degrees) });
controller.set({ rotor: 0 });
`;

const body = k.plateHtml({
  fig: "Fig 3D",
  title: "Windmill",
  hint: "Drag the rotor \u00b7 arrow keys",
  readout: "rotor 0\u00b0",
  keys: [
    { mark: "raised", label: "The rotor: hub and four blades, one rigid group" },
    { mark: "flat", label: "The tower and the base: static kit art" },
  ],
  caption: "3D mode: the rotor is re-projected and re-shaded every frame by the kit's own rules, and painted in an order solved from separating planes.",
  body: `<style>${out.css}</style>${stage}`,
});
const page = k.pageHtml({
  title: "Windmill (3D)",
  theme: THEME,
  body,
  script: turnScript() + glScript() + (VERIFY ? `window.__isoVerify = ${JSON.stringify(out.verify)};\n` : "") + LIVE,
  width: PORTRAIT ? 620 : 1180,
});

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const name = OUT ?? join(HERE, `turn-windmill-${ASPECT.replace(":", "x")}-${THEME}.html`);
  writeFileSync(name, page, "utf-8");
  console.log(`wrote ${name} · ${(page.length / 1024).toFixed(0)} KB · ${out.report.parts} parts · ${out.report.layers.map((l) => `${l.name}: ${l.planar} planes, ${l.dynamic} dynamic`).join(" · ")}`);
}

export { page, out, P, WIDTH, HEIGHT };
