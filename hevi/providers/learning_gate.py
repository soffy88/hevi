"""Fail-closed boundary between provider results and learning progression.

Provider output is not learning evidence by itself.  A caller must submit the
terminal ``ProviderCallResult`` through this gate before it can create an
evidence record or advance mastery/FSRS.  The operation key is also the
idempotency key, so a safe transport retry cannot create duplicate
progression.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hevi.providers.reliability import ProviderCallResult


@dataclass(frozen=True, slots=True)
class LearningProgressionDecision:
    accepted: bool
    reason: str
    evidence: Any | None = None


class ProviderLearningGate:
    """One-process idempotent, fail-closed progression gate.

    Durable evidence repositories should additionally enforce a unique
    operation key.  This in-memory guard prevents duplicate callbacks within
    a worker and documents the contract for provider adapters.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._committed_keys: set[str] = set()

    def commit(
        self,
        result: ProviderCallResult[Any],
        *,
        operation_key: str,
        create_evidence: Callable[[Any], Any],
        advance_mastery: Callable[[Any], None],
        advance_fsrs: Callable[[Any], None],
    ) -> LearningProgressionDecision:
        """Create exactly one evidence record and progress learning once.

        Any non-success provider result is rejected before any callback is
        touched.  ``operation_key`` must be stable across transport retries;
        it must not contain prompt content or PII.
        """

        if not operation_key or any(char.isspace() for char in operation_key):
            raise ValueError("operation_key must be a non-empty opaque key")
        if not result.ok or not result.evidence_eligible or result.value is None:
            return LearningProgressionDecision(False, "provider_result_not_evidence_eligible")

        with self._lock:
            if operation_key in self._committed_keys:
                return LearningProgressionDecision(False, "duplicate_operation")
            evidence = create_evidence(result.value)
            # Mark before progression callbacks so a callback retry cannot
            # duplicate evidence.  A callback exception is still surfaced to
            # the transaction owner; durable callers should use a DB tx.
            self._committed_keys.add(operation_key)
            advance_mastery(evidence)
            advance_fsrs(evidence)
        return LearningProgressionDecision(True, "committed", evidence)


__all__ = ["LearningProgressionDecision", "ProviderLearningGate"]
