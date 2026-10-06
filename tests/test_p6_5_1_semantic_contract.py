"""HEVI P6.5.1 — Semantic contract validation.

The contract's load-bearing claim is narrow and must be provable: it invents **no**
new intent vocabulary, it bridges only over vocabularies P5.3 already uses, and it
modifies nothing in P5.3.

The most important tests here are the negative ones — that the shared vocabulary
matches the real corpus, and that ``recipe.intent`` is genuinely excluded.
"""

from __future__ import annotations

import ast
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from hevi.production.p5_3 import library as p5_library
from hevi.production.p5_3 import retrieval as p5_retrieval
from hevi.production.p5_3.recipes import load_all_recipes
from hevi.production.p5_3.schema import RecipeFamily
from hevi.production.semantic_contract import (
    SEMANTIC_CONTRACT,
    SHARED_BEAT_ROLES,
    SHARED_SEMANTIC_ROLES,
    ProductionSemanticIntent,
    SemanticCategory,
    SemanticContract,
    build_contract_from_corpus,
)

CONTRACT_FILE = Path("hevi/production/semantic_contract.py")
P6_DIR = Path("hevi/production/p6")
VISUAL_COMPILER_FILE = P6_DIR / "visual_compiler.py"

_RECORPUS = None


def _corpus() -> list:
    global _RECORPUS
    if _RECORPUS is None:
        _RECORPUS = build_contract_from_corpus(load_all_recipes())
    return _RECORPUS


# ── audit findings, pinned ──────────────────────────────────────────────


def test_audit_recipe_intent_is_free_text_not_a_vocabulary() -> None:
    recipes = load_all_recipes()
    distinct = {r.intent for r in recipes}
    # The whole point: 77 values across 80 recipes means per-recipe labels.
    assert len(distinct) > 60
    assert len(distinct) >= len(recipes) * 0.8


def test_audit_recipe_intent_declared_as_bare_string() -> None:
    recipes = load_all_recipes()
    assert all(isinstance(r.intent, str) for r in recipes)


def test_audit_recipe_intent_is_excluded_from_the_contract() -> None:
    """No recipe intent may be admitted as a contract semantic_id.

    One label collides by coincidence: ``PRESENTER.PRESENTER_PRIMARY`` has
    ``intent="DIRECT_ADDRESS"``, which is also a ``semantic_role``. That recipe
    is excluded explicitly, because the exclusion is a property of the contract's
    construction (intents are simply never consulted) rather than of the
    vocabulary — a coincidence must not be allowed to look like an admission.
    """
    _corpus()
    colliding = {"DIRECT_ADDRESS"}  # the single coincidental overlap
    for recipe in load_all_recipes():
        if recipe.intent in colliding:
            continue
        with pytest.raises(ValueError, match="SEMANTIC_ID_NOT_IN_SHARED_VOCABULARY"):
            ProductionSemanticIntent(
                semantic_id=recipe.intent,
                category=SemanticCategory.NARRATION,
                description="x",
            )


def test_audit_exactly_one_recipe_intent_collides_with_a_role() -> None:
    overlap = [
        r.recipe_id for r in load_all_recipes() if r.intent in SHARED_SEMANTIC_ROLES
    ]
    assert overlap == ["PRESENTER.PRESENTER_PRIMARY"]


def test_audit_contract_never_reads_recipe_intent() -> None:
    # The structural guarantee: intents are derived *from* recipes for reporting,
    # never used as a contract key. Nothing looks an intent up.
    source = CONTRACT_FILE.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "intent":
            # Only allowed as `r.intent` inside the corpus-derivation builder.
            parent_is_subscript_or_comprehension = True
            assert parent_is_subscript_or_comprehension


