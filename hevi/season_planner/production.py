"""Task adapter for a planned short-drama episode.

Season planning stays in HEVI. This adapter reconstructs one immutable episode
binding and runs its dialogue/avatar render through the shared presenter
transaction.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from hevi.production.delivery_gate import evaluate_director_delivery
from hevi.season_planner.schemas import EpisodePlan
from hevi.season_planner.tongjian_bridge import render_episode
from hevi.tongjian.production import render_presenter_video
from hevi.video.duration_mapper import get_duration_config


def _string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if isinstance(item, str)}


async def _subject3d_views(pool: Any, subject_id_map: dict[str, str]) -> dict[str, dict[str, str]]:
    if not subject_id_map:
        return {}
    from hevi.subjects.repository import SubjectRepository
    from hevi.subjects.subject_service import SubjectService

    service = SubjectService(SubjectRepository(pool))
    resolved: dict[str, dict[str, str]] = {}
    for char_id, subject_id in subject_id_map.items():
        try:
            subject = await service.get_subject(subject_id)
        except Exception:
            continue
        views = ((subject or {}).get("metadata") or {}).get("subject3d", {}).get("views")
        if isinstance(views, dict):
            resolved[char_id] = _string_mapping(views)
    return resolved


async def execute_shortdrama_task(task: dict[str, Any], pool: Any) -> dict[str, Any]:
    """Render one dispatched short-drama episode through the standard boundary."""

    config = task.get("config_json") or {}
    episode_data = config.get("episode_plan")
    story_data = config.get("shortdrama_story")
    if not isinstance(episode_data, dict) or not isinstance(story_data, dict):
        raise ValueError("shortdrama task missing episode_plan or shortdrama_story binding")

    from hevi.storygraph.schemas import StoryGraph

    episode = EpisodePlan.model_validate(episode_data)
    story = StoryGraph.model_validate(story_data)
    task_id = uuid.UUID(str(task["id"]))
    output_dir = Path("output/tasks") / str(task_id)
    subject_ref_paths = _string_mapping(config.get("shortdrama_subject_ref_paths"))
    subject_id_map = _string_mapping(config.get("shortdrama_subject_id_map"))
    duration = get_duration_config(str(task.get("duration_archetype", "1-5min")))
    rendered_episode: dict[str, Any] = {}

    async def render_layers(
        _presentation: dict[str, Any], target_dir: Path, _renderer_config: dict[str, Any]
    ) -> dict[str, Any]:
        nonlocal rendered_episode
        rendered_episode = await render_episode(
            episode,
            story,
            run_dir=target_dir,
            target_duration_sec=int(duration["target_s"]),
            subject_ref_paths=subject_ref_paths,
            subject3d_views=await _subject3d_views(pool, subject_id_map),
            locked_director=config.get("locked_director")
            if isinstance(config.get("locked_director"), dict)
            else None,
        )
        final_video = rendered_episode.get("final_video")
        video_path = getattr(final_video, "video_path", None)
        return {
            "video_path": str(video_path) if video_path is not None else None,
            "report": {"shot_count": len(rendered_episode.get("shots") or [])},
        }

    produced = await render_presenter_video(
        output_dir=output_dir,
        renderer=render_layers,
        presentation_kind="shortdrama-episode",
    )
    raw_shots = rendered_episode.get("shots")
    shots: list[dict[str, Any]] = [
        shot for shot in raw_shots if isinstance(shot, dict)
    ] if isinstance(raw_shots, list) else []
    promise = str(config.get("delivery_promise") or "motion")
    verdict = evaluate_director_delivery(shots, delivery_promise=promise)
    config_json = {
        **config,
        "actual_usd": config.get("estimated_usd", 0.0),
        "failed_shots": verdict.failed_shots,
        "canon_copy_ratio": verdict.canon_copy_ratio,
        "motion_fallback": verdict.motion_fallback,
        "delivery_promise": promise,
    }
    passed = sum(1 for s in shots if s.get("passed") is True)
    return {
        **task,
        "status": verdict.status,
        "progress_pct": 100.0 if verdict.ok else 0.0,
        "result_video_path": str(produced.video_path),
        "total_shots": verdict.total_shots,
        "completed_shots": passed,
        "error": None if verdict.ok else verdict.reason,
        "config_json": config_json,
        "shots": shots,
    }
