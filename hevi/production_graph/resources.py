"""Resource profiles and deterministic admission for production execution.

The profile is deliberately independent from a particular provider or worker
implementation.  It describes what the current process was actually given;
callers then derive a safe concurrency for a named execution lane.  GPU
discovery is evidence based: an unavailable or unprobeable GPU is reported as
unavailable rather than inferred from configuration.
"""

from __future__ import annotations

import math
import os
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
    cpu_capacity: float | None = Field(default=None, ge=0)
    affinity_cpus: int | None = Field(default=None, ge=0)
    cpuset_cpus: int | None = Field(default=None, ge=0)
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

        capacities = [
            capacity for capacity in (self.cpu_quota, self.cpu_capacity) if capacity is not None
        ]
        if self.affinity_cpus is not None:
            capacities.append(float(self.affinity_cpus))
        if self.cpuset_cpus is not None:
            capacities.append(float(self.cpuset_cpus))
        if not capacities:
            return max(self.render_concurrency, self.provider_concurrency, self.io_concurrency)
        capacity = min(capacities)
        if capacity <= 0:
            return 0
        # A fractional CPU still permits one serialized task.  The limit is a
        # scheduler slot count, not a claim that the task owns one full CPU.
        return max(1, math.floor(capacity))

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
            not self.gpu_available or self.gpu_vram_mb is None or self.gpu_vram_mb < gpu_vram_mb
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
        cpuset_cpus = _read_cpuset_count(cgroup_root)
        affinity_cpus = _read_affinity_count()
        cpu_capacity = _effective_cpu_capacity(
            cpu_quota=cpu_quota,
            cpuset_cpus=cpuset_cpus,
            affinity_cpus=affinity_cpus,
        )
        memory_limit_mb = _read_memory_limit(cgroup_root)
        gpu_count, gpu_vram_mb = _probe_nvidia()
        return cls(
            cpu_quota=cpu_quota,
            cpu_capacity=cpu_capacity,
            affinity_cpus=affinity_cpus,
            cpuset_cpus=cpuset_cpus,
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
    try:
        raw = (root / "cpu.max").read_text(encoding="utf-8").split()
        if len(raw) >= 2 and raw[0] != "max":
            quota, period = float(raw[0]), float(raw[1])
            return quota / period if period > 0 else 0.0
        if raw and raw[0] == "max":
            return None
    except (OSError, ValueError, IndexError):
        pass
    # cgroup v1 exposes the same constraint as two files.
    try:
        quota = float((root / "cpu.cfs_quota_us").read_text(encoding="utf-8").strip())
        period = float((root / "cpu.cfs_period_us").read_text(encoding="utf-8").strip())
        if quota < 0:
            return None
        return quota / period if period > 0 else 0.0
    except (OSError, ValueError, IndexError):
        return None


def _parse_cpuset(value: str) -> int:
    """Count CPUs in a Linux cpuset expression such as ``0-3,7``."""

    count = 0
    for part in value.strip().split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            start, end = item.split("-", 1)
            start_i, end_i = int(start), int(end)
            if start_i < 0 or end_i < start_i:
                raise ValueError("invalid cpuset range")
            count += end_i - start_i + 1
        else:
            if int(item) < 0:
                raise ValueError("invalid cpuset cpu")
            count += 1
    return count


def _read_cpuset_count(root: Path) -> int | None:
    """Read cgroup v2/v1 cpuset metadata without treating malformed data as capacity."""

    for filename in ("cpuset.cpus.effective", "cpuset.cpus"):
        try:
            raw = (root / filename).read_text(encoding="utf-8")
            if not raw.strip():
                continue
            count = _parse_cpuset(raw)
            if count > 0:
                return count
        except OSError, ValueError:
            continue
    return None


def _read_affinity_count() -> int | None:
    """Return the scheduler-visible CPU set, when the platform exposes it."""

    try:
        return len(os.sched_getaffinity(0))
    except AttributeError, OSError:
        return None


def _effective_cpu_capacity(
    *,
    cpu_quota: float | None,
    cpuset_cpus: int | None,
    affinity_cpus: int | None,
) -> float | None:
    """Choose the tightest observed runtime CPU envelope.

    A missing or malformed cgroup file is not interpreted as unlimited CPU.
    Scheduler affinity is preferred as a safe fallback; only when neither
    cgroup nor affinity metadata exists do we use the process CPU count.
    """

    observed = [
        value
        for value in (
            cpu_quota,
            float(cpuset_cpus) if cpuset_cpus is not None else None,
            float(affinity_cpus) if affinity_cpus is not None else None,
        )
        if value is not None and value >= 0
    ]
    if observed:
        return min(observed)
    fallback = os.cpu_count()
    return float(fallback) if fallback is not None and fallback > 0 else 1.0


def _read_memory_limit(root: Path) -> int | None:
    value = root / "memory.max"
    try:
        raw = value.read_text(encoding="utf-8").strip()
        if not raw or raw == "max":
            return None
        return max(0, int(int(raw) / (1024 * 1024)))
    except OSError, ValueError:
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
    except OSError, subprocess.SubprocessError:
        return 0, None
    if result.returncode != 0:
        return 0, None
    values: list[int] = []
    for line in getattr(result, "stdout", "").splitlines():
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
