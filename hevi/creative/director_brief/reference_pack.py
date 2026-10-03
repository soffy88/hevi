"""S1 ReferencePack — the references consulted plus the constraint ledger read off them.

Authority boundary (S1 scope): the pack owns no creative authority.
- Reference/principle extraction stays in the P10b `BenchmarkSet`; the pack pins
  it via `benchmark_ref` instead of re-declaring principles.
- Canon/Style/Asset/Provider are addressed by id string only, never imported.

Every constraint carries an epistemic status so downstream stages can tell
"read off a reference" from "we decided this":
  observed  — read directly from a cited reference (provenance required)
  inferred  — derived, not read (provenance + rationale required)
  target    — what the film must reach (measurable required)
  forbidden — must never happen (reason required, so it can be scoped later)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from hevi.creative.director_brief.codec import (
    as_dict,
    as_dict_list,
    as_str,
    canonical_hash,
    reject_unknown,
    require_keys,
)
from hevi.creative.director_brief.errors import DirectorBriefError

SCHEMA = "hevi.director_brief.reference_pack/1"

# Same severity vocabulary as P10c CueAction.required / P10b check classes.
SEVERITY = ("must", "should", "may")
PIN_RE = re.compile(r"^[0-9a-f]{64}$")


class ConstraintStatus(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    TARGET = "target"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True)
class Provenance:
    """Why a constraint may be believed: which reference, read when, which bytes."""

    reference_id: str
    uri: str = ""
    retrieved_at: str = ""
    content_hash: str = ""
    extractor: str = ""

    _FIELDS = ("reference_id", "uri", "retrieved_at", "content_hash", "extractor")

    def validate(self) -> None:
        absent = [name for name in ("reference_id", "uri", "retrieved_at", "content_hash")
                  if not getattr(self, name)]
        if absent:
            raise DirectorBriefError(f"provenance missing {absent}", code="PROVENANCE_INCOMPLETE")

    def to_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self._FIELDS}

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> Provenance:
        reject_unknown(payload, cls._FIELDS, "provenance")
        require_keys(payload, ("reference_id",), "provenance")
        return cls(reference_id=as_str(payload, "reference_id"), uri=as_str(payload, "uri"),
                   retrieved_at=as_str(payload, "retrieved_at"),
                   content_hash=as_str(payload, "content_hash"),
                   extractor=as_str(payload, "extractor"))


@dataclass(frozen=True)
class ReferenceEntry:
    """Reference identity + access record. Principles stay in the benchmark set."""

    id: str
    title: str
    creator: str = ""
    kind: str = "benchmark"
    provenance: Provenance | None = None

    _FIELDS = ("id", "title", "creator", "kind", "provenance")

    def validate(self) -> None:
        if not (self.id and self.title):
            raise DirectorBriefError("reference id + title required", code="REFERENCE_INCOMPLETE")
        if self.provenance is None:
            raise DirectorBriefError(f"reference {self.id}: provenance required",
                                     code="REFERENCE_UNPROVENANCED")
        if self.provenance.reference_id != self.id:
            raise DirectorBriefError(
                f"reference {self.id}: provenance points at {self.provenance.reference_id}",
                code="REFERENCE_IDENTITY_MISMATCH")
        self.provenance.validate()

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "title": self.title, "creator": self.creator, "kind": self.kind,
                "provenance": self.provenance.to_dict() if self.provenance else None}

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ReferenceEntry:
        reject_unknown(payload, cls._FIELDS, "reference")
        require_keys(payload, ("id", "title"), "reference")
        raw = payload.get("provenance")
        return cls(id=as_str(payload, "id"), title=as_str(payload, "title"),
                   creator=as_str(payload, "creator"), kind=as_str(payload, "kind", "benchmark"),
                   provenance=(Provenance.from_dict(as_dict(payload, "provenance"))
                               if raw is not None else None))


@dataclass(frozen=True)
class Constraint:
    """One directional constraint, tagged with how it is known and what anchors it."""

    id: str
    key: str
    statement: str
    status: ConstraintStatus
    dimension: str = ""
    severity: str = "must"
    measurable: str = ""
    rationale: str = ""
    provenance: Provenance | None = None

    _FIELDS = ("id", "key", "statement", "status", "dimension", "severity", "measurable",
               "rationale", "provenance")

    def validate(self) -> None:
        if not (self.id and self.key and self.statement):
            raise DirectorBriefError(f"constraint {self.id or '?'}: id/key/statement required",
                                     code="CONSTRAINT_INCOMPLETE")
        if not isinstance(self.status, ConstraintStatus):
            raise DirectorBriefError(f"constraint {self.id}: bad status {self.status!r}",
                                     code="CONSTRAINT_BAD_STATUS")
        if self.severity not in SEVERITY:
            raise DirectorBriefError(f"constraint {self.id}: bad severity {self.severity!r}",
                                     code="CONSTRAINT_BAD_SEVERITY")
        if self.status in (ConstraintStatus.OBSERVED, ConstraintStatus.INFERRED):
            if self.provenance is None:
                raise DirectorBriefError(f"constraint {self.id}: {self.status} needs provenance",
                                         code="CONSTRAINT_UNSOURCED")
            self.provenance.validate()
        if self.status is ConstraintStatus.INFERRED and not self.rationale:
            raise DirectorBriefError(f"constraint {self.id}: inferred without rationale",
                                     code="INFERRED_CONSTRAINT_UNGROUNDED")
        if self.status is ConstraintStatus.TARGET and not self.measurable:
            raise DirectorBriefError(f"constraint {self.id}: target without measurable",
                                     code="TARGET_CONSTRAINT_UNMEASURABLE")
        if self.status is ConstraintStatus.FORBIDDEN and not self.rationale:
            raise DirectorBriefError(f"constraint {self.id}: forbidden without reason",
                                     code="FORBIDDEN_CONSTRAINT_UNREASONED")

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "key": self.key, "statement": self.statement,
                "status": str(self.status), "dimension": self.dimension, "severity": self.severity,
                "measurable": self.measurable, "rationale": self.rationale,
                "provenance": self.provenance.to_dict() if self.provenance else None}

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> Constraint:
        reject_unknown(payload, cls._FIELDS, "constraint")
        require_keys(payload, ("id", "key", "statement", "status"), "constraint")
        raw = payload.get("provenance")
        return cls(id=as_str(payload, "id"), key=as_str(payload, "key"),
                   statement=as_str(payload, "statement"), status=ConstraintStatus(str(payload["status"])),
                   dimension=as_str(payload, "dimension"), severity=as_str(payload, "severity", "must"),
                   measurable=as_str(payload, "measurable"), rationale=as_str(payload, "rationale"),
                   provenance=(Provenance.from_dict(as_dict(payload, "provenance"))
                               if raw is not None else None))


@dataclass(frozen=True)
class ReferencePack:
    """Constraints read off the references, with the benchmark set that owns them pinned."""

    benchmark_ref: str
    references: tuple[ReferenceEntry, ...] = ()
    constraints: tuple[Constraint, ...] = ()
    note: str = ""

    _FIELDS = ("benchmark_ref", "references", "constraints", "note")

    def validate(self) -> None:
        if not PIN_RE.match(self.benchmark_ref):
            raise DirectorBriefError(
                "benchmark_ref must pin the P10b BenchmarkSet hash (sha256 hex)",
                code="BENCHMARK_UNPINNED")
        if not self.references:
            raise DirectorBriefError("reference pack has no references", code="REFPACK_EMPTY")
        ref_ids = [ref.id for ref in self.references]
        repeated = sorted({i for i in ref_ids if ref_ids.count(i) > 1})
        if repeated:
            raise DirectorBriefError(f"duplicate reference ids {repeated}",
                                     code="REFPACK_DUP_REFERENCE")
        for ref in self.references:
            ref.validate()
        if not self.constraints:
            raise DirectorBriefError("reference pack has no constraints",
                                     code="REFPACK_NO_CONSTRAINT")
        constraint_ids = [c.id for c in self.constraints]
        repeated = sorted({i for i in constraint_ids if constraint_ids.count(i) > 1})
        if repeated:
            raise DirectorBriefError(f"duplicate constraint ids {repeated}",
                                     code="CONSTRAINT_DUP_ID")
        known_refs = set(ref_ids)
        for constraint in self.constraints:
            constraint.validate()
            if constraint.provenance is not None and constraint.provenance.reference_id not in known_refs:
                raise DirectorBriefError(
                    f"constraint {constraint.id}: provenance cites unknown reference "
                    f"{constraint.provenance.reference_id}",
                    code="CONSTRAINT_UNTRACEABLE")
        statuses: dict[str, set[str]] = {}
        for constraint in self.constraints:
            statuses.setdefault(constraint.key, set()).add(str(constraint.status))
        conflicts = sorted(key for key, seen in statuses.items()
                           if {ConstraintStatus.TARGET, ConstraintStatus.FORBIDDEN} <= {str(s) for s in seen})
        if conflicts:
            raise DirectorBriefError(f"contradictory constraints on key(s) {conflicts}",
                                     code="CONSTRAINT_CONTRADICTION")

    def constraints_by_status(self, status: ConstraintStatus) -> tuple[Constraint, ...]:
        return tuple(c for c in self.constraints if c.status == status)

    def target_constraints(self) -> tuple[Constraint, ...]:
        return self.constraints_by_status(ConstraintStatus.TARGET)

    def forbidden_constraints(self) -> tuple[Constraint, ...]:
        return self.constraints_by_status(ConstraintStatus.FORBIDDEN)

    def required_constraints(self) -> tuple[Constraint, ...]:
        return tuple(c for c in self.constraints if c.severity == "must")

    def pack_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {"schema": SCHEMA, "benchmark_ref": self.benchmark_ref,
                "references": [ref.to_dict() for ref in self.references],
                "constraints": [c.to_dict() for c in self.constraints], "note": self.note}

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ReferencePack:
        reject_unknown(payload, (*cls._FIELDS, "schema"), "reference_pack")
        require_keys(payload, ("benchmark_ref", "references", "constraints"), "reference_pack")
        if as_str(payload, "schema", SCHEMA) != SCHEMA:
            raise DirectorBriefError(f"unsupported schema {payload.get('schema')!r}",
                                     code="PAYLOAD_SCHEMA_UNSUPPORTED")
        return cls(benchmark_ref=as_str(payload, "benchmark_ref"),
                   references=tuple(ReferenceEntry.from_dict(item)
                                    for item in as_dict_list(payload, "references")),
                   constraints=tuple(Constraint.from_dict(item)
                                     for item in as_dict_list(payload, "constraints")),
                   note=as_str(payload, "note"))