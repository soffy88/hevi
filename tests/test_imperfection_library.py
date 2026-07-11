"""非完美事件库测试(HEVI 路线图 Phase3 #38)。"""

from __future__ import annotations

import random

from hevi.style.imperfection_library import IMPERFECTION_EVENTS, pick_imperfection_event


def _all_events() -> list[str]:
    return [e for events in IMPERFECTION_EVENTS.values() for e in events]


def test_pick_returns_an_event_from_the_library():
    used: set[str] = set()
    picked = pick_imperfection_event(used=used, rng=random.Random(0))
    assert picked in _all_events()


def test_pick_adds_choice_to_used_set():
    used: set[str] = set()
    picked = pick_imperfection_event(used=used, rng=random.Random(0))
    assert picked in used


def test_pick_never_repeats_within_same_used_set():
    used: set[str] = set()
    rng = random.Random(0)
    picks = [pick_imperfection_event(used=used, rng=rng) for _ in range(len(_all_events()))]
    assert None not in picks
    assert len(set(picks)) == len(picks)  # 全部不同


def test_pick_returns_none_when_library_exhausted():
    used = set(_all_events())
    assert pick_imperfection_event(used=used, rng=random.Random(0)) is None


def test_four_categories_present():
    assert set(IMPERFECTION_EVENTS) == {"摄影师失误", "环境介入", "主体自然行为", "收束方式"}
