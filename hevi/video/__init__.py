from hevi.video.duration_mapper import DURATION_ARCHETYPES, get_duration_config
from hevi.video.kernel_service import generate_clip
from hevi.video.presets import (
    DEFAULT_PRESET,
    EXECUTION_PRESETS,
    ExecutionPreset,
    get_execution_preset,
    resolve_preset,
)
from hevi.video.provider_config import VideoProvider
from hevi.video.quality_profile import (
    DEFAULT_QUALITY,
    QUALITY_PROFILES,
    QualityProfile,
    get_quality_cost_multiplier,
    get_quality_profile,
)

from hevi.video.media_profiles import (
    MediaProfile,
    ffmpeg_for_profile,
    ffmpeg_output_args,
    get_media_profile,
    list_profiles,
)

# --- Wan-Dancer music-to-dance provider ---
from hevi.video.provider_wan_dancer import (
    DanceGenre,
    WanDancerRequest,
    WanDancerResult,
    KeyframePlan,
    generate_dance_video,
    plan_keyframes as plan_dance_keyframes,
    supported_genres as supported_dance_genres,
)

# --- Motion templates ---
from hevi.video.motion_templates import (
    MotionCatalog,
    MotionPreset,
    MotionRenderRequest,
    MotionRenderResult,
    MotionTemplate,
    MotionTemplateId,
    MotionVariable,
    get_catalog as get_motion_catalog,
    get_template as get_motion_template,
    list_presets as list_motion_presets,
    render_motion,
    render_with_preset,
)

# --- HTML video pipeline ---
from hevi.video.html_video_pipeline import (
    HtmlVideoRequest,
    HtmlVideoResult,
    render_html_video as render_html_template_video,
    render_storyboard,
    build_storyboard,
)
from hevi.video.html_templates import (
    HtmlVideoTemplate,
    list_html_templates,
    get_html_template,
)
from hevi.video.content_graph import (
    ContentGraph,
    Storyboard,
    parse_script_to_graph,
    graph_to_storyboard,
)

__all__ = [
    "DEFAULT_PRESET",
    "DEFAULT_QUALITY",
    "DURATION_ARCHETYPES",
    "EXECUTION_PRESETS",
    "MediaProfile",
    "QUALITY_PROFILES",
    "ExecutionPreset",
    "QualityProfile",
    "VideoProvider",
    "ffmpeg_for_profile",
    "ffmpeg_output_args",
    "generate_clip",
    "get_duration_config",
    "get_execution_preset",
    "get_media_profile",
    "get_quality_cost_multiplier",
    "get_quality_profile",
    "list_profiles",
    "resolve_preset",
    # Wan-Dancer
    "DanceGenre",
    "WanDancerRequest",
    "WanDancerResult",
    "KeyframePlan",
    "generate_dance_video",
    "plan_dance_keyframes",
    "supported_dance_genres",
    # Motion templates
    "MotionCatalog",
    "MotionPreset",
    "MotionRenderRequest",
    "MotionRenderResult",
    "MotionTemplate",
    "MotionTemplateId",
    "MotionVariable",
    "get_motion_catalog",
    "get_motion_template",
    "list_motion_presets",
    "render_motion",
    "render_with_preset",
    # HTML video pipeline
    "HtmlVideoRequest",
    "HtmlVideoResult",
    "HtmlVideoTemplate",
    "render_html_template_video",
    "render_storyboard",
    "build_storyboard",
    "list_html_templates",
    "get_html_template",
    "ContentGraph",
    "Storyboard",
    "parse_script_to_graph",
    "graph_to_storyboard",
]
