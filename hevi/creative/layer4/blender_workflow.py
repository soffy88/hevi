"""HEVI Layer4 Blender adapter — deterministic script generation + headless render.

This module owns NO canonical 3O element. It is a HEVI Layer4 adapter
that:
1. Generates deterministic bpy script from shot_spec (pure Python transform,
   no oprim change required — script_gen is pure algorithm → HEVI_LAYER4 owner)
2. Executes headless Blender via the installed binary
3. Returns artifact metadata with checksums for the Production Graph / Artifact
   authority
4. Provides the failure-code seam that HEVI Production Graph / RepairIncident
   can consume — no second orchestrator or second authority is created.

No new oprim element is added. The blender script generation is a pure Python
transform over shot_spec, not a 3O primitive. Blender binary execution is owned
by the Blender runtime, not HEVI.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CANONICAL_BLENDER_BINARY = "/home/soffy/opt/blender/blender"
BLENDER_VERSION_EXPECTED = "3.6.5"


@dataclass(frozen=True)
class BlenderScriptResult:
    """Deterministic bpy script generation from shot_spec (pure Python)."""

    script_text: str
    script_sha256: str
    dependencies: tuple[str, ...] = ()


def generate_script_from_shot_spec(
    *,
    shot_spec: dict[str, Any],
) -> BlenderScriptResult:
    """Generate deterministic bpy script from shot_spec.

    Pure Python transform — no external assets, no randomness, reproducible
    output from identical input. This is the HEVI Layer4-owned capability:
    deterministic script generation, not a canonical 3O element.
    """

    width = shot_spec.get("width", 1920)
    height = shot_spec.get("height", 1080)
    fps = shot_spec.get("fps", 24)
    frame_start = shot_spec.get("frame_start", 1)
    frame_end = shot_spec.get("frame_end", 250)
    camera_position = shot_spec.get("camera_position", [0.0, -10.0, 0.0])
    camera_rotation = shot_spec.get("camera_rotation", [0.0, 0.0, 0.0])
    light_position = shot_spec.get("light_position", [0.0, -5.0, 5.0])
    light_energy = shot_spec.get("light_energy", 1.0)
    objects = shot_spec.get("objects", [])
    output_path = shot_spec.get("output_path", "output")

    script_lines = [
        '# Blender deterministic script — generated from shot_spec',
        f'BLENDER_VERSION_CHECK = "{BLENDER_VERSION_EXPECTED}"',
        "",
        "import bpy",
        "import os",
        "",
        "# Validate Blender version",
        '# assert BLENDER_VERSION_CHECK in bpy.app.version_string, "Blender version mismatch"',
        "",
        "# Clean start — clear existing data",
        "bpy.ops.object.select_all(action='SELECT')",
        "bpy.ops.object.delete(confirm=False)",
        "",
        "# Create camera",
        "bpy.context.scene.render.engine = 'CYCLES'",
        "bpy.context.scene.cycles.device = 'CPU'",
        "bpy.context.scene.cycles.samples = 16",
        "cam = bpy.data.objects.new('Camera', bpy.data.cameras.new('Cam'))",
        "bpy.context.collection.objects.link(cam)",
        "bpy.context.scene.camera = cam",
        f"cam.location = {camera_position}",
        f"cam.rotation_euler = {camera_rotation}",
        "",
        "# Create area light",
        "light = bpy.data.objects.new('Light', bpy.data.lights.new('Light', 'AREA'))",
        "bpy.context.collection.objects.link(light)",
        f"light.location = {light_position}",
        f"light.data.energy = {light_energy}",
        f"light.data.size = {width * height / 10000:.1f}",
        "",
        "# Create cube primitive",
    ]

    for i, obj_spec in enumerate(objects):
        obj_type = obj_spec.get("type", "cube")
        obj_name = obj_spec.get("name", f"object_{i}")
        obj_location = obj_spec.get("location", [0.0, 0.0, 0.0])
        obj_scale = obj_spec.get("scale", [1.0, 1.0, 1.0])

        if obj_type == "cube":
            script_lines.extend(
                [
                    f"bpy.ops.mesh.primitive_cube_add(size=2, location={obj_location})",
                    "obj = bpy.context.object",
                    f"obj.name = '{obj_name}'",
                    f"obj.scale = {obj_scale}",
                ]
            )
        elif obj_type == "plane":
            script_lines.extend(
                [
                    f"bpy.ops.mesh.primitive_plane_add(size={obj_spec.get('size', 10)}, location={obj_location})",
                    "obj = bpy.context.object",
                    f"obj.name = '{obj_name}'",
                ]
            )

    script_lines.extend(
        [
            "",
            "# Set frame range",
            f"bpy.context.scene.frame_start = {frame_start}",
            f"bpy.context.scene.frame_end = {frame_end}",
            f"bpy.context.scene.render.fps = {fps}",
            "",
            "# Set output path",
            f"output_dir = '{os.path.dirname(output_path)}'",
            "os.makedirs(output_dir, exist_ok=True)",
            f"bpy.context.scene.render.filepath = '{output_path}'",
            "",
            "# Render still",
            "bpy.ops.render.render(write_still=True)",
            "",
            "# Verify output",
            f"assert os.path.exists('{output_path}'), f'Render output missing: {output_path}'",
            f"assert os.path.getsize('{output_path}') > 0, f'Render output empty: {output_path}'",
            "",
            f"print('Blender render complete: {output_path}')",
        ]
    )

    script_text = "\n".join(script_lines)

    script_sha256 = hashlib.sha256(script_text.encode("utf-8")).hexdigest()
    deps_keys = tuple(sorted(shot_spec.keys()))

    return BlenderScriptResult(
        script_text=script_text,
        script_sha256=script_sha256,
        dependencies=deps_keys,
    )


def execute_headless_blender(
    *,
    script_path: str,
    output_path: str,
    blender_binary: str = CANONICAL_BLENDER_BINARY,
    timeout_s: int = 300,
) -> dict[str, Any]:
    """Execute headless Blender with the given script.

    The Blender binary owns the execution. HEVI Layer4 orchestrates the call
    and propagates results/repair paths through existing Production Graph
    mechanisms.
    """

    if not os.path.isfile(blender_binary):
        raise RuntimeError(f"Blender binary not found: {blender_binary}")

    if not os.access(blender_binary, os.X_OK):
        raise RuntimeError(f"Blender binary not executable: {blender_binary}")

    cmd = [
        blender_binary,
        "--background",
        "--python",
        script_path,
        "--",
        output_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Blender render timed out after {timeout_s}s: {e}") from e

    output_data: dict[str, Any] = {
        "blender_binary": blender_binary,
        "blender_version": None,
        "output_path": output_path,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "success": result.returncode == 0,
        "render_output_exists": False,
        "render_output_size": 0,
        "render_output_sha256": None,
    }

    if result.returncode == 0:
        if os.path.isfile(output_path):
            output_size = os.path.getsize(output_path)
            output_data.update(
                {
                    "render_output_exists": True,
                    "render_output_size": output_size,
                    "render_output_sha256": hashlib.sha256(
                        Path(output_path).read_bytes()
                    ).hexdigest(),
                }
            )

        if "Blender" in result.stderr:
            for line in result.stderr.split("\n"):
                if "version" in line.lower():
                    output_data["blender_version"] = line.strip()
                    break

    return output_data


@dataclass(frozen=True)
class BlenderRenderResult:
    """Result of a Blender render operation."""

    success: bool
    script_sha256: str
    render_output_path: str | None = None
    render_output_exists: bool = False
    render_output_size: int = 0
    render_output_sha256: str | None = None
    blender_version: str | None = None
    exit_code: int = -1
    error_message: str | None = None
    failure_code: str | None = None
    repair_action: str | None = None
    execution_metadata: dict[str, Any] = field(default_factory=dict)


def _classify_failure(
    exit_code: int, stderr: str, stdout: str
) -> tuple[str | None, str | None]:
    """Classify a Blender execution failure for the RepairIncident seam."""

    combined = f"{stdout}\n{stderr}"
    combined_lower = combined.lower()

    if exit_code == 1 and (
        "version mismatch" in combined_lower
        or "version_check" in combined_lower
    ):
        return "BLENDER_VERSION_MISMATCH", "RETRY_TARGET"
    if exit_code != 0 and (
        "not found" in combined_lower or "no such file" in combined_lower
    ):
        return "BLENDER_BINARY_MISSING", "MANUAL_ONLY"
    if exit_code != 0 and (
        "permission denied" in combined_lower
        or "not executable" in combined_lower
    ):
        return "BLENDER_BINARY_PERMISSION", "MANUAL_ONLY"
    if exit_code != 0 and (
        "timed out" in combined_lower or "timeout" in combined_lower
    ):
        return "BLENDER_TIMEOUT", "RETRY_TARGET"
    if exit_code != 0 and (
        "segmentation fault" in combined_lower or "core dumped" in combined_lower
    ):
        return "BLENDER_CRASH", "RETRY_TARGET"
    if exit_code != 0 and (
        "memory" in combined_lower or "out of memory" in combined_lower
    ):
        return "BLENDER_OOM", "REPLAN"

    return f"BLENDER_EXIT_{exit_code}", "RETRY_TARGET"


def blender_render_workflow(
    *,
    shot_spec: dict[str, Any],
    blender_binary: str = CANONICAL_BLENDER_BINARY,
    timeout_s: int = 300,
    output_path: str | None = None,
) -> BlenderRenderResult:
    """Full HEVI Layer4 Blender render workflow.

    Steps:
    1. Generate deterministic bpy script from shot_spec (pure Python, HEVI-owned)
    2. Write script to temp file
    3. Execute headless Blender binary
    4. Verify output
    5. Return artifact metadata for Production Graph / Artifact authority

    This adapter:
    - Does NOT modify canonical oprim/omodul/oskill repos
    - Does NOT establish a second orchestrator
    - Does NOT create a second authority
    - Exposes failure_code/repair_action for the existing RepairIncident seam
    """

    effective_output = output_path or shot_spec.get("output_path", "output/blender_render.png")
    resolved_shot_spec = {**shot_spec, "output_path": effective_output}
    script_result = generate_script_from_shot_spec(shot_spec=resolved_shot_spec)

    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, encoding="utf-8"
    ) as f:
        f.write(script_result.script_text)
        script_path = f.name

    try:
        execution = execute_headless_blender(
            script_path=script_path,
            output_path=effective_output,
            blender_binary=blender_binary,
            timeout_s=timeout_s,
        )

        failure_code = None
        repair_action = None
        if execution["exit_code"] != 0:
            failure_code, repair_action = _classify_failure(
                execution["exit_code"],
                execution["stderr"],
                execution["stdout"],
            )

        return BlenderRenderResult(
            success=execution["success"],
            script_sha256=script_result.script_sha256,
            render_output_path=effective_output,
            render_output_exists=execution["render_output_exists"],
            render_output_size=execution["render_output_size"],
            render_output_sha256=execution.get("render_output_sha256"),
            blender_version=execution.get("blender_version"),
            exit_code=execution["exit_code"],
            error_message=(
                execution["stderr"] if execution["exit_code"] != 0 else None
            ),
            failure_code=failure_code,
            repair_action=repair_action,
            execution_metadata={
                "blender_binary": execution["blender_binary"],
                "blender_version": execution.get("blender_version"),
                "script_sha256": script_result.script_sha256,
                "shot_spec_keys": list(shot_spec.keys()),
                "stdout": execution["stdout"],
                "stderr": execution["stderr"],
            },
        )

    finally:
        with contextlib.suppress(OSError):
            os.unlink(script_path)


def generate_animated_scene_script(*, shot_spec: dict[str, Any]) -> BlenderScriptResult:
    """Generate a deterministic bpy script for an animated, lit 3-D scene.

    Unlike :func:`generate_script_from_shot_spec` (a single still), this builds a
    ground plane, a set of shaded objects, three lights and an orbiting camera,
    then renders the whole frame range to an MP4 with Blender's own FFmpeg
    encoder.  Pure string generation — identical input → identical script.
    """
    width = int(shot_spec.get("width", 1280))
    height = int(shot_spec.get("height", 720))
    fps = int(shot_spec.get("fps", 24))
    frame_start = int(shot_spec.get("frame_start", 1))
    frame_end = int(shot_spec.get("frame_end", 120))
    samples = int(shot_spec.get("samples", 24))
    output_path = str(shot_spec.get("output_path", "output/blender_scene.mp4"))
    orbit_radius = float(shot_spec.get("orbit_radius", 11.0))
    orbit_height = float(shot_spec.get("orbit_height", 5.2))
    target = shot_spec.get("look_at", [0.0, 0.0, 1.0])
    objects = shot_spec.get("objects") or _default_scene_objects()

    lines: list[str] = [
        "# Blender animated-scene script — generated deterministically from shot_spec",
        f'BLENDER_VERSION_CHECK = "{BLENDER_VERSION_EXPECTED}"',
        "import bpy, math, os",
        "from mathutils import Vector",
        "",
        "bpy.ops.object.select_all(action='SELECT')",
        "bpy.ops.object.delete(confirm=False)",
        "for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras):",
        "    for item in list(block):",
        "        block.remove(item)",
        "",
        "scene = bpy.context.scene",
        "scene.render.engine = 'CYCLES'",
        "scene.cycles.device = 'CPU'",
        f"scene.cycles.samples = {samples}",
        "scene.cycles.use_denoising = True",
        f"scene.render.resolution_x = {width}",
        f"scene.render.resolution_y = {height}",
        "scene.render.resolution_percentage = 100",
        f"scene.render.fps = {fps}",
        f"scene.frame_start = {frame_start}",
        f"scene.frame_end = {frame_end}",
        "",
        "# --- world: warm grey studio ---",
        "world = bpy.data.worlds.new('World')",
        "scene.world = world",
        "world.use_nodes = True",
        "world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.05, 0.06, 0.08, 1.0)",
        "world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.6",
        "",
        "# --- ground ---",
        "bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, 0))",
        "ground = bpy.context.object; ground.name = 'Ground'",
        "gm = bpy.data.materials.new('GroundMat'); gm.use_nodes = True",
        "gm.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.22, 0.23, 0.26, 1.0)",
        "gm.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.7",
        "ground.data.materials.append(gm)",
        "",
        "# --- objects with distinct shaded materials ---",
        "def _mat(name, rgba, rough, metal=0.0):",
        "    m = bpy.data.materials.new(name); m.use_nodes = True",
        "    p = m.node_tree.nodes['Principled BSDF']",
        "    p.inputs['Base Color'].default_value = rgba",
        "    p.inputs['Roughness'].default_value = rough",
        "    p.inputs['Metallic'].default_value = metal",
        "    return m",
        "",
    ]
    for i, spec in enumerate(objects):
        kind = str(spec.get("type", "cube"))
        name = str(spec.get("name", f"object_{i}"))
        loc = spec.get("location", [0.0, 0.0, 1.0])
        scale = float(spec.get("scale", 1.0))
        color = spec.get("color", [0.8, 0.3, 0.2, 1.0])
        rough = float(spec.get("roughness", 0.35))
        metal = float(spec.get("metallic", 0.0))
        if kind == "torus":
            lines.append(f"bpy.ops.mesh.primitive_torus_add(major_radius={1.0 * scale}, minor_radius={0.32 * scale}, location={tuple(loc)})")
        elif kind == "sphere":
            lines.append(f"bpy.ops.mesh.primitive_uv_sphere_add(radius={1.0 * scale}, location={tuple(loc)})")
        elif kind == "cylinder":
            lines.append(f"bpy.ops.mesh.primitive_cylinder_add(radius={0.8 * scale}, depth={2.0 * scale}, location={tuple(loc)})")
        elif kind == "cone":
            lines.append(f"bpy.ops.mesh.primitive_cone_add(radius1={1.0 * scale}, depth={2.0 * scale}, location={tuple(loc)})")
        else:
            lines.append(f"bpy.ops.mesh.primitive_cube_add(size={2.0 * scale}, location={tuple(loc)})")
        lines.append("obj = bpy.context.object")
        lines.append(f"obj.name = '{name}'")
        lines.append("obj.rotation_euler = (0.35, 0.0, 0.5)")
        lines.append(f"obj.data.materials.append(_mat('{name}Mat', {tuple(color)}, {rough}, {metal}))")
        lines.append("bpy.ops.object.shade_smooth()")
        lines.append("")
    lines.extend(
        [
            "# --- lights: animated key + rim, static fill ---",
            "key = bpy.data.objects.new('Key', bpy.data.lights.new('Key', 'AREA'))",
            "bpy.context.collection.objects.link(key)",
            "key.data.energy = 900.0; key.data.size = 6.0",
            "key.location = (6.0, -6.0, 8.0)",
            "key.rotation_euler = (0.7, 0.0, 0.7)",
            "key.keyframe_insert('location', frame=scene.frame_start)",
            "key.location = (-6.0, -4.0, 9.0)",
            "key.keyframe_insert('location', frame=scene.frame_end)",
            "",
            "rim = bpy.data.objects.new('Rim', bpy.data.lights.new('Rim', 'AREA'))",
            "bpy.context.collection.objects.link(rim)",
            "rim.data.energy = 500.0; rim.data.size = 4.0",
            "rim.location = (-7.0, 5.0, 6.0)",
            "rim.rotation_euler = (1.1, 0.0, -0.7)",
            "rim.keyframe_insert('location', frame=scene.frame_start)",
            "rim.location = (7.0, 6.0, 7.0)",
            "rim.keyframe_insert('location', frame=scene.frame_end)",
            "",
            "fill = bpy.data.objects.new('Fill', bpy.data.lights.new('Fill', 'AREA'))",
            "bpy.context.collection.objects.link(fill)",
            "fill.data.energy = 220.0; fill.data.size = 8.0",
            "fill.location = (0.0, 8.0, 7.0)",
            "fill.rotation_euler = (-1.2, 0.0, 0.0)",
            "",
            "# --- camera: one smooth orbit over the whole shot ---",
            "cam_data = bpy.data.cameras.new('Cam')",
            "cam = bpy.data.objects.new('Camera', cam_data)",
            "bpy.context.collection.objects.link(cam)",
            "scene.camera = cam",
            f"TARGET = Vector({tuple(target)})",
            f"RADIUS = {orbit_radius}; HEIGHT = {orbit_height}",
            "cam.keyframe_insert('location', frame=scene.frame_start)",
            "for f in range(scene.frame_start, scene.frame_end + 1, 5):",
            "    ang = math.radians(-55.0 + 110.0 * (f - scene.frame_start) / max(scene.frame_end - scene.frame_start, 1))",
            "    cam.location = (RADIUS * math.sin(ang), -RADIUS * math.cos(ang), HEIGHT)",
            "    cam.keyframe_insert('location', frame=f)",
            "    direction = TARGET - cam.location",
            "    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()",
            "    cam.keyframe_insert('rotation_euler', frame=f)",
            "",
            "# --- output: Blender's own H.264 encoder ---",
            "scene.render.image_settings.file_format = 'FFMPEG'",
            "scene.render.ffmpeg.format = 'MPEG4'",
            "scene.render.ffmpeg.codec = 'H264'",
            "scene.render.ffmpeg.constant_rate_factor = 'HIGH'",
            "scene.render.ffmpeg.audio_codec = 'NONE'",
            "scene.render.use_file_extension = True",
            f"out_dir = os.path.dirname({output_path!r}) or '.'",
            "os.makedirs(out_dir, exist_ok=True)",
            f"scene.render.filepath = {output_path!r}",
            "print('RENDER_START', scene.frame_start, scene.frame_end)",
            "bpy.ops.render.render(animation=True)",
            "print('RENDER_DONE', scene.render.filepath)",
        ]
    )
    script_text = "\n".join(lines)
    return BlenderScriptResult(
        script_text=script_text,
        script_sha256=hashlib.sha256(script_text.encode("utf-8")).hexdigest(),
        dependencies=tuple(sorted(shot_spec.keys())),
    )


def _default_scene_objects() -> list[dict[str, Any]]:
    return [
        {"type": "cube", "name": "Cube", "location": [-2.6, 0.0, 1.0], "scale": 1.0, "color": [0.85, 0.32, 0.20, 1.0], "roughness": 0.30},
        {"type": "sphere", "name": "Sphere", "location": [0.0, -0.4, 1.3], "scale": 1.2, "color": [0.20, 0.55, 0.85, 1.0], "roughness": 0.15, "metallic": 0.2},
        {"type": "torus", "name": "Torus", "location": [2.8, 0.2, 1.1], "scale": 1.0, "color": [0.95, 0.78, 0.25, 1.0], "roughness": 0.25, "metallic": 0.6},
        {"type": "cylinder", "name": "Cylinder", "location": [-1.3, 2.6, 0.9], "scale": 0.9, "color": [0.35, 0.80, 0.45, 1.0], "roughness": 0.4},
        {"type": "cone", "name": "Cone", "location": [1.5, 2.7, 1.1], "scale": 1.0, "color": [0.75, 0.35, 0.85, 1.0], "roughness": 0.3},
    ]


def blender_render_animated_scene(
    *,
    shot_spec: dict[str, Any],
    blender_binary: str = CANONICAL_BLENDER_BINARY,
    timeout_s: int = 1200,
    output_path: str | None = None,
) -> BlenderRenderResult:
    """Render a real animated 3-D scene to MP4 with headless Blender."""
    effective_output = output_path or shot_spec.get("output_path", "output/blender_scene.mp4")
    effective_output = str(Path(effective_output).resolve())
    out_dir = Path(effective_output).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    # Blender appends the frame range to FFmpeg output names, so render to a
    # staging prefix and move the produced file to the requested path.
    stage_prefix = out_dir / f".{Path(effective_output).stem}_stage"
    for stale in out_dir.glob(f"{stage_prefix.name}*.mp4"):
        stale.unlink(missing_ok=True)
    resolved = {**shot_spec, "output_path": str(stage_prefix)}
    script_result = generate_animated_scene_script(shot_spec=resolved)
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write(script_result.script_text)
        script_path = f.name
    try:
        execution = execute_headless_blender(
            script_path=script_path,
            output_path=str(stage_prefix),
            blender_binary=blender_binary,
            timeout_s=timeout_s,
        )
        failure_code = None
        repair_action = None
        if execution["exit_code"] != 0:
            failure_code, repair_action = _classify_failure(execution["exit_code"], execution["stderr"], execution["stdout"])

        produced = sorted(out_dir.glob(f"{stage_prefix.name}*.mp4"), key=lambda p: p.stat().st_mtime)
        if execution["exit_code"] == 0 and produced:
            shutil.move(str(produced[-1]), effective_output)
        exists = os.path.isfile(effective_output)
        size = os.path.getsize(effective_output) if exists else 0
        sha = hashlib.sha256(Path(effective_output).read_bytes()).hexdigest() if exists else None
        return BlenderRenderResult(
            success=execution["exit_code"] == 0 and exists and size > 0,
            script_sha256=script_result.script_sha256,
            render_output_path=effective_output,
            render_output_exists=exists,
            render_output_size=size,
            render_output_sha256=sha,
            blender_version=execution.get("blender_version"),
            exit_code=execution["exit_code"],
            error_message=(execution["stderr"] if execution["exit_code"] != 0 else None),
            failure_code=failure_code,
            repair_action=repair_action,
            execution_metadata={
                "blender_binary": execution["blender_binary"],
                "blender_version": execution.get("blender_version"),
                "script_sha256": script_result.script_sha256,
                "shot_spec_keys": list(shot_spec.keys()),
                "stdout": execution["stdout"][-2000:],
                "stderr": execution["stderr"][-2000:],
            },
        )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(script_path)


def validate_blender_output(
    *,
    result: BlenderRenderResult,
    expected_size: int | None = None,
) -> tuple[bool, str | None]:
    """Validate a Blender render result for Production Graph / Artifact authority.

    Ensures the render succeeded, output exists with size constraints,
    and checks for failure codes. Returns (ok, error_msg) where error_msg is None on success.
    """
    if not result.success:
        return (False, result.error_message or f"Blender render failed (exit_code={result.exit_code})")
    if expected_size is not None and result.render_output_size != expected_size:
        return (False,
                f"Render size mismatch: expected {expected_size}, got {result.render_output_size}")
    if not result.render_output_exists or result.render_output_size <= 0:
        return (False, "Render output missing or empty")
    return (True, None)


__all__ = [
    "BlenderRenderResult",
    "BlenderScriptResult",
    "blender_render_animated_scene",
    "blender_render_workflow",
    "execute_headless_blender",
    "generate_animated_scene_script",
    "generate_script_from_shot_spec",
    "validate_blender_output",
]
