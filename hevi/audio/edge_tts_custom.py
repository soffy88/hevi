"""edge_tts 语速/音高/音色覆盖 —— hevi 自有轻量实现(不改 vendored oprim)。

oprim.edge_tts_synthesize 已支持多语言旁白,但没有 rate/pitch/显式音色覆盖的公开入口
(其 `_synth_fn` 是文档标注的测试注入钩子,非生产 API)。这里用同样的"逐行合成 → ffmpeg
concat 成统一 WAV"套路,换成 `edge_tts.Communicate(text, voice, rate=, pitch=)` 直调。

仅当 orchestrate_longvideo 收到 voice_rate/voice_pitch/voice_name 才走这条路径;否则
用回 registry 默认 provider,零行为变化。
"""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from obase.ffmpeg import run as ffmpeg_run

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")

# 精选几个常用中/英神经语音,供前端"音色"下拉选择(非穷举 edge-tts 全量音色表)。
CURATED_VOICES: dict[str, str] = {
    "zh_female_standard": "zh-CN-XiaoxiaoNeural",
    "zh_female_warm": "zh-CN-XiaoyiNeural",
    "zh_male_standard": "zh-CN-YunxiNeural",
    "zh_male_deep": "zh-CN-YunjianNeural",
    "en_female_standard": "en-US-AriaNeural",
    "en_male_standard": "en-US-GuyNeural",
}


def _default_voice(text: str, language: str | None) -> str:
    if language:
        base = language.split("-")[0].lower()
        if base == "zh":
            return CURATED_VOICES["zh_female_standard"]
        if base == "en":
            return CURATED_VOICES["en_female_standard"]
    return (
        CURATED_VOICES["zh_female_standard"]
        if _CJK_RE.search(text or "")
        else CURATED_VOICES["en_female_standard"]
    )


async def edge_tts_synthesize_smart(
    *,
    config: dict[str, Any] | None = None,
    script: list[Any],
    output_path: Path,
    language: str | None = None,
    watermark: bool = False,
    voice: str | None = None,
    **kwargs: Any,
) -> Path:
    """`edge_tts` provider 注册的真实入口(2026-07-13,取代直接指向
    `oprim.edge_tts_synthesize`)——多角色对话此前只有一个默认声音的根因是
    `oprim.edge_tts_synthesize` 完全不读 `speaker_id`/不接受显式音色,`hevi/tongjian/
    voiceover.py` 逐行调用时又从没传过 `voice_ref` 之外的东西。这里做的是:调用方
    (`voiceover.py::_synthesize_line`)传了 `voice`(该行说话人分配到的 CURATED_VOICES
    音色)就用 `synthesize_with_voice_control` 真正切换音色;没传(旁白/未分配声音的
    行,或任何其它调用点)原样退回 `oprim.edge_tts_synthesize`,行为完全不变——
    这条 provider 注册对所有既有调用方零回归,只是多接了一条"按行选音色"的路。
    """
    if voice:
        return await synthesize_with_voice_control(
            config=config, script=script, output_path=output_path, voice=voice
        )
    from oprim import edge_tts_synthesize

    return await edge_tts_synthesize(
        config=config,
        script=script,
        output_path=output_path,
        language=language,
        watermark=watermark,
        **kwargs,
    )


async def synthesize_with_voice_control(
    *,
    config: dict[str, Any] | None = None,
    script: list[Any],
    output_path: Path,
    rate: str | None = None,
    pitch: str | None = None,
    voice: str | None = None,
) -> Path:
    """script(每行需 .text)→ 单个 WAV,逐行套用 rate/pitch/显式音色。

    voice 接受 CURATED_VOICES 的键或 edge-tts 原生音色 ID(如 "zh-CN-XiaoxiaoNeural")。
    """
    import edge_tts

    cfg = config or {}
    language = cfg.get("language")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [getattr(ln, "text", str(ln)) for ln in script]
    lines = [t.strip() for t in lines if t and t.strip()]
    if not lines:
        raise ValueError("synthesize_with_voice_control: empty script")

    resolved_voice = CURATED_VOICES.get(voice, voice) if voice else None

    with tempfile.TemporaryDirectory(prefix="hevi_edge_tts_") as td:
        tmp = Path(td)
        parts: list[Path] = []
        for i, text in enumerate(lines):
            v = resolved_voice or _default_voice(text, language)
            seg = tmp / f"seg_{i:04d}.mp3"
            try:
                comm = edge_tts.Communicate(text, v, rate=rate or "+0%", pitch=pitch or "+0Hz")
                await comm.save(str(seg))
            except Exception as e:
                logger.warning("edge-tts(rate/pitch) segment %d failed: %s", i, e)
                continue
            if seg.exists() and seg.stat().st_size > 0:
                parts.append(seg)

        if not parts:
            raise RuntimeError("synthesize_with_voice_control: all segments failed")

        if len(parts) == 1:
            args = ["-i", str(parts[0]), "-ar", "44100", "-ac", "1", str(output_path)]
        else:
            inputs: list[str] = []
            for p in parts:
                inputs += ["-i", str(p)]
            n = len(parts)
            filt = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[a]"
            args = [
                *inputs,
                "-filter_complex",
                filt,
                "-map",
                "[a]",
                "-ar",
                "44100",
                "-ac",
                "1",
                str(output_path),
            ]
        await ffmpeg_run(args=args, expected_output=output_path)

    return output_path
