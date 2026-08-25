"""Process entrypoint for the independent scheduler service."""

from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv

from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.scheduler.repository import SchedulerRepository
from hevi.scheduler.service import SchedulerService


async def run() -> None:
    load_dotenv()
    pool = await get_hevi_pg_pool()
    await SchedulerService(SchedulerRepository(pool)).run()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
