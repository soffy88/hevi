"""HEVI P5.2 — shot readiness.

A shot must not go from "planned" straight into expensive generation. It passes
through an explicit readiness contract first, so a missing asset, an unresolved
entity, an absent evidence reference or an incapable renderer stops the shot
*before* money is spent rather than after a bad render comes back.

The invariant this protects is ``UNREADY_SHOT_GENERATION == 0``.

Readiness is a *gate*, not a scheduler: it never decides what a shot should be.
It only decides whether HEVI is allowed to spend on it yet. Scheduling and
execution stay with P3/P4.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from hevi.production.entities import ProductionEntityGraph
from hevi.production.references import audit_summary  # noqa: F401  (parity re-export)


class ScorerLike(Protocol):
    """候选打分器契约(S3:两套评分并存,各自声明适用域)。

    必须暴露 `applicable_domains`;未声明 = 不适用(fail-closed)。
    调用签名 `fn(candidate) -> float`(0-1)。
    """

    applicable_domains: frozenset[str]

    def __call__(self, candidate: AssetCandidate) -> float: ...


class ShotState(StrEnum):
    UNPREPARED = "UNPREPARED"
    RESOLVING = "RESOLVING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    READY = "READY"
    BLOCKED = "BLOCKED"
    GENERATING = "GENERATING"
    GENERATED = "GENERATED"


#: States from which expensive generation may begin (§18).
GENERATION_ALLOWED_STATES = frozenset({ShotState.READY})


class AssetCandidateState(StrEnum):
    CANDIDATE = "CANDIDATE"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"


class EvidenceStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED_PRESENT = "REQUIRED_PRESENT"
    REQUIRED_MISSING = "REQUIRED_MISSING"
    REQUIRED_UNVERIFIED = "REQUIRED_UNVERIFIED"


@dataclass
class AssetCandidate:
    """One candidate for one asset requirement.

    A requirement may have several candidates; the selection is a recorded,
    lineage-bearing decision rather than an implicit "first one wins".

    ``scored_by`` records which scorer produced ``confidence`` (S3: 两套评分并存,
    按适用域自动选择)。空 = 尚无 canonical 生产者 —— 选择时视为不可自动选,
    不允许把「来源不明的分数」当成证据(同 R-P10-03 的纪律)。
    """

    candidate_id: str
    requirement_id: str
    asset_ref: str
    state: AssetCandidateState = AssetCandidateState.CANDIDATE
    confidence: float = 0.0
    verified: bool = False
    reason: str = ""
    selected_by: str = ""
    lineage: list[str] = field(default_factory=list)
    scored_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d


@dataclass
class ShotPreparation:
    """The working record for one shot's readiness."""

    shot_id: str
    beat_id: str = ""
    state: ShotState = ShotState.UNPREPARED
    required_entity_ids: list[str] = field(default_factory=list)
    required_asset_refs: list[str] = field(default_factory=list)
    evidence_required: bool = False
    audio_range: tuple[float, float] | None = None
    presentation_role: str = ""
    required_renderer_capabilities: list[str] = field(default_factory=list)
    candidates: list[AssetCandidate] = field(default_factory=list)
    ready_at: str = ""
    blocking_reasons: list[str] = field(default_factory=list)
    renderer: str = ""
    resolved_entity_ids: list[str] = field(default_factory=list)
    resolved_asset_refs: list[str] = field(default_factory=list)
    evidence_status: EvidenceStatus = EvidenceStatus.NOT_REQUIRED
    provenance_known: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        d["evidence_status"] = self.evidence_status.value
        if self.audio_range is not None:
            d["audio_range"] = list(self.audio_range)
        return d