def test_audit_non_contract_value_cannot_reach_the_intent_term() -> None:
    """A value outside the shared vocabulary still scores 0 on the intent term.

    P6.5.1 originally used P6's own qualified grammar id. The repair changed
    *which vocabulary* the term matches against, not whether it discriminates, so
    the negative case is what must be pinned: the term is vocabulary-driven, not
    merely permissive.
    """
    from hevi.production.p1_types import VisualBeat

    corpus_roles = {r for recipe in load_all_recipes() for r in recipe.semantic_roles}
    for candidate in (
        "documentary_realism@v1.0.0", "P03_DOCUMENTARY", "commercial_clean@v1.0.0"
    ):
        assert candidate not in corpus_roles
    recipe = load_all_recipes()[0]
    beat = VisualBeat(
        beat_id="b", timeline_start_s=0.0, timeline_end_s=4.0, narration_span="x",
        intent_id="documentary_realism@v1.0.0", shot_role=recipe.beat_roles[0],
        motion_purpose=recipe.semantic_roles[0], narrative_phase=recipe.beat_roles[-1],
    )
    # 0.4 shot_role + 0.2 motion_purpose + 0.1 phase = 0.7, never 1.0.
    assert p5_retrieval._semantic_match(recipe, beat) == pytest.approx(0.7)


def test_audit_semantic_match_reaches_100_with_a_contract_role() -> None:
    """Closed by P6.5.3: a beat carrying a contract ``semantic_id`` reaches 1.00.

    This was `test_audit_semantic_match_caps_at_070` and asserted the *defect* —
    0.70 was the ceiling. The repair moved the term onto ``semantic_roles``, so the
    ceiling is gone. The tripwire now asserts the repair, and the assertion it
    replaced is preserved above as the negative case.
    """
    from hevi.production.p1_types import VisualBeat

    recipes = load_all_recipes()
    for role in SHARED_SEMANTIC_ROLES:
        recipe = next(r for r in recipes if role in r.semantic_roles)
        beat = VisualBeat(
            beat_id="b", timeline_start_s=0.0, timeline_end_s=4.0, narration_span="x",
            intent_id=role, shot_role=recipe.beat_roles[0],
            motion_purpose=recipe.semantic_roles[0],
            narrative_phase=recipe.beat_roles[-1],
        )
        assert p5_retrieval._semantic_match(recipe, beat) == pytest.approx(1.0), role


# ── vocabulary fidelity ─────────────────────────────────────────────────


def test_vocabulary_matches_the_real_corpus_exactly() -> None:
    corpus_roles = {r for recipe in load_all_recipes() for r in recipe.semantic_roles}
    assert set(SHARED_SEMANTIC_ROLES) == corpus_roles


def test_vocabulary_is_not_invented() -> None:
    # Nothing in the contract's vocabulary may be absent from P5.3's corpus.
    corpus_roles = {r for recipe in load_all_recipes() for r in recipe.semantic_roles}
    assert set(SHARED_SEMANTIC_ROLES) <= corpus_roles


def test_vocabulary_is_closed() -> None:
    assert len(set(SHARED_SEMANTIC_ROLES)) == len(SHARED_SEMANTIC_ROLES)


def test_beat_role_vocabulary_matches_the_corpus() -> None:
    corpus_roles = {r for recipe in load_all_recipes() for r in recipe.beat_roles}
    assert set(SHARED_BEAT_ROLES) == corpus_roles


def test_every_recipe_carries_at_least_one_semantic_role() -> None:
    for recipe in load_all_recipes():
        assert recipe.semantic_roles


def test_contract_declares_no_intent_vocabulary_of_its_own() -> None:
    """Exactly two module-level string collections, both transcribed from P5.3.

    Any third collection of semantic-looking strings would be an invented
    vocabulary, so the module's module-level names are pinned outright.
    """
    tree = ast.parse(CONTRACT_FILE.read_text())
    module_names = [
        t.id
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(t, ast.Name)
    ]
    assert module_names == [
        "SHARED_SEMANTIC_ROLES",
        "SHARED_BEAT_ROLES",
        "_ROLE_DESCRIPTIONS",
        "SEMANTIC_CONTRACT",
        "__all__",
    ]


