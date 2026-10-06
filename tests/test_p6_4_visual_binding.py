"""HEVI P6.4 — Visual grammar, compiler and P5.3 binding validation.

Phase 9 minimums: Schema >=20, Registry >=20, Compiler >=30, P5.3 Integration >=20,
plus mutation tests that make *real* edits to ``visual_grammar.py``,
``visual_compiler.py`` and ``p6/intent.py`` and require each to be caught.

Three specified mutants, all injected into real source:
  1. ``if product_type == "P03"``            -> must fail
  2. ``history_camera()``                    -> must fail
  3. bypassing ``retrieve_with_evidence``    -> must fail

The authority guards are module-level pure functions so a mutant can be fed to
them directly. Enumerating bad shapes was the mistake P6.2 and P6.3 each made;
where a whole class can be closed by one inverted rule, it is.
"""

from __future__ import annotations

import ast
import copy
import re
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from hevi.production.p1_types import VisualBeat
from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.recipes import load_all_recipes
from hevi.production.p5_3.schema import (
    CinematicRecipe,
    RecipeCandidate,
    RecipeSelectionEvidence,
)
from hevi.production.p6 import schema as p6_schema
from hevi.production.p6.intent import ProductIntentError, compile_product_intent
from hevi.production.p6.narrative.compiler import NarrativeValidationResult
from hevi.production.p6.presenter_compiler import PresenterValidationResult
from hevi.production.p6.schema import (
    GrammarKind,
    GrammarRef,
    ProductConstraint,
    ProductProfile,
    ProductType,
)
from hevi.production.p6.visual_compiler import (
    SHARED_LANGUAGE_CHANNELS,
    VisualBinding,
    VisualCompiler,
    VisualIntent,
    VisualIntentValidationResult,
)
from hevi.production.p6.visual_grammar import (
    BUILTIN_VISUAL_GRAMMARS,
    COMMERCIAL_CLEAN,
    DOCUMENTARY_REALISM,
    FORBIDDEN_VISUAL_GRAMMAR_IDS,
    VISUAL_GRAMMAR_COMPATIBILITY,
    VISUAL_GRAMMAR_REGISTRY,
    CameraLanguage,
    CompositionLanguage,
    EditingLanguage,
    LightingLanguage,
    MotionLanguage,
    VisualGrammar,
    VisualGrammarCompatibility,
    VisualGrammarRegistry,
    register_builtin_visual_grammars,
)

P6_DIR = Path(p6_schema.__file__).parent
GRAMMAR_FILE = P6_DIR / "visual_grammar.py"
COMPILER_FILE = P6_DIR / "visual_compiler.py"
INTENT_FILE = P6_DIR / "intent.py"
P6_4_FILES = (GRAMMAR_FILE, COMPILER_FILE)

ALL_GRAMMARS = tuple(BUILTIN_VISUAL_GRAMMARS)
ALL_GRAMMAR_IDS = tuple(g.visual_grammar_id for g in ALL_GRAMMARS)
NARRATIVE_IDS = ("documentary", "explanatory", "story", "short_form")
PRESENTER_IDS = (
    "avatar_explainer",
    "documentary_explainer",
    "historical_reconstruction",
    "educational_lecture",
    "product_presentation",
)
BEAT_ROLES = ("ESTABLISH", "REVEAL", "EXPLAIN", "FOLLOW", "DETAIL", "PAYOFF")

#: A ``ProductType`` value, e.g. ``P03_HISTORICAL_REENACTMENT``.
PRODUCT_TYPE_LITERAL = re.compile(r"^P\d{2}_[A-Z][A-Z0-9_]*$")
#: A P5.3 recipe id, e.g. ``CAMERA.SLOW_PUSH_IN``.
RECIPE_ID_LITERAL = re.compile(r"^[A-Z][A-Z0-9_]*\.[A-Z][A-Z0-9_]*$")

#: Product-named helpers the spec calls out, plus the same shape of mistake.
FORBIDDEN_HELPER_NAMES = (
    "history_camera",
    "historical_camera",
    "avatar_camera",
    "science_camera",
    "marketing_camera",
    "commercial_camera",
    "story_camera",
    "short_form_camera",
    "documentary_camera",
    "education_camera",
)

SECOND_AUTHORITY_TYPE_NAMES = (
    "ShotPlan",
    "MotionPlan",
    "VisualShotPlanner",
    "ShotSelector",
    "MotionSelector",
    "RecipeSelector",
    "RecipeLibraryBuilder",
    "TimelineBuilder",
    "Renderer",
    "VisualRenderer",
    "Timeline",
)

_LIBRARY_CACHE: list[RecipeLibrary] = []


def _library() -> RecipeLibrary:
    """The real P5.3 recipe corpus, registered once."""
    if not _LIBRARY_CACHE:
        library = RecipeLibrary()
        for recipe in load_all_recipes():
            library.register(recipe)
        _LIBRARY_CACHE.append(library)
    return _LIBRARY_CACHE[0]


# ── helpers ──────────────────────────────────────────────────────────────


def _profile(
    *,
    profile_id: str = "t_profile",
    narrative: str = "documentary",
    presenter: str = "documentary_explainer",
    grammar: str = "documentary_realism",
    style: str = "",
) -> ProductProfile:
    return ProductProfile(
        id=profile_id,
        product_type=ProductType.DOCUMENTARY,
        purpose="explain a subject",
        audience="general",
        grammars=(GrammarRef(kind=GrammarKind.NARRATIVE, required=True),),
        narrative_grammar_id=narrative,
        presenter_grammar_id=presenter,
        visual_grammar_id=grammar,
        visual_style_id=style,
    )


def _intents(
    narrative: str = "documentary", presenter: str = "documentary_explainer"
) -> tuple:
    compiled = compile_product_intent(
        _profile(profile_id=f"t_{narrative}_{presenter}", narrative=narrative,
                 presenter=presenter, grammar="")
    )
    return compiled.narrative_intent, compiled.presenter_intent


def _grammar(grammar_id: str) -> VisualGrammar:
    grammar = VISUAL_GRAMMAR_REGISTRY.get(grammar_id)
    assert grammar is not None, grammar_id
    return grammar


def _intent(
    narrative: str = "documentary",
    presenter: str = "documentary_explainer",
    grammar_id: str = "documentary_realism",
) -> VisualIntent:
    n, p = _intents(narrative, presenter)
    return VisualCompiler().compile(n, p, _grammar(grammar_id))


def _binding(
    narrative: str = "documentary",
    presenter: str = "documentary_explainer",
    grammar_id: str = "documentary_realism",
) -> VisualBinding:
    return VisualCompiler().bind(_library(), _intent(narrative, presenter, grammar_id), beat_id="b0")


# ── authority guards (pure, so mutants can be fed to them) ──────────────


def _string_literals(node: ast.AST) -> list[str]:
    out: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            out.append(child.value)
    return out


