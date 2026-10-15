import { chromePort } from "../../../third_party/anatomy/scripts/chrome-port.mjs";
import { LINE_ENDS } from "../../../third_party/anatomy/scripts/line-ends.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

async function main() {
  const htmlPath = process.argv[2];
  if (!htmlPath) {
    console.error("Usage: node audit_lines.mjs <file.html>");
    process.exit(1);
  }
  const htmlContent = readFileSync(htmlPath, "utf-8");
  const binary = process.env.CHROME_PATH || "/snap/bin/chromium";
  const profile = mkdtempSync(join(tmpdir(), "iso-lines-"));
  const chrome = spawn(binary, [
    "--headless=new", "--no-sandbox", "--remote-debugging-port=0",
    `--user-data-dir=${profile}`, "--no-first-run", "--no-default-browser-check",
    "--hide-scrollbars", "--enable-unsafe-swiftshader", "about:blank"
  ]);
  const port = await chromePort(chrome, profile);
  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  socket.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.id && pending.has(data.id)) {
      pending.get(data.id)(data);
      pending.delete(data.id);
    }
  };
  const resCall = (method, params = {}) => new Promise((resolve) => {
    const call = ++id;
    pending.set(call, resolve);
    socket.send(JSON.stringify({ id: call, method, params }));
  });
  await new Promise((r) => socket.onopen = r);
  await resCall("Runtime.enable");
  await resCall("Page.enable");
  await resCall("Page.navigate", { url: "about:blank" });
  await resCall("Runtime.evaluate", { expression: `
    document.open();
    document.write(` + JSON.stringify(htmlContent) + `);
    document.close();
  `});
  await new Promise((r) => setTimeout(r, 600));
  const res = await resCall("Runtime.evaluate", {
    expression: `(${LINE_ENDS})({ tolerance: 1 })`,
    awaitPromise: true,
    returnByValue: true
  });
  socket.close();
  chrome.kill("SIGKILL");
  try { rmSync(profile, { recursive: true, force: true }); } catch {}
  if (res.result && res.result.result) {
    const data = res.result.result.value;
    console.log("Line ends check result:", data);
    if (data && data.problems && data.problems.length > 0) {
      console.error("Floating lines found:", data.problems);
      process.exit(1);
    }
  } else if (res.error || res.result?.exceptionDetails) {
    console.error("Line ends error:", res.error || res.result?.exceptionDetails);
    process.exit(1);
  }
}
main().catch(err => { console.error(err); process.exit(1); });
