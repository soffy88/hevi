"""S22 成本账本 —— 只追加 JSONL，无迁移、无新依赖。

账本记录“时间 / 镜头 / 模型 / 秒数 / 金额”，与 S21 的 format_events 分开：
format_events 管用户行为，这里管钱与镜头路线。管理后台按需聚合。

行格式（``kind`` 区分）：

    {"ts": 1762..., "kind": "quote", "plan_id": "...", "format": "live_drama",
     "shot": 1, "route": "generation", "model": "wan_2_7", "seconds": 5,
     "cny": 3.6, "elapsed_s": 0, "status": "quoted"}

金额单位人民币元，模型单价来自 ``hevi.cost.pricing_table``（美元→人民币汇率由
``HEVI_USD_CNY`` 决定，默认 7.2）。
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
DEFAULT_PATH = "output/analytics/craft_ledger.jsonl"


def ledger_path() -> Path:
    return Path(os.environ.get("HEVI_CRAFT_LEDGER_PATH", DEFAULT_PATH))


def record(entry: dict[str, Any]) -> dict[str, Any]:
    """追加一行账本；缺省字段补齐，时间由服务端决定。"""
    row = {
        "ts": time.time(),
        "kind": str(entry.get("kind") or "quote"),
        "plan_id": str(entry.get("plan_id") or ""),
        "format": str(entry.get("format") or ""),
        "style": str(entry.get("style") or ""),
        "shot": int(entry.get("shot") or 0),
        "route": str(entry.get("route") or ""),
        "model": str(entry.get("model") or ""),
        "seconds": round(float(entry.get("seconds") or 0), 3),
        "cny": round(float(entry.get("cny") or 0), 4),
        "elapsed_s": round(float(entry.get("elapsed_s") or 0), 3),
        "status": str(entry.get("status") or "quoted"),
        "note": str(entry.get("note") or ""),
    }
    path = ledger_path()
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def record_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """把一个 craft plan 的逐镜报价写进账本（同一 plan_id 一组）。"""
    plan_id = str(plan.get("plan_id") or "")
    budget = plan.get("budget") or {}
    overhead = float(budget.get("overhead_cny") or 0)
    rows: list[dict[str, Any]] = [
        record(
            {
                "kind": "quote",
                "plan_id": plan_id,
                "format": plan.get("format"),
                "style": plan.get("style"),
                "shot": shot.get("index"),
                "route": shot.get("route"),
                "model": shot.get("model"),
                "seconds": shot.get("duration_s"),
                "cny": shot.get("cost_cny"),
                "elapsed_s": shot.get("render_s_est"),
                "status": "quoted",
            }
        )
        for shot in plan.get("shots") or []
    ]
    if overhead:
        rows.append(
            record(
                {
                    "kind": "quote",
                    "plan_id": plan_id,
                    "format": plan.get("format"),
                    "style": plan.get("style"),
                    "shot": 0,
                    "route": "overhead",
                    "model": "assembly",
                    "seconds": budget.get("total_seconds") or 0,
                    "cny": overhead,
                    "elapsed_s": 0,
                    "status": "quoted",
                    "note": "配音/字幕/合成",
                }
            )
        )
    return rows


def read_rows(limit: int = 500) -> list[dict[str, Any]]:
    path = ledger_path()
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
    return rows[-max(1, limit):]


def summary(limit: int = 1000) -> dict[str, Any]:
    rows = read_rows(limit=limit)
    per_route: dict[str, dict[str, float]] = defaultdict(
        lambda: {"shots": 0.0, "seconds": 0.0, "cny": 0.0, "elapsed_s": 0.0}
    )
    per_model: dict[str, dict[str, float]] = defaultdict(
        lambda: {"shots": 0.0, "seconds": 0.0, "cny": 0.0}
    )
    total_cny = 0.0
    total_seconds = 0.0
    plans: set[str] = set()
    for row in rows:
        route = str(row.get("route") or "unknown")
        model = str(row.get("model") or "unknown")
        bucket = per_route[route]
        bucket["shots"] += 1
        bucket["seconds"] += float(row.get("seconds") or 0)
        bucket["cny"] += float(row.get("cny") or 0)
        bucket["elapsed_s"] += float(row.get("elapsed_s") or 0)
        mbucket = per_model[model]
        mbucket["shots"] += 1
        mbucket["seconds"] += float(row.get("seconds") or 0)
        mbucket["cny"] += float(row.get("cny") or 0)
        total_cny += float(row.get("cny") or 0)
        total_seconds += float(row.get("seconds") or 0)
        if row.get("plan_id"):
            plans.add(str(row["plan_id"]))

    def _clean(data: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
        out = []
        for key, value in sorted(data.items()):
            out.append(
                {
                    "key": key,
                    "shots": int(value["shots"]),
                    "seconds": round(value["seconds"], 2),
                    "cny": round(value["cny"], 2),
                    **(
                        {"elapsed_s": round(value["elapsed_s"], 2)}
                        if "elapsed_s" in value
                        else {}
                    ),
                }
            )
        return out

    return {
        "rows": len(rows),
        "plans": len(plans),
        "total_seconds": round(total_seconds, 2),
        "total_cny": round(total_cny, 2),
        "by_route": _clean(per_route),
        "by_model": _clean(per_model),
        "recent": rows[-50:],
    }
