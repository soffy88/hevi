"""Tests for edit.editorial_project (A1-A4 model discipline).

Positive and negative case for every rule. No rendering, no
network, no provider: the model is plain dicts.
"""

import pytest

from hevi.capabilities.editorial_project import (
    activate_take,
    add_clip,
    add_edge,
    add_take,
    add_view_reference,
    apply_command,
    create_project,
    effective_asset_id,
    register_asset,
    remove_edge,
    remove_view_reference,
    replace_clip_asset,
    restore_original,
    set_pinned_output,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import get


def _project():
    project = create_project("p1")
    project = register_asset(project, "a1", "image", generation_id="g1")
    project = register_asset(project, "a2", "image", generation_id="g1")
    project = register_asset(project, "a3", "video", generation_id="g2")
    return project


def _clip_project():
    project = _project()
    return add_clip(
        project, "c1", "a1",
        start_sec=0.0, in_sec=0.0, out_sec=4.0, duration_sec=4.0,
    )


# ---------------------------------------------------------------- A1

def test_remove_view_reference_keeps_the_asset():
    project = add_view_reference(_project(), "node-1", "canvas", "a1")
    assert "a1" in project["assets"]
    project = remove_view_reference(project, "node-1")
    assert project["views"] == []
    assert "a1" in project["assets"]
    assert project["assets"]["a1"]["status"] == "ready"


def test_remove_unknown_view_fails_and_duplicate_asset_fails():
    with pytest.raises(CapabilityError):
        remove_view_reference(_project(), "nope")
    with pytest.raises(CapabilityError):
        register_asset(_project(), "a1", "image")


def test_view_reference_to_unknown_asset_fails():
    with pytest.raises(CapabilityError):
        add_view_reference(_project(), "node-1", "canvas", "ghost")


# ---------------------------------------------------------------- A2

def test_pinned_output_change_never_moves_a_clip():
    project = set_pinned_output(_clip_project(), "g1", "a2")
    assert project["pinned_outputs"]["g1"] == "a2"
    assert project["clips"]["c1"]["asset_id"] == "a1"
    assert effective_asset_id(project, "c1") == "a1"


def test_replace_clip_asset_without_confirmation_is_refused_untouched():
    project = _clip_project()
    outcome = replace_clip_asset(project, "c1", "a2", confirmed=False)
    assert outcome["applied"] is False
    assert outcome["code"] == "replacement_needs_confirmation"
    assert outcome["project"]["clips"]["c1"]["asset_id"] == "a1"
    assert project["clips"]["c1"]["asset_id"] == "a1"


def test_replace_clip_asset_with_confirmation_records_replaced_from():
    outcome = replace_clip_asset(_clip_project(), "c1", "a2", confirmed=True)
    assert outcome["applied"] is True
    clip = outcome["project"]["clips"]["c1"]
    assert clip["asset_id"] == "a2"
    assert clip["replaced_from"] == ["a1"]
    assert clip["original_asset_id"] == "a2"


def test_replace_clip_asset_to_unknown_asset_fails():
    with pytest.raises(CapabilityError):
        replace_clip_asset(_clip_project(), "c1", "ghost", confirmed=True)


def test_add_clip_rejects_bad_times():
    project = _project()
    with pytest.raises(CapabilityError):
        add_clip(project, "c1", "a1", start_sec=0.0, in_sec=0.0,
                 out_sec=4.0, duration_sec=3.0)
    with pytest.raises(CapabilityError):
        add_clip(project, "c1", "a1", start_sec=0.0, in_sec=2.0,
                 out_sec=2.0, duration_sec=0.0)
    with pytest.raises(CapabilityError):
        add_clip(project, "c1", "ghost", start_sec=0.0, in_sec=0.0,
                 out_sec=4.0, duration_sec=4.0)


# ---------------------------------------------------------------- A3

def test_take_activation_keeps_position_and_restores_original():
    project = _clip_project()
    project = add_take(project, "c1", "t1", "a3", duration_sec=4.0,
                       source="derived")
    outcome = activate_take(project, "c1", "t1")
    assert outcome["applied"] is True
    project = outcome["project"]
    clip = project["clips"]["c1"]
    assert clip["start_sec"] == 0.0
    assert clip["duration_sec"] == 4.0
    assert clip["original_asset_id"] == "a1"
    assert effective_asset_id(project, "c1") == "a3"
    outcome = restore_original(project, "c1")
    assert outcome["applied"] is True
    assert effective_asset_id(outcome["project"], "c1") == "a1"
    assert len(outcome["project"]["clips"]["c1"]["takes"]) == 1


def test_take_too_short_cannot_be_activated():
    project = _clip_project()
    project = add_take(project, "c1", "t1", "a3", duration_sec=2.0,
                       source="derived")
    outcome = activate_take(project, "c1", "t1")
    assert outcome["applied"] is False
    assert outcome["code"] == "take_too_short"
    assert effective_asset_id(outcome["project"], "c1") == "a1"


def test_take_exactly_covering_the_slot_activates():
    project = _clip_project()
    project = add_take(project, "c1", "t1", "a3", duration_sec=4.0,
                       source="imported")
    assert activate_take(project, "c1", "t1")["applied"] is True


def test_restore_without_active_take_is_refused():
    outcome = restore_original(_clip_project(), "c1")
    assert outcome["applied"] is False
    assert outcome["code"] == "no_active_take"


def test_add_take_rejects_unknown_source_and_duplicate_id():
    project = _clip_project()
    with pytest.raises(CapabilityError):
        add_take(project, "c1", "t1", "a3", duration_sec=4.0, source="weird")
    project = add_take(project, "c1", "t1", "a3", duration_sec=4.0,
                       source="original")
    with pytest.raises(CapabilityError):
        add_take(project, "c1", "t1", "a3", duration_sec=4.0, source="original")


# ------------------------------------------------------- A4 lineage / edges

def test_edge_changes_never_touch_lineage():
    project = _project()
    project = register_asset(project, "a4", "image", generation_id="g3",
                             derived_from="a1")
    assert project["lineage"] == [
        {"child_asset_id": "a4", "parent_asset_id": "a1",
         "generation_id": "g3"}
    ]
    before = list(project["lineage"])
    project = add_edge(project, "n1", "n2")
    assert project["lineage"] == before
    project = remove_edge(project, "n1", "n2")
    assert project["lineage"] == before
    assert project["edges"] == []


def test_deriving_an_asset_creates_no_edge():
    project = register_asset(_project(), "a4", "image", derived_from="a1")
    assert project["edges"] == []
    assert len(project["lineage"]) == 1


# ------------------------------------------------------- revision / CAS path

def _cmd(op, payload, key, revision, command_id=None):
    return apply_command(
        _project(),
        {"op": op, "payload": payload, "command_id": command_id},
        expected_revision=revision, idempotency_key=key,
    )


def test_apply_command_advances_revision_by_one_and_stores_receipt():
    outcome = _cmd("register_asset", {"asset_id": "a9", "kind": "image"},
                   "k1", 0, command_id="cmd-1")
    assert outcome["applied"] is True
    assert outcome["project"]["revision"] == 1
    assert outcome["receipt"]["revision"] == 1
    assert "a9" in outcome["project"]["assets"]


def test_apply_command_replay_returns_receipt_without_reexecuting():
    project = _project()
    first = apply_command(
        project, {"op": "register_asset", "payload": {"asset_id": "a9", "kind": "image"}},
        expected_revision=0, idempotency_key="k1",
    )
    assert first["applied"] is True
    second = apply_command(
        first["project"],
        {"op": "register_asset", "payload": {"asset_id": "a9", "kind": "image"}},
        expected_revision=0, idempotency_key="k1",
    )
    assert second["replayed"] is True
    assert second["applied"] is False
    assert second["project"]["revision"] == 1
    assert second["receipt"] == first["receipt"]


def test_apply_command_revision_conflict_applies_nothing():
    outcome = _cmd("register_asset", {"asset_id": "a9", "kind": "image"},
                   "k1", 5)
    assert outcome["applied"] is False
    assert outcome["code"] == "revision_conflict"
    assert outcome["current_revision"] == 0
    assert "a9" not in outcome["project"]["assets"]
    assert outcome["project"]["revision"] == 0


def test_apply_command_whole_replace_is_refused():
    for op in ("replace_document", "replace_project", "set_state"):
        outcome = apply_command(
            _project(), {"op": op, "payload": {"revision": 99}},
            expected_revision=0, idempotency_key=f"k-{op}",
        )
        assert outcome["applied"] is False
        assert outcome["code"] == "whole_replace_refused"
        assert outcome["project"]["revision"] == 0


def test_apply_command_unknown_op_raises_and_bad_key_raises():
    with pytest.raises(CapabilityError):
        _cmd("teleport", {}, "k1", 0)
    with pytest.raises(CapabilityError):
        apply_command(_project(), {"op": "register_asset", "payload": {}},
                      expected_revision=0, idempotency_key="")


def test_apply_command_unconfirmed_replace_is_a_state_refusal_not_a_raise():
    project = _clip_project()
    outcome = apply_command(
        project,
        {"op": "replace_clip_asset",
         "payload": {"clip_id": "c1", "new_asset_id": "a2", "confirmed": False}},
        expected_revision=0, idempotency_key="k1",
    )
    assert outcome["applied"] is False
    assert outcome["code"] == "replacement_needs_confirmation"
    assert outcome["project"]["revision"] == 0
    assert outcome["project"]["clips"]["c1"]["asset_id"] == "a1"


def test_apply_command_does_not_mutate_input_project():
    import json
    project = _project()
    before = json.dumps(project, sort_keys=True)
    apply_command(
        project, {"op": "register_asset", "payload": {"asset_id": "a9", "kind": "image"}},
        expected_revision=0, idempotency_key="k1",
    )
    assert json.dumps(project, sort_keys=True) == before


def test_capability_registered():
    assert get("edit.editorial_project") is not None
