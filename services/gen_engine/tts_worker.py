"""hevi-gen-engine vibevoice 合成 worker —— 独立 ai-venv 子进程入口。

与 hevi-api 旧 vibevoice_worker.py 同构, 但**不依赖 oprim**: 直接使用
vibevoice PyPI 包完成模型加载与逐行推理。子进程退出即回收全部 GPU VRAM。

用法:
    /opt/ai-venv/bin/python tts_worker.py <args.json>

Args JSON schema:
    {
      "script": [{"speaker_id": "host", "text": "...", "voice_ref": null}],
      "output_path": "/tmp/out.wav",
      "model_dir": "/models/vibevoice-1.5b",
      "watermark": false
    }
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class _Line:
    speaker_id: str
    text: str
    voice_ref: Path | None = None


def _patch_vibevoice_exports() -> None:
    """vibevoice PyPI 0.0.1 的顶层 __init__.py 是空的, 必须手动补导出。"""
    try:
        import vibevoice  # type: ignore[import-not-found]
        from vibevoice.modular.modeling_vibevoice_inference import (  # type: ignore
            VibeVoiceForConditionalGenerationInference,
        )
        from vibevoice.processor.vibevoice_processor import (  # type: ignore
            VibeVoiceProcessor,
        )

        vibevoice.VibeVoiceForConditionalGenerationInference = (
            VibeVoiceForConditionalGenerationInference
        )
        vibevoice.VibeVoiceProcessor = VibeVoiceProcessor
    except Exception as exc:
        raise RuntimeError(f"vibevoice 导出补丁失败: {exc}") from exc


def _patch_reference_audio_kwarg() -> None:
    """修复 vibevoice 0.0.1 的 reference_audio kwarg bug。

    该版本的 VibeVoiceProcessor.__call__ 没有 reference_audio 参数(真实参数名是
    voice_samples), 未知 kwarg 被静默吸收 → speech_tensors=None → model.generate()
    崩在 'NoneType' object has no attribute 'to'。与 hevi/audio/vibevoice_patch.py
    的补丁完全同构, 在引擎 worker 里必须同样生效。
    """
    from vibevoice.processor.vibevoice_processor import VibeVoiceProcessor  # type: ignore

    if getattr(VibeVoiceProcessor.__call__, "_hevi_patched", False):
        return

    original_call = VibeVoiceProcessor.__call__

    def _patched_call(self, *args, **kwargs):
        reference_audio = kwargs.pop("reference_audio", None)
        if reference_audio is not None and kwargs.get("voice_samples") is None:
            kwargs["voice_samples"] = [reference_audio]
        return original_call(self, *args, **kwargs)

    _patched_call._hevi_patched = True
    VibeVoiceProcessor.__call__ = _patched_call


def _load_model(model_dir: Path) -> tuple[Any, Any, str]:
    import torch  # type: ignore[import-not-found]
    from vibevoice import (  # type: ignore[import-not-found]
        VibeVoiceForConditionalGenerationInference,
        VibeVoiceProcessor,
    )

    if not model_dir.exists():
        raise RuntimeError(f"VibeVoice 模型目录不存在: {model_dir}")

    # GPU 优先; 显存不足/不可用时自动降级 CPU(多引擎共存阶段 GPU 可能被占满)。
    device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        processor = VibeVoiceProcessor.from_pretrained(str(model_dir))
        model = VibeVoiceForConditionalGenerationInference.from_pretrained(
            str(model_dir),
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            device_map=device,
        )
    except (RuntimeError, torch.cuda.OutOfMemoryError):  # type: ignore[attr-defined]
        if device == "cuda":
            import gc

            gc.collect()
            torch.cuda.empty_cache()
            device = "cpu"
            processor = VibeVoiceProcessor.from_pretrained(str(model_dir))
            model = VibeVoiceForConditionalGenerationInference.from_pretrained(
                str(model_dir),
                torch_dtype=torch.float32,
                device_map="cpu",
            )
        else:
            raise
    return processor, model, device


def _make_inference(model_bundle: Any, watermark: bool) -> Any:
    """逐行合成闭包(在 executor 中执行, 避免阻塞事件循环)。"""
    _spk_map: dict[str, int] = {}

    def _infer(text: str, speaker_id: str, voice_ref: Path | None) -> bytes:
        import numpy as np
        import torch

        if speaker_id not in _spk_map:
            _spk_map[speaker_id] = len(_spk_map) + 1
        speaker_num = _spk_map[speaker_id]

        processor, model, device = model_bundle
        inputs: dict[str, Any] = {
            "text": f"Speaker {speaker_num}: {text}",
            "return_tensors": "pt",
        }
        if voice_ref is not None and voice_ref.exists():
            inputs["reference_audio"] = str(voice_ref)

        with torch.no_grad():
            encoded = processor(**inputs)
            encoded = {k: v.to(device) if hasattr(v, "to") else v for k, v in encoded.items()}
            output = model.generate(**encoded, tokenizer=processor.tokenizer)

        speech_outputs = getattr(output, "speech_outputs", None)
        if not speech_outputs or speech_outputs[0] is None:
            raise RuntimeError("VibeVoice 未产生语音输出")
        waveform_np = speech_outputs[0].squeeze().cpu().float().numpy()
        sample_rate: int = getattr(
            getattr(processor, "audio_processor", None), "sampling_rate", 24000
        )
        if watermark:
            pass  # 与 oprim 一致: 水印为占位(responsible-AI 标记, 生产可接真实库)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            pcm = np.clip(waveform_np, -1.0, 1.0)
            wf.writeframes((pcm * 32767).astype("int16").tobytes())
        return buf.getvalue()

    return _infer


def _concat_wav(segments: list[bytes], output_path: Path) -> None:
    if not segments:
        raise RuntimeError("没有可拼接的音频段")
    with wave.open(str(output_path), "wb") as out_wf:
        params_set = False
        for seg in segments:
            with wave.open(io.BytesIO(seg)) as seg_wf:
                if not params_set:
                    out_wf.setnchannels(seg_wf.getnchannels())
                    out_wf.setsampwidth(seg_wf.getsampwidth())
                    out_wf.setframerate(seg_wf.getframerate())
                    params_set = True
                out_wf.writeframes(seg_wf.readframes(seg_wf.getnframes()))


async def _main(args_path: str) -> None:
    data = json.loads(Path(args_path).read_text(encoding="utf-8"))
    script = [
        _Line(
            speaker_id=line["speaker_id"],
            text=line["text"],
            voice_ref=Path(line["voice_ref"]) if line.get("voice_ref") else None,
        )
        for line in data["script"]
    ]
    model_dir = Path(data["model_dir"])
    output_path = Path(data["output_path"])
    watermark = bool(data.get("watermark", True))

    _patch_vibevoice_exports()
    _patch_reference_audio_kwarg()
    model_bundle = _load_model(model_dir)
    infer = _make_inference(model_bundle, watermark)

    loop = asyncio.get_event_loop()
    segments: list[bytes] = []
    for line in script:
        wav_bytes = await loop.run_in_executor(
            None, infer, line.text, line.speaker_id, line.voice_ref
        )
        segments.append(wav_bytes)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _concat_wav(segments, output_path)
    print(f"OK {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: tts_worker.py <args.json>", file=sys.stderr)
        sys.exit(1)
    try:
        asyncio.run(_main(sys.argv[1]))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
