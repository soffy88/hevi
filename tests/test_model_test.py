"""Contract tests for story.model_test (offline, deterministic).

Fixtures are invented for these tests only: a riverside tea stall
and its keepers. Scores are supplied by injected eval functions;
no generation API is called and no score is ever invented by the
capability itself.
"""

import json
from pathlib import Path

import pytest

from hevi.capabilities import registry
from hevi.capabilities.errors import CapabilityError
import hevi.capabilities.model_test as mt_cap


def _test_set():
    return {
        "characters": [
            {"id": "C01", "name": "阿棠"},
            {"id": "C02", "name": "老周"},
        ],
        "scenes": [{"id": "SC01", "name": "河边茶摊"}],
        "key_shots": [
            {"id": "K01", "description": "阿棠把陶壶放在木桌上"},
            {"id": "K02", "description": "老周站在渡口望向河面"},
        ],
    }


def _flat(score):
    def _eval(kind, item):
        return {
            "texture": score,
            "lighting": score,
            "consistency": score,
            "action_accuracy": score,
        }

    return _eval


def test_registry_resolves():
    assert registry.get("story.model_test").name == "story.model_test"


def test_pending_without_eval_fn():
    card = mt_cap.build_scorecard(_test_set())
    assert card["status"] == "pending"
    assert card["released"] is False
    assert card["dimension_means"] is None
    assert card["overall_mean"] is None
    assert card["composition"] == {
        "character_count": 2,
        "scene_count": 1,
        "key_shot_count": 2,
        "total_items": 5,
    }
    assert all(item["scores"] is None for item in card["items"])
    assert all(item["status"] == "pending" for item in card["items"])


def test_released_when_all_dimensions_pass():
    card = mt_cap.build_scorecard(_test_set(), eval_fn=_flat(8))
    assert card["status"] == "released"
    assert card["released"] is True
    assert card["overall_mean"] == 8.0
    assert all(entry["met"] for entry in card["dimension_means"].values())
    assert all(c["met"] for c in card["release_conditions"])


def test_not_released_when_one_dimension_fails():
    def _eval(kind, item):
        scores = _flat(8)(kind, item)
        scores["consistency"] = 5
        return scores

    card = mt_cap.build_scorecard(_test_set(), eval_fn=_eval)
    assert card["status"] == "not_released"
    assert card["released"] is False
    assert card["dimension_means"]["consistency"]["met"] is False
    assert "人物一致性" in card["recommendation"]


def test_missing_dimension_keeps_card_pending():
    def _eval(kind, item):
        return {"texture": 9, "lighting": 9, "consistency": 9}  # no action_accuracy

    card = mt_cap.build_scorecard(_test_set(), eval_fn=_eval)
    assert card["status"] == "pending"
    assert card["released"] is False
    assert all(item["status"] == "error" for item in card["items"])
    assert any("缺维度" in item["error"] for item in card["items"])


def test_out_of_range_score_is_an_error():
    def _eval(kind, item):
        scores = _flat(8)(kind, item)
        scores["lighting"] = 11
        return scores

    card = mt_cap.build_scorecard(_test_set(), eval_fn=_eval)
    assert card["status"] == "pending"
    assert any("超出 0-10" in item["error"] for item in card["items"])


def test_raising_eval_fn_is_an_error_not_a_crash():
    def _eval(kind, item):
        raise RuntimeError("judge exploded")

    card = mt_cap.build_scorecard(_test_set(), eval_fn=_eval)
    assert card["status"] == "pending"
    assert card["released"] is False
    assert all(item["status"] == "error" for item in card["items"])


def test_partial_errors_still_report_scored_means_but_pending():
    def _eval(kind, item):
        if item["id"] == "K02":
            return {"texture": 9}  # incomplete
        return _flat(8)(kind, item)

    card = mt_cap.build_scorecard(_test_set(), eval_fn=_eval)
    assert card["status"] == "pending"
    assert card["released"] is False
    assert card["dimension_means"]["texture"]["mean"] == 8.0  # over scored items only
    assert sum(1 for i in card["items"] if i["status"] == "error") == 1


def test_empty_test_set_is_pending_with_blocker():
    card = mt_cap.build_scorecard({"characters": [], "scenes": [], "key_shots": []})
    assert card["status"] == "pending"
    assert card["released"] is False
    assert card["composition"]["total_items"] == 0
    assert any(f["severity"] == "blocker" for f in card["findings"])


def test_threshold_is_respected():
    card = mt_cap.build_scorecard(_test_set(), eval_fn=_flat(8), release_threshold=9)
    assert card["status"] == "not_released"
    card2 = mt_cap.build_scorecard(_test_set(), eval_fn=_flat(8), release_threshold=8)
    assert card2["status"] == "released"
    with pytest.raises(CapabilityError, match="release_threshold"):
        mt_cap.build_scorecard(_test_set(), eval_fn=_flat(8), release_threshold=11)


