"""hevi.pipeline_lite —— Lite 管道(HTML + Playwright + FFmpeg)的 3O 包。

严格 3O 目录结构(原子能力 / 业务编排 / 路由接入):
    oprim/   原子能力层(绝对无状态):HTML 合成、无头录屏、FFmpeg 混流
    omodul/  业务编排层:唯一有权调用 oprim 的地方
    oapp/    路由接入层:HTTP 入口
    schemas.py  数据契约(全层共享)
"""

from __future__ import annotations

from hevi.pipeline_lite.schemas import LiteAssembleResult, LiteCue, LiteTaskContext

__all__ = ["LiteAssembleResult", "LiteCue", "LiteTaskContext"]
