"""Default koubo_cut canvas graph (canvas MVP).

One node per production step, in the order the offline pipeline already runs:

    script → sentences → TTS → avatar/footage → evidence shot → edit →
    subtitle → final

The shape is a plain chain of legal hevi canvas types (``text → script →
audio → video → video → video → text → video``); every edge is in
``hevi.canvas.validation.EDGE_MATRIX`` and no edge rule is relaxed.

`build_koubo_graph` can project an ``ExecutionPlan`` (either the compiler
``hevi.production_graph.domain.ExecutionPlan`` or the immutable
``hevi.execution.plan.ExecutionPlan``) onto the step skeleton: matching node
keys override the step config, and a plan whose node count matches the
skeleton is projected by order.  The plan never becomes a second source of
truth — it only feeds the skeleton.
"""

from __future__ import annotations

from typing import Any

KOUBO_TEMPLATE_ID = "koubo_cut"
KOUBO_GRAPH_NAME = "koubo_cut 口播默认图"

KOUBO_STEPS: tuple[dict[str, Any], ...] = (
    {"key": "script", "label": "脚本", "node_type": "text", "koubo_step": "script"},
    {"key": "sentences", "label": "分句", "node_type": "script", "koubo_step": "sentences"},
    {"key": "tts", "label": "TTS 旁白", "node_type": "audio", "koubo_step": "tts"},
    {"key": "avatar", "label": "头像/实拍", "node_type": "video", "koubo_step": "avatar"},
    {"key": "evidence", "label": "证据截图", "node_type": "video", "koubo_step": "evidence"},
    {"key": "edit", "label": "剪辑", "node_type": "video", "koubo_step": "edit"},
    {"key": "subtitle", "label": "字幕", "node_type": "text", "koubo_step": "subtitle"},
    {"key": "final", "label": "成片", "node_type": "video", "koubo_step": "final"},
)

_EDGE_KINDS = {
    ("script", "sentences"): "data",
    ("sentences", "tts"): "data",
    ("tts", "avatar"): "data",
    ("avatar", "evidence"): "data",
    ("evidence", "edit"): "reference",
    ("edit", "subtitle"): "subtitle",
    ("subtitle", "final"): "subtitle",
}


def _plan_nodes(plan: Any) -> list[dict[str, Any]]:
    if plan is None:
        return []
    if hasattr(plan, "model_dump"):
        plan = plan.model_dump(mode="json")
    if not isinstance(plan, dict):
        return []
    raw_plan = plan.get("plan_json") if isinstance(plan.get("plan_json"), dict) else plan
    nodes = raw_plan.get("nodes") or plan.get("nodes") or []
    return [n for n in nodes if isinstance(n, dict)]


def project_execution_plan(plan: Any) -> dict[str, dict[str, Any]]:
    """Map plan nodes onto the koubo step skeleton (key match, then order)."""
    nodes = _plan_nodes(plan)
    if not nodes:
        return {}
    by_key: dict[str, dict[str, Any]] = {}
    for node in nodes:
        key = str(
            node.get("node_key")
            or node.get("node_id")
            or node.get("id")
            or node.get("step")
            or ""
        )
        if key:
            by_key[key] = node
    if not by_key and len(nodes) == len(KOUBO_STEPS):
        by_key = {step["key"]: node for step, node in zip(KOUBO_STEPS, nodes, strict=True)}
    projected: dict[str, dict[str, Any]] = {}
    for step in KOUBO_STEPS:
        node = by_key.get(step["key"])
        if not node:
            continue
        config: dict[str, Any] = {}
        raw_cfg = node.get("config")
        if isinstance(raw_cfg, dict):
            config.update(raw_cfg)
        for source, target in (
            ("prompt", "prompt"),
            ("parameters", "parameters"),
            ("provider", "provider"),
            ("model", "model"),
            ("duration", "duration_s"),
            ("duration_s", "duration_s"),
            ("capability", "capability"),
        ):
            if node.get(source) not in (None, ""):
                config[target] = node[source]
        projected[step["key"]] = config
    return projected


def build_koubo_graph(
    *,
    script_text: str = "",
    topic: str = "",
    duration_s: float = 10.0,
    engine: str = "livliv",
    character_id: str = "d03ft",
    out_dir: str = "",
    plan: Any = None,
    positions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a canvas graph dict (nodes/edges/name/description)."""
    projected = project_execution_plan(plan)
    base = {
        "script_text": script_text,
        "topic": topic or script_text,
        "duration_s": float(duration_s),
        "engine": str(engine or "livliv"),
        "character_id": str(character_id or "d03ft"),
        "out_dir": str(out_dir or ""),
    }
    nodes: list[dict[str, Any]] = []
    for index, step in enumerate(KOUBO_STEPS):
        config: dict[str, Any] = {**base, "koubo_step": step["koubo_step"]}
        if step["key"] == "script":
            config.update({"content": script_text or topic, "min_chars": 8})
        if step["key"] == "tts":
            config.update({"sub_type": "tts", "provider": "piper"})
        if step["key"] == "subtitle":
            config.update({"sub_type": "srt"})
        config.update(projected.get(step["key"], {}))
        pos = (positions or {}).get(step["key"]) or {
            "x": 60 + index * 280,
            "y": 180 + (index % 2) * 90,
        }
        nodes.append(
            {
                "node_id": step["key"],
                "node_type": step["node_type"],
                "label": step["label"],
                "config": config,
                "position": pos,
                "input_refs": [] if index == 0 else [KOUBO_STEPS[index - 1]["key"]],
            }
        )
    edges: list[dict[str, Any]] = []
    for index in range(1, len(KOUBO_STEPS)):
        src = KOUBO_STEPS[index - 1]["key"]
        dst = KOUBO_STEPS[index]["key"]
        edges.append(
            {
                "edge_id": f"e_{src}_{dst}",
                "from_node_id": src,
                "to_node_id": dst,
                "kind": _EDGE_KINDS.get((src, dst), "data"),
            }
        )
    return {
        "name": KOUBO_GRAPH_NAME,
        "description": (
            "koubo_cut 默认图：脚本 → 分句 → TTS → 头像/实拍 → 证据截图 → "
            "剪辑 → 字幕 → 成片；每步一个节点，执行时可只重跑选中节点及下游。"
        ),
        "template_id": KOUBO_TEMPLATE_ID,
        "nodes": nodes,
        "edges": edges,
    }
