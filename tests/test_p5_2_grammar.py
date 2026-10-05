"""HEVI P5.2 — Parts A/B/C: entity graph, shot readiness, creative variety.

Covers the ProductionEntityGraph, entity identity and continuity, the shot
readiness contract, unready-generation blocking, asset candidate selection, the
creative ledger, the variety audit and justified repetition.
"""

from __future__ import annotations

import pytest

from hevi.production.creative_ledger import (
    CreativeLedger,
    VarietyFindingKind,
    duration_bucket,
    fingerprint_from_shot,
)
from hevi.production.entities import (
    EntityRelation,
    EntityType,
    ProductionEntity,
    ProductionEntityGraph,
    VisualConstraint,
    audit_continuity,
    identity_key,
    normalise_name,
    person_entity,
    product_entity,
)
from hevi.production.references import (
    REFERENCES,
    AdoptionMode,
    assert_license_boundary,
    audit_summary,
    record_for,
)
from hevi.production.shot_readiness import (
    AssetCandidate,
    AssetCandidateState,
    EvidenceStatus,
    ShotPreparation,
    ShotReadinessError,
    ShotState,
    assert_ready_for_generation,
    audit_shot_batch,
    evaluate_readiness,
    needs_human_review,
    select_candidate,
)

# ── test_entity_graph ────────────────────────────────────────────────────


def test_entity_graph_holds_typed_entities_and_relationships() -> None:
    graph = ProductionEntityGraph("proj-1")
    person, _ = graph.register(person_entity("Ada Lovelace", face_ref="faces/ada.png"))
    product, _ = graph.register(
        product_entity("Acme Console", official_url="https://acme.dev", logo_ref="logo.png")
    )
    edge = graph.relate(
        person.entity_id, EntityRelation.DEMONSTRATES, product.entity_id
    )
    assert edge is not None
    assert graph.count() == 2
    assert graph.neighbours(person.entity_id) == [product.entity_id]
    assert graph.of_type(EntityType.PRODUCT) == [product]
    payload = graph.to_dict()
    assert payload["project_id"] == "proj-1"
    assert len(payload["entities"]) == 2
    assert payload["relationships"][0]["relation"] == "DEMONSTRATES"


def test_entity_graph_covers_every_required_relation() -> None:
    required = {r.value for r in EntityRelation}
    assert required == {
        "APPEARS_IN", "USES", "WEARS", "LOCATED_IN",
        "BELONGS_TO", "REPRESENTS", "DEMONSTRATES", "REFERENCES",
    }


def test_entity_graph_covers_every_required_entity_type() -> None:
    required = {
        "PERSON", "CHARACTER", "PRODUCT", "BOOK", "LOCATION", "SCENE",
        "PROP", "CLOTHING", "UI_PRODUCT", "DOCUMENT", "BRAND", "VISUAL_STYLE",
    }
    assert required == {e.value for e in EntityType}


def test_relate_rejects_unknown_entities() -> None:
    graph = ProductionEntityGraph("proj")
    assert graph.relate("nope", EntityRelation.USES, "also-nope") is None


def test_entity_graph_is_not_an_asset_database() -> None:
    """Entities reference canonical media; they never own it."""
    product = product_entity(
        "Acme", official_url="https://acme.dev", evidence_refs=["artifact://shot1"]
    )
    assert product.canonical_assets == ["artifact://shot1"]
    assert "path" not in product.to_dict()
    assert "blob" not in product.to_dict()


# ── test_entity_identity ─────────────────────────────────────────────────


def test_entity_identity_is_stable_across_shots() -> None:
    """A1: the same thing written twice must not become two identities."""
    graph = ProductionEntityGraph("proj")
    first, created_first = graph.register(person_entity("Ada Lovelace", face_ref="a.png"))
    second, created_second = graph.register(person_entity("ada  lovelace", face_ref="b.png"))
    assert created_first is True
    assert created_second is False
    assert first.entity_id == second.entity_id
    assert graph.count() == 1


def test_entity_identity_normalises_punctuation_and_articles() -> None:
    assert normalise_name("The Acme Console.") == normalise_name("acme console")
    assert identity_key(product_entity("Acme Console")) == "PRODUCT:acmeconsole"


