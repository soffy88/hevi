"""连续性报告测试(HEVI 路线图 Phase3 #41)。"""

from __future__ import annotations

import pytest

from hevi.tasks.continuity_report import build_continuity_report


def _row(index: int, **selection: object) -> dict:
    return {"shot_index": index, "status": "completed", "selection_json": selection}


def test_empty_shots_returns_valid_empty_report():
    report = build_continuity_report([])
    assert report["shots"] == []
    assert report["summary"]["total_shots"] == 0
    assert report["summary"]["pass_rate"] is None
    assert report["summary"]["avg_consistency_score"] is None


def test_pass_rate_and_avg_consistency_computed():
    shots = [
        _row(0, passed=True, consistency_score=0.9),
        _row(1, passed=False, consistency_score=0.3),
        _row(2, passed=True, consistency_score=0.8),
    ]
    report = build_continuity_report(shots)
    s = report["summary"]
    assert s["total_shots"] == 3
    assert s["passed_shots"] == 2
    assert s["pass_rate"] == pytest.approx(2 / 3)
    assert s["avg_consistency_score"] == pytest.approx((0.9 + 0.3 + 0.8) / 3)


def test_diagnosis_breakdown_counts_categories():
    shots = [
        _row(0, passed=False, diagnosis_category="参考图角色错配"),
        _row(1, passed=False, diagnosis_category="参考图角色错配"),
        _row(2, passed=True, diagnosis_category=None),
    ]
    report = build_continuity_report(shots)
    assert report["summary"]["diagnosis_breakdown"] == {"参考图角色错配": 2}


def test_subject_and_stylepack_refs_deduplicated():
    shots = [
        _row(
            0, subject_id="sub-1", subject_version=2, style_pack_id="pack-1", style_pack_version=3
        ),
        _row(
            1, subject_id="sub-1", subject_version=2, style_pack_id="pack-1", style_pack_version=3
        ),
    ]
    report = build_continuity_report(shots)
    assert report["summary"]["subject_refs"] == [{"subject_id": "sub-1", "subject_version": 2}]
    assert report["summary"]["style_pack_refs"] == [
        {"style_pack_id": "pack-1", "style_pack_version": 3}
    ]


def test_shot_rows_include_all_verdict_fields():
    shots = [
        _row(
            0,
            provider="wan_local",
            model_version="wan_local",
            passed=True,
            consistency_score=0.9,
            style_score=None,
            vlm_score=0.3,
            vlm_violations=["肢体畸变"],
            diagnosis_category=None,
            duration_s=4.0,
            tier0_passed=True,
            tier1_passed=False,
        )
    ]
    report = build_continuity_report(shots)
    row = report["shots"][0]
    assert row["index"] == 0
    assert row["provider"] == "wan_local"
    assert row["vlm_violations"] == ["肢体畸变"]
    assert row["tier1_passed"] is False


def test_missing_selection_json_does_not_crash():
    report = build_continuity_report([{"shot_index": 0, "status": "completed"}])
    assert report["shots"][0]["passed"] is None
    assert report["summary"]["total_shots"] == 1
