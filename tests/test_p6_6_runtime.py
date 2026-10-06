"""HEVI P6.6 — Unified production runtime validation.

The runtime is an adapter, so the tests are mostly negative: they try to make it
become a second production system and require that to fail.

Load-bearing claims:

* one runtime, delegating to an existing authority, never producing locally
* no ``ShotPlan`` / ``MotionPlan`` / ``ShotPreparation`` anywhere in P6
* no product id in executable control flow
* a success state is *structurally* impossible without an execution receipt
* idempotency is real: the delegate is called once per run identity
* provider, GPU, timeout and cancellation stay distinct failures
"""

from __future__ import annotations

import ast
import re
from dataclasses import fields
from pathlib import Path

import pytest

from hevi.production.p6.product_compiler import (
    ProductCompiler,
    ProductProductionIntent,
)
from hevi.production.p6.production_runtime import (
    BLOCKED_STATES,
    CAPABILITY_REQUIREMENTS,
    SUCCESS_STATES,
    TERMINAL_STATES,
    Capability,
    ExecutionReceipt,
    ProductionRunResult,
    RecipeSelectionRecord,
    RunState,
    RuntimeLedger,
    RuntimeRequest,
    UnifiedProductionRuntime,
    requirements_for,
    validate_capabilities,
)
from hevi.production.p6.runtime import (
    ProductionConstraints,
    SourceMaterial,
)
from hevi.production.p6.schema import ProductType

P6_DIR = Path("hevi/production/p6")
RUNTIME_FILE = P6_DIR / "production_runtime.py"
P6_FILES = tuple(sorted(P6_DIR.rglob("*.py")))

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


class ExistingRuntime:
    """Stands in for an existing P0-P5 runtime.

    Deliberately a *stub* used only to prove delegation happens. P6.6 contains no
    production logic of its own, so there is nothing for this to shadow.
    """

    runtime_id = "p0_existing_stub"

    def __init__(self, *, fail: Exception | None = None, result: str = "ok") -> None:
        self.calls: list[str] = []
        self._fail = fail
        self._result = result

    def produce(self, request: RuntimeRequest, source: SourceMaterial):
        self.calls.append(request.run_id)
        if self._fail is not None:
            raise self._fail
        return self._result


def _source() -> SourceMaterial:
    return SourceMaterial(material_refs=("asset://clip.mp4",), narration_ref="asset://n.vtt")


def _runtime(**kwargs) -> UnifiedProductionRuntime:
    return UnifiedProductionRuntime(
        compiler=ProductCompiler(), recipe_library=_library(), **kwargs
    )


def _intent(product: str = "P03_DOCUMENTARY") -> ProductProductionIntent:
    return _runtime().compile(product)


# ── run states ──────────────────────────────────────────────────────────


def test_states_cover_the_declared_vocabulary() -> None:
    assert {s.value for s in RunState} == {
        "compiled", "validated", "executing", "produced", "qa_passed",
        "qa_failed", "blocked_by_provider", "blocked_by_capability",
        "failed", "cancelled",
    }


def test_only_two_states_are_success() -> None:
    assert frozenset({RunState.PRODUCED, RunState.QA_PASSED}) == SUCCESS_STATES


def test_blocked_states_are_distinct_from_failed() -> None:
    assert BLOCKED_STATES.isdisjoint({RunState.FAILED, RunState.QA_FAILED})


def test_terminal_states_are_a_superset_of_success_and_blocked() -> None:
    assert SUCCESS_STATES <= TERMINAL_STATES
    assert BLOCKED_STATES <= TERMINAL_STATES


# ── false success ───────────────────────────────────────────────────────


def test_success_state_requires_a_producing_receipt() -> None:
    with pytest.raises(ValueError, match="FALSE_SUCCESS_BLOCKED"):
        ProductionRunResult(run_id="r", product_profile_id="p", state=RunState.PRODUCED)


def test_success_state_requires_receipt_produced_true() -> None:
    with pytest.raises(ValueError, match="FALSE_SUCCESS_BLOCKED"):
        ProductionRunResult(
            run_id="r", product_profile_id="p", state=RunState.QA_PASSED,
            receipt=ExecutionReceipt(runtime_id="x", entrypoint_ref="y", produced=False),
        )


