"""Manim math-explainer capability (3Blue1Brown style).

Registers one ``hevi.capabilities`` entry:

* ``video.manim_render`` — render a ManimCE scene to MP4.  Input is a
  scene ``.py`` file (``scene_file``) or inline scene source
  (``scene_code``) plus the scene class name; output is the rendered
  MP4 plus probe info (duration / resolution / render wall-time).
  Black-background geometry-and-formula explainers in the 3B1B style:
  deterministic Cairo rendering, real LaTeX formulae via MathTex
  (texlive is installed on the render host).  Silent picture only —
  narration and alignment stay with the existing LuxTTS /
  whisper_local lines.

Manim itself lives in a dedicated venv (ManimCommunity/manim, MIT;
its dependency set — moderngl, scipy, pycairo — must not perturb the
main hevi environment).  The interpreter is resolved from
``HEVI_MANIM_PYTHON`` and defaults to
``/data/soffy/venvs/manim/bin/python``.  A missing interpreter or a
failed render raises :class:`CapabilityError` with the real error —
never a fake success.

Registration note: this module registers itself on import (guarded,
idempotent).  ``hevi/capabilities/__init__.py`` is intentionally NOT
edited by this change because that file carries unrelated uncommitted
work; once that lands, move the import there and drop the import-time
call.  Same transitional pattern as ``shot.recipe_cards``.

CLI (same level as ``python -m hevi.storyfilm.oneclick``)::

    python -m hevi.capabilities.manim_render scene.py UnitCircleSine \
        --quality medium --out out_dir
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)
from hevi.capabilities.pure_helpers import (
    DEFAULT_MANIM_PYTHON,
    manim_python,
)

_Registered = False


_QUALITY_FLAGS = {
    "low": "l",        # 480p15
    "medium": "m",     # 720p30
    "high": "h",       # 1080p60
    "production": "p",  # 1440p60
}




def _probe_mp4(path: Path) -> dict[str, Any]:
    """ffprobe duration / resolution; empty dict when ffprobe is absent."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {}
    try:
        raw = subprocess.run(
            [
                ffprobe, "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", str(path),
            ],
            capture_output=True, text=True, timeout=60,
        )
        info = json.loads(raw.stdout or "{}")
    except Exception:
        return {}
    out: dict[str, Any] = {}
    fmt = info.get("format") or {}
    if fmt.get("duration"):
        out["duration_s"] = float(fmt["duration"])
    for stream in info.get("streams") or []:
        if stream.get("codec_type") == "video":
            out["width"] = int(stream.get("width", 0))
            out["height"] = int(stream.get("height", 0))
            break
    return out


def _render_manim(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    scene_name = str(params.get("scene_name", "") or "").strip()
    if not scene_name:
        raise CapabilityError("video.manim_render: params.scene_name is required")
    scene_file = str(params.get("scene_file", "") or "")
    scene_code = str(params.get("scene_code", "") or "")
    if bool(scene_file) == bool(scene_code):
        raise CapabilityError(
            "video.manim_render: give exactly one of params.scene_file / params.scene_code"
        )
    quality = str(params.get("quality", "medium") or "medium")
    if quality not in _QUALITY_FLAGS:
        raise CapabilityError(
            f"video.manim_render: unknown quality {quality!r}; "
            f"expected one of {sorted(_QUALITY_FLAGS)}"
        )
    timeout_s = float(params.get("timeout_s", 1800) or 1800)

    interpreter = manim_python()
    if not interpreter.is_file():
        raise CapabilityError(
            f"video.manim_render: manim interpreter not found at {interpreter} "
            "(set HEVI_MANIM_PYTHON to the Manim venv python)"
        )

    work = out_dir / "manim_work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    if scene_code:
        scene_py = work / "scene.py"
        scene_py.write_text(scene_code, encoding="utf-8")
    else:
        src = Path(scene_file).expanduser()
        if not src.is_file():
            raise CapabilityError(f"video.manim_render: scene_file not found: {src}")
        scene_py = work / src.name
        shutil.copyfile(src, scene_py)

    output_file = str(params.get("output_file", "") or scene_name)
    cmd = [
        str(interpreter), "-m", "manim", "render",
        f"-q{_QUALITY_FLAGS[quality]}",
        "--format=mp4",
        "--media_dir", str(work / "media"),
        "--output_file", output_file,
        str(scene_py.name), scene_name,
    ]
    fps = params.get("fps")
    if fps:
        cmd[4:4] = ["--fps", str(int(fps))]

    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=str(work), capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise CapabilityError(
            f"video.manim_render: render timed out after {timeout_s:.0f}s "
            f"(scene {scene_name})"
        ) from exc
    render_s = time.monotonic() - started
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-3000:]
        raise CapabilityError(
            f"video.manim_render: manim exited {proc.returncode} "
            f"(scene {scene_name}):\n{tail}"
        )

    produced = sorted((work / "media").rglob(f"{output_file}.mp4"))
    if not produced:
        tail = (proc.stdout or "")[-1500:]
        raise CapabilityError(
            f"video.manim_render: render reported success but no MP4 was "
            f"produced (scene {scene_name}); manim output tail:\n{tail}"
        )
    final = out_dir / f"{output_file}.mp4"
    shutil.copyfile(produced[0], final)

    probe = _probe_mp4(final)
    return CapabilityResult(
        mp4=str(final),
        duration_s=float(probe.get("duration_s", 0.0)),
        sha256=compute_sha256(final),
        qa={
            "scene_name": scene_name,
            "quality": quality,
            "width": probe.get("width"),
            "height": probe.get("height"),
            "render_seconds": round(render_s, 2),
            "mp4_bytes": final.stat().st_size,
            "manim_python": str(interpreter),
            "note": (
                "ManimCE render (ManimCommunity/manim, MIT) in the "
                "dedicated venv; deterministic Cairo rasterisation. "
                "Silent picture only — pair with LuxTTS narration + "
                "whisper_local alignment for voiced explainers."
            ),
        },
    )


