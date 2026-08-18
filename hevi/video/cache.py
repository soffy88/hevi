"""material_cache.py - Pixabay/Coverr/Archive缓存实现"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
import hashlib
import json

from hevi.video.material_corpus import (
    search_pixabay_videos,
    search_coverr_videos,
    search_archive_videos,
)

# 缓存接口协议
class CacheProtocol(Protocol):
    def get(self, query: str) -> list[dict[str, Any]] | None:
        ...
    def put(self, results: list[dict[str, Any]], ttl: int) -> None:
        ...

# Pixabay缓存
class PixabayCache(CacheProtocol):
    def get(self, query: str) -> list[dict[str, Any]] | None:
        key = hashlib.sha256(query.encode()).hexdigest()
        return self._load_or_fetch(key, search_pixabay_videos)

    def put(self, results: list[dict[str, Any]], ttl: int) -> None:
        key = hashlib.sha256(query.encode()).hexdigest()
        self._save_to_disk(key, json.dumps(results), ttl)

# Coverr缓存
class CoverrCache(CacheProtocol):
    def get(self, query: str) -> list[dict[str, Any]] | None:
        key = hashlib.sha256(query.encode()).hexdigest()
        return self._load_or_fetch(key, search_coverr_videos)

    def put(self, results: list[dict[str, Any]], ttl: int) -> None:
        key = hashlib.sha256(query.encode()).hexdigest()
        self._save_to_disk(key, json.dumps(results), ttl)

# Archive缓存
class ArchiveCache(CacheProtocol):
    def get(self, query: str) -> list[dict[str, Any]] | None:
        key = hashlib.sha256(query.encode()).hexdigest()
        return self._load_or_fetch(key, search_archive_videos)

    def put(self, results: list[dict[str, Any]], ttl: int) -> None:
        key = hashlib.sha256(query.encode()).hexdigest()
        self._save_to_disk(key, json.dumps(results), ttl)


# 磁盘存储辅助
class CacheStorage:
    """管理所有缓存文件"""

    def __init__(self, cache_dir: Path):
        self.dir = cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def _save_to_disk(self, key: str, content: str, ttl: int):
        fd = self.dir / f"{key}.json"
        expires = (datetime.now() + timedelta(seconds=ttl)).isoformat()
        fd.write_json({
            "results": json.loads(content),
            "expires": expires
        })

    def _load_or_fetch(self, key: str, search_func: Callable):
        fd = self.dir / f"{key}.json"
        if fd.exists():
            data = fd.read_json()
            if datetime.fromisoformat(data["expires"]) > datetime.now():
                return data["results"]
        return search_func(key)

# 配置
CACHE_STORAGE = CacheStorage(Path(settings.cache_dir))
PIXABAY_CACHE = PixabayCache()
COVR_CACHE = CoverrCache()
ARCHIVE_CACHE = ArchiveCache()
"""

# 通过 settings.enable_pixabay_cache等在 core/config.py 中启用