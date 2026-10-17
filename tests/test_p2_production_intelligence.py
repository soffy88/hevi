"""P2 Gold D-J control-plane acceptance tests.

These tests intentionally exercise the same repository-backed service used by
the API. They prove typed persistence and authority boundaries without
inventing a provider or task runtime.
"""

import httpx
import pytest

from hevi.api.main import app
from hevi.api.routers import studio_v2
from hevi.auth.dependencies import get_current_user
from hevi.production_graph.domain import ProductionProject
from hevi.production_graph.intelligence import (
    AdaptiveCrew,
    AntiTheaterEvidence,
    ConflictResolution,
    CrewProposal,
    CrewRole,
    DispatchLease,
    EvaluationCase,
    EvaluationResult,
    LocalizationTrack,
    NLEOperation,
    PluginManifest,
    PluginPermission,
    PluginProposal,
    ProductionIntelligenceService,
    ProductionOutcome,
    ReviewThread,
    RightsLedgerEntry,
    SpatialConstraint,
)
from hevi.production_graph.repository import ProductionGraphRepository

pytestmark = pytest.mark.p2_gold


async def _context() -> tuple[ProductionIntelligenceService, str, str]:
    repo = ProductionGraphRepository()
    snapshot = await repo.create_project(ProductionProject(user_id="p2-gold-user", title="P2 Gold"))
    return ProductionIntelligenceService(repo), snapshot.project.id, snapshot.revision.id


@pytest.mark.asyncio
async def test_gold_d_adaptive_crew_conflict_and_anti_theater() -> None:
    service, project_id, revision_id = await _context()
    crew = await service.save(
        AdaptiveCrew(project_id=project_id, revision_id=revision_id, objective="resolve continuity")
    )
    story = await service.save(
        CrewProposal(
            project_id=project_id,
            revision_id=revision_id,
            role=CrewRole.STORY,
            action_type="propose_patch",
            payload={"field": "scene.order"},
            rationale="preserves causal order",
        )
    )
    evidence = await service.save(
        AntiTheaterEvidence(
            project_id=project_id,
            revision_id=revision_id,
            proposal_id=story["id"],
            required_fields=["field", "rationale"],
            evidence_refs=[crew["id"]],
            canonical_effect="RevisionPatch proposal only",
            passed=True,
        )
    )
    resolution = await service.save(
        ConflictResolution(
            project_id=project_id,
            revision_id=revision_id,
            proposal_ids=[story["id"], evidence["id"]],
            winner_id=story["id"],
            reason="typed proposal has canonical evidence",
        )
    )
    assert crew["id"] and resolution["anti_theater_check"] is True
    assert await service.list(project_id, "crew_proposal")


@pytest.mark.asyncio
async def test_gold_e_outcome_learning_respects_authority_order() -> None:
    service, project_id, revision_id = await _context()
    outcome = ProductionOutcome(
        project_id=project_id,
        revision_id=revision_id,
        accepted=True,
        metrics={"identity": 0.97},
        artifact_id="artifact-gold-e",
    )
    saved, preference = await service.learn_from_outcome(
        outcome, preference_key="camera.motion", preference_value="restrained"
    )
    assert saved["accepted"] is True
    assert preference["source"] == f"outcome:{outcome.id}"
    assert service.resolve_preference(None, None, "policy-value", "learned-value") == "policy-value"
    assert (
        service.resolve_preference("user-value", "locked-value", "policy-value", "learned-value")
        == "user-value"
    )


@pytest.mark.asyncio
async def test_gold_f_collaboration_review_is_revision_bound() -> None:
    service, project_id, revision_id = await _context()
    review = await service.save(
        ReviewThread(
            project_id=project_id,
            revision_id=revision_id,
            base_revision_id=revision_id,
            object_type="Shot",
            object_id="shot-f",
            reviewer_id="reviewer",
            comment="Please hold the eyeline.",
        )
    )
    assert review["base_revision_id"] == revision_id
    assert await service.list(project_id, "review") == [review]


