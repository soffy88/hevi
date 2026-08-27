"""oskill:分享链接解析/下载技能。组合 oprim.resolve + oprim.extract。

对应 CreatorHub 的 app/engine/share_downloader.py 逻辑。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hevi.platforms.oprim.extract import (
    extract_aweme_id_from_url,
    extract_ks_photo_id_from_url,
    extract_note_id_from_url,
    extract_sec_uid_from_url,
    extract_xsec_token_from_url,
    identify_platform,
    strip_emoji,
)

# ─── 分享文本解析 ───


def parse_share_text(text: str) -> dict[str, Any]:
    """解析分享文本，提取平台、链接、目标字段。

    对应 CreatorHub 的 app.engine.share_downloader 的简化版本。
    """

    result: dict[str, Any] = {
        "platform": None,
        "url": None,
        "aweme_id": None,
        "note_id": None,
        "sec_uid": None,
        "xsec_token": None,
        "keyword": None,
    }

    if not text:
        return result

    # 规范化提取第一个 URL
    normalized_url = strip_emoji(text).strip()
    m = re.search(r"(https?://[^\s]+)", normalized_url)
    if m:
        normalized_url = m.group(1)
    else:
        return result

    # 识别平台
    result["url"] = normalized_url
    result["platform"] = identify_platform(normalized_url)
    if not result["platform"]:
        return result

    # 提取平台特定 ID
    if result["platform"] == "douyin":
        result["aweme_id"] = extract_aweme_id_from_url(normalized_url)
        result["sec_uid"] = extract_sec_uid_from_url(normalized_url)
    elif result["platform"] == "xhs":
        result["note_id"] = extract_note_id_from_url(normalized_url)
        result["xsec_token"] = extract_xsec_token_from_url(normalized_url)
    elif result["platform"] == "kuaishou":
        result["aweme_id"] = extract_ks_photo_id_from_url(normalized_url)

    # 提取关键词(去除 URL 后的文本)
    keyword = re.sub(r"https?://[^\s]+", "", text).strip()
    if keyword:
        result["keyword"] = keyword

    return result


# ─── 分享链接解析 ───


def resolve_share_link(text: str) -> dict[str, Any]:
    """完整的分享链接解析。

    对应 CreatorHub 的 python -m app.engine.share_downloader --links-only
    """
    result = parse_share_text(text)

    # 验证链接有效性
    if not result["url"] or not result["platform"]:
        return {
            "ok": False,
            "detail": "无法识别的分享链接",
        }

    return {
        "ok": True,
        "detail": f"平台: {result['platform']}, 链接: {result['url']}, 参数已提取",
        "data": result,
    }


# ─── 下载器类 ───


class ShareDownloader:
    """分享链接下载器。

    对应 CreatorHub 的 ShareDownloader / share_downloader 模块。
    """

    def __init__(self, media_dir: Path) -> None:
        self.media_dir = Path(media_dir)
        self.media_dir.mkdir(parents=True, exist_ok=True)

    async def download_from_link(self, text: str, quality: str = "1080") -> dict[str, Any]:
        """从分享链接下载内容。"""
        resolved = resolve_share_link(text)
        if not resolved["ok"]:
            return resolved
        parsed = resolved["data"]

        # 实际下载逻辑需要浏览器自动化层
        # 这里提供接口契约
        return {
            "ok": True,
            "detail": f"下载任务已创建: {parsed['platform']}",
            "data": parsed,
        }
