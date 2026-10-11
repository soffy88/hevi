"""L4 Editor —— 消费评分卡 → 返工与节奏。

设计 §3 L4:Editor 读裁决结果,决定重拍哪些镜头、什么时候交付。它把这一路的件闭成环:
  - 输入:整片确定性体检 `quality`(§7-4)+ 逐镜头选优明细 `shots`(C3 落库,含
    consistency_score / passed)
  - 输出:`EditDecision`(交付 or 定向返工),`regenerate_shot_ids` + `hints` 直接喂
    `TaskService.regenerate_task_shots`(verdict→返工闭环)。

"guilty until proven innocent":不及格镜头 / 一致性分偏低 → 返工;整片体检不过 → 不交付。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# HEVI 路线图 §4.3"返工接口升级":固定诊断分类表,取代此前的自由文本 hints——让重新
# 富化 prompt 的一步知道该拉哪根杠杆,而不是盲目重掷。目前只有身份/一致性这一个信号源
# 能可靠归类(→ REFERENCE_MISMATCH);其余分类需要 Tier0/Tier1(#32/#33)、VLM 违规明细
# 等尚未接入的信号,先占好位置,不用没有依据的启发式硬猜。
CAMERA = "运镜"
LIGHTING = "光照"
MOTION = "动作"
REFERENCE_MISMATCH = "参考图角色错配"
DURATION = "时长"
COMPOSITION = "构图"
AUDIO = "音频"
SAFETY_FALSE_POSITIVE = "安全词误触发"
DIAGNOSIS_CATEGORIES = (
    CAMERA,
    LIGHTING,
    MOTION,
    REFERENCE_MISMATCH,
    DURATION,
    COMPOSITION,
    AUDIO,
    SAFETY_FALSE_POSITIVE,
)


@dataclass
class EditDecision:
    deliver: bool
    regenerate_shot_ids: list[int]
    hints: dict[int, str]
    # shot idx → DIAGNOSIS_CATEGORIES 里的固定分类(不是 hints 里的自由文本,供
    # shot_verdict/日志按分类统计返工原因分布,见 HEVI 路线图 §6.2)。
    diagnosis: dict[int, str] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


# 返工一致性门槛默认值。**尺度警告**:shot_states.consistency_score 是 scorecard 的
# identity_score(CLIP 余弦,scorecard 自己的 identity_floor=0.2),不是 0-1 均匀分布的
# 质量分。2026-07-11 G1 真跑实测 mean 0.591 / min 0.454、全部 passed=True,却因旧默认
# 0.75 被判 100% “参考图角色错配” → 整轮重烧。0.35 与 scorecard 尺度对齐。
DEFAULT_CONSISTENCY_FLOOR = 0.35


def select_rework_shots(
    shots: list[dict[str, Any]],
    *,
    consistency_floor: float = DEFAULT_CONSISTENCY_FLOOR,
    min_rework_count: int = 1,
    full_rework: bool = False,
) -> list[int]:
    """确定性挑选需要返工的镜头。**只挑未通过/低分/有诊断的镜头**,已通过的镜头不选。

    - `full_rework=True`:显式整轮重做(旧行为,保留给人工兜底/换风格场景),返回全部。
    - `passed=False` → 硬失败,必须返工。
    - `consistency_score < consistency_floor` → 软错配,受 `min_rework_count` 门槛过滤
      (零星软错配只记诊断不返工)。
    - 已通过且无诊断的镜头永远不进列表 → 调用方复用其产物。
    """
    indexes = [s.get("index") for s in shots if s.get("index") is not None]
    if full_rework:
        return sorted(indexes)
    hard: set[int] = set()
    soft: set[int] = set()
    for s in shots:
        idx = s.get("index")
        if idx is None:
            continue
        score = s.get("consistency_score")
        if not s.get("passed", False):
            hard.add(idx)
        elif score is not None and score < consistency_floor:
            soft.add(idx)
    if soft and len(soft) < min_rework_count:
        soft = set()
    return sorted(hard | soft)


def review(
    *,
    quality: dict[str, Any] | None,
    shots: list[dict[str, Any]],
    consistency_floor: float = DEFAULT_CONSISTENCY_FLOOR,
    min_rework_count: int = 1,
    full_rework: bool = False,
) -> EditDecision:
    """裁决:哪些镜头返工、能否交付。

    - 镜头 `passed=False` 或 `consistency_score < floor` → 列入 `regenerate_shot_ids` + hints。
    - 整片体检 `quality.passed=False` 或有镜头待返工 → `deliver=False`。
    - 返工完成后由调用方再 review 一轮(loop 收敛)。
    - `min_rework_count`:错配镜头数门槛(G1 实测身份匹配系统性偏低,
      零星 1-2 镜错配直接返工 = 每任务白付 2× 云费;低于门槛只记录诊断,
      不触发整片返工 —— 全废(黑帧/大面积错配)仍会返工)。
    - `full_rework=True`:显式整轮重做(所有镜头),不再按镜头级判定。
    """
    hard: dict[int, str] = {}  # passed=False(黑帧/全废) → 必须返工
    soft: dict[int, str] = {}  # 一致性分偏低(软错配) → 可按门槛过滤
    diagnosis: dict[int, str] = {}
    reasons: list[str] = []

    for s in shots:
        idx = s.get("index")
        if idx is None:
            continue
        score = s.get("consistency_score")
        if not s.get("passed", False):
            diagnosis[idx] = REFERENCE_MISMATCH
            hard[idx] = f"[{REFERENCE_MISMATCH}] 镜头未过一致性校验,重生成"
        elif score is not None and score < consistency_floor:
            diagnosis[idx] = REFERENCE_MISMATCH
            soft[idx] = (
                f"[{REFERENCE_MISMATCH}] 一致性分 {score:.2f} < {consistency_floor} 偏低,重生成"
            )

    # 软错配门槛(G1 实测身份匹配系统性偏低,零星错配直接返工 = 白付 2× 云费):
    # 低于门槛的零星软错配只记录诊断不返工;硬失败(黑帧/全废)与大面积错配仍返工。
    if soft and len(soft) < min_rework_count:
        reasons.append(
            f"{len(soft)} 个镜头一致性偏低(< 门槛 {min_rework_count}),本次不返工,已记录诊断"
        )
        soft = {}

    if full_rework:
        all_idx = [s.get("index") for s in shots if s.get("index") is not None]
        regen = {idx: f"[显式整轮重做] 重生成镜头 {idx}" for idx in all_idx}
        for idx in all_idx:
            diagnosis.setdefault(idx, REFERENCE_MISMATCH)
        reasons.append(f"显式整轮重做:{len(regen)} 个镜头")
    else:
        regen = {**hard, **soft}

    quality_ok = quality is not None and quality.get("passed") is True
    if not quality_ok and quality is not None:
        reasons.append(f"整片体检不过:{quality.get('violations', [])}")
    if regen:
        reasons.append(f"{len(regen)} 个镜头需返工:{sorted(regen)}")

    return EditDecision(
        deliver=quality_ok and not regen,
        regenerate_shot_ids=sorted(regen),
        hints=regen,
        diagnosis=diagnosis,
        reasons=reasons,
    )
