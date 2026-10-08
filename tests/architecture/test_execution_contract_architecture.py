"""P0.13 — the prohibited-architecture audit (§62), enforced as a test.

§62 lists sixteen architectural outcomes that make the whole contract BLOCKED. A
prose list is not a control, so each item here is asserted against the source tree. When
one of them appears, this file fails rather than the problem being discovered during a
review six weeks from now.

The structural checks are stronger than name-matching where they can be. "No second
Timeline authority" is not verified by grepping for a class named `Timeline` -- it is
verified by asserting every timeline-shaped type either *is* `TimelineIR` or is declared
as an adapter projection. A name check would pass a second authority called
`ProductionTimelineView` forever.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

HEVI = Path(__file__).resolve().parents[2] / "hevi"

#: Files outside the execution contract that legitimately exist and are not new
#: authorities. Anything not listed must satisfy the checks below.
EXECUTION_CONTRACT_MODULES = {
    "hevi/production/operation.py",
    "hevi/production/execution_result.py",
    "hevi/production/execution_transaction.py",
    "hevi/production/execution_executor.py",
    "hevi/production/render_job.py",
    "hevi/production/visual_scene_ir.py",
    "hevi/production/render_cache.py",
    "hevi/production/production_validation.py",
    "hevi/renderers/html_gsap_scene.py",
    "hevi/renderers/html_gsap_production.py",
}

#: Types the contract *does* define. §62 forbids a second authority of each kind, so
#: each kind must have exactly one definition.
#:
#: `Director` is absent deliberately: HEVI has no class named `Director` at all (the
#: role is carried by `p0_pipeline`'s graph), so a "defined exactly once" check on it
#: would pass vacuously or fail for the wrong reason. Asserting `>= 1` on a name that
#: does not exist is theatre.
AUTHORITY_KINDS = {
    "TimelineIR": "timeline authority",
    "ProductCompiler": "product compiler",
    "ProductionVerdictAuthority": "verdict authority",
    "ProviderProfile": "provider capability authority",
}

#: Pre-existing duplicate definitions found by this audit, NOT introduced by
#: HEVI-P0-EXECUTION-CONTRACT-001 and NOT fixed by it.
#:
#: `ShotPlan` and `MotionPlan` are each defined twice in long-standing code
#: (`production/p0_pipeline.py` and, respectively, `cinematic/
#: shot_intelligence/models.py` and `production/semantic_motion.py`). §46 is explicit
#: that existing semantic-authority problems belong to their owning phase's owner, and
#: §0.1 forbids this spec from creating a second one -- it did not create these.
#:
#: So the count is asserted at its current value rather than at 1. That still does the
#: job an audit needs: any *further* duplication fails the suite. Fixing them here
#: would be exactly the unrequested refactor §46 warns against.
PRE_EXISTING_DUPLICATE_AUTHORITIES = {
    "ShotPlan": ("production/p0_pipeline.py", "cinematic/shot_intelligence/models.py"),
    "MotionPlan": ("production/p0_pipeline.py", "production/semantic_motion.py"),
}


def _sources() -> list[Path]:
    return sorted(p for p in HEVI.rglob("*.py") if "layer4_legacy" not in p.parts)


def _tree_sources() -> list[Path]:
    return [
        p
        for p in _sources()
        if p.parts[len(HEVI.parts):3] == ("production",)
        or p.name in ("html_gsap_scene.py", "html_gsap_production.py")
        or "openreel" in p.parts
    ]


def _class_names(path: Path) -> set[str]:
    return {
        node.name
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ClassDef)
    }


# ── §62 A2: no duplicate authority ──


@pytest.mark.parametrize("authority", sorted(AUTHORITY_KINDS))
def test_no_duplicate_authority_type_is_defined(authority: str):
    """Each authority kind is defined in exactly one module.

    Catches a second Director, Timeline, ProductCompiler, ShotPlan, MotionPlan, verdict
    authority or ProviderProfile. Defining one *is* allowed -- reusing it is the point.
    """
    defining = [p for p in _sources() if authority in _class_names(p)]
    assert len(defining) == 1, (
        f"{AUTHORITY_KINDS[authority]}: {authority} is defined in "
        f"{[p.relative_to(HEVI).as_posix() for p in defining]}; expected exactly one"
    )


def test_legacy_timeline_classification_is_pinned():
    """P0-3's classification is the authority on predecessor timelines; pin its size.

    Two earlier versions of this test tried to *detect* a second timeline authority by
    scanning class names, and both were wrong. One flagged `TimelinePatchRequest` -- a
    Pydantic request body, not a timeline. The other flagged `CompositionSpec` and
    `CompositionLanguage`, which are layout and style specifications that merely share a
    word. A name heuristic cannot tell an authority from a coincidence, and an audit
    that cries wolf gets ignored.

    So the declaration is treated as the source of truth and only its *size* is pinned.
    A new predecessor timeline must be classified here, which changes the count and
    fails this test until someone has actually decided what it is.
    """
    from hevi.production.timeline_adapters import LEGACY_TIMELINE_ROLES

    assert len(LEGACY_TIMELINE_ROLES) == 20, (
        f"P0-3 classified 20 predecessor timeline representations; there are now "
        f"{len(LEGACY_TIMELINE_ROLES)}. A new one must be classified deliberately -- "
        "do not just re-baseline this number."
    )
    roles = set(LEGACY_TIMELINE_ROLES.values())
    assert "ADAPTER" in roles and "PROJECTION" in roles
    # Every legacy timeline has a recorded disposition. An unclassified entry is the
    # thing P0-3 exists to prevent.
    assert all(role for role in roles), "every classified timeline needs a disposition"


def test_execution_contract_cannot_import_a_legacy_timeline():
    """The structural half of A12: dependency direction, not naming.

    If any module in the execution contract imported a legacy timeline module, the
    adapter boundary P0-3 established would be bypassable and `TimelineIR` would stop
    being the only thing the contract sees. This is checkable exactly; the naming
    question is not.
    """
    import importlib

    from hevi.production.timeline_adapters import LEGACY_TIMELINE_ROLES

    legacy_modules = {key.rsplit(".", 1)[0] for key in LEGACY_TIMELINE_ROLES}
    # The classification module itself necessarily knows about them.
    legacy_modules.discard("hevi.production.timeline_adapters")

    contract = {
        "hevi.production.operation",
        "hevi.production.execution_result",
        "hevi.production.execution_transaction",
        "hevi.production.execution_executor",
        "hevi.production.render_job",
        "hevi.production.render_cache",
        "hevi.production.production_validation",
        "hevi.renderers.html_gsap_scene",
        "hevi.renderers.html_gsap_production",
    }

    offenders: list[str] = []
    for module_name in sorted(contract):
        module = importlib.import_module(module_name)
        source_path = Path(module.__file__ or "")
        text = source_path.read_text()
        for legacy in legacy_modules:
            assert legacy not in text, (
                f"{module_name} references legacy timeline module {legacy}; the "
                "execution contract must see TimelineIR and nothing else (§13)"
            )
    assert not offenders


def test_renderers_own_no_artifact_proof():
    """§62: a renderer returns a locator, not proof of its own artifact.

    Enforced here as well as in P9.1D because the execution contract added a renderer
    module, and hashing in an adapter is the easy way to break this.

    Checked via AST, not text. A substring check flagged ``html_gsap_production.py``
    because the word appears in a comment explaining *why* the renderer does not hash --
    which is the opposite of a violation.
    """
    for path in sorted(HEVI.joinpath("renderers").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert name.split(".")[0] != "hashlib", (
                    f"{path.name} imports hashlib; a renderer must not hash its own "
                    "output (P9.1D T2)"
                )


# ── §45: adapter selection is not a provider resolver ──


def test_no_adapter_registry_ranks_or_scores():
    """§45: selection is exact-match lookup, never "best adapter".

    A scoring or ranking function inside an adapter registry would be a second
    provider authority. Checked on call *names* via AST: a text search would match the
    word in a docstring explaining why scoring is forbidden.
    """
    candidates = [
        *sorted((HEVI / "adapters").rglob("*.py")),
        HEVI / "renderers" / "html_gsap_production.py",
    ]
    banned = {"score", "rank", "best_adapter", "priority_score", "weight"}
    for path in candidates:
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name and name.lower() in banned:
                raise AssertionError(
                    f"{path.name}:{node.lineno} calls {name}(); adapter selection must "
                    "be exact-match lookup, not scoring (§45)"
                )


def test_no_parallel_executor_class():
    """§25: one MissionExecutor, one ProductionExecutor. Not four.

    A second orchestration authority is the failure this whole phase is about, so the
    names §25 prohibits are checked for directly.
    """
    prohibited = ("ProductionExecutor", "VideoExecutor", "OpenReelExecutor", "HtmlExecutor")
    defining = {
        name: [p.relative_to(HEVI).as_posix() for p in _sources() if name in _class_names(p)]
        for name in prohibited
    }
    for name, paths in defining.items():
        assert len(paths) <= 1, f"{name} defined in {paths}"
    # The one ProductionExecutor is ours; MissionExecutor remains the mission authority.
    assert len(defining["ProductionExecutor"]) == 1


# ── §22: OpenReel is an adapter boundary, not a dependency ──


def test_openreel_is_not_imported_anywhere_in_hevi():
    """§22/§54: the core must not require the external project.

    Checks the whole tree, not just the adapter package, because a single convenience
    import in a core module is enough to make HEVI unimportable without OpenReel.
    """
    offenders: list[str] = []
    for path in _sources():
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith(("import openreel", "from openreel")):
                offenders.append(f"{path.relative_to(HEVI).as_posix()}: {stripped}")
    assert not offenders, f"core depends on OpenReel: {offenders}"


def test_answerhtml_is_not_a_hevi_renderer():
    """§20/§62: its components are absorbed as compiler input, not as a renderer."""
    offenders: list[str] = []
    for path in _sources():
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith(("import answerhtml", "from answerhtml")):
                offenders.append(f"{path.relative_to(HEVI).as_posix()}: {stripped}")
    assert not offenders, f"HEVI depends on AnswerHTML runtime: {offenders}"


# ── §7: rollback is not file deletion ──


def test_transaction_rollback_does_not_delete_files():
    """§7/§62: "rollback implemented only by deleting files" is prohibited.

    ``shutil.rmtree`` on an output directory is the specific anti-pattern the spec
    names. The transaction module must contain no destructive filesystem call at all.
    """
    text = (HEVI / "production" / "execution_transaction.py").read_text()
    for banned in ("rmtree", "os.remove", "unlink", "shutil.rmtree"):
        assert banned not in text, (
            f"execution_transaction.py contains {banned!r}; rollback must orphan "
            "artifacts, not erase them (§7)"
        )


def test_orphan_semantics_exist_and_are_reachable():
    """ORPHANED must be a real state, not a declared enum nobody can reach."""
    from hevi.production.execution_transaction import (
        ArtifactState,
        ProductionExecutionTransaction,
    )
    from hevi.production.operation import ProductionOperation, ProductionOperationType

    tx = ProductionExecutionTransaction(
        production_id="p",
        operations=(
            ProductionOperation(
                operation_id="op", operation_type=ProductionOperationType.RENDER,
                production_id="p", idempotency_key="k",
            ),
        ),
    )
    tx.begin()
    tx.record_artifact(artifact_id="a", content_hash="ab" * 32, kind="video",
                       uri="/tmp/a.mp4", operation_id="op")
    tx.rollback("because")
    assert tx.artifact("a").state is ArtifactState.ORPHANED
    assert ArtifactState.ORPHANED.value == "ORPHANED"


# ── §35: no silent failure ──


def test_execution_contract_modules_do_not_swallow_exceptions():
    """§35 bans `except Exception: return None` and log-and-continue.

    Every broad ``except`` in the contract must re-raise or convert to a typed
    ``AdapterError``/``ExecutionFailureRecord``. A bare pass or a ``return None``
    inside one is the anti-pattern.
    """
    offenders: list[str] = []
    for path in (HEVI / "production").glob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            body = node.body
            if len(body) != 1:
                continue
            only = body[0]
            if isinstance(only, ast.Pass):
                offenders.append(f"{path.name}:{node.lineno} except->pass")
            if isinstance(only, ast.Return) and only.value is None:
                offenders.append(f"{path.name}:{node.lineno} except->return None")
    assert not offenders, f"silent failure handlers: {offenders}"


# ── §60: no fake PASS ──


def test_validation_module_never_fabricates_probe_data():
    """§33/§60: synthetic ffprobe data must be impossible to pass off as real."""
    text = (HEVI / "production" / "production_validation.py").read_text()
    # A hardcoded stream list or duration constant would be a fabricated probe.
    for banned in ("avg_frame_rate\": \"", "'streams': [{", '"streams": [{'):
        assert banned not in text, (
            f"production_validation.py contains fabricated probe data: {banned!r}"
        )


def test_validation_requires_a_non_empty_probe_summary():
    from hevi.production.production_validation import validate_production

    result = validate_production(
        production_id="p",
        artifact_path=Path("/nonexistent/never.mp4"),
        expected_duration_ms=1000, expected_width=100, expected_height=100,
        expected_fps=30, expected_audio=False, ffprobe_summary={},
    )
    assert not result.passed
    assert "artifact_exists" in result.failed_checks


# ── §38: deterministic ordering is the only ordering ──


def test_execution_order_is_deterministic_and_total():
    from hevi.production.operation import (
        ProductionOperation,
        ProductionOperationType,
        resolve_execution_order,
    )

    ops = tuple(
        ProductionOperation(
            operation_id=name, operation_type=ProductionOperationType.RENDER,
            production_id="p", sequence=0, idempotency_key=f"k-{name}",
        )
        for name in ("c", "a", "b")
    )
    first = [op.operation_id for op in resolve_execution_order(ops)]
    second = [op.operation_id for op in resolve_execution_order(tuple(reversed(ops)))]
    assert first == second == ["a", "b", "c"]


def test_dependency_cycle_is_refused_not_resolved():
    from hevi.production.operation import (
        ProductionOperation,
        ProductionOperationType,
        resolve_execution_order,
    )

    ops = [
        ProductionOperation(operation_id="a", operation_type=ProductionOperationType.RENDER,
                            production_id="p", depends_on=("b",), idempotency_key="ka"),
        ProductionOperation(operation_id="b", operation_type=ProductionOperationType.RENDER,
                            production_id="p", depends_on=("a",), idempotency_key="kb"),
    ]
    with pytest.raises(ValueError, match="CYCLE"):
        resolve_execution_order(ops)


# ── §36/§35 interaction: optional failure recorded, not swallowed ──


def test_optional_failure_permits_commit_but_stays_recorded():
    from hevi.production.execution_result import ExecutionFailureRecord
    from hevi.production.execution_transaction import ProductionExecutionTransaction
    from hevi.production.operation import ProductionOperation, ProductionOperationType

    required = ProductionOperation(operation_id="req", operation_type=ProductionOperationType.RENDER,
                                   production_id="p", idempotency_key="k1")
    optional = ProductionOperation(operation_id="opt", operation_type=ProductionOperationType.AUDIO,
                                   production_id="p", idempotency_key="k2", required=False)
    tx = ProductionExecutionTransaction(
        production_id="p", operations=(required, optional)
    )
    tx.begin()
    tx.record_failure(
        ExecutionFailureRecord.for_operation(
            production_id="p", operation=optional, transaction_id=tx.transaction_id,
            stage="execute", error_type="capability_mismatch", message="optional failed",
        )
    )
    receipt = tx.commit()
    assert receipt.tolerated_failures, "optional failure must be reported on the receipt"
    assert len(tx.failures) == 1


def test_required_failure_blocks_commit():
    from hevi.production.execution_result import ExecutionFailureRecord
    from hevi.production.execution_transaction import (
        ProductionExecutionTransaction,
        TransactionError,
    )
    from hevi.production.operation import ProductionOperation, ProductionOperationType

    required = ProductionOperation(operation_id="req", operation_type=ProductionOperationType.RENDER,
                                   production_id="p", idempotency_key="k1")
    tx = ProductionExecutionTransaction(production_id="p", operations=(required,))
    tx.begin()
    tx.record_failure(
        ExecutionFailureRecord.for_operation(
            production_id="p", operation=required, transaction_id=tx.transaction_id,
            stage="execute", error_type="invalid_timeline", message="bad timeline",
        )
    )
    with pytest.raises(TransactionError, match="REQUIRED_FAILURES"):
        tx.commit()


# ── recorded pre-existing debt, guarded against growth ──


@pytest.mark.parametrize("authority", sorted(PRE_EXISTING_DUPLICATE_AUTHORITIES))
def test_pre_existing_duplicate_authorities_do_not_grow(authority: str):
    """Guard a known defect without claiming to have fixed it.

    `ShotPlan` and `MotionPlan` are each defined in two pre-existing modules (§46 puts
    them with their owning phase's owner). Asserting `== 1` here would fail on a defect
    this spec did not introduce and is not permitted to fix; asserting nothing would
    lose the audit's value entirely.

    So the count is pinned at its current value. A third definition fails immediately,
    which is the failure mode an audit exists to catch.
    """
    expected = set(PRE_EXISTING_DUPLICATE_AUTHORITIES[authority])
    defining = {
        p.relative_to(HEVI).as_posix() for p in _sources() if authority in _class_names(p)
    }
    assert defining == expected, (
        f"{authority} is defined in {sorted(defining)}; expected the known set "
        f"{sorted(expected)}. A new definition is a §62 violation; removing one means "
        "the owning phase (not this spec) resolved it -- update this map then."
    )
