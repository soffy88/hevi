"""LongCat-Video 能力适配层 — 核心机制集成到 Hevi 视频生成管线。

模块:
  1. video_continuation  — 镜头链式续接(末帧条件传递)
  2. coarse_to_fine      — 渐进生成(草稿验证 + 精修渲染)
  3. cfg_zero            — CFG-Zero 自适应引导优化
  4. avatar_driver       — 音频驱动数字人(半身像讲解)
  5. narrator_prompts    — 讲解数字人 prompt 工程
  6. narration_avatar    — 讲解段集成适配(替换静帧为数字人)

参考: https://github.com/meituan-longcat/LongCat-Video
"""

from hevi.video.longcat.avatar_driver import (
    AudioPreprocessConfig,
    AvatarDriverResult,
    AvatarEncoder,
    AvatarFraming,
    AvatarGenConfig,
    build_avatar_gen_config,
    build_avatar_prompt,
    compute_audio_duration_frames,
    generate_avatar_video,
    preprocess_audio_for_avatar,
)
from hevi.video.longcat.cfg_zero import (
    GuidanceConfig,
    GuidanceStats,
    GuidanceTracker,
    apply_cfg_zero,
    cfg_zero_noise_combine,
    cfg_zero_scale,
    recommend_guidance_scale,
)
from hevi.video.longcat.coarse_to_fine import (
    CoarseToFineConfig,
    CoarseToFineResult,
    DraftStrategy,
    build_coarse_to_fine_config,
    compute_draft_steps,
    generate_coarse_to_fine,
    select_draft_resolution,
)
from hevi.video.longcat.narration_avatar import (
    NarrationAvatarConfig,
    NarrationAvatarResult,
    build_narration_avatar_pipeline_config,
    generate_narration_avatar,
)
from hevi.video.longcat.narrator_prompts import (
    NARRATOR_PERSONAS,
    NarratorPersona,
    NarratorPromptConfig,
    build_narrator_negative,
    build_narrator_prompt,
    infer_gesture_from_text,
)
from hevi.video.longcat.video_continuation import (
    ContinuationConfig,
    ContinuationMode,
    ShotContinuation,
    apply_continuation_to_shots,
    build_continuation_config,
    compute_cond_frames_count,
    extract_video_last_frames,
)

__all__ = [
    # video_continuation
    "ContinuationMode",
    "ContinuationConfig",
    "ShotContinuation",
    "build_continuation_config",
    "apply_continuation_to_shots",
    "extract_video_last_frames",
    "compute_cond_frames_count",
    # coarse_to_fine
    "DraftStrategy",
    "CoarseToFineConfig",
    "CoarseToFineResult",
    "build_coarse_to_fine_config",
    "generate_coarse_to_fine",
    "compute_draft_steps",
    "select_draft_resolution",
    # cfg_zero
    "cfg_zero_scale",
    "apply_cfg_zero",
    "cfg_zero_noise_combine",
    "GuidanceTracker",
    "GuidanceStats",
    "GuidanceConfig",
    "recommend_guidance_scale",
    # avatar_driver
    "AvatarEncoder",
    "AvatarFraming",
    "AvatarGenConfig",
    "AudioPreprocessConfig",
    "AvatarDriverResult",
    "build_avatar_gen_config",
    "build_avatar_prompt",
    "compute_audio_duration_frames",
    "preprocess_audio_for_avatar",
    "generate_avatar_video",
    # narrator_prompts
    "NarratorPersona",
    "NarratorPromptConfig",
    "NARRATOR_PERSONAS",
    "build_narrator_prompt",
    "build_narrator_negative",
    "infer_gesture_from_text",
    # narration_avatar
    "NarrationAvatarConfig",
    "NarrationAvatarResult",
    "build_narration_avatar_pipeline_config",
    "generate_narration_avatar",
]
