"""D2-C: self-healing creative production (HEVI Layer 4).

Composes the existing durability substrate — Production Graph, Artifact
Currency, Failure Transparency, Repair Actions, Durable Runtime — into
one self-healing runtime. This module adds NO second orchestrator, NO
second production graph, NO new capability taxonomy:

- ``RepairIncident`` — the single canonical record binding run + node +
  artifact + root cause + evidence + candidate actions + selected action
  + execution status + verification result.
- Deterministic-first classification: known failure signatures map to a
  repair action WITHOUT any LLM/agent call. Only genuinely creative
  decisions return ``needs_agent=True`` — and the agent may only PROPOSE
  an action into the existing Production Graph; execution stays with the
  existing runtime authority (the coordinator never executes).
- ``RepairPolicy`` gates: AUTO_SAFE / CONFIRM_REQUIRED / MANUAL_ONLY.
- Cost safety: any action that may incur new paid generation is forced
  to CONFIRM_REQUIRED unless the project policy explicitly allows
  budget-bound auto repair. The auto path never spends money.
- Enforced post-repair verification: RESOLVED requires fresh evidence
  (task + artifact + currency + presentation); otherwise REPAIR_FAILED
  or a new incident. Previous valid artifacts must be preserved.
- Loop protection: max attempts, same-action fingerprint dedupe,
  cooldown — no infinite retry.

Action kinds reuse ``RepairKind`` from ``plan_projection``; failure
codes reuse ``normalize_failure`` from ``quality.taxonomy``.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from hevi.creative.layer4.plan_projection import RepairKind
from hevi.quality.taxonomy import normalize_failure


class IncidentError(ValueError):
    """Refusal with a stable machine code."""


class RootCauseCategory(StrEnum):
    EXPIRED_DOWNLOAD_URL = "expired_download_url"
    PROVIDER_TEMP_UNAVAILABLE = "provider_temp_unavailable"
    STALE_DEPENDENCY_REVISION = "stale_dependency_revision"
    UNSUPPORTED_RESOLUTION = "unsupported_resolution"
    UNSUPPORTED_PROVIDER_PARAM = "unsupported_provider_param"
    MISSING_REFERENCE = "missing_reference"
    INVALID_ARTIFACT = "invalid_artifact"
    WORKER_RESTART = "worker_restart"
    PAID_REGENERATION_NEEDED = "paid_regeneration_needed"
    CREDENTIAL_MISSING = "credential_missing"
    RIGHTS_LICENSING = "rights_licensing"
    UNKNOWN_NEEDS_AGENT = "unknown_needs_agent"


class RepairPolicy(StrEnum):
    AUTO_SAFE = "auto_safe"
    CONFIRM_REQUIRED = "confirm_required"
    MANUAL_ONLY = "manual_only"


class IncidentStatus(StrEnum):
    OPEN = "open"
    REPAIR_PLANNED = "repair_planned"
    REPAIR_EXECUTING = "repair_executing"
    RESOLVED = "resolved"
    REPAIR_FAILED = "repair_failed"
    ESCALATED_MANUAL = "escalated_manual"


class RepairActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: RepairKind
    target_id: str = ""
    detail: str = ""
    policy: RepairPolicy = RepairPolicy.CONFIRM_REQUIRED
    estimated_cost_usd: float = Field(ge=0.0, default=0.0)
    idempotent: bool = True


class RepairIncident(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    production_run_id: str = Field(min_length=1)
    node_key: str = Field(min_length=1)
    artifact_id: str = ""
    owner_id: str = ""
    root_cause: RootCauseCategory
    failure_code: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    diagnosis: str = ""
    candidate_actions: tuple[RepairActionProposal, ...] = ()
    selected_action: RepairActionProposal | None = None
    needs_agent: bool = False
    status: IncidentStatus = IncidentStatus.OPEN
    attempts: int = 0
    verification_result: dict[str, bool] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProjectRepairPolicy(BaseModel):
    """Project-level auto-repair budget. Default: auto path spends nothing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allow_budget_bound_auto_repair: bool = False
    auto_budget_usd: float = Field(ge=0.0, default=0.0)


def _code_of(failure: str, evidence: dict[str, Any]) -> str:
    raw = str(failure or evidence.get("failure_code") or "DELIVERY_INTEGRITY")
    return normalize_failure(raw).value


