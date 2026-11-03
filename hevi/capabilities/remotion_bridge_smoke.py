"""Remotion bridge smoke test (``video.remotion_bridge_smoke``).

Clean-room restatement of the tutorial method in
``hevi-vs-3d-cartoon-tutorial-6steps.md`` section 2 item 1: before a
style is trusted, a seconds-long vertical test render must come out
of the real pipeline. This module exercises the existing bridge
``hevi.video.remotion_service`` end to end against the fixture-driven
``MotionGraphics`` composition already present in ``hevi-remotion/``:
a 3-second 9:16 render whose output is verified with ffprobe
(resolution, frame rate, frame count, duration).

Honest scope, recorded in every evidence file:

* The bridge half is proven here: manifest -> ``npx remotion
  render`` -> verified MP4. The ``hevi-remotion`` project carries
  no ``three`` dependency, so no Three.js geometry is rendered by
  this smoke; the Three.js geometry half stays unproven and is
  recorded as such, never claimed.
* A missing render environment (no Node, no ``node_modules``, no
  ffprobe) fails closed with ``CapabilityError`` and an
  ``environment_missing`` record. Nothing is installed, nothing is
  downloaded, and a missing environment is never reported as a
  pass.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REMOTION_DIR = _REPO_ROOT / "hevi-remotion"


def _resolve_node_bin(explicit: str | Path | None = None) -> Path:
    """Find a Node binary. Raises CapabilityError when none is found."""
    candidates: list[Path] = []
    env_bin = os.environ.get("HEVI_NODE_BIN")
    if env_bin:
        candidates.append(Path(env_bin))
    if explicit is not None:
        candidates.append(Path(explicit))
    which = shutil.which("node")
    if which:
        candidates.append(Path(which))
    nvm_root = Path.home() / ".nvm" / "versions" / "node"
    if nvm_root.is_dir():
        for version_dir in sorted(nvm_root.iterdir(), reverse=True):
            candidates.append(version_dir / "bin" / "node")
    candidates.append(Path.home() / ".local" / "bin" / "node")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise CapabilityError(
        "video.remotion_bridge_smoke: no Node.js binary found "
        "(HEVI_NODE_BIN, PATH, or ~/.nvm); environment_missing"
    )


@contextmanager
def _node_on_path(node_bin: Path) -> Iterator[None]:
    previous = os.environ.get("PATH", "")
    os.environ["PATH"] = str(node_bin.parent) + os.pathsep + previous
    try:
        yield
    finally:
        os.environ["PATH"] = previous


def _ffprobe_facts(mp4_path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise CapabilityError(
            "video.remotion_bridge_smoke: ffprobe not found; environment_missing"
        )
    result = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate,nb_frames,codec_name",
            "-show_entries", "format=duration",
            "-of", "json",
            str(mp4_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise CapabilityError(
            f"video.remotion_bridge_smoke: ffprobe failed: {result.stderr.strip()}"
        )
    try:
        probe = json.loads(result.stdout)
        stream = probe["streams"][0]
        duration = float(probe["format"]["duration"])
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise CapabilityError(
            f"video.remotion_bridge_smoke: unparseable ffprobe output: {exc}"
        ) from exc
    num, _, den = str(stream.get("avg_frame_rate", "0/1")).partition("/")
    fps = float(num) / float(den) if den and float(den) else 0.0
    try:
        frames = int(stream.get("nb_frames", "0"))
    except ValueError:
        frames = 0
    return {
        "codec": stream.get("codec_name"),
        "width": int(stream.get("width", 0)),
        "height": int(stream.get("height", 0)),
        "fps": fps,
        "nb_frames": frames,
        "duration_s": duration,
    }


def _threejs_present(remotion_dir: Path) -> bool:
    package_json = remotion_dir / "package.json"
    if not package_json.is_file():
        return False
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except ValueError:
        return False
    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    return "three" in deps or "@remotion/three" in deps


def run_remotion_bridge_smoke(
    output_dir: str | Path,
    *,
    width: int = 540,
    height: int = 960,
    fps: int = 30,
    duration_frames: int = 90,
    node_bin: str | Path | None = None,
) -> dict[str, Any]:
    """Render a 3-second vertical smoke MP4 through the Remotion bridge.

    Returns the evidence record. Raises ``CapabilityError`` on any
    failure, including a missing render environment. Never returns
    a fabricated success.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    node = _resolve_node_bin(node_bin)
    if not _REMOTION_DIR.is_dir():
        raise CapabilityError(
            f"video.remotion_bridge_smoke: hevi-remotion not found at {_REMOTION_DIR}; "
            "environment_missing"
        )
    if not (_REMOTION_DIR / "node_modules").is_dir():
        raise CapabilityError(
            "video.remotion_bridge_smoke: hevi-remotion/node_modules is missing; "
            "environment_missing (nothing was installed)"
        )
    try:
        node_version = subprocess.run(
            [str(node), "--version"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        raise CapabilityError(
            f"video.remotion_bridge_smoke: node --version failed: {exc}"
        ) from exc
    try:
        remotion_version = json.loads(
            (_REMOTION_DIR / "package.json").read_text(encoding="utf-8")
        )["dependencies"]["remotion"]
    except (KeyError, ValueError, OSError):
        remotion_version = "unknown"

    manifest = {
        "spec": {
            "composition_id": "MotionGraphics",
            "width": width,
            "height": height,
            "fps": fps,
            "duration_frames": duration_frames,
            "layers": [
                {
                    "id": "bg",
                    "type": "background",
                    "color": "#1a2b4a",
                    "start_frame": 0,
                    "end_frame": duration_frames,
                },
                {
                    "id": "smoke",
                    "type": "text",
                    "text": "SMOKE",
                    "x": 50,
                    "y": 45,
                    "fontSize": 48,
                    "start_frame": 0,
                    "end_frame": duration_frames,
                    "animation": "scale",
                },
            ],
        }
    }
    mp4_path = out_dir / "remotion_bridge_smoke.mp4"
    from hevi.video.remotion_service import render_remotion

    with _node_on_path(node):
        try:
            render_remotion(
                manifest,
                mp4_path,
                composition="MotionGraphics",
                width=width,
                height=height,
                fps=fps,
                codec="h264",
                image_format="jpeg",
                quality=80,
            )
        except Exception as exc:  # bridge raises RuntimeError; never swallow it
            raise CapabilityError(
                f"video.remotion_bridge_smoke: Remotion render failed: {exc}"
            ) from exc
    if not mp4_path.is_file():
        raise CapabilityError(
            "video.remotion_bridge_smoke: render returned but no MP4 exists"
        )
    facts = _ffprobe_facts(mp4_path)
    expected_duration = duration_frames / fps
    failures = []
    if (facts["width"], facts["height"]) != (width, height):
        failures.append(
            f"resolution {facts['width']}x{facts['height']}, expected {width}x{height}"
        )
    if abs(facts["fps"] - fps) > 0.01:
        failures.append(f"fps {facts['fps']}, expected {fps}")
    if abs(facts["nb_frames"] - duration_frames) > 1:
        failures.append(f"frames {facts['nb_frames']}, expected {duration_frames}")
    if abs(facts["duration_s"] - expected_duration) > 0.2:
        failures.append(
            f"duration {facts['duration_s']:.3f}s, expected {expected_duration:.3f}s"
        )
    if failures:
        raise CapabilityError(
            "video.remotion_bridge_smoke: output verification failed: " + "; ".join(failures)
        )
    evidence: dict[str, Any] = {
        "ok": True,
        "mp4": str(mp4_path),
        "sha256": compute_sha256(mp4_path),
        "composition": "MotionGraphics",
        "width": width,
        "height": height,
        "fps": fps,
        "duration_frames": duration_frames,
        "ffprobe": facts,
        "node_version": node_version,
        "node_bin": str(node),
        "remotion_version": remotion_version,
        "threejs_present_in_hevi_remotion": _threejs_present(_REMOTION_DIR),
        "threejs_geometry": "not_rendered",
        "threejs_note": (
            "hevi-remotion carries no three dependency; this smoke proves "
            "the Remotion timeline bridge only. The Three.js geometry half "
            "stays unproven."
        ),
        "fixture": manifest,
    }
    (out_dir / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return evidence


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    evidence = run_remotion_bridge_smoke(
        out_dir,
        width=int(params.get("width", 540)),
        height=int(params.get("height", 960)),
        fps=int(params.get("fps", 30)),
        duration_frames=int(params.get("duration_frames", 90)),
    )
    return CapabilityResult(
        duration_s=float(evidence["ffprobe"]["duration_s"]),
        sha256=evidence["sha256"],
        qa={
            "evidence_json": str(Path(out_dir) / "evidence.json"),
            "ok": True,
        },
    )


def register_remotion_bridge_smoke_capabilities_once() -> list[str]:
    """Register ``video.remotion_bridge_smoke`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.remotion_bridge_smoke",
            kind="line",
            aspects=["9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "fps": {"type": "integer"},
                    "duration_frames": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=True,
            description=(
                "Remotion bridge smoke: a 3-second vertical render through "
                "hevi.video.remotion_service, verified with ffprobe. A "
                "missing render environment fails closed; the Three.js "
                "geometry half is recorded as unproven, never claimed."
            ),
            line="video",
        )
    )
    return ["video.remotion_bridge_smoke"]


register_remotion_bridge_smoke_capabilities_once()
