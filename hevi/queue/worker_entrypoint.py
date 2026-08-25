"""Standalone billable worker process.

Run with ``python -m hevi.queue.worker_entrypoint``.  Keeping this entrypoint
outside FastAPI means API replicas can scale independently without creating
duplicate executors in every web process.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from dotenv import load_dotenv

from hevi.core.config import settings
from hevi.credits.account_service import AccountService
from hevi.credits.billing_service import BillingService
from hevi.credits.repository import CreditRepository
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.queue.worker import QueueWorker
from hevi.resilience.balance_prober import BalanceProber
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService

logger = logging.getLogger(__name__)


async def run() -> None:
    load_dotenv()
    pool = await get_hevi_pg_pool()
    repository = TaskRepository(pool)
    billing = BillingService(AccountService(CreditRepository(pool)))
    service = TaskService(repository, billing_svc=billing)
    worker = QueueWorker(
        service,
        poll_interval=5.0,
        resource_class=settings.worker_resource_class,
        available_vram_mb=settings.worker_available_vram_mb,
        capacity_slots=settings.worker_capacity_slots,
    )
    prober = BalanceProber(poll_interval=3600.0)
    worker_task = asyncio.create_task(worker.run())
    prober_task = asyncio.create_task(prober.run())
    try:
        await worker_task
    finally:
        worker.stop()
        prober.stop()
        prober_task.cancel()
        with suppress(asyncio.CancelledError):
            await prober_task


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