def test_entity_identity_treats_a_variant_as_a_distinct_entity() -> None:
    v1 = ProductionEntity(entity_type=EntityType.PRODUCT, canonical_name="Acme")
    v2 = ProductionEntity(
        entity_type=EntityType.PRODUCT, canonical_name="Acme", variant_of="v1"
    )
    assert identity_key(v1) != identity_key(v2)
    graph = ProductionEntityGraph("proj")
    graph.register(v1)
    graph.register(v2)
    assert graph.count() == 2


def test_entity_resolves_by_alias() -> None:
    graph = ProductionEntityGraph("proj")
    person, _ = graph.register(person_entity("Ada Lovelace"))
    person.aliases.append("AL")
    assert graph.resolve("al") is person
    assert graph.resolve("nobody") is None


def test_entity_alias_colliding_with_a_live_name_is_drift() -> None:
    graph = ProductionEntityGraph("proj")
    person, _ = graph.register(person_entity("Ada Lovelace"))
    graph.register(product_entity("Acme Console", official_url="https://acme.dev"))
    person.aliases.append("Acme Console")
    report = audit_continuity(graph)
    assert report.ok is False
    assert any("ENTITY_IDENTITY_DRIFT" in v for v in report.violations)


# ── test_entity_continuity ───────────────────────────────────────────────


def test_entity_continuity_passes_when_nothing_drifts() -> None:
    graph = ProductionEntityGraph("proj")
    person, _ = graph.register(
        person_entity("Ada", face_ref="a.png", clothing_ref="navy.png", framing="medium")
    )
    graph.bind_shot("shot_1", [person.entity_id])
    graph.bind_shot("shot_2", [person.entity_id])
    report = audit_continuity(
        graph,
        declared_states={
            person.entity_id: {
                "clothing_reference": {"shot_1": "navy", "shot_2": "navy"},
                "framing": {"shot_1": "medium", "shot_2": "medium"},
            }
        },
    )
    assert report.ok is True
    assert report.gates["PRODUCTION_ENTITY_GRAPH"] is True
    assert graph.shots_for(person.entity_id) == ["shot_1", "shot_2"]


def test_entity_continuity_detects_a_changed_costume() -> None:
    """A2: a character asset changing without a revision is continuity drift."""
    graph = ProductionEntityGraph("proj")
    person, _ = graph.register(person_entity("Ada", clothing_ref="navy.png"))
    report = audit_continuity(
        graph,
        declared_states={
            person.entity_id: {"clothing_reference": {"shot_1": "navy", "shot_2": "red"}}
        },
    )
    assert report.ok is False
    assert report.gates["CHARACTER_CONTINUITY"] is False
    assert any("CONTINUITY_DRIFT" in v for v in report.violations)


def test_entity_continuity_requires_a_revision_to_change_identity() -> None:
    graph = ProductionEntityGraph("proj")
    original, _ = graph.register(person_entity("Ada", face_ref="a.png"))
    revised = ProductionEntity(
        entity_type=EntityType.PERSON, canonical_name="Ada", variant_of=original.entity_id
    )
    graph.register(revised)
    assert original.entity_id != revised.entity_id
    assert revised.variant_of == original.entity_id


def test_unverified_brand_token_blocks_product_continuity() -> None:
    """A3: a brand token the model guessed must not pass."""
    graph = ProductionEntityGraph("proj")
    graph.register(
        ProductionEntity(
            entity_type=EntityType.BRAND,
            canonical_name="Acme",
            visual_constraints=[VisualConstraint(key="logo", value="guessed.png", verified=False)],
        )
    )
    report = audit_continuity(graph)
    assert report.ok is False
    assert any("UNVERIFIED_BRAND_TOKEN" in v for v in report.violations)


def test_verified_brand_token_passes() -> None:
    graph = ProductionEntityGraph("proj")
    graph.register(
        ProductionEntity(
            entity_type=EntityType.BRAND,
            canonical_name="Acme",
            visual_constraints=[
                VisualConstraint(
                    key="logo", value="logo.png", verified=True, source_ref="https://acme.dev/brand"
                )
            ],
        )
    )
    assert audit_continuity(graph).ok is True


def test_empty_continuity_binding_blocks() -> None:
    graph = ProductionEntityGraph("proj")
    person, _ = graph.register(person_entity("Ada"))
    report = audit_continuity(graph, asset_bindings={person.entity_id: {"shot_1": []}})
    assert report.ok is False


# ── test_shot_readiness ─────────────────────────────────────────────────


