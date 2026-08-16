"""replay trace —— 导演决策四阶段痕迹(3O 内化 Phase A,来源 dramaclaw replay_capture)。

dramaclaw 的 replay_capture 是比"事后 shot_verdict 分数"深一层的设计:
**每一次** beat 尝试都记录 trace_id + prompt 字节 + response 字节 + gate 判定 + 终态,
落库后**数月后可回放**,用于对比新旧导演策略、复现失败、沉淀训练数据。

本实现为 hevi 暂驻(待上游 `omodul.replay_trace`),JSON 文件持久化(与
hevi 既有 decision_trail 落盘同风格):
  begin_trace(...) → record_prompt_and_response(...) → record_gate(...) → finalize(...)
四阶段;任何阶段失败都不阻断主流水线(best-effort,与来源一致)。

3O 归属(待上游): `omodul.replay_trace`(四阶段握手 + 回放查询)。
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TraceHandle:
    """一次 beat 尝试的痕迹句柄,贯穿四阶段。"""

    trace_id: str
    source_run_id: str
    ref_type: str  # episode | shot | beat
    ref_id: str
    phase: str
    root: Path
    data: dict[str, Any] = field(default_factory=dict)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha12(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


class ReplayTraceError(Exception):
    """痕迹读写失败。"""


def begin_trace(
    root: Path,
    *,
    source_run_id: str,
    ref_type: str,
    ref_id: str,
    phase: str,
    extra: dict[str, Any] | None = None,
) -> TraceHandle:
    """阶段 1:开启一次尝试,写入初始元数据行。"""
    root = Path(root)
    try:
        root.mkdir(parents=True, exist_ok=True)
        trace_id = uuid.uuid4().hex[:16]
        handle = TraceHandle(
            trace_id=trace_id,
            source_run_id=source_run_id,
            ref_type=ref_type,
            ref_id=ref_id,
            phase=phase,
            root=root,
        )
        handle.data = {
            "trace_id": trace_id,
            "source_run_id": source_run_id,
            "ref_type": ref_type,
            "ref_id": ref_id,
            "phase": phase,
            "started_at": _utc_now(),
            "status": "in_progress",
            "prompt_version": None,
            "response_version": None,
            "gate_result": None,
            "failure_codes": [],
            "final_status": None,
        }
        if extra:
            handle.data["extra"] = extra
        _write_trace(root, trace_id, handle.data)
        return handle
    except OSError as e:
        raise ReplayTraceError(f"begin_trace failed: {e}") from e


def record_prompt_and_response(
    handle: TraceHandle, *, prompt: str, response: str
) -> None:
    """阶段 2:记录 prompt 字节 + response 字节(存版本指纹,原文落盘)。"""
    handle.data["prompt_version"] = _sha12(prompt)
    handle.data["response_version"] = _sha12(response)
    try:
        artifacts = handle.root / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / f"{handle.trace_id}.prompt.txt").write_text(
            prompt, encoding="utf-8"
        )
        (artifacts / f"{handle.trace_id}.response.txt").write_text(
            response, encoding="utf-8"
        )
        _write_trace(handle.root, handle.trace_id, handle.data)
    except OSError as e:
        raise ReplayTraceError(f"record_prompt_and_response failed: {e}") from e


def record_gate(
    handle: TraceHandle,
    *,
    gate_result: dict[str, Any],
    failure_codes: list[str] | None = None,
) -> None:
    """阶段 3:记录 gate 判定 + 观察到的失败码。"""
    handle.data["gate_result"] = gate_result
    if failure_codes:
        handle.data["failure_codes"] = list(dict.fromkeys(failure_codes))  # 去重保序
    _write_trace(handle.root, handle.trace_id, handle.data)


def finalize(handle: TraceHandle, *, final_status: str) -> None:
    """阶段 4:终态(accepted | reworked | abandoned)。"""
    handle.data["final_status"] = final_status
    handle.data["status"] = "done"
    handle.data["finished_at"] = _utc_now()
    _write_trace(handle.root, handle.trace_id, handle.data)


def _write_trace(root: Path, trace_id: str, data: dict[str, Any]) -> None:
    p = root / f"{trace_id}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_traces(root: Path) -> list[dict[str, Any]]:
    """回放:读取全部痕迹(按 started_at 升序)。"""
    root = Path(root)
    if not root.exists():
        return []
    traces: list[dict[str, Any]] = []
    for p in sorted(root.glob("*.json")):
        try:
            traces.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("replay_trace: skip unreadable %s: %s", p, e)
    traces.sort(key=lambda t: t.get("started_at", ""))
    return traces


def summary(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """痕迹概览:按 ref_type/phase 统计 + 失败码频次(供策略对比/趋势)。"""
    by_status: dict[str, int] = {}
    by_failure: dict[str, int] = {}
    for t in traces:
        status = t.get("final_status") or t.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        for code in t.get("failure_codes", []):
            by_failure[code] = by_failure.get(code, 0) + 1
    return {
        "total": len(traces),
        "by_status": by_status,
        "failure_frequency": dict(
            sorted(by_failure.items(), key=lambda item: item[1], reverse=True)
        ),
    }
