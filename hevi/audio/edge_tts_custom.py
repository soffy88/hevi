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
    "zh_female_mature": "zh-CN-liaoning-XiaobeiNeural",
    "zh_male_standard": "zh-CN-YunxiNeural",
    "zh_male_deep": "zh-CN-YunjianNeural",
    "zh_male_young": "zh-CN-YunyangNeural",
    "zh_male_mature": "zh-CN-YunxiaNeural",
    "en_female_standard": "en-US-AriaNeural",
    "en_male_standard": "en-US-GuyNeural",
}

# 按性别分池,供"每个角色分到一个不同音色"的轮询分配(见
# hevi/api/routers/director_pipeline.py::_assign_character_voices)。多角色对话时,同性别
# 的不同角色至少落到不同音色,不再全部一个声音。
MALE_VOICE_POOL: tuple[str, ...] = (
    "zh_male_standard",
    "zh_male_deep",
    "zh_male_young",
    "zh_male_mature",
)
FEMALE_VOICE_POOL: tuple[str, ...] = (
    "zh_female_standard",
    "zh_female_warm",
    "zh_female_mature",
)


# 情绪化配音(2026-07-13):hevi/tongjian/schemas.py::ScriptLine.emotion 是 LLM 填的自由文本
# 关键词(如"倨傲/决绝""惊惧""悲怆"),不是枚举。用关键词命中分桶映射到 rate/pitch delta——
# 按出现顺序取第一个命中的桶,命不中任何关键词就回退"+0%"/"+0Hz"(不影响没写情绪的旧脚本)。
_EMOTION_RATE_PITCH: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("悲", "哀", "凄", "无奈", "低落", "怆"), "-15%", "-15Hz"),
    (("惧", "惊", "慌", "急促", "紧张", "焦"), "+20%", "+15Hz"),
    (("怒", "愤", "恼", "决绝", "威严", "倨傲", "傲慢", "冷峻"), "-5%", "-10Hz"),
    (("喜", "欣", "振奋", "豪迈", "激昂"), "+10%", "+10Hz"),
)


def emotion_to_rate_pitch(emotion: str | None) -> tuple[str, str]:
    """自由文本情绪标签 → (rate, pitch) delta,edge-tts 直接可用的格式。"""
    if emotion:
        for keywords, rate, pitch in _EMOTION_RATE_PITCH:
            if any(k in emotion for k in keywords):
                return rate, pitch
    return "+0%", "+0Hz"


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
    emotion: str | None = None,
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

    `emotion`(2026-07-13 新增,治"ScriptLine.emotion 填了但 TTS 从不读"):非空就也走
    `synthesize_with_voice_control`,即使没显式 `voice`——旁白/未分配音色的对白一样能
    按情绪调 rate/pitch,只是音色仍用默认规则挑。
    """
    if voice or emotion:
        return await synthesize_with_voice_control(
            config=config, script=script, output_path=output_path, voice=voice, emotion=emotion
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
    emotion: str | None = None,
) -> Path:
    """script(每行需 .text)→ 单个 WAV,逐行套用 rate/pitch/显式音色。

    voice 接受 CURATED_VOICES 的键或 edge-tts 原生音色 ID(如 "zh-CN-XiaoxiaoNeural")。
    rate/pitch 显式传值时优先(对全部行统一生效);否则:每行若自带 `.emotion` 属性
    (2026-07-13,SPEC-002 B1——`longvideo_orchestrator.py::injected_audio_fn` 用
    `infer_line_emotions` 批量推断后包进 hevi 侧 SimpleNamespace,不改 oskill 的
    ShotPlan schema),该行单独用 `emotion_to_rate_pitch` 换算;没有 `.emotion` 属性
    的行(tongjian 的 `_Line`、任何普通调用方)退回整批统一的 `emotion` 参数换算,
    再退回 "+0%"/"+0Hz"(旧行为完全不变)。
    """
    import edge_tts

    cfg = config or {}
    language = cfg.get("language")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    _pairs = [(ln, str(getattr(ln, "text", str(ln))).strip()) for ln in script]
    _pairs = [(ln, t) for ln, t in _pairs if t]
    if not _pairs:
        raise ValueError("synthesize_with_voice_control: empty script")

    resolved_voice = CURATED_VOICES.get(voice, voice) if voice else None
    _batch_rate, _batch_pitch = rate, pitch
    if _batch_rate is None and _batch_pitch is None and emotion:
        _batch_rate, _batch_pitch = emotion_to_rate_pitch(emotion)

    with tempfile.TemporaryDirectory(prefix="hevi_edge_tts_") as td:
        tmp = Path(td)
        parts: list[Path] = []
        for i, (ln, text) in enumerate(_pairs):
            # 每行优先用该行自带的 .voice(角色专属音色,见 injected_audio_fn 的 edge_tts
            # 多角色分支);没有再退回整批的 voice,最后回退语言默认音色。
            _line_voice = getattr(ln, "voice", None)
            v = (CURATED_VOICES.get(_line_voice, _line_voice) if _line_voice else None) or (
                resolved_voice or _default_voice(text, language)
            )
            _line_emotion = getattr(ln, "emotion", None)
            if _line_emotion and rate is None and pitch is None:
                _r, _p = emotion_to_rate_pitch(_line_emotion)
            else:
                _r, _p = _batch_rate, _batch_pitch
            seg = tmp / f"seg_{i:04d}.mp3"
            try:
                comm = edge_tts.Communicate(text, v, rate=_r or "+0%", pitch=_p or "+0Hz")
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
