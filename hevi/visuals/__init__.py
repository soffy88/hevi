"""视觉来源域 —— 决定镜头用「搜索素材」还是「Archify 生成」。

子模块:
  - :mod:`hevi.visuals.router`          确定性选择器(search vs archify)
  - :mod:`hevi.visuals.archify_source`  archify CLI 包装 + 竖版截图 + 溢出门禁
  - :mod:`hevi.visuals.search_source`   本地素材/远程检索适配器(降级)
"""

from hevi.visuals.router import VisualRoute, route_visual
from hevi.visuals.archify_source import (
    ArchifyRenderError,
    build_ir,
    capture_png,
    detect_overflow,
    render_archify,
    render_with_overflow_gate,
)

__all__ = [
    "ArchifyRenderError",
    "VisualRoute",
    "build_ir",
    "capture_png",
    "detect_overflow",
    "render_archify",
    "render_with_overflow_gate",
    "route_visual",
]
