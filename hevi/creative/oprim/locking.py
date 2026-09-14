"""Project write locks with explicit busy and stale recovery semantics."""

from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path


class ResourceBusy(RuntimeError):
    """Another run owns the project lock."""


@dataclass
class ProjectLock:
    path: Path
    owner_id: str
    _fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise ResourceBusy(self._owner_from_file()) from exc
        payload = {"owner_id": self.owner_id, "pid": os.getpid()}
        os.write(self._fd, json.dumps(payload).encode("utf-8"))
        os.fsync(self._fd)

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        with suppress(FileNotFoundError):
            self.path.unlink()

    def recover_stale(self) -> bool:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError, OSError, ValueError:
            return False
        pid = payload.get("pid")
        if not isinstance(pid, int) or Path(f"/proc/{pid}").exists():
            return False
        self.path.unlink(missing_ok=True)
        return True

    def _owner_from_file(self) -> str:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return "unknown"
        return str(payload.get("owner_id", "unknown"))


__all__ = ["ProjectLock", "ResourceBusy"]
