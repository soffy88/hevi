"""hevi-gen-engine F5-TTS 零样本音色克隆 worker —— 独立 ai-venv 子进程入口。

F5-TTS(参考: abus-aikorea/voice-pro 的 abus_tts_f5.py 用法)用参考音频
(≤12s 自动截断)+ 参考文本做零样本克隆, 质量优于 Qwen3-CustomVoice 单点;
本 worker 由 `/api/ai/f5_tts` 端点以子进程方式调用(与 fish_worker 同模式),
退出即释放显存。

用法:
    /opt/ai-venv/bin/python f5_worker.py <args.json>

Args JSON schema:
    {
      "text": "要合成的文本",
      "reference_audio": "/models/.../ref.wav",   # 必填(克隆音色)
      "reference_text": "参考音频的转录文本",       # 必填(缺失时质量不可控)
      "output_path": "/tmp/speech.wav",
      "model_dir": "/models/f5-tts",               # 默认读 F5_TTS_MODEL_DIR
      "seed": 42 | null,                           # 可选, 固定可复现
      "speed": 1.0                                 # 语速
    }

模型目录布局(model_dir):
    F5TTS_Base/model_1200000.safetensors   (SWivid/F5-TTS)
    F5TTS_Base/vocab.txt
    vocos/config.yaml + pytorch_model.bin   (charactr/vocos-mel-24khz)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _main(args_path: str) -> None:
    data = json.loads(Path(args_path).read_text(encoding="utf-8"))
    text = str(data["text"]).strip()
    ref_path = Path(data["reference_audio"])
    ref_text = str(data.get("reference_text") or "").strip()
    out_path = Path(data["output_path"])
    model_dir = Path(
        data.get("model_dir") or os.environ.get("F5_TTS_MODEL_DIR") or "/models/f5-tts"
    )
    seed = data.get("seed")
    speed = float(data.get("speed", 1.0))
    if not text:
        raise ValueError("text 为空")
    if not ref_path.exists():
        raise FileNotFoundError(f"参考音频不存在: {ref_path}")
    if not ref_text:
        raise ValueError(
            "reference_text 必填: F5-TTS 需要参考音频的转录文本做条件, "
            "缺失会导致克隆音色不可控(不自动转写, 生产容器离线纪律)"
        )

    import torch  # type: ignore[import-not-found]
    import torchaudio  # type: ignore[import-untyped]
    from f5_tts.infer.utils_infer import (  # type: ignore[import-not-found]
        infer_process,
        load_model,
        load_vocoder,
        preprocess_ref_audio_text,
    )
    from f5_tts.model import DiT  # type: ignore[import-not-found]

    device = "cuda" if torch.cuda.is_available() else "cpu"

    ckpt_path = model_dir / "F5TTS_Base" / "model_1200000.safetensors"
    vocab_file = model_dir / "F5TTS_Base" / "vocab.txt"
    vocos_dir = model_dir / "vocos"
    for p, label in (
        (ckpt_path, "F5-TTS 权重 (F5TTS_Base/model_1200000.safetensors)"),
        (vocab_file, "F5-TTS vocab.txt"),
        (vocos_dir / "config.yaml", "Vocos config.yaml"),
        (vocos_dir / "pytorch_model.bin", "Vocos pytorch_model.bin"),
    ):
        if not p.exists():
            raise FileNotFoundError(
                f"{label} 缺失: {p} —— 请按 docs/VOICEBOX-INTEGRATION.md 在宿主机 "
                f"snapshot_download 到 {model_dir}"
            )

    if seed is not None:
        torch.manual_seed(int(seed))

    # F5TTS_Base 配置(与 voice-pro abus_tts_f5_models.json 的 SWivid/F5-TTS 一致)。
    model_cfg = {
        "dim": 1024, "depth": 22, "heads": 16, "ff_mult": 2, "text_dim": 512,
        "conv_layers": 4,
    }
    model = load_model(
        DiT, model_cfg, str(ckpt_path), vocab_file=str(vocab_file), device=device
    )
    vocoder = load_vocoder(
        vocoder_name="vocos", is_local=True, local_path=str(vocos_dir), device=device
    )

    # 参考音频预处理(静音裁剪/限幅 → 缓存), 参考文本必填所以不会触发 ASR 转写。
    ref_audio, ref_text_pp = preprocess_ref_audio_text(str(ref_path), ref_text)

    wav, sr, _spect = infer_process(
        ref_audio,
        ref_text_pp,
        text,
        model_obj=model,
        vocoder=vocoder,
        speed=speed,
        show_info=lambda *_a, **_k: None,
        progress=None,
    )
    if wav is None:
        raise RuntimeError("F5-TTS 未产出音频(文本分块为空?)")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(out_path), wav, int(sr))
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"产物缺失或为空: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("args_json")
    args = parser.parse_args()
    try:
        _main(args.args_json)
    except Exception as exc:
        print(f"f5_worker failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
