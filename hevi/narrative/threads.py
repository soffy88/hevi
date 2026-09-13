"""Open narrative thread tracking."""

from __future__ import annotations

from hevi.narrative.models import NarrativeThread


def thread_diagnostics(threads: tuple[NarrativeThread, ...]) -> list[str]:
    findings: list[str] = []
    ids = [thread.id for thread in threads]
    if len(ids) != len(set(ids)):
        findings.append("DUPLICATE_THREAD")
    if any(thread.status == "OPEN" and thread.kind == "HIGH_PRIORITY" for thread in threads):
        findings.append("UNRESOLVED_HIGH_PRIORITY_THREAD")
    return findings
