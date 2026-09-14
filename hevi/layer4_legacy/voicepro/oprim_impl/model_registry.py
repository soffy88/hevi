"""Local speech model registry primitives.

The registry is deliberately metadata-only.  It never downloads weights or
claims that an engine is ready merely because a catalog entry exists.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MODEL_STATES = ("catalog", "registered", "ready", "missing", "error")


@dataclass(frozen=True)
class ModelRecord:
    model_id: str
    name: str
    kind: str
    engine: str
    state: str = "catalog"
    path: str = ""
    device: str = "auto"
    languages: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    source: str = "hevi"
    error: str | None = None
    execution_ready: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["languages"] = list(self.languages)
        body["capabilities"] = list(self.capabilities)
        body["ready"] = self.state == "ready"
        body["execution_ready"] = (
            self.execution_ready if self.execution_ready is not None else body["ready"]
        )
        return body


def inspect_path(path: str | Path) -> tuple[str, str | None]:
    """Return a truthful registry state for a local model path."""

    if not str(path).strip():
        return "missing", "未登记本地模型路径"
    candidate = Path(path).expanduser()
    if not candidate.exists():
        return "missing", f"模型路径不存在: {candidate}"
    if not (candidate.is_file() or candidate.is_dir()):
        return "error", f"模型路径不可读: {candidate}"
    return "ready", None


def make_record(
    *,
    model_id: str,
    name: str,
    kind: str,
    engine: str,
    state: str = "catalog",
    path: str = "",
    device: str = "auto",
    languages: tuple[str, ...] = (),
    capabilities: tuple[str, ...] = (),
    source: str = "hevi",
    error: str | None = None,
    execution_ready: bool | None = None,
) -> ModelRecord:
    if state not in MODEL_STATES:
        raise ValueError(f"unknown model state: {state}")
    return ModelRecord(
        model_id=model_id,
        name=name,
        kind=kind,
        engine=engine,
        state=state,
        path=path,
        device=device,
        languages=languages,
        capabilities=capabilities,
        source=source,
        error=error,
        execution_ready=execution_ready,
    )


__all__ = ["MODEL_STATES", "ModelRecord", "inspect_path", "make_record"]
