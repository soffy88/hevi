"""Serial, approval-gated Blender render pipeline for the SCENE3D sub-line."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .check_brief import check_brief
from .quota import quota_units

__all__ = [
    "FINAL",
    "PREVIEW",
    "TIMEOUT_S",
    "BlenderMissing",
    "NeedsApproval",
    "SceneCheckFailed",
    "build_brief",
    "render_shot",
]

PREVIEW = {"width": 720, "height": 1280, "samples": 16, "label": "preview_720p"}
FINAL = {"width": 1080, "height": 1920, "samples": 24, "label": "final_1080p"}
TIMEOUT_S = 20 * 60
ASSETS3D_ROOT = Path(os.environ.get("HEVI_ASSETS3D", "/data/soffy/assets3d"))


class NeedsApproval(RuntimeError):
    """1080p was requested before a preview was approved."""


class SceneCheckFailed(RuntimeError):
    def __init__(self, message: str, *, report: dict[str, Any]) -> None:
        super().__init__(message)
        self.report = report


class BlenderMissing(RuntimeError):
    pass


def _find_blender() -> str:
    for candidate in (
        os.environ.get("HEVI_BLENDER_BIN"),
        os.environ.get("BLENDER_BIN"),
        shutil.which("blender"),
    ):
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise BlenderMissing(
        "blender binary not found; install Blender or set HEVI_BLENDER_BIN"
    )


def build_brief(
    *,
    topic: str = "",
    quality: str = "preview",
    seconds: float = 2.0,
    fps: int = 24,
    max_triangles: int | None = None,
    max_bbox_m: list[float] | None = None,
) -> dict[str, Any]:
    profile = FINAL if quality == "final" else PREVIEW
    return {
        "topic": topic,
        "quality": quality,
        "width": profile["width"],
        "height": profile["height"],
        "samples": profile["samples"],
        "fps": int(fps),
        "duration_s": float(seconds),
        "max_triangles": int(max_triangles or (250_000 if quality == "final" else 150_000)),
        "max_bbox_m": list(max_bbox_m or [130.0, 130.0, 22.0]),
        "allow_non_manifold_prefixes": ["GROUND", "RIVER", "PARK", "ROUTE", "ASSET_"],
        "forbid_suffix": ".001",
        "require_origin_at_zero": True,
        "require_angles": True,
    }


@contextmanager
def _render_lock(root: Path) -> Iterator[dict[str, Any]]:
    """One Blender render at a time across processes (blocking file lock)."""
    import fcntl

    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "render.lock"
    started = time.monotonic()
    with lock_path.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield {"lock": str(lock_path), "wait_s": round(time.monotonic() - started, 3)}
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _assemble(frames: Path, out_mp4: Path, fps: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")
    pattern = str(frames / "frame_%04d.png")
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-framerate", str(fps), "-i", pattern,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
            str(out_mp4),
        ],
        check=True,
        capture_output=True,
        timeout=600,
    )


def render_shot(
    out_dir: str | Path,
    *,
    topic: str = "",
    quality: str = "preview",
    approved: bool = False,
    seconds: float = 2.0,
    fps: int = 24,
    glb: str = "",
    timeout_s: int = TIMEOUT_S,
) -> dict[str, Any]:
    """Render one 3D shot with the Blender sub-line.

    ``quality="final"`` requires ``approved=True`` and a prior preview in the
    same output folder, so a 1080p render cannot happen before a human has seen
    the 720p cut.  Every run is serialized and capped at 20 minutes.
    """
    if quality not in {"preview", "final"}:
        raise ValueError("quality must be 'preview' or 'final'")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if quality == "final":
        if not approved:
            raise NeedsApproval("1080p Blender render needs approved=True after preview")
        if not (out / "preview" / "measured.json").is_file():
            raise NeedsApproval("1080p render needs a finished preview in preview/ first")

    brief = build_brief(topic=topic, quality=quality, seconds=seconds, fps=fps)
    target = out if quality == "preview" else out / "final"
    target.mkdir(parents=True, exist_ok=True)
    if quality == "final":
        # keep the brief auditable next to the final frames
        brief["preview_measured"] = json.loads(
            (out / "preview" / "measured.json").read_text(encoding="utf-8")
        )

    blender = _find_blender()
    script = Path(__file__).with_name("_shot_scene.py")
    cmd = [
        blender, "-b", "--factory-startup", "--python", str(script), "--",
        "--out", str(target),
        "--width", str(brief["width"]),
        "--height", str(brief["height"]),
        "--fps", str(brief["fps"]),
        "--seconds", str(brief["duration_s"]),
        "--samples", str(brief["samples"]),
        "--angles", "3",
    ]
    if glb:
        cmd += ["--glb", glb]

    started = time.monotonic()
    with _render_lock(ASSETS3D_ROOT) as queue:
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout_s
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"blender shot exceeded the {timeout_s}s queue timeout"
            ) from exc
    wall_s = round(time.monotonic() - started, 2)
    (target / "blender.log").write_text(
        (proc.stdout or "") + "\n--- STDERR ---\n" + (proc.stderr or ""),
        encoding="utf-8",
    )
    if proc.returncode != 0:
        tail = "\n".join(((proc.stdout or "") + (proc.stderr or "")).splitlines()[-20:])
        raise RuntimeError(f"blender exited {proc.returncode}: {tail}")

    measured_path = target / "measured.json"
    if not measured_path.is_file():
        raise RuntimeError("blender finished without measured.json")
    measured = json.loads(measured_path.read_text(encoding="utf-8"))
    report = check_brief(brief, measured)
    (target / "self_check.json").write_text(
        json.dumps({"brief": brief, "report": report, "queue": queue, "wall_s": wall_s},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not report["ok"]:
        raise SceneCheckFailed(
            "scene3d Blender self-check failed: " + "; ".join(report["errors"][:5]),
            report=report,
        )

    mp4 = target / ("preview.mp4" if quality == "preview" else "final.mp4")
    _assemble(target / "frames", mp4, brief["fps"])
    return {
        "status": "ok",
        "quality": quality,
        "label": PREVIEW["label"] if quality == "preview" else FINAL["label"],
        "video": str(mp4),
        "frames_dir": str(target / "frames"),
        "angles": measured.get("angles") or [],
        "measured": measured,
        "self_check": report,
        "brief": brief,
        "queue": queue,
        "wall_s": wall_s,
        "timeout_s": timeout_s,
        "quota_units": quota_units("scene3d_blender"),
        "approved": bool(approved),
        "next": "review preview, then render_shot(quality='final', approved=True)"
        if quality == "preview" else "",
    }
