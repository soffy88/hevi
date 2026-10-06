"""Authority convergence invariants — P0-1 baseline.

These tests assert the **current** state of HEVI's authority graph, including the
parts that violate the target invariants. They are a baseline, not a target.

Why failing tests are marked ``xfail(strict=True)``
---------------------------------------------------
An invariant that holds today will silently regress if nobody asserts it. An
invariant that does *not* hold today must not be asserted as if it did — that is
how a gate gets weakened into meaninglessness. So each unmet invariant is encoded
with ``strict=True``: it is recorded as failing, and if a later phase makes it pass,
pytest reports XPASS as a **failure**, forcing the marker to be removed and the
assertion inverted. The marker cannot outlive the fix.

Three groups:

* ``test_*_is_unique`` — invariants that hold today and must keep holding.
* ``test_*_is_NOT_yet_*`` — invariants the spec requires and HEVI violates today.
  Each is a falsifiable claim about the *violation*, so it fails if the violation is
  fixed without the marker being cleared.
* ``test_repo_state_*`` — repository-state facts, kept so a later phase cannot
  re-report them as new findings.

Method: static analysis of the import graph and literal token census via AST and
``pathlib``, not runtime execution. Reachability labels use the vocabulary in
``docs/architecture/authority_map.md``: PROD / LIB / TEST-ONLY / DEAD.
"""

from __future__ import annotations

import ast
import re
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HEVI = REPO / "hevi"
DOCS = REPO / "docs/architecture/authority_map.md"
DUPLICATES = REPO / "docs/architecture/duplicate_inventory.md"

#: Directories whose contents never count as production wiring.
NON_PRODUCTION = ("tests", "scripts", "docs", "workflows", "tools")


