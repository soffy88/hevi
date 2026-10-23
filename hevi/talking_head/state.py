"""Job ledger for the talking-head pipeline (``job-state.json``).

The ledger is the delivery evidence: every stage records its status,
wall-clock seconds, attempt / retry counts and whether it degraded, and
every gate records its measured numbers next to its thresholds (see
:mod:`hevi.talking_head.gates`).  Nothing in here ever claims a pass that
was not measured — the final status is *derived* from the recorded stage
and gate outcomes by :func:`finalize_status`.

Cost invariant: this pipeline is local-only (LuxTTS HTTP service on the
LAN, faster-whisper on CPU, Wav2Lip / MuseTalk locally, earshot
model-free).  ``cost_usd`` is therefore always ``0`` and the basis is
recorded explicitly as ``external_paid_calls == []``.  If a future stage
ever calls a paid API it must append to that list and update the total —
silently spending while reporting 0 would break the ledger contract.

Pure stdlib: this module is safe to import from tests and tooling.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "STAGE_NAMES",
    "Ledger",
    "finalize_status",
    "new_ledger",
    "validate_ledger",
]

#: Stages in execution order.  ``deliver`` is the ledger-write itself.
STAGE_NAMES: tuple[str, ...] = ("preflight", "tts", "lipsync", "gates", "deliver")

#: Statuses a stage may hold.
STAGE_STATUSES: tuple[str, ...] = ("pending", "running", "ok", "failed", "skipped")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _empty_stage() -> dict[str, Any]:
    return {
        "status": "pending",
        "elapsed_s": None,
        "attempts": 0,
        "retries": 0,
        "degraded": False,
        "detail": {},
        "error": None,
    }


def new_ledger(
    *,
    script_text: str,
    portrait: str,
    engine: str,
    voice: str,
    voice_sample: str | None = None,
) -> dict[str, Any]:
    """Create a fresh ledger dict (pure; no I/O)."""
    return {
        "schema_version": 1,
        "kind": "talking_head_job",
        "job_id": uuid.uuid4().hex,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        # One of: running / delivered / delivered_with_warnings / failed.
        "status": "running",
        "failed_stage": None,
        "inputs": {
            "script_chars": len(script_text),
            "script_text": script_text,
            "portrait": str(portrait),
            "engine": engine,
            "voice": voice,
            "voice_sample": str(voice_sample) if voice_sample else None,
        },
        "stages": {name: _empty_stage() for name in STAGE_NAMES},
        # Gate verdicts land here: {name: {"pass": bool, ...measured...}}.
        "gates": {},
        "artifacts": {},
        "warnings": [],
        # Local-only pipeline: no paid call is ever made by these stages.
        "cost_usd": 0,
        "cost_basis": {
            "external_paid_calls": [],
            "note": (
                "local-only: LuxTTS LAN service, faster-whisper CPU, "
                "wav2lip/musetalk local, earshot model-free; no paid API"
            ),
        },
    }


def finalize_status(ledger: dict[str, Any]) -> str:
    """Derive the final status from recorded stages + gates (pure).

    * any stage ``failed`` -> ``"failed"``
    * else any recorded gate with ``pass is False`` (or a gate block that
      carries an ``error``) -> ``"delivered_with_warnings"``
    * else -> ``"delivered"``
    """
    stages = ledger.get("stages") or {}
    for name, stage in stages.items():
        if isinstance(stage, dict) and stage.get("status") == "failed":
            ledger["failed_stage"] = name
            return "failed"
    gates = ledger.get("gates") or {}
    for gate in gates.values():
        if not isinstance(gate, dict):
            return "delivered_with_warnings"
        if gate.get("pass") is not True:
            return "delivered_with_warnings"
    return "delivered"


def validate_ledger(ledger: Any) -> list[str]:
    """Return structural problems with ``ledger`` (empty list = valid)."""
    errors: list[str] = []
    if not isinstance(ledger, dict):
        return ["ledger is not a dict"]
    required = ("schema_version", "job_id", "status", "inputs", "stages", "gates", "cost_usd")
    errors.extend(f"missing key: {key}" for key in required if key not in ledger)
    if ledger.get("cost_usd") != 0:
        errors.append(f"cost_usd must be 0 for the local pipeline, got {ledger.get('cost_usd')!r}")
    basis = ledger.get("cost_basis")
    if not isinstance(basis, dict) or basis.get("external_paid_calls") != []:
        errors.append("cost_basis.external_paid_calls must be [] while cost_usd is 0")
    stages = ledger.get("stages")
    if not isinstance(stages, dict):
        errors.append("stages is not a dict")
    else:
        for name in STAGE_NAMES:
            stage = stages.get(name)
            if not isinstance(stage, dict):
                errors.append(f"stage missing or not a dict: {name}")
                continue
            stage_fields = ("status", "elapsed_s", "attempts", "retries", "degraded")
            errors.extend(
                f"stage {name} missing field: {field}"
                for field in stage_fields
                if field not in stage
            )
            if stage.get("status") not in (*STAGE_STATUSES, "ok"):
                errors.append(f"stage {name} has unknown status {stage.get('status')!r}")
    gates = ledger.get("gates")
    if gates is not None and not isinstance(gates, dict):
        errors.append("gates is not a dict")
    return errors


class Ledger:
    """Mutable wrapper around the ledger dict, with timing + persistence."""

    def __init__(self, data: dict[str, Any], path: Path) -> None:
        self.data = data
        self.path = Path(path)
        self._started: dict[str, float] = {}

    # -- stage lifecycle -------------------------------------------------
    def start_stage(self, name: str) -> None:
        stage = self.data["stages"][name]
        stage["status"] = "running"
        stage["attempts"] = int(stage.get("attempts") or 0) + 1
        self._started[name] = time.monotonic()
        self._touch()

    def finish_stage(self, name: str, *, detail: dict[str, Any] | None = None) -> None:
        stage = self.data["stages"][name]
        stage["status"] = "ok"
        stage["elapsed_s"] = self._elapsed(name)
        if detail:
            stage["detail"].update(detail)
        self._touch()

    def fail_stage(self, name: str, error: str, *, detail: dict[str, Any] | None = None) -> None:
        stage = self.data["stages"][name]
        stage["status"] = "failed"
        stage["elapsed_s"] = self._elapsed(name)
        stage["error"] = error
        if detail:
            stage["detail"].update(detail)
        self._touch()

    def record_retry(self, name: str) -> None:
        stage = self.data["stages"][name]
        stage["retries"] = int(stage.get("retries") or 0) + 1
        self._touch()

    def mark_degraded(self, name: str, reason: str) -> None:
        stage = self.data["stages"][name]
        stage["degraded"] = True
        stage["detail"].setdefault("degradations", []).append(reason)
        self.add_warning(f"{name}: {reason}")
        self._touch()

    # -- other records ----------------------------------------------------
    def add_warning(self, message: str) -> None:
        self.data.setdefault("warnings", []).append(message)
        self._touch()

    def set_gates(self, gates: dict[str, Any]) -> None:
        self.data["gates"] = gates
        self._touch()

    def set_artifact(self, key: str, value: str) -> None:
        self.data.setdefault("artifacts", {})[key] = value
        self._touch()

    def finalize(self) -> str:
        self.data["status"] = finalize_status(self.data)
        self._touch()
        return str(self.data["status"])

    # -- persistence --------------------------------------------------------
    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._touch()
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return self.path

    @staticmethod
    def load(path: Path) -> Ledger:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return Ledger(data, Path(path))

    # -- internals ----------------------------------------------------------
    def _elapsed(self, name: str) -> float | None:
        started = self._started.pop(name, None)
        if started is None:
            return self.data["stages"][name].get("elapsed_s")
        return round(time.monotonic() - started, 3)

    def _touch(self) -> None:
        self.data["updated_at"] = _now_iso()
