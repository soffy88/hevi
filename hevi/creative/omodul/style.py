"""Abstract style analysis and synthetic-writing quality checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from hevi.obase.creative import StyleProfile


class NaturalnessFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    severity: str
    excerpt: str
    recommendation: str


class WritingNaturalnessAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    findings: tuple[NaturalnessFinding, ...] = ()


@dataclass(frozen=True)
class StyleApplication:
    profile_id: UUID
    instructions: tuple[str, ...]


class StyleModule:
    def analyze(self, *, project_id: UUID, name: str, text: str) -> StyleProfile:
        if not text.strip():
            raise ValueError("STYLE_EMPTY_INPUT")
        sentences = [part for part in re.split(r"[.!?。！？]+", text) if part.strip()]
        words = text.split()
        dialogue = len(re.findall(r"[\"“].*?[\"”]", text, re.DOTALL))
        return StyleProfile(
            project_id=project_id,
            name=name,
            sentence_length=f"{sum(len(sentence.split()) for sentence in sentences) / max(1, len(sentences)):.1f}",
            lexical_characteristics=(
                "long-token" if any(len(word) > 12 for word in words) else "compact",
            ),
            rhythm="varied"
            if len({len(sentence.split()) for sentence in sentences}) > 1
            else "uniform",
            dialogue_ratio=min(1.0, dialogue / max(1, len(text))),
            paragraph_structure="multi-paragraph" if "\n\n" in text else "single-block",
            pov_tendencies=(),
            tone=(),
            descriptive_density="measured",
        )

    def apply(self, profile: StyleProfile) -> StyleApplication:
        instructions = tuple(
            value
            for value in (
                f"sentence_length={profile.sentence_length}" if profile.sentence_length else None,
                f"rhythm={profile.rhythm}" if profile.rhythm else None,
                f"paragraph_structure={profile.paragraph_structure}"
                if profile.paragraph_structure
                else None,
            )
            if value
        )
        return StyleApplication(profile.object_id, instructions)

    def audit_naturalness(self, text: str) -> WritingNaturalnessAudit:
        findings: list[NaturalnessFinding] = []
        repeated = re.search(r"\b(\w+)(?:\s+\1){2,}\b", text, re.IGNORECASE)
        if repeated:
            findings.append(
                NaturalnessFinding(
                    code="REPETITIVE_PHRASE",
                    severity="WARN",
                    excerpt=repeated.group(0),
                    recommendation="vary the repeated phrase",
                )
            )
        if re.search(r"\b(very|really|just)\b", text, re.IGNORECASE):
            findings.append(
                NaturalnessFinding(
                    code="EMPTY_INTENSIFIER",
                    severity="WARN",
                    excerpt="intensifier",
                    recommendation="replace with a concrete action or image",
                )
            )
        return WritingNaturalnessAudit(
            status="FAIL"
            if any(item.severity == "ERROR" for item in findings)
            else "WARN"
            if findings
            else "PASS",
            findings=tuple(findings),
        )


__all__ = ["NaturalnessFinding", "StyleApplication", "StyleModule", "WritingNaturalnessAudit"]
