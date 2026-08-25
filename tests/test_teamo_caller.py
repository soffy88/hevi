"""TeamoRouter Grok/Pi 注册与选模(不打真实网关)。"""

from __future__ import annotations

import json

from hevi.obase.provider_presets import get_preset
from hevi.providers import llm_pick, teamo_caller
from hevi.providers.teamo_caller import register_teamo_llm, slot_model


def test_slot_models_from_env(monkeypatch):
    monkeypatch.setenv("TEAMOROUTER_GROK_MODEL", "grok-4.6")
    monkeypatch.setenv("TEAMOROUTER_PI_MODEL", "pi-custom")
    monkeypatch.setenv("TEAMOROUTER_FREE_MODEL", "deepseek-v4-pro-free")
    assert slot_model("grok") == "grok-4.6"
    assert slot_model("pi") == "pi-custom"
    assert slot_model("teamo") == "grok-4.6"
    assert slot_model("teamo_free") == "deepseek-v4-pro-free"


def test_register_without_key_is_noop(monkeypatch):
    monkeypatch.delenv("TEAMOROUTER_API_KEY", raising=False)
    register_teamo_llm()


def test_register_slots(monkeypatch):
    from obase.provider_registry import ProviderRegistry

    monkeypatch.setenv("TEAMOROUTER_API_KEY", "sk-teamo-test")
    monkeypatch.delenv("HEVI_LLM_PROVIDER", raising=False)
    register_teamo_llm()
    registry = ProviderRegistry.get()
    for name in ("grok", "pi", "teamo", "teamo_free"):
        assert callable(registry.llm(name))


def test_chat_payload_and_content(monkeypatch):
    captured: dict = {}

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"ok": true}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
                "model": "grok-4.6",
            }

    class _Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr(teamo_caller.httpx, "Client", _Client)
    out = teamo_caller.teamo_chat_completions(
        model="grok-4.6",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-teamo-test",
        base_url="https://api.teamorouter.com/v1",
    )
    assert captured["url"] == "https://api.teamorouter.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-teamo-test"
    assert captured["json"]["model"] == "grok-4.6"
    assert out["content"]
    assert json.loads(out["content"])["ok"] is True


def test_resolve_prefers_qwen_cloud_then_grok(monkeypatch):
    seen: list[str] = []

    class _Reg:
        def llm(self, name: str):
            seen.append(name)
            if name == "qwen_cloud":
                raise RuntimeError("missing")
            if name == "grok":
                return "GROK"
            raise RuntimeError("nope")

    import obase.provider_registry as pr

    monkeypatch.setattr(pr.ProviderRegistry, "get", staticmethod(lambda: _Reg()))
    assert llm_pick.resolve_text_llm() == "GROK"
    assert seen[:2] == ["qwen_cloud", "grok"]


def test_presets_include_grok_and_pi():
    grok = get_preset("grok")
    pi = get_preset("pi")
    assert grok is not None and grok["api_key_env"] == "TEAMOROUTER_API_KEY"
    assert pi is not None and pi["strategy"]["model"] == "pi"
    assert grok["strategy"]["model"] == "grok-4.6"
