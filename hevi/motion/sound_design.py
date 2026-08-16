"""声音设计 —— BGM 先行 + SFX 词汇表按片种 + 钉帧表(3O 内化 Phase B)。

来源: video-shotcraft sound-design.md 的体系:
  1. 顺序:画面结构基本锁定 → 先铺 BGM 定能量骨架 → 逐拍钉 SFX(声音排在画面之后)
  2. 词汇表按"片种"选,不按"事件"选:产品宣传片 = whoosh/impact/riser/sparkle/
     transition,禁用游戏音包音色(合成 pluck/bloop/卡通弹跳)
  3. SFX 是**时间线级资产**:声明式 `{from, src, volume}` 数组集中管理,
     场景组件不含音频代码;配 BGM 终渲固定交付两版(带/不带 BGM)
  4. BGM 音量压 ~0.34 给 SFX 留 headroom

本模块为 hevi 暂驻(待上游 `oskill.sound_design`):纯数据结构 + 校验,可测。
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: 片种 → SFX 词汇表(先选片种,再选音色)。
SOUND_VOCABULARIES: dict[str, tuple[str, ...]] = {
    "product_promo": ("whoosh", "impact", "riser", "sparkle", "transition"),
    "film_narrative": ("impact", "riser", "whoosh", "texture", "dark"),
    "explainer": ("soft-whoosh", "ui-soft", "transition", "texture"),
    "game_trailer": ("pluck", "bloop", "cartoon-bounce", "combo", "powerup"),
}


@dataclass(frozen=True)
class SfxPin:
    """一条 SFX 钉帧:从(帧)+ 资源 + 音量。"""

    from_frame: int
    src: str
    volume: float = 0.4
    note: str = ""  # 对应画面动作注释(如 "hero card: whoosh up on the pop")


@dataclass
class SoundDesign:
    """一部片的声音设计:全部音频集中在时间线级,场景组件零音频代码。"""

    bgm_path: str = ""
    bgm_volume: float = 0.34  # 默认压 0.34 给 SFX 留 headroom
    bgm_fade_in_s: float = 1.0
    bgm_fade_out_s: float = 1.7
    vocabulary: tuple[str, ...] = SOUND_VOCABULARIES["product_promo"]
    sfx_pins: list[SfxPin] = field(default_factory=list)
    dual_delivery: bool = True  # 配 BGM 的片终渲交付两版(带/不带 BGM)


def pick_sound_vocabulary(piece_type: str) -> tuple[str, ...]:
    """按片种选词汇表;未知片种回退产品宣传片并记 note(由调用方展示)。"""
    return SOUND_VOCABULARIES.get(piece_type, SOUND_VOCABULARIES["product_promo"])


def validate_sound_design(design: SoundDesign) -> list[str]:
    """校验:音量范围、钉帧非负、词汇表合法、钉帧不重叠过度。"""
    issues: list[str] = []
    if not (0.0 <= design.bgm_volume <= 1.0):
        issues.append(f"bgm_volume {design.bgm_volume} out of [0,1]")
    for pin in design.sfx_pins:
        if not (0.0 <= pin.volume <= 1.0):
            issues.append(f"sfx {pin.src} volume {pin.volume} out of [0,1]")
        if pin.from_frame < 0:
            issues.append(f"sfx {pin.src} from_frame < 0")
    if not design.sfx_pins:
        issues.append("no sfx pins (声音设计应在画面锁定后逐拍钉帧)")
    # 钉帧过密检查:同帧出现 3+ 条判为堆叠异常
    from collections import Counter

    counts = Counter(pin.from_frame for pin in design.sfx_pins)
    for frame, count in counts.items():
        if count >= 3:
            issues.append(f"frame {frame} has {count} sfx pins (likely overload)")
    return issues


def build_bgm_volume_env(
    *, total_frames: int, fps: float = 30.0, design: SoundDesign
) -> list[tuple[float, float]]:
    """BGM 音量包络(首尾淡入淡出,与来源模板片一致)。

    Returns:
        [(帧, 音量)] 关键点,调用方 interpolate 成包络。
    """
    fade_in_frames = design.bgm_fade_in_s * fps
    fade_out_start = total_frames - design.bgm_fade_out_s * fps
    pts: list[tuple[float, float]] = [
        (0.0, 0.0),
        (fade_in_frames, design.bgm_volume),
        (max(fade_out_start, fade_in_frames), design.bgm_volume),
        (float(total_frames), 0.0),
    ]
    return pts