@pytest.mark.asyncio
async def test_gold_g_nle_localization_and_spatial_are_typed_records() -> None:
    service, project_id, revision_id = await _context()
    spatial = await service.save(
        SpatialConstraint(
            project_id=project_id,
            revision_id=revision_id,
            shot_id="shot-g",
            subject_id="subject-g",
            position={"x": 0.4, "y": 0.6},
            facing_degrees=90,
        )
    )
    nle = await service.save(
        NLEOperation(
            project_id=project_id,
            revision_id=revision_id,
            sequence_id="sequence-g",
            operation="subtitle",
            target_id="shot-g",
            params={"text": "Bonjour"},
        )
    )
    locale = await service.save(
        LocalizationTrack(
            project_id=project_id,
            revision_id=revision_id,
            locale="fr-FR",
            source_track_id="subtitles-g",
            segments=[{"start": 0, "end": 1, "text": "Bonjour"}],
        )
    )
    assert spatial["status"] == "VALID"
    assert nle["operation"] == "subtitle"
    assert locale["locale"] == "fr-FR"


@pytest.mark.asyncio
async def test_gold_h_distributed_recovery_preserves_checkpoint() -> None:
    service, project_id, revision_id = await _context()
    lease = DispatchLease(
        project_id=project_id,
        revision_id=revision_id,
        task_id="task-h",
        worker_id="worker-a",
        lease_token="lease-h",
        expires_at=ProductionOutcome.model_fields["created_at"].default_factory(),
        checkpoint={"stage": "render", "frame": 42},
    )
    recovered = service.recover_lease(lease, worker_id="worker-b")
    saved = await service.save(recovered)
    assert saved["state"] == "RECOVERED"
    assert saved["checkpoint"] == {"stage": "render", "frame": 42}


@pytest.mark.asyncio
async def test_gold_i_plugin_security_allows_typed_proposals_only() -> None:
    service, project_id, revision_id = await _context()
    manifest = await service.save(
        PluginManifest(
            project_id=project_id,
            revision_id=revision_id,
            plugin_name="continuity-checker",
            plugin_version="1.0.0",
            permissions=[PluginPermission.READ_GRAPH, PluginPermission.PROPOSE_PATCH],
            signature="test-signature",
            enabled=True,
        )
    )
    proposal = await service.save(
        PluginProposal(
            project_id=project_id,
            revision_id=revision_id,
            plugin_id=manifest["id"],
            action_type="revision_patch",
            payload={"operations": []},
            validated=True,
        )
    )
    assert manifest["enabled"] is True
    assert proposal["validated"] is True


@pytest.mark.asyncio
async def test_gold_j_evaluation_and_rights_link_evidence() -> None:
    service, project_id, revision_id = await _context()
    case = await service.save(
        EvaluationCase(
            project_id=project_id,
            revision_id=revision_id,
            name="identity-regression",
            input_refs=["artifact-j"],
            expected={"identity": 0.9},
            metric_names=["identity"],
        )
    )
    result = await service.save(
        EvaluationResult(
            project_id=project_id,
            revision_id=revision_id,
            case_id=case["id"],
            metrics={"identity": 0.97},
            passed=True,
            evidence_refs=["artifact-j"],
        )
    )
    right = await service.save(
        RightsLedgerEntry(
            project_id=project_id,
            revision_id=revision_id,
            asset_id="artifact-j",
            right_type="source",
            licensor="public-domain",
            license_id="CC0",
            territories=["WORLDWIDE"],
            evidence_refs=[result["id"]],
        )
    )
    assert result["passed"] is True
    assert right["allowed"] is True
    assert right["evidence_refs"] == [result["id"]]


@pytest.mark.asyncio
async def test_p2_api_persists_typed_record_through_studio_boundary() -> None:
    repo = ProductionGraphRepository()
    user = {"id": "p2-api-user", "is_active": True}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[studio_v2.get_graph_repository] = lambda: repo
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/studio/projects", json={"title": "P2 API"})
            assert created.status_code == 201
            project = created.json()["project"]
            response = await client.post(
                f"/api/studio/projects/{project['id']}/intelligence",
                json={
                    "kind": "spatial",
                    "record": {
                        "shot_id": "shot-api",
                        "subject_id": "subject-api",
                        "position": {"x": 0.5, "y": 0.5},
                    },
                },
            )
            assert response.status_code == 201
            listed = await client.get(f"/api/studio/projects/{project['id']}/intelligence/spatial")
            assert listed.status_code == 200
            assert listed.json()["records"][0]["shot_id"] == "shot-api"
    finally:
        app.dependency_overrides.clear()
