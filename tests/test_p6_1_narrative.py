"""HEVI P6.1 — Narrative grammar: schema, registry, compiler, boundary.

Phase 1-7 of the P6.1 spec. Every gate here executes; none is asserted from
description text.

Guards are scoped to an explicit P6.1 module list rather than a repo-wide glob,
matching the P6.0 rationale: HEVI already contains same-named types outside P6's
control (``hevi.cinematic.shot_intelligence.models.ShotPlan``,
``hevi.production.semantic_motion.MotionPlan``), so a glob would fail on
somebody else's code and train the guard to be ignored.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

P6_1_MODULES: tuple[str, ...] = (
    "hevi.production.p6.narrative.model",
    "hevi.production.p6.narrative.registry",
    "hevi.production.p6.narrative.builtin",
    "hevi.production.p6.narrative.compiler",
    "hevi.production.p6.intent",
)


def _source(module: str) -> str:
    return Path(inspect.getfile(importlib.import_module(module))).read_text(encoding="utf-8")


def _tree(module: str) -> ast.Module:
    return ast.parse(_source(module))


def _indexes_product_type(node: ast.Subscript) -> bool:
    """True when a subscript's index is derived from a product type.

    Walks the whole index expression, so both ``T[profile.product_type]`` and
    ``T[profile.product_type.value]`` are caught, as is anything wrapped in a
    call such as ``T[profile.product_type.value.lower()]``.
    """
    for sub in ast.walk(node.slice):
        if isinstance(sub, ast.Attribute) and sub.attr in {
            "product_type", "product_kind",
        }:
            return True
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if sub.value.startswith(("P0", "P1")):
                return True
    return False


def _profile(grammar_id: str = "documentary", **kwargs):
    """A valid profile wired to a registered narrative grammar."""
    from hevi.production.p6 import (
        DurationPolicy,
        GrammarKind,
        GrammarRef,
        ProductProfile,
        ProductType,
    )

    defaults = dict(
        id="P6_1_TEST",
        product_type=ProductType.DOCUMENTARY,
        purpose="test narrative compilation",
        audience="test audience",
        grammars=(GrammarRef(kind=GrammarKind.NARRATIVE),),
        duration_policy=DurationPolicy(target_s=30.0, min_s=15.0, max_s=60.0),
        narrative_grammar_id=grammar_id,
        qualification_profile="QP_TEST",
    )
    defaults.update(kwargs)
    return ProductProfile(**defaults)


# ── Schema ──────────────────────────────────────────────────────────────


def test_narrative_schema() -> None:
    """NarrativeGrammar and NarrativeNode carry the spec's required fields."""
    import dataclasses

    from hevi.production.p6.narrative import NarrativeGrammar, NarrativeNode

    grammar_fields = {f.name for f in dataclasses.fields(NarrativeGrammar)}
    assert {"id", "version", "name", "description", "nodes", "transitions", "constraints"} <= grammar_fields

    node_fields = {f.name for f in dataclasses.fields(NarrativeNode)}
    assert {"id", "type", "required", "optional", "order", "constraints"} <= node_fields

    assert NarrativeGrammar.__dataclass_params__.frozen is True
    assert NarrativeNode.__dataclass_params__.frozen is True


def test_canonical_node_types_present() -> None:
    """All eleven canonical types from the spec exist."""
    from hevi.production.p6.narrative import NarrativeNodeType

    canonical = {
        "HOOK", "CONTEXT", "SETUP", "DEVELOPMENT", "EVIDENCE", "CONFLICT",
        "TURNING_POINT", "EXPLANATION", "RESOLUTION", "CONCLUSION", "CTA",
    }
    present = {n.value for n in NarrativeNodeType}
    assert canonical <= present, f"missing canonical node types: {canonical - present}"


