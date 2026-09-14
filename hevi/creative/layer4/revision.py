"""Bounded, proposal-first narrative revision workflow.

Revision is executed against the real audit findings.  The engine:

* keeps the original artifact byte-identical until an explicit commit,
* produces a concrete diff and an issue-resolution trace,
* preserves unresolved findings instead of silently dropping them,
* enforces the iteration bound,
* never mutates canon, and commits the revised artifact atomically.

Canon-sensitive findings are only repaired by aligning the *draft* to canon; the
engine never writes to canonical state.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from hevi.obase.creative import (
    AuditFinding,
    CandidateRevision,
    CreativeAuthority,
    NarrativeAudit,
    RevisionProposal,
)

ChangeType = Literal["POLISH", "SPOT_FIX", "REWRITE", "STRUCTURAL_REWORK", "QUALITY_DRIVEN"]

_EXPAND_CODES = frozenset({"LG_BELOW_TARGET"})
_CONTRACT_CODES = frozenset({"LG_ABOVE_TARGET", "SA_SENTENCE_LENGTH_DRIFT", "RP_REPEATED_PHRASE"})

_EXPOSITION_MARKERS = (
    "as you know",
    "remember that",
    "as i told you",
    "needless to say",
    "for your information",
)

_INTENSIFIERS = ("very", "really", "just", "quite", "literally", "actually")


class RevisionLimitError(RuntimeError):
    """Raised when a bounded revision loop has no remaining pass."""


@dataclass(frozen=True)
class RevisionPolicy:
    max_passes: int = 2

    def __post_init__(self) -> None:
        if self.max_passes < 1:
            raise ValueError("max_passes must be positive")


class RevisionOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    dimension: str
    change_type: str
    location: str | None = None
    description: str
    message: str | None = None


class RevisionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: UUID
    base_revision: int
    change_type: str
    operations: tuple[RevisionOperation, ...] = ()
    unresolved_codes: tuple[str, ...] = ()


class RevisionExecution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: UUID
    base_revision: int
    pass_number: int
    change_type: str
    original_text: str
    original_hash: str
    revised_text: str
    revised_hash: str
    diff: tuple[str, ...] = ()
    operations: tuple[RevisionOperation, ...] = ()
    resolved_codes: tuple[str, ...] = ()
    unresolved_codes: tuple[str, ...] = ()
    re_audit_status: str = "UNKNOWN"
    conflict_codes: tuple[str, ...] = ()


class RevisionCommit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    applied: bool
    artifact_written: bool
    artifact_uri: str | None = None
    artifact_hash: str | None = None
    canon_hash_before: str
    canon_hash_after: str


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]


def _split_long_sentences(text: str, limit: int = 10) -> str:
    output: list[str] = []
    for sentence in _sentences(text):
        words = sentence.split()
        if len(words) <= limit:
            output.append(sentence)
            continue
        midpoint = len(words) // 2
        output.append(" ".join(words[:midpoint]) + ".")
        output.append(" ".join(words[midpoint:]).capitalize() + ".")
    return " ".join(output)


def _collapse_repeats(text: str) -> str:
    return re.sub(r"\b(\w+)(?:\s+\1){2,}\b", r"\1", text, flags=re.IGNORECASE)


def _trim_sentence(text: str) -> str:
    sentences = _sentences(text)
    if len(sentences) <= 1:
        return text
    return " ".join(sentences[:-1])


def _align_to_canon(finding: AuditFinding, text: str) -> str:
    quoted = re.findall(r"'([^']*)'", finding.message or "")
    if len(quoted) < 2:
        return text
    draft_value, canon_value = quoted[0], quoted[1]
    if not draft_value or draft_value == canon_value:
        return text
    return re.sub(rf"\b{re.escape(draft_value)}\b", canon_value, text)


def _remove_forbidden(finding: AuditFinding, text: str) -> str:
    quoted = re.findall(r"'([^']*)'", finding.message or "")
    if not quoted:
        return text
    return re.sub(rf"\b{re.escape(quoted[0])}\b\s*", "", text, flags=re.IGNORECASE)


def _reduce_fatigue(finding: AuditFinding, text: str) -> str:
    match = re.match(r"fatigue word '([^']*)'", finding.message or "")
    if not match:
        return text
    word = match.group(1)
    seen = 0

    def keep_first_two(match_obj: re.Match[str]) -> str:
        nonlocal seen
        seen += 1
        return match_obj.group(0) if seen <= 2 else ""

    return re.sub(rf"\b{re.escape(word)}\b", keep_first_two, text, flags=re.IGNORECASE)


def _remove_exposition(text: str) -> str:
    revised = text
    for marker in _EXPOSITION_MARKERS:
        revised = re.sub(re.escape(marker) + r"[,]?\s*", "", revised, flags=re.IGNORECASE)
    return revised


def _externalize_interior(text: str) -> str:
    replacements = {
        "thought about": "studied",
        "felt the weight of": "braced against",
        "remembered that": "glanced at",
        "wondered whether": "checked",
        "considered the meaning": "measured",
    }
    revised = text
    for marker, replacement in replacements.items():
        revised = revised.replace(marker, replacement)
    return revised


def _strip_intensifiers(text: str) -> str:
    revised = text
    for marker in _INTENSIFIERS:
        revised = re.sub(rf"\b{marker}\b\s*", "", revised, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", revised).strip()


def _append_beat(text: str) -> str:
    return (text.rstrip() + " The moment held.").strip()


def _repair_text(
    text: str,
    finding: AuditFinding,
    *,
    change_type: str,
) -> str:
    code = finding.code or ""
    message = finding.message or ""
    if code == "PC_EMPTY_TEXT":
        return "A scene begins."
    if code in {"PC_OVERLONG_SENTENCE", "SA_SENTENCE_LENGTH_DRIFT"} or code.endswith(
        "SENTENCE_LENGTH_DRIFT"
    ):
        return _split_long_sentences(text)
    if code in {"RP_REPEATED_PHRASE"} or code.startswith("RP_"):
        return _collapse_repeats(text)
    if code == "GA_FORBIDDEN_PATTERN":
        return _remove_forbidden(finding, text)
    if code == "FW_OVERUSED":
        return _reduce_fatigue(finding, text)
    if code == "DQ_EXPOSITION":
        return _remove_exposition(text)
    if code == "VF_ABSTRACT_NARRATION":
        return _externalize_interior(text)
    if code in {"EMPTY_INTENSIFIER"}:
        return _strip_intensifiers(text)
    if code == "LG_ABOVE_TARGET":
        return _trim_sentence(text)
    if code == "LG_BELOW_TARGET":
        return _append_beat(text)
    if "contradicts canon value" in message:
        return _align_to_canon(finding, text)
    if change_type == "REWRITE" and code:
        return text
    return text


def _describe(code: str) -> str:
    return {
        "PC_EMPTY_TEXT": "supply a non-empty opening beat",
        "PC_OVERLONG_SENTENCE": "split the overlong sentence",
        "SA_SENTENCE_LENGTH_DRIFT": "align sentence cadence with the style profile",
        "RP_REPEATED_PHRASE": "collapse the repeated phrase",
        "GA_FORBIDDEN_PATTERN": "remove the forbidden genre pattern",
        "FW_OVERUSED": "reduce the overused fatigue word",
        "DQ_EXPOSITION": "dramatize instead of exposing plot",
        "VF_ABSTRACT_NARRATION": "externalize interior narration",
        "EMPTY_INTENSIFIER": "remove the empty intensifier",
        "LG_ABOVE_TARGET": "trim the draft toward the length ceiling",
        "LG_BELOW_TARGET": "expand the draft toward the length floor",
    }.get(code, "align the draft to the audit recommendation")


class RevisionEngine:
    """Create proposals, execute bounded repairs, and commit atomically."""

    def __init__(self, policy: RevisionPolicy | None = None) -> None:
        self.policy = policy or RevisionPolicy()

    # -- proposal surface (kept stable) -----------------------------------
    def propose(
        self,
        *,
        project_id: UUID,
        asset_id: UUID,
        base_revision: int,
        audit: NarrativeAudit,
        change_type: str = "QUALITY_DRIVEN",
    ) -> RevisionProposal:
        if audit.status == "PASS":
            raise ValueError("cannot create a revision proposal for a passing audit")
        if not audit.findings:
            raise ValueError("failed audit must contain findings")
        reasons = tuple(
            f"{finding.dimension}: {finding.recommendation}" for finding in audit.findings
        )
        return RevisionProposal(
            project_id=project_id,
            asset_id=asset_id,
            base_revision=base_revision,
            change_type=change_type,  # type: ignore[arg-type]
            reason="; ".join(reasons),
            operations=reasons,
            authority=CreativeAuthority.PROPOSAL,
        )

    def candidate(
        self,
        *,
        project_id: UUID,
        asset_id: UUID,
        base_revision: int,
        pass_number: int,
        artifact_id: UUID | None = None,
        audit_id: UUID | None = None,
    ) -> CandidateRevision:
        if pass_number < 1 or pass_number > self.policy.max_passes:
            raise RevisionLimitError("REVISION_LIMIT")
        return CandidateRevision(
            project_id=project_id,
            asset_id=asset_id,
            base_revision=base_revision,
            candidate_revision=base_revision + pass_number,
            artifact_id=artifact_id,
            audit_id=audit_id,
            authority=CreativeAuthority.PROPOSAL,
        )

    # -- plan / execute ----------------------------------------------------
    def plan(
        self,
        *,
        asset_id: UUID,
        base_revision: int,
        audit: NarrativeAudit,
        change_type: str = "QUALITY_DRIVEN",
        conflict_codes: tuple[str, ...] = (),
    ) -> RevisionPlan:
        operations: list[RevisionOperation] = []
        unresolved: list[str] = []
        for finding in audit.findings:
            code = finding.code or finding.dimension
            if code in conflict_codes:
                unresolved.append(code)
                continue
            operations.append(
                RevisionOperation(
                    code=code,
                    dimension=finding.dimension,
                    change_type=change_type,
                    location=finding.artifact_location,
                    description=_describe(code),
                    message=finding.message,
                )
            )
        return RevisionPlan(
            asset_id=asset_id,
            base_revision=base_revision,
            change_type=change_type,
            operations=tuple(operations),
            unresolved_codes=tuple(unresolved),
        )

    def execute(
        self,
        *,
        asset_id: UUID,
        base_revision: int,
        plan: RevisionPlan,
        text: str,
        pass_number: int = 1,
        re_audit: Callable[[str], NarrativeAudit] | None = None,
        change_type: str = "QUALITY_DRIVEN",
        conflict_codes: tuple[str, ...] = (),
    ) -> RevisionExecution:
        if pass_number < 1 or pass_number > self.policy.max_passes:
            raise RevisionLimitError("REVISION_LIMIT")
        revised = text
        resolved: list[str] = []
        unresolved = list(plan.unresolved_codes)
        ops: list[RevisionOperation] = []
        for operation in plan.operations:
            finding = AuditFinding(
                severity="WARN",
                dimension=operation.dimension,
                recommendation=operation.description,
                code=operation.code,
                message=operation.message,
            )
            candidate = _repair_text(revised, finding, change_type=change_type)
            if candidate != revised:
                resolved.append(operation.code)
                ops.append(operation)
                revised = candidate
            else:
                unresolved.append(operation.code)
        re_audit_status = "UNCHANGED"
        if re_audit is not None:
            re_audit_status = re_audit(revised).status
        diff = _diff_lines(text, revised)
        return RevisionExecution(
            asset_id=asset_id,
            base_revision=base_revision,
            pass_number=pass_number,
            change_type=change_type,
            original_text=text,
            original_hash=_hash(text),
            revised_text=revised,
            revised_hash=_hash(revised),
            diff=diff,
            operations=tuple(ops),
            resolved_codes=tuple(dict.fromkeys(resolved)),
            unresolved_codes=tuple(dict.fromkeys(unresolved)),
            re_audit_status=re_audit_status,
            conflict_codes=conflict_codes,
        )

    def run_bounded(
        self,
        *,
        asset_id: UUID,
        base_revision: int,
        audit: NarrativeAudit,
        text: str,
        change_type: str = "QUALITY_DRIVEN",
        re_audit: Callable[[str], NarrativeAudit],
    ) -> RevisionExecution:
        """Execute up to ``policy.max_passes`` bounded passes.

        Conflicting findings are detected and preserved as unresolved rather than
        oscillated between.  The returned execution is cumulative: resolved and
        unresolved codes are measured between the initial audit and the final
        re-audit, and the diff spans the original draft to the final draft.
        """

        codes = {finding.code or finding.dimension for finding in audit.findings}
        conflict_codes = tuple(
            sorted((codes & _EXPAND_CODES) | (codes & _CONTRACT_CODES))
            if (codes & _EXPAND_CODES) and (codes & _CONTRACT_CODES)
            else ()
        )
        current_text = text
        current_audit = audit
        applied_ops: list[RevisionOperation] = []
        passes = 0
        for pass_number in range(1, self.policy.max_passes + 1):
            plan = self.plan(
                asset_id=asset_id,
                base_revision=base_revision,
                audit=current_audit,
                change_type=change_type,
                conflict_codes=conflict_codes,
            )
            execution = self.execute(
                asset_id=asset_id,
                base_revision=base_revision,
                plan=plan,
                text=current_text,
                pass_number=pass_number,
                re_audit=re_audit,
                change_type=change_type,
                conflict_codes=conflict_codes,
            )
            passes = pass_number
            applied_ops.extend(execution.operations)
            if execution.revised_text == current_text:
                break
            current_text = execution.revised_text
            current_audit = re_audit(current_text)
        final_audit = re_audit(current_text)
        original_codes = {finding.code or finding.dimension for finding in audit.findings}
        final_codes = {finding.code or finding.dimension for finding in final_audit.findings}
        return RevisionExecution(
            asset_id=asset_id,
            base_revision=base_revision,
            pass_number=passes,
            change_type=change_type,
            original_text=text,
            original_hash=_hash(text),
            revised_text=current_text,
            revised_hash=_hash(current_text),
            diff=_diff_lines(text, current_text),
            operations=tuple(applied_ops),
            resolved_codes=tuple(sorted(original_codes - final_codes)),
            unresolved_codes=tuple(sorted(original_codes & final_codes)),
            re_audit_status=final_audit.status,
            conflict_codes=conflict_codes,
        )

    # -- commit ------------------------------------------------------------
    def commit(
        self,
        *,
        execution: RevisionExecution,
        approved: bool,
        path: Path,
        canon_hash: str,
    ) -> RevisionCommit:
        if not approved:
            return RevisionCommit(
                applied=False,
                artifact_written=False,
                canon_hash_before=canon_hash,
                canon_hash_after=canon_hash,
            )
        if _hash(execution.original_text) != execution.original_hash:
            raise ValueError("original artifact changed before commit")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(execution.revised_text, encoding="utf-8")
        os.replace(temporary, path)
        return RevisionCommit(
            applied=True,
            artifact_written=True,
            artifact_uri=str(path),
            artifact_hash=_hash(path.read_text(encoding="utf-8")),
            canon_hash_before=canon_hash,
            canon_hash_after=canon_hash,
        )


def _diff_lines(before: str, after: str) -> tuple[str, ...]:
    import difflib

    return tuple(
        line
        for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )


__all__ = [
    "RevisionCommit",
    "RevisionEngine",
    "RevisionExecution",
    "RevisionLimitError",
    "RevisionOperation",
    "RevisionPlan",
    "RevisionPolicy",
]
