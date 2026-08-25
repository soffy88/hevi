"""Standalone provider health sampler entrypoint."""

from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv

from .health import run_provider_health_service


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_provider_health_service())


if __name__ == "__main__":
    main()
