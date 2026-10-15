"""Deterministic Seeded PRNG for Particle Science (mulberry32)."""

from __future__ import annotations


class SeededRNG:
    def __init__(self, seed: int) -> None:
        self.state = seed & 0xFFFFFFFF

    def next_float(self) -> float:
        z = (self.state + 0x6D2B79F5) & 0xFFFFFFFF
        z = (z ^ (z >> 15)) * (1 | z) & 0xFFFFFFFF
        z ^= z + ((z ^ (z >> 7)) * (61 | z) & 0xFFFFFFFF)
        self.state = (z ^ (z >> 14)) & 0xFFFFFFFF
        return float(self.state) / 4294967296.0

    def range(self, low: float, high: float) -> float:
        return low + (high - low) * self.next_float()

    def randint(self, low: int, high: int) -> int:
        return int(low + self.next_float() * (high - low + 1))


__all__ = ["SeededRNG"]
