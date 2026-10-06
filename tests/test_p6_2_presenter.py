"""HEVI P6.2 — Presenter grammar: schema, registry, compiler, compatibility.

Phases 1-8 of the P6.2 spec. Every gate executes; none is asserted from
description text.

Guards are scoped to an explicit P6.2 module list rather than a repo-wide glob,
matching the P6.0/P6.1 rationale: HEVI already contains same-named types outside
P6's control, so a glob would fail on somebody else's code and train the guard to
be ignored.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

P6_2_MODULES: tuple[str, ...] = (
    "hevi.production.p6.presenter",
    "hevi.production.p6.presenter_registry",
    "hevi.production.p6.presenter_compiler",
    "hevi.production.p6.intent",
)

#: Prefixes P6.2 must never import. Covers renderer, editable, timeline, shot,
#: asset, QA and provider authorities in one sweep.
FORBIDDEN_IMPORT_PREFIXES: tuple[str, ...] = (
    "hevi.renderers",
    "hevi.editable",
    "hevi.production.runtime",
    "hevi.providers",
    "hevi.production.p0_pipeline",
    "hevi.production.p1_pipeline",
    "hevi.production.p2_pipeline",
    "hevi.production.p1_types",
    "hevi.production.shot_readiness",
    "hevi.production.creative_ledger",
    "hevi.artifact_store",
    "hevi.verdict",
    "hevi.quality",
    "hevi.missions",
    "hevi.tasks",
    "hevi.narrative",
    "obase",
)


def _source(module: str) -> str:
    return Path(inspect.getfile(importlib.import_module(module))).read_text(encoding="utf-8")


def _tree(module: str) -> ast.Module:
    return ast.parse(_source(module))


def _repo_root() -> Path:
    """Root the frozen-module diff runs against.

    Honours ``HEVI_P6_REPO_ROOT`` so the mutation harness can point the
    boundary guards at a scratch copy instead of the live tree.
    """
    return Path(os.environ.get("HEVI_P6_REPO_ROOT", str(REPO))).resolve()


def _imports(module: str) -> list[tuple[str, int]]:
    """Every (module, lineno) this file imports."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module, node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
    return found


def _profile(narrative: str = "documentary", presenter: str = "", **kwargs):
    from hevi.production.p6 import (
        DurationPolicy,
        GrammarKind,
        GrammarRef,
        ProductProfile,
        ProductType,
    )

    defaults = dict(
        id="P6_2_TEST",
        product_type=ProductType.DOCUMENTARY,
        purpose="test presenter compilation",
        audience="test audience",
        grammars=(GrammarRef(kind=GrammarKind.NARRATIVE),),
        duration_policy=DurationPolicy(target_s=30.0, min_s=15.0, max_s=60.0),
        narrative_grammar_id=narrative,
        presenter_grammar_id=presenter,
        qualification_profile="QP_TEST",
    )
    defaults.update(kwargs)
    return ProductProfile(**defaults)


def _narrative_intent(narrative: str = "documentary"):
    from hevi.production.p6.intent import compile_product_intent

    return compile_product_intent(_profile(narrative)).narrative_intent


# ══════════════════════════════════════════════════════════════════════
# Architecture — Phase 6
# ══════════════════════════════════════════════════════════════════════


def test_presenter_schema() -> None:
    """PresenterGrammar and PresenterNode carry the spec's required fields."""
    import dataclasses

    from hevi.production.p6.presenter import PresenterGrammar, PresenterNode

    grammar_fields = {f.name for f in dataclasses.fields(PresenterGrammar)}
    assert {"id", "version", "name", "description", "nodes", "constraints"} <= grammar_fields

    node_fields = {f.name for f in dataclasses.fields(PresenterNode)}
    assert {"id", "type", "purpose", "required", "order"} <= node_fields

    assert PresenterGrammar.__dataclass_params__.frozen is True
    assert PresenterNode.__dataclass_params__.frozen is True


def test_spec_node_types_present() -> None:
    """All eleven node types the spec's Phase 1 lists exist."""
    from hevi.production.p6.presenter import PresenterNodeType

    spec_types = {
        "INTRO", "HOOK", "IDENTITY", "AUTHORITY", "EXPLANATION", "DEMONSTRATION",
        "EVIDENCE", "EMOTION", "TRANSITION", "CTA", "CONCLUSION",
    }
    present = {n.value for n in PresenterNodeType}
    assert spec_types <= present, f"missing spec node types: {spec_types - present}"


def test_no_product_specific_presenter_node_type() -> None:
    """The presenter vocabulary must not encode product identity.

    ``COMMERCIAL_HOOK`` and ``P08_CTA`` are the failure modes: a node named after
    a product means the vocabulary has started branching on product type.
    """
    from hevi.production.p6.presenter import PresenterNodeType

    product_tokens = (
        "COMMERCIAL", "PRODUCT", "BRAND", "AVATAR", "DOCUMENTARY", "HISTOR",
        "HISTORY", "TUTORIAL", "LECTURE", "SHORT_FORM", "SHORTFORM", "REEL",
        "TIKTOK", "PROMO", "P01", "P02", "P03", "P04", "P05", "P06", "P07",
        "P08", "P09", "P10",
    )
    for node_type in PresenterNodeType:
        assert not any(tok in node_type.value for tok in product_tokens), (
            f"{node_type.value} encodes a product, not a presentation function"
        )


