"""L4 Director —— 分镜 → 选角 → 下发。**输出物 = canvas 节点图**。

设计 §3 L4:Director 的产出是一张 canvas 节点图(不是直接跑管线)。全自动模式 = 生成图后
直接交 executor 执行;人在环 = 用户在图上改(换角色 / 改某镜头 prompt / 删节点)再执行。

§7-7 已让 canvas 的 video/kernel 节点走真实生成,所以 Director 产的图是**可执行**的:
  topic(text 节点) → shot_0..N(video 节点,各带分镜 prompt)。

分镜 prompts 由上层(storyboard 规划 / 用户)给;Director 只负责把它们组装成图 + 灌入
Producer 定的 provider/角色约束。
"""

from __future__ import annotations

from typing import Any

from oprim._hevi_types import CanvasEdge, CanvasNode

from hevi.director.producer import ProducerPlan


def build_canvas_graph(
    *,
    plan: ProducerPlan,
    shot_prompts: list[str],
    character_reference: str | None = None,
    graph_name: str | None = None,
    duration_s: float = 5.0,
) -> dict[str, Any]:
    """ProducerPlan + 分镜 prompts → 可执行 canvas 图(dict:name/nodes/edges)。

    - topic 一个 text 节点;每条分镜一个 video/kernel 节点,边 text→video。
    - 角色锁定(character_reference)→ 每个 video 节点走 i2v + 参考图(跨镜身份一致)。
    - provider 用 Producer 路由/指定的结果。节点可直接交 canvas executor 执行(§7-7)。
    """
    if not shot_prompts:
        raise ValueError("shot_prompts must not be empty")

    name = graph_name or f"director_{plan.topic[:24]}"
    mode = "i2v" if character_reference else "t2v"
    nodes: list[CanvasNode] = [
        CanvasNode(node_id="topic", node_type="text", label="选题", config={"content": plan.topic})
    ]
    edges: list[CanvasEdge] = []

    for i, prompt in enumerate(shot_prompts):
        vid = f"shot_{i:04d}"
        cfg: dict[str, Any] = {
            "sub_type": "kernel",
            "prompt": prompt,
            "provider": plan.video_provider,
            "mode": mode,
            "duration_s": duration_s,
            "output_path": f"output/canvas/{name}/{vid}.mp4",
        }
        if character_reference:
            cfg["reference_image"] = character_reference
        nodes.append(CanvasNode(node_id=vid, node_type="video", label=f"镜头 {i}", config=cfg))
        edges.append(
            CanvasEdge(
                edge_id=f"e_{i:04d}",
                from_node_id="topic",
                to_node_id=vid,
                from_type="text",
                to_type="video",
            )
        )

    return {
        "name": name,
        "nodes": [n.model_dump() for n in nodes],
        "edges": [e.model_dump() for e in edges],
    }
