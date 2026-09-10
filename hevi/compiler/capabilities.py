"""Provider capability declarations consumed by the Production Compiler."""

from __future__ import annotations

from pydantic import BaseModel, Field

from hevi.production_graph.domain import GenerationIntent, ReferenceRole


class ProviderCapabilities(BaseModel):
    provider_id: str
    model: str
    supported_intents: set[GenerationIntent] = Field(default_factory=set)
    supported_reference_roles: set[ReferenceRole] = Field(default_factory=set)
    max_reference_items: int = Field(default=8, ge=0)
    max_duration_s: float = Field(default=10.0, gt=0)
    min_duration_s: float = Field(default=0.1, gt=0)
    max_prompt_length: int = Field(default=4000, gt=0)
    supported_resolutions: set[str] = Field(default_factory=lambda: {"720p"})
    default_resolution: str = "720p"
    supports_negative_prompt: bool = True
    supports_audio: bool = False
    cost_per_second_usd: float = Field(default=0.0, ge=0)
    estimated_latency_s: float | None = Field(default=None, ge=0)
    resource_profile: dict[str, object] = Field(default_factory=dict)

    def supports_intent(self, intent: GenerationIntent) -> bool:
        return intent in self.supported_intents


class ResourceBudget(BaseModel):
    """Compile-time budget and resource admission inputs."""

    max_cost_usd: float | None = Field(default=None, ge=0)
    resolution: str | None = None
    resources_available: bool = True
    resource_profile: dict[str, object] = Field(default_factory=dict)


__all__ = ["ProviderCapabilities", "ResourceBudget"]
