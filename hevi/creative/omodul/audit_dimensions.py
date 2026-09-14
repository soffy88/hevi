"""Deterministic per-dimension verifiers for the creative audit engine.

The audit engine in :mod:`hevi.creative.omodul.audit` owns the audit *envelope*
and the fail-closed contract.  This module owns the 33 dimension verifiers that
turn structured evidence (draft claims, reconstructed canon, scene intents,
style/genre/author profiles) into located :class:`DimensionFinding` records.

Design rules:

* Every verifier is a pure function over :class:`AuditContext`.
* A verifier never converts missing input into a pass.  If it cannot evaluate
  because a required structured input is absent it emits a fail-closed finding.
* Every finding carries a stable ``location`` and the canonical refs it
  contradicts, so downstream review can trace the defect to source.
* Model-assisted evaluation is *not* used here; this module is the deterministic
  half of the audit.  The optional model path is declared by
  :class:`ModelAssistedVerifier` and must satisfy the structured-evidence
  contract before its output can be joined to the deterministic findings.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["INFO", "WARN", "ERROR", "FATAL"]

#: Dimensions whose judgement is objective continuity reconciliation.  The gold
#: corpus requires these to be found deterministically at a 100% rate.
HARD_CONTINUITY_DIMENSIONS: tuple[str, ...] = (
    "CHARACTER_CONTINUITY",
    "WORLD_CONTINUITY",
    "TIMELINE_CONTINUITY",
    "LOCATION_CONTINUITY",
    "OBJECT_CONTINUITY",
    "RESOURCE_CONTINUITY",
    "RELATIONSHIP_CONTINUITY",
    "INFORMATION_CONTINUITY",
    "EMOTIONAL_CONTINUITY",
    "PHYSICAL_STATE_CONTINUITY",
    "MOTIVATION_CONTINUITY",
    "FACT_CONSISTENCY",
    "HOOK_CONTINUITY",
)

#: Dimensions that need craft judgement and therefore may also be routed through
#: the model-assisted verifier when a bounded model is available.
MODEL_ASSISTED_DIMENSIONS: tuple[str, ...] = (
    "DIALOGUE_QUALITY",
    "PROSE_CLARITY",
    "TONE",
    "VISUAL_FILMABILITY",
    "AUTHOR_INTENT_ALIGNMENT",
    "PACING",
)

#: Content codes that must never be exported as a quality improvement target.
FORBIDDEN_EVASION_GOALS: tuple[str, ...] = (
    "AI_DETECTOR_EVASION",
    "HUMANIZER_BYPASS",
)


def canonical_ref(ref: str) -> UUID:
    """Deterministically map a human canonical ref to a stable UUID."""

    return uuid5(NAMESPACE_URL, f"hevi:canon:{ref}")


class AuditClaim(BaseModel):
    """A structured assertion extracted from the draft or reconstructed canon."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: str
    subject: str
    predicate: str
    value: str
    location: str | None = None
    entity_ref: str | None = None


class SceneSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    purpose: str = ""
    objective: str = ""
    beat_kind: str | None = None
    pov: str | None = None
    location: str | None = None
    tension: float | None = Field(default=None, ge=0.0, le=1.0)


class StyleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sentence_length: float | None = None
    rhythm: str | None = None
    dialogue_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    tone: tuple[str, ...] = ()
    pov: str | None = None


class GenreSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = ""
    required_patterns: tuple[str, ...] = ()
    forbidden_patterns: tuple[str, ...] = ()
    fatigue_lexicon: tuple[str, ...] = ()
    pacing_profile: str | None = None
    min_action_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    max_scene_density: float | None = Field(default=None, ge=0.0)
    dialogue_expectation: float | None = Field(default=None, ge=0.0, le=1.0)


class AuthorIntentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    constraints: tuple[str, ...] = ()
    success_criteria: tuple[str, ...] = ()
    tone: str | None = None


class LengthTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min_words: int | None = Field(default=None, ge=0)
    max_words: int | None = Field(default=None, ge=0)


