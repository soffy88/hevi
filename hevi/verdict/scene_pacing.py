"""场景步骤节奏校验 —— 帧精确模拟步骤时间轴 + narration cue 对齐断言。

对标 OpenMontage lib/verify_scene_pacing.py(3O 内化, 差距 B4 补面):
合成 UI/终端类场景的 `steps` 列表在渲染器里的推进速度可精确估算
(逐字符打字速度 + 停顿), 用它反推每个可见事件的视频时间戳, 再断言
旁白 cue 与视觉里程碑对齐(±tolerance 秒), 同时检查步骤总时长不
溢出/不过度欠填场景。

与 hevi/verdict/production_checks.py 的 check_scene_pacing 关系:
那是**时长分布**统计(过短/过长/方差, 不需要 step 语义); 这里是
**帧精确步骤模拟**(需要 step 的 kind/text/typeSpeed/holdSeconds),
两者互补。本模块全部为纯函数, 零媒体解码依赖。

使用:
    from hevi.verdict.scene_pacing import trace, assert_alignment

    trace(install_steps, scene_start=50.0)
    assert_alignment(
        install_steps,
        scene_start=50.0, scene_end=110.0,
        narration_cues=[(57.0, "克隆仓库"), (65.5, "执行 setup"), ...],
        tolerance=1.0,
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# 步骤 kind: cmd(打字命令) / out(输出回显) / pause(停顿) / pill(非阻塞角标)。
# pill 不推进游标 —— 它是覆盖层, 不占视频时间。
_KNOWN_KINDS = frozenset({"cmd", "out", "pause", "pill"})


def step_duration(step: dict[str, Any], fps: int = 30) -> float:
    """返回单个步骤的游标推进秒数(帧精确, 1/fps 取整)。

    pill 不推进游标(非阻塞覆盖层), 恒为 0.0。
    """
    kind = step.get("kind")
    if kind == "cmd":
        text = str(step.get("text") or "")
        type_frames = math.ceil(len(text) * float(step.get("typeSpeed", 0.035)) * fps)
        return type_frames / fps + float(step.get("holdSeconds", 0.3))
    if kind == "out":
        reveal_frames = max(2, math.ceil(0.08 * fps))
        return reveal_frames / fps + float(step.get("holdSeconds", 0.15))
    if kind == "pause":
        return float(step.get("seconds", 0.0))
    if kind == "pill":
        return 0.0
    raise ValueError(f"未知步骤 kind: {kind!r} (可选: {sorted(_KNOWN_KINDS)})")


@dataclass
class Landmark:
    """一个可见事件在视频时间轴上的里程碑。"""

    video_time: float
    kind: str
    text: str


def trace(
    steps: list[dict[str, Any]],
    scene_start: float = 0.0,
    fps: int = 30,
    *,
    quiet: bool = False,
) -> list[Landmark]:
    """沿步骤列表推进游标, 为每个可见事件打印视频时间里程碑。

    Returns: 里程碑列表(供对齐断言用)。
    """
    cursor = 0.0
    out: list[Landmark] = []
    for s in steps:
        k = s.get("kind", "")
        vt = round(cursor + scene_start, 2)
        if k in ("cmd", "out", "pill"):
            text = str(s.get("text", ""))
            out.append(Landmark(video_time=vt, kind=k.upper(), text=text))
            if not quiet:
                prefix = {"CMD": "CMD  ", "OUT": "OUT  ", "PILL": "PILL "}[k.upper()]
                print(f"  {vt:7.2f}s  {prefix}{text[:60]}")
        cursor += step_duration(s, fps)
    if not quiet:
        end_vt = round(cursor + scene_start, 2)
        print(f"  {end_vt:7.2f}s  -- 步骤结束 --")
    return out


def assert_alignment(
    steps: list[dict[str, Any]],
    scene_start: float,
    scene_end: float,
    narration_cues: list[tuple[float, str]],
    *,
    tolerance: float = 1.0,
    fps: int = 30,
) -> None:
    """断言每个旁白 cue 在 tolerance 秒内都有对应视觉里程碑。

    同时检查步骤总时长不溢出 scene_end(+0.5s), 且不过度欠填
    (>5s 冻结空场 → 提示补一个 closing pause)。

    Raises: AssertionError —— 任一 cue 失配或时长越界。
    """
    landmarks = trace(steps, scene_start, fps, quiet=True)
    errors: list[str] = []

    for cue_time, cue_desc in narration_cues:
        if not landmarks:
            errors.append(f"cue {cue_time:.2f}s ({cue_desc}): 无任何里程碑")
            continue
        closest = min(landmarks, key=lambda lm: abs(lm.video_time - cue_time))
        delta = closest.video_time - cue_time
        if abs(delta) > tolerance:
            errors.append(
                f"cue {cue_time:.2f}s ({cue_desc}) 在 ±{tolerance:.1f}s 内无视觉对齐 —— "
                f"最近的是 {closest.kind}@{closest.video_time:.2f}s ({delta:+.2f}s 偏差): "
                f"{closest.text[:40]}"
            )

    cursor = sum(step_duration(s, fps) for s in steps)
    scene_duration = scene_end - scene_start
    if cursor > scene_duration + 0.5:
        errors.append(
            f"步骤溢出场景: 游标止于 {scene_start + cursor:.2f}s, 但 scene_end 是 "
            f"{scene_end:.2f}s (溢出 {cursor - scene_duration:.2f}s)"
        )
    if cursor < scene_duration - 5.0:
        errors.append(
            f"步骤欠填场景 {scene_duration - cursor:.2f}s —— 最后一个可见步骤从 "
            f"{scene_start + cursor:.2f}s 冻结到 {scene_end:.2f}s。补一个 closing pause。"
        )

    if errors:
        raise AssertionError(
            "场景节奏校验失败:\n  - " + "\n  - ".join(errors)
        )


__all__ = ["Landmark", "assert_alignment", "step_duration", "trace"]
