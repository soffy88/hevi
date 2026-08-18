"""合句拆句 + 把 TTS 片段落到 SRT 时钟。

组合: `group_cues` + `split_into_sentences` + `char_weighted_spans` + `place_clips_on_clock`。
3O 归属(待上游): `oskill.subtitle_timeline`。
"""

from __future__ import annotations

from hevi.voicepro.oprim.cue_clock import (
    char_weighted_spans,
    detect_lang_hint,
    group_cues,
    join_group_text,
    merge_sentence_fragments,
    normalize_text,
    split_into_sentences,
)
from hevi.voicepro.oprim.timeline_pad import place_clips_on_clock
from hevi.voicepro.schemas import TimedCue, TimelineSlot


def merge_and_split_cues(
    cues: list[TimedCue],
    *,
    lang: str | None = None,
) -> list[TimedCue]:
    """Voice-Pro spaCy 合句:按空隙分组 → 断句 → 不完整句粘下一条 → 按字重切时钟。"""
    if not cues:
        return []
    hint = lang or detect_lang_hint(next((cue.text for cue in cues if cue.text.strip()), ""))
    result: list[TimedCue] = []
    for group in group_cues(cues):
        texts = [normalize_text(cue.text, hint) for cue in group if cue.text.strip()]
        full = join_group_text(texts, hint)
        sentences = merge_sentence_fragments(split_into_sentences(full))
        if not sentences:
            continue
        spans = char_weighted_spans(sentences, group[0].start, group[-1].end)
        speaker = next((cue.speaker for cue in group if cue.speaker), "")
        emotion = next((cue.emotion for cue in group if cue.emotion != "neutral"), "neutral")
        for sent, (start, end) in zip(sentences, spans, strict=False):
            result.append(
                TimedCue(
                    start=start,
                    end=end,
                    text=sent,
                    speaker=speaker,
                    emotion=emotion,
                )
            )
    return result


def plan_timeline(cues: list[TimedCue], clip_durations_s: list[float]) -> list[TimelineSlot]:
    """整理后的 cue + 实测 TTS 时长 → 输出时钟。"""
    starts = [cue.start for cue in cues]
    return place_clips_on_clock(starts, clip_durations_s)
