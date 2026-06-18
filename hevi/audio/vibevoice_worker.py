"""vibevoice synthesis worker — standalone subprocess entry point.

Invoked by hevi.audio.tts_service._run_worker() as a subprocess.
Reads a JSON args-file, synthesizes audio via vibevoice directly (bypassing
oprim's broken _infer which omits tokenizer in model.generate), writes the
output WAV, then exits.  On exit the OS fully reclaims all VRAM.

Usage:
    python vibevoice_worker.py <args.json>

Args JSON schema:
    {
      "script": [{"speaker_id": "host", "text": "...", "voice_ref": null}],
      "output_path": "/tmp/out.wav",
      "model_dir": "/home/user/models/vibevoice-1.5b",
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


@dataclass
class _Line:
    speaker_id: str
    text: str
    voice_ref: Path | None = None


async def _main(args_path: str) -> None:
    data = json.loads(Path(args_path).read_text(encoding="utf-8"))

    # vibevoice processor requires "Speaker {n}: text" format.
    # oprim._infer receives speaker_id but never includes it in processor inputs,
    # so we pre-format text here to satisfy _parse_script's regex.
    script = [
        _Line(
            speaker_id=line["speaker_id"],
            text=f"Speaker 0: {line['text']}",
            voice_ref=Path(line["voice_ref"]) if line.get("voice_ref") else None,
        )
        for line in data["script"]
    ]

    import torch
    from vibevoice import (  # noqa: PLC0415
        VibeVoiceForConditionalGenerationInference,
        VibeVoiceProcessor,
    )

    model_dir = data["model_dir"]
    device = "cuda" if torch.cuda.is_available() else "cpu"

    processor = VibeVoiceProcessor.from_pretrained(model_dir)
    model = VibeVoiceForConditionalGenerationInference.from_pretrained(
        model_dir,
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        device_map=device,
    )
    model.eval()

    output_path = Path(data["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)

    segments: list[bytes] = []

    loop = asyncio.get_event_loop()

    def _infer_line(line: _Line) -> bytes:
        inputs: dict[str, object] = {"text": line.text, "return_tensors": "pt"}
        if line.voice_ref is not None and line.voice_ref.exists():
            inputs["reference_audio"] = str(line.voice_ref)

        with torch.no_grad():
            encoded = processor(**inputs)
            encoded = {
                k: v.to(device) if hasattr(v, "to") else v
                for k, v in encoded.items()
            }
            # Pass tokenizer explicitly — oprim omits this, causing AttributeError
            output = model.generate(**encoded, tokenizer=processor.tokenizer)

        speech = output.speech_outputs[0] if output.speech_outputs else None
        if speech is None:
            raise RuntimeError("vibevoice produced no audio output")

        # speech is a 1-D float tensor (mono waveform, 24 kHz)
        waveform_np = speech.squeeze().cpu().float().numpy()

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            pcm = (waveform_np * 32767).clip(-32768, 32767).astype("int16")
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()

    for line in script:
        wav_bytes = await loop.run_in_executor(None, _infer_line, line)
        segments.append(wav_bytes)

    _concat_wav(segments, output_path)


def _concat_wav(segments: list[bytes], output_path: Path) -> None:
    if not segments:
        raise RuntimeError("No audio segments to concatenate")
    if len(segments) == 1:
        output_path.write_bytes(segments[0])
        return

    all_frames: list[bytes] = []
    params = None
    for seg in segments:
        with wave.open(io.BytesIO(seg)) as wf:
            if params is None:
                params = wf.getparams()
            all_frames.append(wf.readframes(wf.getnframes()))

    with wave.open(str(output_path), "wb") as out:
        if params is not None:
            out.setparams(params)
        for frame in all_frames:
            out.writeframes(frame)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: vibevoice_worker.py <args.json>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(_main(sys.argv[1]))
