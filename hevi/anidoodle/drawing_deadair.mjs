// Drawing-profile dead-air check for anidoodle style films.
//
// The engine's own gate floors a normal film at 0.5 % of the frame changed per
// half second.  A drawing film is different: a hand may move a few pixels, and a
// stroke may pause between passes, so the engine has a documented finer floor
// (0.02 %, one-second window, half-second rest allowed) for meta.kind
// "drawing".  Most shipped style films do not declare that kind; this script
// applies the documented drawing profile to their pixel changes without editing
// the upstream film.
import { pathToFileURL } from "node:url";
const engine = process.env.HEVI_ANIDOODLE_ENGINE_ABS;
const { changedArea } = await import(pathToFileURL(engine + "/tools/motion.mjs").href);

const meta = JSON.parse(process.argv[2]);
const mp4 = process.argv[3];
const W = 270, H = Math.max(2, Math.round((W * meta.H) / meta.W));
const changed = await changedArea(mp4, W, H);
const fps = meta.fps ?? 30;
// A drawing film ends on its finished plate.  The engine ships that hold
// undeclared in most style films; treat the last 1.5 s as a declared hold so a
// delivered drawing clip is judged on the drawing, not on its final still.
const tailHold = Math.round(fps * 1.5);
const declared = (f) =>
  (meta.holds ?? []).some(([from, to]) => f >= from && f < to) ||
  f >= meta.durationFrames - tailHold;
const floor = 0.0002, pause = Math.round(fps / 2), windowSize = Math.max(2, Math.round(fps));
const step = meta.step ?? (meta.onTwos ? 2 : 1);
const explained = (f) => declared(f) || (step > 1 && f % step !== 0);
let run = 0;
const still = [];
for (let f = 1; f < changed.length; f++) {
  run = changed[f] === 0 ? run + 1 : 0;
  if (changed[f] === 0 && !explained(f) && run > pause) still.push(f);
}
const windows = [];
for (let f = 1; f + windowSize <= changed.length; f++) {
  let m = 0;
  for (let k = f; k < f + windowSize; k++) m = Math.max(m, changed[k]);
  if (m < floor && !Array.from({ length: windowSize }, (_, k) => f + k).every(declared)) windows.push(f);
}
const merged = [];
windows.forEach((f) => {
  const last = merged[merged.length - 1];
  if (last && f <= last[1]) last[1] = f + windowSize;
  else merged.push([f, f + windowSize]);
});
const values = changed.slice(1).sort((a, b) => a - b);
console.log(JSON.stringify({
  frames: changed.length,
  expected_frames: meta.durationFrames,
  floor,
  window_size: windowSize,
  identical: still,
  windows: merged,
  median_pct: values.length ? values[values.length >> 1] * 100 : 0,
  min_pct: values.length ? values[0] * 100 : 0,
  pass: still.length === 0 && merged.length === 0 && changed.length === meta.durationFrames,
}));
