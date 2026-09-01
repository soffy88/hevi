"""语义时序契约:有 token 才给毫秒,禁止按字数估。"""

from __future__ import annotations

import pytest

from hevi.explainer.phrase_timeline import (
    build_phrase_timeline,
    infer_relationship,
    page_from_phrases,
    phrases_from_narration,
)


def test_phrases_keep_book_title() -> None:
    assert phrases_from_narration("先看《盐铁论》，再讲盐税。") == [
        "先看",
        "《盐铁论》",
        "再讲盐税。",
    ]


def test_timeline_uses_caption_ms() -> None:
    captions = [
        {"text": "盐税", "startMs": 120, "endMs": 400, "confidence": 0.9},
        {"text": "是什么", "startMs": 400, "endMs": 900, "confidence": 0.9},
    ]
    timeline = build_phrase_timeline("盐税是什么", captions)
    assert timeline["phrases"][0]["start_ms"] == 120
    assert timeline["phrases"][0]["boundary_source"] == "caption-token"
    assert timeline["coverage"] >= 0.72


def test_timeline_refuses_missing_captions() -> None:
    with pytest.raises(RuntimeError, match="token"):
        build_phrase_timeline("盐税是什么", [])


def test_relationship_defaults_none() -> None:
    assert infer_relationship("盐税是一种间接税") == "none"
    assert infer_relationship("首先加盐，然后收税") == "sequence"
    assert infer_relationship("因为短缺所以涨价") == "cause"


def test_page_rejects_unknown_phrase_id() -> None:
    with pytest.raises(RuntimeError, match="不存在"):
        page_from_phrases(
            [{"id": "p01", "text": "盐", "start_ms": 0, "end_ms": 100}],
            title="盐",
            idea="盐",
            trigger_ids=["p99"],
        )
