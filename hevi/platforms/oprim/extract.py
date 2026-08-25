"""oprim:平台内容解析提取原子。不得 import oskill / omodul。"""

from __future__ import annotations

import re
from typing import Any

from hevi.platforms.schemas import MonitorTarget

# ─────────── URL/链接解析 ───────────


def looks_like_platform_url(url: str) -> bool:
    """判断是否为已知平台的分享链接(抖音/小红书/快手/视频号)。"""
    text = url.strip().lower()
    if not text:
        return False
    if "douyin.com" in text or "iesdouyin.com" in text or "v.douyin.com" in text:
        return True
    if "xiaohongshu.com" in text or "xhslink" in text:
        return True
    if "kuaishou.com" in text or "ks.com" in text:
        return True
    return bool("video.weixin.qq.com" in text or "share.videostore.weixin.qq.com" in text)


def is_short_link(url: str) -> bool:
    """判断是否为平台短链(dy.xx, ks.xx 等)。"""
    text = url.strip().lower()
    if not text:
        return False
    if text.startswith(("dy", "aweme", "vg")):
        return True
    return bool(text.startswith(("ks", "short")))


def normalize_share_text(text: str) -> str:
    """规范化分享文本，提取纯链接。"""
    if not text:
        return ""
    m = re.search(r"(https?://[^\s]+)", text)
    if m:
        return m.group(1)
    return text


def strip_emoji(text: str) -> str:
    """移除表情符号(保留中文)。"""
    if not text:
        return ""
    result = []
    for ch in text:
        cp = ord(ch)
        if (0x20 <= cp <= 0x7E) or (0x4E00 <= cp <= 0x9FFF) or cp in (0x0020, 0x002E, 0x002C, 0x003A, 0x003B, 0x0021, 0x003F, 0x0022, 0x0027):
            result.append(ch)
    return "".join(result)


def extract_urls(text: str) -> list[str]:
    """从文本中提取所有 URL。"""
    if not text:
        return []
    pattern = re.compile(r"https?://[^\s)]+")
    return pattern.findall(text)


def extract_short_link(text: str) -> str | None:
    """从文本中提取短链(如 v.douyin.com/xxx)。"""
    if not text:
        return None
    m = re.search(r"(?:v\.douyin\.com|douyin\.com|iesdouyin\.com|xiaohongshu\.com|xhslink\.com|kuaishou\.com|ks\.com)/([A-Za-z0-9]+)", text)
    if m:
        return m.group(0)
    return None


def identify_platform(url: str) -> str | None:
    """从 URL 识别平台。"""
    if not url:
        return None
    text = url.lower()
    if "douyin.com" in text or "iesdouyin.com" in text or "v.douyin.com" in text:
        return "douyin"
    if "xiaohongshu.com" in text or "xhslink" in text:
        return "xhs"
    if "kuaishou.com" in text or "ks.com" in text:
        return "kuaishou"
    if "video.weixin.qq.com" in text or "share.videostore.weixin.qq.com" in text:
        return "shipinhao"
    return None


def extract_query_params(url: str) -> dict[str, str]:
    """提取 URL 查询参数。"""
    if not url:
        return {}
    from urllib.parse import parse_qs, urlparse
    parsed = urlparse(url)
    return {k: v[0] for k, v in parse_qs(parsed.query).items()}


def extract_aweme_id_from_url(url: str) -> str | None:
    """从抖音 URL 提取 aweme_id。"""
    if not url:
        return None
    params = extract_query_params(url)
    if "aweme_id" in params:
        return params["aweme_id"]
    m = re.search(r"/(\d+)(?:\?.*)?$", url)
    if m:
        return m.group(1)
    return None


def extract_sec_uid_from_url(url: str) -> str | None:
    """从抖音 URL 提取 sec_uid。"""
    if not url:
        return None
    params = extract_query_params(url)
    if "sec_uid" in params:
        return params["sec_uid"]
    return None


def extract_aweme_id(url: str) -> str | None:
    """从抖音分享链接中提取 aweme_id(作品 ID)。"""
    if not url:
        return None
    text = url.strip()
    m = re.search(r"aweme_id=(\d+)", text)
    if m:
        return m.group(1)
    m = re.search(r"/(\d+)(?:\?.*)?$", text)
    if m:
        return m.group(1)
    return None


