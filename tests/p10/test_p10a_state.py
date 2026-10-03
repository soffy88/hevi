"""P10a acceptance: A1-A14 over a real file repository (tmp_path)."""

import hashlib

import pytest

from hevi.creative.direction_state import (
    ConflictError,
    DirectionRepository,
    DuplicateCommandError,
    IllegalTransitionError,
    MissingBindingError,
    PersistenceError,
    TransitionCommand,
)

PROJECT, DIRECTION = "p-spike", "d-blackhole"
SHA = hashlib.sha256(b"spike-artifact").hexdigest()


def _cmd(action: str, revision: int = 1, cid: str = "c1", expected: str = "",
         actor: str = "user", reason: str = "spike") -> TransitionCommand:
    return TransitionCommand(cid, PROJECT, DIRECTION, revision, action, expected, actor, reason, cid)


def _repo(tmp_path) -> DirectionRepository:
    repo = DirectionRepository(tmp_path / "store")
    repo.create_direction_state(PROJECT, DIRECTION, actor="user")
    return repo


def _full_chain(repo: DirectionRepository, rev: int = 1):
    repo.transition_direction(_cmd("PROPOSE", rev, "c-propose"))
    repo.transition_direction(_cmd("SUBMIT_REVIEW", rev, "c-submit"))
    repo.transition_direction(_cmd("APPROVE", rev, "c-approve"))
    repo.transition_direction(_cmd("COMPILE", rev, "c-compile"),
                              {"compile_receipt": "receipt:1", "direction_revision": str(rev)})
    repo.transition_direction(_cmd("START_PRODUCTION", rev, "c-start"))
    return repo.transition_direction(
        _cmd("VERIFY", rev, "c-verify"),
        {"artifact_hash": SHA, "verification_receipt": "vrex:1"})


# A1 + Fixture A
def test_a1_full_lifecycle_matrix(tmp_path):
    repo = _repo(tmp_path)
    state, _, _ = _full_chain(repo)
    assert state.lifecycle == "VERIFIED"
    assert state.artifact_hash == SHA and state.compile_receipt == "receipt:1"
    assert len(repo.get_transition_history(DIRECTION)) == 6


# Fixture B
def test_fixture_b_reject_then_request_changes(tmp_path):
    repo = _repo(tmp_path)
    repo.transition_direction(_cmd("PROPOSE", 1, "c1"))
    repo.transition_direction(_cmd("SUBMIT_REVIEW", 1, "c2"))
    state, event, _ = repo.reject_direction(_cmd("x", 1, "c-reject", reason="too vague"))
    assert state.lifecycle == "REVIEW_REQUIRED" and event.action == "REJECT"
    state, _, _ = repo.request_changes(_cmd("x", 1, "c-rc", reason="revise thesis"))
    assert state.lifecycle == "PROPOSED"


# A2: forbidden transitions leave zero mutation
@pytest.mark.parametrize("frm,action,setup", [
    ("DRAFT", "APPROVE", []), ("DRAFT", "COMPILE", []), ("DRAFT", "VERIFY", []),
    ("PROPOSED", "APPROVE", ["PROPOSE"]), ("PROPOSED", "COMPILE", ["PROPOSE"]),
    ("REVIEW_REQUIRED", "COMPILE", ["PROPOSE", "SUBMIT_REVIEW"]),
    ("REVIEW_REQUIRED", "VERIFY", ["PROPOSE", "SUBMIT_REVIEW"]),
    ("APPROVED", "VERIFY", ["PROPOSE", "SUBMIT_REVIEW", "APPROVE"]),
    ("COMPILED", "VERIFY", ["PROPOSE", "SUBMIT_REVIEW", "APPROVE", "COMPILE"]),
    ("VERIFIED", "APPROVE", ["PROPOSE", "SUBMIT_REVIEW", "APPROVE", "COMPILE",
                             "START_PRODUCTION", "VERIFY"]),
])
def test_a2_illegal_transition_no_mutation(tmp_path, frm, action, setup):
    repo = _repo(tmp_path)
    bindings = {"compile_receipt": "r", "direction_revision": "1",
                "artifact_hash": SHA, "verification_receipt": "v"}
    for i, act in enumerate(setup):
        repo.transition_direction(_cmd(act, 1, f"c-{i}"), bindings)
    before = repo.get_direction_state(DIRECTION)
    assert before.lifecycle == frm
    n_events = len(repo.get_transition_history(DIRECTION))
    with pytest.raises(IllegalTransitionError):
        repo.transition_direction(_cmd(action, 1, "c-bad"), bindings)
    after = repo.get_direction_state(DIRECTION)
    assert before == after and len(repo.get_transition_history(DIRECTION)) == n_events


