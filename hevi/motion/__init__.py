"""hevi 运动资产域(motion)—— 镜头词汇表/节拍/声音/页面采集/调色/序列模式。

来源: Vincentwei1021/video-shotcraft(Phase B + Round 3 序列/终检)+ heygen-com/hyperframes(调色)。

3O 归属(待上游):
  - `obase.shot_recipe_card`(卡片 schema + 库)
  - `obase.motion_stylepack`(品牌→动效参数表)
  - `oprim.beat_grid_analyze` / `oskill.beat_sync`(节拍卡点)
  - `oskill.sound_design`(BGM 先行 + SFX 钉帧表 + 双版本)
  - `oprim.page_capture` / `oprim.design_token_extract`(产品视频采集)
  - `oprim.color_grade`(分级预设 / LUT 校验)
  - `obase.sequence_pattern` / `oskill.plan_sequence`(能量弧序列模式)
"""

from hevi.motion.beat_sync import (
    BeatGrid,
    BeatSyncError,
    analyze_beat_grid,
    beat_time,
    measure_cut_error,
)
from hevi.motion.color_grade import (
    GRADE_PRESETS,
    GradePreset,
    Lut3D,
    build_ffmpeg_grade_filter,
    grade_ffmpeg_command,
    grade_preset_by_name,
    parse_cube_lut,
)
from hevi.motion.design_token import (
    DesignTokenError,
    DesignTokens,
    normalize_design_tokens,
)
from hevi.motion.interactive import (
    AtlasBudget,
    AtlasManifest,
    atlas_budget,
    atlas_css_background,
    build_atlas_manifest,
    decide_resource_form,
    interactive_frame_budget,
    map_input_to_frame,
    ring_shortest_delta,
    save_atlas_manifest,
)
from hevi.motion.motion_stylepack import (
    MOTION_PRESETS,
    MotionPreset,
    resolve_motion_preset,
)
from hevi.motion.page_capture import (
    PageAsset,
    PageCaptureError,
    capture_page_assets,
)
from hevi.motion.recipe_card import (
    CARD_CATEGORIES,
    ShotRecipeCard,
    build_seed_library,
    find_card,
    validate_card,
)
from hevi.motion.sequence import (
    PROMO_ENERGY_ARC,
    PlannedShot,
    SequencePattern,
    SequenceSegment,
    find_sequence_pattern,
    plan_sequence,
)
from hevi.motion.sound_design import (
    SOUND_VOCABULARIES,
    SfxPin,
    SoundDesign,
    pick_sound_vocabulary,
    validate_sound_design,
)

__all__ = [
    "CARD_CATEGORIES",
    "GRADE_PRESETS",
    "MOTION_PRESETS",
    "PROMO_ENERGY_ARC",
    "SOUND_VOCABULARIES",
    "AtlasBudget",
    "AtlasManifest",
    "BeatGrid",
    "BeatSyncError",
    "DesignTokenError",
    "DesignTokens",
    "GradePreset",
    "Lut3D",
    "MotionPreset",
    "PageAsset",
    "PageCaptureError",
    "PlannedShot",
    "SequencePattern",
    "SequenceSegment",
    "SfxPin",
    "ShotRecipeCard",
    "SoundDesign",
    "analyze_beat_grid",
    "atlas_budget",
    "atlas_css_background",
    "beat_time",
    "build_atlas_manifest",
    "build_ffmpeg_grade_filter",
    "build_seed_library",
    "capture_page_assets",
    "decide_resource_form",
    "find_card",
    "find_sequence_pattern",
    "grade_ffmpeg_command",
    "grade_preset_by_name",
    "interactive_frame_budget",
    "map_input_to_frame",
    "measure_cut_error",
    "normalize_design_tokens",
    "parse_cube_lut",
    "pick_sound_vocabulary",
    "plan_sequence",
    "resolve_motion_preset",
    "ring_shortest_delta",
    "save_atlas_manifest",
    "validate_card",
    "validate_sound_design",
]