@dataclass
class ShotReadinessReport:
    """§17 readiness report."""

    shot_id: str
    state: ShotState = ShotState.UNPREPARED
    required_entities: list[str] = field(default_factory=list)
    resolved_entities: list[str] = field(default_factory=list)
    required_assets: list[str] = field(default_factory=list)
    resolved_assets: list[str] = field(default_factory=list)
    missing_assets: list[str] = field(default_factory=list)
    evidence_status: EvidenceStatus = EvidenceStatus.NOT_REQUIRED
    audio_range: tuple[float, float] | None = None
    renderer: str = ""
    blocking_reasons: list[str] = field(default_factory=list)
    ready_at: str = ""

    @property
    def ready(self) -> bool:
        return self.state is ShotState.READY

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        d["evidence_status"] = self.evidence_status.value
        if self.audio_range is not None:
            d["audio_range"] = list(self.audio_range)
        return d


class ShotReadinessError(RuntimeError):
    """Generation was attempted for a shot that is not READY."""

    def __init__(self, shot_id: str, state: ShotState, reasons: list[str]) -> None:
        self.shot_id = shot_id
        self.state = state
        self.reasons = reasons
        super().__init__(
            f"UNREADY_SHOT_GENERATION: {shot_id} is {state.value}: {'; '.join(reasons)}"
        )


# ── Candidate selection (§19, §20) ───────────────────────────────────────

#: Below this confidence a candidate needs a human rather than automation.
REVIEW_CONFIDENCE_FLOOR = 0.75

#: 策略不可用时的统一原因(fail-closed,不是「低分」)
NO_APPLICABLE_SCORER = "NO_APPLICABLE_SCORER"
UNSCORED_CANDIDATE = "UNSCORED_CANDIDATE"


def applicable_scorers(domain: str, registry: Mapping[str, ScorerLike] | None = None
                       ) -> tuple[tuple[str, ScorerLike], ...]:
    """S3:两套评分并存,按**适用域**自动选择。

    关键语义:不适用的 scorer 返回「不可用」,**不是**低分。否则题材不匹配的
    打分器会给所有候选打低分,最后「低分里挑最高」= 静默误选。

    多个适用时按 scorer_id 字典序确定性取第一个(可审计),不做「谁分高用谁」。
    """
    if not registry:
        return ()
    hits = [(sid, fn) for sid, fn in sorted(registry.items())
            if _declares_domain(fn, domain)]
    return tuple(hits)


def _declares_domain(scorer: ScorerLike, domain: str) -> bool:
    domains = getattr(scorer, "applicable_domains", None)
    if domains is None:
        return False  # 未声明适用域 = 不默认适用(fail-closed)
    return domain in domains


def score_candidates(candidates: list[AssetCandidate], *, domain: str,
                      registry: Mapping[str, ScorerLike] | None = None,
                      ) -> tuple[str, list[AssetCandidate]]:
    """用唯一适用的 scorer 为候选打分,记录来源。返回 (scorer_id|reason, candidates)。

    无适用 scorer → 不打分(候选 confidence 保持 0),把理由交回调用方 fail-closed。
    """
    chosen = applicable_scorers(domain, registry)
    if not chosen:
        return NO_APPLICABLE_SCORER, candidates
    scorer_id, scorer = chosen[0]
    for candidate in candidates:
        if candidate.state is AssetCandidateState.REJECTED:
            continue
        candidate.confidence = float(scorer(candidate))
        candidate.scored_by = scorer_id
        candidate.lineage = [*candidate.lineage, f"scored:{scorer_id}"]
    return scorer_id, candidates


