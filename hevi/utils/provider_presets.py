"""Provider Presets — 预置 provider 配置（对标 ViMax provider_presets.py）。

为常见 provider 提供预置配置，减少用户配置负担：
  - base_url 自动填充
  - context_window 自动填充
  - 默认参数（temperature/max_tokens 等）

支持的 provider：
  - LLM: openai / anthropic / openrouter / minimax / dashscope
  - Image: openai_dalle / stability / replicate
  - Video: veo / minimax / kling / pika
"""

from dataclasses import dataclass, field
from typing import Any, Literal


# ── 预置配置数据 ──────────────────────────────────────────────────────


@dataclass
class ProviderPreset:
    """Provider 预置配置。"""

    name: str
    category: Literal["llm", "image", "video"]
    base_url: str = ""
    context_window: int = 0
    default_params: dict[str, Any] = field(default_factory=dict)
    api_key_env: str = ""  # 环境变量名
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "base_url": self.base_url,
            "context_window": self.context_window,
            "default_params": self.default_params,
            "api_key_env": self.api_key_env,
            "notes": self.notes,
        }


# ── LLM Provider 预置 ─────────────────────────────────────────────────


LLM_PRESETS: dict[str, ProviderPreset] = {
    "openai": ProviderPreset(
        name="openai",
        category="llm",
        base_url="https://api.openai.com/v1",
        context_window=128_000,
        default_params={
            "temperature": 0.7,
            "max_tokens": 4096,
        },
        api_key_env="OPENAI_API_KEY",
        notes="GPT-4o / GPT-4 / GPT-3.5",
    ),
    "anthropic": ProviderPreset(
        name="anthropic",
        category="llm",
        base_url="https://api.anthropic.com/v1",
        context_window=200_000,
        default_params={
            "temperature": 0.7,
            "max_tokens": 8192,
        },
        api_key_env="ANTHROPIC_API_KEY",
        notes="Claude 3.5 Sonnet / Claude 3 Opus",
    ),
    "openrouter": ProviderPreset(
        name="openrouter",
        category="llm",
        base_url="https://openrouter.ai/api/v1",
        context_window=128_000,  # 取决于具体模型
        default_params={
            "temperature": 0.7,
            "max_tokens": 4096,
        },
        api_key_env="OPENROUTER_API_KEY",
        notes="统一访问多个 LLM provider",
    ),
    "minimax": ProviderPreset(
        name="minimax",
        category="llm",
        base_url="https://api.minimax.chat/v1",
        context_window=32_000,
        default_params={
            "temperature": 0.7,
            "max_tokens": 4096,
        },
        api_key_env="MINIMAX_API_KEY",
        notes="MiniMax 文本模型",
    ),
    "dashscope": ProviderPreset(
        name="dashscope",
        category="llm",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        context_window=32_000,
        default_params={
            "temperature": 0.7,
            "max_tokens": 4096,
        },
        api_key_env="DASHSCOPE_API_KEY",
        notes="阿里云通义千问",
    ),
}


# ── Image Provider 预置 ───────────────────────────────────────────────


IMAGE_PRESETS: dict[str, ProviderPreset] = {
    "openai_dalle": ProviderPreset(
        name="openai_dalle",
        category="image",
        base_url="https://api.openai.com/v1",
        context_window=0,
        default_params={
            "size": "1024x1024",
            "quality": "standard",
            "n": 1,
        },
        api_key_env="OPENAI_API_KEY",
        notes="DALL-E 3 / DALL-E 2",
    ),
    "stability": ProviderPreset(
        name="stability",
        category="image",
        base_url="https://api.stability.ai/v1",
        context_window=0,
        default_params={
            "width": 1024,
            "height": 1024,
            "steps": 30,
            "cfg_scale": 7.0,
        },
        api_key_env="STABILITY_API_KEY",
        notes="Stable Diffusion XL / SD3",
    ),
    "replicate": ProviderPreset(
        name="replicate",
        category="image",
        base_url="https://api.replicate.com/v1",
        context_window=0,
        default_params={
            "num_outputs": 1,
            "guidance_scale": 7.5,
        },
        api_key_env="REPLICATE_API_TOKEN",
        notes="Flux / SDXL / 其他开源模型",
    ),
}


# ── Video Provider 预置 ───────────────────────────────────────────────


