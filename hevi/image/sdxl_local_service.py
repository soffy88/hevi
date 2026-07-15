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
_BATCH_WORKER_SCRIPT = Path(__file__).parent / "_sdxl_batch_worker.py"
_DEFAULT_MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
_DEFAULT_STEPS = 30
_DEFAULT_GUIDANCE = 7.0
_DEFAULT_NEGATIVE = (
    "blurry, distorted, low quality, low resolution, deformed, disfigured, "
    "extra limbs, bad anatomy, watermark, text, jpeg artifacts, modern clothing, "
    "anachronistic objects, "
    # 2026-07-09 加固:CPU 回退验证时实测过 SDXL Base 1.0 对中文历史人物 prompt
    # 会跑偏成这些内容——国旗/军装/拼贴/地图这类硬伤,不是"低质量"能概括的,
    # 得专门排除。
    "national flag, flags, military uniform, western suit, necktie, sunglasses, "
    "collage, multiple panels, comic panel, grid layout, cartoon sticker, poster, "
    "infographic, map, diagram, logo, signature"
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


class GPUUnavailableError(RuntimeError):
    """本地 GPU 探活失败(常见于这台机器反复出现的 RTX 3080 掉出 PCIe 总线故障,
    Xid 79 → 154 Node Reboot Required)。调用方应据此降级到云端 image_gen,而不是
    先拉起一次完整的 SDXL 子进程(模型加载几十秒)才在 CUDA 崩溃里发现卡已经死了。
    """


_GPU_PREFLIGHT_TIMEOUT_S = 10.0


async def check_gpu_available(timeout_s: float = _GPU_PREFLIGHT_TIMEOUT_S) -> None:
    """`nvidia-smi` 探活——特意不在这个(主)进程里 import torch/碰 CUDA,同模块
    docstring 的既有原则(常驻进程不占显存)。卡掉出总线时 nvidia-smi 会返回非零
    退出码或直接报 "Unable to determine the device handle"。
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=name",
            "--format=csv,noheader",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise GPUUnavailableError("nvidia-smi 不存在,无法探活") from e

    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise GPUUnavailableError(f"nvidia-smi 探活超时(>{timeout_s}s),GPU 可能已挂起") from None

    if proc.returncode != 0:
        raise GPUUnavailableError(
            f"nvidia-smi 探活失败(exit {proc.returncode}): {stderr.decode(errors='replace').strip()}"
        )


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
    require_gpu: bool = True,
    **_: Any,
) -> dict[str, Any]:
    """Generate a single SDXL image via an isolated subprocess.

    Matches obase.provider_registry.ImageGenCaller so it can be registered under
    the "image_gen" category and called via oprim.image_generate.

    require_gpu=False skips the preflight GPU probe and lets the worker itself
    decide (CUDA if available, else a slow CPU fallback — see _sdxl_worker.py).
    Only meant for manually verifying the pipeline while the GPU is down; normal
    callers want the fast-fail default so a dead card doesn't eat a subprocess +
    model-load before anyone notices.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if seed is None:
        seed = _seed_for(output_path)
    extra = extra or {}

    if require_gpu:
        await check_gpu_available()
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


async def sdxl_local_generate_batch(
    requests: list[dict[str, Any]],
    *,
    require_gpu: bool = True,
) -> list[dict[str, Any] | Exception]:
    """Generate many images in one subprocess — model loaded once, VRAM released
    only after the whole batch finishes.

    require_gpu=False skips the preflight GPU probe (see sdxl_local_generate's
    docstring for when that's appropriate — manual verification only, not
    production call sites).

    Cuts GPU power-cycling churn versus sdxl_local_generate()'s one-subprocess-
    per-image isolation: call sites that need many images from the same identity/
    style back-to-back (HEVI-EXEC-01 M2 identity-pack construction, ~17 calls per
    character) were repeatedly forcing a full CUDA init/teardown every few
    seconds, which was implicated in a GPU-fallen-off-PCIe-bus fault (Xid 79) on
    this host's consumer-grade hardware.

    Each dict in `requests` takes the same keys as sdxl_local_generate()'s kwargs
    (prompt, negative_prompt, width, height, output_path, seed, extra). Returns a
    list of the same length, in order: a result dict on success, or the Exception
    on failure for that one item (isolated — one bad prompt/path doesn't sink the
    rest of the batch), for the caller to log/skip exactly like a single-call
    try/except would.

    Note (2026-07-08): a single-subprocess/single-model-load smoke test of this
    exact function still triggered Xid 79 within ~7min of a clean `nvidia-smi`,
    which weighs against the power-cycling theory above and toward a plain
    physical-layer fault — this function still cuts subprocess/model-load
    overhead when the GPU is healthy, just don't expect it to fix the PCIe
    dropout. `check_gpu_available()` below is the actual mitigation: fail fast
    before sinking a subprocess+model-load into a dead card.
    """
    if not requests:
        return []
    if require_gpu:
        await check_gpu_available()
    async with scheduler.acquire(VRAM_SDXL_LOCAL):
        return await _run_batch_worker(requests)


async def _run_batch_worker(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any] | Exception]:
    items: list[dict[str, Any]] = []
    for req in requests:
        output_path = Path(req["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        seed = req.get("seed")
        if seed is None:
            seed = _seed_for(output_path)
        extra = req.get("extra") or {}
        items.append(
            {
                "prompt": req["prompt"],
                "negative_prompt": req.get("negative_prompt") or _DEFAULT_NEGATIVE,
                "width": req.get("width", 1024),
                "height": req.get("height", 1024),
                "output_path": str(output_path),
                "seed": seed,
                "num_inference_steps": extra.get("num_inference_steps", _DEFAULT_STEPS),
                "guidance_scale": extra.get("guidance_scale", _DEFAULT_GUIDANCE),
                "ip_adapter_image": extra.get("ip_adapter_image"),
                "ip_adapter_weight": extra.get("ip_adapter_weight", 0.6),
            }
        )

    with tempfile.TemporaryDirectory(prefix="sdxl_batch_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        task_json = tmp_path / "batch_task.json"
        results_json = tmp_path / "results.json"
        payload = {
            "items": items,
            "model_id": os.getenv("SDXL_MODEL_ID", _DEFAULT_MODEL_ID),
            "cache_dir": settings.sdxl_model_dir,
            "results_path": str(results_json),
        }
        task_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(_BATCH_WORKER_SCRIPT),
            str(task_json),
            # 离线加载:所有权重已在 settings.sdxl_model_dir 缓存(SDXL base+VAE+IP-Adapter
            # 含其 CLIP-ViT-H image_encoder)。不设离线标志时,无网环境(生产容器连不上
            # huggingface.co)下 diffusers 仍会联网校验 revision 而无限卡住,直到 worker
            # 600s 超时被杀(实测容器内 IP-Adapter 关键帧即撞)。离线后容器内 137s 正常出图。
            env={
                **os.environ,
                "PYTHONUNBUFFERED": "1",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        async def _consume_and_wait() -> int:
            assert proc.stdout is not None
            async for line in proc.stdout:
                txt = line.decode(errors="replace").rstrip()
                if txt:
                    logger.debug("sdxl_batch_worker: %s", txt)
            return await proc.wait()

        try:
            rc = await asyncio.wait_for(
                _consume_and_wait(), timeout=_SDXL_TIMEOUT_S * max(1, len(items))
            )
        except TimeoutError, asyncio.CancelledError:
            logger.error("sdxl_local: batch subprocess timed out/cancelled — killing worker")
            proc.kill()
            await proc.wait()
            raise

        if not results_json.exists():
            raise RuntimeError(f"SDXL batch worker produced no results (exit {rc})")
        raw_results = json.loads(results_json.read_text(encoding="utf-8"))

    # raw_results can be shorter than items: _sdxl_batch_worker.py flushes after every
    # item, so a mid-batch crash (e.g. another Xid 79) still leaves the items completed
    # before the crash. Items past that point get no entry — pad them as failures
    # rather than silently truncating, since callers (e.g. identity_pack.py) zip this
    # return value positionally against their own key lists with strict=True.
    results: list[dict[str, Any] | Exception] = []
    for i, item in enumerate(items):
        r = raw_results[i] if i < len(raw_results) else None
        if r is None:
            results.append(
                RuntimeError(
                    f"SDXL batch worker crashed before this item ran (exit {rc}) — "
                    f"{len(raw_results)}/{len(items)} items completed"
                )
            )
        elif r.get("ok"):
            results.append({"output_path": item["output_path"], "seed": item["seed"]})
        else:
            results.append(RuntimeError(r.get("error", "unknown SDXL batch item failure")))
    return results


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
            # 离线加载:所有权重已在 settings.sdxl_model_dir 缓存(SDXL base+VAE+IP-Adapter
            # 含其 CLIP-ViT-H image_encoder)。不设离线标志时,无网环境(生产容器连不上
            # huggingface.co)下 diffusers 仍会联网校验 revision 而无限卡住,直到 worker
            # 600s 超时被杀(实测容器内 IP-Adapter 关键帧即撞)。离线后容器内 137s 正常出图。
            env={
                **os.environ,
                "PYTHONUNBUFFERED": "1",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            },
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
