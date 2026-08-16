"""H3 w4a8_mixed 冒烟:真实 ComfyUI 512² t2v 一镜,验证 UNETLoader 新模型路径。

零花费(本地 GPU)。跑通 = 模板/模型/客户端全链路 OK。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hevi.providers.h3_local.comfy_client import (  # noqa: E402
    ComfyClient,
    h3_length_for_duration,
)


async def main() -> None:
    client = ComfyClient(base_url="http://127.0.0.1:8188", serial=True)
    out = Path("/data/soffy/projects/hevi/output/h3_e2e_test/w4a8_smoke.mp4")
    length = h3_length_for_duration(5.0)  # 124 帧
    print(f"length={length} (124 期望)")
    result = await client.run_workflow(
        client.build_workflow(
            client.load_workflow("h3_w4a8_zh.json"),
            prompt="【场景】雨夜街角。昏黄路灯下,一个撑着红伞的行人缓步走过积水路面。",
            width=512,
            height=512,
            length=length,
            seed=20260816,
            output_prefix="w4a8_smoke",
            ref_images=[],
            extra_fills={
                "__UNET_GGUF__": "minimax_h3_fl2va_pruned_w4a8_mixed.safetensors",
                "__CLIP_GGUF__": "qwen3vl-32B-MiniMax-H3-Q2_K.gguf",
                "__VIDEO_VAE__": "minimax_h3_video_vae_fp16.safetensors",
                "__AUDIO_VAE__": "minimax_h3_audio_vae_fp32.safetensors",
            },
        ),
        output_path=out,
        timeout_s=1800,
    )
    print(f"OK {out} {out.stat().st_size} bytes")


if __name__ == "__main__":
    asyncio.run(main())
