"""E3 execution presets (economy/balanced/fast)."""
import uuid

import pytest

from hevi.video import EXECUTION_PRESETS, get_execution_preset, resolve_preset


def test_three_presets_exist():
    assert set(EXECUTION_PRESETS) == {"economy", "balanced", "fast"}


def test_economy_is_local_zero_cost():
    p = get_execution_preset("economy")
    assert p.video_provider == "wan_local"  # local → $0 cloud cost


def test_fast_is_cloud_high_quality():
    p = get_execution_preset("fast")
    assert p.video_provider == "ltx2_cloud"
    assert p.quality_profile == "high"


def test_unknown_preset_raises():
    with pytest.raises(ValueError, match="Unknown execution preset"):
        get_execution_preset("turbo")


def test_resolve_preset_explicit_overrides():
    out = resolve_preset("economy", video_provider="ltx2_cloud")
    assert out["video_provider"] == "ltx2_cloud"  # explicit wins
    assert out["audio_provider"] == "vibevoice"   # from preset


def test_resolve_preset_none_returns_only_explicit():
    assert resolve_preset(None) == {}
    assert resolve_preset(None, video_provider="wan_local") == {"video_provider": "wan_local"}


@pytest.mark.asyncio
async def test_api_create_task_with_preset(client):
    """POST /api/tasks with preset=economy → task uses wan_local (local → queued)."""
    email = f"preset_{uuid.uuid4().hex[:6]}@example.com"
    await client.post("/api/auth/register", json={
        "email": email, "password": "password123", "display_name": "P"
    })
    login = await client.post("/api/auth/login", json={
        "email": email, "password": "password123"
    })
    token = login.json()["access_token"]

    resp = await client.post(
        "/api/tasks",
        json={"topic": "Demo", "duration_archetype": "short", "preset": "economy"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["video_provider"] == "wan_local"
    # local provider → enqueued, not background-run
    assert body["status"] == "queued"
