"""Process entrypoint for the independent scheduler service."""

from __future__ import annotations

import asyncio
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from hevi.core.config import settings  # noqa: F401
from hevi.core.exceptions import ConfigurationError
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.scheduler.repository import SchedulerRepository
from hevi.scheduler.service import SchedulerService


async def run() -> None:
    pool = await get_hevi_pg_pool()
    await SchedulerService(SchedulerRepository(pool)).run()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run())
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
