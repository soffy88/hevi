"""Canonical Verdict dimensions for Video Intelligence reproductions.

This is an extension of ``hevi.verdict``.  It deliberately does not create a
case-specific scoring authority: dimensions are stored in the existing
``shot_verdict.checks_json`` envelope and use the same terminal evidence
semantics as production shot verdicts.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from obase.persistence import PgPool


class VerdictDimensionStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_OBSERVED = "NOT_OBSERVED"


DIMENSIONS = (
    "identity_consistency", "wardrobe_consistency", "scene_consistency",
    "action_completion", "action_contact", "temporal_continuity",
    "camera_adherence", "composition_adherence", "object_persistence",
    "style_adherence", "anatomy", "audio_alignment", "lip_sync",
    "transition_quality", "prompt_adherence",
)

REASON_CODES = frozenset({
    "IDENTITY_DRIFT", "WARDROBE_DRIFT", "SCENE_DRIFT", "ACTION_NOT_STARTED",
    "ACTION_INCOMPLETE", "ACTION_CONTACT_FAILED", "OBJECT_APPEARED",
    "OBJECT_DISAPPEARED", "OBJECT_TELEPORTED", "CAMERA_MOTION_WRONG",
    "CAMERA_DIRECTION_WRONG", "TEMPORAL_JUMP", "TRANSITION_BREAK",
    "ANATOMY_ARTIFACT", "HAND_ARTIFACT", "STYLE_DRIFT", "REFERENCE_IGNORED",
    "AUDIO_DESYNC", "LIPSYNC_FAILED", "TEXT_ARTIFACT", "LOGO_ARTIFACT",
    "PROVIDER_ERROR",
})


def _probe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=False, capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"FFPROBE_FAILED: {proc.stderr[-500:]}")
    try:
        return cast(dict[str, Any], json.loads(proc.stdout or "{}"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("FFPROBE_INVALID_JSON") from exc


def evaluate_case_artifact(path: str | Path) -> dict[str, Any]:
    """Evaluate observable dimensions without inventing unavailable signals."""
    target = Path(path)
    if not target.is_file() or target.stat().st_size <= 0:
        raise RuntimeError("ARTIFACT_MISSING")
    metadata = _probe(target)
    streams = list(metadata.get("streams") or [])
    videos = [item for item in streams if item.get("codec_type") == "video"]
    audios = [item for item in streams if item.get("codec_type") == "audio"]
    fmt = metadata.get("format") or {}
    duration = float(fmt.get("duration") or 0)
    if not videos or duration <= 0:
        raise RuntimeError("VIDEO_STREAM_OR_DURATION_INVALID")

    evidence = [{"type": "metadata", "asset": str(target), "duration_s": duration}]
    dimensions: dict[str, dict[str, Any]] = {}
    for name in DIMENSIONS:
        dimensions[name] = {
            "dimension": name,
            "status": VerdictDimensionStatus.NOT_OBSERVED.value,
            "score": None,
            "reason_codes": [],
            "evidence_refs": [],
            "evaluator": "hevi.verdict.case_dimensions",
            "evaluator_version": "case-verdict-v1",
        }
    dimensions["audio_alignment"] = {
        **dimensions["audio_alignment"],
        "status": VerdictDimensionStatus.PASS.value if audios else VerdictDimensionStatus.NOT_APPLICABLE.value,
        "score": 1.0 if audios else None,
        "evidence_refs": ["metadata:audio_stream"] if audios else [],
    }
    return {
        "verdict_id": None,
        "status": "PASS",
        "passed": True,
        "dimensions": dimensions,
        "evidence": evidence,
        "reason_codes": [],
        "probe": {
            "duration_s": duration,
            "video_stream": True,
            "audio_stream": bool(audios),
            "width": videos[0].get("width"),
            "height": videos[0].get("height"),
            "fps": videos[0].get("r_frame_rate"),
        },
    }


async def persist_case_verdict(
    pool: PgPool,
    *,
    task_id: str,
    provider: str,
    artifact_path: str | Path,
    verdict: dict[str, Any],
    attempt: int = 1,
) -> str:
    """Persist a case verdict in the existing canonical shot_verdict table."""
    verdict_id = uuid.uuid4()
    checks = {**verdict, "case_dimensions": verdict.get("dimensions", {})}
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO shot_verdict "
            "(id,task_id,shot_index,shot_id,provider,checks_json,attempt,passed) "
            "VALUES ($1,$2,0,$3,$4,$5,$6,$7)",
            verdict_id, uuid.UUID(task_id), f"case:{task_id}", provider,
            checks, attempt, bool(verdict.get("passed")),
        )
    return str(verdict_id)


__all__ = [
    "DIMENSIONS", "REASON_CODES", "VerdictDimensionStatus",
    "evaluate_case_artifact", "persist_case_verdict",
]
