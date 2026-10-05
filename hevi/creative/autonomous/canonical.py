"""S1 CANONOMICALIZATION —— 唯一「谁拥有什么」的地方。

裁决(2026-10-03):本包**不得**新增第 6/7 套 Requirement / Decision / Storyboard /
VisualIntent / Runner / QC / Repair 词汇。它只做三件事:

1. 把 canonical owner 的类型**原样再导出**(供下游单一 import 入口);
2. 提供 **adapter**:Director shot → p0 VisualIntent、shot → p7 AssetRequirement;
3. 记录已知的**词汇分裂**(如实暴露,不假装统一)。

架构守卫见 tests/p10/test_s1_canonical_authority.py:本模块不得定义
AssetRequirement/AssetDecision/VisualIntent/Storyboard/*Runner/Repair* 等类型。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ── canonical re-exports(原样,不改名不包装)──────────────────────────────
from hevi.director.pipeline_schemas import (
    Concept,
    DesignList,
    SceneStage,
    SceneStageSet,
    Screenplay,
    ShotList,
    ShotListItem,
)
from hevi.production.p0_pipeline import VisualIntent
from hevi.production.p7.asset_contract import AssetSemanticRole, MediaType
from hevi.production.p7.asset_decision import AssetDecision, AssetDecisionState
from hevi.production.p7.asset_intelligence import AssetDecisionAuthority, AssetResolution
from hevi.production.p7.asset_requirement import AssetRequirement, SourcePolicy

DIRECTOR_ENTRY = "director_pipeline:semantic_spine"
DIRECTOR_STAGES = ("concept", "screenplay", "design_list", "scene_stage", "shot_list")

# 再导出即本包的公开词汇入口(下游只从这里 import canonical 类型)
__all__ = [
    "DIRECTOR_ENTRY",
    "DIRECTOR_STAGES",
    "KNOWN_SPLITS",
    "AssetDecision",
    "AssetDecisionAuthority",
    "AssetDecisionState",
    "AssetRequirement",
    "AssetResolution",
    "AssetSemanticRole",
    "Concept",
    "DesignList",
    "MediaType",
    "SceneStage",
    "SceneStageSet",
    "Screenplay",
    "ShotList",
    "ShotListItem",
    "SourcePolicy",
    "VisualIntent",
    "VocabularySplit",
    "plan_summary",
    "require_canonical",
    "to_asset_requirement",
    "to_visual_intent",
]


@dataclass(frozen=True)
class VocabularySplit:
    """已知的跨层词汇分裂。如实登记,不假装统一(P1 收口时逐条消解)。"""
    concept: str
    owners: tuple[str, ...]
    canonical: str
    seam: str


KNOWN_SPLITS: tuple[VocabularySplit, ...] = (
    VocabularySplit(
        "ProviderPolicy/ProviderDecision",
        ("hevi/provider_policy/policy.py (pydantic, 权威)",
         "hevi/missions/p3_types.py (dataclass, MissionExecutor 用)"),
        "hevi/provider_policy/policy.py",
        "MissionExecutor 的 mission.provider_policy 是 p3 自己的 dataclass;"
        " 接线时不得把它当 provider_policy 的决策,需显式转换。",
    ),
    VocabularySplit(
        "RunState",
        ("hevi/production/p6/production_runtime.py:73",
         "obase(经 hevi/pipeline/manifest.py:45 引入)"),
        "hevi/production/p6/production_runtime.py",
        "hevi/execution/* 刻意不命名 RunState;三套词汇并存。",
    ),
    VocabularySplit(
        "RepairAction/RepairPlan",
        ("hevi/director/repair_agents.py", "hevi/quality/repair_controller.py",
         "hevi/execution/plan.py", "hevi/creative/layer4/plan_projection.py",
         "hevi/production_graph/contracts.py", "hevi/cinematic/video_gen.py"),
        "hevi/creative/layer4/repair_incident.py",
        "canonical 失败/修复状态 = RepairIncident;其余为 adapter/executor。",
    ),
    VocabularySplit(
        "Subtitle writer",
        ("hevi/assembly/subtitle_align.py", "hevi/assembly/subtitle_timeline_atoms.py",
         "hevi/tongjian/assemble.py", "hevi/ops/p5_1_production.py",
         "hevi/production/media_workflows.py", "hevi/openshorts/clip_engine.py"),
        "hevi/assembly/subtitle_timeline_atoms.py",
        "7 个 writer;validate_srt 在 canonical 侧,生成侧未收口。",
    ),
)


def require_canonical(name: str) -> str:
    """守卫:拒绝在本包内定义被裁决为 canonical-owned 的词汇。"""
    forbidden = {
        "AssetRequirement", "AssetDecision", "AssetScore", "VisualIntent", "Storyboard",
        "AutonomousRunner", "ProductionOrchestrator", "PipelineExecutor", "RepairPolicy",
        "RepairIncident", "QualityEvaluation", "ProductionVerdict", "AutonomousStoryboard",
        "ShotPlan",
    }
    if name in forbidden:
        raise ValueError(f"CANONICALIZATION_VIOLATION:{name} has a canonical owner")
    return name


# ── adapter 1:ShotListItem → p0 VisualIntent ─────────────────────────────


def to_visual_intent(item: ShotListItem, *, timeline_lock_id: str, start_s: float,
                     end_s: float) -> VisualIntent:
    """Director 镜头 → canonical VisualIntent(p0 语义,9 个必填字段)。

    不新增字段;p6 的 `visual_compiler.VisualIntent` 降为 compiler-local,不经此出口。
    """
    entities = tuple(n for n in (item.character_names or []) if n)
    concepts = tuple(n for n in (item.scene_name, item.recipe) if n)
    return VisualIntent(
        intent_id=f"vi:{item.shot_id}",
        timeline_lock_id=timeline_lock_id,
        narration_segment=item.shot_id,
        start_s=start_s,
        end_s=end_s,
        required_entities=entities,
        required_concepts=concepts,
        visual_purpose=item.visual_prompt or item.shot_size or "unspecified",
        motion_purpose=item.camera or "static",
    )


# ── adapter 2:ShotListItem → p7 AssetRequirement ──────────────────────────


def to_asset_requirement(item: ShotListItem, *, semantic_role: AssetSemanticRole,
                         media_type: MediaType = MediaType.VIDEO,
                         source_policy: SourcePolicy = SourcePolicy.PREFERRED_LICENSED,
                         quality_floor: int = 7) -> AssetRequirement:
    """Director 镜头 → canonical p7 AssetRequirement。

    p7 的 requirement 是「类型 + 语义角色 + 约束」,不是 spec 里那套 shot/subject/action。
    镜头语义留在 ShotListItem;需求只表达**要什么类型的什么角色素材**。

    只使用 p7 KNOWN_CONSTRAINTS 里语义相符的键:
      duration ← 镜头时长;query ← 画面检索意图。
    **不**把 shot_size 塞进 `period`(那是年代语义,不是景别)——错键会静默污染
    provider 检索。景别/机位保留在 ShotListItem 与 VisualIntent。
    """
    constraints: list[tuple[str, str]] = []
    if item.duration_s > 0:
        constraints.append(("duration", str(item.duration_s)))
    if item.visual_prompt:
        constraints.append(("query", item.visual_prompt))
    return AssetRequirement(
        media_type=media_type, semantic_role=semantic_role, quantity=1,
        quality_floor=quality_floor, source_policy=source_policy,
        constraints=tuple(constraints),
    )


def plan_summary(*, concept: Concept, screenplay: Screenplay, design_list: DesignList,
                 stage_set: SceneStageSet, shot_list: ShotList) -> dict[str, Any]:
    """dry-run 摘要。只读投影,不新增状态机。"""
    shots = tuple(shot_list.shots)
    return {
        "director_entry": DIRECTOR_ENTRY,
        "stages": list(DIRECTOR_STAGES),
        "concept": concept.model_dump(mode="json"),
        "scenes": len(screenplay.scenes),
        "characters": len(design_list.characters),
        "scenes_designed": len(design_list.scenes),
        "scene_stages": len(stage_set.stages),
        "shots": len(shots),
        "shot_ids": [s.shot_id for s in shots],
        "total_shot_duration_s": round(sum(s.duration_s for s in shots), 3),
        "visual_intents": [
            to_visual_intent(s, timeline_lock_id="dry-run", start_s=0.0,
                             end_s=s.duration_s).intent_id
            for s in shots
        ],
    }