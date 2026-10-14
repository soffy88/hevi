"""hevi 风格/镜头语言预设 —— 供 inject_visual_style 用。

RFC-002 item 12: 从 3 个扩到 20 个,覆盖常见视频题材;每个含 style/lighting/
camera/color_grade + negative(负向词,供逐镜头下发,RFC-002 item 8)。
键为中文题材名(沿用既有约定)。
"""

__all__ = [
    "STYLE_PRESETS",
    "get_style_preset",
    "list_style_presets",
    "KEYFRAME_STYLE_PRESETS",
    "DEFAULT_KEYFRAME_STYLE",
    "get_keyframe_style",
    "list_keyframe_styles",
]

# 键匹配 inject_visual_style 的 kwargs: style / lighting / camera / color_grade;
# 额外 negative 键供 engineer_prompt_pair_from_preset 合并负向。
_COMMON_NEG = "blurry, distorted, low quality, deformed, watermark, text, jpeg artifacts"

STYLE_PRESETS: dict[str, dict[str, str | None]] = {
    "科普": {
        "style": "educational clear, informative",
        "lighting": "bright even",
        "camera": "smooth pan",
        "color_grade": "neutral balanced",
        "negative": _COMMON_NEG,
    },
    "严肃": {
        "style": "serious documentary",
        "lighting": "dramatic",
        "camera": "slow push in",
        "color_grade": "desaturated muted",
        "negative": _COMMON_NEG + ", cartoonish, oversaturated",
    },
    "搞笑": {
        "style": "playful vibrant, comedic",
        "lighting": "warm bright",
        "camera": "dynamic quick",
        "color_grade": "saturated punchy",
        "negative": _COMMON_NEG + ", gloomy, dark",
    },
    "电影感": {
        "style": "cinematic, filmic, anamorphic",
        "lighting": "dramatic chiaroscuro",
        "camera": "slow dolly, shallow depth of field",
        "color_grade": "teal and orange",
        "negative": _COMMON_NEG + ", flat lighting, amateur",
    },
    "赛博朋克": {
        "style": "cyberpunk, futuristic neon city",
        "lighting": "neon glow, high contrast",
        "camera": "tracking shot",
        "color_grade": "magenta and cyan neon",
        "negative": _COMMON_NEG + ", daylight, rural, pastel",
    },
    "国风水墨": {
        "style": "chinese ink painting, traditional, ethereal",
        "lighting": "soft diffused",
        "camera": "gentle drift",
        "color_grade": "ink wash, muted earth tones",
        "negative": _COMMON_NEG + ", western, neon, 3d render",
    },
    "治愈系": {
        "style": "healing, cozy, gentle slice of life",
        "lighting": "soft warm golden hour",
        "camera": "static or slow",
        "color_grade": "warm pastel",
        "negative": _COMMON_NEG + ", harsh, violent, dark",
    },
    "商务专业": {
        "style": "corporate professional, clean",
        "lighting": "bright studio softbox",
        "camera": "steady locked",
        "color_grade": "crisp cool neutral",
        "negative": _COMMON_NEG + ", messy, grungy, dim",
    },
    "美食": {
        "style": "appetizing food, close-up macro",
        "lighting": "soft warm key light",
        "camera": "slow rotate, overhead",
        "color_grade": "warm rich saturated",
        "negative": _COMMON_NEG + ", unappetizing, dull, grey",
    },
    "旅行Vlog": {
        "style": "travel vlog, scenic, energetic",
        "lighting": "natural daylight",
        "camera": "handheld, sweeping aerial",
        "color_grade": "vivid sunny",
        "negative": _COMMON_NEG + ", studio, indoor, static",
    },
    "产品广告": {
        "style": "product commercial, sleek premium",
        "lighting": "studio rim light, glossy",
        "camera": "slow orbit, macro detail",
        "color_grade": "clean high-key",
        "negative": _COMMON_NEG + ", cluttered, cheap, dull",
    },
    "新闻播报": {
        "style": "broadcast news, authoritative",
        "lighting": "even studio",
        "camera": "locked centered",
        "color_grade": "neutral broadcast-safe",
        "negative": _COMMON_NEG + ", artistic, blurry motion",
    },
    "悬疑": {
        "style": "suspense thriller, moody tension",
        "lighting": "low-key shadows",
        "camera": "slow creeping, dutch angle",
        "color_grade": "cold desaturated",
        "negative": _COMMON_NEG + ", bright cheerful, flat",
    },
    "史诗": {
        "style": "epic cinematic, grand scale",
        "lighting": "god rays, volumetric",
        "camera": "sweeping crane, wide establishing",
        "color_grade": "rich dramatic",
        "negative": _COMMON_NEG + ", small scale, mundane",
    },
    "复古胶片": {
        "style": "vintage retro, 1970s film",
        "lighting": "soft hazy",
        "camera": "subtle handheld",
        "color_grade": "faded film grain, warm sepia",
        "negative": _COMMON_NEG + ", modern, digital, sharp clinical",
    },
    "动漫": {
        "style": "anime, cel-shaded, expressive",
        "lighting": "stylized bright",
        "camera": "dynamic action",
        "color_grade": "vivid saturated",
        "negative": _COMMON_NEG + ", photorealistic, 3d, live action",
    },
    "极简": {
        "style": "minimalist, clean negative space",
        "lighting": "soft even",
        "camera": "static symmetrical",
        "color_grade": "monochrome muted",
        "negative": _COMMON_NEG + ", cluttered, busy, ornate",
    },
    "自然纪录片": {
        "style": "nature documentary, wildlife",
        "lighting": "natural golden hour",
        "camera": "long lens tracking, slow motion",
        "color_grade": "lush natural",
        "negative": _COMMON_NEG + ", urban, artificial, cartoon",
    },
    "时尚": {
        "style": "fashion editorial, high-end chic",
        "lighting": "dramatic fashion strobe",
        "camera": "smooth glide, slow motion",
        "color_grade": "high-contrast stylized",
        "negative": _COMMON_NEG + ", casual, plain, dull",
    },
    "运动": {
        "style": "sports action, energetic dynamic",
        "lighting": "bright punchy",
        "camera": "fast tracking, whip pan",
        "color_grade": "vivid high-contrast",
        "negative": _COMMON_NEG + ", static, slow, dull",
    },
}


