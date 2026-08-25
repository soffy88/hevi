"""oskill:账号管理技能。组合 oprim.login + oprim.extract。

对应 CreatorHub 的 app/browser/manager.py + app/profiles.py 逻辑。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hevi.platforms.oprim.login import (
    has_a1,
    platform_needs_creator_state,
    resolve_browser_mode,
    validate_storage_state,
)
from hevi.platforms.schemas import AccountProfile, PlatformName

logger = logging.getLogger(__name__)


# ─── 账号状态管理 ───


class AccountManager:
    """账号持久化管理器。

    管理账号的存储状态、Profile 目录、代理绑定。
    """

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.profiles_dir = self.base_dir / "profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

    def profile_dir(self, account_id: int, platform: str) -> Path:
        """账号的 Profile 目录。"""
        return self.profiles_dir / platform / f"account_{account_id}"

    def storage_state_path(self, account_id: int, platform: str, creator: bool = False) -> Path:
        """Storage State 文件路径。"""
        suffix = "creator" if creator else "read"
        return self.profile_dir(account_id, platform) / f"storage_{suffix}.json"

    def load_read_state(self, account_id: int, platform: str) -> str | None:
        """加载读取态。"""
        path = self.storage_state_path(account_id, platform, creator=False)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def load_creator_state(self, account_id: int, platform: str) -> str | None:
        """加载创作者态。"""
        path = self.storage_state_path(account_id, platform, creator=True)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def save_read_state(self, account_id: int, platform: str, state_json: str) -> None:
        """保存读取态。"""
        path = self.storage_state_path(account_id, platform, creator=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(state_json, encoding="utf-8")

    def save_creator_state(self, account_id: int, platform: str, state_json: str) -> None:
        """保存创作者态。"""
        path = self.storage_state_path(account_id, platform, creator=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(state_json, encoding="utf-8")

    def has_valid_read_state(self, account_id: int, platform: str) -> bool:
        """检查是否有有效的读取态。"""
        state = self.load_read_state(account_id, platform)
        if not state:
            return False
        result = validate_storage_state(state)
        return bool(result.get("valid")) and int(result.get("cookies_count", 0)) > 0

    def has_valid_creator_state(self, account_id: int, platform: str) -> bool:
        """检查是否有有效的创作者态。"""
        state = self.load_creator_state(account_id, platform)
        if not state:
            return False
        result = validate_storage_state(state)
        return bool(result.get("valid")) and int(result.get("cookies_count", 0)) > 0 and (
            has_a1(result.get("cookie_str", "")) if platform == PlatformName.XIAOHONGSHU.value else True
        )

    def get_account_profile(self, account_id: int, platform: str) -> AccountProfile | None:
        """从存储状态构建账号档案。"""
        read_state = self.load_read_state(account_id, platform)
        creator_state = self.load_creator_state(account_id, platform)

        if not read_state and not creator_state:
            return None

        profile = AccountProfile(
            id=account_id,
            platform=platform,
            has_read_state=bool(read_state),
            has_creator_state=bool(creator_state),
        )

        # 从读取态提取基本信息
        if read_state:
            try:
                data = json.loads(read_state)
                cookies = data.get("cookies") or []
                profile.cookies_count = len(cookies)
            except Exception:
                pass

        return profile

    def delete_account(self, account_id: int, platform: str) -> bool:
        """删除账号所有数据。"""
        import shutil
        profile_dir = self.profile_dir(account_id, platform)
        if profile_dir.exists():
            shutil.rmtree(profile_dir)
            return True
        return False

    def list_accounts(self, platform: str | None = None) -> list[dict[str, Any]]:
        """列出所有账号。"""
        accounts: list[dict[str, Any]] = []
        platforms = [platform] if platform else [p.value for p in PlatformName]
        for p in platforms:
            pdir = self.profiles_dir / p
            if not pdir.exists():
                continue
            for item in pdir.iterdir():
                if item.is_dir() and item.name.startswith("account_"):
                    account_id = int(item.name.split("_")[1])
                    prof = self.get_account_profile(account_id, p)
                    if prof:
                        accounts.append(prof.model_dump())
        return accounts


# ─── 独立函数接口 ───


def load_account_state(base_dir: Path, account_id: int, platform: str) -> dict[str, str]:
    """加载账号完整状态。"""
    mgr = AccountManager(base_dir)
    return {
        "read_state": mgr.load_read_state(account_id, platform) or "",
        "creator_state": mgr.load_creator_state(account_id, platform) or "",
    }


def save_account_state(base_dir: Path, account_id: int, platform: str,
                        read_state: str = "", creator_state: str = "") -> None:
    """保存账号完整状态。"""
    mgr = AccountManager(base_dir)
    if read_state:
        mgr.save_read_state(account_id, platform, read_state)
    if creator_state:
        mgr.save_creator_state(account_id, platform, creator_state)


def verify_account(base_dir: Path, account_id: int, platform: str) -> dict[str, Any]:
    """验证账号登录态有效性。"""
    mgr = AccountManager(base_dir)
    has_read = mgr.has_valid_read_state(account_id, platform)
    has_creator = mgr.has_valid_creator_state(account_id, platform)

    return {
        "account_id": account_id,
        "platform": platform,
        "has_read_state": has_read,
        "has_creator_state": has_creator,
        "can_publish": has_read or has_creator,
        "browser_mode": resolve_browser_mode("auto", has_chrome=True),
        "needs_creator": platform_needs_creator_state(platform),
    }
