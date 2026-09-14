"""Abstract style analysis and synthetic-writing quality checks.

The naturalness auditor targets writing *quality*: repetition, template cadence,
generic transitions, empty intensifiers, semantic repetition, unnatural
dialogue, over-explanation, cliché density, style drift, paragraph monotony, and
syntactic monotony.  It explicitly does not implement AI-detector evasion or
humanization-for-bypass; the only goal is a better draft.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from hevi.obase.creative import StyleProfile

#: Content codes that are explicitly out of scope for this module.
FORBIDDEN_EVASION_GOALS: tuple[str, ...] = (
    "AI_DETECTOR_EVASION",
    "HUMANIZER_BYPASS",
)

EMPTY_INTENSIFIERS: tuple[str, ...] = (
    "very",
    "really",
    "just",
    "quite",
    "literally",
    "actually",
    "basically",
    "truly",
    "totally",
)

GENERIC_TRANSITIONS: tuple[str, ...] = (
    "meanwhile",
    "suddenly",
    "somehow",
    "eventually",
    "without warning",
    "at that moment",
)

OVER_EXPLANATION_MARKERS: tuple[str, ...] = (
    "which meant that",
    "this is because",
    "in other words",
    "that is to say",
    "as previously mentioned",
    "for the reason that",
)

CLICHES: tuple[str, ...] = (
    "at the end of the day",
    "heart of gold",
    "cold as ice",
    "little did they know",
    "suddenly everything changed",
    "tip of the iceberg",
    "only time will tell",
    "calm before the storm",
)

STILTED_DIALOGUE_MARKERS: tuple[str, ...] = (
    "it is i",
    "i am not able",
    "do not you",
    "shall not",
    "it is not possible that",
)

_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "that",
        "with",
        "from",
        "this",
        "they",
        "were",
        "have",
        "been",
        "into",
        "then",
        "them",
        "there",
        "their",
        "what",
        "when",
        "your",
        "will",
        "would",
        "could",
        "should",
        "about",
        "after",
        "before",
        "over",
        "under",
        "again",
        "once",
    }
)

_VARYING_OPENERS: tuple[str, ...] = (
    "Then",
    "Later on",
    "Afterward in time",
    "Soon enough",
    "Beyond the wall",
)


class NaturalnessFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    severity: str
    excerpt: str
    recommendation: str
    location: str | None = None
    explanation: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class WritingNaturalnessAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    findings: tuple[NaturalnessFinding, ...] = ()
    metrics: dict[str, float] = Field(default_factory=dict)


class NaturalnessRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revised_text: str
    operations: tuple[str, ...] = ()
    before_codes: tuple[str, ...] = ()
    after_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class StyleApplication:
    profile_id: UUID
    instructions: tuple[str, ...]


def _sentences(text: str) -> tuple[str, ...]:
    parts = re.split(r"(?<=[.!?。！？])\s+", text.strip())
    return tuple(part.strip() for part in parts if part.strip())


def _paragraphs(text: str) -> tuple[str, ...]:
    parts = re.split(r"\n\s*\n", text.strip())
    return tuple(part.strip() for part in parts if part.strip())


def _words(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[A-Za-z0-9']+", text))


def _location(text: str, needle: str) -> str | None:
    lowered = needle.casefold()
    for index, sentence in enumerate(_sentences(text), start=1):
        if lowered in sentence.casefold():
            return f"sentence:{index}"
    return None


def _dialogue_ratio(text: str) -> float | None:
    if not text.strip():
        return None
    quoted = sum(len(match) for match in re.findall(r"[\"“].*?[\"”]", text, re.DOTALL))
    return min(1.0, quoted / len(text))


def _finding(
    code: str,
    severity: str,
    excerpt: str,
    recommendation: str,
    text: str,
    *,
    location: str | None = None,
    explanation: str | None = None,
) -> NaturalnessFinding:
    return NaturalnessFinding(
        code=code,
        severity=severity,
        excerpt=excerpt,
        recommendation=recommendation,
        location=location or _location(text, excerpt),
        explanation=explanation,
    )


def _detect_repetitive_phrase(text: str) -> list[NaturalnessFinding]:
    findings: list[NaturalnessFinding] = []
    consecutive = re.search(r"\b(\w+)(?:\s+\1){2,}\b", text, re.IGNORECASE)
    if consecutive:
        findings.append(
            _finding(
                "REPETITIVE_PHRASE",
                "WARN",
                consecutive.group(0),
                "vary the repeated phrase or cut the repetition",
                text,
                explanation="the same token repeats consecutively within one span",
            )
        )
    grams: dict[str, int] = {}
    words = [word.casefold() for word in _words(text)]
    for index in range(len(words) - 2):
        gram = " ".join(words[index : index + 3])
        grams[gram] = grams.get(gram, 0) + 1
    for gram, count in grams.items():
        if count >= 3:
            findings.append(
                _finding(
                    "REPETITIVE_PHRASE",
                    "WARN",
                    gram,
                    "vary the repeated phrase or cut the repetition",
                    text,
                    explanation=f"the trigram {gram!r} repeats {count} times",
                )
            )
            break
    return findings


def _detect_template_cadence(text: str) -> list[NaturalnessFinding]:
    sentences = _sentences(text)
    if len(sentences) < 5:
        return []
    openings: dict[str, int] = {}
    for sentence in sentences:
        tokens = _words(sentence)
        if not tokens:
            continue
        openings[tokens[0].casefold()] = openings.get(tokens[0].casefold(), 0) + 1
    repeated = [(word, count) for word, count in openings.items() if count >= 4]
    if repeated:
        word, count = max(repeated, key=lambda item: item[1])
        return [
            _finding(
                "TEMPLATE_CADENCE",
                "WARN",
                word,
                "vary sentence openings and rhythm",
                text,
                explanation=f"{count} sentences start with {word!r}",
            )
        ]
    lengths = [len(_words(sentence)) for sentence in sentences]
    if len(set(lengths)) == 1:
        return [
            _finding(
                "TEMPLATE_CADENCE",
                "WARN",
                f"uniform:{lengths[0]}",
                "vary sentence length across the passage",
                text,
                explanation="every sentence has an identical length",
            )
        ]
    return []


def _detect_generic_transition(text: str) -> list[NaturalnessFinding]:
    findings: list[NaturalnessFinding] = []
    lowered = text.casefold()
    for marker in GENERIC_TRANSITIONS:
        count = lowered.count(marker)
        if count == 0:
            continue
        sentence_initial = any(
            sentence.casefold().startswith(marker) for sentence in _sentences(text)
        )
        if count >= 2 or sentence_initial:
            findings.append(
                _finding(
                    "GENERIC_TRANSITION",
                    "WARN",
                    marker,
                    "replace the generic transition with a concrete beat",
                    text,
                    explanation=f"generic transition {marker!r} appears {count} time(s)",
                )
            )
    return findings


def _detect_empty_intensifier(text: str) -> list[NaturalnessFinding]:
    return [
        _finding(
            "EMPTY_INTENSIFIER",
            "WARN",
            marker,
            "replace the intensifier with a concrete action or image",
            text,
            explanation=f"empty intensifier {marker!r} weakens the clause",
        )
        for marker in EMPTY_INTENSIFIERS
        if re.search(rf"\b{marker}\b", text, re.IGNORECASE)
    ]


def _detect_semantic_repetition(text: str) -> list[NaturalnessFinding]:
    counts: dict[str, int] = {}
    for word in _words(text):
        lowered = word.casefold()
        if len(lowered) < 4 or lowered in _STOPWORDS:
            continue
        counts[lowered] = counts.get(lowered, 0) + 1
    findings: list[NaturalnessFinding] = []
    for word, count in counts.items():
        if count >= 4:
            findings.append(
                _finding(
                    "SEMANTIC_REPETITION",
                    "WARN",
                    word,
                    "replace later occurrences with a pronoun or a synonym",
                    text,
                    explanation=f"content word {word!r} repeats {count} times",
                )
            )
    return findings


def _detect_unnatural_dialogue(text: str) -> list[NaturalnessFinding]:
    findings: list[NaturalnessFinding] = []
    for match in re.finditer(r"[\"“](.*?)[\"”]", text, re.DOTALL):
        line = match.group(1).strip()
        lowered = line.casefold()
        for marker in STILTED_DIALOGUE_MARKERS:
            if marker in lowered:
                findings.append(
                    _finding(
                        "UNNATURAL_DIALOGUE",
                        "WARN",
                        line,
                        "rewrite the line with natural spoken rhythm",
                        text,
                        explanation=f"stilted construction {marker!r} in dialogue",
                    )
                )
                break
    return findings


def _detect_over_explanation(text: str) -> list[NaturalnessFinding]:
    lowered = text.casefold()
    return [
        _finding(
            "OVER_EXPLANATION",
            "WARN",
            marker,
            "trust the reader and cut the explanation",
            text,
            explanation=f"explanatory connective {marker!r} states the obvious",
        )
        for marker in OVER_EXPLANATION_MARKERS
        if marker in lowered
    ]


def _detect_cliche_density(text: str) -> list[NaturalnessFinding]:
    lowered = text.casefold()
    return [
        _finding(
            "CLICHE_DENSITY",
            "WARN",
            cliche,
            "replace the cliché with a specific image",
            text,
            explanation=f"received phrase {cliche!r} is a cliché",
        )
        for cliche in CLICHES
        if cliche in lowered
    ]


def _detect_style_drift(text: str, style_profile: StyleProfile | None) -> list[NaturalnessFinding]:
    if style_profile is None or style_profile.sentence_length is None:
        return []
    try:
        target = float(style_profile.sentence_length)
    except ValueError:
        return []
    sentences = _sentences(text)
    if not sentences:
        return []
    observed = sum(len(_words(sentence)) for sentence in sentences) / len(sentences)
    if abs(observed - target) <= max(6.0, target * 0.75):
        return []
    return [
        _finding(
            "STYLE_DRIFT",
            "WARN",
            f"{observed:.1f}",
            "align cadence with the project style profile",
            text,
            location="text:all",
            explanation=f"mean sentence length {observed:.1f} drifts from {target:.1f}",
        )
    ]


def _detect_paragraph_monotony(text: str) -> list[NaturalnessFinding]:
    paragraphs = _paragraphs(text)
    if len(paragraphs) < 3:
        return []
    counts = [len(_sentences(paragraph)) for paragraph in paragraphs]
    if len(set(counts)) == 1 and counts[0] >= 2:
        return [
            _finding(
                "PARAGRAPH_MONOTONY",
                "WARN",
                f"paragraphs:{counts[0]}",
                "vary paragraph length and internal shape",
                text,
                location="paragraph:all",
                explanation=f"all {len(paragraphs)} paragraphs contain {counts[0]} sentences",
            )
        ]
    lengths = [len(_words(paragraph)) for paragraph in paragraphs]
    if max(lengths) - min(lengths) <= 1 and lengths[0] >= 12:
        return [
            _finding(
                "PARAGRAPH_MONOTONY",
                "WARN",
                "paragraphs:uniform",
                "vary paragraph length and internal shape",
                text,
                location="paragraph:all",
                explanation="all paragraphs have a near-identical length",
            )
        ]
    return []


_SYNTAX_TEMPLATE = re.compile(r"^(?:The|A|An)\s+\w+\s+(?:was|were|is|are)\s+\w+\.?$", re.IGNORECASE)


def _detect_syntactic_monotony(text: str) -> list[NaturalnessFinding]:
    sentences = _sentences(text)
    if len(sentences) < 4:
        return []
    templated = sum(1 for sentence in sentences if _SYNTAX_TEMPLATE.match(sentence))
    if templated / len(sentences) >= 0.6:
        return [
            _finding(
                "SYNTACTIC_MONOTONY",
                "WARN",
                f"template:{templated}/{len(sentences)}",
                "vary the syntactic template across sentences",
                text,
                location="text:all",
                explanation=f"{templated} of {len(sentences)} sentences share one template",
            )
        ]
    return []


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

    def audit_naturalness(
        self,
        text: str,
        *,
        style_profile: StyleProfile | None = None,
    ) -> WritingNaturalnessAudit:
        findings: list[NaturalnessFinding] = []
        findings.extend(_detect_repetitive_phrase(text))
        findings.extend(_detect_template_cadence(text))
        findings.extend(_detect_generic_transition(text))
        findings.extend(_detect_empty_intensifier(text))
        findings.extend(_detect_semantic_repetition(text))
        findings.extend(_detect_unnatural_dialogue(text))
        findings.extend(_detect_over_explanation(text))
        findings.extend(_detect_cliche_density(text))
        findings.extend(_detect_style_drift(text, style_profile))
        findings.extend(_detect_paragraph_monotony(text))
        findings.extend(_detect_syntactic_monotony(text))
        status = (
            "FAIL"
            if any(item.severity == "ERROR" for item in findings)
            else "WARN"
            if findings
            else "PASS"
        )
        return WritingNaturalnessAudit(
            status=status,
            findings=tuple(findings),
            metrics={"finding_count": float(len(findings))},
        )

    def revise_naturalness(self, text: str, audit: WritingNaturalnessAudit) -> NaturalnessRevision:
        """Apply deterministic, quality-only repairs for the observed findings."""

        codes = {finding.code for finding in audit.findings}
        operations: list[str] = []
        revised = text
        if "REPETITIVE_PHRASE" in codes:
            revised = re.sub(r"\b(\w+)(?:\s+\1){2,}\b", r"\1", revised, flags=re.IGNORECASE)
            revised = _collapse_trigrams(revised)
            operations.append("collapse consecutive repetition")
        if "TEMPLATE_CADENCE" in codes:
            revised = _vary_openings(revised)
            operations.append("vary sentence openings")
        if "GENERIC_TRANSITION" in codes:
            revised = re.sub(
                r"\b(?:meanwhile|suddenly|somehow|eventually|without warning|at that moment)\b[,]?\s*",
                "",
                revised,
                flags=re.IGNORECASE,
            )
            operations.append("remove generic transitions")
        if "EMPTY_INTENSIFIER" in codes:
            revised = re.sub(
                r"\b(?:very|really|just|quite|literally|actually|basically|truly|totally)\b\s*",
                "",
                revised,
                flags=re.IGNORECASE,
            )
            operations.append("remove empty intensifiers")
        if "SEMANTIC_REPETITION" in codes:
            revised = _replace_repeats(revised)
            operations.append("replace repeated content words")
        if "UNNATURAL_DIALOGUE" in codes:
            revised = revised.replace("It is I", "It's me")
            revised = revised.replace("it is I", "it's me")
            revised = revised.replace("I am not able", "I can't")
            revised = revised.replace("Do not you", "Don't you")
            revised = revised.replace("shall not", "won't")
            operations.append("naturalize stilted dialogue")
        if "OVER_EXPLANATION" in codes:
            for marker in OVER_EXPLANATION_MARKERS:
                revised = re.sub(re.escape(marker) + r",?\s*", "", revised, flags=re.IGNORECASE)
            operations.append("cut over-explanation")
        if "CLICHE_DENSITY" in codes:
            for cliche in CLICHES:
                revised = re.sub(re.escape(cliche), "in the end", revised, flags=re.IGNORECASE)
            operations.append("replace clichés")
        if "STYLE_DRIFT" in codes:
            revised = re.sub(r",?\s+while\s+", ". The scene ", revised)
            revised = re.sub(r"\s+and\s+", ". Then ", revised)
            operations.append("align sentence cadence")
        if "PARAGRAPH_MONOTONY" in codes:
            revised = revised.replace("\n\n", " The moment held.\n\n", 1)
            operations.append("vary paragraph shape")
        if "SYNTACTIC_MONOTONY" in codes:
            revised = revised.replace(" was ", " grew ").replace(" were ", " became ")
            operations.append("vary syntactic template")
        revised = re.sub(r"[ \t]{2,}", " ", revised).strip()
        after = self.audit_naturalness(revised)
        return NaturalnessRevision(
            revised_text=revised,
            operations=tuple(operations),
            before_codes=tuple(sorted(codes)),
            after_codes=tuple(sorted({finding.code for finding in after.findings})),
        )


def _collapse_trigrams(text: str) -> str:
    words = list(_words(text))
    if len(words) < 6:
        return text
    lowered = [word.casefold() for word in words]
    for index in range(len(lowered) - 2):
        gram = tuple(lowered[index : index + 3])
        occurrences = [
            other for other in range(len(lowered) - 2) if tuple(lowered[other : other + 3]) == gram
        ]
        if len(occurrences) >= 3:
            drop: set[int] = set()
            for start in occurrences[1:]:
                drop.update(range(start, start + 3))
            kept = [word for position, word in enumerate(words) if position not in drop]
            return " ".join(kept)
    return text


def _vary_openings(text: str) -> str:
    sentences = _sentences(text)
    if not sentences:
        return text
    seen: dict[str, int] = {}
    output: list[str] = []
    cycle = 0
    for sentence in sentences:
        tokens = _words(sentence)
        opening = tokens[0].casefold() if tokens else ""
        seen[opening] = seen.get(opening, 0) + 1
        if opening and seen[opening] > 1:
            opener = _VARYING_OPENERS[cycle % len(_VARYING_OPENERS)]
            cycle += 1
            output.append(f"{opener} {sentence[0].lower()}{sentence[1:]}")
        else:
            output.append(sentence)
    return " ".join(output)


def _replace_repeats(text: str) -> str:
    counts: dict[str, int] = {}
    for word in _words(text):
        lowered = word.casefold()
        if len(lowered) < 4 or lowered in _STOPWORDS:
            continue
        counts[lowered] = counts.get(lowered, 0) + 1
    repeated = {word for word, count in counts.items() if count >= 4}
    if not repeated:
        return text
    seen: dict[str, int] = {}

    def swap(match: re.Match[str]) -> str:
        word = match.group(0)
        lowered = word.casefold()
        if lowered not in repeated:
            return word
        seen[lowered] = seen.get(lowered, 0) + 1
        return "it" if seen[lowered] > 1 else word

    return re.sub(r"[A-Za-z']+", swap, text)


__all__ = [
    "CLICHES",
    "EMPTY_INTENSIFIERS",
    "FORBIDDEN_EVASION_GOALS",
    "GENERIC_TRANSITIONS",
    "OVER_EXPLANATION_MARKERS",
    "NaturalnessFinding",
    "NaturalnessRevision",
    "StyleApplication",
    "StyleModule",
    "WritingNaturalnessAudit",
]
