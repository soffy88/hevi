"""常用资产包:名人音色目录 / 拉取 / 登记。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from hevi.studio.assets import list_assets, reset_assets
from hevi.studio.packs import pull_pack
from hevi.studio.tools import invoke_tool
from hevi.studio.voices import find_voice, list_voices, resolve_voice


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_assets()
    yield
    reset_assets()


def test_catalog_lists_chinese_celebs() -> None:
    voices = list_voices(language="zh")
    names = {item.display for item in voices}
    assert "杨幂" in names
    assert "赵丽颖" in names
    assert find_voice("Yang Mi") is not None
    assert find_voice("yang-mi") is not None


def _write_pack_zip(path: Path) -> Path:
    audio = b"RIFF....WAVEfake"
    index = {
        "Chinese": {
            "files": [
                {
                    "audio_file": "Yang Mi.wav",
                    "image_file": "Yang Mi.jpg",
                    "display_name": "杨幂",
                    "transcript": "大家好，我是杨幂。",
                }
            ]
        }
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Chinese/Yang Mi.wav", audio)
        archive.writestr("Chinese/Yang Mi.jpg", b"jpeg")
        archive.writestr("celebrities30s.json5", json.dumps(index, ensure_ascii=False))
    return path


def test_pull_pack_extracts_and_binds(tmp_path: Path) -> None:
    zip_src = _write_pack_zip(tmp_path / "src.zip")

    def fetch(_repo: str, _name: str, dest: Path) -> Path:
        dest.write_bytes(zip_src.read_bytes())
        return dest

    result = pull_pack("celebrities30s", root=tmp_path, fetch_fn=fetch)
    assert result.pulled == 1
    yang = find_voice("杨幂", root=tmp_path)
    assert yang is not None and yang.local
    assert yang.transcript == "大家好，我是杨幂。"
    resolved = resolve_voice("yang-mi", root=tmp_path)
    assert Path(resolved.audio_path).exists()
    voices = list_assets(kind="voice")
    assert any(item.label == "杨幂" for item in voices)


@pytest.mark.asyncio
async def test_voice_tools_list_and_resolve(tmp_path: Path) -> None:
    listed = await invoke_tool("voice.list", {"language": "zh"})
    assert listed.status == "ok"
    assert listed.payload["count"] >= 5
    missing = await invoke_tool(
        "voice.resolve",
        {"name": "杨幂", "require_local": True, "root": str(tmp_path / "empty")},
    )
    assert missing.status == "failed"

    def fetch(_repo: str, _name: str, dest: Path) -> Path:
        _write_pack_zip(dest)
        return dest

    pulled = await invoke_tool(
        "asset.pull",
        {"pack": "celebrities30s", "root": str(tmp_path), "fetch_fn": fetch},
    )
    assert pulled.status == "ok"
    assert pulled.payload["pulled"] == 1
    found = await invoke_tool(
        "voice.resolve",
        {"name": "杨幂", "root": str(tmp_path)},
    )
    assert found.status == "ok"
    assert found.payload["voice"]["local"] is True
