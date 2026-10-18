"""Tests for oskill.factor.sector_rotation."""

from __future__ import annotations

from datetime import date

import pytest

from oskill.factor.sector_rotation import sector_capital_rotation_detect


def _make_flow(sym, dt, inflow):
    return {"symbol": sym, "date": dt, "net_inflow": inflow}


class TestSectorCapitalRotationDetect:
    def test_empty_input_returns_no_rotation(self):
        result = sector_capital_rotation_detect([], {})
        assert result["rotation_detected"] is False
        assert result["top_inflow_sectors"] == []
        assert result["top_outflow_sectors"] == []
        assert result["rotation_intensity"] == 0.0

    def test_required_keys_in_result(self):
        flows = [_make_flow("A", date(2024, 1, 1), 1e6)]
        result = sector_capital_rotation_detect(flows, {"A": "tech"})
        assert "rotation_detected" in result
        assert "top_inflow_sectors" in result
        assert "top_outflow_sectors" in result
        assert "rotation_intensity" in result

    def test_single_sector_inflow(self):
        flows = [_make_flow("A", date(2024, 1, 1), 1e6)]
        result = sector_capital_rotation_detect(flows, {"A": "tech"})
        assert len(result["top_inflow_sectors"]) == 1
        assert result["top_inflow_sectors"][0]["sector"] == "tech"

    def test_outflow_detected(self):
        flows = [_make_flow("A", date(2024, 1, 1), -1e6)]
        result = sector_capital_rotation_detect(flows, {"A": "finance"})
        assert len(result["top_outflow_sectors"]) == 1
        assert result["top_outflow_sectors"][0]["sector"] == "finance"

    def test_rotation_intensity_zero_full_overlap(self):
        # same top sector in both periods
        flows = [
            _make_flow("A", date(2024, 1, 2), 1e6),
            _make_flow("A", date(2024, 1, 1), 0.9e6),
        ]
        result = sector_capital_rotation_detect(flows, {"A": "tech"}, prev_window_days=1, top_n=1)
        assert result["rotation_intensity"] == pytest.approx(0.0)

    def test_rotation_intensity_one_no_overlap(self):
        # current: tech; prev: finance
        flows = [
            _make_flow("A", date(2024, 1, 2), 1e6),  # current -> tech
            _make_flow("B", date(2024, 1, 1), 0.9e6),  # prev -> finance
        ]
        classification = {"A": "tech", "B": "finance"}
        result = sector_capital_rotation_detect(flows, classification, prev_window_days=1, top_n=1)
        assert result["rotation_intensity"] == pytest.approx(1.0)

    def test_rotation_detected_threshold(self):
        # intensity > 0.4 triggers rotation_detected
        flows = [
            _make_flow("A", date(2024, 1, 2), 1e6),
            _make_flow("B", date(2024, 1, 1), 0.9e6),
            _make_flow("C", date(2024, 1, 1), 0.8e6),
        ]
        classification = {"A": "tech", "B": "finance", "C": "energy"}
        result = sector_capital_rotation_detect(flows, classification, prev_window_days=1, top_n=3)
        assert isinstance(result["rotation_detected"], bool)

    def test_top_n_limits_results(self):
        flows = [
            _make_flow("A", date(2024, 1, 1), 3e6),
            _make_flow("B", date(2024, 1, 1), 2e6),
            _make_flow("C", date(2024, 1, 1), 1e6),
            _make_flow("D", date(2024, 1, 1), 0.5e6),
        ]
        classification = {"A": "s1", "B": "s2", "C": "s3", "D": "s4"}
        result = sector_capital_rotation_detect(flows, classification, top_n=2)
        assert len(result["top_inflow_sectors"]) <= 2

    def test_unknown_symbol_classified_as_unknown(self):
        flows = [_make_flow("UNKNOWN", date(2024, 1, 1), 1e6)]
        result = sector_capital_rotation_detect(flows, {})
        # should still return a result, just "unknown" sector
        assert result["top_inflow_sectors"][0]["sector"] == "unknown"

    def test_net_inflow_values_correct_sign(self):
        flows = [
            _make_flow("A", date(2024, 1, 1), 5e6),
            _make_flow("B", date(2024, 1, 1), -2e6),
        ]
        classification = {"A": "tech", "B": "finance"}
        result = sector_capital_rotation_detect(flows, classification)
        inflow_sectors = {s["sector"]: s["net_inflow"] for s in result["top_inflow_sectors"]}
        outflow_sectors = {s["sector"]: s["net_inflow"] for s in result["top_outflow_sectors"]}
        if "tech" in inflow_sectors:
            assert inflow_sectors["tech"] > 0
        if "finance" in outflow_sectors:
            assert outflow_sectors["finance"] < 0

    @pytest.mark.academic_reference
    def test_stovall_sector_rotation_quantitative(self):
        """Stovall (2006) Sector Rotation Quantitative Analysis.

        Compare current vs previous window sector rank. Rotation detected when
        top inflow sectors differ significantly.
        Setup: prev window top = finance; current window top = tech.
        -> full rotation (intensity=1.0, rotation_detected=True).
        """
        flows = [
            _make_flow("A", date(2024, 1, 3), 5e6),  # current: tech
            _make_flow("B", date(2024, 1, 2), 4e6),  # prev: finance
            _make_flow("C", date(2024, 1, 1), 3e6),  # prev: energy
        ]
        classification = {"A": "tech", "B": "finance", "C": "energy"}
        result = sector_capital_rotation_detect(flows, classification, prev_window_days=2, top_n=1)
        assert result["rotation_intensity"] == pytest.approx(1.0)
        assert result["rotation_detected"] is True
