from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from hevi.capabilities.anatomy_explainer import craft
from hevi.capabilities.anatomy_explainer.chrome import chrome_env
from hevi.capabilities.anatomy_explainer.verify import (
    AnatomyVerifyError,
    VerifyReport,
    build_turning_page,
    capture_still,
    check_fidelity,
    check_lines,
    check_turn,
    contact_sheet,
    image_stats,
)
from hevi.capabilities.registry import Capability, CapabilityResult, register
from hevi.quality.kids_gate import kids_gate_workflow


VALID_OBJECTS = {"windmill", "waterwheel", "soap_pump", "clock_gear"}
VALID_MODES = {"2d", "3d"}
#: Objects that have a real turning-group build (3D mode).
VALID_TURN_OBJECTS = {"windmill"}
FPS = 30


def validate_anatomy_params(params: dict[str, Any]) -> dict[str, Any]:
    mode = str(params.get("mode", "2d"))
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid anatomy mode: {mode}. Must be one of {sorted(VALID_MODES)}")

    obj = params.get("object", "windmill")
    allowed = VALID_TURN_OBJECTS if mode == "3d" else VALID_OBJECTS
    if obj not in allowed:
        raise ValueError(
            f"Invalid anatomy object for mode={mode}: {obj}. Must be one of {sorted(allowed)}"
        )

    duration = float(params.get("duration", 5.0))
    if duration < 2.0 or duration > 15.0:
        raise ValueError(f"Duration {duration} out of bounds [2.0, 15.0]")

    validated = {
        "object": obj,
        "mode": mode,
        "duration": duration,
        "seed": int(params.get("seed", 42)),
        "self_check": bool(params.get("self_check", True)),
    }
    craft.validate_generation_constraints(validated)
    return validated