def _ready_preparation(**overrides) -> ShotPreparation:
    base = {
        "shot_id": "shot_1",
        "beat_id": "beat_1",
        "audio_range": (0.0, 4.2),
        "presentation_role": "DIRECT_ADDRESS",
        "renderer": "remotion",
        "required_renderer_capabilities": ["TEXT"],
    }
    base.update(overrides)
    return ShotPreparation(**base)


def test_shot_readiness_reports_every_contract_field() -> None:
    graph = ProductionEntityGraph("proj")
    person, _ = graph.register(person_entity("Ada"))
    prep = _ready_preparation(
        required_entity_ids=[person.entity_id], required_asset_refs=["bg.mp4"]
    )
    report = evaluate_readiness(
        prep, graph=graph, available_assets={"bg.mp4"},
        renderer_capabilities={"TEXT"}, now="2026-09-27T00:00:00Z",
    )
    payload = report.to_dict()
    for field in (
        "shot_id", "state", "required_entities", "resolved_entities",
        "required_assets", "resolved_assets", "missing_assets",
        "evidence_status", "audio_range", "renderer", "blocking_reasons", "ready_at",
    ):
        assert field in payload, field
    assert report.ready is True
    assert report.ready_at == "2026-09-27T00:00:00Z"


def test_shot_readiness_starts_unprepared() -> None:
    assert ShotPreparation(shot_id="s").state is ShotState.UNPREPARED


def test_missing_visual_beat_blocks() -> None:
    prep = _ready_preparation(beat_id="")
    report = evaluate_readiness(prep)
    assert report.state is ShotState.BLOCKED
    assert "VISUAL_BEAT_UNRESOLVED" in report.blocking_reasons


def test_unresolved_entity_blocks() -> None:
    prep = _ready_preparation(required_entity_ids=["ghost"])
    report = evaluate_readiness(prep, graph=ProductionEntityGraph("p"))
    assert "ENTITY_UNRESOLVED:ghost" in report.blocking_reasons


def test_missing_asset_blocks_and_is_listed() -> None:
    prep = _ready_preparation(required_asset_refs=["bg.mp4", "evidence.png"])
    report = evaluate_readiness(prep, available_assets={"bg.mp4"})
    assert report.missing_assets == ["evidence.png"]
    assert report.state is ShotState.BLOCKED


def test_missing_evidence_cannot_be_ready() -> None:
    """A5: evidence required but absent must not be READY."""
    prep = _ready_preparation(required_asset_refs=["bg.mp4"], evidence_required=True)
    report = evaluate_readiness(prep, available_assets={"bg.mp4"})
    assert report.evidence_status is EvidenceStatus.REQUIRED_MISSING
    assert report.state is ShotState.BLOCKED


def test_unresolved_audio_range_blocks() -> None:
    prep = _ready_preparation(audio_range=None)
    assert "AUDIO_RANGE_UNRESOLVED" in evaluate_readiness(prep).blocking_reasons


def test_inverted_audio_range_blocks() -> None:
    prep = _ready_preparation(audio_range=(4.0, 1.0))
    assert "AUDIO_RANGE_INVALID" in evaluate_readiness(prep).blocking_reasons


def test_unresolved_presentation_role_blocks() -> None:
    prep = _ready_preparation(presentation_role="")
    assert "PRESENTATION_ROLE_UNRESOLVED" in evaluate_readiness(prep).blocking_reasons


def test_missing_renderer_capability_blocks() -> None:
    prep = _ready_preparation(required_renderer_capabilities=["CANVAS"])
    report = evaluate_readiness(prep, renderer_capabilities={"TEXT"})
    assert any("RENDERER_CAPABILITY_MISSING" in r for r in report.blocking_reasons)


def test_unavailable_renderer_blocks() -> None:
    prep = _ready_preparation(renderer="manim")
    report = evaluate_readiness(prep, available_renderers={"remotion"})
    assert "RENDERER_UNAVAILABLE:manim" in report.blocking_reasons


def test_unknown_provenance_blocks() -> None:
    prep = _ready_preparation(provenance_known=False)
    assert "PROVENANCE_UNKNOWN" in evaluate_readiness(prep).blocking_reasons


# ── test_unready_generation_block ────────────────────────────────────────


