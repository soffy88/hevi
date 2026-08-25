"""oprim:抖音请求签名原子。不得 import oskill / omodul。"""

from __future__ import annotations

import importlib.util
from typing import Any

# ─── ABogus 签名 ───


def abogus_available() -> bool:
    """检查是否可用 abogus 签名模块。"""
    return importlib.util.find_spec("abogus") is not None


def sign_request(params: dict[str, Any], user_agent: str) -> str:
    """为抖音请求生成 abogus 签名。

    依赖外部 abogus 库，对齐 CreatorHub 的 abogus.py。
    """
    if not abogus_available():
        # 返回空签名，上层处理降级
        return ""
    try:
        from abogus import douyin  # type: ignore

        ab = douyin.AbOgUs(params, user_agent)
        ab.get_value()
        return str(ab.result)
    except Exception:
        return ""


# ─── 其他签名方法(预留) ───


def sign_xhs_request(params: dict[str, Any], cookie: str) -> str:
    """小红书 xsec_token 签名(预留)。"""
    # CreatorHub 中小红笔记口需要 xsec_token
    # 此处为原子层，具体实现留给外部服务
    return ""
