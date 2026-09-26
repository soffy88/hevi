"""P5 approval runtime unit tests."""

from __future__ import annotations

import pytest
from pathlib import Path

from hevi.ops.p5_types import (
    ContentItem,
    ContentRequest,
    ContentStatus,
    ApprovalType,
    ApprovalStatus,
    ApprovalPolicy,
    ApprovalPolicySet,
    BookSourceBundle,
)
from hevi.ops.p5_approval import (
    ApprovalStore,
    ApprovalRuntime,
    BatchApprovalManager,
    create_approval,
    check_approval_policy,
    apply_approval_decision,
    invalidate_stale_approvals,
    compute_targeted_repair,
    apply_targeted_repair,
)


def _make_item() -> ContentItem:
    req = ContentRequest(
        topic="Test Book",
        profile_id="EMOTIONAL_BOOK_REVIEW",
        book_source=BookSourceBundle(
            book_title="Test Book",
            author="Author",
            verified_facts=["fact 1"],
        )
    )
    return ContentItem(content_id="test-item", request=req)


def test_approval_store_save_load(tmp_path) -> None:
    store = ApprovalStore(tmp_path)
    item = _make_item()
    store.save(item)

    loaded = store.load()
    assert loaded is not None
    assert loaded.content_id == "test-item"


def test_create_approval() -> None:
    item = _make_item()
    approval = create_approval(item, ApprovalType.SCRIPT, 1, {"script": "path"})
    assert approval.approval_id.startswith("appr-")
    assert approval.content_id == "test-item"
    assert approval.type == ApprovalType.SCRIPT
    assert approval.revision == 1


def test_check_approval_policy() -> None:
    skip, reason = check_approval_policy(ApprovalPolicy.SKIP)
    assert skip and reason == "SKIP"

    skip, reason = check_approval_policy(ApprovalPolicy.AUTO_IF_CONFIDENT, 0.95)
    assert skip and reason == "AUTO_IF_CONFIDENT"

    skip, reason = check_approval_policy(ApprovalPolicy.AUTO_IF_CONFIDENT, 0.5)
    assert not skip and reason == "REQUIRED"

    skip, reason = check_approval_policy(ApprovalPolicy.REQUIRED)
    assert not skip and reason == "REQUIRED"


def test_apply_approval_decision() -> None:
    item = _make_item()
    create_approval(item, "SCRIPT", 1, {})
    apply_approval_decision(item, "SCRIPT", "APPROVED", "human", "looks good")
    assert item.approvals["SCRIPT"].status == "APPROVED"
    assert item.approvals["SCRIPT"].decided_by == "human"


def test_invalidate_stale_approvals() -> None:
    item = _make_item()
    create_approval(item, "SCRIPT", 1, {})
    item.approvals["SCRIPT"].status = "APPROVED"
    item.current_revision = 2

    invalidated = invalidate_stale_approvals(item, 2)
    assert "SCRIPT" in invalidated
    assert item.approvals["SCRIPT"].status == "CANCELLED"


def test_compute_targeted_repair() -> None:
    item = _make_item()
    repair = compute_targeted_repair(item, "SCRIPT", "changes requested")
    assert "tts" in repair.affected_stages
    assert "visual_production" in repair.affected_stages
    assert "proof" in repair.affected_stages
    assert "final_render" in repair.affected_stages
    assert "delivery" in repair.affected_stages
    assert "research" in repair.preserve_stages


def test_apply_targeted_repair() -> None:
    item = _make_item()
    item.voice_performance = type("VP", (), {"audio_path": "/tmp/a.wav"})()
    item.visual_assets = [type("Asset", (), {})()]
    item.proof_mp4 = "/tmp/proof.mp4"
    item.final_mp4 = "/tmp/final.mp4"

    repair = compute_targeted_repair(item, "SCRIPT", "changes")
    repair.content_id = item.content_id
    apply_targeted_repair(item, repair)

    assert item.voice_performance is None
    assert item.visual_assets == []
    assert item.proof_mp4 == ""
    assert item.final_mp4 == ""
    assert item.current_revision == 2


def test_approval_runtime_request_approval() -> None:
    store = ApprovalStore(Path("/tmp/test_approval"))
    runtime = ApprovalRuntime(store)

    item = _make_item()
    skip, approval = runtime.request_approval(item, "SCRIPT", {"script": "path"})
    assert not skip
    assert approval is not None
    assert approval.status == "PENDING"


def test_approval_runtime_skip() -> None:
    store = ApprovalStore(Path("/tmp/test_approval"))
    runtime = ApprovalRuntime(store)

    item = _make_item()
    item.request.approval_policy.script = ApprovalPolicy.SKIP
    skip, approval = runtime.request_approval(item, ApprovalType.SCRIPT, {})
    assert skip
    assert approval is None


def test_batch_approval_manager() -> None:
    store = ApprovalStore(Path("/tmp/test_batch"))
    runtime = ApprovalRuntime(store)
    manager = BatchApprovalManager(runtime)

    manager.register_waiting("item1", "SCRIPT")
    manager.register_waiting("item2", "PROOF")

    assert "item1" in manager.get_blocked_items()
    assert "item2" in manager.get_blocked_items()

    manager.notify_decision("item1", "SCRIPT", "APPROVED")
    assert "item1" not in manager.get_blocked_items()
    assert "item2" in manager.get_blocked_items()

    can_proceed = manager.can_proceed_others("item1", ["item1", "item2", "item3"])
    assert "item2" in can_proceed
    assert "item3" in can_proceed
    assert "item1" not in can_proceed


def test_approval_status_transitions() -> None:
    item = _make_item()
    create_approval(item, "SCRIPT", 1, {})
    assert item.approvals["SCRIPT"].status == "PENDING"

    apply_approval_decision(item, "SCRIPT", "APPROVED", "human")
    assert item.approvals["SCRIPT"].status == "APPROVED"

    # Test rejected
    create_approval(item, "PROOF", 1, {})
    apply_approval_decision(item, "PROOF", "REJECTED", "human", "issues found")
    assert item.approvals["PROOF"].status == "REJECTED"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])