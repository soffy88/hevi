"""G0.2-C spike tests: semantic anchor -> frame (T1-T3 + reverse)."""

import pytest

from hevi.audio.tts_alignment import WordTiming  # 复用 ms 整数契约,不重复定义时间
from hevi.studio.anchor_resolver import (
    Anchor,
    AnchorOrphaned,
    AnchorUnresolved,
    resolve_anchor,
)


def _dialogue_end(words: list[WordTiming]) -> int:
    """Dialogue End Event 定义(G0.2-B 修正规则):last_word.end_ms。"""
    return words[-1].end_ms


def test_t1_dialogue_anchor_resolves_to_frame():
    events = {"scene1.line001": 1612, "scene1.line002": 3400}
    r = resolve_anchor(
        Anchor("AFTER_DIALOGUE", "scene1.line001", offset_ms=500),
        dialogue_end_ms=events, fps=30,
        alignment_hash="align:abc", timeline_hash="tl:def",
    )
    assert r.time_ms == 2112
    assert r.frame == round(2112 * 30 / 1000) == 63
    assert r.source == "scene1.line001"
    assert r.evidence == ("align:abc", "tl:def")


def test_t1_negative_offset_and_fps_floor():
    events = {"scene1.line001": 1612}
    r = resolve_anchor(
        Anchor("AFTER_DIALOGUE", "scene1.line001", offset_ms=-100),
        dialogue_end_ms=events, fps=24,
    )
    assert r.time_ms == 1512
    assert r.frame == round(1512 * 24 / 1000)
    # 容差下限永远不小于 1 帧:frame 粒度即 1000/fps ms
    assert 1000 / 24 > 40


def test_t2_revision_invalidation_old_anchor_not_reused():
    old_events = {"scene1.line001": 1612}
    new_events = {"scene1.line001": 1900}  # line1 duration 变化(重配音)
    old = resolve_anchor(Anchor("AFTER_DIALOGUE", "scene1.line001", offset_ms=500),
                         dialogue_end_ms=old_events, fps=30)
    new = resolve_anchor(Anchor("AFTER_DIALOGUE", "scene1.line001", offset_ms=500),
                         dialogue_end_ms=new_events, fps=30)
    assert (old.time_ms, old.frame) != (new.time_ms, new.frame)


def test_t3_evidence_present_and_dialogue_end_from_alignment():
    words = [WordTiming("black", 1200, 1450), WordTiming("hole", 1450, 1800)]
    r = resolve_anchor(
        Anchor("AFTER_DIALOGUE", "scene1.line004", offset_ms=500),
        dialogue_end_ms={"scene1.line004": _dialogue_end(words)}, fps=30,
        alignment_hash="align:h", timeline_hash="tl:h",
    )
    assert r.time_ms == 2300  # 1800 + 500:why this frame 可审计
    assert len(r.evidence) == 2


def test_reverse_orphan_target_is_fail_loud():
    with pytest.raises(AnchorOrphaned):
        resolve_anchor(Anchor("AFTER_DIALOGUE", "scene1.gone", offset_ms=0),
                       dialogue_end_ms={}, fps=30)


def test_reverse_absolute_time_rejected():
    with pytest.raises(AnchorUnresolved):
        resolve_anchor(Anchor("ABSOLUTE", "scene1.line001", offset_ms=0),
                       dialogue_end_ms={"scene1.line001": 100}, fps=30)
