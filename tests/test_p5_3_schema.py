"""HEVI P5.3 — schema tests: typed structured contract, not prompt."""

from __future__ import annotations

import pytest

from hevi.production.p5_3.schema import (
    AdoptionMode,
    CinematicRecipe,
    CreativeVarietyScore,
    LicenseProvenance,
    QualificationEvidence,
    QualificationState,
    RecipeCandidate,
    RecipeFamily,
    RecipeParameters,
    RecipeSelectionEvidence,
    RecipeUsageRecord,
    ReferenceGrammar,
    ReferenceRepository,
    SourceProvenance,
)


def _recipe(**kwargs: object) -> CinematicRecipe:
    defaults: dict[str, object] = dict(
        recipe_id="COMPOSITION.CENTERED_HERO",
        version="1.0.0",
        recipe_family=RecipeFamily.COMPOSITION,
        name="Centered Hero",
        description="Subject centered, evidence on right",
    )
    defaults.update(kwargs)
    return CinematicRecipe(**defaults)  # type: ignore[arg-type]


def test_recipe_requires_id_version_name() -> None:
    with pytest.raises(ValueError, match="RECIPE_ID_REQUIRED"):
        CinematicRecipe(recipe_id="", version="1.0.0", recipe_family=RecipeFamily.COMPOSITION, name="x", description="y")
    with pytest.raises(ValueError, match="RECIPE_VERSION_REQUIRED"):
        CinematicRecipe(recipe_id="X", version="", recipe_family=RecipeFamily.COMPOSITION, name="x", description="y")
    with pytest.raises(ValueError, match="RECIPE_NAME_REQUIRED"):
        CinematicRecipe(recipe_id="X", version="1.0.0", recipe_family=RecipeFamily.COMPOSITION, name="", description="y")


def test_prompt_hint_is_never_canonical() -> None:
    """A prompt hint may exist but must never be the only content."""
    r = _recipe(prompt_hint="make this cinematic")
    assert r.prompt_hint == "make this cinematic"
    # The canonical representation is the structured fields, not the hint
    d = r.to_dict()
    assert d["name"] == "Centered Hero"
    assert d["description"] == "Subject centered, evidence on right"
    assert d["prompt_hint"] == "make this cinematic"


def test_prompt_hint_length_limit() -> None:
    with pytest.raises(ValueError, match="PROMPT_HINT_TOO_LONG"):
        _recipe(prompt_hint="x" * 501)


def test_content_hash_is_stable() -> None:
    r1 = _recipe()
    r2 = _recipe()
    assert r1.content_hash() == r2.content_hash()


def test_content_hash_changes_with_content() -> None:
    r1 = _recipe()
    r2 = _recipe(name="Different")
    assert r1.content_hash() != r2.content_hash()


def test_qualified_id_format() -> None:
    r = _recipe()
    assert r.qualified_id == "COMPOSITION.CENTERED_HERO@1.0.0"


def test_from_dict_round_trip() -> None:
    r = _recipe(intent="ESTABLISH", semantic_roles=["DIRECT_ADDRESS"])
    d = r.to_dict()
    r2 = CinematicRecipe.from_dict(d)
    assert r2.recipe_id == r.recipe_id
    assert r2.version == r.version
    assert r2.recipe_family is r.recipe_family
    assert r2.intent == r.intent
    assert r2.semantic_roles == r.semantic_roles


def test_all_families_exist() -> None:
    families = [f.value for f in RecipeFamily]
    assert len(families) == 8
    assert "COMPOSITION" in families
    assert "CAMERA" in families
    assert "EVIDENCE" in families
    assert "EXPLAINER" in families
    assert "EMOTIONAL" in families
    assert "PRESENTER" in families
    assert "PRODUCT" in families
    assert "DATA" in families


def test_all_qualification_states() -> None:
    states = [s.value for s in QualificationState]
    assert "EXPERIMENTAL" in states
    assert "QUALIFIED" in states
    assert "DEPRECATED" in states
    assert "REJECTED" in states


def test_all_adoption_modes() -> None:
    modes = [m.value for m in AdoptionMode]
    assert "REFERENCE_ONLY" in modes
    assert "CONTRACT_ADOPT" in modes
    assert "RECIPE_SOURCE" in modes
    assert "CODE_ADOPT_ALLOWED" in modes
    assert "REJECT" in modes


def test_recipe_parameters_round_trip() -> None:
    p = RecipeParameters(duration=3.5, position=(0.0, 0.78), scale=1.2)
    d = p.to_dict()
    p2 = RecipeParameters.from_dict(d)
    assert p2.duration == 3.5
    assert p2.position == (0.0, 0.78)
    assert p2.scale == 1.2


def test_recipe_candidate_to_dict() -> None:
    c = RecipeCandidate(recipe_id="X", version="1.0.0", semantic_match=0.9)
    d = c.to_dict()
    assert d["recipe_id"] == "X"
    assert d["semantic_match"] == 0.9
    assert d["selection_score"] == 0.0


def test_selection_evidence_to_dict() -> None:
    e = RecipeSelectionEvidence(
        visual_beat_id="b1",
        candidate_recipe_ids=["A", "B"],
        selected_recipe_id="A",
        selected_version="1.0.0",
        selection_factors={"semantic": 0.9},
        rejected_candidates=["B"],
        rejection_reasons={"B": "PROFILE_INCOMPATIBLE"},
    )
    d = e.to_dict()
    assert d["selected_recipe_id"] == "A"
    assert d["rejection_reasons"]["B"] == "PROFILE_INCOMPATIBLE"


def test_qualification_evidence_to_dict() -> None:
    e = QualificationEvidence(render_success=True, usage_count=5, failure_count=0)
    d = e.to_dict()
    assert d["render_success"] is True
    assert d["usage_count"] == 5


def test_reference_repository_to_dict() -> None:
    r = ReferenceRepository(repository="test", revision="abc", category="test")
    d = r.to_dict()
    assert d["repository"] == "test"
    assert d["adoption_mode"] == "REFERENCE_ONLY"


def test_reference_grammar_to_dict() -> None:
    g = ReferenceGrammar(reference_id="ref1", pacing_signature="mixed_pacing")
    d = g.to_dict()
    assert d["reference_id"] == "ref1"
    assert d["pacing_signature"] == "mixed_pacing"


def test_creative_variety_score_to_dict() -> None:
    v = CreativeVarietyScore(variety_score=0.8, semantic_override=False)
    d = v.to_dict()
    assert d["variety_score"] == 0.8
    assert d["semantic_override"] is False


def test_recipe_usage_record_to_dict() -> None:
    r = RecipeUsageRecord(
        recipe_id="X", recipe_version="1.0.0", profile="EMOTIONAL_BOOK_REVIEW",
        content_id="c1", beat_role="ESTABLISH",
    )
    d = r.to_dict()
    assert d["recipe_id"] == "X"
    assert d["profile"] == "EMOTIONAL_BOOK_REVIEW"


def test_source_provenance_defaults() -> None:
    p = SourceProvenance(origin="hand_crafted")
    assert p.origin == "hand_crafted"
    assert p.source_repository == ""


def test_license_provenance_defaults() -> None:
    p = LicenseProvenance()
    assert p.license == ""
    assert p.license_confidence == ""
    assert p.commercial_use_allowed is False
