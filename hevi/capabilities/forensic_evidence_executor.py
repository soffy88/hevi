"""Deterministic forensic evidence executor (``qa.forensic_evidence_executor``).

Clean-room rewrite of the *deterministic* layer of the method in
the rea-video field report (``hevi-vs-rea-video.md`` section 2.1
item 1): before any looking reviewer or vision model is asked,
cheap measurements are taken from the frames themselves. This
executor measures three of them, locally, with ffmpeg plus
numpy/PIL only:

1. Shot cuts: the mean absolute difference between consecutive
   downscaled grayscale frames; a jump above a caller-supplied
   threshold is a cut.
2. Frozen runs: consecutive frames whose difference stays below
   a caller-supplied epsilon for at least a caller-supplied run
   length.
3. Repeated-frame ratio: the fraction of consecutive pairs
   below epsilon, from which a source frame rate is estimated
   (a 24fps source carried at 30fps shows roughly one repeated
   frame in five).

Thresholds have no defaults: no author-reported number is used,
and a missing threshold raises instead of passing. The executor
never judges a production method -- it only returns the
evidence record that the vocabulary and evidence-priority gates
judge. It downloads nothing, calls no model, and holds no key.
No upstream accuracy figure is used as a threshold.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise CapabilityError(f"forensic executor requires {name} on PATH")
    return path


def _probe(path: Path) -> dict[str, Any]:
    ffprobe = _require_tool("ffprobe")
    out = subprocess.run(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=r_frame_rate,width,height,nb_frames",
            "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True, timeout=60,
    )
    data = json.loads(out.stdout)
    stream = (data.get("streams") or [{}])[0]
    num, _, den = stream.get("r_frame_rate", "0/1").partition("/")
    fps = float(num) / float(den) if float(den or 0) else 0.0
    return {
        "fps": fps,
        "width": stream.get("width"),
        "height": stream.get("height"),
        "nb_frames": stream.get("nb_frames"),
        "duration_s": float((data.get("format") or {}).get("duration", 0.0)),
    }


def _extract_frames(path: Path, work: Path) -> list[Path]:
    ffmpeg = _require_tool("ffmpeg")
    frames_dir = work / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg, "-v", "error", "-y", "-i", str(path),
            str(frames_dir / "f%05d.png"),
        ],
        check=True, timeout=120,
    )
    return sorted(frames_dir.glob("f*.png"))


def _frame_vector(png: Path) -> np.ndarray:
    with Image.open(png) as image:
        gray = image.convert("L").resize((32, 18))
        return np.asarray(gray, dtype=np.float32).ravel()


def analyze_video(
    path: str | Path,
    *,
    cut_threshold: float,
    frozen_epsilon: float,
    min_frozen_frames: int,
) -> dict[str, Any]:
    """Measure cuts, frozen runs, and repeated frames of a video file."""
    if cut_threshold is None or frozen_epsilon is None or min_frozen_frames is None:
        raise CapabilityError(
            "cut_threshold, frozen_epsilon and min_frozen_frames are all "
            "required: this executor uses no default thresholds"
        )
    if min_frozen_frames < 2:
        raise CapabilityError("min_frozen_frames must be at least 2")
    video = Path(path)
    if not video.is_file():
        raise CapabilityError(f"video file not found: {video}")
    probe = _probe(video)
    with tempfile.TemporaryDirectory(prefix="forensic-") as tmp:
        frames = _extract_frames(video, Path(tmp))
        if len(frames) < 2:
            raise CapabilityError("video yielded fewer than 2 frames")
        vectors = [_frame_vector(frame) for frame in frames]
    diffs = [
        float(np.mean(np.abs(vectors[i + 1] - vectors[i])))
        for i in range(len(vectors) - 1)
    ]
    fps = probe["fps"] or 0.0
    cuts = [
        {"after_frame": i + 1, "time_s": round((i + 1) / fps, 4) if fps else None,
         "difference": round(diffs[i], 3)}
        for i, diff in enumerate(diffs)
        if diff > cut_threshold
    ]
    frozen_runs: list[dict[str, Any]] = []
    run_start: int | None = None
    for i, diff in enumerate(diffs):
        if diff <= frozen_epsilon:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None:
                length = i - run_start + 1
                if length >= min_frozen_frames:
                    frozen_runs.append(
                        {"start_frame": run_start, "end_frame": i, "frames": length}
                    )
                run_start = None
    if run_start is not None:
        length = len(diffs) - run_start + 1
        if length >= min_frozen_frames:
            frozen_runs.append(
                {"start_frame": run_start, "end_frame": len(diffs), "frames": length}
            )
    repeated = sum(1 for diff in diffs if diff <= frozen_epsilon)
    repeat_ratio = repeated / len(diffs) if diffs else 0.0
    estimated_fps = round(fps * (1.0 - repeat_ratio), 3) if fps else None
    return {
        "video": str(video),
        "probe": probe,
        "frame_count": len(frames),
        "cut_threshold": cut_threshold,
        "frozen_epsilon": frozen_epsilon,
        "cuts": cuts,
        "frozen_runs": frozen_runs,
        "repeated_frame_ratio": round(repeat_ratio, 4),
        "estimated_source_fps": estimated_fps,
        "evidence_kinds": ["histogram_cut", "frozen_frame", "frame_rate_fingerprint"],
        "note": (
            "Evidence only. Thresholds are caller-supplied; no production-"
            "method judgement is made here."
        ),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = analyze_video(
        params.get("video"),
        cut_threshold=params.get("cut_threshold"),
        frozen_epsilon=params.get("frozen_epsilon"),
        min_frozen_frames=params.get("min_frozen_frames"),
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "forensic_evidence.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "frame_count": report["frame_count"],
            "cuts": len(report["cuts"]),
        },
    )


_Registered = False


def register_forensic_evidence_executor_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.forensic_evidence_executor",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "video": {"type": "string"},
                    "cut_threshold": {"type": "number"},
                    "frozen_epsilon": {"type": "number"},
                    "min_frozen_frames": {"type": "integer"},
                },
                "required": ["video", "cut_threshold", "frozen_epsilon",
                             "min_frozen_frames"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Deterministic forensic evidence executor (rea-video "
                "B1, clean-room): local cut, frozen-run, and "
                "repeated-frame measurements with caller-supplied "
                "thresholds; evidence only, no judgement. See "
                "REA_VIDEO_ATTRIBUTION.md."
            ),
            line="qa",
        )
    )
    return ["qa.forensic_evidence_executor"]


register_forensic_evidence_executor_capabilities_once()
