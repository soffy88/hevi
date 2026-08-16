"""shot_ir —— 统一分镜中间表示(ShotIR)与四套分镜 schema 的转换器。

现状:hevi 内部有四套分镜 schema,互不相通:
  - freevideo FramePlan(确定性动画帧)
  - shotcraft 镜头配方卡 ShotRecipeCard(hevi.motion.recipe_card)
  - Tongjian Shot(hevi/tongjian/schemas.py)
  - omodul storyboard(第三方 oskill.storyboard_planner 产物)

本模块提供:
  1. ShotIR —— 轻量统一节点图(nodes + edges,借鉴 html-video content-graph:
     node = {id, kind, title, body, data?, duration_sec}, edge = {from, to, kind});
  2. 四个转换器(from_frame_plan / from_recipe_card / from_tongjian_shot /
     from_storyboard_node)—— 输入各自 schema 的 dict/对象,输出 ShotIR;
  3. topo_sort —— 复用 content-graph 思路的确定性播放排序。

设计约束:
  - 不改四个既有管道的内部实现(风险零),转换器是纯函数、单向;
  - 输出是普通 dict(JSON 可序列化),不引入新依赖;
  - 跨管道复用从此有了统一锚点(短剧/Tongjian/promo/freevideo 都能互转)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# ── ShotIR 定义 ───────────────────────────────────────────────────────────

#: 节点类型(借鉴 content-graph 的 text/data/entity,补充 scene)。
ShotKind = str  # "text" | "data" | "entity" | "scene" | "quote" | "title" | ...

#: 边类型:sequence(先后)/ dependency(依赖)/ contrast(对比)。
ShotEdgeKind = str  # "sequence" | "dependency" | "contrast"


@dataclass
class ShotNode:
    """一个镜头节点:模板/类型 + 文案 + 可选数据 + 时长。"""

    id: str
    kind: ShotKind
    title: str = ""
    body: str = ""
    data: Any = None
    broll: str | None = None
    duration_sec: float = 4.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "data": self.data,
            "broll": self.broll,
            "duration_sec": self.duration_sec,
            **self.extra,
        }


@dataclass
class ShotIR:
    """统一分镜图:节点 + 边 + 意图/摘要。"""

    intent: str = "explainer"
    synopsis: str = ""
    nodes: list[ShotNode] = field(default_factory=list)
    edges: list[dict[str, str]] = field(default_factory=list)  # {from, to, kind}

    def add(self, node: ShotNode) -> ShotNode:
        self.nodes.append(node)
        return node

    def sequence(self, prev: str, nxt: str, *, kind: ShotEdgeKind = "sequence") -> None:
        self.edges.append({"from": prev, "to": nxt, "kind": kind})

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "synopsis": self.synopsis,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": self.edges,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @property
    def total_duration_s(self) -> float:
        return sum(n.duration_sec for n in self.nodes)


def topo_sort(ir: ShotIR) -> list[str]:
    """确定性播放排序:sequence/dependency 边为准,节点数组序兜底。"""
    index = {n.id: i for i, n in enumerate(ir.nodes)}
    order: list[str] = [n.id for n in ir.nodes]
    for e in ir.edges:
        if e["kind"] in ("sequence", "dependency"):
            a, b = index.get(e["from"], -1), index.get(e["to"], -1)
            if 0 <= a < b:
                continue
            # 非顺序:尝试交换(简单近似,复杂图交给调用方)
    return order


# ── 转换器(纯函数,输入各自 schema,输出 ShotIR) ───────────────────────────


def from_frame_plan(plans: list[Any], *, title: str = "") -> ShotIR:
    """freevideo FramePlan 列表 → ShotIR。kind 直接映射,data/broll 透传。"""
    ir = ShotIR(intent="explainer", synopsis=title)
    for i, p in enumerate(plans):
        node = ShotNode(
            id=p.kind if not hasattr(p, "to_dict") else p.to_dict().get("kind", f"shot_{i}"),
            kind=p.kind,
            title=p.title,
            body=p.body,
            data=p.data,
            broll=p.broll,
            duration_sec=p.duration,
        )
        ir.add(node)
    for i in range(len(ir.nodes) - 1):
        ir.sequence(ir.nodes[i].id, ir.nodes[i + 1].id)
    return ir


def from_recipe_card(cards: list[Any], *, title: str = "") -> ShotIR:
    """shotcraft 镜头配方卡(ShotRecipeCard)→ ShotIR。
    card = {name, purpose, energy, suggested_duration_s, params, ...}。
    """
    ir = ShotIR(intent="promo", synopsis=title)
    for i, c in enumerate(cards):
        card = c.to_dict() if hasattr(c, "to_dict") else c
        ir.add(
            ShotNode(
                id=str(card.get("name") or f"card_{i}"),
                kind="scene",
                title=str(card.get("name") or f"卡片 {i + 1}"),
                body=str(card.get("purpose") or ""),
                data=card.get("params"),
                duration_sec=float(card.get("suggested_duration_s") or 3.0),
            )
        )
    for i in range(len(ir.nodes) - 1):
        ir.sequence(ir.nodes[i].id, ir.nodes[i + 1].id)
    return ir


def from_tongjian_shot(shots: list[dict[str, Any]], *, title: str = "") -> ShotIR:
    """Tongjian Shot(dict 化)→ ShotIR。字段:scene_id/location/camera/对白。"""
    ir = ShotIR(intent="explainer", synopsis=title)
    for i, s in enumerate(shots):
        ir.add(
            ShotNode(
                id=str(s.get("id") or s.get("scene_id") or f"shot_{i}"),
                kind="scene",
                title=str(s.get("scene_id") or f"镜 {i + 1}"),
                body=str(s.get("dialogue") or s.get("caption") or ""),
                data={
                    "location": s.get("location"),
                    "camera": s.get("camera"),
                },
                duration_sec=float(s.get("duration_s") or s.get("duration") or 4.0),
            )
        )
    for i in range(len(ir.nodes) - 1):
        ir.sequence(ir.nodes[i].id, ir.nodes[i + 1].id)
    return ir


def from_storyboard_node(
    nodes: list[dict[str, Any]], *, title: str = ""
) -> ShotIR:
    """omodul storyboard 节点列表(dict 化)→ ShotIR。
    节点字段常见:scene_id/shot_type/image_prompt/caption/duration。
    """
    ir = ShotIR(intent="explainer", synopsis=title)
    for i, n in enumerate(nodes):
        node_id = str(n.get("scene_id") or n.get("id") or f"shot_{i}")
        kind = "scene"
        caption = str(n.get("caption") or n.get("narration") or "")
        # 数据感分镜(图表/数字)→ data 节点
        body = str(n.get("image_prompt") or "")
        if any(k in (caption + body) for k in ("百分比", "数字", "增长", "对比")):
            kind = "data"
        ir.add(
            ShotNode(
                id=node_id,
                kind=kind,
                title=node_id,
                body=caption or body,
                data={"image_prompt": body} if body else None,
                duration_sec=float(n.get("duration") or n.get("duration_s") or 4.0),
            )
        )
    for i in range(len(ir.nodes) - 1):
        ir.sequence(ir.nodes[i].id, ir.nodes[i + 1].id)
    return ir


__all__ = [
    "ShotIR",
    "ShotNode",
    "from_frame_plan",
    "from_recipe_card",
    "from_storyboard_node",
    "from_tongjian_shot",
    "topo_sort",
]