def test_item_ids_and_labels():
    test_set = {"characters": [{"name": "无名氏"}], "scenes": [], "key_shots": [{}]}
    card = mt_cap.build_scorecard(test_set, eval_fn=_flat(9))
    assert card["items"][0]["id"] == "character_1"
    assert card["items"][0]["label"] == "无名氏"
    assert card["items"][1]["id"] == "key_shot_1"


def test_render_writes_pending_report_via_registry(tmp_path):
    cap = registry.get("story.model_test")
    result = cap.render_safe(
        {"test_set": _test_set()}, tmp_path, duration=0.0, aspect="16:9", seed=42
    )
    report = json.loads(Path(result.qa["report_json"]).read_text(encoding="utf-8"))
    assert result.sha256
    assert report["status"] == "pending"  # JSON params carry no eval_fn
    assert report["composition"]["total_items"] == 5


def test_render_with_eval_fn_releases(tmp_path):
    cap = registry.get("story.model_test")
    result = cap.render_safe(
        {"test_set": _test_set(), "eval_fn": _flat(9)},
        tmp_path, duration=0.0, aspect="16:9", seed=42,
    )
    report = json.loads(Path(result.qa["report_json"]).read_text(encoding="utf-8"))
    assert report["status"] == "released"


def test_confirmation_gates_reported_pilot_binding():
    card = mt_cap.build_scorecard(_test_set(), eval_fn=_flat(8))
    gates = {g["gate"]: g["status"] for g in card["confirmation_gates"]}
    assert gates == {
        "direction": "pending",  # no direction confirmation supplied
        "core_assets": "passed",
        "pilot_shots": "passed",
        "delivery": "pending",
    }
    # Gates are informational by default: the plain scorecard still releases.
    assert card["status"] == "released"
    # With gates required, an unconfirmed direction blocks release.
    card2 = mt_cap.build_scorecard(
        _test_set(), eval_fn=_flat(8), require_confirmation_gates=True
    )
    assert card2["status"] == "not_released"
    assert any(f["check"] == "model_test" for f in card2["findings"])
    # With direction confirmed, all four gates pass and it releases.
    card3 = mt_cap.build_scorecard(
        _test_set(), eval_fn=_flat(8), direction={"confirmed": True},
        require_confirmation_gates=True,
    )
    assert card3["status"] == "released"
    assert all(g["status"] == "passed" for g in card3["confirmation_gates"])


def test_pilot_failed_gate_blocks_batch():
    card = mt_cap.build_scorecard(_test_set(), eval_fn=_flat(5))
    gates = {g["gate"]: g["status"] for g in card["confirmation_gates"]}
    assert gates["pilot_shots"] == "failed"
    assert card["status"] == "not_released"
    assert "试点镜未过" in card["recommendation"]


def test_uncertain_evidence_blocks_release():
    card = mt_cap.build_scorecard(
        _test_set(), eval_fn=_flat(9),
        evidence_grades={"K01": "uncertain", "C01": "observed"},
    )
    assert card["status"] == "not_released"
    assert card["released"] is False
    assert "K01" in card["recommendation"]
    assert card["evidence_summary"]["uncertain"] == 1
    assert card["evidence_summary"]["observed"] == 1
    assert card["evidence_summary"]["unspecified"] == 3


def test_observed_and_user_specified_grades_do_not_block():
    card = mt_cap.build_scorecard(
        _test_set(), eval_fn=_flat(9),
        evidence_grades={"K01": "user_specified", "C01": "observed"},
    )
    assert card["status"] == "released"
    items = {i["id"]: i["evidence_grade"] for i in card["items"]}
    assert items["K01"] == "user_specified"
    assert items["C01"] == "observed"
    assert items["C02"] == "unspecified"


def test_invalid_evidence_grade_raises():
    with pytest.raises(CapabilityError, match="unknown evidence grade"):
        mt_cap.build_scorecard(
            _test_set(), eval_fn=_flat(9),
            evidence_grades={"K01": "definitely"},
        )


def test_core_assets_gate_failed_without_scenes():
    test_set = {"characters": [], "scenes": [], "key_shots": [{"id": "K01"}]}
    card = mt_cap.build_scorecard(test_set, eval_fn=_flat(9))
    gates = {g["gate"]: g["status"] for g in card["confirmation_gates"]}
    assert gates["core_assets"] == "failed"
    # Informational by default; binding only when gates are required.
    assert card["status"] == "released"
    card2 = mt_cap.build_scorecard(
        test_set, eval_fn=_flat(9), require_confirmation_gates=True
    )
    assert card2["status"] == "not_released"
