"""AVP 风格配置根:workspace + project 合并,冻结 SHA。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hevi.studio.kit import freeze_profile, verify_profile


def load_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def resolve_and_freeze(
    *,
    workspace_path: Path,
    project_path: Path | None,
    dest: Path,
) -> dict[str, Any]:
    workspace = load_mapping(workspace_path)
    project = load_mapping(project_path) if project_path else {}
    return freeze_profile({"workspace": workspace, "project": project, "dest": str(dest)})


def assert_frozen(resolved_path: Path) -> dict[str, Any]:
    result = verify_profile({"resolved_path": str(resolved_path)})
    if not result.get("passed"):
        raise RuntimeError(
            f"resolved profile SHA mismatch: {resolved_path} "
            f"expected={result.get('expected')} actual={result.get('actual')}"
        )
    return result
