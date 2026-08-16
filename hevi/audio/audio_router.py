"""🚨 v9.0: 多模型音频路由中枢 —— 双音色情绪播报 + TTS 无缝拼接。

遍历 cues，根据 `audio_style`（formal / conversational）分别调用：
- formal  → CosyVoice（权威播音风格）
- conversational → ChatTTS 或 Voicebox（松弛口语化，支持 [laugh]、[uv_break] 等控制符）

生成的多个音频片段通过 pydub / FFmpeg 顺序拼接为唯一的 Master Audio。

使用方式：
    from hevi.audio.audio_router import route_and_stitch_master_audio
    
    master_path = await route_and_stitch_master_audio(
        cues=[...],       # list of ExplainerCue with text/audio_style fields
        output_dir=Path("output/audio"),
        voice="cosyvoice_default",
    )
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Literal

from oprim import probe_duration

logger = logging.getLogger(__name__)

AudioStyle = Literal["formal", "conversational"]


class AudioRoutingError(RuntimeError):
    """音频路由/拼接失败。"""


def _infer_audio_style(text: str) -> AudioStyle:
    """Heuristic to infer audio_style from text content.

    Used as a fallback when the cue does not explicitly set audio_style.
    - Text containing colloquial markers like 「啦」「呢」「嘛」「哈哈」「好吧」
      → conversational
    - Otherwise → formal (default).
    """
    conversational_markers = ["啦", "呢", "嘛", "哈", "嘿", "哇", "哦", "嗯", "好吧",
                              "嘿嘿", "哈哈哈", "哎呀", "其实", "说白了", "要知道"]
    for marker in conversational_markers:
        if marker in text:
            return "conversational"
    return "formal"


async def route_single_cue(
    *,
    cue_text: str,
    cue_style: AudioStyle | None,
    output_path: Path,
    voice: str,
    instruct: str | None = None,
    **tts_kwargs: Any,
) -> Path:
    """Route one cue to the correct TTS backend based on audio_style."""
    style = cue_style or _infer_audio_style(cue_text)
    
    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if style == "conversational":
            # Try Voicebox first (supports emotion/instruct)
            result_path = await _synthesize_conversational(
                text=cue_text,
                output_path=output_path,
                instruct=instruct,
                **tts_kwargs,
            )
        else:
            # Formal → CosyVoice or default Voicebox profile
            result_path = await _synthesize_formal(
                text=cue_text,
                output_path=output_path,
                voice=voice,
                instruct=instruct,
                **tts_kwargs,
            )
        
        if not result_path.exists() or result_path.stat().st_size < 100:
            raise AudioRoutingError(f"Synthesis produced empty file: {result_path}")
        return result_path

    except Exception as exc:
        logger.warning("TTS routing failed for cue style=%s: %s", style, exc)
        # Fallback: always attempt voicebox
        fallback = await _synthesize_formal(
            text=cue_text,
            output_path=output_path,
            voice=voice,
            **tts_kwargs,
        )
        if fallback.exists():
            return fallback
        raise AudioRoutingError(f"All TTS backends failed: {exc}") from exc


async def _synthesize_conversational(
    *, text: str, output_path: Path, instruct: str | None, **_kw: Any
) -> Path:
    """Conversational synthesis — supports ChatTTS-style control tokens.

    Voicebox handles emotion tags like [laugh], [uv_break], [breath] natively.
    For raw ChatTTS, this delegates to the oprim.chattts_call entry point.
    """
    provider = os.getenv("HEVI_TTS_CONVERSATIONAL_PROVIDER", "voicebox").strip().lower()

    if provider == "chattts":
        try:
            from oprim import chattts_call as _chattts_api
            result = _chattts_api(text=text, output_path=str(output_path))
            return Path(result) if isinstance(result, str) else output_path
        except ImportError:
            logger.debug("ChatTTS oprim not installed; falling back to voicebox")

    # Default: Voicebox with emotional instruction
    from hevi.explainer.voicebox_client import synthesize as vb_synthesize
    await vb_synthesize(text, output_path, instruct=instruct or "casual, conversational")
    return output_path


async def _synthesize_formal(
    *, text: str, output_path: Path, voice: str, instruct: str | None, **_kw: Any
) -> Path:
    """Formal synthesis — CosyVoice authoritative broadcast style."""
    provider = os.getenv("HEVI_TTS_FORMAL_PROVIDER", "cosyvoice").strip().lower()

    if provider == "cosyvoice":
        from types import SimpleNamespace

        from hevi.audio.cosyvoice_service import cosyvoice_synthesize
        await cosyvoice_synthesize(
            script=[SimpleNamespace(text=text)],
            output_path=output_path,
        )
        return output_path

    if provider == "voicebox":
        from hevi.explainer.voicebox_client import synthesize as vb_synthesize
        await vb_synthesize(text, output_path, instruct=instruct or "professional, clear narration")
        return output_path

    # Last resort: edge-tts
    try:
        import edge_tts
        comm = edge_tts.Communicate(text, voice)
        await comm.save(str(output_path))
        return output_path
    except ImportError:
        pass

    raise AudioRoutingError(f"No formal TTS backend available for provider={provider}")


async def route_and_stitch_master_audio(
    cues: list[Any],
    output_dir: Path,
    *,
    voice: str = "Dylan",
    aspect_ratio: str = "9:16",
    stitch_format: str = "wav",
) -> dict[str, Any]:
    """🚨 Core orchestrator: Route each cue → TTS, then stitch into one master.

    Returns:
        {
            "master_path": Path,           # Stitched master WAV/MP3
            "segment_paths": [Path, ...],  # Individual cue audio files
            "total_duration_s": float,     # Combined duration
            "manifest": list[dict],        # Per-segment metadata (for Remotion)
        }
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    segment_paths: list[Path] = []
    manifest_segments: list[dict[str, Any]] = []
    cursor_sec = 0.0

    for idx, cue in enumerate(cues):
        cue_text = getattr(cue, "text", "") or ""
        cue_style = getattr(cue, "audio_style", None)
        cue_id = getattr(cue, "id", f"cue-{idx + 1}")
        getattr(cue, "start_sec", cursor_sec)
        cue_captions = getattr(cue, "captions", [])

        suffix = stitch_format or ("mp3" if "edge_tts" in voice else "wav")
        seg_path = output_dir / f"{cue_id}.{suffix}"

        try:
            routed = await route_single_cue(
                cue_text=cue_text,
                cue_style=cue_style,
                output_path=seg_path,
                voice=voice,
            )
            segment_paths.append(routed)
            dur = probe_duration(routed)  # type: ignore[no-untyped-call]
        except Exception as e:
            logger.error("Failed to route cue %s: %s", cue_id, e)
            continue

        manifest_segments.append({
            "id": cue_id,
            "text": cue_text,
            "audio_file": str(routed),
            "duration_sec": round(dur, 3),
            "start_sec": round(cursor_sec, 3),
            "captions": cue_captions if isinstance(cue_captions, list) else [],
            "visual_type": getattr(cue, "visual_type", "voiceover"),
            "visual_config": getattr(cue, "visual_config", {}),
            "layout_mode": getattr(cue, "layout_mode", "fullscreen"),
            "keywords": getattr(cue, "keywords", []),
        })
        cursor_sec += dur

    # Stitch all segments into master audio
    master_path = output_dir / f"master_audio.{stitch_format}"
    master_dur = cursor_sec

    if len(segment_paths) > 1:
        concat_list = output_dir / "_concat_list.txt"
        lines = [f"file '{sp.resolve()}'" for sp in segment_paths]
        concat_list.write_text("\n".join(lines))

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c:a", "pcm_s16le" if stitch_format == "wav" else "aac",
            "-b:a", "192k" if stitch_format != "wav" else "0",
            "-ar", "48000",
            "-ac", "1",
            str(master_path),
        ]
        await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        concat_list.unlink(missing_ok=True)

    if not master_path.exists() and segment_paths:
        # Copy the single segment as master
        import shutil
        shutil.copy2(segment_paths[0], master_path)

    return {
        "master_path": master_path,
        "segment_paths": segment_paths,
        "total_duration_s": round(master_dur, 3),
        "manifest": manifest_segments,
    }


# Import at bottom to avoid circular deps
