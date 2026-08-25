"""material_cache.py - Pixabay/Coverr/Archive缓存实现"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast

from hevi.core.config import settings
from hevi.video.material_corpus import (
    search_archive_videos,
    search_coverr_videos,
    search_pixabay_videos,
)


# 缓存接口协议
class CacheProtocol(Protocol):
    def get(self, query: str) -> list[dict[str, Any]] | None:
        ...
    def put(self, results: list[dict[str, Any]], ttl: int) -> None:
        ...

# Pixabay缓存
class PixabayCache(CacheProtocol):
    def __init__(self, storage: CacheStorage) -> None:
        self.storage = storage

    def get(self, query: str) -> list[dict[str, Any]] | None:
        key = hashlib.sha256(query.encode()).hexdigest()
        return self.storage.load_or_fetch(key, search_pixabay_videos)

    def put(self, results: list[dict[str, Any]], ttl: int) -> None:
        key = hashlib.sha256(json.dumps(results, sort_keys=True).encode()).hexdigest()
        self.storage.save_to_disk(key, json.dumps(results), ttl)

# Coverr缓存
class CoverrCache(CacheProtocol):
    def __init__(self, storage: CacheStorage) -> None:
        self.storage = storage

    def get(self, query: str) -> list[dict[str, Any]] | None:
        key = hashlib.sha256(query.encode()).hexdigest()
        return self.storage.load_or_fetch(key, search_coverr_videos)

    def put(self, results: list[dict[str, Any]], ttl: int) -> None:
        key = hashlib.sha256(json.dumps(results, sort_keys=True).encode()).hexdigest()
        self.storage.save_to_disk(key, json.dumps(results), ttl)

# Archive缓存
class ArchiveCache(CacheProtocol):
    def __init__(self, storage: CacheStorage) -> None:
        self.storage = storage

    def get(self, query: str) -> list[dict[str, Any]] | None:
        key = hashlib.sha256(query.encode()).hexdigest()
        return self.storage.load_or_fetch(key, search_archive_videos)

    def put(self, results: list[dict[str, Any]], ttl: int) -> None:
        key = hashlib.sha256(json.dumps(results, sort_keys=True).encode()).hexdigest()
        self.storage.save_to_disk(key, json.dumps(results), ttl)


# 磁盘存储辅助
class CacheStorage:
    """管理所有缓存文件"""

    def __init__(self, cache_dir: Path):
        self.dir = cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def save_to_disk(self, key: str, content: str, ttl: int) -> None:
        fd = self.dir / f"{key}.json"
        expires = (datetime.now() + timedelta(seconds=ttl)).isoformat()
        fd.write_text(json.dumps({
            "results": json.loads(content),
            "expires": expires
        }), encoding="utf-8")

    def load_or_fetch(self, key: str, search_func: Callable[..., Any]) -> list[dict[str, Any]]:
        fd = self.dir / f"{key}.json"
        if fd.exists():
            data = json.loads(fd.read_text(encoding="utf-8"))
            if datetime.fromisoformat(data["expires"]) > datetime.now():
                return cast(list[dict[str, Any]], data["results"])
        return cast(list[dict[str, Any]], search_func(key))

# 配置
CACHE_STORAGE = CacheStorage(Path(getattr(settings, "material_cache_dir", "data/material_cache")))
PIXABAY_CACHE = PixabayCache(CACHE_STORAGE)
COVR_CACHE = CoverrCache(CACHE_STORAGE)
ARCHIVE_CACHE = ArchiveCache(CACHE_STORAGE)

# 通过 settings.enable_pixabay_cache等在 core/config.py 中启用
