"""拆条病毒打分 —— 对照 AI-Youtube-Shorts-Generator。"""

from __future__ import annotations

from hevi.ingest.video_transcript import TranscriptSegment
from hevi.openshorts.virality import (
    Highlight,
    chunk_segments,
    dedupe_highlights,
    score_highlights,
    score_text,
)


def test_score_text_hook_beats_plain():
    hook, hits = score_text("其实没人告诉你这个秘密")
    plain, _ = score_text("今天天气不错我们出去走走")
    assert "hook" in hits
    assert hook > plain


def test_dedupe_keeps_higher_score():
    a = Highlight("a", 0.0, 60.0, 90, "h", "hook")
    b = Highlight("b", 10.0, 50.0, 40, "h", "overlap")
    c = Highlight("c", 80.0, 140.0, 70, "h", "later")
    kept = dedupe_highlights([a, b, c])
    titles = {h.title for h in kept}
    assert "a" in titles and "c" in titles
    assert "b" not in titles


def test_chunk_long_video():
    segs = [TranscriptSegment(float(i), float(i + 30), f"seg {i}") for i in range(0, 2400, 30)]
    chunks = chunk_segments(segs)
    assert len(chunks) >= 2


def test_score_highlights_deterministic():
    segs = [
        TranscriptSegment(0.0, 8.0, "开场闲聊今天天气不错我们出去走走还要买菜做饭"),
        TranscriptSegment(8.0, 70.0, "其实没人告诉你这个秘密。数据显示原来可以三步记住。"),
        TranscriptSegment(70.0, 140.0, "千万别再这样做。方法很简单记住公式。"),
    ]
    hits = score_highlights(segs, target_clips=2)
    assert hits
    assert hits[0].score >= 10
    assert hits[0].end_s > hits[0].start_s


def test_score_highlights_llm_path():
    segs = [TranscriptSegment(0.0, 50.0, "hello world this is filler talking about nothing much")]

    def llm(_prompt: str) -> str:
        return '{"highlights":[{"title":"T","start_time":1,"end_time":40,"score":88,"hook_sentence":"H","virality_reason":"hook"}]}'

    hits = score_highlights(segs, target_clips=1, llm_fn=llm)
    assert hits[0].title == "T"
    assert hits[0].score == 88
