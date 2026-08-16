"""本地 i2v 通路验证脚本(待 GPU 余量 ≥6GB 时运行,共享主机勿强跑)。

链路: sdxl_local 出关键帧(构图可控)→ wan_local_generate(reference_image=...)
走 Wan2GP VACE 图生视频 → 真生成剪辑(画面构图由本地生成的图约束)。

用法:
    uv run python scripts/wan_i2v_verify.py            # --dry-run 先探 GPU
    uv run python scripts/wan_i2v_verify.py --real     # GPU 余量够时真跑

前置: ~/Wan2GP(含 wan2.1_Vace_1_3B_module.safetensors,已确认在 ckpts/)。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _gpu_headroom_mb() -> int:
    """当前 GPU 可用显存(MiB)。"""
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10,
    )
    used, total = (int(x) for x in out.stdout.strip().split(","))
    return total - used


async def main(real: bool) -> None:
    headroom = _gpu_headroom_mb()
    print(f"GPU 余量: {headroom} MiB (wan_local 需 ~5407 MiB)")
    if headroom < 6000:
        print("⚠ 余量不足,跳过。共享主机其他进程占着 GPU,勿杀(STATUS.md 纪律)。")
        return

    out_dir = Path("output/wan_i2v_verify")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. sdxl_local 出关键帧(构图可控:山洞 + 火光)
    from hevi.image.sdxl_local_service import sdxl_local_generate

    keyframe = out_dir / "keyframe_cave.png"
    if not keyframe.exists():
        print(f"[{time.strftime('%H:%M:%S')}] SDXL 出关键帧 …")
        await sdxl_local_generate(
            prompt=(
                "interior of a prehistoric limestone cave at Zhoukoudian, a campfire "
                "burning in the center, warm orange firelight on rough stone walls, "
                "dark shadows, cinematic, photorealistic"
            ),
            negative_prompt="text, watermark, people, modern objects",
            width=832,
            height=480,
            output_path=keyframe,
        )
        print(f"[{time.strftime('%H:%M:%S')}] 关键帧 → {keyframe}")

    # 2. wan VACE i2v:参考帧约束的真生成剪辑
    from hevi.video.wan_local_service import wan_local_generate

    print(f"[{time.strftime('%H:%M:%S')}] Wan VACE i2v(参考关键帧,~3-4min)…")
    t0 = time.monotonic()
    clip = await wan_local_generate(
        prompt=(
            "slow camera push-in towards the campfire, embers rising and drifting, "
            "firelight flickering and pulsing on the cave walls, subtle smoke, "
            "cinematic, atmospheric"
        ),
        output_path=out_dir / "cave_i2v.mp4",
        size=(832, 480),
        frame_num=81,
        reference_image=keyframe,
    )
    print(f"[{time.strftime('%H:%M:%S')}] ✅ i2v 剪辑 → {clip} ({(time.monotonic()-t0)/60:.1f}min)")

    result = {"keyframe": str(keyframe), "clip": str(clip), "ok": True}
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    (out_dir / "result.json").write_text(payload, encoding="utf-8")
    print("验证完成,产物见 output/wan_i2v_verify/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="GPU 余量够时真跑")
    args = parser.parse_args()
    asyncio.run(main(real=args.real))
