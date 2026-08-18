"""hevi.publishers —— 跨平台一键发布骨架(3O omodul 风格, 差距 B2)。

对标 MoneyPrinterTurbo 的 TikTok/Instagram/YouTube Shorts 自动上传, 补 hevi 差距:
此前成片止步于本地/URL, 无发布闭环。

设计(务实骨架, 可插拔 + 空实现):
  - `Publisher` 抽象基类: name / platforms / available()(凭据探测) /
    publish()(上传主流程)。
  - 空实现(TikTok/IG/YT): OAuth 凭据未配置 → available() 恒 False,
    publish() 返回 status="skipped"(不 raise, 满足 omodul 返回契约)。
  - 真实 OAuth 上传播放留接入方(需平台开发者账号/审核); 本骨架保证
    「检测到凭据即启用」的接入点已就位, 不会把发布链路卡死。
  - `publish_to_platform()` 一体入口: 选平台 → 探测 → 调用 → 记 decision trail。

3O 归属: omodul 边界(≥2 步: 探测 + 上传), 失败不 raise, status 返回。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 平台名常量
PLATFORM_TIKTOK = "tiktok"
PLATFORM_INSTAGRAM = "instagram"
PLATFORM_YOUTUBE = "youtube"


@dataclass
class PublishResult:
    """一次发布尝试的结果。status: published | skipped | failed。"""

    status: str
    platform: str
    external_id: str | None = None
    url: str | None = None
    reason: str = ""
    trail: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "platform": self.platform,
            "external_id": self.external_id,
            "url": self.url,
            "reason": self.reason,
            "trail": self.trail,
        }


class Publisher(ABC):
    """发布器抽象。子类实现 available() 与 publish()。

    - available(): 凭据探测, 缺凭据返回 False(发布器登记但不可用)。
    - publish(): 上传主流程, 失败**不 raise**, 返回 status="failed" 或
      "skipped"(附 reason), 满足 omodul 返回契约。
    """

    name: str = ""
    platforms: tuple[str, ...] = ()

    @abstractmethod
    def available(self) -> bool:
        """当前环境是否具备该平台发布凭据。"""

    @abstractmethod
    async def publish(
        self,
        media_path: Path,
        *,
        title: str = "",
        description: str = "",
        tags: list[str] | None = None,
        **meta: Any,
    ) -> PublishResult:
        """发布单个成片。media_path 不存在 → status="failed"(不 raise)。"""


# ---------------------------------------------------------------------------
# 空实现(骨架): 凭据未配置 → 恒不可用, publish 返回 skipped
# ---------------------------------------------------------------------------


class TikTokPublisher(Publisher):
    name = "tiktok"
    platforms = (PLATFORM_TIKTOK,)

    def available(self) -> bool:
        return False  # OAuth 凭据未接入(需 TikTok 开发者账号)

    async def publish(self, media_path: Path, **meta: Any) -> PublishResult:
        return PublishResult(
            status="skipped",
            platform=self.name,
            reason="tiktok publisher is a stub: OAuth credentials not configured",
            trail=[{"step": "detect_credentials", "ok": False}],
        )


class InstagramPublisher(Publisher):
    name = "instagram"
    platforms = (PLATFORM_INSTAGRAM,)

    def available(self) -> bool:
        return False  # OAuth 凭据未接入(需 Meta for Developers)

    async def publish(self, media_path: Path, **meta: Any) -> PublishResult:
        return PublishResult(
            status="skipped",
            platform=self.name,
            reason="instagram publisher is a stub: OAuth credentials not configured",
            trail=[{"step": "detect_credentials", "ok": False}],
        )


class YouTubePublisher(Publisher):
    name = "youtube"
    platforms = (PLATFORM_YOUTUBE,)

    def available(self) -> bool:
        return False  # OAuth 凭据未接入(需 Google Cloud OAuth)

    async def publish(self, media_path: Path, **meta: Any) -> PublishResult:
        return PublishResult(
            status="skipped",
            platform=self.name,
            reason="youtube publisher is a stub: OAuth credentials not configured",
            trail=[{"step": "detect_credentials", "ok": False}],
        )


# ---------------------------------------------------------------------------
# 注册表 + 一体入口
# ---------------------------------------------------------------------------

_PUBLISHERS: dict[str, Publisher] = {}


def register_publisher(pub: Publisher) -> None:
    """注册发布器(按 name; 重复覆盖, 便于宿主注入真实实现)。"""
    _PUBLISHERS[pub.name] = pub
    for platform in pub.platforms:
        _PUBLISHERS.setdefault(platform, pub)


def list_publishers() -> list[dict[str, Any]]:
    """列出全部发布器(含可用性探测结果)。"""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, pub in _PUBLISHERS.items():
        if name in seen:
            continue
        seen.add(name)
        out.append(
            {
                "name": name,
                "platforms": list(pub.platforms),
                "available": pub.available(),
                "type": type(pub).__name__,
            }
        )
    return out


def get_publisher(name: str) -> Publisher | None:
    return _PUBLISHERS.get(name)


async def publish_to_platform(
    platform: str,
    media_path: Path,
    *,
    title: str = "",
    description: str = "",
    tags: list[str] | None = None,
    **meta: Any,
) -> PublishResult:
    """一体发布入口: 选平台 → 探测 → 调用 → 结果(失败不 raise)。

    平台不存在/不可用/媒体缺失 → status="skipped" 或 "failed" + reason,
    满足 omodul 返回契约(调用方永不因发布抛异常)。
    """
    pub = get_publisher(platform)
    if pub is None:
        return PublishResult(
            status="failed",
            platform=platform,
            reason=f"unknown publisher: {platform}",
        )
    if not pub.available():
        return PublishResult(
            status="skipped",
            platform=platform,
            reason=f"{platform} publisher unavailable (credentials missing)",
            trail=[{"step": "detect_credentials", "ok": False}],
        )
    if not media_path.exists():
        return PublishResult(
            status="failed",
            platform=platform,
            reason=f"media not found: {media_path}",
        )
    try:
        return await pub.publish(
            media_path, title=title, description=description, tags=tags or [], **meta
        )
    except Exception as exc:
        logger.exception("publish to %s failed", platform)
        return PublishResult(
            status="failed", platform=platform, reason=f"exception: {exc}"
        )


def _register_defaults() -> None:
    for pub in (TikTokPublisher(), InstagramPublisher(), YouTubePublisher()):
        register_publisher(pub)


_register_defaults()

__all__ = [
    "PLATFORM_INSTAGRAM",
    "PLATFORM_TIKTOK",
    "PLATFORM_YOUTUBE",
    "InstagramPublisher",
    "PublishResult",
    "Publisher",
    "TikTokPublisher",
    "YouTubePublisher",
    "get_publisher",
    "list_publishers",
    "publish_to_platform",
    "register_publisher",
]