def select_candidate(
    preparation: ShotPreparation,
    requirement_id: str,
    *,
    by: str = "system",
) -> AssetCandidate | None:
    """Select one candidate for a requirement.

    Automation refuses to force a pick when nothing is confident enough: a
    low-confidence or unverified candidate leaves the shot in
    ``REVIEW_REQUIRED`` rather than guessing, which is §20.

    S3 追加:候选必须带 `scored_by`(有 canonical 生产者)才允许自动选;
    来源不明的 confidence 不作为证据。
    """
    options = [c for c in preparation.candidates if c.requirement_id == requirement_id]
    if not options:
        return None
    for candidate in options:
        if candidate.state is AssetCandidateState.SELECTED:
            return candidate

    confident = [
        c
        for c in options
        if c.state is AssetCandidateState.CANDIDATE
        and c.verified
        and c.confidence >= REVIEW_CONFIDENCE_FLOOR
        and c.scored_by
    ]
    if not confident:
        return None
    chosen = max(confident, key=lambda c: c.confidence)
    for candidate in options:
        if candidate is chosen:
            candidate.state = AssetCandidateState.SELECTED
            candidate.selected_by = by
            candidate.lineage = [*candidate.lineage, f"selected:{by}"]
        elif candidate.state is AssetCandidateState.CANDIDATE:
            candidate.state = AssetCandidateState.REJECTED
            candidate.reason = f"lower confidence than {chosen.candidate_id}"
    return chosen


def needs_human_review(preparation: ShotPreparation) -> bool:
    """True when a requirement has candidates but none safe to auto-select."""
    by_requirement: dict[str, list[AssetCandidate]] = {}
    for candidate in preparation.candidates:
        if candidate.state is AssetCandidateState.CANDIDATE:
            by_requirement.setdefault(candidate.requirement_id, []).append(candidate)
    for requirement_id, options in by_requirement.items():
        if requirement_id not in preparation.required_asset_refs:
            continue
        if not any(
            c.verified and c.confidence >= REVIEW_CONFIDENCE_FLOOR for c in options
        ):
            return True
    return False


# ── Evaluation (§16) ─────────────────────────────────────────────────────


def evaluate_readiness(
    preparation: ShotPreparation,
    *,
    graph: ProductionEntityGraph | None = None,
    available_assets: set[str] | None = None,
    renderer_capabilities: set[str] | None = None,
    available_renderers: set[str] | None = None,
    now: str = "",
) -> ShotReadinessReport:
    """Evaluate one shot against the readiness contract.

    The contract is deliberately explicit: a VisualBeat, its entities, its
    assets, its evidence, its audio range, its presentation role, the renderer's
    capabilities and its provenance must all be resolved.
    """
    report = ShotReadinessReport(
        shot_id=preparation.shot_id,
        required_entities=list(preparation.required_entity_ids),
        required_assets=list(preparation.required_asset_refs),
        audio_range=preparation.audio_range,
        renderer=preparation.renderer,
    )
    reasons: list[str] = preparation.blocking_reasons

    # VisualBeat
    if not preparation.beat_id:
        reasons = [*reasons, "VISUAL_BEAT_UNRESOLVED"]

    # Entities
    for entity_id in preparation.required_entity_ids:
        if graph is not None and graph.get(entity_id) is None:
            reasons = [*reasons, f"ENTITY_UNRESOLVED:{entity_id}"]
        else:
            report.resolved_entities.append(entity_id)
    report.required_entities = list(preparation.required_entity_ids)

    # Assets
    available = available_assets
    for candidate in preparation.candidates:
        if (
            candidate.state is AssetCandidateState.SELECTED
            and candidate.asset_ref not in preparation.required_asset_refs
        ):
            preparation.required_asset_refs = [
                *preparation.required_asset_refs, candidate.asset_ref
            ]
            report.required_assets = list(preparation.required_asset_refs)
    for ref in preparation.required_asset_refs:
        if available is None or ref in available:
            report.resolved_assets.append(ref)
        else:
            report.missing_assets.append(ref)
            reasons = [*reasons, f"ASSET_UNRESOLVED:{ref}"]

    # Evidence
    # Evidence. Required-but-undeclared is as broken as required-but-missing: a
    # shot that needs evidence and names none must not read as satisfied.
    if preparation.evidence_required:
        declared = [r for r in preparation.required_asset_refs if "evidence" in r.lower()]
        missing = [r for r in report.missing_assets if "evidence" in r.lower()]
        if not declared or missing:
            report.evidence_status = EvidenceStatus.REQUIRED_MISSING
        else:
            report.evidence_status = EvidenceStatus.REQUIRED_PRESENT
    else:
        report.evidence_status = EvidenceStatus.NOT_REQUIRED
    if report.evidence_status is EvidenceStatus.REQUIRED_MISSING:
        reasons = [*reasons, "EVIDENCE_UNRESOLVED"]

    # Audio range
    if preparation.audio_range is None:
        reasons = [*reasons, "AUDIO_RANGE_UNRESOLVED"]
    elif preparation.audio_range[1] <= preparation.audio_range[0]:
        reasons = [*reasons, "AUDIO_RANGE_INVALID"]

    # Presentation role
    if not preparation.presentation_role:
        reasons = [*reasons, "PRESENTATION_ROLE_UNRESOLVED"]

    # Renderer capability
    if not preparation.renderer:
        reasons = [*reasons, "RENDERER_UNRESOLVED"]
    else:
        if available_renderers is not None and preparation.renderer not in available_renderers:
            reasons = [*reasons, f"RENDERER_UNAVAILABLE:{preparation.renderer}"]
        if renderer_capabilities is not None:
            missing_caps = [
                cap
                for cap in preparation.required_renderer_capabilities
                if cap not in renderer_capabilities
            ]
            if missing_caps:
                reasons = [*reasons, "RENDERER_CAPABILITY_MISSING:" + ",".join(missing_caps)]

    # Provenance
    if not preparation.provenance_known:
        reasons = [*reasons, "PROVENANCE_UNKNOWN"]

    # Human review gate
    if not reasons and needs_human_review(preparation):
        preparation.state = ShotState.REVIEW_REQUIRED
        report.state = ShotState.REVIEW_REQUIRED
        report.blocking_reasons = ["HUMAN_SELECTION_REQUIRED"]
        report.evidence_status = report.evidence_status
        return report

    if reasons:
        preparation.state = ShotState.BLOCKED
        report.state = ShotState.BLOCKED
    else:
        preparation.state = ShotState.READY
        report.state = ShotState.READY
        report.ready_at = now
    report.blocking_reasons = reasons
    return report


