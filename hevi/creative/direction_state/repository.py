"""P10a file persistence adapter (§12–13). Events are source of truth.

Layout: <root>/<direction_id>/rev_<n>/state.json + events.jsonl (+ meta.json).
- transition: validate → append event (flush+fsync) → snapshot tmp+os.replace.
  Crash between the two converges on reload (replay rewrites snapshot).
- No new ledger backend: plain files, same precedent as approvals.json/.gates.jsonl.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from hevi.creative.direction_state import machine
from hevi.creative.direction_state.errors import (
    ConflictError,
    DuplicateCommandError,
    IllegalTransitionError,
    PersistenceError,
    RevisionNotFoundError,
)
from hevi.creative.direction_state.state import (
    DirectionState,
    Lifecycle,
    ReviewEvent,
    TransitionCommand,
    TransitionEvent,
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))  # corrupt line -> fail-loud, never skip
    return out


class DirectionRepository:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    # ── paths ──
    def _rev_dir(self, direction_id: str, revision: int) -> Path:
        return self.root / direction_id / f"rev_{revision}"

    def _lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    # ── low-level IO (seams for fault injection) ──
    def _append_event(self, events_path: Path, payload: dict[str, object]) -> None:
        try:
            with events_path.open("a", encoding="utf-8") as fh:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            raise PersistenceError(f"event append failed: {exc}") from exc

    def _write_snapshot(self, state_path: Path, state: DirectionState) -> None:
        try:
            tmp = state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(state), ensure_ascii=False, sort_keys=True, indent=2),
                           encoding="utf-8")
            os.replace(tmp, state_path)
        except OSError as exc:
            raise PersistenceError(f"snapshot write failed: {exc}") from exc

    def _load_rev(self, direction_id: str, revision: int) -> tuple[DirectionState, list[dict[str, object]]]:
        rev = self._rev_dir(direction_id, revision)
        state_path, events_path = rev / "state.json", rev / "events.jsonl"
        if not state_path.is_file():
            raise RevisionNotFoundError(f"unknown revision: {direction_id} r{revision}")
        state = DirectionState(**json.loads(state_path.read_text(encoding="utf-8")))
        # lifecycle is str in json; coerce back
        object.__setattr__(state, "lifecycle", Lifecycle(state.lifecycle))
        return state, _read_jsonl(events_path)

    def _seen_commands(self, events: list[dict[str, object]]) -> dict[str, dict[str, object]]:
        return {str(e["command_id"]): e for e in events if e.get("command_id")}

    # ── API (§14) ──
    def create_direction_state(self, project_id: str, direction_id: str, actor: str = "") -> DirectionState:
        rev = self._rev_dir(direction_id, 1)
        if (rev / "state.json").is_file():
            raise DuplicateCommandError(f"direction exists: {direction_id}")
        rev.mkdir(parents=True, exist_ok=True)
        (rev / "meta.json").write_text(json.dumps({"initial": "DRAFT"}, indent=2), encoding="utf-8")
        state = DirectionState(project_id, direction_id, 1, Lifecycle.DRAFT, updated_at=_now())
        self._write_snapshot(rev / "state.json", state)
        return state

    def get_direction_state(self, direction_id: str, revision: int = 0) -> DirectionState:
        revision = revision or self._latest_revision(direction_id)
        state, _ = self._load_rev(direction_id, revision)
        return state

    def _latest_revision(self, direction_id: str) -> int:
        base = self.root / direction_id
        revs = [int(p.name.split("_")[1]) for p in base.glob("rev_*") if (p / "state.json").is_file()]
        if not revs:
            raise RevisionNotFoundError(f"unknown direction: {direction_id}")
        return max(revs)

    def transition_direction(
        self, cmd: TransitionCommand, bindings: dict[str, str] | None = None
    ) -> tuple[DirectionState, TransitionEvent | ReviewEvent | None, bool]:
        """Returns (state, event_or_none, replayed). Raises on any failure; on
        failure lifecycle/event/revision are unchanged (I6)."""
        bindings = bindings or {}
        lock = self._lock_for(f"{cmd.direction_id}:r{cmd.revision}")
        with lock:
            state, events = self._load_rev(cmd.direction_id, cmd.revision)
            seen = self._seen_commands(events)
            if cmd.command_id in seen:
                prior = seen[cmd.command_id]
                if prior.get("action") != cmd.action or int(str(prior.get("revision", -1))) != cmd.revision:
                    raise DuplicateCommandError(f"command_id reused with different payload: {cmd.command_id}")
                return state, None, True  # idempotent replay: no new event
            if cmd.expected_state and cmd.expected_state != state.lifecycle:
                raise ConflictError(
                    f"expected {cmd.expected_state}, actual {state.lifecycle} (no last-write-wins)")
            to_state = machine.resolve(state.lifecycle, cmd.action)  # I1, no mutation yet
            bound_hash = bindings.get("proposal_hash", "")
            if cmd.action == "APPROVE" and state.proposal_hash and bound_hash != state.proposal_hash:
                raise ConflictError("APPROVE proposal_hash does not match current proposal")
            if cmd.action == "COMPILE" and state.proposal_hash:
                if bound_hash != state.proposal_hash:
                    raise ConflictError("COMPILE proposal_hash does not match current proposal")
                if state.approved_proposal_hash != state.proposal_hash:
                    raise ConflictError("COMPILE requires approval bound to current proposal")
            machine.check_bindings(cmd.action, to_state, cmd.revision, bindings)  # I5
            if cmd.action == "REJECT":
                event: TransitionEvent | ReviewEvent = ReviewEvent(
                    action="REJECT", revision=cmd.revision, reason=cmd.reason,
                    actor=cmd.actor, command_id=cmd.command_id)
                self._append_event(self._rev_dir(cmd.direction_id, cmd.revision) / "events.jsonl",
                                   {"kind": "review", **asdict(event), "from_state": state.lifecycle,
                                    "to_state": state.lifecycle})
                return state, event, False  # I3: lifecycle unchanged
            new_state = DirectionState(
                state.project_id, state.direction_id, state.revision, Lifecycle(to_state),
                updated_at=_now(), version=state.version + 1,
                compile_receipt=bindings.get("compile_receipt", state.compile_receipt),
                artifact_hash=bindings.get("artifact_hash", state.artifact_hash),
                proposal_hash=bindings.get("proposal_hash", state.proposal_hash),
                approved_proposal_hash=(
                    bindings.get("proposal_hash", state.approved_proposal_hash)
                    if cmd.action == "APPROVE" else state.approved_proposal_hash
                ))
            seq = len(events) + 1
            tev = TransitionEvent(
                event_id=f"{cmd.direction_id}:r{cmd.revision}:{seq}", command_id=cmd.command_id,
                project_id=cmd.project_id, direction_id=cmd.direction_id, revision=cmd.revision,
                from_state=state.lifecycle, action=cmd.action, to_state=to_state,
                actor=cmd.actor, reason=cmd.reason, created_at=_now())
            self._append_event(self._rev_dir(cmd.direction_id, cmd.revision) / "events.jsonl",
                               {"kind": "transition", **asdict(tev)})
            self._write_snapshot(self._rev_dir(cmd.direction_id, cmd.revision) / "state.json", new_state)
            return new_state, tev, False

    def approve_direction(self, cmd: TransitionCommand, bindings: dict[str, str] | None = None) -> tuple[DirectionState, TransitionEvent | ReviewEvent | None, bool]:
        return self.transition_direction(
            TransitionCommand(cmd.command_id, cmd.project_id, cmd.direction_id, cmd.revision,
                              "APPROVE", cmd.expected_state, cmd.actor, cmd.reason, cmd.idempotency_key),
            bindings)

    def reject_direction(self, cmd: TransitionCommand) -> tuple[DirectionState, TransitionEvent | ReviewEvent | None, bool]:
        return self.transition_direction(
            TransitionCommand(cmd.command_id, cmd.project_id, cmd.direction_id, cmd.revision,
                              "REJECT", cmd.expected_state, cmd.actor, cmd.reason, cmd.idempotency_key))

    def request_changes(self, cmd: TransitionCommand) -> tuple[DirectionState, TransitionEvent | ReviewEvent | None, bool]:
        return self.transition_direction(
            TransitionCommand(cmd.command_id, cmd.project_id, cmd.direction_id, cmd.revision,
                              "REQUEST_CHANGES", cmd.expected_state, cmd.actor, cmd.reason, cmd.idempotency_key))

    def create_revision(self, direction_id: str, revision: int, actor: str,
                        command_id: str, reason: str = "") -> DirectionState:
        """VERIFIED rN -> new rN+1 at REVISION_PROPOSED. Old revision untouched."""
        lock = self._lock_for(f"{direction_id}:r{revision}")
        with lock:
            state, _ = self._load_rev(direction_id, revision)
            if state.lifecycle != Lifecycle.VERIFIED:
                raise IllegalTransitionError(
                    f"CREATE_REVISION only from VERIFIED, actual {state.lifecycle}")
            new_rev = revision + 1
            rev = self._rev_dir(direction_id, new_rev)
            if (rev / "state.json").is_file():
                raise DuplicateCommandError(f"revision exists: {direction_id} r{new_rev}")
            rev.mkdir(parents=True, exist_ok=True)
            (rev / "meta.json").write_text(
                json.dumps({"initial": "REVISION_PROPOSED", "from_revision": revision}, indent=2),
                encoding="utf-8")
            new_state = DirectionState(state.project_id, direction_id, new_rev,
                                       Lifecycle.REVISION_PROPOSED, updated_at=_now())
            self._append_event(rev / "events.jsonl",
                               {"kind": "transition", "event_id": f"{direction_id}:r{new_rev}:1",
                                "command_id": command_id, "project_id": state.project_id,
                                "direction_id": direction_id, "revision": new_rev,
                                "from_state": f"VERIFIED(r{revision})", "action": "CREATE_REVISION",
                                "to_state": "REVISION_PROPOSED", "actor": actor, "reason": reason,
                                "created_at": _now()})
            self._write_snapshot(rev / "state.json", new_state)
            return new_state

    def get_transition_history(self, direction_id: str, revision: int = 0) -> list[dict[str, object]]:
        revision = revision or self._latest_revision(direction_id)
        _, events = self._load_rev(direction_id, revision)
        return events

    def reload_direction_state(self, direction_id: str, revision: int = 0) -> DirectionState:
        """Replay events from disk; snapshot must agree or divergence is fail-loud (§13)."""
        revision = revision or self._latest_revision(direction_id)
        rev = self._rev_dir(direction_id, revision)
        meta = json.loads((rev / "meta.json").read_text(encoding="utf-8"))
        events = _read_jsonl(rev / "events.jsonl")
        current = meta["initial"]
        for e in events:
            if e.get("kind") == "transition" and not str(e.get("from_state", "")).startswith("VERIFIED(r"):
                current = e["to_state"]
        state, _ = self._load_rev(direction_id, revision)
        if state.lifecycle != current:
            # converge: events are source of truth, rewrite snapshot
            fixed = DirectionState(state.project_id, state.direction_id, state.revision,
                                   Lifecycle(current), updated_at=_now(), version=state.version + 1,
                                   compile_receipt=state.compile_receipt, artifact_hash=state.artifact_hash)
            self._write_snapshot(rev / "state.json", fixed)
            return fixed
        return state