def test_builtin_grammars_have_spec_structures() -> None:
    """The four built-ins match the structures the spec prescribes."""
    from hevi.production.p6.narrative import (
        DOCUMENTARY,
        EXPLANATORY,
        SHORT_FORM,
        STORY,
    )

    assert EXPLANATORY.sequence() == (
        "HOOK", "CONTEXT", "EXPLANATION", "DEMONSTRATION", "CONCLUSION"
    )
    assert DOCUMENTARY.sequence() == (
        "HOOK", "CONTEXT", "EVIDENCE", "DEVELOPMENT", "INTERPRETATION", "CONCLUSION"
    )
    assert STORY.sequence() == (
        "HOOK", "SETUP", "CONFLICT", "TURNING_POINT", "RESOLUTION", "CONCLUSION"
    )
    assert SHORT_FORM.sequence() == (
        "HOOK", "PATTERN_INTERRUPT", "DEVELOPMENT", "PAYOFF", "CTA"
    )


def test_pattern_interrupt_is_a_general_node_type() -> None:
    """PATTERN_INTERRUPT is vocabulary, not a short-form runtime branch.

    It lives on the shared enum alongside every other node type, so a
    documentary or a story may use it. If it were short-form-only, this test
    would fail — which is the point.
    """
    from hevi.production.p6.narrative import NarrativeNode, NarrativeNodeType

    assert NarrativeNodeType.PATTERN_INTERRUPT.value == "PATTERN_INTERRUPT"
    assert "SHORT_FORM" not in NarrativeNodeType.PATTERN_INTERRUPT.value
    # A non-short-form grammar may legitimately contain it.
    node = NarrativeNode(id="interrupt", type=NarrativeNodeType.PATTERN_INTERRUPT, order=1)
    assert node.type is NarrativeNodeType.PATTERN_INTERRUPT


def test_no_product_specific_node_type() -> None:
    """The node vocabulary must not encode product identity.

    ``COMMERCIAL_HOOK`` and ``HISTORY_SCENE`` are the failure modes: a node type
    named after a product means the vocabulary is branching on product type.
    """
    from hevi.production.p6.narrative import NarrativeNodeType

    product_tokens = (
        "COMMERCIAL", "PRODUCT", "BRAND", "HISTOR", "HISTORY", "DOCUMENTARY",
        "TUTORIAL", "AVATAR", "SHORT_FORM", "SHORTFORM", "REEL", "TIKTOK",
        "PROMO", "P01", "P02", "P03", "P04", "P05", "P06", "P07", "P08", "P09", "P10",
    )
    for node_type in NarrativeNodeType:
        assert not any(tok in node_type.value for tok in product_tokens), (
            f"{node_type.value} encodes a product, not a narrative function"
        )


def test_node_rejects_contradictory_flags() -> None:
    from hevi.production.p6.narrative import NarrativeNode, NarrativeNodeType

    with pytest.raises(ValueError, match="CONTRADICTORY_NODE_FLAGS"):
        NarrativeNode(
            id="x", type=NarrativeNodeType.HOOK, required=True, optional=True
        )


def test_node_rejects_unknown_type() -> None:
    """The vocabulary is closed — a typo cannot become a node type."""
    from hevi.production.p6.narrative import NarrativeNode

    with pytest.raises(ValueError, match="UNKNOWN_NARRATIVE_NODE_TYPE"):
        NarrativeNode(id="x", type="COMMERCIAL_HOOK", order=0)  # type: ignore[arg-type]


# ── Registry ────────────────────────────────────────────────────────────


def test_registry_unique() -> None:
    """Registering the same id@version twice raises."""
    from hevi.production.p6.narrative import (
        NARRATIVE_GRAMMAR_REGISTRY,
    )

    grammar = NARRATIVE_GRAMMAR_REGISTRY.get("documentary")
    assert grammar is not None
    with pytest.raises(ValueError, match="NARRATIVE_GRAMMAR_IMMUTABLE"):
        NARRATIVE_GRAMMAR_REGISTRY.register(grammar)


