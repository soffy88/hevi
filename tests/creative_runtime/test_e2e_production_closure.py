"""W15 end-to-end production closure proofs (E2E-1..E2E-4).

Each test composes real authorities across waves with real persistence
(SQLite / JSON-roundtripped repos / loopback HTTP / real media files).
No internal function is mocked; fakes exist only where production has
ports (repository interface, provider HTTP).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest


class _DictRepository:
    def __init__(self) -> None:
        self.pool = object()
        self._rows: dict[str, dict[str, Any]] = {}

    def seed(self, task: dict[str, Any]) -> uuid.UUID:
        task_id = uuid.uuid4()
        self._rows[str(task_id)] = json.loads(json.dumps({**task, "id": str(task_id)}))
        return task_id

    async def get_task(self, task_id: uuid.UUID) -> dict[str, Any] | None:
        row = self._rows.get(str(task_id))
        return json.loads(json.dumps(row)) if row is not None else None

    async def update_task(self, task_id: uuid.UUID, data: dict[str, Any]) -> bool:
        row = self._rows.get(str(task_id))
        if row is None:
            return False
        self._rows[str(task_id)] = json.loads(json.dumps({**row, **data}))
        return True


def _ffmpeg_clip(path: Any, duration_s: int = 1) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg required")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration_s}:size=128x128:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(path),
            "-y",
        ],
        check=True,
    )


@pytest.mark.asyncio
async def test_e2e1_appearance_edit_to_export_same_selection(tmp_path) -> None:
    """E2E-1: appearance edit -> stale -> plan repair -> regen -> presentation -> export."""

    from hevi.creative.layer4.character_authority import (
        AppearanceKind,
        CharacterAuthority,
        VoiceIdentity,
    )
    from hevi.creative.layer4.currency import ArtifactBasis, ArtifactCurrency, evaluate_currency
    from hevi.creative.layer4.editable_delivery import assert_snapshot_parity, build_timeline
    from hevi.creative.layer4.plan_projection import TargetFact, TargetStatus, project_plan
    from hevi.creative.layer4.presentation import (
        AudioMode,
        CandidateMedia,
        PresentationSelector,
        for_download,
    )

    authority = CharacterAuthority()
    authority.register(
        character_id="ch-anna", canonical_name="Anna", voice=VoiceIdentity(voice_id="v-anna")
    )
    authority.add_appearance("ch-anna", appearance_id="armor", kind=AppearanceKind.OUTFIT)
    edges = (("board-1", "appearance:armor"), ("clip-1", "appearance:armor"))
    assert authority.appearance_change_impact("ch-anna", "armor", edges) == ("board-1", "clip-1")

    stale = evaluate_currency(
        ArtifactBasis(artifact_id="clip-1", role="final_video", dependency_revision="graph@7"),
        {"graph": "8"},
    )
    assert stale.currency is ArtifactCurrency.STALE and stale.usable is True
    plan = project_plan((TargetFact(target_id="clip-1", currency=stale.currency),))
    assert plan[0].status is TargetStatus.STALE
    assert plan[0].repair_actions  # repair proposed, nothing auto re-billed

    _ffmpeg_clip(tmp_path / "regen.mp4")
    current = evaluate_currency(
        ArtifactBasis(
            artifact_id="clip-1",
            role="final_video",
            dependency_revision="graph@8",
        ),
        {"graph": "8"},
    )
    assert current.currency is ArtifactCurrency.CURRENT

    snapshot = PresentationSelector().select(
        project_id="p1",
        production_run_id="r1",
        revision_id="rev-10",
        scope_id="s1",
        video_candidates=(
            CandidateMedia(
                artifact_id="clip-1",
                version=2,
                path=str(tmp_path / "regen.mp4"),
                kind="video",
                dependency_revision="graph@8",
            ),
        ),
        actual_durations_ms={"clip-1": 1000},
        audio_mode=AudioMode.SILENT,
        dependency_revisions={"graph": "8"},
    )
    timeline = build_timeline(snapshot)
    assert assert_snapshot_parity(timeline, snapshot) is timeline
    assert for_download(snapshot)["video_artifact_id"] == "clip-1"


@pytest.mark.asyncio
async def test_e2e2_crash_restart_download_resume_no_resubmit(tmp_path) -> None:
    """E2E-2: submit -> remote success -> crash -> restart -> download resume."""

    from hevi.creative.layer4.currency import ArtifactBasis, ArtifactCurrency, evaluate_currency
    from hevi.tasks.durable_execution import load_record, submission_count
    from hevi.tasks.task_service import TaskService

    repo = _DictRepository()
    service = TaskService(repo)  # type: ignore[arg-type]
    task_id = repo.seed({"status": "running", "config_json": {}})
    intent = {
        "provider": "maas_lock",
        "endpoint": "https://provider.example/v1/jobs",
        "model": "happyhorse-1.1",
        "request": {"prompt": "雨夜街景", "duration_s": 5},
        "production_revision": "rev-9",
        "target_artifact_id": "clip-1",
        "idempotency_key": "idem-e2e2",
    }
    assert (await service.begin_durable_execution(task_id, **intent))["action"] == "submit"
    await service.record_durable_event(task_id, {"kind": "submitted", "provider_job_id": "job-1"})
    await service.record_durable_event(
        task_id, {"kind": "remote_success", "remote_artifact_url": "https://cdn.example/c.mp4"}
    )
    await service.record_durable_event(
        task_id, {"kind": "download_progress", "received_bytes": 512, "etag": "e1"}
    )
    # process crash: brand-new service instance over the same repository
    restarted = TaskService(repo)  # type: ignore[arg-type]
    assert (await restarted.recover_durable_execution(task_id))["action"] == "resume_download"
    assert (await restarted.begin_durable_execution(task_id, **intent))[
        "action"
    ] == "resume_download"
    await restarted.record_durable_event(
        task_id,
        {
            "kind": "download_complete",
            "local_artifact_path": "/v/c.mp4",
            "checksum": "cc",
            "actual_cost": 0.45,
        },
    )
    task = await repo.get_task(task_id)
    assert task is not None
    record = load_record(task["config_json"])
    assert record is not None and record.done is True
    assert submission_count(task["config_json"], record.request_fingerprint) == 1
    assert record.billing_state.value == "billed"
    currency = evaluate_currency(
        ArtifactBasis(artifact_id="clip-1", role="final_video", dependency_revision="rev-9"),
        {"revision": "rev-9"},
    )
    assert currency.currency is ArtifactCurrency.CURRENT


class _E2E3Handler(BaseHTTPRequestHandler):
    submits = 0

    def log_message(self, *args: Any) -> None:
        pass

    def _json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        type(self).submits += 1
        self._json(
            {
                "job": {
                    "id": "job-e2e3",
                    "status": "succeeded",
                    "video_url": f"http://127.0.0.1:{self.server.server_port}/f.mp4",
                }
            }
        )

    def do_GET(self) -> None:
        if self.path == "/f.mp4":
            data = bytes(type(self).artifact_bytes)
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)


def test_e2e3_endpoint_to_presentation_with_usage(tmp_path) -> None:
    """E2E-3: definition test/enable -> generation -> usage -> manifest -> presentation."""

    from hevi.creative.layer4.endpoint_execution import execute_endpoint
    from hevi.creative.layer4.endpoint_lifecycle import (
        AuthMode,
        CapabilityDeclaration,
        DeclarativeEndpointDefinition,
        SyncMode,
        enable,
        mark_validated,
        record_trial,
    )
    from hevi.creative.layer4.usage_ledger import aggregate

    _ffmpeg_clip(tmp_path / "srv.mp4")
    _E2E3Handler.artifact_bytes = (tmp_path / "srv.mp4").read_bytes()
    _E2E3Handler.submits = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _E2E3Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        definition = DeclarativeEndpointDefinition(
            name="e2e3-video",
            provider_family="e2e3",
            base_url=f"{base}/v1/generate",
            auth_mode=AuthMode.NONE,
            request_schema={"properties": {"prompt": {}}},
            request_template='{"prompt": "{{prompt}}"}',
            sync_mode=SyncMode.SYNC,
            artifact_url_path="job.video_url",
            capability=CapabilityDeclaration(media_type="video", durations_s=(5,), async_job=False),
        )
        tested = record_trial(mark_validated(definition), outcome="success")
        enabled = enable(tested)
        report = execute_endpoint(
            enabled,
            {
                "prompt": "x",
                "duration_s": 5,
                "production_revision": "rev-1",
                "target_artifact_id": "e2e3-clip",
                "production_run_id": "r-e2e3",
            },
            {},
            tmp_path / "out",
            project_ref="e2e3",
        )
        assert report.submitted is True
        assert _E2E3Handler.submits == 1
        assert report.presentation["video"]["artifact_id"] == "e2e3-clip"
        assert report.presentation["effective_duration_ms"] == 1000
        from hevi.creative.layer4.usage_ledger import ProviderCallRecord

        analytics = aggregate((ProviderCallRecord.model_validate(report.call_record),))
        assert analytics.total_calls == 1 and analytics.succeeded == 1
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_e2e4_memory_precedence_chain_no_pii(tmp_path) -> None:
    """E2E-4: pref persisted -> new session -> convention -> instruction -> no PII."""

    from hevi.creative.layer4.creative_memory import CreativeMemory, MemoryError, MemorySource
    from hevi.memory.store import MemoryStore

    session_a = CreativeMemory(MemoryStore(tmp_path / "e2e4.db"))
    session_a.remember(scope="user", key="subtitle_style", content="双语白字", session_id="A")
    session_b = CreativeMemory(MemoryStore(tmp_path / "e2e4.db"))  # new Agent session
    assert any(
        h.entry_key == "subtitle_style" for h in session_b.recall_for_project("p9", "subtitle")
    )
    session_b.remember(
        scope="project:p9", key="subtitle_style", content="单语", project_id="p9", session_id="B"
    )
    resolved = session_b.resolve("p9", instruction="这次无字幕")
    by_key = {r.entry_key: r for r in resolved}
    assert by_key["subtitle_style"].source is MemorySource.PROJECT_CONVENTION
    assert by_key["subtitle_style"].content == "单语"
    assert resolved[-1].source is MemorySource.INSTRUCTION
    with pytest.raises(MemoryError):
        session_b.remember(scope="user", key="contact", content="mail me at a@b.com")
    store = MemoryStore(tmp_path / "e2e4.db")
    assert all(
        "a@b.com" not in (hit.payload.get("content", ""))
        for hit in store.recent("semantic", limit=100)
    )
