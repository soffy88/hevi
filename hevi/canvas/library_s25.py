"""S25：个人资产库（私有、按用户隔离、文件存储）。

画布产物（图/视频/音频/文本）可以一键收藏；收藏只记**引用**（路径/URL + 提示词
+ 来源节点），不复制大文件。删除收藏不影响画布与原文件。

存储：``output/canvas_s25/library/<sha256(user_id)[:16]>.json``，原子写，
每个用户最多 500 条（超出按时间淘汰最旧的非手工条目）。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from hevi.canvas.backup_s25 import _within_allowed

MAX_ITEMS = 500
_LOCK = threading.Lock()
KINDS = frozenset({"image", "video", "audio", "text", "other"})


def library_root() -> Path:
    return Path(os.environ.get("HEVI_CANVAS_LIBRARY_DIR", "output/canvas_s25/library"))


def _path(user_id: str) -> Path:
    digest = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:16]
    return library_root() / f"{digest}.json"


def _read(user_id: str) -> dict[str, Any]:
    path = _path(user_id)
    if not path.is_file():
        return {"schema": "hevi.canvas.library.v1", "items": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": "hevi.canvas.library.v1", "items": []}
    if not isinstance(data, dict):
        return {"schema": "hevi.canvas.library.v1", "items": []}
    data.setdefault("items", [])
    return data


def _write(user_id: str, data: dict[str, Any]) -> None:
    path = _path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _kind(node_type: str, path: str) -> str:
    if node_type in KINDS - {"other"}:
        return node_type
    suffix = Path(path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    if suffix in {".mp4", ".mov", ".webm", ".mkv"}:
        return "video"
    if suffix in {".mp3", ".wav", ".m4a", ".aac"}:
        return "audio"
    if suffix in {".txt", ".md", ".srt", ".json"}:
        return "text"
    return "other"


def add_item(
    user_id: str,
    *,
    title: str,
    path: str = "",
    url: str = "",
    kind: str = "",
    source_graph: str = "",
    source_node: str = "",
    prompt: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    title = str(title or "").strip()
    if not title:
        raise ValueError("收藏需要一个标题")
    path = str(path or "").strip()
    url = str(url or "").strip()
    if not path and not url:
        raise ValueError("需要 path 或 url 之一")
    if path:
        local = Path(path)
        if not local.is_absolute():
            local = Path(__file__).resolve().parents[2] / local
        if not _within_allowed(local):
            raise ValueError("资产路径必须在 data/output/assets 内")
        path = str(local)
    chosen_kind = kind if kind in KINDS else _kind("", path or url)
    item = {
        "id": uuid.uuid4().hex[:16],
        "title": title,
        "kind": chosen_kind,
        "path": path,
        "url": url,
        "source_graph": str(source_graph or ""),
        "source_node": str(source_node or ""),
        "prompt": str(prompt or ""),
        "tags": [str(t) for t in (tags or [])][:12],
        "created_at": time.time(),
    }
    with _LOCK:
        data = _read(user_id)
        items = [it for it in data["items"] if isinstance(it, dict)]
        items.append(item)
        if len(items) > MAX_ITEMS:
            items = sorted(items, key=lambda it: float(it.get("created_at") or 0))[-MAX_ITEMS:]
        data["items"] = items
        _write(user_id, data)
    return item


def list_items(user_id: str, *, kind: str | None = None, q: str = "") -> list[dict[str, Any]]:
    items = [it for it in _read(user_id)["items"] if isinstance(it, dict)]
    if kind:
        items = [it for it in items if it.get("kind") == kind]
    if q:
        needle = q.lower()
        items = [
            it
            for it in items
            if needle in str(it.get("title") or "").lower()
            or needle in str(it.get("prompt") or "").lower()
        ]
    items.sort(key=lambda it: float(it.get("created_at") or 0), reverse=True)
    return items


def remove_item(user_id: str, item_id: str) -> bool:
    with _LOCK:
        data = _read(user_id)
        before = len(data["items"])
        data["items"] = [it for it in data["items"] if str(it.get("id")) != str(item_id)]
        removed = len(data["items"]) != before
        if removed:
            _write(user_id, data)
    return removed