def get_style_preset(name: str) -> dict[str, str | None]:
    """返回某风格预设(inject_visual_style kwargs + negative)。未知名报错。"""
    if name not in STYLE_PRESETS:
        raise ValueError(f"Unknown style preset: {name!r}. Valid: {list(STYLE_PRESETS)}")
    return STYLE_PRESETS[name]


def list_style_presets() -> list[str]:
    """列出所有可用风格预设名(供 API/前端展示)。"""
    return list(STYLE_PRESETS)


# ---------------------------------------------------------------------------
# Keyframe generation style presets (shared by dramakey / comicnarr / script2video)
#
# CPU 上跑写实真人没有优势（SD-Turbo 512px 写实人脸糊、且不像角色卡），因此默认
# 画风改为国风动漫插画 `anime_guofeng`，写实 `photoreal` 保留为可选且默认关闭。
# 每个预设提供：prompt_prefix(前置风格词) + style_tags(后置风格词) + negative
# (负向词，合并进最终 negative) + photoreal(是否写实真人)。
# ---------------------------------------------------------------------------
_STYLE_NEG_PHOTO = (
    "photo, photograph, photorealistic, realistic, hyperrealistic, 3d render, cgi, "
    "octane render, unreal engine, live-action, real human face, skin pores, dslr, "
    "film grain, depth of field bokeh"
)

KEYFRAME_STYLE_PRESETS: dict[str, dict[str, object]] = {
    "anime_guofeng": {
        "label": "国风动漫插画",
        "prompt_prefix": (
            "chinese anime illustration, guofeng donghua art style, 2d animation cel, "
            "stylized character design"
        ),
        "style_tags": (
            "flat color shading, bold clean line art, unified limited color palette, "
            "elegant ancient Chinese costume design, hand-drawn illustration background"
        ),
        "negative": _STYLE_NEG_PHOTO,
        "photoreal": False,
    },
    "ink": {
        "label": "国风水墨",
        "prompt_prefix": "traditional chinese ink wash painting, shuimo guofeng style",
        "style_tags": (
            "flowing ink brush strokes, xuan paper texture, monochrome with subtle washes, "
            "minimalist negative space, ethereal atmosphere"
        ),
        "negative": _STYLE_NEG_PHOTO + ", western oil painting, neon, saturated colors",
        "photoreal": False,
    },
    "flat_comic": {
        "label": "平涂漫画",
        "prompt_prefix": "flat comic book illustration, graphic novel panel art",
        "style_tags": (
            "flat cel shading, crisp ink outlines, limited halftone palette, "
            "bold graphic composition"
        ),
        "negative": _STYLE_NEG_PHOTO + ", painterly, soft gradients",
        "photoreal": False,
    },
    "photoreal": {
        "label": "写实真人（可选，默认关闭）",
        "prompt_prefix": "cinematic photorealistic live-action film still",
        "style_tags": (
            "photorealistic, realistic skin texture, natural lighting, "
            "shallow depth of field, 8k detailed"
        ),
        "negative": "cartoon, anime, illustration, painting, drawing, cgi, flat colors",
        "photoreal": True,
    },
}

DEFAULT_KEYFRAME_STYLE = "anime_guofeng"


def get_keyframe_style(name: str | None) -> dict[str, object]:
    """Return a keyframe style preset. Unknown/None -> default (anime_guofeng).

    Raises ValueError only for a non-empty unknown name so that callers can tell a
    typo apart from the default; None/"" select the default style.
    """
    if not name:
        return KEYFRAME_STYLE_PRESETS[DEFAULT_KEYFRAME_STYLE]
    if name not in KEYFRAME_STYLE_PRESETS:
        raise ValueError(
            f"Unknown keyframe style: {name!r}. Valid: {list(KEYFRAME_STYLE_PRESETS)}"
        )
    return KEYFRAME_STYLE_PRESETS[name]


def list_keyframe_styles() -> list[str]:
    """List available keyframe generation style names (for CLI/API/frontend)."""
    return list(KEYFRAME_STYLE_PRESETS)
