"""P10-E ShotSpec validator: pure, deterministic, no IO and no LLM.

Reports rather than raises by default so a caller can surface every problem at
once; `raise_for_blocking()` is the fail-loud edge (P10d rule 5: no silent skip).

A reference index is *required*, not optional. An absent upstream id is an
unresolved reference, not an assumed-present one — an empty index therefore
yields unresolved findings instead of a clean report.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from hevi.creative.direction_shot.contracts import CONTENT_PIN_KEYS, ShotSpec
from hevi.creative.direction_shot.errors import ShotSpecError


@dataclass(frozen=True)
class Finding:
    code: str
    shot_id: str
    detail: str = ""
    blocking: bool = True


@dataclass(frozen=True)
class ValidationReport:
    findings: tuple[Finding, ...] = ()

    @property
    def blocking(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.blocking)

    @property
    def ok(self) -> bool:
        return not self.blocking

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(f.code for f in self.blocking)

    def raise_for_blocking(self) -> None:
        if self.blocking:
            summary = "; ".join(f"{f.shot_id or '-'}:{f.code}" for f in self.blocking)
            raise ShotSpecError(f"shot spec validation failed: {summary}",
                                code=self.blocking[0].code)


@dataclass(frozen=True)
class ShotRefIndex:
    """Upstream ids a revision declares. Every ref in a ShotSpec must appear here."""

    beats: frozenset[str] = frozenset()
    cues: frozenset[str] = frozenset()
    decisions: frozenset[str] = frozenset()
    authority: frozenset[str] = frozenset()

    @staticmethod
    def of(*, beats: tuple[str, ...] = (), cues: tuple[str, ...] = (),
           decisions: tuple[str, ...] = (), authority: tuple[str, ...] = ()) -> ShotRefIndex:
        return ShotRefIndex(frozenset(beats), frozenset(cues),
                            frozenset(decisions), frozenset(authority))


def _pin_findings(spec: ShotSpec, expected: dict[str, str]) -> list[Finding]:
    drifted = [k for k in CONTENT_PIN_KEYS if spec.content_pins.get(k) != expected.get(k)]
    if drifted:
        return [Finding("SHOT_PINS_DIVERGED", spec.shot_id,
                        f"content pins differ within revision: {sorted(drifted)}")]
    return []


def _check_spec(spec: ShotSpec, index: ShotRefIndex,
                expected_pins: dict[str, str]) -> list[Finding]:
    out: list[Finding] = []
    try:
        spec.validate()
    except ShotSpecError as exc:
        out.append(Finding(exc.code, spec.shot_id, str(exc)))
        return out  # local contract broken; cross-refs on it would be noise

    out.extend(_pin_findings(spec, expected_pins))
    if spec.beat_ref and spec.beat_ref not in index.beats:
        out.append(Finding("SHOT_REF_UNRESOLVED", spec.shot_id, f"beat_ref {spec.beat_ref}"))
    out.extend(Finding("SHOT_REF_UNRESOLVED", spec.shot_id, f"cue_ref {cue}")
               for cue in spec.cue_refs if cue not in index.cues)
    out.extend(Finding("SHOT_REF_UNRESOLVED", spec.shot_id, f"decision_ref {decision}")
               for decision in spec.decision_refs if decision not in index.decisions)
    out.extend(Finding("SHOT_AUTHORITY_UNPINNED", spec.shot_id, f"authority {pin}")
               for pin in spec.authority_pins if pin not in index.authority)
    if spec.status == "APPROVED":
        out.extend(Finding("SHOT_H_UNATTESTED", spec.shot_id,
                           f"must class-H check {check_id} has no attestation surface")
                   for check_id in spec.h_class_musts())
    return out


def validate_shot_specs(specs: Sequence[ShotSpec],
                        index: ShotRefIndex) -> ValidationReport:
    """Validate one revision's shot specs against the declared upstream index."""
    findings: list[Finding] = []
    if not specs:
        return ValidationReport((Finding("SHOT_EMPTY", "", "no shot specs in revision"),))

    # Content pins are revision-level in P10b, so the first spec sets the
    # expectation and every sibling must agree with it.
    expected_pins = dict(specs[0].content_pins)
    seen_ids: set[str] = set()
    for spec in specs:
        if spec.shot_id in seen_ids:
            findings.append(Finding("SHOT_DUP_ID", spec.shot_id, "duplicate shot_id"))
        seen_ids.add(spec.shot_id)
        findings.extend(_check_spec(spec, index, expected_pins))

    findings.extend(_overlap_findings(specs))
    findings.extend(_signature_findings(specs))
    return ValidationReport(tuple(findings))


def _overlap_findings(specs: Sequence[ShotSpec]) -> list[Finding]:
    """Overlap is only decidable between shots sharing (target, type, edge).

    Different anchors are left alone rather than ordered by guesswork; those
    cases are the anchor resolver's job (G0.2 A/B verified it).
    """
    out: list[Finding] = []
    placed: list[tuple[ShotSpec, tuple[str, str, str, int, int]]] = []
    for spec in specs:
        key = spec.timing.order_key()
        for other, other_key in placed:
            same_axis = key[:3] == other_key[:3]
            if same_axis and key[3] < other_key[4] and other_key[3] < key[4]:
                out.append(Finding("SHOT_TIME_OVERLAP", spec.shot_id,
                                   f"overlaps {other.shot_id} in film-global ms"))
        placed.append((spec, key))
    return out


def _signature_findings(specs: Sequence[ShotSpec]) -> list[Finding]:
    """Advisory only: P10c requires camera-signature uniqueness for signature
    shots, not for every shot, so a repeat is reported, not rejected."""
    out: list[Finding] = []
    seen: dict[str, str] = {}
    for spec in specs:
        digest = spec.camera.signature_hash()
        if digest in seen:
            out.append(Finding("SHOT_CAMERA_SIGNATURE_DUPLICATE", spec.shot_id,
                               f"same camera signature as {seen[digest]}", blocking=False))
        seen[digest] = spec.shot_id
    return out
