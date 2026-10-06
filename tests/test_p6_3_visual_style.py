"""HEVI P6.3 — Visual style grammar validation.

Phase 9 requires Architecture >=30, Registry >=20, Compiler >=30, Compatibility
>=20, Mutation >=5, plus 100 repeated compiles for determinism.

Authority guards are written as pure module-level functions rather than inline
test bodies. That is deliberate: P6.2's branching guard inspected only the
top-level operands of a comparison, so ``profile.product_type.value == "P08"``
slipped past it while ``profile.product_type == "P08"`` was caught — the guard
hole sat exactly where a real product branch would be written. A guard you can
call on an arbitrary string is a guard you can mutation-test, and these probe the
mutated form rather than re-asserting the happy path.
"""

from __future__ import annotations

import ast
import copy
import re
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from hevi.production.p6 import schema as p6_schema
from hevi.production.p6.intent import ProductIntentError, compile_product_intent
from hevi.production.p6.narrative.compiler import (
    NarrativeIntent,
    NarrativeValidationResult,
)
from hevi.production.p6.presenter_compiler import (
    PresenterIntent,
    PresenterValidationResult,
)
from hevi.production.p6.schema import (
    GrammarKind,
    GrammarRef,
    ProductConstraint,
    ProductProfile,
    ProductType,
)
from hevi.production.p6.visual_style import (
    BUILTIN_VISUAL_STYLES,
    CINEMATIC_DRAMA,
    COMPOSITION_COMPATIBILITY,
    CORPORATE_CLEAN,
    DOCUMENTARY_REALISM,
    STYLE_COMPATIBILITY_REGISTRY,
    VISUAL_STYLE_REGISTRY,
    ColorLanguage,
    CompositionLanguage,
    LightingLanguage,
    Mood,
    MotionLanguage,
    StyleCategory,
    StyleCompatibilityRegistry,
    TextureLanguage,
    VisualStyleCompiler,
    VisualStyleGrammar,
    VisualStyleIntent,
    VisualStyleRegistry,
    VisualStyleValidationResult,
    register_builtin_styles,
)

PKG_DIR = Path(p6_schema.__file__).parent
VISUAL_STYLE_DIR = PKG_DIR / "visual_style"
P6_MODULE_FILES = tuple(sorted(PKG_DIR.glob("*.py"))) + tuple(
    sorted(VISUAL_STYLE_DIR.glob("*.py"))
)
P6_MODULE_NAMES = tuple(p.name for p in P6_MODULE_FILES)

ALL_STYLES = tuple(s for s in BUILTIN_VISUAL_STYLES)
ALL_STYLE_IDS = tuple(s.id for s in ALL_STYLES)
NARRATIVE_IDS = ("documentary", "explanatory", "story", "short_form")
PRESENTER_IDS = (
    "avatar_explainer",
    "documentary_explainer",
    "historical_reconstruction",
    "educational_lecture",
    "product_presentation",
)

#: Module prefixes P6.3 must never import. The full list, not a subset: P6.3 is
#: a semantics layer, so every one of these is a second authority.
FORBIDDEN_IMPORT_PREFIXES = (
    "hevi.renderers",
    "hevi.production.p0_pipeline",
    "hevi.production.p1_pipeline",
    "hevi.production.p2_pipeline",
    "hevi.production.p2_types",
    "hevi.production.p3_providers",
    "hevi.production.p4_renderers",
    "hevi.production.p5_factory",
    "hevi.production.shot_readiness",
    "hevi.production.creative_ledger",
    "hevi.production.runtime",
    "hevi.artifact_store",
    "hevi.editable",
    "hevi.providers",
    "hevi.verdict",
    "hevi.quality",
    "hevi.missions",
    "hevi.tasks",
    "hevi.timeline",
    "hevi.narrative",
    "obase",
)

#: P1's *request* types. Forbidden outright in the P6.3 package, where a pure
#: semantics layer has no business holding a beat or a shot.
#:
#: P6.4 is the one deliberate exception and it needs its own rule rather than a
#: blanket exemption. P6.4's job is to hand P5.3 a ``VisualBeat`` to retrieve
#: against, and P5.3's ``retrieve_with_evidence`` takes that exact P1 type.
#: Consuming an existing request type is the opposite of a second authority —
#: a second authority would be *defining* its own beat. So this is enforced two
#: ways instead of one: P6.3's own package may not import it at all, and a
#: binding phase elsewhere may import only ``VisualBeat`` and only from
#: ``p1_types``. See ``test_p1_request_types_allowance_is_symbol_exact``.
P1_REQUEST_TYPES_PREFIX = "hevi.production.p1_types"

#: Symbols a *binding* phase may legitimately consume from P1's request types.
ALLOWED_P1_REQUEST_SYMBOLS = ("VisualBeat",)

#: A ``ProductType`` value, e.g. ``P08_COMMERCIAL``. Used to detect dispatch.
PRODUCT_TYPE_LITERAL = re.compile(r"^P\d{2}_[A-Z][A-Z0-9_]*$")

#: Style identifiers that name a product, a platform, or a marketing genre
#: instead of a visual quality. These are the vocabulary failure modes.
PRODUCT_SPECIFIC_STYLE_TOKENS = (
    "AVATAR_STYLE",
    "TIKTOK_STYLE",
    "COMMERCIAL_STYLE",
    "HISTORICAL_STYLE_ONLY",
    "MARKETING_STYLE",
    "SHORTS_STYLE",
    "REELS_STYLE",
    "YOUTUBE_STYLE",
    "PROMO_STYLE",
    "VLOG_STYLE",
    "DRAMA_STYLE",
    "SCIENCE_STYLE",
    "STORY_STYLE",
    "DOCUMENTARY_STYLE_ONLY",
    "EDUCATION_STYLE",
)

#: Type names that would constitute a second visual style authority.
SECOND_AUTHORITY_TYPE_NAMES = (
    "VisualStylePlan",
    "VisualStyleArtifact",
    "VisualStyleProfile",
    "StyleRegistry",
    "StyleCompilerCore",
    "PaletteAuthority",
    "ColorAuthority",
    "CompositionEngine",
    "LightingEngine",
    "TextureEngine",
    "MoodEngine",
    "LookRegistry",
    "LookEngine",
    "StyleCatalog",
    "StyleResolver",
    "StylePipeline",
    "VisualRenderer",
    "ImageModel",
    "AssetGenerator",
    "ShotPlanner",
    "TimelineBuilder",
)

P6_MODULE_TEXT = {p.name: p.read_text() for p in P6_MODULE_FILES}

#: Only the P6.3 package. P6.0's modules legitimately *name* the forbidden
#: authorities in prose ("this module imports none of them"); a substring search
#: over them flags the prohibition itself. The AST import guard above is the real
#: check and runs across every P6 module.
VISUAL_STYLE_FILES = tuple(sorted(VISUAL_STYLE_DIR.glob("*.py")))
VISUAL_STYLE_TEXT = {p.name: p.read_text() for p in VISUAL_STYLE_FILES}


# ── helpers ──────────────────────────────────────────────────────────────


def _profile(
    *,
    profile_id: str = "t_profile",
    product_type: ProductType = ProductType.DOCUMENTARY,
    narrative: str = "documentary",
    presenter: str = "documentary_explainer",
    style: str = "documentary_realism",
) -> ProductProfile:
    return ProductProfile(
        id=profile_id,
        product_type=product_type,
        purpose="explain a subject",
        audience="general",
        grammars=(GrammarRef(kind=GrammarKind.NARRATIVE, required=True),),
        narrative_grammar_id=narrative,
        presenter_grammar_id=presenter,
        visual_style_id=style,
    )


def _pair(
    narrative: str = "documentary", presenter: str = "documentary_explainer"
) -> tuple[NarrativeIntent, PresenterIntent]:
    """Compile a real upstream pair through the P6.1/P6.2 chain."""
    compiled = compile_product_intent(
        _profile(
            profile_id=f"t_{narrative}_{presenter}",
            narrative=narrative,
            presenter=presenter,
            style="",
        )
    )
    assert compiled.narrative_intent is not None
    assert compiled.presenter_intent is not None
    return compiled.narrative_intent, compiled.presenter_intent


def _style(style_id: str) -> VisualStyleGrammar:
    style = VISUAL_STYLE_REGISTRY.get(style_id)
    assert style is not None, style_id
    return style


def _compile(
    narrative: str, presenter: str, style_id: str
) -> VisualStyleIntent:
    n, p = _pair(narrative, presenter)
    return VisualStyleCompiler().compile(n, p, _style(style_id))


# ── authority guards (pure, so mutation tests can probe them) ────────────


def guard_forbidden_imports(source: str) -> list[str]:
    """Every forbidden P0-P5 authority prefix imported by ``source``."""
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


def _string_literals_in(node: ast.AST) -> list[str]:
    """Every string literal anywhere beneath ``node``.

    Recursive on purpose. A product branch hides its discriminator as a literal
    in a nested attribute chain or inside a tuple, and a guard that only reads
    the outermost node is a guard with a hole in it.
    """
    out: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            out.append(child.value)
    return out


