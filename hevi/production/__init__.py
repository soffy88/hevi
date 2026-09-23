"""Canonical production contracts, adapters, and artifact records."""

from hevi.production.artifacts import (
    Artifact,
    ArtifactManifest,
    ArtifactVerificationError,
    manifest_from_task,
    verify_local_manifest,
    verify_production_artifact,
)
from hevi.production.contracts import (
    PRODUCTION_STATUSES,
    ExecutionBinding,
    ProductionRequest,
    ProductionResult,
    ProductionSource,
    completion_failure,
)
from hevi.production.execution import execute_standard_operation, execution_binding
from hevi.production.gpu_compute import (
    GpuComputeProvider,
    GpuLease,
    GpuResultCache,
    GpuWorkQueue,
    HourlyGpuProvider,
    LocalGpuProvider,
    RemoteGpuProvider,
)

__all__ = [
    "Artifact",
    "ArtifactManifest",
    "ArtifactVerificationError",
    "ExecutionBinding",
    "ProductionRequest",
    "ProductionSource",
    "execute_standard_operation",
    "execution_binding",
    "manifest_from_task",
    "verify_local_manifest",
    "verify_production_artifact",
    "ProductionResult",
    "PRODUCTION_STATUSES",
    "completion_failure",
    "GpuComputeProvider",
    "GpuLease",
    "GpuResultCache",
    "GpuWorkQueue",
    "HourlyGpuProvider",
    "LocalGpuProvider",
    "RemoteGpuProvider",
]