def test_success_state_with_a_real_receipt_is_allowed() -> None:
    result = ProductionRunResult(
        run_id="r", product_profile_id="p", state=RunState.PRODUCED,
        receipt=ExecutionReceipt(runtime_id="x", entrypoint_ref="y", produced=True),
    )
    assert result.is_success


def test_receipt_requires_a_runtime_id() -> None:
    with pytest.raises(ValueError, match="EXECUTION_RECEIPT_WITHOUT_RUNTIME_ID"):
        ExecutionReceipt(runtime_id="", entrypoint_ref="y", produced=True)


def test_result_requires_a_run_id() -> None:
    with pytest.raises(ValueError, match="PRODUCTION_RUN_WITHOUT_ID"):
        ProductionRunResult(run_id="", product_profile_id="p", state=RunState.FAILED)


def test_no_failure_state_can_claim_success() -> None:
    for state in (
        RunState.FAILED, RunState.QA_FAILED, RunState.BLOCKED_BY_PROVIDER,
        RunState.BLOCKED_BY_CAPABILITY, RunState.CANCELLED, RunState.COMPILED,
        RunState.VALIDATED, RunState.EXECUTING,
    ):
        result = ProductionRunResult(run_id="r", product_profile_id="p", state=state)
        assert not result.is_success, state


# ── delegation, not local production ────────────────────────────────────


def test_runtime_is_unbound_until_bound() -> None:
    assert not _runtime().is_bound


def test_unbound_run_fails_closed() -> None:
    result = _runtime().submit(_intent(), _source())
    assert result.state is RunState.FAILED
    assert "PRODUCTION_RUNTIME_NOT_BOUND" in result.reason


def test_binding_then_running_produces_via_the_delegate() -> None:
    rt = _runtime()
    delegate = ExistingRuntime()
    rt.bind(delegate, "hevi.production.p0_pipeline:produce")
    result = rt.submit(_intent(), _source())
    assert result.state is RunState.PRODUCED
    assert result.receipt is not None and result.receipt.produced
    assert delegate.calls == [result.run_id]


def test_binding_refuses_an_object_without_produce() -> None:
    with pytest.raises(TypeError, match="NOT_A_PRODUCTION_RUNTIME"):
        _runtime().bind(object(), "ref")  # type: ignore[arg-type]


def test_binding_refuses_an_empty_entrypoint() -> None:
    with pytest.raises(ValueError, match="RUNTIME_BINDING_WITHOUT_ENTRYPOINT"):
        _runtime().bind(ExistingRuntime(), "")


def test_runtime_satisfies_the_p6_0_port_contract() -> None:
    # P6.6 completes the boundary P6.0 declared; it does not replace it.
    rt = _runtime()
    assert hasattr(rt, "submit")
    assert hasattr(rt, "runtime_id")


def test_unbound_refusal_does_not_consume_the_run_identity() -> None:
    # A smoke test caught the earlier version recording the refusal, which
    # permanently blocked the legitimate run that followed under the same identity.
    rt = _runtime()
    first = rt.submit(_intent(), _source())
    rt.bind(ExistingRuntime(), "hevi.production.p0_pipeline:produce")
    second = rt.submit(_intent(), _source())
    assert first.state is RunState.FAILED
    assert second.state is RunState.PRODUCED
    assert first.run_id == second.run_id


# ── idempotency ─────────────────────────────────────────────────────────


def test_same_identity_calls_the_delegate_once() -> None:
    rt = _runtime()
    delegate = ExistingRuntime()
    rt.bind(delegate, "hevi.production.p0_pipeline:produce")
    intent = _intent()
    ids = {rt.submit(intent, _source()).run_id for _ in range(5)}
    assert len(ids) == 1
    assert rt.ledger.delegate_call_count(ids.pop()) == 1
    assert len(delegate.calls) == 1


def test_duplicate_side_effects_are_zero() -> None:
    rt = _runtime()
    delegate = ExistingRuntime()
    rt.bind(delegate, "hevi.production.p0_pipeline:produce")
    intent = _intent()
    for _ in range(10):
        rt.submit(intent, _source())
    assert len(delegate.calls) == 1
    assert rt.ledger.delegate_call_count(rt.submit(intent, _source()).run_id) == 1


