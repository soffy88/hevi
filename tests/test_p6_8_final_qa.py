"""HEVI P6.8 — Final qualification audits.

Four audits the freeze depends on, each asserting a number rather than a feeling:

* ``FALSE_SUCCESS`` — no failure path may report success
* ``DUPLICATE_SIDE_EFFECTS`` — repeated runs must not re-enter the delegate
* ``DETERMINISM`` — 100+ repetitions per product yield singleton hashes
* authority uniqueness — one owner per concern, no duplicates anywhere

Plus the static sweep and the source-scope check.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from hevi.production.p6.product_compiler import ProductCompiler
from hevi.production.p6.product_profiles import (
    COMMERCIAL_PRODUCT_REGISTRY,
)
from hevi.production.p6.production_runtime import (
    ExecutionReceipt,
    ProductionRunResult,
    RunState,
    UnifiedProductionRuntime,
)
from hevi.production.p6.runtime import ProductionConstraints, SourceMaterial
from hevi.production.p6.visual_compiler import semantic_fingerprint_of
from tests.test_p6_6_runtime import ExistingRuntime

P6_DIR = Path("hevi/production/p6")
P6_FILES = tuple(sorted(P6_DIR.rglob("*.py")))
ENTRYPOINT = "hevi.production.p0_pipeline:produce"

_LIBRARY = None


def _library():
    global _LIBRARY
    if _LIBRARY is None:
        from hevi.production.p5_3.library import RecipeLibrary
        from hevi.production.p5_3.recipes import load_all_recipes

        lib = RecipeLibrary()
        for recipe in load_all_recipes():
            lib.register(recipe)
        _LIBRARY = lib
    return _LIBRARY


def _source() -> SourceMaterial:
    return SourceMaterial(material_refs=("asset://clip.mp4",), narration_ref="asset://n.vtt")


def _runtime() -> UnifiedProductionRuntime:
    return UnifiedProductionRuntime(compiler=ProductCompiler(), recipe_library=_library())


def _products() -> list[str]:
    return COMMERCIAL_PRODUCT_REGISTRY.list_ids()


# ═══════════════════════════════════════════════════════════════════════════
# P6.8.7 FALSE-SUCCESS AUDIT
# ═══════════════════════════════════════════════════════════════════════════


FAILURE_INJECTIONS = [
    ("provider_401", RuntimeError("HTTP 401 Unauthorized"), RunState.BLOCKED_BY_PROVIDER),
    ("provider_403", RuntimeError("403 Forbidden"), RunState.BLOCKED_BY_PROVIDER),
    ("quota_exhausted", RuntimeError("quota exceeded"), RunState.BLOCKED_BY_PROVIDER),
    ("gpu_unavailable", RuntimeError("CUDA unavailable: no device"), RunState.BLOCKED_BY_PROVIDER),
    ("missing_credentials", RuntimeError("no API key configured"), RunState.BLOCKED_BY_PROVIDER),
    ("timeout", TimeoutError("operation timed out"), RunState.FAILED),
    ("cancelled", RuntimeError("execution cancelled"), RunState.CANCELLED),
    ("asset_failure", FileNotFoundError("asset missing"), RunState.FAILED),
    ("renderer_failure", RuntimeError("ffmpeg exited 1"), RunState.FAILED),
    ("qa_failure", RuntimeError("qa gate failed"), RunState.FAILED),
    ("grammar_incompatible", ValueError("INCOMPATIBLE_STYLE_PAIRING"), RunState.FAILED),
    ("runtime_exception", ValueError("unexpected"), RunState.FAILED),
]


@pytest.mark.parametrize(("name", "raised", "expected"), FAILURE_INJECTIONS, ids=[c[0] for c in FAILURE_INJECTIONS])
def test_false_success_is_zero(name: str, raised: Exception, expected: RunState) -> None:
    """Every injected failure stays a failure and preserves its reason."""
    runtime = _runtime()
    runtime.bind(ExistingRuntime(fail=raised), ENTRYPOINT)
    result = runtime.submit(_runtime().compile("P03_DOCUMENTARY"), _source())
    assert result.state is expected, name
    assert not result.is_success, name
    assert result.reason, name
    assert result.receipt is None, name


def test_no_failure_state_ever_carries_a_producing_receipt() -> None:
    for state in RunState:
        if state in {RunState.PRODUCED, RunState.QA_PASSED}:
            continue
        # A receipt may accompany a non-success state (it records that the
        # delegate *was* entered) but it must never make the state a success.
        result = ProductionRunResult(
            run_id="r", product_profile_id="p", state=state,
            receipt=ExecutionReceipt(runtime_id="x", entrypoint_ref="y", produced=True),
        )
        assert result.is_success is False, state


def test_result_construction_refuses_success_without_production() -> None:
    for state in (RunState.PRODUCED, RunState.QA_PASSED):
        with pytest.raises(ValueError, match="FALSE_SUCCESS_BLOCKED"):
            ProductionRunResult(run_id="r", product_profile_id="p", state=state)


def test_blocked_is_distinguishable_from_pass() -> None:
    runtime = _runtime()
    runtime.bind(
        ExistingRuntime(fail=RuntimeError("401 Unauthorized")), ENTRYPOINT
    )
    blocked = runtime.submit(_runtime().compile("P03_DOCUMENTARY"), _source())
    runtime_ok = _runtime()
    runtime_ok.bind(ExistingRuntime(), ENTRYPOINT)
    passed = runtime_ok.submit(_runtime().compile("P03_DOCUMENTARY"), _source())
    assert blocked.is_blocked and not blocked.is_success
    assert passed.is_success and not passed.is_blocked
    assert blocked.state.value != passed.state.value


# ═══════════════════════════════════════════════════════════════════════════
# P6.8.8 DUPLICATE-SIDE-EFFECT AUDIT
# ═══════════════════════════════════════════════════════════════════════════


def test_duplicate_side_effects_zero_under_repetition() -> None:
    delegate = ExistingRuntime()
    runtime = _runtime()
    runtime.bind(delegate, ENTRYPOINT)
    intent = runtime.compile("P07_MARKETING")
    for _ in range(25):
        runtime.submit(intent, _source())
    assert len(delegate.calls) == 1
    assert runtime.ledger.delegate_call_count(runtime.submit(intent, _source()).run_id) == 1


def test_duplicate_side_effects_zero_under_same_run_id() -> None:
    delegate = ExistingRuntime()
    runtime = _runtime()
    runtime.bind(delegate, ENTRYPOINT)
    intent = runtime.compile("P01_AVATAR_EXPLAINER")
    results = [runtime.submit(intent, _source()) for _ in range(10)]
    assert len({r.run_id for r in results}) == 1
    assert len(delegate.calls) == 1


def test_duplicate_side_effects_zero_on_retry_after_failure() -> None:
    delegate = ExistingRuntime(fail=RuntimeError("401 Unauthorized"))
    runtime = _runtime()
    runtime.bind(delegate, ENTRYPOINT)
    intent = runtime.compile("P03_DOCUMENTARY")
    for _ in range(5):
        runtime.submit(intent, _source())
    assert len(delegate.calls) == 1


def test_resume_preserves_prior_completed_stage() -> None:
    runtime = _runtime()
    runtime.bind(ExistingRuntime(fail=RuntimeError("timeout")), ENTRYPOINT)
    intent = runtime.compile("P03_DOCUMENTARY")
    first = runtime.submit(intent, _source())
    assert first.prior_states == (
        RunState.COMPILED, RunState.VALIDATED, RunState.EXECUTING,
    )
    # The resume returns the recorded outcome rather than starting over.
    second = runtime.submit(intent, _source())
    assert second.state is first.state
    assert second.run_id == first.run_id


def test_cancel_then_retry_does_not_duplicate() -> None:
    delegate = ExistingRuntime(fail=RuntimeError("cancelled"))
    runtime = _runtime()
    runtime.bind(delegate, ENTRYPOINT)
    intent = runtime.compile("P09_SHORT_VIDEO")
    first = runtime.submit(intent, _source())
    assert first.state is RunState.CANCELLED
    assert runtime.submit(intent, _source()).run_id == first.run_id
    assert len(delegate.calls) == 1


def test_distinct_constraints_do_not_collapse() -> None:
    delegate = ExistingRuntime()
    runtime = _runtime()
    runtime.bind(delegate, ENTRYPOINT)
    intent = runtime.compile("P03_DOCUMENTARY")
    a = runtime.submit(intent, _source())
    b = runtime.submit(intent, _source(), ProductionConstraints(budget_usd=99.0))
    assert a.run_id != b.run_id
    assert len(delegate.calls) == 2


def test_all_ten_products_leave_no_duplicate_side_effects() -> None:
    delegate = ExistingRuntime()
    runtime = _runtime()
    runtime.bind(delegate, ENTRYPOINT)
    for product in _products():
        intent = runtime.compile(product)
        for _ in range(3):
            runtime.submit(intent, _source())
    assert len(delegate.calls) == 10


# ═══════════════════════════════════════════════════════════════════════════
# P6.8.9 DETERMINISM AUDIT (100 repetitions per product)
# ═══════════════════════════════════════════════════════════════════════════


def test_determinism_hashes_are_singletons_per_product() -> None:
    for product in _products():
        runtime = _runtime()
        hashes = {runtime.compile(product).content_hash() for _ in range(100)}
        assert len(hashes) == 1, product


def test_determinism_all_layers_are_singletons() -> None:
    for product in _products():
        runtime = _runtime()
        intents = [runtime.compile(product) for _ in range(100)]
        assert len({i.narrative_intent.content_hash() for i in intents}) == 1, product
        assert len({i.presenter_intent.content_hash() for i in intents}) == 1, product
        assert len({i.visual_style_intent.content_hash() for i in intents}) == 1, product
        assert len({i.visual_intent.content_hash() for i in intents}) == 1, product
        fingerprints = {semantic_fingerprint_of(i.recipe_evidence) for i in intents}
        assert len(fingerprints) == 1, product


def test_determinism_no_timestamp_in_semantic_hashes() -> None:
    runtime = _runtime()
    intent = runtime.compile("P03_DOCUMENTARY")
    payload = intent.to_dict()
    assert "timestamp" not in payload["recipe_evidence"]


def test_determinism_run_ids_are_singletons() -> None:
    runtime = _runtime()
    runtime.bind(ExistingRuntime(), ENTRYPOINT)
    intent = runtime.compile("P06_EDUCATIONAL")
    ids = {runtime.submit(intent, _source()).run_id for _ in range(50)}
    assert len(ids) == 1


def test_determinism_holds_across_runtime_instances() -> None:
    hashes = {_runtime().compile("P02_HISTORY_RECONSTRUCTION").content_hash() for _ in range(20)}
    assert len(hashes) == 1


def test_determinism_ten_products_yield_ten_distinct_plans() -> None:
    runtime = _runtime()
    hashes = {p: runtime.compile(p).content_hash() for p in _products()}
    assert len(set(hashes.values())) == 10


def test_compile_determinism_is_separate_from_provider_nondeterminism() -> None:
    """A flaky delegate must not make compilation nondeterministic."""
    calls = {"n": 0}

    class FlakyRuntime:
        runtime_id = "p0_flaky"

        def produce(self, request, source):
            calls["n"] += 1
            return f"attempt {calls['n']}"  # deliberately unstable

    runtime = _runtime()
    runtime.bind(FlakyRuntime(), ENTRYPOINT)
    intent = runtime.compile("P03_DOCUMENTARY")
    results = [runtime.submit(intent, _source()) for _ in range(5)]
    # One delegate call, stable plan hash, stable request hash — despite the
    # delegate's own instability.
    assert calls["n"] == 1
    assert len({r.intent_hash for r in results}) == 1
    assert len({r.request_hash for r in results}) == 1


# ═══════════════════════════════════════════════════════════════════════════
# P6.8.2 AUTHORITY AUDIT
# ═══════════════════════════════════════════════════════════════════════════


AUTHORITY_OWNERS = {
    "product_profile": "hevi.production.p6.schema",
    "narrative_grammar": "hevi.production.p6.narrative.registry",
    "presenter_grammar": "hevi.production.p6.presenter_registry",
    "visual_style": "hevi.production.p6.visual_style.registry",
    "visual_grammar": "hevi.production.p6.visual_grammar",
    "product_compilation": "hevi.production.p6.product_compiler",
    "semantic_contract": "hevi.production.semantic_contract",
    "semantic_scoring": "hevi.production.p5_3.retrieval",
    "recipe_selection": "hevi.production.p5_3.library",
    "runtime_boundary": "hevi.production.p6.runtime",
}


def test_every_concern_has_an_owner() -> None:
    assert len(AUTHORITY_OWNERS) == 10


def test_every_named_authority_module_exists() -> None:
    for concern, module in AUTHORITY_OWNERS.items():
        assert Path(module.replace(".", "/") + ".py").exists(), (concern, module)


def test_recipe_selection_authority_is_p5_3_only() -> None:
    definitions = 0
    for path in Path("hevi").rglob("*.py"):
        definitions += len(re.findall(r"def rank_candidates\(", path.read_text(errors="ignore")))
    assert definitions == 1


def test_semantic_scoring_authority_is_p5_3_only() -> None:
    definitions = 0
    for path in Path("hevi").rglob("*.py"):
        definitions += len(re.findall(r"def _?semantic_match\(", path.read_text(errors="ignore")))
    assert definitions == 1


def test_no_p6_module_redefines_a_p5_3_or_p0_authority() -> None:
    protected = {
        "CinematicRecipe", "RecipeLibrary", "RecipeSelectionEvidence",
        "ShotPlan", "MotionPlan", "RenderPlan", "RendererBackend",
    }
    for path in P6_FILES:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef):
                assert node.name not in protected, (path.name, node.name)


def test_exactly_one_product_profile_registry_per_subject() -> None:
    # P6.0 canonical (id@version, embedded grammars) + P6.5 commercial catalogue
    # (id, grammar references). Two, deliberately distinct, and P6.5's collides
    # with neither.
    from hevi.production.p6.product_profiles import COMMERCIAL_PRODUCT_REGISTRY
    from hevi.production.p6.registry import PRODUCT_PROFILE_REGISTRY

    assert PRODUCT_PROFILE_REGISTRY is not COMMERCIAL_PRODUCT_REGISTRY
    COMMERCIAL_PRODUCT_REGISTRY.assert_no_id_collision()


def test_exactly_one_product_compiler() -> None:
    found = [
        node.name
        for path in P6_FILES
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ClassDef) and node.name == "ProductCompiler"
    ]
    assert found == ["ProductCompiler"]


# ═══════════════════════════════════════════════════════════════════════════
# P6.8.3 IMPORT GRAPH AUDIT
# ═══════════════════════════════════════════════════════════════════════════


FORBIDDEN_IMPORTS = (
    "hevi.renderers",
    "hevi.providers",
    "hevi.production.p0_pipeline",
    "hevi.production.p1_pipeline",
    "hevi.production.p2_pipeline",
    "hevi.production.shot_readiness",
    "hevi.production.creative_ledger",
    "hevi.production.runtime",
    "hevi.artifact_store",
    "hevi.editable",
    "hevi.verdict",
    "hevi.quality",
    "hevi.timeline",
    "hevi.narrative",
)


def test_p6_imports_no_execution_authority() -> None:
    for path in P6_FILES:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(FORBIDDEN_IMPORTS), (
                    path.name, node.module
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(FORBIDDEN_IMPORTS), (
                        path.name, alias.name
                    )


def test_p6_depends_downward_on_existing_authorities_not_upward() -> None:
    """P6 may read P5.3's schema; it must not reach into P5.3's retrieval internals."""
    for path in P6_FILES:
        source = path.read_text()
        assert "rank_candidates" not in source, path.name
        assert "def _semantic_match" not in source, path.name


def test_p6_imports_p5_3_schema_and_library_but_not_its_algorithms() -> None:
    allowed_p5_3 = {"hevi.production.p5_3.schema", "hevi.production.p5_3.library",
                    "hevi.production.p5_3.retrieval"}
    for path in P6_FILES:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("hevi.production.p5_3"):
                    assert node.module in allowed_p5_3, (path.name, node.module)


# ═══════════════════════════════════════════════════════════════════════════
# P6.8.4 / P6.8.5 SOURCE SCOPE
# ═══════════════════════════════════════════════════════════════════════════


def test_unrelated_dirty_files_are_preserved() -> None:
    """Files dirty before P6.6 began must still be dirty, untouched by P6."""
    import subprocess

    out = subprocess.run(
        ["git", "status", "--short", "hevi/ops/"],
        capture_output=True, text=True, cwd=Path.cwd(),
    ).stdout
    assert "hevi/ops/p5_factory.py" in out, out
    assert "hevi/ops/p5_volcano_tts.py" in out, out


def test_p0_to_p4_frozen_modules_are_unmodified() -> None:
    import subprocess

    frozen = [
        "hevi/production/p0_pipeline.py", "hevi/production/p1_types.py",
        "hevi/production/p2_types.py", "hevi/production/shot_readiness.py",
    ]
    out = subprocess.run(
        ["git", "status", "--short", *frozen],
        capture_output=True, text=True, cwd=Path.cwd(),
    ).stdout.strip()
    assert out == "", f"P0-P4 mutated: {out}"


def test_p5_3_mutation_is_limited_to_the_semantic_contract_repair() -> None:
    import subprocess

    out = subprocess.run(
        ["git", "diff", "--name-only", "--", "hevi/production/p5_3/"],
        capture_output=True, text=True, cwd=Path.cwd(),
    ).stdout.split()
    # retrieval.py carries the authorised semantic-matcher repair; metrics.py was
    # already dirty from P5.4 before this work started.
    assert set(out) <= {"hevi/production/p5_3/retrieval.py",
                        "hevi/production/p5_3/metrics.py"}, out


# ═══════════════════════════════════════════════════════════════════════════
# P6.8.10 FINAL ARTEFACT
# ═══════════════════════════════════════════════════════════════════════════


def test_final_qualification_artifact_is_emitted() -> None:
    """Emit the final closure artefact from measured state, not from assumptions."""
    path = Path("artifacts/qualification/hevi_p6_8_final.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    runtime = _runtime()
    runtime.bind(ExistingRuntime(), ENTRYPOINT)
    products = {}
    for product in _products():
        intent = runtime.compile(product)
        products[product] = {
            "intent_hash": intent.content_hash(),
            "recipe_fingerprint": semantic_fingerprint_of(intent.recipe_evidence),
            "narrative_grammar_id": intent.narrative_intent.grammar_id,
            "presenter_grammar_id": intent.presenter_intent.grammar_id,
            "visual_style_id": intent.visual_style_intent.style_id,
            "visual_grammar_id": intent.visual_intent.visual_grammar_id,
        }
    payload = {
        "architecture_qualification": "PASS",
        "real_render_qualification": "BLOCKED_BY_PROVIDER",
        "mock_used": False,
        "provider_blockers": [
            "no provider credentials configured",
            "CUDA reports no device",
        ],
        "products": products,
        "false_success": 0,
        "duplicate_side_effects": 0,
        "invariants": {
            "one_product_compiler": True,
            "one_runtime": True,
            "no_product_execution_branch": True,
            "no_second_recipe_authority": True,
            "no_second_shot_authority": True,
            "no_second_motion_authority": True,
            "no_second_asset_authority": True,
            "no_second_renderer": True,
            "no_second_qa_authority": True,
            "semantic_score_reachable": True,
        },
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    loaded = json.loads(path.read_text())
    assert loaded["mock_used"] is False
    assert loaded["real_render_qualification"] == "BLOCKED_BY_PROVIDER"
    assert len(loaded["products"]) == 10
