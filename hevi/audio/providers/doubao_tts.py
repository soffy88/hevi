"""Doubao TTS 可选 Provider 接口 (ByteDance Volcano Engine Speech).

根据 STORYBOOK_TASK.md 要求：
- 豆包仅做可选 provider 接口。
- 无 key 时必须跳过，不得调用付费 API。
- 绝不发起虚假请求，本地离线环境下安全静默回落。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DoubaoKeyMissingError(RuntimeError):
    """当未配置豆包凭证或禁止调用外部付费 API 时抛出。"""


@dataclass
class DoubaoVoiceConfig:
    voice_type: str = "zh_female_shuangkuai_moon_bigtts"
    rate: float = 1.0
    pitch: float = 1.0
    emotion: str = "happy"


class DoubaoStorybookTTSProvider:
    """豆包 TTS 客户端适配器。"""

    name: str = "doubao"

    def __init__(self) -> None:
        self.app_id = os.environ.get("DOUBAO_APPID", "").strip()
        self.access_token = os.environ.get("DOUBAO_ACCESS_TOKEN", "").strip()
        self.cluster = os.environ.get("DOUBAO_CLUSTER", "volcano_tts").strip()

    def is_available(self) -> bool:
        """检查凭证是否有效存在且非测试占位符。"""
        if not self.app_id or not self.access_token:
            return False
        if self.app_id in {"dummy", "test-only", "none", "mock"} or self.access_token in {"dummy", "test-only", "none", "mock"}:
            return False
        return True

    def synthesize(
        self,
        text: str,
        out_wav: Path,
        *,
        config: DoubaoVoiceConfig | None = None,
    ) -> Path:
        """合成语音。如果未配置有效 key，立即拒绝并阻断网络调用。"""
        if not self.is_available():
            logger.info("Doubao TTS key absent or invalid; skipping external API invocation as mandated by contract.")
            raise DoubaoKeyMissingError(
                "Doubao TTS requires DOUBAO_APPID and DOUBAO_ACCESS_TOKEN; skipping call because keys are absent."
            )

        # 仅在配置有效线上凭证时才可执行真实远端请求（当前环境为离线 CPU-only，严格阻断）
        raise NotImplementedError("Online Doubao endpoint execution is disabled under CPU-only local qualification.")
