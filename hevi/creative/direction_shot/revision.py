"""P10-E ShotSpec revision store: append-only chain, file adapter.

Layout (same precedent as P10a DirectionRepository — plain files, no new ledger):
    <root>/<direction_id>/shot_r<n>/specs.json     written once, never rewritten
    <root>/<direction_id>/shot_r<n>/events.jsonl   append-only, source of truth

Invariants this layer owns (P10a doctrine, applied to shot level):
  - a revision's spec payload is immutable; status changes are events, so no
    operation ever rewrites an existing specs.json
  - on any raise, nothing is written (validate → append event → create dir/file)
  - same command_id + same payload replays without mutation; the same id with a
    different payload is rejected
  - each revision links to the prior one by chain hash, so a rewritten or
    reordered spec set is detectable by recomputation (verify_chain)
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hevi.creative.direction_plan.models import Anchor, CameraSpec, Movement, TimeBinding
from hevi.creative.direction_shot.contracts import ShotSpec, ShotTiming, ShotVerification
from hevi.creative.direction_shot.errors import (
    ChainBrokenError,
    ShotSpecError,
    ShotSpecImmutableError,
    ShotSpecNotFoundError,
)
from hevi.creative.direction_shot.hashing import chain_hash, is_hash, shot_spec_hash
from hevi.creative.direction_shot.validator import ShotRefIndex, validate_shot_specs

REVISION_STATUSES = ("DRAFT", "APPROVED", "SUPERSEDED")
_REV_PREFIX = "shot_r"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))  # corrupt line -> fail-loud, never skip
    return out


def _payload_digest(specs: tuple[ShotSpec, ...]) -> str:
    """Digest of one revision's ordered spec set, independent of its predecessor.

    Used as the idempotency fingerprint: replaying a command with the same
    command_id *and* the same payload is a no-op, a different payload is not.
    """
    return chain_hash("", [shot_spec_hash(s) for s in specs])


# ── wire format ──


def _spec_to_wire(spec: ShotSpec) -> dict[str, Any]:
    return asdict(spec)


def _spec_from_wire(payload: dict[str, Any]) -> ShotSpec:
    timing = payload["timing"]
    movement = payload["camera"].get("movement", {})
    return ShotSpec(
        shot_id=payload["shot_id"],
        revision=int(payload["revision"]),
        timing=ShotTiming(
            start=_binding_from_wire(timing["start"]),
            end=_binding_from_wire(timing["end"])),
        camera=CameraSpec(
            shot_size=payload["camera"].get("shot_size", "wide"),
            framing=payload["camera"].get("framing", ""),
            angle=payload["camera"].get("angle", "eye"),
            lens=payload["camera"].get("lens", "normal"),
            depth=payload["camera"].get("depth", ""),
            composition=payload["camera"].get("composition", ""),
            lighting=payload["camera"].get("lighting", ""),
            blocking=payload["camera"].get("blocking", ""),
            movement=Movement(
                type=movement.get("type", "static"),
                geometry_class=movement.get("geometry_class", "extrinsic"),
                motivation_type=movement.get("motivation_type", ""),
                motivation_reason=movement.get("motivation_reason", ""),
                intensity=movement.get("intensity", "subtle"),
                magnitude_metric=movement.get("magnitude_metric", ""),
                mag_min=float(movement.get("mag_min", 0.0)),
                mag_max=float(movement.get("mag_max", 0.0)))),
        beat_ref=payload.get("beat_ref", ""),
        cue_refs=tuple(payload.get("cue_refs", ())),
        decision_refs=tuple(payload.get("decision_refs", ())),
        verification=tuple(ShotVerification(**c) for c in payload.get("verification", ())),
        content_pins=dict(payload.get("content_pins", {})),
        authority_pins=tuple(payload.get("authority_pins", ())),
        status=payload.get("status", "DRAFT"),
        spec_hash=payload.get("spec_hash", ""),
    )


def _binding_from_wire(payload: dict[str, Any]) -> TimeBinding:
    anchor = payload["anchor"]
    return TimeBinding(
        anchor=Anchor(
            type=anchor.get("type", ""), target=anchor.get("target", ""),
            edge=anchor.get("edge", "end"), offset_ms=int(anchor.get("offset_ms", 0)),
            coordinate=anchor.get("coordinate", "film-global")),
        tolerance_class=payload.get("tolerance_class", "EVENT_LOOSE"))


@dataclass(frozen=True)
class ShotSpecRevision:
    direction_id: str
    revision: int
    status: str
    specs: tuple[ShotSpec, ...]
    previous_chain_hash: str = ""
    chain_hash: str = ""

    def spec_hashes(self) -> tuple[str, ...]:
        return tuple(s.spec_hash for s in self.specs)

    def recompute_chain_hash(self) -> str:
        return chain_hash(self.previous_chain_hash, self.spec_hashes())


class ShotSpecRevisionStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    # ── paths ──
    def _rev_dir(self, direction_id: str, revision: int) -> Path:
        return self.root / direction_id / f"shot_r{revision}"

    def _lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    # ── IO seams (fault injection points) ──
    def _append_event(self, path: Path, payload: dict[str, Any]) -> None:
        try:
            with path.open("a", encoding="utf-8") as fh:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            raise ShotSpecError(f"shot revision event append failed: {exc}",
                                code="SHOT_PERSISTENCE_FAILED") from exc

    def _write_snapshot(self, path: Path, payload: dict[str, Any]) -> None:
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
                           encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            raise ShotSpecError(f"shot revision snapshot write failed: {exc}",
                                code="SHOT_PERSISTENCE_FAILED") from exc

    # ── read ──
    def _load_payload(self, direction_id: str, revision: int) -> dict[str, Any]:
        path = self._rev_dir(direction_id, revision) / "specs.json"
        if not path.is_file():
            raise ShotSpecNotFoundError(f"unknown shot revision: {direction_id} r{revision}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        specs = tuple(_spec_from_wire(s) for s in payload["specs"])
        for spec in specs:
            if not is_hash(spec.spec_hash):
                raise ChainBrokenError(
                    f"shot {spec.shot_id} r{revision}: spec_hash missing or not sha256")
            if spec.spec_hash != shot_spec_hash(spec):
                raise ChainBrokenError(
                    f"shot {spec.shot_id} r{revision}: spec_hash does not match payload")
        return {"payload": payload, "specs": specs, "events": _read_jsonl(
            self._rev_dir(direction_id, revision) / "events.jsonl")}

    def _revisions(self, direction_id: str) -> list[int]:
        base = self.root / direction_id
        if not base.is_dir():
            return []
        return sorted(int(p.name.removeprefix(_REV_PREFIX)) for p in base.glob(f"{_REV_PREFIX}*")
                      if (p / "specs.json").is_file())

    def _status_from_events(self, events: list[dict[str, Any]]) -> str:
        status = "DRAFT"
        for event in events:
            if event.get("kind") == "status":
                status = str(event["to_status"])
                if status not in REVISION_STATUSES:  # corrupt log -> fail-loud
                    raise ShotSpecError(f"unknown revision status in log: {status}",
                                        code="SHOT_BAD_STATUS")
        return status

    def _assemble(self, direction_id: str, revision: int) -> ShotSpecRevision:
        loaded = self._load_payload(direction_id, revision)
        payload, specs, events = loaded["payload"], loaded["specs"], loaded["events"]
        return ShotSpecRevision(
            direction_id=direction_id, revision=revision,
            status=self._status_from_events(events), specs=specs,
            previous_chain_hash=payload.get("previous_chain_hash", ""),
            chain_hash=payload.get("chain_hash", ""))

    def get_revision(self, direction_id: str, revision: int = 0) -> ShotSpecRevision:
        revision = revision or self.latest_revision(direction_id)
        return self._assemble(direction_id, revision)

    def latest_revision(self, direction_id: str) -> int:
        revs = self._revisions(direction_id)
        if not revs:
            raise ShotSpecNotFoundError(f"unknown shot direction: {direction_id}")
        return revs[-1]

    def revision_statuses(self, direction_id: str) -> dict[int, str]:
        return {r: self._assemble(direction_id, r).status for r in self._revisions(direction_id)}

    # ── idempotency ──
    @staticmethod
    def _seen(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {str(e["command_id"]): e for e in events if e.get("command_id")}

    def _replay_guard(self, events: list[dict[str, Any]], *, command_id: str,
                      action: str, revision: int, payload_digest: str) -> bool:
        prior = self._seen(events).get(command_id)
        if prior is None:
            return False
        if (prior.get("action") != action or int(str(prior.get("revision", -1))) != revision
                or prior.get("payload_digest") != payload_digest):
            raise ShotSpecError(f"command_id reused with different payload: {command_id}",
                                code="SHOT_DUPLICATE_COMMAND")
        return True

    # ── write path (validate → append event → create immutable snapshot) ──
    def _commit(self, *, direction_id: str, revision: int, specs: tuple[ShotSpec, ...],
                previous_chain: str, action: str, actor: str, command_id: str,
                reason: str, payload_digest: str) -> None:
        mismatched = [s.shot_id for s in specs if s.revision != revision]
        if mismatched:
            raise ShotSpecError(
                f"spec revision does not match r{revision}: {sorted(mismatched)}",
                code="SHOT_REVISION_MISMATCH")
        rev_dir = self._rev_dir(direction_id, revision)
        rev_dir.mkdir(parents=True, exist_ok=True)
        sealed = tuple(s.sealed() for s in specs)
        record = {
            "direction_id": direction_id,
            "revision": revision,
            "previous_chain_hash": previous_chain,
            "chain_hash": chain_hash(previous_chain, [s.spec_hash for s in sealed]),
            "specs": [_spec_to_wire(s) for s in sealed],
        }
        self._write_snapshot(rev_dir / "specs.json", record)
        self._append_event(rev_dir / "events.jsonl", {
            "kind": "revision", "action": action, "command_id": command_id,
            "direction_id": direction_id, "revision": revision, "actor": actor,
            "reason": reason, "payload_digest": payload_digest,
            "chain_hash": record["chain_hash"], "created_at": _now(),
        })

    # ── API ──
    def create_revision(self, direction_id: str, specs: tuple[ShotSpec, ...], *,
                        actor: str, command_id: str,
                        index: ShotRefIndex | None = None) -> ShotSpecRevision:
        """First revision for a direction, at DRAFT. Refuses to overwrite."""
        digest = _payload_digest(specs)
        with self._lock_for(direction_id):
            existing = self._revisions(direction_id)
            if existing:
                raise ShotSpecError(f"shot direction already exists: {direction_id}",
                                    code="SHOT_DIRECTION_EXISTS")
            if index is not None:
                validate_shot_specs(list(specs), index).raise_for_blocking()
            self._commit(direction_id=direction_id, revision=1, specs=specs,
                         previous_chain="", action="CREATE_REVISION", actor=actor,
                         command_id=command_id, reason="", payload_digest=digest)
            return self._assemble(direction_id, 1)

    def revise(self, direction_id: str, specs: tuple[ShotSpec, ...], *,
               actor: str, command_id: str, reason: str = "",
               index: ShotRefIndex | None = None) -> ShotSpecRevision:
        """APPROVED head rN -> new rN+1 at DRAFT. rN's payload is never touched."""
        digest = _payload_digest(specs)
        with self._lock_for(direction_id):
            head = self.latest_revision(direction_id)
            loaded = self._load_payload(direction_id, head)
            if self._replay_guard(loaded["events"], command_id=command_id,
                                  action="REVISE", revision=head, payload_digest=digest):
                return self._assemble(direction_id, head)
            current = self._assemble(direction_id, head)
            if current.status != "APPROVED":
                raise ShotSpecError(
                    f"revise requires an APPROVED head, r{head} is {current.status}",
                    code="SHOT_REVISION_NOT_APPROVED")
            new_rev = head + 1
            if index is not None:
                validate_shot_specs(list(specs), index).raise_for_blocking()
            self._commit(direction_id=direction_id, revision=new_rev, specs=specs,
                         previous_chain=current.chain_hash, action="REVISE", actor=actor,
                         command_id=command_id, reason=reason, payload_digest=digest)
            self._append_event(
                self._rev_dir(direction_id, head) / "events.jsonl",
                {"kind": "status", "action": "SUPERSEDE", "command_id": f"{command_id}:supersede",
                 "direction_id": direction_id, "revision": head, "to_status": "SUPERSEDED",
                 "superseded_by": new_rev, "actor": actor, "created_at": _now()})
            return self._assemble(direction_id, new_rev)

    def approve_revision(self, direction_id: str, revision: int, *, index: ShotRefIndex,
                         actor: str, command_id: str,
                         reason: str = "") -> ShotSpecRevision:
        """DRAFT -> APPROVED. Validator must be clean; nothing is written otherwise."""
        digest = ""
        with self._lock_for(direction_id):
            loaded = self._load_payload(direction_id, revision)
            if self._replay_guard(loaded["events"], command_id=command_id,
                                  action="APPROVE", revision=revision,
                                  payload_digest=digest):
                return self._assemble(direction_id, revision)
            current = self._assemble(direction_id, revision)
            if current.status != "DRAFT":
                raise ShotSpecImmutableError(
                    f"r{revision} is {current.status}; only DRAFT may be approved")
            validate_shot_specs(list(current.specs), index).raise_for_blocking()
            self._append_event(
                self._rev_dir(direction_id, revision) / "events.jsonl",
                {"kind": "status", "action": "APPROVE", "command_id": command_id,
                 "direction_id": direction_id, "revision": revision,
                 "to_status": "APPROVED", "actor": actor, "reason": reason,
                 "payload_digest": digest, "created_at": _now()})
            return self._assemble(direction_id, revision)

    def verify_chain(self, direction_id: str) -> tuple[str, ...]:
        """Recompute every link; disagreement is ChainBrokenError (no repair, no skip)."""
        with self._lock_for(direction_id):
            revisions = self._revisions(direction_id)
            if not revisions:
                raise ShotSpecNotFoundError(f"unknown shot direction: {direction_id}")
            previous = ""
            for revision in revisions:
                current = self._assemble(direction_id, revision)
                if current.previous_chain_hash != previous:
                    raise ChainBrokenError(
                        f"r{revision}: previous_chain_hash does not match r{revision - 1}")
                expected = current.recompute_chain_hash()
                if expected != current.chain_hash:
                    raise ChainBrokenError(f"r{revision}: chain hash mismatch")
                previous = current.chain_hash
            return tuple(self._assemble(direction_id, r).chain_hash for r in revisions)