@pytest.mark.parametrize(
    "state",
    [
        ShotState.UNPREPARED, ShotState.RESOLVING, ShotState.REVIEW_REQUIRED,
        ShotState.BLOCKED, ShotState.GENERATING, ShotState.GENERATED,
    ],
)
def test_unready_generation_block(state: ShotState) -> None:
    """A4: no state other than READY may start expensive generation."""
    with pytest.raises(ShotReadinessError):
        assert_ready_for_generation(ShotPreparation(shot_id="s", state=state))


def test_ready_shot_may_generate() -> None:
    assert_ready_for_generation(ShotPreparation(shot_id="s", state=ShotState.READY))


def test_unready_generation_error_names_the_shot_and_reasons() -> None:
    prep = ShotPreparation(shot_id="shot_9", state=ShotState.BLOCKED,
                           blocking_reasons=["ASSET_UNRESOLVED:bg.mp4"])
    with pytest.raises(ShotReadinessError) as excinfo:
        assert_ready_for_generation(prep)
    assert "shot_9" in str(excinfo.value)
    assert "ASSET_UNRESOLVED" in str(excinfo.value)


def test_shot_batch_audit_reports_readiness() -> None:
    preps = [
        _ready_preparation(shot_id="a"),
        _ready_preparation(shot_id="b", required_asset_refs=["missing.mp4"]),
    ]
    evaluate_readiness(preps[0], available_assets=set())
    evaluate_readiness(preps[1], available_assets=set())
    audit = audit_shot_batch(preps)
    assert audit["ready"] == 1
    assert audit["blocked"] == 1
    assert audit["UNREADY_SHOT_GENERATION"] == 0


# ── test_asset_candidate_selection ───────────────────────────────────────


def test_asset_candidate_may_have_several_options() -> None:
    prep = _ready_preparation(required_asset_refs=["ev.png"])
    prep.candidates = [
        AssetCandidate(candidate_id="c1", requirement_id="ev.png", asset_ref="a.png", confidence=0.4),
        AssetCandidate(candidate_id="c2", requirement_id="ev.png", asset_ref="b.png", confidence=0.4),
    ]
    assert {c.state for c in prep.candidates} == {AssetCandidateState.CANDIDATE}


def test_confident_candidate_is_selected_and_others_rejected() -> None:
    prep = _ready_preparation(required_asset_refs=["ev.png"])
    # S3 契约收紧:自动选择要求 confidence 有 canonical 生产者(scored_by)。
    # 来源不明的分数不作为证据(同 R-P10-03:高数值不等于真实证据)。
    prep.candidates = [
        AssetCandidate(candidate_id="c1", requirement_id="ev.png", asset_ref="low.png",
                       confidence=0.3, verified=True, scored_by="fixture"),
        AssetCandidate(candidate_id="c2", requirement_id="ev.png", asset_ref="high.png",
                       confidence=0.95, verified=True, scored_by="fixture"),
    ]
    chosen = select_candidate(prep, "ev.png")
    assert chosen is not None and chosen.asset_ref == "high.png"
    assert chosen.state is AssetCandidateState.SELECTED
    assert chosen.lineage and chosen.lineage[0].startswith("selected:")
    other = next(c for c in prep.candidates if c.candidate_id == "c1")
    assert other.state is AssetCandidateState.REJECTED


def test_candidate_without_scored_by_is_not_auto_selected() -> None:
    """S3:confidence 无来源 = 不自动选(留 REVIEW_REQUIRED),不猜。"""
    prep = _ready_preparation(required_asset_refs=["ev.png"])
    prep.candidates = [
        AssetCandidate(candidate_id="c1", requirement_id="ev.png", asset_ref="high.png",
                       confidence=0.99, verified=True)
    ]
    assert select_candidate(prep, "ev.png") is None


def test_unverified_candidate_is_not_auto_selected() -> None:
    """§20: automation must not force a pick it does not believe."""
    prep = _ready_preparation(required_asset_refs=["ev.png"])
    prep.candidates = [
        AssetCandidate(candidate_id="c1", requirement_id="ev.png", asset_ref="a.png",
                       confidence=0.99, verified=False)
    ]
    assert select_candidate(prep, "ev.png") is None
    assert needs_human_review(prep) is True


def test_low_confidence_candidate_requires_human_review() -> None:
    prep = _ready_preparation(required_asset_refs=["ev.png"])
    prep.candidates = [
        AssetCandidate(candidate_id="c1", requirement_id="ev.png", asset_ref="a.png",
                       confidence=0.4, verified=True)
    ]
    report = evaluate_readiness(prep)
    assert report.state is ShotState.REVIEW_REQUIRED
    assert report.blocking_reasons == ["HUMAN_SELECTION_REQUIRED"]


