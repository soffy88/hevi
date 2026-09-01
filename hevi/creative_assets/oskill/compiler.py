"""Natural-language-to-visual-brief compiler."""

from __future__ import annotations

from hevi.creative_assets.oprim.contracts import VisualAssetRequest

STYLE_CATALOG: dict[str, dict[str, str]] = {
    "cinematic": {"look": "cinematic product photography", "light": "controlled key light"},
    "editorial": {"look": "clean editorial composition", "light": "soft studio light"},
    "ink": {"look": "expressive ink wash illustration", "light": "paper-texture diffuse light"},
    "minimal": {"look": "minimal high-contrast graphic composition", "light": "even soft light"},
    "documentary": {"look": "observational documentary frame", "light": "natural available light"},
}

_PLATFORM_RATIOS = {
    "douyin": "9:16",
    "kuaishou": "9:16",
    "xiaohongshu": "3:4",
    "bilibili": "16:9",
    "youtube": "16:9",
    "generic": "16:9",
}


def default_aspect_ratio(platform: str) -> str:
    return _PLATFORM_RATIOS.get(platform, "16:9")


def compile_visual_prompt(request: VisualAssetRequest) -> str:
    """Compile a short provider-neutral prompt; no upstream prompt text is copied."""

    style = STYLE_CATALOG.get(request.style, STYLE_CATALOG["cinematic"])
    ratio = request.aspect_ratio or default_aspect_ratio(request.platform)
    parts = [
        request.subject.strip(),
        style["look"],
        style["light"],
        f"{ratio} composition",
        "clear subject separation, production-ready framing",
    ]
    if request.reference_path:
        parts.append("preserve the identity and key visual traits from the local reference")
    if request.negative_prompt.strip():
        parts.append(f"avoid: {request.negative_prompt.strip()}")
    return ", ".join(parts)


__all__ = ["STYLE_CATALOG", "compile_visual_prompt", "default_aspect_ratio"]
