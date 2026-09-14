"""Crash-safe workspace transaction primitives."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path


class WorkspaceCommitError(RuntimeError):
    """Raised when a workspace transaction cannot be finalized."""


class AtomicWorkspace:
    """Stage a complete workspace and swap it as one directory operation."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.parent.mkdir(parents=True, exist_ok=True)
        self.staging: Path | None = None

    def begin(self) -> None:
        if self.staging is not None:
            raise WorkspaceCommitError("workspace transaction already open")
        self.staging = Path(tempfile.mkdtemp(prefix=f".{self.root.name}.", dir=self.root.parent))

    def stage_json(self, name: str, value: object) -> None:
        if self.staging is None:
            raise WorkspaceCommitError("workspace transaction is not open")
        target = self.staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def commit(self) -> None:
        if self.staging is None:
            raise WorkspaceCommitError("workspace transaction is not open")
        for path in self.staging.rglob("*"):
            if path.is_file():
                with path.open("rb") as handle:
                    os.fsync(handle.fileno())
        backup: Path | None = None
        try:
            if self.root.exists():
                backup = self.root.with_name(f".{self.root.name}.backup")
                if backup.exists():
                    shutil.rmtree(backup)
                os.replace(self.root, backup)
            os.replace(self.staging, self.root)
            self.staging = None
            if backup is not None:
                shutil.rmtree(backup)
        except OSError as exc:
            if self.staging is not None:
                self.rollback()
            if backup is not None and backup.exists() and not self.root.exists():
                os.replace(backup, self.root)
            raise WorkspaceCommitError("workspace commit failed") from exc

    def rollback(self) -> None:
        if self.staging is not None:
            shutil.rmtree(self.staging, ignore_errors=True)
            self.staging = None


__all__ = ["AtomicWorkspace", "WorkspaceCommitError"]