VIDEO_PRESETS: dict[str, ProviderPreset] = {
    "veo": ProviderPreset(
        name="veo",
        category="video",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        context_window=0,
        default_params={
            "duration_s": 8,
            "aspect_ratio": "16:9",
            "resolution": "720p",
        },
        api_key_env="GOOGLE_API_KEY",
        notes="Google Veo 2",
    ),
    "minimax_video": ProviderPreset(
        name="minimax_video",
        category="video",
        base_url="https://api.minimax.chat/v1",
        context_window=0,
        default_params={
            "duration_s": 5,
            "resolution": "720p",
            "aspect_ratio": "16:9",
        },
        api_key_env="MINIMAX_API_KEY",
        notes="MiniMax video-01",
    ),
    "kling": ProviderPreset(
        name="kling",
        category="video",
        base_url="https://api.kling.ai/v1",
        context_window=0,
        default_params={
            "duration_s": 5,
            "mode": "std",
            "aspect_ratio": "16:9",
        },
        api_key_env="KLING_API_KEY",
        notes="快手 Kling",
    ),
    "pika": ProviderPreset(
        name="pika",
        category="video",
        base_url="https://api.pika.art/v1",
        context_window=0,
        default_params={
            "duration_s": 3,
            "style": "natural",
        },
        api_key_env="PIKA_API_KEY",
        notes="Pika Labs",
    ),
}


# ── 查询函数 ──────────────────────────────────────────────────────────


def get_preset(
    name: str,
    category: Literal["llm", "image", "video"] | None = None,
) -> ProviderPreset | None:
    """获取预置配置。

    Args:
        name: provider 名称（如 "openai"）
        category: 可选类别过滤

    Returns:
        ProviderPreset 或 None（未找到）
    """
    if category == "llm":
        return LLM_PRESETS.get(name)
    elif category == "image":
        return IMAGE_PRESETS.get(name)
    elif category == "video":
        return VIDEO_PRESETS.get(name)
    else:
        # 搜索所有类别
        for presets in [LLM_PRESETS, IMAGE_PRESETS, VIDEO_PRESETS]:
            if name in presets:
                return presets[name]
        return None


def list_presets(
    category: Literal["llm", "image", "video"] | None = None,
) -> list[str]:
    """列出所有预置 provider 名称。

    Args:
        category: 可选类别过滤

    Returns:
        provider 名称列表
    """
    if category == "llm":
        return list(LLM_PRESETS.keys())
    elif category == "image":
        return list(IMAGE_PRESETS.keys())
    elif category == "video":
        return list(VIDEO_PRESETS.keys())
    else:
        all_names = []
        for presets in [LLM_PRESETS, IMAGE_PRESETS, VIDEO_PRESETS]:
            all_names.extend(presets.keys())
        return all_names


def get_all_presets() -> dict[str, ProviderPreset]:
    """获取所有预置配置。"""
    all_presets = {}
    for presets in [LLM_PRESETS, IMAGE_PRESETS, VIDEO_PRESETS]:
        all_presets.update(presets)
    return all_presets


# ── 配置合并 ──────────────────────────────────────────────────────────


def resolve_config(
    provider_name: str,
    user_config: dict[str, Any],
    category: Literal["llm", "image", "video"] | None = None,
) -> dict[str, Any]:
    """合并用户配置与预置配置。

    用户配置优先，预置配置作为默认值。

    Args:
        provider_name: provider 名称
        user_config: 用户提供的配置
        category: 可选类别

    Returns:
        合并后的配置
    """
    preset = get_preset(provider_name, category)
    if not preset:
        return user_config

    merged = {}

    # 预置默认值
    if preset.base_url:
        merged["base_url"] = preset.base_url
    if preset.context_window > 0:
        merged["context_window"] = preset.context_window
    if preset.api_key_env:
        merged["api_key_env"] = preset.api_key_env
    merged.update(preset.default_params)

    # 用户配置覆盖
    merged.update(user_config)

    return merged


def resolve_chat_model_config(
    model: str,
    provider: str,
    api_key: str = "",
    **kwargs,
) -> dict[str, Any]:
    """解析聊天模型配置（便捷函数）。

    Args:
        model: 模型名称（如 "gpt-4o"）
        provider: provider 名称（如 "openai"）
        api_key: API key（可选，可从环境变量读取）
        **kwargs: 其他参数

    Returns:
        完整配置字典
    """
    user_config = {
        "model": model,
        "provider": provider,
    }
    if api_key:
        user_config["api_key"] = api_key
    user_config.update(kwargs)

    return resolve_config(provider, user_config, category="llm")


def resolve_image_generator_config(
    provider: str,
    api_key: str = "",
    **kwargs,
) -> dict[str, Any]:
    """解析图像生成器配置（便捷函数）。"""
    user_config = {"provider": provider}
    if api_key:
        user_config["api_key"] = api_key
    user_config.update(kwargs)

    return resolve_config(provider, user_config, category="image")


def resolve_video_generator_config(
    provider: str,
    api_key: str = "",
    **kwargs,
) -> dict[str, Any]:
    """解析视频生成器配置（便捷函数）。"""
    user_config = {"provider": provider}
    if api_key:
        user_config["api_key"] = api_key
    user_config.update(kwargs)

    return resolve_config(provider, user_config, category="video")