def register_manim_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.manim_render",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "scene_file": {
                        "type": "string",
                        "default": "",
                        "description": "Path to a ManimCE scene .py file",
                    },
                    "scene_code": {
                        "type": "string",
                        "default": "",
                        "description": "Inline ManimCE scene source (alternative to scene_file)",
                    },
                    "scene_name": {
                        "type": "string",
                        "description": "Scene class name to render",
                    },
                    "quality": {
                        "type": "string",
                        "enum": sorted(_QUALITY_FLAGS),
                        "default": "medium",
                        "description": "low=480p15, medium=720p30, high=1080p60, production=1440p60",
                    },
                    "fps": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 120,
                        "description": "Optional fps override",
                    },
                    "output_file": {
                        "type": "string",
                        "default": "",
                        "description": "Output stem (defaults to the scene name)",
                    },
                    "timeout_s": {
                        "type": "number",
                        "minimum": 10,
                        "default": 1800,
                        "description": "Hard render timeout in seconds",
                    },
                },
                "required": ["scene_name"],
                "additionalProperties": False,
            },
            cpu_cost_hint=3.0,
            render=_render_manim,
            description=(
                "Render a ManimCE scene (3Blue1Brown-style math/science "
                "explainer: grids, geometry, LaTeX formulae) to MP4 via "
                "the dedicated Manim venv. Deterministic, CPU-only, "
                "no API cost."
            ),
            line="explainer",
        )
    )
    return ["video.manim_render"]


# Import-time registration (see module docstring for why this is not
# wired through hevi/capabilities/__init__.py yet).
register_manim_capabilities_once()


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hevi.capabilities.manim_render",
        description="Render a ManimCE scene to MP4 (video.manim_render).",
    )
    parser.add_argument("scene_file", help="Path to the scene .py file")
    parser.add_argument("scene_name", help="Scene class name")
    parser.add_argument("--quality", default="medium", choices=sorted(_QUALITY_FLAGS))
    parser.add_argument("--fps", type=int, default=None)
    parser.add_argument("--out", default="manim_out", help="Output directory")
    args = parser.parse_args(argv)

    from hevi.capabilities.registry import get

    cap = get("video.manim_render")
    params: dict[str, Any] = {
        "scene_file": args.scene_file,
        "scene_name": args.scene_name,
        "quality": args.quality,
    }
    if args.fps:
        params["fps"] = args.fps
    cap.validate_params(params)
    result = cap.render(params, Path(args.out), duration=0.0, aspect="16:9", seed=0)
    print(json.dumps({"mp4": result.mp4, "duration_s": result.duration_s,
                      "sha256": result.sha256, "qa": result.qa},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
