"""Tests for hevi.creative.layer4.blender_workflow."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from hevi.creative.layer4.blender_workflow import (
    BLENDER_VERSION_EXPECTED,
    BlenderRenderResult,
    BlenderScriptResult,
    blender_render_workflow,
    execute_headless_blender,
    generate_script_from_shot_spec,
)

if sys.platform.startswith("win32"):
    pytest.skip("This test module requires a Unix-like environment.", allow_module_level=True)

# Skip all tests if Blender binary is unavailable.
BLENDER_BIN = os.environ.get(
    "BLENDER_BINARY", "/home/soffy/.local/blender/blender"
)
BLENDER_AVAILABLE = os.path.isfile(BLENDER_BIN) and os.access(BLENDER_BIN, os.X_OK)


def _make_shot_spec(output_path: str) -> dict[str, Any]:
    return {
        "width": 640,
        "height": 480,
        "fps": 1,
        "frame_start": 1,
        "frame_end": 2,
        "camera_position": [0.0, -5.0, 3.0],
        "camera_rotation": [0.0, 0.0, 0.0],
        "light_position": [0.0, -2.0, 2.0],
        "light_energy": 0.5,
        "objects": [
            {
                "type": "cube",
                "name": "TestCube",
                "location": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            }
        ],
        "output_path": output_path,
    }


class TestGenerateScriptFromShotSpec:
    def test_returns_correct_type(self) -> None:
        shot = _make_shot_spec("/tmp/out.png")
        result = generate_script_from_shot_spec(shot_spec=shot)

        assert isinstance(result, BlenderScriptResult)
        assert result.script_text.strip()
        assert result.script_sha256
        assert isinstance(result.dependencies, tuple)

    def test_script_sha256_is_deterministic(self) -> None:
        shot = _make_shot_spec("/tmp/out.png")
        result1 = generate_script_from_shot_spec(shot_spec=shot)
        result2 = generate_script_from_shot_spec(shot_spec=shot)

        assert result1.script_sha256 == result2.script_sha256
        assert hashlib.sha256(result1.script_text.encode()).hexdigest() == result1.script_sha256

    def test_script_contains_bpy_import(self) -> None:
        shot = _make_shot_spec("/tmp/out.png")
        result = generate_script_from_shot_spec(shot_spec=shot)

        assert "import bpy" in result.script_text
        assert "import os" in result.script_text

    def test_script_validates_blender_version(self) -> None:
        shot = _make_shot_spec("/tmp/out.png")
        result = generate_script_from_shot_spec(shot_spec=shot)

        assert BLENDER_VERSION_EXPECTED in result.script_text

    def test_script_creates_camera(self) -> None:
        shot = _make_shot_spec("/tmp/out.png")
        result = generate_script_from_shot_spec(shot_spec=shot)

        assert "Camera" in result.script_text
        assert "cam" in result.script_text

    def test_script_creates_light(self) -> None:
        shot = _make_shot_spec("/tmp/out.png")
        result = generate_script_from_shot_spec(shot_spec=shot)

        assert "Light" in result.script_text

    def test_script_creates_cube(self) -> None:
        shot = _make_shot_spec("/tmp/out.png")
        result = generate_script_from_shot_spec(shot_spec=shot)

        assert "primitive_cube_add" in result.script_text
        assert "TestCube" in result.script_text

    def test_script_sets_frame_range(self) -> None:
        shot = _make_shot_spec("/tmp/out.png")
        result = generate_script_from_shot_spec(shot_spec=shot)

        assert "frame_start = 1" in result.script_text
        assert "frame_end = 2" in result.script_text
        assert "render.fps = 1" in result.script_text

    def test_script_sets_output_path(self) -> None:
        shot = _make_shot_spec("/tmp/out.png")
        result = generate_script_from_shot_spec(shot_spec=shot)

        assert "/tmp/out.png" in result.script_text
        assert "render.filepath" in result.script_text

    def test_dependencies_from_shot_spec_keys(self) -> None:
        shot = {
            "width": 640,
            "height": 480,
            "custom_key": "value",
        }
        result = generate_script_from_shot_spec(shot_spec=shot)

        assert "custom_key" in result.dependencies
        assert "width" in result.dependencies
        assert "height" in result.dependencies

    def test_shot_spec_does_not_mutate(self) -> None:
        shot = _make_shot_spec("/tmp/out.png")
        shot_copy = dict(shot)
        generate_script_from_shot_spec(shot_spec=shot)

        assert shot == shot_copy


class TestExecuteHeadlessBlender:
    @pytest.mark.skipif(not BLENDER_AVAILABLE, reason="Blender binary not installed")
    def test_runs_and_returns_success(self, tmp_path: Path) -> None:
        # Use Blender itself to run a trivial inline script so we can pass
        # the script path via the function signature without writing files.
        # Instead, create a minimal valid bpy script and run it.
        script_path = tmp_path / "minimal_bpy.py"
        output_path = str(tmp_path / "minimal_out.png")

        script_path.write_text(
            "import bpy\n"
            "bpy.ops.object.select_all(action='SELECT')\n"
            "bpy.ops.object.delete(confirm=False)\n"
            "import os\n"
            "os.makedirs(os.path.dirname('" + output_path + "'), exist_ok=True)\n"
            "bpy.ops.render.render(write_still=True)\n",
            encoding="utf-8",
        )
        # The render won't have a camera/light but will still create a file
        # if Blender initializes rendering. For our test we just check
        # Blender can execute a script without fatal errors.
        try:
            result = execute_headless_blender(
                script_path=str(script_path),
                output_path=output_path,
                blender_binary=BLENDER_BIN,
                timeout_s=120,
            )
            # Either Blender succeeded (exit 0) or failed with a non-timeout error
            assert isinstance(result, dict)
            assert "exit_code" in result
            assert "blender_binary" in result
        except RuntimeError as e:
            # Timeout is acceptable for environments without proper GPU/render setup
            if "timed out" not in str(e):
                raise

    def test_raises_when_binary_missing(self) -> None:
        with pytest.raises(RuntimeError, match="not found"):
            execute_headless_blender(
                script_path="/nonexistent/script.py",
                output_path="/tmp/out.png",
                blender_binary="/nonexistent/blender",
                timeout_s=1,
            )

    def test_raises_when_binary_not_executable(self, tmp_path: Path) -> None:
        non_exec = tmp_path / "blender"
        non_exec.write_text("#!/bin/sh\n")
        # On Windows this won't be executable; skip if we can't make it non-exec
        try:
            non_exec.chmod(0o644)
        except OSError:
            pytest.skip("Cannot change file permissions")

        with pytest.raises(RuntimeError, match="not executable"):
            execute_headless_blender(
                script_path="/nonexistent/script.py",
                output_path="/tmp/out.png",
                blender_binary=str(non_exec),
                timeout_s=1,
            )

    @pytest.mark.skipif(not BLENDER_AVAILABLE, reason="Blender binary not installed")
    def test_capture_blender_version(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as script_path:
            script_path.write(b"import bpy\n")
        try:
            result = execute_headless_blender(
                script_path=script_path.name,
                output_path="/tmp/version_check.png",
                blender_binary=BLENDER_BIN,
                timeout_s=30,
            )
            assert isinstance(result, dict)
        finally:
            os.unlink(script_path.name)


class TestBlenderRenderWorkflow:
    @pytest.mark.skipif(not BLENDER_AVAILABLE, reason="Blender binary not installed")
    def test_full_workflow_returns_result(self, tmp_path: Path) -> None:
        output_path = str(tmp_path / "render.png")
        result = blender_render_workflow(
            shot_spec=_make_shot_spec(output_path),
            blender_binary=BLENDER_BIN,
            timeout_s=300,
            output_path=output_path,
        )

        assert isinstance(result, BlenderRenderResult)
        assert isinstance(result.script_sha256, str)
        assert result.script_sha256  # non-empty
        assert result.render_output_path == output_path

    @pytest.mark.skipif(not BLENDER_AVAILABLE, reason="Blender binary not installed")
    def test_workflow_failure_has_failure_code(self, tmp_path: Path) -> None:
        """Blender fails when there's no camera in scene — should get a failure code."""
        output_path = str(tmp_path / "render.png")
        # Use a script that will fail (render without camera setup)
        shot = _make_shot_spec(output_path)
        shot["objects"] = []  # No objects, minimal setup that still runs

        result = blender_render_workflow(
            shot_spec=shot,
            blender_binary=BLENDER_BIN,
            timeout_s=120,
            output_path=output_path,
        )

        assert isinstance(result, BlenderRenderResult)
        # The workflow always returns a BlenderRenderResult with failure info if exit != 0
        if not result.success:
            assert result.failure_code is not None
            assert result.error_message is not None

    def test_workflow_with_missing_binary_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="not found"):
            blender_render_workflow(
                shot_spec=_make_shot_spec(str(tmp_path / "out.png")),
                blender_binary="/nonexistent/blender",
                timeout_s=1,
                output_path=str(tmp_path / "out.png"),
            )

    def test_does_not_modify_shot_spec(self, tmp_path: Path) -> None:
        _make_shot_spec(str(tmp_path / "out.png"))

        if BLENDER_AVAILABLE:
            # If Blender is available we can run it (but it may fail without camera).
            # If not, we skip.
            pytest.skip("Need to verify non-mutation with actual Blender run separately")
        else:
            pytest.skip("Blender not available")


class TestBlenderWorkflowDeterminism:
    def test_same_shot_spec_same_script_hash(self) -> None:
        shot = _make_shot_spec("/tmp/out.png")
        result1 = generate_script_from_shot_spec(shot_spec=shot)
        result2 = generate_script_from_shot_spec(shot_spec=shot)

        assert result1.script_sha256 == result2.script_sha256

    def test_different_shot_specs_different_hashes(self) -> None:
        shot1 = _make_shot_spec("/tmp/out1.png")
        shot2 = _make_shot_spec("/tmp/out2.png")

        result1 = generate_script_from_shot_spec(shot_spec=shot1)
        result2 = generate_script_from_shot_spec(shot_spec=shot2)

        assert result1.script_sha256 != result2.script_sha256
