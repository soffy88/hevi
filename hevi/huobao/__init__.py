"""Hevi Huobao package — short-drama agent layer absorbed from huobao-drama.

Implements:
1. Asset registry & cross-episode dedup (Character, Scene, Prop).
2. Keyframe generation for assets & shots (CPU guofeng_anime preset).
3. Storyboard @ref syntax resolution (@角色/@场景/@道具).
4. Tone-aware novel-to-screenplay rewriter with verbatim dialogue preservation.
5. Batch estimation, failed-shot retry, and merge validation.
"""

from __future__ import annotations

from hevi.huobao.assets import (
    AssetRegistry,
    CharacterAsset,
    PropAsset,
    SceneAsset,
    normalize_name,
)
from hevi.huobao.batch import (
    BatchEstimate,
    MissingClipPrerequisiteError,
    ShotTask,
    estimate_batch,
    retry_failed_shots,
    validate_merge_prerequisites,
)
from hevi.huobao.refs import (
    ResolvedPrompt,
    UnknownAssetReferenceError,
    parse_references,
    resolve_references,
)
from hevi.huobao.rewrite import (
    TONES,
    rewrite_novel_to_screenplay,
    verify_dialogue_retention,
)
from hevi.huobao.capabilities import (
    register_huobao_capabilities,
)

__all__ = [
    "TONES",
    "AssetRegistry",
    "BatchEstimate",
    "CharacterAsset",
    "MissingClipPrerequisiteError",
    "PropAsset",
    "ResolvedPrompt",
    "SceneAsset",
    "ShotTask",
    "UnknownAssetReferenceError",
    "estimate_batch",
    "normalize_name",
    "parse_references",
    "register_huobao_capabilities",
    "resolve_references",
    "retry_failed_shots",
    "rewrite_novel_to_screenplay",
    "validate_merge_prerequisites",
    "verify_dialogue_retention",
]
