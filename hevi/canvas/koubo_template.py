"""Default koubo_cut canvas graph (canvas MVP).

The graph is a parallel per-sentence structure, not a single chain:

    script ─ sentences ─┬─ tts_1 ─ avatar_1 ─┐
                        ├─ evidence_1 ───────┤
                        ├─ tts_2 ─ avatar_2 ─┤
                        ├─ evidence_2 ───────┤
                        │        …           ├─ edit ─ subtitle ─ final
                        └────────────────────┘

Each sentence owns its TTS / evidence / avatar / segment branch; ``edit`` only
concatenates the finished per-sentence clips.  Editing sentence 2 therefore
re-runs sentence 2's branch (plus the cheap concat), while every other branch's
artifacts keep their content hash and are reused by the content-hash engine
(``hevi.canvas.graph_diff`` + ``incremental_executor``).

Every edge stays inside ``hevi.canvas.validation.EDGE_MATRIX`` and no rule is
relaxed.  ``project_execution_plan`` still projects an ``ExecutionPlan`` onto
the eight logical steps and feeds the skeleton; it never becomes a second
source of truth.
"""

from __future__ import annotations

from typing import Any

KOUBO_TEMPLATE_ID = "koubo_cut"
KOUBO_GRAPH_NAME = "koubo_cut 口播默认图"

# Logical steps kept for ExecutionPlan projection (key or order).
KOUBO_STEPS: tuple[dict[str, Any], ...] = (
    {"key": "script", "label": "脚本", "node_type": "text", "koubo_step": "script"},
    {"key": "sentences", "label": "分句", "node_type": "script", "koubo_step": "sentences"},
    {"key": "tts", "label": "TTS 旁白", "node_type": "audio", "koubo_step": "tts"},
    {"key": "avatar", "label": "头像", "node_type": "video", "koubo_step": "avatar"},
    {"key": "evidence", "label": "证据素材", "node_type": "video", "koubo_step": "evidence"},
    {"key": "edit", "label": "剪辑", "node_type": "video", "koubo_step": "edit"},
    {"key": "subtitle", "label": "字幕", "node_type": "text", "koubo_step": "subtitle"},
    {"key": "final", "label": "成片", "node_type": "video", "koubo_step": "final"},
)

PER_SENTENCE_STEPS: tuple[dict[str, Any], ...] = (
    {"prefix": "tts", "label": "TTS", "node_type": "audio", "koubo_step": "tts_sentence"},
    {"prefix": "evidence", "label": "证据", "node_type": "video", "koubo_step": "evidence_sentence"},
    {"prefix": "avatar", "label": "头像", "node_type": "video", "koubo_step": "avatar_sentence"},
    {"prefix": "segment", "label": "分镜段", "node_type": "video", "koubo_step": "segment"},
)


