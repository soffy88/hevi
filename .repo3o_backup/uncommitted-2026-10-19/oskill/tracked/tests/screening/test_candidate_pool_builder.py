"""Tests for oskill.screening.candidate_pool_builder (S1)."""

from oskill.screening import candidate_pool_builder


class TestCandidatePoolBuilder:
    def test_empty_universe(self) -> None:
        result = candidate_pool_builder(universe=[], scoring_fn=lambda x: 1.0)
        assert result["candidates"] == []

    def test_all_reject(self) -> None:
        universe = [{"name": "a"}, {"name": "b"}]
        result = candidate_pool_builder(
            universe=universe, scoring_fn=lambda x: 1.0, filter_rules=[lambda x: False]
        )
        assert result["candidates"] == []

    def test_top_n_truncation(self) -> None:
        universe = [{"name": f"s{i}"} for i in range(50)]
        result = candidate_pool_builder(universe=universe, scoring_fn=lambda x: 1.0, top_n=10)
        assert len(result["candidates"]) == 10

    def test_min_score(self) -> None:
        universe = [{"name": "a", "v": 1}, {"name": "b", "v": 5}]
        result = candidate_pool_builder(universe=universe, scoring_fn=lambda x: x["v"], min_score=3)
        assert len(result["candidates"]) == 1

    def test_scoring_fn_exception(self) -> None:
        universe = [{"name": "a"}, {"name": "b"}]

        def bad_score(x):
            if x["name"] == "a":
                raise ValueError("bad")
            return 1.0

        result = candidate_pool_builder(universe=universe, scoring_fn=bad_score)
        assert result["stats"]["errors"] == 1

    def test_filter_short_circuit(self) -> None:
        universe = [{"name": "a"}]
        calls = []

        def rule1(x):
            calls.append(1)
            return False

        def rule2(x):
            calls.append(2)
            return True

        candidate_pool_builder(
            universe=universe, scoring_fn=lambda x: 1.0, filter_rules=[rule1, rule2]
        )
        assert 2 not in calls  # rule2 never called due to short-circuit


class TestRegimeAware:
    def test_injects_regime_to_candidates(self) -> None:
        """regime_aware=True injects _regime into candidate for scoring_fn."""
        seen: list[dict] = []

        def scoring_fn(candidate):
            seen.append(candidate)
            return 50.0

        candidate_pool_builder(
            universe=[{"name": "A"}, {"name": "B"}],
            scoring_fn=scoring_fn,
            regime_aware=True,
            regime="积极",
        )
        assert all(c.get("_regime") == "积极" for c in seen)

    def test_raises_if_regime_none(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="regime parameter required"):
            candidate_pool_builder(
                universe=[{"name": "A"}],
                scoring_fn=lambda x: 50.0,
                regime_aware=True,
                regime=None,
            )

    def test_metadata_records_regime(self) -> None:
        result = candidate_pool_builder(
            universe=[{"name": "A"}],
            scoring_fn=lambda x: 50.0,
            regime_aware=True,
            regime="积极",
        )
        assert result["metadata"]["regime_aware"] is True
        assert result["metadata"]["regime"] == "积极"

    def test_backward_compat_no_regime_aware(self) -> None:
        """Without regime_aware, behavior matches v3.x."""
        result = candidate_pool_builder(
            universe=[{"name": "A"}],
            scoring_fn=lambda x: 50.0,
        )
        assert result["metadata"]["regime_aware"] is False
        assert result["metadata"]["regime"] is None
