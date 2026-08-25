"""oprim:链接解析与分享文本规范化原子。不得 import oskill / omodul。"""

from __future__ import annotations

import re

# ─── 分享文本规范化 ───


def normalize_share_text(text: str) -> str:
    """规范化分享文本，提取纯链接。"""
    if not text:
        return ""
    # 去除首尾空白
    text = text.strip()
    # 提取第一个 http(s):// 链接
    m = re.search(r"(https?://[^\s]+)", text)
    if m:
        return m.group(1)
    return text


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


# ─── 平台识别 ───


def identify_platform(url: str) -> str | None:
    """从 URL 识别平台。

    返回: douyin | xhs | kuaishou | shipinhao | None
    """
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


# ─── 参数提取 ───


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
    # 短链格式
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