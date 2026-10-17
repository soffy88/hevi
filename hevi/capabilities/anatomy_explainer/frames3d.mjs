/**
 * Record frames from a turning (3D) Anatomy page.
 *
 * The page exposes `window.__heviSeek(degrees)` (see turn_windmill.mjs), which
 * sets the rotor group and renders synchronously.  This script launches one
 * headless Chromium (CPU: SwiftShader, no GPU needed), seeks to an exact angle
 * per frame, waits two animation frames and writes a PNG of the card.
 *
 * Usage:
 *   node frames3d.mjs <page.html> <frames-dir> [--fps 30] [--seconds 4]
 *        [--width 1280] [--height 720] [--degrees-per-second 36]
 *        [--start 0] [--scale 1] [--selector .iso-plate]
 *
 * Prints one JSON line: {"frames":N,"angles":[...],"clip":{...}}.
 */
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromePort } from "../../../third_party/anatomy/scripts/chrome-port.mjs";

const argv = process.argv.slice(2);
const take = (flag, fallback) => {
  const at = argv.indexOf(flag);
  if (at < 0) return fallback;
  const value = argv[at + 1];
  argv.splice(at, 2);
  return value;
};
const [page, framesDir] = argv;
if (!page || !framesDir) {
  console.error("usage: node frames3d.mjs <page.html> <frames-dir> [--fps 30] [--seconds 4] [--degrees-per-second 36]");
  process.exit(2);
}
const fps = Number(take("--fps", "30"));
const seconds = Number(take("--seconds", "4"));
const width = Number(take("--width", "1280"));
const height = Number(take("--height", "720"));
const degreesPerSecond = Number(take("--degrees-per-second", "36"));
const start = Number(take("--start", "0"));
const scale = Number(take("--scale", "1"));
const selector = take("--selector", ".iso-plate");
for (const [name, value] of [["fps", fps], ["seconds", seconds], ["width", width], ["height", height], ["degrees-per-second", degreesPerSecond], ["scale", scale]]) {
  if (!Number.isFinite(value) || value <= 0) {
    console.error(`frames3d: --${name} needs a number above 0, got ${value}`);
    process.exit(2);
  }
}
const total = Math.max(1, Math.round(fps * seconds));
const binary = process.env.CHROME_PATH;
if (!binary) {
  console.error("frames3d: CHROME_PATH is not set (the renderer resolves it with chrome.py)");
  process.exit(2);
}
mkdirSync(framesDir, { recursive: true });

const profile = mkdtempSync(join(tmpdir(), "iso-3d-"));
const chrome = spawn(binary, [
  "--headless=new",
  "--no-sandbox",
  "--disable-gpu",
  "--enable-unsafe-swiftshader",
  "--ignore-gpu-blocklist",
  "--remote-debugging-port=0",
  `--user-data-dir=${profile}`,
  "--no-first-run",
  "--no-default-browser-check",
  "--hide-scrollbars",
  "--allow-file-access-from-files",
  "about:blank",
]);

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

async function main() {
  const port = await chromePort(chrome, profile);
  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  socket.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.id && pending.has(data.id)) {
      const { done, fail, timer } = pending.get(data.id);
      clearTimeout(timer);
      pending.delete(data.id);
      if (data.error) fail(new Error(`${data.error.message ?? "CDP error"}`));
      else done(data);
    }
  };
  const send = (method, params = {}, patience = 60000) =>
    new Promise((done, fail) => {
      const call = ++id;
      const timer = setTimeout(() => {
        pending.delete(call);
        fail(new Error(`Chrome did not answer ${method} within ${Math.round(patience / 1000)} s`));
      }, patience);
      pending.set(call, { done, fail, timer });
      socket.send(JSON.stringify({ id: call, method, params }));
    });
  const evaluate = async (expression) => {
    const reply = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (reply.result?.exceptionDetails) throw new Error(`page exception: ${reply.result.exceptionDetails.text}`);
    return reply.result?.result?.value;
  };
  await new Promise((done) => (socket.onopen = done));
  await send("Runtime.enable");
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: pathToFileURL(resolve(page)).href });
  // wait for the page and for the 3D controller to be installed
  for (let attempt = 0; attempt < 200; attempt++) {
    const ready = await evaluate(`document.readyState === "complete" && typeof window.__heviSeek === "function"`);
    if (ready) break;
    await sleep(50);
  }
  const ready = await evaluate(`typeof window.__heviSeek === "function" && Boolean(document.querySelector(${JSON.stringify(selector)}))`);
  if (!ready) throw new Error("frames3d: page never exposed window.__heviSeek or the card selector");
  await evaluate(`document.fonts && document.fonts.ready ? document.fonts.ready.then(() => true) : true`);
  const box = await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})()`);
  if (!box || box.width < 40 || box.height < 40) throw new Error(`frames3d: card selector ${selector} measured ${JSON.stringify(box)}`);

  const angles = [];
  for (let i = 0; i < total; i++) {
    const angle = start + (i * degreesPerSecond) / fps;
    angles.push(Math.round(angle * 1000) / 1000);
    await evaluate(`window.__heviSeek(${angle})`);
    await evaluate(`new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => done(true))))`);
    const shot = await send("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: true,
      clip: { x: box.x, y: box.y, width: box.width, height: box.height, scale },
    });
    const file = join(framesDir, `${String(i).padStart(4, "0")}.png`);
    writeFileSync(file, Buffer.from(shot.result.data, "base64"));
  }
  const errors = await evaluate(`(window.__isoConsoleErrors ?? []).slice(0, 5)`);
  if (Array.isArray(errors) && errors.length) throw new Error(`frames3d: page console errors: ${JSON.stringify(errors)}`);
  console.log(JSON.stringify({ frames: total, angles: [angles[0], angles[angles.length - 1]], clip: { width: Math.round(box.width * scale), height: Math.round(box.height * scale) }, selector }));
  socket.close();
}

main()
  .then(() => {
    chrome.kill("SIGKILL");
    try {
      rmSync(profile, { recursive: true, force: true });
    } catch {}
  })
  .catch((error) => {
    chrome.kill("SIGKILL");
    try {
      rmSync(profile, { recursive: true, force: true });
    } catch {}
    console.error(String(error?.stack ?? error));
    process.exit(1);
  });
