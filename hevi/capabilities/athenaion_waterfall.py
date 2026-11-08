"""B4 waterfall tracing, minimal version (clean-room, method only).

Method source: Athenaion's waterfall tracing as described in
``hevi-vs-athenaion.md`` -- trace a stream down the heightfield,
build a ribbon carrying an arrival time tau per vertex, and shade
it with a flowing-noise shader in (across, t - tau) space; see
ATHENAION_ATTRIBUTION.md. The tracer, the ribbon builder and the
shader here are newly written. The heightfield is the shared
analytic field from ``athenaion_world.height_at``; the one
waterfall starts at a caller-chosen lip point on the western
plateau edge and follows steepest descent to the plain.

Continuity is measured, not claimed: the trace step length is
bounded, tau strictly increases along the ribbon, and the
rendered frames change over time (flowing) while the ribbon
geometry stays fixed. A trace that cannot descend, or a ribbon
whose tau does not increase, fails instead of rendering a
static sheet.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hevi.capabilities.athenaion_browser import capture_actions, page_html
from hevi.capabilities.pure_helpers import (
    height_at,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False


def trace_stream(
    lip: tuple[float, float],
    *,
    step: float = 0.5,
    max_steps: int = 240,
    flow_speed: float = 3.0,
    eps: float = 0.25,
) -> dict[str, Any]:
    """Steepest-descent trace from ``lip`` over the heightfield."""
    if not _is_num(step) or float(step) <= 0:
        raise CapabilityError("video.athenaion_waterfall: step must be > 0")
    if not _is_num(flow_speed) or float(flow_speed) <= 0:
        raise CapabilityError("video.athenaion_waterfall: flow_speed must be > 0")
    x, z = float(lip[0]), float(lip[1])
    points: list[dict[str, float]] = []
    total_length = 0.0
    for _ in range(max_steps):
        h = height_at(x, z)
        gx = (height_at(x + eps, z) - height_at(x - eps, z)) / (2.0 * eps)
        gz = (height_at(x, z + eps) - height_at(x, z - eps)) / (2.0 * eps)
        slope = math.hypot(gx, gz)
        points.append({"x": x, "z": z, "h": h, "slope": slope})
        # Stop on flat ground: below this the stream has reached the
        # plain. A higher floor than 0.02 avoids ping-ponging in a
        # shallow hollow (gradient sign flips each step there).
        if slope < 0.06:
            break
        nx, nz = x - gx / slope * float(step), z - gz / slope * float(step)
        # Cycle guard: a step that returns near the point two steps
        # back is oscillating in a hollow, not descending.
        if len(points) >= 2:
            px, pz = points[-2]["x"], points[-2]["z"]
            if math.hypot(nx - px, nz - pz) < 0.05:
                break
        total_length += math.hypot(nx - x, nz - z)
        x, z = nx, nz
        if not (-80.0 <= x <= 80.0 and -80.0 <= z <= 80.0):
            break
    if len(points) < 4:
        raise CapabilityError(
            "video.athenaion_waterfall: trace produced too few points; "
            "the lip point does not descend"
        )
    drop = points[0]["h"] - points[-1]["h"]
    if drop < 1.0:
        raise CapabilityError(
            f"video.athenaion_waterfall: trace drop {drop:.2f}m is too small for a waterfall"
        )
    # Arrival time tau: cumulative length / flow speed, strictly increasing.
    tau = 0.0
    prev = points[0]
    for point in points:
        tau += math.hypot(point["x"] - prev["x"], point["z"] - prev["z"]) / float(flow_speed)
        point["tau"] = tau
        point["length"] = total_length
        prev = point
    steps = [
        math.hypot(points[i + 1]["x"] - points[i]["x"], points[i + 1]["z"] - points[i]["z"])
        for i in range(len(points) - 1)
    ]
    return {
        "lip": [float(lip[0]), float(lip[1])],
        "points": points,
        "point_count": len(points),
        "total_length_m": round(total_length, 3),
        "drop_m": round(drop, 3),
        "max_step_m": round(max(steps), 3),
        "tau_end_s": round(points[-1]["tau"], 3),
        "flow_speed": float(flow_speed),
    }


def build_ribbon(trace: dict[str, Any], *, half_width: float = 0.9) -> dict[str, Any]:
    """Ribbon mesh along the trace, vertices carrying tau and across."""
    points = trace["points"]
    positions: list[list[float]] = []
    taus: list[float] = []
    across: list[float] = []
    indices: list[int] = []
    for i, point in enumerate(points):
        if i < len(points) - 1:
            tx = points[i + 1]["x"] - point["x"]
            tz = points[i + 1]["z"] - point["z"]
        else:
            tx = point["x"] - points[i - 1]["x"]
            tz = point["z"] - points[i - 1]["z"]
        length = math.hypot(tx, tz) or 1.0
        px, pz = -tz / length, tx / length
        for side in (-1.0, 1.0):
            positions.append([
                point["x"] + px * half_width * side,
                point["h"] - 0.12,
                point["z"] + pz * half_width * side,
            ])
            taus.append(point["tau"])
            across.append(side)
        if i < len(points) - 1:
            base = i * 2
            indices.extend([base, base + 1, base + 2, base + 1, base + 3, base + 2])
    taus_list = [p["tau"] for p in points]
    strictly_increasing = all(b > a for a, b in zip(taus_list, taus_list[1:]))
    return {
        "positions": positions,
        "taus": taus,
        "across": across,
        "indices": indices,
        "triangles": len(indices) // 3,
        "tau_strictly_increasing": strictly_increasing,
    }


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def build_waterfall_html(
    *,
    width: int,
    height: int,
    fps: int,
    duration_s: float,
    ribbon: dict[str, Any],
    trace: dict[str, Any],
    seed: int = 0,
) -> str:
    total = max(1, round(duration_s * fps))
    lip = trace["lip"]
    js = f"""
