"""Gold behaviour for signed webhook delivery with bounded retry."""

from __future__ import annotations

import http.server
import json
import socket
import threading

from hevi.creative.oprim import WebhookLedger, WebhookSigner, deliver


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _receiver(signer: WebhookSigner, fail_first: int = 0):
    seen = {"count": 0}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            envelope = json.loads(body)
            seen["count"] += 1
            valid = signer.verify(
                self.headers.get("X-Hevi-Signature", ""),
                str(envelope["event_id"]),
                envelope["payload"],
            )
            if seen["count"] <= fail_first:
                self.send_response(503)
            else:
                self.send_response(204 if valid else 400)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    return server, seen


def test_deliver_retries_until_receiver_accepts() -> None:
    signer = WebhookSigner(b"gold-secret")
    ledger = WebhookLedger()
    server, seen = _receiver(signer, fail_first=2)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_address[1]}/hook"
    try:
        ok = deliver(
            event_id="retry-1",
            payload={"status": "production_complete"},
            endpoint=endpoint,
            signer=signer,
            ledger=ledger,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert ok
    assert seen["count"] == 3
    assert ledger.attempts["retry-1"] == 3
    assert "retry-1" in ledger.delivered


def test_dead_endpoint_is_dead_lettered() -> None:
    signer = WebhookSigner(b"gold-secret")
    ledger = WebhookLedger()
    ok = deliver(
        event_id="dead-1",
        payload={"status": "failed"},
        endpoint=f"http://127.0.0.1:{_free_port()}/hook",
        signer=signer,
        ledger=ledger,
        max_attempts=2,
    )
    assert not ok
    assert ledger.attempts["dead-1"] == 2
    assert ledger.dead_letters["dead-1"].startswith("exhausted")


def test_delivery_is_idempotent() -> None:
    signer = WebhookSigner(b"gold-secret")
    ledger = WebhookLedger()
    ledger.delivered.add("done-1")
    assert deliver(
        event_id="done-1",
        payload={},
        endpoint="http://127.0.0.1:1/hook",
        signer=signer,
        ledger=ledger,
    )
    assert "done-1" not in ledger.attempts
