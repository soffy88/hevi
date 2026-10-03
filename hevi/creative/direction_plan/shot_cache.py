"""A9:以内容哈希为键的 per-shot 缓存(early cutoff 的存储基础)。

键 = 意图哈希 + 计划哈希 + 生成参数(不含时间戳/随机种子等易变字段)。
命中即复用产物;未命中 = MISS,由调用方生成。绝不用时间或路径做键。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "a9-1"


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      default=str)


def shot_cache_key(*, intent: Any, plan: Any, generation: dict[str, Any] | None = None) -> str:
    payload = {"schema": SCHEMA_VERSION, "intent": intent, "plan": plan,
               "generation": generation or {}}
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


@dataclass(frozen=True)
class CacheEntry:
    key: str
    artifact_path: str
    artifact_hash: str
    provider: str = ""
    created_at: str = ""


@dataclass
class ShotCache:
    root: Path
    entries: dict[str, CacheEntry] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def lookup(self, key: str) -> CacheEntry | None:
        entry = self.entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        if not Path(entry.artifact_path).is_file():
            del self.entries[key]  # 产物被清理 = 失效,不返回悬空引用
            self.misses += 1
            return None
        self.hits += 1
        return entry

    def store(self, entry: CacheEntry) -> CacheEntry:
        self.entries[entry.key] = entry
        (self.root / f"{entry.key}.json").write_text(
            _canonical({"key": entry.key, "artifact_path": entry.artifact_path,
                        "artifact_hash": entry.artifact_hash, "provider": entry.provider,
                        "created_at": entry.created_at}) + "\n",
            encoding="utf-8")
        return entry

    def load(self) -> int:
        count = 0
        for path in sorted(self.root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.entries[str(payload["key"])] = CacheEntry(
                key=str(payload["key"]), artifact_path=str(payload["artifact_path"]),
                artifact_hash=str(payload["artifact_hash"]), provider=str(payload.get("provider", "")),
                created_at=str(payload.get("created_at", "")))
            count += 1
        return count