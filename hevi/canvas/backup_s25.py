"""S25：画布导出 / 导入备份。

目标不是“把 JSON 复制一份”，而是**可校验、可解释、可回滚**的备份：

* ``schema`` + ``checksum``：导入先验校验，内容被改过就拒绝（除非显式允许）；
* 结构校验：节点 id 唯一、边两端存在、边类型合法（复用 ``EDGE_MATRIX``）；
* 媒体清单：逐个记路径、是否存在、sha256、大小；缺失只警告，不静默丢；
* 导出可选打 zip（媒体总大小超限就只带清单），不复制视频到 DB。

所有路径都必须落在允许的根目录（仓库 data/output/assets）内，防止备份接口
被用来读任意文件。
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hevi.canvas.validation import EDGE_MATRIX

BACKUP_SCHEMA = "hevi.canvas.backup.v1"
MAX_ZIP_MEDIA_BYTES = 512 * 1024 * 1024  # 512 MiB

_MEDIA_KEYS = (
    "media_path", "source_path", "video_path", "audio_path", "image_path",
    "path", "file", "local_path", "reference_image", "first_frame", "tail_frame",
)


def allowed_roots() -> list[Path]:
    repo = Path(__file__).resolve().parents[2]
    return [repo / "data", repo / "output", repo / "assets"]


def _within_allowed(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in allowed_roots():
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _graph_parts(graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = graph.get("nodes") or graph.get("nodes_json") or []
    edges = graph.get("edges") or graph.get("edges_json") or []
    return [dict(n) for n in nodes], [dict(e) for e in edges]


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("node_id") or node.get("id") or "")


def _edge_endpoints(edge: dict[str, Any]) -> tuple[str, str]:
    return (
        str(edge.get("from_node_id") or edge.get("from") or edge.get("source") or ""),
        str(edge.get("to_node_id") or edge.get("to") or edge.get("target") or ""),
    )


def _cfg(node: dict[str, Any]) -> dict[str, Any]:
    cfg = node.get("config")
    return dict(cfg) if isinstance(cfg, dict) else {}


def collect_media(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """按节点 config 里已知的媒体字段收集本地文件（http 链接不进备份）。"""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in _graph_parts(graph)[0]:
        cfg = _cfg(node)
        for key in _MEDIA_KEYS:
            value = cfg.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            text = value.strip()
            if text.startswith(("http://", "https://", "data:", "/uploads/")):
                continue
            path = Path(text)
            if not path.is_absolute():
                path = Path(__file__).resolve().parents[2] / path
            resolved = str(path.resolve()) if path.exists() else str(path)
            if resolved in seen:
                continue
            seen.add(resolved)
            entry: dict[str, Any] = {
                "node_id": _node_id(node),
                "field": key,
                "path": resolved,
                "exists": path.is_file() and _within_allowed(path),
            }
            if entry["exists"]:
                data = path.read_bytes()
                entry["sha256"] = hashlib.sha256(data).hexdigest()
                entry["bytes"] = len(data)
            else:
                entry["reason"] = "文件不存在或不在允许目录（data/output/assets）内"
            items.append(entry)
    return items


def export_backup(
    graph: dict[str, Any],
    *,
    name: str | None = None,
    note: str = "",
    include_media_bytes: bool = False,
    out_zip: str | Path | None = None,
) -> dict[str, Any]:
    """返回可序列化的备份对象；``out_zip`` 给出时额外打包存在的媒体。"""
    nodes, edges = _graph_parts(graph)
    media = collect_media({"nodes": nodes, "edges": edges})
    core = {
        "schema": BACKUP_SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "name": name or str(graph.get("name") or "未命名画布"),
        "note": note,
        "format": graph.get("format") or "",
        "style": graph.get("style") or "",
        "graph": {"nodes": nodes, "edges": edges},
        "media": [{k: v for k, v in m.items() if k in ("node_id", "field", "path", "exists", "sha256", "bytes", "reason")} for m in media],
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "media_total": len(media),
            "media_missing": sum(1 for m in media if not m["exists"]),
        },
    }
    core["checksum"] = hashlib.sha256(_canonical(core).encode("utf-8")).hexdigest()
    if out_zip:
        path = Path(out_zip)
        path.parent.mkdir(parents=True, exist_ok=True)
        total = sum(int(m.get("bytes") or 0) for m in media if m["exists"])
        packed = 0
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("backup.json", json.dumps(core, ensure_ascii=False, indent=2))
            if include_media_bytes and total <= MAX_ZIP_MEDIA_BYTES:
                for i, item in enumerate(media):
                    if not item["exists"]:
                        continue
                    src = Path(item["path"])
                    zf.write(src, f"media/{i:04d}-{src.name}")
                    packed += 1
        core["zip"] = {"path": str(path), "media_packed": packed}
    return core


def verify_backup(payload: dict[str, Any], *, strict_media: bool = False) -> dict[str, Any]:
    """结构 + 校验和 + 边合法 + 媒体存在性。返回 findings，不抛异常。"""
    findings: list[dict[str, str]] = []
    if not isinstance(payload, dict) or payload.get("schema") != BACKUP_SCHEMA:
        return {
            "ok": False,
            "findings": [{"level": "error", "code": "schema", "message": "不是 S25 画布备份（schema 不匹配）"}],
            "stats": {},
        }
    core = {k: v for k, v in payload.items() if k not in ("checksum", "zip")}
    checksum = hashlib.sha256(_canonical(core).encode("utf-8")).hexdigest()
    if checksum != payload.get("checksum"):
        findings.append({"level": "error", "code": "checksum", "message": "备份内容与校验和不一致，可能被修改过"})
    nodes, edges = _graph_parts(payload.get("graph") or {})
    ids = [_node_id(n) for n in nodes]
    if len(ids) != len(set(ids)):
        findings.append({"level": "error", "code": "duplicate_node_id", "message": "节点 id 重复"})
    if any(not i for i in ids):
        findings.append({"level": "error", "code": "empty_node_id", "message": "存在空节点 id"})
    known = set(ids)
    types = {_node_id(n): str(n.get("node_type") or n.get("type") or "") for n in nodes}
    for edge in edges:
        src, dst = _edge_endpoints(edge)
        if src not in known or dst not in known:
            findings.append(
                {"level": "error", "code": "dangling_edge", "message": f"边 {src} → {dst} 的端点不存在"}
            )
            continue
        allowed = EDGE_MATRIX.get(types.get(src, ""), frozenset())
        dst_type = types.get(dst)
        if dst_type and dst_type not in allowed:
            findings.append(
                {
                    "level": "error",
                    "code": "illegal_edge",
                    "message": f"{types.get(src)} → {dst_type} 不是合法数据流",
                }
            )
    media = payload.get("media") or []
    missing = [m for m in media if not m.get("exists")]
    findings.extend(
        {
            "level": "error" if strict_media else "warning",
            "code": "media_missing",
            "message": f"{item.get('node_id')} 的 {item.get('path')} 不可用",
        }
        for item in missing
    )
    errors = [f for f in findings if f["level"] == "error"]
    return {
        "ok": not errors,
        "findings": findings,
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "media_total": len(media),
            "media_missing": len(missing),
        },
        "checksum_ok": checksum == payload.get("checksum"),
    }


def import_backup(
    payload: dict[str, Any],
    *,
    allow_checksum_mismatch: bool = False,
    strict_media: bool = False,
) -> dict[str, Any]:
    """校验后返回可直接保存的新画布（不写库；保存由 GraphService 做）。"""
    report = verify_backup(payload, strict_media=strict_media)
    if not report["ok"] and (
        not allow_checksum_mismatch
        or any(f["code"] != "checksum" for f in report["findings"] if f["level"] == "error")
    ):
        codes = ", ".join(f["code"] for f in report["findings"] if f["level"] == "error")
        raise ValueError(f"备份校验失败：{codes}")
    graph = payload.get("graph") or {}
    nodes, edges = _graph_parts(graph)
    return {
        "name": str(payload.get("name") or "导入的画布") + "（导入）",
        "description": f"由 S25 备份导入 · {payload.get('created_at') or ''}",
        "nodes": nodes,
        "edges": edges,
        "format": payload.get("format") or "",
        "style": payload.get("style") or "",
        "verify": report,
        "numbers": {"nodes": len(nodes), "edges": len(edges)},
    }
