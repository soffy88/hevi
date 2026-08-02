"""HeyGen head/tail avatar provider boundary (Explainer v8 Step 7)."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any


class HeyGenUnavailable(RuntimeError):
    pass


async def heygen_avatar_generate(
    *,
    text: str,
    presenter_id: str,
    output_path: Path,
    provider: Any = None,
) -> Path:
    """Generate one real avatar clip; no placeholder path is ever returned."""
    if provider is None:
        try:
            from oprim import heygen_avatar_generate as imported_provider
        except ImportError as exc:
            raise HeyGenUnavailable(
                "HeyGen 数字人不可用：当前 oprim 未安装 heygen_avatar_generate"
            ) from exc
        provider = imported_provider
    try:
        result = provider(
            text=text,
            presenter_id=presenter_id,
            output_path=output_path,
        )
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, dict):
            result = result.get("path") or result.get("video_path")
        path = Path(result or output_path)
        if not path.is_file() or path.stat().st_size == 0:
            raise HeyGenUnavailable(f"HeyGen 未产出视频文件: {path}")
        return path
    except HeyGenUnavailable:
        raise
    except Exception as exc:
        raise HeyGenUnavailable(f"HeyGen 生成失败: {exc}") from exc
