"""Tests for video_cost_proposal."""

from __future__ import annotations

import pytest
from obase.provider_contract import ProviderContract, ProviderContractRegistry

from oskill._video_cost_proposal import CostProposal, video_cost_proposal


def _reg() -> ProviderContractRegistry:
    reg = ProviderContractRegistry()
    reg.register(
        ProviderContract(
            name="wan_local",
            location="local",
            capability="video_gen",
            unit_cost_usd=0.0,
            unit="per_second",
        )
    )
    reg.register(
        ProviderContract(
            name="wan_cloud",
            location="cloud",
            capability="video_gen",
            unit_cost_usd=0.08,
            unit="per_second",
        )
    )
    reg.register(
        ProviderContract(
            name="ltx2_local",
            location="local",
            capability="video_gen",
            unit_cost_usd=0.0,
            unit="per_second",
            alias_of="wan_local",
        )
    )
    reg.register(
        ProviderContract(
            name="llm_cloud",
            location="cloud",
            capability="llm",
            unit_cost_usd=0.005,
            unit="per_call",
        )
    )
    return reg


class TestVideoCostProposal:
    def test_returns_cost_proposal(self):
        shots = [{"shot_type": "generative", "provider": "wan_local", "duration_s": 5.0}]
        result = video_cost_proposal(shots=shots, contract_registry=_reg())
        assert isinstance(result, CostProposal)

    def test_economy_all_local_zero_cost(self):
        shots = [
            {"shot_type": "generative", "provider": "wan_local", "duration_s": 5.0},
            {"shot_type": "code_render", "provider": "wan_local", "duration_s": 10.0},
        ]
        result = video_cost_proposal(shots=shots, contract_registry=_reg())
        assert result.total_cost_usd == 0.0

    def test_cloud_provider_nonzero_cost(self):
        shots = [{"shot_type": "generative", "provider": "wan_cloud", "duration_s": 10.0}]
        result = video_cost_proposal(shots=shots, contract_registry=_reg())
        assert result.total_cost_usd == pytest.approx(0.80)  # 0.08 * 10

    def test_alias_pricing_equals_target_pricing(self):
        shots_local = [{"shot_type": "generative", "provider": "wan_local", "duration_s": 5.0}]
        shots_alias = [{"shot_type": "generative", "provider": "ltx2_local", "duration_s": 5.0}]
        reg = _reg()
        r_local = video_cost_proposal(shots=shots_local, contract_registry=reg)
        r_alias = video_cost_proposal(shots=shots_alias, contract_registry=reg)
        assert r_alias.total_cost_usd == r_local.total_cost_usd

    def test_locked_runtime_in_proposal(self):
        shots = [{"shot_type": "generative", "provider": "wan_local", "duration_s": 5.0}]
        result = video_cost_proposal(
            shots=shots, contract_registry=_reg(), render_runtime="generative"
        )
        assert result.locked_runtime == "generative"

    def test_per_shot_breakdown_correct(self):
        shots = [
            {"shot_type": "generative", "provider": "wan_cloud", "duration_s": 5.0},
            {"shot_type": "generative", "provider": "wan_local", "duration_s": 5.0},
        ]
        result = video_cost_proposal(shots=shots, contract_registry=_reg())
        assert len(result.per_shot) == 2
        cloud_shot = next(s for s in result.per_shot if s["provider"] == "wan_cloud")
        local_shot = next(s for s in result.per_shot if s["provider"] == "wan_local")
        assert cloud_shot["cost_usd"] == pytest.approx(0.40)
        assert local_shot["cost_usd"] == 0.0

    def test_per_call_unit_cost(self):
        shots = [{"shot_type": "generative", "provider": "llm_cloud", "duration_s": 0.0}]
        result = video_cost_proposal(shots=shots, contract_registry=_reg())
        assert result.total_cost_usd == pytest.approx(0.005)

    def test_breakdown_by_provider(self):
        shots = [
            {"shot_type": "generative", "provider": "wan_cloud", "duration_s": 5.0},
            {"shot_type": "generative", "provider": "wan_cloud", "duration_s": 5.0},
        ]
        result = video_cost_proposal(shots=shots, contract_registry=_reg())
        assert result.breakdown["by_provider"]["wan_cloud"] == pytest.approx(0.80)