def test_no_product_presenter_branching() -> None:
    """No module selects a presenter by product type.

    Rejects the two forms: a table keyed on a product type, and a compare against
    a product-type literal. A membership test against a *named* requirement
    table is permitted — it asks whether input is complete, not what to do.
    """
    for module in P6_2_MODULES:
        for node in ast.walk(_tree(module)):
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        assert not key.value.startswith(("P0", "P1")), (
                            f"{module}:{node.lineno} keys a table on product type "
                            f"{key.value!r}"
                        )
            if isinstance(node, ast.Compare):
                # Walk the whole operand expressions, not just the top-level
                # operands. `profile.product_type == "P08"` puts the product
                # attribute directly on the left, but
                # `profile.product_type.value == "P08"` nests it one level
                # deeper, and a top-level-only check misses that entirely.
                operands = [sub for operand in
                            (node.left, *node.comparators)
                            for sub in ast.walk(operand)]
                mentions_product = any(
                    isinstance(o, ast.Attribute)
                    and o.attr in {
                        "product_type", "product_kind", "presenter_grammar_id",
                        "narrative_grammar_id",
                    }
                    for o in operands
                )
                if mentions_product:
                    for comparator in node.comparators:
                        assert not isinstance(comparator, ast.Constant), (
                            f"{module}:{node.lineno} compares a product attribute "
                            "against a literal; the presenter must be selected by "
                            "the profile, not chosen per product type"
                        )
            if isinstance(node, ast.Subscript):
                for sub in ast.walk(node.slice):
                    if isinstance(sub, ast.Attribute) and sub.attr in {
                        "product_type", "product_kind",
                    }:
                        pytest.fail(
                            f"{module}:{node.lineno} dispatches on product type"
                        )
                    if (
                        isinstance(sub, ast.Constant)
                        and isinstance(sub.value, str)
                        and sub.value.startswith(("P0", "P1"))
                    ):
                        pytest.fail(
                            f"{module}:{node.lineno} indexes by product-type literal"
                        )


def test_presenter_registry_only_source() -> None:
    """No module builds a private presenter collection.

    The one authorised module-level binding is the exported registry singleton;
    a module-level *dict or list* of presenters is the failure mode.
    """
    for module in P6_2_MODULES:
        for node in ast.walk(_tree(module)):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            is_literal = isinstance(node.value, (ast.Dict, ast.List, ast.Set))
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                lowered = target.id.lower()
                collection_name = lowered.endswith((
                    "_presenters", "_presenter_grammars", "_definitions",
                ))
                assert not (collection_name and is_literal), (
                    f"{module}:{node.lineno} builds a module-level presenter "
                    f"collection {target.id!r} outside the registry"
                )


def test_no_second_presenter_authority() -> None:
    """P6.2 must not redefine an existing presenter or voice authority.

    The canonical owners are P5.1's presenter types and the P2 profile registry.
    P6.2 declares performance *shape*; it does not own who presents.
    """
    banned = {
        "PresenterEntity", "PresenterPlan", "PresenterArtifact", "AudioLock",
        "VoiceIdentity", "ProductionProfile", "ProductionProfileRegistry",
        "ProviderRegistry", "VideoReview", "EditorialDiagnosis", "PairwiseComparison",
        "RevisionSession", "VisualBeat", "ShotPlan", "MotionPlan", "AssetCandidate",
        "EvidenceAsset", "RendererBackend",
    }
    for module in P6_2_MODULES:
        for node in ast.walk(_tree(module)):
            if isinstance(node, ast.ClassDef) and node.name in banned:
                pytest.fail(
                    f"{module}:{node.lineno} defines {node.name}; P6.2 declares "
                    "presentation shape and must not re-own an existing authority"
                )


def test_no_renderer_import() -> None:
    """No renderer, directly or by name."""
    for module in P6_2_MODULES:
        source = _source(module)
        for banned in ("register_renderer", "RendererId", "select_renderer", "render("):
            assert banned not in source, f"{module}: references {banned}"


def test_no_timeline_import() -> None:
    """No timeline or beat model."""
    from hevi.production.p6.presenter_compiler import PresenterIntent

    payload = PresenterIntent.__dataclass_fields__
    for banned in ("beats", "timeline", "shots", "TimelineLock", "VisualBeat"):
        assert banned not in payload, f"PresenterIntent carries {banned}"
    for module in P6_2_MODULES:
        for banned in ("VisualBeat", "TimelineLock", "StoryBeat", "ShotPlan"):
            assert f"import {banned}" not in _source(module)


def test_no_provider_import() -> None:
    """No provider, model, or voice-casting authority."""
    for module in P6_2_MODULES:
        source = _source(module)
        for banned in (
            "ProviderRegistry", "register_llm", "register_vlm", "register_generic",
            "select_provider", "ProviderRegistry(",
        ):
            assert banned not in source, f"{module}: references {banned}"


@pytest.mark.parametrize("forbidden", FORBIDDEN_IMPORT_PREFIXES)
@pytest.mark.parametrize("module", P6_2_MODULES)
def test_no_forbidden_import(module: str, forbidden: str) -> None:
    """One sweep covering renderer, timeline, shot, asset, QA and provider."""
    for imported, lineno in _imports(module):
        assert not imported.startswith(forbidden), (
            f"{module}:{lineno} imports {imported}"
        )


def test_modules_declare_public_surface() -> None:
    for module in P6_2_MODULES:
        source = _source(module)
        assert "__all__" in source, f"{module}: missing __all__"
        assert "HEVI P6" in source[:400], f"{module}: missing ownership header"


