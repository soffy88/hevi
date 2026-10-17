"""S1 DirectorBrief — the entry contract a director session is handed.

Authority boundary (S1 scope): the brief *references* existing authorities, it
owns none of them.
- Thesis / treatment / brief content is owned by the P10b objects; the brief pins
  their content hashes (`brief_ref`, `thesis_ref`, `treatment_ref`).
- Benchmark/reference extraction is owned by the P10b `BenchmarkSet`, pinned via
  `ReferencePack.benchmark_ref`.
- Lifecycle vocabulary is the P10a `Lifecycle`; the brief cannot mint its own.
- No agent, orchestrator, planner, or provider selection lives here: S1 is data +
  validation only, so S2+ stages can consume it without a second authority.

Constraint ledger is not duplicated: `constraints` reads through to the pack.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from hevi.creative.direction_state.state import Lifecycle
from hevi.creative.director_brief.codec import (
    as_dict,
    as_dict_list,
    as_int,
    as_str,
    as_str_tuple,
    canonical_hash,
    reject_unknown,
    require_keys,
)
from hevi.creative.director_brief.errors import DirectorBriefError
from hevi.creative.director_brief.reference_pack import (
    SEVERITY,
    Constraint,
    ConstraintStatus,
    ReferencePack,
)

SCHEMA = "hevi.director_brief.director_brief/1"

PRIORITY_DIMENSIONS = ("visual", "motion")
SOURCE_TYPES = ("user", "narrative", "imported")
PIN_RE = re.compile(r"^[0-9a-f]{64}$")

# P10a Lifecycle states a brief may itself be in; COMPILED..REVISION_PROPOSED
# belong to DirectionState and are not the brief's to claim.
BRIEF_DECISION_STATES = (Lifecycle.DRAFT, Lifecycle.PROPOSED, Lifecycle.REVIEW_REQUIRED,
                         Lifecycle.APPROVED)


@dataclass(frozen=True)
class SourceRef:
    """Where the direction request came from. Narrative direction must pin Canon."""

    type: str
    reference: str = ""
    content_hash: str = ""

    _FIELDS = ("type", "reference", "content_hash")

    def validate(self) -> None:
        if self.type not in SOURCE_TYPES:
            raise DirectorBriefError(f"bad source type {self.type!r}", code="BRIEF_BAD_SOURCE")
        if self.type == "narrative" and not self.reference:
            raise DirectorBriefError("narrative direction must pin a canon reference",
                                     code="BRIEF_CANON_UNPINNED")
        if self.type == "imported" and not PIN_RE.match(self.content_hash):
            raise DirectorBriefError("imported direction must carry its source content_hash",
                                     code="BRIEF_IMPORT_UNHASHED")

    def to_dict(self) -> dict[str, object]:
        return {"type": self.type, "reference": self.reference, "content_hash": self.content_hash}

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> SourceRef:
        reject_unknown(payload, cls._FIELDS, "source")
        require_keys(payload, ("type",), "source")
        return cls(type=as_str(payload, "type"), reference=as_str(payload, "reference"),
                   content_hash=as_str(payload, "content_hash"))


@dataclass(frozen=True)
class Priority:
    """A required visual or motion intent, anchored to at least one constraint."""

    id: str
    dimension: str
    statement: str
    required: str = "must"
    rationale: str = ""
    constraint_refs: tuple[str, ...] = ()
    reference_refs: tuple[str, ...] = ()

    _FIELDS = ("id", "dimension", "statement", "required", "rationale", "constraint_refs",
               "reference_refs")

    def validate(self) -> None:
        if not (self.id and self.statement):
            raise DirectorBriefError(f"priority {self.id or '?'}: id + statement required",
                                     code="PRIORITY_INCOMPLETE")
        if self.dimension not in PRIORITY_DIMENSIONS:
            raise DirectorBriefError(f"priority {self.id}: bad dimension {self.dimension!r}",
                                     code="PRIORITY_BAD_DIMENSION")
        if self.required not in SEVERITY:
            raise DirectorBriefError(f"priority {self.id}: bad severity {self.required!r}",
                                     code="PRIORITY_BAD_SEVERITY")
        if self.required == "must" and not (self.rationale and self.constraint_refs):
            raise DirectorBriefError(
                f"priority {self.id}: a must-priority needs rationale + constraint_refs",
                code="PRIORITY_UNGROUNDED")

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "dimension": self.dimension, "statement": self.statement,
                "required": self.required, "rationale": self.rationale,
                "constraint_refs": list(self.constraint_refs),
                "reference_refs": list(self.reference_refs)}

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> Priority:
        reject_unknown(payload, cls._FIELDS, "priority")
        require_keys(payload, ("id", "dimension", "statement"), "priority")
        return cls(id=as_str(payload, "id"), dimension=as_str(payload, "dimension"),
                   statement=as_str(payload, "statement"),
                   required=as_str(payload, "required", "must"), rationale=as_str(payload, "rationale"),
                   constraint_refs=as_str_tuple(payload, "constraint_refs"),
                   reference_refs=as_str_tuple(payload, "reference_refs"))


@dataclass(frozen=True)
class AntiPattern:
    """What must not read on screen, and why — so it cannot be silently dropped."""

    id: str
    description: str
    rationale: str
    constraint_refs: tuple[str, ...] = ()

    _FIELDS = ("id", "description", "rationale", "constraint_refs")

    def validate(self) -> None:
        if not (self.id and self.description and self.rationale):
            raise DirectorBriefError(f"anti-pattern {self.id or '?'}: id/description/rationale required",
                                     code="ANTIPATTERN_INCOMPLETE")

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "description": self.description, "rationale": self.rationale,
                "constraint_refs": list(self.constraint_refs)}

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> AntiPattern:
        reject_unknown(payload, cls._FIELDS, "anti_pattern")
        require_keys(payload, ("id", "description", "rationale"), "anti_pattern")
        return cls(id=as_str(payload, "id"), description=as_str(payload, "description"),
                   rationale=as_str(payload, "rationale"),
                   constraint_refs=as_str_tuple(payload, "constraint_refs"))


@dataclass(frozen=True)
class ApprovalRecord:
    """Attestation of the exact brief content that was reviewed."""

    state: Lifecycle
    actor: str = ""
    decided_at: str = ""
    rationale: str = ""
    pinned_hash: str = ""

    _FIELDS = ("state", "actor", "decided_at", "rationale", "pinned_hash")

    def validate(self) -> None:
        if self.state not in BRIEF_DECISION_STATES:
            raise DirectorBriefError(f"brief cannot be in state {self.state}",
                                     code="APPROVAL_OUT_OF_BAND")
        if self.state is Lifecycle.APPROVED:
            if not (self.actor and self.decided_at):
                raise DirectorBriefError("approved brief needs actor + decided_at",
                                         code="APPROVAL_UNATTESTED")
            if not PIN_RE.match(self.pinned_hash):
                raise DirectorBriefError("approved brief must pin the approved content hash",
                                         code="APPROVAL_UNPINNED")

    def to_dict(self) -> dict[str, object]:
        return {"state": str(self.state), "actor": self.actor, "decided_at": self.decided_at,
                "rationale": self.rationale, "pinned_hash": self.pinned_hash}

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ApprovalRecord:
        reject_unknown(payload, cls._FIELDS, "approval")
        require_keys(payload, ("state",), "approval")
        return cls(state=Lifecycle(str(payload["state"])), actor=as_str(payload, "actor"),
                   decided_at=as_str(payload, "decided_at"), rationale=as_str(payload, "rationale"),
                   pinned_hash=as_str(payload, "pinned_hash"))


@dataclass(frozen=True)
class BriefCompleteness:
    """Diagnostic list of required direction inputs that are still absent."""

    missing: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.missing


@dataclass(frozen=True)
class DirectorBrief:
    """Session entry contract: source, reference pack, priorities, anti-patterns, approval."""

    direction_id: str
    revision: int
    source: SourceRef
    reference_pack: ReferencePack
    approval: ApprovalRecord = field(default_factory=lambda: ApprovalRecord(Lifecycle.DRAFT))
    brief_ref: str = ""
    thesis_ref: str = ""
    treatment_ref: str = ""
    priorities: tuple[Priority, ...] = ()
    anti_patterns: tuple[AntiPattern, ...] = ()

    _FIELDS = ("direction_id", "revision", "source", "reference_pack", "approval", "brief_ref",
               "thesis_ref", "treatment_ref", "priorities", "anti_patterns")

    @property
    def constraints(self) -> tuple[Constraint, ...]:
        return self.reference_pack.constraints

    def completeness(self) -> BriefCompleteness:
        dimensions = {p.dimension for p in self.priorities}
        missing = [f"priorities.{d}" for d in PRIORITY_DIMENSIONS if d not in dimensions]
        if not self.anti_patterns:
            missing.append("anti_patterns")
        if not self.reference_pack.constraints_by_status(ConstraintStatus.TARGET):
            missing.append("constraints.target")
        if not self.reference_pack.constraints_by_status(ConstraintStatus.FORBIDDEN):
            missing.append("constraints.forbidden")
        return BriefCompleteness(tuple(missing))

    def validate(self, *, require_complete: bool = False) -> None:
        if not self.direction_id or self.revision < 1:
            raise DirectorBriefError("direction_id + revision >= 1 required",
                                     code="BRIEF_INCOMPLETE")
        self.source.validate()
        self.reference_pack.validate()
        for name, pin in (("brief_ref", self.brief_ref), ("thesis_ref", self.thesis_ref),
                          ("treatment_ref", self.treatment_ref)):
            if not PIN_RE.match(pin):
                raise DirectorBriefError(f"{name} must pin a P10b content hash (sha256 hex)",
                                         code="BRIEF_CONTENT_UNPINNED")
        self.approval.validate()
        known = {c.id for c in self.reference_pack.constraints}
        self._reject_duplicates([p.id for p in self.priorities], "priority", "PRIORITY_DUP_ID")
        for priority in self.priorities:
            priority.validate()
            unknown = sorted(set(priority.constraint_refs) - known)
            if unknown:
                raise DirectorBriefError(f"priority {priority.id}: unknown constraint_refs {unknown}",
                                         code="PRIORITY_CONSTRAINT_UNKNOWN")
        self._reject_duplicates([a.id for a in self.anti_patterns], "anti-pattern",
                                "ANTIPATTERN_DUP_ID")
        for anti in self.anti_patterns:
            anti.validate()
            unknown = sorted(set(anti.constraint_refs) - known)
            if unknown:
                raise DirectorBriefError(f"anti-pattern {anti.id}: unknown constraint_refs {unknown}",
                                         code="ANTIPATTERN_CONSTRAINT_UNKNOWN")
        if require_complete:
            gap = self.completeness()
            if not gap.complete:
                raise DirectorBriefError(f"brief incomplete: {list(gap.missing)}",
                                         code="BRIEF_NOT_COMPLETE")

    def validate_for_approval(self) -> None:
        """Complete + internally consistent + approved content unchanged (no in-place edit)."""
        self.validate(require_complete=True)
        if (self.approval.state is Lifecycle.APPROVED
                and self.approval.pinned_hash != self.brief_hash()):
            raise DirectorBriefError("APPROVAL_VOID: approved brief content drifted",
                                     code="APPROVAL_VOID")

    def content_pins(self) -> dict[str, str]:
        """P10b revision pin set (brief/thesis/benchmarks/treatment) plus this brief's own
        content hash, so S1 constraint edits are caught by the existing pin record too."""
        return {"brief": self.brief_ref, "thesis": self.thesis_ref,
                "benchmarks": self.reference_pack.benchmark_ref, "treatment": self.treatment_ref,
                "director_brief": self.brief_hash()}

    def content_payload(self) -> dict[str, object]:
        """Creative content only. The approval record is the attestation about this
        content, so it is excluded: approving must not change the hash it attests to."""
        payload = self.to_dict()
        payload.pop("approval")
        return payload

    def brief_hash(self) -> str:
        return canonical_hash(self.content_payload())

    def to_dict(self) -> dict[str, object]:
        return {"schema": SCHEMA, "direction_id": self.direction_id, "revision": self.revision,
                "source": self.source.to_dict(), "reference_pack": self.reference_pack.to_dict(),
                "approval": self.approval.to_dict(), "brief_ref": self.brief_ref,
                "thesis_ref": self.thesis_ref, "treatment_ref": self.treatment_ref,
                "priorities": [p.to_dict() for p in self.priorities],
                "anti_patterns": [a.to_dict() for a in self.anti_patterns]}

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> DirectorBrief:
        reject_unknown(payload, (*cls._FIELDS, "schema"), "director_brief")
        require_keys(payload, ("direction_id", "revision", "source", "reference_pack"),
                     "director_brief")
        if as_str(payload, "schema", SCHEMA) != SCHEMA:
            raise DirectorBriefError(f"unsupported schema {payload.get('schema')!r}",
                                     code="PAYLOAD_SCHEMA_UNSUPPORTED")
        approval = (ApprovalRecord.from_dict(as_dict(payload, "approval"))
                    if payload.get("approval") is not None
                    else ApprovalRecord(Lifecycle.DRAFT))
        return cls(direction_id=as_str(payload, "direction_id"),
                   revision=as_int(payload, "revision", 0),
                   source=SourceRef.from_dict(as_dict(payload, "source")),
                   reference_pack=ReferencePack.from_dict(as_dict(payload, "reference_pack")),
                   approval=approval, brief_ref=as_str(payload, "brief_ref"),
                   thesis_ref=as_str(payload, "thesis_ref"),
                   treatment_ref=as_str(payload, "treatment_ref"),
                   priorities=tuple(Priority.from_dict(item)
                                    for item in as_dict_list(payload, "priorities")),
                   anti_patterns=tuple(AntiPattern.from_dict(item)
                                       for item in as_dict_list(payload, "anti_patterns")))

    @staticmethod
    def _reject_duplicates(ids: list[str], what: str, code: str) -> None:
        repeated = sorted({i for i in ids if ids.count(i) > 1})
        if repeated:
            raise DirectorBriefError(f"duplicate {what} ids {repeated}", code=code)