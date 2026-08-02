"""逐镜编辑回路 —— 执行(用户编辑过的)canvas 分镜图 → 装配成片 → 落任务记录。

与自动管线的区别:不重跑 omodul 的 storyboard→分镜,而是直接用图里每个 video 节点的
prompt/provider/mode(用户改过的)逐镜出片,再用同一个 assemble_longvideo 装配。这样"改哪镜
就重出哪镜、其余不动"成真。产出写进 video_tasks,和普通任务一样在「我的」里看。
"""

from __future__ import annotations

import logging
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def collect_shot_clips(results: dict[str, Any]) -> list[Path]:
    """从 execute_graph 的逐节点结果里取 video 节点产出的 mp4,按 node_id(shot_XXXX)排序。"""
    found: list[tuple[str, Path]] = []
    for nid, r in results.items():
        if not isinstance(r, dict) or r.get("node_type") != "video" or not r.get("success"):
            continue
        out = (r.get("output") or {}).get("output")
        if out:
            found.append((nid, Path(str(out))))
    found.sort(key=lambda x: x[0])
    return [p for _, p in found]


async def render_graph_episode(
    *,
    graph_id: str,
    task_id: uuid.UUID,
    executor_service: Any,
    task_service: Any,
    width: int,
    height: int,
    fps: int,
    transition: str = "fade",
    bgm: str | None = None,
    sfx: str | None = None,
    intro_clip: str | None = None,
    outro_clip: str | None = None,
) -> None:
    """后台:执行图 → 收集逐镜 clip → 装配(可混 BGM/音效、拼片头尾)→ 更新任务。"""
    try:
        rendered = await render_graph_episode_artifact(
            graph_id=graph_id,
            output_dir=Path("output/tasks") / str(task_id),
            executor_service=executor_service,
            width=width,
            height=height,
            fps=fps,
            transition=transition,
            bgm=bgm,
            sfx=sfx,
            intro_clip=intro_clip,
            outro_clip=outro_clip,
        )
        await task_service.repository.update_task(
            task_id,
            {
                "status": "completed",
                "progress_pct": 100.0,
                "result_video_path": rendered["video_path"],
                "total_shots": rendered["shot_count"],
                "completed_shots": rendered["shot_count"],
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        logger.info(
            "graph episode %s assembled → %s (%d 镜)",
            task_id,
            rendered["video_path"],
            rendered["shot_count"],
        )
    except Exception as e:
        logger.exception("graph episode render failed: %s", e)
        with suppress(Exception):
            await task_service.repository.update_task(
                task_id,
                {
                    "status": "failed",
                    "error": str(e)[:500],
                    "updated_at": datetime.now(UTC).replace(tzinfo=None),
                },
            )


async def render_graph_episode_artifact(
    *,
    graph_id: str,
    output_dir: Path,
    executor_service: Any,
    width: int,
    height: int,
    fps: int,
    transition: str = "fade",
    bgm: str | None = None,
    sfx: str | None = None,
    intro_clip: str | None = None,
    outro_clip: str | None = None,
) -> dict[str, Any]:
    """Execute an edited canvas graph and return a real assembled artifact.

    This is intentionally persistence-free so it can be injected into the
    standard presenter transaction.  The caller owns task state projection.
    """
    from hevi.assembly.assembler import ShotSegment, assemble_longvideo
    from hevi.pipeline.longvideo_orchestrator import _order_and_dedup_shots

    result = await executor_service.execute_graph(graph_id)
    clips = _order_and_dedup_shots(collect_shot_clips(result.get("results", {})))
    clips = [path for path in clips if path.exists() and path.stat().st_size > 64]
    if not clips:
        raise RuntimeError("图执行未产出任何镜头(检查各 video 节点是否成功出片)")

    output_dir.mkdir(parents=True, exist_ok=True)
    final = output_dir / "final.mp4"

    from hevi.audio.bgm_library import BGMLibrary

    library = BGMLibrary()
    bgm_path = library.select_bgm(bgm) if bgm else None
    sfx_path = None
    if sfx:
        direct_path = Path(sfx)
        sfx_path = direct_path if direct_path.is_file() else library.get_sfx(sfx)
    intro_path = Path(intro_clip) if intro_clip and Path(intro_clip).is_file() else None
    outro_path = Path(outro_clip) if outro_clip and Path(outro_clip).is_file() else None

    segments = [ShotSegment(path) for path in clips]
    if intro_path is not None:
        segments.insert(0, ShotSegment(intro_path))
    if outro_path is not None:
        segments.append(ShotSegment(outro_path))

    await assemble_longvideo(
        shots=segments,
        output_path=final,
        bgm_path=bgm_path,
        sfx_path=sfx_path,
        width=width,
        height=height,
        fps=fps,
        transition=transition,
    )
    return {"video_path": str(final), "shot_count": len(clips)}


async def execute_task(task: dict[str, Any], pool: Any) -> dict[str, Any]:
    """TaskService adapter for the director's edited-canvas render path."""
    from hevi.canvas.executor_service import ExecutorService
    from hevi.canvas.graph_repository import GraphRepository
    from hevi.canvas.graph_service import GraphService
    from hevi.tongjian.production import render_presenter_video

    config = task.get("config_json") or {}
    graph_id = config.get("graph_id")
    render_spec = config.get("render_spec") or {}
    if not isinstance(graph_id, str) or not graph_id:
        raise ValueError("director_graph task missing config_json.graph_id")

    task_id = uuid.UUID(str(task["id"]))
    graph_service = GraphService(GraphRepository(pool))
    executor_service = ExecutorService(graph_service)
    output_dir = Path("output/tasks") / str(task_id)

    async def render_canvas(
        _presentation: dict[str, Any], target_dir: Path, _config: dict[str, Any]
    ) -> dict[str, Any]:
        rendered = await render_graph_episode_artifact(
            graph_id=graph_id,
            output_dir=target_dir,
            executor_service=executor_service,
            width=int(render_spec.get("width", 1080)),
            height=int(render_spec.get("height", 1920)),
            fps=int(render_spec.get("fps", 24)),
            transition=str(render_spec.get("transition", "fade")),
            bgm=render_spec.get("bgm"),
            sfx=render_spec.get("sfx"),
            intro_clip=render_spec.get("intro_clip"),
            outro_clip=render_spec.get("outro_clip"),
        )
        return {
            "video_path": rendered["video_path"],
            "report": {"shot_count": rendered["shot_count"], "graph_id": graph_id},
        }

    produced = await render_presenter_video(
        output_dir=output_dir,
        renderer=render_canvas,
        presentation_kind="director-canvas",
    )
    report = produced.engine_result.get("report") or {}
    return {
        **task,
        "status": "completed",
        "progress_pct": 100.0,
        "result_video_path": str(produced.video_path),
        "total_shots": int(report.get("shot_count", 0)),
        "completed_shots": int(report.get("shot_count", 0)),
    }
