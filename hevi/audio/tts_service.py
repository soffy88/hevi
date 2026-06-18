"""hevi TTS service — subprocess-isolated vibevoice synthesis.

vibevoice_worker.py is spawned as a fresh subprocess so the model is loaded
in a separate process.  On subprocess exit, the OS fully reclaims all GPU
VRAM (same pattern as wan_local_service / Wan2GP).

Tests patch the module-level vibevoice_synthesize name:
    patch("hevi.audio.tts_service.vibevoice_synthesize", ...)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from hevi.audio.audio_config import AudioProvider
from hevi.gpu import VRAM_VIBEVOICE, scheduler
from hevi.observability import track_provider_call

logger = logging.getLogger(__name__)

_WORKER = Path(__file__).parent / "vibevoice_worker.py"
# Project venv python — same venv has oprim/vibevoice/torch installed.
_HEVI_PYTHON = Path(__file__).parent.parent.parent / ".venv/bin/python"

__all__ = ["synthesize_dialogue", "vibevoice_synthesize"]


async def vibevoice_synthesize(
    *,
    config: dict[str, Any] | None = None,
    script: list[Any],
    output_path: Path,
    watermark: bool = True,
    _inference_fn: Any = None,  # accepted for interface compat; ignored in subprocess mode
) -> Path:
    """Subprocess-isolated vibevoice synthesis (same interface as oprim.vibevoice_synthesize).

    Spawns vibevoice_worker.py in a fresh process.  On subprocess exit the OS
    fully reclaims GPU VRAM — vs. gc-only which leaves ~8.4 GB resident.

    This name is patchable by tests:
        patch("hevi.audio.tts_service.vibevoice_synthesize", AsyncMock(...))
    """
    cfg = config or {}
    model_dir = (
        cfg.get("VIBEVOICE_MODEL_DIR")
        or os.environ.get("VIBEVOICE_MODEL_DIR", "vendor/vibevoice")
    )
    return await _run_worker(
        script=script,
        output_path=output_path,
        model_dir=model_dir,
        watermark=watermark,
    )


async def _run_worker(
    *,
    script: list[Any],
    output_path: Path,
    model_dir: str,
    watermark: bool,
) -> Path:
    """Spawn vibevoice_worker.py and wait for completion."""
    with tempfile.NamedTemporaryFile(
        prefix="vv_args_", suffix=".json", mode="w", encoding="utf-8", delete=False
    ) as fh:
        args_path = Path(fh.name)
        json.dump(
            {
                "script": [
                    {
                        "speaker_id": getattr(line, "speaker_id", "host"),
                        "text": getattr(line, "text", str(line)),
                        "voice_ref": str(line.voice_ref)
                        if getattr(line, "voice_ref", None)
                        else None,
                    }
                    for line in script
                ],
                "output_path": str(output_path),
                "model_dir": model_dir,
                "watermark": watermark,
            },
            fh,
            ensure_ascii=False,
        )

    try:
        python = str(_HEVI_PYTHON) if _HEVI_PYTHON.exists() else sys.executable
        cmd = [python, str(_WORKER), str(args_path)]
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}

        logger.info("vibevoice: spawning synthesis worker subprocess")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        assert proc.stdout is not None
        async for raw in proc.stdout:
            txt = raw.decode(errors="replace").rstrip()
            if txt:
                logger.debug("vibevoice_worker: %s", txt)

        rc = await proc.wait()
        if rc != 0:
            raise RuntimeError(f"vibevoice_worker exited with code {rc}")

        if not output_path.exists():
            raise RuntimeError(f"vibevoice_worker produced no output: {output_path}")

        logger.info("vibevoice: saved to %s", output_path)
        return output_path
    finally:
        args_path.unlink(missing_ok=True)


async def synthesize_dialogue(
    *,
    config: Any,
    script: list[Any],
    output_path: Path,
    watermark: bool = True,
) -> Path:
    """Multi-speaker TTS via subprocess-isolated vibevoice_worker."""
    if not script:
        raise ValueError("Script cannot be empty")

    async with scheduler.acquire(VRAM_VIBEVOICE):
        async with track_provider_call(AudioProvider.VIBEVOICE):
            result = await vibevoice_synthesize(
                config=config if isinstance(config, dict) else None,
                script=script,
                output_path=output_path,
                watermark=watermark,
            )
            return Path(result)