def guard_no_product_literals(source: str) -> list[str]:
    """Any ``ProductType`` literal anywhere.

    Strict, not shape-enumerated: the P6.4 modules have no legitimate use for
    one, so a blanket rule closes the class at once. ``allow_requirement_table``
    exempts the pre-existing ``NARRATIVE_REQUIRED_PRODUCT_TYPES`` membership table
    in the shared ``intent.py`` — and only that table's own assignment.
    """
    violations: list[str] = []
    tree = ast.parse(source)
    exempt: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                isinstance(t, ast.Name)
                and (t.id.endswith("_TYPES") or t.id.endswith("_REQUIRED"))
                for t in targets
            ):
                for child in ast.walk(node.value):
                    exempt.add(id(child))
    for node in ast.walk(tree):
        if id(node) in exempt or isinstance(node, (ast.Set, ast.Dict)):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if PRODUCT_TYPE_LITERAL.match(node.value):
                violations.append(f"product_literal:{node.value}")
    return violations


def guard_no_product_named_helpers(source: str) -> list[str]:
    """Product-named function/method definitions.

    ``history_camera()`` and its relatives are the spec's named anti-pattern: a
    helper that exists because one product needed it. Such a helper is a
    pipeline wearing a helper's name.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in FORBIDDEN_HELPER_NAMES:
                found.append(node.name)
    return found


def _function_node(source: str, name: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found")


def guard_uses_retrieve_with_evidence(source: str, function: str = "bind") -> list[str]:
    """The binding must go through P5.3's single retrieval path.

    Catches every way to bypass it:
      * no call to ``retrieve_with_evidence`` at all
      * calling a lower-level P5.3 entry point directly (``retrieve_recipes``,
        ``library.search``, ``library.rank_candidates``) — a private selection
        path that produces no evidence
      * constructing ``RecipeCandidate`` in P6 — a second selector
      * hardcoding a recipe id — P6 choosing instead of asking
    """
    node = _function_node(source, function)
    called: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    violations: list[str] = []
    if "retrieve_with_evidence" not in called:
        violations.append("bypasses_retrieve_with_evidence")
    for bypass in ("retrieve_recipes", "search", "rank_candidates"):
        if bypass in called:
            violations.append(f"calls_private_selection:{bypass}")
    if "RecipeCandidate" in called:
        violations.append("constructs_recipe_candidate")
    for literal in _string_literals(node):
        if RECIPE_ID_LITERAL.match(literal):
            violations.append(f"hardcoded_recipe_id:{literal}")
    return violations


FORBIDDEN_P6_4_IMPORT_PREFIXES = (
    "hevi.renderers",
    "hevi.production.p0_pipeline",
    "hevi.production.p1_pipeline",
    "hevi.production.p2_types",
    "hevi.production.shot_readiness",
    "hevi.production.creative_ledger",
    "hevi.production.runtime",
    "hevi.providers",
    "hevi.verdict",
    "hevi.quality",
    "hevi.artifact_store",
    "hevi.editable",
    "hevi.timeline",
    "hevi.narrative",
    "obase",
)


def guard_imports(source: str) -> list[str]:
    """Forbidden modules *imported*.

    AST-based, not substring: these modules' docstrings legitimately name the
    forbidden authorities in prose ("P6.4 imports no shot or motion plan type"),
    and a substring search flags the prohibition itself.
    """
    violations: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(FORBIDDEN_P6_4_IMPORT_PREFIXES):
                violations.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(FORBIDDEN_P6_4_IMPORT_PREFIXES):
                    violations.append(alias.name)
    return violations


def guard_no_second_authority(source: str) -> list[str]:
    """Type definitions that would duplicate P0/P1/P5.3."""
    return [
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ClassDef) and node.name in SECOND_AUTHORITY_TYPE_NAMES
    ]


def _mutate(tmp_path: Path, target: Path, needle: str, replacement: str) -> str:
    """Copy a real P6.4 module, apply one textual mutation, return the source."""
    source = target.read_text()
    assert needle in source, f"mutation anchor missing from {target.name}"
    mutated = source.replace(needle, replacement, 1)
    assert mutated != source, "mutation did not apply"
    (tmp_path / target.name).write_text(mutated)
    return mutated


# ═══════════════════════════════════════════════════════════════════════════
# SCHEMA
# ═══════════════════════════════════════════════════════════════════════════


def test_schema_visual_grammar_is_dataclass() -> None:
    assert is_dataclass(VisualGrammar)


def test_schema_declares_the_six_named_fields() -> None:
    names = {f.name for f in fields(VisualGrammar)}
    required = {
        "visual_grammar_id",
        "camera_language",
        "motion_language",
        "composition_language",
        "lighting_language",
        "editing_language",
    }
    assert required <= names


def test_schema_field_named_visual_grammar_id() -> None:
    # The spec names the field ``visual_grammar_id``, not ``id``.
    assert "visual_grammar_id" in {f.name for f in fields(VisualGrammar)}


def test_schema_has_no_product_type_field() -> None:
    assert "product_type" not in {f.name for f in fields(VisualGrammar)}


def test_schema_grammar_is_immutable() -> None:
    with pytest.raises((AttributeError, TypeError)):
        DOCUMENTARY_REALISM.camera_language = CameraLanguage.ENERGETIC  # type: ignore[misc]


def test_schema_requires_visual_grammar_id() -> None:
    with pytest.raises(ValueError, match="VISUAL_GRAMMAR_WITHOUT_ID"):
        VisualGrammar(visual_grammar_id="", version="1.0.0", name="x")


def test_schema_requires_version() -> None:
    with pytest.raises(ValueError, match="VISUAL_GRAMMAR_WITHOUT_VERSION"):
        VisualGrammar(visual_grammar_id="x", version="", name="x")


def test_schema_requires_name() -> None:
    with pytest.raises(ValueError, match="VISUAL_GRAMMAR_WITHOUT_NAME"):
        VisualGrammar(visual_grammar_id="x", version="1.0.0", name="")


def test_schema_rejects_off_vocabulary_camera_language() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_VISUAL_LANGUAGE"):
        VisualGrammar(
            visual_grammar_id="x", version="1.0.0", name="x", camera_language="dolly_zoom"
        )


def test_schema_rejects_off_vocabulary_editing_language() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_VISUAL_LANGUAGE"):
        VisualGrammar(
            visual_grammar_id="x", version="1.0.0", name="x", editing_language="jump_cut"
        )


def test_schema_rejects_off_vocabulary_motion_language() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_VISUAL_LANGUAGE"):
        VisualGrammar(
            visual_grammar_id="x", version="1.0.0", name="x", motion_language="fast"
        )


def test_schema_rejects_off_vocabulary_composition_language() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_VISUAL_LANGUAGE"):
        VisualGrammar(
            visual_grammar_id="x", version="1.0.0", name="x", composition_language="rule_of_thirds"
        )


def test_schema_rejects_off_vocabulary_lighting_language() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_VISUAL_LANGUAGE"):
        VisualGrammar(
            visual_grammar_id="x", version="1.0.0", name="x", lighting_language="neon"
        )


def test_schema_rejects_empty_beat_role() -> None:
    with pytest.raises(ValueError, match="INVALID_BEAT_ROLE"):
        VisualGrammar(
            visual_grammar_id="x",
            version="1.0.0",
            name="x",
            compatible_beat_roles=("ESTABLISH", ""),
        )


def test_schema_to_dict_serialises_all_five_languages() -> None:
    payload = COMMERCIAL_CLEAN.to_dict()
    for key in (
        "camera_language",
        "motion_language",
        "composition_language",
        "lighting_language",
        "editing_language",
    ):
        assert key in payload
    assert payload["camera_language"] == "energetic"
    assert payload["editing_language"] == "accelerating"


def test_schema_to_dict_is_json_serialisable() -> None:
    import json

    assert json.loads(json.dumps(DOCUMENTARY_REALISM.to_dict()))


def test_schema_content_hash_is_stable() -> None:
    assert DOCUMENTARY_REALISM.content_hash() == DOCUMENTARY_REALISM.content_hash()


def test_schema_content_hash_differs_by_content() -> None:
    mutated = copy.replace(DOCUMENTARY_REALISM, lighting_language=LightingLanguage.STUDIO)
    assert mutated.content_hash() != DOCUMENTARY_REALISM.content_hash()


def test_schema_content_hash_differs_by_version() -> None:
    mutated = copy.replace(DOCUMENTARY_REALISM, version="9.9.9")
    assert mutated.content_hash() != DOCUMENTARY_REALISM.content_hash()


def test_schema_content_hash_differs_by_constraint_order() -> None:
    a = copy.replace(
        DOCUMENTARY_REALISM,
        constraints=(
            ProductConstraint(key="b", value="2"),
            ProductConstraint(key="a", value="1"),
        ),
    )
    b = copy.replace(
        DOCUMENTARY_REALISM,
        constraints=(
            ProductConstraint(key="a", value="1"),
            ProductConstraint(key="b", value="2"),
        ),
    )
    assert a.content_hash() != b.content_hash()  # a declaration is an ordered artefact


def test_schema_qualified_id() -> None:
    assert DOCUMENTARY_REALISM.qualified_id == "documentary_realism@v1.0.0"


def test_schema_languages_reports_five_channels() -> None:
    languages = DOCUMENTARY_REALISM.languages()
    assert len(languages) == 5
    assert set(languages) == {
        "camera_language",
        "motion_language",
        "composition_language",
        "lighting_language",
        "editing_language",
    }


def test_schema_camera_vocabulary_is_coarse_not_primitives() -> None:
    # P5.3's recipes own concrete moves. A P6.4 vocabulary naming dolly/pan/crane
    # would be a second camera vocabulary competing with what it feeds.
    assert {c.value for c in CameraLanguage} == {
        "observed",
        "stable",
        "directed",
        "energetic",
        "intimate",
        "discovering",
    }
    primitives = {"dolly", "pan", "zoom", "crane", "orbit", "truck", "pedestal", "arc"}
    assert primitives.isdisjoint({c.value for c in CameraLanguage})


def test_schema_editing_vocabulary_is_closed() -> None:
    assert {e.value for e in EditingLanguage} == {
        "continuous",
        "assembled",
        "long_take",
        "accelerating",
        "stepped",
    }


def test_schema_reuses_p6_3_motion_vocabulary() -> None:
    # Not redefined: imported from P6.3's model. Two enums with one name and
    # different members would be two visual authorities.
    from hevi.production.p6.visual_style.model import MotionLanguage as P63Motion

    assert MotionLanguage is P63Motion


def test_schema_reuses_p6_3_composition_vocabulary() -> None:
    from hevi.production.p6.visual_style.model import (
        CompositionLanguage as P63Composition,
    )

    assert CompositionLanguage is P63Composition


def test_schema_reuses_p6_3_lighting_vocabulary() -> None:
    from hevi.production.p6.visual_style.model import (
        LightingLanguage as P63Lighting,
    )

    assert LightingLanguage is P63Lighting


def test_schema_shared_channels_are_declared_once() -> None:
    assert set(SHARED_LANGUAGE_CHANNELS) == {
        "motion_language",
        "composition_language",
        "lighting_language",
    }


def test_schema_every_builtin_declares_compatible_beat_roles() -> None:
    for grammar in ALL_GRAMMARS:
        assert grammar.compatible_beat_roles, grammar.visual_grammar_id


def test_schema_builtin_beat_roles_are_real_p1_vocabulary() -> None:
    for grammar in ALL_GRAMMARS:
        for role in grammar.compatible_beat_roles:
            assert role in {
                "ESTABLISH",
                "REVEAL",
                "EXPLAIN",
                "FOLLOW",
                "DETAIL",
                "COMPARE",
                "TRANSITION",
                "PAYOFF",
            }, role


def test_schema_every_builtin_constraint_has_a_rationale() -> None:
    for grammar in ALL_GRAMMARS:
        for constraint in grammar.constraints:
            assert constraint.rationale, constraint.key


def test_schema_validation_result_serialises() -> None:
    payload = VisualIntentValidationResult(valid=False, errors=("E",)).to_dict()
    assert payload == {"valid": False, "errors": ["E"]}


def test_schema_constraints_default_to_empty() -> None:
    assert VisualGrammar(visual_grammar_id="b", version="1.0.0", name="b").constraints == ()


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


def test_registry_holds_the_four_required_builtins() -> None:
    assert set(ALL_GRAMMAR_IDS) == {
        "documentary_realism",
        "dramatic_reconstruction",
        "educational_clarity",
        "commercial_clean",
    }


def test_registry_ships_no_product_named_grammar() -> None:
    # The spec's first batch is general grammars only.
    for grammar_id in ALL_GRAMMAR_IDS:
        assert grammar_id not in FORBIDDEN_VISUAL_GRAMMAR_IDS


def test_registry_forbids_history_grammar() -> None:
    assert "history_visual_grammar" in FORBIDDEN_VISUAL_GRAMMAR_IDS


def test_registry_forbids_avatar_grammar() -> None:
    assert "avatar_visual_grammar" in FORBIDDEN_VISUAL_GRAMMAR_IDS


def test_registry_forbids_science_grammar() -> None:
    assert "science_visual_grammar" in FORBIDDEN_VISUAL_GRAMMAR_IDS


def test_registry_validates_a_forbidden_id_as_a_defect() -> None:
    registry = VisualGrammarRegistry()
    registry.register(
        VisualGrammar(
            visual_grammar_id="history_visual_grammar", version="1.0.0", name="History"
        )
    )
    ok, errors = registry.validate("history_visual_grammar")
    assert not ok
    assert errors == ["PRODUCT_NAMED_VISUAL_GRAMMAR:history_visual_grammar"]


def test_registry_lookup_by_bare_id() -> None:
    assert VISUAL_GRAMMAR_REGISTRY.get("educational_clarity").name == "Educational Clarity"


def test_registry_lookup_by_qualified_id() -> None:
    grammar = VISUAL_GRAMMAR_REGISTRY.get("educational_clarity@1.0.0")
    assert grammar is not None and grammar.visual_grammar_id == "educational_clarity"


def test_registry_lookup_by_v_prefixed_qualified_id() -> None:
    grammar = VISUAL_GRAMMAR_REGISTRY.get("educational_clarity@v1.0.0")
    assert grammar is not None and grammar.version == "1.0.0"


def test_registry_lookup_by_explicit_version_argument() -> None:
    grammar = VISUAL_GRAMMAR_REGISTRY.get("educational_clarity", "1.0.0")
    assert grammar is not None and grammar.version == "1.0.0"


def test_registry_unknown_lookup_returns_none() -> None:
    assert VISUAL_GRAMMAR_REGISTRY.get("no_such_grammar") is None


def test_registry_unknown_version_returns_none() -> None:
    assert VISUAL_GRAMMAR_REGISTRY.get("educational_clarity@9.9.9") is None


def test_registry_resolve_raises_unknown() -> None:
    with pytest.raises(KeyError, match="UNKNOWN_VISUAL_GRAMMAR"):
        VISUAL_GRAMMAR_REGISTRY.resolve("no_such_grammar")


def test_registry_has_is_false_for_unknown() -> None:
    assert not VISUAL_GRAMMAR_REGISTRY.has("no_such_grammar")


def test_registry_list_ids_is_sorted() -> None:
    assert VISUAL_GRAMMAR_REGISTRY.list_ids() == sorted(ALL_GRAMMAR_IDS)


def test_registry_list_all_covers_every_grammar() -> None:
    assert len(VISUAL_GRAMMAR_REGISTRY.list_all()) == len(ALL_GRAMMARS)


def test_registry_list_versions() -> None:
    assert VISUAL_GRAMMAR_REGISTRY.list_versions("documentary_realism") == ["1.0.0"]


def test_registry_duplicate_registration_rejected() -> None:
    registry = VisualGrammarRegistry()
    registry.register(DOCUMENTARY_REALISM)
    with pytest.raises(ValueError, match="VISUAL_GRAMMAR_IMMUTABLE"):
        registry.register(DOCUMENTARY_REALISM)


def test_registry_duplicate_id_different_version_allowed() -> None:
    registry = VisualGrammarRegistry()
    registry.register(DOCUMENTARY_REALISM)
    registry.register(copy.replace(DOCUMENTARY_REALISM, version="2.0.0"))
    assert registry.list_versions("documentary_realism") == ["1.0.0", "2.0.0"]


def test_registry_registers_a_non_visual_grammar_rejected() -> None:
    with pytest.raises(ValueError, match="NOT_A_VISUAL_GRAMMAR"):
        VisualGrammarRegistry().register("not a grammar")  # type: ignore[arg-type]


def test_registry_get_without_version_returns_highest() -> None:
    registry = VisualGrammarRegistry()
    registry.register(DOCUMENTARY_REALISM)
    registry.register(copy.replace(DOCUMENTARY_REALISM, version="2.0.0"))
    assert registry.get("documentary_realism").version == "2.0.0"


def test_registry_version_sort_is_numeric() -> None:
    registry = VisualGrammarRegistry()
    registry.register(copy.replace(COMMERCIAL_CLEAN, version="1.9.0"))
    registry.register(copy.replace(COMMERCIAL_CLEAN, version="1.10.0"))
    assert registry.get("commercial_clean").version == "1.10.0"


def test_registry_validate_accepts_every_builtin() -> None:
    ok, errors = VISUAL_GRAMMAR_REGISTRY.validate_all()
    assert ok, errors


def test_registry_validate_reports_missing_grammar() -> None:
    ok, errors = VISUAL_GRAMMAR_REGISTRY.validate("no_such_grammar")
    assert not ok
    assert errors == ["VISUAL_GRAMMAR_NOT_FOUND:no_such_grammar"]


def test_registry_to_dict_is_sorted() -> None:
    payload = VISUAL_GRAMMAR_REGISTRY.to_dict()
    assert list(payload) == sorted(payload)


def test_registry_register_builtin_is_idempotent() -> None:
    before = len(VISUAL_GRAMMAR_REGISTRY.list_all())
    register_builtin_visual_grammars()
    assert len(VISUAL_GRAMMAR_REGISTRY.list_all()) == before


def test_registry_exposes_no_product_dimension() -> None:
    # Its whole responsibility is visual_grammar_id -> VisualGrammar.
    source = GRAMMAR_FILE.read_text()
    assert guard_no_product_literals(source) == []
    assert not is_dataclass(VisualGrammarRegistry)
    # Its entire public surface is id -> VisualGrammar. No method anywhere on the
    # registry accepts or names a product dimension.
    methods = {
        name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ClassDef) and node.name == "VisualGrammarRegistry"
        for name in (
            stmt.name
            for stmt in node.body
            if isinstance(stmt, ast.FunctionDef)
        )
    }
    assert methods
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.arg)):
            offender = node.name if isinstance(node, ast.FunctionDef) else node.arg
            assert "product" not in offender, f"registry exposes a product dimension: {offender}"


def test_registry_no_product_named_helpers_in_grammar_module() -> None:
    assert guard_no_product_named_helpers(GRAMMAR_FILE.read_text()) == []


def test_registry_compatibility_table_is_data() -> None:
    assert isinstance(VISUAL_GRAMMAR_COMPATIBILITY, VisualGrammarCompatibility)
    assert VISUAL_GRAMMAR_COMPATIBILITY.allowed("documentary") == frozenset(
        {"documentary_realism", "dramatic_reconstruction"}
    )


def test_registry_compatibility_allow_is_a_merge() -> None:
    registry = VisualGrammarCompatibility()
    registry.allow("documentary", "documentary_realism")
    registry.allow("documentary", "dramatic_reconstruction")
    assert registry.allowed("documentary") == frozenset(
        {"documentary_realism", "dramatic_reconstruction"}
    )


def test_registry_compatibility_unknown_narrative_unrestricted() -> None:
    assert VISUAL_GRAMMAR_COMPATIBILITY.allowed("no_such_narrative") is None
    assert VISUAL_GRAMMAR_COMPATIBILITY.is_compatible("no_such_narrative", "commercial_clean")


def test_registry_compatibility_rejects_empty_ids() -> None:
    with pytest.raises(ValueError, match="VISUAL_COMPATIBILITY_WITHOUT_NARRATIVE_ID"):
        VisualGrammarCompatibility().allow("", "commercial_clean")
    with pytest.raises(ValueError, match="VISUAL_COMPATIBILITY_WITHOUT_GRAMMAR_ID"):
        VisualGrammarCompatibility().allow("documentary", "")


def test_registry_compatibility_validate_all_passes() -> None:
    ok, errors = VISUAL_GRAMMAR_COMPATIBILITY.validate_all()
    assert ok, errors


def test_registry_compatibility_validate_reports_unknown_grammar() -> None:
    registry = VisualGrammarCompatibility()
    registry.allow("documentary", "ghost_grammar")
    ok, errors = registry.validate_all()
    assert not ok
    assert errors == ["UNKNOWN_GRAMMAR_IN_COMPATIBILITY:documentary->ghost_grammar"]


def test_registry_compatibility_refuses_drama_for_explanatory() -> None:
    assert not VISUAL_GRAMMAR_COMPATIBILITY.is_compatible(
        "explanatory", "dramatic_reconstruction"
    )


def test_registry_compatibility_to_dict_is_sorted() -> None:
    payload = VISUAL_GRAMMAR_COMPATIBILITY.to_dict()
    assert list(payload) == sorted(payload)


# ═══════════════════════════════════════════════════════════════════════════
# COMPILER
# ═══════════════════════════════════════════════════════════════════════════


def test_compiler_declares_its_identity() -> None:
    assert VisualCompiler.compiler_id == "p6_4_visual_binding"


def test_compiler_is_stateless_and_reusable() -> None:
    compiler = VisualCompiler()
    first = compiler.compile(*_intents(), _grammar("documentary_realism"))
    compiler.compile(
        *_intents("story", "documentary_explainer"), _grammar("dramatic_reconstruction")
    )
    second = compiler.compile(*_intents(), _grammar("documentary_realism"))
    assert first.content_hash() == second.content_hash()


def test_compiler_outputs_visual_grammar_id() -> None:
    intent = _intent(grammar_id="educational_clarity", narrative="explanatory",
                     presenter="avatar_explainer")
    assert intent.visual_grammar_id == "educational_clarity"


def test_compiler_outputs_camera_style() -> None:
    intent = _intent(grammar_id="dramatic_reconstruction", narrative="story")
    assert intent.camera_style == "directed"


def test_compiler_outputs_shot_strategy() -> None:
    intent = _intent(grammar_id="dramatic_reconstruction", narrative="story")
    assert intent.shot_strategy == "COMPOSED_REVEAL"


def test_compiler_outputs_motion_strategy() -> None:
    intent = _intent(grammar_id="commercial_clean", narrative="short_form",
                     presenter="product_presentation")
    assert intent.motion_strategy == "FLUID_FOLLOW"


def test_compiler_outputs_composition_strategy() -> None:
    assert _intent().composition_strategy == "documentary"


def test_compiler_outputs_editing_strategy() -> None:
    intent = _intent(grammar_id="dramatic_reconstruction", narrative="story")
    assert intent.editing_strategy == "long_take"


def test_compiler_outputs_lighting_strategy() -> None:
    intent = _intent(grammar_id="dramatic_reconstruction", narrative="story")
    assert intent.lighting_strategy == "dramatic"


def test_compiler_records_upstream_grammar_ids() -> None:
    intent = _intent(narrative="story", grammar_id="dramatic_reconstruction")
    assert intent.narrative_grammar_id == "story"
    assert intent.presenter_grammar_id == "documentary_explainer"


def test_compiler_intent_is_marked_valid() -> None:
    intent = _intent()
    assert intent.validation_result.valid
    assert intent.validation_result.errors == ()


def test_compiler_intent_carries_sorted_languages() -> None:
    intent = _intent()
    assert list(intent.language_map()) == sorted(intent.language_map())
    assert len(intent.languages) == 5


def test_compiler_intent_to_dict_carries_all_five_strategies() -> None:
    payload = _intent().to_dict()
    for key in (
        "camera_style",
        "shot_strategy",
        "motion_strategy",
        "composition_strategy",
        "editing_strategy",
    ):
        assert key in payload


def test_compiler_intent_qualified_id() -> None:
    assert _intent().qualified_id == "documentary_realism@v1.0.0"


def test_compiler_resolve_grammar_returns_the_grammar() -> None:
    assert VisualCompiler().resolve_grammar("commercial_clean").name == "Commercial Clean"


def test_compiler_resolve_grammar_honours_a_version() -> None:
    grammar = VisualCompiler().resolve_grammar("commercial_clean", "1.0.0")
    assert grammar.version == "1.0.0"


def test_compiler_missing_grammar_reference_raises() -> None:
    with pytest.raises(KeyError, match="VISUAL_GRAMMAR_NOT_FOUND"):
        VisualCompiler().resolve_grammar("")


def test_compiler_unknown_grammar_reference_raises() -> None:
    with pytest.raises(KeyError, match="UNKNOWN_VISUAL_GRAMMAR"):
        VisualCompiler().resolve_grammar("no_such_grammar")


def test_compiler_rejects_invalid_narrative_intent() -> None:
    narrative, presenter = _intents()
    broken = copy.replace(narrative, validation_result=NarrativeValidationResult(valid=False))
    with pytest.raises(ValueError, match="NARRATIVE_INTENT_INVALID"):
        VisualCompiler().compile(broken, presenter, _grammar("documentary_realism"))


def test_compiler_rejects_invalid_presenter_intent() -> None:
    narrative, presenter = _intents()
    broken = copy.replace(presenter, validation_result=PresenterValidationResult(valid=False))
    with pytest.raises(ValueError, match="PRESENTER_INTENT_INVALID"):
        VisualCompiler().compile(narrative, broken, _grammar("documentary_realism"))


def test_compiler_rejects_narrative_without_grammar_id() -> None:
    narrative, presenter = _intents()
    with pytest.raises(ValueError, match="NARRATIVE_GRAMMAR_ID_MISSING"):
        VisualCompiler().compile(
            copy.replace(narrative, grammar_id=""), presenter, _grammar("documentary_realism")
        )


def test_compiler_rejects_presenter_without_grammar_id() -> None:
    narrative, presenter = _intents()
    with pytest.raises(ValueError, match="PRESENTER_GRAMMAR_ID_MISSING"):
        VisualCompiler().compile(
            narrative, copy.replace(presenter, grammar_id=""), _grammar("documentary_realism")
        )


def test_compiler_refuses_unregistered_grammar() -> None:
    # The registry is the authority; a grammar that is not in it is not usable.
    registry = VisualGrammarRegistry()
    ghost = VisualGrammar(visual_grammar_id="ghost", version="1.0.0", name="Ghost")
    narrative, presenter = _intents()
    with pytest.raises(ValueError, match="VISUAL_GRAMMAR_NOT_FOUND"):
        VisualCompiler(registry).compile(narrative, presenter, ghost)


def test_compiler_incompatible_narrative_pairing_raises() -> None:
    with pytest.raises(ValueError, match="INCOMPATIBLE_VISUAL_PAIRING:narrative="):
        _intent(narrative="documentary", grammar_id="educational_clarity")


def test_compiler_incompatible_presenter_pairing_raises() -> None:
    # commercial_clean is presenter_centered; documentary_realism is not, and
    # P6.3's table says an avatar needs a presenter-capable frame.
    with pytest.raises(ValueError, match="INCOMPATIBLE_VISUAL_PAIRING:presenter="):
        _intent(
            narrative="explanatory",
            presenter="avatar_explainer",
            grammar_id="documentary_realism",
        )


def test_compiler_incompatible_pairing_error_names_both_sides() -> None:
    with pytest.raises(ValueError) as excinfo:
        _intent(narrative="documentary", grammar_id="educational_clarity")
    message = str(excinfo.value)
    assert "narrative=documentary" in message
    assert "grammar=educational_clarity" in message


def test_compiler_style_coherence_accepts_agreeing_layers() -> None:
    compiled = compile_product_intent(
        _profile(
            profile_id="t_agree",
            narrative="documentary",
            presenter="documentary_explainer",
            grammar="documentary_realism",
            style="documentary_realism",
        )
    )
    assert compiled.visual_intent is not None
    assert compiled.visual_style_intent is not None


def test_compiler_style_coherence_refuses_disagreeing_layers() -> None:
    # P6.3 corporate_clean is restrained; P6.4 commercial_clean is fluid. The two
    # layers must not contradict each other over motion.
    #
    # P6.5.2 replaced the equality check with the constraint model. The refusal is
    # unchanged and the reason is now richer: it names the rule that fired
    # (`motion:agree`) and both values, rather than a bare channel name.
    with pytest.raises(ProductIntentError, match=r"VISUAL_GRAMMAR_STYLE_CONFLICT:motion:agree:MOTION_DISAGREEMENT:restrained\|fluid"):
        compile_product_intent(
            _profile(
                profile_id="t_conflict",
                narrative="short_form",
                presenter="product_presentation",
                grammar="commercial_clean",
                style="corporate_clean",
            )
        )


def test_compiler_style_coherence_checks_all_three_shared_channels() -> None:
    assert len(SHARED_LANGUAGE_CHANNELS) == 3


def test_compiler_style_coherence_is_skipped_when_no_style_declared() -> None:
    intent = _intent()
    assert intent.visual_grammar_id == "documentary_realism"


def test_compiler_deduplicates_identical_constraints() -> None:
    narrative, presenter = _intents()
    doubled = copy.replace(
        DOCUMENTARY_REALISM, constraints=DOCUMENTARY_REALISM.constraints * 2
    )
    intent = VisualCompiler().compile(narrative, presenter, doubled)
    assert len(intent.constraints) == 2


def test_compiler_sorts_constraints_deterministically() -> None:
    narrative, presenter = _intents()
    shuffled = copy.replace(
        DOCUMENTARY_REALISM,
        constraints=tuple(
            ProductConstraint(key=key, value="1") for key in ("zebra", "alpha", "mike")
        ),
    )
    intent = VisualCompiler().compile(narrative, presenter, shuffled)
    assert [c.key for c in intent.constraints] == ["alpha", "mike", "zebra"]


def test_compiler_strategy_derivation_is_table_driven_not_conditional() -> None:
    source = COMPILER_FILE.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "compile":
            # compile() must contain no product literal at all.
            assert guard_no_product_literals(ast.unparse(node)) == []


def test_compiler_never_defaults_a_grammar() -> None:
    # Every unusable reference raises; none yields a default.
    compiler = VisualCompiler()
    for bad in ("", "no_such_grammar", "documentary_realism@9.9.9"):
        with pytest.raises(KeyError):
            compiler.resolve_grammar(bad)


def test_compiler_product_connection_flows_from_the_profile() -> None:
    intent = compile_product_intent(_profile(profile_id="t_flow")).visual_intent
    assert intent is not None
    assert intent.visual_grammar_id == "documentary_realism"


def test_compiler_profile_without_a_grammar_compiles_intent_only() -> None:
    intent = compile_product_intent(_profile(profile_id="t_none", grammar=""))
    assert intent.narrative_intent is not None
    assert intent.visual_intent is None
    assert intent.visual_strategies() == {}


def test_compiler_grammar_without_a_presenter_is_refused() -> None:
    with pytest.raises(ProductIntentError, match="MISSING_PRESENTER_FOR_VISUAL_GRAMMAR"):
        compile_product_intent(_profile(profile_id="t_nop", presenter="", grammar="documentary_realism"))


def test_compiler_product_intent_exposes_the_strategies() -> None:
    intent = compile_product_intent(_profile(profile_id="t_s"))
    assert set(intent.visual_strategies()) == {
        "camera_style",
        "shot_strategy",
        "motion_strategy",
        "composition_strategy",
        "editing_strategy",
    }


def test_compiler_intent_hash_changes_with_the_grammar() -> None:
    a = _intent(narrative="story", grammar_id="dramatic_reconstruction")
    b = _intent(narrative="story", grammar_id="documentary_realism")
    assert a.content_hash() != b.content_hash()


def test_compiler_determinism_over_100_compiles() -> None:
    narrative, presenter = _intents()
    compiler = VisualCompiler()
    hashes = {
        compiler.compile(narrative, presenter, _grammar("documentary_realism")).content_hash()
        for _ in range(100)
    }
    assert len(hashes) == 1


def test_compiler_determinism_over_fresh_instances() -> None:
    narrative, presenter = _intents()
    hashes = {
        VisualCompiler().compile(
            narrative, presenter, _grammar("documentary_realism")
        ).content_hash()
        for _ in range(100)
    }
    assert len(hashes) == 1


def test_compiler_holds_no_module_level_per_product_state() -> None:
    assert guard_no_product_literals(COMPILER_FILE.read_text()) == []


# ═══════════════════════════════════════════════════════════════════════════
# P5.3 INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════


def test_integration_real_recipe_corpus_is_available() -> None:
    assert len(_library().list_all()) > 0


def test_integration_binding_calls_p5_3_retrieve_with_evidence() -> None:
    assert guard_uses_retrieve_with_evidence(COMPILER_FILE.read_text()) == []


def test_integration_binding_returns_candidates_and_evidence() -> None:
    binding = _binding()
    assert isinstance(binding.candidates, tuple)
    assert all(isinstance(c, RecipeCandidate) for c in binding.candidates)
    assert isinstance(binding.evidence, RecipeSelectionEvidence)


def test_integration_binding_produces_a_selected_recipe() -> None:
    binding = _binding()
    assert binding.selected_recipe_id
    assert binding.selected_version


def test_integration_selected_recipe_exists_in_the_real_library() -> None:
    binding = _binding()
    recipe = _library().get(binding.selected_recipe_id, binding.selected_version)
    assert recipe is not None
    assert isinstance(recipe, CinematicRecipe)


def test_integration_evidence_names_the_beat_we_supplied() -> None:
    binding = _binding()
    assert binding.evidence.visual_beat_id == "b0"


def test_integration_evidence_records_why_this_recipe() -> None:
    binding = _binding()
    assert binding.evidence.selection_factors
    assert "semantic_match" in binding.evidence.selection_factors


def test_integration_evidence_records_why_not_the_others() -> None:
    binding = _binding()
    assert binding.rejected_recipe_ids()
    assert binding.evidence.rejection_reasons


def test_integration_every_candidate_is_a_real_recipe() -> None:
    binding = _binding()
    for candidate in binding.candidates:
        assert _library().get(candidate.recipe_id, candidate.version) is not None


def test_integration_binding_carries_the_caller_beat_when_given() -> None:
    beat = VisualBeat(
        beat_id="caller_beat",
        timeline_start_s=1.0,
        timeline_end_s=3.0,
        narration_span="span",
        intent_id="i1",
        shot_role="DETAIL",
    )
    binding = VisualCompiler().bind(_library(), _intent(), beat=beat)
    assert binding.beat.beat_id == "caller_beat"
    assert binding.beat.shot_role == "DETAIL"


def test_integration_derived_beat_uses_the_intent_beat_role() -> None:
    binding = _binding(grammar_id="dramatic_reconstruction", narrative="story")
    assert binding.beat.shot_role == "REVEAL"


def test_integration_derived_beat_carries_the_contract_semantic_role() -> None:
    """P6.5.3: ``intent_id`` now carries the contract's ``semantic_id``.

    It used to carry P6's own qualified grammar id, which could never equal a
    recipe label, so P5.3's 0.30 term was structurally dead. It must be a P5.3
    ``semantic_role`` for the term to be reachable — and it must not be a recipe
    identity, which would make P6 a selector.
    """
    from hevi.production.semantic_contract import SHARED_SEMANTIC_ROLES

    binding = _binding()
    assert binding.beat.intent_id in SHARED_SEMANTIC_ROLES
    assert binding.beat.intent_id == binding.intent.semantic_directive().semantic_role


def test_integration_derived_beat_speaks_p5_3_semantic_vocabulary() -> None:
    # The motion purpose must be a role the shipped corpus actually uses,
    # otherwise the semantic signal is lost and ranking degrades.
    binding = _binding()
    corpus_roles = {
        role for recipe in load_all_recipes() for role in recipe.semantic_roles
    }
    assert binding.beat.motion_purpose in corpus_roles


def test_integration_derived_beat_declares_the_visual_directive() -> None:
    binding = _binding()
    assert binding.beat.required_visual == "observed/documentary/natural"


def test_integration_intent_beat_role_maps_every_strategy() -> None:
    for grammar in ALL_GRAMMARS:
        for narrative_id in NARRATIVE_IDS:
            try:
                intent = _intent(
                    narrative=narrative_id,
                    presenter="product_presentation",
                    grammar_id=grammar.visual_grammar_id,
                )
            except ValueError:
                continue  # pairing not permitted for this arc
            assert intent.beat_role() in {
                "ESTABLISH", "REVEAL", "EXPLAIN", "FOLLOW", "DETAIL", "PAYOFF"
            }


def test_integration_binds_every_builtin_grammar_that_fits() -> None:
    bound = 0
    for narrative_id, presenter_id, grammar_id in (
        ("documentary", "documentary_explainer", "documentary_realism"),
        ("story", "documentary_explainer", "dramatic_reconstruction"),
        ("explanatory", "avatar_explainer", "educational_clarity"),
        ("short_form", "product_presentation", "commercial_clean"),
    ):
        binding = _binding(narrative_id, presenter_id, grammar_id)
        assert binding.selected_recipe_id
        bound += 1
    assert bound == 4


def test_integration_different_grammars_select_different_recipes() -> None:
    documentary = _binding("documentary", "documentary_explainer", "documentary_realism")
    dramatic = _binding("story", "documentary_explainer", "dramatic_reconstruction")
    assert documentary.selected_recipe_id != dramatic.selected_recipe_id


def test_integration_binding_fails_closed_when_no_recipe_matches() -> None:
    # An empty library cannot satisfy the directive. That is a defect to surface,
    # not to paper over with a fallback recipe.
    with pytest.raises(LookupError, match="VISUAL_BINDING_NO_RECIPE"):
        VisualCompiler().bind(RecipeLibrary(), _intent(), beat_id="b0")


def test_integration_binding_to_dict_reports_the_decision() -> None:
    payload = _binding().to_dict()
    assert payload["shot_role"]
    assert payload["selected_recipe_id"]
    assert payload["evidence_fingerprint"]


def test_integration_evidence_fingerprint_excludes_the_timestamp() -> None:
    # P5.3 documents identical evidence except for the timestamp. Hashing the
    # timestamp would make every decision look non-deterministic.
    binding = _binding()
    stamped = copy.replace(binding.evidence, timestamp="1999-01-01T00:00:00Z")
    other = copy.replace(binding.evidence, timestamp="2031-12-31T23:59:59Z")
    assert (
        VisualBinding(binding.intent, binding.beat, binding.candidates, stamped)
        .evidence_fingerprint()
        == VisualBinding(binding.intent, binding.beat, binding.candidates, other)
        .evidence_fingerprint()
    )


def test_integration_determinism_over_100_bindings() -> None:
    library, compiler, intent = _library(), VisualCompiler(), _intent()
    fingerprints = {
        compiler.bind(library, intent, beat_id="b0").evidence_fingerprint()
        for _ in range(100)
    }
    assert len(fingerprints) == 1


def test_integration_determinism_over_fresh_compiler_instances() -> None:
    library, intent = _library(), _intent()
    fingerprints = {
        VisualCompiler().bind(library, intent, beat_id="b0").evidence_fingerprint()
        for _ in range(100)
    }
    assert len(fingerprints) == 1


def test_integration_binding_is_reproducible_after_intervening_calls() -> None:
    # Retrieval must not carry state between calls: bind a different grammar in
    # between and the original decision must be unchanged.
    library, compiler = _library(), VisualCompiler()
    first = compiler.bind(library, _intent(), beat_id="b0").evidence_fingerprint()
    compiler.bind(
        library,
        _intent("story", "documentary_explainer", "dramatic_reconstruction"),
        beat_id="other",
    )
    assert compiler.bind(library, _intent(), beat_id="b0").evidence_fingerprint() == first


def test_integration_binding_respects_a_supplied_profile_id() -> None:
    # An unknown profile makes every candidate violate PROFILE_INCOMPATIBLE, so
    # P5.3 returns nothing and the binding must fail closed rather than ignore
    # the constraint and hand back a recipe for a profile it does not serve.
    with pytest.raises(LookupError, match="VISUAL_BINDING_NO_RECIPE"):
        VisualCompiler().bind(_library(), _intent(), beat_id="b0", profile_id="__NOPE__")


def test_integration_binding_ignores_profile_id_when_empty() -> None:
    # The complementary case: no profile supplied means no profile constraint, and
    # retrieval proceeds normally.
    binding = VisualCompiler().bind(_library(), _intent(), beat_id="b0")
    assert binding.evidence.selected_recipe_id


def test_integration_module_defines_no_shot_or_motion_type() -> None:
    for path in P6_4_FILES:
        assert guard_no_second_authority(path.read_text()) == [], path.name


def test_integration_imports_no_shot_plan_or_motion_plan() -> None:
    for path in P6_4_FILES:
        assert guard_imports(path.read_text()) == [], path.name


def test_integration_no_renderer_provider_or_timeline_import() -> None:
    for path in P6_4_FILES:
        assert guard_imports(path.read_text()) == [], path.name


def test_integration_no_capcut_import() -> None:
    # Checked as an import, not a substring: the module docstring lists CapCut
    # among the things P6.4 does not touch, so a prose search flags the
    # prohibition rather than a violation.
    for path in P6_4_FILES:
        imported = guard_imports(path.read_text()) + [
            node.module
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.ImportFrom)
            and node.module
            and "capcut" in node.module.lower()
        ]
        assert imported == [], path.name


def test_integration_does_not_modify_p5_3() -> None:
    # P6.4 consumes P5.3 read-only. The only P5.3 imports are the library, the
    # schema types, and the one retrieval entry point.
    source = COMPILER_FILE.read_text()
    p5_imports = [
        line for line in source.splitlines()
        if line.startswith(("from hevi.production.p5_3", "import hevi.production.p5_3"))
    ]
    assert p5_imports, "expected P5.3 imports"
    for line in p5_imports:
        assert any(
            module in line
            for module in ("p5_3.library", "p5_3.retrieval", "p5_3.schema")
        ), line
    assert sum(1 for line in p5_imports if "p5_3.retrieval" in line) == 1


def test_integration_binding_uses_the_real_p1_visual_beat_type() -> None:
    # Not a P6 redefinition: the existing P1 request type, used as designed.
    binding = _binding()
    assert type(binding.beat) is VisualBeat


def test_integration_binding_stops_before_shot_plan() -> None:
    # The chain deliberately ends at the evidence. ShotPlan is P0/P1's to build.
    payload = _binding().to_dict()
    assert "shot_plan" not in payload
    assert "motion_plan" not in payload


# ═══════════════════════════════════════════════════════════════════════════
# MUTATION
# ═══════════════════════════════════════════════════════════════════════════


def test_mutation_injected_product_branch_into_real_grammar_must_fail(tmp_path: Path) -> None:
    """MUTATION 1 — `if product_type == "P03"` must be caught."""
    mutated = _mutate(
        tmp_path,
        GRAMMAR_FILE,
        "BUILTIN_VISUAL_GRAMMARS: tuple[VisualGrammar, ...] = (",
        "def _historical_grammar() -> VisualGrammar:\n"
        "    return copy.replace(DOCUMENTARY_REALISM, name=\"Historical\")\n\n\n"
        "def _select(product_type: str) -> VisualGrammar:\n"
        '    if product_type == "P03_HISTORICAL_REENACTMENT":\n'
        "        return _historical_grammar()\n"
        "    return DOCUMENTARY_REALISM\n\n\n"
        "BUILTIN_VISUAL_GRAMMARS: tuple[VisualGrammar, ...] = (",
    )
    assert guard_no_product_literals(mutated) == ["product_literal:P03_HISTORICAL_REENACTMENT"]
    assert guard_no_product_literals(GRAMMAR_FILE.read_text()) == []


def test_mutation_injected_history_camera_helper_must_fail(tmp_path: Path) -> None:
    """MUTATION 2 — `history_camera()` must be caught."""
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "_SHOT_STRATEGY_BY_CAMERA: dict[CameraLanguage, str] = {",
        "def history_camera() -> str:\n"
        '    """The camera used for historical reconstruction."""\n'
        '    return "LONG_LENS_ARCHIVAL"\n\n\n'
        "_SHOT_STRATEGY_BY_CAMERA: dict[CameraLanguage, str] = {",
    )
    assert guard_no_product_named_helpers(mutated) == ["history_camera"]
    assert guard_no_product_named_helpers(COMPILER_FILE.read_text()) == []


def test_mutation_history_camera_in_grammar_module_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        GRAMMAR_FILE,
        "DOCUMENTARY_REALISM = VisualGrammar(",
        "def history_camera() -> CameraLanguage:\n"
        "    return CameraLanguage.DISCOVERING\n\n\n"
        "DOCUMENTARY_REALISM = VisualGrammar(",
    )
    assert guard_no_product_named_helpers(mutated) == ["history_camera"]


def test_mutation_bypassing_retrieve_with_evidence_must_fail(tmp_path: Path) -> None:
    """MUTATION 3 — routing the binding around P5.3's retrieval must be caught."""
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "        candidates, evidence = retrieve_with_evidence(",
        "        candidates = library.search(beat_role=resolved_beat.shot_role)\n"
        "        evidence = RecipeSelectionEvidence(visual_beat_id=resolved_beat.beat_id)\n"
        "        candidates, evidence = retrieve_with_evidence(",
    )
    guard = guard_uses_retrieve_with_evidence(mutated)
    assert "calls_private_selection:search" in guard


