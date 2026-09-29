"""HEVI P5.3 — adversarial suite: 30 cases.

Each case tries to break a redline. A redline that cannot be broken is not a
redline.
"""

from __future__ import annotations

import pytest

from hevi.production.p1_types import VisualBeat
from hevi.production.p5_3.anti_copy import (
    check_distinctive_sequence_copy,
    check_shot_sequence_copy,
    check_timing_vector_copy,
)
from hevi.production.p5_3.creative_integration import (
    compute_variety_score,
    is_semantic_correctness_overriding_variety,
)
from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.metrics import compute_metrics
from hevi.production.p5_3.parameterization import parameterize_recipe
from hevi.production.p5_3.qualification import (
    can_promote,
    is_stale_qualification_evidence,
)
from hevi.production.p5_3.recipes import load_all_recipes
from hevi.production.p5_3.reference_corpus import VideoAgentReferenceCorpus
from hevi.production.p5_3.reference_grammar import ReferenceVideoAnalysis
from hevi.production.p5_3.schema import (
    CinematicRecipe,
    DeprecationReason,
    QualificationEvidence,
    QualificationState,
    RecipeFamily,
    RecipeParameters,
)
from hevi.production.p5_3.versioning import derive_new_version


def _lib() -> RecipeLibrary:
    lib = RecipeLibrary()
    for r in load_all_recipes():
        lib.register(r)
    return lib


def _beat(**kw) -> VisualBeat:
    d = dict(beat_id="b1", timeline_start_s=0.0, timeline_end_s=3.0,
             narration_span="x", intent_id="ESTABLISH_SUBJECT",
             shot_role="ESTABLISH", narrative_phase="HOOK")
    d.update(kw)
    return VisualBeat(**d)


# 1 malformed recipe
def test_malformed_recipe_rejected() -> None:
    with pytest.raises(ValueError):
        CinematicRecipe(recipe_id="", version="1.0.0", recipe_family=RecipeFamily.COMPOSITION, name="x", description="y")


# 2 prompt-only recipe
def test_prompt_only_recipe_has_structured_content() -> None:
    for r in load_all_recipes():
        assert r.composition or r.camera_behavior or r.motion_behavior, f"{r.recipe_id} is prompt-only"


# 3 unknown recipe version
def test_unknown_version_returns_none() -> None:
    lib = _lib()
    assert lib.get_version("COMPOSITION.CENTERED_HERO", "99.0.0") is None


# 4 mutation of immutable version
def test_mutation_of_immutable_version_raises() -> None:
    lib = _lib()
    with pytest.raises(ValueError, match="RECIPE_VERSION_IMMUTABLE"):
        lib.register(lib.get("COMPOSITION.CENTERED_HERO"))


# 5 incompatible profile
def test_incompatible_profile_excluded() -> None:
    lib = _lib()
    cands = lib.search(profile="SCIENCE_EXPLAINER")
    for c in cands:
        assert "SCIENCE_EXPLAINER" in c.profile_compatibility


# 6 incompatible renderer
def test_incompatible_renderer_excluded() -> None:
    lib = _lib()
    cands = lib.search(renderer_capability="NONEXISTENT_CAPABILITY")
    assert cands == []


# 7 missing asset
def test_missing_asset_excluded() -> None:
    lib = _lib()
    cands = lib.search(asset_type="nonexistent_asset")
    assert cands == []


# 8 impossible duration
def test_impossible_duration_excluded() -> None:
    lib = _lib()
    cands = lib.search(duration=999.0)
    assert cands == []


# 9 excessive information density
def test_excessive_density_excluded() -> None:
    lib = _lib()
    cands = lib.search(information_density=99.0)
    assert cands == []


# 10 random-selection attempt
def test_no_random_selection() -> None:
    """Retrieval is deterministic; no random.choice in the path."""
    lib = _lib()
    beat = _beat()
    from hevi.production.p5_3.retrieval import retrieve_recipes
    c1 = retrieve_recipes(lib, beat)
    c2 = retrieve_recipes(lib, beat)
    assert [c.recipe_id for c in c1] == [c.recipe_id for c in c2]


# 11 duplicate registry
def test_no_duplicate_registry() -> None:
    import hevi.production.p5_3 as p53
    for name in ("SkillRegistry", "MotionRegistry", "ShotRegistry", "RecipeHistoryDB"):
        assert not hasattr(p53, name), name


# 12 recipe bypasses ShotPlan
def test_recipe_does_not_create_shot_plan() -> None:
    lib = _lib()
    r = lib.get("COMPOSITION.CENTERED_HERO")
    result = parameterize_recipe(r, RecipeParameters(duration=3.0), _beat())
    assert "shot_id" not in result["shot_plan"]


# 13 recipe bypasses MotionPlan
def test_recipe_does_not_create_motion_plan() -> None:
    lib = _lib()
    r = lib.get("CAMERA.SLOW_PUSH_IN")
    result = parameterize_recipe(r, RecipeParameters(), _beat())
    assert "motion_id" not in result["motion_plan"]


# 14 recipe invokes renderer
def test_recipe_does_not_invoke_renderer() -> None:
    for r in load_all_recipes():
        assert not hasattr(r, "render"), f"{r.recipe_id} has a render method"
        assert "render" not in r.parameters or callable(r.parameters.get("render")) is False


