"""Tests for K-AII-5: theorem_verify_3way."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from oskill._theorem_verify_3way import theorem_verify_3way

# ---------------------------------------------------------------------------
# Stub types mirroring MathlibLookupResult / MathlibHit
# ---------------------------------------------------------------------------


@dataclass
class _Hit:
    name: str
    module: str = "Mathlib"
    type_signature: str = ""


@dataclass
class _LookupResult:
    query: str = ""
    count: int = 1
    hits: list = field(default_factory=list)


def _make_lookup(count: int, lean_name: str = "Theorem.name", type_sig: str = "∀ x, P x"):
    """Return a sync callable that simulates mathlib_lookup returning one result."""

    def _lookup(candidate: str) -> _LookupResult:
        if count == 1:
            return _LookupResult(
                query=candidate,
                count=1,
                hits=[_Hit(name=lean_name, type_signature=type_sig)],
            )
        return _LookupResult(query=candidate, count=count, hits=[])

    return _lookup


def _make_llm(verdict: str, reason: str = ""):
    """Return a mock LLM that responds with the given verdict JSON."""
    payload = json.dumps({"verdict": verdict, "reason": reason})

    async def llm(*, messages, system=None, max_tokens=256, **kw):
        return {"content": [{"type": "text", "text": payload}], "usage": {}}

    return llm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTheoremVerify3Way:
    # 1. 正例：语义一致 → verified
    async def test_consistent_returns_verified(self):
        result = await theorem_verify_3way(
            ku_text="For any continuous function on [a,b], there exists c where f'(c)=0.",
            candidate_lean_names=["Rolle.theorem"],
            mathlib_lookup=_make_lookup(
                count=1,
                lean_name="Rolle.theorem",
                type_sig="∀ f : ℝ → ℝ, Differentiable ℝ f → ∃ c, deriv f c = 0",
            ),
            llm=_make_llm("consistent", "core assertion matches"),
        )
        assert result.verdict == "verified"
        assert result.lean_name == "Rolle.theorem"
        assert result.type_signature is not None
        assert result.reason == ""

    # 2. 假阳性拦截：罗尔 KU + 拉格朗日 lean_name，LLM inconsistent → rejected
    async def test_rolle_ku_lagrange_name_rejected(self):
        result = await theorem_verify_3way(
            ku_text="If f is continuous on [a,b] and f(a)=f(b), there exists c with f'(c)=0.",
            candidate_lean_names=["MeanValue.lagrange"],
            mathlib_lookup=_make_lookup(
                count=1,
                lean_name="MeanValue.lagrange",
                type_sig="∀ f, ∃ c ∈ (a,b), deriv f c = (f b - f a) / (b - a)",
            ),
            llm=_make_llm("inconsistent", "Lagrange MVT differs from Rolle's theorem"),
        )
        assert result.verdict == "rejected"
        assert result.lean_name is None

    # 3. 反向假阳性：拉格朗日 KU + 罗尔 lean_name → rejected
    async def test_lagrange_ku_rolle_name_rejected(self):
        result = await theorem_verify_3way(
            ku_text="There exists c in (a,b) such that f'(c) equals the mean slope (f(b)-f(a))/(b-a).",
            candidate_lean_names=["Rolle.theorem"],
            mathlib_lookup=_make_lookup(
                count=1,
                lean_name="Rolle.theorem",
                type_sig="∀ f, f a = f b → ∃ c, deriv f c = 0",
            ),
            llm=_make_llm("inconsistent", "Rolle requires f(a)=f(b); KU describes MVT"),
        )
        assert result.verdict == "rejected"

    # 4. count != 1 → rejected（count=0）
    async def test_count_zero_rejected(self):
        result = await theorem_verify_3way(
            ku_text="Some theorem.",
            candidate_lean_names=["Unknown.theorem"],
            mathlib_lookup=_make_lookup(count=0, lean_name="Unknown.theorem"),
            llm=_make_llm("consistent"),
        )
        assert result.verdict == "rejected"
        assert "count=0" in result.reason

    # 4b. count=2 → rejected
    async def test_count_two_rejected(self):
        result = await theorem_verify_3way(
            ku_text="Some theorem.",
            candidate_lean_names=["Ambiguous.theorem"],
            mathlib_lookup=_make_lookup(count=2, lean_name="Ambiguous.theorem"),
            llm=_make_llm("consistent"),
        )
        assert result.verdict == "rejected"
        assert "count=2" in result.reason

    # 5. LLM uncertain + strict=True → rejected（命门：不得通过）
    async def test_uncertain_strict_true_rejected(self):
        result = await theorem_verify_3way(
            ku_text="Possibly related theorem.",
            candidate_lean_names=["Maybe.theorem"],
            mathlib_lookup=_make_lookup(count=1, lean_name="Maybe.theorem"),
            llm=_make_llm("uncertain", "partial overlap"),
            strict=True,
        )
        assert result.verdict == "rejected"
        assert result.lean_name is None

    # 6. LLM uncertain + strict=False → ambiguous
    async def test_uncertain_strict_false_ambiguous(self):
        result = await theorem_verify_3way(
            ku_text="Possibly related theorem.",
            candidate_lean_names=["Maybe.theorem"],
            mathlib_lookup=_make_lookup(count=1, lean_name="Maybe.theorem"),
            llm=_make_llm("uncertain", "partial overlap"),
            strict=False,
        )
        assert result.verdict == "ambiguous"
        assert result.lean_name is None
        assert result.reason

    # 7. 空 candidates → rejected
    async def test_empty_candidates_rejected(self):
        result = await theorem_verify_3way(
            ku_text="Any theorem.",
            candidate_lean_names=[],
            mathlib_lookup=_make_lookup(count=1),
            llm=_make_llm("consistent"),
        )
        assert result.verdict == "rejected"
        assert "no candidates" in result.reason

    # 8. 多候选：第一个 reject，第二个 verified → 返回 verified
    async def test_multi_candidate_first_reject_second_verified(self):
        call_count = [0]

        def multi_lookup(candidate: str) -> _LookupResult:
            call_count[0] += 1
            if candidate == "Bad.theorem":
                return _LookupResult(query=candidate, count=0, hits=[])
            return _LookupResult(
                query=candidate,
                count=1,
                hits=[_Hit(name="Good.theorem", type_signature="∀ n : ℕ, n ≥ 0")],
            )

        result = await theorem_verify_3way(
            ku_text="Natural numbers are non-negative.",
            candidate_lean_names=["Bad.theorem", "Good.theorem"],
            mathlib_lookup=multi_lookup,
            llm=_make_llm("consistent", "matches"),
        )
        assert result.verdict == "verified"
        assert result.lean_name == "Good.theorem"
        assert call_count[0] == 2  # both candidates tried

    # 9. mathlib_lookup 抛异常 → 该候选 reject，继续下一个
    async def test_lookup_exception_skips_candidate(self):
        call_seq = [0]

        def flaky_lookup(candidate: str) -> _LookupResult:
            call_seq[0] += 1
            if call_seq[0] == 1:
                raise ConnectionError("network timeout")
            return _LookupResult(
                count=1,
                hits=[_Hit(name="Fallback.theorem", type_signature="∀ x, Q x")],
            )

        result = await theorem_verify_3way(
            ku_text="A valid theorem.",
            candidate_lean_names=["Flaky.theorem", "Fallback.theorem"],
            mathlib_lookup=flaky_lookup,
            llm=_make_llm("consistent"),
        )
        assert result.verdict == "verified"
        assert result.lean_name == "Fallback.theorem"

    # 10. LLM 返回非法 JSON → 该候选 reject
    async def test_invalid_llm_json_rejects_candidate(self):
        async def bad_llm(*, messages, system=None, max_tokens=256, **kw):
            return {"content": [{"type": "text", "text": "not json at all"}], "usage": {}}

        result = await theorem_verify_3way(
            ku_text="Some theorem.",
            candidate_lean_names=["Valid.theorem"],
            mathlib_lookup=_make_lookup(count=1, lean_name="Valid.theorem"),
            llm=bad_llm,
        )
        assert result.verdict == "rejected"

    # 11. verified 命门：lean_name 来自 mathlib_lookup，非 LLM
    async def test_verified_lean_name_from_lookup_not_llm(self):
        # LLM response says consistent but we verify lean_name is from lookup
        llm_payload = json.dumps(
            {
                "verdict": "consistent",
                "reason": "match",
                "lean_name": "LLM.injected.name",  # LLM tries to inject lean_name — must be ignored
            }
        )

        async def injecting_llm(*, messages, system=None, max_tokens=256, **kw):
            return {"content": [{"type": "text", "text": llm_payload}], "usage": {}}

        result = await theorem_verify_3way(
            ku_text="The theorem.",
            candidate_lean_names=["Mathlib.RealThm"],
            mathlib_lookup=_make_lookup(count=1, lean_name="Mathlib.RealThm", type_sig="P"),
            llm=injecting_llm,
        )
        assert result.verdict == "verified"
        assert result.lean_name == "Mathlib.RealThm"  # from lookup, not LLM
        assert result.lean_name != "LLM.injected.name"
