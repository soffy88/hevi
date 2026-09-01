"""Accumulate lint/gate failures. Write errors never block the main flow.

Pure helpers do not touch the filesystem. append_gate_log is best-effort IO.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KNOWN_RULES: tuple[str, ...] = (
    "L1",
    "L2",
    "L3",
    "L4",
    "H1",
    "H2",
    "C1",
    "R1",
    "R2",
    "B1",
    "D1",
    "P1",
    "P2",
)

_DEFAULT_PATH = Path("data/workspace/.gates.jsonl")


def _rule_of(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("rule") or "")
    return str(getattr(item, "rule", "") or "")


def _message_of(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("message") or "")
    return str(getattr(item, "message", "") or "")


def _shot_ids_of(item: Any) -> list[str]:
    raw = item.get("shot_ids") if isinstance(item, dict) else getattr(item, "shot_ids", [])
    return [str(x) for x in (raw or [])]


def gate_log_entries(
    *,
    source: str,
    findings: list[Any],
    extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """One run row + one row per finding. Pure."""
    rows: list[dict[str, Any]] = [
        {
            "kind": "run",
            "source": source,
            "gates": len(findings),
            "failed": sum(1 for item in findings if _rule_of(item)),
            **(extra or {}),
        }
    ]
    rows.extend(
        {
            "kind": "fail",
            "source": source,
            "rule": _rule_of(item),
            "detail": _message_of(item),
            "shot_ids": _shot_ids_of(item),
        }
        for item in findings
    )
    return rows


def summarize_gate_log(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Which rules fire most / never / what the details look like."""
    fails = [e for e in entries if e.get("kind") == "fail" and e.get("rule")]
    counts = Counter(str(e.get("rule")) for e in fails)
    loudest = [{"rule": rule, "count": n} for rule, n in counts.most_common()]
    silent = [rule for rule in KNOWN_RULES if counts.get(rule, 0) == 0]
    return {
        "runs": sum(1 for e in entries if e.get("kind") == "run"),
        "failures": len(fails),
        "by_rule": dict(counts),
        "loudest": loudest,
        "silent": silent,
        "details": [e.get("detail") for e in fails[:20] if e.get("detail")],
    }


def gate_log_enabled() -> bool:
    return (os.getenv("HEVI_GATE_LOG") or "1").strip() not in {"0", "false", "no"}


def gate_log_path() -> Path:
    override = (os.getenv("HEVI_GATE_LOG_PATH") or "").strip()
    return Path(override) if override else _DEFAULT_PATH


def append_gate_log(path: Path | None, entries: list[dict[str, Any]]) -> None:
    """Best-effort. Missing dir / permission / disk full → skip."""
    if not entries or not gate_log_enabled():
        return
    dest = path or gate_log_path()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        stamped = datetime.now(UTC).isoformat()
        with dest.open("a", encoding="utf-8") as handle:
            for row in entries:
                payload = {"ts": stamped, **row}
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.debug("gate log skip: %s", exc)
