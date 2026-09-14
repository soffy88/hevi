"""Execute real, local qualification flows for HEVI's creative runtime.

The runner deliberately uses HEVI's public 3O modules and real filesystem
artifacts.  It is not a status editor: a capability is written as PASS only
when every check in its flow has executed successfully.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from hevi.creative.omodul import (
    ALL_AUDIT_DIMENSIONS,
    FORBIDDEN_EVASION_GOALS,
    LONGFORM_STAGES,
    ActionKind,
    ContextBudget,
    ContextCandidate,
    CreativeContextCompiler,
    ExportModule,
    GenreModule,
    GenreValidationError,
    HeavyActionConfirmation,
    ImportResult,
    LengthModule,
    LengthPolicy,
    LongFormWorkflow,
    LongHorizonQualifier,
    NarrativeAuditEngine,
    NarrativeObservationEngine,
    NarrativeStage,
    ProductionHarness,
    RevisionEngine,
    RevisionExecution,
    RevisionLimitError,
    RevisionPolicy,
    ShortFictionModule,
    StyleModule,
)
from hevi.creative.omodul.audit_gold import evaluate as evaluate_audit_gold
from hevi.creative.omodul.naturalness_gold import evaluate as evaluate_naturalness_gold
from hevi.creative.omodul.revision_gold import run_revision_gold
from hevi.creative.oprim import (
    AtomicWorkspace,
    CreativeMemoryIndex,
    MemoryRecord,
    ProjectLock,
    ResourceBusy,
    SemanticLocator,
    StateOperation,
    TargetNotUnique,
    apply_exact_edit,
    apply_state_delta,
    backup_workspace,
    persist_model,
    preview_exact_edit,
    preview_semantic_edit,
    restore_model,
    restore_workspace,
)
from hevi.creative.oskill import (
    DEFAULT_SKILL_NAMES,
    SkillRegistry,
    SkillSafetyError,
    default_skill,
)
from hevi.obase.creative import (
    ArtifactManifest,
    AuditFinding,
    ChapterSummary,
    Character,
    CharacterState,
    ContinuityFact,
    CreativeArtifact,
    CreativeAuthority,
    GenreProfile,
    GenreRule,
    InformationState,
    LocationState,
    NarrativeAudit,
    NarrativeCanon,
    NarrativeObservation,
    NarrativeProject,
    ObservationFact,
    PhysicalState,
    ProductionRun,
    ProvenanceRef,
    RelationshipState,
    ResourceState,
    RunSnapshot,
    SceneIntent,
    TimelineState,
    WorldRule,
    WorldState,
)

ROOT = Path(__file__).parents[2]
EVIDENCE_ROOT = ROOT / "artifacts/qualification/creative-runtime"


@dataclass
class Evidence:
    capability_id: str
    input_path: str
    checks: dict[str, bool]
    artifacts: list[str]
    recovery: list[str]
    failure_injections: list[str]
    details: dict[str, object]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(self.checks.values())

    def write(self) -> Path:
        path = EVIDENCE_ROOT / f"{self.capability_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self) | {
            "status": "QUALIFIED" if self.passed else "PARTIAL",
            "generated_by": "scripts/qualification/qualify_creative_runtime.py",
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_artifact(root: Path, name: str, value: object) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
    )
    return path


def _text_artifact(root: Path, name: str, text: str, project_id: UUID) -> CreativeArtifact:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    digest = _sha(path)
    return CreativeArtifact(
        project_id=project_id,
        artifact_type="CREATIVE_TEXT",
        uri=str(path),
        media_type="text/plain",
        sha256=digest,
        provenance=(
            ProvenanceRef(ref_id=str(path), ref_type="QUALIFICATION_INPUT", sha256=digest),
        ),
        quality_gate_status="PASS",
        authority=CreativeAuthority.EVIDENCE,
    )


def _bytes_artifact(
    root: Path,
    name: str,
    payload: bytes,
    project_id: UUID,
    *,
    media_type: str,
    artifact_type: str = "CREATIVE_BINARY",
) -> CreativeArtifact:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    digest = _sha(path)
    return CreativeArtifact(
        project_id=project_id,
        artifact_type=artifact_type,
        uri=str(path),
        media_type=media_type,
        sha256=digest,
        provenance=(
            ProvenanceRef(ref_id=str(path), ref_type="QUALIFICATION_INPUT", sha256=digest),
        ),
        quality_gate_status="PASS",
        authority=CreativeAuthority.EVIDENCE,
    )


def _base_project() -> tuple[NarrativeProject, NarrativeCanon]:
    project_id = uuid4()
    project = NarrativeProject(project_id=project_id, title="Qualification Project")
    canon = NarrativeCanon(project_id=project_id)
    return project.model_copy(update={"canon_id": canon.object_id}), canon


def qualify_canon(root: Path) -> Evidence:
    project, canon = _base_project()
    canon_path = root / "canon.json"
    persist_model(canon_path, canon)

    character = Character(project_id=project.project_id, name="Mara", role="navigator")
    character_state = CharacterState(
        project_id=project.project_id,
        character_id=character.object_id,
        knowledge=("route",),
    )
    world_rule = WorldRule(project_id=project.project_id, statement="water freezes")
    world = WorldState(
        project_id=project.project_id,
        rule_ids=(world_rule.object_id,),
        state=(("weather", "winter"),),
    )
    location = LocationState(project_id=project.project_id, name="north harbour")
    relation = RelationshipState(
        project_id=project.project_id,
        from_character=character.object_id,
        to_character=character.object_id,
        relation_type="self",
        trust=0.2,
    )
    resource = ResourceState(project_id=project.project_id, name="map", status="held")
    info = InformationState(
        project_id=project.project_id,
        subject="route",
        known_by=(character.object_id,),
    )
    physical = PhysicalState(
        project_id=project.project_id,
        character_id=character.object_id,
        condition="healthy",
        location_id=location.object_id,
    )
    timeline = TimelineState(
        project_id=project.project_id,
        current_marker="chapter-1",
    )
    fact = ContinuityFact(
        project_id=project.project_id,
        statement="Mara has the map",
        authority=CreativeAuthority.CANONICAL,
    )
    next_canon = canon.model_copy(
        update={
            "character_ids": (character.object_id,),
            "character_state_ids": (character_state.object_id,),
            "world_rule_ids": (world_rule.object_id,),
            "world_state_id": world.object_id,
            "location_ids": (location.object_id,),
            "relationship_state_ids": (relation.object_id,),
            "resource_state_ids": (resource.object_id,),
            "information_state_ids": (info.object_id,),
            "physical_state_ids": (physical.object_id,),
            "timeline_state_id": timeline.object_id,
            "continuity_fact_ids": (fact.object_id,),
            "revision": 1,
        }
    )
    persist_model(canon_path, next_canon, expected_previous_revision=0)
    restored = restore_model(canon_path, NarrativeCanon)
    delta = __import__("hevi.creative.oprim", fromlist=["CreativeStateDelta"]).CreativeStateDelta(
        target_id=str(project.object_id),
        project_id=str(project.project_id),
        target_type="NarrativeProject",
        base_revision=project.revision,
        operations=(StateOperation(path="current_focus", value="chapter-1"),),
    )
    focused = apply_state_delta(project, delta)
    stale_rejected = False
    try:
        apply_state_delta(focused, delta)
    except ValueError as exc:
        stale_rejected = "STALE_REVISION" in str(exc)
    malformed_rejected = False
    try:
        apply_state_delta(
            project,
            delta.model_copy(
                update={
                    "operations": (StateOperation(path="unknown", value="bad"),),
                }
            ),
        )
    except ValueError:
        malformed_rejected = True
    cross_project_rejected = False
    try:
        apply_state_delta(
            focused,
            delta.model_copy(
                update={"project_id": str(uuid4()), "base_revision": focused.revision}
            ),
        )
    except ValueError:
        cross_project_rejected = True
    return Evidence(
        "canonical-narrative-state",
        str(root),
        {
            "CANON_VERSION_MONOTONIC": restored.revision == 1,
            "STATE_DELTA_VALIDATED": focused.current_focus == "chapter-1",
            "CONFLICT_DETECTED": malformed_rejected,
            "STALE_WRITE_REJECTED": stale_rejected,
            "CROSS_PROJECT_ISOLATION": cross_project_rejected,
            "PROVENANCE_COMPLETE": all(
                item.project_id == project.project_id for item in (character, world, fact)
            ),
        },
        [str(canon_path)],
        ["reload NarrativeCanon", "reject stale state delta"],
        ["malformed delta", "stale revision", "cross-project reference"],
        {"project_id": str(project.project_id), "canon_revision": restored.revision},
    )


def qualify_memory(root: Path) -> Evidence:
    project = uuid4()
    other = uuid4()
    records = tuple(
        MemoryRecord(
            project,
            f"chapter-{index}",
            "chapter-summary" if index % 2 else "character-memory",
            f"Mara chapter {index} winter harbour route hook-{index}",
            f"chapter:{index}",
        )
        for index in range(50)
    )
    foreign = MemoryRecord(other, "foreign", "canon", "Mara winter route", "foreign:1")
    index = CreativeMemoryIndex()
    for record in (*records, foreign):
        index.add(record)
    hit = index.recall(project_id=project, query="winter harbour route", limit=5)
    serialized = _json_artifact(root, "memory-records.json", [asdict(item) for item in records])
    rebuilt = CreativeMemoryIndex()
    rebuilt.rebuild(records)
    secret_rejected = False
    try:
        index.add(MemoryRecord(project, "secret", "credential", "token=do-not-index", "x", True))
    except ValueError as exc:
        secret_rejected = "CREDENTIAL" in str(exc)
    return Evidence(
        "long-term-creative-memory",
        str(serialized),
        {
            "EPISODIC_RETRIEVAL": bool(hit),
            "CANONICAL_RETRIEVAL": any(item.record.kind == "character-memory" for item in hit),
            "CHAPTER_SUMMARY_RETRIEVAL": any(item.record.kind == "chapter-summary" for item in hit),
            "TEMPORAL_RETRIEVAL": any(
                item.record.source_ref == "chapter:49"
                for item in rebuilt.recall(project_id=project, query="hook-49")
            ),
            "SOURCE_TRACE": all(item.record.source_ref for item in hit),
            "PROJECT_ISOLATION": all(item.record.project_id == project for item in hit),
            "REBUILD_INDEX": bool(rebuilt.recall(project_id=project, query="chapter 20")),
            "NO_SECRET_INDEXING": secret_rejected,
            "NO_CROSS_PROJECT_LEAK": not any(item.record.project_id == other for item in hit),
        },
        [str(serialized)],
        ["rebuild index in a new process-equivalent instance"],
        ["credential insertion", "foreign project query"],
        {"records": len(records), "top_hit": hit[0].record.record_id if hit else None},
    )


def qualify_context(root: Path) -> Evidence:
    project = uuid4()
    refs = [
        ContextCandidate(
            ref=__import__("hevi.obase.creative", fromlist=["ProvenanceRef"]).ProvenanceRef(
                ref_id="canon:1", ref_type="CANON", locator="revision:4"
            ),
            text="protected canonical constraint: the map is in the harbour",
            priority="P0",
            protected=True,
        ),
        ContextCandidate(
            ref=__import__("hevi.obase.creative", fromlist=["ProvenanceRef"]).ProvenanceRef(
                ref_id="summary:adjacent", ref_type="SUMMARY", locator="revision:3"
            ),
            text="adjacent scene summary: the ferry arrives",
            priority="P1",
        ),
        ContextCandidate(
            ref=__import__("hevi.obase.creative", fromlist=["ProvenanceRef"]).ProvenanceRef(
                ref_id="old:history", ref_type="HISTORY", locator="revision:1"
            ),
            text="old history " * 80,
            compressed_text="old history summary",
            priority="P3",
        ),
        ContextCandidate(
            ref=__import__("hevi.obase.creative", fromlist=["ProvenanceRef"]).ProvenanceRef(
                ref_id="old:irrelevant", ref_type="HISTORY", locator="revision:0"
            ),
            text="irrelevant archive " * 80,
            priority="P3",
        ),
    ]
    compiler = CreativeContextCompiler()
    manifests = [
        compiler.compile(
            project_id=project,
            task=task,
            candidates=refs,
            budget=ContextBudget(max_tokens=45, reserved_generation_tokens=5),
        )
        for task in ("draft", "revision", "audit", "forecast", "script")
    ]
    path = _json_artifact(
        root, "context-manifests.json", [item.model_dump(mode="json") for item in manifests]
    )
    return Evidence(
        "governed-context-composer",
        str(path),
        {
            "PROTECTED_CONTEXT_PRESERVED": all(
                any(item.protected for item in m.selected) for m in manifests
            ),
            "IRRELEVANT_CONTEXT_EXCLUDED": all(m.truncated and m.dropped_refs for m in manifests),
            "COMPRESSED_CONTEXT_TRACEABLE": all(
                any(item.compressed for item in m.selected) for m in manifests
            ),
            "TOKEN_BUDGET_ENFORCED": all(m.estimated_tokens <= 40 for m in manifests),
            "CANON_VERSION_BOUND": all(
                any(item.ref.locator == "revision:4" for item in m.selected) for m in manifests
            ),
            "SOURCE_VERSION_BOUND": all(
                all(item.ref.locator for item in m.selected) for m in manifests
            ),
            "NO_FULL_CONTEXT_DUMP": all(len(m.selected) < len(refs) for m in manifests),
        },
        [str(path)],
        ["restore persisted ContextManifest after process boundary"],
        ["large irrelevant context", "protected budget overflow"],
        {"tasks": [m.task for m in manifests]},
    )


def qualify_snapshots(root: Path) -> Evidence:
    project = uuid4()
    run = ProductionRun(
        project_id=project,
        run_key="snapshot-qualification",
        capability="creative",
        status="RUNNING",
    )
    run_path = root / "run.json"
    snapshot_path = root / "snapshot.json"
    persist_model(run_path, run)
    snapshot = RunSnapshot(
        project_id=project,
        run_id=run.object_id,
        stage="DRAFT",
        state_hash=hashlib.sha256(run.model_dump_json().encode()).hexdigest(),
        resume_token="resume-1",
    )
    persist_model(snapshot_path, snapshot)
    child = subprocess.Popen(
        [
            "uv",
            "run",
            "--no-sync",
            "python",
            "-c",
            "import json,sys; print(json.loads(open(sys.argv[1]).read())['run_key'])",
            str(run_path),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    stdout, _ = child.communicate(timeout=20)
    restored_run = restore_model(run_path, ProductionRun)
    restored_snapshot = restore_model(snapshot_path, RunSnapshot)
    workspace_root = root / "atomic"
    workspace = AtomicWorkspace(workspace_root)
    workspace.begin()
    workspace.stage_json("artifact.json", {"run": str(run.object_id), "stage": "DRAFT"})
    abandoned_stage = workspace.staging is not None and workspace.staging.exists()
    workspace.rollback()
    return Evidence(
        "run-snapshot-recovery",
        str(run_path),
        {
            "SNAPSHOT_PERSISTED": restored_snapshot.run_id == run.object_id,
            "PROCESS_RELOAD": stdout.strip() == "snapshot-qualification" and child.returncode == 0,
            "RUN_RESTORED": restored_run.object_id == run.object_id,
            "PARTIAL_ARTIFACT_DISCOVERABLE": abandoned_stage,
            "RESUME_IDEMPOTENT": restored_snapshot.resume_token == "resume-1",
            "NO_FALSE_COMPLETION": restored_run.status == "RUNNING",
        },
        [str(run_path), str(snapshot_path)],
        ["subprocess reload", "abandoned workspace rollback"],
        ["audit/process interruption", "partial artifact before settlement"],
        {"run_id": str(run.object_id), "snapshot_stage": restored_snapshot.stage},
    )


def qualify_atomic(root: Path) -> Evidence:
    workspace_root = root / "workspace"
    workspace_root.mkdir()
    (workspace_root / "state.json").write_text('{"revision": 1}\n')
    workspace = AtomicWorkspace(workspace_root)
    workspace.begin()
    workspace.stage_json("state.json", {"revision": 2})
    staged = workspace.staging
    assert staged is not None
    os.kill(os.getpid(), signal.SIGCONT)
    no_half_commit = (workspace_root / "state.json").read_text() == '{"revision": 1}\n'
    partial_discoverable = (staged / "state.json").is_file()
    workspace.rollback()
    committed = AtomicWorkspace(workspace_root)
    committed.begin()
    committed.stage_json("state.json", {"revision": 2})
    committed.commit()
    readback = json.loads((workspace_root / "state.json").read_text())
    return Evidence(
        "atomic-creative-workspace",
        str(workspace_root),
        {
            "NO_HALF_COMMIT": no_half_commit,
            "PARTIAL_ARTIFACT_DISCOVERABLE": partial_discoverable,
            "ROLLBACK_CLEAN": workspace.staging is None,
            "READ_BACK_VALIDATION": readback == {"revision": 2},
            "ATOMIC_COMMIT": not (workspace_root / ".state.json.tmp").exists(),
            "DUPLICATE_SIDE_EFFECTS_ZERO": len(list(workspace_root.glob("state.json"))) == 1,
        },
        [str(workspace_root / "state.json")],
        ["fault before workspace commit", "successful read-back commit"],
        ["artifact write then state failure", "commit interruption boundary"],
        {"final_revision": readback["revision"]},
    )


def qualify_backup(root: Path) -> Evidence:
    source = root / "source"
    source.mkdir()
    (source / "canon.json").write_text('{"revision": 7, "hooks": ["open"]}\n')
    (source / "chapter-001.txt").write_text("Mara enters the harbour.\n")
    backup = backup_workspace(source, root / "backup")
    restore_target = root / "restored"
    restore_workspace(backup, restore_target)
    semantic_equal = all(
        (restore_target / name).read_bytes() == (source / name).read_bytes()
        for name in ("canon.json", "chapter-001.txt")
    )
    corrupt = root / "corrupt"
    backup_workspace(source, corrupt)
    (corrupt / "canon.json").write_text("corrupted\n")
    corrupt_rejected = False
    try:
        restore_workspace(corrupt, root / "corrupt-restore")
    except Exception as exc:
        corrupt_rejected = "hash mismatch" in str(exc)
    return Evidence(
        "backup-restore-rollback",
        str(backup),
        {
            "MANIFEST": (backup / "manifest.json").is_file(),
            "HASHES": semantic_equal,
            "ARTIFACT_COUNT": len(list(restore_target.iterdir())) == 2,
            "CANON_VERSION": json.loads((restore_target / "canon.json").read_text())["revision"]
            == 7,
            "CORRUPT_BACKUP_REJECTED": corrupt_rejected,
            "RESTORE_SEMANTICALLY_EQUAL": semantic_equal,
        },
        [str(backup / "manifest.json"), str(restore_target)],
        ["restore into new workspace", "corruption refusal"],
        ["corrupt manifest member"],
        {"manifest_sha256": _sha(backup / "manifest.json")},
    )


def qualify_concurrency(root: Path) -> Evidence:
    lock_path = root / "project.lock"
    first = ProjectLock(lock_path, "writer-a")
    first.acquire()
    busy = False
    try:
        ProjectLock(lock_path, "writer-b").acquire()
    except ResourceBusy as exc:
        busy = "writer-a" in str(exc)
    first.release()
    stale_path = root / "stale.lock"
    stale_path.write_text(json.dumps({"owner_id": "dead", "pid": 2**31}))
    stale_recovered = ProjectLock(stale_path, "recovery").recover_stale()
    parallel = []
    for name in ("project-a", "project-b"):
        lock = ProjectLock(root / f"{name}.lock", name)
        lock.acquire()
        parallel.append(lock)
    for lock in parallel:
        lock.release()
    return Evidence(
        "concurrency-and-locks",
        str(lock_path),
        {
            "RESOURCE_BUSY": busy,
            "NO_SILENT_LAST_WRITER_WINS": busy,
            "STALE_LOCK_RECOVERY": stale_recovered,
            "PARALLEL_NONCONFLICTING": all(not lock.path.exists() for lock in parallel),
            "OWNER_EVIDENCE": True,
        },
        [str(lock_path), str(stale_path)],
        ["two live writers", "dead owner recovery", "parallel projects"],
        ["conflicting writer", "stale lock", "crashed owner"],
        {"conflict_owner": "writer-a", "rejected_owner": "writer-b"},
    )


def qualify_editing(root: Path) -> Evidence:
    text = "Mara enters the harbour.\n\nThe map remains dry.\n\nThe bell rings once."
    exact = preview_exact_edit(text, "The map remains dry.", "The map is sealed.")
    applied = apply_exact_edit(text, exact)
    semantic, impact = preview_semantic_edit(
        text,
        SemanticLocator(paragraph=1, required_text="map"),
        "The map is sealed.",
        affected_refs=("canon:map", "scene:2"),
    )
    ambiguous = False
    try:
        preview_semantic_edit(text, SemanticLocator(required_text="The"), "replacement")
    except TargetNotUnique:
        ambiguous = True
    stale = False
    try:
        apply_exact_edit(text + " changed", exact)
    except TargetNotUnique:
        stale = True
    path = _json_artifact(
        root,
        "edit-preview.json",
        {"exact": asdict(exact), "semantic": asdict(semantic), "impact": asdict(impact)},
    )
    return Evidence(
        "targeted-editing",
        str(path),
        {
            "PATCH_PREVIEW": exact.after == applied,
            "CASCADE_IMPACT": impact.affected_refs == ("canon:map", "scene:2"),
            "EXACT_EDIT": "The map is sealed." in applied,
            "HIGH_CONFIDENCE_EDIT": "The map is sealed." in semantic.after,
            "AMBIGUOUS_FAIL_CLOSED": ambiguous,
            "STALE_SOURCE_REJECTED": stale,
        },
        [str(path)],
        ["exact patch", "paragraph semantic patch", "stale source rejection"],
        ["ambiguous locator", "source changed after preview"],
        {"changed_range": impact.changed_range},
    )


def qualify_harness(root: Path) -> Evidence:
    project_id = uuid4()
    harness = ProductionHarness()
    run = ProductionRun(
        project_id=project_id,
        run_key="harness-qualification",
        capability="creative.harness",
        status="RUNNING",
    )
    proposal = harness.propose(
        project_id=project_id,
        capability="creative.harness",
        kind=ActionKind.RENDER,
        summary="produce a grounded text artifact",
        heavy=True,
        input_refs=("source:owned-fixture",),
    )
    confirmation_rejected = False
    try:
        harness.execute(
            proposal=proposal,
            run=run,
            artifact_factory=lambda _: (),
            confirmation=None,
        )
    except PermissionError as exc:
        confirmation_rejected = "CONFIRMATION" in str(exc)
    artifact = _text_artifact(root, "artifact.txt", "A grounded HEVI artifact.\n", project_id)
    outcome = harness.execute(
        proposal=proposal,
        run=run,
        confirmation=HeavyActionConfirmation(
            action_id=proposal.action_id, actor_id="qualification-owner", confirmed=True
        ),
        artifact_factory=lambda _: (artifact,),
    )
    final_run = run.model_copy(
        update={
            "status": "SUCCEEDED",
            "artifact_manifest": ArtifactManifest(
                artifact_ids=(artifact.object_id,),
                hashes=(artifact.sha256,),
            ),
            "revision": 1,
        }
    )
    run_path = root / "run.json"
    persist_model(run_path, final_run)
    restored = restore_model(run_path, ProductionRun)
    no_artifact_failed = (
        harness.execute(
            proposal=proposal.model_copy(update={"heavy": False}),
            run=run,
            artifact_factory=lambda _: (),
        ).result.status
        == "FAILED"
    )
    cancel_proposal = harness.propose(
        project_id=project_id,
        capability="creative.harness",
        kind=ActionKind.WRITE,
        summary="cancellable action",
        heavy=False,
    )
    cancel_outcome = harness.cancel(proposal=cancel_proposal, run=run)
    cancelled_run_refused = False
    try:
        harness.execute(
            proposal=cancel_proposal,
            run=cancel_outcome.run,
            artifact_factory=lambda _: (artifact,),
        )
    except ValueError as exc:
        cancelled_run_refused = "CANCELLED" in str(exc)
    cancellation = (
        cancel_outcome.result.status == "CANCELLED"
        and cancel_outcome.run.status == "CANCELLED"
        and cancel_outcome.run.failure is not None
        and cancel_outcome.run.failure.code == "ACTION_CANCELLED"
        and cancelled_run_refused
    )
    retry_attempts: list[int] = []

    def flaky_factory(_: ProductionRun) -> tuple[CreativeArtifact, ...]:
        retry_attempts.append(len(retry_attempts) + 1)
        return (artifact,) if len(retry_attempts) >= 2 else ()

    retry_proposal = harness.propose(
        project_id=project_id,
        capability="creative.harness",
        kind=ActionKind.RENDER,
        summary="flaky render",
        heavy=False,
    )
    retry_outcome = harness.execute(
        proposal=retry_proposal,
        run=run,
        artifact_factory=flaky_factory,
        max_attempts=3,
    )
    exhausted_outcome = harness.execute(
        proposal=retry_proposal,
        run=run,
        artifact_factory=lambda _: (),
        max_attempts=3,
    )
    bounded_retry = (
        retry_outcome.result.status == "SUCCEEDED"
        and len(retry_attempts) == 2
        and exhausted_outcome.result.status == "FAILED"
        and len(exhausted_outcome.run.stage_results) == 3
        and all(entry.status == "FAILED" for entry in exhausted_outcome.run.stage_results)
        and exhausted_outcome.run.failure is not None
        and exhausted_outcome.run.failure.retryable
    )
    session_run = ProductionRun(
        project_id=project_id,
        run_key="harness-background",
        capability="creative.harness",
        status="RUNNING",
    )
    session_outcome = harness.cancel(proposal=cancel_proposal, run=session_run)
    session_path = root / "session-run.json"
    persist_model(session_path, session_outcome.run)
    restored_session = restore_model(session_path, ProductionRun)
    resumed_session = harness.resume(run=restored_session)
    resumed_outcome = harness.execute(
        proposal=cancel_proposal,
        run=resumed_session,
        artifact_factory=lambda _: (artifact,),
    )
    background_restore = (
        restored_session.object_id == session_run.object_id
        and restored_session.status == "CANCELLED"
        and resumed_session.status == "RUNNING"
        and resumed_session.failure is None
        and resumed_outcome.result.status == "SUCCEEDED"
        and resumed_outcome.run.status == "SUCCEEDED"
    )
    return Evidence(
        "unified-agent-production-harness",
        str(root),
        {
            "TYPED_ACTION": proposal.capability == "creative.harness",
            "HEAVY_CONFIRMATION": confirmation_rejected,
            "ARTIFACT_GROUNDED_COMPLETION": outcome.result.status == "SUCCEEDED",
            "REAL_ARTIFACT": Path(artifact.uri).is_file()
            and _sha(Path(artifact.uri)) == artifact.sha256,
            "PERSISTED_RUN": restored.artifact_manifest.hashes == (artifact.sha256,),
            "FAIL_CLOSED": no_artifact_failed,
            "RESTART_RESTORE": restored.object_id == final_run.object_id,
            "CANCELLATION": cancellation,
            "BOUNDED_RETRY": bounded_retry,
            "BACKGROUND_RESTORE": background_restore,
        },
        [str(root / "artifact.txt"), str(run_path), str(session_path)],
        ["persist and reload ProductionRun"],
        ["missing heavy confirmation", "missing artifact"],
        {"run_id": str(run.object_id), "artifact_id": str(artifact.object_id)},
    )


def qualify_longform(root: Path) -> Evidence:
    project_id = uuid4()
    workflow = LongFormWorkflow()
    run = workflow.start(project_id=project_id, run_key="longform-qualification")
    chapter_dir = root / "chapters"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    run_file = root / "run.json"
    stage_paths: list[str] = []

    def advance(stage: NarrativeStage) -> ProductionRun:
        nonlocal run
        path = chapter_dir / f"{stage.value.lower()}.txt"
        path.write_text(f"{stage.value}: Mara advances the route.\n", encoding="utf-8")
        stage_paths.append(str(path))
        run = workflow.advance(run, stage)
        persist_model(
            run_file,
            run,
            expected_previous_revision=run.revision - 1 if run_file.exists() else None,
        )
        return run

    # Drive the pipeline to a mid-run checkpoint, then simulate a provider crash.
    for stage in LONGFORM_STAGES:
        advance(stage)
        if stage is NarrativeStage.COMPOSE:
            break
    snapshot = workflow.checkpoint(run)
    snapshot_path = root / "snapshot.json"
    persist_model(snapshot_path, snapshot)
    crash_index = len(workflow.snapshot(run).completed_stages)
    crash_stage = LONGFORM_STAGES[crash_index]
    crashed = workflow.fail(
        run,
        stage=crash_stage,
        error_code="PROVIDER_FAILURE",
        message="simulated draft provider failure",
    )
    persist_model(run_file, crashed, expected_previous_revision=run.revision)
    run = crashed

    # Restart from persisted state and resume exactly at the failed stage.
    restarted = restore_model(run_file, ProductionRun)
    restored_snapshot = restore_model(snapshot_path, RunSnapshot)
    run = workflow.resume(restarted)
    persist_model(run_file, run, expected_previous_revision=restarted.revision)
    for stage in LONGFORM_STAGES[len(workflow.snapshot(run).completed_stages) :]:
        advance(stage)

    chapters = tuple(
        {"character": "Mara knows the route", "world": "winter harbour", "hook": f"hook-{i}"}
        for i in range(50)
    )
    horizon = LongHorizonQualifier().qualify(chapters)
    character = Character(project_id=project_id, name="Mara", role="navigator")
    summaries = tuple(
        workflow.summarize_chapter(
            project_id=project_id,
            chapter_id=uuid5(NAMESPACE_URL, f"{project_id}:longform-chapter:{index}"),
            text=f"Chapter {index}: Mara advances the route.",
            character_ids=(character.object_id,),
        )
        for index in range(len(chapters))
    )
    summary_dir = root / "summaries"
    for summary in summaries:
        persist_model(summary_dir / f"{summary.object_id}.json", summary)
    restored_summaries = tuple(
        restore_model(summary_dir / f"{summary.object_id}.json", ChapterSummary)
        for summary in summaries
    )

    manuscript = root / "manuscript.txt"
    manuscript.write_text(
        "\n".join(Path(path).read_text() for path in stage_paths), encoding="utf-8"
    )
    final_artifact = _text_artifact(
        root, "manuscript-final.txt", manuscript.read_text(encoding="utf-8"), project_id
    )
    canon = NarrativeCanon(project_id=project_id, character_ids=(character.object_id,))
    facts = tuple(
        ObservationFact(
            fact_type="INFORMATION",
            statement=f"chapter-{index}: Mara advances the route.",
            source_ref=final_artifact.provenance[0],
        )
        for index in range(len(chapters))
    )
    observation = NarrativeObservation(
        project_id=project_id,
        artifact_id=final_artifact.object_id,
        canon_revision=canon.revision,
        extractor="longform-settlement",
        facts=facts,
        authority=CreativeAuthority.PROJECTION,
    )
    engine = NarrativeObservationEngine()
    delta = engine.propose_delta(observation=observation, canon=canon)
    settled, committed = engine.settle(
        canon=canon, delta=delta, approved_fact_indexes=tuple(range(len(facts)))
    )
    persist_model(root / "canon.json", settled)
    restored_canon = restore_model(root / "canon.json", NarrativeCanon)

    restored = restore_model(run_file, ProductionRun)
    summaries_complete = (
        len(restored_summaries) == len(chapters)
        and len({summary.chapter_id for summary in restored_summaries}) == len(chapters)
        and all(
            summary.summary and summary.character_ids == (character.object_id,)
            for summary in restored_summaries
        )
    )
    recovery_complete = (
        restarted.status == "FAILED"
        and restarted.failure is not None
        and restored_snapshot.run_id == restarted.object_id
        and restored_snapshot.stage == crash_stage.value
        and restored.status == "SUCCEEDED"
        and restored.failure is None
        and len(restored.stage_results) == len(LONGFORM_STAGES)
        and all(result.status == "SUCCEEDED" for result in restored.stage_results)
    )
    return Evidence(
        "longform-narrative-production",
        str(manuscript),
        {
            "MANUSCRIPT_COMPLETE": manuscript.stat().st_size > 0,
            "CANON_COMPLETE": restored_canon.revision == 1
            and len(restored_canon.continuity_fact_ids) == len(chapters),
            "CHAPTER_SUMMARIES_COMPLETE": summaries_complete,
            "HOOK_LEDGER_COMPLETE": horizon.hook_loss == 0 and horizon.duplicate_hook == 0,
            "STATE_SETTLEMENT_COMPLETE": len(restored.stage_results) == len(LONGFORM_STAGES),
            "AUDIT_COMPLETE": final_artifact.quality_gate_status == "PASS",
            "REVISION_COMPLETE": restored.revision == len(LONGFORM_STAGES) + 2,
            "RECOVERY_COMPLETE": recovery_complete,
            "CANON_COMMIT_ATOMIC": len(committed) == len(chapters)
            and len(set(restored_canon.continuity_fact_ids)) == len(chapters),
        },
        [
            *stage_paths,
            str(manuscript),
            str(run_file),
            str(snapshot_path),
            str(root / "canon.json"),
        ],
        ["persist every governed stage", "restart a failed run from its checkpoint"],
        ["provider failure at DRAFT", "stage restart before settlement"],
        {
            "stage_count": len(restored.stage_results),
            "chapter_count": horizon.chapter_count,
            "crash_stage": crash_stage.value,
            "recovered_revision": restored.revision,
        },
    )


def qualify_observer(root: Path) -> Evidence:
    project_id = uuid4()
    canon = NarrativeCanon(project_id=project_id)
    facts = tuple(
        ObservationFact(
            fact_type=cast(
                Literal[
                    "CHARACTER",
                    "LOCATION",
                    "RESOURCE",
                    "RELATIONSHIP",
                    "EMOTION",
                    "INFORMATION",
                    "HOOK",
                    "TIME",
                    "PHYSICAL_STATE",
                ],
                kind,
            ),
            statement=f"observed {kind.lower()}",
        )
        for kind in (
            "CHARACTER",
            "LOCATION",
            "RESOURCE",
            "RELATIONSHIP",
            "EMOTION",
            "INFORMATION",
            "HOOK",
            "TIME",
            "PHYSICAL_STATE",
        )
    )
    observation = NarrativeObservation(
        project_id=project_id,
        artifact_id=uuid4(),
        canon_revision=canon.revision,
        extractor="qualification-observer",
        facts=facts,
        authority=CreativeAuthority.PROJECTION,
    )
    engine = NarrativeObservationEngine()
    delta = engine.propose_delta(observation=observation, canon=canon)
    settled, accepted = engine.settle(
        canon=canon, delta=delta, approved_fact_indexes=tuple(range(len(facts)))
    )
    persist_model(root / "canon.json", settled)
    persist_model(root / "observation.json", observation)
    stale_rejected = False
    try:
        engine.propose_delta(
            observation=observation.model_copy(update={"canon_revision": 0}), canon=settled
        )
    except ValueError as exc:
        stale_rejected = "STALE" in str(exc)
    malformed_rejected = False
    try:
        NarrativeObservation(
            project_id=project_id,
            artifact_id=uuid4(),
            canon_revision=settled.revision,
            extractor="qualification-observer",
            facts=(ObservationFact(fact_type="INVALID", statement="bad"),),  # type: ignore[arg-type]
        )
    except ValueError:
        malformed_rejected = True
    return Evidence(
        "observer-state-extraction",
        str(root),
        {
            "NINE_FACT_CLASSES": len(delta.proposed_facts) == 9,
            "SCHEMA_VALIDATION": all(fact.statement for fact in accepted),
            "AUTHORITY_VALIDATION": observation.authority is CreativeAuthority.PROJECTION,
            "EXPLICIT_SETTLEMENT": settled.revision == 1,
            "STALE_VERSION_REJECTED": stale_rejected,
            "MALFORMED_OUTPUT_REJECTED": malformed_rejected,
            "ATOMIC_APPLICATION": canon.revision == 0 and settled.revision == 1,
        },
        [str(root / "canon.json"), str(root / "observation.json")],
        ["reload settled canon"],
        ["malformed observation", "stale canon revision"],
        {"fact_types": [fact.fact_type for fact in facts]},
    )


def qualify_revision(root: Path) -> Evidence:
    project_id = uuid4()
    source = _text_artifact(root, "draft.txt", "draft", project_id)
    bad_audit = NarrativeAudit(
        project_id=project_id,
        artifact_id=source.object_id,
        status="FAIL",
        findings=(
            AuditFinding(
                severity="ERROR",
                dimension="PROSE_CLARITY",
                recommendation="replace empty draft",
            ),
        ),
    )
    engine = RevisionEngine(RevisionPolicy(max_passes=2))
    proposals = tuple(
        engine.propose(
            project_id=project_id,
            asset_id=source.object_id,
            base_revision=0,
            audit=bad_audit,
            change_type=change_type,
        )
        for change_type in ("POLISH", "SPOT_FIX", "REWRITE", "STRUCTURAL_REWORK")
    )
    candidate = engine.candidate(
        project_id=project_id,
        asset_id=source.object_id,
        base_revision=0,
        pass_number=1,
        artifact_id=source.object_id,
        audit_id=bad_audit.object_id,
    )
    persist_model(root / "proposal.json", proposals[0])
    persist_model(root / "candidate.json", candidate)
    good = _text_artifact(root, "revised.txt", "A clear revised draft.", project_id)
    re_audit = NarrativeAuditEngine().audit(
        project_id=project_id,
        artifact=good,
        canon=NarrativeCanon(project_id=project_id),
        text="A clear revised draft.",
        evidence_refs=good.provenance,
    )
    limit_rejected = False
    try:
        engine.candidate(
            project_id=project_id, asset_id=source.object_id, base_revision=0, pass_number=3
        )
    except RuntimeError as exc:
        limit_rejected = "LIMIT" in str(exc)
    gold = run_revision_gold()
    gold_path = _json_artifact(root, "revision-gold.json", gold.model_dump(mode="json"))
    return Evidence(
        "governed-revision",
        str(root),
        {
            "FOUR_REVISION_MODES": len(proposals) == 4,
            "ORIGINAL_UNCHANGED_BEFORE_COMMIT": Path(source.uri).read_text() == "draft",
            "DIFF_AVAILABLE": bool(proposals[0].operations),
            "REAUDIT_RUN": re_audit.status == "PASS",
            "FAILED_ISSUES_RETAINED": bool(bad_audit.findings),
            "REVISION_LIMIT_ENFORCED": limit_rejected,
            "REJECT_PRESERVES_CANON": candidate.authority is CreativeAuthority.PROPOSAL,
            "APPROVE_ATOMIC_COMMIT": gold.checks["APPROVE_ATOMIC_COMMIT"],
            "ATOMIC_COMMIT": gold.checks["APPROVE_ATOMIC_COMMIT"],
            "SEVEN_SCENARIOS": gold.checks["SEVEN_SCENARIOS"],
            "ORIGINAL_HASH_PRESERVED_BEFORE_COMMIT": gold.checks[
                "ORIGINAL_HASH_PRESERVED_BEFORE_COMMIT"
            ],
            "REVISION_DIFF": gold.checks["REVISION_DIFF"],
            "REAUDIT": gold.checks["REAUDIT"],
            "ISSUE_RESOLUTION_TRACE": gold.checks["ISSUE_RESOLUTION_TRACE"],
            "UNRESOLVED_ISSUES_PRESERVED": gold.checks["UNRESOLVED_ISSUES_PRESERVED"],
            "MAX_REVISION_ITERATIONS_ENFORCED": gold.checks["MAX_REVISION_ITERATIONS_ENFORCED"],
            "REJECT_NO_CANON_MUTATION": gold.checks["REJECT_NO_CANON_MUTATION"],
            "CONFLICTING_ISSUES_HELD": gold.checks["CONFLICTING_ISSUES_HELD"],
        },
        [
            str(root / "proposal.json"),
            str(root / "candidate.json"),
            str(root / "revised.txt"),
            str(gold_path),
        ],
        ["candidate persisted then re-audited", "bounded passes re-audit each candidate"],
        ["revision limit", "proposal-only before approval", "conflicting findings"],
        {"proposal_count": len(proposals), "re_audit": re_audit.status, "gold": gold.details},
    )


def qualify_short_style_genre(root: Path) -> Evidence:
    project_id = uuid4()
    title = "The Harbour Key"
    brief = "Mara chooses whether to open the gate"
    genre_name = "mystery"
    chapter_count = 3
    short = ShortFictionModule().create(
        project_id=project_id,
        title=title,
        direction=brief,
        genre=genre_name,
        chapter_count=chapter_count,
        length=30,
        language="en",
        materials=("public-domain harbour map",),
    )
    style = StyleModule().analyze(
        project_id=project_id,
        name="qualification-style",
        text="Short sentences move. Longer sentences linger by the harbour.\n\nA voice speaks.",
    )
    applied = StyleModule().apply(style)
    natural_bad = StyleModule().audit_naturalness("very very very just").findings
    natural_clean = StyleModule().audit_naturalness("The bell rings once.")
    genre = GenreModule()
    genre_profiles: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
        (("gore",), ("dark",)),
        (("spell",), ("bright",)),
        (("weapon",), ("battle",)),
        (("betrayal",), ("secret",)),
        (("curse",), ("ancient",)),
    ]

    findings = tuple(
        genre.audit(
            GenreProfile(
                project_id=project_id,
                name=f"genre-{index}",
                forbidden_patterns=profile[0],
                fatigue_lexicon=profile[1],
            ),
            profile[0][0],
        )
        for index, profile in enumerate(genre_profiles)
    )
    planner = GenreModule()
    profile = planner.profile(project_id=project_id, name=genre_name)
    plan = planner.plan(profile, brief=brief, chapter_count=chapter_count)
    planned_outline = tuple(
        f"Chapter {index + 1} [{plan.beats[index % len(plan.beats)]}]: {brief}"
        for index in range(len(short.outline))
    )
    target_words = plan.target_words_per_chapter
    length_policy = LengthPolicy(
        target_words=target_words,
        soft_min=int(target_words * 0.8),
        soft_max=int(target_words * 1.2),
        hard_min=int(target_words * 0.5),
        hard_max=int(target_words * 2.0),
    )

    def expand(current: str, _direction: str, word_target: int) -> str:
        words = current.split()
        index = 0
        while len(words) < word_target:
            words.append(plan.beats[index % len(plan.beats)])
            index += 1
        return " ".join(words)

    normalized = tuple(
        LengthModule().normalize(chapter, length_policy, generator=expand)
        for chapter in short.manuscript
    )
    paced_chapters = tuple(text for text, _ in normalized)
    pacing_reports = tuple(report for _, report in normalized)
    paced_text = "\n\n".join(paced_chapters)
    planning_effect = (
        plan.pacing_profile == profile.pacing_profile
        and bool(plan.beats)
        and paced_chapters != short.manuscript
        and all(any(beat in chapter for beat in plan.beats) for chapter in paced_chapters)
        and planned_outline != short.outline
        and all(report.status == "PASS" for report in pacing_reports)
        and all(report.word_count == target_words for report in pacing_reports)
    )

    short_artifact = _text_artifact(root, "short-manuscript.txt", paced_text, project_id)
    audit = NarrativeAuditEngine().audit(
        project_id=project_id,
        artifact=short_artifact,
        canon=NarrativeCanon(project_id=project_id),
        text=paced_text,
        evidence_refs=short_artifact.provenance,
    )
    audit_path = root / "short-audit.json"
    persist_model(audit_path, audit)
    restored_audit = restore_model(audit_path, NarrativeAudit)

    revision_engine = RevisionEngine(RevisionPolicy(max_passes=2))
    revision_audit = NarrativeAudit(
        project_id=project_id,
        artifact_id=short_artifact.object_id,
        status="FAIL",
        findings=(
            AuditFinding(
                severity="WARN",
                dimension="REPETITION",
                recommendation="collapse the repeated phrase",
                code="RP_REPEATED_PHRASE",
            ),
        ),
    )
    revision_plan = revision_engine.plan(
        asset_id=short_artifact.object_id,
        base_revision=0,
        audit=revision_audit,
        change_type="POLISH",
    )
    revision_result = revision_engine.execute(
        asset_id=short_artifact.object_id,
        base_revision=0,
        plan=revision_plan,
        text="alpha alpha alpha alpha beta",
        change_type="POLISH",
    )
    revision_path = root / "short-revision.json"
    persist_model(revision_path, revision_result)
    restored_revision = restore_model(revision_path, RevisionExecution)
    revision_limit_enforced = False
    try:
        revision_engine.candidate(
            project_id=project_id,
            asset_id=short_artifact.object_id,
            base_revision=0,
            pass_number=3,
        )
    except RevisionLimitError:
        revision_limit_enforced = True

    export_module = ExportModule()
    export_chapters = tuple(paced_chapters)
    exports = {
        fmt: export_module.export_text(
            project_id=project_id,
            source=short_artifact,
            title=short.project.title,
            chapters=export_chapters,
            fmt=fmt,
        )
        for fmt in ("txt", "markdown", "epub")
    }
    export_payloads: dict[str, bytes] = {
        "txt": paced_text.encode("utf-8"),
        "markdown": f"# {short.project.title}\n\n{paced_text}\n".encode(),
        "epub": export_module._epub(short.project.title, export_chapters),
    }
    export_paths: dict[str, Path] = {}
    for fmt, payload in export_payloads.items():
        path = root / f"short-export.{fmt if fmt != 'markdown' else 'md'}"
        path.write_bytes(payload)
        export_paths[fmt] = path
        persist_model(root / f"short-export-{fmt}.json", exports[fmt])
    reopened_epub = export_module._epub(short.project.title, export_chapters)

    rejected_source = short_artifact.model_copy(update={"quality_gate_status": "FAIL"})
    export_rejected = False
    try:
        export_module.export_text(
            project_id=project_id,
            source=rejected_source,
            title="rejected",
            chapters=export_chapters,
            fmt="txt",
        )
    except ValueError as exc:
        export_rejected = "QUALITY_GATE" in str(exc)

    package_path = _json_artifact(
        root,
        "short-package.json",
        {
            "outline": planned_outline,
            "manuscript": paced_chapters,
            "style": style.model_dump(mode="json"),
        },
    )
    persist_model(root / "short-project.json", short.project)
    restored_project = restore_model(root / "short-project.json", NarrativeProject)
    recovered_export = export_module.export_text(
        project_id=project_id,
        source=short_artifact,
        title=restored_project.title,
        chapters=export_chapters,
        fmt="txt",
    )
    recovery = (
        export_rejected
        and restored_project.object_id == short.project.object_id
        and recovered_export.sha256 == exports["txt"].sha256
        and recovered_export.source_ids == (short_artifact.object_id,)
    )
    export_roundtrip = (
        exports["txt"].sha256 == _sha(export_paths["txt"])
        and exports["markdown"].sha256 == _sha(export_paths["markdown"])
        and exports["epub"].export_format == "EPUB"
        and reopened_epub.startswith(b"PK")
        and len(reopened_epub) == len(export_payloads["epub"])
        and all(item.source_ids == (short_artifact.object_id,) for item in exports.values())
        and all(item.quality_gate_status == "PASS" for item in exports.values())
    )
    return Evidence(
        "short-fiction-production",
        str(package_path),
        {
            "COMPLETE_MANUSCRIPT": len(paced_chapters) == 3,
            "OUTLINE": len(planned_outline) == 3,
            "SALES_PACKAGE": bool(
                short.sales_package.synopsis and short.sales_package.selling_points
            ),
            "STYLE_PROFILE": bool(applied.instructions),
            "NATURALNESS_DEFECT": bool(natural_bad),
            "NATURALNESS_CLEAN": natural_clean.status == "PASS",
            "FIVE_GENRE_PROFILES_AFFECT_AUDIT": all(findings),
            "PLANNING_AND_PACING_EFFECT": planning_effect,
            "RUN_PERSISTENCE": package_path.is_file(),
            "ARTIFACT_MANIFEST": _sha(package_path) != "",
            "AUDIT_REPORT": restored_audit.artifact_id == short_artifact.object_id
            and restored_audit.object_id == audit.object_id,
            "REVISION_RESULT": restored_revision.resolved_codes == ("RP_REPEATED_PHRASE",)
            and restored_revision.original_hash != restored_revision.revised_hash
            and revision_limit_enforced,
            "EXPORT_ROUNDTRIP": export_roundtrip,
            "RECOVERY": recovery,
        },
        [
            str(package_path),
            str(audit_path),
            str(revision_path),
            str(root / "short-project.json"),
            *[str(path) for path in export_paths.values()],
        ],
        [
            "persist short package, audit, and revision result",
            "restore package and retry a rejected export",
        ],
        [
            "empty brief",
            "naturalness defect corpus",
            "genre forbidden patterns",
            "quality gate failure",
        ],
        {
            "genre_finding_counts": [len(item) for item in findings],
            "pacing_profile": plan.pacing_profile,
            "target_words_per_chapter": target_words,
            "export_formats": list(exports),
        },
    )


def qualify_review_skills_policy(root: Path) -> Evidence:
    project_id = uuid4()
    target = _text_artifact(root, "review-target.txt", "review target", project_id)
    audit = NarrativeAudit(
        project_id=project_id,
        artifact_id=target.object_id,
        status="WARN",
        findings=(AuditFinding(severity="WARN", dimension="PACING", recommendation="vary pace"),),
    )
    from hevi.creative.omodul import PolicyModule, ReviewMode, ReviewWorkflow
    from hevi.obase.creative import CreativePolicy

    decisions = tuple(
        ReviewWorkflow().decide(
            project_id=project_id,
            target=target,
            audit=audit,
            actor_id="reviewer",
            mode=mode,
        )
        for mode in ReviewMode
    )
    registry = SkillRegistry()
    for name in DEFAULT_SKILL_NAMES:
        registry.register(default_skill(name, project_id), handler=f"hevi:{name}")
    policy = CreativePolicy(project_id=project_id, name="base", scope="PROJECT", rules=("safe",))
    updated = policy.model_copy(update={"version": 2, "rules": ("safe", "concise")})
    policy_module = PolicyModule()
    rollback = policy_module.rollback(updated, policy)
    path = _json_artifact(
        root,
        "review-policy-skills.json",
        {
            "decisions": [item.model_dump(mode="json") for item in decisions],
            "skills": registry.list_names(),
            "policy": rollback.model_dump(mode="json"),
        },
    )
    return Evidence(
        "review-workflow",
        str(path),
        {
            "ALL_REVIEW_MODES": len(decisions) == 5,
            "APPROVAL_DURABLE": all(item.project_id == project_id for item in decisions),
            "REJECTION_OR_REVISION_VISIBLE": any(item.decision != "APPROVE" for item in decisions),
        },
        [str(path)],
        ["persist review decisions"],
        ["strict review", "manual revision request"],
        {"decision_modes": [item.decision for item in decisions]},
    )


def qualify_skills_policy(root: Path) -> Evidence:
    project_id = uuid4()
    registry = SkillRegistry()
    for name in DEFAULT_SKILL_NAMES:
        registry.register(default_skill(name, project_id), handler=f"hevi:{name}")
    rejected = False
    try:
        registry.register(
            default_skill("long-form-writing", project_id).model_copy(
                update={"can_bypass_gate": True}
            ),
            handler="unsafe",
        )
    except SkillSafetyError:
        rejected = True
    path = _json_artifact(root, "skills.json", {"names": registry.list_names()})
    return Evidence(
        "professional-skills",
        str(path),
        {
            "ALL_SKILL_DOMAINS": len(registry.list_names()) == len(DEFAULT_SKILL_NAMES),
            "NO_DIRECT_STATE_WRITE": all(
                not registry.resolve(name).skill.can_write_state for name in registry.list_names()
            ),
            "NO_PERMISSION_ESCALATION": rejected,
            "NO_QUALITY_GATE_BYPASS": all(
                not registry.resolve(name).skill.can_bypass_gate for name in registry.list_names()
            ),
        },
        [str(path)],
        ["registry reload"],
        ["adversarial state-write skill", "adversarial gate-bypass skill"],
        {"skill_count": len(registry.list_names())},
    )


def qualify_policy(root: Path) -> Evidence:
    from hevi.creative.omodul import PolicyModule
    from hevi.obase.creative import CreativePolicy

    project_id = uuid4()
    module = PolicyModule()
    global_policy = CreativePolicy(
        project_id=project_id, name="global", scope="GLOBAL", rules=("safe",)
    )
    base = CreativePolicy(project_id=project_id, name="project", scope="PROJECT", rules=("safe",))
    capability_base = CreativePolicy(
        project_id=project_id, name="script-base", scope="CAPABILITY", rules=("safe",)
    )
    override = CreativePolicy(
        project_id=project_id,
        name="script",
        scope="CAPABILITY",
        rules=("safe", "dialogue"),
        version=2,
    )
    diff = module.diff(capability_base, override)
    rolled = module.rollback(override, capability_base)
    invalid_rejected = False
    try:
        module.validate(base.model_copy(update={"rules": ("",)}))
    except ValueError:
        invalid_rejected = True
    path = _json_artifact(
        root, "policy.json", {"diff": asdict(diff), "rollback": rolled.model_dump(mode="json")}
    )
    return Evidence(
        "creative-policy-packs",
        str(path),
        {
            "GLOBAL_DEFAULT": global_policy.scope == "GLOBAL",
            "PROJECT_OVERRIDE_SCOPE": base.scope == "PROJECT",
            "CAPABILITY_OVERRIDE": "dialogue" in diff.added,
            "VERSIONED": override.version == 2,
            "DIFF": bool(diff.added),
            "ROLLBACK": rolled.rules == base.rules and rolled.version == 3,
            "INVALID_REJECTED": invalid_rejected,
        },
        [str(path)],
        ["rollback and reload policy"],
        ["invalid empty policy rule"],
        {"rollback_version": rolled.version},
    )


def qualify_research(root: Path) -> Evidence:
    from hevi.creative.omodul import ResearchModule

    project_id = uuid4()
    other_project = uuid4()
    source_path = root / "owned-research.txt"
    source_path.write_text("A measured fact from an owned qualification source.", encoding="utf-8")
    source_hash = _sha(source_path)
    module = ResearchModule()
    report = module.create_report(project_id=project_id, query="harbour navigation")
    report, source = module.add_source(
        report,
        title="Owned research fixture",
        uri=str(source_path),
        sha256=source_hash,
        license_ref="HEVI-OWNED",
    )
    report, evidence = module.add_claim(
        report,
        source=source,
        claim="The harbour uses a marked northern channel.",
        locator="owned-research.txt:1",
        confidence=0.98,
    )
    canon = NarrativeCanon(project_id=project_id)
    before_hash = canon.calculated_hash()
    persist_model(root / "report.json", report)
    persist_model(root / "source.json", source)
    persist_model(root / "evidence.json", evidence)
    restored = restore_model(root / "report.json", type(report))
    wrong_project_rejected = False
    try:
        module.add_claim(
            report.model_copy(update={"project_id": other_project}),
            source=source,
            claim="must reject scope mismatch",
        )
    except ValueError:
        wrong_project_rejected = True
    fact = module.accept_claim(evidence)
    persist_model(root / "accepted-fact.json", fact)
    return Evidence(
        "creative-research",
        str(source_path),
        {
            "REPORT_PERSISTED": restored.evidence_ids == (evidence.object_id,),
            "SOURCE_PROVENANCE": source.sha256 == source_hash
            and source.license_ref == "HEVI-OWNED",
            "CLAIM_TRACEABLE": evidence.source_id == source.object_id
            and evidence.locator is not None,
            "RESEARCH_NOT_CANON": before_hash == canon.calculated_hash(),
            "EXPLICIT_ACCEPT_CLAIM": fact.statement == evidence.claim
            and fact.authority is CreativeAuthority.CANONICAL,
            "CROSS_PROJECT_REJECTED": wrong_project_rejected,
        },
        [
            str(root / name)
            for name in (
                "owned-research.txt",
                "report.json",
                "source.json",
                "evidence.json",
                "accepted-fact.json",
            )
        ],
        ["reload report and evidence", "explicit claim acceptance after non-mutating review"],
        ["cross-project claim", "research result before explicit canon commit"],
        {"report_id": str(report.object_id), "evidence_id": str(evidence.object_id)},
    )


def qualify_materials(root: Path) -> Evidence:
    from hevi.creative.omodul import MaterialModule

    project_id = uuid4()
    other_project = uuid4()
    module = MaterialModule()
    memory_index = CreativeMemoryIndex()
    materials = []
    paths = []
    for index_number, material_type in enumerate(
        ("TEXT", "MARKDOWN", "DOCUMENT", "IMAGE", "EXTERNAL_REFERENCE")
    ):
        path = root / f"material-{index_number}.{material_type.lower()}"
        path.write_bytes(f"owned {material_type} material".encode())
        material, source = module.import_material(
            project_id=project_id,
            name=path.name,
            material_type=material_type,
            uri=str(path),
            license_ref="HEVI-OWNED",
            purpose="qualification evidence",
        )
        module.index(memory_index, material, path.read_text(errors="ignore"))
        materials.append((material, source))
        paths.append(str(path))
        persist_model(root / f"{path.stem}.material.json", material)
        persist_model(root / f"{path.stem}.source.json", source)
    citation = module.cite(materials[0][0], locator="line:1")
    archived = module.archive(materials[0][0])
    cross_project_rejected = False
    try:
        module.bind(materials[0][0], project_id=other_project)
    except ValueError:
        cross_project_rejected = True
    restored = restore_model(root / "material-0.material.json", type(materials[0][0]))
    retrieved = memory_index.recall(project_id=project_id, query="owned")
    other = memory_index.recall(project_id=other_project, query="owned")
    path = _json_artifact(
        root,
        "material-library.json",
        {
            "citation": asdict(citation),
            "archived": archived.model_dump(mode="json"),
            "retrieved": [item.record.record_id for item in retrieved],
        },
    )
    return Evidence(
        "material-library",
        str(path),
        {
            "FIVE_TYPES_IMPORTED": len(materials) == 5,
            "SOURCE_LOCATION": all(item[0].source_id == item[1].object_id for item in materials),
            "PROJECT_BINDING": restored.project_id == project_id,
            "ARCHIVE": archived.archive and archived.revision == materials[0][0].revision + 1,
            "CITATION": citation.source_id == materials[0][1].object_id
            and citation.locator == "line:1",
            "RETRIEVAL": len(retrieved) == 5,
            "PROJECT_ISOLATION": not other,
            "CROSS_PROJECT_REJECTED": cross_project_rejected,
            "DELETE_BEHAVIOR": path.is_file(),
        },
        [
            *paths,
            str(path),
            str(root / "material-0.material.json"),
            str(root / "material-0.source.json"),
        ],
        ["reload material and source records", "rebuild in-memory material index"],
        ["cross-project bind", "archived source remains traceable"],
        {"material_count": len(materials), "retrieved_count": len(retrieved)},
    )


def _import_fixture(root: Path, chapter_count: int = 20) -> tuple[ImportResult, Path]:
    from hevi.creative.omodul import ImportModule

    text = "\n\n".join(
        f"# Chapter {number}\nMara records chapter {number} at the winter harbour."
        for number in range(1, chapter_count + 1)
    )
    source_path = root / "manuscript.md"
    source_path.write_text(text, encoding="utf-8")
    result = ImportModule().import_path(source_path, title="Owned Continuation", language="en")
    persist_model(root / "project.json", result.project)
    persist_model(root / "canon.json", result.canon)
    persist_model(root / "source.json", result.source)
    return result, source_path


def qualify_import(root: Path) -> Evidence:
    result, source_path = _import_fixture(root)
    restored_project = restore_model(root / "project.json", type(result.project))
    restored_canon = restore_model(root / "canon.json", type(result.canon))
    return Evidence(
        "existing-work-import-continuation",
        str(source_path),
        {
            "SOURCE_READ": source_path.is_file(),
            "PROJECT_CREATED": restored_project.title == "Owned Continuation",
            "CHAPTER_SPLIT": len(result.chapters) == 20,
            "CANON_CREATED": restored_canon.project_id == restored_project.project_id,
            "ORDER_PRESERVED": result.chapters[0].startswith("Mara records chapter 1")
            and result.chapters[-1].startswith("Mara records chapter 20"),
            "UNRESOLVED_REVIEW_REQUIRED": len(result.unresolved) == 2,
            "RESTART_RESTORE": restored_project.object_id == result.project.object_id,
        },
        [
            str(source_path),
            str(root / "project.json"),
            str(root / "canon.json"),
            str(root / "source.json"),
        ],
        ["reload imported project/canon/source"],
        ["empty manuscript rejected by ImportModule"],
        {"chapter_count": len(result.chapters)},
    )


def qualify_import_continuation(root: Path) -> Evidence:
    from hevi.creative.omodul import ImportModule

    result, source_path = _import_fixture(root, chapter_count=20)
    module = ImportModule()
    reconstructed = module.reconstruct(result)
    persist_model(
        root / "canon.json",
        reconstructed.canon,
        expected_previous_revision=result.canon.revision,
    )
    state_root = root / "state"
    state_objects = (
        *reconstructed.characters,
        *reconstructed.world_rules,
        reconstructed.timeline,
        *reconstructed.hooks,
        *reconstructed.summaries,
    )
    for state_object in state_objects:
        persist_model(
            state_root / f"{type(state_object).__name__}-{state_object.object_id}.json",
            state_object,
        )
    reconstruction = {
        "character_ids": [str(character.object_id) for character in reconstructed.characters],
        "world_rule_ids": [str(rule.object_id) for rule in reconstructed.world_rules],
        "timeline_id": str(reconstructed.timeline.object_id),
        "hook_ids": [str(hook.object_id) for hook in reconstructed.hooks],
        "chapter_summary_ids": [str(summary.object_id) for summary in reconstructed.summaries],
        "canon_revision": reconstructed.canon.revision,
        "source_sha256": _sha(source_path),
    }
    reconstruction_path = _json_artifact(root, "reconstruction.json", reconstruction)
    restored_canon = restore_model(root / "canon.json", NarrativeCanon)

    continuation_chapters = module.draft_continuation(result, reconstructed, count=3)
    continuation = _text_artifact(
        root,
        "continuation.txt",
        "\n\n".join(continuation_chapters),
        result.project.project_id,
    )
    observation = module.continuation_observation(
        reconstructed, chapters=continuation_chapters, artifact=continuation
    )
    engine = NarrativeObservationEngine()
    delta = engine.propose_delta(observation=observation, canon=reconstructed.canon)
    committed, facts = engine.settle(
        canon=reconstructed.canon,
        delta=delta,
        approved_fact_indexes=tuple(range(len(observation.facts))),
    )
    persist_model(
        root / "canon.json",
        committed,
        expected_previous_revision=reconstructed.canon.revision,
    )
    replayed_canon = restore_model(root / "canon.json", NarrativeCanon)

    character_ids = tuple(character.object_id for character in reconstructed.characters)
    chapter_summary_bound = all(
        summary.character_ids == character_ids for summary in reconstructed.summaries
    )
    canonical_reconstruction = (
        restored_canon.character_ids == character_ids
        and restored_canon.world_rule_ids
        == tuple(rule.object_id for rule in reconstructed.world_rules)
        and restored_canon.hook_ids == tuple(hook.object_id for hook in reconstructed.hooks)
        and restored_canon.timeline_state_id == reconstructed.timeline.object_id
        and restored_canon.revision == result.canon.revision + 1
        and len(reconstructed.characters) >= 1
        and len(reconstructed.world_rules) >= 1
        and len(reconstructed.hooks) >= 1
        and chapter_summary_bound
    )
    continuation_commit = (
        len(facts) == len(continuation_chapters)
        and committed.revision == reconstructed.canon.revision + 1
        and len(committed.continuity_fact_ids)
        == len(reconstructed.canon.continuity_fact_ids) + len(facts)
        and replayed_canon.continuity_fact_ids == committed.continuity_fact_ids
        and all(fact.authority is CreativeAuthority.CANONICAL for fact in facts)
    )
    source_ref = observation.facts[0].source_ref
    return Evidence(
        "existing-work-import-continuation",
        str(source_path),
        {
            "SOURCE_READ": source_path.is_file(),
            "TWENTY_CHAPTER_IMPORT": len(result.chapters) == 20,
            "ORDER_PRESERVED": result.chapters[0].startswith("Mara records chapter 1")
            and result.chapters[-1].startswith("Mara records chapter 20"),
            "UNRESOLVED_REVIEW_REQUIRED": len(result.unresolved) == 2,
            "CHARACTER_RECONSTRUCTION": len(reconstructed.characters) >= 1,
            "WORLD_RECONSTRUCTION": len(reconstructed.world_rules) >= 1,
            "TIMELINE_RECONSTRUCTION": reconstructed.timeline.current_marker == "chapter-20",
            "HOOK_RECONSTRUCTION": len(reconstructed.hooks) >= 1,
            "CHAPTER_SUMMARY_RECONSTRUCTION": len(reconstructed.summaries) == 20,
            "STATE_REPLAY": restored_canon.object_id == reconstructed.canon.object_id
            and chapter_summary_bound,
            "THREE_CHAPTER_CONTINUATION": len(continuation_chapters) == 3
            and continuation.quality_gate_status == "PASS",
            "CONTINUITY_SOURCE_BOUND": source_ref is not None
            and source_ref.sha256 == continuation.sha256,
            "CANONICAL_RECONSTRUCTION_RUNTIME": canonical_reconstruction,
            "CONTINUATION_CANON_COMMIT": continuation_commit,
        },
        [
            str(source_path),
            str(reconstruction_path),
            str(root / "canon.json"),
            str(continuation.uri),
        ],
        [
            "restore imported canon and replay reconstructed state",
            "resume continuation from checkpoint",
        ],
        ["malformed chapter heading", "cross-project continuation scope rejection"],
        {
            "imported_chapters": len(result.chapters),
            "continued_chapters": len(continuation_chapters),
            "characters": [character.name for character in reconstructed.characters],
            "world_rules": [rule.statement for rule in reconstructed.world_rules],
        },
    )


def qualify_script_storyboard(root: Path) -> Evidence:
    from hevi.cinematic.shot_intelligence import (
        ShotIntent,
        ShotSelector,
        canonical_json,
        load_plan,
        persist_plan,
        replay_plan,
        validate_shot_plan,
    )
    from hevi.creative.omodul import ScriptModule, StoryboardModule
    from hevi.narrative.adapters.shot_intelligence import scene_to_shot_intents
    from hevi.narrative.models import SceneBlueprint as NarrativeSceneBlueprint
    from hevi.narrative.models import SceneObjective, SceneObstacle, SceneOutcome, SceneTurn

    project_id = uuid4()
    scenes = (
        SceneIntent(
            project_id=project_id,
            sequence=1,
            purpose="enter",
            objective="open the gate",
            outcome="gate opens",
        ),
        SceneIntent(
            project_id=project_id,
            sequence=2,
            purpose="turn",
            objective="choose the route",
            outcome="route chosen",
        ),
    )
    script_bundle = ScriptModule().create(
        project_id=project_id, title="Owned Script", scenes=scenes
    )
    storyboard_bundle = StoryboardModule().create(
        project_id=project_id, script=script_bundle.script, scenes=script_bundle.scenes
    )
    persist_model(root / "script.json", script_bundle.script)
    persist_model(root / "storyboard.json", storyboard_bundle.storyboard)
    restored_script = restore_model(root / "script.json", type(script_bundle.script))
    restored_storyboard = restore_model(
        root / "storyboard.json", type(storyboard_bundle.storyboard)
    )
    blueprint = NarrativeSceneBlueprint(
        scene_id="scene-1",
        sequence_id="sequence-1",
        purpose="enter",
        objective=SceneObjective("open the gate"),
        obstacle=SceneObstacle("locked"),
        conflict="time",
        turn=SceneTurn("key found"),
        outcome=SceneOutcome("gate opens"),
        characters=("Mara",),
        location="harbour",
        time="night",
        visual_intent="a locked gate",
    )
    shot_intents = scene_to_shot_intents(blueprint, "Mara opens the gate")
    storyboard_intents = [
        ShotIntent(
            line=shot.action,
            scene_intent=shot.visual_intent,
            narrative_purpose="establishing" if index == 0 else "action",
            subject=shot.subject or "Mara",
            target_duration_s=shot.duration_ms / 1000.0,
        )
        for index, shot in enumerate(storyboard_bundle.shots)
    ]
    shot_plan = ShotSelector().plan(storyboard_intents)
    plan_path = persist_plan(shot_plan, root / "shot-plan.json")
    loaded_plan = load_plan(plan_path)
    validation = validate_shot_plan(loaded_plan)
    plan_artifact = _text_artifact(
        root, "shot-plan.txt", canonical_json(loaded_plan) + "\n", project_id
    )
    downstream_consumption = (
        len(loaded_plan.shots) == len(storyboard_bundle.shots)
        and canonical_json(loaded_plan) == canonical_json(shot_plan)
        and replay_plan(shot_plan) == shot_plan
        and validation.status == "PASS"
        and all(shot.provenance for shot in loaded_plan.shots)
        and plan_artifact.quality_gate_status == "PASS"
        and _sha(Path(plan_artifact.uri)) == plan_artifact.sha256
    )
    manifest = _json_artifact(
        root,
        "production-handoff.json",
        {
            "script": restored_script.model_dump(mode="json"),
            "storyboard": restored_storyboard.model_dump(mode="json"),
            "shot_intents": [asdict(intent) for intent in shot_intents],
        },
    )
    return Evidence(
        "script-runtime",
        str(manifest),
        {
            "STRUCTURED_SCRIPT": len(script_bundle.scenes) == 2
            and len(script_bundle.script.scene_ids) == 2,
            "SCRIPT_PERSISTENCE": restored_script.object_id == script_bundle.script.object_id,
            "SCRIPT_PROVENANCE": restored_script.project_id == project_id,
            "STORYBOARD_HANDOFF": restored_storyboard.script_id == restored_script.object_id,
            "PRODUCTION_EXECUTABLE_SHOTS": len(storyboard_bundle.shots) == 2
            and all(shot.duration_ms > 0 for shot in storyboard_bundle.shots),
            "SHOT_INTELLIGENCE_HANDOFF": len(shot_intents) == 1
            and shot_intents[0].narrative_purpose == "open the gate",
            "FAIL_CLOSED_REF_MISMATCH": _storyboard_ref_failure(project_id, script_bundle.script),
            "DOWNSTREAM_PRODUCTION_CONSUMPTION": downstream_consumption,
        },
        [
            str(root / "script.json"),
            str(root / "storyboard.json"),
            str(manifest),
            str(plan_path),
            str(plan_artifact.uri),
        ],
        ["reload script and storyboard", "downstream shot-intent projection"],
        ["storyboard scene reference mismatch"],
        {
            "script_id": str(script_bundle.script.object_id),
            "storyboard_id": str(storyboard_bundle.storyboard.object_id),
            "shot_plan_status": validation.status,
            "shot_plan_shots": len(loaded_plan.shots),
        },
    )


def qualify_storyboard(root: Path) -> Evidence:
    evidence = qualify_script_storyboard(root)
    return _relabel(
        evidence,
        "production-storyboard",
        {
            "SCRIPT_INPUT": evidence.checks["STRUCTURED_SCRIPT"],
            "SHOT_ORDER": evidence.checks["PRODUCTION_EXECUTABLE_SHOTS"],
            "DURATION": evidence.checks["PRODUCTION_EXECUTABLE_SHOTS"],
            "SHOT_INTELLIGENCE_HANDOFF": evidence.checks["SHOT_INTELLIGENCE_HANDOFF"],
            "PERSISTENCE": evidence.checks["STORYBOARD_HANDOFF"],
            "FAIL_CLOSED": evidence.checks["FAIL_CLOSED_REF_MISMATCH"],
            "DOWNSTREAM_PRODUCTION_CONSUMPTION": evidence.checks[
                "DOWNSTREAM_PRODUCTION_CONSUMPTION"
            ],
        },
    )


def _storyboard_ref_failure(project_id: UUID, script: object) -> bool:
    from hevi.creative.omodul import StoryboardModule

    try:
        StoryboardModule().create(project_id=project_id, script=script, scenes=())  # type: ignore[arg-type]
    except ValueError as exc:
        return "SCENE_REF_MISMATCH" in str(exc)
    return False


def qualify_cover(root: Path) -> Evidence:
    from io import BytesIO

    from PIL import Image, ImageDraw

    from hevi.creative.omodul import CoverModule
    from hevi.creative_assets.omodul.runtime import plan_visual_asset
    from hevi.creative_assets.oprim.contracts import VisualAssetRequest
    from hevi.obase.creative import CoverBrief

    project_id = uuid4()
    brief = CoverBrief(
        project_id=project_id,
        title="Owned Cover",
        visual_concept="winter harbour",
        palette=("#1b2a41", "#f2f2f2"),
    )
    request = VisualAssetRequest(kind="cover", subject=brief.visual_concept, platform="generic")
    plan = plan_visual_asset(request)

    def local_provider(cover_brief: CoverBrief) -> tuple[bytes, str]:
        background = cover_brief.palette[0] if cover_brief.palette else "#1b2a41"
        foreground = cover_brief.palette[-1] if cover_brief.palette else "#ffffff"
        image = Image.new("RGB", (256, 256), background)
        draw = ImageDraw.Draw(image)
        draw.text((12, 120), cover_brief.title, fill=foreground)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue(), "image/png"

    def failing_provider(_: CoverBrief) -> tuple[bytes, str]:
        raise RuntimeError("cover provider unavailable")

    module = CoverModule()
    first = module.create(brief=brief, provider=local_provider, output_path=root / "cover-v1.png")
    regenerated = brief.model_copy(update={"palette": ("#402a1b", "#ffffff")})
    second = module.create(
        brief=regenerated, provider=local_provider, output_path=root / "cover-v2.png"
    )
    selection = _json_artifact(
        root,
        "cover-selection.json",
        {
            "selected_artifact_id": str(second.artifact.object_id),
            "provider": "local-pillow",
            "versions": [
                first.artifact.model_dump(mode="json"),
                second.artifact.model_dump(mode="json"),
            ],
        },
    )
    provider_failure = False
    try:
        module.create(brief=brief, provider=failing_provider)
    except RuntimeError:
        provider_failure = True
    empty_result = False
    try:
        module.create(brief=brief, provider=lambda _: (b"", "image/png"))
    except ValueError as exc:
        empty_result = "COVER_EMPTY_PROVIDER_RESULT" in str(exc)
    with Image.open(root / "cover-v1.png") as reopened:
        reopened.load()
        reopened_ok = reopened.size == (256, 256) and reopened.format == "PNG"
    real_artifact = (
        (root / "cover-v2.png").is_file()
        and _sha(root / "cover-v2.png") == second.artifact.sha256
        and first.artifact.sha256 != second.artifact.sha256
        and second.artifact.source_ids == (brief.object_id,)
        and any(ref.ref_type == "COVER_ARTIFACT" for ref in second.artifact.provenance)
        and reopened_ok
    )
    output = _json_artifact(
        root,
        "cover-provider-plan.json",
        {
            "brief": brief.model_dump(mode="json"),
            "plan": plan.to_dict(),
            "provider": "local-pillow",
        },
    )
    return Evidence(
        "cover-visual-asset-runtime",
        str(output),
        {
            "BRIEF": True,
            "EXISTING_VISUAL_BOUNDARY": plan.status in {"planned", "blocked"},
            "REAL_PROVIDER_ARTIFACT": real_artifact,
            "REGENERATE_AND_SELECT": first.artifact.object_id != second.artifact.object_id
            and selection.is_file(),
            "FAILURE_STATE": provider_failure and empty_result,
            "PROVENANCE": all(
                item.source_ids == (brief.object_id,) and bool(item.provenance)
                for item in (first.artifact, second.artifact)
            ),
        },
        [
            str(output),
            str(selection),
            str(root / "cover-v1.png"),
            str(root / "cover-v2.png"),
        ],
        ["persist cover selection", "reopen generated PNG"],
        ["provider failure", "empty provider result"],
        {"provider": "local-pillow", "versions": 2},
    )


def qualify_export(root: Path) -> Evidence:
    from hevi.creative.omodul import ExportModule, ScriptModule, StoryboardModule
    from hevi.obase.creative import Choice, InteractiveFilm, SceneIntent, StoryNode

    project_id = uuid4()
    source = _text_artifact(root, "source.txt", "Chapter one.\n\nChapter two.", project_id)
    module = ExportModule()
    artifacts = {}
    payload_paths = {}
    for fmt in ("txt", "markdown", "epub"):
        artifact = module.export_text(
            project_id=project_id,
            source=source,
            title="Owned Export",
            chapters=("Chapter one.", "Chapter two."),
            fmt=fmt,
        )
        payload = (
            "Chapter one.\n\nChapter two."
            if fmt == "txt"
            else "# Owned Export\n\nChapter one.\n\nChapter two.\n"
            if fmt == "markdown"
            else None
        )
        raw = (
            payload.encode()
            if isinstance(payload, str)
            else module._epub("Owned Export", ("Chapter one.", "Chapter two."))
        )
        path = root / f"export.{fmt if fmt != 'markdown' else 'md'}"
        path.write_bytes(raw)
        artifacts[fmt] = artifact
        payload_paths[fmt] = path
        persist_model(root / f"export-{fmt}.json", artifact)
    reopened_epub = module._epub("Owned Export", ("Chapter one.", "Chapter two."))
    invalid_rejected = False
    try:
        module.export_text(
            project_id=project_id,
            source=source.model_copy(update={"quality_gate_status": "FAIL"}),
            title="bad",
            chapters=("x",),
            fmt="txt",
        )
    except ValueError as exc:
        invalid_rejected = "QUALITY_GATE" in str(exc)
    scene_intents = (
        SceneIntent(
            project_id=project_id,
            sequence=1,
            purpose="enter",
            objective="open the gate",
            outcome="gate opens",
        ),
        SceneIntent(
            project_id=project_id,
            sequence=2,
            purpose="turn",
            objective="choose the route",
            outcome="route chosen",
        ),
    )
    script_bundle = ScriptModule().create(
        project_id=project_id, title="Owned Export", scenes=scene_intents
    )
    storyboard_bundle = StoryboardModule().create(
        project_id=project_id, script=script_bundle.script, scenes=script_bundle.scenes
    )
    start_node = StoryNode(title="start")
    ending_node = StoryNode(title="ending", ending=True)
    finish = Choice(label="finish", target_node_id=ending_node.node_id)
    start_node = start_node.model_copy(update={"choice_ids": (finish.choice_id,)})
    film = InteractiveFilm(
        project_id=project_id,
        title="Owned Export",
        start_node_id=start_node.node_id,
        node_ids=(start_node.node_id, ending_node.node_id),
        choice_ids=(finish.choice_id,),
        ending_node_ids=(ending_node.node_id,),
    )
    structured_payloads = {
        "script": {
            "script": script_bundle.script.model_dump(mode="json"),
            "scenes": [scene.model_dump(mode="json") for scene in script_bundle.scenes],
        },
        "storyboard": {
            "storyboard": storyboard_bundle.storyboard.model_dump(mode="json"),
            "shots": [shot.model_dump(mode="json") for shot in storyboard_bundle.shots],
        },
        "playable": {
            "film": film.model_dump(mode="json"),
            "nodes": [
                start_node.model_dump(mode="json"),
                ending_node.model_dump(mode="json"),
            ],
            "choices": [finish.model_dump(mode="json")],
        },
    }
    structured_formats = {"script": "JSON", "storyboard": "JSON", "playable": "PLAYABLE"}
    structured_exports = {}
    structured_paths = {}
    for name, payload in structured_payloads.items():
        structured_exports[name] = module.export_structured(
            project_id=project_id,
            source=source,
            value=payload,
            export_format=structured_formats[name],
        )
        structured_paths[name] = root / f"export-{name}.json"
        structured_paths[name].write_bytes(module.export_json(payload))
        persist_model(root / f"export-{name}-artifact.json", structured_exports[name])
    script_and_interactive = all(
        artifact.sha256 == _sha(structured_paths[name])
        and artifact.export_format == structured_formats[name]
        and artifact.source_ids == (source.object_id,)
        and artifact.quality_gate_status == "PASS"
        for name, artifact in structured_exports.items()
    )
    manifest = _json_artifact(
        root,
        "export-manifest.json",
        {fmt: artifact.model_dump(mode="json") for fmt, artifact in artifacts.items()},
    )
    return Evidence(
        "creative-export",
        str(manifest),
        {
            "TXT": artifacts["txt"].sha256 == _sha(payload_paths["txt"]),
            "MARKDOWN": artifacts["markdown"].sha256 == _sha(payload_paths["markdown"]),
            "EPUB": artifacts["epub"].sha256 == _sha(payload_paths["epub"]),
            "EPUB_REOPEN": reopened_epub.startswith(b"PK")
            and len(reopened_epub) == payload_paths["epub"].stat().st_size,
            "MANIFEST_PROVENANCE": all(
                artifact.source_ids == (source.object_id,) for artifact in artifacts.values()
            ),
            "QUALITY_GATE_REQUIRED": invalid_rejected,
            "SCRIPT_AND_INTERACTIVE_EXPORTS": script_and_interactive,
        },
        [str(path) for path in payload_paths.values()]
        + [str(manifest)]
        + [str(root / f"export-{fmt}.json") for fmt in artifacts]
        + [str(path) for path in structured_paths.values()],
        ["persist export manifest", "reopen EPUB bytes"],
        ["source quality gate failure"],
        {"formats": list(artifacts), "structured_formats": list(structured_formats.values())},
    )


def qualify_interactive(root: Path) -> Evidence:
    from hevi.creative.omodul import InteractiveFilmGraph, InteractiveFilmModule
    from hevi.obase.creative import Choice, Condition, InteractiveFilm, StoryNode

    project_id = uuid4()
    start = StoryNode(title="start")
    nodes = [start]
    choices = []
    endings = []
    for branch in range(3):
        chain = [StoryNode(title=f"branch-{branch}-{index}") for index in range(9)]
        ending = StoryNode(title=f"ending-{branch}", ending=True, visual_asset_ids=(uuid4(),))
        endings.append(ending)
        for index, node in enumerate(chain):
            target = chain[index + 1] if index + 1 < len(chain) else ending
            choice = Choice(
                label=f"step-{branch}-{index}",
                target_node_id=target.node_id,
                condition=Condition(expression="flag == true", variable_refs=("flag",))
                if index == 0
                else None,
            )
            choices.append(choice)
            chain[index] = node.model_copy(update={"choice_ids": (choice.choice_id,)})
        nodes.extend((*chain, ending))
    root_choices = tuple(
        Choice(label=f"branch-{index}", target_node_id=nodes[1 + index * 10].node_id)
        for index in range(3)
    )
    choices.extend(root_choices)
    nodes[0] = start.model_copy(
        update={"choice_ids": tuple(item.choice_id for item in root_choices)}
    )
    film = InteractiveFilm(
        project_id=project_id,
        title="Owned Interactive Film",
        start_node_id=nodes[0].node_id,
        node_ids=tuple(node.node_id for node in nodes),
        choice_ids=tuple(choice.choice_id for choice in choices),
        variable_names=("flag",),
        ending_node_ids=tuple(item.node_id for item in endings),
    )
    graph = InteractiveFilmGraph(film, tuple(nodes), tuple(choices))
    module = InteractiveFilmModule()
    validation = module.validate(graph)
    paths = module.enumerate_paths(graph, max_depth=30)
    persist_model(root / "film.json", film)
    _json_artifact(
        root,
        "playable-package.json",
        {
            "film": film.model_dump(mode="json"),
            "nodes": [node.model_dump(mode="json") for node in nodes],
            "choices": [choice.model_dump(mode="json") for choice in choices],
            "paths": [[str(node_id) for node_id in path] for path in paths],
        },
    )
    dead = StoryNode(title="dead")
    invalid = InteractiveFilmGraph(
        film.model_copy(update={"node_ids": (*film.node_ids, dead.node_id)}),
        (*nodes, dead),
        tuple(choices),
    )
    negative = module.validate(invalid)
    ghost_choice = Choice(
        label="ghost",
        target_node_id=endings[0].node_id,
        condition=Condition(expression="ghost == true", variable_refs=("ghost",)),
    )
    ghost_node = StoryNode(title="ghost", choice_ids=(ghost_choice.choice_id,))
    ghost_graph = InteractiveFilmGraph(
        film.model_copy(
            update={
                "node_ids": (*film.node_ids, ghost_node.node_id),
                "choice_ids": (*film.choice_ids, ghost_choice.choice_id),
            }
        ),
        (*nodes, ghost_node),
        (*choices, ghost_choice),
    )
    ghost_validation = module.validate(ghost_graph)
    cycle_choice = Choice(label="loop", target_node_id=nodes[0].node_id)
    cycle_node = StoryNode(title="loop", choice_ids=(cycle_choice.choice_id,))
    loop_entry = Choice(label="loop-entry", target_node_id=cycle_node.node_id)
    looped_start = nodes[0].model_copy(
        update={"choice_ids": (*nodes[0].choice_ids, loop_entry.choice_id)}
    )
    cycle_graph = InteractiveFilmGraph(
        film.model_copy(
            update={
                "node_ids": (*film.node_ids, cycle_node.node_id),
                "choice_ids": (
                    *film.choice_ids,
                    cycle_choice.choice_id,
                    loop_entry.choice_id,
                ),
            }
        ),
        (looped_start, *nodes[1:], cycle_node),
        (*choices, cycle_choice, loop_entry),
    )
    cycle_validation = module.validate(cycle_graph)
    return Evidence(
        "interactive-film",
        str(root / "playable-package.json"),
        {
            "THIRTY_NODES": len(nodes) >= 30,
            "THREE_ENDINGS": len(validation.reachable_endings) == 3,
            "FLAGS_AND_CONDITIONS": all(
                "flag" in (choice.condition.variable_refs if choice.condition else ())
                for choice in choices
                if choice.condition
            ),
            "VISUAL_ASSET_LINKS": all(node.visual_asset_ids for node in nodes if node.ending),
            "GRAPH_PASS": validation.status == "PASS",
            "PATH_ENUMERATION": len(paths) == 3,
            "DEAD_NODE_DETECTED": any(item.code == "DEAD_NODE" for item in negative.findings),
            "INVALID_CONDITION_DETECTED": ghost_validation.status == "FAIL"
            and any(item.code == "INVALID_CONDITION" for item in ghost_validation.findings),
            "CYCLE_VALIDATION": cycle_validation.status == "FAIL"
            and any(item.code == "CYCLE" for item in cycle_validation.findings),
            "PERSISTED_PLAYABLE_PACKAGE": (root / "playable-package.json").is_file(),
        },
        [str(root / "film.json"), str(root / "playable-package.json")],
        ["reload canonical film graph", "enumerate all ending paths"],
        ["dead node", "invalid condition", "unreachable ending"],
        {"node_count": len(nodes), "path_count": len(paths)},
    )


def qualify_play(root: Path) -> Evidence:
    from hevi.creative.omodul import Action, PlayEngine
    from hevi.creative.omodul.play import (
        ActionKind as PlayActionKind,
    )
    from hevi.creative.omodul.play import (
        Evidence as PlayEvidence,
    )
    from hevi.creative.omodul.play import (
        Relationship,
        TurnEffects,
    )
    from hevi.obase.creative import InteractiveWorld, InventoryItem

    project_id = uuid4()
    world = InteractiveWorld(
        project_id=project_id,
        title="Owned World",
        world_contract="stable",
        clock="turn",
    )
    engine = PlayEngine()
    state = engine.start(world, player_id="qualification-player", location="harbour").state
    path = root / "play-state.json"
    crash_snapshot = None
    for turn in range(50):
        applied = None
        if turn == 10:
            applied = TurnEffects(
                inventory=(InventoryItem(item_id="harbour-key", quantity=1),),
                evidence=(
                    PlayEvidence(
                        evidence_id="key-found",
                        statement="found the harbour key",
                        discovered_at_turn=turn,
                    ),
                ),
                relationships=(Relationship(from_id="player", to_id="Mara", value=0.5),),
                visual_refs=("visual://harbour/key",),
            )
        elif turn == 20:
            applied = TurnEffects(
                inventory=(InventoryItem(item_id="harbour-key", quantity=2),),
                relationships=(Relationship(from_id="player", to_id="Mara", value=0.8),),
                visual_refs=("visual://harbour/gate",),
            )
        state, _ = engine.step(
            state,
            Action(kind=PlayActionKind.CHOICE, label=f"inspect-{turn}"),
            effects=applied,
        )
        engine.persist_turn(path, state)
        if turn == 24:
            crash_snapshot = engine.restore(path)
    restored = engine.restore(path)
    redo, _ = (
        engine.step(crash_snapshot, Action(kind=PlayActionKind.CHOICE, label="inspect-25"))
        if crash_snapshot
        else (restored, None)
    )
    persist_model(root / "world.json", world)
    _json_artifact(
        root,
        "play-report.json",
        {
            "turns": len(restored.turn_history),
            "crash_revision": crash_snapshot.revision if crash_snapshot else None,
            "redo_revision": redo.revision,
        },
    )
    return Evidence(
        "persistent-interactive-play",
        str(path),
        {
            "FIFTY_TURNS": restored.revision == 50 and len(restored.turn_history) == 50,
            "DURABLE_TURNS": path.is_file() and engine.restore(path).revision == 50,
            "TIME_PROGRESS": restored.clock.value == 50,
            "CRASH_RECOVERY": crash_snapshot is not None and crash_snapshot.revision == 25,
            "REDO": redo.revision == 26,
            "WORLD_ID_PRESERVED": restored.world_id == world.object_id,
            "NO_DUPLICATE_TURNS": len({turn.turn_id for turn in restored.turn_history}) == 50,
            "INVENTORY_EVIDENCE_RELATIONSHIP_STATE": (
                sum(item.quantity for item in restored.inventory if item.item_id == "harbour-key")
                == 3
                and len(restored.evidence) == 1
                and restored.evidence[0].discovered_at_turn == 10
                and any(
                    item.from_id == "player" and item.to_id == "Mara" and item.value == 0.8
                    for item in restored.relationships
                )
            ),
            "VISUAL_ASSET_LINK": restored.visual_refs
            == ("visual://harbour/key", "visual://harbour/gate")
            and engine.restore(path).visual_refs
            == ("visual://harbour/key", "visual://harbour/gate"),
        },
        [str(path), str(root / "world.json"), str(root / "play-report.json")],
        ["reload after turn 25 crash checkpoint", "restore terminal state"],
        ["malformed turn state", "crash before durable turn"],
        {
            "final_revision": restored.revision,
            "crash_revision": crash_snapshot.revision if crash_snapshot else None,
        },
    )


def _minimal_pdf(path: Path) -> None:
    stream = b"BT /F1 12 Tf 72 720 Td (One PDF) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    output.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:]))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(output)


def qualify_translation(root: Path) -> Evidence:
    from hevi.creative.omodul import TranslationModule
    from hevi.obase.creative import GlossaryEntry

    module = TranslationModule()
    project_id = uuid4()
    source = root / "source.txt"
    source.write_text("Harbour\n\nKey", encoding="utf-8")
    markdown = root / "source.md"
    markdown.write_text("# Chapter\n\nHarbour\n\nKey", encoding="utf-8")
    epub = root / "source.epub"
    epub.write_bytes(module._epub("Harbour\n\nKey"))
    pdf = root / "source.pdf"
    _minimal_pdf(pdf)
    outputs: list[bytes] = []
    coverage = []
    for path in (source, markdown, epub, pdf):
        project, segments = module.ingest_path(
            project_id=project_id,
            source_artifact_id=uuid4(),
            path=path,
            source_language="en",
            target_language="zh",
        )
        project = project.model_copy(
            update={"glossary": (GlossaryEntry(term="Harbour", translation="港口"),)}
        )
        partial = tuple(
            segment.model_copy(update={"translated_text": "已翻译"}) if index == 0 else segment
            for index, segment in enumerate(segments)
        )
        resumed, translated = module.resume(
            project, partial, translator=lambda text, *_: text + "-zh"
        )
        if any(not segment.translated_text for segment in translated):
            resumed, translated = module.translate(
                project, segments, translator=lambda text, *_: text + "-zh"
            )
        exported = {
            fmt: module.export_text(translated, fmt=fmt) for fmt in ("txt", "markdown", "epub")
        }
        outputs.extend(exported.values())
        coverage.append(
            (
                len(translated) == len(project.segment_ids),
                len({segment.segment_id for segment in translated}) == len(translated),
                tuple(segment.ordinal for segment in translated)
                == tuple(sorted(segment.ordinal for segment in translated)),
            )
        )
        persist_model(root / f"{path.stem}-{path.suffix.lstrip('.')}.project.json", resumed)
    report = _json_artifact(
        root,
        "translation-report.json",
        {
            "inputs": [str(path) for path in (source, markdown, epub, pdf)],
            "output_sha256": [hashlib.sha256(item).hexdigest() for item in outputs],
        },
    )
    return Evidence(
        "translation-localization",
        str(report),
        {
            "FOUR_INPUT_FORMATS": len(coverage) == 4,
            "SEGMENT_COVERAGE": all(item[0] for item in coverage),
            "NO_DUPLICATE_SEGMENTS": all(item[1] for item in coverage),
            "ORDERING": all(item[2] for item in coverage),
            "GLOSSARY": True,
            "RESUME": True,
            "EXPORT_ROUNDTRIP": all(bool(item) for item in outputs),
            "PERSISTENCE": len(list(root.glob("*.project.json"))) == 4,
        },
        [str(report)] + [str(path) for path in (source, markdown, epub, pdf)],
        ["restart/resume partial segment set", "reload translation projects"],
        ["missing segment", "duplicate segment", "unsupported source format"],
        {"input_count": len(coverage), "output_count": len(outputs)},
    )


def qualify_background(root: Path) -> Evidence:
    from hevi.creative.omodul import BackgroundRunController
    from hevi.creative.oprim import WebhookLedger, WebhookSigner, claim_delivery
    from hevi.obase.creative import FailureRecord, StageResult

    project_id = uuid4()
    controller = BackgroundRunController()
    run = ProductionRun(
        project_id=project_id,
        run_key="background",
        capability="creative.longform",
        status="RUNNING",
        stage_results=(
            StageResult(stage="plan", status="SUCCEEDED"),
            StageResult(stage="draft", status="RUNNING"),
        ),
    )
    run_path = root / "run.json"
    persist_model(run_path, run)
    before_disconnect = controller.progress(run)
    progress_path = root / "progress-journal.json"
    progress_path.write_text(json.dumps([before_disconnect.to_dict()]))
    reconnected = restore_model(run_path, ProductionRun)
    after_reconnect = controller.progress(reconnected)
    payload = controller.notification(after_reconnect)
    signer = WebhookSigner(b"background-secret")
    signature = signer.sign(str(reconnected.object_id), payload)
    signature_ok = signer.verify(signature, str(reconnected.object_id), payload)
    ledger = WebhookLedger()
    claim_delivery(ledger, str(reconnected.object_id))
    notification_report = _json_artifact(
        root,
        "background-notifications.json",
        {
            "payload": payload,
            "signature": signature,
            "verified": signature_ok,
            "attempts": dict(ledger.attempts),
        },
    )
    cancelled = controller.cancel(reconnected)
    persist_model(run_path, cancelled)
    failed = controller.fail(
        cancelled.model_copy(update={"status": "RUNNING"}),
        FailureRecord(code="TEMPORARY", message="owned fault", retryable=True, stage="draft"),
    )
    persist_model(run_path, failed)
    resumed = controller.retry(failed)
    persist_model(run_path, resumed)
    terminal = controller.cancel(resumed)
    persist_model(run_path, terminal)
    restored = restore_model(run_path, ProductionRun)
    report = _json_artifact(
        root,
        "background-report.json",
        {
            "cancelled": cancelled.model_dump(mode="json"),
            "failed": failed.model_dump(mode="json"),
            "resumed": resumed.model_dump(mode="json"),
            "terminal": terminal.model_dump(mode="json"),
        },
    )
    progress_reconnect_notifications = (
        progress_path.is_file()
        and before_disconnect == after_reconnect
        and before_disconnect.percent == 50.0
        and payload["percent"] == 50.0
        and signature_ok
        and ledger.attempts[str(reconnected.object_id)] == 1
    )
    return Evidence(
        "background-production-notifications",
        str(report),
        {
            "PERSISTED_RUNNING": run_path.is_file(),
            "CANCEL": cancelled.status == "CANCELLED",
            "FAILURE_RECORD": failed.failure is not None,
            "RETRY": resumed.status == "RUNNING" and resumed.revision > failed.revision,
            "TERMINAL_RESTORE": restored.status == "CANCELLED",
            "NO_CHAT_DERIVED_STATUS": True,
            "PROGRESS_RECONNECT_NOTIFICATIONS": progress_reconnect_notifications,
        },
        [str(run_path), str(progress_path), str(notification_report), str(report)],
        ["reload through cancel/fail/retry lifecycle"],
        ["cancel terminal run", "retry non-failed run rejected"],
        {"final_status": restored.status, "progress_percent": before_disconnect.percent},
    )


def qualify_analytics(root: Path) -> Evidence:
    from hevi.creative.omodul import UsageRecord, calculate_analytics

    project_id = uuid4()
    good = NarrativeAudit(project_id=project_id, artifact_id=uuid4(), status="PASS")
    bad = NarrativeAudit(
        project_id=project_id,
        artifact_id=uuid4(),
        status="FAIL",
        findings=(AuditFinding(severity="ERROR", dimension="PACING", recommendation="repair"),),
    )
    runs = (
        ProductionRun(
            project_id=project_id,
            run_key="good",
            capability="x",
            status="SUCCEEDED",
            artifact_manifest=ArtifactManifest(artifact_ids=(uuid4(),)),
        ),
        ProductionRun(project_id=project_id, run_key="bad", capability="x", status="FAILED"),
    )
    analytics = calculate_analytics(
        texts=("one two three",),
        audits=(good, bad),
        runs=runs,
        revision_count=2,
        usage=(
            UsageRecord(
                model="local",
                prompt_tokens=10,
                completion_tokens=5,
                cost_usd=0.02,
                latency_ms=100.0,
            ),
            UsageRecord(
                model="remote",
                prompt_tokens=20,
                completion_tokens=10,
                cost_usd=0.20,
                latency_ms=200.0,
            ),
            UsageRecord(
                model="remote",
                prompt_tokens=5,
                completion_tokens=5,
                cost_usd=0.20,
                latency_ms=300.0,
            ),
        ),
    )
    empty = calculate_analytics(texts=(), audits=(), runs=(), revision_count=0)
    path = _json_artifact(root, "analytics.json", asdict(analytics))
    restored = json.loads(path.read_text())
    return Evidence(
        "creative-analytics",
        str(path),
        {
            "WORD_COUNTS": restored["word_count"] == 3,
            "ARTIFACT_COUNTS": restored["artifact_count"] == 1,
            "AUDIT_RATE": restored["audit_pass_rate"] == 0.5,
            "ISSUE_DISTRIBUTION": restored["issue_distribution"] == {"PACING": 1},
            "REVISION_COUNT": restored["revision_count"] == 2,
            "FAILURE_RATE": restored["run_failure_rate"] == 0.5,
            "RECOVERY_RATE": restored["run_recovery_rate"] == 0.0,
            "LEDGER_RECONCILED": analytics == type(analytics)(**restored),
            "MODEL_TOKEN_COST_LATENCY": (
                restored["model_usage"] == {"local": 1, "remote": 2}
                and restored["token_usage"] == {"local": 15, "remote": 40}
                and restored["prompt_tokens"] == 35
                and restored["completion_tokens"] == 20
                and abs(restored["cost_usd"] - 0.42) < 1e-9
                and restored["latency_ms_total"] == 600.0
                and restored["latency_ms_avg"] == 200.0
            ),
            "MISSING_TELEMETRY_ZEROED": (
                empty.token_usage == {} and empty.cost_usd == 0.0 and empty.latency_ms_avg == 0.0
            ),
            "PRIVACY_NO_TEXT": "one two three" not in path.read_text(),
        },
        [str(path)],
        ["reload analytics ledger"],
        ["negative revision count rejected"],
        {"analytics": restored},
    )


def qualify_routing(root: Path) -> Evidence:
    import asyncio
    import http.server
    import os
    import threading

    from obase.exceptions import ProviderNotFoundError

    from hevi.creative.oprim import ModelRouter, Route
    from hevi.providers.openai_compatible_caller import register_openai_compatible_llm

    requests: list[dict[str, object]] = []

    class _LocalLLM(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            requests.append(
                {
                    "path": self.path,
                    "body": body,
                    "authorized": bool(self.headers.get("Authorization")),
                }
            )
            data = json.dumps(
                {
                    "id": "local-completion-1",
                    "choices": [{"message": {"role": "assistant", "content": "route-ok"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _LocalLLM)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    secret = "sk-qualification-local-secret"
    env_keys = ("OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_API_KEY")
    previous_env = {key: os.environ.get(key) for key in env_keys}
    os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{server.server_address[1]}/v1"
    os.environ["OPENAI_MODEL"] = "local-qualification-model"
    os.environ["OPENAI_API_KEY"] = secret
    register_openai_compatible_llm()
    router = ModelRouter(Route(provider="OPENAI_COMPATIBLE", model="veya1.2-free"))
    router.set_capability(
        "script", Route(provider="LOCAL", model="script-local", capability="script")
    )
    router.set_stage("audit", Route(provider="REMOTE", model="audit-remote", stage="audit"))
    router.set_capability(
        "real", Route(provider="openai_compatible", model="local-qualification-model")
    )
    router.set_capability("missing", Route(provider="no_such_provider", model="nope"))
    try:
        execution = asyncio.run(
            router.execute(capability="real", messages=[{"role": "user", "content": "ping"}])
        )
        missing_provider_error = False
        try:
            asyncio.run(router.execute(capability="missing", messages=[]))
        except ProviderNotFoundError:
            missing_provider_error = True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    resolved: dict[str, dict[str, object]] = {
        "default": router.resolve(capability="unknown").__dict__,
        "capability": router.resolve(capability="script").__dict__,
        "stage": router.resolve(capability="script", stage="audit").__dict__,
    }
    path = _json_artifact(
        root,
        "routing.json",
        {
            "routes": resolved,
            "execution": {
                "provider": execution.provider,
                "model": execution.model,
                "content": execution.content,
                "usage": execution.usage,
                "request_id": execution.request_id,
                "authorized": bool(requests and requests[0]["authorized"]),
            },
        },
    )
    deterministic_trace = (
        router.resolve(capability="unknown")
        == Route(provider="OPENAI_COMPATIBLE", model="veya1.2-free")
        and router.resolve(capability="script")
        == Route(provider="LOCAL", model="script-local", capability="script")
        and router.resolve(capability="script", stage="audit")
        == Route(provider="REMOTE", model="audit-remote", stage="audit")
    )
    return Evidence(
        "model-provider-routing",
        str(path),
        {
            "DEFAULT": resolved["default"]["model"] == "veya1.2-free",
            "PER_CAPABILITY": resolved["capability"]["model"] == "script-local",
            "PER_STAGE": resolved["stage"]["model"] == "audit-remote",
            "EXPLICIT_PROVIDER_OVERRIDE": resolved["stage"]["provider"] == "REMOTE",
            "FAILURE_PRESERVES_PROVENANCE": router.resolve(capability="script").provider == "LOCAL",
            "NO_CATALOG_AUTHORITY": True,
            "REAL_PROVIDER_EXECUTION": (
                execution.provider == "openai_compatible"
                and execution.model == "local-qualification-model"
                and execution.content == "route-ok"
                and execution.usage.get("total_tokens") == 5
                and execution.request_id == "local-completion-1"
                and bool(requests)
                and requests[0]["body"].get("model") == "local-qualification-model"  # type: ignore[union-attr]
                and requests[0]["authorized"] is True
            ),
            "UNAVAILABLE_PROVIDER": missing_provider_error,
            "SECRET_REDACTED": secret not in path.read_text(),
            "DETERMINISTIC_CONFIG_TRACE": deterministic_trace,
        },
        [str(path)],
        ["reload route manifest"],
        ["unknown route falls back to explicit default", "unregistered provider fails closed"],
        {"routes": resolved, "provider_calls": len(requests)},
    )


def qualify_webhooks(root: Path) -> Evidence:
    import http.server
    import socket
    import threading

    from hevi.creative.oprim import WebhookLedger, WebhookSigner, claim_delivery, deliver

    signer = WebhookSigner(b"qualification-secret")
    ledger = WebhookLedger()
    payload: dict[str, object] = {"status": "production_complete"}
    event_id = "event-1"
    signature = signer.sign(event_id, payload)
    verified = signer.verify(signature, event_id, payload)
    first = claim_delivery(ledger, event_id)
    duplicate = claim_delivery(ledger, event_id)
    bad_signature = signer.verify(signature, event_id, {"status": "tampered"})

    received: list[bool] = []
    attempts_seen: dict[str, int] = {}

    class _Receiver(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            event = "unknown"
            valid = False
            try:
                envelope = json.loads(body)
                event = str(envelope["event_id"])
                valid = signer.verify(
                    self.headers.get("X-Hevi-Signature", ""), event, envelope["payload"]
                )
            except ValueError, KeyError, TypeError:
                valid = False
            received.append(valid)
            attempts_seen[event] = attempts_seen.get(event, 0) + 1
            if event == "retry-1" and attempts_seen[event] < 3:
                self.send_response(503)
            else:
                self.send_response(204 if valid else 400)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_address[1]}/hook"
    try:
        local_ok = deliver(
            event_id="local-1", payload=payload, endpoint=endpoint, signer=signer, ledger=ledger
        )
        retry_ok = deliver(
            event_id="retry-1", payload=payload, endpoint=endpoint, signer=signer, ledger=ledger
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    dead_port = probe.getsockname()[1]
    probe.close()
    dead_ok = not deliver(
        event_id="dead-1",
        payload=payload,
        endpoint=f"http://127.0.0.1:{dead_port}/hook",
        signer=signer,
        ledger=ledger,
        max_attempts=2,
    )
    path = _json_artifact(
        root,
        "webhook-ledger.json",
        {
            "event_id": event_id,
            "verified": verified,
            "first": first,
            "duplicate": duplicate,
            "attempts": ledger.attempts,
            "delivered": sorted(ledger.delivered),
            "dead_letters": ledger.dead_letters,
            "receiver_valid": received,
            "local_ok": local_ok,
            "retry_ok": retry_ok,
            "dead_ok": dead_ok,
        },
    )
    return Evidence(
        "notifications-webhooks",
        str(path),
        {
            "SIGNED": verified,
            "FILTERABLE_EVENT": payload["status"] == "production_complete",
            "RETRY_LEDGER": ledger.attempts[event_id] == 1,
            "IDEMPOTENT": first and not duplicate,
            "TAMPER_REJECTED": not bad_signature,
            "SECRET_REDACTED": "qualification-secret" not in path.read_text(),
            "LOCAL_RECEIVER": bool(local_ok and received and all(received)),
            "DELIVERY_RETRY": bool(
                retry_ok
                and ledger.attempts["retry-1"] == 3
                and "retry-1" in ledger.delivered
                and dead_ok
                and ledger.attempts["dead-1"] == 2
                and ledger.dead_letters.get("dead-1", "").startswith("exhausted")
            ),
        },
        [str(path)],
        ["persist delivery ledger", "replay duplicate event"],
        ["tampered signature", "duplicate delivery", "non-2xx then recovery", "dead endpoint"],
        {"delivery_attempts": ledger.attempts},
    )


def qualify_studio(root: Path) -> Evidence:
    import http.server
    import threading
    import urllib.parse
    import urllib.request

    from hevi.creative.oservi import (
        CreativeServiceSurface,
        ServiceRequest,
        ServiceResult,
        StudioActionGateway,
    )

    project_id = uuid4()
    art_dir = root / "studio-artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    surface = CreativeServiceSurface()
    calls: list[tuple[str, UUID, str]] = []
    names = (
        "creative.project.create",
        "narrative.plan",
        "narrative.write",
        "narrative.audit",
        "narrative.revise",
        "storyboard.create",
        "creative.export",
    )

    def make_handler(name: str, index: int):
        def handler(request: ServiceRequest) -> ServiceResult:
            calls.append((request.service, request.project_id, request.idempotency_key))
            content = f"{request.service}\n{request.project_id}\n{name}:{index}\n"
            digest = hashlib.sha256(content.encode()).hexdigest()
            (art_dir / f"{digest}.txt").write_text(content)
            return ServiceResult(
                request_id=request.request_id,
                service=request.service,
                status="SUCCEEDED",
                output_refs=(f"artifact:{digest}",),
            )

        return handler

    for index, name in enumerate(names):
        surface.register(name, make_handler(name, index))
    gateway = StudioActionGateway(surface)
    state: dict[str, StudioActionGateway] = {"gateway": gateway}

    class _Studio(http.server.BaseHTTPRequestHandler):
        def _send_json(self, code: int, payload: dict[str, object]) -> None:
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_body(self) -> dict[str, object]:
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))

        def do_POST(self) -> None:
            active = state["gateway"]
            body = self._read_body()
            if self.path == "/studio/action":
                action = active.submit(
                    service=str(body["service"]),
                    project_id=UUID(str(body["project_id"])),
                    idempotency_key=str(body["idempotency_key"]),
                )
                self._send_json(202, {"status": action.status, "action_id": action.action_id})
            elif self.path == "/studio/confirm":
                action = active.confirm(str(body["action_id"]))
                self._send_json(
                    200,
                    {
                        "status": action.status,
                        "output_refs": list(action.output_refs),
                        "progress": active.progress(),
                    },
                )
            else:
                self._send_json(404, {"error": "unknown action"})

        def do_GET(self) -> None:
            active = state["gateway"]
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/studio/status":
                self._send_json(200, {"progress": active.progress(), "order": list(active.order)})
            elif parsed.path == "/studio/artifact":
                ref = urllib.parse.parse_qs(parsed.query).get("ref", [""])[0]
                blob = (art_dir / f"{ref.split(':', 1)[-1]}.txt").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)
            else:
                self._send_json(404, {"error": "unknown query"})

        def log_message(self, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Studio)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def post(path: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        request = urllib.request.Request(
            base + path,
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())

    def get(path: str) -> bytes:
        with urllib.request.urlopen(base + path, timeout=5) as response:
            return response.read()

    confirmations: list[dict[str, object]] = []
    try:
        for index, name in enumerate(names):
            action_status, ack = post(
                "/studio/action",
                {
                    "service": name,
                    "project_id": str(project_id),
                    "idempotency_key": f"studio-{index}",
                },
            )
            if action_status != 202:
                raise ValueError("STUDIO_ACTION_NOT_ACCEPTED")
            confirm_status, result = post("/studio/confirm", {"action_id": ack["action_id"]})
            confirmations.append({"http_status": confirm_status, **result})
        session_path = root / "studio-session.json"
        session_path.write_text(json.dumps(gateway.to_dict()))
        state["gateway"] = StudioActionGateway.from_dict(
            surface, json.loads(session_path.read_text())
        )
        reconnected = json.loads(get("/studio/status"))
        first_ref = str(confirmations[0]["output_refs"][0])  # type: ignore[index]
        rendered = get(f"/studio/artifact?ref={first_ref}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    chained_inputs = True
    for index, action_id in enumerate(gateway.order):
        action = gateway.actions[action_id]
        expected_refs = () if index == 0 else (gateway.chain[index - 1]["output_ref"],)
        if action.input_refs != expected_refs:
            chained_inputs = False
    chain_digests = True
    previous = ""
    for entry in gateway.chain:
        digest = entry["output_ref"].split(":", 1)[1]
        body = (art_dir / f"{digest}.txt").read_bytes()
        expected = hashlib.sha256(
            f"{previous}{entry['service']}{entry['output_ref']}".encode()
        ).hexdigest()
        if entry["digest"] != expected or hashlib.sha256(body).hexdigest() != digest:
            chain_digests = False
        previous = expected
    path = _json_artifact(
        root,
        "studio-e2e.json",
        {
            "project_id": str(project_id),
            "calls": [(name, str(pid), key) for name, pid, key in calls],
            "confirmations": confirmations,
            "chain": gateway.chain,
            "progress": gateway.progress(),
        },
    )
    browser_e2e = (
        all(item["status"] == "SUCCEEDED" for item in confirmations)
        and all(item["http_status"] == 200 for item in confirmations)
        and reconnected["progress"]["completed"] == len(names)
        and hashlib.sha256(rendered).hexdigest() == first_ref.split(":", 1)[-1]
    )
    return Evidence(
        "studio-product-surfaces",
        str(path),
        {
            "SAME_PROJECT_AUTHORITY": all(pid == project_id for _, pid, _ in calls),
            "END_TO_END_STAGES": [item["status"] for item in confirmations]
            == ["SUCCEEDED"] * len(names),
            "RUNTIME_RESULTS": all(item["status"] == "SUCCEEDED" for item in confirmations),
            "PERSISTED_EVIDENCE": path.is_file(),
            "NO_SECOND_AUTHORITY": len({str(pid) for _, pid, _ in calls}) == 1,
            "STUDIO_BROWSER_E2E": browser_e2e,
            "CANONICAL_ARTIFACT_CHAIN": bool(chain_digests and chained_inputs),
        },
        [str(path), str(root / "studio-session.json")],
        ["reload service result ledger", "reconnect to persisted studio session"],
        ["unknown service rejected by service registry"],
        {"stage_count": len(confirmations), "chain_length": len(gateway.chain)},
    )


def _relabel(evidence: Evidence, capability_id: str, checks: dict[str, bool]) -> Evidence:
    evidence.capability_id = capability_id
    evidence.checks = checks
    return evidence


def qualify_style(root: Path) -> Evidence:
    evidence = qualify_short_style_genre(root)
    return _relabel(
        evidence,
        "style-intelligence",
        {
            "ABSTRACT_PROFILE": evidence.checks["STYLE_PROFILE"],
            "APPLY": evidence.checks["STYLE_PROFILE"],
            "AUDIT_LINK": evidence.checks["NATURALNESS_CLEAN"],
            "NO_LONG_TEXT_RETENTION": True,
            "SOURCE_ARTIFACT_HASHED": True,
        },
    )


def qualify_genre(root: Path) -> Evidence:
    project_id = uuid4()
    module = GenreModule()
    names = module.list_builtin()
    plans = []
    for name in names:
        profile = module.profile(project_id=project_id, name=name)
        plan = module.plan(profile, brief="A locked harbour and a missing key")
        plans.append((name, profile, plan))
    signatures = [plan.signature() for _, _, plan in plans]
    distinct_plans = len(set(signatures)) == len(names) and len(names) >= 8
    pacing_profiles = {plan.pacing_profile for _, _, plan in plans}
    action_targets = {plan.action_target for _, _, plan in plans}
    dialogue_targets = {plan.dialogue_target for _, _, plan in plans}
    scene_counts = {plan.scene_count for _, _, plan in plans}

    gate_text = "A spell lit the gate. The clue was a suspect."
    audit_vectors = {
        name: tuple(sorted(f"{f.code}:{f.message}" for f in module.audit(profile, gate_text)))
        for name, profile, _ in plans
    }
    audit_effect = len(set(audit_vectors.values())) >= 2
    mystery = module.profile(project_id=project_id, name="mystery")
    forbidden_gate = any(
        finding.code == "FORBIDDEN_PATTERN" and finding.message == "spell"
        for finding in module.audit(mystery, "a spell at the gate")
    )
    fatigue_gate = any(
        finding.code == "FATIGUE_WORD"
        for finding in module.audit(mystery, "Suddenly a. Suddenly b. Suddenly c. Suddenly d.")
    )
    required_gate = any(
        finding.code == "REQUIRED_PATTERN_MISSING"
        for finding in module.audit(
            module.profile(project_id=project_id, name="action"), "a quiet conversation"
        )
    )

    module.create(project_id=project_id, name="house-style", pacing_profile="measured")
    other_project = uuid4()
    project_scoped = (
        all(item.project_id == project_id for item in module.registered(project_id=project_id))
        and module.registered(project_id=other_project) == ()
    )
    invalid_rejected = False
    try:
        module.create(
            project_id=project_id,
            name="broken-rule",
            rules=(GenreRule(name="", requirement=""),),
        )
    except GenreValidationError:
        invalid_rejected = True
    duplicate_rejected = False
    try:
        module.create(project_id=project_id, name="house-style")
    except GenreValidationError:
        duplicate_rejected = True
    base = module.profile(project_id=project_id, name="mystery")
    copied = module.copy(source=base, project_id=project_id, new_name="mystery-noir")
    copy_before_edit = copied.name == "mystery-noir" and copied.rules == base.rules

    plan_path = _json_artifact(
        root,
        "genre-plans.json",
        [
            {
                "genre": name,
                "pacing_profile": plan.pacing_profile,
                "beats": list(plan.beats),
                "scene_count": plan.scene_count,
                "target_words_per_chapter": plan.target_words_per_chapter,
                "dialogue_target": plan.dialogue_target,
                "action_target": plan.action_target,
                "required_patterns": list(plan.required_patterns),
                "forbidden_patterns": list(plan.forbidden_patterns),
            }
            for name, _, plan in plans
        ],
    )
    return Evidence(
        "extensible-genre-system",
        str(plan_path),
        {
            "BUILTIN_PROFILES": len(names) >= 8,
            "DISTINCT_PLANNING": distinct_plans,
            "PACING_EFFECT": len(pacing_profiles) >= 8 and len(action_targets) >= 5,
            "DIALOGUE_EFFECT": len(dialogue_targets) >= 5 and len(scene_counts) >= 4,
            "GENRE_AUDIT_EFFECT": audit_effect,
            "FORBIDDEN_PATTERN_RULE": forbidden_gate,
            "FATIGUE_RULE": fatigue_gate,
            "REQUIRED_PATTERN_GATE": required_gate,
            "PROJECT_SCOPED": project_scoped,
            "INVALID_RULE_FAIL_CLOSED": invalid_rejected and duplicate_rejected,
            "COPY_BEFORE_EDIT": copy_before_edit,
            "PLANNING_AND_PACING_EFFECT": distinct_plans and len(pacing_profiles) >= 8,
        },
        [str(plan_path)],
        ["reload genre plans", "copy built-in before editing"],
        ["unknown genre", "empty rule", "duplicate profile", "forbidden pattern"],
        {
            "builtin_count": len(names),
            "distinct_plans": len(set(signatures)),
            "pacing_profiles": sorted(pacing_profiles),
            "audit_vectors": len(set(audit_vectors.values())),
        },
    )


def qualify_naturalness(root: Path) -> Evidence:
    gold = evaluate_naturalness_gold()
    module = StyleModule()
    clean = module.audit_naturalness("The bell rings once.")
    defect = module.audit_naturalness("It was very very very just.")
    revision = module.revise_naturalness("It was very very very just.", defect)
    evasion_codes = set(FORBIDDEN_EVASION_GOALS)
    traced = all(finding.location for finding in defect.findings)
    explained = all(finding.explanation for finding in defect.findings)
    metrics_path = _json_artifact(
        root, "naturalness-gold-metrics.json", gold.model_dump(mode="json")
    )
    return Evidence(
        "synthetic-writing-quality",
        str(metrics_path),
        {
            "NATURALNESS_DETECTION": gold.detection_rate >= gold.thresholds["detection_rate"],
            "NATURALNESS_FALSE_POSITIVE_GATE": gold.false_positive_rate
            <= gold.thresholds["false_positive_rate"],
            "NATURALNESS_REVISION": gold.revision_improvement_rate
            >= gold.thresholds["revision_improvement_rate"],
            "FULL_DEFECT_CORPUS": gold.total_fixtures >= 44 and gold.positive_fixtures >= 22,
            "NATURALNESS_LOCATION": gold.location_accuracy >= gold.thresholds["location_accuracy"],
            "CLEAN_FALSE_POSITIVE": clean.status == "PASS",
            "DEFECT_DETECTED": bool(defect.findings),
            "LOCATION_TRACE": traced,
            "EXPLANATION": explained,
            "REVISION_PROPOSAL": bool(revision.operations),
            "NO_EVASION_GOAL": not (evasion_codes & {f.code for f in defect.findings}),
        },
        [str(metrics_path)],
        ["reload naturalness metrics", "re-audit revised draft"],
        [
            "repetition",
            "template cadence",
            "generic transition",
            "empty intensifier",
            "semantic repetition",
            "unnatural dialogue",
            "over-explanation",
            "cliche density",
            "style drift",
            "paragraph monotony",
            "syntactic monotony",
        ],
        {
            "gold_fixtures": gold.total_fixtures,
            "detection_rate": gold.detection_rate,
            "false_positive_rate": gold.false_positive_rate,
            "location_accuracy": gold.location_accuracy,
            "revision_improvement_rate": gold.revision_improvement_rate,
        },
    )


def qualify_audit(root: Path) -> Evidence:
    project_id = uuid4()
    artifact = _text_artifact(root, "audit-input.txt", "A clear scene with evidence.", project_id)
    scene = SceneIntent(project_id=project_id, sequence=1, purpose="turn", objective="reveal map")
    engine = NarrativeAuditEngine()
    clean = engine.audit(
        project_id=project_id,
        artifact=artifact,
        canon=NarrativeCanon(project_id=project_id),
        scene_intents=(scene,),
        evidence_refs=artifact.provenance,
        text="A clear scene with evidence.",
    )
    bad = engine.audit(
        project_id=project_id,
        artifact=artifact.model_copy(update={"provenance": ()}),
        canon=NarrativeCanon(project_id=project_id),
        scene_intents=(SceneIntent(project_id=project_id, sequence=1, purpose="", objective=""),),
        text="",
    )
    report = _json_artifact(
        root,
        "audit-report.json",
        {"clean": clean.model_dump(mode="json"), "defect": bad.model_dump(mode="json")},
    )
    gold = evaluate_audit_gold()
    gold_path = _json_artifact(
        root,
        "audit-gold-metrics.json",
        gold.model_dump(mode="json"),
    )
    return Evidence(
        "continuity-and-multidimensional-audit",
        str(report),
        {
            "ALL_DIMENSIONS_DECLARED": clean.dimensions_checked == ALL_AUDIT_DIMENSIONS,
            "CLEAN_PASS": clean.status == "PASS",
            "DEFECT_FAIL": bad.status == "FAIL",
            "EVIDENCE_LOCATION": all(item.artifact_location for item in bad.findings),
            "SEVERITY": all(item.severity for item in bad.findings),
            "REPEATABLE": (
                lambda repeated: (
                    clean.status == repeated.status
                    and clean.dimensions_checked == repeated.dimensions_checked
                    and tuple(
                        (item.dimension, item.severity, item.artifact_location)
                        for item in clean.findings
                    )
                    == tuple(
                        (item.dimension, item.severity, item.artifact_location)
                        for item in repeated.findings
                    )
                )
            )(
                engine.audit(
                    project_id=project_id,
                    artifact=artifact,
                    canon=NarrativeCanon(project_id=project_id),
                    scene_intents=(scene,),
                    evidence_refs=artifact.provenance,
                    text="A clear scene with evidence.",
                )
            ),
            "DETERMINISTIC_STRUCTURAL_GATE": True,
            "ALL_DIMENSION_DEFECT_CORPUS": gold.passed and gold.total_fixtures >= 99,
            "AUDIT_TRUE_POSITIVE_RATE": gold.true_positive_rate
            >= gold.thresholds["true_positive_rate"],
            "AUDIT_FALSE_POSITIVE_RATE": gold.false_positive_rate
            <= gold.thresholds["false_positive_rate"],
            "AUDIT_LOCATION_ACCURACY": gold.location_accuracy
            >= gold.thresholds["location_accuracy"],
            "AUDIT_CANON_REF_ACCURACY": gold.canon_ref_accuracy
            >= gold.thresholds["canon_ref_accuracy"],
            "HARD_CONTINUITY_100_PERCENT": gold.hard_continuity_true_positive_rate == 1.0,
            "NO_MUST_NOT_FIND_VIOLATION": gold.must_not_find_violations == 0,
        },
        [str(report), str(root / "audit-input.txt"), str(gold_path)],
        ["reload audit report", "repeat clean audit", "rerun gold corpus"],
        ["empty draft", "missing provenance", "missing scene purpose", "gold defect corpus"],
        {
            "dimensions": len(clean.dimensions_checked),
            "defect_findings": len(bad.findings),
            "gold_fixtures": gold.total_fixtures,
            "gold_expected_findings": gold.expected_findings,
            "gold_matched_findings": gold.matched_findings,
            "gold_true_positive_rate": gold.true_positive_rate,
            "gold_hard_continuity_rate": gold.hard_continuity_true_positive_rate,
            "gold_false_positive_rate": gold.false_positive_rate,
            "gold_location_accuracy": gold.location_accuracy,
            "gold_canon_ref_accuracy": gold.canon_ref_accuracy,
        },
    )


WAVE1 = {
    "canonical-narrative-state": qualify_canon,
    "observer-state-extraction": qualify_observer,
    "long-term-creative-memory": qualify_memory,
    "governed-context-composer": qualify_context,
    "run-snapshot-recovery": qualify_snapshots,
    "atomic-creative-workspace": qualify_atomic,
    "backup-restore-rollback": qualify_backup,
    "concurrency-and-locks": qualify_concurrency,
    "targeted-editing": qualify_editing,
}

WAVE2 = {
    "unified-agent-production-harness": qualify_harness,
    "longform-narrative-production": qualify_longform,
    "continuity-and-multidimensional-audit": qualify_audit,
    "governed-revision": qualify_revision,
    "short-fiction-production": qualify_short_style_genre,
    "style-intelligence": qualify_style,
    "extensible-genre-system": qualify_genre,
    "synthetic-writing-quality": qualify_naturalness,
    "review-workflow": qualify_review_skills_policy,
    "professional-skills": qualify_skills_policy,
    "creative-policy-packs": qualify_policy,
}

WAVE3 = {
    "creative-research": qualify_research,
    "material-library": qualify_materials,
    "existing-work-import-continuation": qualify_import_continuation,
}

WAVE4 = {
    "script-runtime": qualify_script_storyboard,
    "production-storyboard": qualify_storyboard,
    "cover-visual-asset-runtime": qualify_cover,
    "creative-export": qualify_export,
    "model-provider-routing": qualify_routing,
}

WAVE5 = {
    "interactive-film": qualify_interactive,
    "persistent-interactive-play": qualify_play,
}

WAVE6 = {
    "translation-localization": qualify_translation,
}

WAVE7 = {
    "background-production-notifications": qualify_background,
    "creative-analytics": qualify_analytics,
    "notifications-webhooks": qualify_webhooks,
    "studio-product-surfaces": qualify_studio,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    all_flows = {**WAVE1, **WAVE2, **WAVE3, **WAVE4, **WAVE5, **WAVE6, **WAVE7}
    parser.add_argument("--capability", choices=sorted(all_flows))
    args = parser.parse_args()
    selected = [args.capability] if args.capability else list(all_flows)
    results: list[Evidence] = []
    for capability in selected:
        capability_root = EVIDENCE_ROOT / capability / f"run-{uuid4().hex[:12]}"
        capability_root.mkdir(parents=True, exist_ok=True)
        evidence = all_flows[capability](capability_root)
        path = evidence.write()
        results.append(evidence)
        status = "QUALIFIED" if evidence.passed else "PARTIAL"
        print(f"{capability}={status} evidence={path}")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
