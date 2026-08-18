"""把 TTS 片段按 SRT 时钟垫静音 / 溢出后移。

对齐 Voice-Pro `srt_to_voice`:片头垫到第一条 start;下一条未到则垫静音;
合成超时则把后续时钟整体后移(保时长)。
3O 归属(待上游): `oprim.timeline_pad`。
"""

from __future__ import annotations

from hevi.voicepro.schemas import TimelineSlot


def s_to_ms(seconds: float) -> int:
    return max(0, round(float(seconds) * 1000))


def place_clips_on_clock(
    cue_starts_s: list[float],
    clip_durations_s: list[float],
) -> list[TimelineSlot]:
    """给定每条 cue 的 SRT 起点与实际 TTS 时长,算出输出时间轴。"""
    if len(cue_starts_s) != len(clip_durations_s):
        raise ValueError("cue_starts_s and clip_durations_s must align")
    slots: list[TimelineSlot] = []
    cursor_ms = 0
    for index, (start_s, clip_s) in enumerate(zip(cue_starts_s, clip_durations_s, strict=True)):
        clock_ms = s_to_ms(start_s)
        clip_ms = s_to_ms(clip_s)
        overflowed = False
        if index == 0:
            start_ms = clock_ms
            cursor_ms = start_ms + clip_ms
        else:
            if cursor_ms < clock_ms:
                start_ms = cursor_ms
                # 静音垫在上一条 pad_after 里,本条从时钟点开始
                start_ms = clock_ms
                cursor_ms = start_ms + clip_ms
            else:
                start_ms = cursor_ms
                overflowed = cursor_ms > clock_ms
                cursor_ms = start_ms + clip_ms
        slots.append(
            TimelineSlot(
                cue_index=index,
                start_ms=start_ms,
                clip_ms=clip_ms,
                pad_after_ms=0,
                clock_start_ms=clock_ms,
                overflowed=overflowed,
            )
        )
    for index, slot in enumerate(slots):
        if index + 1 >= len(slots):
            slot.pad_after_ms = 0
            continue
        nxt = slots[index + 1]
        target = nxt.clock_start_ms if not nxt.overflowed else nxt.start_ms
        gap = target - (slot.start_ms + slot.clip_ms)
        if gap > 0 and not nxt.overflowed:
            slot.pad_after_ms = gap
        else:
            slot.pad_after_ms = 0
    if slots:
        first = slots[0]
        if first.clock_start_ms > 0 and first.start_ms == first.clock_start_ms:
            # 片头静音用一条虚拟 pad 表达:第一条 start_ms 保持时钟,调用方在 concat 前插 leading
            pass
    return slots


def leading_silence_ms(slots: list[TimelineSlot]) -> int:
    if not slots:
        return 0
    return slots[0].start_ms


def total_timeline_ms(slots: list[TimelineSlot]) -> int:
    if not slots:
        return 0
    last = slots[-1]
    return last.start_ms + last.clip_ms + last.pad_after_ms
