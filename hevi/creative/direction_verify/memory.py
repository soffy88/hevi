"""P10d Creative Memory (evidence promotion + scope + retirement). Suggestions only."""

from __future__ import annotations

from dataclasses import dataclass

from hevi.creative.direction_verify.errors import VerifyError

KINDS = ("approved_pattern", "rejected_pattern", "preference", "outcome")
SCOPES = ("project", "user")
STATUSES = ("candidate", "active", "retired")
PROMOTION_THRESHOLD = 2


@dataclass
class MemoryEntry:
    id: str
    kind: str
    category: str
    pattern: str
    context_tags: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    support_count: int = 0
    scope: str = "project"
    status: str = "candidate"
    refusals: int = 0

    def validate(self) -> None:
        if self.scope == "global":
            # Q2 决策:global 作用域默认禁用,写 global 是显式越权,不是笔误。
            raise VerifyError(f"memory {self.id}: global scope disabled by decision (Q2)",
                              code="MEMORY_SCOPE_GLOBAL_DISABLED")
        if self.kind not in KINDS or self.scope not in SCOPES or self.status not in STATUSES:
            raise VerifyError(f"bad memory entry: {self.id}", code="MEMORY_BAD_ENTRY")
        if not self.evidence:
            raise VerifyError(f"memory {self.id}: evidence required", code="MEMORY_NO_EVIDENCE")


class CreativeMemory:
    """Candidate -> active needs >=2 independent evidence; explicit user feedback
    applies directly in user scope. Suggestions never lower gates or auto-approve."""

    def __init__(self) -> None:
        self._entries: dict[str, MemoryEntry] = {}

    def record(self, entry: MemoryEntry) -> MemoryEntry:
        entry.validate()
        if entry.support_count == 0 and entry.evidence:
            entry = MemoryEntry(entry.id, entry.kind, entry.category, entry.pattern,
                                entry.context_tags, entry.evidence, len(entry.evidence),
                                entry.scope, entry.status, entry.refusals)
        self._entries[entry.id] = entry
        return entry

    def add_evidence(self, entry_id: str, evidence_ref: str, *, explicit_user: bool = False) -> MemoryEntry:
        current = self._entries[entry_id]
        evidence = (*current.evidence, evidence_ref)
        support = current.support_count + 1
        status = current.status
        if (explicit_user and current.scope == "user") or (status == "candidate" and support >= PROMOTION_THRESHOLD):
            status = "active"
        updated = MemoryEntry(current.id, current.kind, current.category, current.pattern,
                              current.context_tags, evidence, support, current.scope,
                              status, current.refusals)
        self._entries[entry_id] = updated
        return updated

    def supersede(self, entry_id: str) -> MemoryEntry:
        current = self._entries[entry_id]
        updated = MemoryEntry(current.id, current.kind, current.category, current.pattern,
                              current.context_tags, current.evidence, current.support_count,
                              current.scope, "retired", current.refusals)
        self._entries[entry_id] = updated
        return updated

    def refuse(self, entry_id: str) -> MemoryEntry:
        current = self._entries[entry_id]
        refusals = current.refusals + 1
        status = "candidate" if refusals >= 2 and current.status == "active" else current.status
        updated = MemoryEntry(current.id, current.kind, current.category, current.pattern,
                              current.context_tags, current.evidence, current.support_count,
                              current.scope, status, refusals)
        self._entries[entry_id] = updated
        return updated

    def suggest(self, context_tags: tuple[str, ...] = ()) -> list[MemoryEntry]:
        suggestions = [e for e in self._entries.values()
                       if e.status in ("active", "candidate") and e.refusals < 2]
        if context_tags:
            suggestions = [e for e in suggestions if set(e.context_tags) & set(context_tags)]
        return sorted(suggestions,
                      key=lambda e: (e.status != "active", -e.support_count, e.refusals))
