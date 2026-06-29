"""Wan 2.1 T2V-1.3B local inference — Wan2GP + CausVid 8-step via subprocess.

Measured performance (RTX 3080, profile 5 = VerylowRAM_LowVRAM, int8 T5):
  VRAM peak : 5407 MiB  (CausVid LoRA, vs 9917 MiB native)
  Per-clip  : ~226s (3m46s) for 5s / 81f / 832×480

Replaces native wan.WanT2V (40 min / 30 steps) with Wan2GP + CausVid (3m46s / 8 steps).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from hevi.gpu import VRAM_WAN_LOCAL, scheduler

logger = logging.getLogger(__name__)

_wan2gp_env = os.environ.get("WAN2GP_DIR", "")
_WAN2GP_DIR = Path(_wan2gp_env) if _wan2gp_env else Path.home() / "Wan2GP"
_WAN2GP_PYTHON = _WAN2GP_DIR / "venv_wan/bin/python"
_WAN2GP_SCRIPT = _WAN2GP_DIR / "wgp.py"
_CAUSVID_LORA = "Wan21_CausVid_bidirect2_T2V_1_3B_lora_rank32.safetensors"

_DEFAULT_SIZE = (832, 480)   # 480P 16:9 (W×H)
_DEFAULT_FRAMES = 81          # ~5s @ 16fps
# Generous ceiling: a clip is ~226s; a >30min run means wgp.py has hung and is
# holding the GPU scheduler lock, starving every other local task. Kill it.
_WAN_TIMEOUT_S = 1800


def _seed_for(output_path: Path) -> int:
    """Derive a deterministic seed from the output filename.

    omodul writes shot variants/retries to distinct paths (shot_0001_v0.mp4 vs
    shot_0001_v1.mp4). A hardcoded seed made every variant byte-identical —
    wasting 2x compute and making consistency-selection meaningless. Deriving the
    seed from the filename keeps generation reproducible while making variants
    genuinely different.
    """
    digest = hashlib.sha256(output_path.stem.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)

# Model files that wgp.py loads for T2V-1.3B (profile 5).
# Pre-warming ensures they're in OS page cache before the subprocess starts,
# preventing the 59-min cold-load penalty when cache is evicted under memory pressure.
# Combined size ~11.9 GB; at 1.3 GB/s clean disk ≈ 9s. If already cached: <1s.
_WAN_CACHE_FILES: list[Path] = [
    _WAN2GP_DIR / "ckpts/umt5-xxl/models_t5_umt5-xxl-enc-quanto_int8.safetensors",  # 6.3 GB
    _WAN2GP_DIR / "ckpts/wan2.1_text2video_1.3B_mbf16.safetensors",  # 2.7 GB
    _WAN2GP_DIR
    / "ckpts/xlm-roberta-large/models_clip_open-clip-xlm-roberta-large-vit-huge-14-bf16.safetensors",  # noqa: E501
    _WAN2GP_DIR / "ckpts/Wan2.1_VAE.safetensors",  # 485 MB
]
_PREWARM_CHUNK = 64 * 1024 * 1024  # 64 MB — balances syscall overhead vs responsiveness


def _read_file_to_cache(path: Path) -> float:
    """Read file sequentially to populate OS page cache. Returns elapsed seconds."""
    t0 = time.monotonic()
    with open(path, "rb") as f:
        while f.read(_PREWARM_CHUNK):
            pass
    return time.monotonic() - t0


async def prewarm_wan_cache() -> None:
    """Pre-warm Wan2GP model files into OS page cache.

    Call before acquiring GPU scheduler lock so there is no I/O competition
    with an active Wan2GP subprocess or Ollama. If files are already cached
    (common between shots) the reads return from RAM in <1 second total.
    """
    for model_file in _WAN_CACHE_FILES:
        if not model_file.exists():
            continue
        size_mb = model_file.stat().st_size / 1024 / 1024
        elapsed = await asyncio.to_thread(_read_file_to_cache, model_file)
        speed_mbs = size_mb / max(elapsed, 0.001)
        logger.info(
            "wan_local: cache-warm %s  %.0f MB in %.1fs (%.0f MB/s)",
            model_file.name, size_mb, elapsed, speed_mbs,
        )


async def wan_local_generate(
    *,
    prompt: str,
    output_path: Path | str,
    size: tuple[int, int] = _DEFAULT_SIZE,
    frame_num: int = _DEFAULT_FRAMES,
    seed: int | None = None,
    **_: Any,
) -> Path:
    """Generate a 5s clip via Wan2GP + CausVid LoRA (8 steps, ~3m46s).

    Pre-warms model files into OS page cache before acquiring the GPU scheduler
    lock. This prevents the 59-min cold-load penalty when page cache is evicted
    under memory pressure (observed when T5 6.3 GB was re-read at 1.9 MB/s due
    to I/O thrashing from concurrent Ollama + swap). Clean disk reads at 1.3 GB/s
    warm all 11.9 GB of model weights in ~9s instead.

    Holds GPU scheduler lock for full subprocess duration so qwen/duix cannot
    overlap. Subprocess (wgp.py) self-manages mmgp offloading internally.

    Returns the resolved output Path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if seed is None:
        seed = _seed_for(output_path)

    # Pre-warm before acquiring GPU lock — no subprocess running yet, I/O is free.
    await prewarm_wan_cache()

    async with scheduler.acquire(VRAM_WAN_LOCAL):
        return await _run_wgp(
            prompt=prompt,
            output_path=output_path,
            size=size,
            frame_num=frame_num,
            seed=seed,
        )


