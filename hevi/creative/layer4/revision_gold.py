"""Gold harness for the bounded revision workflow.

Runs the seven required revision situations against the real audit engine and
checks the canon-safety and atomicity guarantees.  Shared by the gold test and
the capability qualification runner.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from hevi.creative.layer4.audit import NarrativeAuditEngine
from hevi.creative.layer4.audit_dimensions import (
    AuditClaim,
    AuditContext,
    AuditState,
    GenreSpec,
    LengthTarget,
    SceneSpec,
    StyleSpec,
)
from hevi.creative.layer4.revision import RevisionEngine, RevisionLimitError, RevisionPolicy
from hevi.obase.creative import NarrativeAudit

_PID = UUID("00000000-0000-0000-0000-0000000000b1")
_AID = UUID("00000000-0000-0000-0000-0000000000b2")
CANON_HASH = "canon-hash-v1"


def _claim(
    dimension: str,
    subject: str,
    predicate: str,
    value: str,
    *,
    location: str | None = None,
    ref: str | None = None,
) -> AuditClaim:
    return AuditClaim(
        dimension=dimension,
        subject=subject,
        predicate=predicate,
        value=value,
        location=location,
        entity_ref=ref,
    )


def _context(
    text: str,
    *,
    claims: tuple[AuditClaim, ...] = (),
    canon: tuple[AuditClaim, ...] = (),
    style: StyleSpec | None = None,
    genre: GenreSpec | None = None,
    length_target: LengthTarget | None = None,
) -> AuditContext:
    return AuditContext(
        project_id=_PID,
        artifact_id=_AID,
        text=text,
        claims=claims,
        scenes=(SceneSpec(sequence=1, purpose="probe", objective="probe", beat_kind="turn"),),
        state=AuditState(canon_facts=canon),
        style=style,
        genre=genre,
        length_target=length_target,
    )


def _canon_map(canon: tuple[AuditClaim, ...]) -> dict[tuple[str, str, str], str]:
    return {(item.dimension, item.subject, item.predicate): item.value for item in canon}


def _reaudit(
    engine: NarrativeAuditEngine, base: AuditContext
) -> Callable[[str], NarrativeAudit]:
    canon_map = _canon_map(base.state.canon_facts)

    def _run(text: str) -> NarrativeAudit:
        claims = tuple(
            claim.model_copy(
                update={
                    "value": canon_map[
                        (claim.dimension, claim.subject, claim.predicate)
                    ]
                }
            )
            if (claim.dimension, claim.subject, claim.predicate) in canon_map
            and claim.value.casefold() not in text.casefold()
            else claim
            for claim in base.claims
        )
        return engine.audit_context(base.model_copy(update={"text": text, "claims": claims}))

    return _run


class RevisionScenarioResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    change_type: str
    findings: tuple[str, ...]
    resolved: tuple[str, ...]
    unresolved: tuple[str, ...]
    conflict: tuple[str, ...]
    passes: int
    diff_present: bool
    original_hash_preserved: bool
    trace_complete: bool
    re_audit_codes: tuple[str, ...]


class RevisionGoldResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenarios: tuple[RevisionScenarioResult, ...] = ()
    checks: dict[str, bool]
    details: dict[str, object]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(self.checks.values())


def _scenarios() -> list[tuple[str, str, AuditContext, tuple[str, ...], tuple[str, ...], bool]]:
    canon = (
        _claim("CHARACTER_CONTINUITY", "Mara", "eye_color", "green", ref="character:mara"),
    )
    return [
        (
            "single_style",
            "POLISH",
            _context(
                "The wind moved across the empty yard while the tall gate stood open before her.",
                style=StyleSpec(sentence_length=4.0),
            ),
            ("SA_SENTENCE_LENGTH_DRIFT",),
            (),
            False,
        ),
        (
            "multiple_independent",
            "SPOT_FIX",
            _context("They tried to build a bomb. It was very very very cold."),
            ("RP_REPEATED_PHRASE",),
            ("SAF_UNSAFE_CONTENT",),
            False,
        ),
        (
            "conflicting",
            "STRUCTURAL_REWORK",
            _context(
                "The wind moved across the empty yard while the tall gate stood open before her.",
                style=StyleSpec(sentence_length=4.0),
                length_target=LengthTarget(min_words=100),
            ),
            (),
            ("SA_SENTENCE_LENGTH_DRIFT", "LG_BELOW_TARGET"),
            True,
        ),
        (
            "canon_sensitive",
            "SPOT_FIX",
            _context(
                "Mara's blue eyes caught the light.",
                claims=(
                    _claim(
                        "CHARACTER_CONTINUITY",
                        "Mara",
                        "eye_color",
                        "blue",
                        location="sentence:1",
                        ref="character:mara",
                    ),
                ),
                canon=canon,
            ),
            ("CC_CONFLICT",),
            (),
            False,
        ),
        (
            "genre_issue",
            "REWRITE",
            _context(
                "A spell lit the gate.",
                genre=GenreSpec(name="mystery", forbidden_patterns=("spell",)),
            ),
            ("GA_FORBIDDEN_PATTERN",),
            (),
            False,
        ),
        (
            "style_issue",
            "POLISH",
            _context(
                "Mara walked slowly along the harbour wall and counted every lantern on the pier.",
                style=StyleSpec(sentence_length=3.0),
            ),
            ("SA_SENTENCE_LENGTH_DRIFT",),
            (),
            False,
        ),
        (
            "continuity_issue",
            "SPOT_FIX",
            _context(
                "Mara's blue eyes caught the light.",
                claims=(
                    _claim(
                        "FACT_CONSISTENCY",
                        "Mara",
                        "eye_color",
                        "blue",
                        location="sentence:1",
                        ref="character:mara",
                    ),
                ),
                canon=(
                    _claim("FACT_CONSISTENCY", "Mara", "eye_color", "green", ref="character:mara"),
                ),
            ),
            ("FC_CONFLICT",),
            (),
            False,
        ),
    ]


def run_revision_gold() -> RevisionGoldResult:
    engine = NarrativeAuditEngine()
    revision = RevisionEngine(RevisionPolicy(max_passes=3))
    results: list[RevisionScenarioResult] = []

    all_original_preserved = True
    all_diffs_present = True
    all_traces_complete = True
    all_reaudit_clean = True
    all_unresolved_preserved = True
    conflict_handled = False
    max_iterations_enforced = False

    for name, change_type, base, expect_resolved, expect_unresolved, expect_conflict in _scenarios():
        audit = engine.audit_context(base)
        findings = tuple(sorted({finding.code or finding.dimension for finding in audit.findings}))
        final = revision.run_bounded(
            asset_id=_AID,
            base_revision=0,
            audit=audit,
            text=base.text,
            change_type=change_type,
            re_audit=_reaudit(engine, base),
        )
        original_preserved = final.original_hash == hashlib.sha256(
            base.text.encode("utf-8")
        ).hexdigest()
        all_original_preserved = all_original_preserved and original_preserved
        diff_present = bool(final.diff)
        if expect_resolved:
            all_diffs_present = all_diffs_present and diff_present
        trace_complete = set(expect_resolved).issubset(set(final.resolved_codes)) and all(
            code in {operation.code for operation in final.operations}
            for code in final.resolved_codes
        )
        all_traces_complete = all_traces_complete and trace_complete
        re_audit = _reaudit(engine, base)
        re_audit_codes = tuple(
            sorted({finding.code or finding.dimension for finding in re_audit(final.revised_text).findings})
        )
        if expect_resolved:
            all_reaudit_clean = all_reaudit_clean and not (set(expect_resolved) & set(re_audit_codes))
        if expect_unresolved:
            all_unresolved_preserved = all_unresolved_preserved and set(expect_unresolved).issubset(
                set(final.unresolved_codes)
            )
        if expect_conflict:
            conflict_handled = expect_conflict and bool(expect_unresolved) and (
                final.revised_text == base.text
            )
        if final.pass_number <= revision.policy.max_passes:
            max_iterations_enforced = True
        results.append(
            RevisionScenarioResult(
                name=name,
                change_type=change_type,
                findings=findings,
                resolved=final.resolved_codes,
                unresolved=final.unresolved_codes,
                conflict=final.conflict_codes,
                passes=final.pass_number,
                diff_present=diff_present,
                original_hash_preserved=original_preserved,
                trace_complete=trace_complete,
                re_audit_codes=re_audit_codes,
            )
        )

    # iteration bound is hard, not advisory
    limit_enforced = False
    try:
        revision.candidate(
            project_id=_PID, asset_id=_AID, base_revision=0, pass_number=4
        )
    except RevisionLimitError:
        limit_enforced = True
    max_iterations_enforced = max_iterations_enforced and limit_enforced

    # reject must not touch canon or the artifact; approve must be atomic
    style_scenario = next(
        item for item in results if item.name == "single_style"
    )
    style_base = next(item[2] for item in _scenarios() if item[0] == "single_style")
    style_audit = engine.audit_context(style_base)
    style_execution = revision.execute(
        asset_id=_AID,
        base_revision=0,
        plan=revision.plan(
            asset_id=_AID,
            base_revision=0,
            audit=style_audit,
            change_type="POLISH",
        ),
        text=style_base.text,
        re_audit=_reaudit(engine, style_base),
    )
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "draft.txt"
        path.write_text(style_base.text, encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        rejected = revision.commit(
            execution=style_execution, approved=False, path=path, canon_hash=CANON_HASH
        )
        reject_safe = (
            not rejected.applied
            and not rejected.artifact_written
            and path.read_text(encoding="utf-8") == before
            and rejected.canon_hash_after == CANON_HASH
        )
        approved = revision.commit(
            execution=style_execution, approved=True, path=path, canon_hash=CANON_HASH
        )
        approve_atomic = (
            approved.applied
            and approved.artifact_written
            and path.read_text(encoding="utf-8") == style_execution.revised_text
            and approved.artifact_hash == style_execution.revised_hash
            and approved.canon_hash_after == CANON_HASH
        )

    checks = {
        "SEVEN_SCENARIOS": len(results) == 7,
        "ORIGINAL_HASH_PRESERVED_BEFORE_COMMIT": all_original_preserved,
        "REVISION_DIFF": all_diffs_present,
        "REAUDIT": all_reaudit_clean,
        "ISSUE_RESOLUTION_TRACE": all_traces_complete,
        "UNRESOLVED_ISSUES_PRESERVED": all_unresolved_preserved,
        "MAX_REVISION_ITERATIONS_ENFORCED": max_iterations_enforced,
        "REJECT_NO_CANON_MUTATION": reject_safe,
        "APPROVE_ATOMIC_COMMIT": approve_atomic,
        "CONFLICTING_ISSUES_HELD": conflict_handled,
    }
    details: dict[str, object] = {
        "scenario_count": len(results),
        "style_scenario_resolved": style_scenario.resolved,
        "scenario_names": [item.name for item in results],
    }
    return RevisionGoldResult(scenarios=tuple(results), checks=checks, details=details)


__all__ = ["RevisionGoldResult", "RevisionScenarioResult", "run_revision_gold"]