def run_with_retry(cmd: list[str], *, retries: int = 3, delay: float = 1.0, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    for attempt in range(retries):
        res = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
        if res.returncode == 0:
            return res
        if attempt < retries - 1:
            time.sleep(delay)
    return res


def ffmpeg_bin() -> str:
    candidate = os.environ.get("HEVI_FFMPEG", "/home/soffy/.local/bin/ffmpeg")
    return candidate if os.path.exists(candidate) else "ffmpeg"


def ffprobe_bin() -> str:
    candidate = os.environ.get("HEVI_FFPROBE", "/home/soffy/.local/bin/ffprobe")
    return candidate if os.path.exists(candidate) else "ffprobe"


def encode_mp4(frames_dir: Path, mp4_path: Path, *, fps: int = FPS, pattern: str = "%04d.png") -> Path:
    # libx264 needs even dimensions; the 3D clips come in at card sizes.
    cmd = [
        ffmpeg_bin(), "-y", "-framerate", str(fps),
        "-i", str(frames_dir / pattern),
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
        str(mp4_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {res.stderr[-4000:]}")
    return mp4_path


def probe_video(mp4_path: Path) -> dict[str, Any]:
    res = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(mp4_path)],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {mp4_path}: {res.stderr[-2000:]}")
    data = json.loads(res.stdout)
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "duration_s": float(data.get("format", {}).get("duration", 0.0)),
        "width": int(stream.get("width", 0)),
        "height": int(stream.get("height", 0)),
        "codec": stream.get("codec_name"),
        "fps": stream.get("avg_frame_rate"),
    }


def _kids_gate(mp4_path: Path, out_dir: Path, duration: float, label: str) -> dict[str, Any]:
    srt_path = out_dir / "sub.srt"
    srt_path.write_text(f"1\n00:00:00,000 --> 00:00:{int(duration):02d},000\n{label}\n", encoding="utf-8")
    meta_path = out_dir / "meta.json"
    meta_path.write_text(json.dumps({"subtitle_font_px": 64}), encoding="utf-8")
    qa_report = kids_gate_workflow(mp4_path, srt_path=srt_path, metadata_path=meta_path)
    if not qa_report.get("passed", False):
        raise RuntimeError(f"Kids gate failed for anatomy_explainer: {qa_report}")
    return qa_report


def _render_2d(
    params: dict[str, Any],
    out_dir: Path,
    *,
    obj_name: str,
    duration: float,
    aspect: str,
    seed: int,
) -> tuple[Path, Path, VerifyReport]:
    """The original flat-figure path: kit figure -> audits -> frames -> mp4."""
    html_path = out_dir / f"anatomy_{obj_name}_{aspect.replace(':', '_')}.html"
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    mp4_path = out_dir / f"anatomy_{obj_name}_{aspect.replace(':', '_')}.mp4"
    report = VerifyReport()

    figures_mjs_path = Path(__file__).parent / "figures.mjs"
    third_party_scripts = Path(__file__).parents[3] / "third_party" / "anatomy" / "scripts"

    builder_script = out_dir / "build_one.mjs"
    builder_script.write_text(f"""
import {{ generateFigureHtml }} from "{figures_mjs_path.resolve()}";
generateFigureHtml("{obj_name}", "{aspect}", {seed}, "{html_path.resolve()}");
""", encoding="utf-8")

    res_build = run_with_retry(["node", str(builder_script)])
    if res_build.returncode != 0:
        raise RuntimeError(f"Builder failed: {res_build.stderr}\nstdout: {res_build.stdout}")

    html_content = html_path.read_text(encoding="utf-8")

    # Kit geometry audit (no clipping, every endpoint supported, draw order).
    audit_script = Path(__file__).parent / "audit_figure.mjs"
    audit_json = out_dir / "anatomy_audit.json"
    audit_env = {**os.environ}
    if params.get("inject_audit_failure") or os.environ.get("HEVI_ANATOMY_AUDIT_INJECT"):
        audit_env["HEVI_ANATOMY_AUDIT_INJECT"] = "clip"
    res_audit = run_with_retry(["node", str(audit_script), obj_name, aspect, str(audit_json)], env=audit_env)
    if res_audit.returncode != 0:
        raise RuntimeError(f"Anatomy geometry audit failed: {res_audit.stderr}\nstdout: {res_audit.stdout}")
    report.add("geometry_audit", report=res_audit.stdout.strip().splitlines()[-1] if res_audit.stdout.strip() else "passed")

    # Render frames (headless Chromium, SwiftShader) by seeking window.__heviSeek.
    fps = FPS
    total_frames = int(duration * fps)
    renderer_script = out_dir / "render_frames.mjs"
    renderer_script.write_text(f"""
import {{ chromePort }} from "{third_party_scripts / 'chrome-port.mjs'}";
import {{ spawn }} from "node:child_process";
import {{ mkdtempSync, writeFileSync }} from "node:fs";
import {{ tmpdir }} from "node:os";
import {{ join }} from "node:path";

async function main() {{
  const binary = process.env.CHROME_PATH;
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
  const htmlContent = {json.dumps(html_content)};
  await send("Runtime.evaluate", {{ expression: `
    document.open();
    document.write(` + JSON.stringify(htmlContent) + `);
    document.close();
  `}});
  for (let attempt = 0; attempt < 50; attempt++) {{
    const res = await send("Runtime.evaluate", {{ expression: "document.readyState", returnByValue: true }});
    if (res.result && res.result.result && res.result.result.value === "complete") break;
    await new Promise((r) => setTimeout(r, 100));
  }}
  await new Promise((r) => setTimeout(r, 800));
  const total_frames = {total_frames};
  for (let i = 0; i < total_frames; i++) {{
    const t = i / 30.0;
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

    res_render = run_with_retry(["node", str(renderer_script)], env=chrome_env())
    if res_render.returncode != 0:
        raise RuntimeError(f"Renderer failed: {res_render.stderr}\nstdout: {res_render.stdout}")
    frames = sorted(frames_dir.glob("*.png"))
    if len(frames) != total_frames:
        raise RuntimeError(f"Renderer wrote {len(frames)} frames, expected {total_frames}")
    report.add("frames", count=len(frames), fps=fps, width=1920 if aspect != "9:16" else 1080)
    return html_path, mp4_path, report


def _render_3d(
    out_dir: Path,
    *,
    aspect: str,
    duration: float,
) -> tuple[Path, Path, VerifyReport]:
    """The turning (3D) path: turn-build figure -> kit checks -> seeked frames."""
    report = VerifyReport()
    html_path, build_stdout = build_turning_page(
        out_dir,
        aspect=aspect,
        theme="light",
        verify=True,
        audit=False,
    )
    report.add("build", report=build_stdout.strip().splitlines()[-1])

    fidelity = check_fidelity(Path(__file__).parent / "turn_windmill.mjs", angles="7,97,187")
    report.add("kit_fidelity", report=fidelity["report"])

    turn = check_turn(html_path, order=True, pops=False, out_dir=out_dir / "turn-check")
    report.add("turn_check", report=turn["report"])

    still = capture_still(html_path, out_dir / "keyframe_3d.png")
    report.add("capture", **still)

    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    total_frames = int(duration * FPS)
    # One full turn per `duration` seconds: 360/duration degrees per second.
    degrees_per_second = 360.0 / duration
    cmd = [
        "node",
        str(Path(__file__).parent / "frames3d.mjs"),
        str(html_path),
        str(frames_dir),
        "--fps", str(FPS),
        "--seconds", str(duration),
        "--degrees-per-second", str(degrees_per_second),
        "--width", "1280",
        "--height", "720",
        "--scale", "1",
    ]
    res = run_with_retry(cmd, env=chrome_env())
    if res.returncode != 0:
        raise AnatomyVerifyError(f"3D frame recorder failed:\n{res.stderr[-4000:]}")
    try:
        meta = json.loads(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise AnatomyVerifyError(f"3D frame recorder printed no summary: {res.stdout[-2000:]!r}") from exc
    frames = sorted(frames_dir.glob("*.png"))
    if len(frames) != total_frames:
        raise AnatomyVerifyError(f"3D recorder wrote {len(frames)} frames, expected {total_frames}")
    report.add("frames", count=len(frames), fps=FPS, angles=meta.get("angles"), clip=meta.get("clip"))

    # Prove the rotor actually turned: the first and mid frames must differ.
    first = image_stats(frames[0])
    mid = image_stats(frames[len(frames) // 2])
    report.add("still_0", ink_ratio=first["ink_ratio"], colours=first["colours"])
    report.add("still_mid", ink_ratio=mid["ink_ratio"], colours=mid["colours"])
    return html_path, out_dir / f"anatomy_turning_windmill_{aspect.replace(':', 'x')}.mp4", report


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
    mode = validated["mode"]

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_base = Path(os.environ.get("TMPDIR", tempfile.gettempdir()))
    tmp_base.mkdir(parents=True, exist_ok=True)

    if mode == "3d":
        html_path, mp4_path, report = _render_3d(out_dir, aspect=aspect, duration=duration)
    else:
        html_path, mp4_path, report = _render_2d(
            params, out_dir, obj_name=obj_name, duration=duration, aspect=aspect, seed=seed
        )

    # Post-render self-checks: capture.mjs still, drive.mjs contact sheet,
    # lines.mjs floating-line check.  Any failure raises with the script named.
    if validated["self_check"]:
        still = capture_still(html_path, out_dir / "selfcheck_capture.png")
        report.add("selfcheck_capture", **still)
        sheet = contact_sheet(html_path, out_dir / "selfcheck_sheet.png", every=200, count=6)
        report.add("selfcheck_sheet", **sheet)
        lines = check_lines(html_path, out_png=out_dir / "selfcheck_lines.png")
        report.add("selfcheck_lines", **lines)
        if mode == "2d":
            # The 2D path also runs the upstream check as a gate on the built page.
            check_lines(html_path)

    encode_mp4(out_dir / "frames", mp4_path)
    probe = probe_video(mp4_path)
    if probe["duration_s"] + 0.05 < duration:
        raise RuntimeError(
            f"encoded video is {probe['duration_s']:.3f}s, shorter than the requested {duration:.3f}s"
        )
    report.add("video", **probe)

    qa_report = _kids_gate(mp4_path, out_dir, duration, obj_name)
    report.add("kids_gate", passed=qa_report.get("passed"), verdict=qa_report.get("verdict"))

    craft_report = craft.measure_figure(html_path, frames_dir=out_dir / "frames", mode=mode)
    craft.write_report(out_dir / "anatomy_craft.json", craft_report)
    craft.enforce(craft_report)

    report_path = report.write(out_dir / "anatomy_verify.json")
    sha256 = hashlib.sha256(mp4_path.read_bytes()).hexdigest()

    qa = {
        **qa_report,
        "mode": mode,
        "html": str(html_path),
        "verify_report": str(report_path),
        "craft_report": str(out_dir / "anatomy_craft.json"),
        "probe": probe,
        "verify": report.as_dict()["checks"],
    }
    return CapabilityResult(
        mp4=str(mp4_path),
        duration_s=duration,
        sha256=sha256,
        qa=qa,
    )


register(Capability(
    name="anatomy_explainer",
    kind="shot",
    aspects=["16:9", "9:16"],
    params_schema={
        "type": "object",
        "properties": {
            "object": {"type": "string", "enum": sorted(VALID_OBJECTS | VALID_TURN_OBJECTS)},
            "mode": {"type": "string", "enum": sorted(VALID_MODES), "default": "2d"},
            "duration": {"type": "number", "minimum": 2.0, "maximum": 15.0},
            "seed": {"type": "integer"},
            "self_check": {"type": "boolean", "default": True},
        },
        "required": ["object"],
    },
    cpu_cost_hint=1.5,
    render=render_anatomy_explainer,
    description="幼儿科普机械科普动画（动态等距小机器；mode=3d 为可转动的三维转台）",
    line="anatomy"
))
