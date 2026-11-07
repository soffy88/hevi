"""Verify HMAC-SHA256 signing matches OKX docs reference format."""

import base64
import re
from datetime import UTC

from oskill.exchange.okx_demo._signing import make_timestamp, sign_request


def test_known_signature_produces_sha256_bytes():
    sig = sign_request(
        api_secret="C8K70SL5ETWA60V1IXBSTOK0M0J8C4UE",
        timestamp="2020-12-08T09:08:57.715Z",
        method="GET",
        request_path="/users/self/verify",
    )
    decoded = base64.b64decode(sig)
    assert len(decoded) == 32, "SHA256 digest must be 32 bytes"


def test_different_bodies_give_different_signatures():
    common = dict(
        api_secret="test-secret",
        timestamp="2024-01-01T00:00:00.000Z",
        method="POST",
        request_path="/api/v5/trade/order",
    )
    sig1 = sign_request(**common, body='{"sz":"0.001"}')
    sig2 = sign_request(**common, body='{"sz":"0.002"}')
    assert sig1 != sig2


def test_get_vs_post_gives_different_signatures():
    common = dict(
        api_secret="test-secret",
        timestamp="2024-01-01T00:00:00.000Z",
        request_path="/api/v5/trade/order",
    )
    sig_get = sign_request(**common, method="GET")
    sig_post = sign_request(**common, method="POST")
    assert sig_get != sig_post


def test_timestamp_format():
    ts = make_timestamp()
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", ts), (
        f"Timestamp {ts!r} does not match OKX format"
    )


def test_timestamp_is_utc():
    from datetime import datetime

    ts = make_timestamp()
    assert ts.endswith("Z")
    parsed = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    now = datetime.now(UTC)
    delta = abs((now - parsed).total_seconds())
    assert delta < 5, f"Timestamp is more than 5s from now: {delta}s"
