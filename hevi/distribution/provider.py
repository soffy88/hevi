from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from hevi.distribution.models import (
    DistributionAccount,
    DistributionJob,
    DistributionResult,
    DistributionTarget,
)


class DistributionProvider(ABC):
    """Provider contract; it is not an orchestration or queue authority."""

    name: str = ""

    @abstractmethod
    async def probe(self) -> dict[str, Any]: ...

    @abstractmethod
    async def list_accounts(self) -> Sequence[DistributionAccount]: ...

    @abstractmethod
    async def validate_account(self, account: DistributionAccount) -> bool: ...

    @abstractmethod
    async def publish(self, job: DistributionJob, source: Path) -> DistributionResult: ...

    @abstractmethod
    async def schedule(self, job: DistributionJob, source: Path) -> DistributionResult: ...

    @abstractmethod
    async def save_draft(self, job: DistributionJob, source: Path) -> DistributionResult: ...

    @abstractmethod
    async def poll(self, job: DistributionJob) -> DistributionResult: ...

    @abstractmethod
    async def history(self, *, platform: str | None = None) -> Sequence[dict[str, Any]]: ...

    async def cancel(self, job: DistributionJob) -> DistributionResult:
        return DistributionResult(
            job=job.model_copy(update={"state": "NEEDS_ATTENTION", "failure_class": "UNSUPPORTED"}),
            provider_status="UNSUPPORTED",
            success=False,
            failure_class="UNSUPPORTED",
            message="provider does not expose a safe cancel operation",
        )

    @staticmethod
    def target_for(job: DistributionJob) -> DistributionTarget:
        return DistributionTarget(
            platform=job.platform,
            account_ref=job.account_ref,
            title=job.title,
            description=job.description,
            tags=job.tags,
            scheduled_at=job.scheduled_at,
        )
