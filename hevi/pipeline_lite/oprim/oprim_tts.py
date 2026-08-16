"""oprim:oprim_tts —— Lite 管道旁白合成原子能力(绝对无状态)。

只负责:把 cues 合成一条 master_audio.wav, 返回文件路径。不涉及状态写入。

双通道(自动降级, 严格失败):
  1. 首选 hevi-gen-engine CosyVoice HTTP 客户端(hevi/audio/cosyvoice_service):
     逐段合成 → ffmpeg apad 间隔拼接 → master_audio.wav;
  2. 引擎不可用/无模型(AiEngineError)→ 降级 edge-tts(oprim.edge_tts_synthesize
     单次调用整条脚本, edge 自带句间自然停顿);
  3. 两路全失败 → 抛 RuntimeError, 由 omodul 决定静音直出还是失败。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hevi.audio.cosyvoice_service import AiEngineError, cosyvoice_synthesize
from hevi.pipeline_lite.schemas import LiteCue

logger = logging.getLogger(__name__)

_EDGE_GAP_S = 0.4


async def synthesize_master_audio(
    cues: list[LiteCue],
    output_path: Path | str,
    *,
    language: str = "zh",
    gap_s: float = _EDGE_GAP_S,
    _cosyvoice: Callable[..., Any] | None = None,
    _edge_synthesize: Callable[..., Any] | None = None,
) -> Path:
    """合成一条完整旁白 master_audio.wav(逐段 + 间隔拼接)。

    ``_cosyvoice`` / ``_edge_synthesize`` 为测试注入钩子; 缺省走真实通道。
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    cosyvoice = _cosyvoice or cosyvoice_synthesize
    edge_synthesize = _edge_synthesize

    # ── 通道 1: AI 引擎 CosyVoice 逐段合成 ─────────────────
    try:
        segments: list[Path] = []
        for index, cue in enumerate(cues):
            seg = output.parent / f"_tts_seg_{index:03d}.wav"
            await cosyvoice(
                script=[SimpleNamespace(text=cue.narration, speaker_id="host")],
                output_path=seg,
            )
            if not seg.exists() or seg.stat().st_size == 0:
                raise AiEngineError(f"引擎未产出段音频: {seg}")
            segments.append(seg)
        return await _concat_with_gap(segments, output, gap_s=gap_s)
    except AiEngineError as exc:
        logger.info("ai-engine CosyVoice 不可用, 降级 edge-tts: %s", exc)

    # ── 通道 2: edge-tts 单次整条合成 ──────────────────────
    if edge_synthesize is None:
        try:
            from oprim import edge_tts_synthesize as _default_edge

            edge_synthesize = _default_edge
        except ImportError as exc:  # pragma: no cover - 依赖缺失
            raise RuntimeError("edge-tts 未安装, 且 AI 引擎不可用") from exc

    script = [SimpleNamespace(text=cue.narration, speaker_id="host") for cue in cues]
    try:
        await edge_synthesize(
            script=script,
            output_path=output,
            language=language,
        )
    except Exception as exc:
        raise RuntimeError(f"TTS 全部通道失败: {exc}") from exc

    if not output.exists() or output.stat().st_size == 0:
        raise RuntimeError(f"TTS 未产出音频: {output}")
    return output


async def _concat_with_gap(segments: list[Path], output: Path, *, gap_s: float) -> Path:
    """把各段 wav 用 ffmpeg apad 间隔拼接(每段末尾补 gap_s 静音)。"""
    if not shutil.which("ffmpeg"):
        # 无 ffmpeg: 单段直接复制, 多段报错(不静默丢段)。
        if len(segments) == 1:
            segments[0].replace(output)
            return output
        raise RuntimeError("ffmpeg 缺失, 无法拼接多段音频")
    if len(segments) == 1:
        segments[0].replace(output)
        return output

    inputs: list[str] = []
    filters: list[str] = []
    for index, seg in enumerate(segments):
        inputs += ["-i", str(seg)]
        if index < len(segments) - 1:
            filters.append(f"[{index}:a]apad=pad_dur={gap_s}[a{index}]")
        else:
            filters.append(f"[{index}:a]anull[a{index}]")
    concat_inputs = "".join(f"[a{i}]" for i in range(len(segments)))
    filters.append(f"{concat_inputs}concat=n={len(segments)}:v=0:a=1[out]")

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[out]",
        "-c:a", "pcm_s16le",
        "-ar", "24000",
        "-ac", "1",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"音频拼接失败: {result.stderr[-300:]}")
    if not output.exists() or output.stat().st_size == 0:
        raise RuntimeError("音频拼接未产出文件")
    return output


__all__ = ["synthesize_master_audio"]