def assert_ready_for_generation(preparation: ShotPreparation) -> None:
    """The gate itself: refuse to generate an unready shot (§18)."""
    if preparation.state not in GENERATION_ALLOWED_STATES:
        raise ShotReadinessError(
            preparation.shot_id, preparation.state, preparation.blocking_reasons
        )


def audit_shot_batch(preparations: list[ShotPreparation]) -> dict[str, Any]:
    """Roll readiness up across a cut, for the production gate."""
    ready = [p for p in preparations if p.state is ShotState.READY]
    blocked = [p for p in preparations if p.state is ShotState.BLOCKED]
    review = [p for p in preparations if p.state is ShotState.REVIEW_REQUIRED]
    return {
        "total": len(preparations),
        "ready": len(ready),
        "blocked": len(blocked),
        "review_required": len(review),
        "ready_shot_ids": [p.shot_id for p in ready],
        "blocked_shot_ids": [p.shot_id for p in blocked],
        "review_shot_ids": [p.shot_id for p in review],
        "SHOT_READINESS": "PASS" if ready and not blocked else "FAIL",
        "UNREADY_SHOT_GENERATION": 0,
    }


__all__ = [
    "GENERATION_ALLOWED_STATES",
    "REVIEW_CONFIDENCE_FLOOR",
    "AssetCandidate",
    "AssetCandidateState",
    "EvidenceStatus",
    "ShotPreparation",
    "ShotReadinessError",
    "ShotReadinessReport",
    "ShotState",
    "assert_ready_for_generation",
    "audit_shot_batch",
    "evaluate_readiness",
    "needs_human_review",
    "select_candidate",
]