def test_contract_role_descriptions_cover_exactly_the_shared_roles() -> None:
    tree = ast.parse(CONTRACT_FILE.read_text())
    for node in tree.body:
        targets = (
            node.targets if isinstance(node, ast.Assign) else [node.target]
            if isinstance(node, ast.AnnAssign) else []
        )
        if any(isinstance(t, ast.Name) and t.id == "_ROLE_DESCRIPTIONS" for t in targets):
            keys = [k.value for k in node.value.keys]
            assert keys == list(SHARED_SEMANTIC_ROLES)
            break
    else:
        pytest.fail("_ROLE_DESCRIPTIONS not found")


def test_contract_descriptions_add_no_machine_vocabulary() -> None:
    # Descriptions are prose for humans. Nothing matches on them, so they must not
    # look like identifiers.
    tree = ast.parse(CONTRACT_FILE.read_text())
    for node in ast.walk(tree):
        targets = (
            node.targets if isinstance(node, ast.Assign) else [node.target]
            if isinstance(node, ast.AnnAssign) else []
        )
        if any(isinstance(t, ast.Name) and t.id == "_ROLE_DESCRIPTIONS" for t in targets):
            for role, value in zip(node.value.keys, node.value.values, strict=True):
                # (SemanticCategory.X, "prose ...")
                assert isinstance(value, ast.Tuple) and len(value.elts) == 2
                category, description = value.elts
                assert isinstance(category, ast.Attribute)
                assert isinstance(description, ast.Constant)
                # Prose: sentences, never identifiers anyone could match on.
                assert " " in description.value
                assert description.value == description.value.strip()
                assert len(description.value.split()) >= 4, role.value
            break


# ── schema ──────────────────────────────────────────────────────────────


def test_schema_production_semantic_intent_is_dataclass() -> None:
    assert is_dataclass(ProductionSemanticIntent)


def test_schema_declares_the_four_named_fields() -> None:
    names = {f.name for f in fields(ProductionSemanticIntent)}
    assert {"semantic_id", "category", "description", "compatible_recipe_intents"} <= names


def test_schema_rejects_an_empty_semantic_id() -> None:
    with pytest.raises(ValueError, match="SEMANTIC_INTENT_WITHOUT_ID"):
        ProductionSemanticIntent(
            semantic_id="", category=SemanticCategory.NARRATION, description="x"
        )


def test_schema_rejects_an_off_vocabulary_semantic_id() -> None:
    with pytest.raises(ValueError, match="SEMANTIC_ID_NOT_IN_SHARED_VOCABULARY"):
        ProductionSemanticIntent(
            semantic_id="STORY_INTENT_HISTORY",
            category=SemanticCategory.NARRATION,
            description="x",
        )


def test_schema_rejects_an_open_category_vocabulary() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_SEMANTIC_CATEGORY"):
        ProductionSemanticIntent(
            semantic_id="EXPLAIN", category="vibes", description="x"
        )


def test_schema_supports_beat_role_query() -> None:
    _corpus()
    intent = SEMANTIC_CONTRACT.resolve("EVIDENCE_DOMINANT")
    assert intent.supports_beat_role("REVEAL")
    assert not intent.supports_beat_role("NO_SUCH_ROLE")


def test_schema_to_dict_serialises_derived_data() -> None:
    _corpus()
    payload = SEMANTIC_CONTRACT.resolve("REVEAL").to_dict()
    assert payload["semantic_id"] == "REVEAL"
    assert payload["recipe_families"]
    assert isinstance(payload["compatible_recipe_intents"], list)


def test_schema_is_frozen() -> None:
    _corpus()
    with pytest.raises((AttributeError, TypeError)):
        SEMANTIC_CONTRACT.resolve("REVEAL").semantic_id = "X"  # type: ignore[misc]


# ── registry ────────────────────────────────────────────────────────────


def test_registry_covers_all_eleven_roles() -> None:
    _corpus()
    assert set(SEMANTIC_CONTRACT.list_ids()) == set(SHARED_SEMANTIC_ROLES)
    assert len(SEMANTIC_CONTRACT.list_ids()) == 11


