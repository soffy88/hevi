"""Production Graph adapter for the existing HEVI visual quality authority."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from hevi.creative.layer4.incident_store import track_task_failure
from hevi.production.artifacts import Artifact, ArtifactManifest
from hevi.quality.visual_quality import analyze_video, evaluate_visual_quality


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def execute_visual_quality_task(task: dict[str, Any], pool: Any) -> dict[str, Any]:
    config = dict(task.get("config_json") or {})
    production_id = str(config.get("production_id") or task.get("id") or "visual-quality")
    output_dir = Path(config.get("output_dir") or Path("output/tasks") / str(task.get("id") or production_id))
    output_dir.mkdir(parents=True, exist_ok=True)
    cached = config.get("visual_quality_report")
    cached_manifest = config.get("artifact_manifest")
    if isinstance(cached, dict) and isinstance(cached_manifest, dict):
        manifest = ArtifactManifest.model_validate(cached_manifest)
        if all(Path(item.path).is_file() and Path(item.path).stat().st_size > 0 for item in manifest.artifacts):
            return {"status": "completed", "config_json": config, "artifacts": [a.model_dump(mode="json") for a in manifest.artifacts],
                    "report": {"visual_quality": cached}, "review_pending": False}
    source = Path(str(config.get("source_video_path") or ""))
    evidence_path = output_dir / "visual_quality_evidence.json"
    try:
        analysis_source = source
        if source.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            analysis_source = output_dir / "image_quality_probe.mp4"
            subprocess.run(
                ["ffmpeg", "-y", "-loop", "1", "-i", str(source), "-t", "1", "-r", "1",
                 "-pix_fmt", "yuv420p", "-c:v", "libx264", str(analysis_source)],
                capture_output=True, check=True,
            )
        audio_duration = config.get("audio_duration_ms")
        measurements = analyze_video(
            analysis_source,
            max_frames=int(config.get("max_analysis_frames") or 32),
            audio_duration_ms=int(audio_duration) if audio_duration is not None else None,
            shot_boundaries_ms=[int(x) for x in config.get("shot_boundaries_ms") or []],
        )
        decision = evaluate_visual_quality(
            measurements,
            planned_shot_count=config.get("planned_shot_count"),
            allow_static=bool(config.get("allow_static", False)),
        )
        source_sha = _sha(source)
        report = {
            "source_video_artifact_id": str(config.get("source_video_artifact_id") or ""),
            "source_audio_artifact_id": str(config.get("source_audio_artifact_id") or ""),
            "source_subtitle_artifact_id": str(config.get("source_subtitle_artifact_id") or ""),
            "source_type": str(config.get("source_type") or "generic"),
            "source_sha256": source_sha,
            "measurements": measurements.model_dump(mode="json"),
            "policy": decision.model_dump(mode="json"),
            "policy_owner": "HEVI_LAYER4",
            "allow_static": bool(config.get("allow_static", False)),
            "v2v_contract_compatible": True,
        }
        evidence_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        if decision.status == "BLOCK":
            incident_id = track_task_failure(
                production_run_id=str(task.get("id") or production_id), node_key="visual_quality",
                failure="VISUAL_QUALITY_BLOCK", evidence={"reasons": list(decision.reasons), "evidence_path": str(evidence_path)},
                owner_id="hevi_layer4",
            )
            return {"status": "failed", "error": "visual quality policy blocked artifact", "review_pending": False,
                    "artifacts": [], "report": {"visual_quality": report, "repair_incident_id": incident_id}}
        evidence_artifact = Artifact.from_path(
            evidence_path, kind="quality_evidence", media_type="application/json", primary=True,
            logical_role="visual_quality_evidence", parent_artifact_ids=[x for x in [config.get("source_video_artifact_id"), config.get("source_audio_artifact_id"), config.get("source_subtitle_artifact_id")] if x],
            metadata={"source_sha256": source_sha, "decision": decision.status, "policy_owner": "HEVI_LAYER4"},
        )
        manifest = ArtifactManifest(
            production_id=production_id, revision_id=str(task.get("revision_id") or ""),
            attempt_id=str(task.get("_attempt_id") or task.get("id") or ""), tenant_id="HEVI_LAYER4", artifacts=[evidence_artifact],
        )
        config.update({"artifact_manifest": manifest.model_dump(mode="json"), "visual_quality_report": report})
        return {"status": "completed", "config_json": config, "artifacts": [evidence_artifact.model_dump(mode="json")],
                "report": {"visual_quality": report}, "review_pending": decision.status == "WARN"}
    except Exception as exc:
        incident_id = track_task_failure(
            production_run_id=str(task.get("id") or production_id), node_key="visual_quality",
            failure="VISUAL_QUALITY_ANALYSIS_FAILED", evidence={"error": str(exc)}, owner_id="hevi_layer4",
        )
        return {"status": "failed", "error": str(exc), "review_pending": False, "artifacts": [],
                "report": {"repair_incident_id": incident_id}}


__all__ = ["execute_visual_quality_task"]
