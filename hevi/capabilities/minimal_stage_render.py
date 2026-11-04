"""Minimal browser 3D stage renderer (``video.minimal_stage_render``).

Clean-room minimal renderer for the code-stage method
described in ``hevi-vs-code-stage-mv.md`` section 5: one
Three.js scene, built from code with zero external assets
(no models, textures, fonts or footage), driven by the
``window.__hf`` seek protocol and the determinism discipline
of ``qa.frame_adapter_contract`` /
``qa.deterministic_render_gate``. The render plan is judged
by those two gates *before* any browser is launched: frame
time is integer math ``t = floor(frame) / fps``, fps /
dimensions / variables lock before frame 0, no wall-clock
reads, no unseeded randomness, no fetch during render, and
capture is atomic -- one whole composited frame per seek,
only after settle confirmation.

The scene is deliberately minimal: a floor plane, one
geometric proxy figure (spheres and cylinders, no skeleton
dance product -- the article's pure-code skeleton route is
not revived here; this figure is a stage placeholder whose
motion is a pure function of time), two lights and a seeded
particle field, all parameterised from the stage template
(``pipeline.project_style_sheet`` stage block). Camera
movement is limited to ``static`` / ``orbit`` / ``dolly`` /
``pan``; anything else fails instead of silently falling
back. This is the minimal版 only: no Studio, no keyed
video figure, no full stage system.

Determinism is measured, not claimed: the stage is rendered
twice in two fresh browsers and the per-frame PNG hashes
must match exactly, in order. A mismatch returns
``verdict: "fail"`` with the first differing frame named.
A missing Three.js vendor file or a missing browser raises
:class:`CapabilityError` -- the renderer never returns a
fake frame. The vendored Three.js build already in this
repository is reused; nothing is downloaded.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from hevi.capabilities.deterministic_render_gate import check_render_plan
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.frame_adapter_contract import check_adapter_plan
from hevi.capabilities.project_style_sheet import validate_stage_block
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

SUPPORTED_MOVEMENTS = ("static", "orbit", "dolly", "pan")

CHROMIUM_ARGS = [
    "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
    "--ignore-gpu-blocklist", "--no-sandbox",
    "--disable-gpu-sandbox", "--disable-dev-shm-usage",
    "--font-render-hinting=none", "--disable-lcd-text",
    "--disable-font-subpixel-positioning", "--hide-scrollbars",
    "--force-color-profile=srgb", "--force-device-scale-factor=1",
]

_PARTICLE_COLORS = {
    "sparkle": "#ffffff", "dust": "#c9c2b4", "confetti": "#ff5da2",
    "glow": "#88ccff", "petal": "#ffb7c5", "snow": "#eef6ff",
    "ember": "#ff7733", "bubble": "#aee6ff", "star": "#ffe27a",
}

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def resolve_three_module() -> Path:
    """Locate the vendored Three.js module already in this repo."""
    env = os.environ.get("HEVI_THREE_MODULE")
    candidates = []
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve()
    candidates.append(here.parents[1] / "video" / "hyperframes_vendor" / "three.module.js")
    candidates.append(
        here.parents[1] / "layer4_legacy" / "scene3d" / "vendor" / "three" / "three.module.js"
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise CapabilityError(
        "video.minimal_stage_render: vendored three.module.js not found; "
        "checked HEVI_THREE_MODULE and the hyperframes/scene3d vendor "
        "paths. Nothing is downloaded; the renderer is unavailable "
        "until the vendored file is present."
    )


def normalise_stage_block(template: Any) -> dict[str, Any]:
    """Return the stage block from a bare block or a sheet wrapper. Composes (3O SPEC 1.2): validate_stage_block."""
    if not isinstance(template, dict):
        raise CapabilityError("video.minimal_stage_render: stage template must be a JSON object")
    block = template.get("stage") if isinstance(template.get("stage"), dict) else None
    if block is None and "lighting_rig" in template:
        block = template
    if block is None:
        raise CapabilityError(
            "video.minimal_stage_render: stage template carries no stage block; "
            "a stage plan needs lighting_rig, camera_path, particles and materials"
        )
    report = validate_stage_block(block)
    if not report["ok"]:
        raise CapabilityError(
            "video.minimal_stage_render: stage block invalid: " + "; ".join(report["problems"])
        )
    return block


def build_stage_plan(
    *,
    width: int,
    height: int,
    fps: int,
    duration_s: float,
    seed: int = 0,
) -> dict[str, Any]:
    """Build the adapter + render plans the two gates judge."""
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
        "duration_s": duration_s,
    }


def validate_stage_plan(plan: Any) -> dict[str, Any]:
    """Judge a stage plan with the __hf + determinism gates. Composes (3O SPEC 1.2): check_render_plan."""
    if not isinstance(plan, dict):
        raise CapabilityError("video.minimal_stage_render: stage plan must be a JSON object")
    adapter = check_adapter_plan({"adapter": plan.get("adapter")})
    render = check_render_plan(plan.get("render"))
    issues = list(adapter["issues"]) + list(render["issues"])
    return {
        "verdict": "fail" if issues else "pass",
        "adapter": adapter,
        "render": render,
        "issues": issues,
    }


def _stage_render_params(block: dict[str, Any]) -> dict[str, Any]:
    rig = block.get("lighting_rig") or {}
    lights = rig.get("lights") or []
    first = lights[0] if lights else {}
    second = lights[1] if len(lights) > 1 else first
    camera_path = block.get("camera_path") or {}
    particles = block.get("particles") or {}
    materials = block.get("materials") or {}
    floor = materials.get("floor") or {}
    movement = str(camera_path.get("movement", "static")).strip().lower().replace("-", "_")
    if movement not in SUPPORTED_MOVEMENTS:
        raise CapabilityError(
            f"video.minimal_stage_render: camera movement {movement!r} is not "
            f"supported by the minimal renderer; supported: {list(SUPPORTED_MOVEMENTS)}"
        )
    floor_hex = floor.get("color_hex") or "#101018"
    if not isinstance(floor_hex, str) or not _HEX_RE.match(floor_hex.strip()):
        raise CapabilityError("video.minimal_stage_render: floor color_hex must be #RRGGBB")
    light_hex = first.get("color_hex") or "#ffffff"
    if not isinstance(light_hex, str) or not _HEX_RE.match(light_hex.strip()):
        light_hex = "#ffffff"
    second_hex = second.get("color_hex") or "#88aaff"
    if not isinstance(second_hex, str) or not _HEX_RE.match(second_hex.strip()):
        second_hex = "#88aaff"
    density = particles.get("density", 0.3)
    kind = str(particles.get("kind", "sparkle")).strip().lower()
    return {
        "floor_color": floor_hex.strip().lower(),
        "floor_roughness": float(floor.get("roughness", 0.2)),
        "floor_reflective": bool(floor.get("reflective", False)),
        "light_color": light_hex.strip().lower(),
        "light_intensity": float(first.get("intensity", 1.0)),
        "rim_color": second_hex.strip().lower(),
        "rim_intensity": float(second.get("intensity", 0.6)),
        "movement": movement,
        "particle_kind": kind,
        "particle_color": _PARTICLE_COLORS.get(kind, "#ffffff"),
        "particle_count": max(0, round(20 + 80 * float(density))),
        "particle_speed": float(particles.get("speed", 1.0)),
    }


def build_stage_html(
    *,
    width: int,
    height: int,
    fps: int,
    duration_s: float,
    params: dict[str, Any],
    seed: int = 0,
) -> str:
    """Build the self-contained stage page (Three.js via import map).

    The page script is a pure function of frame time: no
    Date.now, no performance.now, no Math.random at render
    time. Particle base positions come from a seeded LCG run
    once at setup; every per-frame value is computed from t.
    """
    total = max(1, round(duration_s * fps))
    js = f"""
