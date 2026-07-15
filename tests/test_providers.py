"""providers 模块回归测试(item 4)。

providers/registry.py 是 hevi 对 4 个私有上游库(obase/oprim/oskill/omodul)+
vibevoice 的 9 处运行时猴子补丁的宿主,却长期无测试 —— 上游任一升版都可能使补丁
失配、且失败被 try/except 静默吞掉。这些测试把"补丁应达成的契约"固化下来:任一
补丁失效即在此报警,而非在出片链深处以隐蔽方式崩。
"""

from __future__ import annotations

import pytest

from hevi.providers import local_qwen_adapter as lqa
from hevi.providers.registry import ProviderRegistry, register_all_providers


@pytest.fixture(autouse=True)
def _reset():
    register_all_providers()
    yield


def test_all_expected_providers_registered():
    reg = ProviderRegistry.get()
    for name in (
        "ltx2_cloud",
        "wan_cloud",
        "wan_local",
        "ltx2_local",
        "veo3",
        "kling_v2",
        "hailuo",  # 高写实云档
    ):
        assert reg.generic("video", name) is not None, f"video/{name} missing"
    for name in ("edge_tts", "vibevoice", "duix"):
        assert reg.generic("audio", name) is not None, f"audio/{name} missing"
    # 首尾帧关键帧(2026-07-13):此前 category="image_to_video" 从未注册过任何 provider,
    # oprim.first_last_frame_transition 100% 保证撞 FrameTransitionProviderNotFoundError。
    assert reg.generic("image_to_video", "wan22_kf2v_maas") is not None, (
        "image_to_video/wan22_kf2v_maas missing"
    )
    assert reg.llm("default") is not None
    assert reg.llm("local") is not None


def test_llm_default_is_local_qwen():
    """item 8:DashScope 已欠费,默认 LLM 应为本地 qwen(除非显式 dashscope)。"""
    assert ProviderRegistry.get().llm("default") is lqa.local_qwen_adapter


def test_vibevoice_toplevel_exports_patched():
    """vibevoice==0.0.1 空 __init__ 补丁:裸 import 两个类应可用。"""
    from vibevoice import (
        VibeVoiceForConditionalGenerationInference,
        VibeVoiceProcessor,
    )

    assert VibeVoiceForConditionalGenerationInference is not None
    assert VibeVoiceProcessor is not None


# [test_wan_cloud_invoke_filters_unsupported_args_and_fixes_model 已随 B1 迁 oprim v3.11.0:
#  wan_cloud 默认值/参数过滤在上游修复,hevi 已删 _patched_wan_invoke 猴补丁;此契约由
#  oprim 自测,hevi 不再测。]


# [test_edge_tts_voice_selection 已随 A1 迁 oprim v3.11.0:_voice_for 是 oprim 内部,
#  由 oprim 自测,hevi 不再测上游内部。hevi 侧只保留 registration 契约测试。]


def test_local_qwen_retries_transient_500(monkeypatch):
    """local_qwen:ollama 冷加载/卸载竞争的瞬时 500 应重试后成功。"""
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)  # 免等待

    calls = {"n": 0}

    class _Resp:
        def __init__(self, status, payload=None):
            self.status_code = status
            self._payload = payload or {}
            self.request = None

        def raise_for_status(self):
            if self.status_code >= 400:
                import httpx

                raise httpx.HTTPStatusError("err", request=None, response=self)

        def json(self):
            return self._payload

    good = {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}], "usage": {}}

    def fake_post(url, *a, **k):
        # chat 端点:前一次 500,后一次 200;unload 端点:总 200。
        if "chat/completions" in url:
            calls["n"] += 1
            return _Resp(500) if calls["n"] == 1 else _Resp(200, good)
        return _Resp(200, {})

    monkeypatch.setattr(lqa.httpx, "post", fake_post)

    resp = lqa._call_ollama(messages=[{"role": "user", "content": "hi"}])
    assert resp["content"] == "hi"
    assert calls["n"] == 2  # 首次 500 → 重试第二次成功


def test_register_all_providers_idempotent():
    """重复注册不应抛异常(replace=True)。"""
    register_all_providers()
    register_all_providers()


# [test_fal_aspect_ratio / test_fal_providers_build_payloads 已随 A2 迁 oprim v3.11.0:
#  veo3/kling/hailuo 原语与 _aspect_ratio 是 oprim 内部,由 oprim 自测;hevi 侧只保留
#  test_all_expected_providers_registered 验证 registry 正确 wire 了 oprim 的这些原语。]
