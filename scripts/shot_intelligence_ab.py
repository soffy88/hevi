"""Deterministic local A/B render evidence for Shot Intelligence.

This is a planning/renderability validation, not production qualification.  It
uses the same fixed inputs and a local FFmpeg render for both arms; no provider
or fixture artifact is treated as a production result.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from itertools import pairwise
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from hevi.cinematic.shot_intelligence.catalog import default_catalog
from hevi.cinematic.shot_intelligence.integration import plan_for_line
from hevi.cinematic.shot_intelligence.models import ShotIntent, ShotPlan
from hevi.cinematic.shot_intelligence.persistence import persist_plan, replay_plan
from hevi.cinematic.shot_intelligence.projections import to_ffmpeg
from hevi.cinematic.shot_intelligence.validator import validate_shot_plan

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/shot_intelligence/ab"
LINES = ("kinetic_promo", "shorts_clip", "explainer")


def _intents(line: str) -> list[ShotIntent]:
    return [
        ShotIntent(line, "opening", "establishing", "subject", target_duration_s=2.0, aspect_ratio="16:9"),
        ShotIntent(line, "proof", "action", "subject", narration_present=True, target_duration_s=2.0, aspect_ratio="16:9"),
        ShotIntent(line, "payoff", "cta", "subject", narration_present=True, target_duration_s=2.0, aspect_ratio="16:9"),
    ]


def _legacy_plan(line: str) -> ShotPlan:
    catalog = default_catalog()
    return ShotPlan(line=line, shots=(catalog[0], catalog[1], catalog[4]))


def _render(plan: ShotPlan, output: Path) -> dict[str, Any]:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return {"render_success": False, "artifact_validity": False, "error": "ffmpeg/ffprobe unavailable"}
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="hevi_shot_ab_") as temp:
        pieces: list[Path] = []
        for index, shot in enumerate(plan.shots):
            piece = Path(temp) / f"piece-{index}.mp4"
            duration = max(0.5, float(shot.duration_range_s[0] + shot.duration_range_s[1]) / 2.0)
            color = ("0x263238", "0x1565c0", "0x6a1b9a", "0x2e7d32")[index % 4]
            command = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s=640x360:r=24", "-t", f"{duration:.3f}", "-pix_fmt", "yuv420p", str(piece)]
            result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
            if result.returncode != 0:
                return {"render_success": False, "artifact_validity": False, "error": result.stderr[-500:]}
            pieces.append(piece)
        concat = Path(temp) / "concat.txt"
        concat.write_text("\n".join(f"file '{piece}'" for piece in pieces), encoding="utf-8")
        result = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(output)], capture_output=True, text=True, check=False, timeout=60)
        if result.returncode != 0:
            return {"render_success": False, "artifact_validity": False, "error": result.stderr[-500:]}
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-show_streams", "-of", "json", str(output)], capture_output=True, text=True, check=False, timeout=30)
    try:
        payload = json.loads(probe.stdout)
        duration = float(payload["format"]["duration"])
        valid = probe.returncode == 0 and output.stat().st_size > 0 and duration > 0 and any(s.get("codec_type") == "video" for s in payload.get("streams", []))
    except (ValueError, KeyError, TypeError, OSError):
        duration, valid = 0.0, False
    return {"render_success": result.returncode == 0, "artifact_validity": valid, "duration_s": duration, "sha256": _sha256(output)}


def _metrics(plan: ShotPlan) -> dict[str, Any]:
    types = [shot.shot_type for shot in plan.shots]
    framings = [shot.framing for shot in plan.shots]
    motions = [shot.camera_motion.name for shot in plan.shots]
    durations = [(shot.duration_range_s[0] + shot.duration_range_s[1]) / 2.0 for shot in plan.shots]
    repetitions = sum(a == b for a, b in pairwise(types))
    signatures = [(shot.shot_type, shot.framing, shot.camera_motion.name) for shot in plan.shots]
    return {"shot_count": len(plan.shots), "shot_type_distribution": _counts(types), "framing_distribution": _counts(framings), "motion_distribution": _counts(motions), "mean_shot_duration": sum(durations) / len(durations), "duration_variance": _variance(durations), "transition_distribution": _counts([shot.transition.name for shot in plan.shots]), "visual_variation_score": len(set(signatures)) / max(1, len(signatures)), "repetition_score": repetitions / max(1, len(types) - 1), "pacing_score": 1.0 - repetitions / max(1, len(types) - 1)}


def _counts(values: list[str]) -> dict[str, int]:
    return {value: values.count(value) for value in sorted(set(values))}


def _variance(values: list[float]) -> float:
    mean = sum(values) / max(1, len(values))
    return sum((value - mean) ** 2 for value in values) / max(1, len(values))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ["SHOT_INTELLIGENCE_ENABLED"] = "1"
    summary: dict[str, Any] = {}
    for line in LINES:
        line_dir = OUT / line
        line_dir.mkdir(parents=True, exist_ok=True)
        intents = _intents(line)
        plans = {"A": _legacy_plan(line), "B": plan_for_line(line, intents)}
        assert plans["B"] is not None
        row: dict[str, Any] = {"input": {"line": line, "seed": 0, "aspect_ratio": "16:9", "duration_s": 6.0}, "arms": {}}
        for arm, plan in plans.items():
            assert plan is not None
            round_trip = replay_plan(plan)
            if round_trip != plan:
                raise RuntimeError(f"non-deterministic persistence for {line}/{arm}")
            persist_plan(plan, line_dir / f"{arm}.shot-plan.json")
            qa = validate_shot_plan(plan)
            artifact = _render(plan, line_dir / f"{arm}.mp4")
            row["arms"][arm] = {**_metrics(plan), "qa_warnings": list(qa.warnings), "qa_status": qa.status, **artifact, "projection": to_ffmpeg(plan)}
        (line_dir / "result.json").write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        summary[line] = row
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not all(arm["render_success"] and arm["artifact_validity"] for row in summary.values() for arm in row["arms"].values()):
        return 1
    print(f"shot-intelligence A/B PASS ({len(LINES)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
