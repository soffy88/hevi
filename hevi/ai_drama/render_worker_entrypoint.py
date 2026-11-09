"""Entrypoint for the dedicated drama render worker.

Run as ``python -m hevi.ai_drama.render_worker_entrypoint``.  The worker
defaults ``HEVI_WORKER_RESOURCE_CLASS`` to ``drama_render`` before the settings
module is imported, so it can only claim drama render jobs.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("HEVI_WORKER_RESOURCE_CLASS", "drama_render")
os.environ.setdefault("HEVI_RENDER_MODE", "drama")

from hevi.queue.worker_entrypoint import main  # noqa: E402

if __name__ == "__main__":
    logging.getLogger(__name__).info("drama render worker starting (resource_class=drama_render)")
    main()
