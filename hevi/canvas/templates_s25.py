"""S25：带版本的工作流模板（换素材复用）。

与 BeefTV 的“保存为工作流 + 模板版本”对齐，但只复用 hevi 已有画布图结构：

* 模板 = 一份画布图 + 一组**槽位**（节点里的可替换字段：主题、提示词、媒体路径）；
* 发布新版本不改旧实例：``apply`` 必须显式指定版本（默认当前版），返回的图里带
  ``template_id`` / ``template_version``，实例钉住版本；
* 存储是文件（``output/canvas_templates``，容器里是持久卷），原子写，无迁移；
* 每个出品形式内置 1 个模板（首次读取时生成，不调用模型/网络）。

槽位规则：只暴露“内容型”字段（prompt/content/text/topic/media_path/...），
不暴露 node_id、工具 id、时长这类结构字段；换素材只改值，不改图。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TEMPLATE_SCHEMA = "hevi.canvas.template.v1"
_LOCK = threading.Lock()

_SLOT_FIELDS = (
    "topic", "content", "text", "prompt", "line", "narration",
    "media_path", "source_path", "video_path", "audio_path", "image_path",
)


def template_dir() -> Path:
    return Path(os.environ.get("HEVI_CANVAS_TEMPLATE_DIR", "output/canvas_templates"))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _index_path() -> Path:
    return template_dir() / "index.json"


def _load_index() -> dict[str, Any]:
    return _read(_index_path()) or {"schema": TEMPLATE_SCHEMA, "builtin_done": False, "templates": {}}


def _save_index(index: dict[str, Any]) -> None:
    _atomic_write(_index_path(), index)


def _graph_parts(graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = graph.get("nodes") or graph.get("nodes_json") or []
    edges = graph.get("edges") or graph.get("edges_json") or []
    return [dict(n) for n in nodes], [dict(e) for e in edges]


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("node_id") or node.get("id") or "")


def derive_slots(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """从图里派生槽位；同名字段在多个节点上按节点 id 区分。"""
    slots: list[dict[str, Any]] = []
    for node in _graph_parts(graph)[0]:
        nid = _node_id(node)
        cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
        for field in _SLOT_FIELDS:
            if field not in cfg:
                continue
            value = cfg.get(field)
            if isinstance(value, (dict, list)):
                continue
            slots.append(
                {
                    "key": f"{nid}.{field}",
                    "node_id": nid,
                    "field": field,
                    "label": f"{node.get('label') or nid} · {field}",
                    "kind": "media" if field.endswith(("_path",)) else "text",
                    "value": value,
                }
            )
    return slots


def _path_for(template_id: str, version: int) -> Path:
    return template_dir() / f"{template_id}.v{version}.json"


def _snapshot(
    template_id: str,
    *,
    name: str,
    format_id: str,
    style: str,
    graph: dict[str, Any],
    note: str = "",
) -> dict[str, Any]:
    index = _load_index()
    meta = index["templates"].get(template_id) or {}
    version = int(meta.get("current_version") or 0) + 1
    nodes, edges = _graph_parts(graph)
    body = {
        "schema": TEMPLATE_SCHEMA,
        "id": template_id,
        "name": name,
        "format": format_id,
        "style": style,
        "version": version,
        "created_at": datetime.now(UTC).isoformat(),
        "note": note,
        "graph": {"nodes": nodes, "edges": edges},
        "slots": derive_slots({"nodes": nodes, "edges": edges}),
        "stats": {"nodes": len(nodes), "edges": len(edges)},
    }
    body["sha256"] = _sha(body)
    _atomic_write(_path_for(template_id, version), body)
    index["templates"][template_id] = {
        "id": template_id,
        "name": name,
        "format": format_id,
        "style": style,
        "current_version": version,
        "updated_at": body["created_at"],
        "builtin": bool(meta.get("builtin")),
    }
    _save_index(index)
    return body


def ensure_builtin_templates() -> list[dict[str, Any]]:
    """为每个出品形式生成 1 个内置模板（只做一次）。"""
    index = _load_index()
    if index.get("builtin_done"):
        return list_templates()
    from hevi.canvas import agent_build
    from hevi.studio.formats import FORMATS

    for fmt in FORMATS:
        topic = fmt.example.strip("「」") or fmt.label
        try:
            plan = agent_build.build_plan(topic, format_id=fmt.id, structural_only=False)
            graph = agent_build.apply_plan(plan, confirm_token=plan["confirm_token"], name=f"内置 · {fmt.label}")
        except Exception:
            continue
        template_id = f"builtin-{fmt.id}"
        body = _snapshot(
            template_id,
            name=f"内置 · {fmt.label}",
            format_id=fmt.id,
            style=fmt.default_style,
            graph={"nodes": graph["nodes"], "edges": graph["edges"]},
            note="S25 内置：换主题/提示词/素材即可复用，不改结构。",
        )
        idx = _load_index()
        idx["templates"][template_id]["builtin"] = True
        idx["templates"][template_id]["example"] = topic
        _save_index(idx)
        body.setdefault("example", topic)
    idx = _load_index()
    idx["builtin_done"] = True
    _save_index(idx)
    return list_templates()


def list_templates(format_id: str | None = None) -> list[dict[str, Any]]:
    index = _load_index()
    items = []
    for meta in index.get("templates", {}).values():
        if format_id and meta.get("format") != format_id:
            continue
        items.append(dict(meta))
    items.sort(key=lambda m: (not m.get("builtin"), str(m.get("name") or "")))
    return items


def get_template(template_id: str, version: int | None = None) -> dict[str, Any]:
    index = _load_index()
    meta = index["templates"].get(template_id)
    if not meta:
        raise ValueError(f"模板不存在：{template_id}")
    ver = int(version or meta.get("current_version") or 1)
    body = _read(_path_for(template_id, ver))
    if not body:
        raise ValueError(f"模板版本不存在：{template_id} v{ver}")
    return body


def create_template(
    *,
    template_id: str,
    name: str,
    graph: dict[str, Any],
    format_id: str = "",
    style: str = "",
    note: str = "",
) -> dict[str, Any]:
    if not template_id or not template_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("模板 id 只能用小写字母、数字、- 和 _")
    with _LOCK:
        return _snapshot(
            template_id, name=name, format_id=format_id, style=style, graph=graph, note=note
        )


def publish_version(
    template_id: str,
    graph: dict[str, Any],
    *,
    note: str = "",
    name: str | None = None,
) -> dict[str, Any]:
    with _LOCK:
        index = _load_index()
        meta = index["templates"].get(template_id)
        if not meta:
            raise ValueError(f"模板不存在：{template_id}")
        return _snapshot(
            template_id,
            name=name or str(meta.get("name") or template_id),
            format_id=str(meta.get("format") or ""),
            style=str(meta.get("style") or ""),
            graph=graph,
            note=note,
        )


def apply_template(
    template_id: str,
    values: dict[str, Any] | None = None,
    *,
    version: int | None = None,
) -> dict[str, Any]:
    """返回钉住版本的新画布图；``values`` 是槽位 key → 新值。"""
    body = get_template(template_id, version)
    graph = json.loads(json.dumps(body["graph"], ensure_ascii=False))
    slots = {s["key"]: s for s in body.get("slots") or []}
    unknown = [k for k in (values or {}) if k not in slots]
    if unknown:
        raise ValueError("未知槽位：" + ", ".join(sorted(unknown)[:5]))
    for key, value in (values or {}).items():
        slot = slots[key]
        for node in graph["nodes"]:
            if _node_id(node) != slot["node_id"]:
                continue
            cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
            cfg[slot["field"]] = value
            node["config"] = cfg
    return {
        "template_id": template_id,
        "template_name": body.get("name"),
        "template_version": body.get("version"),
        "template_sha256": body.get("sha256"),
        "format": body.get("format"),
        "style": body.get("style"),
        "nodes": graph["nodes"],
        "edges": graph["edges"],
        "slots": body.get("slots") or [],
        "numbers": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"])},
    }


def diff_versions(template_id: str, from_version: int, to_version: int) -> dict[str, Any]:
    a = get_template(template_id, from_version)
    b = get_template(template_id, to_version)
    a_nodes = {_node_id(n): n for n in a["graph"]["nodes"]}
    b_nodes = {_node_id(n): n for n in b["graph"]["nodes"]}
    added = sorted(set(b_nodes) - set(a_nodes))
    removed = sorted(set(a_nodes) - set(b_nodes))
    changed = sorted(
        nid for nid in set(a_nodes) & set(b_nodes) if _canonical(a_nodes[nid]) != _canonical(b_nodes[nid])
    )
    a_slots = {s["key"]: s.get("value") for s in a.get("slots") or []}
    b_slots = {s["key"]: s.get("value") for s in b.get("slots") or []}
    slot_changes = [
        {"key": k, "from": a_slots.get(k), "to": b_slots.get(k)}
        for k in sorted(set(a_slots) | set(b_slots))
        if a_slots.get(k) != b_slots.get(k)
    ]
    return {
        "template_id": template_id,
        "from_version": from_version,
        "to_version": to_version,
        "nodes": {"added": added, "removed": removed, "changed": changed},
        "slot_changes": slot_changes,
        "summary": f"v{from_version} → v{to_version}：+{len(added)} / -{len(removed)} / ~{len(changed)} 节点，{len(slot_changes)} 个槽位",
    }


def template_payload_meta(body: dict[str, Any]) -> dict[str, Any]:
    """给列表/详情用的窄结构（不重复整张图）。"""
    return {
        "id": body.get("id"),
        "name": body.get("name"),
        "format": body.get("format"),
        "style": body.get("style"),
        "version": body.get("version"),
        "created_at": body.get("created_at"),
        "note": body.get("note"),
        "stats": body.get("stats"),
        "slots": [{k: s.get(k) for k in ("key", "label", "kind", "node_id", "field")} for s in body.get("slots") or []],
        "sha256": body.get("sha256"),
    }


def now_ms() -> int:
    return int(time.time() * 1000)
