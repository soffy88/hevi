"""NIM 研究 LLM 的 key 选择与注册逻辑测试(不发起真实网络请求)。"""

from __future__ import annotations

import json

import pytest

from hevi.providers import nim_caller
from hevi.providers.nim_caller import _nim_keys, register_nim_llm


def _write_pool(tmp_path, slots: dict[str, str]) -> None:
    f = tmp_path / ".pipeline_keys.json"
    f.write_text(json.dumps(slots), encoding="utf-8")
    return f


@pytest.fixture
def pool_file(tmp_path, monkeypatch):
    f = _write_pool(
        tmp_path,
        {
            "econ": "nvapi-AAA",
            "math_en": "nvapi-BBB",
            "econ_zh": "nvapi-CCC",
            "learning": "nvapi-AAA",  # 与 econ 重复,应被去重
        },
    )
    monkeypatch.setenv("HEVI_PIPELINE_KEYS", str(f))
    # 阻断真实 stratum 密钥池,保证测试隔离
    monkeypatch.setattr(nim_caller, "_PIPELINE_KEYS_CANDIDATES", ())
    for env in ("HEVI_NIM_KEYS", "HEVI_NIM_KEY_NAMES", "NVIDIA_NIM_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    return f


def test_default_picks_first_two_distinct(pool_file):
    keys = _nim_keys()
    assert keys == ["nvapi-AAA", "nvapi-BBB"]  # learning 的 AAA 与 econ 重复,去重


def test_key_names_select_slots(pool_file, monkeypatch):
    monkeypatch.setenv("HEVI_NIM_KEY_NAMES", "math_en,learning")
    assert _nim_keys() == ["nvapi-BBB", "nvapi-AAA"]


def test_key_names_missing_slot_falls_back_to_env(pool_file, monkeypatch):
    monkeypatch.setenv("HEVI_NIM_KEY_NAMES", "nonexistent")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nvapi-ENV")
    assert _nim_keys() == ["nvapi-AAA", "nvapi-BBB", "nvapi-ENV"]


def test_literal_keys_override_pool(pool_file, monkeypatch):
    monkeypatch.setenv("HEVI_NIM_KEYS", "nvapi-X1, nvapi-X2")
    assert _nim_keys() == ["nvapi-X1", "nvapi-X2"]


def test_no_keys_returns_empty(pool_file, monkeypatch):
    pool_file.unlink()
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    assert _nim_keys() == []


def test_register_without_keys_is_noop(pool_file, monkeypatch):
    """没有 key 时注册应静默跳过,不抛异常(research 回落 default)。"""
    pool_file.unlink()
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    register_nim_llm()  # 不应抛异常


def test_register_registers_nim_provider(monkeypatch):
    from obase.provider_registry import ProviderRegistry

    # 不依赖真实密钥池:字面 key + 阻断真实文件
    monkeypatch.setenv("HEVI_NIM_KEYS", "nvapi-X1,nvapi-X2")
    monkeypatch.delenv("HEVI_NIM_KEY_NAMES", raising=False)
    monkeypatch.setattr(nim_caller, "_PIPELINE_KEYS_CANDIDATES", ())
    register_nim_llm()
    llm = ProviderRegistry.get().llm("nim")
    assert callable(llm)
    # 模型名默认 nemotron-super-49b(实测速度/质量平衡)
    assert nim_caller.DEFAULT_NIM_MODEL == "nvidia/llama-3.3-nemotron-super-49b-v1.5"
