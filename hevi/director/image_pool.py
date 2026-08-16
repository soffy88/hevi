"""图片池索引 —— 生成图统一索引 + 按 beat 检索/去重(3O 内化 Round 3d,来源 dramaclaw pool_indexer)。

dramaclaw 的 pool_indexer 管理所有生成图片(1x1/3x3/5x5 网格等)的统一索引与检索;
grid_splitter 负责把网格切成单格。hevi 的 sketch_storyboard 已有"候选→评分→选择",
缺**池级索引**(内容哈希去重 + 按 beat 作用域检索)。本模块补池层,选择复用 sketch 闸门。

3O 归属(待上游): `oprim.image_pool_index`(哈希/索引/检索,纯算法)。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PoolImage:
    """池中一张图。"""

    path: Path
    pool_id: str
    content_hash: str
    beat_id: str = ""
    grid: str = ""  # "1x1" | "3x3" | "5x5" …
    row: int = -1
    col: int = -1
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "pool_id": self.pool_id,
            "content_hash": self.content_hash,
            "beat_id": self.beat_id,
            "grid": self.grid,
            "row": self.row,
            "col": self.col,
            "metadata": self.metadata,
        }


def content_hash(path: Path) -> str:
    """图内容哈希(sha256 前 16 hex;不依赖图像库,读字节即可)。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


class ImagePool:
    """图片池:登记(按内容哈希去重)→ 按 beat 检索。"""

    def __init__(self, images: list[PoolImage] | None = None) -> None:
        self._images: list[PoolImage] = list(images or [])

    def add(self, image: PoolImage) -> bool:
        """登记;内容哈希重复返回 False(不重复入池)。"""
        if any(existing.content_hash == image.content_hash for existing in self._images):
            return False
        self._images.append(image)
        return True

    def by_beat(self, beat_id: str) -> list[PoolImage]:
        return [i for i in self._images if i.beat_id == beat_id]

    def by_grid(self, grid: str) -> list[PoolImage]:
        return [i for i in self._images if i.grid == grid]

    @property
    def images(self) -> list[PoolImage]:
        return list(self._images)

    def dedupe_count(self) -> int:
        """池中内容哈希去重后的数量 vs 原始数量差异。"""
        return len(self._images) - len({i.content_hash for i in self._images})

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps([i.to_dict() for i in self._images], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> ImagePool:
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8"))
        return cls(
            [
                PoolImage(
                    path=Path(item["path"]),
                    pool_id=item["pool_id"],
                    content_hash=item["content_hash"],
                    beat_id=item.get("beat_id", ""),
                    grid=item.get("grid", ""),
                    row=item.get("row", -1),
                    col=item.get("col", -1),
                    metadata=dict(item.get("metadata", {})),
                )
                for item in raw
            ]
        )


def pick_best_for_beat(
    pool: ImagePool, beat_id: str, *, coverage: dict[str, float] | None = None
) -> PoolImage | None:
    """按 beat 检索后选最优:优先覆盖度高者(缺省按入池顺序取最新)。"""
    candidates = pool.by_beat(beat_id)
    if not candidates:
        return None
    if not coverage:
        return candidates[-1]
    return max(candidates, key=lambda i: coverage.get(i.pool_id, 0.0))
