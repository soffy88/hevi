"""Tests for Particle Science capability and line (PARTSCI-R1)."""

from __future__ import annotations

from pathlib import Path
import pytest

from hevi.capabilities import get, list_capabilities
from hevi.partsci.facts import get_fact_card, verify_mechanism
from hevi.partsci.storyboard import PartsciStoryboard, PartsciShot


def test_partsci_capabilities_registered():
    caps = list_capabilities(kind="shot")
    names = [c.name for c in caps]
    assert "particle_text" in names
    assert "particle_science_scene" in names
    assert "parallax_layers" in names


def test_facts_and_mechanism():
    card = get_fact_card("sky_blue")
    assert "散射" in card["fact"]
    assert verify_mechanism("sky_blue", "太阳光散射") is True
    assert verify_mechanism("sky_blue", "错误机制") is False


def test_storyboard_approval_gate():
    shot = PartsciShot(
        shot_index=1,
        duration=3.0,
        concept="sky_blue",
        keyword="蓝天",
        narration="天是蓝的",
        mechanism="太阳光散射",
        approved=False
    )
    story = PartsciStoryboard(
        title="测试",
        concept_key="sky_blue",
        aspect="16:9",
        shots=[shot],
        approved=False
    )
    with pytest.raises(RuntimeError):
        story.validate_all()

    shot.approved = True
    story.approved = True
    story.validate_all()  # Should pass


@pytest.mark.slow
def test_partsci_render_sample(tmp_path: Path):
    cap = get("particle_science_scene")
    res = cap.render(
        {
            "concept": "sky_blue",
            "theme": "sky",
            "keyword": "蓝天",
            "narration": "太阳光散射让天空变蓝。",
            "mechanism": "太阳光散射",
            "seed": 123
        },
        tmp_path,
        duration=2.0,
        aspect="16:9",
        seed=123
    )
    assert res.mp4 is not None
    assert Path(res.mp4).exists()
    assert res.sha256
    assert res.qa.get("passed", True) is True
