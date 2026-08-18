"""hyperframes —— HTML/GSAP 构图的第二渲染运行时。"""

from hevi.providers.hyperframes.compiler import (
    HyperClip,
    HyperComposition,
    compile_composition,
    render_html,
)
from hevi.providers.hyperframes.provider import (
    HYPERFRAMES_CAPABILITY,
    HyperframesRenderError,
    detect_hyperframes_bin,
    hyperframes_generate,
    register_hyperframes,
)

__all__ = [
    "HYPERFRAMES_CAPABILITY",
    "HyperClip",
    "HyperComposition",
    "HyperframesRenderError",
    "compile_composition",
    "detect_hyperframes_bin",
    "hyperframes_generate",
    "register_hyperframes",
    "render_html",
]