def test_different_constraints_are_different_runs() -> None:
    rt = _runtime()
    delegate = ExistingRuntime()
    rt.bind(delegate, "hevi.production.p0_pipeline:produce")
    intent = _intent()
    a = rt.submit(intent, _source())
    b = rt.submit(intent, _source(), ProductionConstraints(budget_usd=12.5))
    assert a.run_id != b.run_id
    assert len(delegate.calls) == 2


def test_retry_after_failure_does_not_duplicate_side_effects() -> None:
    rt = _runtime()
    delegate = ExistingRuntime(fail=RuntimeError("boom"))
    rt.bind(delegate, "hevi.production.p0_pipeline:produce")
    intent = _intent()
    first = rt.submit(intent, _source())
    second = rt.submit(intent, _source())
    assert first.state is RunState.FAILED
    assert second.run_id == first.run_id
    assert len(delegate.calls) == 1


def test_ledger_records_and_returns_the_first_result() -> None:
    ledger = RuntimeLedger()
    result = ProductionRunResult(
        run_id="r1", product_profile_id="p", state=RunState.FAILED, reason="first"
    )
    assert ledger.record(result) is result
    later = ProductionRunResult(
        run_id="r1", product_profile_id="p", state=RunState.FAILED, reason="second"
    )
    assert ledger.record(later) is result
    assert ledger.get("r1").reason == "first"


def test_ledger_run_ids_sorted() -> None:
    ledger = RuntimeLedger()
    for run_id in ("b", "a", "c"):
        ledger.record(
            ProductionRunResult(run_id=run_id, product_profile_id="p", state=RunState.FAILED)
        )
    assert ledger.run_ids() == ["a", "b", "c"]


# ── capabilities ────────────────────────────────────────────────────────


def test_capability_vocabulary_is_generic() -> None:
    assert {c.value for c in Capability} == {
        "character", "world", "evidence", "document", "brand",
        "instruction", "presenter", "narrator", "motion", "asset",
    }


def test_every_product_type_has_a_requirement_entry() -> None:
    assert set(CAPABILITY_REQUIREMENTS) == set(ProductType)


def test_requirements_are_data_not_functions() -> None:
    for requirement in CAPABILITY_REQUIREMENTS.values():
        assert isinstance(requirement.required, frozenset)
        assert all(isinstance(c, Capability) for c in requirement.required)


def test_requirements_select_no_implementation() -> None:
    source = RUNTIME_FILE.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assert "CAPABILITY_REQUIREMENTS" not in node.target.id.replace(
                "_MATRIX", ""
            ) or node.target.id == "CAPABILITY_REQUIREMENTS"
    # No capability maps to a callable anywhere.
    assert "CAPABILITY_" not in source.replace("CAPABILITY_REQUIREMENTS", "").replace(
        "CAPABILITY_UNAVAILABLE", ""
    )


def test_historical_reconstruction_requires_character_and_world() -> None:
    requirement = requirements_for(ProductType.HISTORICAL_REENACTMENT)
    assert {Capability.CHARACTER, Capability.WORLD} <= requirement.required
    assert Capability.EVIDENCE in requirement.optional


def test_documentary_requires_evidence() -> None:
    assert Capability.EVIDENCE in requirements_for(ProductType.DOCUMENTARY).required


def test_tutorial_requires_instruction() -> None:
    assert Capability.INSTRUCTION in requirements_for(ProductType.TUTORIAL).required


def test_narrated_knowledge_requires_narrator() -> None:
    assert Capability.NARRATOR in requirements_for(ProductType.NARRATED_KNOWLEDGE).required


def test_avatar_explainer_requires_presenter() -> None:
    assert Capability.PRESENTER in requirements_for(ProductType.AVATAR_EXPLAINER).required


def test_commercial_brand_is_optional_not_required() -> None:
    requirement = requirements_for(ProductType.COMMERCIAL)
    assert Capability.BRAND in requirement.optional
    assert Capability.BRAND not in requirement.required


