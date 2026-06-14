import uuid

import pytest


@pytest.mark.asyncio
async def test_template_crud(client):
    # 1. Create
    payload = {
        "name": "E-commerce Pro",
        "category": "e-commerce",
        "canvas_json": {"nodes": [], "edges": []},
        "is_official": True,
        "metadata": {"version": "1.0"}
    }
    resp = await client.post("/api/templates/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    template_id = data["id"]
    assert data["name"] == "E-commerce Pro"
    assert data["category"] == "e-commerce"

    # 2. Get
    resp = await client.get(f"/api/templates/{template_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "E-commerce Pro"

    # 3. List
    resp = await client.get("/api/templates/?official_only=true")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # 4. List with category
    resp = await client.get("/api/templates/?category=e-commerce")
    assert resp.status_code == 200
    assert any(t["id"] == template_id for t in resp.json())

    # 5. Apply
    resp = await client.post(f"/api/templates/{template_id}/apply")
    assert resp.status_code == 200
    assert resp.json() == {"nodes": [], "edges": []}

    # 6. Delete
    resp = await client.delete(f"/api/templates/{template_id}")
    assert resp.status_code == 200
    
    # Verify deleted
    resp = await client.get(f"/api/templates/{template_id}")
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_template_multi_tenancy(client):
    # Create private template
    user_id = "user_123"
    payload = {
        "name": "My Private Template",
        "category": "personal",
        "canvas_json": {},
        "user_id": user_id,
        "is_official": False
    }
    resp = await client.post("/api/templates/", json=payload)
    template_id = resp.json()["id"]

    # List as same user
    resp = await client.get(f"/api/templates/?user_id={user_id}")
    assert any(t["id"] == template_id for t in resp.json())

    # List as another user (should NOT see private template)
    resp = await client.get("/api/templates/?user_id=other_user")
    assert not any(t["id"] == template_id for t in resp.json())

@pytest.mark.asyncio
async def test_audio_library_crud(client):
    # 1. Create
    payload = {
        "name": "Happy Summer",
        "asset_type": "bgm",
        "file_path": "bgm/happy/summer.mp3",
        "mood": "happy",
        "duration_s": 120.5,
        "tags": ["summer", "energetic"],
        "is_official": True
    }
    resp = await client.post("/api/audio/", json=payload)
    assert resp.status_code == 201
    asset_id = resp.json()["id"]

    # 2. Get
    resp = await client.get(f"/api/audio/{asset_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Happy Summer"

    # 3. Search type
    resp = await client.get("/api/audio/?asset_type=bgm")
    assert any(a["id"] == asset_id for a in resp.json())

    # 4. Search mood
    resp = await client.get("/api/audio/?mood=happy")
    assert any(a["id"] == asset_id for a in resp.json())

    # 5. Search tags
    resp = await client.get("/api/audio/?tags=summer")
    assert any(a["id"] == asset_id for a in resp.json())

    # 6. Search query
    resp = await client.get("/api/audio/?query=Happy")
    assert any(a["id"] == asset_id for a in resp.json())

    # 7. Delete
    resp = await client.delete(f"/api/audio/{asset_id}")
    assert resp.status_code == 200

@pytest.mark.asyncio
async def test_audio_service_physical_path():
    from unittest.mock import MagicMock

    from hevi.audio_library.audio_lib_service import AudioLibraryService
    
    mock_repo = MagicMock()
    service = AudioLibraryService(mock_repo)
    path = service.get_physical_path("bgm/test.mp3")
    assert "assets/audio/bgm/test.mp3" in path

@pytest.mark.asyncio
async def test_template_apply_errors(client):
    fake_id = str(uuid.uuid4())
    resp = await client.post(f"/api/templates/{fake_id}/apply")
    assert resp.status_code == 404
    assert "Template not found" in resp.json()["detail"]

@pytest.mark.asyncio
async def test_template_list_filters(client):
    # Setup: 1 official e-commerce, 1 user personal
    user_id = "filter_user"
    await client.post("/api/templates/", json={
        "name": "Off-Ecom", "category": "e-commerce", "canvas_json": {}, "is_official": True
    })
    await client.post("/api/templates/", json={
        "name": "User-Pers",
        "category": "personal",
        "canvas_json": {},
        "user_id": user_id,
        "is_official": False
    })

    # Test category filter
    resp = await client.get("/api/templates/?category=e-commerce")
    assert all(t["category"] == "e-commerce" for t in resp.json())

    # Test official_only
    resp = await client.get(f"/api/templates/?official_only=true&user_id={user_id}")
    assert all(t["is_official"] for t in resp.json())
    assert not any(t["name"] == "User-Pers" for t in resp.json())

@pytest.mark.asyncio
async def test_audio_search_multi_tenancy(client):
    user_id = "audio_user"
    # Official asset
    await client.post("/api/audio/", json={
        "name": "Off-Audio",
        "asset_type": "sfx",
        "file_path": "f1",
        "is_official": True
    })
    # User asset
    await client.post("/api/audio/", json={
        "name": "User-Audio",
        "asset_type": "sfx",
        "file_path": "f2",
        "user_id": user_id,
        "is_official": False
    })

    # Search as user
    resp = await client.get(f"/api/audio/?user_id={user_id}")
    names = [a["name"] for a in resp.json()]
    assert "Off-Audio" in names
    assert "User-Audio" in names

    # Search as other
    resp = await client.get("/api/audio/?user_id=other")
    names = [a["name"] for a in resp.json()]
    assert "Off-Audio" in names
    assert "User-Audio" not in names

@pytest.mark.asyncio
async def test_audio_errors(client):
    fake_id = str(uuid.uuid4())
    # Get 404
    resp = await client.get(f"/api/audio/{fake_id}")
    assert resp.status_code == 404
    # Delete non-existent (soft_delete_one returns False if not found or already deleted)
    resp = await client.delete(f"/api/audio/{fake_id}")
    assert resp.status_code == 404
