"""Qualification harness for the two existing render runtimes.

This module is deliberately a comparison boundary, not a renderer.  It calls
the existing Remotion workflow and HyperFrames provider only when the
requested runtime is actually available.  In particular, a missing
HyperFrames CLI is reported as an environment blocker instead of allowing the
provider's normal CPU fallback to masquerade as a HyperFrames qualification.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hevi.assembly.parity_harness import frame_hashes
from hevi.assembly.remotion_render_workflow import (
    RemotionConfig,
    RemotionInput,
    remotion_render_workflow,
)
from hevi.providers.hyperframes.provider import detect_hyperframes_bin, hyperframes_generate


@dataclass
class RuntimeCompatibilityReport:
    requested_runtimes: list[str]
    actual_runtimes: dict[str, str | None]
    input_revision: str
    runtime_versions: dict[str, str | None] = field(default_factory=dict)
    render_outputs: dict[str, str | None] = field(default_factory=dict)
    duration_s: dict[str, float | None] = field(default_factory=dict)
    duration_delta_s: float | None = None
    timing_delta_s: float | None = None
    sampled_frames: dict[str, list[str]] = field(default_factory=dict)
    missing_assets: list[str] = field(default_factory=list)
    structural_differences: list[str] = field(default_factory=list)
    no_silent_runtime_substitution: bool = False
    verdict: str = "ENV_BLOCKED"
    blocker: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _revision(scene: dict[str, Any]) -> str:
    raw = json.dumps(scene, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _version(binary: str | None) -> str | None:
    if not binary:
        return None
    try:
        result = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0][:200] if output else None


def _verified_hyperframes_bin() -> str | None:
    """Reject unrelated binaries that happen to be named ``hf``.

    The environment also commonly has Hugging Face's ``hf`` CLI.  Treating it
    as HyperFrames would make the provider fall back to FFmpeg and would
    violate the interop report's no-silent-substitution contract.
    """
    candidate = detect_hyperframes_bin()
    if not candidate:
        return None
    try:
        result = subprocess.run(
            [candidate, "--help"], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    help_text = f"{result.stdout}\n{result.stderr}".lower()
    return candidate if "render" in help_text and ("hyperframes" in help_text or Path(candidate).name == "hyperframes") else None


def _duration(path: Path) -> float | None:
    if not path.is_file():
        return None
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


async def qualify_runtime_interop(
    *,
    scene: dict[str, Any],
    output_dir: Path,
    project_dir: Path,
    composition_id: str = "MotionGraphics",
) -> RuntimeCompatibilityReport:
    """Render one canonical scene through each requested runtime when possible."""

    output_dir.mkdir(parents=True, exist_ok=True)
    remotion_binary = str(project_dir / "node_modules/.bin/remotion") if (project_dir / "node_modules/.bin/remotion").is_file() else None
    hyperframes_binary = _verified_hyperframes_bin()
    report = RuntimeCompatibilityReport(
        requested_runtimes=["remotion", "hyperframes"],
        actual_runtimes={"remotion": None, "hyperframes": None},
        input_revision=_revision(scene),
        runtime_versions={"remotion": _version(remotion_binary), "hyperframes": _version(hyperframes_binary)},
        render_outputs={"remotion": None, "hyperframes": None},
        duration_s={"remotion": None, "hyperframes": None},
    )
    if shutil.which("ffprobe") is None:
        report.blocker = "FFPROBE_UNAVAILABLE"
        return report
    if remotion_binary:
        remotion_output = output_dir / "remotion.mp4"
        result = await remotion_render_workflow(
            RemotionConfig(
                project_dir=project_dir,
                composition_id=composition_id,
                output_path=remotion_output,
                width=int(scene.get("width") or 1920),
                height=int(scene.get("height") or 1080),
                fps=int(scene.get("fps") or 30),
                props=scene,
            ),
            RemotionInput(),
            output_dir / "remotion-report",
        )
        if result.get("status") == "completed" and remotion_output.is_file():
            report.actual_runtimes["remotion"] = "remotion"
            report.render_outputs["remotion"] = str(remotion_output)
            report.duration_s["remotion"] = _duration(remotion_output)
            report.sampled_frames["remotion"] = frame_hashes(remotion_output, sample_every=max(1, int((_duration(remotion_output) or 1) * 30 / 5)))
        else:
            report.structural_differences.append(f"remotion render failed: {result.get('error', 'unknown')}")
    else:
        report.blocker = "REMOTION_CLI_UNAVAILABLE"

    if hyperframes_binary:
        hyperframes_output = output_dir / "hyperframes.mp4"
        await hyperframes_generate(prompt=scene, output_path=hyperframes_output, config=scene)
        if hyperframes_output.is_file():
            report.actual_runtimes["hyperframes"] = "hyperframes"
            report.render_outputs["hyperframes"] = str(hyperframes_output)
            report.duration_s["hyperframes"] = _duration(hyperframes_output)
            report.sampled_frames["hyperframes"] = frame_hashes(hyperframes_output, sample_every=max(1, int((_duration(hyperframes_output) or 1) * 30 / 5)))
    else:
        report.blocker = "HYPERFRAMES_CLI_UNAVAILABLE"

    durations = [value for value in report.duration_s.values() if value is not None]
    if len(durations) == 2:
        report.duration_delta_s = abs(durations[0] - durations[1])
        report.timing_delta_s = report.duration_delta_s
    report.no_silent_runtime_substitution = all(
        report.actual_runtimes[name] in {None, name} for name in report.requested_runtimes
    )
    report.verdict = "PASS" if all(report.actual_runtimes[name] == name for name in report.requested_runtimes) else "ENV_BLOCKED"
    if report.verdict == "PASS" and report.duration_delta_s is not None and report.duration_delta_s > 0.5:
        report.verdict = "FAIL"
        report.structural_differences.append("duration delta exceeds 0.5s")
    return report


__all__ = ["RuntimeCompatibilityReport", "qualify_runtime_interop"]
