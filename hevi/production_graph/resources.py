"""Resource profiles and deterministic admission for production execution.

The profile is deliberately independent from a particular provider or worker
implementation.  It describes what the current process was actually given;
callers then derive a safe concurrency for a named execution lane.  GPU
discovery is evidence based: an unavailable or unprobeable GPU is reported as
unavailable rather than inferred from configuration.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import Field

from hevi.production_graph.domain import DomainModel
from hevi.production_graph.ids import CanonicalId, new_id

ExecutionLane = Literal["render", "provider", "io"]


class ResourceUnavailableError(RuntimeError):
    """Raised when a request cannot be admitted on the actual worker."""


class ExecutionProfile(DomainModel):
    """The resource envelope visible to one HEVI worker.

    ``cpu_quota`` is expressed in CPUs, not host CPUs.  A value of ``None``
    means the cgroup has no CPU quota.  Concurrency fields are policy caps;
    :meth:`concurrency_limit` additionally applies the measured CPU envelope.
    """

    id: CanonicalId = Field(default_factory=new_id)
    cpu_quota: float | None = Field(default=None, ge=0)
    memory_limit_mb: int | None = Field(default=None, ge=0)
    gpu_available: bool = False
    gpu_count: int = Field(default=0, ge=0)
    gpu_vram_mb: int | None = Field(default=None, ge=0)
    render_concurrency: int = Field(default=1, ge=1)
    provider_concurrency: int = Field(default=1, ge=1)
    io_concurrency: int = Field(default=1, ge=1)
    source: str = "explicit"

    def model_post_init(self, __context: object) -> None:
        if self.gpu_count == 0 and self.gpu_available:
            raise ValueError("gpu_available requires gpu_count > 0")
        if self.gpu_count > 0 and not self.gpu_available:
            raise ValueError("gpu_count > 0 requires evidence of GPU availability")

    @property
    def cpu_concurrency_limit(self) -> int:
        """Return executable CPU slots without exceeding a measured quota."""

        if self.cpu_quota is None:
            return max(self.render_concurrency, self.provider_concurrency, self.io_concurrency)
        if self.cpu_quota <= 0:
            return 0
        # A fractional CPU still permits one serialized task.  The limit is a
        # scheduler slot count, not a claim that the task owns one full CPU.
        return max(1, math.floor(self.cpu_quota))

    def concurrency_limit(self, lane: ExecutionLane = "render") -> int:
        configured = {
            "render": self.render_concurrency,
            "provider": self.provider_concurrency,
            "io": self.io_concurrency,
        }[lane]
        return min(configured, self.cpu_concurrency_limit)

    def effective_concurrency(self, requested: int, lane: ExecutionLane = "render") -> int:
        if requested < 1:
            raise ValueError("requested concurrency must be >= 1")
        limit = self.concurrency_limit(lane)
        if limit < 1:
            raise ResourceUnavailableError(f"no {lane} execution capacity is allocated")
        return min(requested, limit)

    def require(self, *, gpu_count: int = 0, gpu_vram_mb: int = 0, memory_mb: int = 0) -> None:
        if gpu_count > 0 and (not self.gpu_available or self.gpu_count < gpu_count):
            raise ResourceUnavailableError("requested GPU is unavailable")
        if gpu_vram_mb > 0 and (
            not self.gpu_available
            or self.gpu_vram_mb is None
            or self.gpu_vram_mb < gpu_vram_mb
        ):
            raise ResourceUnavailableError("requested GPU VRAM is unavailable")
        if memory_mb > 0 and self.memory_limit_mb is not None and self.memory_limit_mb < memory_mb:
            raise ResourceUnavailableError("requested memory exceeds the allocated limit")

    @classmethod
    def from_system(
        cls,
        *,
        cgroup_root: Path = Path("/sys/fs/cgroup"),
        render_concurrency: int = 1,
        provider_concurrency: int = 1,
        io_concurrency: int = 1,
    ) -> ExecutionProfile:
        """Discover cgroup limits and GPU evidence for the current worker."""

        cpu_quota = _read_cpu_quota(cgroup_root)
        memory_limit_mb = _read_memory_limit(cgroup_root)
        gpu_count, gpu_vram_mb = _probe_nvidia()
        return cls(
            cpu_quota=cpu_quota,
            memory_limit_mb=memory_limit_mb,
            gpu_available=gpu_count > 0,
            gpu_count=gpu_count,
            gpu_vram_mb=gpu_vram_mb,
            render_concurrency=render_concurrency,
            provider_concurrency=provider_concurrency,
            io_concurrency=io_concurrency,
            source="cgroup+nvidia-smi",
        )


def _read_cpu_quota(root: Path) -> float | None:
    value = root / "cpu.max"
    try:
        raw = value.read_text(encoding="utf-8").split()
        if len(raw) < 2 or raw[0] == "max":
            return None
        quota, period = float(raw[0]), float(raw[1])
        return quota / period if period > 0 else 0.0
    except (OSError, ValueError, IndexError):
        return None


def _read_memory_limit(root: Path) -> int | None:
    value = root / "memory.max"
    try:
        raw = value.read_text(encoding="utf-8").strip()
        if not raw or raw == "max":
            return None
        return max(0, int(int(raw) / (1024 * 1024)))
    except (OSError, ValueError):
        return None


def _probe_nvidia() -> tuple[int, int | None]:
    """Return GPU count/VRAM only when nvidia-smi supplies runtime evidence."""

    executable = shutil.which("nvidia-smi")
    if executable is None:
        return 0, None
    try:
        result = subprocess.run(
            [executable, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 0, None
    if result.returncode != 0:
        return 0, None
    values: list[int] = []
    for line in result.stdout.splitlines():
        try:
            values.append(int(line.strip()))
        except ValueError:
            continue
    return len(values), min(values) if values else None


def assert_concurrency(
    profile: ExecutionProfile,
    requested: int,
    lane: ExecutionLane = "render",
) -> int:
    """Admit and return a safe concurrency, making the invariant executable."""

    effective = profile.effective_concurrency(requested, lane)
    if effective > profile.concurrency_limit(lane):
        raise ResourceUnavailableError("requested concurrency exceeds allocated resources")
    return effective


__all__ = [
    "ExecutionLane",
    "ExecutionProfile",
    "ResourceUnavailableError",
    "assert_concurrency",
]
