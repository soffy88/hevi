"""讲解段契约测试 —— §3 逐字投影 + G1a"不自造字段"纪律。"""

import pytest
from pydantic import ValidationError

from hevi.tongjian.explainer_contract import (
    Account,
    DualAccountFact,
    EpisodePlan,
    NarrationBeat,
    Quantity,
    VisualFact,
)


def test_visualfact_exact_field_set():
    # §3 VisualFact 字段集,逐字(不多不少)
    expect = {
        "beat_id",
        "ku_refs",
        "date",
        "scope",
        "forces",
        "regions",
        "routes",
        "markers",
        "persons",
        "quantities",
        "evidence_tier",
        "confirmed_by",
    }
    assert set(VisualFact.model_fields) == expect


def test_narrationbeat_exact_field_set():
    assert set(NarrationBeat.model_fields) == {
        "beat_id",
        "order",
        "vo_text",
        "est_vo_seconds",
        "visual_intent",
        "fact_ref",
    }


def test_episodeplan_exact_field_set():
    assert set(EpisodePlan.model_fields) == {
        "episode_id",
        "dynasty_era",
        "event_ku_refs",
        "narrative_frame",
        "narration_script_ref",
    }


def test_visual_intent_enum_rejects_invented():
    with pytest.raises(ValidationError):
        NarrationBeat(
            beat_id="b1", order=1, vo_text="x", est_vo_seconds=5, visual_intent="zoom_spin"
        )  # 自造 intent → 拒


def test_evidence_tier_enum():
    VisualFact(beat_id="b1", evidence_tier="E3")
    with pytest.raises(ValidationError):
        VisualFact(beat_id="b1", evidence_tier="E9")


def test_dualaccount_requires_exactly_two():
    ok = DualAccountFact(
        beat_id="b1",
        accounts=[Account(source_display="《资治通鉴》"), Account(source_display="《史记》")],
    )
    assert len(ok.accounts) == 2
    with pytest.raises(ValidationError):
        DualAccountFact(beat_id="b1", accounts=[Account(source_display="仅一个")])


def test_quantity_source_display():
    q = Quantity(value=3.0, unit="家", source_display="《史记·赵世家》载", ku_ref="ku:x")
    vf = VisualFact(beat_id="b1", quantities=[q], persons=["智伯"], date=-453)
    assert vf.quantities[0].source_display.startswith("《史记")
    assert vf.date == -453
