"""preflight 通过率统计测试：首条口径、失败分布、反哺报告。"""

import pytest

from hevi.preflight import PassRateLedger


def test_first_pass_rate_counts_first_record_only(tmp_path):
    ledger = PassRateLedger(tmp_path / "pass.jsonl")
    ledger.record(beat_id="b1", model="veo_fast", outcome="fail",
                  failure_category="dialogue_garbled", cost=20, currency="credits")
    ledger.record(beat_id="b1", model="veo_fast", outcome="pass", cost=20, currency="credits")
    ledger.record(beat_id="b2", model="veo_fast", outcome="pass", cost=20, currency="credits")
    st = ledger.stats()
    assert st["attempts"] == 3 and st["beats"] == 2
    assert st["first_pass_rate"] == 0.5  # b1 首条 fail，b2 首条 pass
    assert st["failure_distribution"] == {"dialogue_garbled": 1}
    report = ledger.feedback_report()
    assert "dialogue_garbled" in report and "4.5 字／秒" in report


def test_invalid_outcome_and_category_rejected(tmp_path):
    ledger = PassRateLedger(tmp_path / "pass.jsonl")
    with pytest.raises(ValueError):
        ledger.record(beat_id="b1", model="veo_fast", outcome="maybe")
    with pytest.raises(ValueError):
        ledger.record(beat_id="b1", model="veo_fast", outcome="fail",
                      failure_category="made_up")


def test_empty_ledger_stats(tmp_path):
    st = PassRateLedger(tmp_path / "pass.jsonl").stats()
    assert st["attempts"] == 0 and st["first_pass_rate"] == 0.0
