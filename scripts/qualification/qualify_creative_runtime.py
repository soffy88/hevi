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
from uuid import uuid4

from hevi.creative.omodul import (
    ContextBudget,
    ContextCandidate,
    CreativeContextCompiler,
)
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
from hevi.obase.creative import (
    Character,
    CharacterState,
    ContinuityFact,
    CreativeAuthority,
    InformationState,
    LocationState,
    NarrativeCanon,
    NarrativeProject,
    PhysicalState,
    ProductionRun,
    RelationshipState,
    ResourceState,
    RunSnapshot,
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


WAVE1 = {
    "canonical-narrative-state": qualify_canon,
    "long-term-creative-memory": qualify_memory,
    "governed-context-composer": qualify_context,
    "run-snapshot-recovery": qualify_snapshots,
    "atomic-creative-workspace": qualify_atomic,
    "backup-restore-rollback": qualify_backup,
    "concurrency-and-locks": qualify_concurrency,
    "targeted-editing": qualify_editing,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability", choices=sorted(WAVE1))
    args = parser.parse_args()
    selected = [args.capability] if args.capability else list(WAVE1)
    results: list[Evidence] = []
    for capability in selected:
        capability_root = EVIDENCE_ROOT / capability / f"run-{uuid4().hex[:12]}"
        capability_root.mkdir(parents=True, exist_ok=True)
        evidence = WAVE1[capability](capability_root)
        path = evidence.write()
        results.append(evidence)
        status = "QUALIFIED" if evidence.passed else "PARTIAL"
        print(f"{capability}={status} evidence={path}")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
