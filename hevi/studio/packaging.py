"""成片后的矩阵包装:分平台改标题/封面/标签,再按账号排队。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PLATFORM_PACK: dict[str, dict[str, Any]] = {
    "douyin": {
        "title_max": 30,
        "cover": "9:16 大字钩子",
        "tags": ("盐税", "历史", "短视频"),
        "suffix": " #抖音",
    },
    "kuaishou": {
        "title_max": 28,
        "cover": "9:16 近景人脸",
        "tags": ("历史现场", "涨知识"),
        "suffix": "",
    },
    "xiaohongshu": {
        "title_max": 20,
        "cover": "3:4 封面笔记",
        "tags": ("历史", "纪录片", "笔记"),
        "suffix": "",
    },
    "shipinhao": {
        "title_max": 32,
        "cover": "16:9 标题卡",
        "tags": ("历史", "官方号"),
        "suffix": "",
    },
    "bilibili": {
        "title_max": 80,
        "cover": "16:9 分区封面",
        "tags": ("历史", "人文", "纪录片"),
        "suffix": "【完整】",
    },
    "toutiao": {
        "title_max": 36,
        "cover": "16:9 资讯图",
        "tags": ("时事", "历史"),
        "suffix": "",
    },
}


@dataclass
class PackVariant:
    platform: str
    title: str
    description: str
    tags: list[str]
    cover_hint: str
    account: str = ""
    media_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PackQueue:
    variants: list[PackVariant] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"variants": [item.to_dict() for item in self.variants], "count": len(self.variants)}


def pack_variant(
    topic: str,
    platform: str,
    *,
    description: str = "",
    account: str = "",
    media_path: str = "",
) -> PackVariant:
    spec = PLATFORM_PACK.get(platform) or {
        "title_max": 40,
        "cover": "16:9",
        "tags": (topic[:8],),
        "suffix": "",
    }
    title = (topic or "未命名")[: int(spec["title_max"])] + str(spec.get("suffix") or "")
    body = description or topic
    return PackVariant(
        platform=platform,
        title=title.strip(),
        description=body,
        tags=[str(tag) for tag in spec.get("tags") or ()],
        cover_hint=str(spec.get("cover") or ""),
        account=account,
        media_path=media_path,
    )


def pack_queue(
    topic: str,
    platforms: list[str],
    *,
    description: str = "",
    accounts: dict[str, list[str]] | None = None,
    media_path: str = "",
) -> PackQueue:
    """platforms × 账号。无账号时每平台一条空账号工单。"""
    variants: list[PackVariant] = []
    table = accounts or {}
    for platform in platforms:
        names = table.get(platform) or [""]
        variants.extend(
            pack_variant(
                topic,
                platform,
                description=description,
                account=name,
                media_path=media_path,
            )
            for name in names
        )
    return PackQueue(variants=variants)


def write_pack_tickets(queue: PackQueue, dest_dir: Path) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for index, variant in enumerate(queue.variants):
        slug = variant.account or "default"
        path = dest_dir / f"{index:02d}-{variant.platform}-{slug}.publish.json"
        payload = json.dumps(variant.to_dict(), ensure_ascii=False, indent=2)
        path.write_text(payload, encoding="utf-8")
        written.append(path)
    return written
