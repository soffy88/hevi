"""S30E: the 暖黑金图解 line must have a real executor, and the script it
builds from a studio plan must pass warm-gold's own self-check.

Before the fix the studio production order for ``warm_gold`` had no renderer
registered at all, so "暖黑金图解" could never deliver a film.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hevi.studio.fulfill import _RENDERERS, _warm_gold_script


def _order(topic: str, lines: list[str]) -> dict:
    return {
        "line_id": "warm_gold",
        "target": "explainer",
        "topic": topic,
        "script_lines": list(lines),
        "slots": {},
    }


def test_warm_gold_has_a_media_executor() -> None:
    assert "warm_gold" in _RENDERERS, "暖黑金图解没有真实媒体执行器"


def test_warm_gold_script_passes_its_own_check() -> None:
    from hevi.explainer.warmgold import beats, scriptcheck

    order = _order(
        "为什么复利这么反直觉",
        [
            "复利最反直觉的地方，是它一开始慢得让人想放弃。",
            "第一年你只有 100 块，涨到 110 块，几乎没有变化。",
            "时间越长，斜率越陡，这就是复利的形状。",
        ],
    )
    script = _warm_gold_script(order, list(order["script_lines"]))
    beat_data = beats.build_beats(script)
    report = scriptcheck.check_script(script, beat_data)
    assert report["pass"], report["issues"]


def test_warm_gold_script_trims_long_topics_to_the_safe_area() -> None:
    order = _order(
        "为什么三十秒就能讲清楚一个非常反直觉的复利道理",
        ["你有没有想过，数字为什么最后会自己跑起来。"],
    )
    script = _warm_gold_script(order, list(order["script_lines"]))
    for shot in script["shots"]:
        assert len(shot["big"]) <= 20
        assert len(shot["small"]) <= 30


def test_warm_gold_script_declares_screen_numbers() -> None:
    order = _order("30 秒讲清楚复利", ["你有没有想过，30 秒够不够。"])
    script = _warm_gold_script(order, list(order["script_lines"]))
    values = {str(item.get("value")) for item in script.get("numbers") or []}
    assert "30" in values
    assert all(
        str(item.get("source")) in {"实测", "估计", "用户提供", "示意"}
        for item in script.get("numbers") or []
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
