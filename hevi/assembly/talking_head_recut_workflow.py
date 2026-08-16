"""说话人重剪工作流 —— 既有 talking-head/播客 → 设计化图形覆盖(3O 内化 Round 3)。

来源: HyperFrames /talking-head-recut —— lower-thirds、数据调用、动态标题、
pull-quotes、侧栏、PiP,footage 不动,只加覆盖层。hevi 侧:确定性产出覆盖层计划
(时间线级,与 sound_design 的 SFX 钉帧表同范式),渲染交 remotion。

3O 归属(待上游): `omodul.talking_head_recut_workflow`。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 覆盖层类型(hyperframes talking-head-recut 词汇)。
OVERLAY_KINDS: tuple[str, ...] = (
    "lower_third", "pull_quote", "kinetic_title", "data_callout", "pip", "side_panel",
)


@dataclass
class RecutConfig:
    """重剪配置。"""

    video_path: Path
    out_path: Path
    style_tokens: str = "产品演示风格,克制"  # 设计 token 描述(或复用 hevi.motion.design_token)
    pip_rect: str = ""  # PiP 画面位置(如 "bottom-right 320x240")


@dataclass
class RecutInput:
    """输入:说话人片段 + 关键信息(数据/金句/标题)。"""

    segments: list[dict[str, Any]] = field(default_factory=list)  # [{start,end,summary}]
    pull_quotes: list[str] = field(default_factory=list)
    data_callouts: list[dict[str, Any]] = field(default_factory=list)  # [{label,value,at}]
    titles: list[dict[str, Any]] = field(default_factory=list)  # [{text,at}]
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class OverlayPlan:
    """覆盖层计划(时间线级,集中管理)。"""

    overlays: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"overlays": self.overlays}


def build_overlay_plan(config: RecutConfig, input_data: RecutInput) -> OverlayPlan:
    """确定性:segments/信息 → 覆盖层时间线。

    规则:
      - 每 segment 起步一个 lower_third(说话人身份,4s)。
      - pull_quotes 在对应 segment 内以 pull_quote 呈现(强调主视觉,不遮挡人脸)。
      - data_callouts 按 at 时刻插 data_callout(给数字留呼吸 2.5s)。
      - titles 在 at 时刻 kinetic_title(hold 按 token 风格 ≥1s)。
    """
    overlays: list[dict[str, Any]] = []
    for idx, seg in enumerate(input_data.segments):
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start + 10.0))
        name = seg.get("summary", f"片段 {idx + 1}")[:28]
        overlays.append(
            {
                "kind": "lower_third",
                "from": start,
                "duration": 4.0,
                "text": name,
                "style": config.style_tokens,
            }
        )
        # 金句:该段内中段呈现 5s
        if idx < len(input_data.pull_quotes):
            overlays.append(
                {
                    "kind": "pull_quote",
                    "from": start + (end - start) / 2,
                    "duration": 5.0,
                    "text": input_data.pull_quotes[idx],
                    "style": config.style_tokens,
                }
            )
    overlays.extend(
        {
            "kind": "data_callout",
            "from": float(callout.get("at", 0.0)),
            "duration": 2.5,
            "text": f"{callout.get('label', '')} {callout.get('value', '')}".strip(),
            "style": config.style_tokens,
        }
        for callout in input_data.data_callouts
    )
    overlays.extend(
        {
            "kind": "kinetic_title",
            "from": float(title.get("at", 0.0)),
            "duration": 1.5,
            "text": title.get("text", ""),
            "style": config.style_tokens,
        }
        for title in input_data.titles
    )
    if config.pip_rect:
        overlays.append(
            {"kind": "pip", "from": 0.0, "duration": 0.0, "text": "", "rect": config.pip_rect}
        )
    overlays.sort(key=lambda o: float(o.get("from", 0.0)))
    return OverlayPlan(overlays=overlays)


async def talking_head_recut_workflow(
    config: RecutConfig,
    input_data: RecutInput,
    output_dir: Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """标准 omodul:覆盖层计划 → report;渲染交 remotion(可选)。"""
    _enabled_pillars = {"report", "cost", "decision_trail"}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def _step(stage: str, pct: float) -> None:
        if callable(on_step):
            on_step({"stage": stage, "pct": pct})

    try:
        if not config.video_path.exists():
            return {"status": "failed", "error": f"video not found: {config.video_path}"}
        _step("validate", 20.0)
        plan = build_overlay_plan(config, input_data)
        _step("plan", 60.0)
        report = {"status": "completed", "plan": plan.to_dict()}
        report_path = output_dir / "recut_report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"status": "completed", "plan": plan.to_dict(), "report_path": str(report_path)}
    except Exception as e:
        logger.exception("talking_head_recut_workflow failed")
        return {"status": "failed", "error": str(e)}
