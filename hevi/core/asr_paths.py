"""faster-whisper 模型定位（容器/宿主两套 env 的单一事实源）。

容器里常见三种写法，历史上只有 ``FASTER_WHISPER_MODEL_DIR`` 被识别：

* ``FASTER_WHISPER_MODEL_DIR=/models/faster-whisper-large-v3-turbo``
* ``HEVI_WHISPER_MODEL=/models/faster-whisper-large-v3-turbo``（compose 一直这么配）
* ``HEVI_TALKCRAFT_WHISPER=/models/faster-whisper-large-v3-turbo``

本模块按顺序解析，接受本地目录或 faster-whisper 的模型名（tiny/base/small/
medium/large-v2/large-v3/large-v3-turbo/turbo）。全部不可用时抛出中文可理解的
错误，而不是把 ``/app/models/...`` 当成 HuggingFace repo id 再报 wire 错误。
"""

from __future__ import annotations

import os
from pathlib import Path

# Model names faster-whisper can resolve by itself (downloads or local cache).
KNOWN_MODEL_NAMES = frozenset(
    {"tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium",
     "medium.en", "large", "large-v1", "large-v2", "large-v3", "large-v3-turbo", "turbo"}
)

_ENV_KEYS = (
    "FASTER_WHISPER_MODEL_DIR",
    "HEVI_WHISPER_MODEL",
    "HEVI_TALKCRAFT_WHISPER",
)

_DEFAULT_DIRS = (
    "/models/faster-whisper-large-v3-turbo",
    "/data/soffy/models/faster-whisper-large-v3-turbo",
    "~/models/faster-whisper-large-v3-turbo",
)


def _accept(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    if value in KNOWN_MODEL_NAMES:
        return value
    path = Path(value).expanduser()
    if path.is_dir():
        return str(path.resolve())
    return None


def resolve_whisper_model(explicit: str | None = None, *, required: bool = True) -> str | None:
    """Return a usable faster-whisper model reference.

    ``explicit`` wins, then the three env keys, then the conventional local
    directories.  With ``required=False`` an unresolvable setup returns ``None``
    so import-time constants stay cheap; callers that actually transcribe pass
    ``required=True`` and get a readable Chinese error.
    """
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    candidates.extend(os.environ.get(key, "") for key in _ENV_KEYS)
    candidates.extend(_DEFAULT_DIRS)
    for raw in candidates:
        resolved = _accept(raw)
        if resolved:
            return resolved
    if not required:
        return None
    tried = ", ".join(repr(c) for c in candidates if c)
    raise FileNotFoundError(
        "找不到可用的 faster-whisper 模型：请把模型目录挂载进容器，并设置 "
        "FASTER_WHISPER_MODEL_DIR（或 HEVI_WHISPER_MODEL / HEVI_TALKCRAFT_WHISPER）。"
        f" 已尝试：{tried or '（空）'}"
    )


__all__ = ["KNOWN_MODEL_NAMES", "resolve_whisper_model"]