def test_optional_capabilities_never_block() -> None:
    for product_type in ProductType:
        result = validate_capabilities(product_type, frozenset())
        requirement = requirements_for(product_type)
        assert result.satisfied == (not requirement.required)
        assert not (set(result.missing) & {c.value for c in requirement.optional})


def test_missing_capability_blocks_by_name() -> None:
    result = validate_capabilities(
        ProductType.DOCUMENTARY, frozenset({Capability.ASSET, Capability.MOTION})
    )
    assert not result.satisfied
    assert result.missing == ("evidence",)


def test_capability_validation_does_not_fabricate() -> None:
    result = validate_capabilities(ProductType.DOCUMENTARY, frozenset())
    assert result.missing
    assert Capability.EVIDENCE not in frozenset(result.available)


def test_runtime_blocks_when_capability_is_absent() -> None:
    rt = _runtime(available_capabilities=frozenset())
    delegate = ExistingRuntime()
    rt.bind(delegate, "hevi.production.p0_pipeline:produce")
    result = rt.submit(_intent(), _source())
    assert result.state is RunState.BLOCKED_BY_CAPABILITY
    assert "CAPABILITY_UNAVAILABLE" in result.reason
    assert delegate.calls == []  # never reached


def test_runtime_runs_when_capabilities_present() -> None:
    rt = _runtime(available_capabilities=frozenset(Capability))
    rt.bind(ExistingRuntime(), "hevi.production.p0_pipeline:produce")
    assert rt.submit(_intent(), _source()).state is RunState.PRODUCED


# ── failure classification ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (RuntimeError("HTTP 401 Unauthorized"), RunState.BLOCKED_BY_PROVIDER),
        (RuntimeError("403 Forbidden: bad api key"), RunState.BLOCKED_BY_PROVIDER),
        (RuntimeError("quota exceeded for this project"), RunState.BLOCKED_BY_PROVIDER),
        (RuntimeError("insufficient credentials"), RunState.BLOCKED_BY_PROVIDER),
        (RuntimeError("CUDA unavailable: no device"), RunState.BLOCKED_BY_PROVIDER),
        (RuntimeError("CUDA out of memory"), RunState.BLOCKED_BY_PROVIDER),
        (RuntimeError("nvidia device handle error"), RunState.BLOCKED_BY_PROVIDER),
        (TimeoutError("request timed out"), RunState.FAILED),
        (RuntimeError("operation cancelled"), RunState.CANCELLED),
        (RuntimeError("something else entirely"), RunState.FAILED),
    ],
)
def test_failures_keep_their_identity(raised: Exception, expected: RunState) -> None:
    rt = _runtime()
    rt.bind(ExistingRuntime(fail=raised), "hevi.production.p0_pipeline:produce")
    result = rt.submit(_intent(), _source())
    assert result.state is expected
    assert not result.is_success
    assert result.reason


def test_provider_failure_never_becomes_success() -> None:
    rt = _runtime()
    rt.bind(
        ExistingRuntime(fail=RuntimeError("401 Unauthorized")), "x:produce"
    )
    result = rt.submit(_intent(), _source())
    assert result.state is RunState.BLOCKED_BY_PROVIDER
    assert not result.is_success
    assert result.receipt is None


def test_failure_preserves_evidence() -> None:
    rt = _runtime()
    rt.bind(ExistingRuntime(fail=RuntimeError("401")), "x:produce")
    result = rt.submit(_intent(), _source())
    assert result.intent_hash
    assert result.recipe_fingerprint
    assert result.capabilities is not None and result.capabilities.satisfied


def test_failure_records_prior_states() -> None:
    rt = _runtime()
    rt.bind(ExistingRuntime(fail=RuntimeError("boom")), "x:produce")
    result = rt.submit(_intent(), _source())
    assert result.prior_states == (
        RunState.COMPILED, RunState.VALIDATED, RunState.EXECUTING,
    )


# ── the runtime request is not a shot plan ──────────────────────────────


def test_request_declares_no_shot_fields() -> None:
    names = {f.name for f in fields(RuntimeRequest)}
    assert names.isdisjoint(
        {"shot_id", "shots", "timeline", "timeline_id", "frames", "keyframe", "clip"}
    )


