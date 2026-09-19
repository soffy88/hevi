"""D5-C: coordinated backup/restore for the differentiation stores.

The differentiation authorities live in separate SQLite files on one
authoritative host (topology ``single_host_durable``). A backup is taken
as a **coordinated set** under one boundary token: all files are copied in
a single call, and each copy's sha256 is recorded in one manifest. The
manifest is the consistency boundary — a restore is only valid when the
whole set is restored together, and ``verify_backup`` fails closed if any
member was mutated independently.

This is snapshot-per-database under a shared boundary token, not a
distributed transaction across databases; that distinction is explicit
and is why readers must consume the set, never a single file.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from hevi.creative.layer4.store_topology import TOPOLOGY


class BackupError(RuntimeError):
    """Refusal with a stable machine code."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_stores(
    stores: dict[str, Path],
    dest_dir: Path,
    *,
    boundary_token: str = "",
    now: float | None = None,
) -> dict[str, Any]:
    """Back up a set of SQLite stores under one boundary token."""
    if not stores:
        raise BackupError("BACKUP_NO_STORES")
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    token = boundary_token or f"boundary-{uuid.uuid4().hex[:12]}"
    created = time.time() if now is None else now
    members: list[dict[str, Any]] = []
    for name, source in stores.items():
        source = Path(source)
        if not source.exists():
            raise BackupError(f"BACKUP_SOURCE_MISSING:{name}")
        target = dest / f"{name}.db"
        with sqlite3.connect(str(source)) as src, sqlite3.connect(str(target)) as dst:
            src.backup(dst)
        members.append(
            {
                "name": name,
                "source": str(source),
                "backup": str(target),
                "sha256": _sha256(target),
                "bytes": target.stat().st_size,
            }
        )
    manifest = {
        "boundary_token": token,
        "created_at": created,
        "topology": TOPOLOGY,
        "members": members,
    }
    manifest_path = dest / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest


def verify_backup(manifest_path: Path) -> dict[str, bool]:
    """Recompute member hashes; closed only if every member matches."""
    manifest = json.loads(Path(manifest_path).read_text())
    results: dict[str, bool] = {}
    for member in manifest.get("members", []):
        path = Path(member["backup"])
        results[str(member["name"])] = (
            path.exists() and _sha256(path) == member["sha256"]
        )
    return results


def restore_stores(
    manifest_path: Path, target_dir: Path
) -> dict[str, str]:
    """Restore the whole set together; refuses if the set is inconsistent."""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    verified = verify_backup(manifest_path)
    if not verified or not all(verified.values()):
        raise BackupError(f"BACKUP_INCONSISTENT:{verified}")
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    restored: dict[str, str] = {}
    for member in manifest.get("members", []):
        source = Path(member["backup"])
        destination = target / f"{member['name']}.db"
        with sqlite3.connect(str(source)) as src, sqlite3.connect(str(destination)) as dst:
            src.backup(dst)
        restored[str(member["name"])] = str(destination)
    return restored


def boundary_token(manifest_path: Path) -> str:
    manifest = json.loads(Path(manifest_path).read_text())
    return str(manifest.get("boundary_token", ""))


__all__ = [
    "BackupError",
    "backup_stores",
    "boundary_token",
    "restore_stores",
    "verify_backup",
]
