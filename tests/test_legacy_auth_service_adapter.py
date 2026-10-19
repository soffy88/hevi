"""Regression tests for the legacy service adapter's canonical JWT integration."""

import pytest

from hevi.services.auth_service import AuthServiceMicroservice


@pytest.mark.asyncio
async def test_legacy_auth_service_signs_and_verifies_canonical_access_token() -> None:
    service = AuthServiceMicroservice()
    token = await service.create_token({"sub": "hevi-regression-user"})
    payload = await service.verify_token(token)

    assert payload is not None
    assert payload["sub"] == "hevi-regression-user"


@pytest.mark.asyncio
async def test_legacy_auth_service_rejects_missing_user_identifier() -> None:
    service = AuthServiceMicroservice()

    with pytest.raises(ValueError, match="must include sub, user_id, or id"):
        await service.create_token({"email": "test@example.invalid"})
