"""Named HEVI creative service surface over the shared runtime registry."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from hevi.creative.oservi.registry import (
    CreativeServiceRegistry,
    ServiceRequest,
    ServiceResult,
)

CREATIVE_SERVICE_NAMES = (
    "creative.project.create",
    "creative.import",
    "creative.research",
    "narrative.plan",
    "narrative.write",
    "narrative.audit",
    "narrative.revise",
    "narrative.forecast",
    "script.create",
    "storyboard.create",
    "interactive_film.create",
    "play.start",
    "play.step",
    "translation.create",
    "translation.run",
    "cover.create",
    "creative.export",
)


class CreativeServiceSurface:
    """Registration helper; execution remains owned by HEVI runtime callers."""

    def __init__(self, registry: CreativeServiceRegistry | None = None) -> None:
        self.registry = registry or CreativeServiceRegistry()

    def register(self, name: str, handler: Callable[[ServiceRequest], ServiceResult]) -> None:
        if name not in CREATIVE_SERVICE_NAMES:
            raise ValueError(f"unknown creative service: {name}")
        self.registry.register(name, handler)

    def call(self, request: ServiceRequest) -> ServiceResult:
        return self.registry.call(request)


@dataclass
class StudioAction:
    """One Studio action, from submission through confirmation to a result."""

    action_id: str
    service: str
    project_id: UUID
    idempotency_key: str
    status: str
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "service": self.service,
            "project_id": str(self.project_id),
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "error_code": self.error_code,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StudioAction:
        return cls(
            action_id=str(data["action_id"]),
            service=str(data["service"]),
            project_id=UUID(str(data["project_id"])),
            idempotency_key=str(data["idempotency_key"]),
            status=str(data["status"]),
            input_refs=tuple(str(item) for item in data.get("input_refs") or ()),
            output_refs=tuple(str(item) for item in data.get("output_refs") or ()),
            error_code=None if data.get("error_code") is None else str(data["error_code"]),
        )


class StudioActionGateway:
    """Studio confirmation/progress/artifact session over a service surface.

    The gateway owns only session mechanism: it never executes creative logic
    itself, it dispatches to the injected :class:`CreativeServiceSurface`.
    """

    def __init__(
        self, surface: CreativeServiceSurface, *, chain: list[dict[str, str]] | None = None
    ) -> None:
        self.surface = surface
        self.actions: dict[str, StudioAction] = {}
        self.order: list[str] = []
        self.chain: list[dict[str, str]] = chain if chain is not None else []

    def submit(
        self,
        *,
        service: str,
        project_id: UUID,
        idempotency_key: str,
        action_id: str | None = None,
    ) -> StudioAction:
        action = StudioAction(
            action_id=action_id or uuid4().hex,
            service=service,
            project_id=project_id,
            idempotency_key=idempotency_key,
            status="AWAITING_CONFIRMATION",
        )
        self.actions[action.action_id] = action
        self.order.append(action.action_id)
        return action

    def confirm(self, action_id: str) -> StudioAction:
        action = self.actions[action_id]
        if action.status != "AWAITING_CONFIRMATION":
            raise ValueError("STUDIO_ACTION_NOT_PENDING")
        input_refs = (self.chain[-1]["output_ref"],) if self.chain else ()
        result = self.surface.call(
            ServiceRequest(
                service=action.service,
                project_id=action.project_id,
                idempotency_key=action.idempotency_key,
                input_refs=input_refs,
            )
        )
        confirmed = StudioAction(
            action_id=action.action_id,
            service=action.service,
            project_id=action.project_id,
            idempotency_key=action.idempotency_key,
            status=result.status,
            input_refs=input_refs,
            output_refs=result.output_refs,
            error_code=result.error_code,
        )
        self.actions[action_id] = confirmed
        if confirmed.status == "SUCCEEDED":
            previous = self.chain[-1]["digest"] if self.chain else ""
            output_ref = confirmed.output_refs[0]
            digest = hashlib.sha256(f"{previous}{action.service}{output_ref}".encode()).hexdigest()
            self.chain.append(
                {"service": action.service, "output_ref": output_ref, "digest": digest}
            )
        return confirmed

    def progress(self) -> dict[str, int]:
        return {
            "completed": sum(item.status != "AWAITING_CONFIRMATION" for item in self.actions.values()),
            "total": len(self.actions),
            "chain_length": len(self.chain),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "order": list(self.order),
            "actions": {key: value.to_dict() for key, value in self.actions.items()},
            "chain": [dict(entry) for entry in self.chain],
        }

    @classmethod
    def from_dict(
        cls, surface: CreativeServiceSurface, data: dict[str, Any]
    ) -> StudioActionGateway:
        gateway = cls(surface, chain=[dict(entry) for entry in data.get("chain") or ()])
        for key, value in (data.get("actions") or {}).items():
            gateway.actions[str(key)] = StudioAction.from_dict(value)
        gateway.order = [str(item) for item in data.get("order") or ()]
        return gateway


__all__ = ["CREATIVE_SERVICE_NAMES", "CreativeServiceSurface", "StudioAction", "StudioActionGateway"]
