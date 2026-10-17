"""hevi 工具集 — ViMax 对标基础设施。

提供：
  - rate_limiter: 通用速率限制器（令牌桶 + per-service 限流）
  - robust_json: 健壮 JSON 解析器（容忍 LLM 输出格式错误）
  - image_guard: 图像方向守卫（横屏验证）
  - provider_presets: Provider 预置配置（自动填充 base_url/context_window）
"""

from hevi.utils.image_guard import (
    ImageDimensions,
    ImageOrientationError,
    ensure_landscape,
    ensure_not_portrait,
    get_image_dimensions,
    guard_image,
    landscape_guard_requested,
)
from hevi.utils.provider_presets import (
    ProviderPreset,
    get_preset,
    list_presets,
    resolve_chat_model_config,
    resolve_config,
    resolve_image_generator_config,
    resolve_video_generator_config,
)
from hevi.utils.rate_limiter import (
    RateLimitConfig,
    RateLimiter,
    RateLimiterRegistry,
    create_limiter,
)
from hevi.utils.robust_json import (
    extract_json_from_markdown,
    robust_json_loads,
    safe_json_loads,
)

__all__ = [
    "ImageDimensions",
    "ImageOrientationError",
    "ProviderPreset",
    "RateLimitConfig",
    "RateLimiter",
    "RateLimiterRegistry",
    "create_limiter",
    "ensure_landscape",
    "ensure_not_portrait",
    "extract_json_from_markdown",
    "get_image_dimensions",
    "get_preset",
    "guard_image",
    "landscape_guard_requested",
    "list_presets",
    "resolve_chat_model_config",
    "resolve_config",
    "resolve_image_generator_config",
    "resolve_video_generator_config",
    "robust_json_loads",
    "safe_json_loads",
]