def test_registry_resolve() -> None:
    """Resolve by bare id (latest) and by qualified id."""
    from hevi.production.p6.narrative import NARRATIVE_GRAMMAR_REGISTRY

    latest = NARRATIVE_GRAMMAR_REGISTRY.resolve("documentary")
    assert latest.version == "1.0.0"
    qualified = NARRATIVE_GRAMMAR_REGISTRY.resolve("documentary@1.0.0")
    assert qualified.qualified_id == latest.qualified_id
    with pytest.raises(KeyError, match="NARRATIVE_GRAMMAR_NOT_FOUND"):
        NARRATIVE_GRAMMAR_REGISTRY.resolve("no_such_grammar")


def test_registry_is_single_authority() -> None:
    """No duplicate registry instance and no local dict.

    Checked structurally: the module exports exactly one registry singleton, and
    no module builds a private grammar dict at runtime.
    """
    from hevi.production.p6 import narrative
    from hevi.production.p6.narrative import NARRATIVE_GRAMMAR_REGISTRY, registry

    assert narrative.NARRATIVE_GRAMMAR_REGISTRY is NARRATIVE_GRAMMAR_REGISTRY
    assert registry.NARRATIVE_GRAMMAR_REGISTRY is NARRATIVE_GRAMMAR_REGISTRY
    assert "NARRATIVE_GRAMMAR_REGISTRY" in registry.__all__

    # No module may build a private grammar collection. The one authorised
    # module-level grammar binding is the exported registry singleton itself, so
    # only a *collection* (plural, or a dict/list literal) is forbidden here.
    for module in P6_1_MODULES:
        for node in ast.walk(_tree(module)):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            value = node.value
            is_collection_literal = isinstance(
                value, (ast.Dict, ast.List, ast.Set)
            )
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                name = target.id
                lowered = name.lower()
                plural = lowered.endswith(("_grammars", "_definitions"))
                assert not (plural and is_collection_literal), (
                    f"{module}:{node.lineno} builds a module-level grammar "
                    f"collection {name!r} outside the registry"
                )


def test_registry_has_no_product_specific_grammars() -> None:
    """Built-ins are general shapes, not per-product grammars."""
    from hevi.production.p6.narrative import NARRATIVE_GRAMMAR_REGISTRY

    assert set(NARRATIVE_GRAMMAR_REGISTRY.list_ids()) == {
        "explanatory", "documentary", "story", "short_form"
    }
    for grammar_id in NARRATIVE_GRAMMAR_REGISTRY.list_ids():
        assert not grammar_id.startswith(("P0", "P1", "commercial_", "historical_"))


def test_registry_validates_all() -> None:
    from hevi.production.p6.narrative import NARRATIVE_GRAMMAR_REGISTRY

    ok, errors = NARRATIVE_GRAMMAR_REGISTRY.validate_all()
    assert ok, errors


# ── Compiler ────────────────────────────────────────────────────────────


def test_compile_explanatory() -> None:
    from hevi.production.p6.intent import compile_product_intent

    intent = compile_product_intent(_profile("explanatory"))
    assert intent.narrative_sequence() == (
        "HOOK", "CONTEXT", "EXPLANATION", "DEMONSTRATION", "CONCLUSION"
    )
    assert intent.narrative_intent.validation_result.valid


def test_compile_documentary() -> None:
    from hevi.production.p6.intent import compile_product_intent

    intent = compile_product_intent(_profile("documentary"))
    assert intent.narrative_sequence() == (
        "HOOK", "CONTEXT", "EVIDENCE", "DEVELOPMENT", "INTERPRETATION", "CONCLUSION"
    )
    assert "evidence_before_interpretation" in {
        c.key for c in intent.constraints
    }
    order = {t: i for i, t in enumerate(intent.narrative_sequence())}
    assert order["EVIDENCE"] < order["INTERPRETATION"], "evidence must precede interpretation"


