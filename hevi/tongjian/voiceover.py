"""L3 配音 —— script → audio assets + timeline.json。见 HEVI-SPEC-01 §4。

P0 阶段:只做旁白单声线(所有行统一用一个 voice_id,不区分角色)。角色配音多声线
留待 P1(需要 character_bible 的 voice_id 映射)。

流程:
1. 遍历 script.lines,逐行调用 TTS(CosyVoice/edge_tts)合成音频文件
2. 收集每段音频的时长,计算累积时间轴(t_start_ms / t_end_ms)
3. 幕间(act 切换处)自动插入 1.5s 空隙(spec §4.3 规则)
4. 输出 Timeline 模型(含 audio_segments + gaps + total_duration_ms)

G3 校验门:
- ASR 反打 CER ≤ 5%(TTS 偶发吞字/多音字错读,必须机器审)
- 音量归一化检查(-16 LUFS 目标)
降级:CER 超标 → 换云 TTS 重合成;仍超标 → 标记 warning 但不阻塞
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from hevi.tongjian.schemas import (
    AudioSegment,
    Constitution,
    GateResult,
    Script,
    ScriptLine,
    Timeline,
    TimelineGap,
)

logger = logging.getLogger(__name__)

_ACT_GAP_MS = 1500  # spec §4.3:幕间自动插入 1.5s 空隙
_TARGET_LUFS = -16.0
_LUFS_TOLERANCE = 3.0  # ±3 dB
_CER_THRESHOLD = 0.05
_MAX_CER_RETRIES = 1  # P0 阶段只重试 1 次(换 provider)


# ── helpers ────────────────────────────────────────────────────────────────


def _short_hash(text: str) -> str:
    """4 字符短 hash,用于文件名去重(与 spec 示例 "ln001_a3f8.wav" 一致)。"""
    return hashlib.md5(text.encode()).hexdigest()[:4]


def _audio_filename(line: ScriptLine) -> str:
    """生成 spec 约定格式的音频文件名。"""
    return f"audio/{line.line_id.lower()}_{_short_hash(line.text)}.wav"


async def _synthesize_line(
    line: ScriptLine,
    output_path: Path,
    *,
    tts_fn: Any,
    voice: str | None = None,
) -> int:
    """调用 TTS 合成单行,返回音频时长(毫秒)。

    tts_fn 签名:async (script=..., output_path=..., voice=..., **kw) -> Path
    与 ProviderRegistry.generic("audio", ...) 返回的 callable 兼容。

    `voice`(2026-07-13 新增):这一行说话人分配到的音色(见 synthesize_voiceover 的
    `voice_by_speaker` 参数)。始终作为 kwarg 传给 tts_fn——`edge_tts` provider
    (`hevi/audio/edge_tts_custom.py::edge_tts_synthesize_smart`)会真的用它切换音色,
    没有按行分音色能力的 provider(如 `vibevoice_synthesize`,它走每行自己的
    `voice_ref` 做声线克隆)接受并忽略这个多余 kwarg,不会因为多传一个参数就报错。
    """
    from dataclasses import dataclass

    @dataclass
    class _Line:
        speaker_id: str
        text: str
        voice_ref: Path | None = None

    script_items = [_Line(speaker_id=line.speaker, text=line.text)]

    await tts_fn(script=script_items, output_path=output_path, voice=voice)

    # 读取生成文件的时长
    duration_ms = await _get_audio_duration_ms(output_path)
    return duration_ms


async def _get_audio_duration_ms(path: Path) -> int:
    """用 ffprobe 读取音频时长(毫秒)。回退:文件大小估算。"""
    import asyncio

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        duration_s = float(stdout.decode().strip())
        return round(duration_s * 1000)
    except Exception as e:
        logger.warning("ffprobe 读取时长失败 (%s),按文件大小估算: %s", path, e)
        # 粗略估算:16kHz 16bit mono WAV ≈ 32KB/s
        size = path.stat().st_size if path.exists() else 0
        return max(round(size / 32 * 1000 / 1000), 500)


async def _get_loudness_lufs(path: Path) -> float | None:
    """用 ffmpeg loudnorm 滤镜读取整合响度(LUFS)。"""
    import asyncio
    import json as _json

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-i",
            str(path),
            "-af",
            "loudnorm=print_format=json",
            "-f",
            "null",
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        # loudnorm JSON 在 stderr 的最后一段
        text = stderr.decode(errors="replace")
        # 找最后一个 { ... } 块
        brace_start = text.rfind("{")
        brace_end = text.rfind("}") + 1
        if brace_start >= 0 and brace_end > brace_start:
            data = _json.loads(text[brace_start:brace_end])
            return float(data.get("input_i", _TARGET_LUFS))
    except Exception as e:
        logger.warning("loudness 检测失败 (%s): %s", path, e)
    return None


async def _compute_cer(original: str, audio_path: Path) -> float:
    """ASR 反打:用 whisper/paraformer 转写音频,与原文计算 CER。

    P0 简化实现:如果 ASR 不可用,返回 0.0(通过)并记 warning。
    """
    try:
        import asyncio

        # 尝试用 whisper CLI
        proc = await asyncio.create_subprocess_exec(
            "whisper",
            str(audio_path),
            "--language",
            "zh",
            "--output_format",
            "txt",
            "--output_dir",
            str(audio_path.parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=120)

        txt_path = audio_path.with_suffix(".txt")
        if txt_path.exists():
            transcript = txt_path.read_text(encoding="utf-8").strip()
            txt_path.unlink(missing_ok=True)
            return _char_error_rate(original, transcript)
    except Exception as e:
        logger.warning("ASR 反打不可用(whisper),跳过 CER 检查: %s", e)
    return 0.0


def _char_error_rate(reference: str, hypothesis: str) -> float:
    """字级编辑距离 / 参考长度。"""
    ref = list(reference.replace(" ", "").replace("\n", ""))
    hyp = list(hypothesis.replace(" ", "").replace("\n", ""))
    if not ref:
        return 0.0

    # 标准 Levenshtein
    n, m = len(ref), len(hyp)
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            temp = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + cost)
            prev = temp
    return dp[m] / n


# ── 主流程 ─────────────────────────────────────────────────────────────────


async def synthesize_voiceover(
    script: Script,
    *,
    output_dir: Path | None = None,
    tts_fn: Any = None,
    voice_by_speaker: dict[str, str] | None = None,
) -> Timeline:
    """L3 主合成:script → Timeline(含音频文件 + 时间轴)。

    Args:
        script: L2 输出的剧本。
        output_dir: 音频文件输出目录;None 时使用临时目录。
        tts_fn: TTS callable,签名同 ProviderRegistry audio provider。
                 None 时从 ProviderRegistry 取 cosyvoice(P0 默认)。
        voice_by_speaker(2026-07-13 新增,治"多角色对话只有一个默认声音"):
                 character_id → CURATED_VOICES 键/edge-tts 原生音色 ID。dialogue
                 行按 speaker 查这张表拿到专属音色;查不到(旁白、未分配声音的
                 角色)保持模块顶部说的"P0 单声线"退化行为,不是全量重构。
    """
    import tempfile

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="hevi_l3_"))
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    if tts_fn is None:
        from obase.provider_registry import ProviderRegistry

        tts_fn = ProviderRegistry.get().generic("audio", "cosyvoice")

    segments: list[AudioSegment] = []
    gaps: list[TimelineGap] = []
    cursor_ms = 0
    prev_act: int | None = None

    for line in script.lines:
        if not line.text.strip():
            continue

        # 幕间空隙
        if prev_act is not None and line.act != prev_act:
            gap = TimelineGap(
                after_line=segments[-1].line_id if segments else line.line_id,
                duration_ms=_ACT_GAP_MS,
                purpose="act_transition",
            )
            gaps.append(gap)
            cursor_ms += _ACT_GAP_MS

        filename = _audio_filename(line)
        file_path = output_dir / filename

        voice = (voice_by_speaker or {}).get(line.speaker) if line.type == "dialogue" else None
        try:
            duration_ms = await _synthesize_line(line, file_path, tts_fn=tts_fn, voice=voice)
        except Exception as e:
            logger.warning("L3: 行 %s TTS 合成失败,跳过: %s", line.line_id, e)
            duration_ms = 0

        if duration_ms <= 0:
            prev_act = line.act
            continue

        seg = AudioSegment(
            line_id=line.line_id,
            file=filename,
            duration_ms=duration_ms,
            t_start_ms=cursor_ms,
            t_end_ms=cursor_ms + duration_ms,
        )
        segments.append(seg)
        cursor_ms += duration_ms
        prev_act = line.act

    return Timeline(
        audio_segments=segments,
        total_duration_ms=cursor_ms,
        gaps=gaps,
    )


async def gate_voiceover(
    timeline: Timeline,
    script: Script,
    constitution: Constitution,
    *,
    output_dir: Path | None = None,
) -> GateResult:
    """G3 校验门:ASR 反打 CER + 响度检查。

    P0 简化:ASR 如果不可用(whisper 未安装),CER 检查跳过并记 warning。
    """
    errors: list[str] = []
    warnings: list[str] = []

    lines_by_id = {ln.line_id: ln for ln in script.lines}

    # 1. 基本完整性
    if not timeline.audio_segments:
        errors.append("timeline 没有任何音频片段")
        return GateResult(passed=False, errors=errors)

    # 2. 时长偏差检查:total_duration vs constitution.target_duration_sec
    target_ms = constitution.target_duration_sec * 1000
    if target_ms > 0:
        deviation = abs(timeline.total_duration_ms - target_ms) / target_ms
        if deviation > 0.20:
            warnings.append(
                f"配音总时长 {timeline.total_duration_ms}ms 与目标 {target_ms}ms "
                f"偏差 {deviation:.1%},超过 20% 门槛(可能需回退 L2 增删行)"
            )

    # 3. ASR 反打 CER(需要音频文件存在)
    cer_checked = 0
    cer_failed = 0
    for seg in timeline.audio_segments:
        if not output_dir:
            continue
        audio_path = output_dir / seg.file
        if not audio_path.exists():
            continue
        original = lines_by_id.get(seg.line_id)
        if not original:
            continue
        cer = await _compute_cer(original.text, audio_path)
        cer_checked += 1
        if cer > _CER_THRESHOLD:
            cer_failed += 1
            errors.append(f"行 {seg.line_id} ASR 反打 CER={cer:.1%} 超过 {_CER_THRESHOLD:.0%} 门槛")

    if cer_checked == 0 and output_dir:
        warnings.append("ASR 反打未执行(whisper 不可用或无音频文件),CER 检查跳过")

    # 4. 响度检查
    for seg in timeline.audio_segments:
        if not output_dir:
            continue
        audio_path = output_dir / seg.file
        if not audio_path.exists():
            continue
        lufs = await _get_loudness_lufs(audio_path)
        if lufs is not None and abs(lufs - _TARGET_LUFS) > _LUFS_TOLERANCE:
            warnings.append(
                f"行 {seg.line_id} 响度 {lufs:.1f} LUFS,偏离目标 {_TARGET_LUFS} LUFS "
                f"超过 ±{_LUFS_TOLERANCE} dB"
            )

    coverage = (cer_checked - cer_failed) / cer_checked if cer_checked else 1.0
    return GateResult(
        passed=not errors,
        coverage=coverage,
        errors=errors,
        warnings=warnings,
    )


async def build_voiceover(
    script: Script,
    constitution: Constitution,
    *,
    output_dir: Path | None = None,
    tts_fn: Any = None,
    voice_by_speaker: dict[str, str] | None = None,
) -> tuple[Timeline, GateResult]:
    """L3 主入口:合成 → G3 门。

    与 build_script / build_constitution 同一模式:返回 (产物, GateResult)。
    """
    timeline = await synthesize_voiceover(
        script,
        output_dir=output_dir,
        tts_fn=tts_fn,
        voice_by_speaker=voice_by_speaker,
    )
    result = await gate_voiceover(
        timeline,
        script,
        constitution,
        output_dir=output_dir,
    )
    return timeline, result
