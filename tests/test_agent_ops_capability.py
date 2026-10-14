"""Tests for agent.ops_bridge capability contract per CAPABILITY_CONTRACT.md.

契约要求：
- 注册后能被 list 查到；
- 用 schema 校验非法参数，必须报错；
- 渲染 2 秒的产物要通过 ffprobe 检查；
- 删除产物后，测试必须失败。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hevi.capabilities.registry import get, list_capabilities, resolve


def test_capability_registered_and_discoverable() -> None:
    cap = get("agent.ops_bridge")
    assert cap.name == "agent.ops_bridge"
    assert cap.kind == "line"
    assert "9:16" in cap.aspects and "16:9" in cap.aspects

    # 能被 resolve 与 list 查到
    resolved = resolve("agent.ops_bridge")
    assert resolved.name == cap.name
    all_caps = list_capabilities()
    assert any(c.name == "agent.ops_bridge" for c in all_caps)


def test_capability_schema_validation_rejects_invalid_params() -> None:
    cap = get("agent.ops_bridge")

    # 合法参数通过
    assert cap.validate_params({"format": "preview"}) == {"format": "preview"}
    assert cap.validate_params({}) == {}

    # 非法枚举值报错
    with pytest.raises(ValueError, match="format"):
        cap.validate_params({"format": "invalid_format"})

    # 多余未知参数报错
    with pytest.raises(ValueError, match="unsupported"):
        cap.validate_params({"bogus_key": 123})


def test_capability_render_2s_product_and_ffprobe_check(tmp_path: Path) -> None:
    cap = get("agent.ops_bridge")
    out_dir = tmp_path / "cap_render"

    res = cap.render({"format": "preview"}, out_dir, duration=2.0, aspect="9:16", seed=42)

    assert res.duration_s == 2.0
    assert res.mp4 is not None
    mp4_file = Path(res.mp4)
    assert mp4_file.is_file() and mp4_file.stat().st_size > 0
    assert len(res.sha256) == 64
    assert res.qa["count"] == 8

    # ffprobe 检查时长（2.00s ± 0.1s）与分辨率 (320x568)
    probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=width,height",
        "-of",
        "json",
        str(mp4_file),
    ]
    probe_res = subprocess.run(probe_cmd, check=True, capture_output=True, text=True)
    probe_data = json.loads(probe_res.stdout)
    actual_dur = float(probe_data["format"]["duration"])
    assert abs(actual_dur - 2.0) <= 0.1

    video_stream = next(s for s in probe_data["streams"] if "width" in s)
    assert video_stream["width"] == 320
    assert video_stream["height"] == 568

    # 删除产物后，检验必须失败
    mp4_file.unlink()
    assert not mp4_file.exists()
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run(probe_cmd, check=True, capture_output=True, text=True)