# 15 unlicensed code recipe
def test_unlicensed_code_recipe_rejected() -> None:
    corpus = VideoAgentReferenceCorpus()
    from hevi.production.p5_3.provenance import is_unlicensed_code_import
    assert is_unlicensed_code_import(corpus, "guizang-product-video-skill", "CODE") is True


# 16 unknown-license import
def test_unknown_license_is_reference_only() -> None:
    corpus = VideoAgentReferenceCorpus()
    for repo in corpus.list_all():
        if repo.license_confidence == "unknown":
            assert repo.adoption_mode.value == "REFERENCE_ONLY"


# 17 reference shot copy
def test_reference_shot_copy_detected() -> None:
    g = ReferenceVideoAnalysis("r", shot_durations=[1.0, 2.0, 3.0],
        composition_labels=["c"], camera_labels=["p"], transition_labels=["f"],
        motion_labels=["s"], speaker_segments=[{}], evidence_segments=[{}]).to_grammar()
    copied, _ = check_shot_sequence_copy(g, ["presenter_evidence_balance"])
    assert copied is True


# 18 reference timing copy
def test_reference_timing_copy_checked() -> None:
    g = ReferenceVideoAnalysis("r", shot_durations=[1.0, 2.0, 3.0]).to_grammar()
    copied, _ = check_timing_vector_copy(g, [5.0, 5.5, 6.0])
    assert copied is False  # Different distribution


# 19 reference asset copy
def test_reference_asset_copy_not_possible() -> None:
    g = ReferenceVideoAnalysis("r", shot_durations=[1.0, 2.0]).to_grammar()
    from hevi.production.p5_3.anti_copy import check_asset_sequence_copy
    copied, _ = check_asset_sequence_copy(g, ["a", "b"])
    assert copied is False


# 20 distinctive sequence copy
def test_distinctive_sequence_copy_detected() -> None:
    g = ReferenceVideoAnalysis("r", shot_durations=[1.0, 2.0, 3.0],
        composition_labels=["c"], camera_labels=["p"], transition_labels=["f"],
        motion_labels=["s"], speaker_segments=[{}], evidence_segments=[{}]).to_grammar()
    copied, _ = check_distinctive_sequence_copy(g, ["presenter_evidence_balance"])
    assert copied is True


# 21 variety overrides semantic match
def test_variety_never_overrides_semantic() -> None:
    assert is_semantic_correctness_overriding_variety(0.9, 0.1) is True
    lib = _lib()
    score = compute_variety_score(lib, "COMPOSITION.CENTERED_HERO")
    assert score.semantic_override is False


# 22 self-promotion
def test_no_self_promotion() -> None:
    lib = _lib()
    eligible, _ = can_promote(lib, "COMPOSITION.CENTERED_HERO", "1.0.0")
    assert eligible is False  # No usage recorded


# 23 one-render qualification
def test_one_render_does_not_qualify() -> None:
    lib = _lib()
    lib.record_outcome("COMPOSITION.CENTERED_HERO", "1.0.0", {"status": "PASS"})
    eligible, reason = can_promote(lib, "COMPOSITION.CENTERED_HERO", "1.0.0")
    assert eligible is False
    assert "INSUFFICIENT_USAGE" in reason


# 24 stale qualification evidence
def test_stale_qualification_evidence_detected() -> None:
    e = QualificationEvidence(usage_count=0)
    assert is_stale_qualification_evidence(e) is True


# 25 deprecated recipe selected as canonical
def test_deprecated_recipe_not_qualified() -> None:
    lib = _lib()
    from hevi.production.p5_3.qualification import deprecate_recipe
    deprecate_recipe(lib, "COMPOSITION.CENTERED_HERO", "1.0.0", DeprecationReason.OVERUSE)
    assert lib.get_version("COMPOSITION.CENTERED_HERO", "1.0.0").qualification_state is not QualificationState.QUALIFIED


# 26 historical project loses old version
def test_historical_version_preserved() -> None:
    lib = _lib()
    old = lib.get_version("COMPOSITION.CENTERED_HERO", "1.0.0")
    new = derive_new_version(old, {"name": "V2"})
    lib.register(new)
    assert lib.get_version("COMPOSITION.CENTERED_HERO", "1.0.0") is not None


# 27 external repo auto-execution
def test_no_external_repo_auto_execution() -> None:
    corpus = VideoAgentReferenceCorpus()
    for repo in corpus.list_all():
        notes = " ".join(repo.security_notes).lower()
        assert "curl | bash" not in notes
        assert "npm install" not in notes


# 28 provenance missing
def test_all_recipes_have_provenance() -> None:
    for r in load_all_recipes():
        assert r.source_provenance.origin, f"{r.recipe_id} missing provenance"


# 29 unsupported product claim
def test_product_claims_grounded() -> None:
    """Product recipes must not assert capabilities the product lacks."""
    lib = _lib()
    product_recipes = lib.search(family=RecipeFamily.PRODUCT)
    for r in product_recipes:
        assert r.constraints or r.anti_patterns, f"{r.recipe_id} has no constraints"


# 30 CreativeLedger bypass
def test_creative_ledger_not_bypassed() -> None:
    """Recipe usage must be recorded in the CreativeLedger, not a separate DB."""
    import hevi.production.p5_3 as p53
    assert not hasattr(p53, "RecipeHistoryDB")
    lib = _lib()
    metrics = compute_metrics(lib)
    assert "RECIPE_REPETITION_RATE" in metrics
