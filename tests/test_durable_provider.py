"""W16 driver qualification: lifecycle, retry rules, resume, billing-once."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from hevi.tasks.durable_execution import load_record
from hevi.tasks.durable_provider import (
    DurableProviderError,
    JobPoll,
    SubmitRejected,
    download_with_resume,
    run_durable_provider_job,
)


def _spec(**kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "config": {},
        "provider": "fake",
        "endpoint": "fake-jobs",
        "model": "fake-1",
        "request": {"prompt": "x"},
        "production_revision": "rev-1",
        "target_artifact_id": "clip-1",
        "idempotency_key": "idem-1",
        "output_path": Path("/nonexistent/out.mp4"),
    }
    args.update(kw)
    return args


def _ok_download(monkeypatch: pytest.MonkeyPatch, payload: bytes = b"0123456789"):
    async def fake_download(url: str, dest: Path, **kw: Any) -> tuple[int, str | None]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        return len(payload), None

    monkeypatch.setattr("hevi.tasks.durable_provider.download_with_resume", fake_download)


@pytest.mark.asyncio
async def test_fresh_submit_poll_download(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ok_download(monkeypatch)
    persisted: list[dict[str, Any]] = []

    async def persist(config: dict[str, Any]) -> None:
        persisted.append(json.loads(json.dumps(config)))

    async def submit() -> str:
        return "job-1"

    polls = 0

    async def poll(job_id: str) -> JobPoll:
        nonlocal polls
        assert job_id == "job-1"
        polls += 1
        if polls < 2:
            return JobPoll(state="running")
        return JobPoll(state="succeeded", artifact_url="https://cdn.example/a.mp4", terminal="ok")

    _config, path, dump = await run_durable_provider_job(
        **_spec(config={}, output_path=tmp_path / "a.mp4", persist=persist),
        submit=submit,
        poll=poll,
        poll_interval_s=0,
    )
    assert path == tmp_path / "a.mp4"
    assert dump["remote_state"] == "remote_succeeded"
    assert dump["acquisition_state"] == "download_complete"
    assert dump["billing_state"] == "billed"
    assert dump["provider_job_id"] == "job-1"
    assert any(
        "job-1" in str(p.get("provider_execution", {}).get("provider_job_id")) for p in persisted
    )


@pytest.mark.asyncio
async def test_submit_rejection_retries_then_succeeds(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_download(monkeypatch)
    attempts = 0

    async def submit() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise SubmitRejected(429, "limited")
        return "job-9"

    async def poll(job_id: str) -> JobPoll:
        return JobPoll(state="succeeded", artifact_url="https://cdn.example/a.mp4")

    _config, path, dump = await run_durable_provider_job(
        **_spec(config={}, output_path=tmp_path / "a.mp4"),
        submit=submit,
        poll=poll,
        poll_interval_s=0,
        submit_backoff_s=(0, 0, 0, 0, 0),
    )
    assert attempts == 3
    assert dump["provider_job_id"] == "job-9"
    assert path.exists()


@pytest.mark.asyncio
async def test_submit_transport_ambiguity_surfaces_immediately() -> None:
    async def submit() -> str:
        raise httpx.ConnectError("conn lost after ambiguous POST")

    async def poll(job_id: str) -> JobPoll:  # pragma: no cover
        raise AssertionError("must not poll")

    with pytest.raises(httpx.ConnectError):
        await run_durable_provider_job(
            **_spec(config={}), submit=submit, poll=poll, poll_interval_s=0
        )


@pytest.mark.asyncio
async def test_resume_poll_after_restart_submits_once(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_download(monkeypatch)
    submits = 0

    async def submit() -> str:
        nonlocal submits
        submits += 1
        return "job-7"

    async def poll(job_id: str) -> JobPoll:
        return JobPoll(state="succeeded", artifact_url="https://cdn.example/a.mp4")

    first_config: dict[str, Any] = {}
    config, _, _ = await run_durable_provider_job(
        **_spec(config=first_config, output_path=tmp_path / "a.mp4"),
        submit=submit,
        poll=poll,
        poll_interval_s=0,
    )
    # crash + restart with persisted config: same fingerprint resumes
    _config2, path2, dump2 = await run_durable_provider_job(
        **_spec(config=config, output_path=tmp_path / "a.mp4"),
        submit=submit,
        poll=poll,
        poll_interval_s=0,
    )
    assert submits == 1
    assert dump2["provider_job_id"] == "job-7"
    assert path2.exists()


@pytest.mark.asyncio
async def test_remote_success_download_crash_resumes_without_resubmit(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ok_download(monkeypatch)
    submits = 0

    async def submit() -> str:
        nonlocal submits
        submits += 1
        return "job-3"

    async def poll(job_id: str) -> JobPoll:
        return JobPoll(state="succeeded", artifact_url="https://cdn.example/a.mp4")

    config: dict[str, Any] = {}
    config, _, _ = await run_durable_provider_job(
        **_spec(config=config, output_path=tmp_path / "a.mp4"),
        submit=submit,
        poll=poll,
        poll_interval_s=0,
    )
    record = load_record(config)
    assert record is not None and record.done is True
    # duplicate delivery of the finished job: returns path, still one submit
    config, _path, dump = await run_durable_provider_job(
        **_spec(config=config, output_path=tmp_path / "a.mp4"),
        submit=submit,
        poll=poll,
        poll_interval_s=0,
    )
    assert submits == 1
    assert dump["billing_state"] == "billed"


@pytest.mark.asyncio
async def test_expired_remote_fails_explicitly() -> None:
    async def submit() -> str:
        return "job-x"

    async def poll(job_id: str) -> JobPoll:
        return JobPoll(state="expired", error="gone")

    with pytest.raises(DurableProviderError, match="DURABLE_JOB_EXPIRED"):
        await run_durable_provider_job(
            **_spec(config={}), submit=submit, poll=poll, poll_interval_s=0
        )


@pytest.mark.asyncio
async def test_failed_remote_preserves_provider_message() -> None:
    async def submit() -> str:
        return "job-x"

    async def poll(job_id: str) -> JobPoll:
        return JobPoll(state="failed", error="content rejected")

    with pytest.raises(DurableProviderError, match="DURABLE_JOB_FAILED:content rejected"):
        await run_durable_provider_job(
            **_spec(config={}), submit=submit, poll=poll, poll_interval_s=0
        )


@pytest.mark.asyncio
async def test_download_with_resume_range_and_restart(tmp_path) -> None:
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    payload = b"0123456789ABCDEF" * 64  # 1024 bytes

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            if self.path == "/norange":
                body = payload
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            range_header = self.headers.get("Range")
            start = 0
            if range_header and range_header.startswith("bytes="):
                start = int(range_header.split("=")[1].split("-")[0])
                self.send_response(206)
                self.send_header(
                    "Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}"
                )
            else:
                self.send_response(200)
            body = payload[start:]
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", '"etag-1"')
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        dest = tmp_path / "f.bin"
        total, _etag = await download_with_resume(f"{base}/f", dest, min_bytes=100)
        assert total == 1024 and dest.read_bytes() == payload
        # resume from partial: only the tail is fetched
        dest.write_bytes(payload[:900])
        total, _ = await download_with_resume(
            f"{base}/f", dest, start_byte=900, etag='"etag-1"', min_bytes=100
        )
        assert total == 1024 and dest.read_bytes() == payload
        # no-range server restarts from zero without resubmit machinery
        dest2 = tmp_path / "g.bin"
        total, _ = await download_with_resume(
            f"{base}/norange", dest2, start_byte=500, min_bytes=100
        )
        assert total == 1024 and dest2.read_bytes() == payload
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.asyncio
async def test_ledger_emission_success_and_failure(tmp_path, monkeypatch) -> None:
    """W17-C: every provider run emits exactly one call-ledger row."""

    monkeypatch.setenv("HEVI_USAGE_DB", str(tmp_path / "usage.db"))
    _ok_download(monkeypatch)
    from hevi.creative.layer4.authority_stores import CallLedgerStore

    async def submit() -> str:
        return "job-ledger"

    async def poll_ok(job_id: str) -> JobPoll:
        return JobPoll(state="succeeded", artifact_url="https://cdn.example/a.mp4")

    await run_durable_provider_job(
        **_spec(config={}, output_path=tmp_path / "a.mp4", project_ref="proj-x"),
        submit=submit,
        poll=poll_ok,
        poll_interval_s=0,
    )
    rows, total = CallLedgerStore().list_records()
    assert total == 1
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["project_ref"] == "proj-x"
    assert rows[0]["provider"] == "fake"

    async def poll_fail(job_id: str) -> JobPoll:
        return JobPoll(state="failed", error="content rejected")

    with pytest.raises(Exception):  # noqa: B017 - driver error type varies by provider
        await run_durable_provider_job(
            **_spec(
                config={},
                output_path=tmp_path / "b.mp4",
                request={"prompt": "y"},
                provider="fake2",
            ),
            submit=submit,
            poll=poll_fail,
            poll_interval_s=0,
        )
    rows2, total2 = CallLedgerStore().list_records()
    assert total2 == 2
    failed = next(r for r in rows2 if r["status"] == "failed")
    assert failed["normalized_error_code"] == "PROVIDER_REJECTED"
    assert "content rejected" in failed["safe_error_message"]


@pytest.mark.asyncio
async def test_ledger_no_duplicate_row_on_redelivery(tmp_path, monkeypatch) -> None:
    """Retry/recovery must not fabricate a second call row for a finished job."""

    monkeypatch.setenv("HEVI_USAGE_DB", str(tmp_path / "usage.db"))
    _ok_download(monkeypatch)
    from hevi.creative.layer4.authority_stores import CallLedgerStore

    async def submit() -> str:
        return "job-once"

    async def poll(job_id: str) -> JobPoll:
        return JobPoll(state="succeeded", artifact_url="https://cdn.example/a.mp4")

    config, _, _ = await run_durable_provider_job(
        **_spec(config={}, output_path=tmp_path / "a.mp4"),
        submit=submit,
        poll=poll,
        poll_interval_s=0,
    )
    await run_durable_provider_job(
        **_spec(config=config, output_path=tmp_path / "a.mp4"),
        submit=submit,
        poll=poll,
        poll_interval_s=0,
    )
    _rows, total = CallLedgerStore().list_records()
    assert total == 1
