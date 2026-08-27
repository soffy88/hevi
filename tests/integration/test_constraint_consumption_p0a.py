"""P0-A: real PostgreSQL constraint-consumption receipt integration tests."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from obase.persistence import PgPool

from hevi.constraints import (
    Constraint,
    ConstraintGraph,
    ConstraintRepository,
    ConsumptionStage,
    CoverageReport,
    ProviderCapabilities,
    compile_graph,
)
from hevi.production.adapters import ProductionAdapterRegistry
from hevi.production_graph.repository import ProductionGraphRepository


def _payload_hash(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class _Scenario:
    production_id: uuid.UUID
    revision_id: uuid.UUID
    attempt_id: uuid.UUID
    graph: ConstraintGraph
    compiled_ids: list[str]


class _FakeProviderSubmitService:
    """Deterministic provider network boundary used behind the real registry."""

    def __init__(self, *, job_id: str, error: Exception | None = None) -> None:
        self.job_id = job_id
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def submit(self, payload: dict[str, Any]) -> str:
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return self.job_id


class _ConstraintProviderAdapter:
    """A deterministic adapter installed through ProductionAdapterRegistry."""

    def __init__(
        self,
        provider: _FakeProviderSubmitService,
        *,
        fail_mapping: bool = False,
        mapped_constraint_ids: set[str] | None = None,
    ) -> None:
        self.provider = provider
        self.fail_mapping = fail_mapping
        self.mapped_constraint_ids = mapped_constraint_ids

    async def __call__(self, task: dict[str, Any], pool: PgPool) -> dict[str, Any]:
        repo = ConstraintRepository(pool)
        compiled = list(task["compiled_instructions"])
        mappings: list[dict[str, Any]] = []
        for instruction in compiled:
            constraint_id = str(instruction["constraint_id"])
            if self.mapped_constraint_ids is not None and constraint_id not in self.mapped_constraint_ids:
                continue
            if self.fail_mapping:
                raise ValueError(f"adapter mapping failed for {constraint_id}")
            mapping = {
                "constraint_id": constraint_id,
                "mapping_type": "prompt",
                "mapping_path": f"request.constraints[{len(mappings)}]",
                "payload": instruction["payload"],
            }
            mappings.append(mapping)
            await repo.record_consumption_receipt(
                production_id=uuid.UUID(task["production_id"]),
                revision_id=uuid.UUID(task["revision_id"]),
                attempt_id=uuid.UUID(task["attempt_id"]),
                constraint_id=constraint_id,
                provider_id="fake-provider",
                adapter_id="production-constraint-adapter",
                stage=ConsumptionStage.ADAPTER_CONSUMED,
                mapping_type=mapping["mapping_type"],
                mapping_path=mapping["mapping_path"],
                payload_hash=_payload_hash(mapping["payload"]),
            )

        payload = {"constraints": mappings}
        job_id = await self.provider.submit(payload)
        for mapping in mappings:
            for stage in (ConsumptionStage.PROVIDER_SUBMITTED, ConsumptionStage.PROVIDER_ACKED):
                await repo.record_consumption_receipt(
                    production_id=uuid.UUID(task["production_id"]),
                    revision_id=uuid.UUID(task["revision_id"]),
                    attempt_id=uuid.UUID(task["attempt_id"]),
                    constraint_id=mapping["constraint_id"],
                    provider_id="fake-provider",
                    adapter_id="production-constraint-adapter",
                    stage=stage,
                    mapping_type=mapping["mapping_type"],
                    mapping_path=mapping["mapping_path"],
                    payload_hash=_payload_hash(mapping["payload"]),
                    provider_request_id=job_id,
                )
        return {"status": "submitted", "job_id": job_id, "mapped": len(mappings)}


async def _scenario(pool: PgPool, count: int = 2) -> _Scenario:
    production_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    constraints = [
        Constraint(
            id=f"p0a-{production_id.hex}-identity",
            type="identity",
            severity="required",
            scope="shot:0",
            payload={"subject": "alice"},
        ),
        Constraint(
            id=f"p0a-{production_id.hex}-wardrobe",
            type="wardrobe",
            severity="required",
            scope="shot:0",
            payload={"outfit": "blue"},
        ),
    ][:count]
    graph = ConstraintGraph(
        revision_id=None,
        constraints=constraints,
        coverage=CoverageReport(expected_fields=count, derived_constraints=count),
    )
    record = await ProductionGraphRepository(pool).create(
        {
            "work_id": str(production_id),
            "user_id": "p0a-integration",
            "type": "p0a",
            "status": "draft",
            "constraint_graph": graph.model_dump(mode="json"),
        }
    )
    revision_id = uuid.UUID(str(record["revision_id"]))
    compiled = compile_graph(
        graph,
        ProviderCapabilities(
            provider_id="fake-provider",
            adapter_id="production-constraint-adapter",
        ),
    )
    repo = ConstraintRepository(pool)
    await repo.record_compilation(
        str(revision_id),
        compiled=len(compiled.compiled_constraint_ids),
        consumed=0,
        unsupported=len(compiled.unsupported),
        silent_drops=len(compiled.silent_drops),
    )
    for instruction in compiled.instructions:
        await repo.record_consumption_receipt(
            production_id=production_id,
            revision_id=revision_id,
            attempt_id=attempt_id,
            constraint_id=str(instruction["constraint_id"]),
            provider_id="fake-provider",
            adapter_id="production-constraint-adapter",
            stage=ConsumptionStage.COMPILED,
            mapping_type="compiled",
            mapping_path=f"compiled.instructions[{compiled.compiled_constraint_ids.index(instruction['constraint_id'])}]",
            payload_hash=_payload_hash(instruction),
        )
    return _Scenario(production_id, revision_id, attempt_id, graph, compiled.compiled_constraint_ids)


async def _rows(pool: PgPool, scenario: _Scenario) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT constraint_id, stage, mapping_path, payload_hash, provider_request_id
            FROM constraint_consumption_receipts
            WHERE production_id = $1 AND revision_id = $2 AND attempt_id = $3
            ORDER BY constraint_id, stage
            """,
            scenario.production_id,
            scenario.revision_id,
            scenario.attempt_id,
        )
    return [dict(row) for row in rows]


