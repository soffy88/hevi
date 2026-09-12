"""E2 配音 —— CosyVoice 逐段生成配音 + 时长字幕,可选 edge-tts 降级。

默认通过 CosyVoice 公共原语调用本地情绪音色；设置
HEVI_EXPLAINER_TTS_PROVIDER=voicebox 可使用 Voicebox，edge_tts 可回到旧通道。edge-tts 词级时间戳
由 oprim.edge_tts_word_boundary 原子提供(3O §2 Task 2.2 单源收敛),按标点把
词级时间戳聚合成"整句字幕"的起止时间——聚合逻辑靠长度对齐(累计消耗字符数),
不做文本内容比对,足够稳健且不依赖 edge-tts 保留标点(它不保留)。

时长以 oprim.probe_duration(ffprobe)实测的真实文件时长为准,不用最后一个词的
end 时间——后者会截掉尾部静音/呼吸,拼进 Remotion Sequence 的 durationInFrames
会真的把配音尾巴切掉。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from oprim import edge_tts_word_boundary, probe_duration

from hevi.audio.asr_verify import verify_and_retry
from hevi.audio.cosyvoice_service import cosyvoice_synthesize
from hevi.explainer.asr_verify import AsrVerificationError, asr_verification_enabled, verify_audio
from hevi.explainer.schemas import CaptionCue, ManifestSegment, Storyboard, validate_props
from hevi.explainer.voicebox_client import synthesize as synthesize_voicebox

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "Dylan"  # Voicebox Qwen3-TTS 中文预置音色；可用 VOICEBOX_PROFILE_ID 替换
DEFAULT_RATE = "-10%"  # 仅 edge_tts 使用；Voicebox 通过 instruct 控制表达
# edge_tts 需要 Microsoft 完整音色 ID(如 zh-CN-XiaoxiaoNeural),不能用 Voicebox 预设名。
# 这里按 provider 环境变量在 _provider_voice() 里解析,让同一条 explainer 代码在
# voicebox / edge_tts 两条通道上都能拿到各自合法的音色。
EDGE_TTS_DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
EDGE_TTS_DEFAULT_RATE = "+0%"  # edge_tts 语速;Voicebox 通过 instruct 控制表达

_CLAUSE_SPLIT_CHARS = [*list(",,。;;::!!??……~~“”\"'()()·"), r"\s+"]
_CLAUSE_SPLIT_RE = re.compile(
    "|".join(re.escape(c) if len(c) == 1 else c for c in _CLAUSE_SPLIT_CHARS)
)


class VoiceoverError(Exception):
    """配音合成失败(Voicebox/edge-tts 调用失败,或产物为空)。"""


def _clauses_of(text: str) -> list[str]:
    return [c for c in _CLAUSE_SPLIT_RE.split(text) if c.strip()]


async def _synthesize(
    text: str, out_path: Path, *, voice: str, rate: str, max_attempts: int = 5
) -> list[dict[str, Any]]:
    """3O §2 Task 2.2:委托 oprim.edge_tts_word_boundary 原子(单源),
    返回词级 WordBoundary 时间秒。edge_tts 偶发 "No audio was received"
    (服务端瞬断),重试后成功;5 次仍失败才抛 VoiceoverError。"""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = await edge_tts_word_boundary(  # type: ignore[no-untyped-call]
                text, voice=voice, rate=rate, output_path=out_path
            )
            return list(result["words"])
        except Exception as exc:
            last_exc = exc
            msg = str(exc)
            transient = (
                "No audio was received" in msg
                or "EOF" in msg
                or "connection" in msg.lower()
                or "reset" in msg.lower()
                or "timed out" in msg.lower()
            )
            if attempt >= max_attempts or not transient:
                raise
            logger.warning(
                "edge_tts 瞬断重试 %s/%s (%s): %s",
                attempt,
                max_attempts,
                out_path.name,
                exc,
            )
            await asyncio.sleep(min(2 ** attempt, 8))
    raise VoiceoverError(f"edge_tts 合成重试耗尽: {last_exc}") from last_exc


def _captions_from_words(text: str, words: list[dict[str, Any]]) -> list[CaptionCue]:
    clauses = _clauses_of(text)
    captions: list[CaptionCue] = []
    wi = 0
    for clause in clauses:
        target_len = len(clause)
        consumed = 0
        start_word = wi
        while wi < len(words) and consumed < target_len:
            consumed += len(words[wi]["text"])
            wi += 1
        if wi == start_word:
            continue
        captions.append(
            CaptionCue(text=clause, start=words[start_word]["start"], end=words[wi - 1]["end"])
        )
    return captions


def _captions_from_duration(text: str, duration: float) -> list[CaptionCue]:
    """Voicebox 没有 word boundary 时，按真实时长和分句字符权重生成字幕。"""
    clauses = _clauses_of(text)
    if not clauses or duration <= 0:
        return []
    weights = [max(len(clause), 1) for clause in clauses]
    total = sum(weights)
    cursor = 0.0
    captions: list[CaptionCue] = []
    for index, (clause, weight) in enumerate(zip(clauses, weights, strict=True)):
        end = duration if index == len(clauses) - 1 else cursor + duration * weight / total
        captions.append(CaptionCue(text=clause, start=cursor, end=end))
        cursor = end
    return captions


def _provider() -> str:
    return os.environ.get("HEVI_EXPLAINER_TTS_PROVIDER", "cosyvoice").strip().lower()


def _allow_edge_fallback() -> bool:
    return any(
        os.environ.get(name, "0").lower() in {"1", "true", "yes"}
        for name in ("VOICEBOX_ALLOW_EDGE_FALLBACK", "COSYVOICE_ALLOW_EDGE_FALLBACK")
    )


async def synthesize_storyboard(
    storyboard: Storyboard,
    audio_dir: Path,
    *,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
    audio_public_prefix: str = "audio",
) -> list[ManifestSegment]:
    """storyboard(E0 产出)→ 逐段配音,写音频到 audio_dir,返回 ManifestSegment 列表。

    audio_dir 写到 hevi-remotion/public/<prefix>(按 job 隔离)。ManifestSegment.audio_file
    是相对 public/ 的路径(Remotion staticFile() 约定),不是绝对路径。
    """
    provider = _provider()
    if provider not in {"cosyvoice", "voicebox", "edge_tts"}:
        raise VoiceoverError(f"不支持的解说 TTS provider: {provider}")
    manifest: list[ManifestSegment] = []
    cursor = 0.0
    for seg in storyboard.segments:
        active_provider = provider
        suffix = "wav" if provider in {"cosyvoice", "voicebox"} else "mp3"
        out_path = audio_dir / f"{seg.id}.{suffix}"
        words: list[dict[str, Any]] = []
        try:
            if provider == "cosyvoice":
                mode = os.environ.get("HEVI_COSY_INFERENCE_MODE", "").strip() or None
                await cosyvoice_synthesize(
                    script=[
                        SimpleNamespace(
                            text=seg.narration,
                            inference_mode=mode,
                        )
                    ],
                    output_path=out_path,
                )
            elif provider == "voicebox":
                await synthesize_voicebox(seg.narration, out_path)
            else:
                words = await _synthesize(
                    seg.narration, out_path, voice=voice, rate=rate
                )
        except Exception as e:
            if provider not in {"cosyvoice", "voicebox"}:
                raise VoiceoverError(f"段 {seg.id} 配音合成失败: {e}") from e
            provider_label = "CosyVoice" if provider == "cosyvoice" else "Voicebox"
            if not _allow_edge_fallback():
                raise VoiceoverError(f"段 {seg.id} {provider_label} 配音失败: {e}") from e
            logger.warning(
                "%s unavailable for %s; falling back to edge_tts: %s",
                provider_label,
                seg.id,
                e,
            )
            active_provider = "edge_tts"
            out_path = audio_dir / f"{seg.id}.mp3"
            try:
                words = await _synthesize(
                    seg.narration, out_path, voice=voice, rate=rate
                )
            except Exception as fallback_error:
                raise VoiceoverError(
                    f"段 {seg.id} {provider_label}/edge_tts 均失败: {fallback_error}"
                ) from fallback_error
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise VoiceoverError(f"段 {seg.id} 配音产物为空: {out_path}")

        if asr_verification_enabled():
            try:
                if active_provider == "cosyvoice":
                    from oprim import whisper_asr_verify

                    async def retry_sentence(
                        retry_text: str = seg.narration,
                        retry_path: Path = out_path,
                    ) -> Path:
                        await cosyvoice_synthesize(
                            script=[
                                SimpleNamespace(
                                    text=retry_text,
                                    inference_mode=os.environ.get(
                                        "HEVI_COSY_INFERENCE_MODE", ""
                                    ).strip()
                                    or None,
                                )
                            ],
                            output_path=retry_path,
                        )
                        return retry_path

                    verification = await verify_and_retry(
                        seg.narration,
                        out_path,
                        asr=whisper_asr_verify,
                        retry_synthesize=retry_sentence,
                    )
                else:
                    verification = await verify_audio(seg.narration, out_path)
                logger.info("explainer ASR: 段 %s CER %.3f", seg.id, verification["cer"])
            except AsrVerificationError as exc:
                raise VoiceoverError(f"段 {seg.id} ASR 校验失败: {exc}") from exc

        duration = probe_duration(out_path)  # type: ignore[no-untyped-call]
        captions = (
            _captions_from_words(seg.narration, words)
            if words
            else _captions_from_duration(seg.narration, duration)
        )
        props = validate_props(seg.scene_type, seg.props)

        manifest.append(
            ManifestSegment(
                id=seg.id,
                scene_type=seg.scene_type,
                text=seg.narration,
                audio_file=(
                    f"{audio_public_prefix.rstrip('/')}/"
                    f"{seg.id}.{'mp3' if active_provider == 'edge_tts' else 'wav'}"
                ),
                duration_sec=duration,
                start_sec=cursor,
                keywords=seg.keywords,
                props=props,
                captions=captions,
                visual_type=seg.visual_type,
                visual_config={
                    **seg.visual_config,
                    "layout_mode": getattr(seg, "layout_mode", "fullscreen") or "fullscreen",
                    "audio_style": getattr(seg, "audio_style", "formal") or "formal",
                },
                layout_mode=getattr(seg, "layout_mode", "fullscreen") or "fullscreen",
                audio_style=getattr(seg, "audio_style", "formal") or "formal",
            )
        )
        logger.info("explainer voiceover: 段 %s 时长 %.2fs (累计 %.2fs)", seg.id, duration, cursor)
        cursor += duration

    return manifest
