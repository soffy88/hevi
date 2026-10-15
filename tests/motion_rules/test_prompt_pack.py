"""Tests for rule card loading and prompt pack rendering."""

from pathlib import Path
from hevi.motion_rules.prompt_pack import load_rule_cards, render_prompt_pack, RuleCard


REQUIRED_RULE_IDS = {
    "pure_draw_seek_stateless",
    "closed_form_spring",
    "single_shape_morph",
    "content_container_timing",
    "short_blur_transition",
    "bpm_grid_alignment",
    "loop_first_last_frame",
    "prohibited_elements",
    "real_assets_not_placeholders",
    "contact_sheet_first",
}


def test_rule_cards_loaded_and_valid() -> None:
    cards = load_rule_cards()
    assert len(cards) >= 8, f"Expected at least 8 rule cards, found {len(cards)}"
    assert len(cards) == 10, f"Expected 10 rule cards, found {len(cards)}"

    loaded_ids = {c.id for c in cards}
    assert REQUIRED_RULE_IDS.issubset(loaded_ids), f"Missing required rule IDs: {REQUIRED_RULE_IDS - loaded_ids}"

    for c in cards:
        assert c.id, "Rule card missing id"
        assert c.title, f"Rule {c.id} missing title"
        assert c.category, f"Rule {c.id} missing category"
        assert len(c.trigger) > 0, f"Rule {c.id} missing trigger conditions"
        assert len(c.counter_example) > 10, f"Rule {c.id} missing counter_example"
        assert len(c.correct_approach) > 10, f"Rule {c.id} missing correct_approach"
        assert c.source_case_id, f"Rule {c.id} missing source_case_id"
        assert c.source_author, f"Rule {c.id} missing source_author"
        assert c.prompt_summary, f"Rule {c.id} missing prompt_summary"


def test_render_prompt_pack_modes() -> None:
    # 1. Detailed mode
    detailed = render_prompt_pack(mode="detailed")
    assert "# Hevi 动效设计与工程规则库" in detailed
    for r_id in REQUIRED_RULE_IDS:
        assert r_id in detailed

    # 2. Compact mode
    compact = render_prompt_pack(mode="compact")
    assert "【Hevi 动效工程核心准则】" in compact
    assert "10." in compact

    # 3. System prompt mode
    sys_prompt = render_prompt_pack(mode="system_prompt")
    assert "<motion_design_rules>" in sys_prompt
    assert "</motion_design_rules>" in sys_prompt


def test_render_prompt_pack_filtering() -> None:
    subset = ["pure_draw_seek_stateless", "prohibited_elements"]
    rendered = render_prompt_pack(rule_ids=subset, mode="compact")
    assert "draw(t)" in rendered
    assert "shockwave" in rendered
    assert "1." in rendered
    assert "2." in rendered
    assert "3." not in rendered