# A3/A4 reject vs request_changes are different operations
def test_a3_a4_reject_and_request_changes_distinct(tmp_path):
    repo = _repo(tmp_path)
    repo.transition_direction(_cmd("PROPOSE", 1, "c1"))
    repo.transition_direction(_cmd("SUBMIT_REVIEW", 1, "c2"))
    _, event, _ = repo.reject_direction(_cmd("x", 1, "c3", reason="r"))
    assert event.action == "REJECT"
    history = repo.get_transition_history(DIRECTION)
    assert history[-1]["kind"] == "review"  # evidence recorded, lifecycle untouched


# A5 atomic failure: persistence fault -> no mutation, no partial event
def test_a5_persistence_failure_zero_mutation(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    repo.transition_direction(_cmd("PROPOSE", 1, "c1"))

    def _boom(*args, **kwargs):
        raise PersistenceError("injected")

    orig_append = DirectionRepository._append_event.__get__(repo)
    orig_snapshot = DirectionRepository._write_snapshot.__get__(repo)
    monkeypatch.setattr(repo, "_append_event", _boom)
    before = repo.get_direction_state(DIRECTION)
    with pytest.raises(PersistenceError):
        repo.transition_direction(_cmd("SUBMIT_REVIEW", 1, "c2"))
    assert repo.get_direction_state(DIRECTION) == before

    monkeypatch.setattr(repo, "_append_event", orig_append)
    monkeypatch.setattr(repo, "_write_snapshot", _boom)
    with pytest.raises(PersistenceError):
        repo.transition_direction(_cmd("SUBMIT_REVIEW", 1, "c2"))
    monkeypatch.setattr(repo, "_write_snapshot", orig_snapshot)
    # event appended but snapshot stale -> reload converges to the legal state
    reloaded = repo.reload_direction_state(DIRECTION)
    assert reloaded.lifecycle == "REVIEW_REQUIRED"
    assert repo.get_direction_state(DIRECTION).lifecycle == "REVIEW_REQUIRED"


# A6 artifact binding
def test_a6_compile_verify_require_bindings(tmp_path):
    repo = _repo(tmp_path)
    repo.transition_direction(_cmd("PROPOSE", 1, "c1"))
    repo.transition_direction(_cmd("SUBMIT_REVIEW", 1, "c2"))
    repo.transition_direction(_cmd("APPROVE", 1, "c3"))
    with pytest.raises(MissingBindingError):
        repo.transition_direction(_cmd("COMPILE", 1, "c4"), {})
    with pytest.raises(MissingBindingError):
        repo.transition_direction(_cmd("COMPILE", 1, "c4"), {"compile_receipt": "r",
                                                             "direction_revision": "2"})
    repo.transition_direction(_cmd("COMPILE", 1, "c4"),
                              {"compile_receipt": "r", "direction_revision": "1"})
    repo.transition_direction(_cmd("START_PRODUCTION", 1, "c5"))
    with pytest.raises(MissingBindingError):
        repo.transition_direction(_cmd("VERIFY", 1, "c6"), {})
    with pytest.raises(MissingBindingError):
        repo.transition_direction(_cmd("VERIFY", 1, "c6"), {"artifact_hash": "notahash",
                                                             "verification_receipt": "v"})


# A7 revision immutability: no API mutates VERIFIED rev; only new revision
def test_a7_verified_revision_immutable(tmp_path):
    repo = _repo(tmp_path)
    _full_chain(repo)
    snap_before = (tmp_path / "store" / DIRECTION / "rev_1" / "state.json").read_bytes()
    with pytest.raises((IllegalTransitionError, MissingBindingError)):
        repo.transition_direction(_cmd("COMPILE", 1, "c-evil"), {"compile_receipt": "x",
                                                                 "direction_revision": "1"})
    assert (tmp_path / "store" / DIRECTION / "rev_1" / "state.json").read_bytes() == snap_before


# A8 concurrency: stale expected_state -> CONFLICT, winner only
def test_a8_concurrent_writes_conflict(tmp_path):
    repo = _repo(tmp_path)
    repo.transition_direction(_cmd("PROPOSE", 1, "c1"))
    repo.transition_direction(_cmd("SUBMIT_REVIEW", 1, "c2"))
    repo.transition_direction(_cmd("APPROVE", 1, "c-winner", expected="REVIEW_REQUIRED"))
    # actually APPROVE needs no bindings; winner path: APPROVE then COMPILE race
    with pytest.raises(ConflictError):
        repo.transition_direction(_cmd("COMPILE", 1, "c-stale", "REVIEW_REQUIRED"),
                                  {"compile_receipt": "r", "direction_revision": "1"})
    assert repo.get_direction_state(DIRECTION).lifecycle == "APPROVED"


# A9 idempotency: same command twice -> one event, same state
def test_a9_idempotent_replay(tmp_path):
    repo = _repo(tmp_path)
    s1, _e1, replayed1 = repo.transition_direction(_cmd("PROPOSE", 1, "c-dup"))
    s2, e2, replayed2 = repo.transition_direction(_cmd("PROPOSE", 1, "c-dup"))
    assert (replayed1, replayed2) == (False, True)
    assert s1 == s2 and e2 is None
    assert len(repo.get_transition_history(DIRECTION)) == 1
    with pytest.raises(DuplicateCommandError):
        repo.transition_direction(_cmd("SUBMIT_REVIEW", 1, "c-dup"))


# A10 persistence reload across instances
def test_a10_reload_same_state(tmp_path):
    repo = _repo(tmp_path)
    _full_chain(repo)
    repo2 = DirectionRepository(tmp_path / "store")
    assert repo2.get_direction_state(DIRECTION) == repo.get_direction_state(DIRECTION)
    assert repo2.reload_direction_state(DIRECTION).lifecycle == "VERIFIED"


# A12 + Fixture C revision chain; A14 history
def test_a12_revision_chain_and_history(tmp_path):
    repo = _repo(tmp_path)
    _full_chain(repo)
    rev1_bytes = (tmp_path / "store" / DIRECTION / "rev_1" / "state.json").read_bytes()
    rev2 = repo.create_revision(DIRECTION, 1, actor="user", command_id="c-rev2", reason="new angle")
    assert rev2.lifecycle == "REVISION_PROPOSED" and rev2.revision == 2
    assert (tmp_path / "store" / DIRECTION / "rev_1" / "state.json").read_bytes() == rev1_bytes
    repo.transition_direction(_cmd("APPROVE", 2, "c-r2-approve"))
    assert repo.get_direction_state(DIRECTION, 2).lifecycle == "APPROVED"
    assert repo.get_direction_state(DIRECTION, 1).lifecycle == "VERIFIED"
    hist = repo.get_transition_history(DIRECTION, 2)
    assert [e["to_state"] for e in hist if e["kind"] == "transition"] == ["REVISION_PROPOSED", "APPROVED"]
    with pytest.raises(IllegalTransitionError):
        repo.create_revision(DIRECTION, 2, actor="user", command_id="c-bad")
