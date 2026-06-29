import uuid
from typing import Any

import pytest


async def _auth(client: Any) -> dict[str, str]:
    """Register + login a fresh user, return Authorization headers."""
    email = f"lib_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/auth/register", json={
        "email": email, "password": "password123", "display_name": "Lib"
    })
    login = await client.post("/api/auth/login", json={
        "email": email, "password": "password123"
    })
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_template_crud(client):
    h = await _auth(client)
    # 1. Create (is_official from client is ignored — server forces False/owner)
    payload = {
        "name": "E-commerce Pro",
        "category": "e-commerce",
        "canvas_json": {"nodes": [], "edges": []},
        "is_official": True,  # should be ignored
        "metadata": {"version": "1.0"},
    }
    resp = await client.post("/api/templates/", json=payload, headers=h)
    assert resp.status_code == 201
    data = resp.json()
    template_id = data["id"]
    assert data["name"] == "E-commerce Pro"
    assert data["is_official"] is False  # client cannot mint official

    # 2. Get (owner)
    resp = await client.get(f"/api/templates/{template_id}", headers=h)
    assert resp.status_code == 200
    assert resp.json()["name"] == "E-commerce Pro"

    # 3. List (owner sees own)
    resp = await client.get("/api/templates/", headers=h)
    assert resp.status_code == 200
    assert any(t["id"] == template_id for t in resp.json())

    # 4. List with category
    resp = await client.get("/api/templates/?category=e-commerce", headers=h)
    assert any(t["id"] == template_id for t in resp.json())

    # 5. Apply
    resp = await client.post(f"/api/templates/{template_id}/apply", headers=h)
    assert resp.status_code == 200
    assert resp.json() == {"nodes": [], "edges": []}

    # 6. Delete
    resp = await client.delete(f"/api/templates/{template_id}", headers=h)
    assert resp.status_code == 200
    resp = await client.get(f"/api/templates/{template_id}", headers=h)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_templates_require_auth(client):
    assert (await client.get("/api/templates/")).status_code in (401, 403)


@pytest.mark.asyncio
async def test_template_multi_tenancy(client):
    """A 的私有模板,B 看不到、读不到、删不掉。"""
    a = await _auth(client)
    b = await _auth(client)
    payload = {"name": "My Private Template", "category": "personal", "canvas_json": {}}
    template_id = (await client.post("/api/templates/", json=payload, headers=a)).json()["id"]

    # A 能看到
    a_list = await client.get("/api/templates/", headers=a)
    assert any(t["id"] == template_id for t in a_list.json())
    # B 看不到 / 读不到 / 删不掉
    b_list = await client.get("/api/templates/", headers=b)
    assert not any(t["id"] == template_id for t in b_list.json())
    assert (await client.get(f"/api/templates/{template_id}", headers=b)).status_code == 404
    assert (await client.delete(f"/api/templates/{template_id}", headers=b)).status_code == 404


@pytest.mark.asyncio
async def test_audio_library_crud(client):
    h = await _auth(client)
    payload = {
        "name": "Happy Summer",
        "asset_type": "bgm",
        "file_path": "bgm/happy/summer.mp3",
        "mood": "happy",
        "duration_s": 120.5,
        "tags": ["summer", "energetic"],
        "is_official": True,  # ignored
    }
    resp = await client.post("/api/audio/", json=payload, headers=h)
    assert resp.status_code == 201
    asset = resp.json()
    asset_id = asset["id"]
    assert asset["is_official"] is False

    assert (await client.get(f"/api/audio/{asset_id}", headers=h)).json()["name"] == "Happy Summer"
    assert any(a["id"] == asset_id
               for a in (await client.get("/api/audio/?asset_type=bgm", headers=h)).json())
    assert any(a["id"] == asset_id
               for a in (await client.get("/api/audio/?mood=happy", headers=h)).json())
    assert any(a["id"] == asset_id
               for a in (await client.get("/api/audio/?tags=summer", headers=h)).json())
    assert any(a["id"] == asset_id
               for a in (await client.get("/api/audio/?query=Happy", headers=h)).json())
    assert (await client.delete(f"/api/audio/{asset_id}", headers=h)).status_code == 200


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
    h = await _auth(client)
    fake_id = str(uuid.uuid4())
    resp = await client.post(f"/api/templates/{fake_id}/apply", headers=h)
    assert resp.status_code == 404
    assert "Template not found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_template_list_filters(client):
    h = await _auth(client)
    await client.post("/api/templates/", json={
        "name": "Ecom", "category": "e-commerce", "canvas_json": {}
    }, headers=h)
    await client.post("/api/templates/", json={
        "name": "Pers", "category": "personal", "canvas_json": {}
    }, headers=h)

    # category filter
    resp = await client.get("/api/templates/?category=e-commerce", headers=h)
    assert all(t["category"] == "e-commerce" for t in resp.json())

    # official_only → 用户自建均非官方,故不含 "Pers"
    resp = await client.get("/api/templates/?official_only=true", headers=h)
    assert all(t["is_official"] for t in resp.json())
    assert not any(t["name"] == "Pers" for t in resp.json())


@pytest.mark.asyncio
async def test_audio_search_multi_tenancy(client):
    """A 的音频资产 B 搜不到。"""
    a = await _auth(client)
    b = await _auth(client)
    await client.post("/api/audio/", json={
        "name": "User-Audio", "asset_type": "sfx", "file_path": "f2"
    }, headers=a)

    a_names = [x["name"] for x in (await client.get("/api/audio/", headers=a)).json()]
    assert "User-Audio" in a_names
    b_names = [x["name"] for x in (await client.get("/api/audio/", headers=b)).json()]
    assert "User-Audio" not in b_names


@pytest.mark.asyncio
async def test_audio_errors(client):
    h = await _auth(client)
    fake_id = str(uuid.uuid4())
    assert (await client.get(f"/api/audio/{fake_id}", headers=h)).status_code == 404
    assert (await client.delete(f"/api/audio/{fake_id}", headers=h)).status_code == 404
