"""OKX API request signing (HMAC-SHA256).

Reference: https://www.okx.com/docs-v5/en/#overview-api-authentication
"""

import base64
import hashlib
import hmac
from datetime import UTC, datetime


def sign_request(
    api_secret: str,
    timestamp: str,
    method: str,
    request_path: str,
    body: str = "",
) -> str:
    """Generate OKX signature.

    timestamp format: ISO8601 with milliseconds, e.g. "2024-01-01T12:00:00.000Z"
    method: GET / POST / etc.
    request_path: full path including query string, e.g. "/api/v5/trade/order"
    body: JSON string for POST, "" for GET
    """
    message = f"{timestamp}{method.upper()}{request_path}{body}"
    mac = hmac.new(
        api_secret.encode("utf-8"),
        message.encode("utf-8"),
        digestmod=hashlib.sha256,
    )
    return base64.b64encode(mac.digest()).decode("utf-8")


def make_timestamp() -> str:
    """OKX-style ISO8601 timestamp."""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"
