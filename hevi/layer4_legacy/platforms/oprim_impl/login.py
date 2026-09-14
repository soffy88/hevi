"""oprim:登录态与 Cookie 处理原子。不得 import oskill / omodul。"""

from __future__ import annotations

import json
from typing import Any

from hevi.platforms.schemas import PlatformName

# ─── Cookie 与 Storage State 处理 ───


def cookie_str_from_state(state_json: str) -> str:
    """从 Playwright/Patchright storage_state JSON 中提取 Cookie 字符串。

    对应 CreatorHub 的 cookie_str_from_state。
    """
    if not state_json:
        return ""
    try:
        data = json.loads(state_json)
        cookies = data.get("cookies") or []
        parts = []
        for c in cookies:
            name = c.get("name") or ""
            value = c.get("value") or ""
            if name and value:
                parts.append(f"{name}={value}")
        return "; ".join(parts)
    except Exception:
        return ""


def has_a1(cookie_str: str) -> bool:
    """判断 Cookie 中是否包含小红书的 a1 字段(登录态必要字段)。

    对应 CreatorHub 的 has_a1。
    """
    if not cookie_str:
        return False
    # a1 通常是 a1=xxx; 的形式
    import re
    return bool(re.search(r"(^|;\s*)a1\s*=", cookie_str))


def is_creator_cookie(cookie_str: str) -> bool:
    """判断 Cookie 是否包含创作者平台所需的特定字段。

    对应 CreatorHub 的 has_creator_cookies。
    """
    if not cookie_str:
        return False
    import re
    # 小红书创作者平台需要 xsec_token, a1, web_session 等
    return bool(re.search(r"(xsec_token|web_session)", cookie_str, re.IGNORECASE))


def validate_storage_state(state_json: str) -> dict[str, Any]:
    """校验 storage_state 是否有效。

    返回: {"valid": bool, "cookies_count": int, "has_a1": bool, "is_creator": bool, "errors": []}
    """
    if not state_json:
        return {"valid": False, "cookies_count": 0, "has_a1": False, "is_creator": False, "errors": ["empty"]}

    try:
        data = json.loads(state_json)
        cookies = data.get("cookies") or []
        cookie_str = cookie_str_from_state(state_json)
        return {
            "valid": len(cookies) > 0,
            "cookies_count": len(cookies),
            "has_a1": has_a1(cookie_str),
            "is_creator": is_creator_cookie(cookie_str),
            "errors": [],
        }
    except Exception as e:
        return {"valid": False, "cookies_count": 0, "has_a1": False, "is_creator": False, "errors": [str(e)]}


# ─── 平台特定登录判定 ───


def platform_needs_creator_state(platform: str) -> bool:
    """判断平台是否需要创作者态进行发布。"""
    return platform in (PlatformName.DOUYIN.value, PlatformName.KUAISHOU.value, PlatformName.SHIPINHAO.value)


def platform_supports_keyword_collection(platform: str) -> bool:
    """判断平台是否支持关键词批量采集。"""
    # 当前仅抖音支持
    return platform == PlatformName.DOUYIN.value


# ─── Browser Mode 判定 ───


def resolve_browser_mode(config_mode: str, has_chrome: bool) -> str:
    """解析浏览器模式。

    对应 CreatorHub 的 xhs_browser_mode 解析:
    - auto: 有 Chrome 走 CDP，无则回退 Patchright
    - cdp: 强制 CDP，无 Chrome 报错
    - patchright: 强制 Patchright
    """
    if config_mode == "patchright":
        return "patchright"
    if config_mode == "cdp":
        return "cdp" if has_chrome else "error"
    # auto
    return "cdp" if has_chrome else "patchright"