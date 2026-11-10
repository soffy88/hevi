"""出品形式埋点 —— 只追加 JSONL，无迁移、无新依赖。

事件（S21）：
* ``format_selected``    用户点了某个形式（或自动）
* ``auto_changed``       自动路由结果被用户改选（记录从哪个形式改到哪个）
* ``storyboard_edited``  分镜确认前改单格（detail.count 为改动次数）
* ``render_started``     确认后开始渲染
* ``render_completed``   成片完成（detail.status）
* ``gated_click``        点了“即将开放”的形式

管理后台通过 ``metrics()`` 聚合：每个形式的选择次数、自动被改选次数、
分镜修改次数、完成率。
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
DEFAULT_PATH = "output/analytics/format_events.jsonl"
_ALLOWED = {
    "format_selected",
    "auto_changed",
    "storyboard_edited",
    "render_started",
    "render_completed",
    "gated_click",
}


def events_path() -> Path:
    return Path(os.environ.get("HEVI_FORMAT_EVENTS_PATH", DEFAULT_PATH))


def record_event(
    event: str,
    *,
    user_id: str | None = None,
    format_id: str = "",
    style: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    if event not in _ALLOWED:
        raise ValueError(f"unknown format event: {event}")
    path = events_path()
    row = {
        "ts": time.time(),
        "event": event,
        "user_id": str(user_id or ""),
        "format": format_id,
        "style": style,
        "detail": detail or {},
    }
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_events() -> list[dict[str, Any]]:
    path = events_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def metrics() -> dict[str, Any]:
    rows = read_events()
    per_format: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "selected": 0,
            "auto_changed": 0,
            "storyboard_edits": 0,
            "render_started": 0,
            "render_completed": 0,
            "gated_click": 0,
        }
    )
    for row in rows:
        fmt = str(row.get("format") or "unknown")
        bucket = per_format[fmt]
        event = row.get("event")
        if event == "format_selected":
            bucket["selected"] += 1
        elif event == "auto_changed":
            bucket["auto_changed"] += 1
            detail = row.get("detail") or {}
            if detail.get("from"):
                per_format[str(detail["from"])]["auto_changed"] += 1
        elif event == "storyboard_edited":
            bucket["storyboard_edits"] += int((row.get("detail") or {}).get("count") or 1)
        elif event == "render_started":
            bucket["render_started"] += 1
        elif event == "render_completed":
            bucket["render_completed"] += 1
        elif event == "gated_click":
            bucket["gated_click"] += 1

    formats: list[dict[str, Any]] = []
    for fmt, bucket in sorted(per_format.items()):
        started = bucket["render_started"]
        completed = bucket["render_completed"]
        formats.append(
            {
                "format": fmt,
                **bucket,
                "completion_rate": round(completed / started, 3) if started else None,
            }
        )
    totals = {
        "selections": sum(b["selected"] for b in per_format.values()),
        "auto_changed": sum(b["auto_changed"] for b in per_format.values()),
        "storyboard_edits": sum(b["storyboard_edits"] for b in per_format.values()),
        "render_started": sum(b["render_started"] for b in per_format.values()),
        "render_completed": sum(b["render_completed"] for b in per_format.values()),
        "gated_clicks": sum(b["gated_click"] for b in per_format.values()),
    }
    totals["completion_rate"] = (
        round(totals["render_completed"] / totals["render_started"], 3)
        if totals["render_started"]
        else None
    )
    return {"total_events": len(rows), "totals": totals, "formats": formats}
