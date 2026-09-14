"""Versioned, user-facing creative policy packs."""

from __future__ import annotations

from dataclasses import dataclass

from hevi.obase.creative import CreativePolicy


@dataclass(frozen=True)
class PolicyDiff:
    added: tuple[str, ...]
    removed: tuple[str, ...]


class PolicyModule:
    def diff(self, before: CreativePolicy, after: CreativePolicy) -> PolicyDiff:
        return PolicyDiff(
            added=tuple(sorted(set(after.rules) - set(before.rules))),
            removed=tuple(sorted(set(before.rules) - set(after.rules))),
        )

    def validate(self, policy: CreativePolicy) -> None:
        if not policy.name.strip() or any(not rule.strip() for rule in policy.rules):
            raise ValueError("POLICY_INVALID")

    def rollback(self, current: CreativePolicy, previous: CreativePolicy) -> CreativePolicy:
        self.validate(previous)
        if current.scope != previous.scope:
            raise ValueError("POLICY_SCOPE_MISMATCH")
        return previous.model_copy(update={"version": current.version + 1})


__all__ = ["PolicyDiff", "PolicyModule"]
