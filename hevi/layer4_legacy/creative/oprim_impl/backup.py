"""Hash-manifest backup and restore for creative workspaces."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


class BackupError(RuntimeError):
    """Backup or restore failed closed."""


def backup_workspace(source: str | Path, destination: str | Path) -> Path:
    source_path = Path(source)
    destination_path = Path(destination)
    if not source_path.is_dir():
        raise BackupError("workspace source is not a directory")
    if destination_path.exists():
        raise BackupError("backup destination already exists")
    shutil.copytree(source_path, destination_path)
    manifest: dict[str, str] = {}
    for path in destination_path.rglob("*"):
        if path.is_file():
            manifest[str(path.relative_to(destination_path))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    (destination_path / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return destination_path


def restore_workspace(backup: str | Path, destination: str | Path) -> None:
    backup_path = Path(backup)
    manifest_path = backup_path / "manifest.json"
    if not manifest_path.is_file():
        raise BackupError("backup manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for relative, expected in manifest.items():
        source = backup_path / relative
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise BackupError(f"backup hash mismatch: {relative}")
    destination_path = Path(destination)
    if destination_path.exists():
        raise BackupError("restore destination already exists")
    shutil.copytree(backup_path, destination_path, ignore=shutil.ignore_patterns("manifest.json"))


__all__ = ["BackupError", "backup_workspace", "restore_workspace"]
