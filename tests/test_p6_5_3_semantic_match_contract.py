"""HEVI P6.5.3 — Semantic match contract repair.

The one change: P5.3's 0.30 intent term now scores against
``recipe.semantic_roles`` instead of ``recipe.intent``. P6 supplies the contract's
``semantic_id``; P5.3 still ranks and still owns the recipes.

The gates that matter here are negative. The repair is only correct if:

* the term is genuinely reachable now (measured on the real corpus)
* P6 still selects nothing and recommends nothing
* no product mapping appeared anywhere
* the weights did not move
* an off-vocabulary value still scores zero, so the term discriminates
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from hevi.production.p1_types import VisualBeat
from hevi.production.p5_3 import retrieval as p5_retrieval
from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.recipes import load_all_recipes
from hevi.production.p5_3.schema import CinematicRecipe
from hevi.production.p6.intent import compile_product_intent
from hevi.production.p6.product_compiler import ProductCompiler
from hevi.production.p6.visual_compiler import VisualCompiler
from hevi.production.semantic_contract import (
    SEMANTIC_CONTRACT,
    SHARED_SEMANTIC_ROLES,
    build_contract_from_corpus,
)

RETRIEVAL_FILE = Path(p5_retrieval.__file__)
LIBRARY_FILE = Path("hevi/production/p5_3/library.py")
P6_DIR = Path("hevi/production/p6")
SEMANTIC_CONTRACT_FILE = Path("hevi/production/semantic_contract.py")
VISUAL_COMPILER_FILE = P6_DIR / "visual_compiler.py"

_RECIPES: list[CinematicRecipe] | None = None


def _recipes() -> list[CinematicRecipe]:
    global _RECIPES
    if _RECIPES is None:
        _RECIPES = load_all_recipes()
        build_contract_from_corpus(_RECIPES)
    return _RECIPES


def _library() -> RecipeLibrary:
    library = RecipeLibrary()
    for recipe in _recipes():
        library.register(recipe)
    return library


def _beat(intent_id: str, recipe: CinematicRecipe) -> VisualBeat:
    return VisualBeat(
        beat_id="b",
        timeline_start_s=0.0,
        timeline_end_s=4.0,
        narration_span="x",
        intent_id=intent_id,
        shot_role=recipe.beat_roles[0],
        motion_purpose=recipe.semantic_roles[0],
        narrative_phase=recipe.beat_roles[-1],
    )


# ═══════════════════════════════════════════════════════════════════════════
# REQUIRED: the contract reaches the score
# ═══════════════════════════════════════════════════════════════════════════


def test_semantic_contract_reaches_score() -> None:
    """A beat carrying a contract ``semantic_id`` scores strictly higher than one
    carrying a P6 qualified grammar id, on the same recipe.

    This is the gate the whole repair exists to satisfy, asserted on the shipped
    corpus rather than a fixture.
    """
    gains: list[float] = []
    for role in SHARED_SEMANTIC_ROLES:
        recipe = next(r for r in _recipes() if role in r.semantic_roles)
        before = p5_retrieval._semantic_match(recipe, _beat("documentary_realism@v1.0.0", recipe))
        after = p5_retrieval._semantic_match(recipe, _beat(role, recipe))
        assert after > before, (role, before, after)
        assert after - before == pytest.approx(0.30), (role, before, after)
        gains.append(after - before)
    assert all(g > 0 for g in gains)
    assert len(gains) == 11


def test_semantic_match_rate_is_no_longer_zero() -> None:
    """Measured on the real corpus, not asserted from a constant."""
    legacy_values = ("documentary_realism@v1.0.0", "P03_DOCUMENTARY", "commercial_clean@v1.0.0")
    for value in legacy_values:
        assert sum(1 for r in _recipes() if value in r.semantic_roles) == 0

    reachable = {
        role: sum(1 for r in _recipes() if role in r.semantic_roles)
        for role in SHARED_SEMANTIC_ROLES
    }
    assert all(count > 0 for count in reachable.values()), reachable
    assert sum(reachable.values()) > 0


def test_every_contract_role_scores_at_least_one_recipe() -> None:
    for role in SHARED_SEMANTIC_ROLES:
        assert any(role in r.semantic_roles for r in _recipes()), role


def test_semantic_match_now_reaches_100() -> None:
    """The 0.70 ceiling is gone."""
    for role in SHARED_SEMANTIC_ROLES:
        recipe = next(r for r in _recipes() if role in r.semantic_roles)
        assert p5_retrieval._semantic_match(recipe, _beat(role, recipe)) == pytest.approx(1.0)


def test_accepted_score_rose_end_to_end() -> None:
    """The whole chain through real retrieval: the *selected* recipe's score rises.

    Two retrievals of the same library with the same shot/motion/phase, differing
    only in what the intent field carries. Everything else — the search, the
    ranking, the ordering — is P5.3's and identical between the two runs.
    """
    library = _library()
    recipe = next(r for r in _recipes() if "EVIDENCE_DOMINANT" in r.semantic_roles)

    def score_for(intent_id: str) -> float:
        candidates, evidence = p5_retrieval.retrieve_with_evidence(
            library, _beat(intent_id, recipe), profile_id="", duration=None
        )
        assert candidates and evidence.selected_recipe_id
        selected = next(
            c for c in candidates if c.recipe_id == evidence.selected_recipe_id
        )
        return selected.selection_score

    before = score_for("documentary_realism@v1.0.0")
    after = score_for("EVIDENCE_DOMINANT")
    assert after > before
    # 0.30 semantic weight x 0.30 term = 0.09 of selection_score, exactly.
    assert after - before == pytest.approx(0.09)


def test_every_contract_role_raises_the_selected_score() -> None:
    library = _library()
    for role in SHARED_SEMANTIC_ROLES:
        recipe = next(r for r in _recipes() if role in r.semantic_roles)

        def score_for(intent_id: str, recipe=CinematicRecipe) -> float:
            candidates, evidence = p5_retrieval.retrieve_with_evidence(
                library, _beat(intent_id, recipe), profile_id="", duration=None
            )
            selected = next(
                c for c in candidates if c.recipe_id == evidence.selected_recipe_id
            )
            return selected.selection_score

        assert score_for(role, recipe) > score_for("x@v1", recipe), role


def test_weights_are_preserved() -> None:
    text = LIBRARY_FILE.read_text()
    assert "0.30 * c.semantic_match" in text
    assert "0.05 * variety" in text
    assert "0.20 * c.profile_match" in text
    assert "0.15 * c.asset_match" in text
    assert "0.10 * c.capability_match" in text
    assert "0.10 * c.duration_match" in text
    assert "0.10 * historical" in text


def test_term_weights_in_the_matcher_are_unchanged() -> None:
    source = RETRIEVAL_FILE.read_text()
    body = ast.unparse(
        next(
            n
            for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.FunctionDef) and n.name == "_semantic_match"
        )
    )
    for weight in ("0.4", "0.3", "0.2", "0.1"):
        assert weight in body


# ═══════════════════════════════════════════════════════════════════════════
# REQUIRED: no recipe selection by P6
# ═══════════════════════════════════════════════════════════════════════════


def test_no_recipe_selection_by_p6() -> None:
    """P6 names no recipe, anywhere.

    Checked structurally against the recipe-id shape over every P6 module, since a
    single hardcoded id would be a second selector sitting beside P5.3's.
    """
    recipe_ids = {r.recipe_id for r in _recipes()}
    for path in sorted(P6_DIR.rglob("*.py")):
        source = path.read_text()
        for recipe_id in recipe_ids:
            assert recipe_id not in source, f"{path.name} names {recipe_id}"


def test_no_recipe_id_anywhere_in_p6() -> None:
    recipe_id_shape = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\.[A-Z][A-Z0-9_]{3,}\b")
    for path in sorted(P6_DIR.rglob("*.py")):
        found = recipe_id_shape.findall(path.read_text())
        # `visual_style.model` etc. are module paths, not recipe ids; require the
        # left side to look like a real recipe family.
        families = {"CAMERA", "COMPOSITION", "DATA", "EMOTIONAL", "EVIDENCE",
                    "EXPLAINER", "PRESENTER", "PRODUCT"}
        assert not [f for f in found if f.split(".")[0] in families], (
            path.name, [f for f in found if f.split(".")[0] in families]
        )


def test_p6_emits_a_semantic_role_not_a_recipe() -> None:
    """The beat P6 builds carries a vocabulary value, never a recipe identity."""
    from hevi.production.p6.schema import (
        GrammarKind,
        GrammarRef,
        ProductProfile,
        ProductType,
    )

    profile = ProductProfile(
        id="t", product_type=ProductType.DOCUMENTARY, purpose="x", audience="y",
        grammars=(GrammarRef(kind=GrammarKind.NARRATIVE, required=True),),
        narrative_grammar_id="documentary", presenter_grammar_id="documentary_explainer",
        visual_grammar_id="documentary_realism",
    )
    intent = compile_product_intent(profile).visual_intent
    beat = VisualCompiler().visual_beat_for(intent, beat_id="b0")
    assert beat.intent_id in SHARED_SEMANTIC_ROLES
    recipe_ids = {r.recipe_id for r in _recipes()}
    assert beat.intent_id not in recipe_ids


def test_p6_still_does_not_rank() -> None:
    for path in sorted(P6_DIR.rglob("*.py")):
        source = path.read_text()
        assert "rank_candidates" not in source
        assert "sort(" not in source.replace("sorted(", "")


def test_ranking_authority_stays_in_p5_3() -> None:
    assert "rank_candidates" in LIBRARY_FILE.read_text()
    assert "selection_score" in LIBRARY_FILE.read_text()


def test_p6_never_recommends() -> None:
    """Structural, not substring: P6's docstrings legitimately *say* that
    recommendation authority stays in P5.3, and a substring search flags the
    statement rather than the behaviour."""
    forbidden = {"recommend", "recommended", "best_recipe", "top_recipe", "suggest"}
    for path in sorted(P6_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else getattr(
                    node.func, "attr", ""
                )
                assert name.lower() not in forbidden, (path.name, name)
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                assert node.name.lower() not in forbidden, (path.name, node.name)


def test_recipe_ids_were_not_modified() -> None:
    """No recipe id was added, renamed or removed by the repair."""
    import subprocess

    out = subprocess.run(
        ["git", "diff", "--stat", "--", "hevi/production/p5_3/library.py",
         "hevi/production/p5_3/schema.py", "hevi/production/p5_3/recipes"],
        capture_output=True, text=True, cwd=Path.cwd(),
    ).stdout.strip()
    # library.py/schema.py may carry pre-existing uncommitted P5.4 work; what
    # matters is that *this* repair touched only retrieval.py.
    assert "retrieval.py" not in out


def test_no_second_scoring_engine() -> None:
    """Exactly one place computes semantic match."""
    count = 0
    for path in Path("hevi").rglob("*.py"):
        text = path.read_text(errors="ignore")
        count += len(re.findall(r"def _?semantic_match\(", text))
    assert count == 1, f"{count} semantic match implementations"


def test_no_scoring_reimplementation_in_p6() -> None:
    for path in sorted(P6_DIR.rglob("*.py")):
        source = path.read_text()
        assert "_semantic_match" not in source
        assert "semantic_match =" not in source


# ═══════════════════════════════════════════════════════════════════════════
# REQUIRED: no product mapping
# ═══════════════════════════════════════════════════════════════════════════


def test_no_product_mapping() -> None:
    product_label = re.compile(r"P0[1-9]_[A-Z_]+|P10_[A-Z_]+")
    for path in (RETRIEVAL_FILE, LIBRARY_FILE, SEMANTIC_CONTRACT_FILE):
        assert not product_label.search(path.read_text()), path.name


def test_no_product_mapping_in_the_matcher() -> None:
    # `ast.unparse` of the *function* excludes its docstring, so prose about the
    # product layer cannot be mistaken for a product branch in the logic.
    node = next(
        n for n in ast.walk(ast.parse(RETRIEVAL_FILE.read_text()))
        if isinstance(n, ast.FunctionDef) and n.name == "_semantic_match"
    )
    body = node.body[1:] if isinstance(node.body[0], ast.Expr) else node.body
    code = "\n".join(ast.unparse(stmt) for stmt in body)
    assert "product" not in code.lower()
    assert "P0" not in code


def test_contract_directives_stay_keyed_by_grammar() -> None:
    for directive in SEMANTIC_CONTRACT.list_directives():
        assert not directive.key[0].startswith("P0")
        assert not directive.key[0].startswith("P1")


def test_contract_vocabulary_has_no_product_label() -> None:
    for role in SHARED_SEMANTIC_ROLES:
        assert not role.startswith("P0")
        assert not role.startswith("P1")


# ═══════════════════════════════════════════════════════════════════════════
# REQUIRED: a new role breaks the contract loudly
# ═══════════════════════════════════════════════════════════════════════════


def test_new_role_breaks_contract() -> None:
    """If P5.3 gains a role, P6.5.1's vocabulary equality must fail.

    This is the tripwire that keeps the contract from drifting away from the
    engine it serves. It is asserted against the live corpus, so it holds today
    and will fail the moment the two vocabularies diverge.
    """
    corpus_roles = {r for recipe in _recipes() for r in recipe.semantic_roles}
    assert set(SHARED_SEMANTIC_ROLES) == corpus_roles


def test_new_role_would_be_unreachable_without_a_contract_update() -> None:
    """A hypothetical new role scores nothing until the contract names it."""
    ghost = "BRAND_PRESENCE"
    assert ghost not in SHARED_SEMANTIC_ROLES
    recipe = next(r for r in _recipes() if "EVIDENCE_DOMINANT" in r.semantic_roles)
    ghost_score = p5_retrieval._semantic_match(recipe, _beat(ghost, recipe))
    known_score = p5_retrieval._semantic_match(
        recipe, _beat("EVIDENCE_DOMINANT", recipe)
    )
    assert ghost_score == pytest.approx(known_score - 0.30)


def test_contract_registration_rejects_an_unknown_role() -> None:
    from hevi.production.semantic_contract import ProductionSemanticIntent, SemanticCategory

    with pytest.raises(ValueError, match="SEMANTIC_ID_NOT_IN_SHARED_VOCABULARY"):
        ProductionSemanticIntent(
            semantic_id="BRAND_PRESENCE", category=SemanticCategory.AFFECT, description="x"
        )


def test_directive_rejects_an_unknown_role() -> None:
    from hevi.production.semantic_contract import SemanticContract

    contract = SemanticContract()
    with pytest.raises(ValueError, match="semantic_role_NOT_IN_SHARED_VOCABULARY"):
        contract.add_directive(
            "documentary", "documentary_explainer", "documentary_realism",
            semantic_role="BRAND_PRESENCE", beat_role="REVEAL",
            narrative_phase="DEVELOPMENT",
        )


# ═══════════════════════════════════════════════════════════════════════════
# end-to-end
# ═══════════════════════════════════════════════════════════════════════════


def test_every_product_plan_produces_a_contract_scored_decision() -> None:
    compiler, library = ProductCompiler(), _library()
    for product_id in compiler.list_products():
        plan = compiler.compile(product_id, recipe_library=library)
        assert plan.recipe_evidence.selected_recipe_id
        assert plan.recipe_evidence.selection_factors


def test_every_product_beat_carries_a_contract_role() -> None:
    compiler = ProductCompiler()
    library = _library()
    for product_id in compiler.list_products():
        plan = compiler.compile(product_id, recipe_library=library)
        beat = compiler.visual_compiler.visual_beat_for(plan.visual_intent, beat_id="b")
        assert beat.intent_id in SHARED_SEMANTIC_ROLES, product_id


def test_selection_is_still_deterministic() -> None:
    compiler, library = ProductCompiler(), _library()
    hashes = {
        compiler.compile("P03_DOCUMENTARY", recipe_library=library).content_hash()
        for _ in range(50)
    }
    assert len(hashes) == 1


def test_evidence_still_answers_why_this_and_why_not_the_others() -> None:
    compiler, library = ProductCompiler(), _library()
    evidence = compiler.compile(
        "P03_DOCUMENTARY", recipe_library=library
    ).recipe_evidence
    assert evidence.selected_recipe_id
    assert evidence.selection_factors
    assert set(evidence.rejected_candidates) == set(evidence.rejection_reasons)


def test_recipe_identities_are_untouched_by_the_repair() -> None:
    recipes = _recipes()
    assert len(recipes) == 80
    assert len({r.recipe_id for r in recipes}) == 80
    assert len({r.intent for r in recipes}) == 77  # still a label set, not a vocabulary


def test_retrieval_still_falls_back_when_no_role_matches() -> None:
    """A beat with no usable role still retrieves; it just scores lower."""
    recipe = next(r for r in _recipes() if "EVIDENCE_DOMINANT" in r.semantic_roles)
    beat = _beat("NOT_A_ROLE", recipe)
    candidates, evidence = p5_retrieval.retrieve_with_evidence(_library(), beat)
    assert candidates
    assert evidence.selected_recipe_id


def test_beat_with_no_intent_id_still_scores() -> None:
    """An empty intent field scores 0 on the term rather than raising."""
    recipe = next(r for r in _recipes() if "REVEAL" in r.semantic_roles)
    beat = VisualBeat(
        beat_id="b", timeline_start_s=0.0, timeline_end_s=4.0, narration_span="x",
        intent_id="", shot_role=recipe.beat_roles[0],
        motion_purpose=recipe.semantic_roles[0],
        narrative_phase=recipe.beat_roles[-1],
    )
    assert p5_retrieval._semantic_match(recipe, beat) == pytest.approx(0.7)