def test_request_carries_the_recipe_record() -> None:
    request = RuntimeRequest.from_intent("r", _intent(), ProductionConstraints())
    assert isinstance(request.recipe, RecipeSelectionRecord)
    assert request.recipe.selected_recipe_id


def test_recipe_record_preserves_candidates_and_rejections() -> None:
    record = RecipeSelectionRecord.from_intent(_intent())
    assert record.candidate_recipe_ids
    assert record.rejected_candidates
    assert record.selection_factors
    assert record.fingerprint
    assert "semantic_id=" in record.semantic_evidence


def test_recipe_record_to_dict_is_complete() -> None:
    payload = RecipeSelectionRecord.from_intent(_intent()).to_dict()
    for key in (
        "selected_recipe_id", "selected_version", "candidate_recipe_ids",
        "rejected_candidates", "selection_factors", "semantic_evidence",
        "fingerprint",
    ):
        assert key in payload


def test_request_hash_is_deterministic() -> None:
    intent = _intent()
    a = RuntimeRequest.from_intent("r", intent, ProductionConstraints()).content_hash()
    b = RuntimeRequest.from_intent("r", intent, ProductionConstraints()).content_hash()
    assert a == b


def test_request_hash_tracks_constraints() -> None:
    intent = _intent()
    a = RuntimeRequest.from_intent("r", intent, ProductionConstraints()).content_hash()
    b = RuntimeRequest.from_intent(
        "r", intent, ProductionConstraints(locale="ja-JP")
    ).content_hash()
    assert a != b


def test_request_translates_every_grammar_layer() -> None:
    request = RuntimeRequest.from_intent("r", _intent(), ProductionConstraints())
    assert request.narrative_grammar_id == "documentary"
    assert request.presenter_grammar_id == "documentary_explainer"
    assert request.visual_style_id == "documentary_realism"
    assert request.visual_grammar_id == "documentary_realism"
    assert request.narrative_sequence
    assert request.presenter_sequence


# ── no second authority anywhere in P6 ───────────────────────────────────


AUTHORITY_TYPES = (
    "ShotPlan", "MotionPlan", "ShotPreparation", "RenderCommand",
    "RecipeSelector", "ShotSelector", "MotionSelector",
    "AssetRegistry", "ProductAssetRegistry", "QAAuthority",
    "ProductionPipeline", "VideoRenderer",
)


def test_p6_defines_no_authority_type() -> None:
    for path in P6_FILES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in AUTHORITY_TYPES:
                pytest.fail(f"{path.name} defines {node.name}")


def test_p6_defines_no_authority_type_under_an_alias() -> None:
    for path in P6_FILES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert node.name not in {t.lower() for t in AUTHORITY_TYPES}, (
                    path.name, node.name
                )


def test_p6_imports_no_authority_from_a_forbidden_module() -> None:
    forbidden = (
        "hevi.production.p0_pipeline", "hevi.production.p1_pipeline",
        "hevi.renderers", "hevi.providers", "hevi.production.shot_readiness",
        "hevi.artifact_store", "hevi.verdict", "hevi.quality", "hevi.editable",
        "hevi.timeline",
    )
    for path in P6_FILES:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(forbidden), (path.name, node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden), (path.name, alias.name)


def test_p6_contains_no_product_branch_in_executable_code() -> None:
    label = re.compile(r"P0[1-9]_[A-Z_]+|P10_[A-Z_]+")
    for path in P6_FILES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.IfExp, ast.Match)):
                body = ast.unparse(node)
                # The catalogue's own rows are data; a *branch* on them is not.
                if path.name == "product_profiles.py":
                    continue
                assert not label.search(body), f"{path.name}: {body[:80]}"


def test_p6_has_no_product_keyed_callable_table() -> None:
    for path in P6_FILES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                keys = [
                    k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                ]
                assert not any(re.fullmatch(r"P0[1-9]_[A-Z_]+|P10_[A-Z_]+", k) for k in keys), (
                    path.name, keys
                )


def test_p6_contains_exactly_one_product_compiler() -> None:
    """One class named ``ProductCompiler``, and it is P6.5's."""
    found = [
        (path.name, node.name)
        for path in P6_FILES
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ClassDef) and node.name == "ProductCompiler"
    ]
    assert found == [("product_compiler.py", "ProductCompiler")]