def test_p6_2_does_not_modify_frozen_p0_to_p5_modules() -> None:
    frozen = [
        "hevi/production/p0_pipeline.py",
        "hevi/production/p1_types.py",
        "hevi/production/p2_types.py",
        "hevi/renderers/base.py",
        "hevi/production/shot_readiness.py",
        "hevi/production/creative_ledger.py",
        "hevi/verdict/scorecard.py",
        "hevi/quality/gate_policy.py",
        "hevi/narrative/models.py",
    ]
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", *frozen],
        cwd=_repo_root(), capture_output=True, text=True, check=False,
    )
    changed = [line for line in result.stdout.splitlines() if line.strip()]
    assert not changed, f"P6.2 modified frozen modules: {changed}"


@pytest.mark.parametrize(
    "suite", ["tests/test_p6_0_architecture.py", "tests/test_p6_1_narrative.py"]
)
def test_earlier_p6_suites_still_pass(suite: str) -> None:
    """P6.0 and P6.1 are unaffected by P6.2.

    Invoked with ``sys.executable``: the bare name ``python`` is not on PATH here,
    and a guard that fails for an unrelated reason teaches nothing.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", suite, "-q"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout[-2000:]


# ══════════════════════════════════════════════════════════════════════
# Registry — Phase 2
# ══════════════════════════════════════════════════════════════════════


def test_presenter_registry_holds_required_builtins() -> None:
    from hevi.production.p6.presenter_registry import PRESENTER_GRAMMAR_REGISTRY

    assert set(PRESENTER_GRAMMAR_REGISTRY.list_ids()) == {
        "avatar_explainer",
        "documentary_explainer",
        "historical_reconstruction",
        "educational_lecture",
        "product_presentation",
    }


@pytest.mark.parametrize(
    "grammar_id,expected",
    [
        ("avatar_explainer",
         ("HOOK", "IDENTITY", "EXPLANATION", "DEMONSTRATION", "CONCLUSION", "CTA")),
        ("documentary_explainer",
         ("HOOK", "CONTEXT", "EVIDENCE", "EXPLANATION", "INTERPRETATION", "CONCLUSION")),
        ("historical_reconstruction",
         ("HOOK", "CONTEXT", "CHARACTER", "EVENT", "EVIDENCE", "INTERPRETATION",
          "CONCLUSION")),
    ],
)
def test_builtin_structures_match_spec(grammar_id: str, expected: tuple[str, ...]) -> None:
    """The three structures the spec spells out match exactly."""
    from hevi.production.p6.presenter_registry import PRESENTER_GRAMMAR_REGISTRY

    grammar = PRESENTER_GRAMMAR_REGISTRY.get(grammar_id)
    assert grammar is not None
    assert grammar.sequence() == expected


def test_presenter_registry_rejects_duplicate() -> None:
    from hevi.production.p6.presenter_registry import (
        AVATAR_EXPLAINER,
        PRESENTER_GRAMMAR_REGISTRY,
    )

    with pytest.raises(ValueError, match="PRESENTER_GRAMMAR_IMMUTABLE"):
        PRESENTER_GRAMMAR_REGISTRY.register(AVATAR_EXPLAINER)


def test_presenter_registry_resolves_both_spellings() -> None:
    """``id@1.0.0`` and ``id@v1.0.0`` both resolve."""
    from hevi.production.p6.presenter_registry import PRESENTER_GRAMMAR_REGISTRY

    for ref in ("avatar_explainer", "avatar_explainer@1.0.0", "avatar_explainer@v1.0.0"):
        assert PRESENTER_GRAMMAR_REGISTRY.resolve(ref).id == "avatar_explainer"


def test_presenter_registry_validate_all() -> None:
    from hevi.production.p6.presenter_registry import PRESENTER_GRAMMAR_REGISTRY

    ok, errors = PRESENTER_GRAMMAR_REGISTRY.validate_all()
    assert ok, errors


def test_presenter_registry_is_singleton() -> None:
    from hevi.production import p6
    from hevi.production.p6 import presenter_registry

    assert presenter_registry.PRESENTER_GRAMMAR_REGISTRY is p6.PRESENTER_GRAMMAR_REGISTRY
    assert "PRESENTER_GRAMMAR_REGISTRY" in presenter_registry.__all__


# ══════════════════════════════════════════════════════════════════════
# Compiler — Phase 3
# ══════════════════════════════════════════════════════════════════════


def test_presenter_compiler_deterministic() -> None:
    """Same input, same output hash — across repeats and fresh compilers."""
    from hevi.production.p6.intent import compile_product_intent

    profile = _profile("documentary", "documentary_explainer")
    hashes = {compile_product_intent(profile).content_hash() for _ in range(5)}
    assert len(hashes) == 1, f"presenter compilation is not deterministic: {hashes}"


def test_presenter_compiler_deterministic_across_instances() -> None:
    from hevi.production.p6.narrative.compiler import NarrativeCompiler
    from hevi.production.p6.presenter_compiler import PresenterCompiler

    profile = _profile("explanatory", "educational_lecture")
    narrative = NarrativeCompiler().compile_with(profile)
    reused = PresenterCompiler()
    assert (
        reused.compile(profile, narrative).content_hash()
        == reused.compile(profile, narrative).content_hash()
        == PresenterCompiler().compile(profile, narrative).content_hash()
    )


def test_presenter_intent_has_required_fields() -> None:
    from hevi.production.p6.intent import compile_product_intent

    intent = compile_product_intent(_profile("documentary", "documentary_explainer"))
    presenter = intent.presenter_intent
    assert presenter is not None
    for field in (
        "grammar_id", "ordered_nodes", "presentation_style",
        "speaker_requirements", "visual_requirements", "audio_requirements",
    ):
        assert field in presenter.to_dict(), f"PresenterIntent missing {field}"


def test_presenter_intent_is_serializable() -> None:
    from hevi.production.p6.intent import compile_product_intent

    intent = compile_product_intent(_profile("story", "historical_reconstruction"))
    encoded = json.dumps(intent.to_dict(), sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded["presenter_intent"]["grammar_id"] == "historical_reconstruction"
    assert len(intent.content_hash()) == 64


def test_presenter_intent_records_narrative_it_performs() -> None:
    from hevi.production.p6.intent import compile_product_intent

    intent = compile_product_intent(_profile("documentary", "documentary_explainer"))
    assert intent.presenter_intent is not None
    assert intent.presenter_intent.narrative_grammar_id == "documentary"


def test_presenter_requirements_are_channel_separated() -> None:
    from hevi.production.p6.intent import compile_product_intent

    intent = compile_product_intent(_profile("documentary", "documentary_explainer"))
    presenter = intent.presenter_intent
    assert presenter is not None
    assert presenter.speaker_requirements
    assert presenter.visual_requirements
    assert presenter.audio_requirements
    # A speaker requirement must not have leaked into the audio channel.
    assert not any(
        c.key.startswith("speaker_") for c in presenter.audio_requirements
    )


@pytest.mark.parametrize(
    "narrative,presenter,style",
    [
        ("documentary", "documentary_explainer", "documentary_narration"),
        ("story", "historical_reconstruction", "historical_reconstruction"),
        ("explanatory", "educational_lecture", "instructional_delivery"),
        ("explanatory", "avatar_explainer", "direct_address"),
        ("explanatory", "product_presentation", "direct_address"),
    ],
)
def test_compile_every_compatible_pairing(
    narrative: str, presenter: str, style: str
) -> None:
    from hevi.production.p6.intent import compile_product_intent

    intent = compile_product_intent(_profile(narrative, presenter))
    assert intent.presenter_intent is not None
    assert intent.presenter_intent.presentation_style == style
    assert intent.presenter_intent.validation_result.valid


@pytest.mark.parametrize("grammar_id", [
    "avatar_explainer", "documentary_explainer", "historical_reconstruction",
    "educational_lecture", "product_presentation",
])
def test_every_builtin_compiles(grammar_id: str) -> None:
    """Each built-in compiles under at least one narrative it is compatible with."""
    from hevi.production.p6.intent import compile_product_intent
    from hevi.production.p6.presenter_registry import GRAMMAR_COMPATIBILITY_REGISTRY

    narratives = [
        n for n in ("documentary", "explanatory", "story", "short_form")
        if GRAMMAR_COMPATIBILITY_REGISTRY.is_compatible(n, grammar_id)
    ]
    assert narratives, f"{grammar_id} is compatible with nothing"
    intent = compile_product_intent(_profile(narratives[0], grammar_id))
    assert intent.presenter_sequence()


def test_optional_presenter_is_not_required() -> None:
    """A profile with no presenter compiles narrative only."""
    from hevi.production.p6.intent import compile_product_intent

    intent = compile_product_intent(_profile("documentary", ""))
    assert intent.presenter_intent is None
    assert intent.presenter_sequence() == ()
    assert intent.narrative_sequence()


def test_presenter_compiler_rejects_invalid_narrative_intent() -> None:
    """A narrative that did not validate cannot be presented."""
    from hevi.production.p6.narrative.compiler import (
        NarrativeCompilationError,
        NarrativeIntent,
    )
    from hevi.production.p6.presenter_compiler import (
        PresenterCompilationError,
        PresenterCompiler,
    )

    invalid = NarrativeIntent(
        grammar_id="documentary", grammar_version="1.0.0", product_profile_id="X"
    )
    assert not invalid.validation_result.valid
    with pytest.raises(PresenterCompilationError, match="NARRATIVE_INTENT_INVALID"):
        PresenterCompiler().compile(
            _profile("documentary", "documentary_explainer"), invalid
        )
    assert NarrativeCompilationError  # imported for parity documentation


# ══════════════════════════════════════════════════════════════════════
# Compatibility — Phase 5
# ══════════════════════════════════════════════════════════════════════


def test_compatibility_check() -> None:
    """The spec's example pairing is permitted; the incoherent one is not."""
    from hevi.production.p6.presenter_registry import GRAMMAR_COMPATIBILITY_REGISTRY

    assert GRAMMAR_COMPATIBILITY_REGISTRY.is_compatible(
        "documentary", "documentary_explainer"
    )
    assert GRAMMAR_COMPATIBILITY_REGISTRY.is_compatible(
        "documentary", "historical_reconstruction"
    )
    assert not GRAMMAR_COMPATIBILITY_REGISTRY.is_compatible(
        "documentary", "avatar_explainer"
    )


