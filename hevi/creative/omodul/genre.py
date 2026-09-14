"""Extensible genre rules and fatigue checks."""

from __future__ import annotations

import re
from dataclasses import dataclass

from hevi.obase.creative import GenreProfile


@dataclass(frozen=True)
class GenreFinding:
    code: str
    severity: str
    message: str


class GenreModule:
    def audit(self, profile: GenreProfile, text: str) -> tuple[GenreFinding, ...]:
        findings: list[GenreFinding] = []
        lowered = text.casefold()
        findings.extend(
            GenreFinding("FORBIDDEN_PATTERN", "ERROR", pattern)
            for pattern in profile.forbidden_patterns
            if pattern.casefold() in lowered
        )
        for word in profile.fatigue_lexicon:
            count = len(re.findall(rf"\b{re.escape(word)}\b", lowered))
            if count > 3:
                findings.append(GenreFinding("FATIGUE_WORD", "WARN", f"{word}:{count}"))
        return tuple(findings)


__all__ = ["GenreFinding", "GenreModule"]
