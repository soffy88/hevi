import hmac
import re
from typing import Any

import httpx

from hevi.core.config import settings


class PaddleConfigurationError(ValueError):
    """Paddle is not configured well enough to create a real checkout."""


class PaddleAPIError(RuntimeError):
    """Paddle rejected the request or returned an unusable transaction."""


class PaddleService:
    def __init__(self, api_key: str | None = None, webhook_secret: str | None = None):
        self._api_key = api_key or settings.paddle_api_key
        self._webhook_secret = webhook_secret or settings.paddle_webhook_secret

    async def create_checkout_session(
        self, price_id: str, user_id: str, email: str
    ) -> dict[str, Any]:
        """Create a real Paddle transaction and return its checkout link."""
        if not self._api_key:
            raise PaddleConfigurationError("Paddle API key is not configured")
        if not re.fullmatch(r"pri_[a-z\d]{26}", price_id):
            raise PaddleConfigurationError("Paddle price ID is not configured")

        environment = self._environment()
        api_base = (
            "https://api.paddle.com" if environment == "live" else "https://sandbox-api.paddle.com"
        )
        payload = {
            "items": [{"price_id": price_id, "quantity": 1}],
            "custom_data": {"user_id": user_id, "email": email},
        }
        try:
            async with httpx.AsyncClient(base_url=api_base, timeout=30.0) as client:
                response = await client.post(
                    "/transactions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            raise PaddleAPIError(
                f"Paddle transaction request failed with HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            raise PaddleAPIError("Paddle transaction request failed") from exc

        data = body.get("data") if isinstance(body, dict) else None
        checkout = data.get("checkout") if isinstance(data, dict) else None
        transaction_id = data.get("id") if isinstance(data, dict) else None
        checkout_url = checkout.get("url") if isinstance(checkout, dict) else None
        if not isinstance(transaction_id, str) or not isinstance(checkout_url, str):
            raise PaddleAPIError("Paddle returned no usable transaction checkout")
        return {"id": transaction_id, "url": checkout_url}

    @staticmethod
    def _environment() -> str:
        environment = settings.paddle_environment.strip().lower()
        if environment not in {"sandbox", "live"}:
            raise PaddleConfigurationError("PADDLE_ENVIRONMENT must be sandbox or live")
        return environment

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        """Verify the signature from Paddle.

        Paddle usually provides a signature in the `Paddle-Signature` header.
        Format: hmac_sha256=... (or similar, depending on Paddle API version)
        """
        if not self._webhook_secret:
            # SECURITY: fail-closed. With no secret configured we cannot trust any
            # incoming webhook, so reject rather than accept (accepting = free credits
            # to anyone who can POST to /api/payment/webhook).
            return False

        # Simplified Paddle verification logic (actual header parsing depends on version)
        # Assuming signature is the hex digest for simplicity in this skeleton
        from obase.webhook import sign_payload

        try:
            expected = sign_payload(payload=raw_body, secret=self._webhook_secret)
            return hmac.compare_digest(expected, signature)
        except Exception:
            return False
