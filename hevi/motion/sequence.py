"""全片序列模式 —— 能量弧骨架 + 确定性预算分配(3O 内化 Round 3,来源 shotcraft sequences/)。

video-shotcraft 的 `sequences/promo-energy-arc.md` 是把散落节奏规则合成"一条可直接
填空的全片曲线"的配方:4 段位 + 呼吸字卡。其核心纪律(hevi 此前缺失):
  1. 先按段位分配总预算,再挑卡 —— 不是 ad-hoc 推导。
  2. 每镜预算内**先划走 hold/rest 帧**(R1 落定 ≥30f、批量收尾 15f),再排动效。
  3. 功能段能量交替(高⇄低);信息密度最高的镜头放在峰值收场之前。
  4. 呼吸字卡:每 1–2 个功能镜后一张,50–55f,全片 2–4 张。

本模块为 hevi 暂驻(待上游 `obase.sequence_pattern` / `oskill.plan_sequence`):
确定性分配纯函数可测;promo_video_workflow 用它替代 naive 卡循环。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: 节奏硬项(shotcraft R1/R3 判例):落定 hold ≥30f、批量收尾静止 15f。
HOLD_FRAMES = 30
REST_FRAMES = 15
#: 呼吸字卡:单张 50–55f;每 1–2 功能镜一张;全片 2–4 张。
BREATH_CARD_RANGE = (50, 55)
BREATH_CARD_MIN = 2
BREATH_CARD_MAX = 4


@dataclass(frozen=True)
class SequenceSegment:
    """一个段位:职责 + 时长占比区间 + 能量。"""

    role: str
    share_min: float  # 占总时长比例下限
    share_max: float
    energy: str  # low | medium | high
    purpose: str
    candidate_cards: tuple[str, ...] = ()
    hold_at_end: bool = False  # 段位尾部需要落定 hold(R1)


@dataclass(frozen=True)
class SequencePattern:
    """一条全片序列模式(可直接填空)。"""

    name: str
    one_liner: str
    segments: tuple[SequenceSegment, ...]
    applies_to: str = "30-60s 多功能 web 产品宣传片默认结构"
    known_pitfalls: tuple[str, ...] = ()


#: 种子:promo-energy-arc(来源 shotcraft sequences/promo-energy-arc.md)。
PROMO_ENERGY_ARC = SequencePattern(
    name="promo-energy-arc",
    one_liner="低开品牌 → 单主角立传 → 字卡呼吸间隔的功能爬升段 → 发布会峰值收场",
    segments=(
        SequenceSegment(
            role="brand_open", share_min=0.08, share_max=0.12, energy="low",
            purpose="字标压印 + hold ≥1s,交棒产品页面",
            candidate_cards=("brand-ink-open",), hold_at_end=True,
        ),
        SequenceSegment(
            role="hero", share_min=0.12, share_max=0.15, energy="medium",
            purpose="一个主角、一条完整动作弧 ≥3s,立出产品原子单位",
            candidate_cards=("spotlight-hero-card",),
        ),
        SequenceSegment(
            role="feature_climb", share_min=0.55, share_max=0.65, energy="high",
            purpose="每镜绑一个独特功能、一种手法只当一次主角;能量高⇄低交替",
            candidate_cards=(
                "deck-deal-flyin", "type-and-filter", "list-stack-press",
                "row-embed", "document-typewriter-reveal",
            ),
        ),
        SequenceSegment(
            role="launch_peak", share_min=0.13, share_max=0.16, energy="high",
            purpose="已展示功能各出代表元素合影围住字标,sign-off hold ≥1s",
            candidate_cards=("outro-group-photo-launch",), hold_at_end=True,
        ),
    ),
    known_pitfalls=(
        "骨架当风格令全局硬套:15s 短片或单功能产品应大胆合并段位,但①hold/④峰值两端不可省",
        "功能段只堆高能量镜:连续高能量读作嘈杂,交替与字卡就是节奏本身",
        "呼吸字卡写成第二遍 tagline:字卡与 outro 文案重复即删",
    ),
)


@dataclass
class PlannedShot:
    """分配后的一个镜头槽位。"""

    role: str  # brand_open | hero | feature | breath | launch_peak
    index: int
    start_frame: int
    duration_frames: int
    energy: str
    purpose: str
    candidate_cards: tuple[str, ...] = ()
    hold_frames: int = 0  # 预算内先划走的落定帧
    rest_frames: int = 0  # 批量收尾静止帧

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "index": self.index,
            "start_frame": self.start_frame,
            "duration_frames": self.duration_frames,
            "energy": self.energy,
            "purpose": self.purpose,
            "candidate_cards": list(self.candidate_cards),
            "hold_frames": self.hold_frames,
            "rest_frames": self.rest_frames,
        }


def _alternate_energy(i: int) -> str:
    """功能段能量交替:高→稳→高→稳(信息密度镜头放峰值前倒数位由调用方调)。"""
    return "high" if i % 2 == 0 else "medium"


def plan_sequence(
    pattern: SequencePattern,
    *,
    total_duration_s: float,
    fps: int = 30,
    feature_count: int,
    breath_cards: int | None = None,
) -> list[PlannedShot]:
    """确定性分配:段位占比 → 预算;每镜先划走 hold/rest 再排动效。

    Args:
        pattern: 序列模式(默认 PROMO_ENERGY_ARC)。
        total_duration_s: 全片目标时长。
        fps: 帧率。
        feature_count: 功能镜头数(③段均分预算)。
        breath_cards: 呼吸字卡数;None 按每 2 功能镜一张夹在 [2,4]。

    Returns:
        按 start_frame 升序的 PlannedShot 列表(含呼吸字卡槽位)。
    """
    total_frames = int(total_duration_s * fps)
    if total_frames <= 0:
        return []

    # 1) 段位占比分配(按 share 中值),③ 段剩余吃满
    segment_shares = [((s.share_min + s.share_max) / 2.0) for s in pattern.segments]
    total_share = sum(segment_shares)
    scaled = [s / total_share for s in segment_shares]
    frames_per_segment = [int(total_frames * s) for s in scaled]
    # ③ 段吸收舍入余量
    frames_per_segment[-2] += total_frames - sum(frames_per_segment)

    feature_count = max(feature_count, 1)
    if breath_cards is None:
        breath_cards = max(BREATH_CARD_MIN, min(BREATH_CARD_MAX, feature_count // 2))

    shots: list[PlannedShot] = []
    cursor = 0
    idx = 0
    # ① 品牌开场
    seg0 = pattern.segments[0]
    hold = HOLD_FRAMES if seg0.hold_at_end else 0
    shots.append(
        PlannedShot(
            role=seg0.role, index=idx, start_frame=cursor,
            duration_frames=frames_per_segment[0], energy=seg0.energy,
            purpose=seg0.purpose, candidate_cards=seg0.candidate_cards,
            hold_frames=hold,
        )
    )
    cursor += frames_per_segment[0]
    idx += 1
    # ② 单主角立传
    seg1 = pattern.segments[1]
    shots.append(
        PlannedShot(
            role=seg1.role, index=idx, start_frame=cursor,
            duration_frames=frames_per_segment[1], energy=seg1.energy,
            purpose=seg1.purpose, candidate_cards=seg1.candidate_cards,
        )
    )
    cursor += frames_per_segment[1]
    idx += 1
    # ③ 功能爬升 + 呼吸字卡(字卡夹在功能镜之间,预算从功能段划走)
    seg2 = pattern.segments[2]
    climb_frames = frames_per_segment[2]
    breath_total = sum(BREATH_CARD_RANGE) // 2 * breath_cards  # 每张 ~52f
    feature_frames_total = max(climb_frames - breath_total, feature_count * 30)
    per_feature = feature_frames_total // feature_count
    feature_shots: list[PlannedShot] = []
    for i in range(feature_count):
        energy = _alternate_energy(i)
        feature_shots.append(
            PlannedShot(
                role=seg2.role, index=0, start_frame=0,
                duration_frames=per_feature, energy=energy,
                purpose=seg2.purpose,
                candidate_cards=seg2.candidate_cards,
                rest_frames=REST_FRAMES,
            )
        )
    # 插入呼吸字卡:均匀分布在功能镜之间(不插在最后一个功能镜后),数量 = breath_cards
    # (shotcraft 规则:每 1–2 个功能镜后一张,全片 2–4 张)。
    merged: list[PlannedShot] = []
    if feature_count > 0:
        gaps = feature_count - 1  # 功能镜之间的间隔数
        insert_after = sorted(
            {
                (gaps * k) // (breath_cards + 1)
                for k in range(1, breath_cards + 1)
                if gaps > 0
            }
        )
        for i, shot in enumerate(feature_shots):
            merged.append(shot)
            if i in insert_after and i < feature_count - 1:
                merged.append(
                    PlannedShot(
                        role="breath", index=0, start_frame=0,
                        duration_frames=sum(BREATH_CARD_RANGE) // 2,
                        energy="low", purpose="呼吸字卡:信息落定后的节奏位",
                        candidate_cards=("paper-title-card",),
                        hold_frames=HOLD_FRAMES,
                    )
                )
    for shot in merged:
        shot.start_frame = cursor
        cursor += shot.duration_frames
        shot.index = idx
        idx += 1
    shots.extend(merged)
    # ④ 发布会收场
    seg3 = pattern.segments[-1]
    shots.append(
        PlannedShot(
            role=seg3.role, index=idx, start_frame=cursor,
            duration_frames=frames_per_segment[-1], energy=seg3.energy,
            purpose=seg3.purpose, candidate_cards=seg3.candidate_cards,
            hold_frames=HOLD_FRAMES,
        )
    )
    return shots


def find_sequence_pattern(name: str) -> SequencePattern:
    """按名取模式;未知抛 KeyError。"""
    if name == PROMO_ENERGY_ARC.name:
        return PROMO_ENERGY_ARC
    raise KeyError(f"unknown sequence pattern {name!r}")
