"""K-NEW1 install_plugin — parse and validate a plugin bundle (no disk write).

Composes oprim:
    - load_plugin_raw
    - parse_plugin_manifest

Stateless: reads registry for conflict checking only. Does NOT write disk or
modify the registry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from oprim._cc_types import PluginManifest, PluginSpec
from oprim._load_plugin_raw import load_plugin_raw
from oprim._parse_plugin_manifest import parse_plugin_manifest


async def install_plugin(source: Path, *, registry: Any) -> PluginSpec:
    """Parse and validate a plugin bundle at *source*.

    Steps:
    1. Load raw manifest (load_plugin_raw -> IO).
    2. Parse manifest (parse_plugin_manifest -> pure compute).
    3. Validate:
        - Name conflict with registry.plugins
        - Command name conflicts with registry.command_names
        - Skill name conflicts with registry.skill_names

    Args:
        source: Plugin bundle directory path.
        registry: Read-only registry for conflict checking.

    Returns:
        PluginSpec with validation result (is_valid reflects no conflicts).

    Raises:
        FileNotFoundError: If source or plugin.json does not exist.
        ValueError: If manifest JSON is invalid.
    """
    raw = await load_plugin_raw(source)
    manifest: PluginManifest = parse_plugin_manifest(raw)

    errors: list[str] = []

    existing_plugins: dict[str, Any] = getattr(registry, "plugins", {})
    if manifest.name in existing_plugins:
        existing = existing_plugins[manifest.name]
        existing_version = getattr(getattr(existing, "manifest", None), "version", "?")
        errors.append(f"Plugin '{manifest.name}' already installed (version {existing_version})")

    registry_commands: set[str] = getattr(registry, "command_names", set())
    for cmd in manifest.commands:
        cmd_name = cmd.get("name", "") if isinstance(cmd, dict) else str(cmd)
        if cmd_name and cmd_name in registry_commands:
            errors.append(f"Command name conflict: '{cmd_name}' already registered")

    registry_skills: set[str] = getattr(registry, "skill_names", set())
    for skill in manifest.skills:
        skill_name = skill.get("name", "") if isinstance(skill, dict) else str(skill)
        if skill_name and skill_name in registry_skills:
            errors.append(f"Skill name conflict: '{skill_name}' already registered")

    return PluginSpec(
        name=manifest.name,
        version=manifest.version,
        manifest=manifest,
        source_path=source,
        validation_errors=errors,
    )
