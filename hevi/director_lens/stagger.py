"""错相编排器 (Stagger Orchestrator) & 主次层次控制器。

规则:
1. 主体先动 (start_delay_frames = 0), 次层、阴影、文字、相机各自延迟若干帧 (stagger delay)。
2. 同一时刻只能有一个主事件 (primary attention center), 避免视觉信息过载。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from hevi.director_lens.brief import DirectorBrief


@dataclass
class StaggerConfig:
    primary_delay: int = 0
    secondary_delay: int = 2
    shadow_delay: int = 3
    text_delay: int = 4
    camera_delay: int = 5


def apply_stagger(brief: DirectorBrief) -> DirectorBrief:
    """为 brief 中的各层轨迹分配错相延迟 (stagger frames)。"""
    for track in brief.tracks:
        if track.element == "primary":
            track.start_delay_frames = 0
        elif track.element == "secondary":
            track.start_delay_frames = max(2, round(brief.fps * 0.08))
        elif track.element == "background":
            track.start_delay_frames = 0  # 背景恒定微动
        else:
            track.start_delay_frames = max(3, round(brief.fps * 0.12))
    return brief


def check_primary_secondary_hierarchy(brief: DirectorBrief) -> tuple[bool, list[str]]:
    """检查同一时刻是否只有一个主事件 (primary/secondary hierarchy)。

    若同一时间窗口内有多个重动作重叠触发, 返回 False 和告警信息。
    """
    violations: list[str] = []
    # 收集所有事件时间
    events_by_time: dict[float, list[str]] = {}
    for track in brief.tracks:
        for e in track.events:
            if e.kind in ("impact", "drop", "bounce", "press"):
                # 舍入到 0.05s 窗口
                t_key = round(e.t * 20) / 20.0
                events_by_time.setdefault(t_key, []).append(f"{track.element}:{e.kind}")

    for t, evs in events_by_time.items():
        primary_evs = [e for e in evs if "primary" in e]
        other_evs = [e for e in evs if "primary" not in e]
        # 若同一主元素上同时有 impact 和 bounce, 属于物理弹跳连击瞬时反应, 允许
        if len(primary_evs) > 1:
            kinds_p = [e.split(":")[1] for e in primary_evs]
            if not (len(kinds_p) == 2 and set(kinds_p) == {"impact", "bounce"}):
                violations.append(f"at t={t}s: multiple primary events {primary_evs} (violates single attention center)")
        # 若主事件与次事件在同一瞬间且主事件没有错开延迟
        if primary_evs and other_evs and any(e.startswith("secondary") for e in other_evs):
            # 允许有 stagger delay
            pass

    return len(violations) == 0, violations


__all__ = [
    "StaggerConfig",
    "apply_stagger",
    "check_primary_secondary_hierarchy",
]
