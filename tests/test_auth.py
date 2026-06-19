import uuid

import pytest


@pytest.mark.asyncio
async def test_register_success(client):
    email = f"test_{uuid.uuid4().hex[:6]}@example.com"
    payload = {
        "email": email,
        "password": "strongpassword123",
        "display_name": "Test User"
    }
    resp = await client.post("/api/auth/register", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    # A: register 返回 token(修复前只返回 user dict)
    assert "access_token" in data, "register must return access_token"
    assert "token" in data, "register must return token alias"
    assert data["user"]["email"] == email
    assert "password_hash" not in data


@pytest.mark.asyncio
async def test_register_grants_signup_bonus(client):
    """B: 注册送 1000 credits"""
    email = f"bonus_{uuid.uuid4().hex[:6]}@example.com"
    resp = await client.post("/api/auth/register", json={
        "email": email,
        "password": "strongpassword123",
        "display_name": "Bonus User",
    })
    assert resp.status_code == 201
    token = resp.json()["access_token"]

    balance_resp = await client.get(
        "/api/credits/balance",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert balance_resp.status_code == 200
    assert balance_resp.json()["balance"] == 1000


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    email = "dup@example.com"
    payload = {
        "email": email,
        "password": "password123",
        "display_name": "User 1"
    }
    await client.post("/api/auth/register", json=payload)

    resp = await client.post("/api/auth/register", json=payload)
    assert resp.status_code == 409
    assert "already registered" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login_success(client):
    """A: login 200(字段匹配)"""
    email = f"login_{uuid.uuid4().hex[:6]}@example.com"
    password = "correct_password"
    await client.post("/api/auth/register", json={
        "email": email,
        "password": password,
        "display_name": "Login User"
    })

    resp = await client.post("/api/auth/login", json={
        "email": email,
        "password": password
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == email


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    email = "wrong_pass@example.com"
    await client.post("/api/auth/register", json={
        "email": email,
        "password": "correct_password",
        "display_name": "User"
    })

    resp = await client.post("/api/auth/login", json={
        "email": email,
        "password": "wrong"
    })
    assert resp.status_code == 401
    assert "Invalid email or password" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_me_success(client):
    email = f"me_{uuid.uuid4().hex[:6]}@example.com"
    password = "password123"
    await client.post("/api/auth/register", json={
        "email": email,
        "password": password,
        "display_name": "Me User"
    })

    login_resp = await client.post("/api/auth/login", json={
        "email": email,
        "password": password
    })
    token = login_resp.json()["access_token"]

    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == email


@pytest.mark.asyncio
async def test_get_me_unauthorized(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code in (401, 403, 422)

    resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer invalid_token"})
    assert resp.status_code == 401
    assert "Invalid or expired token" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_google_oauth_skeleton(client):
    payload = {"code": "test_code"}
    resp = await client.post("/api/auth/oauth/google", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["auth_provider"] == "google"


@pytest.mark.asyncio
async def test_google_oauth_invalid(client):
    payload = {"code": "invalid_code"}
    resp = await client.post("/api/auth/oauth/google", json=payload)
    assert resp.status_code == 400
    assert "Invalid OAuth code" in resp.json()["detail"]