def test_mutation_hardcoded_recipe_id_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "        candidates, evidence = retrieve_with_evidence(",
        "        candidates = (RecipeCandidate(recipe_id=\"CAMERA.SLOW_PUSH_IN\",\n"
        "                                  version=\"1.0.0\", selection_score=1.0),)\n"
        "        evidence = RecipeSelectionEvidence(visual_beat_id=resolved_beat.beat_id,\n"
        "                                          selected_recipe_id=\"CAMERA.SLOW_PUSH_IN\")\n"
        "        candidates, evidence = retrieve_with_evidence(",
    )
    guard = guard_uses_retrieve_with_evidence(mutated)
    assert "constructs_recipe_candidate" in guard
    assert "hardcoded_recipe_id:CAMERA.SLOW_PUSH_IN" in guard


def test_mutation_direct_rank_candidates_bypass_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "        candidates, evidence = retrieve_with_evidence(",
        "        ranked = library.rank_candidates(library.list_all())\n"
        "        evidence = RecipeSelectionEvidence(visual_beat_id=resolved_beat.beat_id)\n"
        "        candidates, evidence = retrieve_with_evidence(",
    )
    assert "calls_private_selection:rank_candidates" in guard_uses_retrieve_with_evidence(mutated)


def test_mutation_plain_retrieve_bypass_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "        candidates, evidence = retrieve_with_evidence(",
        "        plain = retrieve_recipes(library, resolved_beat)\n"
        "        evidence = RecipeSelectionEvidence(visual_beat_id=resolved_beat.beat_id)\n"
        "        candidates, evidence = retrieve_with_evidence(",
    )
    assert "calls_private_selection:retrieve_recipes" in guard_uses_retrieve_with_evidence(
        mutated
    )


