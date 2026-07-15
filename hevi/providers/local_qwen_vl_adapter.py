"""Local Qwen-VL mllm adapter — routes visual-judging calls to a local Qwen2.5-VL
via ollama's OpenAI-compatible endpoint, **keeping the image_paths** that the
text-only local_qwen_adapter drops.

3O manifest §C2: omodul does `mllm = providers.get("mllm") or llm`; without a real
VLM the frame-consistency check (oskill.mllm_frame_consistency_check) collapses to
"pick the first variant". This adapter is the `mllm` provider that makes double-variant
selection actually see pixels.

Call convention (mirrors LocalQwenAdapter / AsyncDashScopeAdapter):
  sync:  result = mllm(messages=..., image_paths=[...]); result.get("content")
  async: result = await mllm(messages=..., image_paths=[...]); result.get("content")
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import functools
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

# Reuse endpoint + timeout from the text adapter so both honor the same env config.
from hevi.providers.local_qwen_adapter import _OLLAMA_BASE, _TIMEOUT

logger = logging.getLogger(__name__)

# 与文本 qwen 分开的 VL 模型。默认 3b(~3.2GB):本机 3080 与外部进程(stratum/aii ~4.6GB)
# 共享,仅 ~5.6GB 空余;7b(6GB)会 CPU 卸载并使视觉编码器 OOM。VRAM 宽裕时可 env 切 7b。
# keep_alive:0 调用后即卸载,给 Wan2GP/vibevoice 让显存。
_OLLAMA_VL_MODEL = os.getenv("OLLAMA_VL_MODEL", "qwen2.5vl:3b")


_VIDEO_EXTS = {"mp4", "mov", "webm", "mkv", "avi"}


def _video_frame_to_temp_png(path: Path) -> Path | None:
    """视频直出 provider(happyhorse 等)产的候选是 .mp4,不是静帧——2026-07-12 真实
    撞见:此前 `_b64_data_uri` 不管扩展名直接把原始字节 base64、贴上
    "data:image/mp4"这种假 mime,ollama 正确地把这当非法图片数据秒拒(400)。
    先用 ffmpeg 抽第一帧存临时 PNG,再走正常的图片编码路径。"""
    import subprocess
    import tempfile

    out = Path(tempfile.gettempdir()) / f"vl_frame_{path.stem}_{os.getpid()}.png"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", "0", "-i", str(path), "-frames:v", "1", str(out)],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return out
    except Exception as e:  # noqa: BLE001 — 抽帧失败不阻断,退化为跳过这张图
        logger.warning("VL adapter: 视频抽帧失败 %s: %s", path, e)
        return None


def _b64_data_uri(path: Path) -> str | None:
    """Read an image (or video — first frame gets extracted) file → data: URI
    (OpenAI-compat image_url). None if unreadable."""
    src = path
    tmp_frame: Path | None = None
    if path.suffix.lower().lstrip(".") in _VIDEO_EXTS:
        tmp_frame = _video_frame_to_temp_png(path)
        if tmp_frame is None:
            return None
        src = tmp_frame
    try:
        raw = src.read_bytes()
    except OSError as e:
        logger.warning("VL adapter: cannot read image %s: %s", src, e)
        return None
    finally:
        if tmp_frame is not None:
            with contextlib.suppress(OSError):
                tmp_frame.unlink()
    ext = src.suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    return f"data:image/{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _attach_images(messages: list[dict[str, Any]], image_paths: list[str]) -> list[dict[str, Any]]:
    """Attach images to the last user message as OpenAI-compat image_url content parts.

    Qwen-VL via ollama /v1/chat/completions accepts content as a list of parts:
      [{"type":"text","text":...}, {"type":"image_url","image_url":{"url":"data:..."}}]
    """
    parts = [
        {"type": "image_url", "image_url": {"url": uri}}
        for p in image_paths
        if (uri := _b64_data_uri(Path(p))) is not None
    ]
    if not parts:
        return messages
    out = [dict(m) for m in messages]
    # 找最后一条 user 消息挂图;没有则新增一条。
    for m in reversed(out):
        if m.get("role") == "user":
            text = m.get("content", "")
            m["content"] = [{"type": "text", "text": text if isinstance(text, str) else ""}, *parts]
            return out
    out.append({"role": "user", "content": parts})
    return out


def _extract_json_content(raw: str) -> str:
    """剥 <think>、去 ```json 围栏、抽第一个 JSON 对象/数组 → 交调用方 json.loads。

    consistency check 做 `json.loads(content).get("score")`;Qwen-VL 常把 JSON 裹在
    markdown 围栏或散文里(直接返回原文会解析失败 → 分数恒 0 → 退化选第一个)。
    抽不到 JSON 时返回剥 think 后的原文。
    """
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if not text:
        m = re.search(r"<think>(.*?)</think>", raw, flags=re.DOTALL)
        if m:
            text = m.group(1).strip()
    clean = text.strip()
    if clean.startswith("```"):
        m = re.search(r"```(?:json)?\n?(.*?)\n?```", clean, re.DOTALL)
        if m:
            clean = m.group(1).strip()
    m = re.search(r"(\{.*\}|\[.*\])", clean, re.DOTALL)
    return m.group(1) if m else text


