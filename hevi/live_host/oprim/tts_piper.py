"""Piper 本地 TTS 原子（subprocess 调用 Piper 二进制）。CPU 秒级合成。"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from hevi.live_host.schemas import Engine

logger = logging.getLogger(__name__)


class PiperTTS(Engine):
    """调用 Piper 二进制把文本合成 wav。"""

    name = "piper"

    def __init__(
        self,
        binary: str = "/data/soffy/projects/hevi-zero/.venv/bin/piper",
        model: str = "/data/soffy/projects/hevi-zero/voices/zh_CN-huayan-medium.onnx",
    ) -> None:
        self.binary = binary
        self.model = model

    def available(self) -> bool:
        return Path(self.binary).exists() and Path(self.model).exists()

    def synthesize(self, text: str, output_path: str | Path) -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [self.binary, "--model", self.model, "--output_file", str(out)],
            input=text,
            capture_output=True,
            text=True,
            check=True,
        )
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError(f"Piper 未产出音频: {out} (stderr={proc.stderr[:200]})")
        return out
