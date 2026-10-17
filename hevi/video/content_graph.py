"""内容图 (ContentGraph) IR — 对标 nexu-io/html-video 的 storyboard IR。

脚本 → 内容图 → 分镜 → HTML 渲染。
内容图是中间表示层,将文本/脚本拆解为结构化的视频分镜。

参考: https://github.com/nexu-io/html-video
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

__all__ = [
    "ContentNodeType",
    "ContentNode",
    "ContentGraph",
    "StoryboardFrame",
    "Storyboard",
    "parse_script_to_graph",
    "graph_to_storyboard",
]


class ContentNodeType(str, Enum):
    text = "text"
    image = "image"
    video = "video"
    audio = "audio"
    title = "title"
    subtitle = "subtitle"
    data_point = "data_point"
    transition = "transition"


class ContentNode(BaseModel):
    id: str = ""
    type: ContentNodeType = ContentNodeType.text
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    style: dict[str, Any] = Field(default_factory=dict)
    duration_hint: float = 3.0  # seconds


class ContentGraph(BaseModel):
    nodes: list[ContentNode] = Field(default_factory=list)
    global_style: dict[str, Any] = Field(default_factory=lambda: {
        "font_family": "Inter, sans-serif",
        "background": "#0a0a0a",
        "text_color": "#ffffff",
    })
    soundtrack_config: dict[str, Any] = Field(default_factory=dict)
    aspect_ratio: str = "16:9"
    target_duration: float = 0.0


class StoryboardFrame(BaseModel):
    frame_index: int = 0
    duration: float = 3.0
    html_template: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    transition_in: str = "fade"  # fade, slide, zoom, none
    transition_out: str = "fade"


class Storyboard(BaseModel):
    frames: list[StoryboardFrame] = Field(default_factory=list)
    total_duration: float = 0.0
    resolution: tuple[int, int] = (1920, 1080)
    fps: int = 30


# ---------------------------------------------------------------------------
# Script → Graph → Storyboard
# ---------------------------------------------------------------------------

# Template mapping by node type
_NODE_TEMPLATES: dict[ContentNodeType, str] = {
    ContentNodeType.title: "explainer-intro",
    ContentNodeType.subtitle: "chapter-divider",
    ContentNodeType.text: "bullet-points",
    ContentNodeType.data_point: "stat-highlight",
    ContentNodeType.image: "product-showcase",
    ContentNodeType.video: "split-screen",
    ContentNodeType.audio: "kinetic-typography",
    ContentNodeType.transition: "chapter-divider",
}


def parse_script_to_graph(
    script: str,
    style: str = "default",
    aspect_ratio: str = "16:9",
) -> ContentGraph:
    """将文本脚本解析为内容图。

    简单规则解析(生产环境可用 LLM):
      - # 开头 → title
      - ## 开头 → subtitle/chapter
      - - 开头 → bullet text
      - [数据] → data_point
      - 空行 → transition
      - 其他 → text
    """
    nodes: list[ContentNode] = []
    node_id = 0

    for line in script.strip().split("\n"):
        line = line.strip()
        if not line:
            if nodes and nodes[-1].type != ContentNodeType.transition:
                node_id += 1
                nodes.append(ContentNode(id=str(node_id), type=ContentNodeType.transition, duration_hint=0.5))
            continue

        node_id += 1
        if line.startswith("## "):
            nodes.append(ContentNode(id=str(node_id), type=ContentNodeType.subtitle, content=line[3:], duration_hint=2.0))
        elif line.startswith("# "):
            nodes.append(ContentNode(id=str(node_id), type=ContentNodeType.title, content=line[2:], duration_hint=3.0))
        elif line.startswith("- "):
            nodes.append(ContentNode(id=str(node_id), type=ContentNodeType.text, content=line[2:], duration_hint=2.5))
        elif line.startswith("[") and line.endswith("]"):
            nodes.append(ContentNode(id=str(node_id), type=ContentNodeType.data_point, content=line[1:-1], duration_hint=3.0))
        else:
            nodes.append(ContentNode(id=str(node_id), type=ContentNodeType.text, content=line, duration_hint=3.0))

    total = sum(n.duration_hint for n in nodes)

    _STYLES = {
        "dark": {"background": "#0a0a0a", "text_color": "#ffffff"},
        "light": {"background": "#f5f5f5", "text_color": "#1a1a1a"},
        "brand": {"background": "#1a1a2e", "text_color": "#e0e0ff"},
    }

    return ContentGraph(
        nodes=nodes,
        global_style={**ContentGraph().global_style, **_STYLES.get(style, {})},
        aspect_ratio=aspect_ratio,
        target_duration=total,
    )


def graph_to_storyboard(
    graph: ContentGraph,
    template_pack: str = "default",
) -> Storyboard:
    """将内容图转换为分镜序列。

    每个 ContentNode 映射到一个 StoryboardFrame,
    根据节点类型选择 HTML 模板。
    """
    from hevi.video.html_templates import get_html_template, list_html_templates

    w, h = (1080, 1920) if graph.aspect_ratio == "9:16" else (1920, 1080)
    frames: list[StoryboardFrame] = []

    for idx, node in enumerate(graph.nodes):
        template_id = _NODE_TEMPLATES.get(node.type, "explainer-intro")
        # Find template
        tmpl = None
        try:
            tmpl = get_html_template(template_id)
        except ValueError:
            pass

        html = tmpl.html_source if tmpl else f"<div>{node.content}</div>"

        frame = StoryboardFrame(
            frame_index=idx,
            duration=node.duration_hint,
            html_template=html,
            data={"content": node.content, **node.metadata, **node.style,
                   "background": graph.global_style.get("background", "#0a0a0a"),
                   "text_color": graph.global_style.get("text_color", "#fff")},
            transition_in="fade" if idx > 0 else "none",
            transition_out="fade" if idx < len(graph.nodes) - 1 else "none",
        )
        frames.append(frame)

    total = sum(f.duration for f in frames)
    return Storyboard(frames=frames, total_duration=total, resolution=(w, h), fps=30)
