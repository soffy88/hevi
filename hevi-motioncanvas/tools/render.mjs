#!/usr/bin/env node
/**
 * Headless Motion Canvas render (ubuntu26-verified route).
 *
 * Motion Canvas has NO first-party headless CLI: rendering lives in the
 * browser editor (Renderer + exporter), with @motion-canvas/ffmpeg muxing
 * frames on the Vite dev-server (Node) side. This script therefore:
 *   1. spawns `vite` for the project on a scratch port,
 *   2. drives the real editor in headless Chromium (playwright-core),
 *      selects the "Video (FFmpeg)" exporter and clicks Render,
 *   3. waits until the .mp4 in <project>/output is FINAL: size >= 10KB,
 *      unchanged for 5s, and ffprobe can parse a duration > 0.
 *      (The exporter creates a 48-byte header file immediately; size
 *      stability alone false-positives on it — learned the hard way.)
 *
 * Chromium: the FULL build is required. The chrome-headless-shell build
 * throttles the editor render loop to ~0.25 fps at 1080p (verified:
 * 4.07s of a 6s clip in ~8 min); the full build rendered the same clip
 * (361 frames @60fps) in seconds.
 *
 * Usage:  node tools/render.mjs [projectDir] [--port 9017] [--timeout 300]
 * Env:    MC_CHROMIUM=/path/to/chrome (auto-detected otherwise)
 * Deps:   playwright-core (devDependency), a Chromium build, ffprobe.
 */
import {execFile, spawn} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {chromium} from 'playwright-core';

const args = process.argv.slice(2);
const projectDir = path.resolve(args.find(a => !a.startsWith('--')) || '.');
const opt = (name, dflt) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : dflt;
};
const basePort = Number(opt('--port', '9017'));
const timeoutS = Number(opt('--timeout', '300'));

function findChromium() {
  if (process.env.MC_CHROMIUM) return process.env.MC_CHROMIUM;
  const cache = path.join(os.homedir(), '.cache/ms-playwright');
  const candidates = [];
  if (fs.existsSync(cache)) {
    const dirs = fs.readdirSync(cache).sort().reverse();
    for (const d of dirs) candidates.push(path.join(cache, d, 'chrome-linux64/chrome'));
    for (const d of dirs) candidates.push(path.join(cache, d, 'chrome-linux/chrome'));
    // last resort only (throttles rendering, see header):
    for (const d of dirs) candidates.push(path.join(cache, d, 'chrome-headless-shell-linux64/chrome-headless-shell'));
  }
  candidates.push('/usr/local/bin/chromium-browser', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/snap/bin/chromium');
  return candidates.find(p => fs.existsSync(p));
}

function waitForHttp(url, timeoutMs) {
  const t0 = Date.now();
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const r = await fetch(url);
        if (r.ok) return resolve();
      } catch {}
      if (Date.now() - t0 > timeoutMs) return reject(new Error(`server not up: ${url}`));
      setTimeout(tick, 500);
    };
    tick();
  });
}

function listMp4s(dir) {
  const out = [];
  if (!fs.existsSync(dir)) return out;
  for (const e of fs.readdirSync(dir, {withFileTypes: true, recursive: true})) {
    if (e.isFile() && e.name.endsWith('.mp4')) out.push(path.join(e.parentPath, e.name));
  }
  return out;
}

function probeDuration(file) {
  return new Promise(resolve => {
    execFile(
      'ffprobe',
      ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file],
      (err, stdout) => {
        const d = parseFloat(String(stdout).trim());
        resolve(!err && Number.isFinite(d) && d > 0 ? d : null);
      },
    );
  });
}

const exe = findChromium();
if (!exe) {
  console.error('FAIL: no Chromium found (set MC_CHROMIUM)');
  process.exit(2);
}
console.log(`chromium: ${exe}`);
console.log(`project:  ${projectDir}`);

const t0 = Date.now();
const before = new Set(listMp4s(path.join(projectDir, 'output')));

// --- start vite directly (no npx wrapper: kill must reach the server) ---
const viteBin = path.join(projectDir, 'node_modules/vite/bin/vite.js');
if (!fs.existsSync(viteBin)) {
  console.error(`FAIL: ${viteBin} missing — run npm install in the project first`);
  process.exit(2);
}
const logFd = fs.openSync(path.join(projectDir, 'vite-render.log'), 'w');
let server = null;
let port = basePort;
for (let attempt = 0; attempt < 5 && !server; attempt++) {
  const p = basePort + attempt;
  const child = spawn(
    process.execPath,
    [viteBin, '--port', String(p), '--strictPort', '--host', '127.0.0.1'],
    {cwd: projectDir, stdio: ['ignore', logFd, logFd], detached: true},
  );
  try {
    await waitForHttp(`http://127.0.0.1:${p}/`, 20000);
    server = child;
    port = p;
  } catch {
    try { process.kill(-child.pid, 'SIGKILL'); } catch { child.kill('SIGKILL'); }
  }
}
if (!server) {
  console.error('FAIL: vite did not start (see vite-render.log)');
  process.exit(2);
}
console.log(`vite:     http://127.0.0.1:${port}/ (log: vite-render.log)`);

let browser;
try {
  browser = await chromium.launch({
    executablePath: exe,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage({viewport: {width: 1600, height: 1000}});
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(`http://127.0.0.1:${port}/`, {waitUntil: 'networkidle', timeout: 60000});
  await page.getByText('VIDEO SETTINGS', {exact: false}).first().waitFor({timeout: 60000});
  // the exporter is a native <select> in the Rendering settings
  const exporterSelect = page.locator('select:has(option:text-is("Video (FFmpeg)"))');
  await exporterSelect.selectOption({label: 'Video (FFmpeg)'});
  console.log('exporter:', await exporterSelect.inputValue(), '(1 = Video (FFmpeg))');
  const renderBtn = page.getByRole('button', {name: 'Render'}).first();
  await renderBtn.waitFor({timeout: 30000});
  const clickAt = Date.now();
  console.log('clicking Render…');
  await renderBtn.click();

  const outDir = path.join(projectDir, 'output');
  const deadline = Date.now() + timeoutS * 1000;
  let lastSize = -1;
  let stable = 0;
  let found = null;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 1000));
    const fresh = listMp4s(outDir).filter(f => !before.has(f));
    if (!fresh.length) continue;
    const f = fresh[0];
    const size = fs.statSync(f).size;
    if (size === lastSize) stable++;
    else {
      stable = 0;
      lastSize = size;
    }
    if (size >= 10240 && stable >= 5 && Date.now() - clickAt > 5000) {
      const dur = await probeDuration(f);
      if (dur) {
        found = {file: f, size, duration: dur};
        break;
      }
      stable = 0; // not finalized yet (no moov); keep waiting
    }
  }
  if (!found) {
    console.error(`FAIL: no finalized .mp4 in ${outDir} within ${timeoutS}s; pageerrors=${JSON.stringify(errors)}`);
    process.exitCode = 1;
  } else {
    const secs = ((Date.now() - t0) / 1000).toFixed(1);
    console.log(
      `RENDER OK: ${found.file} (${found.size} bytes, ${found.duration.toFixed(2)}s, wall ${secs}s incl. server+browser startup)`,
    );
  }
} finally {
  if (browser) await browser.close().catch(() => {});
  try { process.kill(-server.pid, 'SIGTERM'); } catch { server.kill('SIGTERM'); }
  fs.closeSync(logFd);
}