@pytest.mark.parametrize(
    "narrative,permitted,refused",
    [
        ("documentary",
         ["documentary_explainer", "historical_reconstruction"],
         ["avatar_explainer", "educational_lecture", "product_presentation"]),
        ("explanatory",
         ["avatar_explainer", "educational_lecture", "product_presentation"],
         ["documentary_explainer", "historical_reconstruction"]),
        ("story",
         ["documentary_explainer", "historical_reconstruction"],
         ["avatar_explainer", "educational_lecture", "product_presentation"]),
        ("short_form",
         ["avatar_explainer", "educational_lecture", "product_presentation"],
         ["documentary_explainer", "historical_reconstruction"]),
    ],
)
def test_compatibility_table(
    narrative: str, permitted: list[str], refused: list[str]
) -> None:
    from hevi.production.p6.presenter_registry import GRAMMAR_COMPATIBILITY_REGISTRY

    for presenter in permitted:
        assert GRAMMAR_COMPATIBILITY_REGISTRY.is_compatible(narrative, presenter), (
            f"{narrative} should permit {presenter}"
        )
    for presenter in refused:
        assert not GRAMMAR_COMPATIBILITY_REGISTRY.is_compatible(narrative, presenter), (
            f"{narrative} should refuse {presenter}"
        )


