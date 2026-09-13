"""Atomic analysis persistence with read-back validation."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel


def atomic_write_model(path: str | Path, model: BaseModel) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, destination)


def read_model[T: BaseModel](path: str | Path, model_type: type[T]) -> T:
    return model_type.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
