"""Wan 2.1 T2V-1.3B local inference — Wan2GP + CausVid 8-step via subprocess.

Measured performance (RTX 3080, profile 5 = VerylowRAM_LowVRAM, int8 T5):
  VRAM peak : 5407 MiB  (CausVid LoRA, vs 9917 MiB native)
  Per-clip  : ~226s (3m46s) for 5s / 81f / 832×480

Replaces native wan.WanT2V (40 min / 30 steps) with Wan2GP + CausVid (3m46s / 8 steps).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from hevi.gpu import VRAM_WAN_LOCAL, scheduler

logger = logging.getLogger(__name__)

_WAN2GP_DIR = Path.home() / "Wan2GP"
_WAN2GP_PYTHON = _WAN2GP_DIR / "venv_wan/bin/python"
_WAN2GP_SCRIPT = _WAN2GP_DIR / "wgp.py"
_CAUSVID_LORA = "Wan21_CausVid_bidirect2_T2V_1_3B_lora_rank32.safetensors"

_DEFAULT_SIZE = (832, 480)   # 480P 16:9 (W×H)
_DEFAULT_FRAMES = 81          # ~5s @ 16fps


async def wan_local_generate(
    *,
    prompt: str,
    output_path: Path | str,
    size: tuple[int, int] = _DEFAULT_SIZE,
    frame_num: int = _DEFAULT_FRAMES,
    seed: int = 42,
    **_: Any,
) -> Path:
    """Generate a 5s clip via Wan2GP + CausVid LoRA (8 steps, ~3m46s).

    Holds GPU scheduler lock for full subprocess duration so qwen/duix cannot
    overlap. Subprocess (wgp.py) self-manages mmgp offloading internally.

    Returns the resolved output Path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

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

        assert proc.stdout is not None
        async for line in proc.stdout:
            txt = line.decode(errors="replace").rstrip()
            if txt:
                logger.debug("wgp: %s", txt)

        rc = await proc.wait()
        if rc != 0:
            raise RuntimeError(f"Wan2GP subprocess failed (exit {rc})")

        videos = sorted(out_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
        if not videos:
            raise RuntimeError("Wan2GP produced no output video")

        shutil.move(str(videos[-1]), str(output_path))
        logger.info("wan_local: saved to %s", output_path)
        return output_path