def _call_vl(**kwargs: Any) -> dict[str, Any]:
    """Sync HTTP call to local Qwen-VL. Safe to run in a thread (not on event loop)."""
    image_paths = kwargs.get("image_paths") or []
    kwargs.pop("result_format", None)
    messages = kwargs.get("messages", [])
    if image_paths:
        messages = _attach_images(messages, [str(p) for p in image_paths])
    payload = {
        "model": _OLLAMA_VL_MODEL,
        "messages": messages,
        "max_tokens": kwargs.get("max_tokens", 512),  # 审片只需短 JSON 分数
        "temperature": kwargs.get("temperature", 0.2),  # 判定要稳,低温
        "stream": False,
    }

    # 与 local_qwen_adapter 同款:对 500/502/503 与连接错误指数退避;4xx 立即抛。
    last_exc: Exception | None = None
    data: dict[str, Any] = {}
    for _attempt in range(4):
        try:
            r = httpx.post(f"{_OLLAMA_BASE}/v1/chat/completions", json=payload, timeout=_TIMEOUT)
            if r.status_code in (500, 502, 503):
                raise httpx.HTTPStatusError(
                    f"ollama-vl transient {r.status_code}", request=r.request, response=r
                )
            r.raise_for_status()
            data = r.json()
            break
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            resp = getattr(exc, "response", None)
            if resp is not None and resp.status_code not in (500, 502, 503):
                raise
            last_exc = exc
            if _attempt < 3:
                time.sleep(1.5 * (_attempt + 1))
                logger.warning("ollama-vl transient error, retry %d/3: %s", _attempt + 1, exc)
    else:
        raise last_exc if last_exc else RuntimeError("ollama-vl call failed")

    # 每次调用后立即卸载,给 Wan2GP/vibevoice 让出显存(与文本 qwen 同策略)。
    with contextlib.suppress(Exception):
        httpx.post(
            f"{_OLLAMA_BASE}/api/generate",
            json={"model": _OLLAMA_VL_MODEL, "keep_alive": 0},
            timeout=5.0,
        )

    oa_choices = data.get("choices", [])
    content = ""
    if oa_choices:
        content = _extract_json_content(oa_choices[0].get("message", {}).get("content", "") or "")
    return {
        "output": {"choices": [{"message": c.get("message", {})} for c in oa_choices]},
        "usage": data.get("usage", {}),
        "content": content,
    }


class LocalQwenVLAdapter:
    """Sync-callable + awaitable VL adapter — mirrors LocalQwenAdapter, keeps images."""

    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs
        self._resp: dict[str, Any] | None = None

    def _ensure_resp(self) -> dict[str, Any]:
        if self._resp is None:
            self._resp = _call_vl(**self._kwargs)
        return self._resp

    def get(self, key: str, default: Any = None) -> Any:
        return self._ensure_resp().get(key, default)

    def __await__(self) -> Any:
        async def _run() -> dict[str, Any]:
            if self._resp is not None:
                return self._resp
            fn = functools.partial(_call_vl, **self._kwargs)
            self._resp = await asyncio.to_thread(fn)
            return self._resp

        return _run().__await__()


def local_qwen_vl_adapter(**kwargs: Any) -> LocalQwenVLAdapter:
    """Factory (the `mllm` provider) — sync-callable + awaitable, image-aware."""
    return LocalQwenVLAdapter(**kwargs)


def vl_model_available() -> bool:
    """True if the configured VL model is present in ollama (gate injection on this)."""
    try:
        r = httpx.get(f"{_OLLAMA_BASE}/api/tags", timeout=5.0)
        r.raise_for_status()
        names = {m.get("name", "") for m in r.json().get("models", [])}
    except Exception as e:
        logger.warning("VL adapter: ollama tags probe failed: %s", e)
        return False
    # 允许 tag 省略(qwen2.5vl 匹配 qwen2.5vl:7b)。
    base = _OLLAMA_VL_MODEL.split(":")[0]
    return any(n == _OLLAMA_VL_MODEL or n.split(":")[0] == base for n in names)
