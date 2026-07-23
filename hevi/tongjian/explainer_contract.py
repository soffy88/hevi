"""讲解段数据契约 —— HEVI-EXPLAINER-PIPELINE-SPEC-001 §3 数据模型的**逐字投影**。

★ G1a 纪律(裁决 2026-07-21):VisualFact 等形状必须是 `history-contract-v0.1` 契约的投影,
**字段自造一个都不行**——这是 G1b(改由 KU 接口拉取)对拍的前置。本文件严格只含 §3 列出的字段,
不多不少;字段名用英文 + §3 原名注释一一对应(命名是语言选择,不是新增字段)。

G1a 手工装配 VisualFact 时用本 schema;G1b 换 KU 拉取时产出必须能填进同一 schema、逐字段对拍。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# visual_intent 枚举(§3,含【新】dual_account)
VISUAL_INTENTS = frozenset(
    {
        "establish",
        "highlight",
        "split_merge",
        "expand",
        "route",
        "battle",
        "character",
        "compare",
        "city",
        "timeline",
        "dual_account",
        "hold",
    }
)

# evidence_tier 分级(§12 R9 / KU §6,E0 最可信 → E4 最弱)
EVIDENCE_TIERS = frozenset({"E0", "E1", "E2", "E3", "E4"})


class EpisodePlan(BaseModel):
    """§3 EpisodePlan {episode_id, 断代, event_ku_refs[], narrative_frame, 讲解稿ref}。"""

    episode_id: str
    dynasty_era: str = ""  # 断代
    event_ku_refs: list[str] = Field(default_factory=list)  # 钉 KU fingerprint 集
    narrative_frame: str = ""
    narration_script_ref: str = ""  # 讲解稿ref


class NarrationBeat(BaseModel):
    """§3 NarrationBeat {beat_id, order, vo_text, est_vo_seconds, visual_intent, fact_ref}。"""

    beat_id: str
    order: int
    vo_text: str
    est_vo_seconds: float
    visual_intent: str
    fact_ref: str = ""

    @field_validator("visual_intent")
    @classmethod
    def _intent_in_enum(cls, v: str) -> str:
        if v not in VISUAL_INTENTS:
            raise ValueError(f"visual_intent 非法: {v!r}(§3 枚举外,不许自造)")
        return v


class Quantity(BaseModel):
    """§3 quantities[] 项 {value, unit, source_display, ku_ref}。R4 逐源标注。"""

    value: float
    unit: str = ""
    source_display: str = ""  # 如 "《史记》载"
    ku_ref: str = ""


class VisualFact(BaseModel):
    """§3 VisualFact {beat_id, ku_refs[], date, scope, forces[], regions[], routes[],
    markers[], persons[], quantities[], evidence_tier, confirmed_by}。**逐字,不多不少。**"""

    beat_id: str
    ku_refs: list[str] = Field(default_factory=list)
    date: int | None = None  # 公元纪年,负=BC(R2 canonical)
    scope: str = ""
    forces: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    routes: list[str] = Field(default_factory=list)
    markers: list[str] = Field(default_factory=list)
    persons: list[str] = Field(default_factory=list)
    quantities: list[Quantity] = Field(default_factory=list)
    evidence_tier: str = "E1"
    confirmed_by: str = ""

    @field_validator("evidence_tier")
    @classmethod
    def _tier_in_enum(cls, v: str) -> str:
        if v not in EVIDENCE_TIERS:
            raise ValueError(f"evidence_tier 非法: {v!r}(须 E0–E4)")
        return v


class Account(BaseModel):
    """§3 DualAccountFact.accounts[] 项 {source_display, 摘述}。"""

    source_display: str
    summary: str = ""  # 摘述


class DualAccountFact(BaseModel):
    """§3 DualAccountFact {beat_id, conflict_ku_ref, accounts[2], dimension, presentation_hint}。
    对勘拍(S12)数据;presentation_hint 决定用 S12 还是主线+角标。"""

    beat_id: str
    conflict_ku_ref: str = ""
    accounts: list[Account]
    dimension: str = ""
    presentation_hint: str = ""

    @field_validator("accounts")
    @classmethod
    def _exactly_two(cls, v: list[Account]) -> list[Account]:
        if len(v) != 2:
            raise ValueError(f"accounts 必须恰好 2 个(§3 accounts[2]),得到 {len(v)}")
        return v