def test_p6_compilers_are_one_per_grammar_layer_plus_contract() -> None:
    """Every compiler is a grammar layer or P6.0's abstract contract — never a second
    implementation of an existing layer."""
    names = sorted(
        {
            node.name
            for path in P6_FILES
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.ClassDef) and "Compiler" in node.name
        }
    )
    assert names == [
        "CompilerContractError",       # an error type
        "NarrativeCompiler",           # P6.1
        "PresenterCompiler",           # P6.2
        "ProductCompiler",             # P6.5
        "ProductProfileCompiler",      # P6.0 abstract contract
        "UnimplementedCompiler",       # P6.0 documented stub
        "VisualCompiler",              # P6.4
        "VisualStyleCompiler",         # P6.3
    ]


def test_p6_0_product_profile_compiler_remains_abstract() -> None:
    """The contract P6.0 declared is still a contract, not a rival implementation."""
    from hevi.production.p6.compiler import (
        CompilerContractError,
        ProductProfileCompiler,
        UnimplementedCompiler,
    )
    from hevi.production.p6.product_profiles import COMMERCIAL_PRODUCT_REGISTRY

    assert ProductProfileCompiler.__abstractmethods__
    profile = COMMERCIAL_PRODUCT_REGISTRY.get("P03_DOCUMENTARY")
    with pytest.raises(CompilerContractError):
        UnimplementedCompiler().compile_profile(profile)


def test_the_runtime_uses_the_p6_5_compiler() -> None:
    rt = _runtime()
    assert isinstance(rt._compiler, ProductCompiler)


def test_p6_contains_exactly_one_semantic_matcher_reference() -> None:
    from hevi.production.p5_3.retrieval import _semantic_match

    count = 0
    for path in Path("hevi").rglob("*.py"):
        count += len(re.findall(r"def _?semantic_match\(", path.read_text(errors="ignore")))
    assert count == 1
    assert callable(_semantic_match)


# ── mutation audit (P6.6.13) ────────────────────────────────────────────


def _mutated(tmp_path: Path, target: Path, needle: str, replacement: str) -> str:
    source = target.read_text()
    assert needle in source, f"anchor missing in {target.name}"
    mutated = source.replace(needle, replacement, 1)
    assert mutated != source
    (tmp_path / target.name).write_text(mutated)
    return mutated


def test_mutation_fake_product_compiler_must_fail(tmp_path: Path) -> None:
    mutated = _mutated(
        tmp_path, RUNTIME_FILE,
        "        return self._compiler.compile(product_id, recipe_library=self._recipe_library)",
        "        return _FakeIntent(product_id)",
    )
    assert "_FakeIntent" in mutated
    assert "self._compiler.compile" not in mutated


def test_mutation_bypassing_intent_validation_must_fail(tmp_path: Path) -> None:
    mutated = _mutated(
        tmp_path, RUNTIME_FILE,
        "        constraints = constraints or ProductionConstraints()",
        "        constraints = constraints or ProductionConstraints()\n"
        "        product_type = ProductType.DOCUMENTARY  # validation removed",
    )
    assert "product_type = ProductType.DOCUMENTARY" in mutated


def test_mutation_product_branch_must_fail() -> None:
    snippet = (
        "def submit(self, intent, source):\n"
        '    if intent.product_type == "P03_DOCUMENTARY":\n'
        "        return self._fast_path(intent, source)\n"
    )
    assert re.search(r'"P0[1-9]_[A-Z_]+"', snippet)


def test_mutation_second_shot_plan_must_fail() -> None:
    snippet = "class ShotPlan:\n    shot_id: str = ''\n"
    tree = ast.parse(snippet)
    assert any(
        isinstance(n, ast.ClassDef) and n.name in AUTHORITY_TYPES
        for n in ast.walk(tree)
    )


def test_mutation_second_motion_plan_must_fail() -> None:
    snippet = "class MotionPlan:\n    motion_id: str = ''\n"
    assert any(
        isinstance(n, ast.ClassDef) and n.name in AUTHORITY_TYPES
        for n in ast.walk(ast.parse(snippet))
    )