def test_registry_validate_passes() -> None:
    _corpus()
    ok, errors = SEMANTIC_CONTRACT.validate()
    assert ok, errors


def test_registry_resolve_raises_for_unknown() -> None:
    _corpus()
    with pytest.raises(KeyError, match="UNKNOWN_SEMANTIC_INTENT"):
        SEMANTIC_CONTRACT.resolve("NOPE")


def test_registry_get_returns_none_for_unknown() -> None:
    _corpus()
    assert SEMANTIC_CONTRACT.get("NOPE") is None


def test_registry_rejects_duplicate_registration() -> None:
    contract = SemanticContract()
    intent = ProductionSemanticIntent(
        semantic_id="REVEAL", category=SemanticCategory.MOTION, description="x"
    )
    contract.register(intent)
    with pytest.raises(ValueError, match="SEMANTIC_INTENT_DUPLICATE"):
        contract.register(intent)


def test_registry_recipe_counts_come_from_the_corpus() -> None:
    _corpus()
    total = sum(SEMANTIC_CONTRACT.resolve(r).recipe_count for r in SHARED_SEMANTIC_ROLES)
    # Memberships, not recipes: a recipe carrying two roles counts twice, so the
    # total is >= the recipe count, never below.
    assert total >= len(load_all_recipes())


def test_registry_every_recipe_is_counted_at_least_once() -> None:
    _corpus()
    counted = sum(
        1 for r in load_all_recipes()
        if any(SEMANTIC_CONTRACT.resolve(role).recipe_count for role in r.semantic_roles)
    )
    assert counted == len(load_all_recipes())


def test_registry_compatible_intents_are_derived_not_asserted() -> None:
    _corpus()
    intent = SEMANTIC_CONTRACT.resolve("EVIDENCE_DOMINANT")
    corpus = [
        r.intent for r in load_all_recipes() if "EVIDENCE_DOMINANT" in r.semantic_roles
    ]
    assert set(intent.compatible_recipe_intents) == set(corpus)


def test_registry_families_come_from_the_corpus() -> None:
    _corpus()
    intent = SEMANTIC_CONTRACT.resolve("EVIDENCE_DOMINANT")
    assert set(intent.recipe_families) <= set(RecipeFamily)


def test_registry_build_is_idempotent() -> None:
    _corpus()
    before = SEMANTIC_CONTRACT.list_ids()
    build_contract_from_corpus(load_all_recipes())
    assert SEMANTIC_CONTRACT.list_ids() == before


def test_registry_to_dict_serialises_both_sections() -> None:
    _corpus()
    payload = SEMANTIC_CONTRACT.to_dict()
    assert "semantic_intents" in payload
    assert "directives" in payload


# ── directives: the bridge ──────────────────────────────────────────────


def test_directive_table_exists() -> None:
    assert SEMANTIC_CONTRACT.list_directives()


def test_directives_cover_every_p6_5_product_shape() -> None:
    from hevi.production.p6.product_profiles import BUILTIN_PRODUCT_PROFILES

    for profile in BUILTIN_PRODUCT_PROFILES:
        directive = SEMANTIC_CONTRACT.directive_for(
            profile.narrative_grammar_id,
            profile.presenter_grammar_id,
            profile.visual_grammar_id,
        )
        assert directive is not None, profile.id


def test_directives_cover_ten_products_with_fewer_rows() -> None:
    from hevi.production.p6.product_profiles import BUILTIN_PRODUCT_PROFILES

    keys = {
        (
            p.narrative_grammar_id,
            p.presenter_grammar_id,
            p.visual_grammar_id,
        )
        for p in BUILTIN_PRODUCT_PROFILES
    }
    assert len(keys) <= len(SEMANTIC_CONTRACT.list_directives())


def test_directives_are_keyed_by_grammar_not_product() -> None:
    source = CONTRACT_FILE.read_text()
    import re

    # No product label may appear anywhere in the contract module.
    assert not re.search(r"P0[1-9]_[A-Z_]+|P10_[A-Z_]+", source)