# ── test_creative_ledger ─────────────────────────────────────────────────


def test_creative_ledger_records_shots_per_video() -> None:
    ledger = CreativeLedger()
    for index in range(3):
        ledger.record(
            fingerprint_from_shot(f"shot_{index}", "v1", layout="split", transition="cut",
                                  motion="push", camera="static", duration_s=3.0)
        )
    assert len(ledger.shots("v1")) == 3
    assert ledger.video_ids() == ["v1"]
    assert ledger.all_shots().__len__() == 3


def test_creative_ledger_covers_every_fingerprint_field() -> None:
    fingerprint = fingerprint_from_shot(
        "s1", "v1", layout="l", transition="t", motion="m", camera="c",
        speaker_layout="pip", evidence_layout="full", caption_layout="lower",
        accent="teal", theme="dark", duration_s=4.5, entrance="rise", exit="fade",
        component="c0", profile_id="KNOWLEDGE_TALK_FINECUT", narrative_phase="HOOK",
    )
    payload = fingerprint.to_dict()
    for field in (
        "layout_family", "transition_family", "motion_family", "camera_family",
        "speaker_layout", "evidence_layout", "caption_layout", "accent_family",
        "duration_bucket",
    ):
        assert field in payload, field
    assert payload["duration_bucket"] == "MEDIUM"


def test_duration_buckets_are_ordered() -> None:
    assert duration_bucket(1.0) == "MICRO"
    assert duration_bucket(2.5) == "SHORT"
    assert duration_bucket(4.5) == "MEDIUM"
    assert duration_bucket(8.0) == "LONG"
    assert duration_bucket(14.0) == "EPIC"


def test_creative_ledger_supports_cross_video_memory() -> None:
    ledger = CreativeLedger()
    ledger.record(fingerprint_from_shot("a1", "v1", layout="l", transition="cut",
                                        motion="m", camera="c"))
    ledger.record(fingerprint_from_shot("b1", "v2", layout="l", transition="cut",
                                        motion="m", camera="c"))
    assert ledger.history_size() == 2
    assert set(ledger.video_ids()) == {"v1", "v2"}


# ── test_variety_audit ──────────────────────────────────────────────────


def test_variety_audit_flags_repeated_families() -> None:
    ledger = CreativeLedger(repeat_limit=2)
    for index in range(5):
        ledger.record(
            fingerprint_from_shot(f"s{index}", "v1", layout="split", transition="cut",
                                  motion="push", camera="static", accent="teal",
                                  theme="dark", duration_s=4.0)
        )
    audit = ledger.audit(video_id="v1")
    kinds = {f.kind for f in audit.findings}
    assert VarietyFindingKind.REPEATED_TRANSITION in kinds
    assert VarietyFindingKind.REPEATED_LAYOUT in kinds
    assert VarietyFindingKind.REPEATED_CAMERA_MOVE in kinds
    assert VarietyFindingKind.REPEATED_ACCENT in kinds
    assert VarietyFindingKind.UNIFORM_SHOT_LENGTH in kinds
    assert audit.ok is False


def test_variety_audit_flags_repeated_entrance_and_exit() -> None:
    ledger = CreativeLedger(repeat_limit=1)
    for index in range(3):
        ledger.record(
            fingerprint_from_shot(f"s{index}", "v1", layout=f"l{index}", transition=f"t{index}",
                                  motion=f"m{index}", camera=f"c{index}",
                                  entrance="rise", exit="fade", duration_s=2.0 + index)
        )
    kinds = {f.kind for f in ledger.audit(video_id="v1").findings}
    assert VarietyFindingKind.REPEATED_ENTRANCE in kinds
    assert VarietyFindingKind.REPEATED_EXIT in kinds


def test_variety_audit_flags_excessive_component_reuse() -> None:
    ledger = CreativeLedger(repeat_limit=1)
    for index in range(3):
        ledger.record(
            fingerprint_from_shot(f"s{index}", "v1", layout=f"l{index}", transition=f"t{index}",
                                  motion=f"m{index}", camera=f"c{index}",
                                  component="Chart", duration_s=2.0 + index)
        )
    audit = ledger.audit(video_id="v1", components={"Chart": 20})
    assert any(f.kind is VarietyFindingKind.EXCESSIVE_COMPONENT_REUSE for f in audit.findings)


