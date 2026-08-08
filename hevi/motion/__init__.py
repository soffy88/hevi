"""hevi 运动资产域(motion)—— 镜头词汇表/节拍/声音/页面采集,3O 内化 Phase B。

来源: Vincentwei1021/video-shotcraft —— Hevi 把 StylePack 停留在文档,
他们做成了 104 张能跑的镜头配方卡 + 判例式审美准则 + 节拍卡点方法论 +
声音设计体系 + 页面采集/设计 token。

3O 归属(待上游):
  - `obase.shot_recipe_card`(卡片 schema + 库)
  - `obase.motion_stylepack`(品牌→动效参数表)
  - `oprim.beat_grid_analyze` / `oskill.beat_sync`(节拍卡点)
  - `oskill.sound_design`(BGM 先行 + SFX 钉帧表 + 双版本)
  - `oprim.page_capture` / `oprim.design_token_extract`(产品视频采集)
  - `oskill.aesthetic_canon`(判例式审美准则,hevi/verdict)
"""

from hevi.motion.beat_sync import (
    BeatGrid,
    BeatSyncError,
    analyze_beat_grid,
    beat_time,
    measure_cut_error,
)
from hevi.motion.design_token import (
    DesignTokenError,
    DesignTokens,
    normalize_design_tokens,
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
from hevi.motion.sound_design import (
    SOUND_VOCABULARIES,
    SfxPin,
    SoundDesign,
    pick_sound_vocabulary,
    validate_sound_design,
)

__all__ = [
    "CARD_CATEGORIES",
    "MOTION_PRESETS",
    "SOUND_VOCABULARIES",
    "BeatGrid",
    "BeatSyncError",
    "DesignTokenError",
    "DesignTokens",
    "MotionPreset",
    "PageAsset",
    "PageCaptureError",
    "SfxPin",
    "ShotRecipeCard",
    "SoundDesign",
    "analyze_beat_grid",
    "beat_time",
    "build_seed_library",
    "capture_page_assets",
    "find_card",
    "measure_cut_error",
    "normalize_design_tokens",
    "pick_sound_vocabulary",
    "resolve_motion_preset",
    "validate_card",
    "validate_sound_design",
]
