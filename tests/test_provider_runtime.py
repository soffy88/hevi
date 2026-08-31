"""Runtime provider wiring and the production media freeze contract."""

from __future__ import annotations

import asyncio

import httpx


def test_provider_configuration_is_redacted_and_uses_runtime_endpoints(monkeypatch):
    from hevi.provider_policy.runtime import provider_configuration

    monkeypatch.setenv("VOICEBOX_BASE_URL", "http://user:secret@engine.test:17600/api?token=x")
    monkeypatch.setenv("LONGCAT_BASE_URL", "https://llm.test/v1")
    monkeypatch.setenv("LONGCAT_API_KEY", "longcat-secret")
    monkeypatch.setenv("JOYAI_BASE_URL", "https://joy.test")
    monkeypatch.setenv("JOYAI_STREAM_WS_PATH", "/edit")

    states = {item["id"]: item for item in provider_configuration()}
    assert states["voicebox"]["configured"] is True
    assert states["voicebox"]["endpoint"] == "http://engine.test:17600/api"
    assert "secret" not in str(states)
    assert states["joyai"]["stream_endpoint"] == "wss://joy.test/edit"


def test_runtime_probes_use_real_provider_endpoints_without_leaking_keys(monkeypatch):
    from hevi.provider_policy.runtime import probe_provider

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "mpt.test":
            return httpx.Response(200, text="pong", request=request)
        if request.url.host == "api.pexels.com":
            return httpx.Response(200, json={"photos": []}, request=request)
        if request.url.host == "longcat.test":
            return httpx.Response(200, json={"data": []}, request=request)
        return httpx.Response(404, request=request)

    async def run() -> list[dict]:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await asyncio.gather(
                probe_provider("mpt", client=client),
                probe_provider("pexels", client=client),
                probe_provider("longcat", client=client),
            )
        finally:
            await client.aclose()

    monkeypatch.setenv("MPT_API_BASE", "http://mpt.test")
    monkeypatch.setenv("PEXELS_API_KEY", "pexels-secret")
    monkeypatch.setenv("LONGCAT_BASE_URL", "http://longcat.test/v1")
    monkeypatch.setenv("LONGCAT_API_KEY", "longcat-secret")

    results = asyncio.run(run())
    assert all(item["ready"] for item in results)
    assert all("secret" not in str(item) for item in results)
    assert {request.url.host for request in seen} == {"mpt.test", "api.pexels.com", "longcat.test"}
    assert any(request.headers.get("Authorization") == "pexels-secret" for request in seen)


def test_joyai_uses_a_real_websocket_probe(monkeypatch):
    from hevi.provider_policy.runtime import probe_provider

    class FakeConnection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    def fake_connect(url, **kwargs):
        assert url == "wss://joy.test/ws/edit"
        assert kwargs["open_timeout"] == 5.0
        return FakeConnection()

    monkeypatch.setattr("websockets.asyncio.client.connect", fake_connect)
    monkeypatch.setenv("JOYAI_STREAM_WS_URL", "wss://joy.test/ws/edit")
    result = asyncio.run(probe_provider("joyai"))
    assert result["configured"] is True
    assert result["reachable"] is True
    assert result["ready"] is True
    assert result["error"] is None


def test_media_default_chain_contains_frozen_stock_resolvers():
    from hevi.sourcing.media_providers import default_providers

    providers = default_providers()
    assert "image" in providers and "stock" in providers["image"]
    assert "video" in providers and "stock" in providers["video"]


def test_download_cached_returns_a_non_empty_local_file(tmp_path):
    from hevi.sourcing.media_providers import _download_cached

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"asset", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        path = _download_cached("https://cdn.test/clip.mp4", tmp_path, ".mp4", client)
    assert path is not None
    assert path.is_file()
    assert path.read_bytes() == b"asset"


def test_fail_closed_readiness_classifies_config_network_auth_and_model_states():
    from hevi.provider_policy.runtime import readiness_from_probe

    missing = readiness_from_probe(
        {
            "id": "longcat",
            "name": "LongCat",
            "configured": False,
            "reachable": False,
            "missing": ["LONGCAT_API_KEY"],
        }
    )
    assert missing["status"] == "BLOCKED_CONFIG"

    network = readiness_from_probe(
        {
            "id": "longcat",
            "name": "LongCat",
            "configured": True,
            "reachable": False,
            "error": "TimeoutException",
        }
    )
    assert network["status"] == "BLOCKED_NETWORK"

    auth = readiness_from_probe(
        {
            "id": "pexels",
            "name": "Pexels",
            "configured": True,
            "reachable": False,
            "http_status": 401,
            "error": "http_401",
        }
    )
    assert auth["status"] == "BLOCKED_AUTH"

    unloaded = readiness_from_probe(
        {"id": "mpt", "name": "MPT", "configured": True, "reachable": True},
    )
    assert unloaded["status"] == "BLOCKED_MODEL"
    assert unloaded["authenticated"] is True


def test_fail_closed_readiness_requires_real_submit_ack_and_artifact(tmp_path):
    from hevi.provider_policy.runtime import readiness_from_probe

    artifact = tmp_path / "real.wav"
    artifact.write_bytes(b"real provider artifact")
    ready = readiness_from_probe(
        {"id": "pocket_tts", "name": "Pocket TTS", "configured": True, "reachable": True},
        model_ready=True,
        submit_ready=True,
        artifact_ready=artifact.is_file() and artifact.stat().st_size > 0,
        provider_job_id="local-pocket-ack",
    )
    assert ready["status"] == "READY"
    assert ready["provider_job_id"] == "local-pocket-ack"

    no_submit = readiness_from_probe(
        {"id": "voicebox", "name": "Voicebox", "configured": True, "reachable": True},
        model_ready=True,
        artifact_ready=True,
    )
    assert no_submit["status"] == "BLOCKED_RUNTIME"