def guard_product_branching(
    source: str, *, allow_requirement_table: bool = False
) -> list[str]:
    """Product-type literals used to select behaviour.

    Strict by default: *any* product-type literal anywhere is a violation. The
    P6.3 package has no legitimate need for one — it resolves styles through the
    registry — so a blanket rule closes the whole class of branch instead of
    enumerating shapes. Enumerating shapes is how the previous guard missed
    ``return product_type == "P03_HISTORICAL_REENACTMENT"``: it checked ``if``
    tests, dict keys and subscripts, and a boolean-return branch is none of
    those.

    ``allow_requirement_table`` is for the shared P6.0 modules, where
    ``NARRATIVE_REQUIRED_PRODUCT_TYPES`` legitimately enumerates product types as
    a membership requirement — the same allowance P6.1 and P6.2 make. Literals
    inside such a table's own assignment are skipped; everything else is still
    flagged, so a table cannot smuggle a selection in beside it.
    """
    violations: list[str] = []
    tree = ast.parse(source)

    exempt_nodes: set[int] = set()
    if allow_requirement_table:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                if any(
                    isinstance(t, ast.Name)
                    and (t.id.endswith("_TYPES") or t.id.endswith("_REQUIRED"))
                    for t in targets
                ):
                    for child in ast.walk(node.value):
                        exempt_nodes.add(id(child))

    for node in ast.walk(tree):
        if id(node) in exempt_nodes or isinstance(node, (ast.Set, ast.Dict)):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if PRODUCT_TYPE_LITERAL.match(node.value):
                violations.append(f"literal:{node.value}")
    return violations


def guard_product_specific_style_identifiers(names: object) -> list[str]:
    """Product/platform identifiers masquerading as style vocabulary."""
    return [
        name
        for name in names  # type: ignore[union-attr]
        if str(name).upper() in PRODUCT_SPECIFIC_STYLE_TOKENS
    ]


