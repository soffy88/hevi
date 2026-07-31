"""Cookie/Session 管理 — 浏览器自动化认证。

为每个平台维护 cookie 文件, 启动 Playwright 时注入。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

__all__ = ["CookieStore", "CookieStatus"]


class CookieStatus(str, Enum):
    valid = "valid"
    expired = "expired"
    missing = "missing"
    invalid = "invalid"


class CookieEntry(BaseModel):
    platform: str
    cookies_path: str
    status: CookieStatus = CookieStatus.missing
    last_validated: Optional[datetime] = None
    expires_hint: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CookieStore:
    """平台 Cookie 存储。

    Cookie 文件存放在 cookies_dir/{platform}.json,
    格式为 Playwright-compatible cookie array。
    """

    def __init__(self, cookies_dir: str = ".cookies"):
        self.cookies_dir = Path(cookies_dir)
        self.cookies_dir.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, CookieEntry] = {}
        self._load_all()

    def _cookie_path(self, platform: str) -> Path:
        return self.cookies_dir / f"{platform}.json"

    def _load_all(self) -> None:
        for f in self.cookies_dir.glob("*.json"):
            platform = f.stem
            self._entries[platform] = CookieEntry(
                platform=platform,
                cookies_path=str(f),
                status=CookieStatus.missing,
            )

    def save_cookies(self, platform: str, cookies: list[dict]) -> Path:
        """保存 Playwright 格式的 cookie 数组。"""
        path = self._cookie_path(platform)
        path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
        self._entries[platform] = CookieEntry(
            platform=platform,
            cookies_path=str(path),
            status=CookieStatus.valid,
            last_validated=datetime.utcnow(),
        )
        logger.info("Saved %d cookies for %s → %s", len(cookies), platform, path)
        return path

    def load_cookies(self, platform: str) -> list[dict] | None:
        """加载cookie, 不存在则返回 None。"""
        path = self._cookie_path(platform)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load cookies for %s: %s", platform, e)
            return None

    def get_status(self, platform: str) -> CookieStatus:
        entry = self._entries.get(platform)
        if not entry:
            return CookieStatus.missing
        path = Path(entry.cookies_path)
        if not path.exists():
            return CookieStatus.missing
        if entry.last_validated and entry.expires_hint and datetime.utcnow() > entry.expires_hint:
            return CookieStatus.expired
        return entry.status if entry.status != CookieStatus.missing else CookieStatus.valid

    def validate(self, platform: str) -> CookieStatus:
        """验证 cookie 文件是否存在且格式正确。"""
        cookies = self.load_cookies(platform)
        if cookies is None:
            status = CookieStatus.missing
        elif not cookies:
            status = CookieStatus.invalid
        else:
            status = CookieStatus.valid

        if platform in self._entries:
            self._entries[platform].status = status
            self._entries[platform].last_validated = datetime.utcnow()
        return status

    def list_platforms(self) -> list[str]:
        return [f.stem for f in self.cookies_dir.glob("*.json")]

    def clear(self, platform: str) -> bool:
        path = self._cookie_path(platform)
        if path.exists():
            path.unlink()
        self._entries.pop(platform, None)
        logger.info("Cleared cookies for %s", platform)
        return True


async def ensure_browser_session(platform: str, store: CookieStore) -> dict:
    """启动 Playwright 浏览器并注入 cookie (stub)。"""
    cookies = store.load_cookies(platform)
    if cookies is None:
        raise RuntimeError(f"No cookies for {platform}. Run login flow first.")
    logger.info("Launching browser session for %s with %d cookies", platform, len(cookies))
    return {"platform": platform, "cookies_loaded": len(cookies), "status": "stub"}


async def refresh_session(platform: str, store: CookieStore) -> bool:
    """尝试刷新 session。"""
    status = store.validate(platform)
    if status == CookieStatus.valid:
        return True
    logger.warning("Session refresh needed for %s (status: %s)", platform, status)
    return False
