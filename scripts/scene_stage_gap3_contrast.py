#!/usr/bin/env python
"""SPEC-004 断链#3 视觉对照(待触发脚本,默认零花费 dry-run)。

问题:`DesignScene.environment/lighting/mood` 此前从桥接层到 L6 渲染 prompt 全程零消费——
画面里根本没有场景。阶段 0.5 已把它接进 `_local_kf_prompt`(空间项排相貌前)。本脚本做
**单变量对照**:同一角色 canon、同一情绪/动作,唯一差异是 scene_space 空 vs 非空,各出一张
关键帧,肉眼/VLM 对比"修完后画面里是否真的出现了场景"。

设计取舍:直接调 `_edit_keyframe` 两次(不走整条 build_frame_manifest_avatar),把变量收窄到
只有 local_prompt 的场景项——排除对白/时长/装配等无关噪声。

用法:
  # 零花费:只打印两条 prompt 的差异(证明字符串接线,不生成图片)
  uv run python scripts/scene_stage_gap3_contrast.py

  # 本地 sdxl(免费,需 GPU 在总线上——按 memory,RTX 3080 常掉线,先 nvidia-smi 确认)
  uv run python scripts/scene_stage_gap3_contrast.py --engine local --gen \
      --ref-image path/to/portrait.png

  # 云端 qwen-image-edit(真实花费,单位数美元级,需显式 --real)
  uv run python scripts/scene_stage_gap3_contrast.py --engine cloud --gen --real \
      --ref-image path/to/portrait.png

无 --ref-image 时会用 qwen_image_generate 现生一张 canon(也算真实花费,需 --real)。
产物落 output/scene_stage_gap3/{without,with}_scene.png。
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

# 单变量:场景空间描述(修复后应出现在 with_scene 帧里,without_scene 帧里没有)
_STYLE = "电影感写实,暖色调"
_APPEARANCE = "中年男子,粗布长衫,面容沧桑"
_EMOTION = "神情凝重"
_ACTION = "拱手作揖"
_SCENE_SPACE = "破败的乡野客栈内,昏黄油灯,墙皮剥落,梁上挂满蛛网,压抑清冷"


async def _run(args: argparse.Namespace) -> None:
    from hevi.tongjian.scene_render_avatar import _local_kf_prompt

    out_dir = Path("output/scene_stage_gap3")
    out_dir.mkdir(parents=True, exist_ok=True)

    prompt_without = _local_kf_prompt(_STYLE, _APPEARANCE, _EMOTION, _ACTION, scene_space="")
    prompt_with = _local_kf_prompt(_STYLE, _APPEARANCE, _EMOTION, _ACTION, scene_space=_SCENE_SPACE)

    print("=" * 72)
    print("SPEC-004 断链#3 单变量对照 —— 唯一差异是 scene_space")
    print("-" * 72)
    print(f"[without_scene] {prompt_without}")
    print(f"[with_scene   ] {prompt_with}")
    print("-" * 72)
    assert _SCENE_SPACE in prompt_with and _SCENE_SPACE not in prompt_without
    assert prompt_with.index(_SCENE_SPACE) < prompt_with.index(_APPEARANCE), "空间须在相貌前"
    print("✅ 字符串接线成立:场景空间已进 with_scene 的 prompt,且排在相貌前(§F.1 口径)")

    if not args.gen:
        print("\n(dry-run:未生成图片。加 --gen 生成对照关键帧;云端/现生 canon 需 --real)")
        return

    # ── 生成对照关键帧(真实算力/花费)──────────────────────────────────────
    from hevi.tongjian.scene_render_avatar import _canonical, _edit_keyframe

    needs_spend = args.engine == "cloud" or not args.ref_image
    if needs_spend and not args.real:
        raise SystemExit(
            "生成会产生真实花费(云端 edit 或现生 canon)——请显式加 --real 确认预算后再跑。"
        )

    canon = await _canonical(
        "contrast_char", _APPEARANCE, out_dir, _STYLE, ref_image=args.ref_image
    )
    print(f"canon: {canon}")

    for tag, local_prompt in (("without_scene", prompt_without), ("with_scene", prompt_with)):
        out = out_dir / f"{tag}.png"
        # 每张都强制重生成(否则第二张会命中第一张的缓存,失去对照意义)
        if out.exists():
            out.unlink()
        await _edit_keyframe(
            image_path=canon,
            instruction=f"{_EMOTION},动作:{_ACTION}",  # cloud edit 路径不含场景(断链本体)
            output_path=out,
            fallback_from=canon,
            engine=args.engine,
            local_prompt=local_prompt,
            ip_adapter_image=canon,
            size=(720, 1280),
        )
        print(f"  → {tag}: {out} ({out.stat().st_size if out.exists() else 0} bytes)")

    print("\n对照产物已出。请肉眼对比:with_scene 应可见客栈/油灯/破败环境,without_scene 不应有。")
    print("(可选)Tier1 VLM 抽帧断言场景元素出现——留给 G-S1 统一客观化,见 SPEC-004 §6。")


def main() -> None:
    p = argparse.ArgumentParser(description="SPEC-004 断链#3 视觉对照")
    p.add_argument("--engine", choices=("local", "cloud"), default="local")
    p.add_argument("--gen", action="store_true", help="真生成对照关键帧(否则只打印 prompt 差异)")
    p.add_argument("--real", action="store_true", help="确认真实花费(云端 edit / 现生 canon)")
    p.add_argument("--ref-image", default=None, help="复用已有角色肖像(免费 canon,避免现生)")
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