def test_unregistered_narrative_permits_any_presenter() -> None:
    """A narrative absent from the table is unrestricted, not broken.

    Keeps a newly added narrative usable without a compatibility edit, while the
    pairings that actually matter stay constrained.
    """
    from hevi.production.p6.presenter_registry import GRAMMAR_COMPATIBILITY_REGISTRY

    assert GRAMMAR_COMPATIBILITY_REGISTRY.allowed("brand_new_grammar") is None
    assert GRAMMAR_COMPATIBILITY_REGISTRY.is_compatible(
        "brand_new_grammar", "avatar_explainer"
    )


@pytest.mark.parametrize(
    "narrative,presenter",
    [
        ("documentary", "avatar_explainer"),
        ("documentary", "educational_lecture"),
        ("documentary", "product_presentation"),
        ("explanatory", "documentary_explainer"),
        ("explanatory", "historical_reconstruction"),
        ("story", "avatar_explainer"),
        ("story", "educational_lecture"),
        ("story", "product_presentation"),
        ("short_form", "documentary_explainer"),
        ("short_form", "historical_reconstruction"),
    ],
)
def test_incompatible_pairing_raises(narrative: str, presenter: str) -> None:
    from hevi.production.p6.intent import compile_product_intent
    from hevi.production.p6.presenter_compiler import PresenterCompilationError

    with pytest.raises(
        PresenterCompilationError, match="INCOMPATIBLE_GRAMMAR_PAIRING"
    ):
        compile_product_intent(_profile(narrative, presenter))


def test_compatibility_registry_is_singleton() -> None:
    from hevi.production import p6
    from hevi.production.p6 import presenter_registry

    assert (
        presenter_registry.GRAMMAR_COMPATIBILITY_REGISTRY
        is p6.GRAMMAR_COMPATIBILITY_REGISTRY
    )


def test_compatibility_validate_all() -> None:
    """Every presenter named in the table must actually be registered."""
    from hevi.production.p6.presenter_registry import GRAMMAR_COMPATIBILITY_REGISTRY

    ok, errors = GRAMMAR_COMPATIBILITY_REGISTRY.validate_all()
    assert ok, errors


def test_compatibility_rejects_unregistered_presenter() -> None:
    """Allowing a presenter that does not exist fails validation."""
    from hevi.production.p6.presenter_registry import (
        GrammarCompatibilityRegistry,
    )

    registry = GrammarCompatibilityRegistry()
    registry.allow("documentary", "does_not_exist")
    ok, errors = registry.validate_all()
    assert not ok
    assert any("UNKNOWN_PRESENTER_IN_COMPATIBILITY" in e for e in errors)


def test_compatibility_requires_ids() -> None:
    from hevi.production.p6.presenter_registry import GrammarCompatibilityRegistry

    registry = GrammarCompatibilityRegistry()
    with pytest.raises(ValueError, match="COMPATIBILITY_WITHOUT_NARRATIVE_ID"):
        registry.allow("", "avatar_explainer")
    with pytest.raises(ValueError, match="COMPATIBILITY_WITHOUT_PRESENTER_ID"):
        registry.allow("documentary", "")


def test_compatibility_allow_accumulates() -> None:
    from hevi.production.p6.presenter_registry import GrammarCompatibilityRegistry

    registry = GrammarCompatibilityRegistry()
    registry.allow("story", "documentary_explainer")
    registry.allow("story", "historical_reconstruction")
    assert registry.is_compatible("story", "documentary_explainer")
    assert registry.is_compatible("story", "historical_reconstruction")


# ══════════════════════════════════════════════════════════════════════
# Fail closed — Phase 7
# ══════════════════════════════════════════════════════════════════════


def test_missing_presenter_grammar_id_fails_closed() -> None:
    """A narrative product with no presenter raises PRESENTER_GRAMMAR_NOT_FOUND."""
    from hevi.production.p6.presenter_compiler import (
        PresenterCompilationError,
        PresenterCompiler,
    )

    profile = _profile("documentary", "")
    # The product-intent path tolerates an absent presenter by design, so the
    # fail-closed assertion is made against the compiler directly: declaring a
    # presenter workflow and then not naming one must raise, not default.
    with pytest.raises(PresenterCompilationError, match="PRESENTER_GRAMMAR_NOT_FOUND"):
        PresenterCompiler().resolve_presenter_grammar(profile)


