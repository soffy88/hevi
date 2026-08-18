"""默认配音合成:translated cues → edge-tts 目标语种音频(复用 audio provider)。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hevi.assembly.subtitle_align import Cue


async def synth_cues_edge_tts(*, cues: list[Cue], language: str, output_path: Path) -> Path:
    """cues → edge-tts(目标语种)WAV。edge_tts_synthesize 期望 script: list[Line](鸭子类型 .text/.speaker_id)。

    情感感知配音:cue.emotion(默认 neutral)驱动 rate/pitch/volume 注入——
    未标注的台词自动按关键词启发式分类(见 hevi.dub.emotion)。"""
    from obase.provider_registry import ProviderRegistry

    from hevi.dub.emotion import detect_emotion, emotion_tts_params

    lines: list[Any] = []
    for c in cues:
        if not c.text.strip():
            continue
        # neutral(未标注)一律按关键词自动情感分类;显式非 neutral 保持
        emotion = c.emotion if c.emotion != "neutral" else detect_emotion(c.text)
        prof = emotion_tts_params(emotion)
        lines.append(
            SimpleNamespace(
                text=c.text,
                speaker_id="host",
                rate=prof["rate"],
                pitch=prof["pitch"],
                volume=prof["volume"],
            )
        )
    caller = ProviderRegistry.get().generic("audio", "edge_tts")
    await caller(script=lines, output_path=output_path, language=language)
    return output_path


async def synth_cues_on_timeline(
    *,
    cues: list[Cue],
    language: str,
    output_path: Path,
    synth_one: Any = None,
    probe: Any = None,
    concat_fn: Any = None,
) -> Path:
    """逐条 TTS 后按 SRT 时钟垫静音拼接(Voice-Pro srt_to_voice)。"""
    from hevi.voicepro.oskill.subtitle_timeline import plan_timeline
    from hevi.voicepro.schemas import TimedCue

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    usable = [c for c in cues if c.text.strip()]
    if not usable:
        raise ValueError("no cues to synthesize")

    if synth_one is None:
        synth_one = _synth_one_edge
    if probe is None:
        from oprim import probe_duration as probe
    if concat_fn is None:
        concat_fn = _concat_with_pads

    clip_paths: list[Path] = []
    durations: list[float] = []
    for index, cue in enumerate(usable):
        clip = output_path.parent / f"{output_path.stem}.cue{index:04d}.wav"
        await synth_one(cue=cue, language=language, output_path=clip)
        clip_paths.append(clip)
        durations.append(float(probe(clip)))

    timed = [TimedCue(start=c.start, end=c.end, text=c.text, emotion=c.emotion) for c in usable]
    slots = plan_timeline(timed, durations)
    await concat_fn(clips=clip_paths, slots=slots, output_path=output_path)
    return output_path


async def _synth_one_edge(*, cue: Cue, language: str, output_path: Path) -> Path:
    return await synth_cues_edge_tts(cues=[cue], language=language, output_path=output_path)


async def _concat_with_pads(*, clips: list[Path], slots: Any, output_path: Path) -> Path:
    from obase.ffmpeg import run as ffmpeg_run

    from hevi.voicepro.oprim.timeline_pad import leading_silence_ms

    parts: list[str] = []
    lead = leading_silence_ms(slots)
    if lead > 0:
        parts.extend(["-f", "lavfi", "-t", f"{lead / 1000:.3f}", "-i", "anullsrc=r=24000:cl=mono"])
    for clip, slot in zip(clips, slots, strict=False):
        parts.extend(["-i", str(clip)])
        if slot.pad_after_ms > 0:
            parts.extend(
                ["-f", "lavfi", "-t", f"{slot.pad_after_ms / 1000:.3f}", "-i", "anullsrc=r=24000:cl=mono"]
            )
    n_inputs = sum(1 for item in parts if item == "-i")
    concat = "".join(f"[{i}:a]" for i in range(n_inputs)) + f"concat=n={n_inputs}:v=0:a=1[a]"
    args = ["-y", *parts, "-filter_complex", concat, "-map", "[a]", str(output_path)]
    await ffmpeg_run(args=args, expected_output=output_path)
    return output_path