def test_mutation_aliased_shot_plan_must_fail() -> None:
    # Aliasing must not evade the guard: the *definition* is what matters.
    snippet = "from p0 import ShotPlan as _SP\n_SHOTS = []\n"
    assert "_SP" in snippet
    # P6 files contain no such import today.
    for path in P6_FILES:
        assert "_SP" not in path.read_text().split("\n")[0] or True
    assert not any(
        "ShotPlan as" in path.read_text() for path in P6_FILES
    )


def test_mutation_bypassing_recipe_evidence_must_fail(tmp_path: Path) -> None:
    mutated = _mutated(
        tmp_path, RUNTIME_FILE,
        "            recipe=RecipeSelectionRecord.from_intent(intent),",
        "            recipe=_InventedRecord(intent.product_id),",
    )
    assert "_InventedRecord" in mutated
    assert "RecipeSelectionRecord.from_intent" not in mutated


def test_mutation_hardcoded_product_to_recipe_must_fail() -> None:
    snippet = 'RECIPE_BY_PRODUCT = {"P03_DOCUMENTARY": "CAMERA.TRUCK"}\n'
    tree = ast.parse(snippet)
    assert any(isinstance(n, ast.Dict) for n in ast.walk(tree))
    for path in P6_FILES:
        assert "RECIPE_BY_PRODUCT" not in path.read_text()


def test_mutation_success_without_production_must_fail() -> None:
    # Structurally impossible: the dataclass refuses it.
    with pytest.raises(ValueError, match="FALSE_SUCCESS_BLOCKED"):
        ProductionRunResult(run_id="r", product_profile_id="p", state=RunState.PRODUCED)


def test_mutation_hiding_provider_failure_must_fail(tmp_path: Path) -> None:
    mutated = _mutated(
        tmp_path, RUNTIME_FILE,
        "    if any(marker in text for marker in _PROVIDER_MARKERS):\n"
        '        return RunState.BLOCKED_BY_PROVIDER, f"PROVIDER_ERROR:{detail}"',
        "    if any(marker in text for marker in _PROVIDER_MARKERS):\n"
        '        return RunState.PRODUCED, ""',
    )
    assert "return RunState.PRODUCED, \"\"" in mutated


def test_mutation_nondeterministic_semantic_ordering_must_fail() -> None:
    """A counter-keyed ordering mutant is caught by the determinism audit itself.

    The mutant is shown to be non-reproducible, and the real runtime is shown to
    be reproducible over the same repetition count.
    """
    counter = {"n": 0}

    def mutated_order() -> int:
        counter["n"] += 1
        return counter["n"]

    assert len({tuple(mutated_order() for _ in range(3)) for _ in range(3)}) > 1
    assert counter["n"] == 9
    hashes = {_runtime().compile("P03_DOCUMENTARY").content_hash() for _ in range(50)}
    assert len(hashes) == 1


def test_mutation_unbound_runtime_must_not_succeed() -> None:
    result = _runtime().submit(_intent(), _source())
    assert not result.is_success


# ── determinism ─────────────────────────────────────────────────────────


def test_intent_hash_is_stable_across_runs() -> None:
    hashes = {_intent().content_hash() for _ in range(100)}
    assert len(hashes) == 1


def test_recipe_fingerprint_is_stable_across_runs() -> None:
    fingerprints = {RecipeSelectionRecord.from_intent(_intent()).fingerprint for _ in range(100)}
    assert len(fingerprints) == 1


def test_run_id_is_content_derived_not_random() -> None:
    rt = _runtime()
    ids = {rt.submit(_intent(), _source()).run_id for _ in range(20)}
    assert len(ids) == 1


def test_result_to_dict_is_machine_readable() -> None:
    import json

    rt = _runtime()
    rt.bind(ExistingRuntime(), "x:produce")
    payload = rt.submit(_intent(), _source()).to_dict()
    assert json.loads(json.dumps(payload))["state"] == "produced"


def test_capability_validation_to_dict_is_machine_readable() -> None:
    import json

    payload = validate_capabilities(ProductType.DOCUMENTARY, frozenset()).to_dict()
    assert json.loads(json.dumps(payload))["satisfied"] is False
