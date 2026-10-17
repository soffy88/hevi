"""hevi 连续性与导演词表扩展子包 (CONT-1017)。"""

from __future__ import annotations

from hevi.prompt.continuity.checklist import ReviewItem, review_checklist
from hevi.prompt.continuity.compiler import (
    ContinuityRender,
    compile_continuity_prompt,
    export_continuity_markdown,
    export_continuity_package,
)
from hevi.prompt.continuity.first_frame import (
    FIRST_FRAME_REQUIREMENTS,
    AssetRefSpec,
    FirstFrameResult,
    build_local_edit_prompt,
    build_outpaint_prompt,
    compile_asset_refs,
    compile_end_frame,
    compile_first_frame,
    validate_first_frame,
)
from hevi.prompt.continuity.schemas import (
    CharacterCard,
    FilmBible,
    GenerationLog,
    PropItem,
    PropLedger,
    ReferenceAsset,
    SceneCard,
    ShotContract,
    ShotDialogue,
    VoiceCard,
)
from hevi.prompt.continuity.validator import validate_film
from hevi.prompt.continuity.vocab import (
    Category,
    RiskLevel,
    VocabItem,
    find_post_only_violations,
    get_vocab_item,
    is_post_only,
    list_vocab_by_category,
)

__all__ = [
    # Schemas
    "FilmBible",
    "CharacterCard",
    "VoiceCard",
    "SceneCard",
    "PropItem",
    "PropLedger",
    "ShotDialogue",
    "ShotContract",
    "GenerationLog",
    "ReferenceAsset",
    # Compiler
    "compile_continuity_prompt",
    "ContinuityRender",
    "export_continuity_package",
    "export_continuity_markdown",
    # First Frame (FF-1017)
    "compile_first_frame",
    "compile_end_frame",
    "compile_asset_refs",
    "build_local_edit_prompt",
    "build_outpaint_prompt",
    "validate_first_frame",
    "FirstFrameResult",
    "AssetRefSpec",
    "FIRST_FRAME_REQUIREMENTS",
    # Validator
    "validate_film",
    # Checklist
    "review_checklist",
    "ReviewItem",
    # Vocab
    "VocabItem",
    "RiskLevel",
    "Category",
    "get_vocab_item",
    "list_vocab_by_category",
    "is_post_only",
    "find_post_only_violations",
]