import * as THREE from 'three';
const W = {width}, H = {height}, FPS = {fps}, TOTAL = {total}, DUR = {duration_s!r};
const P = {json.dumps(params)};
const SEED = {seed};
function lcg(seed) {{ let s = seed >>> 0; return function () {{ s = (1664525 * s + 1013904223) >>> 0; return s / 4294967296; }}; }}
const renderer = new THREE.WebGLRenderer({{ antialias: false, preserveDrawingBuffer: true }});
renderer.setPixelRatio(1);
renderer.setSize(W, H, false);
document.getElementById('stage').appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b0b12);
const camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 100);
const key = new THREE.DirectionalLight(new THREE.Color(P.light_color), P.light_intensity * 2.0);
key.position.set(3, 5, 4);
scene.add(key);
const rim = new THREE.PointLight(new THREE.Color(P.rim_color), P.rim_intensity * 30.0);
rim.position.set(-3, 2, 2);
scene.add(rim);
scene.add(new THREE.AmbientLight(0xffffff, 0.35));
const floor = new THREE.Mesh(
  new THREE.PlaneGeometry(20, 20),
  new THREE.MeshStandardMaterial({{ color: new THREE.Color(P.floor_color), roughness: P.floor_roughness, metalness: P.floor_reflective ? 0.4 : 0.0 }})
);
floor.rotation.x = -Math.PI / 2;
scene.add(floor);
const bodyMat = new THREE.MeshStandardMaterial({{ color: 0xd8d8e0, roughness: 0.6 }});
const accentMat = new THREE.MeshStandardMaterial({{ color: 0x3355ff, roughness: 0.5 }});
const figure = new THREE.Group();
const head = new THREE.Mesh(new THREE.SphereGeometry(0.18, 24, 16), bodyMat);
head.position.y = 1.62;
figure.add(head);
const torso = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.17, 0.55, 16), accentMat);
torso.position.y = 1.18;
figure.add(torso);
function limb(r, len, mat) {{ const g = new THREE.Group(); const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, 10), mat); m.position.y = -len / 2; g.add(m); return g; }}
const armL = limb(0.045, 0.5, bodyMat); armL.position.set(-0.2, 1.4, 0); figure.add(armL);
const armR = limb(0.045, 0.5, bodyMat); armR.position.set(0.2, 1.4, 0); figure.add(armR);
const legL = limb(0.06, 0.85, bodyMat); legL.position.set(-0.09, 0.88, 0); figure.add(legL);
const legR = limb(0.06, 0.85, bodyMat); legR.position.set(0.09, 0.88, 0); figure.add(legR);
scene.add(figure);
const rand = lcg(SEED === 0 ? 12345 : SEED);
const pCount = P.particle_count;
const pBase = new Float32Array(pCount * 3);
const pPhase = new Float32Array(pCount);
for (let i = 0; i < pCount; i++) {{
  pBase[i * 3] = (rand() - 0.5) * 6;
  pBase[i * 3 + 1] = 0.2 + rand() * 2.6;
  pBase[i * 3 + 2] = (rand() - 0.5) * 4;
  pPhase[i] = rand() * Math.PI * 2;
}}
const pGeo = new THREE.BufferGeometry();
pGeo.setAttribute('position', new THREE.BufferAttribute(pBase.slice(), 3));
const points = new THREE.Points(pGeo, new THREE.PointsMaterial({{ color: new THREE.Color(P.particle_color), size: 0.08 }}));
scene.add(points);
function update(t) {{
  const w = Math.PI * 2 * 0.5;
  figure.position.y = 0.04 * Math.sin(w * t);
  figure.rotation.y = 0.35 * Math.sin(w * 0.5 * t);
  armL.rotation.z = 0.5 * Math.sin(w * t);
  armR.rotation.z = -0.5 * Math.sin(w * t);
  legL.rotation.x = 0.25 * Math.sin(w * t);
  legR.rotation.x = -0.25 * Math.sin(w * t);
  const pos = pGeo.attributes.position;
  for (let i = 0; i < pCount; i++) {{
    pos.array[i * 3] = pBase[i * 3] + 0.1 * P.particle_speed * Math.sin(t + pPhase[i]);
    pos.array[i * 3 + 1] = pBase[i * 3 + 1] + 0.3 * P.particle_speed * Math.sin(2 * t + pPhase[i]);
    pos.array[i * 3 + 2] = pBase[i * 3 + 2];
  }}
  pos.needsUpdate = true;
  const k = DUR > 0 ? t / DUR : 0;
  if (P.movement === 'orbit') {{
    const a = k * Math.PI;
    camera.position.set(Math.sin(a) * 4.2, 1.6, Math.cos(a) * 4.2);
  }} else if (P.movement === 'dolly') {{
    camera.position.set(0, 1.6, 4.8 - 1.2 * k);
  }} else if (P.movement === 'pan') {{
    camera.position.set(-1.5 + 3 * k, 1.6, 4.2);
  }} else {{
    camera.position.set(0, 1.6, 4.2);
  }}
  camera.lookAt(0, 1.0, 0);
}}
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
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>html,body{{margin:0;padding:0;background:#0b0b12;overflow:hidden}}canvas{{display:block}}</style>
<script>window.__hfError=null;window.__hfReady=false;window.addEventListener('error',function(e){{window.__hfError=String((e&&e.message)||'page error');}});</script>
<script type="importmap">{{"imports":{{"three":"/three.module.js"}}}}</script>
</head><body><div id="stage"></div>
<script type="module">{js}</script>
</body></html>"""


class _StageHandler(BaseHTTPRequestHandler):
    """Serves the generated stage page and the vendored three.js."""

    def log_message(self, *args: Any) -> None:  # keep test output clean
        pass

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
        if self.path == "/":
            body, ctype = self.server.html_bytes, "text/html; charset=utf-8"
        elif self.path == "/three.module.js":
            body, ctype = self.server.three_bytes, "text/javascript; charset=utf-8"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _run_once(
    *,
    url: str,
    width: int,
    height: int,
    total_frames: int,
    frames_dir: Path,
) -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise CapabilityError(
            f"video.minimal_stage_render: Playwright is required: {exc}"
        ) from exc
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=CHROMIUM_ARGS)
            try:
                page = browser.new_page(
                    viewport={"width": width, "height": height},
                    device_scale_factor=1,
                )
                page.goto(url, wait_until="load", timeout=30000)
                page.wait_for_function("window.__hfReady === true", timeout=30000)
                error = page.evaluate("window.__hfError")
                if error:
                    raise CapabilityError(
                        f"video.minimal_stage_render: stage page failed to load: {error}"
                    )
                total = page.evaluate("window.__hf.getDurationFrames()")
                if int(total) != total_frames:
                    raise CapabilityError(
                        "video.minimal_stage_render: page duration frames "
                        f"{total} != planned {total_frames}"
                    )
                for frame in range(total_frames):
                    page.evaluate(f"window.__hf.seekFrame({frame})")
                    # Settle *confirmation*: the settled frame flag must
                    # read back as this frame before any capture. A
                    # fixed wait would not be a confirmation.
                    page.wait_for_function(
                        f"window.__hfSettledFrame === {frame}", timeout=5000
                    )
                    shot = page.screenshot()
                    if not shot.startswith(b"\x89PNG"):
                        raise CapabilityError(
                            "video.minimal_stage_render: capture did not return a PNG frame"
                        )
                    path = frames_dir / f"frame_{frame:06d}.png"
                    path.write_bytes(shot)
                    frames.append({
                        "frame": frame,
                        "sha256": hashlib.sha256(shot).hexdigest(),
                        "bytes": len(shot),
                        "settled": True,
                        "file": path.name,
                    })
            finally:
                browser.close()
    except CapabilityError:
        raise
    except Exception as exc:
        raise CapabilityError(
            f"video.minimal_stage_render: browser render failed: {exc}"
        ) from exc
    return frames


def render_minimal_stage(
    *,
    stage_template: Any,
    out_dir: Path,
    width: int = 320,
    height: int = 180,
    fps: int = 10,
    duration_s: float = 2.0,
    seed: int = 0,
) -> dict[str, Any]:
    """Render the minimal stage twice; the hashes must match exactly."""
    if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
        raise CapabilityError("video.minimal_stage_render: width must be a positive integer")
    if not isinstance(height, int) or isinstance(height, bool) or height <= 0:
        raise CapabilityError("video.minimal_stage_render: height must be a positive integer")
    if not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
        raise CapabilityError("video.minimal_stage_render: fps must be a positive integer")
    if not _is_num(duration_s) or float(duration_s) <= 0:
        raise CapabilityError("video.minimal_stage_render: duration_s must be > 0")
    block = normalise_stage_block(stage_template)
    params = _stage_render_params(block)
    plan = build_stage_plan(
        width=width, height=height, fps=fps, duration_s=float(duration_s), seed=seed
    )
    gate = validate_stage_plan(plan)
    if gate["verdict"] != "pass":
        raise CapabilityError(
            "video.minimal_stage_render: stage plan failed the __hf / "
            "determinism gates: " + "; ".join(i["message"] for i in gate["issues"])
        )
    three_path = resolve_three_module()
    html = build_stage_html(
        width=width, height=height, fps=fps, duration_s=float(duration_s),
        params=params, seed=seed,
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    total_frames = max(1, round(float(duration_s) * fps))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StageHandler)
    server.html_bytes = html.encode("utf-8")
    server.three_bytes = three_path.read_bytes()
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/"
        run_a = _run_once(
            url=url, width=width, height=height, total_frames=total_frames,
            frames_dir=out_dir / "run_0",
        )
        run_b = _run_once(
            url=url, width=width, height=height, total_frames=total_frames,
            frames_dir=out_dir / "run_1",
        )
    finally:
        server.shutdown()
        server.server_close()
    hashes_a = [f["sha256"] for f in run_a]
    hashes_b = [f["sha256"] for f in run_b]
    identical = hashes_a == hashes_b
    issues: list[dict[str, Any]] = []
    if not identical:
        first_diff = next(
            (i for i, (a, b) in enumerate(zip(hashes_a, hashes_b)) if a != b),
            min(len(hashes_a), len(hashes_b)),
        )
        issues.append({
            "code": "frame_hash_mismatch",
            "message": (
                f"two renders of the same stage differ at frame {first_diff}; "
                "the minimal renderer is not deterministic on this machine"
            ),
            "frame": first_diff,
        })
    return {
        "verdict": "fail" if issues else "pass",
        "issues": issues,
        "plan_gates": gate,
        "width": width,
        "height": height,
        "fps": fps,
        "duration_s": float(duration_s),
        "frame_count": total_frames,
        "stage_params": params,
        "three_module": str(three_path),
        "runs": [
            {"run": 0, "frames": run_a},
            {"run": 1, "frames": run_b},
        ],
        "hashes_identical": identical,
        "human_measured": False,
        "external_assets": [],
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    mode = str(params.get("mode", "render"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if mode == "plan":
        plan = build_stage_plan(
            width=int(params.get("width", 320)),
            height=int(params.get("height", 180)),
            fps=int(params.get("fps", 10)),
            duration_s=float(params.get("duration_s", 2.0)),
            seed=int(params.get("seed", seed)),
        )
        if params.get("stage_template") is not None:
            block = normalise_stage_block(params["stage_template"])
            report: dict[str, Any] = {
                "plan": plan,
                "gates": validate_stage_plan(plan),
                "stage_params": _stage_render_params(block),
            }
        else:
            report = {"plan": plan, "gates": validate_stage_plan(plan)}
        ok = report["gates"]["verdict"] == "pass"
    else:
        report = render_minimal_stage(
            stage_template=params.get("stage_template"),
            out_dir=out_dir,
            width=int(params.get("width", 320)),
            height=int(params.get("height", 180)),
            fps=int(params.get("fps", 10)),
            duration_s=float(params.get("duration_s", 2.0)),
            seed=int(params.get("seed", seed)),
        )
        ok = report["verdict"] == "pass"
    report_path = out_dir / "minimal_stage_render_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    first_frame = out_dir / "run_0" / "frame_000000.png"
    return CapabilityResult(
        png=str(first_frame) if first_frame.is_file() else None,
        duration_s=float(report.get("duration_s", 0.0)),
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report.get("verdict", report.get("gates", {}).get("verdict", "pass" if ok else "fail")),
            "ok": ok,
            "hashes_identical": report.get("hashes_identical"),
        },
    )


def register_minimal_stage_render_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.minimal_stage_render",
            kind="video",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "mode": {"type": "string"},
                    "stage_template": {"type": "object"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "fps": {"type": "integer"},
                    "duration_s": {"type": "number"},
                    "seed": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=1.0,
            render=_render,
            has_media_output=True,
            description=(
                "Minimal browser 3D stage renderer (method "
                "reconstructed from an article description; see "
                "CODE_STAGE_MV_ATTRIBUTION.md): a code-built "
                "Three.js scene with zero external assets, driven "
                "by the window.__hf seek protocol with settle "
                "confirmation and atomic capture, under the "
                "determinism gates. Rendered twice; per-frame "
                "hashes must match exactly. Minimal version only: "
                "no Studio, no keyed figure, no full stage system."
            ),
            line="video",
        )
    )
    return ["video.minimal_stage_render"]


register_minimal_stage_render_capabilities_once()
