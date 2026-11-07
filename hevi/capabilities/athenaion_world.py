"""B1 minimal Three.js world engine (clean-room, method only).

Method source: Athenaion's procedural-world discipline as
described in ``hevi-vs-athenaion.md`` (analytic heightfield,
procedural sky, seeded RNG, quality scaling, ``__hf`` settle
protocol); see ATHENAION_ATTRIBUTION.md. Every line of scene
code here is newly written, the heightfield formula is defined
in this module (Python mirror :func:`height_at` and the JS copy
in the page script use the same constants), and no Athenaion
asset, texture, or self-reported number is used. Quality is two
measured tiers only -- preview/high -- with triangle counts and
build times recorded from the real run, never asserted.

The engine renders through the vendored Three.js module already
in this repository (see ``athenaion_browser.resolve_three_module``)
in headless Chromium with SwiftShader. Frame time is integer
math (``t = floor(frame) / fps``); the page reads no wall clock
and no unseeded randomness at render time.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from hevi.capabilities.athenaion_browser import capture_actions, page_html
from hevi.capabilities.deterministic_render_gate import check_render_plan
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.frame_adapter_contract import check_adapter_plan
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# Analytic heightfield, shared by the Python mirror, the JS page,
# the waterfall tracer (B4) and the scatter planner (B5).
# West plateau (~10 m) falls to an eastern plain (~1 m); hills and
# one mound break the slope. Constants are this module's own.
HEIGHT_CONSTANTS = {
    "plateau_height": 9.0,
    "plateau_edge_x": -12.0,
    "plateau_softness": 3.5,
    "base": 1.0,
    "hill_amp1": 2.2,
    "hill_amp2": 1.1,
    "mound_amp": 3.0,
    "mound_x": 18.0,
    "mound_z": 10.0,
    "mound_sigma2": 180.0,
}


def height_at(x: float, z: float) -> float:
    """Analytic ground height in metres (Python mirror of the JS page)."""
    c = HEIGHT_CONSTANTS
    plateau = c["plateau_height"] / (1.0 + math.exp((x - c["plateau_edge_x"]) / c["plateau_softness"]))
    hills = (
        c["hill_amp1"] * math.sin(x * 0.09 + 0.7) * math.cos(z * 0.07 + 0.3)
        + c["hill_amp2"] * math.sin(x * 0.23) * math.sin(z * 0.19 + 1.3)
    )
    dx, dz = x - c["mound_x"], z - c["mound_z"]
    mound = c["mound_amp"] * math.exp(-(dx * dx + dz * dz) / c["mound_sigma2"])
    return c["base"] + plateau + hills + mound


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def build_world_plan(
    *,
    width: int,
    height: int,
    fps: int,
    duration_s: float,
    seed: int = 0,
    quality: str = "preview",
) -> dict[str, Any]:
    if quality not in ("preview", "high"):
        raise CapabilityError(f"video.athenaion_world_engine: quality must be preview/high, got {quality!r}")
    return {
        "adapter": {
            "protocol": "__hf",
            "methods": ["getDurationFrames", "seekFrame", "destroy"],
            "settle": {"mode": "confirmation", "max_wait_ms": 5000},
            "arbitrary_order": True,
        },
        "render": {
            "fps": fps,
            "width": width,
            "height": height,
            "locked_before_frame_0": True,
            "wall_clock_sources": [],
            "randomness": {"seeded": True, "seed": seed},
            "fetch_during_render": False,
            "atomic_capture": True,
            "encoder": {"chunk_order": "sequential", "hash_check": True},
        },
        "quality": quality,
        "duration_s": duration_s,
    }


def validate_world_plan(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise CapabilityError("video.athenaion_world_engine: plan must be a JSON object")
    adapter = check_adapter_plan({"adapter": plan.get("adapter")})
    render = check_render_plan(plan.get("render"))
    issues = list(adapter["issues"]) + list(render["issues"])
    if plan.get("quality") not in ("preview", "high"):
        issues.append({"code": "quality_invalid", "message": "quality must be preview/high"})
    return {"verdict": "fail" if issues else "pass", "adapter": adapter, "render": render, "issues": issues}


def normalise_look(look: Any) -> dict[str, Any]:
    """Look block: sun + grade only (see qa.look_shot_separation)."""
    if not isinstance(look, dict):
        raise CapabilityError("video.athenaion_world_engine: look must be a JSON object")
    sun = look.get("sun") if isinstance(look.get("sun"), dict) else {}
    elevation = sun.get("elevation_deg", look.get("sun_elevation_deg", 25.0))
    azimuth = sun.get("azimuth_deg", look.get("sun_azimuth_deg", 135.0))
    relative = sun.get("relative", look.get("sun_relative"))
    if not _is_num(elevation) or not _is_num(azimuth):
        raise CapabilityError("video.athenaion_world_engine: sun elevation/azimuth must be numbers")
    grade = look.get("grade") if isinstance(look.get("grade"), dict) else {}
    return {
        "sun_elevation_deg": float(elevation),
        "sun_azimuth_deg": float(azimuth),
        "sun_relative": relative,
        "sun_intensity": float(sun.get("intensity", 2.2)),
        "sun_color": str(sun.get("color_hex", look.get("sun_color_hex", "#ffe8c0"))),
        "exposure": float(grade.get("exposure", look.get("exposure", 1.0))),
        "saturation": float(grade.get("saturation", look.get("saturation", 1.0))),
        "fog_density": float(look.get("fog_density", 0.004)),
        "fog_color": str(look.get("fog_color", "#c8d4e0")),
        "sky_horizon": str(look.get("sky_horizon", "#d8c9a8")),
        "sky_zenith": str(look.get("sky_zenith", "#6fa3d8")),
    }


def normalise_shot(shot: Any) -> dict[str, Any]:
    if not isinstance(shot, dict):
        raise CapabilityError("video.athenaion_world_engine: shot must be a JSON object")
    position = shot.get("position")
    target = shot.get("target")
    if not (isinstance(position, list) and len(position) == 3 and all(_is_num(v) for v in position)):
        raise CapabilityError("video.athenaion_world_engine: shot.position must be [x, y, z] numbers")
    if not (isinstance(target, list) and len(target) == 3 and all(_is_num(v) for v in target)):
        raise CapabilityError("video.athenaion_world_engine: shot.target must be [x, y, z] numbers")
    fov = shot.get("fov", 40.0)
    if not _is_num(fov) or not 1.0 <= float(fov) <= 120.0:
        raise CapabilityError("video.athenaion_world_engine: shot.fov must be in [1, 120]")
    movement = str(shot.get("movement", "static"))
    if movement not in ("static", "orbit", "dolly", "pan"):
        raise CapabilityError(f"video.athenaion_world_engine: unsupported movement {movement!r}")
    return {
        "position": [float(v) for v in position],
        "target": [float(v) for v in target],
        "fov": float(fov),
        "movement": movement,
    }


def build_world_html(
    *,
    width: int,
    height: int,
    fps: int,
    duration_s: float,
    look: dict[str, Any],
    shot: dict[str, Any],
    quality: str = "preview",
    seed: int = 0,
) -> str:
    total = max(1, round(duration_s * fps))
    segments = 48 if quality == "preview" else 96
    js = f"""
