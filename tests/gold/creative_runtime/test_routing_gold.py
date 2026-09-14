"""Gold behaviour for routing a resolved model to a real local provider."""

from __future__ import annotations

import asyncio
import http.server
import json
import threading
from collections.abc import Iterator
from typing import ClassVar

import pytest
from obase.exceptions import ProviderNotFoundError
from obase.provider_registry import ProviderRegistry

from hevi.creative.oprim import ModelRouter, Route
from hevi.providers.openai_compatible_caller import register_openai_compatible_llm


@pytest.fixture
def restore_llm_registry() -> Iterator[None]:
    saved = dict(ProviderRegistry._llms)
    yield
    ProviderRegistry._llms.clear()
    ProviderRegistry._llms.update(saved)


class _LocalLLM(http.server.BaseHTTPRequestHandler):
    calls: ClassVar[list[dict[str, object]]] = []

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        _LocalLLM.calls.append(
            {"body": body, "authorized": bool(self.headers.get("Authorization"))}
        )
        data = json.dumps(
            {
                "id": "gold-completion",
                "choices": [{"message": {"role": "assistant", "content": "pong"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        return


def test_execute_runs_through_registered_provider(
    monkeypatch: pytest.MonkeyPatch, restore_llm_registry: None
) -> None:
    _LocalLLM.calls = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _LocalLLM)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("OPENAI_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gold-model")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-gold-secret")
    register_openai_compatible_llm()
    router = ModelRouter(Route(provider="openai_compatible", model="gold-model"))
    try:
        execution = asyncio.run(
            router.execute(capability="script", messages=[{"role": "user", "content": "ping"}])
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert execution.content == "pong"
    assert execution.provider == "openai_compatible"
    assert execution.model == "gold-model"
    assert execution.usage["total_tokens"] == 2
    assert _LocalLLM.calls[0]["body"]["model"] == "gold-model"
    assert _LocalLLM.calls[0]["authorized"] is True


def test_unregistered_provider_fails_closed(restore_llm_registry: None) -> None:
    router = ModelRouter(Route(provider="nobody", model="none"))
    with pytest.raises(ProviderNotFoundError):
        asyncio.run(router.execute(capability="script", messages=[]))