def classify_deterministic(
    failure: str, evidence: dict[str, Any] | None = None
) -> tuple[RootCauseCategory, RepairActionProposal | None, bool]:
    """Deterministic root-cause classification. No LLM, no agent.

    Returns ``(root_cause, proposal, needs_agent)``. Known signatures get
    a concrete proposal with ``needs_agent=False``; anything else returns
    ``UNKNOWN_NEEDS_AGENT`` with ``needs_agent=True`` so the existing
    HEVI agent/runtime can propose a creative repair into the graph.
    """
    evidence = dict(evidence or {})
    code = _code_of(failure, evidence)
    sig = str(evidence.get("signature") or "").lower()

    if ("expired" in sig and "url" in sig) or evidence.get("download_url_expired"):
        return (
            RootCauseCategory.EXPIRED_DOWNLOAD_URL,
            RepairActionProposal(
                kind=RepairKind.RETRY_TARGET,
                detail="refresh signed URL and resume download",
                policy=RepairPolicy.AUTO_SAFE,
                estimated_cost_usd=0.0,
            ),
            False,
        )
    if ("interrupted" in sig and "download" in sig) or evidence.get("download_interrupted"):
        return (
            RootCauseCategory.EXPIRED_DOWNLOAD_URL,
            RepairActionProposal(
                kind=RepairKind.RETRY_TARGET,
                detail="resume interrupted download from byte offset",
                policy=RepairPolicy.AUTO_SAFE,
                estimated_cost_usd=0.0,
            ),
            False,
        )
    if code == "PROVIDER_FAILURE" and (
        "temporar" in sig or "timeout" in sig or evidence.get("transient")
    ):
        return (
            RootCauseCategory.PROVIDER_TEMP_UNAVAILABLE,
            RepairActionProposal(
                kind=RepairKind.RETRY_TARGET,
                detail="resume poll / retry idempotent provider stage",
                policy=RepairPolicy.AUTO_SAFE,
                estimated_cost_usd=0.0,
            ),
            False,
        )
    if "stale" in sig or evidence.get("stale_dependency_revision"):
        if evidence.get("may_incur_cost"):
            return (
                RootCauseCategory.PAID_REGENERATION_NEEDED,
                RepairActionProposal(
                    kind=RepairKind.REGENERATE_EXPLICIT,
                    detail="regenerate stale artifact (paid provider)",
                    policy=RepairPolicy.CONFIRM_REQUIRED,
                    estimated_cost_usd=float(evidence.get("estimated_cost_usd", 0.0)),
                ),
                False,
            )
        return (
            RootCauseCategory.STALE_DEPENDENCY_REVISION,
            RepairActionProposal(
                kind=RepairKind.REGENERATE_EXPLICIT,
                detail="regenerate stale artifact from local/idempotent stage",
                policy=RepairPolicy.AUTO_SAFE,
                estimated_cost_usd=0.0,
            ),
            False,
        )
    if "unsupported" in sig and "resolution" in sig:
        return (
            RootCauseCategory.UNSUPPORTED_RESOLUTION,
            RepairActionProposal(
                kind=RepairKind.REPLAN,
                detail="clamp to nearest supported resolution, no creative change",
                policy=RepairPolicy.AUTO_SAFE,
                estimated_cost_usd=0.0,
            ),
            False,
        )
    if ("unsupported" in sig and "param" in sig) or evidence.get("unsupported_param"):
        return (
            RootCauseCategory.UNSUPPORTED_PROVIDER_PARAM,
            RepairActionProposal(
                kind=RepairKind.REPLAN,
                detail="drop/adjust unsupported provider parameter",
                policy=RepairPolicy.AUTO_SAFE,
                estimated_cost_usd=0.0,
            ),
            False,
        )
    if ("missing" in sig and "reference" in sig) or evidence.get("missing_reference"):
        return (
            RootCauseCategory.MISSING_REFERENCE,
            RepairActionProposal(
                kind=RepairKind.FIX_REFERENCES,
                detail="missing reference must be supplied by a human/creative step",
                policy=RepairPolicy.MANUAL_ONLY,
                estimated_cost_usd=0.0,
                idempotent=False,
            ),
            False,
        )
    if ("invalid" in sig and "artifact" in sig) or evidence.get("invalid_artifact"):
        if evidence.get("may_incur_cost"):
            return (
                RootCauseCategory.PAID_REGENERATION_NEEDED,
                RepairActionProposal(
                    kind=RepairKind.REGENERATE_EXPLICIT,
                    detail="regenerate invalid artifact (paid provider)",
                    policy=RepairPolicy.CONFIRM_REQUIRED,
                    estimated_cost_usd=float(evidence.get("estimated_cost_usd", 0.0)),
                ),
                False,
            )
        return (
            RootCauseCategory.INVALID_ARTIFACT,
            RepairActionProposal(
                kind=RepairKind.RETRY_TARGET,
                detail="restart idempotent stage that produced the invalid artifact",
                policy=RepairPolicy.AUTO_SAFE,
                estimated_cost_usd=0.0,
            ),
            False,
        )
    if ("worker" in sig and "restart" in sig) or evidence.get("worker_restart"):
        return (
            RootCauseCategory.WORKER_RESTART,
            RepairActionProposal(
                kind=RepairKind.RETRY_TARGET,
                detail="resume from last durable checkpoint after worker restart",
                policy=RepairPolicy.AUTO_SAFE,
                estimated_cost_usd=0.0,
            ),
            False,
        )
    if "credential" in sig or "rights" in sig or "licens" in sig:
        return (
            RootCauseCategory.CREDENTIAL_MISSING
            if "credential" in sig
            else RootCauseCategory.RIGHTS_LICENSING,
            RepairActionProposal(
                kind=RepairKind.CONFIRM_AND_PROCEED,
                detail="requires human decision (credential / rights)",
                policy=RepairPolicy.MANUAL_ONLY,
                estimated_cost_usd=0.0,
                idempotent=False,
            ),
            False,
        )
    if "quota" in sig or "balance" in sig or code == "QUOTA_OR_BALANCE":
        return (
            RootCauseCategory.PAID_REGENERATION_NEEDED,
            RepairActionProposal(
                kind=RepairKind.SWITCH_PROVIDER,
                detail="quota/balance: switching provider may rebill",
                policy=RepairPolicy.CONFIRM_REQUIRED,
                estimated_cost_usd=float(evidence.get("estimated_cost_usd", 0.0)),
            ),
            False,
        )
    return RootCauseCategory.UNKNOWN_NEEDS_AGENT, None, True