def test_variety_audit_passes_on_a_varied_cut() -> None:
    ledger = CreativeLedger(repeat_limit=1)
    ledger.record(fingerprint_from_shot("s0", "v1", layout="split", transition="cut",
                                        motion="push", camera="static", accent="teal",
                                        duration_s=1.5))
    ledger.record(fingerprint_from_shot("s1", "v1", layout="full", transition="dissolve",
                                        motion="reveal", camera="orbit", accent="amber",
                                        duration_s=6.0))
    ledger.record(fingerprint_from_shot("s2", "v1", layout="grid", transition="wipe",
                                        motion="track", camera="dolly", accent="rose",
                                        duration_s=12.0))
    assert ledger.audit(video_id="v1").ok is True


def test_short_cut_is_not_audited_for_uniformity() -> None:
    ledger = CreativeLedger()
    ledger.record(fingerprint_from_shot("s0", "v1", layout="l", transition="t",
                                        motion="m", camera="c", duration_s=3.0))
    assert ledger.audit(video_id="v1").ok is True


# ── test_justified_repetition ────────────────────────────────────────────


def test_justified_repetition_is_preserved_not_flagged() -> None:
    """A7: an intentional motif flagged as an error is a false positive."""
    ledger = CreativeLedger(repeat_limit=2)
    for index in range(5):
        ledger.record(
            fingerprint_from_shot(f"s{index}", "v1", layout="split", transition="cut",
                                  motion="push", camera="static", duration_s=4.0)
        )
    assert ledger.audit(video_id="v1").ok is False
    ledger.justify("family", "TRANSITION:cut", "tutorial continuity requires a hard cut")
    ledger.justify("family", "LAYOUT:split", "brand system locks the split layout")
    ledger.justify("family", "CAMERA:static", "locked-off framing is the brand signature")
    ledger.justify("family", "DURATION:uniform", "deliberate metronomic rhythm")
    audit = ledger.audit(video_id="v1")
    assert audit.ok is True
    assert audit.justified_repetitions >= 4
    assert all(f.justified for f in audit.findings)


def test_empty_justification_is_refused() -> None:
    ledger = CreativeLedger()
    with pytest.raises(ValueError):
        ledger.justify("family", "TRANSITION:cut", "   ")


def test_repetition_in_a_different_video_is_still_flagged() -> None:
    ledger = CreativeLedger(repeat_limit=1)
    for video in ("v1", "v2"):
        for index in range(3):
            ledger.record(
                fingerprint_from_shot(f"{video}_s{index}", video, layout="split",
                                      transition="cut", motion="push", camera="static",
                                      duration_s=4.0)
            )
    assert ledger.audit(video_id="v1").ok is False
    assert ledger.audit(video_id="v2").ok is False


# ── Reference adoption + licence boundary ────────────────────────────────


def test_every_reference_has_an_audited_record() -> None:
    assert len(REFERENCES) == 9
    for record in REFERENCES:
        payload = record.to_dict()
        for field in (
            "repository", "revision", "license", "license_verified",
            "capabilities_reviewed", "adoption_mode", "adopted_contracts",
            "rejected_architecture", "code_import_allowed", "notes",
        ):
            assert field in payload, f"{record.repository}:{field}"
        assert record.revision
        assert record.license_verified is True


def test_licence_boundary_holds_and_imports_nothing() -> None:
    ok, violations = assert_license_boundary()
    assert ok is True, violations
    assert all(record.code_import_allowed is False for record in REFERENCES)


def test_seecut_is_forbidden_and_guizang_is_reference_only() -> None:
    assert record_for("YeJe-cpu/SeeCut").adoption_mode is AdoptionMode.FORBIDDEN_IMPORT
    assert "PolyForm" in record_for("YeJe-cpu/SeeCut").license
    guizang = record_for("op7418/guizang-product-video-skill")
    assert guizang.adoption_mode is AdoptionMode.REFERENCE_ONLY
    assert "AGPL" in guizang.license


def test_audit_summary_counts_modes() -> None:
    summary = audit_summary()
    assert summary["audit_ok"] is True
    assert summary["reference_count"] == 9
    assert summary["code_imported_total"] == 0
    assert summary["forbidden_import_total"] == 1
    assert (
        summary["contract_adopt_total"] + summary["reference_only_total"]
        + summary["forbidden_import_total"]
        == 9
    )
