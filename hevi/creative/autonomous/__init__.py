"""S1 CANONOMICALIZATION —— 把既有能力收敛成一条 One-line → Director → MissionExecutor 主干。

本包**不新增** Requirement / Decision / Storyboard / VisualIntent / Runner / QC / Repair 词汇。
唯一绿地是 production_manifest.json(durable projection)。
"""

from hevi.creative.autonomous.acquire import (
    LocalAssetAcquirer,
    NormalizedCandidate,
    normalize_local_asset,
)
from hevi.creative.autonomous.canonical import (
    DIRECTOR_ENTRY,
    DIRECTOR_STAGES,
    KNOWN_SPLITS,
    AssetRequirement,
    AssetSemanticRole,
    Concept,
    DesignList,
    MediaType,
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
from hevi.creative.autonomous.identity import (
    RequirementBinding,
    RequirementBindingSet,
    RequirementIdentityError,
)
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
from hevi.creative.autonomous.selection import (
    CANDIDATE_SELECTION,
    PROVIDER_SELECTION,
    SelectionAuthority,
    SelectionPath,
    ShotResolution,
    assert_single_authority,
    resolve,
)
from hevi.creative.autonomous.verdict import (
    ProductionVerdict,
    ProductionVerdictAuthority,
    VerdictInput,
    VerdictOutcome,
)

__all__ = [
    "Acquirer",
    "AssetRequirement",
    "AssetResolver",
    "AssetSemanticRole",
    "Concept",
    "DIRECTOR_ENTRY",
    "DIRECTOR_STAGES",
    "DesignList",
    "DryRunResult",
    "ExecutionReadyResolution",
    "KNOWN_SPLITS",
    "LocalAssetAcquirer",
    "MediaType",
    "NormalizedCandidate",
    "CANDIDATE_SELECTION",
    "PROVIDER_SELECTION",
    "ProductionManifest",
    "ProductionVerdict",
    "ProductionVerdictAuthority",
    "RequirementBinding",
    "RequirementBindingSet",
    "RequirementIdentityError",
    "SCHEMA_VERSION",
    "SceneStage",
    "SceneStageSet",
    "Screenplay",
    "ShotList",
    "ShotListItem",
    "SelectionAuthority",
    "SelectionPath",
    "ShotResolution",
    "StageProjection",
    "assert_single_authority",
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
    "normalize_local_asset",
    "resolve",
    "to_visual_intent",
]