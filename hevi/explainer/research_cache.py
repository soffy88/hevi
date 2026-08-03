"""调研结果本地文件缓存(断点续传)。

阶段一 POST /api/explainer/research 完成时,把生成的 3 版脚本与调研数据
(含 v9 Hook 策略矩阵)强行落盘;即使后半段装配/渲染报了天大的错,确稿与
调研数据依然在磁盘上,刷新页面直接读取缓存恢复,**绝对不需要重新跑研究**。

设计:
- 按 session_id 分文件存储,原子写入(先写 .tmp 再 os.replace),杜绝半截
  JSON 损坏导致读不出缓存;
- 目录可用环境变量 EXPLAINER_CACHE_DIR 覆盖(容器内挂载持久卷,本地默认
  data/explainer_cache);
- 读取时任何解析失败都返回 None(不抛异常),绝不把缓存故障升级成接口故障。
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

_DEFAULT_CACHE_DIR = Path("data/explainer_cache")

# 只允许 uuid / 短横线十六进制,防 session_id 目录穿越(../ 等)。
_SESSION_ID_RE = re.compile(r"^[0-9a-fA-F-]{1,64}$")


def cache_dir() -> Path:
    """缓存根目录(环境变量可覆盖,便于测试与容器挂载)。"""
    return Path(os.environ.get("EXPLAINER_CACHE_DIR", str(_DEFAULT_CACHE_DIR)))


def ensure_clean_session_id(session_id: str) -> str:
    """会话 id 清洗:非法/空值直接重新生成 uuid,绝不让脏 id 落进文件路径。"""
    if _SESSION_ID_RE.fullmatch(session_id or ""):
        return session_id
    return str(uuid.uuid4())


def save_research_cache(session_id: str, data: dict[str, Any]) -> Path:
    """强行将调研与脚本数据持久化到本地 JSON 缓存(原子写入)。"""
    safe_id = ensure_clean_session_id(session_id)
    directory = cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    cache_file = directory / f"{safe_id}.json"
    tmp_file = cache_file.with_suffix(".tmp")
    tmp_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp_file, cache_file)
    return cache_file


def load_research_cache(session_id: str) -> dict[str, Any] | None:
    """读取缓存,断点续传;不存在 / 损坏 / 非对象一律返回 None,不抛异常。"""
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
