"""OpenShorts 三大能力内部化：3O §3 Task 3.x 出品。

    schemas.py          # Job/ClipSpec/AIScript/YouTubeStudio 契约
    oprim/              # 原子：clip_reframing / detect_scenes_gemini / transcript / script_gen
    oskill/             # 技能：generate_clips / generate_ai_short / generate_youtube_package
    omodul/             # 规划：plan_clip_generator / plan_ai_short / plan_youtube_studio

对齐 OpenShorts 核心能力：
1. Clip Generator —— 长视频 → 3-15 竖屏 Short (场景检测 + 病毒时刻 + 智能 9:16 重构 + 词级字幕)
2. AI Shorts —— 从零生成 UGC (网站抓取 → 脚本 → 演员 → 视频 → 分发)
3. YouTube Studio —— AI 标题/缩略图/描述/章节
"""

from __future__ import annotations

# ── Omodul ──
from hevi.openshorts.omodul import (
    AVAILABLE_COST_MODES,
    AVAILABLE_LAYOUTS,
    SOCIAL_PLATFORMS,
    execute_ai_short,
    execute_clip_generator,
    execute_youtube_studio,
    plan_ai_short,
    plan_clip_generator,
    plan_youtube_studio,
)

# ── Oprim ──
from hevi.openshorts.oprim import (
    build_transcript_windows,
    clip_reframing_params,
    detect_scenes_gemini,
    extract_transcript_with_words,
    generate_script_from_description,
    generate_youtube_description,
    generate_youtube_thumbnail,
    generate_youtube_titles,
    make_clip_spec,
    plan_ai_short_actor,
    snap_clip_to_words_auto,
)

# ── Oskill ──
from hevi.openshorts.oskill import (
    create_publish_tickets,
    generate_ai_short,
    generate_clips,
    generate_youtube_package,
)

# ── Schemas ──
from hevi.openshorts.schemas import (
    AIActor,
    AICostMode,
    AICostPlan,
    AIScript,
    AIShortJob,
    ClipGeneratorJob,
    ClipSpec,
    PublishTicket,
    ReframingMode,
    SceneDetection,
    ViralMoment,
    WordTimestamp,
    YouTubeChapter,
    YouTubeDescription,
    YouTubeStudioJob,
    YouTubeThumbnail,
    YouTubeTitle,
    make_ai_short_job,
    make_clip_generator_job,
    make_youtube_studio_job,
)

__all__ = [
    "AVAILABLE_COST_MODES",
    "AVAILABLE_LAYOUTS",
    "SOCIAL_PLATFORMS",
    "AIActor",
    "AICostMode",
    "AICostPlan",
    "AIScript",
    "AIShortJob",
    "ClipGeneratorJob",
    "ClipSpec",
    "PublishTicket",
    # Schemas
    "ReframingMode",
    "SceneDetection",
    "ViralMoment",
    "WordTimestamp",
    "YouTubeChapter",
    "YouTubeDescription",
    "YouTubeStudioJob",
    "YouTubeThumbnail",
    "YouTubeTitle",
    "build_transcript_windows",
    # Oprim
    "clip_reframing_params",
    "create_publish_tickets",
    "detect_scenes_gemini",
    "execute_ai_short",
    "execute_clip_generator",
    "execute_youtube_studio",
    "extract_transcript_with_words",
    "generate_ai_short",
    # Oskill
    "generate_clips",
    "generate_script_from_description",
    "generate_youtube_description",
    "generate_youtube_package",
    "generate_youtube_thumbnail",
    "generate_youtube_titles",
    "make_ai_short_job",
    "make_clip_generator_job",
    "make_clip_spec",
    "make_youtube_studio_job",
    "plan_ai_short",
    "plan_ai_short_actor",
    # Omodul
    "plan_clip_generator",
    "plan_youtube_studio",
    "snap_clip_to_words_auto",
]