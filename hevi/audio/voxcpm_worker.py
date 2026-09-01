"""JSON stdin worker for VoxCPM environments that cannot run in HEVI's Python."""

from __future__ import annotations

import base64
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any


def _error(message: str) -> int:
    print(json.dumps({"status": "failed", "error": message}, ensure_ascii=False), flush=True)
    return 1


def main() -> int:
    try:
        request = json.load(sys.stdin)
        operation = str(request.get("operation") or "synthesize")
        text = str(request.get("text") or "").strip()
        output_path_value = str(request.get("output_path") or "").strip()
        output_path = Path(output_path_value).expanduser()
        model_id = str(request.get("model_id") or os.getenv("HEVI_VOXCPM_MODEL", "openbmb/VoxCPM-0.5B"))
        if not text:
            return _error("VoxCPM text cannot be empty")
        if operation != "stream" and not output_path_value:
            return _error("VoxCPM output_path is required")

        voxcpm = importlib.import_module("voxcpm")
        VoxCPM = getattr(voxcpm, "VoxCPM", None)
        if VoxCPM is None:
            return _error("voxcpm module has no VoxCPM entry point")

        if output_path_value:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        model = VoxCPM.from_pretrained(model_id, load_denoiser=False)
        voice_design = str(request.get("voice_design") or "").strip()
        prompt = f"({voice_design}){text}" if voice_design else text
        generation: dict[str, Any] = {
            "text": prompt,
            "cfg_value": float(request.get("cfg_value") or 2.0),
        }
        reference_audio = str(request.get("reference_audio") or "").strip()
        if reference_audio:
            if not Path(reference_audio).is_file():
                return _error(f"reference audio not found: {reference_audio}")
            generation["reference_wav_path"] = reference_audio
        if operation == "stream":
            import numpy as np

            sample_rate = int(getattr(getattr(model, "tts_model", None), "sample_rate", 48_000))
            for index, chunk in enumerate(model.generate_streaming(**generation)):
                values = chunk.detach().cpu().numpy() if hasattr(chunk, "detach") else np.asarray(chunk)
                if values.dtype.kind == "f":
                    pcm = (np.clip(values, -1.0, 1.0) * 32767.0).astype("<i2")
                else:
                    pcm = values.astype("<i2", copy=False)
                print(
                    json.dumps(
                        {
                            "status": "chunk",
                            "index": index,
                            "sample_rate": sample_rate,
                            "pcm_b64": base64.b64encode(pcm.tobytes()).decode("ascii"),
                        }
                    ),
                    flush=True,
                )
            print(json.dumps({"status": "succeeded"}), flush=True)
            return 0
        kwargs = request.get("kwargs") or {}
        if not isinstance(kwargs, dict):
            return _error("VoxCPM kwargs must be an object")
        generation.update(kwargs)
        wav = model.generate(**generation)
        sf = importlib.import_module("soundfile")

        rate = int(getattr(getattr(model, "tts_model", None), "sample_rate", 48_000))
        sf.write(str(output_path), wav, rate)
        if not output_path.is_file() or output_path.stat().st_size == 0:
            return _error("VoxCPM produced no non-empty WAV artifact")
        print(
            json.dumps(
                {"status": "succeeded", "path": str(output_path), "sample_rate": rate},
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 0
    except Exception as exc:  # worker boundary serializes failures for the parent
        return _error(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
