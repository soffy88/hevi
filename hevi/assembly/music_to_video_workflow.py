"""音乐→视频工作流 —— 节拍驱动时间线(3O 内化 Round 3,来源 HyperFrames /music-to-video)。

能力:一首歌(或 mood 生成)→ 节拍网格(hevi.motion.beat_sync:网格拟合+kick 重音)
→ beatF(n) 拍号时间线 → 歌词/幻灯片/动态宣传片。与 hyperframes music-to-video
同范式;hevi 的 beat_sync 更严(最小二乘网格 + 残差阈值 + 回测 ≤3f)。

确定性部分(可测):节拍网格 → 拍号时间线(事件钉在最近拍)→ 歌词逐拍分配。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.motion.beat_sync import BeatGrid, BeatSyncError, analyze_beat_grid, beat_time

logger = logging.getLogger(__name__)

#: 视频形态(hyperframes music-to-video 三态)。
MUSIC_VIDEO_MODES: tuple[str, ...] = ("lyrics", "slideshow", "kinetic_promo")


@dataclass
class MusicVideoConfig:
    """音乐视频配置。"""

    audio_path: Path
    out_path: Path
    mode: str = "lyrics"
    fps: int = 30
    lines_per_slide: int = 2  # lyrics 模式每屏歌词行数
    duration_s: float = 0.0  # 0 = 整首


@dataclass
class MusicVideoInput:
    """输入:歌词/内容(均可选)。"""

    lyrics: list[str] = field(default_factory=list)  # 逐句歌词(时间未知,按拍分配)
    slides: list[dict[str, Any]] = field(default_factory=list)  # [{title,note}]
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class BeatTimeline:
    """拍号时间线:事件 → 最近拍时刻。"""

    events: list[dict[str, Any]]  # [{beat:int, at:float, payload}]
    grid: BeatGrid

    def to_dict(self) -> dict[str, Any]:
        return {
            "bpm": round(self.grid.bpm, 2),
            "events": self.events,
            "grid_trusted": self.grid.trusted,
            "residual_ms": round(self.grid.residual_ms, 1),
        }


def build_beat_timeline(
    grid: BeatGrid, lyrics: list[str], *, lines_per_slide: int = 2
) -> BeatTimeline:
    """歌词 → 拍号时间线:每行歌词占 2 拍(可配),逐拍推进。

    事件钉在**拍上**(beat_time(grid, n)),保证切点与重音对齐(hyperframes 同范式)。
    """
    events: list[dict[str, Any]] = []
    beat_step = max(2, lines_per_slide)  # 每行占 2 拍(快节奏可调)
    for i, line in enumerate(lyrics):
        beat = i * beat_step
        events.append(
            {
                "beat": beat,
                "at": round(beat_time(grid, beat), 3),
                "text": line,
                "kind": "lyric",
            }
        )
    return BeatTimeline(events=events, grid=grid)


async def music_to_video_workflow(
    config: MusicVideoConfig,
    input_data: MusicVideoInput,
    output_dir: Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """标准 omodul:节拍分析 → 拍号时间线 → report;渲染交 remotion(可选)。"""
    _enabled_pillars = {"report", "cost", "decision_trail"}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def _step(stage: str, pct: float) -> None:
        if callable(on_step):
            on_step({"stage": stage, "pct": pct})

    try:
        if not config.audio_path.exists():
            return {"status": "failed", "error": f"audio not found: {config.audio_path}"}
        if config.mode not in MUSIC_VIDEO_MODES:
            return {"status": "failed", "error": f"unknown mode {config.mode!r}"}
        _step("validate", 10.0)

        try:
            grid = analyze_beat_grid(config.audio_path)
        except BeatSyncError as e:
            return {"status": "failed", "error": f"beat analysis failed: {e}"}
        _step("beat_grid", 45.0)

        timeline = build_beat_timeline(
            grid, input_data.lyrics, lines_per_slide=config.lines_per_slide
        )
        _step("timeline", 70.0)

        report = {
            "status": "completed",
            "mode": config.mode,
            "timeline": timeline.to_dict(),
            "cut_error_note": (
                "渲染后回测切点误差(hevi.motion.beat_sync.measure_cut_error)≤3f 判通过"
            ),
        }
        report_path = output_dir / "music_video_report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"status": "completed", "report_path": str(report_path), **report}
    except Exception as e:
        logger.exception("music_to_video_workflow failed")
        return {"status": "failed", "error": str(e)}
