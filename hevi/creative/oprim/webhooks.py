"""Signed, idempotent creative lifecycle webhook delivery ledger."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from time import time


@dataclass
class WebhookLedger:
    delivered: set[str] = field(default_factory=set)
    attempts: dict[str, int] = field(default_factory=dict)


class WebhookSigner:
    def __init__(self, secret: bytes) -> None:
        if not secret:
            raise ValueError("webhook secret is required")
        self.secret = secret

    def sign(self, event_id: str, payload: dict[str, object]) -> str:
        body = json.dumps({"event_id": event_id, "payload": payload}, sort_keys=True).encode()
        timestamp = str(int(time()))
        return f"t={timestamp},v1={self._digest(timestamp, body)}"

    def verify(
        self, signature: str, event_id: str, payload: dict[str, object], *, max_age: int = 300
    ) -> bool:
        try:
            raw_time, raw_digest = signature.split(",", 1)
            timestamp = int(raw_time.removeprefix("t="))
            digest = raw_digest.removeprefix("v1=")
        except ValueError, TypeError:
            return False
        if abs(int(time()) - timestamp) > max_age:
            return False
        body = json.dumps({"event_id": event_id, "payload": payload}, sort_keys=True).encode()
        expected = self._digest(str(timestamp), body)
        return hmac.compare_digest(digest, expected)

    def _digest(self, timestamp: str, body: bytes) -> str:
        return hmac.new(
            self.secret,
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()


def claim_delivery(ledger: WebhookLedger, event_id: str) -> bool:
    if event_id in ledger.delivered:
        return False
    ledger.attempts[event_id] = ledger.attempts.get(event_id, 0) + 1
    ledger.delivered.add(event_id)
    return True


__all__ = ["WebhookLedger", "WebhookSigner", "claim_delivery"]