import * as THREE from 'three';
const W = {width}, H = {height}, FPS = {fps}, TOTAL = {total}, DUR = {duration_s!r};
const LOOK = {json.dumps(look)};
const SHOT = {json.dumps(shot)};
const SEG = {segments};
const SEED = {seed};
function fnv(label) {{ let h = 2166136261; for (let i = 0; i < label.length; i++) {{ h ^= label.charCodeAt(i); h = Math.imul(h, 16777619); }} return h >>> 0; }}
function mulberry32(seed) {{ let s = seed >>> 0; return function () {{ s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }}; }}
function heightAt(x, z) {{
  const plateau = 9.0 / (1.0 + Math.exp((x - (-12.0)) / 3.5));
  const hills = 2.2 * Math.sin(x * 0.09 + 0.7) * Math.cos(z * 0.07 + 0.3)
    + 1.1 * Math.sin(x * 0.23) * Math.sin(z * 0.19 + 1.3);
  const dx = x - 18.0, dz = z - 10.0;
  const mound = 3.0 * Math.exp(-(dx * dx + dz * dz) / 180.0);
  return 1.0 + plateau + hills + mound;
}}
const renderer = new THREE.WebGLRenderer({{ antialias: false, preserveDrawingBuffer: true }});
renderer.setPixelRatio(1);
renderer.setSize(W, H, false);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = LOOK.exposure;
document.getElementById('stage').appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(new THREE.Color(LOOK.fog_color), LOOK.fog_density);
const camera = new THREE.PerspectiveCamera(SHOT.fov, W / H, 0.1, 900);
// Sky dome: procedural gradient + sun disc, no texture.
const sunEl = LOOK.sun_elevation_deg * Math.PI / 180;
const sunAz = LOOK.sun_azimuth_deg * Math.PI / 180;
const sunDir = new THREE.Vector3(Math.cos(sunEl) * Math.sin(sunAz), Math.sin(sunEl), Math.cos(sunEl) * Math.cos(sunAz));
const skyUniforms = {{
  uSunDir: {{ value: sunDir }},
  uHorizon: {{ value: new THREE.Color(LOOK.sky_horizon) }},
  uZenith: {{ value: new THREE.Color(LOOK.sky_zenith) }},
  uSunColor: {{ value: new THREE.Color(LOOK.sun_color) }},
  uSaturation: {{ value: LOOK.saturation }}
}};
const sky = new THREE.Mesh(
  new THREE.SphereGeometry(420, 32, 16),
  new THREE.ShaderMaterial({{
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: skyUniforms,
    vertexShader: 'varying vec3 vDir; void main() {{ vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }}',
    fragmentShader: 'varying vec3 vDir; uniform vec3 uSunDir; uniform vec3 uHorizon; uniform vec3 uZenith; uniform vec3 uSunColor; uniform float uSaturation; void main() {{ float h = clamp(vDir.y, 0.0, 1.0); vec3 col = mix(uHorizon, uZenith, pow(h, 0.55)); float s = max(dot(normalize(vDir), uSunDir), 0.0); col += uSunColor * (pow(s, 900.0) * 3.0 + pow(s, 24.0) * 0.25); float lum = dot(col, vec3(0.2126, 0.7152, 0.0722)); col = mix(vec3(lum), col, uSaturation); gl_FragColor = vec4(col, 1.0); }}'
  }})
);
scene.add(sky);
const sun = new THREE.DirectionalLight(new THREE.Color(LOOK.sun_color), LOOK.sun_intensity);
sun.position.copy(sunDir).multiplyScalar(120);
scene.add(sun);
scene.add(new THREE.HemisphereLight(new THREE.Color(LOOK.sky_zenith), new THREE.Color(0x8a7a5a), 0.55));
scene.add(new THREE.AmbientLight(0xffffff, 0.12));
// Terrain: analytic heightfield grid, vertex colours by height band.
const SIZE = 140, HALF = SIZE / 2;
const geo = new THREE.PlaneGeometry(SIZE, SIZE, SEG, SEG);
geo.rotateX(-Math.PI / 2);
const pos = geo.attributes.position;
const colors = new Float32Array(pos.count * 3);
const sand = new THREE.Color(0xc2a878), grass = new THREE.Color(0x5d7a3a), rock = new THREE.Color(0x8d8578), high = new THREE.Color(0xb8b0a0);
const tmp = new THREE.Color();
for (let i = 0; i < pos.count; i++) {{
  const x = pos.getX(i), z = pos.getZ(i);
  const h = heightAt(x, z);
  pos.setY(i, h);
  if (h < 2.2) tmp.copy(sand); else if (h < 6.0) tmp.copy(grass); else if (h < 9.5) tmp.copy(rock); else tmp.copy(high);
  colors[i * 3] = tmp.r; colors[i * 3 + 1] = tmp.g; colors[i * 3 + 2] = tmp.b;
}}
geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
geo.computeVertexNormals();
const terrain = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({{ vertexColors: true, roughness: 0.95, metalness: 0.0 }}));
scene.add(terrain);
// Water plane on the eastern plain, level varies purely with t.
const water = new THREE.Mesh(
  new THREE.PlaneGeometry(70, 70),
  new THREE.MeshStandardMaterial({{ color: 0x3f7fa8, roughness: 0.15, metalness: 0.0, transparent: true, opacity: 0.78 }})
);
water.rotation.x = -Math.PI / 2;
water.position.set(28, 1.6, 0);
scene.add(water);
// Seeded scatter: rocks + cone trees, placed on the heightfield.
function scatter(label, count, mesh, yOff) {{
  const rand = mulberry32(fnv(label) ^ (SEED === 0 ? 12345 : SEED));
  const dummy = new THREE.Object3D();
  for (let i = 0; i < count; i++) {{
    const x = -60 + rand() * 120, z = -60 + rand() * 120;
    const s = 0.5 + rand() * 1.1;
    dummy.position.set(x, heightAt(x, z) + yOff * s, z);
    dummy.rotation.set(0, rand() * Math.PI * 2, 0);
    dummy.scale.setScalar(s);
    dummy.updateMatrix();
    mesh.setMatrixAt(i, dummy.matrix);
  }}
  mesh.instanceMatrix.needsUpdate = true;
}}
const rocks = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(0.55, 0), new THREE.MeshStandardMaterial({{ color: 0x7d766a, roughness: 0.9 }}), 40);
scatter('rocks', 40, rocks, 0.1);
scene.add(rocks);
const trees = new THREE.InstancedMesh(new THREE.ConeGeometry(1.1, 4.2, 8), new THREE.MeshStandardMaterial({{ color: 0x2f5230, roughness: 0.85 }}), 24);
scatter('trees', 24, trees, 2.0);
scene.add(trees);
function update(t) {{
  water.position.y = 1.6 + 0.05 * Math.sin(t * 1.3);
  const k = DUR > 0 ? t / DUR : 0;
  const base = new THREE.Vector3(SHOT.position[0], SHOT.position[1], SHOT.position[2]);
  const tgt = new THREE.Vector3(SHOT.target[0], SHOT.target[1], SHOT.target[2]);
  if (SHOT.movement === 'orbit') {{
    const a = k * Math.PI * 0.6;
    const r = Math.hypot(base.x - tgt.x, base.z - tgt.z);
    camera.position.set(tgt.x + Math.sin(a) * r, base.y, tgt.z + Math.cos(a) * r);
  }} else if (SHOT.movement === 'dolly') {{
    camera.position.lerpVectors(base, tgt, 0.25 * k);
    camera.position.y = base.y;
  }} else if (SHOT.movement === 'pan') {{
    camera.position.set(base.x - 18 * k + 9, base.y, base.z);
  }} else {{
    camera.position.copy(base);
  }}
  camera.lookAt(tgt);
  sky.position.copy(camera.position);
}}
window.__athenaionStats = function () {{
  return {{ calls: renderer.info.render.calls, triangles: renderer.info.render.triangles,
    geometries: renderer.info.memory.geometries, textures: renderer.info.memory.textures,
    terrain_segments: SEG, quality: '{quality}' }};
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


def _actions_for_frames(total: int) -> list[dict[str, Any]]:
    return [
        {
            "name": f"frame_{frame:04d}",
            "evaluate": f"window.__hf.seekFrame({frame})",
            "settle": f"window.__hfSettledFrame === {frame}",
            "screenshot": True,
        }
        for frame in range(total)
    ]


def render_world(
    *,
    look: dict[str, Any] | None = None,
    shot: dict[str, Any] | None = None,
    out_dir: Path,
    width: int = 480,
    height: int = 270,
    fps: int = 10,
    duration_s: float = 1.0,
    quality: str = "preview",
    seed: int = 0,
    runs: int = 2,
) -> dict[str, Any]:
    """Render the world ``runs`` times in fresh browsers; hashes must match."""
    if runs < 1:
        raise CapabilityError("video.athenaion_world_engine: runs must be >= 1")
    look_n = normalise_look(look or {})
    shot_n = normalise_shot(shot or {"position": [55, 26, 62], "target": [0, 4, 0], "fov": 40, "movement": "static"})
    plan = build_world_plan(width=width, height=height, fps=fps, duration_s=duration_s, seed=seed, quality=quality)
    gate = validate_world_plan(plan)
    if gate["verdict"] != "pass":
        raise CapabilityError("video.athenaion_world_engine: plan failed gates: " + "; ".join(i["message"] for i in gate["issues"]))
    html = build_world_html(width=width, height=height, fps=fps, duration_s=duration_s, look=look_n, shot=shot_n, quality=quality, seed=seed)
    total = max(1, round(duration_s * fps))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_runs: list[dict[str, Any]] = []
    three_module = ""
    for run_index in range(runs):
        result = capture_actions(html, _actions_for_frames(total), width=width, height=height)
        three_module = str(result.get("three_module", ""))
        run_dir = out_dir / f"run_{run_index}"
        run_dir.mkdir(parents=True, exist_ok=True)
        frames = []
        for shot_rec in result["shots"]:
            path = run_dir / f"{shot_rec['name']}.png"
            path.write_bytes(shot_rec["png_bytes"])
            frames.append({"frame": int(shot_rec["name"].split("_")[1]), "sha256": shot_rec["sha256"], "bytes": shot_rec["bytes"], "settled": True, "file": path.name})
        all_runs.append({"run": run_index, "frames": frames, "stats": result["stats"], "ready_ms": result["ready_ms"]})
    hashes = [[f["sha256"] for f in r["frames"]] for r in all_runs]
    identical = all(h == hashes[0] for h in hashes) if hashes else True
    issues: list[dict[str, Any]] = []
    if not identical:
        issues.append({"code": "frame_hash_mismatch", "message": "two renders of the same world differ; not deterministic on this machine"})
    stats0 = all_runs[0]["stats"] if all_runs else {}
    return {
        "verdict": "fail" if issues else "pass",
        "issues": issues,
        "plan_gates": gate,
        "width": width, "height": height, "fps": fps, "duration_s": float(duration_s),
        "frame_count": total, "quality": quality, "seed": seed,
        "look": look_n, "shot": shot_n,
        "three_module": three_module,
        "runs": all_runs,
        "hashes_identical": identical,
        "triangles": stats0.get("triangles"),
        "draw_calls": stats0.get("calls"),
        "human_measured": False,
        "external_assets": [],
    }


def render_long_run(
    *,
    look: dict[str, Any] | None = None,
    shot: dict[str, Any] | None = None,
    out_dir: Path,
    width: int = 480,
    height: int = 270,
    fps: int = 10,
    duration_s: float = 5.2,
    quality: str = "preview",
    seed: int = 0,
) -> dict[str, Any]:
    """One continuous session of ``duration_s`` seconds; must not hang."""
    if duration_s < 5.0:
        raise CapabilityError("video.athenaion_world_engine: long run must be >= 5 seconds")
    report = render_world(
        look=look, shot=shot, out_dir=out_dir, width=width, height=height,
        fps=fps, duration_s=duration_s, quality=quality, seed=seed, runs=1,
    )
    report["long_run"] = True
    report["continuous_seconds"] = float(duration_s)
    return report


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = str(params.get("mode", "render"))
    common = {
        "look": params.get("look"),
        "shot": params.get("shot"),
        "width": int(params.get("width", 480)),
        "height": int(params.get("height", 270)),
        "fps": int(params.get("fps", 10)),
        "duration_s": float(params.get("duration_s", duration or 1.0)),
        "quality": str(params.get("quality", "preview")),
        "seed": int(params.get("seed", seed)),
    }
    if mode == "long":
        report = render_long_run(out_dir=out_dir, **common)
    else:
        report = render_world(out_dir=out_dir, runs=2, **common)
    ok = report["verdict"] == "pass"
    report_path = out_dir / "world_engine_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    first = out_dir / "run_0" / "frame_0000.png"
    return CapabilityResult(
        png=str(first) if first.is_file() else None,
        duration_s=float(report.get("duration_s", 0.0)),
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"], "ok": ok,
            "hashes_identical": report.get("hashes_identical"),
            "triangles": report.get("triangles"), "draw_calls": report.get("draw_calls")},
    )


def register_athenaion_world_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="video.athenaion_world_engine",
        kind="video",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {
                "mode": {"type": "string"},
                "look": {"type": "object"},
                "shot": {"type": "object"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "fps": {"type": "integer"},
                "duration_s": {"type": "number"},
                "quality": {"type": "string"},
                "seed": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        cpu_cost_hint=1.0,
        render=_render,
        has_media_output=True,
        description=(
            "B1 minimal procedural Three.js world: analytic heightfield "
            "terrain, procedural sky, seeded scatter, quality scaling, "
            "__hf settle protocol, rendered twice with identical frame "
            "hashes. Zero external assets; vendored three.js only. "
            "See ATHENAION_ATTRIBUTION.md."
        ),
        line="video",
    ))
    return ["video.athenaion_world_engine"]


register_athenaion_world_capabilities_once()
