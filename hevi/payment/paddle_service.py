import hmac
from typing import Any

from hevi.core.config import settings


class PaddleService:
    def __init__(self, api_key: str | None = None, webhook_secret: str | None = None):
        self._api_key = api_key or settings.paddle_api_key
        self._webhook_secret = webhook_secret or settings.paddle_webhook_secret

    async def create_checkout_session(
        self, price_id: str, user_id: str, email: str
    ) -> dict[str, Any]:
        """Call Paddle API to create a checkout session."""
        if not self._api_key:
            # Mock URL if no API key
            return {
                "id": "ct_dummy_123",
                "url": f"https://checkout.paddle.com/dummy?user_id={user_id}&price_id={price_id}"
            }
        
        # Real implementation would use httpx to POST to Paddle API
        # PENDING: implementation once Paddle SDK or direct API spec is confirmed
        return {
            "id": "ct_mock_123",
            "url": "https://sandbox-checkout.paddle.com/..."
        }

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        """Verify the signature from Paddle.
        
        Paddle usually provides a signature in the `Paddle-Signature` header.
        Format: hmac_sha256=... (or similar, depending on Paddle API version)
        """
        if not self._webhook_secret:
            # TODO: WARNING - In production this must be enabled
            # For dev without secret, we skip verification
            return True

        # Simplified Paddle verification logic (actual header parsing depends on version)
        # Assuming signature is the hex digest for simplicity in this skeleton
        from obase.webhook import sign_payload
        
        try:
            expected = sign_payload(payload=raw_body, secret=self._webhook_secret)
            return hmac.compare_digest(expected, signature)
        except Exception:
            return False
