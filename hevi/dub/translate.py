"""翻译配音导出(设计 §3 L2)—— Series 导出"出 X 语种版"。

全存量零件的组合,唯一新件是**翻译步骤**:
  ASR(faster-whisper,`assembly.subtitle_align`)→ **translate_cues(本地 qwen)** →
  edge-tts 目标语种(`audio` provider)→ mux 回成片(ffmpeg)。

`translate_cues` 是新逻辑;`dub_video` 编排(transcribe/synth/mux 可注入,便于测试与换实现)。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from hevi.assembly.subtitle_align import Cue

logger = logging.getLogger(__name__)


def _safe_json_obj(content: str | None) -> dict[str, Any]:
    if not content:
        return {}
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


async def translate_cues(
    cues: list[Cue],
    *,
    target_language: str,
    llm: Any = None,
    retry_missing: bool = True,
    sleep_fn: Any = None,
) -> list[Cue]:
    """把字幕 cue 文本批量翻译到 target_language,保持时间码。

    批量漏译再按行退避重试(Voice-Pro);整批失败或单行仍空 → 原文兜底。
    """
    if not cues:
        return []
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    texts = [c.text for c in cues]
    prompt = (
        f"把下面编号的字幕逐条翻译成{target_language}。只输出 JSON 对象 "
        '{"0":"译文",...},键为原编号,值为译文,不要额外文字。\n'
        + "\n".join(f"{i}: {t}" for i, t in enumerate(texts))
    )
    batch: dict[int, str] = {}
    try:
        resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=2048)
        data = _safe_json_obj(resp.get("content") if hasattr(resp, "get") else str(resp))
        for i in range(len(texts)):
            v = data.get(str(i))
            if isinstance(v, str) and v.strip():
                batch[i] = v.strip()
    except Exception as e:
        logger.warning("translate LLM failed, keeping source text: %s", e)

    if retry_missing and any(i not in batch for i in range(len(texts))):
        from hevi.voicepro.oskill.translate_retry import fill_missing_lines

        async def _one(text: str) -> str:
            one_prompt = (
                f"把下面字幕翻译成{target_language}。只输出译文,不要额外文字。\n{text}"
            )
            resp = await llm(messages=[{"role": "user", "content": one_prompt}], max_tokens=512)
            content = resp.get("content") if hasattr(resp, "get") else str(resp)
            return str(content or "").strip()

        rows = await fill_missing_lines(
            texts,
            batch,
            _one,
            sleep_fn=sleep_fn,
        )
        translated = [row.translated for row in rows]
    else:
        translated = [batch.get(i, texts[i]) for i in range(len(texts))]

    return [
        Cue(start=c.start, end=c.end, text=t, emotion=c.emotion)
        for c, t in zip(cues, translated, strict=False)
    ]


def _to_timed(cues: list[Cue]) -> list[Any]:
    from hevi.voicepro.schemas import TimedCue

    return [
        TimedCue(start=c.start, end=c.end, text=c.text, emotion=c.emotion)
        for c in cues
    ]


def _from_timed(cues: list[Any]) -> list[Cue]:
    return [
        Cue(start=c.start, end=c.end, text=c.text, emotion=c.emotion) for c in cues
    ]


async def dub_video(
    *,
    video_path: str | Path,
    target_language: str,
    output_path: str | Path,
    llm: Any = None,
    transcribe_fn: Any = None,
    synth_fn: Any = None,
    mux_fn: Any = None,
    model_dir: str | None = None,
    sentence_merge: bool = True,
    keep_clock: bool = False,
    keep_bed: bool = False,
    bed_path: str | Path | None = None,
) -> dict[str, Any]:
    """成片 → 目标语种配音版。transcribe/synth/mux 可注入;默认用存量实现。

    返回 {output, language, cues}。任一步失败向上抛(导出是显式动作,失败该告知)。
    sentence_merge:Voice-Pro 合句后再 TTS。keep_clock:按 SRT 时钟垫静音。
    keep_bed:新配音盖回原声/伴奏床,而不是整轨替换。
    """
    video_path = Path(video_path)
    output_path = Path(output_path)

    if transcribe_fn is None:
        from hevi.assembly.subtitle_align import transcribe_to_cues

        def transcribe_fn(p: Path) -> list[Cue]:
            return transcribe_to_cues(p, model_dir=model_dir)

    cues = transcribe_fn(video_path)
    tcues = await translate_cues(cues, target_language=target_language, llm=llm)
    if sentence_merge and tcues:
        from hevi.voicepro.oskill.subtitle_timeline import merge_and_split_cues

        tcues = _from_timed(merge_and_split_cues(_to_timed(tcues), lang=None))

    dub_audio = output_path.with_suffix(".dub.wav")
    if synth_fn is None:
        if keep_clock:
            from hevi.dub._synth import synth_cues_on_timeline as synth_fn
        else:
            from hevi.dub._synth import synth_cues_edge_tts as synth_fn
    await synth_fn(cues=tcues, language=target_language, output_path=dub_audio)

    if mux_fn is None:
        if keep_bed:
            from hevi.dub._mux import mux_remix_into_video as mux_fn

            await mux_fn(
                video=video_path,
                audio=dub_audio,
                output=output_path,
                bed=Path(bed_path) if bed_path else None,
            )
        else:
            from hevi.dub._mux import mux_audio_into_video as mux_fn

            await mux_fn(video=video_path, audio=dub_audio, output=output_path)
    else:
        await mux_fn(video=video_path, audio=dub_audio, output=output_path)

    return {"output": str(output_path), "language": target_language, "cues": len(tcues)}
