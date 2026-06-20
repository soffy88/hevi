from __future__ import annotations

from typing import Any

from hevi.core.config import settings
from hevi.cost.estimator import estimate_cost
from hevi.credits.account_service import AccountService


class InsufficientCredits(Exception):
    """Raised when user balance is below requested amount."""

    def __init__(self, credits_needed: int, credits_available: int) -> None:
        self.credits_needed = credits_needed
        self.credits_available = credits_available
        super().__init__(
            f"Insufficient credits: needed {credits_needed}, have {credits_available}"
        )


class BillingService:
    def __init__(self, account_svc: AccountService) -> None:
        self._account_svc = account_svc

    async def estimate_credits(
        self,
        duration_archetype: str,
        video_provider: str = "ltx2_cloud",
        ltx2_tier: str = "fast",
        quality_profile: str = "standard",
        num_characters: int = 1,
        **kwargs: Any,
    ) -> int:
        """Estimate credit cost for a video task."""
        # Call E3 estimator
        estimate = await estimate_cost(
            duration_archetype=duration_archetype,
            video_provider=video_provider,
            audio_provider=kwargs.get("audio_provider", "vibevoice"),
            ltx2_tier=ltx2_tier,  # type: ignore
            quality=quality_profile,
            num_characters=num_characters,
        )
        # Convert USD to credits (default $1 = 100 credits)
        return int(estimate.total_usd * settings.credits_per_usd)

    async def check_and_reserve(self, user_id: str, credits_needed: int) -> bool:
        """Check if user has enough credits.
        
        In this implementation, we don't have a 'reserved' state in DB yet,
        so we just check the balance. The actual deduction happens at 'consume'.
        """
        balance = await self._account_svc.get_balance(user_id)
        if balance < credits_needed:
            raise InsufficientCredits(
                credits_needed=credits_needed, credits_available=balance
            )
        return True

    async def consume(
        self, user_id: str, credits: int, task_id: str
    ) -> dict[str, Any]:
        """Finalize credit deduction."""
        return await self._account_svc.consume(user_id, credits, task_ref=task_id)

    async def refund(
        self, user_id: str, credits: int, task_id: str
    ) -> dict[str, Any]:
        """Refund credits for failed task."""
        return await self._account_svc.refund(user_id, credits, task_ref=task_id)
