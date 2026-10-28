"""Tests for pipeline.skill_version: fixed install, rollback, private fork."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import get
from hevi.capabilities.skill_version import (
    fork_private,
    get_private,
    get_skill,
    install_skill,
    rollback_skill,
    version_history,
)


def _store(tmp_path: Path) -> Path:
    return tmp_path / "skill_store.json"


def test_capability_registered() -> None:
    assert get("pipeline.skill_version").name == "pipeline.skill_version"


def test_first_install_has_no_rollback_point(tmp_path: Path) -> None:
    record = install_skill(_store(tmp_path), skill_id="s1", version="1.0",
                           payload={"prompt": "v1"}, actor="soffy",
                           source="local")
    assert record["version"] == "1.0"
    assert record["rollback_point"] is None
    assert record["installed_by"] == "soffy"
    assert record["source"] == "local"


def test_second_install_sets_previous_as_rollback_point(tmp_path: Path) -> None:
    store = _store(tmp_path)
    install_skill(store, skill_id="s1", version="1.0",
                  payload={"prompt": "v1"}, actor="soffy")
    record = install_skill(store, skill_id="s1", version="2.0",
                           payload={"prompt": "v2"}, actor="soffy")
    assert record["version"] == "2.0"
    assert record["rollback_point"]["version"] == "1.0"
    assert record["rollback_point"]["payload"] == {"prompt": "v1"}


def test_rollback_restores_previous_and_consumes_point(tmp_path: Path) -> None:
    store = _store(tmp_path)
    install_skill(store, skill_id="s1", version="1.0",
                  payload={"prompt": "v1"}, actor="soffy")
    install_skill(store, skill_id="s1", version="2.0",
                  payload={"prompt": "v2"}, actor="soffy")
    rolled = rollback_skill(store, skill_id="s1", actor="soffy")
    assert rolled["version"] == "1.0"
    assert rolled["payload"] == {"prompt": "v1"}
    assert rolled["rollback_point"] is None


def test_rollback_without_point_fails_and_keeps_current(tmp_path: Path) -> None:
    store = _store(tmp_path)
    install_skill(store, skill_id="s1", version="1.0",
                  payload={"prompt": "v1"}, actor="soffy")
    before = get_skill(store, "s1")
    with pytest.raises(CapabilityError, match="no rollback point"):
        rollback_skill(store, skill_id="s1", actor="soffy")
    assert get_skill(store, "s1") == before


def test_rollback_unknown_skill_fails(tmp_path: Path) -> None:
    with pytest.raises(CapabilityError, match="unknown skill"):
        rollback_skill(_store(tmp_path), skill_id="ghost", actor="soffy")


def test_corrupt_rollback_point_fails_and_keeps_current(tmp_path: Path) -> None:
    store = _store(tmp_path)
    install_skill(store, skill_id="s1", version="1.0",
                  payload={"prompt": "v1"}, actor="soffy")
    install_skill(store, skill_id="s1", version="2.0",
                  payload={"prompt": "v2"}, actor="soffy")
    data = json.loads(store.read_text(encoding="utf-8"))
    data["skills"]["s1"]["rollback_point"]["payload"] = None
    store.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    with pytest.raises(CapabilityError, match="payload is missing"):
        rollback_skill(store, skill_id="s1", actor="soffy")
    current = get_skill(store, "s1")
    assert current["version"] == "2.0"
    assert current["payload"] == {"prompt": "v2"}


def test_private_fork_does_not_pollute_mainline(tmp_path: Path) -> None:
    store = _store(tmp_path)
    install_skill(store, skill_id="s1", version="1.0",
                  payload={"prompt": "v1", "tone": "calm"}, actor="soffy")
    private = fork_private(store, skill_id="s1", private_id="mine",
                           actor="soffy", overrides={"tone": "wild"})
    assert private["private"] is True
    assert private["base_skill_id"] == "s1"
    assert private["base_version"] == "1.0"
    assert private["payload"] == {"prompt": "v1", "tone": "wild"}
    assert get_skill(store, "s1")["payload"] == {"prompt": "v1",
                                                 "tone": "calm"}
    assert get_private(store, "mine")["payload"]["tone"] == "wild"


def test_mainline_update_does_not_overwrite_private(tmp_path: Path) -> None:
    store = _store(tmp_path)
    install_skill(store, skill_id="s1", version="1.0",
                  payload={"prompt": "v1"}, actor="soffy")
    fork_private(store, skill_id="s1", private_id="mine", actor="soffy",
                 overrides={"extra": True})
    before = get_private(store, "mine")
    install_skill(store, skill_id="s1", version="2.0",
                  payload={"prompt": "v2"}, actor="soffy")
    assert get_private(store, "mine") == before
    assert get_skill(store, "s1")["version"] == "2.0"


def test_fork_unknown_skill_refused(tmp_path: Path) -> None:
    with pytest.raises(CapabilityError, match="unknown skill"):
        fork_private(_store(tmp_path), skill_id="ghost", private_id="mine")


def test_history_records_who_when_from_to_and_rollback_point(tmp_path: Path) -> None:
    store = _store(tmp_path)
    install_skill(store, skill_id="s1", version="1.0",
                  payload={"prompt": "v1"}, actor="alice")
    install_skill(store, skill_id="s1", version="2.0",
                  payload={"prompt": "v2"}, actor="bob")
    rollback_skill(store, skill_id="s1", actor="alice")
    history = version_history(store, "s1")
    assert [h["kind"] for h in history] == ["install", "install", "rollback"]
    assert history[1]["actor"] == "bob"
    assert history[1]["from_version"] == "1.0"
    assert history[1]["to_version"] == "2.0"
    assert history[1]["rollback_point_after"] == "1.0"
    assert history[2]["from_version"] == "2.0"
    assert history[2]["to_version"] == "1.0"
    assert history[2]["rollback_point_after"] is None
    assert all(h["at"] for h in history)


def test_registry_render_install_and_rollback(tmp_path: Path) -> None:
    store = str(_store(tmp_path))
    out = tmp_path / "out"
    result = caps.get("pipeline.skill_version").render(
        {"store_path": store, "action": "install", "skill_id": "s1",
         "version": "1.0", "payload": {"prompt": "v1"}, "actor": "soffy"},
        out, duration=0.0, aspect="16:9", seed=1)
    assert result.qa["result"]["record"]["version"] == "1.0"
    caps.get("pipeline.skill_version").render(
        {"store_path": store, "action": "install", "skill_id": "s1",
         "version": "2.0", "payload": {"prompt": "v2"}, "actor": "soffy"},
        out, duration=0.0, aspect="16:9", seed=1)
    rolled = caps.get("pipeline.skill_version").render(
        {"store_path": store, "action": "rollback", "skill_id": "s1",
         "actor": "soffy"},
        out, duration=0.0, aspect="16:9", seed=1)
    assert rolled.qa["result"]["record"]["version"] == "1.0"
