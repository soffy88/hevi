"""hevi TTS service — VibeVoice 1.5B local inference.

oprim.vibevoice_synthesize (M3) uses AutoModelForTextToWaveform which is not
registered for the 'vibevoice' model type in standard transformers.  This
module bypasses that broken path and calls the native ``vibevoice`` package
(pip install vibevoice) directly.

Bug report for M3 owner: oprim._vibevoice_synthesize should use
  VibeVoiceForConditionalGenerationInference + VibeVoiceProcessor
instead of AutoModelForTextToWaveform + AutoProcessor.
"""
from __future__ import annotations

import asyncio
import io
import os
import wave
from pathlib import Path
from typing import Any

from oprim import SpeakerLine  # protocol only — avoids the broken synthesize call

from hevi.audio.audio_config import AudioProvider
from hevi.observability import track_provider_call

_MODEL_BUNDLE: tuple[Any, Any] | None = None  # (processor, model)


def _get_model_dir() -> Path:
    raw = os.getenv("VIBEVOICE_MODEL_DIR") or os.getenv("VIBEVOICE_MODEL_PATH", "vendor/vibevoice")
    return Path(os.path.expanduser(raw))


def _load_bundle(model_dir: Path) -> tuple[Any, Any]:
    global _MODEL_BUNDLE
    if _MODEL_BUNDLE is not None:
        return _MODEL_BUNDLE

    import torch
    from vibevoice.modular.modeling_vibevoice_inference import (
        VibeVoiceForConditionalGenerationInference,
    )
    from vibevoice.processor.vibevoice_processor import VibeVoiceProcessor

    if not model_dir.exists():
        raise FileNotFoundError(f"VibeVoice model dir not found: {model_dir}")

    processor = VibeVoiceProcessor.from_pretrained(str(model_dir))

    dtype = torch.bfloat16
    try:
        model = VibeVoiceForConditionalGenerationInference.from_pretrained(
            str(model_dir),
            torch_dtype=dtype,
            device_map="cuda",
            attn_implementation="flash_attention_2",
        )
    except Exception:
        model = VibeVoiceForConditionalGenerationInference.from_pretrained(
            str(model_dir),
            torch_dtype=dtype,
            device_map="cuda",
            attn_implementation="sdpa",
        )

    model.eval()
    model.set_ddpm_inference_steps(num_steps=10)
    _MODEL_BUNDLE = (processor, model)
    return _MODEL_BUNDLE


def _build_script_str(script: list[SpeakerLine]) -> tuple[str, list[str | None]]:
    """Convert SpeakerLine list to vibevoice script format.

    Returns (script_text, ordered_voice_samples).
    speaker_ids are mapped to "Speaker 1", "Speaker 2", … in order of first
    appearance to satisfy vibevoice's fixed numbering scheme.
    """
    seen: dict[str, int] = {}
    lines: list[str] = []
    voice_samples: list[str | None] = []

    for line in script:
        if line.speaker_id not in seen:
            n = len(seen) + 1
            seen[line.speaker_id] = n
            ref = str(line.voice_ref) if getattr(line, "voice_ref", None) else None
            voice_samples.append(ref)
        n = seen[line.speaker_id]
        lines.append(f"Speaker {n}: {line.text}")

    return "\n".join(lines), voice_samples


def _wav_bytes_from_tensor(audio_tensor: Any, sample_rate: int = 24000) -> bytes:
    """Encode a float32/bfloat16 waveform tensor as 16-bit PCM WAV bytes."""
    import numpy as np

    arr = audio_tensor.squeeze().cpu().float().numpy()
    pcm = (arr * 32767).clip(-32768, 32767).astype("int16")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def _synthesize_sync(
    script: list[SpeakerLine],
    output_path: Path,
    model_dir: Path,
) -> Path:
    import torch

    processor, model = _load_bundle(model_dir)
    script_text, voice_samples = _build_script_str(script)

    # Filter None voice refs to None list when all absent
    vs_arg = [v for v in voice_samples] if any(v for v in voice_samples) else None

    inputs = processor(
        text=[script_text],
        voice_samples=[vs_arg] if vs_arg else None,
        padding=True,
        return_tensors="pt",
        return_attention_mask=True,
    )

    device = next(model.parameters()).device
    for k, v in inputs.items():
        if torch.is_tensor(v):
            inputs[k] = v.to(device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=None,
            cfg_scale=1.3,
            tokenizer=processor.tokenizer,
            generation_config={"do_sample": False},
            verbose=False,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    processor.save_audio(outputs.speech_outputs[0], output_path=str(output_path))
    return output_path


async def synthesize_dialogue(
    *,
    config: Any,
    script: list[SpeakerLine],
    output_path: Path,
    watermark: bool = True,  # safety flag; oprim placeholder — real impl is in vibevoice pkg
) -> Path:
    """Multi-speaker TTS using native VibeVoice 1.5B.

    Single speaker = script of length 1.
    watermark=True is the default (Microsoft Responsible AI requirement);
    the actual watermarking logic lives in the vibevoice package.
    """
    if not script:
        raise ValueError("Script cannot be empty")

    model_dir = _get_model_dir()

    async with track_provider_call(AudioProvider.VIBEVOICE):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, _synthesize_sync, script, output_path, model_dir
        )
