"""W16 per-adapter fault qualification: legacy loops run the durable plane.

Each migrated async adapter is driven against a scripted loopback HTTP
origin (real TCP, no internal mocks) through: full run, restart from a
post-submit snapshot, duplicate delivery, and download-failure recovery.
Universal gates per adapter: submits == 1, billed once, no resubmit on
download failure, Range resume honored, remote completion never lost.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from hevi.tasks.durable_execution import load_record

FILE_BYTES = b"0123456789ABCDEF" * 128  # 2048 bytes


class OriginHandler(BaseHTTPRequestHandler):
    routes: ClassVar[dict[tuple[str, str], Any]] = {}
    calls: ClassVar[list[tuple[str, str, dict[str, str]]]] = []

    def log_message(self, *args: Any) -> None:
        pass

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        key = (self.command, self.path.split("?")[0])
        type(self).calls.append((self.command, self.path, dict(self.headers)))
        handler = type(self).routes.get(key)
        if handler is None:
            self.send_error(404)
            return
        status, body, headers = handler(dict(self.headers))
        if isinstance(body, (bytes, bytearray)):
            payload = bytes(body)
            content_type = "video/mp4"
        else:
            payload = json.dumps(body).encode()
            content_type = "application/json"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _handle
    do_POST = _handle


@pytest.fixture()
def origin(tmp_path_factory):
    import ssl
    import subprocess

    cert_dir = tmp_path_factory.mktemp("tls")
    key = cert_dir / "key.pem"
    cert = cert_dir / "cert.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "2",
            "-nodes",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    import os

    previous = os.environ.get("SSL_CERT_FILE")
    os.environ["SSL_CERT_FILE"] = str(cert)
    OriginHandler.routes = {}
    OriginHandler.calls = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), OriginHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=5)
    if previous is None:
        os.environ.pop("SSL_CERT_FILE", None)
    else:
        os.environ["SSL_CERT_FILE"] = previous


def _file_route(payload: bytes = FILE_BYTES):
    def handler(headers: dict[str, str]):
        return 200, payload, {"ETag": '"e1"'}

    return handler


def _submit_count(calls: list[tuple[str, str, dict]]) -> int:
    return sum(1 for method, path, _ in calls if method == "POST")


def _range_headers(calls: list[tuple[str, str, dict]]) -> list[str]:
    return [h.get("Range", "") for _, _, h in calls if h.get("Range")]


async def _check_adapter(
    invoke,  # async (durable: dict) -> Path | dict
    *,
    job_id: str,
    output_path: Path,
    fail_once_state: dict[str, Any],
) -> dict[str, Any]:
    """Shared fault matrix. Returns the final durable dict."""

    from hevi.creative.layer4.provider_execution import apply_download_progress
    from hevi.tasks.durable_execution import store_record

    def _posts() -> int:
        return _submit_count(OriginHandler.calls)

    def _range_starts() -> list[str]:
        return [h for h in _range_headers(OriginHandler.calls) if h.startswith("bytes=")]

    durable: dict[str, Any] = {}
    # 0. worker dies during artifact download: submit + remote success must
    # already be persisted (job id present) and no second submit may follow.
    fail_once_state["fail_once"] = True
    with pytest.raises(Exception):  # noqa: B017 - adapter-specific error classes vary
        await invoke(durable)
    assert durable.get("provider_execution", {}).get("provider_job_id") == job_id
    assert _posts() == 1
    fail_once_state["fail_once"] = False
    # 1. restart resumes download only: one submit total, done, billed once.
    await invoke(durable)
    record = load_record(durable)
    assert record is not None and record.done is True
    assert record.provider_job_id == job_id
    assert _posts() == 1
    # 2. partial-file resume honors Range, still one submit.
    mid = apply_download_progress(record, received_bytes=1000, etag=None)
    resumed = store_record(json.loads(json.dumps(durable)), mid)
    output_path.write_bytes(b"0" * 1000)
    await invoke(resumed)
    assert _posts() == 1
    assert "bytes=1000-" in _range_starts()
    assert output_path.stat().st_size >= 1024
    # 3. duplicate delivery of the finished job: path back, billed once.
    await invoke(durable)
    assert _posts() == 1
    final = load_record(durable)
    assert final is not None
    assert final.billing_state.value == "billed"
    return durable


def _routes_with_file(
    base: str,
    submit_path: str,
    submit_body: dict,
    polls: list[dict],
    file_path: str,
    state: dict[str, Any],
) -> None:
    OriginHandler.routes[("POST", submit_path)] = lambda headers: (200, submit_body, {})
    queue = {"polls": list(polls)}

    def poll(headers: dict[str, str]):
        if queue["polls"]:
            return 200, queue["polls"].pop(0), {}
        return 200, polls[-1], {}

    OriginHandler.routes[("GET", polls[0].pop("_path"))] = poll

    def serve_file(headers: dict[str, str]):
        if state.get("fail_once"):
            return 500, {"error": "boom"}, {}
        return 200, FILE_BYTES, {"ETag": '"e1"'}

    OriginHandler.routes[("GET", file_path)] = serve_file


@pytest.mark.asyncio
async def test_maas_durable_fault_matrix(origin, tmp_path, monkeypatch) -> None:
    from hevi.video import alibaba_maas_service as maas

    base = f"127.0.0.1:{origin.server_port}"
    monkeypatch.setenv("ALIBABA_MAAS_API_KEY", "k")
    monkeypatch.setenv("ALIBABA_MAAS_HOST", base)
    state: dict[str, Any] = {}
    _routes_with_file(
        base,
        "/api/v1/services/aigc/video-generation/video-synthesis",
        {"output": {"task_id": "T1"}},
        [
            {"_path": "/api/v1/tasks/T1", "output": {"task_id": "T1", "task_status": "RUNNING"}},
            {
                "_path": "/api/v1/tasks/T1",
                "output": {
                    "task_id": "T1",
                    "task_status": "SUCCEEDED",
                    "video_url": f"https://{base}/f/v.mp4",
                },
            },
        ],
        "/f/v.mp4",
        state,
    )

    async def invoke(durable: dict[str, Any]):
        return await maas.alibaba_maas_generate(
            prompt="x",
            output_path=tmp_path / "out.mp4",
            model="wan_2_7",
            poll_interval_s=0,
            timeout_s=30,
            durable=durable,
        )

    durable = await _check_adapter(
        invoke, job_id="T1", output_path=tmp_path / "out.mp4", fail_once_state=state
    )
    assert (tmp_path / "out.mp4").stat().st_size >= 1024
    assert load_record(durable) is not None


@pytest.mark.asyncio
async def test_wavespeed_durable_fault_matrix(origin, tmp_path, monkeypatch) -> None:
    from hevi.video import wavespeed_service as wavespeed

    monkeypatch.setenv("WAVESPEED_API_KEY", "k")
    monkeypatch.setattr(wavespeed, "_BASE_URL", f"https://127.0.0.1:{origin.server_port}/api/v3")
    base = f"127.0.0.1:{origin.server_port}"
    state: dict[str, Any] = {}
    _routes_with_file(
        base,
        "/api/v3/alibaba/wan-2.7/text-to-video",
        {"data": {"id": "R1"}},
        [
            {"_path": "/api/v3/predictions/R1/result", "data": {"status": "pending"}},
            {
                "_path": "/api/v3/predictions/R1/result",
                "data": {"status": "completed", "outputs": [f"https://{base}/f/v.mp4"]},
            },
        ],
        "/f/v.mp4",
        state,
    )

    async def invoke(durable: dict[str, Any]):
        return await wavespeed.wavespeed_generate(
            prompt="x",
            output_path=tmp_path / "out.mp4",
            model="wan_2_7",
            poll_interval_s=0,
            timeout_s=30,
            durable=durable,
        )

    await _check_adapter(
        invoke, job_id="R1", output_path=tmp_path / "out.mp4", fail_once_state=state
    )


@pytest.mark.asyncio
async def test_vidu_durable_fault_matrix(origin, tmp_path, monkeypatch) -> None:
    from hevi.video import vidu_service as vidu

    monkeypatch.setenv("VIDU_API_KEY", "k")
    monkeypatch.setattr(vidu, "_BASE_URL", f"https://127.0.0.1:{origin.server_port}/ent/v2")
    base = f"127.0.0.1:{origin.server_port}"
    state: dict[str, Any] = {}
    _routes_with_file(
        base,
        "/ent/v2/reference2video",
        {"task_id": "T1"},
        [
            {"_path": "/ent/v2/tasks/T1/creations", "state": "pending"},
            {
                "_path": "/ent/v2/tasks/T1/creations",
                "state": "success",
                "creations": [{"url": f"https://{base}/f/v.mp4"}],
            },
        ],
        "/f/v.mp4",
        state,
    )

    async def invoke(durable: dict[str, Any]):
        return await vidu.vidu_reference_to_video(
            prompt="x",
            reference_images=["https://x/y.png"],
            output_path=tmp_path / "out.mp4",
            poll_interval_s=0,
            timeout_s=30,
            durable=durable,
        )

    await _check_adapter(
        invoke, job_id="T1", output_path=tmp_path / "out.mp4", fail_once_state=state
    )


@pytest.mark.asyncio
async def test_dashscope_durable_fault_matrix(origin, tmp_path, monkeypatch) -> None:
    from hevi.video import dashscope_i2v_service as ds

    base = f"127.0.0.1:{origin.server_port}"
    monkeypatch.setenv("ALIBABA_MAAS_API_KEY", "k")
    monkeypatch.setenv("ALIBABA_MAAS_HOST", base)
    state: dict[str, Any] = {}
    img = tmp_path / "frame.png"
    img.write_bytes(b"fake-png")
    _routes_with_file(
        base,
        "/api/v1/services/aigc/video-generation/video-synthesis",
        {"output": {"task_id": "T1"}},
        [
            {"_path": "/api/v1/tasks/T1", "output": {"task_id": "T1", "task_status": "RUNNING"}},
            {
                "_path": "/api/v1/tasks/T1",
                "output": {
                    "task_id": "T1",
                    "task_status": "SUCCEEDED",
                    "video_url": f"https://{base}/f/v.mp4",
                },
            },
        ],
        "/f/v.mp4",
        state,
    )

    async def invoke(durable: dict[str, Any]):
        return await ds.i2v_animate(
            image_path=img,
            prompt="x",
            output_path=tmp_path / "out.mp4",
            poll_interval_s=0,
            timeout_s=30,
            durable=durable,
        )

    await _check_adapter(
        invoke, job_id="T1", output_path=tmp_path / "out.mp4", fail_once_state=state
    )


@pytest.mark.asyncio
async def test_dashscope_rejection_retries_without_ambiguous_resubmit(
    origin, tmp_path, monkeypatch
) -> None:
    from hevi.video import dashscope_i2v_service as ds

    base = f"127.0.0.1:{origin.server_port}"
    monkeypatch.setenv("ALIBABA_MAAS_API_KEY", "k")
    monkeypatch.setenv("ALIBABA_MAAS_HOST", base)
    monkeypatch.setattr("hevi.tasks.durable_provider.asyncio.sleep", _nosleep)
    img = tmp_path / "frame.png"
    img.write_bytes(b"fake-png")
    attempts = {"n": 0}

    def submit(headers: dict[str, str]):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return 429, {"message": "throttled"}, {}
        return 200, {"output": {"task_id": "T9"}}, {}

    OriginHandler.routes[("POST", "/api/v1/services/aigc/video-generation/video-synthesis")] = (
        submit
    )
    OriginHandler.routes[("GET", "/api/v1/tasks/T9")] = lambda headers: (
        200,
        {
            "output": {
                "task_id": "T9",
                "task_status": "SUCCEEDED",
                "video_url": f"https://{base}/f/v.mp4",
            }
        },
        {},
    )
    OriginHandler.routes[("GET", "/f/v.mp4")] = lambda headers: (200, FILE_BYTES, {})
    out = await ds.i2v_animate(
        image_path=img,
        prompt="x",
        output_path=tmp_path / "o.mp4",
        poll_interval_s=0,
        timeout_s=30,
    )
    assert attempts["n"] == 3
    assert out.exists()


async def _nosleep(*args: Any, **kwargs: Any) -> None:
    return None


@pytest.mark.asyncio
async def test_runway_durable_fault_matrix(origin, tmp_path, monkeypatch) -> None:
    from hevi.video import runway_service as runway

    monkeypatch.setenv("RUNWAY_API_KEY", "k")
    monkeypatch.setattr(runway, "_BASE_URL", f"https://127.0.0.1:{origin.server_port}/v1")
    base = f"127.0.0.1:{origin.server_port}"
    state: dict[str, Any] = {}
    _routes_with_file(
        base,
        "/v1/image_to_video",
        {"id": "T1"},
        [
            {"_path": "/v1/tasks/T1", "status": "PENDING"},
            {"_path": "/v1/tasks/T1", "status": "SUCCEEDED", "output": [f"https://{base}/f/v.mp4"]},
        ],
        "/f/v.mp4",
        state,
    )

    async def invoke(durable: dict[str, Any]):
        return await runway.runway_image_to_video(
            prompt="x",
            reference_images=["https://x/y.png"],
            output_path=tmp_path / "out.mp4",
            poll_interval_s=0,
            timeout_s=30,
            durable=durable,
        )

    await _check_adapter(
        invoke, job_id="T1", output_path=tmp_path / "out.mp4", fail_once_state=state
    )


@pytest.mark.asyncio
async def test_fal_durable_fault_matrix(origin, tmp_path, monkeypatch) -> None:
    from hevi.image import fal_image_service as fal

    base = f"https://127.0.0.1:{origin.server_port}"
    monkeypatch.setenv("FAL_API_KEY", "k")
    monkeypatch.setattr(fal, "_FAL_BASE", base)
    monkeypatch.setattr(fal, "_POLL_INTERVAL_S", 0)
    state: dict[str, Any] = {}
    OriginHandler.routes[("POST", "/fal-ai/flux/schnell")] = lambda headers: (
        200,
        {"status_url": f"{base}/jobs/J1", "response_url": f"{base}/jobs/J1/result"},
        {},
    )
    queue = {"n": 0}

    def poll(headers: dict[str, str]):
        queue["n"] += 1
        if queue["n"] < 2:
            return 200, {"status": "IN_PROGRESS"}, {}
        return 200, {"status": "COMPLETED"}, {}

    OriginHandler.routes[("GET", "/jobs/J1")] = poll
    OriginHandler.routes[("GET", "/jobs/J1/result")] = lambda headers: (
        200,
        {"images": [{"url": f"{base}/f/i.png"}]},
        {},
    )
    OriginHandler.routes[("GET", "/f/i.png")] = lambda headers: (
        (500, {"error": "boom"}, {}) if state.get("fail_once") else (200, FILE_BYTES, {})
    )

    async def invoke(durable: dict[str, Any]):
        result = await fal.fal_image_generate(
            prompt="x", output_path=tmp_path / "out.png", durable=durable
        )
        return Path(result["output_path"])

    await _check_adapter(
        invoke,
        job_id=f"{base}/jobs/J1",
        output_path=tmp_path / "out.png",
        fail_once_state=state,
    )


@pytest.mark.asyncio
async def test_qwen_image_durable_fault_matrix(origin, tmp_path, monkeypatch) -> None:
    from hevi.image import qwen_image_service as qwen

    base = f"127.0.0.1:{origin.server_port}"
    monkeypatch.setenv("ALIBABA_MAAS_API_KEY", "k")
    monkeypatch.setenv("ALIBABA_MAAS_HOST", base)
    state: dict[str, Any] = {}
    _routes_with_file(
        base,
        "/api/v1/services/aigc/text2image/image-synthesis",
        {"output": {"task_id": "T1"}},
        [
            {"_path": "/api/v1/tasks/T1", "output": {"task_id": "T1", "task_status": "RUNNING"}},
            {
                "_path": "/api/v1/tasks/T1",
                "output": {
                    "task_id": "T1",
                    "task_status": "SUCCEEDED",
                    "results": [{"url": f"https://{base}/f/i.png"}],
                },
            },
        ],
        "/f/i.png",
        state,
    )

    async def invoke(durable: dict[str, Any]):
        return await qwen.qwen_image_generate(
            prompt="x",
            output_path=tmp_path / "out.png",
            poll_interval_s=0,
            timeout_s=30,
            durable=durable,
        )

    await _check_adapter(
        invoke, job_id="T1", output_path=tmp_path / "out.png", fail_once_state=state
    )


@pytest.mark.asyncio
async def test_qwen_quota_fast_fail_submits_once(origin, tmp_path, monkeypatch) -> None:
    from hevi.image import qwen_image_service as qwen
    from hevi.image.qwen_image_service import QwenImageError

    base = f"127.0.0.1:{origin.server_port}"
    monkeypatch.setenv("ALIBABA_MAAS_API_KEY", "k")
    monkeypatch.setenv("ALIBABA_MAAS_HOST", base)
    OriginHandler.routes[("POST", "/api/v1/services/aigc/text2image/image-synthesis")] = (
        lambda headers: (403, {"code": "AllocationQuota.FreeTierOnly"}, {})
    )
    with pytest.raises(QwenImageError, match="免费额度"):
        await qwen.qwen_image_generate(
            prompt="x", output_path=tmp_path / "o.png", poll_interval_s=0
        )
    assert _submit_count(OriginHandler.calls) == 1


@pytest.mark.asyncio
async def test_libtv_session_resume_and_download_skip(origin, tmp_path, monkeypatch) -> None:
    from hevi.core.config import settings
    from hevi.video import libtv_service as libtv

    base = f"https://127.0.0.1:{origin.server_port}"
    monkeypatch.setattr(settings, "libtv_im_base", base, raising=False)
    monkeypatch.setattr(settings, "libtv_access_key", "test-key", raising=False)
    video_url = f"{base}/f/v.mp4"
    OriginHandler.routes[("POST", "/openapi/session")] = lambda headers: (
        200,
        {"data": {"sessionId": "S1", "projectUuid": "P1"}},
        {},
    )
    messages = {
        "data": {
            "messages": [
                {
                    "role": "tool",
                    "seq": 2,
                    "content": json.dumps(
                        {"task_result": {"videos": [{"previewPath": video_url}]}}
                    ),
                },
            ]
        }
    }
    OriginHandler.routes[("GET", "/openapi/session/S1")] = lambda headers: (200, messages, {})
    OriginHandler.routes[("GET", "/f/v.mp4")] = lambda headers: (200, FILE_BYTES, {"ETag": '"e1"'})

    durable: dict[str, Any] = {}
    first = await libtv.generate_via_libtv(
        "make a video", tmp_path, poll_interval_s=0, timeout_s=30, prefix="t", durable=durable
    )
    assert first["session_id"] == "S1"
    assert first["video"] is not None
    assert _submit_count(OriginHandler.calls) == 1
    assert durable["provider_execution"]["provider_job_id"] == "S1"
    # restart: same durable dict resumes without creating a new session
    second = await libtv.generate_via_libtv(
        "make a video", tmp_path, poll_interval_s=0, timeout_s=30, prefix="t", durable=durable
    )
    assert second["session_id"] == "S1"
    assert _submit_count(OriginHandler.calls) == 1
    assert second["files"] == first["files"]  # present files skipped, listing rebuilt