def test_compile_story() -> None:
    from hevi.production.p6.intent import compile_product_intent

    intent = compile_product_intent(_profile("story"))
    assert intent.narrative_sequence() == (
        "HOOK", "SETUP", "CONFLICT", "TURNING_POINT", "RESOLUTION", "CONCLUSION"
    )
    assert "CONFLICT" in intent.narrative_sequence()
    assert "TURNING_POINT" in intent.narrative_sequence()


def test_compile_short_form() -> None:
    from hevi.production.p6.intent import compile_product_intent

    intent = compile_product_intent(_profile("short_form"))
    assert intent.narrative_sequence() == (
        "HOOK", "PATTERN_INTERRUPT", "DEVELOPMENT", "PAYOFF", "CTA"
    )


def test_intent_carries_required_fields() -> None:
    from hevi.production.p6.intent import compile_product_intent

    intent = compile_product_intent(_profile("explanatory"))
    payload = intent.narrative_intent.to_dict()
    for field in ("grammar_id", "nodes", "sequence", "constraints", "validation_result"):
        assert field in payload, f"NarrativeIntent missing {field}"
    assert payload["grammar_id"] == "explanatory"
    assert payload["validation_result"]["valid"] is True


def test_intent_is_serializable() -> None:
    """to_dict round-trips through JSON, and the hash derives from it."""
    from hevi.production.p6.intent import compile_product_intent

    intent = compile_product_intent(_profile("story"))
    encoded = json.dumps(intent.to_dict(), sort_keys=True)
    assert json.loads(encoded)["narrative_intent"]["grammar_id"] == "story"
    assert len(intent.content_hash()) == 64


# ── Failure: fail closed ────────────────────────────────────────────────


def test_unknown_grammar_fail_closed() -> None:
    """An unregistered grammar id raises. It never falls back to a default."""
    from hevi.production.p6.intent import compile_product_intent
    from hevi.production.p6.narrative import NarrativeCompilationError

    with pytest.raises(NarrativeCompilationError, match="UNKNOWN_NARRATIVE_GRAMMAR"):
        compile_product_intent(_profile("no_such_grammar"))


def test_missing_grammar_id_fail_closed() -> None:
    """A narrative product with no grammar is incomplete, not exempt."""
    from hevi.production.p6.intent import ProductIntentError, compile_product_intent

    with pytest.raises(ProductIntentError, match="MISSING_NARRATIVE_GRAMMAR_ID"):
        compile_product_intent(_profile(grammar_id=""))


def test_invalid_node_fail_closed() -> None:
    """Malformed nodes are rejected at construction."""
    from hevi.production.p6.narrative import (
        NarrativeGrammar,
        NarrativeNode,
        NarrativeNodeType,
    )

    def _n(nid: str, order: int) -> NarrativeNode:
        return NarrativeNode(id=nid, type=NarrativeNodeType.HOOK, order=order)

    with pytest.raises(ValueError, match="DUPLICATE_NARRATIVE_NODE_ID"):
        NarrativeGrammar(
            id="g", version="1.0.0", name="g", description="d",
            nodes=(_n("a", 0), _n("a", 1)),
        )
    with pytest.raises(ValueError, match="AMBIGUOUS_NODE_ORDER"):
        NarrativeGrammar(
            id="g", version="1.0.0", name="g", description="d",
            nodes=(_n("a", 0), _n("b", 0)),
        )
    with pytest.raises(ValueError, match="NARRATIVE_GRAMMAR_WITHOUT_NODES"):
        NarrativeGrammar(id="g", version="1.0.0", name="g", description="d", nodes=())