async def _cleanup(pool: PgPool, scenario: _Scenario) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM constraint_consumption_receipts WHERE production_id = $1",
            scenario.production_id,
        )
        await conn.execute("DELETE FROM productions WHERE id = $1", scenario.production_id)


@pytest.mark.asyncio
async def test_p0a_a1_compile_success_adapter_mapping_failure(pool: PgPool) -> None:
    scenario = await _scenario(pool)
    try:
        provider = _FakeProviderSubmitService(job_id="unused-a1")
        registry = ProductionAdapterRegistry()
        registry.register("p0a", _ConstraintProviderAdapter(provider, fail_mapping=True))
        with pytest.raises(ValueError, match="adapter mapping failed"):
            await registry.execute(
                {
                    "config_json": {"production_source": "p0a"},
                    "production_id": str(scenario.production_id),
                    "revision_id": str(scenario.revision_id),
                    "attempt_id": str(scenario.attempt_id),
                    "compiled_instructions": [
                        {"constraint_id": cid, "payload": {"id": cid}}
                        for cid in scenario.compiled_ids
                    ],
                },
                pool,
            )
        stages = {row["stage"] for row in await _rows(pool, scenario)}
        assert stages == {"compiled"}
        assert not provider.calls
    finally:
        await _cleanup(pool, scenario)


@pytest.mark.asyncio
async def test_p0a_a2_adapter_success_provider_submit_failure(pool: PgPool) -> None:
    scenario = await _scenario(pool)
    try:
        provider = _FakeProviderSubmitService(
            job_id="unused-a2", error=RuntimeError("provider submit failed")
        )
        registry = ProductionAdapterRegistry()
        registry.register("p0a", _ConstraintProviderAdapter(provider))
        with pytest.raises(RuntimeError, match="provider submit failed"):
            await registry.execute(
                {
                    "config_json": {"production_source": "p0a"},
                    "production_id": str(scenario.production_id),
                    "revision_id": str(scenario.revision_id),
                    "attempt_id": str(scenario.attempt_id),
                    "compiled_instructions": [
                        {"constraint_id": cid, "payload": {"id": cid}}
                        for cid in scenario.compiled_ids
                    ],
                },
                pool,
            )
        stages = {row["stage"] for row in await _rows(pool, scenario)}
        assert stages == {"compiled", "adapter_consumed"}
        assert not {"provider_submitted", "provider_acked"} & stages
    finally:
        await _cleanup(pool, scenario)


@pytest.mark.asyncio
async def test_p0a_a3_provider_submit_success_returns_job_id(pool: PgPool) -> None:
    scenario = await _scenario(pool)
    try:
        job_id = f"fake-job-{uuid.uuid4().hex}"
        provider = _FakeProviderSubmitService(job_id=job_id)
        registry = ProductionAdapterRegistry()
        registry.register("p0a", _ConstraintProviderAdapter(provider))
        result = await registry.execute(
            {
                "config_json": {"production_source": "p0a"},
                "production_id": str(scenario.production_id),
                "revision_id": str(scenario.revision_id),
                "attempt_id": str(scenario.attempt_id),
                "compiled_instructions": [
                    {"constraint_id": cid, "payload": {"id": cid}}
                    for cid in scenario.compiled_ids
                ],
            },
            pool,
        )
        assert result["job_id"] == job_id
        rows = await _rows(pool, scenario)
        assert {row["stage"] for row in rows} == {
            "compiled",
            "adapter_consumed",
            "provider_submitted",
            "provider_acked",
        }
        for row in rows:
            if row["stage"] != "compiled":
                assert row["mapping_path"]
                assert row["payload_hash"]
            if row["stage"] == "provider_acked":
                assert row["provider_request_id"] == job_id
    finally:
        await _cleanup(pool, scenario)


@pytest.mark.asyncio
async def test_p0a_a4_required_unmapped_is_not_consumed(pool: PgPool) -> None:
    scenario = await _scenario(pool)
    try:
        provider = _FakeProviderSubmitService(job_id="fake-job-a4")
        registry = ProductionAdapterRegistry()
        registry.register(
            "p0a",
            _ConstraintProviderAdapter(provider, mapped_constraint_ids={scenario.compiled_ids[0]}),
        )
        await registry.execute(
            {
                "config_json": {"production_source": "p0a"},
                "production_id": str(scenario.production_id),
                "revision_id": str(scenario.revision_id),
                "attempt_id": str(scenario.attempt_id),
                "compiled_instructions": [
                    {"constraint_id": cid, "payload": {"id": cid}}
                    for cid in scenario.compiled_ids
                ],
            },
            pool,
        )
        rows = await _rows(pool, scenario)
        unmapped = scenario.compiled_ids[1]
        assert not any(
            row["constraint_id"] == unmapped and row["stage"] != "compiled" for row in rows
        )
        coverage = await ConstraintRepository(pool).get_consumption_coverage(
            str(scenario.production_id),
            revision_id=str(scenario.revision_id),
            attempt_id=str(scenario.attempt_id),
        )
        assert coverage["silent_drop_rate"] > 0
        assert coverage["provider_submission_rate"] < 1.0
    finally:
        await _cleanup(pool, scenario)
