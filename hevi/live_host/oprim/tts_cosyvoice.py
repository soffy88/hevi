"""CosyVoice 引擎 TTS 原子（HTTP 委托 GPU 引擎容器，可选热切换）。

本地无 GPU 时走 ollama CPU；CosyVoice 由 services/gen_engine(:17600) 提供，
契约为 cosy-ref-v1：每行需 voice_ref（含 builtin: 前缀）或 sft + spk_id。
CPU 模式下该引擎冷启动极慢（分钟级），故 MVP 默认走 Piper，此处仅作可插拔/热切换。
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from hevi.live_host.schemas import Engine

logger = logging.getLogger(__name__)


class CosyVoiceTTS(Engine):
    name = "cosyvoice"

    def __init__(
        self,
        base_url: str = "http://localhost:17600/api/ai/cosyvoice",
        voice_ref: str = "builtin:zh_default",
        ref_text: str = "",
        watermark: bool = False,
    ) -> None:
        self.base_url = base_url
        self.voice_ref = voice_ref
        self.ref_text = ref_text
        self.watermark = watermark

    def available(self) -> bool:
        try:
            r = httpx.get(self.base_url.rsplit("/api", 1)[0] + "/api/ai/health", timeout=5)
            return r.status_code == 200 and r.json().get("cosyvoice") is True
        except Exception:  # pragma: no cover
            return False

    def synthesize(self, text: str, output_path: str | Path) -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "script": [
                {
                    "text": text,
                    "voice_ref": self.voice_ref,
                    "ref_text": self.ref_text,
                    "inference_mode": "zero_shot",
                }
            ],
            "config": {"contract": "cosy-ref-v1", "watermark": self.watermark},
        }
        with httpx.Client(timeout=300) as client:
            resp = client.post(self.base_url, json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(f"CosyVoice 合成失败 HTTP {resp.status_code}: {resp.text[:200]}")
            out.write_bytes(resp.content)
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError(f"CosyVoice 未产出音频: {out}")
        return out
