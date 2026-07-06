"""SDXL local image generation — subprocess-isolated txt2img for L5 角色卡参考图
and L6 场景/角色一致性画面(IP-Adapter conditioning)。

见 HEVI-SPEC-01 §5.1 步骤3 / §7.1-7.2。生成在独立子进程里做(同
hevi/video/wan_local_service.py 的隔离方式),进程退出即释放 VRAM,不占用
主 API 进程常驻显存。

Measured performance (RTX 3080, 2026-07-06):
- Plain txt2img: VRAM peak 8631 MiB (1024×1024, 20 steps, attention slicing +
  VAE tiling, madebyollin/sdxl-vae-fp16-fix — the stock SDXL fp16 VAE overflows
  to NaN at decode unless upcast to fp32, and that upcast alone OOMs on this
  GPU's free VRAM; the fp16-fix VAE avoids it entirely). ~8s denoise once warm.
- IP-Adapter conditioning (`extra.ip_adapter_image`, L6 角色一致性): adds a
  ~2.5GB CLIP-ViT-H image encoder on top of the base pipeline, which OOMs with
  plain `.to("cuda")` on this 10GB card. `_sdxl_worker.py` switches to
  `enable_model_cpu_offload()` for this path instead (peak ~7.1GB, ~13s denoise
  — slower due to CPU↔GPU weight shuffling, but fits). Also: `enable_attention_
  slicing()` must NOT be called after `load_ip_adapter()` — it corrupts the
  IP-Adapter cross-attention processor's `encoder_hidden_states` (ends up a
  bare tuple instead of the (text, image) pair it expects) and crashes with
  `AttributeError: 'tuple' object has no attribute 'shape'`. Real end-to-end
  verified: generated a reference portrait, then a differently-composed scene
  frame conditioned on it — robe style, palette, and facial structure carried
  over correctly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from hevi.core.config import settings
from hevi.gpu import VRAM_SDXL_LOCAL, scheduler

logger = logging.getLogger(__name__)

_WORKER_SCRIPT = Path(__file__).parent / "_sdxl_worker.py"
_DEFAULT_MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
_DEFAULT_STEPS = 30
_DEFAULT_GUIDANCE = 7.0
_DEFAULT_NEGATIVE = (
    "blurry, distorted, low quality, low resolution, deformed, disfigured, "
    "extra limbs, bad anatomy, watermark, text, jpeg artifacts, modern clothing, "
    "anachronistic objects"
)
# Cold model load (first run, no page cache) + generation; generous ceiling —
# a hang here would otherwise starve every other local GPU task via the scheduler lock.
_SDXL_TIMEOUT_S = 600


def _seed_for(output_path: Path) -> int:
    """Derive a deterministic seed from the output filename (same rationale as
    wan_local_service._seed_for: reproducible generation, distinct across variants).
    """
    digest = hashlib.sha256(output_path.stem.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


async def sdxl_local_generate(
    *,
    prompt: str,
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    output_path: Path | str,
    seed: int | None = None,
    timeout_s: float = 120.0,
    extra: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Generate a single SDXL image via an isolated subprocess.

    Matches obase.provider_registry.ImageGenCaller so it can be registered under
    the "image_gen" category and called via oprim.image_generate.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if seed is None:
        seed = _seed_for(output_path)
    extra = extra or {}

    async with scheduler.acquire(VRAM_SDXL_LOCAL):
        await _run_worker(
            prompt=prompt,
            negative_prompt=negative_prompt or _DEFAULT_NEGATIVE,
            width=width,
            height=height,
            output_path=output_path,
            seed=seed,
            num_inference_steps=extra.get("num_inference_steps", _DEFAULT_STEPS),
            guidance_scale=extra.get("guidance_scale", _DEFAULT_GUIDANCE),
            ip_adapter_image=extra.get("ip_adapter_image"),
            ip_adapter_weight=extra.get("ip_adapter_weight", 0.6),
        )

    return {"output_path": str(output_path), "seed": seed}


async def _run_worker(**task: Any) -> None:
    output_path: Path = task["output_path"]
    with tempfile.TemporaryDirectory(prefix="sdxl_gen_") as tmp_dir:
        task_json = Path(tmp_dir) / "task.json"
        payload = {
            **task,
            "output_path": str(output_path),
            "model_id": os.getenv("SDXL_MODEL_ID", _DEFAULT_MODEL_ID),
            "cache_dir": settings.sdxl_model_dir,
        }
        task_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(_WORKER_SCRIPT),
            str(task_json),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        async def _consume_and_wait() -> int:
            assert proc.stdout is not None
            async for line in proc.stdout:
                txt = line.decode(errors="replace").rstrip()
                if txt:
                    logger.debug("sdxl_worker: %s", txt)
            return await proc.wait()

        try:
            rc = await asyncio.wait_for(_consume_and_wait(), timeout=_SDXL_TIMEOUT_S)
        except TimeoutError, asyncio.CancelledError:
            logger.error("sdxl_local: subprocess timed out/cancelled — killing worker")
            proc.kill()
            await proc.wait()
            raise
        if rc != 0:
            raise RuntimeError(f"SDXL worker subprocess failed (exit {rc})")

    if not output_path.exists():
        raise RuntimeError("SDXL worker produced no output image")