async def _run_wgp(
    *,
    prompt: str,
    output_path: Path,
    size: tuple[int, int],
    frame_num: int,
    seed: int,
) -> Path:
    with tempfile.TemporaryDirectory(prefix="wan_gen_") as tmp_dir:
        task_json = Path(tmp_dir) / "task.json"
        out_dir = Path(tmp_dir) / "out"
        out_dir.mkdir()

        task_json.write_text(
            json.dumps({
                "model_type": "t2v_1.3B",
                "prompt": prompt,
                "negative_prompt": "blurry, distorted, low quality",
                "width": size[0],
                "height": size[1],
                "video_length": frame_num,
                "num_inference_steps": 8,
                "guidance_scale": 1,
                "guidance_phases": 1,
                "sample_solver": "causvid",
                "flow_shift": 2,
                "activated_loras": [_CAUSVID_LORA],
                "loras_multipliers": "1",
                "seed": seed,
            }, ensure_ascii=False),
            encoding="utf-8",
        )

        cmd = [
            str(_WAN2GP_PYTHON),
            str(_WAN2GP_SCRIPT),
            "--t2v-1-3B", "--profile", "5",
            "--process", str(task_json),
            "--output-dir", str(out_dir),
        ]

        logger.info("wan_local: starting Wan2GP+CausVid subprocess (8 steps)")
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(_WAN2GP_DIR),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        async def _consume_and_wait() -> int:
            assert proc.stdout is not None
            async for line in proc.stdout:
                txt = line.decode(errors="replace").rstrip()
                if txt:
                    logger.debug("wgp: %s", txt)
            return await proc.wait()

        try:
            rc = await asyncio.wait_for(_consume_and_wait(), timeout=_WAN_TIMEOUT_S)
        except (TimeoutError, asyncio.CancelledError):
            # Never leave a hung/orphaned subprocess holding the GPU scheduler lock.
            logger.error("wan_local: subprocess timed out/cancelled — killing wgp.py")
            proc.kill()
            await proc.wait()
            raise
        if rc != 0:
            raise RuntimeError(f"Wan2GP subprocess failed (exit {rc})")

        videos = sorted(out_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
        if not videos:
            raise RuntimeError("Wan2GP produced no output video")

        shutil.move(str(videos[-1]), str(output_path))
        logger.info("wan_local: saved to %s", output_path)
        return output_path
