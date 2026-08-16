"""hevi freevideo —— 零成本程序化动画通道(html-video 渲染路线 × hevi 分镜)。

核心命题: 不调云视频生成、不调 TTS、不下载素材,只消耗 CPU 时间。
  内容/数据 → 确定性分镜 → 每镜一个自包含动画 HTML(CSS @keyframes + SVG)
  → Playwright 无头录屏 → ffmpeg 拼接 → 真动画 MP4。

渲染路线复刻 html-video(nexu-io/html-video)的 Hyperframes 引擎工程细节:
字体冻结、动画时长探测、lead-in 裁剪;录制/编码复用 hevi.pipeline_lite.oprim。

模块:
  - storyboard : 内容 → 分镜计划(FramePlan 列表)
  - templates  : 动画模板库(kind → 完整自包含 HTML)
  - render     : 逐帧录屏 + 精确时长 + concat
  - workflow   : 3O 编排入口 free_video_workflow
"""

from hevi.assembly.freevideo.storyboard import (
    FramePlan,
    plan_from_json,
    plan_from_text,
)
from hevi.assembly.freevideo.templates import (
    FRAME_KINDS,
    render_frame_html,
)
from hevi.assembly.freevideo.workflow import (
    FreeVideoConfig,
    FreeVideoInput,
    free_video_workflow,
)

__all__ = [
    "FRAME_KINDS",
    "FramePlan",
    "FreeVideoConfig",
    "FreeVideoInput",
    "free_video_workflow",
    "plan_from_json",
    "plan_from_text",
    "render_frame_html",
]
