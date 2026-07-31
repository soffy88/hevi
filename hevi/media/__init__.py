"""Media OS — 统一媒体管理层。

对标 HyperFrames /media-use skill。

核心:任何媒体需求(BGM/SFX/图片/图标/logo/语音/色彩分级/LUT)
统一解析 → 冻结本地文件 → manifest 追踪。

用法:
    from hevi.media import MediaRegistry

    registry = MediaRegistry(cache_dir=Path("output/media"))

    # 注册媒体
    bgm = registry.register("bgm_tense", Path("assets/bgm/tense.mp3"), category="audio")
    logo = registry.register("logo", Path("assets/logo.png"), category="image")

    # 查询
    tense_bgm = registry.resolve("bgm_tense")
    all_audio = registry.list(category="audio")

    # 持久化
    registry.save_manifest(Path("output/media_manifest.json"))

对标: HyperFrames /media-use skill
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

__all__ = [
    "MediaRegistry",
    "MediaAsset",
    "MediaCategory",
]


class MediaCategory:
    """媒体类别。"""
    AUDIO = "audio"       # BGM, SFX, 语音
    IMAGE = "image"       # 图片, 图标, logo
    VIDEO = "video"       # 视频片段
    LUT = "lut"           # 色彩分级 LUT
    FONT = "font"         # 字体文件
    OTHER = "other"


@dataclass
class MediaAsset:
    """媒体资产。"""
    id: str
    path: Path
    category: str
    name: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["path"] = str(self.path)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MediaAsset":
        data = dict(data)
        data["path"] = Path(data["path"])
        return cls(**data)


class MediaRegistry:
    """统一媒体注册表。"""

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir
        self._assets: dict[str, MediaAsset] = {}

    def register(
        self,
        asset_id: str,
        path: Path,
        *,
        category: str = MediaCategory.OTHER,
        name: str = "",
        description: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        copy_to_cache: bool = False,
    ) -> MediaAsset:
        """注册媒体资产。

        Args:
            asset_id: 资产标识(唯一)
            path: 资产路径
            category: 类别(audio/image/video/lut/font)
            name: 显示名称
            description: 描述
            tags: 标签列表
            metadata: 额外元数据
            copy_to_cache: 是否复制到 cache_dir(冻结)

        Returns:
            MediaAsset
        """
        if copy_to_cache and self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path = self.cache_dir / f"{asset_id}{path.suffix}"
            shutil.copy2(path, cache_path)
            path = cache_path

        asset = MediaAsset(
            id=asset_id,
            path=path,
            category=category,
            name=name or asset_id,
            description=description,
            tags=tags or [],
            metadata=metadata or {},
        )
        self._assets[asset_id] = asset
        return asset

    def resolve(self, asset_id: str) -> MediaAsset | None:
        """解析资产。"""
        return self._assets.get(asset_id)

    def list(self, *, category: str | None = None) -> list[MediaAsset]:
        """列出资产(可按类别过滤)。"""
        if category is None:
            return list(self._assets.values())
        return [a for a in self._assets.values() if a.category == category]

    def unregister(self, asset_id: str) -> bool:
        """注销资产。"""
        if asset_id in self._assets:
            del self._assets[asset_id]
            return True
        return False

    def save_manifest(self, output_path: Path) -> None:
        """保存 manifest(JSON)。"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "assets": [a.to_dict() for a in self._assets.values()],
        }
        output_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_manifest(self, manifest_path: Path) -> None:
        """加载 manifest。"""
        if not manifest_path.exists():
            return
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in data.get("assets", []):
            asset = MediaAsset.from_dict(item)
            self._assets[asset.id] = asset

    def __len__(self) -> int:
        return len(self._assets)

    def __contains__(self, asset_id: str) -> bool:
        return asset_id in self._assets
