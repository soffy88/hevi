"""口播粗剪 —— 对照 FireRed-OpenStoryline ASR rough cut。

去掉语气词/填充词,时间轴跟着词级(或插值词)收。不重渲视频,只出 keep 段。
"""

from __future__ import annotations

import re

from hevi.ingest.video_transcript import TranscriptSegment, WordSpan
from hevi.ingest.words import ensure_words

_FILLERS = {
    "啊",
    "呃",
    "嗯",
    "额",
    "那个",
    "就是",
    "就是说",
    "然后",
    "然后就",
    "这个",
    "um",
    "uh",
    "uhh",
    "like",
    "you know",
    "i mean",
    "kinda",
    "sort of",
}
_FILLERS_LONGEST = tuple(sorted(_FILLERS, key=len, reverse=True))


def _norm_token(token: str) -> str:
    t = token.strip().lower()
    return re.sub(r"[。．.、,，!！?？;；:：…]+", "", t)


def _is_filler_token(token: str) -> bool:
    return _norm_token(token) in _FILLERS


def _match_filler(words: list[WordSpan], index: int) -> int:
    """从 index 起匹配最长填充词,返回吃掉的词数(0=不是填充)。"""
    n = len(words)
    for filler in _FILLERS_LONGEST:
        parts = filler.split()
        if len(parts) > 1:
            got = [_norm_token(words[index + k].word) for k in range(len(parts)) if index + k < n]
            if got == parts:
                return len(parts)
            continue
        joined = ""
        k = 0
        while index + k < n and len(joined) < len(filler):
            joined += _norm_token(words[index + k].word)
            k += 1
            if joined == filler:
                return k
    return 0


def strip_fillers(seg: TranscriptSegment) -> TranscriptSegment | None:
    """去掉填充词。整段都是填充词则返回 None(应丢掉)。"""
    if _is_filler_token(seg.text):
        return None
    filled = ensure_words(seg)
    kept: list[WordSpan] = []
    i = 0
    words = list(filled.words)
    while i < len(words):
        n = _match_filler(words, i)
        if n:
            i += n
            continue
        kept.append(words[i])
        i += 1
    if not kept:
        return None
    text = "".join(w.word for w in kept)
    if not any("\u4e00" <= ch <= "\u9fff" for ch in text):
        text = " ".join(w.word for w in kept)
    return TranscriptSegment(
        start=kept[0].start,
        end=kept[-1].end,
        text=text.strip(),
        speaker=seg.speaker,
        words=tuple(kept),
    )


def rough_cut(
    segments: list[TranscriptSegment],
) -> tuple[list[TranscriptSegment], list[TranscriptSegment]]:
    """返回 (保留段, 丢掉的填充段)。"""
    kept: list[TranscriptSegment] = []
    dropped: list[TranscriptSegment] = []
    for seg in segments:
        cleaned = strip_fillers(seg)
        if cleaned is None:
            dropped.append(seg)
        else:
            kept.append(cleaned)
    return kept, dropped
