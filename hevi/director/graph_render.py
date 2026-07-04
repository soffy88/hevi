"""逐镜编辑回路 —— 执行(用户编辑过的)canvas 分镜图 → 装配成片 → 落任务记录。

与自动管线的区别:不重跑 omodul 的 storyboard→分镜,而是直接用图里每个 video 节点的
prompt/provider/mode(用户改过的)逐镜出片,再用同一个 assemble_longvideo 装配。这样"改哪镜
就重出哪镜、其余不动"成真。产出写进 video_tasks,和普通任务一样在「我的」里看。
"""

from __future__ import annotations

import logging
import uuid
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
    from hevi.assembly.assembler import ShotSegment, assemble_longvideo
    from hevi.pipeline.longvideo_orchestrator import _order_and_dedup_shots

    try:
        result = await executor_service.execute_graph(graph_id)
        clips = _order_and_dedup_shots(collect_shot_clips(result.get("results", {})))
        clips = [p for p in clips if p.exists() and p.stat().st_size > 64]
        if not clips:
            raise RuntimeError("图执行未产出任何镜头(检查各 video 节点是否成功出片)")

        out_dir = Path("output/tasks") / str(task_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        final = out_dir / "final.mp4"

        from hevi.audio.bgm_library import BGMLibrary

        _lib = BGMLibrary()
        bgm_path = _lib.select_bgm(bgm) if bgm else None
        sfx_path = None
        if sfx:
            _direct = Path(sfx)
            sfx_path = _direct if _direct.is_file() else _lib.get_sfx(sfx)
        intro_path = Path(intro_clip) if intro_clip and Path(intro_clip).is_file() else None
        outro_path = Path(outro_clip) if outro_clip and Path(outro_clip).is_file() else None

        segments = [ShotSegment(p) for p in clips]
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
        await task_service.repository.update_task(
            task_id,
            {
                "status": "completed",
                "progress_pct": 100.0,
                "result_video_path": str(final),
                "total_shots": len(clips),
                "completed_shots": len(clips),
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            },
        )
        logger.info("graph episode %s assembled → %s (%d 镜)", task_id, final, len(clips))
    except Exception as e:
        logger.exception("graph episode render failed: %s", e)
        try:
            await task_service.repository.update_task(
                task_id,
                {
                    "status": "failed",
                    "error": str(e)[:500],
                    "updated_at": datetime.now(UTC).replace(tzinfo=None),
                },
            )
        except Exception:
            pass
