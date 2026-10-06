"""P9.1.d — Manim adapter: execute only.

Manim was already QUALIFIED end to end (P9.1.b) through the P8 chain. This adapter
gives it the same shape as the others so the framework can drive all five uniformly.
It returns a locator; the framework proves the artifact.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from hevi.qualification.models import (
    AdapterAvailability,
    AdapterFailure,
    Availability,
    ExecutionResult,
    ExecutionState,
    QualificationRequest,
    RuntimeUnavailable,
)
from hevi.qualification.providers._shared import check_locator, result_for, unavailable

SCENE_SOURCE = '''"""A real manim scene, rendered for provider qualification."""

from manim import Create, Dot, Line, ORIGIN, RIGHT, Scene, Text, UP, Write


class HeviQualificationScene(Scene):
    def construct(self):
        title = Text("HEVI qualification")
        self.play(Write(title))
        self.play(title.animate.scale(0.5).to_edge(UP))
        line = Line(ORIGIN - 4 * RIGHT, ORIGIN + 4 * RIGHT, color="#3B82F6")
        dot = Dot(ORIGIN, radius=0.18, color="#F59E0B")
        self.play(Create(line))
        self.play(Create(dot), dot.animate.move_to(RIGHT * 4))
        self.wait(0.2)
'''


def manim_bin() -> str:
    """The declared runtime entry point, or "" when absent."""
    bundled = Path(__file__).resolve().parents[3] / ".venv" / "bin" / "manim"
    if bundled.exists():
        return str(bundled)
    return shutil.which("manim") or ""


class ManimAdapter:
    """Executes `manim render`. Returns a locator."""

    provider_id = "manim"

    def available(self) -> AdapterAvailability:
        if not manim_bin():
            return unavailable("manim_not_found:no interpreter entry point")
        return AdapterAvailability(Availability.AVAILABLE)

    def execute(self, request: QualificationRequest) -> ExecutionResult:
        import subprocess

        availability = self.available()
        if not availability.can_run:
            raise RuntimeUnavailable(availability.reason)

        target = Path(request.output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        scene_dir = target.parent / "manim_scene_src"
        scene_dir.mkdir(parents=True, exist_ok=True)
        (scene_dir / "scene.py").write_text(SCENE_SOURCE, encoding="utf-8")

        proc = subprocess.run(
            [manim_bin(), "render", "scene.py", "HeviQualificationScene",
             "--media_dir", "out", "-ql", "--format", "mp4"],
            cwd=str(scene_dir), capture_output=True, timeout=request.timeout_s, check=False,
        )
        if proc.returncode != 0:
            raise AdapterFailure(
                ExecutionState.FAILED,
                f"exit_{proc.returncode}:{proc.stderr.decode(errors='replace')[:200]}",
            )
        produced = [
            p for p in sorted((scene_dir / "out").rglob("HeviQualificationScene.mp4"))
            if "partial_movie_files" not in str(p)
        ]
        if not produced:
            raise AdapterFailure(
                ExecutionState.NO_ARTIFACT, "manim exited 0 but wrote no mp4"
            )
        target.write_bytes(produced[-1].read_bytes())
        check_locator(request, self.provider_id)
        return result_for(
            request,
            {"runtime_class": "local_process", "binary": manim_bin(), "exit_code": "0"},
        )


__all__ = ["SCENE_SOURCE", "ManimAdapter", "manim_bin"]