def test_invalid_opening_node_fail_closed() -> None:
    """A narrative cannot open on its own conclusion."""
    from hevi.production.p6.narrative import (
        NarrativeGrammar,
        NarrativeNode,
        NarrativeNodeType,
    )

    with pytest.raises(ValueError, match="INVALID_OPENING_NODE"):
        NarrativeGrammar(
            id="g", version="1.0.0", name="g", description="d",
            nodes=(
                NarrativeNode(id="c", type=NarrativeNodeType.CONCLUSION, order=0),
                NarrativeNode(id="h", type=NarrativeNodeType.HOOK, order=1),
            ),
        )


def test_dangling_transition_fail_closed() -> None:
    from hevi.production.p6.narrative import (
        NarrativeGrammar,
        NarrativeNode,
        NarrativeNodeType,
        NarrativeTransition,
    )

    with pytest.raises(ValueError, match="DANGLING_TRANSITION"):
        NarrativeGrammar(
            id="g", version="1.0.0", name="g", description="d",
            nodes=(
                NarrativeNode(id="a", type=NarrativeNodeType.HOOK, order=0),
                NarrativeNode(id="b", type=NarrativeNodeType.CONTEXT, order=1),
            ),
            transitions=(NarrativeTransition("a", "ghost"),),
        )


def test_excluding_required_nodes_fails_compilation() -> None:
    """Dropping a required node raises instead of emitting a holed intent."""
    from hevi.production.p6 import ProductConstraint
    from hevi.production.p6.narrative import (
        NARRATIVE_GRAMMAR_REGISTRY,
        NarrativeCompilationError,
        NarrativeCompiler,
        NarrativeGrammar,
        NarrativeNode,
        NarrativeNodeType,
    )

    grammar = NarrativeGrammar(
        id="fragile", version="1.0.0", name="f", description="d",
        nodes=(
            NarrativeNode(id="a", type=NarrativeNodeType.HOOK, order=0),
            NarrativeNode(
                id="b", type=NarrativeNodeType.DEMONSTRATION, order=1,
                required=False, optional=True,
            ),
        ),
        constraints=(
            ProductConstraint(key="demonstration_required", value="true"),
        ),
    )
    NARRATIVE_GRAMMAR_REGISTRY.register(grammar)
    compiler = NarrativeCompiler(NARRATIVE_GRAMMAR_REGISTRY)
    profile = _profile("fragile")
    with pytest.raises(NarrativeCompilationError, match="DEMONSTRATION_REQUIRED_BUT_ABSENT"):
        compiler.compile_with(profile, include_optional=False)


# ── Determinism ─────────────────────────────────────────────────────────


def test_same_input_same_output() -> None:
    """Identical input produces a byte-identical intent, repeatedly."""
    from hevi.production.p6.intent import compile_product_intent

    profile = _profile("documentary")
    hashes = {compile_product_intent(profile).content_hash() for _ in range(5)}
    assert len(hashes) == 1, f"compilation is not deterministic: {hashes}"


def test_determinism_across_compiler_instances() -> None:
    """A fresh compiler produces the same intent as a reused one."""
    from hevi.production.p6.narrative import NarrativeCompiler

    profile = _profile("story")
    reused = NarrativeCompiler()
    first = reused.compile_with(profile).content_hash()
    second = reused.compile_with(profile).content_hash()
    fresh = NarrativeCompiler().compile_with(profile).content_hash()
    assert first == second == fresh


def test_grammar_content_hash_is_stable() -> None:
    from hevi.production.p6.narrative import NARRATIVE_GRAMMAR_REGISTRY

    grammar = NARRATIVE_GRAMMAR_REGISTRY.get("explanatory")
    assert grammar is not None
    assert grammar.content_hash() == grammar.content_hash()