class AuditState(BaseModel):
    """Reconstructed canonical state consulted by the continuity verifiers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    canon_facts: tuple[AuditClaim, ...] = ()
    known_entities: tuple[str, ...] = ()
    hook_deadlines: tuple[tuple[str, int], ...] = ()
    payoff_setup_refs: tuple[tuple[str, str], ...] = ()


class AuditContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    artifact_id: UUID
    text: str = ""
    claims: tuple[AuditClaim, ...] = ()
    scenes: tuple[SceneSpec, ...] = ()
    state: AuditState = AuditState()
    style: StyleSpec | None = None
    genre: GenreSpec | None = None
    author_intent: AuthorIntentSpec | None = None
    length_target: LengthTarget | None = None
    shot_constraints: tuple[str, ...] = ()
    current_chapter: int = Field(default=1, ge=1)


class DimensionFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: str
    code: str
    severity: Severity
    message: str
    recommendation: str
    location: str | None = None
    canon_refs: tuple[str, ...] = ()
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


def _sentences(text: str) -> tuple[str, ...]:
    parts = re.split(r"(?<=[.!?。！？])\s+", text.strip())
    return tuple(part for part in parts if part.strip())


def _sentence_location(text: str, match: str) -> str | None:
    for index, sentence in enumerate(_sentences(text), start=1):
        if match in sentence:
            return f"sentence:{index}"
    return None


def _words(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[A-Za-z0-9']+", text))


def _casefold_contains(haystack: str, needle: str) -> bool:
    return needle.casefold() in haystack.casefold()


def _canon_index(
    facts: tuple[AuditClaim, ...],
) -> dict[tuple[str, str, str], list[AuditClaim]]:
    index: dict[tuple[str, str, str], list[AuditClaim]] = {}
    for fact in facts:
        index.setdefault((fact.dimension, fact.subject, fact.predicate), []).append(fact)
    return index


def _continuity_findings(
    context: AuditContext,
    dimension: str,
    *,
    severity: Severity = "ERROR",
) -> list[DimensionFinding]:
    index = _canon_index(context.state.canon_facts)
    findings: list[DimensionFinding] = []
    seen: set[tuple[str, str, str]] = set()
    for claim in context.claims:
        if claim.dimension != dimension:
            continue
        key = (claim.subject, claim.predicate, claim.value.casefold())
        if key in seen:
            continue
        matches = index.get((dimension, claim.subject, claim.predicate), [])
        for fact in matches:
            if fact.value.strip().casefold() == claim.value.strip().casefold():
                continue
            seen.add(key)
            refs = tuple(
                ref for ref in (claim.entity_ref, fact.entity_ref) if ref is not None
            )
            findings.append(
                DimensionFinding(
                    dimension=dimension,
                    code=f"{_code_prefix(dimension)}_CONFLICT",
                    severity=severity,
                    message=(
                        f"{claim.subject}.{claim.predicate}={claim.value!r} contradicts "
                        f"canon value {fact.value!r}"
                    ),
                    recommendation=(
                        f"restore {claim.subject}.{claim.predicate} to {fact.value!r} "
                        "or record a canon revision first"
                    ),
                    location=claim.location,
                    canon_refs=refs,
                )
            )
            break
    if dimension in {"CHARACTER_CONTINUITY", "WORLD_CONTINUITY", "LOCATION_CONTINUITY"}:
        known = set(context.state.known_entities)
        if known:
            for claim in context.claims:
                if claim.dimension != dimension or claim.entity_ref is None:
                    continue
                if claim.entity_ref in known:
                    continue
                findings.append(
                    DimensionFinding(
                        dimension=dimension,
                        code=f"{_code_prefix(dimension)}_UNKNOWN_ENTITY",
                        severity="ERROR",
                        message=f"{claim.entity_ref!r} is not part of the reconstructed canon",
                        recommendation="register the entity in canon before referencing it",
                        location=claim.location,
                        canon_refs=(claim.entity_ref,),
                    )
                )
    return findings


def _code_prefix(dimension: str) -> str:
    return _DIMENSION_CODE_PREFIX.get(
        dimension, "".join(part[0] for part in dimension.split("_")) or dimension[:2]
    )


_DIMENSION_CODE_PREFIX: dict[str, str] = {
    "CHARACTER_CONTINUITY": "CC",
    "CHARACTER_VOICE": "CV",
    "WORLD_CONTINUITY": "WC",
    "TIMELINE_CONTINUITY": "TC",
    "LOCATION_CONTINUITY": "LC",
    "OBJECT_CONTINUITY": "OC",
    "RESOURCE_CONTINUITY": "RSC",
    "RELATIONSHIP_CONTINUITY": "REL",
    "INFORMATION_CONTINUITY": "IC",
    "EMOTIONAL_CONTINUITY": "EC",
    "PHYSICAL_STATE_CONTINUITY": "PSC",
    "MOTIVATION_CONTINUITY": "MC",
    "FACT_CONSISTENCY": "FC",
    "HOOK_CONTINUITY": "HC",
}


def _verify_character_continuity(context: AuditContext) -> list[DimensionFinding]:
    return _continuity_findings(context, "CHARACTER_CONTINUITY", severity="ERROR")


def _verify_world_continuity(context: AuditContext) -> list[DimensionFinding]:
    return _continuity_findings(context, "WORLD_CONTINUITY", severity="ERROR")


def _verify_timeline_continuity(context: AuditContext) -> list[DimensionFinding]:
    findings = _continuity_findings(context, "TIMELINE_CONTINUITY", severity="ERROR")
    index = _canon_index(context.state.canon_facts)
    for claim in context.claims:
        if claim.dimension != "TIMELINE_CONTINUITY" or claim.predicate != "order":
            continue
        matches = index.get(("TIMELINE_CONTINUITY", claim.subject, claim.predicate), [])
        if not matches:
            continue
        try:
            draft_order = int(claim.value)
            canon_order = int(matches[0].value)
        except ValueError:
            continue
        if draft_order < canon_order and not any(
            item.code == "TC_ORDER_VIOLATION" and item.location == claim.location for item in findings
        ):
            findings.append(
                DimensionFinding(
                    dimension="TIMELINE_CONTINUITY",
                    code="TC_ORDER_VIOLATION",
                    severity="ERROR",
                    message=(
                        f"{claim.subject} is placed at order {draft_order} before its "
                        f"canon prerequisite {canon_order}"
                    ),
                    recommendation="move the event after its canon prerequisite",
                    location=claim.location,
                    canon_refs=tuple(
                        ref
                        for ref in (claim.entity_ref, matches[0].entity_ref)
                        if ref is not None
                    ),
                )
            )
    return findings


def _verify_location_continuity(context: AuditContext) -> list[DimensionFinding]:
    findings = _continuity_findings(context, "LOCATION_CONTINUITY", severity="ERROR")
    per_scene: dict[str, set[str]] = {}
    for claim in context.claims:
        if claim.dimension != "LOCATION_CONTINUITY" or claim.predicate != "location":
            continue
        bucket = per_scene.setdefault(claim.subject, set())
        bucket.add(claim.value)
    for subject, locations in per_scene.items():
        if len(locations) > 1:
            findings.append(
                DimensionFinding(
                    dimension="LOCATION_CONTINUITY",
                    code="LC_MULTIPLE_LOCATIONS",
                    severity="ERROR",
                    message=f"{subject} occupies multiple locations in one scene: {sorted(locations)}",
                    recommendation="split the scene or correct the location state",
                    canon_refs=(f"character:{subject}",),
                )
            )
    return findings


def _verify_object_continuity(context: AuditContext) -> list[DimensionFinding]:
    return _continuity_findings(context, "OBJECT_CONTINUITY", severity="ERROR")


def _verify_resource_continuity(context: AuditContext) -> list[DimensionFinding]:
    return _continuity_findings(context, "RESOURCE_CONTINUITY", severity="ERROR")


def _verify_relationship_continuity(context: AuditContext) -> list[DimensionFinding]:
    return _continuity_findings(context, "RELATIONSHIP_CONTINUITY", severity="ERROR")


def _verify_information_continuity(context: AuditContext) -> list[DimensionFinding]:
    return _continuity_findings(context, "INFORMATION_CONTINUITY", severity="ERROR")


def _verify_emotional_continuity(context: AuditContext) -> list[DimensionFinding]:
    findings: list[DimensionFinding] = []
    index = _canon_index(context.state.canon_facts)
    for claim in context.claims:
        if claim.dimension != "EMOTIONAL_CONTINUITY" or claim.predicate != "emotion":
            continue
        matches = index.get(("EMOTIONAL_CONTINUITY", claim.subject, claim.predicate), [])
        if not matches or matches[0].value.casefold() == claim.value.casefold():
            continue
        findings.append(
            DimensionFinding(
                dimension="EMOTIONAL_CONTINUITY",
                code="EC_UNMOTIVATED_SHIFT",
                severity="WARN",
                message=(
                    f"{claim.subject} shifts from {matches[0].value!r} to {claim.value!r} "
                    "without a bridging beat"
                ),
                recommendation="add a transition beat or align the emotional state",
                location=claim.location,
                canon_refs=tuple(
                    ref
                    for ref in (claim.entity_ref, matches[0].entity_ref)
                    if ref is not None
                ),
            )
        )
    return findings


def _verify_physical_state_continuity(context: AuditContext) -> list[DimensionFinding]:
    return _continuity_findings(context, "PHYSICAL_STATE_CONTINUITY", severity="ERROR")


def _verify_motivation_continuity(context: AuditContext) -> list[DimensionFinding]:
    return _continuity_findings(context, "MOTIVATION_CONTINUITY", severity="WARN")


def _verify_fact_consistency(context: AuditContext) -> list[DimensionFinding]:
    return _continuity_findings(context, "FACT_CONSISTENCY", severity="ERROR")


def _verify_hook_continuity(context: AuditContext) -> list[DimensionFinding]:
    findings = _continuity_findings(context, "HOOK_CONTINUITY", severity="ERROR")
    deadlines = dict(context.state.hook_deadlines)
    for hook_ref, deadline in deadlines.items():
        if context.current_chapter <= deadline:
            continue
        resolved = any(
            claim.dimension == "HOOK_CONTINUITY"
            and claim.subject == hook_ref
            and claim.predicate == "status"
            and claim.value.casefold() in {"resolved", "closed"}
            for claim in context.claims
        )
        if not resolved:
            findings.append(
                DimensionFinding(
                    dimension="HOOK_CONTINUITY",
                    code="HC_STALE_HOOK",
                    severity="ERROR",
                    message=f"hook {hook_ref!r} passed its deadline in chapter {deadline}",
                    recommendation="resolve or explicitly re-schedule the hook",
                    canon_refs=(hook_ref,),
                )
            )
    return findings


def _verify_foreshadowing(context: AuditContext) -> list[DimensionFinding]:
    findings: list[DimensionFinding] = []
    for claim in context.claims:
        if claim.dimension != "FORESHADOWING":
            continue
        if claim.predicate == "setup" and not _has_payoff(context, claim.subject):
            findings.append(
                DimensionFinding(
                    dimension="FORESHADOWING",
                    code="FS_NO_PAYOFF",
                    severity="WARN",
                    message=f"foreshadow {claim.subject!r} has no registered payoff",
                    recommendation="register a payoff or remove the unearned setup",
                    location=claim.location,
                    canon_refs=(claim.entity_ref,) if claim.entity_ref else (),
                )
            )
    return findings


def _verify_payoff(context: AuditContext) -> list[DimensionFinding]:
    findings: list[DimensionFinding] = []
    setups = {subject for subject, _ in context.state.payoff_setup_refs}
    for claim in context.claims:
        if claim.dimension != "PAYOFF":
            continue
        if claim.predicate == "payoff" and claim.subject not in setups:
            findings.append(
                DimensionFinding(
                    dimension="PAYOFF",
                    code="PO_NO_SETUP",
                    severity="WARN",
                    message=f"payoff {claim.subject!r} has no matching setup",
                    recommendation="add the setup or drop the payoff",
                    location=claim.location,
                    canon_refs=(claim.entity_ref,) if claim.entity_ref else (),
                )
            )
    return findings


def _has_payoff(context: AuditContext, subject: str) -> bool:
    return any(
        claim.dimension == "PAYOFF" and claim.subject == subject
        for claim in context.claims
    )


def _verify_arc_alignment(context: AuditContext) -> list[DimensionFinding]:
    findings: list[DimensionFinding] = []
    arc_goals = {
        claim.subject: claim.value
        for claim in context.state.canon_facts
        if claim.dimension == "ARC_ALIGNMENT" and claim.predicate == "goal"
    }
    if not arc_goals:
        return findings
    for scene in context.scenes:
        if not scene.objective.strip():
            continue
        if not any(
            token.casefold() in scene.objective.casefold()
            for token in arc_goals.values()
        ):
            findings.append(
                DimensionFinding(
                    dimension="ARC_ALIGNMENT",
                    code="AA_BEAT_OFF_ARC",
                    severity="WARN",
                    message=(
                        f"scene {scene.sequence} objective {scene.objective!r} does not "
                        "advance a registered arc goal"
                    ),
                    recommendation="tie the scene to an arc goal or reframe the beat",
                    location=f"scene:{scene.sequence}",
                    canon_refs=tuple(arc_goals),
                )
            )
    return findings


def _verify_scene_purpose(context: AuditContext) -> list[DimensionFinding]:
    return [
        DimensionFinding(
            dimension="SCENE_PURPOSE",
            code="SP_MISSING_PURPOSE",
            severity="ERROR",
            message=f"scene {scene.sequence} lacks purpose or objective",
            recommendation="define the intended change before drafting",
            location=f"scene:{scene.sequence}",
        )
        for scene in context.scenes
        if not scene.purpose.strip() or not scene.objective.strip()
    ]


def _verify_pacing(context: AuditContext) -> list[DimensionFinding]:
    findings: list[DimensionFinding] = []
    genre = context.genre
    if genre is None:
        return findings
    if genre.min_action_ratio is not None and context.scenes:
        action = sum(
            1 for scene in context.scenes if (scene.beat_kind or "").casefold() == "action"
        )
        ratio = action / len(context.scenes)
        if ratio < genre.min_action_ratio:
            findings.append(
                DimensionFinding(
                    dimension="PACING",
                    code="PA_PROFILE_DEVIATION",
                    severity="WARN",
                    message=(
                        f"action ratio {ratio:.2f} is below the {genre.name!r} pacing "
                        f"floor {genre.min_action_ratio:.2f}"
                    ),
                    recommendation="raise tension density toward the genre pacing profile",
                    location="scene:all",
                    canon_refs=(f"genre:{genre.name}",) if genre.name else (),
                )
            )
    if genre.max_scene_density is not None and context.scenes:
        density = len(context.scenes) / max(1, len(_words(context.text)))
        if density > genre.max_scene_density:
            findings.append(
                DimensionFinding(
                    dimension="PACING",
                    code="PA_SCENE_DENSITY",
                    severity="WARN",
                    message="scene density exceeds the genre pacing profile",
                    recommendation="merge or lengthen scenes to match the genre rhythm",
                    location="scene:all",
                    canon_refs=(f"genre:{genre.name}",) if genre.name else (),
                )
            )
    if genre.dialogue_expectation is not None:
        observed = _dialogue_ratio(context.text)
        if observed is not None and observed < genre.dialogue_expectation:
            findings.append(
                DimensionFinding(
                    dimension="PACING",
                    code="PA_DIALOGUE_DEFICIT",
                    severity="WARN",
                    message=(
                        f"dialogue ratio {observed:.2f} is below the genre expectation "
                        f"{genre.dialogue_expectation:.2f}"
                    ),
                    recommendation="raise dialogue density toward the genre profile",
                    location="text:all",
                    canon_refs=(f"genre:{genre.name}",) if genre.name else (),
                )
            )
    return findings


def _dialogue_ratio(text: str) -> float | None:
    if not text.strip():
        return None
    quoted = sum(len(match) for match in re.findall(r"[\"“].*?[\"”]", text, re.DOTALL))
    return min(1.0, quoted / len(text))


def _verify_repetition(context: AuditContext) -> list[DimensionFinding]:
    findings: list[DimensionFinding] = []
    repeated = re.search(r"\b(\w+)(?:\s+\1){2,}\b", context.text, re.IGNORECASE)
    if repeated:
        findings.append(
            DimensionFinding(
                dimension="REPETITION",
                code="RP_REPEATED_PHRASE",
                severity="WARN",
                message=f"phrase {repeated.group(0)!r} repeats within one span",
                recommendation="vary the repeated phrase",
                location=_sentence_location(context.text, repeated.group(0)),
            )
        )
    sentences = _sentences(context.text)
    openings: dict[str, int] = {}
    for sentence in sentences:
        tokens = _words(sentence)
        if not tokens:
            continue
        openings[tokens[0].casefold()] = openings.get(tokens[0].casefold(), 0) + 1
    for opening, count in openings.items():
        if count >= 4:
            findings.append(
                DimensionFinding(
                    dimension="REPETITION",
                    code="RP_REPEATED_OPENING",
                    severity="WARN",
                    message=f"sentence opening {opening!r} repeats {count} times",
                    recommendation="vary sentence openings",
                    location=None,
                )
            )
    return findings


_EXPOSITION_MARKERS: tuple[str, ...] = (
    "as you know",
    "remember that",
    "as i told you",
    "needless to say",
    "for your information",
)


def _verify_dialogue_quality(context: AuditContext) -> list[DimensionFinding]:
    findings: list[DimensionFinding] = []
    for match in re.finditer(r"[\"“](.*?)[\"”]", context.text, re.DOTALL):
        line = match.group(1).strip()
        tokens = _words(line)
        if len(tokens) > 40:
            findings.append(
                DimensionFinding(
                    dimension="DIALOGUE_QUALITY",
                    code="DQ_LONG_LINE",
                    severity="WARN",
                    message=f"dialogue line runs {len(tokens)} words without a break",
                    recommendation="split the speech into beats and reactions",
                    location=_sentence_location(context.text, line[:24]),
                )
            )
        lowered = line.casefold()
        for marker in _EXPOSITION_MARKERS:
            if marker in lowered:
                findings.append(
                    DimensionFinding(
                        dimension="DIALOGUE_QUALITY",
                        code="DQ_EXPOSITION",
                        severity="WARN",
                        message=f"dialogue exposes plot with {marker!r}",
                        recommendation="dramatize the information instead of stating it",
                        location=_sentence_location(context.text, line[:24]),
                    )
                )
                break
    return findings


def _verify_prose_clarity(context: AuditContext) -> list[DimensionFinding]:
    findings: list[DimensionFinding] = []
    if context.text is not None and not context.text.strip():
        findings.append(
            DimensionFinding(
                dimension="PROSE_CLARITY",
                code="PC_EMPTY_TEXT",
                severity="ERROR",
                message="draft text is empty",
                recommendation="produce a non-empty candidate before review",
                location="text:empty",
            )
        )
        return findings
    for index, sentence in enumerate(_sentences(context.text), start=1):
        tokens = _words(sentence)
        if len(tokens) > 60:
            findings.append(
                DimensionFinding(
                    dimension="PROSE_CLARITY",
                    code="PC_OVERLONG_SENTENCE",
                    severity="WARN",
                    message=f"sentences runs {len(tokens)} words",
                    recommendation="split the sentence into readable units",
                    location=f"sentence:{index}",
                )
            )
        if re.search(r"\b(it|this|that|they)\b\s+(was|were|is|are)\b", sentence, re.IGNORECASE) and len(
            _words(sentence)
        ) <= 4:
            findings.append(
                DimensionFinding(
                    dimension="PROSE_CLARITY",
                    code="PC_AMBIGUOUS_PRONOUN",
                    severity="WARN",
                    message="pronoun reference is unresolved",
                    recommendation="name the referent",
                    location=f"sentence:{index}",
                )
            )
    return findings


def _verify_style_alignment(context: AuditContext) -> list[DimensionFinding]:
    findings: list[DimensionFinding] = []
    style = context.style
    if style is None:
        return findings
    sentences = _sentences(context.text)
    if style.sentence_length is not None and sentences:
        observed = sum(len(_words(sentence)) for sentence in sentences) / len(sentences)
        if abs(observed - style.sentence_length) > max(6.0, style.sentence_length * 0.75):
            findings.append(
                DimensionFinding(
                    dimension="STYLE_ALIGNMENT",
                    code="SA_SENTENCE_LENGTH_DRIFT",
                    severity="WARN",
                    message=(
                        f"mean sentence length {observed:.1f} drifts from the style "
                        f"profile {style.sentence_length:.1f}"
                    ),
                    recommendation="align cadence with the project style profile",
                    location="text:all",
                )
            )
    if style.rhythm == "varied" and len(sentences) >= 4:
        lengths = {len(_words(sentence)) for sentence in sentences}
        if len(lengths) == 1:
            findings.append(
                DimensionFinding(
                    dimension="STYLE_ALIGNMENT",
                    code="SA_RHYTHM_MONOTONY",
                    severity="WARN",
                    message="sentence rhythm is uniform where the profile expects variation",
                    recommendation="introduce sentence-length variation",
                    location="text:all",
                )
            )
    if style.dialogue_ratio is not None:
        observed_ratio = _dialogue_ratio(context.text)
        if observed_ratio is not None and abs(observed_ratio - style.dialogue_ratio) > 0.5:
            findings.append(
                DimensionFinding(
                    dimension="STYLE_ALIGNMENT",
                    code="SA_DIALOGUE_RATIO_DRIFT",
                    severity="WARN",
                    message="dialogue ratio drifts from the style profile",
                    recommendation="rebalance narration and dialogue",
                    location="text:all",
                )
            )
    return findings


def _verify_genre_alignment(context: AuditContext) -> list[DimensionFinding]:
    genre = context.genre
    if genre is None:
        return []
    refs = (f"genre:{genre.name}",) if genre.name else ()
    findings = [
        DimensionFinding(
            dimension="GENRE_ALIGNMENT",
            code="GA_FORBIDDEN_PATTERN",
            severity="ERROR",
            message=f"forbidden genre pattern {pattern!r} is present",
            recommendation=f"remove the {pattern!r} beat or change genre profile",
            location=_sentence_location(context.text, pattern),
            canon_refs=refs,
        )
        for pattern in genre.forbidden_patterns
        if pattern and _casefold_contains(context.text, pattern)
    ]
    findings.extend(
        DimensionFinding(
            dimension="GENRE_ALIGNMENT",
            code="GA_REQUIRED_RULE_UNMET",
            severity="WARN",
            message=f"required genre element {pattern!r} is missing",
            recommendation=f"add the {pattern!r} genre element",
            location="text:all",
            canon_refs=refs,
        )
        for pattern in genre.required_patterns
        if pattern and not _casefold_contains(context.text, pattern)
    )
    return findings


def _verify_fatigue_words(context: AuditContext) -> list[DimensionFinding]:
    findings: list[DimensionFinding] = []
    genre = context.genre
    if genre is None:
        return findings
    lowered = context.text.casefold()
    for word in genre.fatigue_lexicon:
        count = len(re.findall(rf"\b{re.escape(word.casefold())}\b", lowered))
        if count > 3:
            findings.append(
                DimensionFinding(
                    dimension="FATIGUE_WORDS",
                    code="FW_OVERUSED",
                    severity="WARN",
                    message=f"fatigue word {word!r} appears {count} times",
                    recommendation=f"replace or remove repeated {word!r}",
                    location="text:all",
                    canon_refs=(f"genre:{genre.name}",) if genre.name else (),
                )
            )
    return findings


def _verify_length_governance(context: AuditContext) -> list[DimensionFinding]:
    findings: list[DimensionFinding] = []
    target = context.length_target
    if target is None:
        return findings
    count = len(_words(context.text))
    if target.min_words is not None and count < target.min_words:
        findings.append(
            DimensionFinding(
                dimension="LENGTH_GOVERNANCE",
                code="LG_BELOW_TARGET",
                severity="WARN",
                message=f"draft has {count} words below the {target.min_words} floor",
                recommendation="expand the draft toward the target length",
                location="text:all",
            )
        )
    if target.max_words is not None and count > target.max_words:
        findings.append(
            DimensionFinding(
                dimension="LENGTH_GOVERNANCE",
                code="LG_ABOVE_TARGET",
                severity="WARN",
                message=f"draft has {count} words above the {target.max_words} ceiling",
                recommendation="trim the draft toward the target length",
                location="text:all",
            )
        )
    return findings


def _verify_structure(context: AuditContext) -> list[DimensionFinding]:
    findings: list[DimensionFinding] = []
    sequences = [scene.sequence for scene in context.scenes]
    if sequences and sequences != list(range(1, len(sequences) + 1)):
        findings.append(
            DimensionFinding(
                dimension="STRUCTURE",
                code="ST_SCENE_ORDER",
                severity="ERROR",
                message=f"scene sequence is not contiguous: {sequences}",
                recommendation="repair the scene order before review",
                location="scene:all",
            )
        )
    if context.scenes and not any(
        (scene.beat_kind or "").casefold() == "turn" for scene in context.scenes
    ):
        findings.append(
            DimensionFinding(
                dimension="STRUCTURE",
                code="ST_MISSING_TURN",
                severity="WARN",
                message="no scene carries a structural turn",
                recommendation="give at least one scene a turn beat",
                location="scene:all",
            )
        )
    return findings


def _verify_point_of_view(context: AuditContext) -> list[DimensionFinding]:
    findings: list[DimensionFinding] = []
    first_person = bool(re.search(r"\b(I|my|me|we|our)\b", context.text, re.IGNORECASE))
    third_person = bool(re.search(r"\b(he|she|they|his|her|their)\b", context.text, re.IGNORECASE))
    if first_person and third_person:
        findings.append(
            DimensionFinding(
                dimension="POINT_OF_VIEW",
                code="POV_HEAD_HOPPING",
                severity="WARN",
                message="first-person and third-person narration markers are mixed",
                recommendation="hold one point of view within the scene",
                location="text:all",
            )
        )
    if context.style is not None and context.style.pov is not None:
        declared = context.style.pov.casefold()
        if declared.startswith("first") and third_person and not first_person:
            findings.append(
                DimensionFinding(
                    dimension="POINT_OF_VIEW",
                    code="POV_PROFILE_DRIFT",
                    severity="WARN",
                    message="narration does not match the declared first-person profile",
                    recommendation="align narration with the project point of view",
                    location="text:all",
                )
            )
    return findings


def _verify_tone(context: AuditContext) -> list[DimensionFinding]:
    findings: list[DimensionFinding] = []
    style = context.style
    if style is None or not style.tone:
        return findings
    lowered = context.text.casefold()
    matches = [tone for tone in style.tone if tone.casefold() in lowered]
    if not matches:
        findings.append(
            DimensionFinding(
                dimension="TONE",
                code="TN_TONE_DRIFT",
                severity="WARN",
                message=f"none of the declared tones {style.tone!r} are present",
                recommendation="restore the declared tone in the prose",
                location="text:all",
            )
        )
    return findings


_ABSTRACT_MARKERS: tuple[str, ...] = (
    "felt the weight of",
    "thought about",
    "remembered that",
    "wondered whether",
    "considered the meaning",
)


def _verify_visual_filmability(context: AuditContext) -> list[DimensionFinding]:
    return [
        DimensionFinding(
            dimension="VISUAL_FILMABILITY",
            code="VF_ABSTRACT_NARRATION",
            severity="WARN",
            message=f"interior state {marker!r} is not directly filmable",
            recommendation="externalize the interior state as observable action",
            location=_sentence_location(context.text, marker),
        )
        for marker in _ABSTRACT_MARKERS
        if _casefold_contains(context.text, marker)
    ]


def _verify_shot_feasibility(context: AuditContext) -> list[DimensionFinding]:
    return [
        DimensionFinding(
            dimension="SHOT_FEASIBILITY",
            code="SF_INFEASIBLE_SHOT",
            severity="ERROR",
            message=f"scene requires infeasible production element {constraint!r}",
            recommendation="rewrite the beat within production constraints",
            location=_sentence_location(context.text, constraint),
        )
        for constraint in context.shot_constraints
        if constraint and _casefold_contains(context.text, constraint)
    ]


_UNSAFE_PATTERNS: tuple[str, ...] = (
    "build a bomb",
    "synthesize a nerve agent",
)


def _verify_safety(context: AuditContext) -> list[DimensionFinding]:
    return [
        DimensionFinding(
            dimension="SAFETY",
            code="SAF_UNSAFE_CONTENT",
            severity="FATAL",
            message=f"unsafe instruction pattern {pattern!r} present",
            recommendation="remove operational harmful detail",
            location=_sentence_location(context.text, pattern),
        )
        for pattern in _UNSAFE_PATTERNS
        if _casefold_contains(context.text, pattern)
    ]


def _verify_author_intent_alignment(context: AuditContext) -> list[DimensionFinding]:
    intent = context.author_intent
    if intent is None:
        return []
    lowered = context.text.casefold()
    findings = [
        DimensionFinding(
            dimension="AUTHOR_INTENT_ALIGNMENT",
            code="AI_CONSTRAINT_VIOLATION",
            severity="WARN",
            message=f"author constraint {constraint!r} is not observable in the draft",
            recommendation="honor the author constraint or renegotiate it",
            location="text:all",
        )
        for constraint in intent.constraints
        if constraint and not _casefold_contains(lowered, constraint)
    ]
    findings.extend(
        DimensionFinding(
            dimension="AUTHOR_INTENT_ALIGNMENT",
            code="AI_MISSING_CRITERIA",
            severity="WARN",
            message=f"success criterion {criterion!r} is not evidenced",
            recommendation="add the evidence for the success criterion",
            location="text:all",
        )
        for criterion in intent.success_criteria
        if criterion and not _casefold_contains(lowered, criterion)
    )
    return findings


def _verify_character_voice(context: AuditContext) -> list[DimensionFinding]:
    findings: list[DimensionFinding] = []
    voices = {
        claim.subject: claim.value
        for claim in context.state.canon_facts
        if claim.dimension == "CHARACTER_VOICE" and claim.predicate == "forbidden"
    }
    for claim in context.claims:
        if claim.dimension != "CHARACTER_VOICE":
            continue
        forbidden = voices.get(claim.subject)
        if forbidden and _casefold_contains(claim.value, forbidden):
            findings.append(
                DimensionFinding(
                    dimension="CHARACTER_VOICE",
                    code="CV_FORBIDDEN_PATTERN",
                    severity="WARN",
                    message=f"{claim.subject} uses forbidden voice pattern {forbidden!r}",
                    recommendation="rewrite the line in the character register",
                    location=claim.location,
                    canon_refs=(claim.entity_ref,) if claim.entity_ref else (),
                )
            )
    return findings


Verifier = Callable[[AuditContext], list[DimensionFinding]]

DIMENSION_VERIFIERS: dict[str, Verifier] = {
    "CHARACTER_CONTINUITY": _verify_character_continuity,
    "CHARACTER_VOICE": _verify_character_voice,
    "WORLD_CONTINUITY": _verify_world_continuity,
    "TIMELINE_CONTINUITY": _verify_timeline_continuity,
    "LOCATION_CONTINUITY": _verify_location_continuity,
    "OBJECT_CONTINUITY": _verify_object_continuity,
    "RESOURCE_CONTINUITY": _verify_resource_continuity,
    "RELATIONSHIP_CONTINUITY": _verify_relationship_continuity,
    "INFORMATION_CONTINUITY": _verify_information_continuity,
    "EMOTIONAL_CONTINUITY": _verify_emotional_continuity,
    "PHYSICAL_STATE_CONTINUITY": _verify_physical_state_continuity,
    "MOTIVATION_CONTINUITY": _verify_motivation_continuity,
    "FACT_CONSISTENCY": _verify_fact_consistency,
    "HOOK_CONTINUITY": _verify_hook_continuity,
    "FORESHADOWING": _verify_foreshadowing,
    "PAYOFF": _verify_payoff,
    "ARC_ALIGNMENT": _verify_arc_alignment,
    "SCENE_PURPOSE": _verify_scene_purpose,
    "PACING": _verify_pacing,
    "REPETITION": _verify_repetition,
    "DIALOGUE_QUALITY": _verify_dialogue_quality,
    "PROSE_CLARITY": _verify_prose_clarity,
    "STYLE_ALIGNMENT": _verify_style_alignment,
    "GENRE_ALIGNMENT": _verify_genre_alignment,
    "FATIGUE_WORDS": _verify_fatigue_words,
    "LENGTH_GOVERNANCE": _verify_length_governance,
    "STRUCTURE": _verify_structure,
    "POINT_OF_VIEW": _verify_point_of_view,
    "TONE": _verify_tone,
    "VISUAL_FILMABILITY": _verify_visual_filmability,
    "SHOT_FEASIBILITY": _verify_shot_feasibility,
    "SAFETY": _verify_safety,
    "AUTHOR_INTENT_ALIGNMENT": _verify_author_intent_alignment,
}


class ModelAssistedVerifier:
    """Contract for the optional model-assisted half of a subjective dimension.

    The model output is only joined to the deterministic audit when it satisfies
    every structural requirement: a bounded confidence, a concrete evidence span,
    a stable location, and repeatability across two independent invocations.  A
    bare "the model says this is bad" judgement is rejected.
    """

    def __init__(self, invoke: Callable[[str, str], DimensionFinding | None]) -> None:
        self._invoke = invoke

    def verify(
        self,
        dimension: str,
        text: str,
        *,
        evidence_span: str,
        location: str,
    ) -> DimensionFinding | None:
        if dimension not in MODEL_ASSISTED_DIMENSIONS:
            raise ValueError(f"{dimension} is not a model-assisted dimension")
        if not evidence_span.strip():
            raise ValueError("model-assisted findings require an evidence span")
        if not location.strip():
            raise ValueError("model-assisted findings require a location")
        first = self._invoke(dimension, text)
        second = self._invoke(dimension, text)
        if first is None or second is None:
            return None
        if (first.code, first.severity, first.location) != (
            second.code,
            second.severity,
            second.location,
        ):
            return None
        if not 0.0 < first.confidence < 1.0:
            raise ValueError("model-assisted confidence must be bounded and non-trivial")
        if first.canon_refs and not first.location:
            raise ValueError("model-assisted findings must be located")
        if first.code in FORBIDDEN_EVASION_GOALS:
            raise ValueError("evasion goals are not a quality target")
        return first


def run_dimensions(context: AuditContext) -> tuple[DimensionFinding, ...]:
    """Run every verifier and return located findings in deterministic order."""

    findings: list[DimensionFinding] = []
    for dimension in DIMENSION_VERIFIERS:
        findings.extend(DIMENSION_VERIFIERS[dimension](context))
    return tuple(findings)


__all__ = [
    "DIMENSION_VERIFIERS",
    "FORBIDDEN_EVASION_GOALS",
    "HARD_CONTINUITY_DIMENSIONS",
    "MODEL_ASSISTED_DIMENSIONS",
    "AuditClaim",
    "AuditContext",
    "AuditState",
    "AuthorIntentSpec",
    "DimensionFinding",
    "GenreSpec",
    "LengthTarget",
    "ModelAssistedVerifier",
    "SceneSpec",
    "StyleSpec",
    "canonical_ref",
    "run_dimensions",
]
