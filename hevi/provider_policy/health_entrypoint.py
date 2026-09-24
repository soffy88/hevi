"""Standalone provider health sampler entrypoint."""

from __future__ import annotations

import asyncio
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from hevi.core.config import settings  # noqa: F401
from hevi.core.exceptions import ConfigurationError

from .health import run_provider_health_service


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_provider_health_service())
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
