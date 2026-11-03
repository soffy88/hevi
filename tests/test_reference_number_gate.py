import pytest

from hevi.capabilities import reference_number_gate as rg
from hevi.capabilities.errors import CapabilityError


def test_parse_lists_refs_in_order():
    refs = rg.parse_numbered_refs("see {{ref 2}} then {{ref 1}}")
    assert [r["number"] for r in refs] == [2, 1]


def test_multi_param_resolves_against_declared_order():
    report = rg.check_references(
        "use {{ref 1}} beside {{ref 2}}", ["hero", "school"],
        mode="multi_param",
    )
    assert report["ok"] is True
    assert [r["asset_id"] for r in report["resolved"]] == ["hero", "school"]


def test_unconfirmed_number_fails_and_is_not_guessed():
    report = rg.check_references(
        "use {{ref 3}}", ["hero", "school"], mode="multi_param",
    )
    assert report["ok"] is False
    assert any("ref 3" in p for p in report["problems"])
    with pytest.raises(CapabilityError, match="ref 3"):
        rg.assert_references(
            "use {{ref 3}}", ["hero", "school"], mode="multi_param",
        )


def test_first_frame_impersonation_fails():
    report = rg.check_references(
        "start from {{ref 2}}", ["hero", "school"],
        mode="first_frame", first_frame_asset_id="hero",
    )
    assert report["ok"] is False
    assert any("first-frame" in p for p in report["problems"])


def test_three_view_sheet_is_not_a_first_frame():
    report = rg.check_references(
        "start from {{ref 1}}", ["hero-sheet"],
        mode="first_frame", first_frame_asset_id="hero-sheet",
        three_view_asset_ids=["hero-sheet"],
    )
    assert report["ok"] is False
    assert any("three-view" in p for p in report["problems"])


def test_reorder_then_recheck_passes_with_new_mapping():
    prompt = "use {{ref 2}}"
    before = rg.check_references(prompt, ["hero", "school"], mode="multi_param")
    assert before["resolved"][0]["asset_id"] == "school"
    after = rg.check_references(prompt, ["school", "hero"], mode="multi_param")
    assert after["ok"] is True
    assert after["resolved"][0]["asset_id"] == "hero"


def test_script_text_is_not_a_connection():
    report = rg.validate_edges(
        [{"ref": 1, "source": "script", "target": "hero"}],
        ["hero", "school"],
    )
    assert report["ok"] is False
    assert any("script text" in p for p in report["problems"])


def test_decorative_edge_fails_and_valid_edges_pass():
    bad = rg.validate_edges(
        [{"ref": 1, "source": "hero", "target": "school", "decorative": True}],
        ["hero", "school"],
    )
    assert bad["ok"] is False
    good = rg.validate_edges(
        [{"ref": 1, "source": "hero", "target": "school"}],
        ["hero", "school"],
    )
    assert good["ok"] is True


def test_prompt_without_refs_is_clean():
    report = rg.check_references(
        "a quiet morning", ["hero"], mode="multi_param",
    )
    assert report["ok"] is True
    assert report["resolved"] == []
