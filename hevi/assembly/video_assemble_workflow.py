"""omodul.video_assemble_workflow — 标准视频装配事务(3O §5 Task 5.1)。

以 hevi/assembly/assembler.py 的 assemble_longvideo 为唯一实现基底,包装为
3O 标准签名的事务(不 raise、返回状态字典、显式声明启用支柱)。

.. note::
   3O 迁移意图:该 workflow 应最终上游至 ``omodul`` 主库
   (``omodul.video_assemble_workflow``),此处为 Hevi 项目侧暂驻实现,
   函数签名与 SPEC §5 完全一致,便于平移到 omodul 源码仓库时零改动。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.assembly.assembler import ShotSegment, assemble_longvideo, probe_duration

logger = logging.getLogger(__name__)


@dataclass
class AssembleConfig:
    """装配配置(确定性参数,不含运行时状态)。"""

    shots: list[ShotSegment]
    output_path: Path
    width: int = 832
    height: int = 480
    fps: int = 24
    transition: str = "fade"
    transition_duration: float = 0.5
    loudness_lufs: float = -14.0
    bgm_gain_db: float = -18.0
    sfx_gain_db: float = -6.0
    color_normalize: bool = True
    subtitle_style: str = "default"


@dataclass
class AssembleInput:
    """装配输入(外部产物路径,均可选)。"""

    narration_audio: Path | None = None
    bgm_path: Path | None = None
    sfx_path: Path | None = None
    subtitle_path: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


async def video_assemble_workflow(
    config: AssembleConfig,
    input_data: AssembleInput,
    output_dir: Path,
    *,
    on_step: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """标准 omodul:执行视频切片、转场、字幕烧录与音频混合。

    Args:
        config: 装配配置(shots/画幅/转场/混音参数)。
        input_data: 旁白/BGM/SFX/字幕等外部产物路径。
        output_dir: 产出目录(报告与 sidecar 落盘处)。
        on_step: 进度回调(dict: {"stage", "pct"} 等),可选。

    Returns:
        {"status": "completed" | "failed", "error": ..., "report_path": ...}
        失败不 raise(3O 规范),错误详情写入 error 字段。

    Note:
        显式声明 3O 支柱:report / cost / decision_trail。
    """
    _enabled_pillars = {"report", "cost", "decision_trail"}

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    decision_trail: list[dict[str, Any]] = []

    def _step(stage: str, pct: float) -> None:
        if on_step is not None:
            on_step({"stage": stage, "pct": pct})

    try:
        if not config.shots:
            return {"status": "failed", "error": "video_assemble_workflow: no shots"}

        _step("normalize_and_concat", 10.0)
        final = await assemble_longvideo(
            shots=config.shots,
            output_path=config.output_path,
            narration_audio=input_data.narration_audio,
            bgm_path=input_data.bgm_path,
            sfx_path=input_data.sfx_path,
            subtitle_path=input_data.subtitle_path,
            width=config.width,
            height=config.height,
            fps=config.fps,
            transition=config.transition,
            transition_duration=config.transition_duration,
            loudness_lufs=config.loudness_lufs,
            bgm_gain_db=config.bgm_gain_db,
            sfx_gain_db=config.sfx_gain_db,
            color_normalize=config.color_normalize,
            subtitle_style=config.subtitle_style,
        )
        _step("probe_and_report", 90.0)

        duration_s = await probe_duration(final)
        decision_trail.append(
            {
                "stage": "assemble",
                "shots": len(config.shots),
                "transition": config.transition,
                "bgm_gain_db": config.bgm_gain_db,
                "width": config.width,
                "height": config.height,
                "duration_s": round(duration_s, 3),
            }
        )

        report_path = output_dir / "assemble_report.json"
        report_path.write_text(
            __import__("json").dumps(
                {
                    "pillars": sorted(_enabled_pillars),
                    "status": "completed",
                    "video_path": str(config.output_path),
                    "duration_s": duration_s,
                    "shots": len(config.shots),
                    "decision_trail": decision_trail,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        _step("completed", 100.0)
        return {
            "status": "completed",
            "report_path": str(report_path),
            "decision_trail": decision_trail,
        }
    except Exception as exc:  # 3O 规范:失败不 raise
        logger.exception("video_assemble_workflow failed")
        return {
            "status": "failed",
            "error": str(exc),
            "report_path": str(output_dir / "assemble_report.json"),
        }
