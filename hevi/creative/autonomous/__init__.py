"""S1 CANONOMICALIZATION —— 把既有能力收敛成一条 One-line → Director → MissionExecutor 主干。

本包**不新增** Requirement / Decision / Storyboard / VisualIntent / Runner / QC / Repair 词汇。
唯一绿地是 production_manifest.json(durable projection)。
"""

from hevi.creative.autonomous.canonical import (
    DIRECTOR_ENTRY,
    DIRECTOR_STAGES,
    KNOWN_SPLITS,
    Concept,
    DesignList,
    SceneStage,
    SceneStageSet,
    Screenplay,
    ShotList,
    ShotListItem,
    VisualIntent,
    VocabularySplit,
    plan_summary,
    require_canonical,
    to_asset_requirement,
    to_visual_intent,
)
from hevi.creative.autonomous.dry_run import DryRunResult, dry_run, to_manifest
from hevi.creative.autonomous.manifest import (
    SCHEMA_VERSION,
    ProductionManifest,
    StageProjection,
    assert_no_secrets,
    build_from_mission,
)
from hevi.creative.autonomous.resolver import (
    Acquirer,
    AssetResolver,
    ExecutionReadyResolution,
)
from hevi.creative.autonomous.verdict import (
    ProductionVerdict,
    ProductionVerdictAuthority,
    VerdictInput,
    VerdictOutcome,
)

__all__ = [
    "Acquirer",
    "AssetResolver",
    "Concept",
    "DIRECTOR_ENTRY",
    "DIRECTOR_STAGES",
    "DesignList",
    "DryRunResult",
    "ExecutionReadyResolution",
    "KNOWN_SPLITS",
    "ProductionManifest",
    "ProductionVerdict",
    "ProductionVerdictAuthority",
    "SCHEMA_VERSION",
    "SceneStage",
    "SceneStageSet",
    "Screenplay",
    "ShotList",
    "ShotListItem",
    "StageProjection",
    "VerdictInput",
    "VerdictOutcome",
    "VocabularySplit",
    "VisualIntent",
    "assert_no_secrets",
    "build_from_mission",
    "dry_run",
    "plan_summary",
    "require_canonical",
    "to_asset_requirement",
    "to_manifest",
    "to_visual_intent",
]