"""SVFACTORY capabilities registration on Hevi unified registry.

Capabilities exposed:
- ``svfactory.montage``: Asset-folder deterministic auto-montage.
- ``svfactory.render``: Local CPU episode render + kids_gate validation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import Capability, CapabilityResult, register
from hevi.svfactory.montage import auto_montage_segments
from hevi.svfactory.renderer import render_svfactory_episode


def _render_svfactory_montage(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    asset_dir = params.get("asset_dir")
    if not asset_dir:
        raise RuntimeError("svfactory.montage 需要 asset_dir")
    res = auto_montage_segments(asset_dir, duration, seed=seed, aspect=aspect)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "montage_segments.json"
    p.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(duration_s=res["total_duration"], qa=res)


register(
    Capability(
        name="svfactory.montage",
        kind="shot",
        aspects=["16:9", "9:16"],
        params_schema={"type": "object", "required": ["asset_dir"]},
        cpu_cost_hint=0.1,
        render=_render_svfactory_montage,
        description="素材文件夹确定性自动混剪（按时长选段、裁画幅、防连击、seed 去重）",
        line="svfactory",
    )
)


def _render_svfactory_episode_cap(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    script_text = params.get("script_text", "宝宝快看，开心学习每一天！")
    asset_dir = params.get("asset_dir")
    out_path = out_dir / "episode.mp4"
    manifest = asyncio_run(
        render_svfactory_episode(
            script_text=script_text,
            asset_dir=asset_dir,
            output_path=out_path,
            aspect=aspect,
            seed=seed,
            voice=params.get("voice", "zh_CN-huayan-medium.onnx"),
            subtitle_style=params.get("subtitle_style", "large_white"),
            bgm_path=params.get("bgm_path"),
        )
    )
    return CapabilityResult(
        mp4=str(out_path),
        duration_s=manifest["duration"],
        qa=manifest["gate_report"],
    )


def asyncio_run(coro):
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # run synchronously via new thread if in running loop
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


register(
    Capability(
        name="svfactory.render",
        kind="shot",
        aspects=["16:9", "9:16"],
        params_schema={"type": "object", "required": ["script_text"]},
        cpu_cost_hint=2.0,
        render=_render_svfactory_episode_cap,
        description="本地 CPU 串行短片渲染（Piper TTS + 混剪 + libass 幼儿大字描边字幕 + kids_gate）。输入为脚本文本+素材目录的真实素材混剪，与 kids.render_local（manifest 驱动验收片）无关",
        line="svfactory",
    )
)