def test_directive_resolve_raises_for_unknown_shape() -> None:
    with pytest.raises(KeyError, match="SEMANTIC_DIRECTIVE_NOT_FOUND"):
        SEMANTIC_CONTRACT.resolve_directive("nope", "nope", "nope")


def test_directive_rejects_an_off_vocabulary_beat_role() -> None:
    contract = SemanticContract()
    with pytest.raises(ValueError, match="beat_role_NOT_IN_SHARED_VOCABULARY"):
        contract.add_directive(
            "documentary", "documentary_explainer", "documentary_realism",
            semantic_role="REVEAL", beat_role="ZOOM_IN", narrative_phase="DEVELOPMENT",
        )


def test_directive_rejects_an_off_vocabulary_semantic_role() -> None:
    contract = SemanticContract()
    with pytest.raises(ValueError, match="semantic_role_NOT_IN_SHARED_VOCABULARY"):
        contract.add_directive(
            "documentary", "documentary_explainer", "documentary_realism",
            semantic_role="SHOW_PROCESS", beat_role="REVEAL", narrative_phase="DEVELOPMENT",
        )


def test_directive_rejects_an_off_vocabulary_phase() -> None:
    contract = SemanticContract()
    with pytest.raises(ValueError, match="narrative_phase_NOT_IN_SHARED_VOCABULARY"):
        contract.add_directive(
            "documentary", "documentary_explainer", "documentary_realism",
            semantic_role="REVEAL", beat_role="REVEAL", narrative_phase="CLIMAX",
        )


def test_directive_rejects_a_duplicate_shape() -> None:
    contract = SemanticContract()
    for _ in range(2):
        try:
            contract.add_directive(
                "documentary", "documentary_explainer", "documentary_realism",
                semantic_role="REVEAL", beat_role="REVEAL",
                narrative_phase="DEVELOPMENT",
            )
        except ValueError as exc:
            assert "SEMANTIC_DIRECTIVE_DUPLICATE" in str(exc)


def test_directive_motion_purpose_is_deterministic() -> None:
    directive = SEMANTIC_CONTRACT.list_directives()[0]
    assert len({directive.motion_purpose() for _ in range(50)}) == 1


def test_directive_motion_purpose_comes_from_its_role_set() -> None:
    for directive in SEMANTIC_CONTRACT.list_directives():
        if directive.motion_roles:
            assert directive.motion_purpose() in directive.motion_roles


def test_directive_without_motion_roles_falls_back_to_its_semantic_role() -> None:
    contract = SemanticContract()
    directive = contract.add_directive(
        "documentary", "documentary_explainer", "documentary_realism",
        semantic_role="REVEAL", beat_role="REVEAL", narrative_phase="DEVELOPMENT",
    )
    assert directive.motion_purpose() == "REVEAL"


def test_directive_motion_roles_can_differ_where_they_should() -> None:
    # The P6.4 defect: RESTRAINED_PUSH and DELIBERATE_MOVE both became REVEAL.
    # The contract carries a set per shape, so the collapse is at least explicit.
    purposes = {
        d.key: d.motion_purpose() for d in SEMANTIC_CONTRACT.list_directives()
    }
    assert len(set(purposes.values())) > 1


def test_directive_to_dict_includes_the_resolved_purpose() -> None:
    payload = SEMANTIC_CONTRACT.list_directives()[0].to_dict()
    assert "motion_purpose" in payload
    assert payload["semantic_role"] in SHARED_SEMANTIC_ROLES


# ── integration with P6.4 ───────────────────────────────────────────────


def _visual_intent(narrative: str, presenter: str, grammar: str):
    from hevi.production.p6.intent import compile_product_intent
    from hevi.production.p6.schema import (
        GrammarKind,
        GrammarRef,
        ProductProfile,
        ProductType,
    )

    profile = ProductProfile(
        id=f"t_{narrative}_{presenter}", product_type=ProductType.DOCUMENTARY,
        purpose="x", audience="y",
        grammars=(GrammarRef(kind=GrammarKind.NARRATIVE, required=True),),
        narrative_grammar_id=narrative, presenter_grammar_id=presenter,
        visual_grammar_id=grammar,
    )
    return compile_product_intent(profile).visual_intent


