from __future__ import annotations

import os
import subprocess
import json
import hashlib
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import Capability, CapabilityResult, register
from hevi.quality.kids_gate import kids_gate_workflow


VALID_OBJECTS = {"windmill", "waterwheel", "soap_pump", "clock_gear"}


def validate_anatomy_params(params: dict[str, Any]) -> dict[str, Any]:
    obj = params.get("object", "windmill")
    if obj not in VALID_OBJECTS:
        raise ValueError(f"Invalid anatomy object: {obj}. Must be one of {VALID_OBJECTS}")
    
    duration = float(params.get("duration", 5.0))
    if duration < 2.0 or duration > 15.0:
        raise ValueError(f"Duration {duration} out of bounds [2.0, 15.0]")

    return {
        "object": obj,
        "duration": duration,
        "seed": int(params.get("seed", 42)),
    }


def render_anatomy_explainer(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    validated = validate_anatomy_params({**params, "duration": duration, "seed": seed})
    obj_name = validated["object"]

    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"anatomy_{obj_name}_{aspect.replace(':', '_')}.html"
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    mp4_path = out_dir / f"anatomy_{obj_name}_{aspect.replace(':', '_')}.mp4"

    figures_mjs_path = Path(__file__).parent / "figures.mjs"
    third_party_scripts = Path(__file__).parents[3] / "third_party" / "anatomy" / "scripts"

    # 1. Build HTML via Node script
    builder_script = out_dir / "build_one.mjs"
    builder_script.write_text(f"""
import {{ generateFigureHtml }} from "{figures_mjs_path.resolve()}";
import {{ existsSync }} from "node:fs";
generateFigureHtml("{obj_name}", "{aspect}", {seed}, "{html_path.resolve()}");
""", encoding="utf-8")

    res_build = subprocess.run(["node", str(builder_script)], capture_output=True, text=True)
    if res_build.returncode != 0:
        raise RuntimeError(f"Builder failed: {res_build.stderr}\nstdout: {res_build.stdout}")

    html_content = html_path.read_text(encoding="utf-8")

    # 2. Render frames using Headless Chrome via Node CDP script with document.write
    fps = 30
    total_frames = int(duration * fps)
    renderer_script = out_dir / "render_frames.mjs"
    renderer_script.write_text(f"""
import {{ chromePort }} from "{third_party_scripts / 'chrome-port.mjs'}";
import {{ spawn }} from "node:child_process";
import {{ mkdtempSync, writeFileSync }} from "node:fs";
import {{ tmpdir }} from "node:os";
import {{ join, resolve }} from "node:path";

async function main() {{
  const binary = process.env.CHROME_PATH || "/snap/bin/chromium";
  const profile = mkdtempSync(join(tmpdir(), "iso-render-"));
  const chrome = spawn(binary, [
    "--headless=new", "--no-sandbox", "--remote-debugging-port=0",
    `--user-data-dir=${{profile}}`, "--no-first-run", "--no-default-browser-check",
    "--hide-scrollbars", "--enable-unsafe-swiftshader", "about:blank"
  ]);
  const port = await chromePort(chrome, profile);
  const target = await (await fetch(`http://127.0.0.1:${{port}}/json/new?about:blank`, {{ method: "PUT" }})).json();
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();

  socket.onmessage = (msg) => {{
    const data = JSON.parse(msg.data);
    if (data.id && pending.has(data.id)) {{
      pending.get(data.id)(data);
      pending.delete(data.id);
    }}
  }};

  const send = (method, params = {{}}) => new Promise((resolve) => {{
    const call = ++id;
    pending.set(call, resolve);
    socket.send(JSON.stringify({{ id: call, method, params }}));
  }});

  await new Promise((r) => socket.onopen = r);
  await send("Runtime.enable");
  await send("Page.enable");
  const isPortrait = "{aspect}" === "9:16";
  const width = isPortrait ? 1080 : 1920;
  const height = isPortrait ? 1920 : 1080;
  await send("Emulation.setDeviceMetricsOverride", {{ width, height, deviceScaleFactor: 1, mobile: isPortrait }});
  
  await send("Page.navigate", {{ url: "about:blank" }});

  // Inject HTML via document.write
  const htmlContent = {json.dumps(html_content)};
  await send("Runtime.evaluate", {{ expression: `
    document.open();
    document.write(` + JSON.stringify(htmlContent) + `);
    document.close();
  `}});

  // Poll readyState
  for (let attempt = 0; attempt < 50; attempt++) {{
    const res = await send("Runtime.evaluate", {{ expression: "document.readyState", returnByValue: true }});
    if (res.result && res.result.result && res.result.result.value === "complete") break;
    await new Promise((r) => setTimeout(r, 100));
  }}
  await new Promise((r) => setTimeout(r, 800)); // settle paint

  const totalFrames = {total_frames};
  for (let i = 0; i < totalFrames; i++) {{
    const t = i / (totalFrames - 1 || 1);
    await send("Runtime.evaluate", {{ expression: `window.__heviSeek(${{t}})` }});
    await send("Runtime.evaluate", {{ expression: `new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))`, awaitPromise: true }});
    const shot = await send("Page.captureScreenshot", {{ format: "png", captureBeyondViewport: true }});
    if (shot.error) throw new Error("Shot error: " + JSON.stringify(shot.error));
    const framePath = join("{frames_dir.resolve()}", String(i).padStart(4, "0") + ".png");
    writeFileSync(framePath, Buffer.from(shot.result.data, "base64"));
  }}
  socket.close();
  chrome.kill("SIGKILL");
}}
main().catch(err => {{ console.error(err); process.exit(1); }});
""", encoding="utf-8")

    env = {**os.environ, "CHROME_PATH": "/snap/bin/chromium"}
    res_render = subprocess.run(["node", str(renderer_script)], capture_output=True, text=True, env=env)
    if res_render.returncode != 0:
        raise RuntimeError(f"Renderer failed: {res_render.stderr}\nstdout: {res_render.stdout}")

    # 3. Assemble MP4 via ffmpeg
    ffmpeg_bin = "/home/soffy/.local/bin/ffmpeg" if os.path.exists("/home/soffy/.local/bin/ffmpeg") else "ffmpeg"
    cmd_ff = [
        ffmpeg_bin, "-y", "-framerate", "30",
        "-i", str(frames_dir / "%04d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
        str(mp4_path)
    ]
    res_ff = subprocess.run(cmd_ff, capture_output=True, text=True)
    if res_ff.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {res_ff.stderr}")

    # Compute sha256
    sha256 = hashlib.sha256(mp4_path.read_bytes()).hexdigest()

    # 4. Run kids_gate
    srt_path = out_dir / "sub.srt"
    srt_path.write_text(f"1\n00:00:00,000 --> 00:00:{int(duration):02d},000\n{obj_name}\n", encoding="utf-8")
    meta_path = out_dir / "meta.json"
    meta_path.write_text(json.dumps({"subtitle_font_px": 64}), encoding="utf-8")

    qa_report = kids_gate_workflow(mp4_path, srt_path=srt_path, metadata_path=meta_path)
    if not qa_report.get("passed", False):
        raise RuntimeError(f"Kids gate failed for anatomy_explainer: {qa_report}")

    return CapabilityResult(
        mp4=str(mp4_path),
        duration_s=duration,
        sha256=sha256,
        qa=qa_report
    )


register(Capability(
    name="anatomy_explainer",
    kind="shot",
    aspects=["16:9", "9:16"],
    params_schema={
        "type": "object",
        "properties": {
            "object": {"type": "string", "enum": list(VALID_OBJECTS)},
            "duration": {"type": "number", "minimum": 2.0, "maximum": 15.0},
            "seed": {"type": "integer"}
        },
        "required": ["object"]
    },
    cpu_cost_hint=1.5,
    render=render_anatomy_explainer,
    description="幼儿科普机械科普动画（动态等距小机器）",
    line="anatomy"
))