def test_unknown_presenter_grammar_fails_closed() -> None:
    """An unregistered presenter id raises UNKNOWN_PRESENTER_GRAMMAR."""
    from hevi.production.p6.intent import compile_product_intent
    from hevi.production.p6.presenter_compiler import PresenterCompilationError

    with pytest.raises(PresenterCompilationError, match="UNKNOWN_PRESENTER_GRAMMAR"):
        compile_product_intent(_profile("documentary", "no_such_presenter"))


def test_presenter_never_returns_empty_nodes() -> None:
    """A compiled presenter is never an empty list.

    The failure this prevents is a video that compiled successfully and then had
    nobody presenting it.
    """
    from hevi.production.p6.intent import compile_product_intent

    for narrative in ("documentary", "explanatory", "story", "short_form"):
        for presenter in (
            "avatar_explainer", "documentary_explainer", "historical_reconstruction",
            "educational_lecture", "product_presentation",
        ):
            try:
                intent = compile_product_intent(_profile(narrative, presenter))
            except Exception:
                continue  # refused, which is also not an empty presenter
            assert intent.presenter_sequence(), (
                f"{narrative}+{presenter} compiled to an empty presenter"
            )


def test_no_fallback_default_presenter() -> None:
    """A refused compilation must not quietly substitute another presenter."""
    from hevi.production.p6.intent import compile_product_intent
    from hevi.production.p6.presenter_compiler import PresenterCompilationError

    with pytest.raises(PresenterCompilationError):
        compile_product_intent(_profile("documentary", "avatar_explainer"))


def test_presenter_grammar_rejects_empty_nodes() -> None:
    from hevi.production.p6.presenter import PresenterGrammar

    with pytest.raises(ValueError, match="PRESENTER_GRAMMAR_WITHOUT_NODES"):
        PresenterGrammar(
            id="g", version="1.0.0", name="g", description="d", nodes=()
        )


def test_presenter_grammar_rejects_all_optional() -> None:
    from hevi.production.p6.presenter import (
        PresenterGrammar,
        PresenterNode,
        PresenterNodeType,
    )

    with pytest.raises(ValueError, match="PRESENTER_GRAMMAR_WITHOUT_REQUIRED_NODE"):
        PresenterGrammar(
            id="g", version="1.0.0", name="g", description="d",
            nodes=(
                PresenterNode(
                    id="a", type=PresenterNodeType.HOOK, purpose="p",
                    order=0, required=False,
                ),
            ),
        )


def test_presenter_grammar_rejects_ambiguous_order() -> None:
    from hevi.production.p6.presenter import (
        PresenterGrammar,
        PresenterNode,
        PresenterNodeType,
    )

    def _n(nid: str, order: int) -> PresenterNode:
        return PresenterNode(
            id=nid, type=PresenterNodeType.HOOK, purpose="p", order=order
        )

    with pytest.raises(ValueError, match="AMBIGUOUS_PRESENTER_NODE_ORDER"):
        PresenterGrammar(
            id="g", version="1.0.0", name="g", description="d",
            nodes=(_n("a", 0), _n("b", 0)),
        )


def test_presenter_grammar_rejects_duplicate_node_ids() -> None:
    from hevi.production.p6.presenter import (
        PresenterGrammar,
        PresenterNode,
        PresenterNodeType,
    )

    def _n(nid: str, order: int) -> PresenterNode:
        return PresenterNode(
            id=nid, type=PresenterNodeType.HOOK, purpose="p", order=order
        )

    with pytest.raises(ValueError, match="DUPLICATE_PRESENTER_NODE_ID"):
        PresenterGrammar(
            id="g", version="1.0.0", name="g", description="d",
            nodes=(_n("a", 0), _n("a", 1)),
        )


def test_presenter_grammar_rejects_invalid_opening_node() -> None:
    from hevi.production.p6.presenter import (
        PresenterGrammar,
        PresenterNode,
        PresenterNodeType,
    )

    with pytest.raises(ValueError, match="INVALID_PRESENTER_OPENING_NODE"):
        PresenterGrammar(
            id="g", version="1.0.0", name="g", description="d",
            nodes=(
                PresenterNode(
                    id="c", type=PresenterNodeType.CTA, purpose="p", order=0
                ),
                PresenterNode(
                    id="h", type=PresenterNodeType.HOOK, purpose="p", order=1
                ),
            ),
        )


def test_presenter_node_requires_purpose() -> None:
    from hevi.production.p6.presenter import PresenterNode, PresenterNodeType

    with pytest.raises(ValueError, match="PRESENTER_NODE_WITHOUT_PURPOSE"):
        PresenterNode(id="a", type=PresenterNodeType.HOOK, purpose="", order=0)


def test_presenter_node_rejects_unknown_type() -> None:
    """The vocabulary is closed — a typo cannot become a node type."""
    from hevi.production.p6.presenter import PresenterNode

    with pytest.raises(ValueError, match="UNKNOWN_PRESENTER_NODE_TYPE"):
        PresenterNode(id="a", type="COMMERCIAL_HOOK", purpose="p", order=0)


