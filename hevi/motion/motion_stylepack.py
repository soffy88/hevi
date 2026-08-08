"""品牌→动效参数表(motion StylePack)—— 能量轴×调性轴 → 缓动/时长/过冲(3O 内化 Phase B)。

来源: video-shotcraft pipeline.md 的"品牌→动效参数推导":不凭手感挑 easing/时长,
先把品牌放两根轴上,再从最近的预设起步;落地要弹的场合 y1 必须 >1。

这里是把"动效版 StylePack"沉淀为数据表 + 解析函数:预设 → 主时长/入场缓动/
过冲/squash,可与 StylePack 的"设备包定质感 × 类型定语法"正交组合。

3O 归属(待上游): `obase.motion_stylepack`(预设表 + resolve)。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MotionPreset:
    """一组动效参数(30fps 基准)。"""

    name: str
    category: str  # 品类标签(搜索/推荐用)
    energy_axis: float  # -1 沉稳 … +1 高能
    tone_axis: float  # -1 严肃 … +1 活泼
    main_duration_frames: int  # 主时长 @30fps
    ease_in: tuple[float, float, float, float]  # cubic-bezier
    overshoot: float  # 过冲
    squash: float  # squash 幅度


#: 预设表(来源 shotcraft 六档:专业信赖/精致高端/活力大胆/活泼愉悦/平静关怀/亲和友好)。
MOTION_PRESETS: tuple[MotionPreset, ...] = (
    MotionPreset(
        name="enterprise",
        category="fintech/enterprise/B2B",
        energy_axis=-1.0,
        tone_axis=-1.0,
        main_duration_frames=21,
        ease_in=(0.0, 0.0, 0.2, 1.0),
        overshoot=1.0,
        squash=0.0,
    ),
    MotionPreset(
        name="luxury",
        category="奢侈品/时尚",
        energy_axis=-0.5,
        tone_axis=-0.3,
        main_duration_frames=48,
        ease_in=(0.4, 0.0, 0.6, 1.0),
        overshoot=1.02,
        squash=0.0,
    ),
    MotionPreset(
        name="bold",
        category="体育/游戏/startup",
        energy_axis=1.0,
        tone_axis=0.2,
        main_duration_frames=18,
        ease_in=(0.16, 1.0, 0.3, 1.0),
        overshoot=1.12,
        squash=0.25,
    ),
    MotionPreset(
        name="playful",
        category="消费/社交",
        energy_axis=0.5,
        tone_axis=1.0,
        main_duration_frames=27,
        ease_in=(0.34, 1.56, 0.64, 1.0),
        overshoot=1.08,
        squash=0.18,
    ),
    MotionPreset(
        name="calm",
        category="健康/教育",
        energy_axis=-0.8,
        tone_axis=0.6,
        main_duration_frames=42,
        ease_in=(0.42, 0.0, 0.58, 1.0),
        overshoot=1.0,
        squash=0.04,
    ),
    MotionPreset(
        name="friendly",
        category="小微/社区",
        energy_axis=0.0,
        tone_axis=0.8,
        main_duration_frames=26,
        ease_in=(0.25, 0.46, 0.45, 0.94),
        overshoot=1.04,
        squash=0.08,
    ),
)


def resolve_motion_preset(
    *, energy_axis: float, tone_axis: float, name: str | None = None
) -> MotionPreset:
    """按两根轴找最近预设;或按名字直接取。

    Args:
        energy_axis: -1(沉稳)… +1(高能)。
        tone_axis: -1(严肃)… +1(活泼)。
        name: 可选,直接指定预设名(忽略轴)。

    Returns:
        最近的预设。落地要弹的场合由调用方按库内硬判例覆盖(y1>1)。
    """
    if name is not None:
        for preset in MOTION_PRESETS:
            if preset.name == name:
                return preset
        raise KeyError(f"unknown motion preset {name!r}")
    best = MOTION_PRESETS[0]
    best_dist = float("inf")
    for preset in MOTION_PRESETS:
        dist = (preset.energy_axis - energy_axis) ** 2 + (preset.tone_axis - tone_axis) ** 2
        if dist < best_dist:
            best_dist = dist
            best = preset
    return best


def motion_voice_check(preset: MotionPreset, words: list[str]) -> str:
    """自检①:用三个词描述成片动效,与品牌词对得上吗(启发式)。

    返回空串 = 通过;否则返回建议。纯经验规则,不阻断。
    """
    energetic = {"高能", "快", "弹", "活泼", "动感", "活力"}
    calm_words = {"沉稳", "安静", "克制", "优雅", "高级", "信赖"}
    hit_e = sum(1 for w in words if w in energetic)
    hit_c = sum(1 for w in words if w in calm_words)
    if preset.energy_axis > 0.3 and hit_c > hit_e:
        return f"预设偏 {preset.name}(高能),但品牌词偏沉稳:{words}"
    if preset.energy_axis < -0.3 and hit_e > hit_c:
        return f"预设偏 {preset.name}(沉稳),但品牌词偏高能:{words}"
    return ""
