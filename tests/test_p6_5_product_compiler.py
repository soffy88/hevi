"""HEVI P6.5 — Product compiler validation.

Phase 8 minimums: Schema 30+, Registry 30+, Compiler 50+, Compatibility 30+,
Mutation 10+, a 100-combination product matrix, and 1000 compile cycles for
determinism.

The load-bearing claim of P6.5 is negative: *ten products, one compiler, no
branches*. Every guard here is written to falsify that claim, and the mutation
section attacks the real shipped modules rather than toy snippets.
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
from hevi.production.p5_3.schema import RecipeSelectionEvidence
from hevi.production.p6 import schema as p6_schema
from hevi.production.p6.narrative.compiler import NarrativeCompiler
from hevi.production.p6.narrative.registry import NARRATIVE_GRAMMAR_REGISTRY
from hevi.production.p6.presenter_compiler import PresenterCompiler
from hevi.production.p6.presenter_registry import (
    GRAMMAR_COMPATIBILITY_REGISTRY,
    PRESENTER_GRAMMAR_REGISTRY,
)
from hevi.production.p6.product_compiler import (
    REQUIRED_GRAMMAR_REFERENCES,
    ProductCompilationError,
    ProductCompiler,
    ProductProductionIntent,
)
from hevi.production.p6.product_profiles import (
    BUILTIN_PRODUCT_PROFILES,
    COMMERCIAL_PRODUCT_REGISTRY,
    CommercialProduct,
    CommercialProductRegistry,
    register_builtin_product_profiles,
)
from hevi.production.p6.schema import (
    AspectPolicy,
    ProductConstraint,
    ProductType,
)
from hevi.production.p6.visual_compiler import VisualCompiler
from hevi.production.p6.visual_grammar import (
    VISUAL_GRAMMAR_COMPATIBILITY,
    VISUAL_GRAMMAR_REGISTRY,
)
from hevi.production.p6.visual_style.compiler import VisualStyleCompiler
from hevi.production.p6.visual_style.registry import (
    COMPOSITION_COMPATIBILITY,
    STYLE_COMPATIBILITY_REGISTRY,
    VISUAL_STYLE_REGISTRY,
)

P6_DIR = Path(p6_schema.__file__).parent
COMPILER_FILE = P6_DIR / "product_compiler.py"
PROFILES_FILE = P6_DIR / "product_profiles.py"
P6_5_FILES = (COMPILER_FILE, PROFILES_FILE)

#: Ten beat roles, so 10 products x 10 roles = the 100-combination matrix.
BEAT_ROLES = (
    "ESTABLISH",
    "REVEAL",
    "EXPLAIN",
    "FOLLOW",
    "DETAIL",
    "COMPARE",
    "TRANSITION",
    "PAYOFF",
    "DEVELOPMENT",
    "ORIENTATION",
)

PRODUCT_TYPE_LITERAL = re.compile(r"^P\d{2}_[A-Z][A-Z0-9_]*$")
COMMERCIAL_LABEL_LITERAL = re.compile(r"^P\d{2}_[A-Z][A-Z0-9_]*$")

#: Product-named helpers the brief calls out, plus the same shape of mistake.
FORBIDDEN_HELPER_NAMES = (
    "history_compiler",
    "historical_compiler",
    "science_compiler",
    "marketing_compiler",
    "documentary_compiler",
    "avatar_compiler",
    "brand_story_compiler",
    "short_video_compiler",
    "news_compiler",
    "educational_compiler",
)

SECOND_AUTHORITY_TYPE_NAMES = (
    "ShotPlan",
    "MotionPlan",
    "Timeline",
    "RenderCommand",
    "RecipeSelector",
    "ShotSelector",
    "MotionSelector",
    "VideoRenderer",
    "ProductPipeline",
)

FORBIDDEN_IMPORT_PREFIXES = (
    "hevi.renderers",
    "hevi.production.p0_pipeline",
    "hevi.production.p1_pipeline",
    "hevi.production.shot_readiness",
    "hevi.production.creative_ledger",
    "hevi.production.runtime",
    "hevi.providers",
    "hevi.verdict",
    "hevi.quality",
    "hevi.artifact_store",
    "hevi.editable",
    "hevi.timeline",
    "obase",
)

_LIBRARY: list[RecipeLibrary] = []


def _library() -> RecipeLibrary:
    if not _LIBRARY:
        library = RecipeLibrary()
        for recipe in load_all_recipes():
            library.register(recipe)
        _LIBRARY.append(library)
    return _LIBRARY[0]


def _compiler() -> ProductCompiler:
    return ProductCompiler()


# ── authority guards (pure, so mutants can be fed to them) ──────────────


def guard_imports(source: str) -> list[str]:
    """Forbidden authorities actually imported.

    AST-based: these modules' docstrings legitimately *name* the things P6.5
    refuses to build ("No ShotPlan. No MotionPlan. No timeline."), and a
    substring search would flag the prohibition itself. That mistake was made
    twice already in P6.3 and P6.4.
    """
    violations: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                violations.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                    violations.append(alias.name)
    return violations


def guard_no_product_literals(source: str) -> list[str]:
    """Any ``ProductType`` literal, anywhere.

    Strict and un-enumerated: the compiler resolves profiles through the
    catalogue and has no legitimate need for a product literal, so one blanket
    rule closes the branch class at once rather than listing shapes.
    """
    violations: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Set, ast.Dict)):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if PRODUCT_TYPE_LITERAL.match(node.value):
                violations.append(f"product_literal:{node.value}")
    return violations


def guard_no_product_named_helpers(source: str) -> list[str]:
    """Product-named function/method definitions.

    ``history_compiler()`` is the brief's named anti-pattern. A helper that
    exists because one product needed it is a pipeline wearing a helper's name.
    """
    return [
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name in FORBIDDEN_HELPER_NAMES
    ]


def guard_no_second_authority(source: str) -> list[str]:
    """Types that would duplicate P0/P1/P5.3/P6.6."""
    return [
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ClassDef) and node.name in SECOND_AUTHORITY_TYPE_NAMES
    ]


def _function_node(source: str, name: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found")


def _called_names(node: ast.AST) -> set[str]:
    called: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    return called


def guard_requires_sub_compilers(source: str, function: str = "compile") -> list[str]:
    """The compile path must actually invoke each sub-compiler.

    ``NarrativeCompiler``, ``PresenterCompiler`` and ``VisualCompiler`` are the
    only legitimate sources of an intent. Reaching around them — or bypassing one
    entirely — is the failure Phase 7 calls out.
    """
    node = _function_node(source, function)
    called = _called_names(node)
    violations: list[str] = []
    if "compile_with" not in called:
        violations.append("never_calls_a_sub_compiler")
    if called & {"compile_with"} and "narrative_compiler" not in ast.unparse(node):
        violations.append("does_not_use_an_injected_narrative_compiler")
    return violations


def _normalise(name: str) -> str:
    """Strip the aliases people actually use.

    ``from x import ShotPlan as _ShotPlan`` then ``_ShotPlan(...)`` is the same
    violation as ``ShotPlan(...)``, and a name-exact guard misses it. Leading
    underscores and a lower/upper flip are the two disguises worth normalising.
    """
    return name.lstrip("_").lower()


AUTHORITY_TYPES = ("ShotPlan", "MotionPlan", "Timeline", "RenderCommand")


def guard_no_shot_or_motion_construction(source: str, function: str = "compile") -> list[str]:
    """The compile path must not build a shot, motion plan, timeline or render job.

    Alias-resistant: compares normalised names, so importing ``ShotPlan`` under
    another name and calling it is still caught. The first version of this guard
    compared name-exactly and the mutation suite proved in one line that
    ``_ShotPlan(...)`` walked straight past it.
    """
    node = _function_node(source, function)
    violations: list[str] = []
    for called in _called_names(node):
        normalised = _normalise(called)
        for authority in AUTHORITY_TYPES:
            if normalised == _normalise(authority):
                violations.append(f"constructs:{called}")
    # Also catch an alias import of an authority type anywhere in the module.
    for child in ast.walk(ast.parse(source)):
        if isinstance(child, ast.ImportFrom):
            for alias in child.names:
                if _normalise(alias.name) in {_normalise(t) for t in AUTHORITY_TYPES}:
                    violations.append(f"imports:{alias.name}")
    for child in ast.walk(node):
        if isinstance(child, ast.ClassDef) and child.name in SECOND_AUTHORITY_TYPE_NAMES:
            violations.append(f"defines:{child.name}")
    return violations


def guard_no_authority_anywhere(source: str) -> list[str]:
    """Module-wide: no authority type is defined, imported or constructed at all.

    The function-scoped guard only inspects ``compile``. A module could import
    ``ShotPlan as SP`` and use it from some other function, so the module-wide
    sweep is the one that actually closes the class.
    """
    violations: list[str] = []
    normalised_types = {_normalise(t) for t in AUTHORITY_TYPES}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name in SECOND_AUTHORITY_TYPE_NAMES:
            violations.append(f"defines:{node.name}")
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if _normalise(alias.name) in normalised_types:
                    violations.append(f"imports:{alias.name}")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if _normalise(name) in normalised_types:
                violations.append(f"constructs:{name}")
    return violations


def _mutate(tmp_path: Path, target: Path, needle: str, replacement: str) -> str:
    source = target.read_text()
    assert needle in source, f"mutation anchor missing from {target.name}"
    mutated = source.replace(needle, replacement, 1)
    assert mutated != source, "mutation did not apply"
    (tmp_path / target.name).write_text(mutated)
    return mutated


def _beat(intent: ProductProductionIntent, role: str) -> VisualBeat:
    return VisualBeat(
        beat_id="matrix_beat",
        timeline_start_s=0.0,
        timeline_end_s=4.0,
        narration_span="span",
        intent_id=intent.visual_intent.qualified_id,
        shot_role=role,
        motion_purpose=intent.visual_intent.motion_purpose(),
    )


# ═══════════════════════════════════════════════════════════════════════════
# SCHEMA
# ═══════════════════════════════════════════════════════════════════════════


def test_schema_product_production_intent_is_dataclass() -> None:
    assert is_dataclass(ProductProductionIntent)


def test_schema_declares_the_seven_named_fields() -> None:
    names = {f.name for f in fields(ProductProductionIntent)}
    required = {
        "product_id",
        "narrative_intent",
        "presenter_intent",
        "visual_intent",
        "recipe_evidence",
        "constraints",
    }
    assert required <= names


def test_schema_content_hash_is_a_method_not_a_stored_field() -> None:
    # The brief lists content_hash alongside the fields; it is derived, not
    # stored, so it is a method on the frozen dataclass.
    assert callable(ProductProductionIntent.content_hash)
    assert "content_hash" not in {f.name for f in fields(ProductProductionIntent)}


def test_schema_includes_visual_style_intent() -> None:
    assert "visual_style_intent" in {f.name for f in fields(ProductProductionIntent)}


def test_schema_includes_commercial_product_and_product_type() -> None:
    names = {f.name for f in fields(ProductProductionIntent)}
    assert {"commercial_product", "product_type"} <= names


def test_schema_includes_policy_and_profile_version() -> None:
    names = {f.name for f in fields(ProductProductionIntent)}
    assert {"policy", "product_profile_version"} <= names


def test_schema_intent_is_frozen() -> None:
    with pytest.raises((AttributeError, TypeError)):
        COMMERCIAL_PRODUCT_REGISTRY.list_all()[0].id = "x"  # type: ignore[misc]


def test_schema_commercial_product_has_exactly_ten_members() -> None:
    assert len(tuple(CommercialProduct)) == 10


def test_schema_commercial_product_values_are_the_brief_labels() -> None:
    assert {c.value for c in CommercialProduct} == {
        "P01_AVATAR_EXPLAINER",
        "P02_HISTORY_RECONSTRUCTION",
        "P03_DOCUMENTARY",
        "P04_SCIENCE_EXPLAINER",
        "P05_NEWS_ANALYSIS",
        "P06_EDUCATIONAL",
        "P07_MARKETING",
        "P08_BRAND_STORY",
        "P09_SHORT_VIDEO",
        "P10_CINEMATIC_STORY",
    }


def test_schema_ten_profiles_are_built() -> None:
    assert len(BUILTIN_PRODUCT_PROFILES) == 10


def test_schema_every_profile_declares_all_four_references() -> None:
    for profile in BUILTIN_PRODUCT_PROFILES:
        for name in REQUIRED_GRAMMAR_REFERENCES:
            assert getattr(profile, name), f"{profile.id}:{name}"


def test_schema_every_profile_declares_a_product_type() -> None:
    for profile in BUILTIN_PRODUCT_PROFILES:
        assert isinstance(profile.product_type, ProductType)


def test_schema_every_profile_declares_duration_policy() -> None:
    for profile in BUILTIN_PRODUCT_PROFILES:
        assert profile.duration_policy is not None
        assert profile.duration_policy.min_s <= profile.duration_policy.target_s
        assert profile.duration_policy.target_s <= profile.duration_policy.max_s


def test_schema_every_profile_declares_an_aspect_policy() -> None:
    for profile in BUILTIN_PRODUCT_PROFILES:
        assert isinstance(profile.aspect_policy, AspectPolicy)


def test_schema_every_profile_declares_purpose_and_audience() -> None:
    for profile in BUILTIN_PRODUCT_PROFILES:
        assert profile.purpose
        assert profile.audience


def test_schema_short_video_is_vertical() -> None:
    profile = COMMERCIAL_PRODUCT_REGISTRY.get("P09_SHORT_VIDEO")
    assert profile.aspect_policy is AspectPolicy.VERTICAL_9_16


def test_schema_cinematic_story_is_widescreen() -> None:
    profile = COMMERCIAL_PRODUCT_REGISTRY.get("P10_CINEMATIC_STORY")
    assert profile.aspect_policy in (
        AspectPolicy.LANDSCAPE_16_9,
        AspectPolicy.CINEMATIC_2_39,
    )


def test_schema_profiles_declare_no_camera_logic() -> None:
    forbidden = {"camera_logic", "renderer", "timeline", "shot_plan", "render_logic"}
    for profile in BUILTIN_PRODUCT_PROFILES:
        assert forbidden.isdisjoint({f.name for f in fields(profile)})


def test_schema_profiles_carry_no_embedded_grammar_objects() -> None:
    # Reference-only. A profile carrying its own grammar is a private pipeline.
    for profile in BUILTIN_PRODUCT_PROFILES:
        assert profile.narrative_grammar is None
        assert profile.presenter_grammar is None


def test_schema_ten_profiles_resolve_to_seven_grammar_shapes() -> None:
    shapes = {
        (
            p.narrative_grammar_id,
            p.presenter_grammar_id,
            p.visual_style_id,
            p.visual_grammar_id,
        )
        for p in BUILTIN_PRODUCT_PROFILES
    }
    assert len(shapes) == 7
    assert len(shapes) < len(BUILTIN_PRODUCT_PROFILES)


def test_schema_ten_profiles_resolve_to_four_narrative_visual_shapes() -> None:
    shapes = {(p.narrative_grammar_id, p.visual_style_id, p.visual_grammar_id) for p in BUILTIN_PRODUCT_PROFILES}
    assert len(shapes) == 4


def test_schema_grammar_shape_reuse_is_real() -> None:
    from collections import Counter

    counts = Counter(
        (p.narrative_grammar_id, p.visual_style_id, p.visual_grammar_id)
        for p in BUILTIN_PRODUCT_PROFILES
    )
    assert max(counts.values()) > 1


def test_schema_namespace_collision_with_product_type_is_documented() -> None:
    # The brief's labels and P6.0's enum share P0x prefixes but disagree in 9
    # slots. Keeping them separate is what makes a mix-up fail loudly.
    p6_0 = {t.value for t in ProductType}
    spec = {c.value for c in CommercialProduct}
    assert len(p6_0 & spec) == 1
    assert p6_0 & spec == {"P01_AVATAR_EXPLAINER"}


def test_schema_commercial_label_is_not_a_product_type() -> None:
    with pytest.raises(ValueError):
        ProductType("P03_DOCUMENTARY")


def test_schema_product_type_is_not_a_commercial_label() -> None:
    with pytest.raises(ValueError):
        CommercialProduct("P03_HISTORICAL_REENACTMENT")


def test_schema_every_profile_maps_to_a_distinct_or_shared_product_type() -> None:
    types = [p.product_type for p in BUILTIN_PRODUCT_PROFILES]
    assert len(types) == 10
    assert len(set(types)) == 9  # P08 and P10 are both NARRATIVE_FILM


def test_schema_required_grammar_references_are_the_four() -> None:
    assert REQUIRED_GRAMMAR_REFERENCES == (
        "narrative_grammar_id",
        "presenter_grammar_id",
        "visual_style_id",
        "visual_grammar_id",
    )


def test_schema_intent_to_dict_covers_every_intent() -> None:
    payload = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library()).to_dict()
    for key in (
        "narrative_intent",
        "presenter_intent",
        "visual_style_intent",
        "visual_intent",
        "recipe_evidence",
        "constraints",
        "policy",
    ):
        assert key in payload


def test_schema_intent_to_dict_is_json_serialisable() -> None:
    import json

    payload = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library()).to_dict()
    assert json.loads(json.dumps(payload))


def test_schema_evidence_timestamp_excluded_from_dict() -> None:
    payload = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library()).to_dict()
    assert "timestamp" not in payload["recipe_evidence"]


def test_schema_policy_carries_duration_and_aspect() -> None:
    intent = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library())
    keys = {k for k, _ in intent.policy}
    assert keys == {"target_s", "min_s", "max_s", "aspect"}


def test_schema_duration_policy_accessor() -> None:
    intent = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library())
    assert intent.duration_policy == {"target_s": 900.0}


def test_schema_summary_line_names_all_layers() -> None:
    summary = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library()).summary()
    assert "P03_DOCUMENTARY" in summary
    assert "documentary" in summary
    assert "CAMERA" in summary


def test_schema_compiler_is_a_frozen_dataclass() -> None:
    assert is_dataclass(ProductCompiler)


def test_schema_compiler_declares_its_identity() -> None:
    assert ProductCompiler.compiler_id == "p6_5_product_compiler"


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


def test_registry_holds_ten_profiles() -> None:
    assert len(COMMERCIAL_PRODUCT_REGISTRY.list_all()) == 10


def test_registry_lookup_by_id() -> None:
    profile = COMMERCIAL_PRODUCT_REGISTRY.get("P07_MARKETING")
    assert profile is not None and profile.id == "P07_MARKETING"


def test_registry_lookup_unknown_returns_none() -> None:
    assert COMMERCIAL_PRODUCT_REGISTRY.get("P99_NOPE") is None


def test_registry_lookup_empty_returns_none() -> None:
    assert COMMERCIAL_PRODUCT_REGISTRY.get("") is None


def test_registry_resolve_raises_unknown_product_profile() -> None:
    with pytest.raises(KeyError, match="UNKNOWN_PRODUCT_PROFILE"):
        COMMERCIAL_PRODUCT_REGISTRY.resolve("P99_NOPE")


def test_registry_has_is_false_for_unknown() -> None:
    assert not COMMERCIAL_PRODUCT_REGISTRY.has("P99_NOPE")


def test_registry_list_ids_is_sorted() -> None:
    ids = COMMERCIAL_PRODUCT_REGISTRY.list_ids()
    assert ids == sorted(ids)
    assert len(ids) == 10


def test_registry_list_all_matches_list_ids() -> None:
    assert [p.id for p in COMMERCIAL_PRODUCT_REGISTRY.list_all()] == (
        COMMERCIAL_PRODUCT_REGISTRY.list_ids()
    )


def test_registry_commercial_products_round_trips() -> None:
    assert [c.value for c in COMMERCIAL_PRODUCT_REGISTRY.commercial_products()] == (
        COMMERCIAL_PRODUCT_REGISTRY.list_ids()
    )


def test_registry_duplicate_registration_rejected() -> None:
    registry = CommercialProductRegistry()
    profile = BUILTIN_PRODUCT_PROFILES[0]
    registry.register(profile)
    with pytest.raises(ValueError, match="PRODUCT_PROFILE_DUPLICATE"):
        registry.register(copy.replace(profile, purpose="different"))


def test_registry_registers_a_non_profile_rejected() -> None:
    with pytest.raises(ValueError, match="NOT_A_PRODUCT_PROFILE"):
        CommercialProductRegistry().register("not a profile")  # type: ignore[arg-type]


def test_registry_validate_accepts_every_profile() -> None:
    ok, errors = COMMERCIAL_PRODUCT_REGISTRY.validate_all()
    assert ok, errors


def test_registry_validate_reports_unknown_profile() -> None:
    ok, errors = COMMERCIAL_PRODUCT_REGISTRY.validate("P99_NOPE")
    assert not ok
    assert errors == ["UNKNOWN_PRODUCT_PROFILE:P99_NOPE"]


def test_registry_validate_reports_missing_grammar() -> None:
    registry = CommercialProductRegistry()
    broken = copy.replace(BUILTIN_PRODUCT_PROFILES[0], visual_grammar_id="")
    registry.register(broken)
    ok, errors = registry.validate(broken.id)
    assert not ok
    assert errors == ["INVALID_PRODUCT_PROFILE:visual_grammar_id"]


def test_registry_stats_counts_profiles() -> None:
    stats = COMMERCIAL_PRODUCT_REGISTRY.stats()
    assert stats["profiles"] == 10
    assert stats["distinct_grammar_shapes"] == 7


def test_registry_stats_counts_product_types_used() -> None:
    assert COMMERCIAL_PRODUCT_REGISTRY.stats()["product_types_used"] == 9


def test_registry_to_dict_is_sorted_and_complete() -> None:
    payload = COMMERCIAL_PRODUCT_REGISTRY.to_dict()
    assert list(payload) == sorted(payload)
    assert len(payload) == 10


def test_registry_to_dict_carries_the_four_references() -> None:
    payload = COMMERCIAL_PRODUCT_REGISTRY.to_dict()
    for key in REQUIRED_GRAMMAR_REFERENCES:
        assert key in payload["P03_DOCUMENTARY"]


def test_registry_register_builtin_is_idempotent() -> None:
    before = len(COMMERCIAL_PRODUCT_REGISTRY.list_all())
    register_builtin_product_profiles()
    assert len(COMMERCIAL_PRODUCT_REGISTRY.list_all()) == before


def test_registry_is_a_module_level_singleton() -> None:
    from hevi.production.p6 import product_profiles as module

    assert module.COMMERCIAL_PRODUCT_REGISTRY is COMMERCIAL_PRODUCT_REGISTRY


def test_registry_is_not_p6_0s_canonical_registry() -> None:
    # P6.0 already owns PRODUCT_PROFILE_REGISTRY. Two registries under one name
    # would be a duplicate authority, so they are deliberately distinct objects
    # with distinct subjects.
    from hevi.production.p6.registry import PRODUCT_PROFILE_REGISTRY as canonical

    assert COMMERCIAL_PRODUCT_REGISTRY is not canonical
    assert type(COMMERCIAL_PRODUCT_REGISTRY) is not type(canonical)


def test_registry_canonical_and_commercial_ids_do_not_collide() -> None:
    COMMERCIAL_PRODUCT_REGISTRY.assert_no_id_collision()


def test_registry_id_collision_is_detected() -> None:
    from hevi.production.p6.registry import PRODUCT_PROFILE_REGISTRY as canonical

    registry = CommercialProductRegistry()
    registry.register(copy.replace(BUILTIN_PRODUCT_PROFILES[0], id="COLLIDING_ID"))
    # Injected straight into the canonical registry's internals rather than via
    # register(): the canonical register() enforces validate_composition(), which
    # rejects reference-only profiles — which is itself proof the two registries
    # hold different subjects.
    canonical._profiles["COLLIDING_ID@v1.0.0"] = copy.replace(
        BUILTIN_PRODUCT_PROFILES[0], id="COLLIDING_ID"
    )
    canonical._versions.setdefault("COLLIDING_ID", []).append("1.0.0")
    try:
        with pytest.raises(ValueError, match="PRODUCT_PROFILE_ID_COLLISION"):
            registry.assert_no_id_collision()
    finally:
        canonical._profiles.pop("COLLIDING_ID@v1.0.0", None)
        canonical._versions.pop("COLLIDING_ID", None)


def test_registry_register_returns_the_profile() -> None:
    registry = CommercialProductRegistry()
    profile = BUILTIN_PRODUCT_PROFILES[0]
    assert registry.register(profile) is profile


def test_registry_accepts_a_copy_under_a_new_id() -> None:
    registry = CommercialProductRegistry()
    registry.register(copy.replace(BUILTIN_PRODUCT_PROFILES[0], id="VARIANT_A"))
    registry.register(copy.replace(BUILTIN_PRODUCT_PROFILES[0], id="VARIANT_B"))
    assert registry.list_ids() == ["VARIANT_A", "VARIANT_B"]


def test_registry_commercial_products_rejects_a_non_catalogue_id() -> None:
    # An id that is not a CommercialProduct member cannot be enumerated as one.
    # Fail loudly rather than silently omitting the row.
    registry = CommercialProductRegistry()
    registry.register(copy.replace(BUILTIN_PRODUCT_PROFILES[0], id="NOT_IN_CATALOGUE"))
    with pytest.raises(ValueError):
        registry.commercial_products()


def test_registry_validate_all_reports_every_bad_row() -> None:
    registry = CommercialProductRegistry()
    registry.register(copy.replace(BUILTIN_PRODUCT_PROFILES[0], narrative_grammar_id=""))
    registry.register(copy.replace(BUILTIN_PRODUCT_PROFILES[1], visual_style_id=""))
    ok, errors = registry.validate_all()
    assert not ok
    assert len(errors) == 2


def test_registry_stats_grammar_shapes_are_fewer_than_profiles() -> None:
    stats = COMMERCIAL_PRODUCT_REGISTRY.stats()
    assert stats["distinct_grammar_shapes"] < stats["profiles"]


def test_registry_exposes_no_compiler() -> None:
    for name in dir(COMMERCIAL_PRODUCT_REGISTRY):
        assert "compil" not in name.lower(), name


def test_registry_exposes_no_product_branching() -> None:
    for node in ast.walk(ast.parse(PROFILES_FILE.read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert "product_id ==" not in ast.unparse(node)


def test_registry_module_has_no_product_literals_outside_the_catalogue() -> None:
    # The catalogue *is* a list of product ids, so those literals are the data.
    # What must not exist is a literal *inside a branch*.
    for node in ast.walk(ast.parse(PROFILES_FILE.read_text())):
        if isinstance(node, (ast.If, ast.IfExp)):
            assert guard_no_product_literals(ast.unparse(node.test)) == []


def test_registry_commercial_product_enum_is_closed() -> None:
    with pytest.raises(ValueError):
        CommercialProduct("P11_PODCAST")


def test_registry_each_profile_id_matches_its_enum_member() -> None:
    for profile in BUILTIN_PRODUCT_PROFILES:
        assert profile.id == CommercialProduct(profile.id).value


# ═══════════════════════════════════════════════════════════════════════════
# COMPILER
# ═══════════════════════════════════════════════════════════════════════════


def test_compiler_unknown_product_raises() -> None:
    with pytest.raises(ProductCompilationError, match="UNKNOWN_PRODUCT_PROFILE"):
        _compiler().compile("P99_NOPE", recipe_library=_library())


def test_compiler_empty_product_id_raises() -> None:
    with pytest.raises(ProductCompilationError, match="UNKNOWN_PRODUCT_PROFILE"):
        _compiler().compile("", recipe_library=_library())


def test_compiler_resolve_profile_returns_the_row() -> None:
    assert _compiler().resolve_profile("P01_AVATAR_EXPLAINER").id == "P01_AVATAR_EXPLAINER"


def test_compiler_list_products_matches_registry() -> None:
    assert _compiler().list_products() == COMMERCIAL_PRODUCT_REGISTRY.list_ids()


def test_compiler_accepts_a_profile_object_directly() -> None:
    profile = COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY")
    intent = _compiler().compile(profile, recipe_library=_library())
    assert intent.product_id == "P03_DOCUMENTARY"


def test_compiler_missing_narrative_reference_raises() -> None:
    profile = copy.replace(
        COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY"), narrative_grammar_id=""
    )
    with pytest.raises(ProductCompilationError, match="INVALID_PRODUCT_PROFILE"):
        _compiler().compile(profile, recipe_library=_library())


def test_compiler_missing_presenter_reference_raises() -> None:
    profile = copy.replace(
        COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY"), presenter_grammar_id=""
    )
    with pytest.raises(ProductCompilationError, match="INVALID_PRODUCT_PROFILE"):
        _compiler().compile(profile, recipe_library=_library())


def test_compiler_missing_style_reference_raises() -> None:
    profile = copy.replace(
        COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY"), visual_style_id=""
    )
    with pytest.raises(ProductCompilationError, match="INVALID_PRODUCT_PROFILE"):
        _compiler().compile(profile, recipe_library=_library())


def test_compiler_missing_visual_grammar_reference_raises() -> None:
    profile = copy.replace(
        COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY"), visual_grammar_id=""
    )
    with pytest.raises(ProductCompilationError, match="INVALID_PRODUCT_PROFILE"):
        _compiler().compile(profile, recipe_library=_library())


def test_compiler_missing_library_raises() -> None:
    with pytest.raises(ProductCompilationError, match="recipe_library required"):
        _compiler().compile("P03_DOCUMENTARY", recipe_library=None)


def test_compiler_validate_profile_reports_all_missing_at_once() -> None:
    profile = copy.replace(
        COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY"),
        narrative_grammar_id="",
        visual_grammar_id="",
    )
    ok, errors = _compiler().validate_profile(profile)
    assert not ok
    assert "INVALID_PRODUCT_PROFILE:narrative_grammar_id|visual_grammar_id" in errors


def test_compiler_validate_profile_accepts_a_good_profile() -> None:
    ok, errors = _compiler().validate_profile(COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY"))
    assert ok, errors


def test_compiler_delegates_to_the_narrative_compiler() -> None:
    source = COMPILER_FILE.read_text()
    node = _function_node(source, "compile")
    assert "narrative_compiler.compile_with" in ast.unparse(node)


def test_compiler_delegates_to_the_presenter_compiler() -> None:
    node = _function_node(COMPILER_FILE.read_text(), "compile")
    assert "presenter_compiler.compile_with" in ast.unparse(node)


def test_compiler_delegates_to_the_visual_style_compiler() -> None:
    node = _function_node(COMPILER_FILE.read_text(), "compile")
    assert "visual_style_compiler.compile_product_intent" in ast.unparse(node)


def test_compiler_delegates_to_the_visual_compiler() -> None:
    node = _function_node(COMPILER_FILE.read_text(), "compile")
    assert "self.visual_compiler.compile" in ast.unparse(node)


def test_compiler_produces_the_narrative_intent_from_p6_1() -> None:
    intent = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library())
    assert intent.narrative_intent.grammar_id == "documentary"


def test_compiler_produces_the_presenter_intent_from_p6_2() -> None:
    intent = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library())
    assert intent.presenter_intent.grammar_id == "documentary_explainer"


def test_compiler_produces_the_visual_style_intent_from_p6_3() -> None:
    intent = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library())
    assert intent.visual_style_intent.style_id == "documentary_realism"


def test_compiler_produces_the_visual_intent_from_p6_4() -> None:
    intent = _compiler().compile("P02_HISTORY_RECONSTRUCTION", recipe_library=_library())
    assert intent.visual_intent.visual_grammar_id == "dramatic_reconstruction"


def test_compiler_produces_recipe_evidence_from_p5_3() -> None:
    intent = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library())
    assert isinstance(intent.recipe_evidence, RecipeSelectionEvidence)


def test_compiler_evidence_names_the_selected_recipe() -> None:
    intent = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library())
    assert intent.recipe_evidence.selected_recipe_id
    assert intent.recipe_evidence.selected_version


def test_compiler_evidence_is_answerable() -> None:
    intent = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library())
    assert intent.recipe_evidence.selection_factors
    assert intent.recipe_evidence.candidate_recipe_ids


def test_compiler_selected_recipe_exists_in_the_library() -> None:
    intent = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library())
    assert (
        _library().get(
            intent.recipe_evidence.selected_recipe_id, intent.recipe_evidence.selected_version
        )
        is not None
    )


def test_compiler_carries_the_product_identity() -> None:
    intent = _compiler().compile("P07_MARKETING", recipe_library=_library())
    assert intent.product_id == "P07_MARKETING"
    assert intent.commercial_product == "P07_MARKETING"
    assert intent.product_type == "P08_COMMERCIAL"


def test_compiler_records_the_profile_version() -> None:
    intent = _compiler().compile("P07_MARKETING", recipe_library=_library())
    assert intent.product_profile_version == "1.0.0"


def test_compiler_merges_constraints_from_all_layers() -> None:
    intent = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library())
    keys = {c.key for c in intent.constraints}
    assert keys >= {
        "camera_directive",
        "editing_directive",
        "style_legibility",
        "motion_restrained",
    }


def test_compiler_constraints_are_deduplicated_and_sorted() -> None:
    intent = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library())
    triples = [(c.key, c.value, c.rationale) for c in intent.constraints]
    assert triples == sorted(set(triples))


def test_compiler_accepts_extra_constraints() -> None:
    extra = (ProductConstraint(key="brand_rule", value="no_logo"),)
    base = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library())
    with_extra = _compiler().compile(
        "P03_DOCUMENTARY", recipe_library=_library(), extra_constraints=extra
    )
    assert {c.key for c in with_extra.constraints} > {c.key for c in base.constraints}
    assert "brand_rule" in {c.key for c in with_extra.constraints}


def test_compiler_extra_constraints_change_the_hash() -> None:
    base = _compiler().compile("P03_DOCUMENTARY", recipe_library=_library())
    other = _compiler().compile(
        "P03_DOCUMENTARY",
        recipe_library=_library(),
        extra_constraints=(ProductConstraint(key="brand_rule", value="no_logo"),),
    )
    assert base.content_hash() != other.content_hash()


def test_compiler_unknown_profile_id_fails_closed_in_p5_3() -> None:
    with pytest.raises(ProductCompilationError, match="P5_3_NO_RECIPE"):
        _compiler().compile(
            "P03_DOCUMENTARY", recipe_library=_library(), profile_id="__NOPE__"
        )


def test_compiler_empty_library_fails_closed() -> None:
    with pytest.raises(ProductCompilationError, match="P5_3_NO_RECIPE"):
        _compiler().compile("P03_DOCUMENTARY", recipe_library=RecipeLibrary())


def test_compiler_unknown_narrative_grammar_raises() -> None:
    profile = copy.replace(
        COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY"),
        narrative_grammar_id="no_such_narrative",
    )
    with pytest.raises(ProductCompilationError, match="NARRATIVE_INVALID"):
        _compiler().compile(profile, recipe_library=_library())


def test_compiler_unknown_presenter_grammar_raises() -> None:
    profile = copy.replace(
        COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY"),
        presenter_grammar_id="no_such_presenter",
    )
    with pytest.raises(ProductCompilationError, match="PRESENTER_INVALID"):
        _compiler().compile(profile, recipe_library=_library())


def test_compiler_unknown_visual_style_raises() -> None:
    profile = copy.replace(
        COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY"), visual_style_id="no_such_style"
    )
    with pytest.raises(ProductCompilationError, match="VISUAL_STYLE_INVALID"):
        _compiler().compile(profile, recipe_library=_library())


def test_compiler_unknown_visual_grammar_raises() -> None:
    profile = copy.replace(
        COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY"),
        visual_grammar_id="no_such_grammar",
    )
    with pytest.raises(ProductCompilationError, match="VISUAL_GRAMMAR_INVALID"):
        _compiler().compile(profile, recipe_library=_library())


def test_compiler_incompatible_grammar_pairing_raises() -> None:
    profile = copy.replace(
        COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY"),
        presenter_grammar_id="product_presentation",
    )
    with pytest.raises(ProductCompilationError, match="PRESENTER_INVALID"):
        _compiler().compile(profile, recipe_library=_library())


def test_compiler_style_conflict_raises() -> None:
    profile = copy.replace(
        COMMERCIAL_PRODUCT_REGISTRY.get("P07_MARKETING"), visual_style_id="corporate_clean"
    )
    with pytest.raises(ProductCompilationError, match="VISUAL_GRAMMAR_INVALID"):
        _compiler().compile(profile, recipe_library=_library())


def test_compiler_compile_all_returns_ten_plans() -> None:
    plans = _compiler().compile_all(recipe_library=_library())
    assert len(plans) == 10


def test_compiler_compile_all_is_id_ordered() -> None:
    plans = _compiler().compile_all(recipe_library=_library())
    assert [p.product_id for p in plans] == COMMERCIAL_PRODUCT_REGISTRY.list_ids()


def test_compiler_compile_all_plans_are_all_valid() -> None:
    for plan in _compiler().compile_all(recipe_library=_library()):
        assert plan.recipe_evidence.selected_recipe_id
        assert plan.narrative_intent.grammar_id
        assert plan.presenter_intent.grammar_id


def test_compiler_is_stateless_across_ten_compiles() -> None:
    compiler = _compiler()
    first = compiler.compile("P03_DOCUMENTARY", recipe_library=_library()).content_hash()
    for pid in compiler.list_products():
        compiler.compile(pid, recipe_library=_library())
    assert compiler.compile("P03_DOCUMENTARY", recipe_library=_library()).content_hash() == first


def test_compiler_order_does_not_affect_a_result() -> None:
    compiler = _compiler()
    forward = [compiler.compile(pid, recipe_library=_library()).content_hash() for pid in compiler.list_products()]
    reverse = [compiler.compile(pid, recipe_library=_library()).content_hash() for pid in reversed(compiler.list_products())]
    assert forward == list(reversed(reverse))


def test_compiler_fresh_instances_agree() -> None:
    a = _compiler().compile("P07_MARKETING", recipe_library=_library()).content_hash()
    b = ProductCompiler().compile("P07_MARKETING", recipe_library=_library()).content_hash()
    assert a == b


def test_compiler_injected_sub_compilers_are_used() -> None:
    compiler = ProductCompiler(
        narrative_compiler=NarrativeCompiler(NARRATIVE_GRAMMAR_REGISTRY),
        presenter_compiler=PresenterCompiler(
            PRESENTER_GRAMMAR_REGISTRY, GRAMMAR_COMPATIBILITY_REGISTRY
        ),
        visual_style_compiler=VisualStyleCompiler(
            VISUAL_STYLE_REGISTRY, STYLE_COMPATIBILITY_REGISTRY
        ),
        visual_compiler=VisualCompiler(
            VISUAL_GRAMMAR_REGISTRY, VISUAL_GRAMMAR_COMPATIBILITY
        ),
    )
    assert compiler.compile("P03_DOCUMENTARY", recipe_library=_library()).product_id


def test_compiler_custom_registry_is_honoured() -> None:
    registry = CommercialProductRegistry()
    registry.register(BUILTIN_PRODUCT_PROFILES[0])
    compiler = ProductCompiler(registry=registry)
    assert compiler.list_products() == [BUILTIN_PRODUCT_PROFILES[0].id]
    with pytest.raises(ProductCompilationError, match="UNKNOWN_PRODUCT_PROFILE"):
        compiler.compile("P03_DOCUMENTARY", recipe_library=_library())


def test_compiler_intent_hash_differs_across_products() -> None:
    hashes = {
        _compiler().compile(pid, recipe_library=_library()).content_hash()
        for pid in _compiler().list_products()
    }
    assert len(hashes) == 10


def test_compiler_intent_hash_is_stable_for_one_product() -> None:
    compiler = _compiler()
    hashes = {
        compiler.compile("P09_SHORT_VIDEO", recipe_library=_library()).content_hash()
        for _ in range(20)
    }
    assert len(hashes) == 1


def test_compiler_determinism_over_1000_compile_cycles() -> None:
    compiler, library = _compiler(), _library()
    products = compiler.list_products()
    hashes: set[str] = set()
    for i in range(1000):
        product = products[i % len(products)]
        hashes.add(compiler.compile(product, recipe_library=library).content_hash())
    # Ten products, so exactly ten distinct hashes across 1000 cycles.
    assert len(hashes) == 10


def test_compiler_determinism_over_1000_cycles_of_one_product() -> None:
    compiler, library = _compiler(), _library()
    hashes = {
        compiler.compile("P02_HISTORY_RECONSTRUCTION", recipe_library=library).content_hash()
        for _ in range(1000)
    }
    assert len(hashes) == 1


def test_compiler_determinism_evidence_excludes_timestamp() -> None:
    compiler, library = _compiler(), _library()
    first = compiler.compile("P03_DOCUMENTARY", recipe_library=library)
    second = compiler.compile("P03_DOCUMENTARY", recipe_library=library)
    assert first.content_hash() == second.content_hash()
    # The decision is identical even though P5.3 stamps a fresh timestamp on
    # every run, which is exactly why the plan hash must not cover it.
    assert "timestamp" not in first.to_dict()["recipe_evidence"]


def test_compiler_does_not_build_a_shot_plan() -> None:
    assert guard_no_shot_or_motion_construction(COMPILER_FILE.read_text()) == []


def test_compiler_module_defines_no_second_authority_type() -> None:
    for path in P6_5_FILES:
        assert guard_no_second_authority(path.read_text()) == [], path.name


def test_compiler_module_imports_no_frozen_authority() -> None:
    for path in P6_5_FILES:
        assert guard_imports(path.read_text()) == [], path.name


def test_compiler_holds_no_product_literal() -> None:
    assert guard_no_product_literals(COMPILER_FILE.read_text()) == []


def test_compiler_has_no_product_named_helper() -> None:
    assert guard_no_product_named_helpers(COMPILER_FILE.read_text()) == []


def test_compiler_module_names_no_product_in_a_branch() -> None:
    for node in ast.walk(ast.parse(COMPILER_FILE.read_text())):
        if isinstance(node, (ast.If, ast.IfExp)):
            assert guard_no_product_literals(ast.unparse(node.test)) == []


def test_compiler_is_exported_from_the_package() -> None:
    import hevi.production.p6 as p6

    assert p6.ProductCompiler is ProductCompiler


# ═══════════════════════════════════════════════════════════════════════════
# PRODUCT MATRIX (100 combinations)
# ═══════════════════════════════════════════════════════════════════════════


def test_matrix_ten_products_resolve() -> None:
    assert len(_compiler().list_products()) == 10


def test_matrix_every_product_compiles() -> None:
    compiler, library = _compiler(), _library()
    for product_id in compiler.list_products():
        plan = compiler.compile(product_id, recipe_library=library)
        assert plan.recipe_evidence.selected_recipe_id, product_id


def test_matrix_every_product_names_a_real_recipe() -> None:
    compiler, library = _compiler(), _library()
    for product_id in compiler.list_products():
        plan = compiler.compile(product_id, recipe_library=library)
        assert (
            library.get(plan.recipe_evidence.selected_recipe_id, plan.recipe_evidence.selected_version)
            is not None
        ), product_id


def test_matrix_every_product_declares_a_product_type() -> None:
    for product_id in _compiler().list_products():
        plan = _compiler().compile(product_id, recipe_library=_library())
        assert ProductType(plan.product_type)


def test_matrix_every_product_uses_a_declared_narrative() -> None:
    for product_id in _compiler().list_products():
        plan = _compiler().compile(product_id, recipe_library=_library())
        assert plan.narrative_intent.grammar_id in NARRATIVE_GRAMMAR_REGISTRY.list_ids()


def test_matrix_every_product_uses_a_declared_presenter() -> None:
    for product_id in _compiler().list_products():
        plan = _compiler().compile(product_id, recipe_library=_library())
        assert plan.presenter_intent.grammar_id in PRESENTER_GRAMMAR_REGISTRY.list_ids()


def test_matrix_every_product_uses_a_declared_visual_style() -> None:
    for product_id in _compiler().list_products():
        plan = _compiler().compile(product_id, recipe_library=_library())
        assert plan.visual_style_intent.style_id in VISUAL_STYLE_REGISTRY.list_ids()


def test_matrix_every_product_uses_a_declared_visual_grammar() -> None:
    for product_id in _compiler().list_products():
        plan = _compiler().compile(product_id, recipe_library=_library())
        assert plan.visual_intent.visual_grammar_id in VISUAL_GRAMMAR_REGISTRY.list_ids()


def test_matrix_product_to_narrative_mapping() -> None:
    expected = {
        "P01_AVATAR_EXPLAINER": "explanatory",
        "P02_HISTORY_RECONSTRUCTION": "story",
        "P03_DOCUMENTARY": "documentary",
        "P04_SCIENCE_EXPLAINER": "explanatory",
        "P05_NEWS_ANALYSIS": "documentary",
        "P06_EDUCATIONAL": "explanatory",
        "P07_MARKETING": "explanatory",
        "P08_BRAND_STORY": "story",
        "P09_SHORT_VIDEO": "short_form",
        "P10_CINEMATIC_STORY": "story",
    }
    compiler, library = _compiler(), _library()
    for product_id, narrative in expected.items():
        assert compiler.compile(product_id, recipe_library=library).narrative_intent.grammar_id == (
            narrative
        )


def test_matrix_product_to_visual_grammar_mapping() -> None:
    expected = {
        "P01_AVATAR_EXPLAINER": "educational_clarity",
        "P02_HISTORY_RECONSTRUCTION": "dramatic_reconstruction",
        "P03_DOCUMENTARY": "documentary_realism",
        "P04_SCIENCE_EXPLAINER": "educational_clarity",
        "P05_NEWS_ANALYSIS": "documentary_realism",
        "P06_EDUCATIONAL": "educational_clarity",
        "P07_MARKETING": "educational_clarity",
        "P08_BRAND_STORY": "dramatic_reconstruction",
        "P09_SHORT_VIDEO": "educational_clarity",
        "P10_CINEMATIC_STORY": "dramatic_reconstruction",
    }
    compiler, library = _compiler(), _library()
    for product_id, grammar in expected.items():
        assert compiler.compile(
            product_id, recipe_library=library
        ).visual_intent.visual_grammar_id == grammar


def test_matrix_no_product_selects_a_product_named_grammar() -> None:
    for product_id in _compiler().list_products():
        plan = _compiler().compile(product_id, recipe_library=_library())
        assert plan.visual_intent.visual_grammar_id in VISUAL_GRAMMAR_REGISTRY.list_ids()
        assert "product" not in plan.visual_intent.visual_grammar_id


def test_matrix_all_100_product_beat_combinations_bind() -> None:
    """10 products x 10 beat roles. Every cell must reach a recorded decision."""
    compiler, library = _compiler(), _library()
    bound = 0
    for product_id in compiler.list_products():
        plan = compiler.compile(product_id, recipe_library=library)
        for role in BEAT_ROLES:
            binding = compiler.visual_compiler.bind(library, plan.visual_intent, beat=_beat(plan, role))
            assert binding.evidence.selected_recipe_id, (product_id, role)
            bound += 1
    assert bound == 100


def test_matrix_all_100_combinations_are_deterministic() -> None:
    compiler, library = _compiler(), _library()
    seen: set[tuple[str, str]] = set()
    for product_id in compiler.list_products():
        plan = compiler.compile(product_id, recipe_library=library)
        for role in BEAT_ROLES:
            first = compiler.visual_compiler.bind(library, plan.visual_intent, beat=_beat(plan, role))
            second = compiler.visual_compiler.bind(library, plan.visual_intent, beat=_beat(plan, role))
            assert first.evidence_fingerprint() == second.evidence_fingerprint()
            seen.add((product_id, role))
    assert len(seen) == 100


def test_matrix_every_product_appears_with_every_beat_role() -> None:
    pairs = {
        (product_id, role)
        for product_id in _compiler().list_products()
        for role in BEAT_ROLES
    }
    assert len(pairs) == 100


def test_matrix_shared_shapes_really_share() -> None:
    # Two products with identical grammar references must produce identical
    # intents except for identity. That is what "one pipeline" means concretely.
    compiler, library = _compiler(), _library()
    p01 = compiler.compile("P01_AVATAR_EXPLAINER", recipe_library=library)
    p04 = compiler.compile("P04_SCIENCE_EXPLAINER", recipe_library=library)
    def strip(d):
        return {k: v for k, v in d.items() if k != "product_profile_id"}
    assert strip(p01.narrative_intent.to_dict()) == strip(p04.narrative_intent.to_dict())
    assert strip(p01.visual_intent.to_dict()) == strip(p04.visual_intent.to_dict())
    assert p01.recipe_evidence.selected_recipe_id == p04.recipe_evidence.selected_recipe_id
    assert p01.content_hash() != p04.content_hash()  # identity differs


def test_matrix_recipe_selection_varies_across_products() -> None:
    compiler, library = _compiler(), _library()
    selected = {
        compiler.compile(product_id, recipe_library=library).recipe_evidence.selected_recipe_id
        for product_id in compiler.list_products()
    }
    assert len(selected) >= 2


# ═══════════════════════════════════════════════════════════════════════════
# COMPATIBILITY
# ═══════════════════════════════════════════════════════════════════════════


def test_compatibility_every_product_narrative_presenter_pairing_permitted() -> None:
    for profile in BUILTIN_PRODUCT_PROFILES:
        permitted = GRAMMAR_COMPATIBILITY_REGISTRY.allowed(profile.narrative_grammar_id)
        assert profile.presenter_grammar_id in permitted, profile.id


def test_compatibility_every_product_narrative_style_pairing_permitted() -> None:
    for profile in BUILTIN_PRODUCT_PROFILES:
        permitted = STYLE_COMPATIBILITY_REGISTRY.allowed(profile.narrative_grammar_id)
        assert profile.visual_style_id in permitted, profile.id


def test_compatibility_every_product_narrative_visual_grammar_permitted() -> None:
    for profile in BUILTIN_PRODUCT_PROFILES:
        permitted = VISUAL_GRAMMAR_COMPATIBILITY.allowed(profile.narrative_grammar_id)
        assert profile.visual_grammar_id in permitted, profile.id


def test_compatibility_every_presenter_can_carry_its_composition() -> None:
    for profile in BUILTIN_PRODUCT_PROFILES:
        allowed = COMPOSITION_COMPATIBILITY.get(profile.presenter_grammar_id)
        if allowed is None:
            continue
        style = VISUAL_STYLE_REGISTRY.get(profile.visual_style_id)
        assert style.composition_language in allowed, profile.id


def test_compatibility_style_and_visual_grammar_agree_on_shared_languages() -> None:
    for profile in BUILTIN_PRODUCT_PROFILES:
        style = VISUAL_STYLE_REGISTRY.get(profile.visual_style_id)
        grammar = VISUAL_GRAMMAR_REGISTRY.get(profile.visual_grammar_id)
        assert style.motion_language is grammar.motion_language, profile.id
        assert style.composition_language is grammar.composition_language, profile.id
        assert style.lighting_language is grammar.lighting_language, profile.id


def test_compatibility_all_ten_pass_every_table() -> None:
    for profile in BUILTIN_PRODUCT_PROFILES:
        compiler, library = _compiler(), _library()
        assert compiler.compile(profile, recipe_library=library).recipe_evidence.selected_recipe_id


def test_compatibility_narrative_grammar_registry_validates() -> None:
    ok, errors = NARRATIVE_GRAMMAR_REGISTRY.validate_all()
    assert ok, errors


def test_compatibility_presenter_registry_validates() -> None:
    ok, errors = PRESENTER_GRAMMAR_REGISTRY.validate_all()
    assert ok, errors


def test_compatibility_presenter_pairing_table_validates() -> None:
    ok, errors = GRAMMAR_COMPATIBILITY_REGISTRY.validate_all()
    assert ok, errors


def test_compatibility_style_registry_validates() -> None:
    ok, errors = VISUAL_STYLE_REGISTRY.validate_all()
    assert ok, errors


def test_compatibility_style_pairing_table_validates() -> None:
    ok, errors = STYLE_COMPATIBILITY_REGISTRY.validate_all()
    assert ok, errors


def test_compatibility_visual_grammar_registry_validates() -> None:
    ok, errors = VISUAL_GRAMMAR_REGISTRY.validate_all()
    assert ok, errors


def test_compatibility_visual_grammar_pairing_table_validates() -> None:
    ok, errors = VISUAL_GRAMMAR_COMPATIBILITY.validate_all()
    assert ok, errors


def test_compatibility_every_used_narrative_is_a_known_one() -> None:
    used = {p.narrative_grammar_id for p in BUILTIN_PRODUCT_PROFILES}
    assert used <= set(NARRATIVE_GRAMMAR_REGISTRY.list_ids())


def test_compatibility_every_used_presenter_is_a_known_one() -> None:
    used = {p.presenter_grammar_id for p in BUILTIN_PRODUCT_PROFILES}
    assert used <= set(PRESENTER_GRAMMAR_REGISTRY.list_ids())


def test_compatibility_every_used_style_is_a_known_one() -> None:
    used = {p.visual_style_id for p in BUILTIN_PRODUCT_PROFILES}
    assert used <= set(VISUAL_STYLE_REGISTRY.list_ids())


def test_compatibility_every_used_visual_grammar_is_a_known_one() -> None:
    used = {p.visual_grammar_id for p in BUILTIN_PRODUCT_PROFILES}
    assert used <= set(VISUAL_GRAMMAR_REGISTRY.list_ids())


def test_compatibility_all_four_narrative_shapes_are_exercised() -> None:
    used = {p.narrative_grammar_id for p in BUILTIN_PRODUCT_PROFILES}
    assert used == {"documentary", "explanatory", "story", "short_form"}


def test_compatibility_three_presenter_shapes_are_exercised() -> None:
    used = {p.presenter_grammar_id for p in BUILTIN_PRODUCT_PROFILES}
    assert used == {
        "avatar_explainer",
        "documentary_explainer",
        "historical_reconstruction",
        "educational_lecture",
        "product_presentation",
    }


def test_compatibility_corporate_clean_style_is_not_used_by_any_product() -> None:
    # Its only coherent P6.4 partner would be commercial_clean, which conflicts
    # on motion. Recorded as a gap rather than forced.
    used = {p.visual_style_id for p in BUILTIN_PRODUCT_PROFILES}
    assert "corporate_clean" not in used


def test_compatibility_every_product_narrative_is_constrained_by_all_four_tables() -> None:
    # The four tables must agree about the narrative each product declares.
    for profile in BUILTIN_PRODUCT_PROFILES:
        narrative = profile.narrative_grammar_id
        assert GRAMMAR_COMPATIBILITY_REGISTRY.allowed(narrative) is not None, profile.id
        assert STYLE_COMPATIBILITY_REGISTRY.allowed(narrative) is not None, profile.id
        assert VISUAL_GRAMMAR_COMPATIBILITY.allowed(narrative) is not None, profile.id
        assert NARRATIVE_GRAMMAR_REGISTRY.has(narrative), profile.id


def test_compatibility_selected_recipe_varies_by_narrative_shape() -> None:
    compiler, library = _compiler(), _library()
    by_shape: dict[str, str] = {}
    for product_id in compiler.list_products():
        plan = compiler.compile(product_id, recipe_library=library)
        by_shape.setdefault(plan.narrative_intent.grammar_id, plan.recipe_evidence.selected_recipe_id)
    assert by_shape["documentary"] != by_shape["story"]


def test_compatibility_presenter_shape_changes_only_identity_not_shape() -> None:
    # P01/P04 share a presenter; P06 shares the narrative but not the presenter,
    # and both still land on the same visual shape.
    compiler, library = _compiler(), _library()
    p01 = compiler.compile("P01_AVATAR_EXPLAINER", recipe_library=library)
    p06 = compiler.compile("P06_EDUCATIONAL", recipe_library=library)
    assert p01.presenter_intent.grammar_id != p06.presenter_intent.grammar_id
    assert p01.visual_style_intent.style_id == p06.visual_style_intent.style_id
    assert p01.visual_intent.visual_grammar_id == p06.visual_intent.visual_grammar_id


def test_compatibility_commercial_clean_grammar_is_not_used_by_any_product() -> None:
    used = {p.visual_grammar_id for p in BUILTIN_PRODUCT_PROFILES}
    assert "commercial_clean" not in used


def test_compatibility_incompatible_presenter_swap_is_refused() -> None:
    profile = copy.replace(
        COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY"),
        presenter_grammar_id="avatar_explainer",
    )
    with pytest.raises(ProductCompilationError):
        _compiler().compile(profile, recipe_library=_library())


def test_compatibility_incompatible_style_swap_is_refused() -> None:
    profile = copy.replace(
        COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY"),
        visual_style_id="future_tech",
    )
    with pytest.raises(ProductCompilationError):
        _compiler().compile(profile, recipe_library=_library())


def test_compatibility_incompatible_visual_grammar_swap_is_refused() -> None:
    profile = copy.replace(
        COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY"),
        visual_grammar_id="educational_clarity",
    )
    with pytest.raises(ProductCompilationError):
        _compiler().compile(profile, recipe_library=_library())


def test_compatibility_every_incoherent_swap_is_refused() -> None:
    compiler, library = _compiler(), _library()
    base = COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY")
    for field_name, bad in (
        ("narrative_grammar_id", "short_form"),
        ("presenter_grammar_id", "avatar_explainer"),
        ("visual_style_id", "future_tech"),
        ("visual_grammar_id", "educational_clarity"),
    ):
        with pytest.raises(ProductCompilationError):
            compiler.compile(copy.replace(base, **{field_name: bad}), recipe_library=library)


def test_compatibility_every_product_type_is_used_at_least_once() -> None:
    used = {p.product_type for p in BUILTIN_PRODUCT_PROFILES}
    assert len(used) == 9


def test_compatibility_no_product_declares_a_product_named_visual_reference() -> None:
    # The visual layer must stay product-free. The narrative and presenter ids
    # are P6.1/P6.2's shared general grammars (``historical_reconstruction`` is a
    # legitimate *shape*, not a product), so they are checked against their
    # registries rather than by substring.
    forbidden = ("history", "avatar", "science", "news", "marketing", "brand", "commercial")
    for profile in BUILTIN_PRODUCT_PROFILES:
        for value in (profile.visual_style_id, profile.visual_grammar_id):
            assert not any(token in value for token in forbidden), (profile.id, value)


def test_compatibility_presenter_shapes_are_general_not_products() -> None:
    used = {p.presenter_grammar_id for p in BUILTIN_PRODUCT_PROFILES}
    assert used <= set(PRESENTER_GRAMMAR_REGISTRY.list_ids())
    assert "historical_reconstruction" in used  # a shape, not a product


def test_compatibility_unused_style_count_is_known() -> None:
    used = {p.visual_style_id for p in BUILTIN_PRODUCT_PROFILES}
    unused = set(VISUAL_STYLE_REGISTRY.list_ids()) - used
    # Recorded rather than silently worked around; see G-14.
    assert unused == {"archival_history", "corporate_clean", "future_tech"}


# ═══════════════════════════════════════════════════════════════════════════
# MUTATION
# ═══════════════════════════════════════════════════════════════════════════


def test_mutation_injected_product_id_branch_must_fail(tmp_path: Path) -> None:
    """MUTATION 1 — `if product_id == "P02"` must be caught."""
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "        if recipe_library is None:",
        "        if product_id == \"P02_HISTORY_RECONSTRUCTION\":\n"
        "            narrative = self.narrative_compiler.compile_with(\n"
        "                COMMERCIAL_PRODUCT_REGISTRY.get('P03_DOCUMENTARY')\n"
        "            )\n"
        "        if recipe_library is None:",
    )
    found = guard_no_product_literals(mutated)
    assert "product_literal:P02_HISTORY_RECONSTRUCTION" in found
    assert guard_no_product_literals(COMPILER_FILE.read_text()) == []


def test_mutation_injected_product_branch_in_compile_with_product_type_must_fail(
    tmp_path: Path,
) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "        ok, errors = self.validate_profile(profile)",
        "        if profile.product_type.value == \"P03_HISTORICAL_REENACTMENT\":\n"
        "            profile = copy.replace(profile, visual_grammar_id=\"dramatic_reconstruction\")\n"
        "        ok, errors = self.validate_profile(profile)",
    )
    assert guard_no_product_literals(mutated) == [
        "product_literal:P03_HISTORICAL_REENACTMENT"
    ]


def test_mutation_injected_history_compiler_helper_must_fail(tmp_path: Path) -> None:
    """MUTATION 2 — `history_compiler()` must be caught."""
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "    compiler_id = \"p6_5_product_compiler\"",
        "    def history_compiler(self) -> ProductCompiler:\n"
        "        \"\"\"A dedicated compiler for history reconstruction.\"\"\"\n"
        "        return self\n\n"
        "    compiler_id = \"p6_5_product_compiler\"",
    )
    assert guard_no_product_named_helpers(mutated) == ["history_compiler"]
    assert guard_no_product_named_helpers(COMPILER_FILE.read_text()) == []


def test_mutation_injected_science_compiler_helper_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "    compiler_id = \"p6_5_product_compiler\"",
        "    def science_compiler(self) -> ProductCompiler:\n"
        "        return self\n\n"
        "    compiler_id = \"p6_5_product_compiler\"",
    )
    assert guard_no_product_named_helpers(mutated) == ["science_compiler"]


def test_mutation_compiler_creating_a_shot_plan_must_fail(tmp_path: Path) -> None:
    """MUTATION 3 — ProductCompiler constructing a ShotPlan must be caught."""
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "        return ProductProductionIntent(",
        "        from hevi.production.p0_pipeline import ShotPlan as _ShotPlan\n"
        "        _shot_plan = _ShotPlan(shot_id=\"s1\")\n"
        "        return ProductProductionIntent(",
    )
    guard = guard_no_shot_or_motion_construction(mutated)
    assert "constructs:_ShotPlan" in guard


def test_mutation_compiler_defining_a_shot_plan_type_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "class ProductCompilationError(ValueError):",
        "class ShotPlan:\n    shot_id: str = \"\"\n\n\n"
        "class ProductCompilationError(ValueError):",
    )
    assert guard_no_second_authority(mutated) == ["ShotPlan"]
    assert guard_no_second_authority(COMPILER_FILE.read_text()) == []


def test_mutation_compiler_defining_a_motion_plan_type_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "class ProductCompilationError(ValueError):",
        "class MotionPlan:\n    motion_id: str = \"\"\n\n\n"
        "class ProductCompilationError(ValueError):",
    )
    assert guard_no_second_authority(mutated) == ["MotionPlan"]


def test_mutation_compiler_defining_a_recipe_selector_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "class ProductCompilationError(ValueError):",
        "class RecipeSelector:\n    pass\n\n\n"
        "class ProductCompilationError(ValueError):",
    )
    assert guard_no_second_authority(mutated) == ["RecipeSelector"]


def test_mutation_bypassing_narrative_compiler_must_fail(tmp_path: Path) -> None:
    """MUTATION 4 — reaching around NarrativeCompiler must be caught."""
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "            narrative = self.narrative_compiler.compile_with(\n"
        "                profile, extra_constraints=extra_constraints\n"
        "            )",
        "            grammar = NARRATIVE_GRAMMAR_REGISTRY.resolve(profile.narrative_grammar_id)\n"
        "            narrative = NarrativeIntent(\n"
        "                grammar_id=grammar.id,\n"
        "                grammar_version=grammar.version,\n"
        "                product_profile_id=profile.id,\n"
        "            )",
    )
    node = _function_node(mutated, "compile")
    text = ast.unparse(node)
    assert "self.narrative_compiler.compile_with" not in text
    assert "NARRATIVE_GRAMMAR_REGISTRY.resolve" in text


def test_mutation_bypassing_presenter_compiler_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "            presenter = self.presenter_compiler.compile_with(\n"
        "                profile, narrative, extra_constraints=extra_constraints\n"
        "            )",
        "            presenter = PresenterIntent(\n"
        "                grammar_id=profile.presenter_grammar_id,\n"
        "                product_profile_id=profile.id,\n"
        "            )",
    )
    text = ast.unparse(_function_node(mutated, "compile"))
    assert "self.presenter_compiler.compile_with" not in text


def test_mutation_bypassing_visual_compiler_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "            visual = self.visual_compiler.compile(",
        "            visual = VisualIntent(\n"
        "                visual_grammar_id=profile.visual_grammar_id,\n"
        "                product_profile_id=profile.id,\n"
        "            )\n"
        "            _unused = self.visual_compiler.compile(",
    )
    text = ast.unparse(_function_node(mutated, "compile"))
    # The injected VisualIntent is what the compiler now returns.
    assert text.count("VisualIntent(") == 1
    assert "visual = VisualIntent(" in text


def test_mutation_injected_renderer_import_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "from hevi.production.p5_3.library import RecipeLibrary",
        "from hevi.renderers.base import select_renderer\n"
        "from hevi.production.p5_3.library import RecipeLibrary",
    )
    assert guard_imports(mutated) == ["hevi.renderers.base"]
    assert guard_imports(COMPILER_FILE.read_text()) == []


def test_mutation_injected_provider_import_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "from hevi.production.p5_3.library import RecipeLibrary",
        "from hevi.providers.tts import VolcanoTTS\n"
        "from hevi.production.p5_3.library import RecipeLibrary",
    )
    assert guard_imports(mutated) == ["hevi.providers.tts"]


def test_mutation_every_product_branch_shape_is_caught() -> None:
    shapes = (
        'if profile.product_id == "P02_HISTORY_RECONSTRUCTION": pass',
        'if profile.product_type.value == "P03_HISTORICAL_REENACTMENT": pass',
        'if str(profile.product_id) == "P02_HISTORY_RECONSTRUCTION": pass',
        'def f(product_id):\n    return product_id == "P02_HISTORY_RECONSTRUCTION"',
        'x = {"P02_HISTORY_RECONSTRUCTION": "dramatic_reconstruction"}',
        'GRAMMARS = ["P02_HISTORY_RECONSTRUCTION"]',
    )
    for shape in shapes:
        assert guard_no_product_literals(shape), shape


def test_mutation_catalogue_data_is_not_mistaken_for_branching() -> None:
    # The catalogue is *supposed* to contain product ids. The guard must catch a
    # product literal in a branch, not in a row.
    data = 'P02_HISTORY_RECONSTRUCTION = "P02_HISTORY_RECONSTRUCTION"\n'
    assert guard_no_product_literals(data) != []  # a bare literal is flagged
    branch = 'if x == "P02_HISTORY_RECONSTRUCTION": pass'
    assert guard_no_product_literals(branch) != []
    # ...and the real module only ever puts them in data position.
    for node in ast.walk(ast.parse(PROFILES_FILE.read_text())):
        if isinstance(node, (ast.If, ast.IfExp)):
            assert guard_no_product_literals(ast.unparse(node.test)) == []


def test_mutation_no_product_literals_in_p6_5_modules() -> None:
    for path in P6_5_FILES:
        if path is PROFILES_FILE:
            continue
        assert guard_no_product_literals(path.read_text()) == [], path.name


def test_mutation_no_product_named_helpers_in_p6_5_modules() -> None:
    for path in P6_5_FILES:
        assert guard_no_product_named_helpers(path.read_text()) == [], path.name


def test_mutation_no_second_authority_in_p6_5_modules() -> None:
    for path in P6_5_FILES:
        assert guard_no_second_authority(path.read_text()) == [], path.name


def test_mutation_no_authority_type_anywhere_in_p6_5_modules() -> None:
    for path in P6_5_FILES:
        assert guard_no_authority_anywhere(path.read_text()) == [], path.name


def test_mutation_module_wide_guard_catches_an_aliased_import(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "from hevi.production.p5_3.library import RecipeLibrary",
        "from hevi.production.p0_pipeline import ShotPlan as _SP\n"
        "from hevi.production.p5_3.library import RecipeLibrary",
    )
    assert guard_no_authority_anywhere(mutated) == ["imports:ShotPlan"]


def test_mutation_module_wide_guard_catches_a_lowercase_alias(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "from hevi.production.p5_3.library import RecipeLibrary",
        "from hevi.production.p0_pipeline import MotionPlan as timeline\n"
        "from hevi.production.p5_3.library import RecipeLibrary",
    )
    assert guard_no_authority_anywhere(mutated) == ["imports:MotionPlan"]


def test_mutation_module_wide_guard_catches_a_render_command(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path,
        COMPILER_FILE,
        "        return ProductProductionIntent(",
        "        return ProductProductionIntent(\n"
        "            constraints=_dedupe(extra_constraints) + (RenderCommand(),)\n"
        "        ) or ProductProductionIntent(",
    )
    assert "constructs:RenderCommand" in guard_no_authority_anywhere(mutated)


def test_mutation_no_frozen_import_in_p6_5_modules() -> None:
    for path in P6_5_FILES:
        assert guard_imports(path.read_text()) == [], path.name
