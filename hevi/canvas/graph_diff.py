"""Pure graph-diff helpers for the incremental canvas executor.

No database, no provider, no network.  These functions decide *what* is stale
and *what* to run; the store and executor only carry the decision out.

Method provenance (ideas only, hevi-written): an upstream change marks the
node stale but never rewrites it, and a rerun touches only the selected node
plus its downstream (``HEVI_CANVAS_DESIGN.md`` §2.1/§2.2).  Locked nodes are
never overwritten and are reported as ``locked_skipped`` (§2.2).
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Iterable
from typing import Any

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_STALE = "stale"
STATUS_LOCKED = "locked"

_RUNNABLE_STATUSES = frozenset({STATUS_PENDING, STATUS_RUNNING, STATUS_STALE, STATUS_FAIL})
# UI-only keys never change an execution result, so they never make a node
# stale.  Explicitly excluding them keeps a label/position edit free.
_UI_CONFIG_KEYS = frozenset(
    {
        "label",
        "position",
        "last_result",
        "ui",
        "selected",
        "notes",
        "review_pending",
        "material_pack_review_pending",
    }
)


def execution_config(config: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (config or {}).items() if k not in _UI_CONFIG_KEYS}


def node_fingerprint(node: dict[str, Any]) -> str:
    """Stable digest of the fields that can change an execution result."""
    payload = {
        "node_type": node.get("node_type") or node.get("type") or "",
        "config": execution_config(node.get("config") or {}),
        "input_refs": node.get("input_refs") or [],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def config_fingerprint(node: dict[str, Any]) -> str:
    """Digest of one node's own execution config (no upstream)."""
    config = execution_config(node.get("config") or {})
    blob = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def output_content_hash(output: Any) -> str:
    """Content hash of one node output (engine bookkeeping excluded).

    A node may declare ``content_hash`` itself (a sentence's text, a segment's
    inputs).  Otherwise the JSON without private ``_`` keys is hashed; that is
    stable because every node writes into its own fixed directory.
    """
    if isinstance(output, dict):
        explicit = output.get("content_hash")
        if isinstance(explicit, str) and explicit:
            return explicit
        engine = output.get("_engine")
        if isinstance(engine, dict) and isinstance(engine.get("content_hash"), str):
            return engine["content_hash"]
        clean = {k: v for k, v in output.items() if not str(k).startswith("_")}
        blob = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    else:
        blob = json.dumps(output, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def node_input_fingerprint(node: dict[str, Any], upstream: dict[str, Any]) -> str:
    """Fingerprint of a node's config plus its upstream *content*.

    Per-sentence koubo nodes declare ``sentence_index``: for those, only that
    slice of an upstream ``sentences`` output counts, so editing sentence 2
    leaves sentence 3's branch fingerprint untouched.  Every other upstream
    contributes its content hash (not its file path or revision).
    """
    config = execution_config(node.get("config") or {})
    index = config.get("sentence_index")
    parts: list[str] = []
    for key in sorted(upstream, key=str):
        out = upstream[key]
        slice_value = None
        if isinstance(index, int) and isinstance(out, dict):
            sentences = out.get("sentences")
            if isinstance(sentences, list) and 0 <= index < len(sentences):
                slice_value = sentences[index]
        parts.append(output_content_hash(slice_value if slice_value is not None else out))
    payload = {
        "config": config,
        "upstream": parts,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _node_key(node: dict[str, Any]) -> str:
    return str(node.get("node_id") or node.get("id") or "")


def edge_pairs(edges: Iterable[dict[str, Any]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for edge in edges:
        src = str(edge.get("from_node_id") or edge.get("source") or "")
        dst = str(edge.get("to_node_id") or edge.get("target") or "")
        if src and dst:
            pairs.append((src, dst))
    return pairs


def adjacency(edges: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = defaultdict(list)
    for src, dst in edge_pairs(edges):
        adj[src].append(dst)
    return adj


def topological_layers(node_keys: Iterable[str], edges: Iterable[dict[str, Any]]) -> list[list[str]]:
    keys = [str(k) for k in node_keys]
    known = set(keys)
    in_degree = dict.fromkeys(keys, 0)
    adj = adjacency(edges)
    for src, dst in edge_pairs(edges):
        if src in known and dst in known:
            in_degree[dst] += 1
    queue = deque(k for k in keys if in_degree[k] == 0)
    layers: list[list[str]] = []
    while queue:
        layer = list(queue)
        layers.append(layer)
        queue.clear()
        for node in layer:
            for nxt in adj.get(node, []):
                if nxt not in known:
                    continue
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)
    if sum(len(layer) for layer in layers) != len(keys):
        raise ValueError("canvas graph contains a cycle")
    return layers


def descendants(edges: Iterable[dict[str, Any]], roots: Iterable[str]) -> set[str]:
    adj = adjacency(edges)
    seen: set[str] = set()
    stack = [str(r) for r in roots]
    while stack:
        node = stack.pop()
        for nxt in adj.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def affected_nodes(
    old_nodes: Iterable[dict[str, Any]],
    new_nodes: Iterable[dict[str, Any]],
    edges: Iterable[dict[str, Any]],
) -> set[str]:
    """Changed/added nodes plus every downstream node (not the unchanged roots)."""
    old = {_node_key(n): n for n in old_nodes if _node_key(n)}
    new = {_node_key(n): n for n in new_nodes if _node_key(n)}
    changed: set[str] = set()
    for key, node in new.items():
        if key not in old or node_fingerprint(node) != node_fingerprint(old[key]):
            changed.add(key)
    # A removed node still invalidates its downstream.
    removed = set(old) - set(new)
    return changed | descendants(edges, changed | removed)


def compute_run_set(
    *,
    scope: str,
    node_keys: Iterable[str],
    edges: Iterable[dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    selected_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return the ordered run plan for one execute call.

    ``nodes`` maps node_key -> {"status", "revision", "locked"}.  The return
    value has:
      run      ordered node keys that will be executed
      skipped  node keys intentionally not run (seeded from last output)
      locked   node keys skipped because they are locked
      layers   topological layers restricted to ``run``
    """
    keys = [str(k) for k in node_keys]
    if scope not in ("all", "dirty", "selected"):
        raise ValueError(f"unknown execute scope: {scope!r}")

    locked = {k for k in keys if bool(nodes.get(k, {}).get("locked"))}
    if scope == "all":
        wanted = set(keys)
    elif scope == "dirty":
        wanted = {
            k
            for k in keys
            if nodes.get(k, {}).get("status") in _RUNNABLE_STATUSES
            or int(nodes.get(k, {}).get("revision") or 0) == 0
        }
    else:
        roots = {str(s) for s in (selected_ids or [])}
        wanted = roots | descendants(edges, roots)
    run = wanted - locked
    skipped = set(keys) - run
    layers = [layer for layer in topological_layers(keys, edges) if any(k in run for k in layer)]
    layers = [[k for k in layer if k in run] for layer in layers]
    layers = [layer for layer in layers if layer]
    ordered = [k for layer in layers for k in layer]
    return {
        "run": ordered,
        "skipped": sorted(skipped),
        "locked": sorted(wanted & locked),
        "layers": layers,
    }