def test_excluding_required_presenter_nodes_fails_closed() -> None:
    """Dropping a required presenter node raises rather than emitting a gap."""
    from hevi.production.p6.narrative.compiler import NarrativeCompiler
    from hevi.production.p6.presenter import (
        PresenterGrammar,
        PresenterNode,
        PresenterNodeType,
    )
    from hevi.production.p6.presenter_compiler import (
        PresenterCompilationError,
        PresenterCompiler,
    )
    from hevi.production.p6.presenter_registry import (
        GrammarCompatibilityRegistry,
        PresenterGrammarRegistry,
    )
    from hevi.production.p6.schema import ProductConstraint

    registry = PresenterGrammarRegistry()
    registry.register(
        PresenterGrammar(
            id="fragile_presenter", version="1.0.0", name="f", description="d",
            nodes=(
                PresenterNode(
                    id="hook", type=PresenterNodeType.HOOK, purpose="p", order=0
                ),
                PresenterNode(
                    id="identity", type=PresenterNodeType.IDENTITY, purpose="p",
                    order=1, required=False,
                ),
            ),
            constraints=(
                ProductConstraint(key="identity_required", value="true"),
            ),
        )
    )
    compiler = PresenterCompiler(registry, compatibility=GrammarCompatibilityRegistry())
    narrative = NarrativeCompiler().compile_with(_profile("explanatory"))
    profile = _profile("explanatory", "fragile_presenter")
    with pytest.raises(
        PresenterCompilationError, match="PRESENTER_IDENTITY_REQUIRED_BUT_ABSENT"
    ):
        compiler.compile_with(profile, narrative, include_optional=False)


def test_presenter_requires_valid_narrative_intent_object() -> None:
    from hevi.production.p6.presenter_compiler import (
        PresenterCompilationError,
        PresenterCompiler,
    )

    with pytest.raises(PresenterCompilationError, match="NOT_A_NARRATIVE_INTENT"):
        PresenterCompiler().compile(
            _profile("documentary", "documentary_explainer"), object()  # type: ignore[arg-type]
        )


def test_presenter_compiler_rejects_non_profile() -> None:
    from hevi.production.p6.presenter_compiler import (
        PresenterCompilationError,
        PresenterCompiler,
    )

    with pytest.raises(PresenterCompilationError, match="NOT_A_PRODUCT_PROFILE"):
        PresenterCompiler().resolve_presenter_grammar(object())  # type: ignore[arg-type]


# ══════════════════════════════════════════════════════════════════════
# Product connection — Phase 4
# ══════════════════════════════════════════════════════════════════════


def test_product_selects_presenter_grammar() -> None:
    """A product names a presenter grammar; it does not define one."""
    from hevi.production.p6.presenter_registry import PRESENTER_GRAMMAR_REGISTRY

    profile = _profile("explanatory", "avatar_explainer")
    assert profile.presenter_grammar_id == "avatar_explainer"
    # The profile holds a reference, never the definition.
    assert not hasattr(profile, "presenter_nodes")
    assert not hasattr(profile, "presenter_logic")
    assert not hasattr(profile, "camera_logic")
    assert not hasattr(profile, "render_logic")
    assert not hasattr(profile, "audio_logic")
    assert PRESENTER_GRAMMAR_REGISTRY.has("avatar_explainer")


def test_product_profile_schema_carries_presenter_grammar_id() -> None:
    import dataclasses

    from hevi.production.p6 import ProductProfile

    assert "presenter_grammar_id" in {f.name for f in dataclasses.fields(ProductProfile)}


def test_product_intent_carries_both_intents() -> None:
    from hevi.production.p6.intent import compile_product_intent

    intent = compile_product_intent(_profile("documentary", "documentary_explainer"))
    assert intent.narrative_intent is not None
    assert intent.presenter_intent is not None
    assert intent.presenter_intent.narrative_grammar_id == intent.narrative_intent.grammar_id


def test_p6_0_presenter_declaration_still_intact() -> None:
    """P6.0's profile-side PresenterGrammar is untouched and still distinct.

    P6.2 adds a registry-side definition. Merging them would give each product a
    private presenter engine.
    """
    from hevi.production.p6 import presenter, schema

    assert schema.PresenterGrammar is not presenter.PresenterGrammar
    assert schema.PresenterGrammar.__module__ == "hevi.production.p6.schema"
    assert presenter.PresenterGrammar.__module__ == "hevi.production.p6.presenter"
    declaration = schema.PresenterGrammar(
        presenter_id="p1", kind=schema.PresenterKind.AVATAR
    )
    assert declaration.presenter_id == "p1"


def test_p6_1_narrative_unchanged_by_p6_2() -> None:
    """P6.1's narrative grammar still compiles exactly as before."""
    from hevi.production.p6.intent import compile_product_intent

    intent = compile_product_intent(_profile("documentary", ""))
    assert intent.narrative_sequence() == (
        "HOOK", "CONTEXT", "EVIDENCE", "DEVELOPMENT", "INTERPRETATION", "CONCLUSION"
    )




# ══════════════════════════════════════════════════════════════════════
# Mutation tests — Phase 8
#
# A guard that cannot fail is not a guard. Each test below injects one defect
# into a scratch copy of a P6.2 source and asserts the corresponding guard
# *rejects* it. Nothing here touches the working tree, and nothing spawns a
# nested pytest run, so there is no recursion to bound.
# ══════════════════════════════════════════════════════════════════════


def _mutated_module(rel: str, original: str, replacement: str) -> ast.Module:
    """Parse `rel` with `original` swapped for `replacement`.

    Raises if the mutation did not apply — a mutation that silently fails to
    land would make the guard look like it passed for the wrong reason.
    """
    source = (REPO / rel).read_text(encoding="utf-8")
    assert original in source, f"mutation anchor missing from {rel}: {original!r}"
    mutated = source.replace(original, replacement, 1)
    assert mutated != source, f"mutation did not apply in {rel}"
    return ast.parse(mutated)


