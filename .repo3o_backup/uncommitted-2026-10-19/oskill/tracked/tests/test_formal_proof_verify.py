from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from oskill.formal_proof_verify import formal_proof_verify


def test_formal_proof_proven():
    # Mock lookup function
    mock_lookup_fn = MagicMock()

    # Mock a hit
    mock_hit = MagicMock()
    mock_hit.name = "Nat.add_comm"
    mock_hit.module = "Mathlib.Algebra.Group.Nat"
    mock_hit.dict.return_value = {"name": "Nat.add_comm", "module": "Mathlib.Algebra.Group.Nat"}

    mock_res = MagicMock()
    mock_res.count = 1
    mock_res.hits = [mock_hit]
    mock_lookup_fn.return_value = mock_res

    name_dict = {"加法交换律": "Nat.add_comm"}
    result = formal_proof_verify(
        theorem_name="加法交换律", name_dict=name_dict, mathlib_lookup_fn=mock_lookup_fn
    )

    assert result.verdict == "proven"
    assert result.matched_lemma == "Nat.add_comm"
    assert result.matched_module == "Mathlib.Algebra.Group.Nat"
    assert result.evidence == "established_proof:mathlib:Nat.add_comm:Mathlib.Algebra.Group.Nat"
    assert len(result.decision_trail) == 3
    assert result.decision_trail[2]["status"] == "proven"

    mock_lookup_fn.assert_called_once_with(identifier="Nat.add_comm")


def test_formal_proof_not_in_dict():
    mock_lookup_fn = MagicMock()
    result = formal_proof_verify(
        theorem_name="未知定理", name_dict={}, mathlib_lookup_fn=mock_lookup_fn
    )
    assert result.verdict == "not_elevated"
    assert result.decision_trail[0]["status"] == "failed"
    mock_lookup_fn.assert_not_called()


def test_formal_proof_no_hits():
    mock_lookup_fn = MagicMock()
    mock_res = MagicMock()
    mock_res.count = 0
    mock_res.hits = []
    mock_lookup_fn.return_value = mock_res

    result = formal_proof_verify(
        theorem_name="定理", name_dict={"定理": "Lemma.none"}, mathlib_lookup_fn=mock_lookup_fn
    )
    assert result.verdict == "not_elevated"
    assert result.decision_trail[2]["reason"] == "not_found"


def test_formal_proof_ambiguous():
    mock_lookup_fn = MagicMock()
    mock_res = MagicMock()
    mock_res.count = 2
    mock_lookup_fn.return_value = mock_res

    result = formal_proof_verify(
        theorem_name="定理", name_dict={"定理": "Lemma.many"}, mathlib_lookup_fn=mock_lookup_fn
    )
    assert result.verdict == "not_elevated"
    assert result.decision_trail[2]["reason"] == "ambiguous"


def test_formal_proof_lookup_error():
    mock_lookup_fn = MagicMock()
    mock_lookup_fn.side_effect = Exception("API fail")

    result = formal_proof_verify(
        theorem_name="定理", name_dict={"定理": "Lemma.fail"}, mathlib_lookup_fn=mock_lookup_fn
    )
    assert result.verdict == "not_elevated"
    assert result.decision_trail[1]["status"] == "error"


def test_formal_proof_empty_name():
    with pytest.raises(ValueError, match="cannot be empty"):
        formal_proof_verify(theorem_name="", name_dict={}, mathlib_lookup_fn=lambda: None)


def test_formal_proof_trail_completeness():
    mock_lookup_fn = MagicMock()
    mock_hit = MagicMock()
    mock_hit.name = "lemma_name"
    mock_hit.module = "module_name"
    mock_hit.dict.return_value = {"name": "lemma_name", "module": "module_name"}
    mock_res = MagicMock()
    mock_res.count = 1
    mock_res.hits = [mock_hit]
    mock_lookup_fn.return_value = mock_res

    result = formal_proof_verify(
        theorem_name="A", name_dict={"A": "B"}, mathlib_lookup_fn=mock_lookup_fn
    )
    # 映射 -> 查询 -> 判定
    steps = [t["step"] for t in result.decision_trail]
    assert steps == ["mapping", "lookup", "verdict"]
