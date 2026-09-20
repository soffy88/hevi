from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import hevi.explainer.render as render


@pytest.mark.asyncio
async def test_remotion_render_reports_missing_remotion_root(monkeypatch, tmp_path: Path):
    """Test that missing Remotion project root raises RenderError."""
    missing_dir = tmp_path / "hevi-remotion"
    monkeypatch.setattr(render, "_HEVI_REMOTION_DIR", missing_dir)

    with pytest.raises(render.RenderError, match="Remotion 项目目录不存在"):
        await render._run_remotion_render("Explainer-Portrait", tmp_path / "out.mp4")


@pytest.mark.asyncio
async def test_remotion_render_reports_render_failure(monkeypatch, tmp_path: Path):
    """Test that Remotion render failure raises RenderError."""
    remotion_dir = tmp_path / "hevi-remotion"
    remotion_dir.mkdir()
    (remotion_dir / "package.json").write_text("{}")
    (remotion_dir / "src" / "data").mkdir(parents=True)
    (remotion_dir / "src" / "data" / "run_manifest.json").write_text("[]")

    monkeypatch.setattr(render, "_HEVI_REMOTION_DIR", remotion_dir)

    # Mock oprim primitive where it's used in the render module
    with patch("hevi.explainer.render.remotion_render_component", new_callable=AsyncMock) as mock_render:
        mock_render.side_effect = Exception("Remotion CLI failed")

        with pytest.raises(render.RenderError, match="remotion render"):
            await render._run_remotion_render("Explainer-Portrait", tmp_path / "out.mp4")


@pytest.mark.asyncio
async def test_remotion_render_resolves_output_outside_remotion_cwd(monkeypatch, tmp_path: Path):
    """Test that output path is resolved to absolute before render."""
    remotion_dir = tmp_path / "hevi-remotion"
    remotion_dir.mkdir()
    (remotion_dir / "package.json").write_text("{}")
    (remotion_dir / "src" / "data").mkdir(parents=True)
    (remotion_dir / "src" / "data" / "run_manifest.json").write_text("[]")

    monkeypatch.setattr(render, "_HEVI_REMOTION_DIR", remotion_dir)

    captured: dict[str, object] = {}

    async def mock_remotion_render(**kwargs):
        captured["kwargs"] = kwargs
        # Create dummy output
        output_path = kwargs["output_path"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("dummy")

    with patch("hevi.explainer.render.remotion_render_component", new=mock_remotion_render):
        await render._run_remotion_render("Explainer-Portrait", tmp_path / "output" / "portrait.mp4")

    assert "output_path" in captured["kwargs"]
    assert captured["kwargs"]["output_path"].is_absolute()
    assert captured["kwargs"]["remotion_root"] == remotion_dir
    assert captured["kwargs"]["component_name"] == "Explainer-Portrait"