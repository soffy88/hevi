"""Small, dependency-free metrics payload for analysis reports."""

from __future__ import annotations

from time import perf_counter


class Stopwatch:
    def __enter__(self) -> Stopwatch:
        self.started = perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        self.elapsed_ms = round((perf_counter() - self.started) * 1000, 3)
