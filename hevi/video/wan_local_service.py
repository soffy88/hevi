"""Wan 2.1 T2V-1.3B local inference — async wrapper around blocking wan.WanT2V.

First call lazy-loads the model (~15-20 min for T5 11GB BF16 on CPU + DiT 5.3GB FP32 to GPU).
Subsequent calls reuse the resident model; only the DiT denoising runs (~6-13 min per 5s clip).

Env requirement:
  ~/Wan-CLI/       — official Wan-Video/Wan2.1 clone with SDPA attention patch applied
  ~/Wan2GP/venv_wan/lib/python3.14/site-packages/  — torch 2.12+cu130 + deps
  ~/models/wan2.1-t2v-1.3b/  — native Wan checkpoint (17GB: T5 + DiT + VAE)
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from hevi.gpu import VRAM_WAN_LOCAL, scheduler, wan_local_provider

logger = logging.getLogger(__name__)

# Native Wan resolution for 480P 16:9 (W×H)
_DEFAULT_SIZE = (832, 480)
_DEFAULT_FRAMES = 81   # ~5s @ 16fps
_DEFAULT_STEPS = 30
_SHIFT_480P = 3.0      # recommended shift for 480P; use 5.0 for 720P


async def wan_local_generate(
    *,
    prompt: str,
    output_path: Path | str,
    size: tuple[int, int] = _DEFAULT_SIZE,
    frame_num: int = _DEFAULT_FRAMES,
    sampling_steps: int = _DEFAULT_STEPS,
    guide_scale: float = 5.0,
    seed: int = -1,
    **_: Any,
) -> Path:
    """Generate a video clip locally via Wan 2.1 T2V-1.3B.

    Acquires GPU scheduler lock for the full duration (load + inference + save).
    First call blocks for model load; caller should set a long timeout.

    Returns the output Path on success.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with scheduler.acquire(VRAM_WAN_LOCAL):
        if not wan_local_provider.is_loaded():
            logger.info("wan_local: model not loaded — starting load (~15-20 min)")
            await wan_local_provider.load()

        model = wan_local_provider.get_model()
        loop = asyncio.get_running_loop()

        logger.info(
            "wan_local: generating %dx%d %d frames %d steps",
            size[0], size[1], frame_num, sampling_steps,
        )

        def _generate() -> Any:
            return model.generate(
                input_prompt=prompt,
                size=size,
                frame_num=frame_num,
                shift=_SHIFT_480P,
                sample_solver="unipc",
                sampling_steps=sampling_steps,
                guide_scale=guide_scale,
                n_prompt="",
                seed=seed,
                offload_model=True,
            )

        video = await loop.run_in_executor(None, _generate)

        def _save() -> None:
            # wan_local_provider._ensure_paths() already ran during load()
            from wan.utils.utils import cache_video  # noqa: PLC0415
            cache_video(
                tensor=video[None],  # [C,T,H,W] → [1,C,T,H,W]
                save_file=str(output_path),
                fps=16,
                nrow=1,
                normalize=True,
                value_range=(-1, 1),
            )

        await loop.run_in_executor(None, _save)
        logger.info("wan_local: saved to %s", output_path)
        return output_path