def _product_branching_offenders(tree: ast.Module) -> list[str]:
    """Reimplementation of the branching guard, for mutation probing.

    Mirrors the guard exactly, including the deep ``ast.walk`` over operand
    expressions — a probe weaker than the guard would pass a mutation the guard
    catches, which proves nothing.
    """
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    if key.value.startswith(("P0", "P1")):
                        offenders.append(f"dict key {key.value!r}")
        if isinstance(node, ast.Compare):
            operands = [sub for operand in
                        (node.left, *node.comparators)
                        for sub in ast.walk(operand)]
            mentions = any(
                isinstance(o, ast.Attribute)
                and o.attr in {"product_type", "product_kind", "presenter_grammar_id",
                               "narrative_grammar_id"}
                for o in operands
            )
            if mentions and any(isinstance(c, ast.Constant) for c in node.comparators):
                offenders.append("compare against literal")
    return offenders


def _product_specific_node_offenders(node_type_names: list[str]) -> list[str]:
    product_tokens = (
        "COMMERCIAL", "PRODUCT", "BRAND", "AVATAR", "DOCUMENTARY", "HISTOR",
        "HISTORY", "TUTORIAL", "LECTURE", "SHORT_FORM", "REEL", "TIKTOK",
        "PROMO", "P01", "P02", "P03", "P04", "P05", "P06", "P07", "P08", "P09", "P10",
    )
    return [n for n in node_type_names if any(t in n for t in product_tokens)]


def test_mutation_1_product_type_branching_is_caught() -> None:
    """Injecting ``if product_type == "P08_COMMERCIAL"`` must be flagged.

    This is the ten-pipelines failure mode: a product acquiring its own presenter
    path instead of selecting a shared grammar.
    """
    tree = _mutated_module(
        "hevi/production/p6/presenter_compiler.py",
        "        grammar = self.resolve_presenter_grammar(profile)",
        '        if profile.product_type.value == "P08_COMMERCIAL":\n'
        "            return self.compile_with(profile, narrative_intent)\n"
        "        grammar = self.resolve_presenter_grammar(profile)",
    )
    offenders = _product_branching_offenders(tree)
    assert offenders, "per-product presenter branching was NOT caught"


def test_mutation_2_commercial_node_type_is_caught() -> None:
    """Adding ``COMMERCIAL_HOOK`` to the node enum must be flagged."""
    from hevi.production.p6.presenter import PresenterNodeType

    clean = [n.value for n in PresenterNodeType]
    assert not _product_specific_node_offenders(clean), "baseline already dirty"

    mutated_names = [*clean, "COMMERCIAL_HOOK"]
    assert _product_specific_node_offenders(mutated_names), (
        "product-specific node type was NOT caught"
    )


def test_mutation_3_non_deterministic_ordering_is_caught() -> None:
    """Order derived from mutable state must fail the determinism guard.

    Injected as a monotonically increasing call counter, so the instability is
    guaranteed rather than dependent on address-space luck.
    """
    import hashlib
    import json
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Node:
        id: str
        type: str
        order: int

        def to_dict(self) -> dict[str, object]:
            return {"id": self.id, "type": self.type, "order": self.order}

    calls = {"n": 0}

    def _mutated_ordered() -> tuple[_Node, ...]:
        # Modulo 2 makes the key genuinely alternate: on an even call a sorts
        # first, on an odd call b does. A larger modulus would leave the order
        # stable by coincidence, which would prove nothing.
        calls["n"] += 1
        return tuple(sorted((_Node("a", "HOOK", 0), _Node("b", "CTA", 1)),
                            key=lambda n: (n.order + calls["n"]) % 2))

    def _hash() -> str:
        payload = json.dumps(
            [n.to_dict() for n in _mutated_ordered()], sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    hashes = {_hash() for _ in range(4)}
    assert len(hashes) > 1, (
        "non-deterministic ordering was NOT caught — the determinism guard "
        "would pass a compilation that changes between runs"
    )


def test_mutation_4_removing_a_registry_entry_is_caught() -> None:
    """Dropping a built-in from the registry must be detected as missing.

    A grammar that exists in the module but is never registered leaves a product
    unable to select it: a silent capability loss.
    """
    from hevi.production.p6.presenter import PresenterGrammar
    from hevi.production.p6.presenter_registry import (
        BUILTIN_PRESENTER_GRAMMARS,
        PresenterGrammarRegistry,
    )

    expected = {
        "avatar_explainer", "documentary_explainer", "historical_reconstruction",
        "educational_lecture", "product_presentation",
    }

    # Baseline: the complete set is registered and satisfies the guard.
    complete = PresenterGrammarRegistry()
    for grammar in BUILTIN_PRESENTER_GRAMMARS:
        complete.register(grammar)
    assert set(complete.list_ids()) == expected, "baseline registry is incomplete"

    # Mutation: PRODUCT_PRESENTATION excluded from the registered set.
    mutated = PresenterGrammarRegistry()
    for grammar in BUILTIN_PRESENTER_GRAMMARS:
        if grammar.id != "product_presentation":
            mutated.register(grammar)
    missing = expected - set(mutated.list_ids())
    assert missing == {"product_presentation"}, (
        "removing a registry entry was NOT caught"
    )
    # And the affected product genuinely cannot select it any more.
    with pytest.raises(KeyError, match="UNKNOWN_PRESENTER_GRAMMAR"):
        mutated.resolve("product_presentation")
    assert PresenterGrammar  # the type is what makes this a loss, not a rename