def incident_fingerprint(
    *,
    root_cause: RootCauseCategory,
    node_key: str,
    action_kind: str,
    production_run_id: str = "",
) -> str:
    canonical = json.dumps(
        {
            "root_cause": root_cause.value,
            "node_key": node_key,
            "action_kind": action_kind,
            "production_run_id": production_run_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class RepairLoopGuard:
    """Loop protection: max attempts, fingerprint dedupe, cooldown."""

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        cooldown_seconds: float = 60.0,
        now: float | None = None,
    ) -> None:
        if max_attempts < 1:
            raise IncidentError("REPAIR_GUARD_MAX_ATTEMPTS_INVALID")
        self.max_attempts = max_attempts
        self.cooldown_seconds = cooldown_seconds
        self._executions: dict[str, list[float]] = {}
        self._now = now

    def _clock(self) -> float:
        return self._now if self._now is not None else time.monotonic()

    def attempts_for(self, fingerprint: str) -> int:
        return len(self._executions.get(fingerprint, ()))

    def allow(self, fingerprint: str) -> tuple[bool, str]:
        history = self._executions.get(fingerprint, ())
        if len(history) >= self.max_attempts:
            return False, "max_repair_attempts_reached"
        if history and self._clock() - history[-1] < self.cooldown_seconds:
            return False, "repair_cooldown_active"
        return True, ""

    def record(self, fingerprint: str) -> None:
        self._executions.setdefault(fingerprint, []).append(self._clock())

    def export_history(self) -> dict[str, list[float]]:
        return {key: list(values) for key, values in self._executions.items()}

    def restore_history(self, history: dict[str, list[float]]) -> None:
        """Reload attempt history after process restart (D3-C/C7)."""
        restored: dict[str, list[float]] = {}
        for key, values in (history or {}).items():
            restored[str(key)] = [float(value) for value in values]
        self._executions = restored


_REQUIRED_VERIFICATION_KEYS: tuple[str, ...] = (
    "task_ok",
    "artifact_ok",
    "currency_ok",
    "presentation_ok",
)


class SelfHealingCoordinator:
    """Policy + verification helper over the existing runtime.

    The coordinator NEVER executes provider work: ``authorize`` only
    approves an action for the existing runtime to run, and ``verify``
    only judges caller-supplied fresh evidence. Agent input arrives via
    :meth:`propose_agent_action` (a proposal into the graph, never an
    execution).
    """

    def __init__(
        self,
        *,
        project_policy: ProjectRepairPolicy | None = None,
        loop_guard: RepairLoopGuard | None = None,
    ) -> None:
        self.project_policy = project_policy or ProjectRepairPolicy()
        self.loop_guard = loop_guard or RepairLoopGuard()
        self._incidents: dict[str, RepairIncident] = {}
        self.dedupe_hits: dict[str, int] = {}

    # -- incident lifecycle --------------------------------------------

    def open_incident(
        self,
        *,
        production_run_id: str,
        node_key: str,
        failure: str,
        artifact_id: str = "",
        evidence: dict[str, Any] | None = None,
        owner_id: str = "",
    ) -> RepairIncident:
        if not production_run_id.strip() or not node_key.strip():
            raise IncidentError("REPAIR_INCIDENT_IDENTITY_REQUIRED")
        evidence = dict(evidence or {})
        root_cause, proposal, needs_agent = classify_deterministic(failure, evidence)
        incident = RepairIncident(
            incident_id=f"incident-{uuid4().hex[:12]}",
            production_run_id=production_run_id,
            node_key=node_key,
            artifact_id=artifact_id,
            owner_id=owner_id,
            root_cause=root_cause,
            failure_code=_code_of(failure, evidence),
            evidence=evidence,
            diagnosis=f"{root_cause.value} from {_code_of(failure, evidence)}",
            candidate_actions=(proposal,) if proposal is not None else (),
            needs_agent=needs_agent,
            status=IncidentStatus.OPEN,
        )
        self._incidents[incident.incident_id] = incident
        return incident

    @staticmethod
    def check_owner(incident: RepairIncident, owner_id: str) -> None:
        """Tenant isolation: an owned incident is invisible to other owners.
        Ownerless (pre-scoping) rows are quarantined from owner-scoped callers."""
        if incident.owner_id != owner_id:
            raise IncidentError("REPAIR_OWNER_MISMATCH")

    def propose_agent_action(
        self, incident_id: str, action: RepairActionProposal, *, owner_id: str = ""
    ) -> RepairIncident:
        """Agentic repair path: the agent PROPOSES; nothing executes here."""
        incident = self._get(incident_id)
        self.check_owner(incident, owner_id)
        if not incident.needs_agent:
            raise IncidentError("REPAIR_AGENT_PROPOSAL_NOT_NEEDED")
        if action.estimated_cost_usd > 0:
            action = action.model_copy(update={"policy": RepairPolicy.CONFIRM_REQUIRED})
        updated = incident.model_copy(
            update={
                "candidate_actions": (*incident.candidate_actions, action),
                "status": IncidentStatus.REPAIR_PLANNED,
            }
        )
        self._incidents[incident_id] = updated
        return updated

    # -- policy gate ----------------------------------------------------

    def authorize(
        self,
        incident_id: str,
        action: RepairActionProposal,
        *,
        confirmed: bool = False,
        owner_id: str = "",
    ) -> tuple[bool, str]:
        """Policy gate. Returns ``(approved, reason)``; never executes."""
        incident = self._get(incident_id)
        self.check_owner(incident, owner_id)
        if incident.status in (IncidentStatus.RESOLVED, IncidentStatus.REPAIR_EXECUTING):
            return False, "incident_not_repair_pending"
        policy = action.policy
        if (
            action.estimated_cost_usd > 0
            and policy is RepairPolicy.AUTO_SAFE
            and not (
                self.project_policy.allow_budget_bound_auto_repair
                and action.estimated_cost_usd <= self.project_policy.auto_budget_usd
            )
        ):
            # Cost safety: paid work can never ride the auto path unless the
            # project policy explicitly allows budget-bound auto repair.
            policy = RepairPolicy.CONFIRM_REQUIRED
        if policy is RepairPolicy.MANUAL_ONLY:
            self._store(incident, status=IncidentStatus.ESCALATED_MANUAL)
            return False, "manual_only_escalated"
        if policy is RepairPolicy.CONFIRM_REQUIRED and not confirmed:
            self._store(incident, status=IncidentStatus.REPAIR_PLANNED)
            return False, "confirmation_required"
        fingerprint = incident_fingerprint(
            root_cause=incident.root_cause,
            node_key=incident.node_key,
            action_kind=action.kind.value,
            production_run_id=incident.production_run_id,
        )
        allowed, reason = self.loop_guard.allow(fingerprint)
        if not allowed:
            self._store(incident, status=IncidentStatus.REPAIR_FAILED)
            return False, reason
        # Reserve the attempt slot at authorization time: exactly one
        # record_execution may consume each authorization.
        self.loop_guard.record(fingerprint)
        self._store(
            incident,
            status=IncidentStatus.REPAIR_EXECUTING,
            selected_action=action,
        )
        return True, "authorized"

    def record_execution(self, incident_id: str, *, owner_id: str = "") -> RepairIncident:
        """Called by the existing runtime AFTER it executes an action."""
        incident = self._get(incident_id)
        self.check_owner(incident, owner_id)
        if incident.status is not IncidentStatus.REPAIR_EXECUTING:
            raise IncidentError("REPAIR_EXECUTION_NOT_AUTHORIZED")
        if incident.selected_action is None:
            raise IncidentError("REPAIR_NO_SELECTED_ACTION")
        fingerprint = incident_fingerprint(
            root_cause=incident.root_cause,
            node_key=incident.node_key,
            action_kind=incident.selected_action.kind.value,
            production_run_id=incident.production_run_id,
        )
        # Duplicate side-effect guard: one record_execution per
        # authorization. A second record without a new authorize cycle
        # means the runtime would double-apply the action — refused.
        if self.loop_guard.attempts_for(fingerprint) != incident.attempts + 1:
            raise IncidentError("REPAIR_DUPLICATE_EXECUTION_REFUSED")
        updated = incident.model_copy(update={"attempts": incident.attempts + 1})
        self._incidents[incident_id] = updated
        return updated

    # -- verification ----------------------------------------------------

    def verify(
        self,
        incident_id: str,
        verification: dict[str, bool],
        *,
        preserved_artifact_ids: tuple[str, ...] = (),
        preserved_intact: bool = True,
        owner_id: str = "",
    ) -> RepairIncident:
        """Enforced post-repair verification. RESOLVED needs full evidence."""
        incident = self._get(incident_id)
        self.check_owner(incident, owner_id)
        if incident.status is not IncidentStatus.REPAIR_EXECUTING:
            raise IncidentError("REPAIR_VERIFY_WITHOUT_EXECUTION")
        result = {key: bool(verification.get(key, False)) for key in _REQUIRED_VERIFICATION_KEYS}
        complete = all(result.values())
        evidence = dict(incident.evidence)
        if preserved_artifact_ids:
            evidence["preserved_artifact_ids"] = list(preserved_artifact_ids)
            evidence["preserved_intact"] = bool(preserved_intact)
        if complete and (not preserved_artifact_ids or preserved_intact):
            updated = incident.model_copy(
                update={
                    "status": IncidentStatus.RESOLVED,
                    "verification_result": result,
                    "evidence": evidence,
                }
            )
        else:
            if not preserved_intact and preserved_artifact_ids:
                result["preserved_artifacts_lost"] = False
            updated = incident.model_copy(
                update={
                    "status": IncidentStatus.REPAIR_FAILED,
                    "verification_result": result,
                    "evidence": evidence,
                }
            )
        self._incidents[incident_id] = updated
        return updated

    def get(self, incident_id: str, *, owner_id: str = "") -> RepairIncident:
        incident = self._get(incident_id)
        self.check_owner(incident, owner_id)
        return incident

    def restore_single(self, incident: RepairIncident) -> None:
        """Reload one incident row (service-level fresh read before CAS)."""
        self._incidents[incident.incident_id] = incident

    def decline_incident(self, incident_id: str, *, reason: str = "user_declined", owner_id: str = "") -> RepairIncident:
        """Explicit user refusal of a CONFIRM_REQUIRED repair (D3-D/D3).

        Terminal: the repair will not execute. Recorded as ESCALATED_MANUAL
        with the refusal reason — never silently dropped, never retried.
        """
        incident = self._get(incident_id)
        self.check_owner(incident, owner_id)
        if incident.status is IncidentStatus.RESOLVED:
            raise IncidentError("REPAIR_INCIDENT_ALREADY_RESOLVED")
        updated = incident.model_copy(
            update={
                "status": IncidentStatus.ESCALATED_MANUAL,
                "diagnosis": f"{incident.diagnosis} | declined:{reason}",
            }
        )
        self._incidents[incident_id] = updated
        return updated

    def open_or_get(
        self,
        *,
        production_run_id: str,
        node_key: str,
        failure: str,
        artifact_id: str = "",
        evidence: dict[str, Any] | None = None,
        owner_id: str = "",
    ) -> RepairIncident:
        """Fingerprint dedupe: the same root cause on the same node reuses
        the already-open incident instead of creating an incident storm."""
        evidence = dict(evidence or {})
        root_cause, proposal, _ = classify_deterministic(failure, evidence)
        action_kind = proposal.kind.value if proposal is not None else "propose"
        fingerprint = incident_fingerprint(
            root_cause=root_cause,
            node_key=node_key,
            action_kind=action_kind,
            production_run_id=production_run_id,
        )
        for incident in self._incidents.values():
            if incident.status in (
                IncidentStatus.RESOLVED,
                IncidentStatus.REPAIR_FAILED,
                IncidentStatus.ESCALATED_MANUAL,
            ):
                continue
            if incident.production_run_id != production_run_id:
                continue
            if incident.selected_action is not None:
                candidate = incident.selected_action.kind.value
            elif incident.candidate_actions:
                candidate = incident.candidate_actions[0].kind.value
            else:
                candidate = "propose"
            existing = incident_fingerprint(
                root_cause=incident.root_cause,
                node_key=incident.node_key,
                action_kind=candidate,
                production_run_id=incident.production_run_id,
            )
            if existing == fingerprint:
                self.check_owner(incident, owner_id)
                self.dedupe_hits[fingerprint] = self.dedupe_hits.get(fingerprint, 0) + 1
                return incident
        return self.open_incident(
            production_run_id=production_run_id,
            node_key=node_key,
            failure=failure,
            artifact_id=artifact_id,
            evidence=evidence,
            owner_id=owner_id,
        )

    def export_state(self) -> list[dict[str, Any]]:
        """Export all incidents for durable persistence (D3-C/C7)."""
        return [incident.model_dump(mode="json") for incident in self._incidents.values()]

    def restore_state(
        self,
        incidents: list[dict[str, Any]],
        guard_history: dict[str, list[float]] | None = None,
        dedupe_hits: dict[str, int] | None = None,
    ) -> None:
        """Reload incidents + attempt/cooldown history after restart (D3-C/C7)."""
        restored: dict[str, RepairIncident] = {}
        for row in incidents or ():
            incident = RepairIncident.model_validate(row)
            restored[incident.incident_id] = incident
        self._incidents = restored
        self.loop_guard.restore_history(guard_history or {})
        self.dedupe_hits = {str(k): int(v) for k, v in (dedupe_hits or {}).items()}

    # -- internals ---------------------------------------------------------

    def _get(self, incident_id: str) -> RepairIncident:
        try:
            return self._incidents[incident_id]
        except KeyError:
            raise IncidentError(f"REPAIR_INCIDENT_UNKNOWN:{incident_id}") from None

    def _store(
        self,
        incident: RepairIncident,
        *,
        status: IncidentStatus,
        selected_action: RepairActionProposal | None = None,
    ) -> None:
        update: dict[str, Any] = {"status": status}
        if selected_action is not None:
            update["selected_action"] = selected_action
        self._incidents[incident.incident_id] = incident.model_copy(update=update)


__all__ = [
    "IncidentError",
    "IncidentStatus",
    "ProjectRepairPolicy",
    "RepairActionProposal",
    "RepairIncident",
    "RepairLoopGuard",
    "RepairPolicy",
    "RootCauseCategory",
    "SelfHealingCoordinator",
    "classify_deterministic",
    "incident_fingerprint",
]
