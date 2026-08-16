"""hevi-gen-engine CosyVoice2/3 合成 worker —— 独立 cosy-venv 子进程入口。

cosy-venv 隔离原因: 重供货的 CosyVoice(services/gen_engine/cosyvoice/, 见
README.md)要求 transformers==5.13.0 及两个行为补丁, 与 ai-venv 的
vibevoice(transformers==4.51.3)版本钉冲突, 故单独 venv(同 asr-venv 模式)。

参考: abus-aikorea/voice-pro 的 abus_tts_cosyvoice.py 推理流
(load_wav 16k → 静音裁剪/归一化 → 零样本或跨语种推理 → torchaudio 保存)。

用法:
    /opt/cosy-venv/bin/python cosy_worker.py <args.json>

Args JSON schema:
    {
      "script": [
        {
          "speaker_id": "host",
          "text": "要合成的文本",
          "voice_ref": "/models/.../ref.wav",   # 必填(克隆音色)
          "ref_text": "参考音频转录" | null,     # 有 → zero-shot; 无 → cross-lingual
          "speed": 1.0
        }
      ],
      "output_path": "/tmp/speech.wav",
      "model_dir": "/opt/cosyvoice/model",       # 含 cosyvoice2.yaml / cosyvoice3.yaml
      "seed": null
    }

模型家族自动检测: model_dir 含 cosyvoice3.yaml → CosyVoice3;
含 cosyvoice2.yaml → CosyVoice2; 否则报错并提示补 yaml。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

#: CosyVoice3 需要系统提示词 + <|endofprompt|> 标记(上游 example.py 约定),
#: 缺失时 LLM 线程静默死亡、产出空音频。
_CV3_SYSTEM_PROMPT = "You are a helpful assistant.<|endofprompt|>"

_PROMPT_SR = 16000
_MAX_VAL = 0.8


def _detect_family(model_dir: Path) -> str:
    if (model_dir / "cosyvoice3.yaml").exists():
        return "cosyvoice3"
    if (model_dir / "cosyvoice2.yaml").exists():
        return "cosyvoice2"
    raise ValueError(
        f"{model_dir} 缺 cosyvoice2.yaml / cosyvoice3.yaml; "
        "旧版 cosyvoice.yaml 布局不兼容重供货代码 —— 从 "
        "FunAudioLLM/CosyVoice2-0.5B hf_hub_download cosyvoice2.yaml 放入模型目录"
    )


def _prepare_prompt_wav(ref_audio: Path, tmp_dir: Path) -> Path:
    """参考音频 → 16k 单声道、静音裁剪、归一化(≤0.8)+ 0.2s 尾静音 → 临时 wav。"""
    import librosa  # type: ignore[import-not-found]
    import torch  # type: ignore[import-not-found]
    import torchaudio  # type: ignore[import-not-found]
    from cosyvoice.utils.file_utils import load_wav  # type: ignore[import-not-found]

    speech = load_wav(str(ref_audio), _PROMPT_SR)
    speech, _ = librosa.effects.trim(
        speech, top_db=60, frame_length=440, hop_length=220
    )
    if speech.abs().max() > _MAX_VAL:
        speech = speech / speech.abs().max() * _MAX_VAL
    speech = torch.concat(
        [speech, torch.zeros(1, int(_PROMPT_SR * 0.2))], dim=1
    )
    prompt_wav = tmp_dir / "prompt.wav"
    torchaudio.save(str(prompt_wav), speech, _PROMPT_SR)
    return prompt_wav


def _synthesize_line(
    cosyvoice: Any,
    family: str,
    text: str,
    voice_ref: Path,
    ref_text: str | None,
    speed: float,
    tmp_dir: Path,
) -> Any:
    """单行合成, 返回 tts_speech tensor(24k / 22.05k, 取决于模型)。"""
    import torch  # type: ignore[import-not-found]

    prompt_wav = _prepare_prompt_wav(voice_ref, tmp_dir)
    prefix = _CV3_SYSTEM_PROMPT if family == "cosyvoice3" else ""
    chunks: list[Any] = []
    if ref_text:
        # zero-shot: 参考文本条件(发音/语气更贴参考); CV3 前缀系统提示词。
        gen = cosyvoice.inference_zero_shot(
            text, prefix + ref_text, str(prompt_wav),
            stream=False, speed=speed, text_frontend=False,
        )
    else:
        # cross-lingual: 无参考文本(音色克隆不需要知道参考说了什么)。
        gen = cosyvoice.inference_cross_lingual(
            prefix + text, str(prompt_wav),
            stream=False, speed=speed, text_frontend=False,
        )
    for chunk in gen:
        speech = chunk["tts_speech"]
        if speech is not None:
            chunks.append(speech.detach().cpu())
    if not chunks:
        raise RuntimeError(
            f"CosyVoice 未产出音频(行: {text[:40]}…) —— CV3 缺系统提示词? 模型损坏?"
        )
    return torch.cat(chunks, dim=1)


def _main(args_path: str) -> None:
    data = json.loads(Path(args_path).read_text(encoding="utf-8"))
    script: list[dict[str, Any]] = data["script"]
    out_path = Path(data["output_path"])
    model_dir = Path(data["model_dir"])
    seed = data.get("seed")
    if not script:
        raise ValueError("script 为空")

    family = _detect_family(model_dir)

    from cosyvoice.cli.cosyvoice import CosyVoice2, CosyVoice3  # type: ignore[import-not-found]

    if seed is not None:
        import random

        from cosyvoice.utils.common import set_all_random_seed  # type: ignore[import-not-found]

        random.seed(int(seed))
        set_all_random_seed(int(seed))

    cosyvoice = (
        CosyVoice3(str(model_dir)) if family == "cosyvoice3" else CosyVoice2(str(model_dir))
    )

    with tempfile.TemporaryDirectory(prefix="hevi-cosy-") as tmp:
        tmp_dir = Path(tmp)
        chunks: list[Any] = []
        for line in script:
            text = str(line.get("text") or "").strip()
            ref_raw = line.get("voice_ref")
            if not text:
                raise ValueError("script 行 text 为空")
            if not ref_raw:
                raise ValueError("script 行缺 voice_ref(F5/CosyVoice 克隆必须参考音频)")
            voice_ref = Path(str(ref_raw))
            if not voice_ref.exists():
                raise FileNotFoundError(f"voice_ref 不可达: {voice_ref}")
            chunks.append(
                _synthesize_line(
                    cosyvoice,
                    family,
                    text,
                    voice_ref,
                    line.get("ref_text") or None,
                    float(line.get("speed", 1.0)),
                    tmp_dir,
                )
            )

    import torch  # type: ignore[import-not-found]
    import torchaudio  # type: ignore[import-not-found]

    wav = torch.cat(chunks, dim=1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(out_path), wav, cosyvoice.sample_rate)
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"产物缺失或为空: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("args_json")
    args = parser.parse_args()
    try:
        _main(args.args_json)
    except Exception as exc:
        print(f"cosy_worker failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
