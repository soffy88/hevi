"""Executable OpenMontage-style production transaction.

The old montage planner is intentionally kept for backwards compatibility.
This module is the execution path: it calls HEVI's real studio stage adapters,
writes per-stage checkpoints, pauses at human gates, and refuses to claim a
compose/publish result without a verified local artifact.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.montage.oprim import (
    load_pipeline_manifest,
    read_checkpoint,
    update_checkpoint_approval,
    write_checkpoint,
)
from hevi.montage.schemas import Artifact, ArtifactType, CheckpointState
from hevi.studio.stages import (
    stage_assets,
    stage_dispatch,
    stage_edit_plan,
    stage_intake,
    stage_publish,
    stage_research,
    stage_runtime,
    stage_script,
    stage_timeline,
    stage_watch,
)

logger = logging.getLogger(__name__)


@dataclass
class AgenticMontageConfig:
    pipeline: str = "animated-explainer"
    budget_usd: float = 2.0
    execute: bool = False
    auto_approve: bool = False
    resume: bool = True
    manifest_path: str | None = None


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        raw = value.model_dump()
        return dict(raw) if isinstance(raw, dict) else {}
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _manifest_path(config: dict[str, Any]) -> Path:
    explicit = config.get("manifest_path")
    if explicit:
        return Path(str(explicit))
    return Path(__file__).resolve().parents[3] / "tools" / "pipeline_defs" / f"{config.get('pipeline', 'animated-explainer')}.yaml"


def _safe_fingerprint(pipeline: str, config: dict[str, Any], data: dict[str, Any]) -> str:
    excluded = {"caller", "llm", "translator", "renderer", "tool_handlers", "stage_handlers", "backlot_log"}
    shape = {
        "pipeline": pipeline,
        "config": {key: value for key, value in config.items() if key not in excluded and not callable(value)},
        "input_keys": sorted(key for key in data if key not in excluded),
        "input_shapes": {
            key: len(value) if isinstance(value, (list, tuple, dict, str)) else type(value).__name__
            for key, value in data.items()
            if key not in excluded
        },
    }
    return hashlib.sha256(json.dumps(shape, sort_keys=True, default=str).encode()).hexdigest()[:24]


async def _notify(on_step: Any, event: dict[str, Any]) -> None:
    if on_step is None:
        return
    result = on_step(event)
    if inspect.isawaitable(result):
        await result


def _emit_backlot(data: dict[str, Any], *, run_id: str, stage: str, event_type: str, payload: dict[str, Any]) -> None:
    log = data.get("backlot_log")
    if log is None:
        return
    try:
        from hevi.backlot import BacklotEvent

        log.emit(BacklotEvent(run_id=run_id, stage=stage, event_type=event_type, payload=payload))
    except Exception as exc:  # best-effort observability must not stop production
        logger.warning("montage backlot event failed: %s", exc)


async def _custom_or(
    name: str,
    default: Any,
    data: dict[str, Any],
    context: dict[str, Any],
    handlers: Mapping[str, Any],
) -> dict[str, Any]:
    handler = handlers.get(name)
    result = default(data, context) if handler is None else handler(data, context)
    result = await result if inspect.isawaitable(result) else result
    if not isinstance(result, dict):
        return {"status": "failed", "reason": f"stage {name} returned non-object"}
    return dict(result)


def _proposal(data: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    concepts = list(data.get("concepts") or [])
    topic = str(data.get("topic") or "HEVI production")
    review = data.get("source_media_review") or {}
    research = data.get("research") or {}
    evidence = str(
        review.get("content")
        or review.get("pacing")
        or research.get("context")
        or research.get("topic")
        or topic
    ).strip()
    if not concepts:
        concepts = [{
            "concept_id": "concept-1",
            "title": topic,
            "angle": "事实解释：先建立问题，再用可追溯证据推进",
            "confidence": "planned",
            "grounded_in": evidence[:240],
            "generated_by": "hevi-local-planner",
        }]
    angles = [
        ("concept-2", "问题驱动：从冲突/反常识切入"),
        ("concept-3", "案例叙事：用人物或真实素材承载信息"),
    ]
    existing_ids = {str(item.get("concept_id")) for item in concepts if isinstance(item, dict)}
    for concept_id, angle in angles:
        if len(concepts) >= 3:
            break
        if concept_id not in existing_ids:
            concepts.append({
                "concept_id": concept_id,
                "title": topic,
                "angle": angle,
                "confidence": "planned",
                "grounded_in": evidence[:240],
                "generated_by": "hevi-local-planner",
            })
    return {
        "proposal": {
            "concept_options": concepts,
            "selected_concept": concepts[0],
            "budget_usd": float(data.get("budget_usd") or 2.0),
            "approval": "pending",
        },
        "proposal_status": "planned",
    }


def _idea(data: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    media_path = str(data.get("media_path") or "").strip()
    topic = str(data.get("topic") or data.get("source_text") or "").strip()
    if not topic and media_path:
        topic = Path(media_path).stem or "source media"
    if not topic:
        return {"status": "failed", "reason": "topic or source_text required"}
    result: dict[str, Any] = {
        "brief": {
            "topic": topic,
            "duration_s": float(data.get("duration_s") or data.get("target_duration_s") or 40.0),
            "aspect_ratio": str(data.get("aspect_ratio") or "9:16"),
            "music_opt_out": bool(data.get("music_opt_out", False)),
        },
        "brief_status": "planned",
    }
    if media_path and "source_media_review" not in data:
        from hevi.montage.oprim import analyze_reference_video, sample_frames

        review = analyze_reference_video(media_path)
        result["source_media_review"] = review.model_dump(mode="json")
        result["reference_frames"] = sample_frames(media_path)
    return result


def _scene_plan(data: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    lines = list(data.get("script_lines") or [])
    scenes = []
    for index, line in enumerate(lines):
        if isinstance(line, str):
            text = line
            duration = 8.0
        elif isinstance(line, dict):
            text = str(line.get("text") or line.get("line") or "").strip()
            duration = float(line.get("duration_s") or 8.0)
        else:
            continue
        if text:
            scenes.append({"scene_id": f"scene-{index + 1}", "narration": text, "target_hold_s": duration, "queries": [text[:80]]})
    return {"scene_plan": scenes, "scene_plan_status": "completed" if scenes else "planned"}


async def _character_design(data: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    """Create a reviewable character design contract, not a fake render."""
    from hevi.studio.tools import invoke_tool

    topic = str(data.get("topic") or data.get("source_text") or "").strip()
    beats = await invoke_tool("character.beats", {"text": topic})
    if beats.status != "ok":
        return {"status": "blocked", "reason": beats.reason or "character beat planning unavailable"}
    subjects = [str(item) for item in (data.get("character_ids") or data.get("characters") or [])]
    return {
        "character_design": {
            "subjects": subjects,
            "style": str(data.get("character_style") or "consistent reusable character system"),
            "motion_beats": beats.payload.get("beats") or [],
        },
        "character_design_status": "planned",
    }


async def _script(data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    result = await stage_script(data, context)
    lines = result.get("script_lines") or []
    return {**result, "script": {"lines": lines, "line_count": len(lines)}}


async def _assets(data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    stage_data = dict(data)
    materials = list(stage_data.get("materials") or [])
    media_path = str(stage_data.get("media_path") or "").strip()
    if media_path and not materials:
        materials = [{"id": "source-media", "source": "local", "url": media_path, "title": Path(media_path).stem}]
    stage_data["materials"] = materials
    result = await stage_assets(stage_data, context)
    ranked = result.get("ranked_materials") or []
    verified_files: list[str] = []
    unresolved: list[str] = []
    for item in ranked:
        if not isinstance(item, dict):
            continue
        candidate = str(item.get("cached_path") or item.get("url") or "").strip()
        if candidate and Path(candidate).is_file() and Path(candidate).stat().st_size > 0:
            verified_files.append(candidate)
        elif candidate:
            unresolved.append(candidate)
    return {
        **result,
        "asset_manifest": {
            "bound_assets": result.get("bound_assets") or [],
            "ranked_materials": ranked,
            "verified_files": verified_files,
            "unresolved": unresolved,
            "generated_files": [],
            "status": "ready" if ranked and not unresolved else ("planned" if ranked else "empty"),
        },
    }


async def _edit(data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    result = await stage_edit_plan(data, context)
    return {**result, "edit_decisions": result.get("edit_plan") or {}}


def _rig_plan(data: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    """Compile rig requirements for a downstream local renderer."""
    design = data.get("character_design") or {}
    subjects = design.get("subjects") if isinstance(design, dict) else []
    return {
        "rig_plan": {
            "subjects": list(subjects or []),
            "rig_type": str(data.get("rig_type") or "2d-reusable"),
            "required_controls": ["root", "head", "eyes", "mouth", "left_arm", "right_arm"],
            "renderer": str(data.get("render_runtime") or "remotion"),
        },
        "rig_plan_status": "planned",
    }


async def _compose(data: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    output_path = data.get("output_path") or str(Path(str(data.get("output_dir") or "output/montage")) / "final.mp4")
    timeline = data.get("timeline")
    from hevi.studio.tools import invoke_tool

    if not isinstance(timeline, dict):
        edit_plan = data.get("edit_plan")
        if not isinstance(edit_plan, dict):
            return {"status": "blocked", "reason": "compose requires an edit_plan or timeline"}
        created = await invoke_tool(
            "timeline.create",
            {"edit_plan": edit_plan, "title": data.get("topic") or "montage"},
        )
        timeline = created.payload.get("timeline") if created.status == "ok" else None
        if not isinstance(timeline, dict):
            return {"status": "blocked", "reason": created.reason or "timeline creation failed"}

    result = await invoke_tool(
        "timeline.export",
        {"timeline_id": timeline.get("timeline_id"), "output_path": str(output_path)},
    )
    exported = result.payload.get("video_path") or result.payload.get("output_path")
    path = Path(str(exported or output_path))
    if result.status != "ok" or not path.is_file() or path.stat().st_size <= 0:
        return {"status": "failed", "reason": result.reason or "compose did not produce a verified local artifact", "output_path": str(path)}
    from hevi.production.delivery_gate import probe_video

    probe = probe_video(path)
    require_audio = bool(data.get("require_audio", False))
    quality = {
        "passed": bool(probe.has_video and (probe.has_audio or not require_audio)),
        "duration_s": probe.duration_s,
        "has_video": probe.has_video,
        "has_audio": probe.has_audio,
        "bytes": probe.size_bytes,
    }
    if not quality["passed"]:
        return {
            "status": "failed",
            "reason": "compose quality gate failed: " + ("missing video stream" if not probe.has_video else "missing required audio stream"),
            "output_path": str(path),
            "quality": quality,
        }
    return {"status": "completed", "render_report": {"output_path": str(path), "bytes": path.stat().st_size, "quality": quality}}


_DEFAULT_STAGES: dict[str, Any] = {
    "intake": stage_intake,
    "research": stage_research,
    "watch": stage_watch,
    "idea": _idea,
    "proposal": _proposal,
    "script": _script,
    "scene_plan": _scene_plan,
    "character_design": _character_design,
    "rig_plan": _rig_plan,
    "assets": _assets,
    "edit": _edit,
    "edit_plan": _edit,
    "timeline": stage_timeline,
    "runtime": stage_runtime,
    "dispatch": stage_dispatch,
    "compose": _compose,
    "publish": stage_publish,
}


def _checkpoint(path: Path, pipeline: str, stage: str, result: dict[str, Any], *, approval: str) -> None:
    cp = CheckpointState(
        pipeline=pipeline,
        stage=stage,
        artifacts={"stage_output": Artifact(type=ArtifactType.CHECKPOINT, pipeline=pipeline, stage=stage, data=result)},
        tool_results={stage: result},
        human_approval=approval,
    )
    write_checkpoint(path, cp)


def _load_resume_data(checkpoint_dir: Path, stage_names: list[str], data: dict[str, Any], trail: list[dict[str, Any]]) -> set[str]:
    completed: set[str] = set()
    for stage in stage_names:
        path = checkpoint_dir / f"{stage}.json"
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("human_approval") not in {"approved", "approved_with_changes"}:
                continue
            output = (raw.get("artifacts") or {}).get("stage_output", {}).get("data") or {}
            if isinstance(output, dict):
                data.update(output)
            completed.add(stage)
            trail.append({"stage": stage, "event": "checkpoint_resume"})
        except (OSError, json.JSONDecodeError):
            continue
    return completed


def _approve_checkpoints(checkpoint_dir: Path, stages: set[str], trail: list[dict[str, Any]]) -> None:
    """Apply explicit human approval before loading resumable checkpoints."""
    for stage in stages:
        path = checkpoint_dir / f"{stage}.json"
        if not path.is_file():
            continue
        try:
            checkpoint = read_checkpoint(path)
            update_checkpoint_approval(checkpoint, "approved", "approved through HEVI montage API")
            write_checkpoint(path, checkpoint)
            trail.append({"stage": stage, "event": "checkpoint_approved"})
        except (OSError, ValueError, TypeError):
            continue


def _prepare_reference_media(data: dict[str, Any]) -> None:
    """Attach real local reference facts before any pipeline stage runs."""
    media_path = str(data.get("media_path") or "").strip()
    if not media_path or "source_media_review" in data:
        return
    from hevi.montage.oprim import analyze_reference_video, extract_transcript, sample_frames

    review = analyze_reference_video(media_path)
    data["source_media_review"] = review.model_dump(mode="json")
    data["reference_frames"] = sample_frames(media_path)
    data.setdefault("transcript", extract_transcript(media_path))


async def agentic_montage_workflow(
    config: AgenticMontageConfig | dict[str, Any],
    input_data: dict[str, Any] | Any,
    output_dir: str | Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """Run the HEVI-owned research-to-compose pipeline with human gates."""

    cfg = _mapping(config)
    data = _mapping(input_data)
    pipeline = str(cfg.get("pipeline") or data.get("pipeline") or "animated-explainer")
    out = Path(output_dir)
    checkpoint_dir = out / "checkpoints"
    report_path = out / "montage_report.json"
    pillars = ["fingerprint", "decision_trail", "report", "cost"]
    trail: list[dict[str, Any]] = []
    artifacts: dict[str, Any] = {}
    fingerprint = _safe_fingerprint(pipeline, cfg, data)
    current_stage: str | None = None
    try:
        manifest = load_pipeline_manifest(_manifest_path({**cfg, "pipeline": pipeline}))
        errors: list[str] = []
        stage_names = [stage.name for stage in manifest.stages]
        if not stage_names:
            return {"status": "blocked", "error": "pipeline manifest has no stages", "fingerprint": fingerprint}
        data.update({
            "pipeline": pipeline,
            "budget_usd": float(cfg.get("budget_usd") or 2.0),
            "execute": bool(cfg.get("execute", False)),
            "output_dir": str(out),
            "output_path": data.get("output_path") or str(out / "final.mp4"),
        })
        budget_usd = float(cfg.get("budget_usd") or data.get("budget_usd") or manifest.budget_default_usd)
        estimated_cost = float(
            data.get("estimated_cost_usd")
            or cfg.get("estimated_cost_usd")
            or data.get("cost_estimate_usd")
            or 0.0
        )
        if estimated_cost > budget_usd:
            reason = f"estimated cost {estimated_cost:.3f} exceeds budget {budget_usd:.3f}"
            trail.append({"stage": "preflight", "event": "budget_blocked", "reason": reason})
            report = {
                "status": "blocked",
                "pipeline": pipeline,
                "run_id": str(data.get("run_id") or fingerprint),
                "stage": "preflight",
                "fingerprint": fingerprint,
                "artifacts": {},
                "decision_trail": trail,
                "errors": [reason],
                "pillars": pillars,
                "cost_usd": 0.0,
                "budget_usd": budget_usd,
                "estimated_cost_usd": estimated_cost,
                "report_path": str(report_path),
            }
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            return report
        _prepare_reference_media(data)
        handlers = cfg.get("stage_handlers") or data.get("stage_handlers") or {}
        approved_stages = set(cfg.get("approved_stages") or data.get("approved_stages") or [])
        _approve_checkpoints(checkpoint_dir, approved_stages, trail)
        completed = _load_resume_data(checkpoint_dir, stage_names, data, trail) if cfg.get("resume", True) else set()
        run_id = str(data.get("run_id") or fingerprint)
        for index, stage_name in enumerate(stage_names):
            current_stage = stage_name
            if stage_name in completed:
                continue
            if not cfg.get("execute") and stage_name in {"compose", "publish"}:
                trail.append({"stage": stage_name, "event": "planned_only"})
                continue
            handler_name = stage_name if stage_name in _DEFAULT_STAGES else stage_name.replace("-", "_")
            default = _DEFAULT_STAGES.get(handler_name)
            if default is None:
                errors.append(f"no HEVI stage adapter for {stage_name}")
                break
            await _notify(on_step, {"stage": stage_name, "progress_pct": round(index / len(stage_names) * 100, 2)})
            _emit_backlot(data, run_id=run_id, stage=stage_name, event_type="stage_start", payload={"index": index})
            try:
                result = await _custom_or(stage_name, default, data, artifacts, handlers)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                result = {"status": "failed", "reason": str(exc)}
            if result.get("status") in {"failed", "blocked"}:
                _emit_backlot(data, run_id=run_id, stage=stage_name, event_type="stage_fail", payload={"reason": result.get("reason") or result.get("error", "")})
                errors.append(f"{stage_name}: {result.get('reason') or result.get('error', 'stage failed')}")
                trail.append({"stage": stage_name, "event": "failed", "reason": errors[-1]})
                break
            data.update(result)
            artifacts.update(result)
            trail.append({"stage": stage_name, "event": "completed", "keys": sorted(result)})
            _emit_backlot(data, run_id=run_id, stage=stage_name, event_type="stage_done", payload={"keys": sorted(result)})
            stage_def = next((item for item in manifest.stages if item.name == stage_name), None)
            if stage_def is not None and stage_def.checkpoint_required:
                checkpoint_dir.mkdir(parents=True, exist_ok=True)
                approved_stages = set(cfg.get("approved_stages") or data.get("approved_stages") or [])
                approval = "approved" if bool(cfg.get("auto_approve")) or stage_name in approved_stages else "pending"
                _checkpoint(checkpoint_dir / f"{stage_name}.json", pipeline, stage_name, result, approval=approval)
                if approval == "pending":
                    report = {
                        "status": "paused",
                        "pipeline": pipeline,
                        "run_id": run_id,
                        "stage": stage_name,
                        "fingerprint": fingerprint,
                        "artifacts": artifacts,
                        "decision_trail": trail,
                        "pillars": pillars,
                        "cost_usd": 0.0,
                        "report_path": str(report_path),
                        "resume_hint": "approve this checkpoint and rerun with resume=true",
                    }
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                    return report
        status = "failed" if errors else ("completed" if cfg.get("execute") else "planned")
        report = {
            "status": status,
            "pipeline": pipeline,
            "run_id": run_id,
            "stage": current_stage,
            "fingerprint": fingerprint,
            "artifacts": artifacts,
            "decision_trail": trail,
            "errors": errors,
            "pillars": pillars,
            "cost_usd": float(data.get("cost_usd") or 0.0),
            "report_path": str(report_path),
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return report
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("agentic_montage_workflow failed")
        report = {
            "status": "failed",
            "pipeline": pipeline,
            "run_id": str(data.get("run_id") or fingerprint),
            "stage": current_stage,
            "fingerprint": fingerprint,
            "error": str(exc),
            "decision_trail": trail,
            "pillars": pillars,
            "cost_usd": 0.0,
            "report_path": str(report_path),
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return report


__all__ = ["AgenticMontageConfig", "agentic_montage_workflow"]
