"""hevi.freezone.store — Freezone 状态持久化(FREEZONE_RESTART_RECOVERY)。

JSON 文件存储 graphs + candidates(含 owner/provenance)。进程重启后
FreezoneService 构造时 hydrate,保证跨重启的租户隔离与候选状态。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_DEFAULT_PATH = "data/freezone/state.json"


class FreezoneStateStore:
    """Freezone 图 + 候选的 JSON 文件存储。"""

    def __init__(self, path: str | Path | None = None) -> None:
        raw = path if path is not None else os.getenv("HEVI_FREEZONE_STATE_PATH", _DEFAULT_PATH)
        self.path = Path(raw)

    @classmethod
    def from_env(cls) -> FreezoneStateStore:
        return cls()

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"graphs": {}, "candidates": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"graphs": {}, "candidates": []}
        if not isinstance(data, dict):
            return {"graphs": {}, "candidates": []}
        graphs = data.get("graphs")
        candidates = data.get("candidates")
        return {
            "graphs": graphs if isinstance(graphs, dict) else {},
            "candidates": candidates if isinstance(candidates, list) else [],
        }

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self.path)
