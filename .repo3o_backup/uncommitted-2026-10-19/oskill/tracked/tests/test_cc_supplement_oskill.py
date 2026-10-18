"""Tests for CC supplement oskill elements (K-NEW1: install_plugin)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_registry(
    plugins: dict | None = None,
    command_names: set | None = None,
    skill_names: set | None = None,
) -> Any:
    class Reg:
        pass

    r = Reg()
    r.plugins = plugins or {}
    r.command_names = command_names or set()
    r.skill_names = skill_names or set()
    return r


def _write_plugin(tmp_path: Path, data: dict) -> Path:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / "plugin.json").write_text(json.dumps(data))
    return plugin_dir


# ── K-NEW1 install_plugin ─────────────────────────────────────────────────────


class TestInstallPlugin:
    @pytest.mark.asyncio
    async def test_valid_plugin_returns_spec(self, tmp_path: Path) -> None:
        from oskill.install_plugin import install_plugin

        plugin_dir = _write_plugin(tmp_path, {"name": "my-plugin", "version": "1.0.0"})
        spec = await install_plugin(plugin_dir, registry=_make_registry())
        assert spec.name == "my-plugin"
        assert spec.version == "1.0.0"
        assert spec.is_valid

    @pytest.mark.asyncio
    async def test_version_conflict_error(self, tmp_path: Path) -> None:
        from oprim._cc_types import PluginManifest, PluginSpec

        from oskill.install_plugin import install_plugin

        plugin_dir = _write_plugin(tmp_path, {"name": "p", "version": "1.0"})
        existing_manifest = PluginManifest(name="p", version="0.9")
        existing_spec = PluginSpec(
            name="p", version="0.9", manifest=existing_manifest, source_path=plugin_dir
        )
        registry = _make_registry(plugins={"p": existing_spec})
        spec = await install_plugin(plugin_dir, registry=registry)
        assert not spec.is_valid
        assert any("p" in e for e in spec.validation_errors)

    @pytest.mark.asyncio
    async def test_command_name_conflict_error(self, tmp_path: Path) -> None:
        from oskill.install_plugin import install_plugin

        plugin_dir = _write_plugin(
            tmp_path,
            {
                "name": "p",
                "version": "1.0",
                "commands": [{"name": "deploy"}],
            },
        )
        spec = await install_plugin(plugin_dir, registry=_make_registry(command_names={"deploy"}))
        assert not spec.is_valid
        assert any("deploy" in e for e in spec.validation_errors)

    @pytest.mark.asyncio
    async def test_skill_name_conflict_error(self, tmp_path: Path) -> None:
        from oskill.install_plugin import install_plugin

        plugin_dir = _write_plugin(
            tmp_path,
            {
                "name": "p",
                "version": "1.0",
                "skills": [{"name": "my-skill"}],
            },
        )
        spec = await install_plugin(plugin_dir, registry=_make_registry(skill_names={"my-skill"}))
        assert not spec.is_valid
        assert any("my-skill" in e for e in spec.validation_errors)

    @pytest.mark.asyncio
    async def test_invalid_manifest_raises_value_error(self, tmp_path: Path) -> None:
        from oskill.install_plugin import install_plugin

        plugin_dir = tmp_path / "plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text("{not valid json")
        with pytest.raises(ValueError):
            await install_plugin(plugin_dir, registry=_make_registry())

    @pytest.mark.asyncio
    async def test_source_not_exists_raises(self, tmp_path: Path) -> None:
        from oskill.install_plugin import install_plugin

        with pytest.raises(FileNotFoundError):
            await install_plugin(tmp_path / "nope", registry=_make_registry())

    @pytest.mark.asyncio
    async def test_does_not_modify_registry(self, tmp_path: Path) -> None:
        from oskill.install_plugin import install_plugin

        plugin_dir = _write_plugin(tmp_path, {"name": "p", "version": "1.0"})
        registry = _make_registry()
        original_plugins = dict(registry.plugins)
        await install_plugin(plugin_dir, registry=registry)
        assert registry.plugins == original_plugins

    @pytest.mark.asyncio
    async def test_returns_plugin_spec_type(self, tmp_path: Path) -> None:
        from oprim._cc_types import PluginSpec

        from oskill.install_plugin import install_plugin

        plugin_dir = _write_plugin(tmp_path, {"name": "p", "version": "1.0"})
        spec = await install_plugin(plugin_dir, registry=_make_registry())
        assert isinstance(spec, PluginSpec)

    @pytest.mark.asyncio
    async def test_manifest_fields_in_spec(self, tmp_path: Path) -> None:
        from oskill.install_plugin import install_plugin

        plugin_dir = _write_plugin(
            tmp_path,
            {
                "name": "rich-plugin",
                "version": "2.1.0",
                "description": "A rich plugin",
                "skills": [{"name": "s1"}],
            },
        )
        spec = await install_plugin(plugin_dir, registry=_make_registry())
        assert spec.manifest.description == "A rich plugin"
        assert len(spec.manifest.skills) == 1

    @pytest.mark.asyncio
    async def test_no_conflicts_spec_is_valid(self, tmp_path: Path) -> None:
        from oskill.install_plugin import install_plugin

        plugin_dir = _write_plugin(
            tmp_path,
            {
                "name": "new-plugin",
                "version": "1.0",
                "skills": [{"name": "skill-a"}],
                "commands": [{"name": "cmd-a"}],
            },
        )
        registry = _make_registry(
            plugins={"other": object()},
            skill_names={"other-skill"},
            command_names={"other-cmd"},
        )
        spec = await install_plugin(plugin_dir, registry=registry)
        assert spec.is_valid