def split_script_lines(
    *, script_text: str = "", topic: str = "", script_lines: list[Any] | None = None
) -> list[str]:
    """Use the koubo pipeline's own splitter so the graph matches rendering."""
    from hevi.koubo_cut.pipeline import _script_lines

    lines = _script_lines(
        script_text=str(script_text or ""),
        script_lines=list(script_lines or []),
        topic=str(topic or ""),
    )
    return [line for line in lines if str(line).strip()]


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
    """Map plan nodes onto the logical koubo steps (key match, then order)."""
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
    script_lines: list[Any] | None = None,
) -> dict[str, Any]:
    """Return a canvas graph dict (nodes/edges/name/description)."""
    projected = project_execution_plan(plan)
    lines = split_script_lines(
        script_text=script_text, topic=topic, script_lines=script_lines
    )
    sentence_count = max(1, len(lines))
    base = {
        "topic": topic or "",
        "duration_s": float(duration_s),
        "engine": str(engine or "livliv"),
        "character_id": str(character_id or "d03ft"),
        "out_dir": str(out_dir or ""),
    }
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def add_node(
        key: str,
        label: str,
        node_type: str,
        koubo_step: str,
        config: dict[str, Any],
        pos: dict[str, Any],
        input_refs: list[str],
    ) -> None:
        nodes.append(
            {
                "node_id": key,
                "node_type": node_type,
                "label": label,
                "config": {**base, "koubo_step": koubo_step, **config},
                "position": pos,
                "input_refs": input_refs,
            }
        )

    def add_edge(src: str, dst: str, kind: str = "data") -> None:
        edges.append(
            {
                "edge_id": f"e_{src}_{dst}",
                "from_node_id": src,
                "to_node_id": dst,
                "kind": kind,
            }
        )

    pos = positions or {}
    add_node(
        "script",
        "脚本",
        "text",
        "script",
        {
            "content": script_text or topic,
            "min_chars": 8,
            "script_lines": list(script_lines or []),
            **projected.get("script", {}),
        },
        pos.get("script") or {"x": 40, "y": 180},
        [],
    )
    add_node(
        "sentences",
        "分句",
        "script",
        "sentences",
        {**projected.get("sentences", {})},
        pos.get("sentences") or {"x": 320, "y": 180},
        ["script"],
    )
    add_edge("script", "sentences")

    for index in range(sentence_count):
        row_y = 80 + index * 300
        tts_key = f"tts_{index + 1}"
        evidence_key = f"evidence_{index + 1}"
        avatar_key = f"avatar_{index + 1}"
        segment_key = f"segment_{index + 1}"
        add_node(
            tts_key,
            f"TTS {index + 1}",
            "audio",
            "tts_sentence",
            {"sentence_index": index, "sub_type": "tts", "provider": "piper", **projected.get("tts", {})},
            {"x": 620, "y": row_y},
            ["sentences"],
        )
        add_node(
            evidence_key,
            f"证据 {index + 1}",
            "video",
            "evidence_sentence",
            {
                "sentence_index": index,
                **projected.get("evidence", {}),
            },
            {"x": 900, "y": row_y},
            ["sentences"],
        )
        add_node(
            avatar_key,
            f"头像 {index + 1}",
            "video",
            "avatar_sentence",
            {"sentence_index": index, **projected.get("avatar", {})},
            {"x": 1180, "y": row_y},
            [tts_key],
        )
        add_node(
            segment_key,
            f"分镜段 {index + 1}",
            "video",
            "segment",
            {"sentence_index": index},
            {"x": 1460, "y": row_y},
            ["sentences", tts_key, evidence_key, avatar_key],
        )
        add_edge("sentences", tts_key)
        add_edge("sentences", evidence_key)
        add_edge(tts_key, avatar_key, "data")
        add_edge("sentences", segment_key)
        add_edge(tts_key, segment_key)
        add_edge(evidence_key, segment_key)
        add_edge(avatar_key, segment_key)

    add_node(
        "edit",
        "剪辑",
        "video",
        "edit_segments",
        {**projected.get("edit", {})},
        pos.get("edit") or {"x": 1760, "y": 180},
        [f"segment_{i + 1}" for i in range(sentence_count)],
    )
    for index in range(sentence_count):
        add_edge(f"segment_{index + 1}", "edit")
    add_node(
        "subtitle",
        "字幕",
        "text",
        "subtitle",
        {"sub_type": "srt", **projected.get("subtitle", {})},
        pos.get("subtitle") or {"x": 2040, "y": 180},
        ["edit"],
    )
    add_edge("edit", "subtitle", "subtitle")
    add_node(
        "final",
        "成片",
        "video",
        "final",
        {**projected.get("final", {})},
        pos.get("final") or {"x": 2320, "y": 180},
        ["subtitle"],
    )
    add_edge("subtitle", "final", "subtitle")

    return {
        "name": KOUBO_GRAPH_NAME,
        "description": (
            "koubo_cut 默认图：脚本 → 分句 → 每句并行（TTS / 证据 / 头像 / 分镜段）"
            " → 剪辑拼接 → 字幕 → 成片；改一句只重做该句分支，其余按内容哈希复用。"
        ),
        "template_id": KOUBO_TEMPLATE_ID,
        "nodes": nodes,
        "edges": edges,
        "sentence_count": sentence_count,
        "sentence_texts": lines,
    }
