"""ai_drama 配音路径解析回归（S30E）。

部署把 Piper 挂载在容器内的 ``/opt/piper``，但 ``hevi/ai_drama/voice.py`` 早期只认
宿主机路径 ``/data/soffy/projects/hevi-zero/...``。API/worker 容器里这两个路径不存在，
真人短剧/漫剧（ai_drama）在 voice 阶段直接报 "piper 音色缺失"，整条线出不了片。

这里钉住：容器优先的候选顺序 + 环境变量仍然优先。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture()
def voice_module(monkeypatch):
    from hevi.ai_drama import voice

    return importlib.reload(voice)


def test_container_paths_are_candidates(voice_module) -> None:
    """容器挂载点必须在候选里，否则 API 容器永远找不到 Piper。"""
    assert "/opt/piper/bin/piper" in voice_module._PIPER_CANDIDATES
    assert "/opt/piper/voices" in voice_module._VOICE_DIR_CANDIDATES


def test_env_override_wins(voice_module, monkeypatch, tmp_path) -> None:
    """显式环境变量仍然优先（部署可覆盖默认挂载点）。"""
    bin_path = tmp_path / "piper"
    bin_path.write_text("#!/bin/sh\n")
    voices = tmp_path / "voices"
    voices.mkdir()
    monkeypatch.setenv("HEVI_PIPER_BIN", str(bin_path))
    monkeypatch.setenv("HEVI_PIPER_VOICES_DIR", str(voices))

    importlib.reload(voice_module)
    assert str(bin_path) == voice_module.PIPER
    assert voices == voice_module.VOICE_DIR
    assert voice_module.PIPER_VOICES["zh_CN-huayan-medium.onnx"] == (
        voices / "zh_CN-huayan-medium.onnx"
    )


def test_missing_voice_raises_clear_error(voice_module, monkeypatch, tmp_path) -> None:
    """音色文件缺失时给出可读错误，而不是静默产出空音频。"""
    empty = tmp_path / "voices"
    empty.mkdir()
    monkeypatch.setenv("HEVI_PIPER_BIN", str(tmp_path / "piper"))
    monkeypatch.setenv("HEVI_PIPER_VOICES_DIR", str(empty))
    importlib.reload(voice_module)

    with pytest.raises(RuntimeError, match="piper 音色缺失"):
        voice_module.synthesize_line(
            "测试",
            {"piper_voice": "zh_CN-huayan-medium.onnx"},
            tmp_path / "out",
        )


def test_module_import_is_side_effect_free(voice_module) -> None:
    """导入不得因为路径缺失而抛异常（导入期失败会让整条产线无法加载）。"""
    assert isinstance(voice_module.PIPER, str)
    assert isinstance(voice_module.VOICE_DIR, Path)
