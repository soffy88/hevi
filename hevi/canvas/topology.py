"""Dynamic per-sentence topology for the koubo canvas template.

The default graph has one ``tts/evidence/avatar/segment`` branch per sentence.
When the script is edited and the sentence count changes, the graph must add or
drop branches instead of silently rendering only the old count.  This module
reconciles an edited graph against the current template:

* surviving nodes keep their config, label and position;
* new sentences get a complete branch (and inherit the per-step config of a
  sibling branch so an ExecutionPlan projection is not lost);
* removed sentence nodes are reported so the caller can archive their
  artifacts before they are soft-deleted.  Their output directory is moved to
  ``<out_dir>/_archive/<node>-<timestamp>`` so a later re-added node can never
  overwrite the archived render;
* locked nodes are kept even when their sentence disappeared (a lock is an
  explicit user promise and wins over the sentence count).

Pure functions except :func:`archive_node_artifacts` (file moves).  No
database, provider or network access.
"""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hevi.canvas.koubo_template import build_koubo_graph, split_script_lines

_SENTENCE_NODE_RE = re.compile(r"^(tts|evidence|avatar|segment)_(\d+)$")


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("node_id") or node.get("id") or "")


def _cfg(node: dict[str, Any]) -> dict[str, Any]:
    return dict(node.get("config") or {})


def _is_koubo_graph(nodes: list[dict[str, Any]]) -> bool:
    ids = {_node_id(n) for n in nodes}
    steps = {str(_cfg(n).get("koubo_step") or "") for n in nodes}
    return {"script", "sentences", "edit"} <= ids and "script" in steps


def _sentence_keys(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if _SENTENCE_NODE_RE.match(_node_id(node)):
            out[_node_id(node)] = node
    return out


def _step_defaults(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-step execution config copied onto newly created branch nodes."""
    defaults: dict[str, dict[str, Any]] = {}
    for node in nodes:
        nid = _node_id(node)
        match = _SENTENCE_NODE_RE.match(nid)
        if not match:
            continue
        step = match.group(1)
        if step in defaults:
            continue
        cfg = dict(_cfg(node))
        cfg.pop("sentence_index", None)
        cfg.pop("graph_id", None)
        defaults[step] = cfg
    return defaults


def _script_context(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    script = next((n for n in nodes if _node_id(n) == "script"), {})
    base = _cfg(script)
    topic = str(base.get("topic") or "")
    if not topic:
        for node in nodes:
            topic = str(_cfg(node).get("topic") or "")
            if topic:
                break
    return {
        "script_text": str(
            base.get("content") or base.get("script_text") or ""
        ),
        "script_lines": list(base.get("script_lines") or []),
        "topic": topic,
        "duration_s": float(base.get("duration_s") or 10.0),
        "engine": str(base.get("engine") or "livliv"),
        "character_id": str(base.get("character_id") or "d03ft"),
        "out_dir": str(base.get("out_dir") or ""),
    }


def reconcile_koubo_topology(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    locked_keys: set[str] | None = None,
) -> dict[str, Any] | None:
    """Return ``{nodes, edges, added, removed, sentence_count, lines}``.

    ``None`` when the graph is not the koubo per-sentence template.
    """
    if not _is_koubo_graph(nodes):
        return None
    locked = set(locked_keys or set())
    context = _script_context(nodes)
    lines = split_script_lines(
        script_text=context["script_text"],
        topic=context["topic"],
        script_lines=context["script_lines"],
    )
    count = max(1, len(lines))
    positions = {_node_id(n): dict(n.get("position") or {}) for n in nodes}
    rebuilt = build_koubo_graph(
        script_text=context["script_text"],
        topic=context["topic"],
        duration_s=context["duration_s"],
        engine=context["engine"],
        character_id=context["character_id"],
        out_dir=context["out_dir"],
        positions=positions,
        script_lines=context["script_lines"],
    )
    old_by_id = {_node_id(n): n for n in nodes}
    defaults = _step_defaults(nodes)
    expected_ids = {_node_id(n) for n in rebuilt["nodes"]}

    merged_nodes: list[dict[str, Any]] = []
    added: list[str] = []
    for fresh in rebuilt["nodes"]:
        nid = _node_id(fresh)
        old = old_by_id.get(nid)
        if old is not None:
            # The edited node's own config wins (script content, plan fields);
            # only the structural sentence_index is refreshed.
            cfg = {**_cfg(fresh), **_cfg(old)}
            if "sentence_index" in _cfg(fresh):
                cfg["sentence_index"] = _cfg(fresh)["sentence_index"]
            merged_nodes.append(
                {
                    **fresh,
                    "config": cfg,
                    "label": old.get("label") or fresh.get("label"),
                    "position": old.get("position") or fresh.get("position"),
                }
            )
            continue
        match = _SENTENCE_NODE_RE.match(nid)
        cfg = dict(_cfg(fresh))
        if match:
            cfg = {**defaults.get(match.group(1), {}), **cfg}
        merged_nodes.append({**fresh, "config": cfg})
        added.append(nid)

    merged_ids = {_node_id(n) for n in merged_nodes}
    removed: list[str] = []
    for nid, node in _sentence_keys(nodes).items():
        if nid in expected_ids:
            continue
        if nid in locked:
            merged_nodes.append(node)
            merged_ids.add(nid)
        else:
            removed.append(nid)

    # Keep custom (non-template) nodes the user added by hand.  Removed
    # per-sentence nodes were already archived above, so skip that pattern.
    for nid, node in old_by_id.items():
        if nid in expected_ids or nid in merged_ids:
            continue
        if _SENTENCE_NODE_RE.match(nid):
            continue
        merged_nodes.append(node)
        merged_ids.add(nid)

    def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(edge.get("from_node_id") or edge.get("source") or ""),
            str(edge.get("to_node_id") or edge.get("target") or ""),
            str(edge.get("kind") or "data"),
        )

    rebuilt_edges = list(rebuilt["edges"])
    seen = {_edge_key(e) for e in rebuilt_edges}
    for edge in edges:
        src, dst, kind = _edge_key(edge)
        if src in merged_ids and dst in merged_ids and (src, dst, kind) not in seen:
            rebuilt_edges.append(edge)
            seen.add((src, dst, kind))

    return {
        "nodes": merged_nodes,
        "edges": rebuilt_edges,
        "added": added,
        "removed": removed,
        "sentence_count": count,
        "lines": lines,
    }


def _out_base(node: dict[str, Any]) -> Path:
    raw = str(_cfg(node).get("out_dir") or "").strip()
    return Path(raw) if raw else Path("output/canvas/koubo")


def archive_node_artifacts(graph_id: str, node: dict[str, Any]) -> str | None:
    """Move a removed node's output directory to the graph archive.

    Handles both the per-graph layout (``<base>/<graph>/<node>``) and the
    legacy shared layout (``<base>/<node>``).  Returns the archive path (or
    ``None`` when there was nothing to move).
    """
    if not graph_id:
        return None
    base = _out_base(node)
    nid = _node_id(node)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_root = base / graph_id / "_archive"
    candidates = [base / graph_id / nid, base / nid]
    moved_to: str | None = None
    for source in candidates:
        if not source.is_dir():
            continue
        archive_root.mkdir(parents=True, exist_ok=True)
        target = archive_root / f"{nid}-{stamp}"
        suffix = 1
        while target.exists():
            suffix += 1
            target = archive_root / f"{nid}-{stamp}-{suffix}"
        try:
            shutil.move(str(source), str(target))
        except OSError:
            continue
        moved_to = str(target)
    return moved_to


__all__ = ["archive_node_artifacts", "reconcile_koubo_topology"]