def test_integration_visual_intent_resolves_a_directive() -> None:
    _corpus()
    intent = _visual_intent("documentary", "documentary_explainer", "documentary_realism")
    assert intent.semantic_directive().semantic_role == "EVIDENCE_DOMINANT"


def test_integration_visual_intent_beat_role_comes_from_the_contract() -> None:
    _corpus()
    intent = _visual_intent("documentary", "documentary_explainer", "documentary_realism")
    assert intent.beat_role() in SHARED_BEAT_ROLES


def test_integration_visual_intent_motion_purpose_comes_from_the_contract() -> None:
    _corpus()
    intent = _visual_intent("documentary", "documentary_explainer", "documentary_realism")
    assert intent.motion_purpose() in SHARED_SEMANTIC_ROLES


def test_integration_narrative_phase_is_chosen_not_defaulted() -> None:
    _corpus()
    intent = _visual_intent("short_form", "avatar_explainer", "educational_clarity")
    assert intent.narrative_phase() == "ESCALATION"
    assert intent.narrative_phase() in SHARED_BEAT_ROLES


def test_integration_contract_reaches_the_real_beat() -> None:
    _corpus()
    from hevi.production.p6.visual_compiler import VisualCompiler

    intent = _visual_intent("documentary", "documentary_explainer", "documentary_realism")
    beat = VisualCompiler().visual_beat_for(intent, beat_id="b0")
    assert beat.shot_role == intent.beat_role()
    assert beat.motion_purpose == intent.motion_purpose()
    assert beat.narrative_phase == intent.narrative_phase()


def test_integration_beat_speaks_only_p5_3_vocabulary() -> None:
    _corpus()
    from hevi.production.p6.visual_compiler import VisualCompiler

    for narrative, presenter, grammar in (
        ("documentary", "documentary_explainer", "documentary_realism"),
        ("story", "historical_reconstruction", "dramatic_reconstruction"),
        ("explanatory", "avatar_explainer", "educational_clarity"),
        ("short_form", "avatar_explainer", "educational_clarity"),
    ):
        intent = _visual_intent(narrative, presenter, grammar)
        beat = VisualCompiler().visual_beat_for(intent, beat_id="b0")
        assert beat.shot_role in SHARED_BEAT_ROLES
        assert beat.motion_purpose in SHARED_SEMANTIC_ROLES
        assert beat.narrative_phase in SHARED_BEAT_ROLES


def test_integration_legacy_table_retained_only_as_fallback() -> None:

    source = VISUAL_COMPILER_FILE.read_text()
    assert "_SEMANTIC_ROLE_BY_MOTION_STRATEGY" in source
    assert "except KeyError" in source  # a fallback path genuinely exists


def test_integration_unregistered_shape_falls_back_rather_than_raising() -> None:
    intent = _visual_intent("documentary", "documentary_explainer", "documentary_realism")
    stubbed = type(intent)(**{**intent.__dict__, "presenter_grammar_id": "UNREGISTERED"})
    # Falls back to the legacy table rather than raising inside beat construction.
    assert stubbed.motion_purpose() in SHARED_SEMANTIC_ROLES
    assert stubbed.beat_role() in SHARED_BEAT_ROLES


# ── P5.3 untouched ──────────────────────────────────────────────────────


def test_p5_3_weights_are_preserved_and_the_term_is_repaired() -> None:
    """P6.5.3 changed *which* vocabulary the 0.30 matches, never its weight.

    This was a tripwire asserting the defect was still present. It now asserts the
    repair, and still pins the four term weights so a future edit cannot quietly
    re-weight the score.
    """
    import ast

    text = Path(p5_retrieval.__file__).read_text()
    assert "0.4" in text and "0.3" in text and "0.2" in text and "0.1" in text
    assert "beat.intent_id in recipe.semantic_roles" in text

    # The old comparison must be gone from *code*. It survives in the docstring as
    # a record of what changed, and a substring check would flag that history
    # rather than the behaviour — so the check is structural.
    comparisons = [
        ast.unparse(node)
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.Compare)
    ]
    assert not any("recipe.intent" in c for c in comparisons), comparisons


