"""K-video_cost_proposal: structured cost estimation from provider contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class CostProposal:
    per_shot: list[dict]  # [{provider, cost_usd, runtime, shot_type, duration_s}]
    total_cost_usd: float
    locked_runtime: str  # "generative" | "code_render" | "mixed"
    breakdown: dict  # {by_provider: {name: total_usd}, by_runtime: {...}}


def video_cost_proposal(
    *,
    shots: list[dict],
    contract_registry,
    render_runtime: Literal["generative", "code_render", "mixed"] = "mixed",
) -> CostProposal:
    """Compute per-shot and total cost from injected ProviderContractRegistry.

    shots: list of {shot_type, provider, duration_s}
    contract_registry: E1 ProviderContractRegistry — pricing derived from contracts.
    render_runtime: locks the execution path reported in the proposal.

    Pure computation — no LLM, no I/O. Pricing is fully injected via contracts.
    """
    per_shot: list[dict] = []
    by_provider: dict[str, float] = {}
    by_runtime: dict[str, float] = {}
    total = 0.0

    for shot in shots:
        provider: str = shot.get("provider", "")
        duration_s: float = float(shot.get("duration_s", 0.0))
        shot_type: str = shot.get("shot_type", "generative")

        contract = contract_registry.resolve(provider)
        unit = contract.unit
        unit_cost = contract.unit_cost_usd

        if unit == "per_second":
            cost = unit_cost * duration_s
        elif unit == "per_call":
            cost = unit_cost
        elif unit == "per_token":
            cost = unit_cost * shot.get("tokens", 1)
        else:
            cost = unit_cost

        runtime = shot_type if render_runtime == "mixed" else render_runtime

        per_shot.append(
            {
                "provider": provider,
                "cost_usd": round(cost, 6),
                "runtime": runtime,
                "shot_type": shot_type,
                "duration_s": duration_s,
            }
        )

        total += cost
        by_provider[provider] = by_provider.get(provider, 0.0) + cost
        by_runtime[runtime] = by_runtime.get(runtime, 0.0) + cost

    return CostProposal(
        per_shot=per_shot,
        total_cost_usd=round(total, 6),
        locked_runtime=render_runtime,
        breakdown={"by_provider": by_provider, "by_runtime": by_runtime},
    )
