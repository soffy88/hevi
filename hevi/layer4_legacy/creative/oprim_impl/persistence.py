"""Atomic persistence primitives for creative objects and run snapshots."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from hevi.obase.creative import CreativeObject


class StaleRevisionError(ValueError):
    """Raised when a write would silently overwrite a newer object."""


class PersistenceValidationError(ValueError):
    """Raised when the read-back object differs from the committed object."""


@dataclass(frozen=True)
class RevisionReceipt:
    asset_id: str
    previous_revision: int | None
    new_revision: int
    committed: bool
    validation: str


def _read_revision(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        value = raw.get("revision")
    except (OSError, ValueError) as exc:
        raise PersistenceValidationError(f"cannot read existing revision: {path}") from exc
    if not isinstance(value, int):
        raise PersistenceValidationError(f"existing record has no integer revision: {path}")
    return value


def persist_model[T: BaseModel](
    path: str | Path,
    model: T,
    *,
    expected_previous_revision: int | None = None,
) -> RevisionReceipt:
    """Write a model with fsync + atomic replace + read-back validation."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    previous_revision = _read_revision(destination)
    if expected_previous_revision is not None and previous_revision != expected_previous_revision:
        raise StaleRevisionError(
            f"STALE_REVISION: expected {expected_previous_revision}, current {previous_revision}"
        )

    if isinstance(model, CreativeObject):
        if previous_revision is not None and model.revision <= previous_revision:
            raise StaleRevisionError(
                f"STALE_REVISION: new {model.revision} is not newer than {previous_revision}"
            )
        new_revision = model.revision
        asset_id = str(model.object_id)
    else:
        new_revision = int(getattr(model, "revision", 0))
        asset_id = str(getattr(model, "object_id", destination.stem))

    payload = model.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        temporary = None
        try:
            directory_fd = os.open(destination.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        restored = type(model).model_validate_json(destination.read_text(encoding="utf-8"))
        if restored.model_dump(mode="json", exclude_none=True) != payload:
            raise PersistenceValidationError("read-back validation changed the persisted model")
    finally:
        if temporary is not None:
            with suppress(FileNotFoundError):
                os.unlink(temporary)

    return RevisionReceipt(
        asset_id=asset_id,
        previous_revision=previous_revision,
        new_revision=new_revision,
        committed=True,
        validation="PASS",
    )


def restore_model[T: BaseModel](path: str | Path, model_type: type[T]) -> T:
    """Restore and validate one persisted model; malformed state fails closed."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    return model_type.model_validate_json(source.read_text(encoding="utf-8"))


__all__ = [
    "PersistenceValidationError",
    "RevisionReceipt",
    "StaleRevisionError",
    "persist_model",
    "restore_model",
]
