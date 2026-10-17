"""搜索素材源 —— 从本地素材库检索真实物体/场景图。

优先级:
  1. 本地素材库(data/、assets/ 里已有的图片): 零依赖, 离线可用。
  2. Pexels/Pixabay 远程检索: 需要 PEXELS_API_KEY/PIXABAY_API_KEY,
     且网络可达。失败静默降级到本地。

设计:
  - 纯函数层可单测, 无网络; IO 层走 httpx, 失败降级不阻断。
  - 不新增付费 API 调用(ARCHIFY_TASK.md §1)。
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@dataclass(frozen=True)
class SearchHit:
    """本地素材命中条目。"""

    path: str
    sha256: str
    bytes: int
    width: int = 0
    height: int = 0
    aspect: str = ""
    source: str = "local"
    query: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "width": self.width,
            "height": self.height,
            "aspect": self.aspect,
            "source": self.source,
            "query": self.query,
        }


def _aspect_ratio(w: int, h: int) -> str:
    if w and h:
        r = w / h
        if r > 1.15:
            return "16:9"
        if 1.0 / r > 1.15:
            return "9:16"
        return "1:1"
    return ""


def scan_local_images(
    root: Path | None = None,
    *,
    max_results: int = 50,
) -> list[SearchHit]:
    """扫描仓库本地素材目录, 返回图片列表。

    扫描 data/ 和 assets/ 两个目录(不含 assets/audio)。
    """
    root = root or REPO_ROOT
    scan_dirs = [
        root / "data",
        root / "assets",
    ]
    hits: list[SearchHit] = []
    for base in scan_dirs:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
                continue
            if "audio" in path.parts:
                continue
            try:
                data = path.read_bytes()
                from PIL import Image

                with Image.open(path) as img:
                    w, h = img.size
            except Exception as exc:  # noqa: BLE001 - 单个文件损坏不阻断扫描
                logger.warning("跳过无法读取的图片 %s: %s", path, exc)
                continue
            hits.append(
                SearchHit(
                    path=str(path),
                    sha256=hashlib.sha256(data).hexdigest(),
                    bytes=len(data),
                    width=w,
                    height=h,
                    aspect=_aspect_ratio(w, h),
                    source="local",
                )
            )
            if len(hits) >= max_results:
                break
        if len(hits) >= max_results:
            break
    return hits


def pick_for_shot(
    shot_text: str,
    *,
    hits: list[SearchHit] | None = None,
    aspect: str = "9:16",
) -> SearchHit | None:
    """从命中里挑最合适的: 优先匹配 aspect, 否则返回第一个。"""
    if hits is None:
        hits = scan_local_images()
    if not hits:
        return None
    target_ratio = 9 / 16 if aspect == "9:16" else 16 / 9
    def score(h: SearchHit) -> float:
        if not h.width or not h.height:
            return 0.0
        r = h.width / h.height
        return 1.0 / (1.0 + abs(r - target_ratio))
    return max(hits, key=score)


def ensure_local_copy(
    hit: SearchHit,
    dest_dir: Path,
    *,
    stem: str = "search",
) -> Path:
    """把命中的素材复制到输出目录, 返回本地路径。"""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    src = Path(hit.path)
    dest = dest_dir / f"{stem}{src.suffix.lower()}"
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest
