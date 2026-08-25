"""HyperFrames 第二运行时:编译 + 无 CLI 回退出片。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from hevi.providers.hyperframes.compiler import compile_composition, render_html
from hevi.providers.hyperframes.provider import (
    HYPERFRAMES_CAPABILITY,
    hyperframes_generate,
    register_hyperframes,
)
from hevi.studio.runtime import select_runtime


def test_capability_row_is_local_and_free() -> None:
    assert HYPERFRAMES_CAPABILITY["id"] == "hyperframes"
    assert HYPERFRAMES_CAPABILITY["cost_per_sec"] == 0
    assert "motion_graphics" in HYPERFRAMES_CAPABILITY["capabilities"]


def test_register_hyperframes_binds_video_slot() -> None:
    from obase.provider_registry import ProviderRegistry

    register_hyperframes()
    bound = ProviderRegistry.get().generic("video", "hyperframes")
    assert bound is hyperframes_generate


def test_compile_emits_clip_timing() -> None:
    comp = compile_composition(
        {
            "topic": "盐税",
            "script_lines": [{"text": "帝国靠它养兵。"}, {"text": "请地由此起。"}],
        }
    )
    html = render_html(comp)
    assert 'class="clip' in html
    assert "data-start=" in html
    assert "data-duration=" in html
    assert 'data-composition-id="main"' in html
    assert "data-no-timeline" in html
    assert "盐税" in html
    assert comp.duration_s > 0


def test_write_workspace_writes_project_files(tmp_path: Path) -> None:
    from hevi.providers.hyperframes.provider import write_workspace

    comp = compile_composition({"topic": "盐税"})
    html = write_workspace(comp, tmp_path)
    assert html.is_file()
    assert (tmp_path / "hyperframes.json").is_file()
    assert (tmp_path / "DESIGN.md").is_file()


def test_runtime_selector_locks_and_intents() -> None:
    locked = select_runtime(locked="hyperframes", intent="随便")
    assert locked == {"runtime": "hyperframes", "locked": True, "reason": "recipe.lock"}
    kinetic = select_runtime(intent="做一条片头花字")
    assert kinetic["runtime"] == "hyperframes"
    math = select_runtime(intent="3b1b 公式")
    assert math["runtime"] == "manim"


@pytest.mark.asyncio
async def test_generate_fallback_writes_mp4(tmp_path: Path) -> None:
    dest = tmp_path / "promo.mp4"
    with patch(
        "hevi.providers.hyperframes.provider.detect_hyperframes_bin",
        return_value=None,
    ):
        produced = await hyperframes_generate(
            prompt={"topic": "盐税", "script_lines": [{"text": "帝国靠它。"}]},
            output_path=dest,
            width=320,
            height=180,
            fps=8,
        )
    assert produced == dest
    assert dest.exists() and dest.stat().st_size > 0


@pytest.mark.asyncio
async def test_generate_cli_path(tmp_path: Path, monkeypatch) -> None:
    """检测到 CLI 时走 hyperframes render,不出意外不落回退。"""
    dest = tmp_path / "promo.mp4"
    fake_cli = tmp_path / "fake-hyperframes"
    fake_cli.write_text("#!/bin/sh\necho fake\n", encoding="utf-8")
    fake_cli.chmod(0o755)
    calls: dict = {}

    async def fake_run_cli(cmd, *, cwd, timeout_s):
        calls["cmd"] = cmd
        calls["cwd"] = str(cwd)
        calls["timeout_s"] = timeout_s
        dest.write_bytes(b"FAKE-MP4")
        return 0, "ok"

    with patch(
        "hevi.providers.hyperframes.provider.detect_hyperframes_bin",
        return_value=str(fake_cli),
    ), patch(
        "hevi.providers.hyperframes.provider._run_cli",
        new=fake_run_cli,
    ):
        produced = await hyperframes_generate(
            prompt={"topic": "盐税", "script_lines": [{"text": "帝国靠它。"}]},
            output_path=dest,
            width=320,
            height=180,
            fps=8,
        )
    assert produced == dest
    assert dest.read_bytes() == b"FAKE-MP4"
    assert calls["cmd"][0] == str(fake_cli)
    assert calls["cmd"][1] == "render"
    assert "-o" in calls["cmd"]
    assert "-f" in calls["cmd"]
    assert calls["cmd"][calls["cmd"].index("-f") + 1] == "8"
    assert (tmp_path / ".promo_hf" / "hyperframes.json").is_file()


@pytest.mark.asyncio
async def test_generate_cli_failure_falls_back(tmp_path: Path, monkeypatch) -> None:
    """CLI 渲染失败自动回退 ffmpeg,仍出片。"""
    dest = tmp_path / "promo.mp4"

    async def fail_run_cli(cmd, *, cwd, timeout_s):
        raise RuntimeError("hyperframes render boom")

    with patch(
        "hevi.providers.hyperframes.provider.detect_hyperframes_bin",
        return_value="/nonexistent/hyperframes",
    ), patch(
        "hevi.providers.hyperframes.provider._run_cli",
        new=fail_run_cli,
    ):
        produced = await hyperframes_generate(
            prompt={"topic": "盐税", "script_lines": [{"text": "帝国靠它。"}]},
            output_path=dest,
            width=320,
            height=180,
            fps=8,
        )
    assert produced == dest
    assert dest.exists() and dest.stat().st_size > 0
