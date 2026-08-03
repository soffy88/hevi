"""异步研究任务 + 结果本地文件缓存(根治长视频研究 524 超时 + 断点续传)。

研究不再是同步 HTTP:POST /api/explainer/research 立刻派任务并落盘一个
"processing"状态信封,后台跑完覆盖成 "ready" + 完整确稿数据(或 "failed"
+ 错误)。前端凭 session_id 轮询 GET /research/{session_id} 拿到信封,
Cloudflare 永远碰不到 100s 超时。原有的"确稿数据持久化、刷新恢复"语义
保留:ready 状态的信封 payload 即完整 ExplainerResearchResponse。

设计:
- 缓存文件即任务状态信封:`{"status","error","payload","topic_or_url"}`。
- 按 session_id 分文件存储,原子写入(先写 .tmp 再 os.replace),杜绝半截
  JSON 损坏导致读不出状态。
- 目录可用环境变量 EXPLAINER_CACHE_DIR 覆盖(容器内挂载持久卷,本地默认
  data/explainer_cache)。
- 读取时任何解析失败都返回 None(不抛异常),绝不把缓存故障升级成接口故障。
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Literal

_DEFAULT_CACHE_DIR = Path("data/explainer_cache")

# 只允许 uuid / 短横线十六进制,防 session_id 目录穿越(../ 等)。
_SESSION_ID_RE = re.compile(r"^[0-9a-fA-F-]{1,64}$")

# 研究任务状态:pending/processing(已派发在建)→ ready(确稿数据齐)→ failed。
ResearchStatus = Literal["pending", "processing", "ready", "failed"]


def cache_dir() -> Path:
    """缓存根目录(环境变量可覆盖,便于测试与容器挂载)。"""
    return Path(os.environ.get("EXPLAINER_CACHE_DIR", str(_DEFAULT_CACHE_DIR)))


def ensure_clean_session_id(session_id: str) -> str:
    """会话 id 清洗:非法/空值直接重新生成 uuid,绝不让脏 id 落进文件路径。"""
    if _SESSION_ID_RE.fullmatch(session_id or ""):
        return session_id
    return str(uuid.uuid4())


def save_research_cache(
    session_id: str,
    *,
    status: ResearchStatus = "ready",
    payload: dict[str, Any] | None = None,
    error: str | None = None,
    topic_or_url: str = "",
) -> Path:
    """原子写入研究任务状态信封到本地 JSON 缓存。

    status=ready 时 payload 为完整 ExplainerResearchResponse(随信封一起持久化)。
    status=processing/failed 时 payload 可空,仅记录状态与错误供前端轮询。
    """
    safe_id = ensure_clean_session_id(session_id)
    directory = cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    cache_file = directory / f"{safe_id}.json"
    tmp_file = cache_file.with_suffix(".tmp")
    envelope = {
        "status": status,
        "error": error,
        "payload": payload,
        "topic_or_url": topic_or_url,
        "session_id": safe_id,
    }
    tmp_file.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp_file, cache_file)
    return cache_file


def load_research_cache(session_id: str) -> dict[str, Any] | None:
    """读取任务状态信封;不存在 / 损坏 / 非对象一律返回 None,不抛异常。"""
    safe_id = ensure_clean_session_id(session_id)
    cache_file = cache_dir() / f"{safe_id}.json"
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError, ValueError):
        return None


__all__ = [
    "cache_dir",
    "ensure_clean_session_id",
    "load_research_cache",
    "save_research_cache",
]