# ── Boundary guards ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "forbidden",
    [
        "hevi.renderers",
        "hevi.production.p0_pipeline",
        "hevi.production.p1_types",
        "hevi.production.p1_pipeline",
        "hevi.production.p2_pipeline",
        "hevi.production.shot_readiness",
        "hevi.production.creative_ledger",
        "hevi.artifact_store",
        "hevi.verdict",
        "hevi.quality",
        "hevi.missions",
        "hevi.tasks",
        "hevi.providers",
        "obase",
    ],
)
@pytest.mark.parametrize("module", P6_1_MODULES)
def test_no_forbidden_import(module: str, forbidden: str) -> None:
    """P6.1 imports no P0-P5 implementation module.

    Covers renderer, timeline, shot, asset and QA in one sweep: every one of
    those authorities lives behind one of these prefixes.
    """
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(forbidden), (
                f"{module}:{node.lineno} imports {node.module}"
            )
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(forbidden), (
                    f"{module}:{node.lineno} imports {alias.name}"
                )


def test_no_renderer_import() -> None:
    """No renderer, directly or transitively through P6.1."""
    from hevi.production.p6.intent import ProductIntent

    assert not hasattr(ProductIntent, "render")
    for module in P6_1_MODULES:
        source = _source(module)
        for banned in ("register_renderer", "RendererId", "render(", "select_renderer"):
            assert banned not in source, f"{module}: references {banned}"


def test_no_timeline_import() -> None:
    """No timeline or beat model."""
    from hevi.production.p6.narrative import NarrativeIntent

    payload = NarrativeIntent.__dataclass_fields__
    for banned in ("beats", "timeline", "shots", "Beat", "TimelineLock"):
        assert banned not in payload, f"NarrativeIntent carries {banned}"
    for module in P6_1_MODULES:
        source = _source(module)
        for banned in ("VisualBeat", "TimelineLock", "StoryBeat"):
            assert f"import {banned}" not in source


def test_no_shot_import() -> None:
    """No shot or motion model."""
    from hevi.production.p6.narrative import NarrativeIntent

    payload = NarrativeIntent.__dataclass_fields__
    for banned in ("shot_plan", "motion_plan", "ShotPlan", "MotionPlan"):
        assert banned not in payload
    for module in P6_1_MODULES:
        source = _source(module)
        for banned in ("ShotPlan", "MotionPlan"):
            assert f"import {banned}" not in source


def test_no_asset_import() -> None:
    """No asset or evidence resolution."""
    for module in P6_1_MODULES:
        source = _source(module)
        for banned in ("AssetCandidate", "EvidenceAsset", "ArtifactRepository", "assert_ready_for_generation"):
            assert f"import {banned}" not in source, f"{module}: references {banned}"


def test_no_qa_import() -> None:
    """No quality, verdict or promotion authority."""
    for module in P6_1_MODULES:
        source = _source(module)
        for banned in ("run_final_review", "shot_scorecard", "GatePolicy", "RepairController"):
            assert f"import {banned}" not in source


