"""fish-speech v1.5 本地 TTS —— 纯本地推理(零 API 费用、零网络依赖)。

与 fish_speech_service.py(HTTP 客户端,依赖 hevi-gen-engine 容器)并存:
本模块直接以子进程方式调 `services/gen_engine/fish_worker_v15.py`(Dual-AR 官方
推理链,兼容 fish-speech-1.5 权重),子进程退出即释放显存。

优势(vs edge_tts):
  - 零网络:完全本地(权重在 /home/soffy/models/fish-speech-1.5);
  - 零样本声音克隆:给 10s 参考音频即克隆音色(多角色配音的关键);
  - 自然韵律:Dual-AR 架构(优于 v1.4;v1.4 代码加载 1.5 权重解码静音)。

约束: 需要 GPU(1.84GB 峰值;显存不足自动降级 CPU,慢数倍)。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = Path("/home/soffy/models/fish-speech-1.5")

#: fish_worker_v15.py 与 services/gen_engine 的相对位置。
_WORKER = Path(__file__).resolve().parent.parent.parent / "services/gen_engine/fish_worker_v15.py"


class FishSpeechLocalError(RuntimeError):
    """本地 fish-speech 推理失败。"""


async def fish_speech_local_synthesize(
    text: str,
    output_path: Path | str,
    *,
    model_dir: Path | str = DEFAULT_MODEL_DIR,
    reference_audio: Path | str | None = None,
    max_new_tokens: int = 1024,
    timeout_s: float = 900.0,
) -> Path:
    """一段文本 → 本地 fish-speech 合成 WAV(支持零样本声音克隆)。

    reference_audio: 参考音频(建议 5-15s 干净人声),给定时克隆其音色。
    失败抛 FishSpeechLocalError(调用方决定降级,如退回 edge_tts)。
    """
    if not text.strip():
        raise ValueError("text 不能为空")
    model_dir = Path(model_dir)
    if not (model_dir / "model.pth").exists():
        raise FishSpeechLocalError(f"fish-speech 权重缺失: {model_dir}")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    ref = Path(reference_audio) if reference_audio else None
    if ref is not None and not ref.exists():
        logger.warning("fish-speech 参考音频不存在,回退默认音色: %s", ref)
        ref = None

    payload = {
        "text": text,
        "model_dir": str(model_dir),
        "reference_audio": str(ref) if ref else None,
        "output_path": str(out),
        "max_new_tokens": max_new_tokens,
    }
    with tempfile.TemporaryDirectory(prefix="fish_local_") as td:
        args_json = Path(td) / "args.json"
        args_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(_WORKER),
            str(args_json),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        log_lines: list[str] = []
        async for line in proc.stdout:
            txt = line.decode(errors="replace").rstrip()
            if txt and not any(skip in txt for skip in ("it/s]", "it/s ")):
                log_lines.append(txt)
        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise FishSpeechLocalError(
                f"fish-speech 超时(>{timeout_s:.0f}s)"
            ) from None

    if rc != 0:
        tail = "\n".join(log_lines[-8:])
        raise FishSpeechLocalError(f"fish-speech 推理失败(rc={rc}): {tail[-500:]}")
    if not out.exists() or out.stat().st_size == 0:
        raise FishSpeechLocalError(f"fish-speech 未产出音频: {out}")

    import wave

    try:
        with wave.open(str(out)) as w:
            duration_s = w.getnframes() / max(w.getframerate(), 1)
    except Exception:
        duration_s = 0.0
    logger.info("fish-speech local: %.1fs %s (ref=%s)", duration_s, out, bool(ref))
    return out


__all__ = ["FishSpeechLocalError", "fish_speech_local_synthesize"]
