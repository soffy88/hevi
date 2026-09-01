"""说话人轮次 —— 对照 VidBee 说话人标签(无 pyannote 时的确定性启发式)。

停顿超过阈值视为换人,两人访谈按 SPEAKER_00 / SPEAKER_01 交替。
不是声纹聚类;notes 必须写明 heuristic。有词级轴时用词间间隙,否则用段间隙。
"""

from __future__ import annotations

from hevi.ingest.video_transcript import TranscriptSegment


def label_speakers(
    segments: list[TranscriptSegment],
    *,
    pause_s: float = 0.8,
) -> list[TranscriptSegment]:
    """给每段打 speaker。空输入返回空列表。"""
    if not segments:
        return []
    ordered = sorted(segments, key=lambda s: s.start)
    out: list[TranscriptSegment] = []
    speaker_idx = 0
    prev_end = ordered[0].start
    for seg in ordered:
        gap = seg.start - prev_end
        if gap >= pause_s and out:
            speaker_idx = 1 - speaker_idx
        label = seg.speaker or f"SPEAKER_{speaker_idx:02d}"
        out.append(
            TranscriptSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text,
                speaker=label,
                words=seg.words,
            )
        )
        prev_end = seg.end
    return out
