"""W12 gates: declarative definitions drive real HTTP end to end.

No internal function is mocked: a scripted fake provider serves real
HTTP over loopback TCP (submit -> poll -> artifact download), and the
artifact is a real ffmpeg-generated mp4 so the manifest -> presentation
link probes a genuine duration.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from hevi.creative.layer4.endpoint_execution import EndpointExecutionError, execute_endpoint
from hevi.creative.layer4.endpoint_lifecycle import (
    AuthMode,
    CapabilityDeclaration,
    DeclarativeEndpointDefinition,
    SyncMode,
    enable,
    mark_validated,
    record_trial,
)
from hevi.creative.layer4.provider_execution import ProviderExecutionRecord

SECRET_VALUE = "fake-secret-value"
FAKE_MP4_DURATION_MS = 1000


class _FakeProviderHandler(BaseHTTPRequestHandler):
    submits = 0
    polls = 0
    seen_authorization: str | None = None
    succeed_after_polls = 2
    fail_job = False

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
        if self.path != "/v1/generate":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        type(self).seen_authorization = self.headers.get("Authorization")
        type(self).submits += 1
        self._json({"job": {"id": "job-1", "status": "running"}})

    def do_GET(self) -> None:
        if self.path == "/v1/jobs/job-1":
            type(self).polls += 1
            if type(self).fail_job:
                self._json(
                    {
                        "job": {
                            "id": "job-1",
                            "status": "failed",
                            "error": {"code": "E1", "message": "nope"},
                        }
                    }
                )
                return
            if type(self).polls <= type(self).succeed_after_polls:
                self._json({"job": {"id": "job-1", "status": "running"}})
                return
            host = f"http://127.0.0.1:{self.server.server_port}"
            self._json(
                {
                    "job": {
                        "id": "job-1",
                        "status": "succeeded",
                        "video_url": f"{host}/file/clip.mp4",
                    }
                }
            )
            return
        if self.path == "/file/clip.mp4":
            data = bytes(type(self).artifact_bytes)
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)


@pytest.fixture()
def fake_provider(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg required for real-media smoke")
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=128x128:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(clip),
            "-y",
        ],
        check=True,
    )
    _FakeProviderHandler.artifact_bytes = clip.read_bytes()
    _FakeProviderHandler.submits = 0
    _FakeProviderHandler.polls = 0
    _FakeProviderHandler.seen_authorization = None
    _FakeProviderHandler.succeed_after_polls = 2
    _FakeProviderHandler.fail_job = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=5)


def _definition(base_url: str, **kw: Any) -> DeclarativeEndpointDefinition:
    args: dict[str, Any] = {
        "name": "fake-video",
        "provider_family": "fake",
        "base_url": f"{base_url}/v1/generate",
        "auth_mode": AuthMode.BEARER,
        "headers_template": {"Authorization": "Bearer {$SECRET:fake_key}"},
        "request_schema": {"properties": {"prompt": {}, "duration_s": {}}},
        "request_template": '{"prompt": "{{prompt}}"}',
        "sync_mode": SyncMode.ASYNC_JOB,
        "job_id_path": "job.id",
        "poll_path_template": f"{base_url}/v1/jobs/{{{{job_id}}}}",
        "status_path": "job.status",
        "success_states": ("succeeded",),
        "failure_states": ("failed",),
        "artifact_url_path": "job.video_url",
        "error_code_path": "error.code",
        "error_message_path": "error.message",
        "capability": CapabilityDeclaration(
            media_type="video", durations_s=(5,), resolutions=("720p",), async_job=True
        ),
        "secret_references": ("fake_key",),
    }
    args.update(kw)
    return DeclarativeEndpointDefinition(**args)


def _enabled(base_url: str) -> DeclarativeEndpointDefinition:
    return enable(record_trial(mark_validated(_definition(base_url)), outcome="success"))


def _params(**kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "prompt": "雨夜街景",
        "duration_s": 5,
        "production_revision": "rev-1",
        "target_artifact_id": "clip-1",
    }
    args.update(kw)
    return args


def test_full_chain_over_real_http(fake_provider, tmp_path) -> None:
    """DECLARATIVE_ENDPOINT_REAL_HTTP + DURABLE_EXECUTION + ARTIFACT_REGISTRATION."""

    base = f"http://127.0.0.1:{fake_provider.server_port}"
    definition = _enabled(base)
    report = execute_endpoint(definition, _params(), {"fake_key": SECRET_VALUE}, tmp_path / "out")
    assert report.submitted is True
    assert report.provider_job_id == "job-1"
    assert report.polls_used >= 2
    assert report.terminal_status == "succeeded"
    assert report.bytes_downloaded > 0
    assert report.artifact_sha256 is not None
    assert report.execution_record["remote_state"] == "remote_succeeded"
    assert report.execution_record["acquisition_state"] == "download_complete"
    assert report.call_record["status"] == "succeeded"
    assert report.manifest["artifacts"][0]["artifact_id"] == "clip-1"
    assert report.presentation["video"]["artifact_id"] == "clip-1"
    assert report.presentation["effective_duration_ms"] == FAKE_MP4_DURATION_MS
    # secret isolation: on the wire yes, in the definition never
    assert _FakeProviderHandler.seen_authorization == f"Bearer {SECRET_VALUE}"
    exported = definition.model_dump(mode="json")
    assert SECRET_VALUE not in json.dumps(exported)


def test_trial_mode_quarantines(fake_provider, tmp_path) -> None:
    from hevi.creative.layer4.endpoint_lifecycle import mark_validated, record_trial

    base = f"http://127.0.0.1:{fake_provider.server_port}"
    tested = record_trial(mark_validated(_definition(base)), outcome="success")
    report = execute_endpoint(
        tested, _params(), {"fake_key": SECRET_VALUE}, tmp_path / "out", test_only=True
    )
    assert report.test_only is True
    assert report.presentation == {}
    assert report.artifact_local_path is not None


def test_not_enabled_refuses_without_submit(fake_provider, tmp_path) -> None:
    base = f"http://127.0.0.1:{fake_provider.server_port}"
    with pytest.raises(EndpointExecutionError, match="ENDPOINT_NOT_ENABLED"):
        execute_endpoint(_definition(base), _params(), {"fake_key": SECRET_VALUE}, tmp_path / "out")
    assert _FakeProviderHandler.submits == 0


def test_blocked_admission_never_submits(fake_provider, tmp_path) -> None:
    base = f"http://127.0.0.1:{fake_provider.server_port}"
    with pytest.raises(EndpointExecutionError, match="ENDPOINT_ADMISSION_BLOCKED"):
        execute_endpoint(
            _enabled(base),
            _params(duration_s=30),
            {"fake_key": SECRET_VALUE},
            tmp_path / "out",
        )
    assert _FakeProviderHandler.submits == 0


def test_secret_unresolved_never_submits(fake_provider, tmp_path) -> None:
    base = f"http://127.0.0.1:{fake_provider.server_port}"
    with pytest.raises(EndpointExecutionError, match="ENDPOINT_SECRET_UNRESOLVED"):
        execute_endpoint(_enabled(base), _params(), {}, tmp_path / "out")
    assert _FakeProviderHandler.submits == 0


def test_poll_budget_exceeded(fake_provider, tmp_path) -> None:
    base = f"http://127.0.0.1:{fake_provider.server_port}"
    with pytest.raises(EndpointExecutionError, match="ENDPOINT_POLL_BUDGET_EXCEEDED"):
        execute_endpoint(
            _enabled(base),
            _params(),
            {"fake_key": SECRET_VALUE},
            tmp_path / "out",
            max_polls=1,
        )
    assert _FakeProviderHandler.submits == 1


def test_transport_failure_carries_usage_evidence(fake_provider, tmp_path) -> None:
    base = "http://127.0.0.1:1"  # nothing listens: transport fails, nothing billed
    with pytest.raises(EndpointExecutionError, match="ENDPOINT_TRANSPORT_FAILED") as exc:
        execute_endpoint(_enabled(base), _params(), {"fake_key": SECRET_VALUE}, tmp_path / "out")
    assert exc.value.details["call_record"]["status"] == "failed"


def test_resume_existing_record_submits_once(fake_provider, tmp_path) -> None:
    base = f"http://127.0.0.1:{fake_provider.server_port}"
    definition = _enabled(base)
    secrets = {"fake_key": SECRET_VALUE}
    first = execute_endpoint(definition, _params(), secrets, tmp_path / "out1")
    record = ProviderExecutionRecord.model_validate(first.execution_record)
    second = execute_endpoint(
        definition, _params(), secrets, tmp_path / "out2", existing_record=record
    )
    assert second.submitted is False
    assert second.provider_job_id == "job-1"
    assert _FakeProviderHandler.submits == 1
