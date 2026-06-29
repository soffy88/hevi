"""C 红线: 全本地生成不拦余额 / 含云步检查余额"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hevi.credits.billing_service import BillingService, InsufficientCredits
from hevi.tasks.task_service import TaskService


def _make_task_service(credits_needed: int) -> tuple[TaskService, MagicMock]:
    repo = MagicMock()
    repo.create_task = AsyncMock(return_value={
        "id": uuid.uuid4(), "topic": "test", "status": "pending",
        "duration_archetype": "short", "video_provider": "ltx2_local",
        "audio_provider": "vibevoice", "config_json": {}, "progress_pct": 0.0,
        "total_shots": 0, "completed_shots": 0, "user_id": "uid",
    })

    billing = MagicMock(spec=BillingService)
    billing.estimate_credits = AsyncMock(return_value=credits_needed)
    billing.check_and_reserve = AsyncMock(return_value=True)

    svc = TaskService(repo, billing_svc=billing)
    return svc, billing


@pytest.mark.asyncio
async def test_local_task_skips_balance_check() -> None:
    """C: 全本地(credits_needed==0)不调 check_and_reserve"""
    svc, billing = _make_task_service(credits_needed=0)

    with patch("hevi.tasks.task_service.estimate_cost", new_callable=AsyncMock) as mock_est, \
         patch("hevi.tasks.task_service.check_before_run", new_callable=AsyncMock):
        mock_est.return_value = MagicMock(total_usd=0.0)
        await svc.create_task(
            topic="test",
            duration_archetype="short",
            video_provider="ltx2_local",
            audio_provider="vibevoice",
            user_id="user-001",
        )

    billing.check_and_reserve.assert_not_called()


@pytest.mark.asyncio
async def test_cloud_task_checks_balance_when_sufficient() -> None:
    """C: 含云步(credits>0)有余额时放行"""
    svc, billing = _make_task_service(credits_needed=10)

    with patch("hevi.tasks.task_service.estimate_cost", new_callable=AsyncMock) as mock_est, \
         patch("hevi.tasks.task_service.check_before_run", new_callable=AsyncMock):
        mock_est.return_value = MagicMock(total_usd=0.1)
        await svc.create_task(
            topic="test",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
            user_id="user-001",
        )

    billing.check_and_reserve.assert_called_once_with("user-001", 10)


@pytest.mark.asyncio
async def test_cloud_task_raises_402_when_insufficient() -> None:
    """C: 含云步余额不足 → InsufficientCredits"""
    svc, billing = _make_task_service(credits_needed=500)
    billing.check_and_reserve = AsyncMock(
        side_effect=InsufficientCredits(credits_needed=500, credits_available=0)
    )

    with patch("hevi.tasks.task_service.estimate_cost", new_callable=AsyncMock) as mock_est, \
         patch("hevi.tasks.task_service.check_before_run", new_callable=AsyncMock):
        mock_est.return_value = MagicMock(total_usd=5.0)
        with pytest.raises(InsufficientCredits):
            await svc.create_task(
                topic="test",
                duration_archetype="long",
                video_provider="ltx2_cloud",
                audio_provider="vibevoice",
                user_id="user-broke",
            )