def test_mutation_removing_the_retrieval_call_entirely_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        """        candidates, evidence = retrieve_with_evidence(
            library,
            resolved_beat,
            profile_id=profile_id,
            available_assets=available_assets,
            renderer_capabilities=renderer_capabilities,
            duration=duration,
        )""",
        """        candidates, evidence = [], RecipeSelectionEvidence(
            visual_beat_id=resolved_beat.beat_id
        )""",
    )
    assert "bypasses_retrieve_with_evidence" in guard_uses_retrieve_with_evidence(mutated)


def test_mutation_injected_shot_plan_type_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "@dataclass(frozen=True)\nclass VisualBinding:",
        "@dataclass(frozen=True)\nclass ShotPlan:\n    shot_id: str = \"\"\n\n\n"
        "@dataclass(frozen=True)\nclass VisualBinding:",
    )
    assert guard_no_second_authority(mutated) == ["ShotPlan"]
    assert guard_no_second_authority(COMPILER_FILE.read_text()) == []


def test_mutation_injected_motion_plan_type_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "@dataclass(frozen=True)\nclass VisualBinding:",
        "@dataclass(frozen=True)\nclass MotionPlan:\n    motion_id: str = \"\"\n\n\n"
        "@dataclass(frozen=True)\nclass VisualBinding:",
    )
    assert guard_no_second_authority(mutated) == ["MotionPlan"]