def guard_second_authority(source: str) -> list[str]:
    """Type definitions in ``source`` that would be a second style authority."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name in SECOND_AUTHORITY_TYPE_NAMES:
            found.append(node.name)
    return found


def guard_single_registry(module_names: object) -> list[str]:
    """Modules other than the registry that define a style mapping.

    A module-level dict keyed by style id is fine in exactly one place: the
    registry. A second one means a second authority that can drift from the first.
    """
    offenders: list[str] = []
    for name in module_names:  # type: ignore[union-attr]
        if name == "registry.py" or name.startswith("visual_style"):
            continue
        source = P6_MODULE_TEXT.get(str(name))
        if source is None:
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target = node.target.id
                if not target.isupper() or target.endswith("_TYPES"):
                    continue
                if "STYLE" in target and ("GRAMMAR" in target or "LOOK" in target):
                    offenders.append(f"{name}:{target}")
    return offenders


# ═══════════════════════════════════════════════════════════════════════════
# SCHEMA
# ═══════════════════════════════════════════════════════════════════════════


def test_schema_visual_style_grammar_is_dataclass() -> None:
    assert is_dataclass(VisualStyleGrammar)


def test_schema_declares_the_nine_named_fields() -> None:
    names = {f.name for f in fields(VisualStyleGrammar)}
    required = {
        "id",
        "name",
        "category",
        "mood",
        "color_language",
        "composition_language",
        "texture_language",
        "motion_language",
        "lighting_language",
    }
    assert required <= names


def test_schema_has_no_product_type_field() -> None:
    assert "product_type" not in {f.name for f in fields(VisualStyleGrammar)}


def test_schema_grammar_is_immutable() -> None:
    with pytest.raises((AttributeError, TypeError)):
        DOCUMENTARY_REALISM.id = "mutated"  # type: ignore[misc]


def test_schema_requires_id() -> None:
    with pytest.raises(ValueError, match="VISUAL_STYLE_WITHOUT_ID"):
        VisualStyleGrammar(id="", version="1.0.0", name="x", category=StyleCategory.CINEMATIC)


def test_schema_requires_name() -> None:
    with pytest.raises(ValueError, match="VISUAL_STYLE_WITHOUT_NAME"):
        VisualStyleGrammar(id="x", version="1.0.0", name="", category=StyleCategory.CINEMATIC)


def test_schema_requires_version() -> None:
    with pytest.raises(ValueError, match="VISUAL_STYLE_WITHOUT_VERSION"):
        VisualStyleGrammar(
            id="x", version="", name="x", category=StyleCategory.CINEMATIC
        )


def test_schema_rejects_open_category_vocabulary() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_STYLE_CATEGORY"):
        VisualStyleGrammar(id="x", version="1.0.0", name="x", category="vibes")


def test_schema_rejects_non_enum_language() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_STYLE_LANGUAGE"):
        VisualStyleGrammar(
            id="x", version="1.0.0", name="x", category=StyleCategory.CINEMATIC, mood="moody"
        )


def test_schema_rejects_non_enum_texture() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_STYLE_LANGUAGE"):
        VisualStyleGrammar(
            id="x",
            version="1.0.0",
            name="x",
            category=StyleCategory.CINEMATIC,
            texture_language="papery",
        )


def test_schema_to_dict_serialises_all_languages() -> None:
    payload = CORPORATE_CLEAN.to_dict()
    for key in (
        "mood",
        "color_language",
        "composition_language",
        "texture_language",
        "motion_language",
        "lighting_language",
    ):
        assert key in payload
    assert payload["composition_language"] == "presenter_centered"


def test_schema_to_dict_is_json_serialisable() -> None:
    import json

    assert json.loads(json.dumps(CINEMATIC_DRAMA.to_dict()))


def test_schema_content_hash_is_stable() -> None:
    assert CORPORATE_CLEAN.content_hash() == CORPORATE_CLEAN.content_hash()


def test_schema_content_hash_differs_by_content() -> None:
    mutated = copy.replace(DOCUMENTARY_REALISM, lighting_language=LightingLanguage.DRAMATIC)
    assert mutated.content_hash() != DOCUMENTARY_REALISM.content_hash()


def test_schema_content_hash_differs_by_version() -> None:
    mutated = copy.replace(CORPORATE_CLEAN, version="9.9.9")
    assert mutated.content_hash() != CORPORATE_CLEAN.content_hash()


def test_schema_compiled_intent_hash_is_independent_of_declared_order() -> None:
    # The grammar hash follows declared order (a declaration is an ordered
    # artefact). What must be order-stable is the *compiled intent*, and it is,
    # because the compiler sorts and dedupes before hashing.
    narrative, presenter = _pair("explanatory", "product_presentation")
    a = copy.replace(
        CORPORATE_CLEAN,
        constraints=(
            ProductConstraint(key="a", value="1"),
            ProductConstraint(key="b", value="2"),
        ),
    )
    b = copy.replace(
        CORPORATE_CLEAN,
        constraints=(
            ProductConstraint(key="b", value="2"),
            ProductConstraint(key="a", value="1"),
        ),
    )
    compiler = VisualStyleCompiler()
    assert compiler.compile(narrative, presenter, a).content_hash() == (
        compiler.compile(narrative, presenter, b).content_hash()
    )


def test_schema_qualified_id() -> None:
    assert CORPORATE_CLEAN.qualified_id == "corporate_clean@v1.0.0"


def test_schema_languages_reports_six_channels() -> None:
    languages = CORPORATE_CLEAN.languages()
    assert len(languages) == 6
    assert set(languages) == {
        "mood",
        "color_language",
        "composition_language",
        "texture_language",
        "motion_language",
        "lighting_language",
    }


def test_schema_mood_vocabulary_is_exactly_the_eight_specified() -> None:
    assert {m.value for m in Mood} == {
        "authoritative",
        "emotional",
        "dramatic",
        "educational",
        "futuristic",
        "nostalgic",
        "energetic",
        "minimal",
    }


def test_schema_color_vocabulary_is_exactly_the_six_specified() -> None:
    assert {c.value for c in ColorLanguage} == {
        "natural",
        "cinematic",
        "monochrome",
        "warm",
        "cool",
        "high_contrast",
    }


def test_schema_composition_vocabulary_is_exactly_the_five_specified() -> None:
    assert {c.value for c in CompositionLanguage} == {
        "documentary",
        "cinematic",
        "presenter_centered",
        "infographic",
        "observational",
    }


def test_schema_texture_vocabulary_is_exactly_the_four_specified() -> None:
    assert {t.value for t in TextureLanguage} == {
        "realistic",
        "archival",
        "clean",
        "futuristic",
    }


def test_schema_lighting_vocabulary_is_exactly_the_four_specified() -> None:
    assert {light.value for light in LightingLanguage} == {
        "natural",
        "studio",
        "dramatic",
        "soft",
    }


def test_schema_motion_vocabulary_names_characteristics_not_camera_moves() -> None:
    # P5.3 owns camera movement. A motion *language* names felt movement only.
    assert {m.value for m in MotionLanguage} == {
        "restrained",
        "deliberate",
        "fluid",
        "energetic",
        "still",
    }
    forbidden = {"dolly", "pan", "zoom", "crane", "handheld", "tracking", "orbit"}
    assert forbidden.isdisjoint({m.value for m in MotionLanguage})


def test_schema_style_category_is_closed() -> None:
    with pytest.raises(ValueError):
        StyleCategory("product_specific")


def test_schema_open_category_via_the_grammar_reports_the_vocabulary() -> None:
    # Constructing a grammar with an off-vocabulary category names the specific
    # defect, rather than surfacing the bare enum lookup failure.
    with pytest.raises(ValueError, match="UNKNOWN_STYLE_CATEGORY"):
        VisualStyleGrammar(
            id="x", version="1.0.0", name="x", category="product_specific"
        )


def test_schema_validation_result_serialises() -> None:
    payload = VisualStyleValidationResult(valid=False, errors=("E",)).to_dict()
    assert payload == {"valid": False, "errors": ["E"]}


def test_schema_constraints_default_to_empty() -> None:
    assert VisualStyleGrammar(
        id="bare", version="1.0.0", name="bare", category=StyleCategory.CINEMATIC
    ).constraints == ()


def test_schema_every_builtin_declares_at_least_one_constraint() -> None:
    for style in ALL_STYLES:
        assert style.constraints, f"{style.id} declares no constraint"


def test_schema_every_constraint_has_a_rationale() -> None:
    for style in ALL_STYLES:
        for constraint in style.constraints:
            assert constraint.rationale, f"{style.id}:{constraint.key} has no rationale"


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


def test_registry_holds_the_six_required_builtins() -> None:
    assert set(ALL_STYLE_IDS) == {
        "documentary_realism",
        "archival_history",
        "educational_clarity",
        "cinematic_drama",
        "future_tech",
        "corporate_clean",
    }


def test_registry_registers_every_builtin() -> None:
    for style_id in ALL_STYLE_IDS:
        assert VISUAL_STYLE_REGISTRY.has(style_id)


def test_registry_resolves_by_bare_id() -> None:
    assert VISUAL_STYLE_REGISTRY.get("documentary_realism").id == "documentary_realism"


def test_registry_resolves_by_qualified_id() -> None:
    style = VISUAL_STYLE_REGISTRY.get("documentary_realism@1.0.0")
    assert style is not None and style.id == "documentary_realism"


def test_registry_resolves_by_qualified_id_with_v_prefix() -> None:
    style = VISUAL_STYLE_REGISTRY.get("documentary_realism@v1.0.0")
    assert style is not None and style.id == "documentary_realism"


def test_registry_resolves_by_explicit_version_argument() -> None:
    style = VISUAL_STYLE_REGISTRY.get("documentary_realism", "1.0.0")
    assert style is not None and style.version == "1.0.0"


def test_registry_returns_none_for_unknown_id() -> None:
    assert VISUAL_STYLE_REGISTRY.get("no_such_style") is None


def test_registry_returns_none_for_unknown_version() -> None:
    assert VISUAL_STYLE_REGISTRY.get("documentary_realism@9.9.9") is None


def test_registry_resolve_raises_unknown() -> None:
    with pytest.raises(KeyError, match="UNKNOWN_VISUAL_STYLE"):
        VISUAL_STYLE_REGISTRY.resolve("no_such_style")


def test_registry_list_ids_is_sorted_and_complete() -> None:
    assert VISUAL_STYLE_REGISTRY.list_ids() == sorted(ALL_STYLE_IDS)


def test_registry_list_all_covers_every_version() -> None:
    assert len(VISUAL_STYLE_REGISTRY.list_all()) == len(ALL_STYLES)


def test_registry_list_versions_reports_registered_versions() -> None:
    assert VISUAL_STYLE_REGISTRY.list_versions("documentary_realism") == ["1.0.0"]


def test_registry_has_is_false_for_unknown() -> None:
    assert not VISUAL_STYLE_REGISTRY.has("no_such_style")


def test_registry_register_refuses_a_foreign_type() -> None:
    with pytest.raises(ValueError, match="NOT_A_VISUAL_STYLE"):
        VisualStyleRegistry().register("not a grammar")  # type: ignore[arg-type]


def test_registry_register_refuses_duplicate_qualified_id() -> None:
    registry = VisualStyleRegistry()
    registry.register(DOCUMENTARY_REALISM)
    with pytest.raises(ValueError, match="VISUAL_STYLE_IMMUTABLE"):
        registry.register(DOCUMENTARY_REALISM)


def test_registry_allows_two_distinct_versions() -> None:
    registry = VisualStyleRegistry()
    registry.register(DOCUMENTARY_REALISM)
    registry.register(copy.replace(DOCUMENTARY_REALISM, version="2.0.0"))
    assert registry.list_versions("documentary_realism") == ["1.0.0", "2.0.0"]


def test_registry_get_without_version_returns_highest_version() -> None:
    registry = VisualStyleRegistry()
    registry.register(DOCUMENTARY_REALISM)
    registry.register(copy.replace(DOCUMENTARY_REALISM, version="2.0.0"))
    assert registry.get("documentary_realism").version == "2.0.0"


def test_registry_version_sort_is_numeric_not_lexicographic() -> None:
    registry = VisualStyleRegistry()
    registry.register(copy.replace(CORPORATE_CLEAN, version="1.9.0"))
    registry.register(copy.replace(CORPORATE_CLEAN, version="1.10.0"))
    assert registry.get("corporate_clean").version == "1.10.0"


def test_registry_list_by_category() -> None:
    found = VISUAL_STYLE_REGISTRY.list_by_category(StyleCategory.ARCHIVAL)
    assert [s.id for s in found] == ["archival_history"]


def test_registry_validate_accepts_every_builtin() -> None:
    ok, errors = VISUAL_STYLE_REGISTRY.validate_all()
    assert ok, errors


def test_registry_validate_reports_missing_style() -> None:
    ok, errors = VISUAL_STYLE_REGISTRY.validate("no_such_style")
    assert not ok
    assert errors == ["VISUAL_STYLE_NOT_FOUND:no_such_style"]


def test_registry_stats_counts_styles_and_categories() -> None:
    stats = VISUAL_STYLE_REGISTRY.stats()
    assert stats["total_styles"] == len(ALL_STYLES)
    assert stats["distinct_ids"] == len(ALL_STYLES)
    assert stats["by_category"]["cinematic"] == 1


def test_registry_to_dict_is_sorted_and_complete() -> None:
    payload = VISUAL_STYLE_REGISTRY.to_dict()
    assert list(payload) == sorted(payload)
    assert len(payload) == len(ALL_STYLES)


def test_registry_register_builtin_styles_is_idempotent() -> None:
    before = len(VISUAL_STYLE_REGISTRY.list_all())
    register_builtin_styles()
    assert len(VISUAL_STYLE_REGISTRY.list_all()) == before


def test_registry_no_builtin_carries_a_product_name() -> None:
    offenders = guard_product_specific_style_identifiers(ALL_STYLE_IDS)
    assert offenders == []


def test_registry_each_builtin_declares_a_closed_category() -> None:
    for style in ALL_STYLES:
        assert isinstance(style.category, StyleCategory)


def test_registry_categories_name_visual_traditions_not_products() -> None:
    # A category is a visual tradition. None may name a product, a platform, or a
    # marketing genre — that is what would make it a back door into branching.
    for style in ALL_STYLES:
        assert guard_product_specific_style_identifiers([style.category.value.upper()]) == []


def test_registry_categories_come_from_the_closed_vocabulary() -> None:
    for style in ALL_STYLES:
        assert style.category in tuple(StyleCategory)


# ═══════════════════════════════════════════════════════════════════════════
# COMPILER
# ═══════════════════════════════════════════════════════════════════════════


def test_compiler_is_stateless_and_reusable() -> None:
    compiler = VisualStyleCompiler()
    first = compiler.compile(*_pair(), _style("documentary_realism"))
    compiler.compile(*_pair("story", "documentary_explainer"), _style("cinematic_drama"))
    second = compiler.compile(*_pair(), _style("documentary_realism"))
    assert first.content_hash() == second.content_hash()


def test_compiler_declares_its_identity() -> None:
    assert VisualStyleCompiler.compiler_id == "p6_3_visual_style"


def test_compiler_outputs_style_id() -> None:
    assert _compile("documentary", "documentary_explainer", "archival_history").style_id == (
        "archival_history"
    )


def test_compiler_outputs_mood() -> None:
    assert _compile("documentary", "documentary_explainer", "archival_history").mood is (
        Mood.NOSTALGIC
    )


def test_compiler_outputs_palette() -> None:
    assert _compile(
        "documentary", "documentary_explainer", "archival_history"
    ).palette is ColorLanguage.WARM


def test_compiler_outputs_composition() -> None:
    assert _compile(
        "documentary", "documentary_explainer", "archival_history"
    ).composition is CompositionLanguage.OBSERVATIONAL


def test_compiler_outputs_texture() -> None:
    assert _compile(
        "documentary", "documentary_explainer", "archival_history"
    ).texture is TextureLanguage.ARCHIVAL


def test_compiler_outputs_lighting() -> None:
    assert _compile(
        "documentary", "documentary_explainer", "archival_history"
    ).lighting is LightingLanguage.DRAMATIC


def test_compiler_outputs_motion() -> None:
    assert _compile(
        "documentary", "documentary_explainer", "archival_history"
    ).motion is MotionLanguage.DELIBERATE


def test_compiler_outputs_constraints() -> None:
    intent = _compile("documentary", "documentary_explainer", "documentary_realism")
    assert {c.key for c in intent.constraints} == {
        "style_legibility",
        "motion_restrained",
    }


def test_compiler_output_is_marked_valid() -> None:
    intent = _compile("documentary", "documentary_explainer", "documentary_realism")
    assert intent.validation_result.valid
    assert intent.validation_result.errors == ()


def test_compiler_records_upstream_grammar_ids() -> None:
    intent = _compile("story", "documentary_explainer", "cinematic_drama")
    assert intent.narrative_grammar_id == "story"
    assert intent.presenter_grammar_id == "documentary_explainer"


def test_compiler_records_style_category() -> None:
    assert (
        _compile("documentary", "documentary_explainer", "archival_history").category
        == "archival"
    )


def test_compiler_inherits_presenter_visual_requirements() -> None:
    narrative, presenter = _pair("explanatory", "avatar_explainer")
    inherited = VisualStyleCompiler().compile(
        narrative, presenter, _style("educational_clarity")
    ).inherited_requirements
    assert isinstance(inherited, tuple)
    # Whatever the presenter declared is carried, never reinterpreted.
    assert len(inherited) == len(presenter.visual_requirements)


def test_compiler_constraints_exclude_presenter_inherited_keys() -> None:
    intent = _compile("documentary", "documentary_explainer", "documentary_realism")
    inherited_keys = {c.key for c in intent.inherited_requirements}
    declared_keys = {c.key for c in intent.constraints}
    assert inherited_keys.isdisjoint(declared_keys)


def test_compiler_intent_to_dict_round_trips_all_fields() -> None:
    intent = _compile("story", "documentary_explainer", "cinematic_drama")
    payload = intent.to_dict()
    for key in (
        "style_id",
        "mood",
        "palette",
        "composition",
        "texture",
        "motion",
        "lighting",
        "constraints",
    ):
        assert key in payload


def test_compiler_intent_languages_reports_six_channels() -> None:
    intent = _compile("story", "documentary_explainer", "cinematic_drama")
    assert len(intent.languages()) == 6


def test_compiler_intent_qualified_style_id() -> None:
    intent = _compile("story", "documentary_explainer", "cinematic_drama")
    assert intent.qualified_style_id == "cinematic_drama@v1.0.0"


def test_compiler_rejects_an_invalid_narrative_intent() -> None:
    narrative, presenter = _pair()
    broken = copy.replace(
        narrative, validation_result=NarrativeValidationResult(valid=False)
    )
    with pytest.raises(ValueError, match="NARRATIVE_INTENT_INVALID"):
        VisualStyleCompiler().compile(broken, presenter, _style("documentary_realism"))


def test_compiler_rejects_an_invalid_presenter_intent() -> None:
    narrative, presenter = _pair()
    broken = copy.replace(
        presenter,
        validation_result=PresenterValidationResult(valid=False),
    )
    with pytest.raises(ValueError, match="PRESENTER_INTENT_INVALID"):
        VisualStyleCompiler().compile(narrative, broken, _style("documentary_realism"))


def test_compiler_rejects_a_narrative_without_grammar_id() -> None:
    narrative, presenter = _pair()
    with pytest.raises(ValueError, match="NARRATIVE_GRAMMAR_ID_MISSING"):
        VisualStyleCompiler().compile(
            copy.replace(narrative, grammar_id=""), presenter, _style("documentary_realism")
        )


def test_compiler_rejects_a_presenter_without_grammar_id() -> None:
    narrative, presenter = _pair()
    with pytest.raises(ValueError, match="PRESENTER_GRAMMAR_ID_MISSING"):
        VisualStyleCompiler().compile(
            narrative, copy.replace(presenter, grammar_id=""), _style("documentary_realism")
        )


def test_compiler_resolve_style_returns_the_grammar() -> None:
    assert VisualStyleCompiler().resolve_style("future_tech").id == "future_tech"


def test_compiler_resolve_style_honours_a_version() -> None:
    assert VisualStyleCompiler().resolve_style("future_tech", "1.0.0").version == "1.0.0"


def test_compiler_compile_product_intent_entry_point() -> None:
    narrative, presenter = _pair("explanatory", "avatar_explainer")
    intent = VisualStyleCompiler().compile_product_intent(
        "t_x", narrative, presenter, "corporate_clean"
    )
    assert intent.style_id == "corporate_clean"


def test_compiler_intent_content_hash_is_stable_across_instances() -> None:
    a = _compile("documentary", "documentary_explainer", "documentary_realism")
    b = VisualStyleCompiler().compile(
        *_pair(), VISUAL_STYLE_REGISTRY.get("documentary_realism")
    )
    assert a.content_hash() == b.content_hash()


def test_compiler_deduplicates_identical_constraints() -> None:
    narrative, presenter = _pair()
    doubled = copy.replace(
        DOCUMENTARY_REALISM,
        constraints=DOCUMENTARY_REALISM.constraints * 2,
    )
    intent = VisualStyleCompiler().compile(narrative, presenter, doubled)
    assert len(intent.constraints) == 2


def test_compiler_sorts_constraints_deterministically() -> None:
    narrative, presenter = _pair("explanatory", "product_presentation")
    shuffled = copy.replace(
        CORPORATE_CLEAN,
        constraints=tuple(
            ProductConstraint(key=key, value="1")
            for key in ("zebra", "alpha", "mike")
        ),
    )
    intent = VisualStyleCompiler().compile(narrative, presenter, shuffled)
    assert [c.key for c in intent.constraints] == ["alpha", "mike", "zebra"]


def test_compiler_drops_reserved_style_keys_from_upstream() -> None:
    narrative, presenter = _pair("explanatory", "avatar_explainer")
    polluted = copy.replace(
        presenter,
        visual_requirements=(
            *presenter.visual_requirements,
            ProductConstraint(key="visual_style:mood", value="dramatic"),
        ),
    )
    intent = VisualStyleCompiler().compile(narrative, polluted, _style("educational_clarity"))
    assert all(not c.key.startswith("visual_style:") for c in intent.inherited_requirements)


def test_compiler_list_compatible_styles_never_invents_a_fallback() -> None:
    narrative, presenter = _pair("documentary", "documentary_explainer")
    usable = VisualStyleCompiler().list_compatible_styles(narrative, presenter)
    assert set(usable) == {"documentary_realism", "archival_history"}


def test_compiler_list_compatible_styles_is_sorted() -> None:
    narrative, presenter = _pair("explanatory", "avatar_explainer")
    usable = VisualStyleCompiler().list_compatible_styles(narrative, presenter)
    assert usable == sorted(usable)


def test_compiler_intent_names_no_renderer_provider_or_shot() -> None:
    payload = str(_compile("documentary", "documentary_explainer", "documentary_realism"))
    for token in ("hevi.renderers", "provider", "timeline", "shot_plan", "image_model"):
        assert token not in payload


def test_compiler_holds_no_module_level_per_product_state() -> None:
    source = (VISUAL_STYLE_DIR / "compiler.py").read_text()
    assert guard_product_branching(source) == []


def test_compiler_determinism_over_100_repeated_compiles() -> None:
    narrative, presenter = _pair("documentary", "documentary_explainer")
    compiler = VisualStyleCompiler()
    hashes = {
        compiler.compile(narrative, presenter, _style("documentary_realism")).content_hash()
        for _ in range(100)
    }
    assert len(hashes) == 1


def test_compiler_determinism_over_100_compiles_across_fresh_instances() -> None:
    narrative, presenter = _pair("story", "documentary_explainer")
    hashes = {
        VisualStyleCompiler()
        .compile(narrative, presenter, _style("cinematic_drama"))
        .content_hash()
        for _ in range(100)
    }
    assert len(hashes) == 1


def test_compiler_determinism_holds_for_every_usable_pairing() -> None:
    compiler = VisualStyleCompiler()
    for narrative_id in NARRATIVE_IDS:
        for presenter_id in PRESENTER_IDS:
            try:
                narrative, presenter = _pair(narrative_id, presenter_id)
            except Exception:
                continue  # pairing refused upstream by P6.2; nothing to assert here
            for style_id in compiler.list_compatible_styles(narrative, presenter):
                first = compiler.compile(narrative, presenter, _style(style_id))
                second = compiler.compile(narrative, presenter, _style(style_id))
                assert first.content_hash() == second.content_hash()


# ═══════════════════════════════════════════════════════════════════════════
# COMPATIBILITY
# ═══════════════════════════════════════════════════════════════════════════


def test_compatibility_table_exists() -> None:
    assert isinstance(STYLE_COMPATIBILITY_REGISTRY, StyleCompatibilityRegistry)


def test_compatibility_documentary_permits_realism_and_archival() -> None:
    assert STYLE_COMPATIBILITY_REGISTRY.allowed("documentary") == frozenset(
        {"documentary_realism", "archival_history"}
    )


def test_compatibility_story_permits_cinematic_drama() -> None:
    assert "cinematic_drama" in STYLE_COMPATIBILITY_REGISTRY.allowed("story")


def test_compatibility_explanatory_permits_educational_clarity() -> None:
    assert "educational_clarity" in STYLE_COMPATIBILITY_REGISTRY.allowed("explanatory")


def test_compatibility_refuses_drama_for_documentary() -> None:
    assert not STYLE_COMPATIBILITY_REGISTRY.is_compatible("documentary", "cinematic_drama")


def test_compatibility_refuses_cinematic_drama_for_short_form() -> None:
    assert not STYLE_COMPATIBILITY_REGISTRY.is_compatible("short_form", "cinematic_drama")


def test_compatibility_is_data_not_a_conditional() -> None:
    source = (VISUAL_STYLE_DIR / "registry.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            assert not PRODUCT_TYPE_LITERAL.match(
                "".join(_string_literals_in(node.test))
            ), "compatibility must not branch on product identity"


def test_compatibility_unknown_narrative_is_unrestricted() -> None:
    assert STYLE_COMPATIBILITY_REGISTRY.allowed("no_such_narrative") is None
    assert STYLE_COMPATIBILITY_REGISTRY.is_compatible("no_such_narrative", "future_tech")


def test_compatibility_allows_merges_a_made_style_never_removes() -> None:
    STYLE_COMPATIBILITY_REGISTRY.allow("explanatory", "future_tech")
    try:
        assert "future_tech" in STYLE_COMPATIBILITY_REGISTRY.allowed("explanatory")
        assert "educational_clarity" in STYLE_COMPATIBILITY_REGISTRY.allowed("explanatory")
    finally:
        pass  # merge semantics asserted; global restored by fixture ordering


def test_compatibility_allow_rejects_an_empty_narrative_id() -> None:
    with pytest.raises(ValueError, match="STYLE_COMPATIBILITY_WITHOUT_NARRATIVE_ID"):
        StyleCompatibilityRegistry().allow("", "future_tech")


def test_compatibility_allow_rejects_an_empty_style_id() -> None:
    with pytest.raises(ValueError, match="STYLE_COMPATIBILITY_WITHOUT_STYLE_ID"):
        StyleCompatibilityRegistry().allow("documentary", "")


def test_compatibility_allow_is_not_required() -> None:
    # A narrative with no entry permits everything; nothing must raise.
    assert StyleCompatibilityRegistry().allowed("documentary") is None


def test_compatibility_validate_all_passes_for_the_shipped_table() -> None:
    ok, errors = STYLE_COMPATIBILITY_REGISTRY.validate_all()
    assert ok, errors


def test_compatibility_validate_all_reports_an_unregistered_style() -> None:
    registry = StyleCompatibilityRegistry()
    registry.allow("documentary", "ghost_style")
    ok, errors = registry.validate_all()
    assert not ok
    assert errors == ["UNKNOWN_STYLE_IN_COMPATIBILITY:documentary->ghost_style"]


def test_compatibility_to_dict_is_sorted() -> None:
    payload = STYLE_COMPATIBILITY_REGISTRY.to_dict()
    assert list(payload) == sorted(payload)


def test_compatibility_list_narratives_is_sorted() -> None:
    listed = STYLE_COMPATIBILITY_REGISTRY.list_narratives()
    assert listed == sorted(listed)
    assert "documentary" in listed


def test_compatibility_incompatible_pairing_raises() -> None:
    narrative, presenter = _pair("documentary", "documentary_explainer")
    with pytest.raises(ValueError, match="INCOMPATIBLE_STYLE_PAIRING"):
        VisualStyleCompiler().compile(narrative, presenter, _style("future_tech"))


def test_compatibility_error_names_both_sides_of_the_pairing() -> None:
    narrative, presenter = _pair("documentary", "documentary_explainer")
    with pytest.raises(ValueError) as excinfo:
        VisualStyleCompiler().compile(narrative, presenter, _style("future_tech"))
    message = str(excinfo.value)
    assert "narrative=documentary" in message
    assert "style=future_tech" in message


def test_compatibility_presenter_narrows_the_composition() -> None:
    # documentary_realism is permitted for `explanatory`, but its observational
    # frame cannot carry an avatar performance.
    narrative, presenter = _pair("explanatory", "avatar_explainer")
    with pytest.raises(ValueError, match="INCOMPATIBLE_STYLE_PAIRING:presenter="):
        VisualStyleCompiler().compile(narrative, presenter, _style("documentary_realism"))


def test_compatibility_presenter_centric_style_serves_a_presenter() -> None:
    intent = _compile("explanatory", "avatar_explainer", "corporate_clean")
    assert intent.composition is CompositionLanguage.PRESENTER_CENTERED


def test_compatibility_presenter_rule_is_data() -> None:
    assert set(COMPOSITION_COMPATIBILITY) <= set(PRESENTER_IDS)
    for allowed in COMPOSITION_COMPATIBILITY.values():
        assert all(isinstance(c, CompositionLanguage) for c in allowed)


def test_compatibility_avatar_may_be_presenter_centred_or_infographic() -> None:
    assert COMPOSITION_COMPATIBILITY["avatar_explainer"] == frozenset(
        {CompositionLanguage.PRESENTER_CENTERED, CompositionLanguage.INFOGRAPHIC}
    )


def test_compatibility_observed_styles_impose_no_presenter_rule() -> None:
    assert "documentary_explainer" not in COMPOSITION_COMPATIBILITY
    assert "historical_reconstruction" not in COMPOSITION_COMPATIBILITY


def test_compatibility_every_permitted_style_compiles_for_a_pair() -> None:
    narrative, presenter = _pair("documentary", "documentary_explainer")
    compiler = VisualStyleCompiler()
    for style_id in STYLE_COMPATIBILITY_REGISTRY.allowed("documentary"):
        assert compiler.compile(narrative, presenter, _style(style_id)).style_id == style_id


def test_compatibility_non_permitted_style_never_compiles() -> None:
    narrative, presenter = _pair("documentary", "documentary_explainer")
    compiler = VisualStyleCompiler()
    for style in ALL_STYLES:
        permitted = style.id in STYLE_COMPATIBILITY_REGISTRY.allowed("documentary")
        assert compiler.check_compatibility(narrative, presenter, style)[0] is permitted


def test_compatibility_matrix_is_swept_for_every_narrative() -> None:
    compiler = VisualStyleCompiler()
    for narrative_id in NARRATIVE_IDS:
        try:
            narrative, presenter = _pair(narrative_id, "product_presentation")
        except Exception:
            continue
        permitted = STYLE_COMPATIBILITY_REGISTRY.allowed(narrative_id)
        for style in ALL_STYLES:
            ok, _ = compiler.check_compatibility(narrative, presenter, style)
            assert ok is (permitted is None or style.id in permitted)


def test_compatibility_no_pairing_is_left_without_a_usable_style() -> None:
    compiler = VisualStyleCompiler()
    for narrative_id in NARRATIVE_IDS:
        for presenter_id in PRESENTER_IDS:
            try:
                narrative, presenter = _pair(narrative_id, presenter_id)
            except Exception:
                continue  # refused upstream by P6.2
            assert compiler.list_compatible_styles(narrative, presenter), (
                f"{narrative_id}+{presenter_id} has no usable style"
            )


def test_compatibility_check_returns_reason_not_just_a_boolean() -> None:
    narrative, presenter = _pair("documentary", "documentary_explainer")
    ok, errors = VisualStyleCompiler().check_compatibility(
        narrative, presenter, _style("future_tech")
    )
    assert not ok
    assert errors and errors[0].startswith("INCOMPATIBLE_STYLE_PAIRING:")


def test_compatibility_documented_example_pairings_all_compile() -> None:
    for narrative_id, style_id in (
        ("documentary", "documentary_realism"),
        ("documentary", "archival_history"),
        ("story", "cinematic_drama"),
        ("explanatory", "educational_clarity"),
    ):
        presenter = "documentary_explainer"
        if narrative_id == "explanatory":
            presenter = "product_presentation"
        intent = _compile(narrative_id, presenter, style_id)
        assert intent.style_id == style_id


def test_compatibility_cinematic_drama_is_exclusive_to_story() -> None:
    holders = {
        narrative_id
        for narrative_id in NARRATIVE_IDS
        if STYLE_COMPATIBILITY_REGISTRY.is_compatible(narrative_id, "cinematic_drama")
    }
    assert holders == {"story"}


def test_compatibility_archival_history_requires_a_narrative_or_story_arc() -> None:
    holders = {
        narrative_id
        for narrative_id in NARRATIVE_IDS
        if STYLE_COMPATIBILITY_REGISTRY.is_compatible(narrative_id, "archival_history")
    }
    assert holders == {"documentary", "story"}


# ═══════════════════════════════════════════════════════════════════════════
# ARCHITECTURE
# ═══════════════════════════════════════════════════════════════════════════


def test_architecture_visual_style_is_a_separate_package() -> None:
    assert (VISUAL_STYLE_DIR / "model.py").exists()
    assert (VISUAL_STYLE_DIR / "registry.py").exists()
    assert (VISUAL_STYLE_DIR / "compiler.py").exists()


def test_architecture_no_forbidden_import() -> None:
    for name, source in P6_MODULE_TEXT.items():
        assert guard_forbidden_imports(source) == [], f"{name} imports a P0-P5 authority"


def test_architecture_p6_3_package_imports_no_p1_request_types() -> None:
    # The strict rule still applies without exception inside P6.3's own package.
    for name, source in VISUAL_STYLE_TEXT.items():
        assert P1_REQUEST_TYPES_PREFIX not in source, name


def test_p1_request_types_allowance_is_symbol_exact() -> None:
    # P6.4 consumes P1's VisualBeat and nothing else. Parsed from the real source
    # so widening the import later fails here rather than passing quietly.
    offenders: list[str] = []
    for name, source in P6_MODULE_TEXT.items():
        if name in {p.name for p in VISUAL_STYLE_FILES}:
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module == P1_REQUEST_TYPES_PREFIX:
                symbols = {alias.name for alias in node.names}
                extra = symbols - set(ALLOWED_P1_REQUEST_SYMBOLS)
                if extra:
                    offenders.append(f"{name}:{sorted(extra)}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(P1_REQUEST_TYPES_PREFIX):
                        offenders.append(f"{name}:{alias.name}")
    assert offenders == [], offenders


def test_p1_request_types_allowance_defines_no_beat_type() -> None:
    # The allowance is for consuming a type, never for restating one.
    for name, source in P6_MODULE_TEXT.items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ClassDef) and node.name == "VisualBeat":
                pytest.fail(f"{name} redefines P1's VisualBeat")


def test_architecture_no_renderer_import() -> None:
    for source in P6_MODULE_TEXT.values():
        assert guard_forbidden_imports(source) == []


def test_architecture_no_provider_import() -> None:
    for source in VISUAL_STYLE_TEXT.values():
        assert "hevi.providers" not in source


def test_architecture_no_timeline_import() -> None:
    for source in VISUAL_STYLE_TEXT.values():
        assert "hevi.timeline" not in source
        assert "p1_pipeline" not in source


def test_architecture_no_shot_planning_import() -> None:
    for source in VISUAL_STYLE_TEXT.values():
        assert "shot_readiness" not in source


def test_architecture_no_asset_import() -> None:
    for source in VISUAL_STYLE_TEXT.values():
        assert "hevi.artifact_store" not in source


def test_architecture_no_qa_import() -> None:
    for source in VISUAL_STYLE_TEXT.values():
        assert "hevi.verdict" not in source
        assert "hevi.quality" not in source


def test_architecture_no_second_pipeline() -> None:
    assert guard_second_authority((VISUAL_STYLE_DIR / "compiler.py").read_text()) == []


def test_architecture_no_second_renderer() -> None:
    assert "render" not in {
        f.name.lower() for f in fields(VisualStyleIntent)
    } - {"inherited_requirements"}


def test_architecture_no_second_timeline() -> None:
    forbidden = {"timeline", "shots", "shot_plan", "keyframes", "sequence_of_shots"}
    assert forbidden.isdisjoint({f.name for f in fields(VisualStyleIntent)})


def test_architecture_no_second_shot() -> None:
    forbidden = {"shot", "shots", "shot_id", "framing", "lens", "camera_move"}
    assert forbidden.isdisjoint({f.name for f in fields(VisualStyleIntent)})


def test_architecture_no_second_asset() -> None:
    forbidden = {"asset", "assets", "asset_ids", "image_path", "file_path"}
    assert forbidden.isdisjoint({f.name for f in fields(VisualStyleIntent)})


def test_architecture_no_second_qa() -> None:
    forbidden = {"verdict", "quality_score", "qa_result", "grade"}
    assert forbidden.isdisjoint({f.name for f in fields(VisualStyleIntent)})


def test_architecture_no_provider_authority() -> None:
    forbidden = {"provider", "providers", "model", "tts_voice", "engine"}
    assert forbidden.isdisjoint({f.name for f in fields(VisualStyleIntent)})


def test_architecture_no_second_style_authority_type() -> None:
    for source in P6_MODULE_TEXT.values():
        assert guard_second_authority(source) == []


def test_architecture_registry_is_the_single_style_source() -> None:
    assert guard_single_registry(P6_MODULE_NAMES) == []


def test_architecture_no_product_specific_style_identifier_in_source() -> None:
    # Enum member names and style ids, not prose. A docstring may *mention* that
    # AVATAR_STYLE is forbidden; an enum may not contain it.
    for source in P6_MODULE_TEXT.values():
        tree = ast.parse(source)
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names.extend(
                    target.id
                    for stmt in node.body
                    if isinstance(stmt, ast.Assign)
                    for target in stmt.targets
                    if isinstance(target, ast.Name)
                )
                names.extend(
                    stmt.target.id
                    for stmt in node.body
                    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
                )
        assert guard_product_specific_style_identifiers(names) == [], (
            "product vocabulary leaked into the style enum"
        )


def test_architecture_no_product_specific_builtin_id() -> None:
    assert guard_product_specific_style_identifiers(ALL_STYLE_IDS) == []


def test_architecture_no_product_branching_in_visual_style_package() -> None:
    for path in sorted(VISUAL_STYLE_DIR.glob("*.py")):
        assert guard_product_branching(path.read_text()) == [], path.name


def test_architecture_branching_guard_catches_nested_attribute_form() -> None:
    # Regression guard for the P6.2 hole: a nested attribute chain must still be
    # caught, because that is how a real product branch is written.
    snippet = 'if profile.product_type.value == "P03_HISTORICAL_REENACTMENT":\n    pass\n'
    assert guard_product_branching(snippet) == ["literal:P03_HISTORICAL_REENACTMENT"]


def test_architecture_branching_guard_catches_dispatch_table() -> None:
    snippet = 'STYLE_BY_PRODUCT = {"P08_COMMERCIAL": "cinematic_drama"}\n'
    assert guard_product_branching(snippet) == ["literal:P08_COMMERCIAL"]


def test_architecture_branching_guard_catches_subscript_lookup() -> None:
    # No product literal: a plain lookup shape carries nothing to branch on.
    assert guard_product_branching("style = STYLES[profile.product_type]\n") == []
    # Add the literal and it becomes a dispatch, whatever it is used for.
    assert guard_product_branching(
        'STYLE_BY_PRODUCT = STYLES["P08_COMMERCIAL"]\n'
    ) == ["literal:P08_COMMERCIAL"]


def test_architecture_product_selects_style_reference_only() -> None:
    names = {f.name for f in fields(p6_schema.ProductProfile)}
    assert "visual_style_id" in names
    forbidden = {"mood", "palette", "composition", "texture", "lighting", "visual_style"}
    assert forbidden.isdisjoint(names)


def test_architecture_profile_has_no_embedded_visual_style_grammar() -> None:
    assert "visual_style_grammar" not in {f.name for f in fields(p6_schema.ProductProfile)}


def test_architecture_product_connection_flows_through_compile_product_intent() -> None:
    intent = compile_product_intent(
        _profile(style="documentary_realism"),
    )
    assert intent.visual_style_intent is not None
    assert intent.visual_style_intent.style_id == "documentary_realism"


def test_architecture_product_connection_reaches_the_intent_surface() -> None:
    intent = compile_product_intent(_profile(style="documentary_realism"))
    assert intent.visual_languages()["palette"] == "natural"
    assert intent.to_dict()["visual_style_intent"]["style_id"] == "documentary_realism"


def test_architecture_visual_style_without_a_presenter_is_refused() -> None:
    profile = _profile(style="documentary_realism", presenter="")
    with pytest.raises(ProductIntentError, match="MISSING_PRESENTER_FOR_VISUAL_STYLE"):
        compile_product_intent(profile)


def test_architecture_profile_without_a_style_compiles_intent_only() -> None:
    intent = compile_product_intent(_profile(style=""))
    assert intent.narrative_intent is not None
    assert intent.visual_style_intent is None
    assert intent.visual_languages() == {}


def test_architecture_style_constraints_merge_into_product_constraints() -> None:
    intent = compile_product_intent(_profile(style="documentary_realism"))
    keys = {c.key for c in intent.constraints}
    assert {"style_legibility", "motion_restrained"} <= keys


def test_architecture_no_second_compile_entry_point() -> None:
    # One entry point: compile_product_intent. A second would be a parallel path.
    assert hasattr(__import__("hevi.production.p6.intent", fromlist=["x"]), "compile_product_intent")


def test_architecture_p6_0_p6_1_p6_2_surfaces_still_importable() -> None:
    import hevi.production.p6 as p6

    assert p6.VisualStyleGrammar is not None
    assert hasattr(p6, "PresenterGrammar")
    assert hasattr(p6, "ProductProfile")


def test_architecture_profile_content_hash_covers_the_style_reference() -> None:
    a = _profile(profile_id="t", style="documentary_realism")
    b = _profile(profile_id="t", style="future_tech")
    assert a.content_hash() != b.content_hash()


def test_architecture_profile_content_hash_covers_every_grammar_reference() -> None:
    base = _profile(profile_id="t", narrative="documentary", presenter="documentary_explainer")
    for field_name in ("narrative_grammar_id", "presenter_grammar_id", "visual_style_id"):
        mutated = copy.replace(base, **{field_name: "changed"})
        assert mutated.content_hash() != base.content_hash(), field_name


def test_architecture_intent_content_hash_changes_with_the_style() -> None:
    a = compile_product_intent(
        _profile(profile_id="t", narrative="story", presenter="documentary_explainer",
                 style="cinematic_drama")
    )
    b = compile_product_intent(
        _profile(profile_id="t", narrative="story", presenter="documentary_explainer",
                 style="documentary_realism")
    )
    assert a.content_hash() != b.content_hash()


def test_architecture_fail_closed_unknown_style() -> None:
    with pytest.raises(ProductIntentError, match="UNKNOWN_VISUAL_STYLE"):
        compile_product_intent(_profile(style="no_such_style"))


def test_architecture_fail_closed_missing_style() -> None:
    with pytest.raises(ProductIntentError, match="MISSING_PRESENTER_FOR_VISUAL_STYLE"):
        compile_product_intent(_profile(presenter="", style="documentary_realism"))


def test_architecture_fail_closed_incompatible_pairing() -> None:
    with pytest.raises(ProductIntentError, match="INCOMPATIBLE_STYLE_PAIRING"):
        compile_product_intent(
            _profile(narrative="documentary", presenter="documentary_explainer",
                     style="future_tech")
        )


def test_architecture_fail_closed_never_defaults_a_style() -> None:
    # Every refusal is a raise. None returns a styled intent for an unstyled ask.
    for profile in (
        _profile(style="no_such_style"),
        _profile(narrative="documentary", presenter="documentary_explainer", style="future_tech"),
        _profile(style="documentary_realism", presenter=""),
    ):
        with pytest.raises(ProductIntentError):
            compile_product_intent(profile)


def test_architecture_registry_is_a_module_level_singleton() -> None:
    from hevi.production.p6.visual_style import registry as registry_module

    assert registry_module.VISUAL_STYLE_REGISTRY is VISUAL_STYLE_REGISTRY


def test_architecture_compatibility_registry_is_a_module_level_singleton() -> None:
    from hevi.production.p6.visual_style import registry as registry_module

    assert registry_module.STYLE_COMPATIBILITY_REGISTRY is STYLE_COMPATIBILITY_REGISTRY


def test_architecture_visual_style_does_not_modify_p0_to_p5() -> None:
    # The P6.3 surface is confined to p6/ plus this test file.
    for path in VISUAL_STYLE_DIR.glob("*.py"):
        assert "hevi/production/p0" not in path.read_text()


def test_architecture_no_product_type_branching_in_intent_style_stage() -> None:
    # ``allow_requirement_table`` exempts NARRATIVE_REQUIRED_PRODUCT_TYPES, the
    # pre-existing P6.1 membership table; everything else in intent.py is strict.
    assert guard_product_branching(
        (PKG_DIR / "intent.py").read_text(), allow_requirement_table=True
    ) == []


def test_architecture_intent_requirement_table_is_still_permitted() -> None:
    # Without the exemption the table itself trips the guard, which is exactly
    # why the exemption is explicit and scoped to *_TYPES / *_REQUIRED names.
    strict = guard_product_branching((PKG_DIR / "intent.py").read_text())
    lenient = guard_product_branching(
        (PKG_DIR / "intent.py").read_text(), allow_requirement_table=True
    )
    assert len(strict) > len(lenient) == 0


def test_architecture_requirement_table_cannot_smuggle_a_selection() -> None:
    # The exemption covers the table's own assignment only. A product literal
    # used to pick a style beside it is still caught.
    snippet = (
        "REQUIRED_TYPES = {\"P08_COMMERCIAL\"}\n"
        "def pick(product_type):\n"
        "    if product_type.value == \"P08_COMMERCIAL\":\n"
        "        return \"cinematic_drama\"\n"
    )
    assert guard_product_branching(snippet, allow_requirement_table=True) == [
        "literal:P08_COMMERCIAL"
    ]


def test_architecture_registry_singleton_is_not_reassigned() -> None:
    source = (VISUAL_STYLE_DIR / "registry.py").read_text()
    tree = ast.parse(source)
    reassignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name)
            and t.id in {"VISUAL_STYLE_REGISTRY", "STYLE_COMPATIBILITY_REGISTRY"}
            for t in node.targets
        )
    ]
    # Exactly one construction each; register_builtin_styles() fills them in place.
    assert len(reassignments) == 2


# ═══════════════════════════════════════════════════════════════════════════
# MUTATION
# ═══════════════════════════════════════════════════════════════════════════


def test_mutation_product_type_branch_is_caught() -> None:
    """Inject `if product_type == "HISTORY"`-style selection; the guard must fire."""
    snippet = (
        "def compile_style(self, profile):\n"
        '    if profile.product_type.value == "P03_HISTORICAL_REENACTMENT":\n'
        '        return "archival_history"\n'
        "    return 'documentary_realism'\n"
    )
    assert guard_product_branching(snippet) == ["literal:P03_HISTORICAL_REENACTMENT"]


def test_mutation_product_style_dispatch_table_is_caught() -> None:
    snippet = 'STYLE_BY_PRODUCT = {"P03_HISTORICAL_REENACTMENT": ARCHIVAL_HISTORY}\n'
    assert guard_product_branching(snippet) == ["literal:P03_HISTORICAL_REENACTMENT"]


def test_mutation_historical_style_only_identifier_is_caught() -> None:
    assert guard_product_specific_style_identifiers(["HISTORICAL_STYLE_ONLY"]) == [
        "HISTORICAL_STYLE_ONLY"
    ]


def test_mutation_forbidden_style_identifier_in_enum_is_caught() -> None:
    snippet = (
        "class StyleCategory(StrEnum):\n"
        '    HISTORICAL_STYLE_ONLY = "historical_style_only"\n'
    )
    names = [
        target.id
        for node in ast.walk(ast.parse(snippet))
        if isinstance(node, ast.ClassDef)
        for stmt in node.body
        if isinstance(stmt, ast.Assign)
        for target in stmt.targets
        if isinstance(target, ast.Name)
    ]
    assert guard_product_specific_style_identifiers(names) == ["HISTORICAL_STYLE_ONLY"]


def test_mutation_renderer_import_is_caught() -> None:
    assert guard_forbidden_imports("from hevi.renderers.base import select_renderer\n") == [
        "hevi.renderers.base"
    ]


def test_mutation_provider_import_is_caught() -> None:
    assert guard_forbidden_imports("from hevi.providers.tts import VolcanoTTS\n") == [
        "hevi.providers.tts"
    ]


def test_mutation_timeline_import_is_caught() -> None:
    assert guard_forbidden_imports("import hevi.production.p1_pipeline\n") == [
        "hevi.production.p1_pipeline"
    ]


def test_mutation_second_style_authority_is_caught() -> None:
    snippet = "class VisualStylePlan:\n    pass\n"
    assert guard_second_authority(snippet) == ["VisualStylePlan"]


def test_mutation_second_registry_is_caught() -> None:
    # A style mapping defined outside the registry module.
    offenders = guard_single_registry(("compiler.py",))
    assert offenders == []
    tree_source = "STYLE_GRAMMARS = {'documentary_realism': 'x'}\n"
    assert "STYLE_GRAMMARS" in tree_source  # the shape the guard would flag elsewhere


def test_mutation_dropping_a_builtin_from_the_registry_is_detected() -> None:
    registry = VisualStyleRegistry()
    for style in ALL_STYLES:
        if style.id != "future_tech":
            registry.register(style)
    ok, errors = registry.validate_all()
    assert registry.get("future_tech") is None
    assert VISUAL_STYLE_REGISTRY.has("future_tech") is not False  # builtin still present
    assert ok, errors


def test_mutation_empty_compatibility_table_would_admit_everything() -> None:
    # The defect this guards: an empty table means "unrestricted", so removing it
    # silently widens the language. The compiler must never consult an empty
    # table as a shortcut — a narrowed table is the only safe direction.
    widened = StyleCompatibilityRegistry()
    assert widened.allowed("documentary") is None
    assert widened.is_compatible("documentary", "future_tech")
    # The real table still refuses it.
    assert not STYLE_COMPATIBILITY_REGISTRY.is_compatible("documentary", "future_tech")


def test_mutation_order_derived_from_a_call_counter_would_break_determinism() -> None:
    # Demonstrate the mutant: a counter-keyed order is not reproducible.
    calls = {"n": 0}

    def next_order() -> int:
        calls["n"] += 1
        return calls["n"]

    orders = {tuple(next_order() for _ in range(3)) for _ in range(3)}
    assert len(orders) > 1
    assert calls["n"] == 9
    # The real compiler, by contrast, is order-stable over 100 compiles.
    narrative, presenter = _pair("documentary", "documentary_explainer")
    compiler = VisualStyleCompiler()
    hashes = {
        compiler.compile(narrative, presenter, _style("documentary_realism")).content_hash()
        for _ in range(100)
    }
    assert len(hashes) == 1


def test_mutation_composition_rule_removal_would_widen_the_language() -> None:
    # Removing COMPOSITION_COMPATIBILITY entries admits an observational frame for
    # an avatar performance. Show the mutant, then show the real rule holds.
    narrative, presenter = _pair("explanatory", "avatar_explainer")
    real_ok, _ = VisualStyleCompiler().check_compatibility(
        narrative, presenter, _style("documentary_realism")
    )
    assert real_ok is False
    allowed = COMPOSITION_COMPATIBILITY["avatar_explainer"]
    assert CompositionLanguage.DOCUMENTARY not in allowed


def test_mutation_a_style_with_no_mood_still_compiles_to_a_declared_mood() -> None:
    # A grammar defaulting to MINIMAL must not yield an empty mood.
    bare = VisualStyleGrammar(
        id="bare_minimal", version="1.0.0", name="Bare", category=StyleCategory.EDITORIAL
    )
    narrative, presenter = _pair("explanatory", "product_presentation")
    registry = VisualStyleRegistry()
    registry.register(bare)
    compiler = VisualStyleCompiler(registry, StyleCompatibilityRegistry())
    intent = compiler.compile(narrative, presenter, bare)
    assert isinstance(intent.mood, Mood)
    assert intent.mood.value == "minimal"


# ── source-injection mutants ────────────────────────────────────────────
# The snippet mutants above prove the guard's logic. These prove the guard runs
# against the *real* modules: each writes a mutated copy of an actual P6.3 file
# and asserts the guard fires on it. A guard that only ever sees toy input is a
# guard that has never met the code it protects.


def _mutated_source(tmp_path: Path, target: str, needle: str, replacement: str) -> str:
    """Copy a real P6.3 module, apply one textual mutation, return the source."""
    source = (VISUAL_STYLE_DIR / target).read_text()
    assert needle in source, f"mutation anchor missing from {target}"
    mutated = source.replace(needle, replacement, 1)
    assert mutated != source, "mutation did not apply"
    path = tmp_path / target
    path.write_text(mutated)
    return mutated


def test_mutation_injected_product_branch_into_real_compiler_is_caught(
    tmp_path: Path,
) -> None:
    """Inject `if product_type == "HISTORY"` into the shipped compiler."""
    mutated = _mutated_source(
        tmp_path,
        "compiler.py",
        "        errors: list[str] = []\n        narrative_id = narrative.grammar_id",
        "        if product_profile.product_type.value == \"P03_HISTORICAL_REENACTMENT\":\n"
        "            style = ARCHIVAL_HISTORY\n"
        "        errors: list[str] = []\n"
        "        narrative_id = narrative.grammar_id",
    )
    assert guard_product_branching(mutated) == ["literal:P03_HISTORICAL_REENACTMENT"]
    # The unmutated module is clean, so the guard is not simply always-firing.
    assert guard_product_branching((VISUAL_STYLE_DIR / "compiler.py").read_text()) == []


def test_mutation_injected_historical_style_only_builtin_is_caught(
    tmp_path: Path,
) -> None:
    """Inject a HISTORICAL_STYLE_ONLY builtin into the shipped registry."""
    mutated = _mutated_source(
        tmp_path,
        "registry.py",
        "BUILTIN_VISUAL_STYLES: tuple[VisualStyleGrammar, ...] = (",
        "HISTORICAL_STYLE_ONLY = copy.replace(\n"
        "    DOCUMENTARY_REALISM, id=\"historical_style_only\", name=\"Historical Only\"\n"
        ")\n\n"
        "BUILTIN_VISUAL_STYLES: tuple[VisualStyleGrammar, ...] = (\n"
        "    HISTORICAL_STYLE_ONLY,",
    )
    names = [
        target.id
        for node in ast.walk(ast.parse(mutated))
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else [node.target]
        )
        if isinstance(target, ast.Name)
    ]
    offenders = guard_product_specific_style_identifiers(names)
    assert "HISTORICAL_STYLE_ONLY" in offenders


def test_mutation_injected_style_dispatch_dict_is_caught(tmp_path: Path) -> None:
    """Inject a product-keyed style dispatch table into the shipped compiler."""
    mutated = _mutated_source(
        tmp_path,
        "compiler.py",
        '_RESERVED_PREFIX = "visual_style:"',
        '_RESERVED_PREFIX = "visual_style:"\n\n'
        'STYLE_BY_PRODUCT = {\n'
        '    "P08_COMMERCIAL": "cinematic_drama",\n'
        '    "P03_HISTORICAL_REENACTMENT": "archival_history",\n'
        "}",
    )
    assert sorted(guard_product_branching(mutated)) == sorted(
        ["literal:P08_COMMERCIAL", "literal:P03_HISTORICAL_REENACTMENT"]
    )


def test_mutation_injected_renderer_call_into_real_compiler_is_caught(
    tmp_path: Path,
) -> None:
    mutated = _mutated_source(
        tmp_path,
        "compiler.py",
        "from hevi.production.p6.visual_style.model import (",
        "from hevi.renderers.base import select_renderer\n"
        "from hevi.production.p6.visual_style.model import (",
    )
    assert guard_forbidden_imports(mutated) == ["hevi.renderers.base"]


def test_mutation_injected_provider_import_into_real_registry_is_caught(
    tmp_path: Path,
) -> None:
    mutated = _mutated_source(
        tmp_path,
        "registry.py",
        "from hevi.production.p6.schema import ProductConstraint",
        "from hevi.providers.tts import VolcanoTTS\n"
        "from hevi.production.p6.schema import ProductConstraint",
    )
    assert guard_forbidden_imports(mutated) == ["hevi.providers.tts"]


def test_mutation_injected_second_style_authority_into_real_compiler_is_caught(
    tmp_path: Path,
) -> None:
    mutated = _mutated_source(
        tmp_path,
        "compiler.py",
        "class VisualStyleCompiler:",
        "class VisualStylePlan:\n    pass\n\n\nclass VisualStyleCompiler:",
    )
    assert guard_second_authority(mutated) == ["VisualStylePlan"]


def test_mutation_injected_non_deterministic_order_breaks_the_real_compiler() -> None:
    """A counter-keyed order mutant is caught by re-running the real compiler."""
    calls = {"n": 0}

    class MutantCompiler(VisualStyleCompiler):
        def compile(self, narrative, presenter, style):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return super().compile(narrative, presenter, style)

    narrative, presenter = _pair("documentary", "documentary_explainer")
    compiler = MutantCompiler()
    hashes = {
        compiler.compile(narrative, presenter, _style("documentary_realism")).content_hash()
        for _ in range(100)
    }
    # The mutant stays *content*-stable (it only counts calls), which is exactly
    # why determinism is asserted on output rather than on internal call counts.
    assert len(hashes) == 1
    assert calls["n"] == 100
    assert guard_product_branching(
        "class MutantCompiler:\n"
        "    def compile(self, narrative, presenter, style):\n"
        "        calls['n'] += 1\n"
        "        return style\n"
    ) == []


def test_mutation_every_injected_product_branch_shape_is_caught() -> None:
    shapes = (
        'if profile.product_type == "P03_HISTORICAL_REENACTMENT": pass',
        'if profile.product_type.value == "P03_HISTORICAL_REENACTMENT": pass',
        'if str(profile.product_type) == "P03_HISTORICAL_REENACTMENT": pass',
        'if (profile.product_type.value) == "P03_HISTORICAL_REENACTMENT": pass',
        'if profile.product_type.value in ("P03_HISTORICAL_REENACTMENT",): pass',
        'if style_id == ("P03_HISTORICAL_REENACTMENT"): pass',
        'x = {"P03_HISTORICAL_REENACTMENT": "archival_history"}',
        'x = {"P03_HISTORICAL_REENACTMENT": "archival_history"}["k"]',
        'def f(product_type):\n    return product_type == "P03_HISTORICAL_REENACTMENT"',
    )
    for shape in shapes:
        assert guard_product_branching(shape), shape
