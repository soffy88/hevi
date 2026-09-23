"""Provider-neutral GPU compute lifecycle for on-demand production stages.

The adapters are intentionally dependency-injected.  This module does not
pretend that the current host has a working GPU, and it does not contain a
vendor-specific provisioning implementation.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GpuAvailability:
    available: bool
    provider: str
    reason: str = ""
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class GpuCostEstimate:
    hourly_rate_usd: float
    estimated_minutes: float

    @property
    def total_usd(self) -> float:
        return self.hourly_rate_usd * self.estimated_minutes / 60.0


class GpuComputeProvider(ABC):
    name: str = "gpu"

    @abstractmethod
    def availability(self) -> GpuAvailability: ...

    @abstractmethod
    def capabilities(self) -> list[str]: ...

    @abstractmethod
    def estimate_cost(self, job: dict[str, Any]) -> GpuCostEstimate: ...

    @abstractmethod
    async def acquire(self, job: dict[str, Any]) -> Any: ...

    @abstractmethod
    async def health_check(self, handle: Any) -> bool: ...

    @abstractmethod
    async def execute(self, handle: Any, job: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    async def collect_artifacts(self, handle: Any, result: dict[str, Any]) -> list[str]: ...

    @abstractmethod
    async def release(self, handle: Any) -> None: ...


class LocalGpuProvider(GpuComputeProvider):
    name = "local_gpu"

    def availability(self) -> GpuAvailability:
        try:
            import torch

            available = bool(torch.cuda.is_available())
            return GpuAvailability(
                available, self.name, "" if available else "HOST_GPU_UNAVAILABLE"
            )
        except Exception as exc:
            return GpuAvailability(False, self.name, f"CUDA_PROBE_FAILED:{type(exc).__name__}")

    def capabilities(self) -> list[str]:
        return ["local_cuda", "gpu_stage_execution"] if self.availability().available else []

    def estimate_cost(self, job: dict[str, Any]) -> GpuCostEstimate:
        return GpuCostEstimate(0.0, float(job.get("estimated_minutes") or 0.0))

    async def acquire(self, job: dict[str, Any]) -> Any:
        if not self.availability().available:
            raise RuntimeError("HOST_GPU_UNAVAILABLE")
        return {"provider": self.name, "job_id": job.get("job_id")}

    async def health_check(self, handle: Any) -> bool:
        return self.availability().available

    async def execute(self, handle: Any, job: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("LOCAL_GPU_EXECUTOR_NOT_BOUND")

    async def collect_artifacts(self, handle: Any, result: dict[str, Any]) -> list[str]:
        return [str(item) for item in result.get("artifacts", [])]

    async def release(self, handle: Any) -> None:
        return None


class _UnavailableRemoteProvider(GpuComputeProvider):
    def __init__(self, name: str, reason: str = "ADAPTER_NOT_CONFIGURED") -> None:
        self.name = name
        self.reason = reason

    def availability(self) -> GpuAvailability:
        return GpuAvailability(False, self.name, self.reason)

    def capabilities(self) -> list[str]:
        return []

    def estimate_cost(self, job: dict[str, Any]) -> GpuCostEstimate:
        return GpuCostEstimate(
            float(job.get("hourly_rate_usd") or 0.0), float(job.get("estimated_minutes") or 0.0)
        )

    async def acquire(self, job: dict[str, Any]) -> Any:
        raise RuntimeError(self.reason)

    async def health_check(self, handle: Any) -> bool:
        return False

    async def execute(self, handle: Any, job: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError(self.reason)

    async def collect_artifacts(self, handle: Any, result: dict[str, Any]) -> list[str]:
        return []

    async def release(self, handle: Any) -> None:
        return None


class RemoteGpuProvider(_UnavailableRemoteProvider):
    def __init__(self) -> None:
        super().__init__("remote_gpu")


class HourlyGpuProvider(_UnavailableRemoteProvider):
    def __init__(self) -> None:
        super().__init__("hourly_gpu")


class GpuLease(AbstractAsyncContextManager["GpuLease"]):
    def __init__(self, provider: GpuComputeProvider, job: dict[str, Any]) -> None:
        self.provider = provider
        self.job = job
        self.handle: Any = None
        self.result: dict[str, Any] | None = None
        self.artifacts: list[str] = []

    async def __aenter__(self) -> GpuLease:
        self.handle = await self.provider.acquire(self.job)
        if not await self.provider.health_check(self.handle):
            await self.provider.release(self.handle)
            self.handle = None
            raise RuntimeError("GPU_HEALTH_CHECK_FAILED")
        return self

    async def run(self) -> dict[str, Any]:
        if self.handle is None:
            raise RuntimeError("GPU_NOT_ACQUIRED")
        self.result = await self.provider.execute(self.handle, self.job)
        self.artifacts = await self.provider.collect_artifacts(self.handle, self.result)
        return self.result

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.handle is not None:
            await self.provider.release(self.handle)
            self.handle = None


@dataclass
class GpuWorkQueue:
    jobs: list[dict[str, Any]] = field(default_factory=list)

    def submit(self, job: dict[str, Any]) -> None:
        self.jobs.append(dict(job))

    def drain(self) -> list[dict[str, Any]]:
        batch = list(self.jobs)
        self.jobs.clear()
        return batch


class GpuResultCache:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(job: dict[str, Any]) -> str:
        payload = json.dumps(
            job, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    def path_for(self, job: dict[str, Any]) -> Path:
        return self.root / self.key(job)

    def lookup(self, job: dict[str, Any]) -> dict[str, Any] | None:
        path = self.path_for(job) / "result.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def store(self, job: dict[str, Any], result: dict[str, Any]) -> Path:
        directory = self.path_for(job)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "result.json"
        path.write_text(
            json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
        )
        return path


__all__ = [
    "GpuAvailability",
    "GpuComputeProvider",
    "GpuCostEstimate",
    "GpuLease",
    "GpuResultCache",
    "GpuWorkQueue",
    "HourlyGpuProvider",
    "LocalGpuProvider",
    "RemoteGpuProvider",
]