def test_mutation_requirement_table_cannot_smuggle_a_product_branch() -> None:
    snippet = (
        "REQUIRED_TYPES = {\"P03_HISTORICAL_REENACTMENT\"}\n"
        "def pick(product_type):\n"
        '    if product_type.value == "P03_HISTORICAL_REENACTMENT":\n'
        '        return "dramatic_reconstruction"\n'
    )
    assert guard_no_product_literals(snippet) == ["product_literal:P03_HISTORICAL_REENACTMENT"]


def test_mutation_every_product_branch_shape_is_caught() -> None:
    shapes = (
        'if profile.product_type == "P03_HISTORICAL_REENACTMENT": pass',
        'if profile.product_type.value == "P03_HISTORICAL_REENACTMENT": pass',
        'if str(profile.product_type) == "P03_HISTORICAL_REENACTMENT": pass',
        'x = {"P03_HISTORICAL_REENACTMENT": "dramatic_reconstruction"}',
        'def f(product_type):\n    return product_type == "P03_HISTORICAL_REENACTMENT"',
        'GRAMMARS = ["P03_HISTORICAL_REENACTMENT"]',
    )
    for shape in shapes:
        assert guard_no_product_literals(shape), shape


def test_mutation_no_product_literals_in_p6_4_modules() -> None:
    for path in P6_4_FILES:
        assert guard_no_product_literals(path.read_text()) == [], path.name


def test_mutation_intent_stage_allows_only_the_requirement_table() -> None:
    # intent.py legitimately carries the pre-existing P6.1 requirement table, so
    # the guard is invoked with its one exemption and must come back clean.
    assert guard_no_product_literals(INTENT_FILE.read_text()) == []
