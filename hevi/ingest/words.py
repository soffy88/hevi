"""词级时间戳与按停顿切句 —— 对照 xiaohu-video-translate / video-talkcraft。

转写常常只给句级 cue。烧字幕、口播锁镜头、拆条 snap 都需要词级轴。
没有 Whisper word timestamp 时,按中英分词在 cue 内线性插值,不假装更准。
"""

from __future__ import annotations

import re

from hevi.ingest.video_transcript import TranscriptSegment, WordSpan

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_PUNCT_END = set("。！？!?.;；…")


def interpolate_words(text: str, start: float, end: float) -> tuple[WordSpan, ...]:
    """把一段文本按字/词均分到 [start, end]。"""
    raw = (text or "").strip()
    if not raw:
        return ()
    if _CJK_RE.search(raw):
        tokens = [ch for ch in raw if not ch.isspace()]
    else:
        tokens = [tok for tok in raw.split() if tok]
    if not tokens:
        return ()
    dur = max(float(end) - float(start), 0.01)
    step = dur / len(tokens)
    return tuple(
        WordSpan(
            word=tok,
            start=round(float(start) + i * step, 3),
            end=round(float(start) + (i + 1) * step, 3),
        )
        for i, tok in enumerate(tokens)
    )


def ensure_words(seg: TranscriptSegment) -> TranscriptSegment:
    """段上已有词级轴则原样返回,否则插值补上。"""
    if seg.words:
        return seg
    return TranscriptSegment(
        start=seg.start,
        end=seg.end,
        text=seg.text,
        speaker=seg.speaker,
        words=interpolate_words(seg.text, seg.start, seg.end),
    )


def flatten_words(segments: list[TranscriptSegment]) -> list[WordSpan]:
    """全部段的词级轴,按时间排序。"""
    words: list[WordSpan] = []
    for seg in segments:
        words.extend(ensure_words(seg).words)
    words.sort(key=lambda w: w.start)
    return words


def split_cues_by_pause(
    words: list[WordSpan],
    *,
    pause_s: float = 0.35,
    max_chars: int = 18,
) -> list[TranscriptSegment]:
    """按停顿 + 句读 + 字数上限切字幕 cue。

    xiaohu 的核心:词级时间戳按「句子 + 停顿」切,字幕不抢拍、不半句甩到下一条。
    """
    if not words:
        return []
    cues: list[TranscriptSegment] = []
    buf: list[WordSpan] = []
    chars = 0

    def _flush() -> None:
        nonlocal buf, chars
        if not buf:
            return
        text = "".join(w.word for w in buf)
        if not _CJK_RE.search(text):
            text = " ".join(w.word for w in buf)
        cues.append(
            TranscriptSegment(
                start=buf[0].start,
                end=buf[-1].end,
                text=text.strip(),
                words=tuple(buf),
            )
        )
        buf = []
        chars = 0

    for i, word in enumerate(words):
        buf.append(word)
        chars += len(word.word)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt.start - word.end) if nxt is not None else 0.0
        punct = word.word[-1:] in _PUNCT_END if word.word else False
        if punct or gap >= pause_s or chars >= max_chars:
            _flush()
    _flush()
    return cues


def lock_cues_to_words(
    cues: list[TranscriptSegment],
    words: list[WordSpan],
    *,
    lead_s: float = 0.05,
    tail_s: float = 0.08,
) -> list[TranscriptSegment]:
    """把句级 cue 钉到最近词边界(talkcraft 声画锁的确定性核)。"""
    if not words:
        return list(cues)
    starts = [w.start for w in words]
    ends = [w.end for w in words]
    out: list[TranscriptSegment] = []
    for cue in cues:
        start = min(starts, key=lambda t: abs(t - cue.start), default=cue.start)
        end = min(ends, key=lambda t: abs(t - cue.end), default=cue.end)
        start = max(0.0, start - lead_s)
        end = max(start + 0.04, end + tail_s)
        owned = tuple(w for w in words if w.start >= start - 0.02 and w.end <= end + 0.02)
        out.append(
            TranscriptSegment(
                start=round(start, 3),
                end=round(end, 3),
                text=cue.text,
                speaker=cue.speaker,
                words=owned or cue.words,
            )
        )
    return out
