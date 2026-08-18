"""quick assemble —— 轻量装配(脚本 → 音频 → 合成, 可选)。

真实合成依赖现有 TTS/ffmpeg 设施; 本模块提供注入式骨架:
  - `assemble_quick(plan, output_dir, cfg)`: 逐行 TTS → 音频段, 轻量合成视频
  - TTS 合成器可注入(默认尝试 hevi.audio.audio_router 的正式档)

未配置 TTS 时降级: 只写 plan + notes, 不抛(omodul 失败契约)。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from hevi.quick.service import QuickPlan, QuickVideoConfig

logger = logging.getLogger(__name__)

# TTS 注入点: (text, output_path, cfg) -> Path(音频文件)
TTSSynth = Callable[[str, Path, QuickVideoConfig], Awaitable[Path]]


async def _default_tts(text: str, output_path: Path, cfg: QuickVideoConfig) -> Path:
    """默认 TTS: 走 hevi.audio.audio_router 的正式档(cosyvoice/f5/voicebox)。"""
    from hevi.audio.audio_router import AudioRoutingError, _synthesize_formal

    await _synthesize_formal(
        text=text,
        output_path=output_path,
        voice="zh-CN-XiaoxiaoNeural",
        instruct="clear, energetic short-video narration",
    )
    return output_path


async def assemble_quick(
    plan: QuickPlan,
    output_dir: Path,
    cfg: QuickVideoConfig,
    *,
    tts_synth: TTSSynth | None = None,
) -> Path:
    """脚本逐行 TTS → 音频段清单; 合成视频默认跳过(返回装配清单), 见 notes。"""
    synth = tts_synth or _default_tts
    output_dir.mkdir(parents=True, exist_ok=True)
    tts_segments: list[dict[str, Any]] = []
    for i, line in enumerate(plan.script_lines):
        seg_path = output_dir / f"seg_{i:02d}.mp3"
        try:
            await synth(line["text"], seg_path, cfg)
            tts_segments.append(
                {"index": i, "text": line["text"], "audio": str(seg_path)}
            )
        except Exception as exc:
            logger.warning("quick tts segment %d failed: %s", i, exc)
            plan.notes.append(f"tts segment {i} failed: {exc}")
    plan.tts_segments = tts_segments
    if not tts_segments:
        raise RuntimeError("no tts segments produced; cannot assemble")
    # 视频合成: 由上游 explainer/assembly 消费 tts_segments + materials。
    # 此处产出装配 manifest 供后续链路使用(合成本身走既有重流程)。
    from hevi.quick.service import QuickPlan as _QP  # noqa: F401

    manifest = output_dir / f"{cfg.output_name}.assembly.json"
    manifest.write_text(
        __import__("json").dumps(
            {
                "topic": plan.topic,
                "aspect": cfg.aspect,
                "tts_segments": tts_segments,
                "materials": plan.materials,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    plan.notes.append(
        "装配清单已产出(assembly.json); 视频合成由上游 explainer/assembly 消费。"
    )
    return manifest
