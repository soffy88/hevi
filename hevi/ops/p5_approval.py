"""HEVI P5 — Approval Runtime.

Durable human approval gates integrated with P3 Mission / P4 Batch.
No second mission runtime; approvals are durable gates on existing pipeline.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hevi.ops.p5_types import (
    ApprovalPolicy,
    ApprovalPolicySet,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalType,
    ContentItem,
    ContentStatus,
    _cid,
    _now,
)


_APPROVAL_STORE_FILENAME = "approvals.json"
_CANCEL_FILENAME = "CANCEL"


class ApprovalStore:
    """Durable file-backed approval store."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self.root / _APPROVAL_STORE_FILENAME

    def save(self, item: ContentItem) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(item.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def load(self) -> ContentItem | None:
        if not self.path.is_file():
            return None
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return self._from_dict(raw)

    def _from_dict(self, raw: dict[str, Any]) -> ContentItem:
        from hevi.ops.p5_types import ContentRequest, ApprovalRequest
        req_data = raw.get("request", {})
        req = ContentRequest(**req_data) if req_data else ContentRequest()
        item = ContentItem(content_id=raw.get("content_id", ""), request=req)
        item.status = ContentStatus(raw.get("status", "CREATED"))
        item.current_revision = int(raw.get("current_revision", 1))
        item.created_at = raw.get("created_at", item.created_at)
        item.updated_at = raw.get("updated_at", item.updated_at)
        item.error = raw.get("error", "")
        item.blockers = list(raw.get("blockers", []))
        for atype_str, adata in raw.get("approvals", {}).items():
            atype = ApprovalType(atype_str)
            item.approvals[atype] = ApprovalRequest(**adata)
        return item


def create_approval(
    item: ContentItem,
    atype: ApprovalType,
    revision: int,
    artifact_refs: dict[str, str],
    reason: str = "",
    risk_flags: list[str] | None = None,
) -> ApprovalRequest:
    """Create a new approval request."""
    approval = ApprovalRequest(
        approval_id=f"appr-{uuid.uuid4().hex[:8]}",
        content_id=item.content_id,
        type=atype,
        revision=revision,
        artifact_refs=artifact_refs,
        reason=reason,
        risk_flags=risk_flags or [],
    )
    item.approvals[atype] = approval
    return approval


def check_approval_policy(policy: ApprovalPolicy, confidence: float = 1.0) -> tuple[bool, str]:
    """Evaluate approval policy. Returns (skip_approval, reason)."""
    if policy == ApprovalPolicy.SKIP:
        return True, "SKIP"
    if policy == ApprovalPolicy.AUTO_IF_CONFIDENT and confidence >= 0.9:
        return True, "AUTO_IF_CONFIDENT"
    return False, "REQUIRED"


async def wait_for_approval(
    item: ContentItem,
    atype: ApprovalType,
    store: ApprovalStore,
    timeout_s: float = 0,
    poll_interval_s: float = 5.0,
    on_status_change: Callable[[str], None] | None = None,
) -> ApprovalStatus:
    """Wait for approval decision. Returns final status."""
    approval = item.approvals.get(atype)
    if not approval:
        return ApprovalStatus.REJECTED

    start = time.monotonic()
    while True:
        if timeout_s > 0 and (time.monotonic() - start) > timeout_s:
            return ApprovalStatus.REJECTED

        reloaded = store.load()
        if reloaded:
            fresh = reloaded.approvals.get(atype)
            if fresh:
                approval.status = fresh.status
                approval.decided_at = fresh.decided_at
                approval.decided_by = fresh.decided_by
                approval.decision_reason = fresh.decision_reason

        if approval.is_terminal():
            if on_status_change:
                on_status_change(approval.status.value)
            return approval.status

        if on_status_change:
            on_status_change("PENDING")

        await asyncio.sleep(poll_interval_s)


def apply_approval_decision(
    item: ContentItem,
    atype: ApprovalType,
    status: ApprovalStatus,
    decided_by: str,
    reason: str = "",
) -> None:
    """Apply approval decision to item."""
    approval = item.approvals.get(atype)
    if not approval:
        return
    approval.status = status
    approval.decided_at = _now()
    approval.decided_by = decided_by
    approval.decision_reason = reason


def invalidate_stale_approvals(item: ContentItem, current_revision: int) -> list[ApprovalType]:
    """Invalidate approvals from previous revisions. Returns list of invalidated types."""
    invalidated = []
    for atype, approval in item.approvals.items():
        if approval.revision < item.current_revision and approval.status == ApprovalStatus.APPROVED:
            approval.status = ApprovalStatus.CANCELLED
            approval.decided_at = _now()
            approval.decided_by = "system"
            approval.decision_reason = f"STALE_REVISION: approved at rev {approval.revision}, current rev {item.current_revision}"
            invalidated.append(approval.type)
    return invalidated


class ApprovalRuntime:
    """Approval lifecycle manager integrated with content item lifecycle."""

    def __init__(self, store: ApprovalStore, policies: Any = None) -> None:
        self.store = store
        self.policies = policies or type("Policies", (), {
            "topic": "AUTO_IF_CONFIDENT",
            "script": "REQUIRED",
            "proof": "REQUIRED",
            "final": "REQUIRED",
        })()

    def request_approval(
        self,
        item: ContentItem,
        atype: ApprovalType,
        artifact_refs: dict[str, str],
        confidence: float = 1.0,
    ) -> tuple[bool, ApprovalRequest | None]:
        """Request approval. Returns (skip, request)."""
        # Use item's approval policy if available, otherwise fall back to default policies
        if item.request and item.request.approval_policy:
            policy_map = {
                ApprovalType.TOPIC: item.request.approval_policy.topic,
                ApprovalType.SCRIPT: item.request.approval_policy.script,
                ApprovalType.PROOF: item.request.approval_policy.proof,
                ApprovalType.FINAL: item.request.approval_policy.final,
            }
        else:
            policy_map = {
                ApprovalType.TOPIC: getattr(self.policies, "topic", ApprovalPolicy.REQUIRED),
                ApprovalType.SCRIPT: getattr(self.policies, "script", ApprovalPolicy.REQUIRED),
                ApprovalType.PROOF: getattr(self.policies, "proof", ApprovalPolicy.REQUIRED),
                ApprovalType.FINAL: getattr(self.policies, "final", ApprovalPolicy.REQUIRED),
            }
        policy_str = policy_map.get(atype, "REQUIRED")
        policy = ApprovalPolicy(policy_str)

        skip, reason = check_approval_policy(ApprovalPolicy(policy_str), 1.0)
        if skip:
            return True, None

        invalidate_stale_approvals(item, item.current_revision)

        approval = create_approval(
            item=item,
            atype=atype,
            revision=item.current_revision,
            artifact_refs=artifact_refs,
        )
        item.status = ContentStatus.WAITING_APPROVAL
        return False, item.approvals[atype]

    async def run_approval_gate(
        self,
        item: ContentItem,
        atype: ApprovalType,
        artifact_refs: dict[str, str],
        confidence: float = 1.0,
        timeout_s: float = 0,
    ) -> ApprovalStatus:
        """Run complete approval gate: request, wait, apply."""
        skip, approval = self.request_approval(item, atype, artifact_refs)
        if skip:
            return ApprovalStatus.APPROVED
        if not approval:
            return ApprovalStatus.REJECTED

        item.status = ContentStatus.WAITING_APPROVAL
        status = await wait_for_approval(
            item, atype, self.store, timeout_s=timeout_s,
            on_status_change=lambda s: print(f"  Approval {atype.value}: {s}")
        )
        apply_approval_decision(item, atype, status, "human", "manual decision")
        return status

    def check_all_approvals(self, item: ContentItem, required_types: list[ApprovalType]) -> tuple[bool, list[ApprovalType]]:
        """Check if all required approvals are approved."""
        missing = []
        for atype in required_types:
            approval = item.approvals.get(atype)
            if not approval or approval.status != ApprovalStatus.APPROVED:
                missing.append(atype)
        return len(missing) == 0, missing

    def get_pending_approvals(self, item: ContentItem) -> list[ApprovalRequest]:
        return [a for a in item.approvals.values() if a.status == ApprovalStatus.PENDING]


# ── Targeted Repair ────────────────────────────────────────────────────


@dataclass
class RepairRequest:
    """Structured repair request from approval changes."""
    content_id: str
    trigger_approval: ApprovalType
    reason: str
    affected_stages: list[str] = field(default_factory=list)
    preserve_stages: list[str] = field(default_factory=list)
    requested_by: str = "human"


def compute_targeted_repair(item: ContentItem, trigger: ApprovalType, reason: str) -> RepairRequest:
    """Compute minimal repair scope based on which approval triggered changes."""
    affected = []
    preserve = ["research"]

    if trigger == ApprovalType.SCRIPT:
        affected = ["tts", "visual_production", "proof", "final_render", "delivery"]
    elif trigger == ApprovalType.PROOF:
        affected = ["final_render", "delivery"]
    elif trigger == ApprovalType.FINAL:
        affected = ["delivery"]
    else:
        affected = []

    return RepairRequest(
        content_id="",
        trigger_approval=trigger,
        reason=reason,
        affected_stages=affected,
        preserve_stages=preserve,
    )


def apply_targeted_repair(item: ContentItem, repair: RepairRequest) -> None:
    """Apply targeted repair: reset affected stages, preserve others."""
    if "tts" in repair.affected_stages:
        item.voice_performance = None
    if "visual_production" in repair.affected_stages:
        item.visual_assets.clear()
    if "proof" in repair.affected_stages:
        item.proof_mp4 = ""
    if "final_render" in repair.affected_stages:
        item.final_mp4 = ""
    if "delivery" in repair.affected_stages:
        item.delivery_receipt = ""
        item.editable_project = None

    item.current_revision += 1
    item.updated_at = _now()

    invalidate_stale_approvals(item, item.current_revision)


# ── Non-blocking Batch Approval ───────────────────────────────────────


class BatchApprovalManager:
    """Manage approvals across batch - non-blocking."""

    def __init__(self, runtime: ApprovalRuntime) -> None:
        self.runtime = runtime
        self.pending: dict[str, list[ApprovalType]] = {}

    def register_waiting(self, content_id: str, atype: ApprovalType) -> None:
        self.pending.setdefault(content_id, []).append(atype)

    def notify_decision(self, content_id: str, atype: ApprovalType, status: ApprovalStatus) -> None:
        if content_id in self.pending:
            self.pending[content_id] = [a for a in self.pending[content_id] if a != atype]
            if not self.pending[content_id]:
                self.pending.pop(content_id, None)

    def get_blocked_items(self) -> list[str]:
        return list(self.pending.keys())

    def can_proceed_others(self, waiting_content_id: str, all_content_ids: list[str]) -> list[str]:
        """Return list of content IDs that can proceed while one waits."""
        return [cid for cid in all_content_ids if cid != waiting_content_id]


__all__ = [
    "ApprovalStore",
    "ApprovalRuntime",
    "BatchApprovalManager",
    "create_approval",
    "check_approval_policy",
    "wait_for_approval",
    "apply_approval_decision",
    "invalidate_stale_approvals",
    "apply_targeted_repair",
    "compute_targeted_repair",
    "ApprovalRuntime",
    "BatchApprovalManager",
]