"""LuxTTS 服务测试 —— 轻量克隆 TTS 适配(差距 B8)。

覆盖: 可用性探测(未安装降级)/合成缺依赖报错/CLI 路径/模块 API 路径(注入假模块)。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from hevi.audio.lux_tts_service import lux_tts_available, synth_with_luxvoice


def test_available_false_when_not_installed(monkeypatch):
    monkeypatch.setattr("hevi.audio.lux_tts_service._import_luxvoice", lambda: None)
    monkeypatch.setattr("hevi.audio.lux_tts_service.shutil.which", lambda _: None)
    assert lux_tts_available() is False


def test_synth_raises_when_not_available(tmp_path: Path):
    with patch("hevi.audio.lux_tts_service._import_luxvoice", return_value=None):
        with pytest.raises(RuntimeError, match="luxvoice not available"):
            import asyncio

            asyncio.run(
                synth_with_luxvoice("你好", tmp_path / "out.wav")
            )


def test_synth_module_api_path(tmp_path: Path):
    """注入假 luxvoice 模块, 验证模块 API 路径。"""
    calls: dict = {}

    async def fake_synth(text, output_path, reference_audio=None, speed=1.0, **kw):
        calls["text"] = text
        calls["output_path"] = output_path
        calls["ref"] = reference_audio
        Path(output_path).write_bytes(b"RIFFfake")

    mod = ModuleType("luxvoice")
    mod.synth = fake_synth

    with patch.dict(sys.modules, {"luxvoice": mod}):
        out = Path(tmp_path) / "out.wav"
        import asyncio

        result = asyncio.run(
            synth_with_luxvoice("测试文本", out, reference_audio="ref.wav", speed=1.2)
        )
    assert result == out
    assert out.exists()
    assert calls["text"] == "测试文本"
    assert calls["ref"] == "ref.wav"
    assert calls["output_path"] == str(out)


def test_synth_cli_path(tmp_path: Path):
    """注入假 CLI(luxvoice 可执行), 验证 CLI 路径。"""
    out = Path(tmp_path) / "out.wav"

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_create(*cmd, **kw):
        out.write_bytes(b"RIFFcli")
        return FakeProc()

    with (
        patch("hevi.audio.lux_tts_service._import_luxvoice", return_value=ModuleType("luxvoice")),
        patch("hevi.audio.lux_tts_service.shutil.which", return_value="/usr/bin/luxvoice"),
        patch("hevi.audio.lux_tts_service.asyncio.create_subprocess_exec", side_effect=fake_create),
    ):
        import asyncio

        result = asyncio.run(synth_with_luxvoice("hi", out))
    assert result == out
    assert out.read_bytes() == b"RIFFcli"


def test_synth_cli_failure(tmp_path: Path):
    class FakeProc:
        returncode = 1

        async def communicate(self):
            return b"", b"boom error"

    async def fake_create(*cmd, **kw):
        return FakeProc()

    with (
        patch("hevi.audio.lux_tts_service._import_luxvoice", return_value=ModuleType("luxvoice")),
        patch("hevi.audio.lux_tts_service.shutil.which", return_value="/usr/bin/luxvoice"),
        patch("hevi.audio.lux_tts_service.asyncio.create_subprocess_exec", side_effect=fake_create),
    ):
        import asyncio

        with pytest.raises(RuntimeError, match="boom error"):
            asyncio.run(synth_with_luxvoice("hi", tmp_path / "o.wav"))


def test_module_without_synth_entry(tmp_path: Path):
    mod = ModuleType("luxvoice")
    with (
        patch.dict(sys.modules, {"luxvoice": mod}),
        patch("hevi.audio.lux_tts_service.shutil.which", return_value=None),
    ):
        import asyncio

        with pytest.raises(RuntimeError, match="no synth entry"):
            asyncio.run(synth_with_luxvoice("hi", tmp_path / "o.wav"))
