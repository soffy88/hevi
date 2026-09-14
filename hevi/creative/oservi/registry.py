"""Typed service dispatch; the registry is not a second orchestration engine."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ServiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID = Field(default_factory=uuid4)
    service: str
    project_id: UUID
    input_refs: tuple[str, ...] = ()
    idempotency_key: str


class ServiceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    service: str
    status: str
    output_refs: tuple[str, ...] = ()
    error_code: str | None = None
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


Handler = Callable[[ServiceRequest], ServiceResult]


@dataclass
class CreativeServiceRegistry:
    handlers: dict[str, Handler]

    def __init__(self) -> None:
        self.handlers = {}

    def register(self, name: str, handler: Handler) -> None:
        if name in self.handlers:
            raise ValueError(f"service already registered: {name}")
        self.handlers[name] = handler

    def call(self, request: ServiceRequest) -> ServiceResult:
        try:
            handler = self.handlers[request.service]
        except KeyError as exc:
            raise ValueError(f"service not registered: {request.service}") from exc
        result = handler(request)
        if result.request_id != request.request_id or result.service != request.service:
            raise ValueError("service returned a mismatched request identity")
        return result


__all__ = ["CreativeServiceRegistry", "ServiceRequest", "ServiceResult"]
