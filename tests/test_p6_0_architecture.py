"""HEVI P6.0 — Commercial Product Grammar architecture.

Every test here is an architecture guard, not a behaviour test. P6.0 ships no
grammar behaviour, so what must be proven is that the *shape* is right and that
P6 has not quietly become a second authority for anything P0-P5 already owns.

The negative guards follow the P5.2 idiom (``tests/test_p5_2_architecture.py``):
AST walks over an explicit module list, with ``file:line`` in every message. The
module list is explicit rather than a repo-wide glob on purpose — HEVI already
contains pre-existing same-named types outside P6's control
(``hevi.cinematic.shot_intelligence.models.ShotPlan``,
``hevi.production.semantic_motion.MotionPlan``,
``hevi.season_planner.preparation.ShotPreparation``), so a glob would fail on
someone else's code and train the guard to be ignored.

Layout note: this file is flat in ``tests/`` rather than in
``tests/architecture/``, because HEVI has no ``tests/architecture/`` directory
and architecture suites are already flat (``test_p5_1_architecture.py``,
``test_p5_2_architecture.py``). Creating a parallel directory was the one thing
the P6 spec forbids.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

P6_MODULES: tuple[str, ...] = (
    "hevi.production.p6.schema",
    "hevi.production.p6.registry",
    "hevi.production.p6.compiler",
    "hevi.production.p6.runtime",
)


def _source(module: str) -> str:
    mod = importlib.import_module(module)
    return Path(inspect.getfile(mod)).read_text(encoding="utf-8")


def _tree(module: str) -> ast.Module:
    return ast.parse(_source(module))


def _top_level_symbols(source: str) -> set[str]:
    """Module-level function, class, and assigned names."""
    names: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _repo_root() -> Path:
    return Path(
        __import__("os").environ.get("HEVI_P6_REPO_ROOT", str(REPO))
    ).resolve()


# ── Product profile schema ──────────────────────────────────────────────


def test_product_profile_schema() -> None:
    from hevi.production.p6 import ProductProfile, ProductType

    members = {f.name for f in __import__("dataclasses").fields(ProductProfile)}
    required = {
        "id",
        "version",
        "product_type",
        "purpose",
        "audience",
        "duration_policy",
        "aspect_policy",
        "narrative_grammar",
        "presenter_grammar",
        "character_grammar",
        "world_grammar",
        "evidence_grammar",
        "documentary_grammar",
        "commercial_grammar",
        "instruction_grammar",
        "short_form_grammar",
        "cinematic_intent",
        "evidence_policy",
        "brand_policy",
        "instruction_policy",
        "short_form_policy",
        "delivery_policy",
        "renderer_constraint",
        "constraints",
        "qualification_profile",
    }
    assert required <= members, f"missing ProductProfile fields: {required - members}"
    assert len(list(ProductType)) == 10, "the canonical product matrix is P01-P10"


def test_product_profile_is_frozen_and_serialisable() -> None:
    """Intent must be immutable and round-trippable, or it is not a contract."""
    import dataclasses

    from hevi.production.p6 import ProductProfile

    assert dataclasses.is_dataclass(ProductProfile)
    params = ProductProfile.__dataclass_params__
    assert params.frozen is True, "ProductProfile must be frozen"

    profile = _sample_profile()
    payload = profile.to_dict()
    assert payload["id"] == profile.id
    assert profile.content_hash() == profile.content_hash(), "hash must be stable"
    assert len(profile.content_hash()) == 64


def test_product_profile_fails_closed_on_missing_intent() -> None:
    from hevi.production.p6 import GrammarRef, ProductProfile, ProductType

    with pytest.raises(ValueError, match="PRODUCT_PROFILE_WITHOUT_PURPOSE"):
        ProductProfile(
            id="X", product_type=ProductType.COMMERCIAL, purpose="", audience="a",
            grammars=(GrammarRef(kind=__import__(
                "hevi.production.p6", fromlist=["GrammarKind"]
            ).GrammarKind.NARRATIVE),),
        )
    with pytest.raises(ValueError, match="PRODUCT_PROFILE_WITHOUT_GRAMMARS"):
        ProductProfile(
            id="X", product_type=ProductType.COMMERCIAL, purpose="p", audience="a",
            grammars=(),
        )


def test_product_profile_rejects_duplicate_grammar_refs() -> None:
    from hevi.production.p6 import GrammarKind, GrammarRef, ProductProfile, ProductType

    with pytest.raises(ValueError, match="DUPLICATE_GRAMMAR_REF"):
        ProductProfile(
            id="X", product_type=ProductType.COMMERCIAL, purpose="p", audience="a",
            grammars=(
                GrammarRef(kind=GrammarKind.NARRATIVE),
                GrammarRef(kind=GrammarKind.NARRATIVE),
            ),
        )


# ── Grammar contract ────────────────────────────────────────────────────


def test_grammar_contract() -> None:
    from hevi.production.p6 import GRAMMAR_REGISTRY, GrammarKind

    ok, errors = GRAMMAR_REGISTRY.validate_all()
    assert ok, errors
    assert len(GrammarKind) == 10, "G01-G10"
    for kind in GrammarKind:
        assert GRAMMAR_REGISTRY.has(kind), f"{kind.value} unregistered"


def test_grammar_composition() -> None:
    """A profile composes grammars; it does not branch on product type."""
    from hevi.production.p6 import GrammarKind, NarrativeMode, NarrativeNode

    profile = _sample_profile()
    assert profile.has_grammar(GrammarKind.NARRATIVE)
    assert profile.has_grammar(GrammarKind.COMMERCIAL)
    # Not composed, therefore absent.
    assert not profile.has_grammar(GrammarKind.DOCUMENTARY)
    assert profile.narrative_grammar is not None
    assert profile.narrative_grammar.mode is NarrativeMode.COMMERCIAL
    assert NarrativeNode.HOOK in profile.narrative_grammar.nodes


def test_grammar_composition_detects_mismatch() -> None:
    """Declared-but-absent and present-but-undeclared both fail closed."""
    from hevi.production.p6 import GrammarKind, GrammarRef, ProductProfile, ProductType

    profile = ProductProfile(
        id="MISMATCH", product_type=ProductType.DOCUMENTARY, purpose="p", audience="a",
        grammars=(
            GrammarRef(kind=GrammarKind.NARRATIVE),
            GrammarRef(kind=GrammarKind.COMMERCIAL),  # declared, not carried
        ),
    )
    ok, errors = profile.validate_composition()
    assert not ok
    assert any("DECLARED_BUT_ABSENT:G07_CommercialGrammar" in e for e in errors)


@pytest.mark.parametrize("module", P6_MODULES)
def test_grammar_modules_declare_public_surface(module: str) -> None:
    """Every P6 module states what it exports and who owns it."""
    source = _source(module)
    assert "__all__" in source, f"{module}: missing __all__"
    assert "HEVI P6" in source[:400], f"{module}: missing HEVI P6 ownership header"


@pytest.mark.parametrize("module", P6_MODULES)
def test_grammar_is_provider_and_runtime_independent(module: str) -> None:
    """No grammar may reach a provider or a runtime.

    Grammars are declarative. A grammar that imports a provider or a renderer
    would make product intent depend on what happens to be installed, which is
    exactly the coupling the architecture forbids.
    """
    forbidden_prefixes = (
        "hevi.providers",
        "hevi.renderers",
        "hevi.production.p0_pipeline",
        "hevi.production.p1_pipeline",
        "hevi.production.p2_pipeline",
        "hevi.tasks",
        "hevi.missions",
        "hevi.verdict",
        "hevi.quality",
        "obase",
    )
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(forbidden_prefixes), (
                f"{module}:{node.lineno} imports {node.module}; grammars must stay "
                "provider- and runtime-independent"
            )
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(forbidden_prefixes), (
                    f"{module}:{node.lineno} imports {alias.name}"
                )


# ── Registry ────────────────────────────────────────────────────────────


def test_product_profile_registry() -> None:
    from hevi.production.p6 import PRODUCT_PROFILE_REGISTRY, ProductProfileRegistry

    assert isinstance(PRODUCT_PROFILE_REGISTRY, ProductProfileRegistry)
    # A fresh process starts empty: profiles are registered deliberately.
    assert PRODUCT_PROFILE_REGISTRY.list_profiles() == []
    ok, errors = PRODUCT_PROFILE_REGISTRY.validate_all()
    assert ok, errors


def test_registry_rejects_duplicate_version_immutably() -> None:
    from hevi.production.p6 import ProductProfileRegistry

    registry = ProductProfileRegistry()
    profile = _sample_profile()
    registry.register(profile)
    with pytest.raises(ValueError, match="PRODUCT_PROFILE_VERSION_IMMUTABLE"):
        registry.register(profile)


def test_registry_rejects_invalid_composition_at_registration() -> None:
    """Fail closed at the boundary, not at first use."""
    from hevi.production.p6 import (
        GrammarKind,
        GrammarRef,
        ProductProfile,
        ProductProfileRegistry,
        ProductType,
    )

    registry = ProductProfileRegistry()
    bad = ProductProfile(
        id="BAD", product_type=ProductType.DOCUMENTARY, purpose="p", audience="a",
        grammars=(GrammarRef(kind=GrammarKind.COMMERCIAL),),
    )
    with pytest.raises(ValueError, match="INVALID_PRODUCT_COMPOSITION"):
        registry.register(bad)


def test_registry_and_compiler_are_module_level_singletons() -> None:
    """Both authorities are exported as one instance each, by name.

    Deliberately does not ``importlib.reload`` these modules. Reloading
    rebinds the module-level singletons while the parent package keeps its
    original references, so the reloaded classes are no longer the classes the
    parent's objects were built from — every later ``isinstance`` check against
    the reloaded class then fails for reasons that have nothing to do with the
    code under test. Singletons are asserted structurally instead.
    """
    from hevi.production import p6
    from hevi.production.p6 import compiler as compiler_mod
    from hevi.production.p6 import registry as registry_mod

    # One instance per module, exported under a stable name.
    assert isinstance(registry_mod.PRODUCT_PROFILE_REGISTRY, registry_mod.ProductProfileRegistry)
    assert isinstance(registry_mod.GRAMMAR_REGISTRY, registry_mod.GrammarRegistry)
    assert isinstance(compiler_mod.P6_0_COMPILER, compiler_mod.ProductProfileCompiler)
    assert compiler_mod.P6_0_COMPILER is p6.P6_0_COMPILER
    assert registry_mod.PRODUCT_PROFILE_REGISTRY is p6.PRODUCT_PROFILE_REGISTRY
    assert registry_mod.GRAMMAR_REGISTRY is p6.GRAMMAR_REGISTRY

    # The package re-export and the defining module agree — one authority, two
    # names pointing at it, never two objects.
    assert "PRODUCT_PROFILE_REGISTRY" in registry_mod.__all__
    assert "GRAMMAR_REGISTRY" in registry_mod.__all__


def test_calling_a_compiler_twice_does_not_duplicate_authority() -> None:
    """Repeated compilation must not accumulate state or extra instances.

    Cheap way to catch an accidental per-call registry construction, which
    would be a second authority wearing a factory's clothes.
    """
    from hevi.production.p6 import P6_0_COMPILER, CompilerContractError

    before = id(P6_0_COMPILER)
    for _ in range(3):
        with pytest.raises(CompilerContractError):
            P6_0_COMPILER.compile_profile(_sample_profile())
    assert id(P6_0_COMPILER) == before


# ── Compiler contract ───────────────────────────────────────────────────


def test_product_profile_compiler() -> None:
    from hevi.production.p6 import (
        COMPILER_CAPABILITIES,
        P6_0_COMPILER,
        CompilerContractError,
        ProductProfileCompiler,
    )

    assert isinstance(P6_0_COMPILER, ProductProfileCompiler)
    assert P6_0_COMPILER.capabilities >= COMPILER_CAPABILITIES
    # P6.0 ships the contract, not a working compiler. It must refuse.
    with pytest.raises(CompilerContractError, match="COMPILER_NOT_IMPLEMENTED"):
        P6_0_COMPILER.compile_profile(_sample_profile())


def test_compiler_rejects_profile_without_duration_policy() -> None:
    """A product with unbounded duration is not compilable.

    ``validate_profile`` is the shared guard, so it runs ahead of
    ``compile_profile``. Testing it directly keeps the assertion about the
    validation rule rather than about which error happens to surface first.
    """
    from hevi.production.p6 import (
        P6_0_COMPILER,
        CompilerContractError,
        GrammarKind,
        GrammarRef,
        NarrativeGrammar,
        NarrativeMode,
        NarrativeNode,
        ProductProfile,
        ProductType,
    )

    profile = ProductProfile(
        id="NO_DURATION",
        product_type=ProductType.COMMERCIAL,
        purpose="p",
        audience="a",
        grammars=(GrammarRef(kind=GrammarKind.NARRATIVE),),
        narrative_grammar=NarrativeGrammar(
            mode=NarrativeMode.COMMERCIAL, nodes=(NarrativeNode.HOOK,)
        ),
        duration_policy=None,
        qualification_profile="QP",
    )
    with pytest.raises(CompilerContractError, match="MISSING_DURATION_POLICY"):
        P6_0_COMPILER.validate_profile(profile)


def test_compiler_validates_before_reporting_unimplemented() -> None:
    """Validation runs first, so an invalid profile is named as invalid.

    Ordering matters: if compilation refused first, a malformed profile would
    be reported as "not implemented" and the real defect would stay hidden.
    """
    from hevi.production.p6 import P6_0_COMPILER, CompilerContractError

    with pytest.raises(CompilerContractError, match="MISSING_QUALIFICATION_PROFILE"):
        P6_0_COMPILER.compile_profile(_sample_no_qualification())


def test_compiler_is_fail_closed_not_silently_partial() -> None:
    """A non-profile input must be rejected, never coerced."""
    from hevi.production.p6 import P6_0_COMPILER, CompilerContractError

    with pytest.raises(CompilerContractError, match="NOT_A_PRODUCT_PROFILE"):
        P6_0_COMPILER.compile_profile(object())  # type: ignore[arg-type]


def test_fail_closed() -> None:
    """Malformed value objects reject at construction."""
    from hevi.production.p6 import (
        CommercialGrammar,
        DurationPolicy,
        EpistemicStatus,
        EvidenceClaim,
    )

    with pytest.raises(ValueError, match="DURATION_OUT_OF_RANGE"):
        DurationPolicy(target_s=99.0, min_s=1.0, max_s=10.0)
    with pytest.raises(ValueError, match="COMMERCIAL_WITHOUT_FORBIDDEN_CLAIMS"):
        CommercialGrammar(brand_id="B")
    with pytest.raises(ValueError, match="FACT_WITHOUT_SOURCE"):
        EvidenceClaim(
            claim_id="c1", statement="s", epistemic_status=EpistemicStatus.FACT, confidence=1.0
        )


# ── Runtime boundary ────────────────────────────────────────────────────


def test_runtime_boundary() -> None:
    from hevi.production.p6 import (
        P6_0_COMPILER,
        PIPELINE_STAGES,
        PipelineStage,
        RuntimeBoundary,
    )

    boundary = RuntimeBoundary(compiler=P6_0_COMPILER)
    assert not boundary.is_bound, "P6.0 ships unbound by design"
    assert len(PIPELINE_STAGES) == 7
    assert PIPELINE_STAGES[0] is PipelineStage.RESOLVE_PROFILE
    assert PIPELINE_STAGES[-1] is PipelineStage.EDITORIAL_RENDER_DELIVERY


def test_runtime_refuses_to_run_its_own_pipeline() -> None:
    """Unbound produce() must raise. P6 never falls back to a built-in run."""
    from hevi.production.p6 import (
        P6_0_COMPILER,
        CompilerContractError,
        ProductionConstraints,
        RuntimeBoundary,
        RuntimeNotBoundError,
        SourceMaterial,
    )

    boundary = RuntimeBoundary(compiler=P6_0_COMPILER)
    # P6.0 stops at the compiler, which is itself fail-closed. The unbound
    # refusal is asserted separately below so both boundaries are proven rather
    # than whichever one happens to be reached first.
    with pytest.raises((RuntimeNotBoundError, CompilerContractError)):
        boundary.produce(
            _sample_profile(), SourceMaterial(narration_ref="n1"), ProductionConstraints()
        )


def test_unbound_runtime_refuses_even_with_a_working_compiler() -> None:
    """The unbound refusal is independent of the compiler.

    P6.1 will supply a working compiler. If the unbound check only appeared to
    work because the compiler raised first, the second pipeline would become
    reachable the moment compilation started working.
    """
    from hevi.production.p6 import (
        CompiledProductIntent,
        ProductionConstraints,
        ProductProfileCompiler,
        RuntimeBoundary,
        RuntimeNotBoundError,
        SourceMaterial,
    )

    class _WorkingCompiler(ProductProfileCompiler):
        compiler_id = "test_working"

        def compile_profile(self, profile) -> CompiledProductIntent:
            self.validate_profile(profile)
            return CompiledProductIntent(
                product_profile_id=profile.id,
                product_profile_version=profile.version,
                product_type=profile.product_type.value,
                purpose=profile.purpose,
                audience=profile.audience,
            )

    boundary = RuntimeBoundary(compiler=_WorkingCompiler())
    with pytest.raises(RuntimeNotBoundError, match="PRODUCTION_RUNTIME_NOT_BOUND"):
        boundary.produce(
            _sample_profile(), SourceMaterial(narration_ref="n1"), ProductionConstraints()
        )


def test_runtime_binding_requires_an_existing_entrypoint() -> None:
    from hevi.production.p6 import RuntimeBinding

    with pytest.raises(ValueError, match="RUNTIME_BINDING_WITHOUT_ENTRYPOINT"):
        RuntimeBinding(runtime_id="p2", entrypoint_ref="")


def test_runtime_rejects_non_port_runtime() -> None:
    from hevi.production.p6 import P6_0_COMPILER, RuntimeBinding, RuntimeBoundary

    boundary = RuntimeBoundary(compiler=P6_0_COMPILER)
    with pytest.raises(TypeError, match="NOT_A_PRODUCTION_RUNTIME"):
        boundary.bind(object(), RuntimeBinding(runtime_id="x", entrypoint_ref="y"))


# ── No second authority (the core redlines) ─────────────────────────────

#: Canonical types P6 must reference, never redefine.
_CANONICAL_TYPES = (
    "VisualBeat",
    "ShotPlan",
    "MotionPlan",
    "RendererBackend",
    "AssetCandidate",
    "EvidenceAsset",
    "CinematicRecipe",
    "RecipeLibrary",
    "ProductionProfile",
    "ProductionProfileRegistry",
    "VideoReview",
    "EditorialDiagnosis",
    "PairwiseComparison",
    "RevisionSession",
    "QualityEvaluation",
    "ProductionEntity",
    "TimelineLock",
    "AudioLock",
    "ResolvedAsset",
    "ProviderRegistry",
    "GatePolicy",
    "NarrativeAssertion",
    "StoryBeat",
)


@pytest.mark.parametrize("module", P6_MODULES)
@pytest.mark.parametrize("name", _CANONICAL_TYPES)
def test_no_second_authority(module: str, name: str) -> None:
    """P6 must not define any canonical P0-P5 type.

    Includes the real class names, not just the ones P5.1 happened to guard.
    """
    tree = _tree(module)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            pytest.fail(
                f"{module}:{node.lineno} defines class {name}; P6 must reference "
                "the existing authority, not redefine it"
            )


@pytest.mark.parametrize("module", P6_MODULES)
def test_no_second_pipeline(module: str) -> None:
    """No P6 module may implement a production pipeline."""
    banned_defs = {"produce", "run_production", "execute", "build_pipeline", "run_pipeline"}
    for node in ast.walk(_tree(module)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.name not in banned_defs or node.name == "produce", (
                f"{module}:{node.lineno} defines {node.name}(); P6 declares a boundary "
                "and delegates"
            )
        if isinstance(node, ast.ClassDef):
            # Base names may be bare Names or attribute chains; flatten both.
            base_names = {
                (b.id if isinstance(b, ast.Name) else b.attr)
                for b in node.bases
                if isinstance(b, (ast.Name, ast.Attribute))
            }
            assert not (base_names & {"Pipeline", "ProductionPipeline", "MissionExecutor", "TaskService"}), (
                f"{module}:{node.lineno} subclasses a runtime owner: {sorted(base_names)}"
            )


@pytest.mark.parametrize("module", P6_MODULES)
def test_no_second_renderer(module: str) -> None:
    """No P6 module may define or select a renderer."""
    source = _source(module)
    for banned in ("register_renderer", "RendererId", "RenderPlan", "RenderResult"):
        assert f"class {banned}" not in source, (
            f"{module}: defines {banned}; hevi.renderers.base is the renderer authority"
        )
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.ClassDef) and "Renderer" in node.name:
            assert node.name == "RendererConstraint", (
                f"{module}:{node.lineno} class {node.name} looks like a renderer; "
                "P6 may only declare RendererConstraint"
            )


@pytest.mark.parametrize("module", P6_MODULES)
def test_no_second_timeline(module: str) -> None:
    """No P6 module may define a timeline or beat container."""
    banned = {"Timeline", "TimelineLock", "Beat", "BeatPlan", "Storyboard", "EditPlan"}
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.ClassDef) and node.name in banned:
            pytest.fail(
                f"{module}:{node.lineno} defines {node.name}; VisualBeat and TimelineLock "
                "are the canonical timeline authority"
            )


@pytest.mark.parametrize("module", P6_MODULES)
def test_no_second_shot_authority(module: str) -> None:
    """No P6 module may define a shot or motion model."""
    banned = {"ShotPlan", "MotionPlan", "Shot", "CameraMove", "MotionPrimitive"}
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.ClassDef) and node.name in banned:
            pytest.fail(
                f"{module}:{node.lineno} defines {node.name}; P0 owns ShotPlan/MotionPlan"
            )


@pytest.mark.parametrize("module", P6_MODULES)
def test_no_second_asset_authority(module: str) -> None:
    """No P6 module may define an asset or evidence type."""
    banned = {"Asset", "AssetCandidate", "EvidenceAsset", "Artifact", "MediaAsset"}
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.ClassDef) and node.name in banned:
            pytest.fail(
                f"{module}:{node.lineno} defines {node.name}; asset authority is "
                "shot_readiness + artifact_store, evidence type is P5.1"
            )


@pytest.mark.parametrize("module", P6_MODULES)
def test_no_second_qa_authority(module: str) -> None:
    """No P6 module may define QA, verdict, or promotion logic.

    Guards the *real* class names (``QualityEvaluation``,
    ``run_final_review``), not only the ones P5.1's guard happened to name.
    """
    banned = {
        "QualityEvaluation", "QualityEvaluator", "GatePolicy", "RepairController",
        "Scorecard", "Verdict", "PromotionDecision",
    }
    banned_funcs = {"run_final_review", "final_qa", "shot_scorecard", "gate_verdict"}
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.ClassDef) and node.name in banned:
            pytest.fail(f"{module}:{node.lineno} defines QA type {node.name}")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.name not in banned_funcs, (
                f"{module}:{node.lineno} defines {node.name}(); QA authority is "
                "hevi.verdict + hevi.quality"
            )


@pytest.mark.parametrize("module", P6_MODULES)
def test_no_provider_authority(module: str) -> None:
    """P6 must not create or select providers."""
    source = _source(module)
    for banned in ("ProviderRegistry(", "register_llm", "register_vlm", "register_image_gen"):
        assert banned not in source, f"{module}: references {banned}"
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.ClassDef) and "Provider" in node.name:
            pytest.fail(f"{module}:{node.lineno} defines provider type {node.name}")


@pytest.mark.parametrize("module", P6_MODULES)
def test_product_branching_absent(module: str) -> None:
    """No branching on product type.

    This is the guard that makes "ten products, one pipeline" true rather than
    aspirational. Composition happens through ``grammars``; if a module ever
    compares a product type to a literal, the single-pipeline claim is false.
    """
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Attribute):
            if node.left.attr in {"product_type", "product_kind"}:
                for comparator in node.comparators:
                    for literal in ast.walk(comparator):
                        if isinstance(literal, ast.Constant) and isinstance(
                            literal.value, str
                        ):
                            if literal.value.startswith("P0") or literal.value.startswith(
                                "P1"
                            ):
                                pytest.fail(
                                    f"{module}:{node.lineno} branches on "
                                    f"{node.left.attr} == {literal.value!r}; compose "
                                    "grammars instead of branching on product type"
                                )
        if isinstance(node, ast.If):
            test = node.test
            for sub in ast.walk(test):
                if isinstance(sub, ast.Attribute) and sub.attr in {
                    "product_type",
                    "product_kind",
                }:
                    pytest.fail(
                        f"{module}:{node.lineno} branches on {sub.attr}; composition "
                        "must be declarative"
                    )


# ── P0-P5 boundary hygiene ──────────────────────────────────────────────


def test_p6_does_not_modify_frozen_p0_to_p5_modules() -> None:
    """P6.0 must not touch P0-P5 core logic."""
    frozen = [
        "hevi/production/p0_pipeline.py",
        "hevi/production/p1_types.py",
        "hevi/production/p2_types.py",
        "hevi/production/p2_profiles.py",
        "hevi/renderers/base.py",
        "hevi/production/shot_readiness.py",
        "hevi/production/creative_ledger.py",
        "hevi/verdict/scorecard.py",
        "hevi/quality/gate_policy.py",
    ]
    root = _repo_root()
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", *frozen],
        cwd=root, capture_output=True, text=True, check=False,
    )
    changed = [line for line in result.stdout.splitlines() if line.strip()]
    assert not changed, f"P6.0 modified frozen modules: {changed}"


def test_p6_does_not_reach_into_private_p5_modules() -> None:
    """P6 consumes P5 public contracts, not private helpers.

    ``p5_1_`` and ``p5_2_`` internals may move. Binding P6 to them would make
    P6 fragile against refactors that are none of its business.
    """
    banned = ("hevi.ops.p5_1_", "hevi.production.p5_3._", "hevi.qualification.")
    for module in P6_MODULES:
        for node in ast.walk(_tree(module)):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(banned), (
                    f"{module}:{node.lineno} imports private {node.module}"
                )


def test_unrelated_dirty_is_preserved() -> None:
    """P6.0 must not clean, reset, or absorb unrelated working-tree state."""
    root = _repo_root()
    result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    # The canonical checkout has substantial unrelated dirty state by design.
    # Asserting a clean tree would fail here and pass in an isolated worktree,
    # which proves nothing. What matters is that P6's own changes are scoped.
    p6_paths = [
        line for line in result.stdout.splitlines()
        if "/p6/" in line or "p6_0" in line or "P6-0" in line
    ]
    for line in p6_paths:
        assert line[3:].startswith(("hevi/production/p6/", "tests/", "docs/")), (
            f"P6 change outside its scope: {line}"
        )


# ── Helpers ─────────────────────────────────────────────────────────────


def _sample_no_qualification():
    """A profile that is well-formed but not compilable: no qualification target."""
    from hevi.production.p6 import (
        DurationPolicy,
        GrammarKind,
        GrammarRef,
        NarrativeGrammar,
        NarrativeMode,
        NarrativeNode,
        ProductProfile,
        ProductType,
    )

    return ProductProfile(
        id="NO_QUALIFICATION",
        product_type=ProductType.COMMERCIAL,
        purpose="p",
        audience="a",
        grammars=(GrammarRef(kind=GrammarKind.NARRATIVE),),
        duration_policy=DurationPolicy(target_s=30.0, min_s=15.0, max_s=60.0),
        narrative_grammar=NarrativeGrammar(
            mode=NarrativeMode.COMMERCIAL, nodes=(NarrativeNode.HOOK,)
        ),
        qualification_profile="",
    )


def _sample_profile():
    """A minimal valid profile used by the guards above."""
    from hevi.production.p6 import (
        CommercialGrammar,
        DurationPolicy,
        GrammarKind,
        GrammarRef,
        NarrativeGrammar,
        NarrativeMode,
        NarrativeNode,
        ProductProfile,
        ProductType,
    )

    return ProductProfile(
        id="P08_COMMERCIAL_SAMPLE",
        product_type=ProductType.COMMERCIAL,
        purpose="sell a product",
        audience="prospects",
        grammars=(
            GrammarRef(kind=GrammarKind.NARRATIVE),
            GrammarRef(kind=GrammarKind.COMMERCIAL),
        ),
        duration_policy=DurationPolicy(target_s=30.0, min_s=15.0, max_s=60.0),
        narrative_grammar=NarrativeGrammar(
            mode=NarrativeMode.COMMERCIAL,
            nodes=(NarrativeNode.HOOK, NarrativeNode.EXPLANATION, NarrativeNode.CTA),
        ),
        commercial_grammar=CommercialGrammar(
            brand_id="B1", forbidden_claims=("unverified_performance",)
        ),
        qualification_profile="QP_SAMPLE",
    )
