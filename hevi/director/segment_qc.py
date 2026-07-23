"""SPEC-007 批1 ①:V2(文档优先架构)段级 QC 统一入口。

`hevi/director/verdict_checks.py::ShotVerdict` 是 V1(cloud_avatar,`shot_id` 从生成产物
文件名派生)绑定的裁决器,不在这里复用它的调用路径——但复用它的 `retake_tier` 五档词汇
(`keep`/`fix_in_post`/`edit`/`re_roll`/`rewrite`,这里只产 `keep`/`re_roll` 两档,其余三档
留给后续批次的人工/后期决策)。V2 的段(`SceneScriptSegment`)没有 `shot_id`,QC 结果直接
按 `segment_id` 索引。

两项检查一次全查,不同原因走同一个 `re_roll` 结论但理由(`retake_reason`)不同——身份分
低是"演员不对",台词装不下是"时长不够",两种问题的重掷策略不同(前者换 seed,后者提高
duration),调用方按 `retake_reason` 里的关键字分流,这里不做值得掷两次骰子的过度设计。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.subjects.subject_embed import cosine_similarity, subject_embed

_IDENTITY_THRESHOLD = 0.65
_DIALOGUE_HANDLE_S = 0.5  # TTS 实际时长之外留的余量,不能卡着秒数正好够


@dataclass
class SegmentQCResult:
    segment_id: str
    identity_scores: dict[str, float] = field(default_factory=dict)
    dialogue_fits: bool = True
    tts_actual_s: float | None = None
    requested_duration_s: float = 0.0
    retake_tier: str = "keep"  # keep / re_roll(复用 ShotVerdict 词汇,见模块 docstring)
    retake_reason: str = ""


def _clip_duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out)


def _extract_frame(clip: Path, out: Path, *, at: str = "last") -> None:
    if at == "last":
        args = ["-y", "-sseof", "-0.3", "-i", str(clip), "-frames:v", "1", str(out)]
    else:
        args = ["-y", "-i", str(clip), "-vf", "select=eq(n\\,0)", "-vframes", "1", str(out)]
    subprocess.run(["ffmpeg", *args], check=True, capture_output=True)


def _identity_scores(frame_path: Path, canon_paths: dict[str, Path]) -> dict[str, float]:
    """CLIP 身份间距——每个出场角色的 frame 向量 vs 各自 canon 图余弦相似度。不问
    VLM"这是谁"(2026-07 观察态重构的教训:开放式认人在这条管线上真实撞见过幻觉)。"""
    frame_emb = subject_embed(image_path=frame_path, kind="face")
    scores: dict[str, float] = {}
    for name, canon_path in canon_paths.items():
        canon_emb = subject_embed(image_path=Path(canon_path), kind="face")
        scores[name] = cosine_similarity(frame_emb, canon_emb)
    return scores


async def _tts_duration_s(
    *, dialogue_text: str, speaker: str | None, voice: str | None, tts_fn: Any, tmp_out: Path
) -> float:
    """给一句台词拿真实 TTS 时长——按 `_synthesize_line` 内部同款 `tts_fn` 契约
    (`hevi/tongjian/voiceover.py:57-92`)直接调 provider,不跨模块调用那个下划线私有函数。"""
    from hevi.tongjian.schemas import ScriptLine

    line = ScriptLine(
        line_id="qc",
        type="dialogue",
        text=dialogue_text,
        **({"speaker": speaker} if speaker else {}),
    )
    await tts_fn(script=[line], output_path=tmp_out, voice=voice, emotion=None)
    return _clip_duration(tmp_out)


async def segment_qc(
    clip_path: Path,
    *,
    segment_id: str,
    character_names: list[str],
    canon_paths: dict[str, Path],
    dialogue_text: str | None = None,
    speaker: str | None = None,
    tts_fn: Any | None = None,
    voice: str | None = None,
    identity_threshold: float = _IDENTITY_THRESHOLD,
    tmp_dir: Path | None = None,
) -> SegmentQCResult:
    """段级 QC 统一入口:身份间距 + 台词完整性一次全查,产 `retake_tier`。

    `tts_fn`/`dialogue_text` 都不给时跳过台词检查(纯动作段没有台词)。`character_names`
    只取 `canon_paths` 里存在的键,不在场角色不参与这一段的身份判定。
    """
    tmp_dir = tmp_dir or clip_path.parent
    requested_dur = _clip_duration(clip_path)

    frame_path = tmp_dir / f"_qc_frame_{segment_id}.png"
    _extract_frame(clip_path, frame_path, at="last")
    relevant_canon = {n: canon_paths[n] for n in character_names if n in canon_paths}
    identity_scores = _identity_scores(frame_path, relevant_canon)

    dialogue_fits = True
    tts_actual_s: float | None = None
    if dialogue_text and tts_fn is not None:
        tmp_audio = tmp_dir / f"_qc_tts_{segment_id}.mp3"
        tts_actual_s = await _tts_duration_s(
            dialogue_text=dialogue_text,
            speaker=speaker,
            voice=voice,
            tts_fn=tts_fn,
            tmp_out=tmp_audio,
        )
        dialogue_fits = requested_dur >= tts_actual_s + _DIALOGUE_HANDLE_S

    min_identity = min(identity_scores.values()) if identity_scores else 1.0
    if min_identity < identity_threshold:
        retake_tier, reason = "re_roll", f"身份分 {min_identity:.3f} 低于阈值 {identity_threshold}"
    elif not dialogue_fits:
        reason = f"台词 TTS {tts_actual_s:.1f}s > 视频 {requested_dur:.1f}s(含 handle)"
        retake_tier = "re_roll"
    else:
        retake_tier, reason = "keep", ""

    return SegmentQCResult(
        segment_id=segment_id,
        identity_scores=identity_scores,
        dialogue_fits=dialogue_fits,
        tts_actual_s=tts_actual_s,
        requested_duration_s=requested_dur,
        retake_tier=retake_tier,
        retake_reason=reason,
    )