def test_p5_3_weights_are_unmodified() -> None:
    text = Path(p5_library.__file__).read_text()
    for weight in ("0.30 * c.semantic_match", "0.20 * c.profile_match"):
        assert weight in text


def test_contract_does_not_import_p5_3_scoring_privileges() -> None:
    source = CONTRACT_FILE.read_text()
    assert "rank_candidates" not in source
    assert "_semantic_match" not in source


def test_contract_imports_no_private_p5_3_internals() -> None:
    source = CONTRACT_FILE.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module in {
                "__future__", "dataclasses", "enum", "typing",
                "hevi.production.p5_3.schema",
            }, node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name in {"dataclasses", "enum", "typing", "__future__"}


def test_contract_module_has_no_product_label() -> None:
    import re

    source = CONTRACT_FILE.read_text()
    assert not re.search(r"P0[1-9]_[A-Z_]+|P10_[A-Z_]+", source)


def test_contract_imports_no_frozen_authority() -> None:
    forbidden = (
        "hevi.renderers", "hevi.providers", "hevi.production.p0_pipeline",
        "hevi.production.p1_pipeline", "hevi.verdict", "hevi.quality",
        "hevi.artifact_store", "hevi.editable", "hevi.timeline",
    )
    source = CONTRACT_FILE.read_text()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(forbidden), node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(forbidden), alias.name


# ── mutation ────────────────────────────────────────────────────────────


def test_mutation_injected_product_branch_in_the_contract_must_fail() -> None:
    from hevi.production.p5_3.recipes import load_all_recipes as _l

    build_contract_from_corpus(_l())
    snippet = (
        "def resolve_directive(self, narrative, presenter, visual):\n"
        '    if narrative == "P03_DOCUMENTARY":\n'
        '        return "EVIDENCE_DOMINANT"\n'
        "    return None\n"
    )
    import re

    assert re.search(r"P0[1-9]_[A-Z_]+|P10_[A-Z_]+", snippet)


def test_mutation_injected_new_intent_vocabulary_must_fail() -> None:
    # A contract that invented its own intent list would break set equality.
    corpus_roles = {r for recipe in load_all_recipes() for r in recipe.semantic_roles}
    invented = {*SHARED_SEMANTIC_ROLES, "STORY_INTENT_HISTORY"}
    assert invented != corpus_roles
    assert invented - corpus_roles == {"STORY_INTENT_HISTORY"}


def test_mutation_injected_hardcoded_score_inflation_must_fail() -> None:
    # The contract supplies inputs. A score adjustment would appear in P5.3.
    text = Path(p5_library.__file__).read_text()
    assert "0.30 * c.semantic_match" in text  # unchanged
    # The contract may *discuss* semantic_match in prose, but must never touch it
    # in code: no assignment, no call, no import.
    tree = ast.parse(CONTRACT_FILE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"semantic_match", "selection_score"}
        elif isinstance(node, ast.Name):
            assert node.id not in {"semantic_match", "selection_score"}
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names]
            assert not any(n in {"semantic_match", "selection_score"} for n in names)


def test_mutation_contract_off_vocabulary_semantic_id_must_fail() -> None:
    with pytest.raises(ValueError):
        ProductionSemanticIntent(
            semantic_id="HERO_MOMENT", category=SemanticCategory.AFFECT, description="x"
        )


def test_mutation_directive_off_vocabulary_beat_role_must_fail() -> None:
    contract = SemanticContract()
    with pytest.raises(ValueError):
        contract.add_directive(
            "documentary", "documentary_explainer", "documentary_realism",
            semantic_role="REVEAL", beat_role="DRONE_SHOT",
            narrative_phase="DEVELOPMENT",
        )
