"""hevi 合成/装配模块。

RFC-002 后已从死代码转为主链路: assembler(音频驱动时长 + xfade + loudnorm)、
subtitle_align(ASR 强制对齐字幕)、cover_extractor 均被 longvideo 编排调用。

剪辑成片层（对标 video-use）: edit_craft 硬规则 + takes_pack + edit_render + cut_self_eval。
"""

from hevi.assembly.animation_overlay import OverlayPlan, OverlayTask, generate_all_overlays
from hevi.assembly.aspect_ratio import AspectRatio
from hevi.assembly.assembler import ShotSegment, assemble_longvideo
from hevi.assembly.color_grade import ASCCDL, GradePipeline, SegmentGrade, resolve_grade
from hevi.assembly.cover_extractor import extract_cover
from hevi.assembly.cut_self_eval import SelfEvalReport, assert_self_eval_passed, self_eval_edl
from hevi.assembly.edit_craft import (
    EditCraftError,
    EditDecisionList,
    EditRange,
    require_strategy_confirmation,
    validate_edl,
)
from hevi.assembly.edit_pipeline import talking_head_cleanup
from hevi.assembly.filler_cut import FillerCutPlan, plan_filler_cut
from hevi.assembly.postprocess_service import postprocess_video
from hevi.assembly.scribe_service import (
    ScribeClient,
    ScribeTranscript,
    ScribeWord,
    WordGap,
    find_best_gap,
    find_word_gaps,
)
from hevi.assembly.session_memory import SessionMemory, load_or_create, save
from hevi.assembly.strategy_enforcement import ConfirmationStatus, StrategyGate
from hevi.assembly.subtitle_align import align_subtitles
from hevi.assembly.takes_pack import pack_edit_dir, pack_phrases
from hevi.assembly.take_selector import SelectionResult, TakeSet, select_best_takes

__all__ = [
    "ASCCDL",
    "AspectRatio",
    "ConfirmationStatus",
    "EditCraftError",
    "EditDecisionList",
    "EditRange",
    "FillerCutPlan",
    "GradePipeline",
    "OverlayPlan",
    "OverlayTask",
    "SegmentGrade",
    "SelectionResult",
    "SelfEvalReport",
    "SessionMemory",
    "ShotSegment",
    "ScribeClient",
    "ScribeTranscript",
    "ScribeWord",
    "StrategyGate",
    "TakeSet",
    "WordGap",
    "align_subtitles",
    "assemble_longvideo",
    "assert_self_eval_passed",
    "extract_cover",
    "find_best_gap",
    "find_word_gaps",
    "generate_all_overlays",
    "load_or_create",
    "pack_edit_dir",
    "pack_phrases",
    "plan_filler_cut",
    "postprocess_video",
    "require_strategy_confirmation",
    "resolve_grade",
    "save",
    "select_best_takes",
    "self_eval_edl",
    "talking_head_cleanup",
    "validate_edl",
]