def test_no_product_branching() -> None:
    """No module branches on product type to choose a narrative.

    This is the guard that keeps one engine serving ten products. A product type
    may appear only in a *requirement table* (``intent.py``), never in a
    conditional that selects behaviour.
    """
    # A membership test against a *named table* is a requirement check, not
    # behavioural branching: `product_type in NARRATIVE_REQUIRED_PRODUCT_TYPES`
    # asks whether input is complete. Selecting behaviour per product type —
    # an equality compare, or a subscript that maps a type to a grammar — is the
    # failure mode. Both are rejected; only the table-membership form passes.
    # Two shapes must never appear, in an `if` *or* anywhere else:
    #   `_DISPATCH = {"P08_COMMERCIAL": "story"}`   a per-product table
    #   `if profile.product_type == "P08_COMMERCIAL"` a per-product branch
    # A dict literal keyed by a product-type string is the clearest form of the
    # failure, so it is checked across the whole module rather than only inside
    # conditionals — an injected dispatch table is often assigned, not branched.
    for module in P6_1_MODULES:
        for node in ast.walk(_tree(module)):
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        assert not key.value.startswith(("P0", "P1")), (
                            f"{module}:{node.lineno} keys a table on product type "
                            f"{key.value!r}; dispatch must not be per-product"
                        )
            if isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                mentions_product = any(
                    isinstance(o, ast.Attribute) and o.attr in {
                        "product_type", "product_kind", "narrative_grammar_id",
                    }
                    for o in operands
                )
                if mentions_product:
                    for comparator in node.comparators:
                        assert not isinstance(comparator, ast.Constant), (
                            f"{module}:{node.lineno} compares a product attribute "
                            "against a literal; narrative must be resolved by "
                            "registry lookup"
                        )

    for module in P6_1_MODULES:
        for node in ast.walk(_tree(module)):
            if not isinstance(node, ast.If):
                continue
            for sub in ast.walk(node.test):
                if isinstance(sub, ast.Compare):
                    # Only a comparison whose operands actually mention a product
                    # type is interesting. `endpoint not in known` is ordinary
                    # data validation and must not be flagged.
                    operands = [sub.left, *sub.comparators]
                    mentions_product = any(
                        isinstance(o, ast.Attribute) and o.attr in {
                            "product_type", "product_kind", "narrative_grammar_id",
                        }
                        for o in operands
                    )
                    if mentions_product:
                        for comparator in sub.comparators:
                            if isinstance(comparator, ast.Constant):
                                pytest.fail(
                                    f"{module}:{node.lineno} branches on a product "
                                    "attribute against a literal; narrative must be "
                                    "resolved by registry lookup"
                                )
                if isinstance(sub, ast.Subscript):
                    # `TABLE[profile.product_type.value]` — a dispatch table keyed
                    # by product type. Any other subscript (`self._grammars[key]`,
                    # `nodes[i]`) is ordinary data access and is allowed, so the
                    # check is specifically for a product-typed index.
                    if _indexes_product_type(sub):
                        base = sub.value
                        base_name = (
                            base.id if isinstance(base, ast.Name)
                            else getattr(base, "attr", "")
                        )
                        pytest.fail(
                            f"{module}:{node.lineno} dispatches on product type via "
                            f"{base_name!r}[...]; narrative must be resolved by "
                            "registry lookup, not per-product dispatch"
                        )


def test_p6_1_does_not_modify_frozen_p0_to_p5_modules() -> None:
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
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    changed = [line for line in result.stdout.splitlines() if line.strip()]
    assert not changed, f"P6.1 modified frozen modules: {changed}"


def test_p6_0_narrative_declaration_still_intact() -> None:
    """P6.0's profile-side NarrativeGrammar is untouched and still distinct.

    P6.1 adds a registry-side definition. Both are legitimate; conflating them
    would give a profile a private narrative engine.
    """
    from hevi.production.p6 import schema
    from hevi.production.p6.narrative import model

    assert schema.NarrativeGrammar is not model.NarrativeGrammar
    assert schema.NarrativeGrammar.__module__ == "hevi.production.p6.schema"
    assert model.NarrativeGrammar.__module__ == "hevi.production.p6.narrative.model"
    # The profile-side declaration still compiles standalone.
    declaration = schema.NarrativeGrammar(
        mode=schema.NarrativeMode.DOCUMENTARY,
        nodes=(schema.NarrativeNode.HOOK, schema.NarrativeNode.EVIDENCE),
    )
    assert declaration.mode is schema.NarrativeMode.DOCUMENTARY


def test_p6_0_suite_still_passes() -> None:
    """P6.0's architecture guards are unaffected by P6.1.

    Invoked with ``sys.executable`` rather than ``"python"``: the bare name is
    not on PATH in this environment, and a guard that fails for an unrelated
    reason teaches nothing.
    """
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_p6_0_architecture.py", "-q"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout[-2000:]


def test_modules_declare_public_surface() -> None:
    for module in P6_1_MODULES:
        source = _source(module)
        assert "__all__" in source, f"{module}: missing __all__"
        assert "HEVI P6" in source[:400], f"{module}: missing ownership header"
