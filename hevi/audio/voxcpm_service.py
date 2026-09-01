"""HEVI-native VoxCPM capability (对照 OpenBMB/VoxCPM).

HEVI owns the voice-design, reference-conditioning, multilingual, streaming
and artifact-validation contract.  An optional upstream VoxCPM runtime may
provide neural-model fidelity, but it is not a prerequisite for execution.

  - `HEVI_VOXCPM_MODEL` is only read by the optional upstream enhancement.
  - `HEVI_TTS_FORMAL_PROVIDER=voxcpm` uses HEVI's native path by default.
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import logging
import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def voxcpm_available() -> bool:
    mod = _import_voxcpm()
    if mod is not None and getattr(mod, "VoxCPM", None) is not None:
        return True
    if _isolated_worker_python() is not None:
        return True
    # Import the concrete runtime symbol so tests and diagnostics can patch the
    # exact provider capability being probed.  The package-level export is a
    # convenience API and may otherwise retain a stale function reference.
    from hevi.voicepro.oskill.native_voice import native_voice_available

    return native_voice_available()


def _import_voxcpm() -> Any | None:
    try:
        return importlib.import_module("voxcpm")
    except ImportError:
        logger.debug("optional VoxCPM module unavailable; HEVI native runtime remains available")
        return None


def _model_id() -> str:
    return os.getenv("HEVI_VOXCPM_MODEL", "openbmb/VoxCPM-0.5B").strip() or "openbmb/VoxCPM-0.5B"


def _isolated_worker_python() -> Path | None:
    """Resolve the compatible Python worker without importing its dependency here."""

    configured = os.getenv("HEVI_VOXCPM_PYTHON", "").strip()
    if not configured:
        return None
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = Path(__file__).resolve().parents[2] / candidate
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate
    return None


def _isolated_worker_script() -> Path:
    return Path(__file__).with_name("voxcpm_worker.py")


async def _synth_with_isolated_worker(
    text: str,
    output_path: Path,
    *,
    language: str,
    reference_audio: str | Path | None,
    voice_design: str,
    speed: float,
    cfg_value: float,
    kwargs: dict[str, Any],
) -> None:
    python = _isolated_worker_python()
    script = _isolated_worker_script()
    if python is None or not script.is_file():
        raise RuntimeError(
            "VoxCPM isolated worker is not configured; set HEVI_VOXCPM_PYTHON "
            "to the compatible Python environment"
        )
    payload = {
        "text": text,
        "output_path": str(output_path.resolve()),
        "model_id": _model_id(),
        "language": language,
        "reference_audio": str(reference_audio) if reference_audio else "",
        "voice_design": voice_design,
        "speed": speed,
        "cfg_value": cfg_value,
        "kwargs": kwargs,
    }
    timeout_s = float(os.getenv("HEVI_VOXCPM_TIMEOUT_S", "900"))
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            [str(python), str(script)],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_s,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"VoxCPM worker timed out after {timeout_s:.0f}s") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "worker exited without details").strip()
        raise RuntimeError(f"VoxCPM worker failed ({completed.returncode}): {detail[-1200:]}")
    try:
        response = json.loads((completed.stdout or "{}").strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("VoxCPM worker returned invalid JSON") from exc
    if response.get("status") != "succeeded":
        raise RuntimeError(str(response.get("error") or "VoxCPM worker did not produce audio"))


async def _stream_with_isolated_worker(
    text: str,
    *,
    language: str,
    reference_audio: str | Path | None,
    voice_design: str,
    speed: float,
    chunk_chars: int,
) -> AsyncIterator[Any]:
    python = _isolated_worker_python()
    script = _isolated_worker_script()
    if python is None or not script.is_file():
        raise RuntimeError("VoxCPM isolated worker is not configured")
    payload = {
        "operation": "stream",
        "text": text,
        "model_id": _model_id(),
        "language": language,
        "reference_audio": str(reference_audio) if reference_audio else "",
        "voice_design": voice_design,
        "speed": speed,
        "chunk_chars": chunk_chars,
    }
    process = await asyncio.create_subprocess_exec(
        str(python),
        str(script),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    await process.stdin.drain()
    process.stdin.close()
    saw_final = False
    from hevi.voicepro.oskill.native_voice import NativeAudioChunk

    async for raw_line in process.stdout:
        try:
            response = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        status = response.get("status")
        if status == "chunk":
            yield NativeAudioChunk(
                index=int(response.get("index", 0)),
                pcm_s16le=base64.b64decode(str(response.get("pcm_b64") or "")),
                sample_rate=int(response.get("sample_rate", 48_000)),
                final=False,
            )
        elif status == "failed":
            raise RuntimeError(str(response.get("error") or "VoxCPM streaming worker failed"))
        elif status == "succeeded":
            saw_final = True
    return_code = await process.wait()
    if return_code != 0 or not saw_final:
        raise RuntimeError(f"VoxCPM streaming worker exited without a final chunk ({return_code})")


async def synth_with_voxcpm(
    text: str,
    output_path: Path,
    *,
    language: str = "",
    reference_audio: str | Path | None = None,
    voice_design: str = "",
    speed: float = 1.0,
    cfg_value: float = 2.0,
    **kwargs: Any,
) -> Path:
    """VoxCPM capability synthesis.

    HEVI's native voice skill is the default implementation.  If the optional
    upstream module is present, it may be used for higher-fidelity inference;
    the HEVI contract and artifact validation stay identical in both cases.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mod = _import_voxcpm()
    if mod is None or getattr(mod, "VoxCPM", None) is None:
        if _isolated_worker_python() is not None:
            await _synth_with_isolated_worker(
                text,
                output_path,
                language=language,
                reference_audio=reference_audio,
                voice_design=voice_design,
                speed=speed,
                cfg_value=cfg_value,
                kwargs=kwargs,
            )
            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise RuntimeError("VoxCPM worker completed without a non-empty WAV artifact")
            return output_path
        from hevi.voicepro.oskill import synthesize_native_voice_sync

        await asyncio.to_thread(
            synthesize_native_voice_sync,
            text,
            output_path,
            language=language,
            reference_audio=reference_audio,
            voice_design=voice_design,
            speed=speed,
        )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError("HEVI native VoxCPM capability produced no audio artifact")
        return output_path
    payload = text
    if voice_design.strip():
        payload = f"({voice_design.strip()}){text}"

    def _run() -> None:
        cls = getattr(mod, "VoxCPM", None)
        if cls is None:
            raise RuntimeError("voxcpm module has no VoxCPM entry point")
        model = cls.from_pretrained(_model_id(), load_denoiser=False)
        gen_kw: dict[str, Any] = {"text": payload, "cfg_value": cfg_value}
        if reference_audio:
            gen_kw["reference_wav_path"] = str(reference_audio)
        gen_kw.update(kwargs)
        wav = model.generate(**gen_kw)
        rate = getattr(getattr(model, "tts_model", None), "sample_rate", 48000)
        try:
            sf = importlib.import_module("soundfile")
        except ImportError as exc:
            raise RuntimeError(
                "VoxCPM produced audio but soundfile is not installed; "
                "install soundfile to write WAV artifacts"
            ) from exc
        sf.write(str(output_path), wav, rate)

    await asyncio.to_thread(_run)
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("voxcpm synth finished without a non-empty output file")
    return output_path


async def stream_voxcpm(
    text: str,
    *,
    voice: str = "",
    language: str = "",
    reference_audio: str | Path | None = None,
    voice_design: str = "",
    speed: float = 1.0,
    chunk_chars: int = 180,
) -> AsyncIterator[Any]:
    """Expose the same incremental PCM contract as the native voice skill."""

    if _isolated_worker_python() is not None:
        async for chunk in _stream_with_isolated_worker(
            text,
            language=language,
            reference_audio=reference_audio,
            voice_design=voice_design,
            speed=speed,
            chunk_chars=chunk_chars,
        ):
            yield chunk
        return

    from hevi.voicepro.oskill import stream_native_voice

    async for chunk in stream_native_voice(
        text,
        voice=voice,
        language=language,
        reference_audio=reference_audio,
        voice_design=voice_design,
        speed=speed,
        chunk_chars=chunk_chars,
    ):
        yield chunk


__all__ = ["stream_voxcpm", "synth_with_voxcpm", "voxcpm_available"]
