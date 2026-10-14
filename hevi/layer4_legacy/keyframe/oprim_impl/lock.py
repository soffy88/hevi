"""Inter-process mutual exclusion for CPU generation models."""

from __future__ import annotations

import contextlib
import fcntl
import logging
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger(__name__)
LOCK_FILE = Path("/tmp/hevi_cpu_render.lock")


@contextlib.contextmanager
def cpu_render_lock(*, timeout_s: float = 300.0) -> Iterator[None]:
    """Acquire exclusive flock on /tmp/hevi_cpu_render.lock."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = None
    try:
        lock_fd = open(LOCK_FILE, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                lock_fd.close()
            except OSError:
                pass
