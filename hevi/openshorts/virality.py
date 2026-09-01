"""拆条病毒打分 —— 对照 AI-Youtube-Shorts-Generator。

确定性核:hook/情绪/金句/实用信号打分 + 重叠去重 + 超 30 分钟分块。
LLM 可选;没有模型也能出候选,不绑 MuAPI。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from hevi.ingest.video_transcript import TranscriptSegment

CHUNK_SIZE_S = 1200.0
LONG_VIDEO_S = 1800.0
CHUNK_OVERLAP_S = 60.0
MIN_CLIP_S = 20.0
SWEET_MIN_S = 45.0
SWEET_MAX_S = 90.0
MAX_CLIP_S = 180.0

_HOOK = (
    r"secret|nobody|the truth|i was wrong|wait|here's why|"
    r"秘密|没人|真相|其实|但是|千万别|第一次|你不知道|揭秘|别再"
)
_EMOTION = r"!|！|哈哈|wow|crazy|insane|离谱|崩了|太狠|笑死|哭了"
_OPINION = r"never|always|everyone|nobody should|必须|千万|绝对|根本|所谓"
_REVEAL = r"percent|%|study|data|research|研究发现|数据显示|原来"
_VALUE = r"how to|tip|hack|步骤|方法|公式|记住|三步"
_QUOTE = r"^.{0,24}$"

_HOOK_RE = re.compile(_HOOK, re.I)
_EMOTION_RE = re.compile(_EMOTION, re.I)
_OPINION_RE = re.compile(_OPINION, re.I)
_REVEAL_RE = re.compile(_REVEAL, re.I)
_VALUE_RE = re.compile(_VALUE, re.I)


@dataclass(frozen=True)
class Highlight:
    title: str
    start_s: float
    end_s: float
    score: int
    hook_sentence: str
    virality_reason: str
    signals: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "start_time": self.start_s,
            "end_time": self.end_s,
            "score": self.score,
            "hook_sentence": self.hook_sentence,
            "virality_reason": self.virality_reason,
            "signals": list(self.signals),
        }


def _duration(segments: list[TranscriptSegment]) -> float:
    if not segments:
        return 0.0
    return max(s.end for s in segments)


def _window_text(segments: list[TranscriptSegment]) -> str:
    return " ".join(s.text.strip() for s in segments if s.text.strip())


def score_text(text: str) -> tuple[int, list[str]]:
    """0–100 启发式。信号可解释,不是黑盒。"""
    if not text.strip():
        return 0, []
    score = 10
    hits: list[str] = []
    if _HOOK_RE.search(text):
        score += 28
        hits.append("hook")
    if _EMOTION_RE.search(text):
        score += 16
        hits.append("emotion")
    if _OPINION_RE.search(text):
        score += 14
        hits.append("opinion")
    if _REVEAL_RE.search(text):
        score += 14
        hits.append("reveal")
    if _VALUE_RE.search(text):
        score += 12
        hits.append("value")
    first = text.strip().split("。")[0].split(".")[0].strip()
    if first and len(first) <= 24:
        score += 8
        hits.append("quotable")
    return max(0, min(100, score)), hits


def _candidate_windows(
    segments: list[TranscriptSegment],
    *,
    target_s: float = 60.0,
) -> list[list[TranscriptSegment]]:
    if not segments:
        return []
    windows: list[list[TranscriptSegment]] = []
    i = 0
    n = len(segments)
    while i < n:
        start = segments[i].start
        j = i
        while j + 1 < n and segments[j + 1].end - start <= MAX_CLIP_S:
            j += 1
            if segments[j].end - start >= target_s:
                break
        span = segments[i : j + 1]
        dur = span[-1].end - span[0].start
        if dur >= MIN_CLIP_S:
            windows.append(span)
        i = j + 1 if j > i else i + 1
    return windows


def chunk_segments(segments: list[TranscriptSegment]) -> list[list[TranscriptSegment]]:
    """超 30 分钟按 20 分钟块、60 秒重叠切开。"""
    total = _duration(segments)
    if total <= LONG_VIDEO_S:
        return [segments]
    chunks: list[list[TranscriptSegment]] = []
    start = 0.0
    while start < total:
        end = min(start + CHUNK_SIZE_S, total)
        piece = [s for s in segments if s.end > start and s.start < end + CHUNK_OVERLAP_S]
        if piece:
            chunks.append(piece)
        start += CHUNK_SIZE_S - CHUNK_OVERLAP_S
    return chunks or [segments]


def dedupe_highlights(highlights: list[Highlight]) -> list[Highlight]:
    """重叠超过较短段 50% 的低分条丢掉。"""
    ranked = sorted(highlights, key=lambda h: h.score, reverse=True)
    kept: list[Highlight] = []
    for h in ranked:
        dur = max(h.end_s - h.start_s, 0.01)
        overlap_hit = False
        for k in kept:
            latest = max(h.start_s, k.start_s)
            earliest = min(h.end_s, k.end_s)
            overlap = earliest - latest
            if overlap > 0 and overlap > 0.5 * dur:
                overlap_hit = True
                break
        if not overlap_hit:
            kept.append(h)
    kept.sort(key=lambda h: h.start_s)
    return kept


def _highlight_from_window(window: list[TranscriptSegment]) -> Highlight | None:
    text = _window_text(window)
    if not text:
        return None
    score, signals = score_text(text)
    hook = window[0].text.strip()
    title = hook[:24] or "highlight"
    reason = "、".join(signals) if signals else "density"
    return Highlight(
        title=title,
        start_s=round(window[0].start, 3),
        end_s=round(window[-1].end, 3),
        score=score,
        hook_sentence=hook,
        virality_reason=reason,
        signals=tuple(signals),
    )


def score_highlights(
    segments: list[TranscriptSegment],
    *,
    target_clips: int = 5,
    llm_fn: object | None = None,
) -> list[Highlight]:
    """主入口。llm_fn(prompt)->str 可选;失败或未提供走启发式。"""
    if not segments:
        return []
    if llm_fn is not None:
        try:
            parsed = _llm_highlights(segments, target_clips=target_clips, llm_fn=llm_fn)
            if parsed:
                return dedupe_highlights(parsed)[:target_clips]
        except Exception:
            pass
    found: list[Highlight] = []
    for chunk in chunk_segments(segments):
        for window in _candidate_windows(chunk):
            hit = _highlight_from_window(window)
            if hit is not None:
                found.append(hit)
    return dedupe_highlights(found)[: max(1, target_clips)]


def _llm_highlights(
    segments: list[TranscriptSegment],
    *,
    target_clips: int,
    llm_fn: object,
) -> list[Highlight]:
    body = "\n".join(f"[{s.start:.1f}-{s.end:.1f}] {s.text}" for s in segments)
    prompt = (
        "Identify viral short-form highlights. JSON only: "
        '{"highlights":[{"title":"","start_time":0,"end_time":1,"score":0,'
        '"hook_sentence":"","virality_reason":""}]}\n'
        f"Need {target_clips} clips.\n{body}"
    )
    raw = llm_fn(prompt)  # type: ignore[operator]
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    data = json.loads(text[text.find("{") : text.rfind("}") + 1])
    out: list[Highlight] = []
    for item in data.get("highlights") or []:
        if not isinstance(item, dict):
            continue
        start = float(item.get("start_time") or -1)
        end = float(item.get("end_time") or -1)
        if start < 0 or end <= start:
            continue
        out.append(
            Highlight(
                title=str(item.get("title") or "Untitled").strip(),
                start_s=start,
                end_s=end,
                score=max(0, min(100, int(float(item.get("score") or 0)))),
                hook_sentence=str(item.get("hook_sentence") or "").strip(),
                virality_reason=str(item.get("virality_reason") or "").strip(),
            )
        )
    return out