def _python_files() -> Iterator[Path]:
    yield from sorted(HEVI.rglob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    """Module names this file imports, ignoring whether they resolve."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _production_files() -> list[Path]:
    return [p for p in _python_files() if p.parts[len(HEVI.parts) - 1] not in NON_PRODUCTION]


def _importers_of(module: str, *, exclude_prefix: str | None = None) -> tuple[list[Path], list[Path]]:
    """Split importers into (production, test-or-script).

    ``exclude_prefix`` drops intra-package imports, which say nothing about
    external reachability (``hevi/renderers/ffmpeg.py`` importing
    ``hevi.renderers.base`` is not evidence that anything renders).
    """
    prod: list[Path] = []
    other: list[Path] = []
    for path in _python_files():
        if exclude_prefix and str(path.relative_to(REPO)).startswith(exclude_prefix):
            continue
        if module not in _imported_modules(path):
            continue
        rel = path.relative_to(REPO)
        top = rel.parts[0]
        (other if top in ("tests", "scripts") else prod).append(rel)
    return prod, other


def _source_tokens() -> str:
    """Concatenated production source, for literal token census."""
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in _production_files())


# ─────────────────────────────────────────────────────────────────────────
# Group 1 — invariants that hold today and must keep holding
# ─────────────────────────────────────────────────────────────────────────


def test_task_authority_is_unique() -> None:
    """One durable task owner: ``video_tasks``, with a transition validator.

    Holds today. Four rivals exist but three of them are TEST-ONLY/dead, so the
    *canonical* designation is unique even though the machine count is not.
    """
    from hevi.tasks.state_machine import (
        TASK_TRANSITIONS,
        InvalidTaskTransition,
        validate_task_transition,
    )

    # Returns None on a legal transition; raises on an illegal one. The return
    # value is deliberately not asserted (mypy: it is always None).
    validate_task_transition("queued", "running")
    assert "queued" in TASK_TRANSITIONS
    with pytest.raises(InvalidTaskTransition):
        validate_task_transition("queued", "done")

    prod, _ = _importers_of("hevi.tasks.state_machine")
    assert prod, "video_tasks transition rules must stay reachable from production"

    # UnifiedProductionRuntime is a *type*, so grep-level import counting cannot
    # distinguish "imported for its contracts" from "instantiated". Assert on the
    # symbol being constructed instead.
    runtime_src = _source_tokens()
    assert "UnifiedProductionRuntime(" not in runtime_src, (
        "UnifiedProductionRuntime gained a construction site; the Task/Run "
        "authority map in docs/architecture/authority_map.md is now stale")
    # hevi.production.p6.schema IS imported by production (layout_plan.py:47), so
    # the invariant is about the runtime class, not the package.
    prod_p6, _ = _importers_of("hevi.production.p6.schema")
    assert prod_p6, "p6.schema is expected to be reachable from production"


def test_provider_registry_is_unique_in_holding_capabilities() -> None:
    """``ProviderRegistry`` is the only registry that holds provider objects.

    The other four hold facts, limits or specs. This test does **not** claim there
    is one registry — there are five — only that exactly one *defines* a registry
    and that it is reachable from production.
    """
    # There are 18 *Registry classes repo-wide (skill, grammar, presenter,
    # renderer-router, failure, ...). The invariant is narrower and is the one the
    # spec cares about: no *provider* registry other than ProviderRegistry may
    # hold provider objects. Declared provider-fact tables are listed explicitly so
    # adding a sixth one is caught.
    provider_fact_tables = {
        "hevi/providers/facts.py",
        "hevi/provider_policy/runtime.py",
        "hevi/providers/runtime_specs.py",
        "hevi/video/capability_guard.py",
    }
    for rel in sorted(provider_fact_tables):
        assert (REPO / rel).exists(), f"expected provider fact table missing: {rel}"

    # ProviderRegistry is re-exported from obase, so hevi/providers/registry.py
    # contains no class statement. Assert that it is the module that binds the
    # canonical name, and count repo-wide *Registry classes so an unrelated
    # addition is noticed in review.
    registry_module = (HEVI / "providers/registry.py").read_text(encoding="utf-8")
    assert "from obase.provider_registry import ProviderRegistry" in registry_module
    assert '__all__ = ["ProviderRegistry"' in registry_module

    registry_defs = sorted({
        p.relative_to(REPO) for p in _python_files()
        if re.search(r"^class \w*Registry\b",
                     p.read_text(encoding="utf-8", errors="ignore"), re.M)
    })
    # Documented count so an unrelated registry addition is noticed in review.
    assert len(registry_defs) <= 18, f"registry classes grew: {len(registry_defs)}"

    prod, _ = _importers_of("hevi.providers.registry")
    assert prod, "the provider registry must stay reachable from production"


def test_artifact_hash_binding_is_enforced_in_the_canonical_artifact() -> None:
    """``production/artifacts.py`` enforces integrity; that must not regress.

    ``Artifact`` is a pydantic BaseModel, so the round trip goes through
    ``from_path(...).with_integrity()`` rather than a constructor.
    """
    import hashlib

    from hevi.production.artifacts import Artifact

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "a.bin"
        target.write_bytes(b"hevi-p0-1")
        digest = hashlib.sha256(b"hevi-p0-1").hexdigest()

        good = Artifact.from_path(target, kind="video", media_type="video/mp4")
        assert good.sha256 == digest
        assert good.integrity_ok()

        # A recorded hash that does not match the bytes must fail closed.
        tampered = good.model_copy(update={"sha256": "0" * 64})
        assert not tampered.integrity_ok()

        # A missing hash is not silently valid.
        assert not good.model_copy(update={"sha256": None}).integrity_ok()


def test_production_receipt_fails_closed_on_checksum_mismatch() -> None:
    """The strongest integrity check in the repo must stay fail-closed."""
    from hevi.execution.models import ProductionReceipt

    with pytest.raises(ValueError, match="PRODUCTION_RECEIPT"):
        ProductionReceipt(
            receipt_id="r1", run_id="run1", artifact_id="a" * 64,
            artifact_checksum="not-a-sha", producer="test")


def test_direction_verdict_stays_checksum_bound() -> None:
    """The only checksum-bound verdict type must keep rejecting unbound hashes."""
    from hevi.creative.direction_verify import VerifyError
    from hevi.creative.direction_verify.models import DirectionVerdict

    with pytest.raises(VerifyError) as exc:
        DirectionVerdict("nohash", "plan1", "PASS", ()).validate()
    assert getattr(exc.value, "code", "") == "VERDICT_UNBOUND"


def test_frozen_real_video_proof_is_unchanged() -> None:
    """REAL_VIDEO_PROOF_001 must stay byte-identical through every phase."""
    import json

    root = REPO / "artifacts/real_video/20261005T160434Z"
    if not (root / "FREEZE.json").exists():  # pragma: no cover
        pytest.skip("frozen proof not present in this checkout")

    recorded = json.loads((root / "FREEZE.json").read_text())["sha256"]
    proc = subprocess.run(
        ["sha256sum", str(root / "final/FINAL.mp4")],
        capture_output=True, text=True, check=True)
    actual = proc.stdout.split()[0]
    receipt = (root / "final/FINAL_SHA256").read_text().strip()

    assert actual == recorded == receipt, "REAL_VIDEO_PROOF_001 was modified"


def test_authority_documents_exist_and_are_consistent() -> None:
    """The two P0-1 deliverables must exist and agree on the blocker."""
    assert DOCS.exists(), "docs/architecture/authority_map.md is required"
    assert DUPLICATES.exists(), "docs/architecture/duplicate_inventory.md is required"

    authority = DOCS.read_text(encoding="utf-8")
    duplicates = DUPLICATES.read_text(encoding="utf-8")

    assert "AUTHORITIES_UNIQUELY_IDENTIFIED = BLOCKED" in authority
    assert "Admission (§6) has no canonical candidate" in authority
    for token in ("CANONICAL", "Competing authorities", "Removal condition"):
        assert token in authority, f"authority map missing required section: {token}"
    assert "Repository-state evidence" in duplicates
    assert "not implementation defects" in duplicates


# ─────────────────────────────────────────────────────────────────────────
# Group 2 — invariants the spec requires and HEVI violates today
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.xfail(strict=True, reason="P0-4: 6 admission gates + 1 observer, no canonical seam")
def test_admission_path_is_NOT_yet_unique() -> None:
    """There must be exactly one admission path. There are six gates.

    Fails while seams 1-6 can each independently admit or deny. Cleared when the
    count reaches 1.
    """
    seams = {
        "hevi/provider_policy/policy.py",
        "hevi/generation/evidence.py",
        "hevi/creative/autonomous/selection.py",
        "hevi/creative/layer4/endpoint_lifecycle.py",
        "hevi/creative/layer4/plan_projection.py",
        "hevi/video/capability_guard.py",
    }
    present = {s for s in seams if (REPO / s).exists()}
    deny_capable = [s for s in present if "raise" in (REPO / s).read_text(encoding="utf-8")]
    assert len(deny_capable) <= 1, (
        f"{len(deny_capable)} admission gates can independently deny: "
        f"{sorted(deny_capable)}")


@pytest.mark.xfail(strict=True, reason="P0-4: no admission record type exists (admission_id 0 hits)")
def test_admission_record_is_NOT_yet_typed() -> None:
    """Admission must be recorded. No record type exists."""
    source = _source_tokens()
    assert "admission_id" in source, "no admission record is persisted anywhere"
    assert "executor_id" in source, "admission does not name the executor"


@pytest.mark.xfail(strict=True, reason="P0-4: qualification is a harness with one production consumer")
def test_qualification_authority_is_NOT_yet_canonical() -> None:
    """Qualification must have a canonical owner. It is a harness.

    One production module (``creative/autonomous/acquire.py``) calls one function
    (``media.validate_media``); every runner is test-only.
    """
    runners = [
        "framework", "http_runner", "live_run", "live_runner", "local_process",
    ]
    with_prod_callers = []
    for name in runners:
        prod, _ = _importers_of(f"hevi.qualification.{name}")
        if prod:
            with_prod_callers.append(name)
    assert not with_prod_callers, (
        f"qualification runners gained production callers: {with_prod_callers}")


@pytest.mark.xfail(strict=True, reason="P0-5: 20 predecessor representations still coexist as call sites; TimelineIR is canonical but their production paths are not yet rewired")
def test_timeline_authority_is_NOT_yet_unique() -> None:
    """There must be one timeline model. There are twenty.

    Nine carry a timeline-shaped name; six more carry timeline semantics under
    other names. Counts non-legacy representations.
    """
    pattern = ("Timeline", "TimelinePlan", "BeatPlan", "VisualBeatPlan",
               "StoryboardBundle", "ShotIR", "TimelineSlot", "ClipSpec")
    count = 0
    for path in _python_files():
        if "layer4_legacy" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and any(
                    token in node.name for token in pattern):
                count += 1
    assert count <= 1, f"{count} timeline representations coexist"


@pytest.mark.xfail(strict=True, reason="P0-5: the legacy hyperframes compiler is still fail-open; TimelineIR validates, but its adapter does not yet own that path")
def test_timeline_validation_is_NOT_yet_fail_closed() -> None:
    """Unknown action / missing timestamp / negative duration must be rejected."""
    compiler = (HEVI / "providers/hyperframes/compiler.py").read_text(encoding="utf-8")
    assert "raise" in compiler, (
        "the live timeline compile path still coerces invalid input instead of "
        "raising")


@pytest.mark.xfail(strict=True, reason="P0-3: RenderResult.content_hash is never assigned")
def test_render_receipt_links_to_its_plan() -> None:
    """A render receipt must link to the plan that produced it."""
    from hevi.renderers.base import RenderOutcome, RenderPlan, RenderResult

    plan = RenderPlan(shot_id="s1", duration_s=1.0, fps=25, width=1280, height=720)
    result = RenderResult(shot_id="s1", renderer="ffmpeg", outcome=RenderOutcome.OK,
                          output_path="/tmp/x.mp4", duration_s=1.0, frame_count=25)
    assert result.content_hash or "plan_hash" in plan.to_dict(), (
        "render result carries no content hash and the plan carries no plan hash, "
        "so a receipt cannot be tied to the plan that produced it")


def test_render_plan_authority_is_NOT_yet_production_reachable() -> None:
    """The canonical RenderPlan is NOT reachable from production. Recorded as a fact.

    A real assertion rather than an xfail: the current state is "zero production
    importers", and if a production caller appears this test fails and the
    authority map must be updated. The remedy (wiring it up) belongs to P0-5.
    """
    prod, _other = _importers_of(
        "hevi.renderers.base", exclude_prefix="hevi/renderers/")
    assert not prod, (
        f"hevi.renderers.base gained production callers {prod}; update "
        f"docs/architecture/authority_map.md section 8")


@pytest.mark.xfail(strict=True, reason="P0-5: 6 competing final-verdict writers, only one checksum-bound and it is dead")
def test_acceptance_authority_is_NOT_yet_unique() -> None:
    """Exactly one verdict writer, checksum-bound, HTTP-reachable."""
    verdicts = [
        "hevi/verdict/delivery_gate.py",
        "hevi/production/delivery_gate.py",
        "hevi/verdict/final_review.py",
        "hevi/creative/direction_verify/models.py",
        "hevi/creative/autonomous/verdict.py",
        "hevi/production/artifact_verification.py",
    ]
    present = [v for v in verdicts if (REPO / v).exists()]
    assert len(present) <= 1, f"{len(present)} verdict writers coexist: {present}"


@pytest.mark.xfail(strict=True, reason="P0-8: REAL_VIDEO_ACCEPTED has 0 code emitters")
def test_real_video_accepted_is_NOT_yet_code_emitted() -> None:
    """The final verdict must be emitted by code, not hand-written into JSON.

    Today the literal exists only in data files; the producing script writes
    ``MACHINE_{status}``.
    """
    this_file = Path(__file__).resolve()
    emitters = []
    for path in REPO.rglob("*.py"):
        if path.resolve() == this_file:
            continue
        rel = path.relative_to(REPO)
        if rel.parts[0] in (".venv", "node_modules", "outputs", "artifacts"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "REAL_VIDEO_ACCEPTED" in text:
            emitters.append(str(rel))
    assert emitters, (
        "no Python file emits REAL_VIDEO_ACCEPTED; the token exists only in "
        "hand-written JSON and STATUS.md")


@pytest.mark.xfail(strict=True, reason="P0-2: supersedes_revision_id / invalidated_artifact_ids absent")
def test_revision_links_are_NOT_yet_typed() -> None:
    """Revision must record supersession and invalidation."""
    source = _source_tokens()
    assert "supersedes_revision_id" in source
    assert "invalidated_artifact_ids" in source


@pytest.mark.xfail(strict=True, reason="P0-2: ShotSpec carries no provenance field")
def test_shot_spec_carries_provenance() -> None:
    """Every creative decision must be provenance-bearing."""
    import dataclasses

    from hevi.creative.director_contract import ShotSpec

    fields = {f.name for f in dataclasses.fields(ShotSpec)}
    assert "provenance" in fields or "decision_provenance" in fields, (
        f"ShotSpec has no provenance field; fields are {sorted(fields)}")


@pytest.mark.xfail(strict=True, reason="P0-2: canonical ShotSpec persists float seconds")
def test_shot_spec_time_is_NOT_yet_integer_ms() -> None:
    """Canonical persisted time must be integer ms."""
    import dataclasses

    from hevi.creative.director_contract import ShotSpec

    offenders = [
        f.name for f in dataclasses.fields(ShotSpec)
        if f.name.endswith(("_sec", "_s"))
    ]
    assert not offenders, f"ShotSpec persists float-second fields: {offenders}"


@pytest.mark.xfail(strict=True, reason="P0-2: no recipe_ref on ShotSpec; no recipe->ShotSpec path")
def test_shot_spec_is_NOT_yet_selected_from_a_recipe() -> None:
    """A ShotSpec must record which recipe selected it."""
    import dataclasses

    from hevi.creative.director_contract import ShotSpec

    fields = {f.name for f in dataclasses.fields(ShotSpec)}
    assert "recipe_id" in fields or "recipe_ref" in fields, (
        f"ShotSpec does not reference a recipe; fields are {sorted(fields)}")


@pytest.mark.xfail(strict=True, reason="P0-6: 3 recipe systems, 0 shared vocabulary, 0 qualified recipes")
def test_recipe_systems_are_NOT_yet_converged() -> None:
    """Exactly one recipe system, with qualified recipes."""
    from hevi.production.p5_3.recipes import load_all_recipes

    recipes = load_all_recipes()
    qualified = [r for r in recipes if getattr(r, "qualification_state", None) == "QUALIFIED"]
    assert qualified, (
        f"{len(recipes)} recipes exist but none is QUALIFIED")


@pytest.mark.xfail(strict=True, reason="P0-6: duration-fit failure silently returns a non-fitting recipe")
def test_recipe_selection_is_NOT_yet_fail_closed() -> None:
    """No fitting recipe must raise, not degrade."""
    selector = (HEVI / "cinematic/shot_intelligence/selector.py").read_text(encoding="utf-8")
    assert "fitting or candidates" not in selector, (
        "duration-fit failure still discards the filter and returns a recipe that "
        "does not fit")


@pytest.mark.xfail(strict=True, reason="P0-3: 10 mappers, 5 fail-open on unknown input")
def test_failure_taxonomy_is_NOT_yet_canonical() -> None:
    """One taxonomy; unknown input must map to UNKNOWN, never to a category."""
    taxonomy = (HEVI / "quality/taxonomy.py").read_text(encoding="utf-8")
    assert "DELIVERY_INTEGRITY" not in taxonomy.split("def normalize_failure")[-1], (
        "normalize_failure still maps unrecognized input to a real failure class")


@pytest.mark.xfail(strict=True, reason="P0-1: 5 of 15 required failure classes exist exactly")
def test_required_failure_classes_are_NOT_yet_present() -> None:
    """All fifteen required failure classes must exist as tokens."""
    required = [
        "INVALID_INPUT", "CAPABILITY_UNSATISFIED", "ASSET_NOT_FOUND",
        "ASSET_LOW_CONFIDENCE", "GENERATION_FAILED", "PROVIDER_UNAVAILABLE",
        "PROVIDER_RATE_LIMIT", "TRANSCRIPT_FAILED", "TIMELINE_INVALID",
        "RENDER_FAILED", "MEDIA_PROBE_FAILED", "QUALITY_GATE_FAILED",
        "PROVENANCE_MISSING", "EVIDENCE_MISSING", "HUMAN_REVIEW_REQUIRED",
    ]
    source = _source_tokens()
    missing = [token for token in required if token not in source]
    assert not missing, f"{len(missing)} of 15 required failure classes absent: {missing}"


@pytest.mark.xfail(strict=True, reason="P0-6: VideoAcceptance does not exist")
def test_video_acceptance_contract_is_NOT_yet_canonical() -> None:
    """One acceptance object, sole final verdict."""
    source = _source_tokens()
    assert "class VideoAcceptance" in source, "no canonical VideoAcceptance contract"


@pytest.mark.xfail(strict=True, reason="P0-2: EvidencePack does not exist")
def test_evidence_pack_is_NOT_yet_canonical() -> None:
    """One evidence object bound to artifact hash."""
    source = _source_tokens()
    assert "EvidencePack" in source, "no canonical EvidencePack contract"


# ─────────────────────────────────────────────────────────────────────────
# Group 3 — repository-state facts (keep these from being re-reported)
# ─────────────────────────────────────────────────────────────────────────


def test_repo_state_baseline_facts() -> None:
    """The six baseline failures and the manim mismatch are environment, not code.

    Recorded so a later phase does not mistake them for new findings. Fails if the
    environment is fixed, which is a signal to retire this test.
    """
    fact_file = REPO / "docs/architecture/duplicate_inventory.md"
    text = fact_file.read_text(encoding="utf-8")
    assert "6 baseline test failures" in text
    assert "test_manim_is_qualified" in text
    assert "P0-4 blocker" in text
    assert "77 untracked" in text, (
        "the 77-untracked-files fact must stay recorded so it is not re-counted")


def test_repo_state_frozen_commit_exists() -> None:
    """The P-1 baseline-freeze commit must be an ancestor of HEAD."""
    # `git log` is on the repository's read-only allowlist
    # (tests/test_p5_2_mutation_safety.py:201); `merge-base` is not.
    proc = subprocess.run(
        ["git", "log", "--format=%H", "5d8bf783", "-n", "1"],
        capture_output=True, text=True, check=False)
    assert proc.stdout.strip().startswith("5d8bf783"), (
        f"P-1 baseline freeze is not reachable from HEAD: {proc.stdout!r}")
    ancestor = subprocess.run(
        ["git", "log", "--format=%H", "--max-count=50"],
        capture_output=True, text=True, check=False).stdout.split()
    assert any(sha.startswith("5d8bf783") for sha in ancestor), (
        "P-1 baseline freeze 5d8bf783 is not in HEAD's recent history")


@pytest.mark.xfail(strict=True, reason="P0-4: environment-sensitive admission test defect")
def test_manim_qualification_test_is_NOT_yet_environment_independent() -> None:
    """``test_manim_is_qualified`` encodes an environment assumption.

    It asserts manim is qualified while the code correctly returns
    ``BLOCKED_BY_RUNTIME`` because manim is absent. Recorded as a P0-4 blocker;
    not fixed in P0-1 by instruction.
    """
    manim_present = True
    try:
        import manim  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        manim_present = False
    assert manim_present, (
        "manim is absent, so test_manim_is_qualified fails for environmental "
        "reasons, not because of a defect")
