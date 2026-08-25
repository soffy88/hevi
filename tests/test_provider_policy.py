import pytest

from hevi.provider_policy import ProviderPolicy, evaluate_provider_policy, require_provider
from hevi.provider_policy.health import ProviderHealthService


@pytest.mark.asyncio
async def test_provider_policy_records_capability_rejections() -> None:
    decision = await evaluate_provider_policy(
        ProviderPolicy(
            mode="t2v",
            quality_floor=9,
            required_capabilities={"lip_sync"},
            candidates=["veo3", "kling_v2"],
        )
    )

    assert require_provider(decision) == "veo3"
    assert decision.eligible == ["veo3"]
    rejected = {item.provider_id: item.reasons for item in decision.rejected}
    assert any(reason.startswith("capability_missing:lip_sync") for reason in rejected["kling_v2"])


@pytest.mark.asyncio
async def test_provider_policy_fails_closed_when_budget_rejects_all() -> None:
    decision = await evaluate_provider_policy(
        ProviderPolicy(candidates=["veo3"], max_estimated_cost_usd=0.0)
    )

    with pytest.raises(ValueError, match="no provider satisfies policy"):
        require_provider(decision)


@pytest.mark.asyncio
async def test_provider_policy_persists_ordered_eligible_candidates() -> None:
    decision = await evaluate_provider_policy(
        ProviderPolicy(candidates=["veo3", "kling_v2"], quality_floor=9)
    )

    assert decision.selected_provider == decision.eligible[0]
    assert set(decision.eligible) == {"veo3", "kling_v2"}


@pytest.mark.asyncio
async def test_provider_policy_fails_closed_on_durable_runtime_state() -> None:
    class State:
        async def get(self, provider_id: str) -> dict[str, object] | None:
            assert provider_id == "veo3"
            return {"health": 0.2, "quota_remaining": 0}

    decision = await evaluate_provider_policy(
        ProviderPolicy(candidates=["veo3"], quality_floor=9),
        state_repository=State(),
    )

    reasons = decision.rejected[0].reasons
    assert "health_below_floor:0.5" in reasons
    assert "quota_below_floor:1" in reasons
    with pytest.raises(ValueError, match="no provider satisfies policy"):
        require_provider(decision)


@pytest.mark.asyncio
async def test_provider_policy_uses_quality_history_over_static_prior() -> None:
    class State:
        async def get(self, provider_id: str) -> dict[str, object] | None:
            assert provider_id == "wan_local"
            return {"quality_score": 0.95}

    decision = await evaluate_provider_policy(
        ProviderPolicy(candidates=["wan_local"], quality_floor=9),
        state_repository=State(),
    )

    assert decision.selected_provider == "wan_local"
    assert decision.candidate_scores["wan_local"]["quality"] == 0.95


@pytest.mark.asyncio
async def test_provider_health_service_persists_probe_result() -> None:
    class Repository:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def upsert(self, provider_id: str, **values: object) -> None:
            self.calls.append({"provider_id": provider_id, **values})

    repo = Repository()
    service = ProviderHealthService(
        repo, provider_ids=["veo3", "kling_v2"], probe=lambda name: _probe(name)
    )
    result = await service.sample_once()

    assert result == {"veo3": True, "kling_v2": False}
    assert repo.calls[0]["health"] == 1.0
    assert repo.calls[1]["health"] == 0.0


async def _probe(provider_id: str) -> bool:
    return provider_id == "veo3"
