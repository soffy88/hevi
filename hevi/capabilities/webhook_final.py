"""Webhook final-state delivery (``edit.webhook_final``).

Clean-room method intake: when a job finishes, exactly one
terminal event is pushed, and only that event. The event name
is fixed at ``job.completed`` and the job status must be
``completed``; a non-terminal job, a different event name, a
missing job id or a missing payload all raise, they do not
produce a signed event for something that did not finish.

Signing: HMAC-SHA256 over a canonical JSON encoding of the
event (keys sorted, compact separators, UTF-8). The secret is
supplied by the caller for this call only, is used only to
compute the signature, and is never written into the output
report. Verification recomputes the signature with
``hmac.compare_digest``; a tampered payload or a wrong secret
fails verification.

Delivery policy, stated in the output rather than executed
against a real endpoint by this capability:
* max_attempts = 4, backoff_sec = [0, 30, 120, 600]
  (first attempt immediate, then 30s, 2min, 10min).
* Retry only on 429, 500, 502, 503, 504. A 4xx other than 429
  is a permanent failure and must not be retried.
* Deduplication key is ``job_id + ':' + event``. A second
  delivery of the same key is suppressed: ``check_duplicate``
  returns True and no second event is minted for that key.
* No public port is opened and no external key is stored:
  this module mints and verifies signed events locally; the
  caller owns transport.

Failure contract: anything that is not a completed job with
a usable payload raises CapabilityError. A signature is
never produced for a non-terminal job.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False
BACKOFF_SEC = [0, 30, 120, 600]
RETRYABLE_STATUS = (429, 500, 502, 503, 504)


def _canonical(data: dict[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"edit.webhook_final: {what} must be a non-empty string")
    return value.strip()


def make_final_event(job: dict[str, Any], secret: str) -> dict[str, Any]:
    if not isinstance(job, dict):
        raise CapabilityError("edit.webhook_final: job must be a JSON object")
    job_id = _require_str(job.get("job_id"), "job.job_id")
    if job.get("status") != "completed":
        raise CapabilityError("edit.webhook_final: only a job with status 'completed' may emit job.completed")
    payload = job.get("payload")
    if not isinstance(payload, dict):
        raise CapabilityError("edit.webhook_final: job.payload must be a JSON object")
    secret = _require_str(secret, "secret")
    event = {
        "event": "job.completed",
        "job_id": job_id,
        "status": "completed",
        "payload": payload,
    }
    signature = hmac.new(secret.encode("utf-8"), _canonical(event), hashlib.sha256).hexdigest()
    return {
        **event,
        "signature": signature,
        "dedup_key": f"{job_id}:job.completed",
        "delivery_policy": {
            "max_attempts": len(BACKOFF_SEC),
            "backoff_sec": list(BACKOFF_SEC),
            "retryable_status": list(RETRYABLE_STATUS),
            "deliver_once": True,
        },
        "transport": "not_sent_by_this_capability",
        "note": "Signed event minted locally; the caller owns transport and must respect deliver_once.",
    }


def verify_final_event(event: dict[str, Any], secret: str) -> bool:
    if not isinstance(event, dict):
        return False
    signature = event.get("signature")
    if not isinstance(signature, str):
        return False
    if event.get("event") != "job.completed" or event.get("status") != "completed":
        return False
    if not isinstance(event.get("job_id"), str) or not event["job_id"]:
        return False
    if not isinstance(event.get("payload"), dict):
        return False
    if not isinstance(secret, str) or not secret:
        return False
    unsigned = {
        "event": event["event"],
        "job_id": event["job_id"],
        "status": event["status"],
        "payload": event["payload"],
    }
    expected = hmac.new(secret.encode("utf-8"), _canonical(unsigned), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def check_duplicate(delivered_keys: Any, event: dict[str, Any]) -> bool:
    if not isinstance(delivered_keys, (list, tuple, set)):
        raise CapabilityError("edit.webhook_final: delivered_keys must be a list, tuple or set")
    if not isinstance(event, dict) or not isinstance(event.get("dedup_key"), str):
        raise CapabilityError("edit.webhook_final: event must carry a dedup_key")
    return event["dedup_key"] in delivered_keys


def _render_webhook(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    job = params.get("job")
    secret = params.get("secret")
    if not isinstance(secret, str):
        raise CapabilityError("edit.webhook_final: secret must be a string")
    result = make_final_event(job, secret)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "webhook_final.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={
            "report_json": str(report),
            "event": result["event"],
            "job_id": result["job_id"],
            "dedup_key": result["dedup_key"],
        },
    )


def register_webhook_final_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="edit.webhook_final",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {
                "job": {"type": "object"},
                "secret": {"type": "string"},
            },
            "required": ["job", "secret"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render_webhook,
        has_media_output=False,
        description=(
            "Webhook final-state delivery (clean-room): exactly one "
            "job.completed event for a completed job, HMAC-SHA256 signed "
            "over canonical JSON, with a stated retry and dedup policy. "
            "Mints and verifies locally; opens no port, stores no key, "
            "and sends nothing itself."
        ),
        line="edit",
    ))
    return ["edit.webhook_final"]


register_webhook_final_capabilities_once()