import * as THREE from 'three';
const W = {width}, H = {height}, FPS = {fps}, TOTAL = {total}, DUR = {duration_s!r};
const RIBBON = {json.dumps(ribbon)};
const renderer = new THREE.WebGLRenderer({{ antialias: false, preserveDrawingBuffer: true }});
renderer.setPixelRatio(1);
renderer.setSize(W, H, false);
document.getElementById('stage').appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x2a3242);
const camera = new THREE.PerspectiveCamera(42, W / H, 0.1, 300);
const sun = new THREE.DirectionalLight(0xffe8c0, 2.2);
sun.position.set(20, 34, 18);
scene.add(sun);
scene.add(new THREE.HemisphereLight(0xbfd4e8, 0x6a5a44, 0.7));
// Cliff backdrop: a wall behind the lip, thin in the flow
// direction so it never fills the frame from the side view.
const cliff = new THREE.Mesh(
  new THREE.BoxGeometry(3, 12, 12),
  new THREE.MeshStandardMaterial({{ color: 0x8d8578, roughness: 0.95 }})
);
cliff.position.set({lip[0] - 1.5!r}, 4.0, {lip[1]!r});
scene.add(cliff);
const ground = new THREE.Mesh(new THREE.PlaneGeometry(80, 80), new THREE.MeshStandardMaterial({{ color: 0x6a7a4a, roughness: 1.0 }}));
ground.rotation.x = -Math.PI / 2;
ground.position.y = 0.4;
scene.add(ground);
const pool = new THREE.Mesh(
  new THREE.CircleGeometry(5, 32),
  new THREE.MeshStandardMaterial({{ color: 0x3f7fa8, roughness: 0.15, transparent: true, opacity: 0.8 }})
);
pool.rotation.x = -Math.PI / 2;
const last = RIBBON.positions[RIBBON.positions.length - 1];
pool.position.set(last[0], 0.55, last[2]);
scene.add(pool);
// Ribbon with (across, t - tau) flowing stripe shader.
const geo = new THREE.BufferGeometry();
geo.setAttribute('position', new THREE.Float32BufferAttribute(RIBBON.positions.flat(), 3));
geo.setAttribute('aTau', new THREE.Float32BufferAttribute(RIBBON.taus, 1));
geo.setAttribute('aAcross', new THREE.Float32BufferAttribute(RIBBON.across, 1));
geo.setIndex(RIBBON.indices);
const uniforms = {{ uTime: {{ value: 0.0 }} }};
const ribbonMat = new THREE.ShaderMaterial({{
  uniforms: uniforms, transparent: true, side: THREE.DoubleSide, depthWrite: false,
  vertexShader: 'attribute float aTau; attribute float aAcross; varying float vTau; varying float vAcross; void main() {{ vTau = aTau; vAcross = aAcross; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }}',
  fragmentShader: 'varying float vTau; varying float vAcross; uniform float uTime; float hash(float n) {{ return fract(sin(n) * 43758.5453123); }} void main() {{ float flow = uTime - vTau; float stripes = 0.5 + 0.5 * sin((vAcross * 2.0 + flow * 2.4) * 6.2831); float n = hash(floor(vAcross * 7.0) * 13.0 + floor(flow * 3.0) * 7.0); vec3 col = mix(vec3(0.85, 0.93, 1.0), vec3(0.35, 0.6, 0.85), stripes * 0.7); float alpha = 0.55 + 0.35 * stripes + 0.1 * n; gl_FragColor = vec4(col, alpha); }}'
}});
const ribbon = new THREE.Mesh(geo, ribbonMat);
scene.add(ribbon);
function update(t) {{
  uniforms.uTime.value = t;
  const first = RIBBON.positions[0];
  // Side view: east of the fall, looking back west along the flow
  // so the ribbon runs across the frame against the cliff face.
  camera.position.set(first[0] + 20, first[1] + 3, first[2] + 10);
  camera.lookAt((first[0] + last[0]) / 2, (first[1] + last[1]) / 2, (first[2] + last[2]) / 2);
}}
window.__athenaionStats = function () {{
  return {{ calls: renderer.info.render.calls, triangles: renderer.info.render.triangles }};
}};
window.__hfSettledFrame = -1;
window.__hf = {{
  getDurationFrames() {{ return TOTAL; }},
  seekFrame(frame) {{
    if (!Number.isInteger(frame) || frame < 0 || frame >= TOTAL) throw new RangeError('frame out of range: ' + frame);
    const t = Math.floor(frame) / FPS;
    update(t);
    renderer.render(scene, camera);
    window.__hfSettledFrame = frame;
    return {{ frame: frame, t: t, settled: true }};
  }},
  destroy() {{ renderer.dispose(); }}
}};
update(0);
renderer.render(scene, camera);
window.__hfReady = true;
"""
    return page_html(js)


def render_waterfall(
    *,
    out_dir: Path,
    width: int = 480,
    height: int = 270,
    fps: int = 10,
    duration_s: float = 5.0,
    lip: tuple[float, float] = (-14.0, 0.0),
    seed: int = 0,
    assemble_video: bool = True,
) -> dict[str, Any]:
    trace = trace_stream(lip)
    ribbon = build_ribbon(trace)
    if not ribbon["tau_strictly_increasing"]:
        raise CapabilityError("video.athenaion_waterfall: tau does not strictly increase along the ribbon")
    html = build_waterfall_html(width=width, height=height, fps=fps, duration_s=duration_s, ribbon=ribbon, trace=trace, seed=seed)
    total = max(1, round(duration_s * fps))
    actions = [
        {"name": f"frame_{frame:04d}", "evaluate": f"window.__hf.seekFrame({frame})",
         "settle": f"window.__hfSettledFrame === {frame}", "screenshot": True}
        for frame in range(total)
    ]
    result = capture_actions(html, actions, width=width, height=height)
    out_dir = Path(out_dir)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for shot_rec in result["shots"]:
        path = frames_dir / f"{shot_rec['name']}.png"
        path.write_bytes(shot_rec["png_bytes"])
        frames.append({"frame": int(shot_rec["name"].split("_")[1]), "sha256": shot_rec["sha256"], "bytes": shot_rec["bytes"], "settled": True, "file": path.name})
    hashes = [f["sha256"] for f in frames]
    flowing = len(set(hashes)) > 1
    video_path: str | None = None
    video_error: str | None = None
    if assemble_video:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            video_error = "ffmpeg not found; frames only"
        else:
            video_path = str(out_dir / "waterfall.mp4")
            cmd = [ffmpeg, "-y", "-framerate", str(fps), "-i", str(frames_dir / "frame_%04d.png"),
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", video_path]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if proc.returncode != 0 or not Path(video_path).is_file():
                video_error = f"ffmpeg failed: {proc.stderr[-300:]}"
                video_path = None
    return {
        "verdict": "pass" if flowing else "fail",
        "issues": [] if flowing else [{"code": "no_flow", "message": "all frames identical; the waterfall shader is not flowing"}],
        "trace": trace,
        "ribbon_triangles": ribbon["triangles"],
        "tau_strictly_increasing": ribbon["tau_strictly_increasing"],
        "frame_count": total,
        "fps": fps,
        "duration_s": float(duration_s),
        "frames": frames,
        "frames_flow": flowing,
        "distinct_frame_hashes": len(set(hashes)),
        "video_path": video_path,
        "video_error": video_error,
        "stats": result["stats"],
        "ready_ms": result["ready_ms"],
        "three_module": result["three_module"],
        "human_measured": False,
        "external_assets": [],
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lip = params.get("lip", [-14.0, 0.0])
    report = render_waterfall(
        out_dir=out_dir,
        width=int(params.get("width", 480)),
        height=int(params.get("height", 270)),
        fps=int(params.get("fps", 10)),
        duration_s=float(params.get("duration_s", 5.0)),
        lip=(float(lip[0]), float(lip[1])),
        seed=int(params.get("seed", seed)),
    )
    report_path = out_dir / "waterfall_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    first = out_dir / "frames" / "frame_0000.png"
    return CapabilityResult(
        png=str(first) if first.is_file() else None,
        duration_s=float(report["duration_s"]),
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"],
            "ok": report["verdict"] == "pass", "frames_flow": report["frames_flow"],
            "video_path": report["video_path"]},
    )


def register_athenaion_waterfall_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="video.athenaion_waterfall",
        kind="video",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "fps": {"type": "integer"},
                "duration_s": {"type": "number"},
                "lip": {"type": "array"},
                "seed": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        cpu_cost_hint=1.0,
        render=_render,
        has_media_output=True,
        description=(
            "B4 waterfall tracing, minimal version: steepest-descent "
            "trace over the shared heightfield, tau-carrying ribbon, "
            "flowing-noise shader, 5-second frame sequence with video "
            "assembly. Zero external assets. See ATHENAION_ATTRIBUTION.md."
        ),
        line="video",
    ))
    return ["video.athenaion_waterfall"]


register_athenaion_waterfall_capabilities_once()
