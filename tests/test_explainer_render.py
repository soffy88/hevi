from __future__ import annotations

from pathlib import Path

import pytest

import hevi.explainer.render as render


@pytest.mark.asyncio
async def test_remotion_render_reports_missing_runtime(monkeypatch, tmp_path: Path):
    missing_dir = tmp_path / "hevi-remotion"
    monkeypatch.setattr(render, "_HEVI_REMOTION_DIR", missing_dir)
    monkeypatch.setattr(render, "_REMOTION_BIN", missing_dir / "node_modules" / ".bin" / "remotion")

    with pytest.raises(render.RenderError, match="Remotion 项目目录不存在"):
        await render._run_remotion_render("Explainer-Portrait", tmp_path / "out.mp4")


@pytest.mark.asyncio
async def test_remotion_render_reports_missing_cli(monkeypatch, tmp_path: Path):
    remotion_dir = tmp_path / "hevi-remotion"
    remotion_dir.mkdir()
    monkeypatch.setattr(render, "_HEVI_REMOTION_DIR", remotion_dir)
    monkeypatch.setattr(
        render, "_REMOTION_BIN", remotion_dir / "node_modules" / ".bin" / "remotion"
    )

    with pytest.raises(render.RenderError, match="Remotion CLI 不可用"):
        await render._run_remotion_render("Explainer-Portrait", tmp_path / "out.mp4")


@pytest.mark.asyncio
async def test_remotion_render_resolves_output_outside_remotion_cwd(monkeypatch, tmp_path: Path):
    remotion_dir = tmp_path / "hevi-remotion"
    remotion_dir.mkdir()
    remotion_bin = remotion_dir / "node_modules" / ".bin" / "remotion"
    remotion_bin.parent.mkdir(parents=True)
    remotion_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    output_root = tmp_path / "output"
    monkeypatch.setattr(render, "_HEVI_REMOTION_DIR", remotion_dir)
    monkeypatch.setattr(render, "_REMOTION_BIN", remotion_bin)

    captured: dict[str, object] = {}

    class _Process:
        returncode = 0

        async def communicate(self):
            return b"", None

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _Process()

    monkeypatch.setattr(render.asyncio, "create_subprocess_exec", fake_exec)
    await render._run_remotion_render("Explainer-Portrait", output_root / "portrait.mp4")

    args = captured["args"]
    assert isinstance(args, tuple)
    assert Path(args[3]).is_absolute()
    assert captured["kwargs"]["cwd"] == str(remotion_dir)
