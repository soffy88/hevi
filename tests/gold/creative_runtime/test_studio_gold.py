"""Gold behaviour for the Studio confirmation/progress/artifact session."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from hevi.creative.oservi import (
    CreativeServiceSurface,
    ServiceRequest,
    ServiceResult,
    StudioActionGateway,
)


def _surface() -> CreativeServiceSurface:
    surface = CreativeServiceSurface()
    for index, name in enumerate(("narrative.plan", "narrative.write")):
        digest = hashlib.sha256(f"{name}:{index}".encode()).hexdigest()

        def handler(
            request: ServiceRequest, ref: str = f"artifact:{digest}"
        ) -> ServiceResult:
            return ServiceResult(
                request_id=request.request_id,
                service=request.service,
                status="SUCCEEDED",
                output_refs=(ref,),
            )

        surface.register(name, handler)
    return surface


def test_action_requires_confirmation_before_dispatch() -> None:
    gateway = StudioActionGateway(_surface())
    action = gateway.submit(
        service="narrative.plan", project_id=uuid4(), idempotency_key="k1"
    )
    assert action.status == "AWAITING_CONFIRMATION"
    assert gateway.progress()["completed"] == 0
    confirmed = gateway.confirm(action.action_id)
    assert confirmed.status == "SUCCEEDED"
    assert gateway.progress() == {"completed": 1, "total": 1, "chain_length": 1}
    with pytest.raises(ValueError, match="STUDIO_ACTION_NOT_PENDING"):
        gateway.confirm(action.action_id)


def test_canonical_chain_links_outputs_to_inputs_and_survives_reload() -> None:
    gateway = StudioActionGateway(_surface())
    project_id = uuid4()
    for index, name in enumerate(("narrative.plan", "narrative.write")):
        action = gateway.submit(
            service=name, project_id=project_id, idempotency_key=f"k{index}"
        )
        gateway.confirm(action.action_id)
    assert gateway.chain[1]["service"] == "narrative.write"
    assert gateway.actions[gateway.order[1]].input_refs == (gateway.chain[0]["output_ref"],)
    previous = gateway.chain[0]["digest"]
    expected = hashlib.sha256(
        f"{previous}narrative.write{gateway.chain[1]['output_ref']}".encode()
    ).hexdigest()
    assert gateway.chain[1]["digest"] == expected
    reconnected = StudioActionGateway.from_dict(_surface(), gateway.to_dict())
    assert reconnected.progress() == gateway.progress()
    assert reconnected.chain == gateway.chain
