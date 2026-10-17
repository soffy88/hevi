"""Piper 本地 TTS 原子（subprocess 调用 Piper 二进制）。CPU 秒级合成。"""

from __future__ import annotations

import json
import logging
import threading
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
        self._srv: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def _server(self) -> subprocess.Popen | None:
        """常驻进程：模型只加载一次，省掉每句约 1 秒的冷启动。失败则退回单次调用。"""
        if self._srv is not None and self._srv.poll() is None:
            return self._srv
        py = Path(self.binary).with_name("python")
        script = Path(__file__).with_name("piper_server.py")
        try:
            srv = subprocess.Popen([str(py), str(script), self.model], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
            if srv.stdout.readline().strip() != "ready":
                srv.kill()
                return None
            self._srv = srv
            return srv
        except Exception:  # noqa: BLE001
            logger.exception("piper 常驻进程启动失败，退回单次调用")
            return None

    def available(self) -> bool:
        return Path(self.binary).exists() and Path(self.model).exists()

    def synthesize(self, text: str, output_path: str | Path) -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            srv = self._server()
            if srv is not None:
                try:
                    srv.stdin.write(json.dumps({"text": text, "out": str(out)}, ensure_ascii=False) + "\n")
                    srv.stdin.flush()
                    if srv.stdout.readline().startswith("ok") and out.exists() and out.stat().st_size > 44:
                        return out
                except Exception:  # noqa: BLE001
                    logger.exception("piper 常驻进程出错，退回单次调用")
                    self._srv = None
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