def extract_note_id_from_url(url: str) -> str | None:
    """从小红书 URL 提取 note_id。"""
    if not url:
        return None
    params = extract_query_params(url)
    if "note_id" in params:
        return params["note_id"]
    return None


def extract_xsec_token_from_url(url: str) -> str | None:
    """从小红书 URL 提取 xsec_token。"""
    if not url:
        return None
    params = extract_query_params(url)
    if "xsec_token" in params:
        return params["xsec_token"]
    return None


def extract_ks_photo_id_from_url(url: str) -> str | None:
    """从快手 URL 提取 photo_id。"""
    if not url:
        return None
    params = extract_query_params(url)
    if "photo_id" in params:
        return params["photo_id"]
    return None


# ─── 内容卡片解析 ──────────────────


def parse_aweme_card(raw_json: dict[str, Any]) -> dict[str, Any]:
    """解析抖音作品卡片 JSON，提取关键字段。"""
    if not isinstance(raw_json, dict):
        return {}
    result: dict[str, Any] = {
        "aweme_id": raw_json.get("aweme_id") or "",
        "desc": raw_json.get("desc") or "",
        "author": raw_json.get("author", {}).get("nickname") or "",
        "author_id": raw_json.get("author", {}).get("uid") or "",
        "create_time": raw_json.get("create_time") or 0,
        "duration": raw_json.get("duration") or 0,
        "like_count": raw_json.get("statistics", {}).get("aweme_id", 0) or 0,
        "comment_count": raw_json.get("statistics", {}).get("comment_count", 0) or 0,
        "share_count": raw_json.get("share_count") or 0,
        "cover_url": raw_json.get("cover") or raw_json.get("pic_url") or "",
        "media_type": raw_json.get("media_type") or "video",
        "tags": raw_json.get("tags") or [],
    }
    music = raw_json.get("music") or {}
    result["music_name"] = music.get("music_name") or ""
    result["music_id"] = music.get("music_id") or ""
    video = raw_json.get("video") or {}
    result["width"] = video.get("width") or 0
    result["height"] = video.get("height") or 0
    return result


def parse_note_card(raw_json: dict[str, Any]) -> dict[str, Any]:
    """解析小红书笔记卡片 JSON，提取关键字段。"""
    if not isinstance(raw_json, dict):
        return {}
    result: dict[str, Any] = {
        "note_id": raw_json.get("note_id") or raw_json.get("id") or "",
        "title": raw_json.get("title") or raw_json.get("display_title") or "",
        "desc": raw_json.get("desc") or "",
        "cover": raw_json.get("cover") or "",
        "media_type": raw_json.get("type") or "normal",
        "tags": [],
    }
    images = raw_json.get("images_list") or raw_json.get("imageList") or []
    result["image_urls"] = []
    for img in images:
        if isinstance(img, dict):
            u = img.get("url") or img.get("url_default") or img.get("urlDefault") or ""
            if u:
                result["image_urls"].append(u)
    video = raw_json.get("video_info") or {}
    if isinstance(video, dict):
        result["video_type"] = video.get("type") or ""
        result["video_cover"] = video.get("cover") or ""
        result["video_duration"] = video.get("duration") or 0
        medias = video.get("medias") or []
        result["video_urls"] = []
        for m in medias:
            if isinstance(m, dict):
                u = m.get("url") or ""
                if u:
                    result["video_urls"].append(u)
    interact = raw_json.get("interact_info") or {}
    result["like_count"] = interact.get("liked_count") or 0
    result["comment_count"] = interact.get("comment_count") or 0
    result["view_count"] = interact.get("view_count") or 0
    return result


# ─── 监控目标解析 ──────────────────


def parse_keyword_target(keyword: str) -> MonitorTarget:
    """解析关键词监控目标。"""
    return MonitorTarget(
        platform="all",
        target_type="keyword",
        target_name=keyword.strip(),
    )


def parse_creator_target(creator_url: str) -> MonitorTarget:
    """解析创作者主页监控目标。"""
    sec_uid = extract_sec_uid_from_url(creator_url)
    note_id = extract_note_id_from_url(creator_url)

    if sec_uid:
        return MonitorTarget(
            platform="douyin",
            target_type="creator",
            target_name="creator_profile",
            target_id=sec_uid,
        )
    if note_id:
        return MonitorTarget(
            platform="xhs",
            target_type="work",
            target_name="note_profile",
            target_id=note_id,
        )
    return MonitorTarget(platform="unknown", target_type="creator", target_name="creator_profile")
