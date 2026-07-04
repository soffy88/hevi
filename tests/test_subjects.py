"""P11.A tests — subject library: service, repository, reference_store, API routes."""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hevi.auth.dependencies import get_current_user
from hevi.subjects.reference_store import ReferenceStore
from hevi.subjects.repository import SUBJECT_KINDS, SubjectRepository
from hevi.subjects.subject_service import SubjectService

_AUTH_USER = {"id": str(uuid.uuid4()), "is_active": True}

# ── Helpers ──────────────────────────────────────────────────────────────────

_SUBJECT_ID = str(uuid.uuid4())

_STORED: dict[str, Any] = {
    "id": _SUBJECT_ID,
    "name": "Ada",
    "description": "",
    "subject_type": "character",
    "reference_images": ["img/ada.jpg"],
    "metadata": {},
    "tags": [],
    "version": 1,
    "user_id": None,
    "deleted_at": None,
}


def _make_repo() -> tuple[SubjectRepository, MagicMock]:
    pool = MagicMock()
    return SubjectRepository(pool), pool


def _make_svc(repo: SubjectRepository | None = None) -> SubjectService:
    if repo is None:
        repo, _ = _make_repo()
    return SubjectService(repo)


# ── 1. SUBJECT_KINDS constant ─────────────────────────────────────────────────


def test_subject_kinds_values() -> None:
    assert frozenset({"character", "portrait", "product", "scene"}) == SUBJECT_KINDS


# ── 2. create_subject — 4 valid kinds ────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["character", "portrait", "product", "scene"])
async def test_create_subject_all_kinds(kind: str) -> None:
    repo, _ = _make_repo()
    stored = {**_STORED, "subject_type": kind}
    with (
        patch(
            "hevi.subjects.repository.insert_one",
            new_callable=AsyncMock,
            return_value=uuid.UUID(_SUBJECT_ID),
        ),
        patch("hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=stored),
    ):
        svc = _make_svc(repo)
        result = await svc.create_subject(
            kind=kind,
            name="Ada",
            reference_images=["img/ada.jpg"],
        )
    assert result["subject_type"] == kind


# ── 3. create_subject — validation errors ────────────────────────────────────


@pytest.mark.asyncio
async def test_create_subject_empty_name_raises() -> None:
    svc = _make_svc()
    with pytest.raises(ValueError, match="name must not be empty"):
        await svc.create_subject(kind="character", name="   ")


@pytest.mark.asyncio
async def test_create_subject_invalid_kind_raises() -> None:
    svc = _make_svc()
    with pytest.raises(ValueError, match="Invalid kind"):
        await svc.create_subject(kind="alien", name="Zork")


@pytest.mark.asyncio
async def test_create_subject_empty_reference_list_raises() -> None:
    svc = _make_svc()
    with pytest.raises(ValueError, match="reference_images must contain"):
        await svc.create_subject(kind="character", name="Ada", reference_images=[])


# ── 4. user_id nullable ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_subject_user_id_nullable() -> None:
    repo, _ = _make_repo()
    with (
        patch(
            "hevi.subjects.repository.insert_one",
            new_callable=AsyncMock,
            return_value=uuid.UUID(_SUBJECT_ID),
        ),
        patch("hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=_STORED),
    ):
        svc = _make_svc(repo)
        result = await svc.create_subject(kind="character", name="Ada", user_id=None)
    assert result["user_id"] is None


# ── 5. ReferenceStore ─────────────────────────────────────────────────────────


def test_reference_store_path_for() -> None:
    rs = ReferenceStore(base_dir="/data/refs")
    path = rs.path_for("sub-123", "face.jpg")
    assert path == "/data/refs/sub-123/face.jpg"


def test_reference_store_validate_refs_strips_empty() -> None:
    rs = ReferenceStore()
    cleaned = rs.validate_refs(["a.jpg", "", "  ", "b.jpg"])
    assert cleaned == ["a.jpg", "b.jpg"]


def test_reference_store_subject_dir() -> None:
    rs = ReferenceStore(base_dir="/data/refs")
    assert str(rs.subject_dir("abc")) == "/data/refs/abc"


# ── 6. Repository methods ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repository_create_calls_insert_one() -> None:
    repo, _pool = _make_repo()
    with (
        patch(
            "hevi.subjects.repository.insert_one",
            new_callable=AsyncMock,
            return_value=uuid.UUID(_SUBJECT_ID),
        ) as m,
        patch("hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=_STORED),
    ):
        await repo.create({"name": "Ada", "subject_type": "character"})
        m.assert_called_once()
        assert m.call_args.kwargs["table"] == "subjects"


@pytest.mark.asyncio
async def test_repository_get_returns_none_for_deleted() -> None:
    repo, _ = _make_repo()
    deleted_record = {**_STORED, "deleted_at": "2026-01-01T00:00:00"}
    mock_read = patch(
        "hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=deleted_record
    )
    with mock_read:
        result = await repo.get(_SUBJECT_ID)
    assert result is None


@pytest.mark.asyncio
async def test_repository_soft_delete_returns_false_for_missing() -> None:
    repo, _ = _make_repo()
    with patch("hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=None):
        result = await repo.soft_delete(_SUBJECT_ID)
    assert result is False


# ── 7. search_subjects ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_by_kind() -> None:
    repo, _ = _make_repo()
    mock_query = patch(
        "hevi.subjects.repository.query", new_callable=AsyncMock, return_value=[_STORED]
    )
    with mock_query as m:
        svc = _make_svc(repo)
        results = await svc.search_subjects(kind="character")
    assert len(results) == 1
    # Verify 'character' appeared somewhere in the SQL query call
    sql_used: str = m.call_args.kwargs.get("sql", "")
    assert "subject_type" in sql_used


@pytest.mark.asyncio
async def test_search_by_query_text() -> None:
    repo, _ = _make_repo()
    with patch("hevi.subjects.repository.query", new_callable=AsyncMock, return_value=[]) as m:
        svc = _make_svc(repo)
        await svc.search_subjects(query="Ada")
    sql_used: str = m.call_args.kwargs.get("sql", "")
    assert "ILIKE" in sql_used


# ── 8. update_subject_metadata ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_subject_metadata_merges() -> None:
    repo, _ = _make_repo()
    base = {**_STORED, "metadata": {"color": "blue"}}
    updated = {**base, "metadata": {"color": "blue", "mood": "happy"}, "version": 2}
    with (
        patch("hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=base),
        patch("hevi.subjects.repository.update_one", new_callable=AsyncMock, return_value=True),
    ):
        # get is called 3×: service exists-check, repo.update exists-check, repo.update return
        with patch.object(repo, "get", new_callable=AsyncMock, side_effect=[base, base, updated]):
            svc = _make_svc(repo)
            result = await svc.update_subject_metadata(_SUBJECT_ID, metadata={"mood": "happy"})
    assert result is not None
    assert result["metadata"]["mood"] == "happy"


@pytest.mark.asyncio
async def test_update_subject_metadata_nonexistent_returns_none() -> None:
    repo, _ = _make_repo()
    with patch("hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=None):
        svc = _make_svc(repo)
        result = await svc.update_subject_metadata(_SUBJECT_ID, metadata={"x": 1})
    assert result is None


# ── 9. soft delete ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_soft_delete_returns_true() -> None:
    repo, _ = _make_repo()
    with (
        patch("hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=_STORED),
        patch("hevi.subjects.repository.update_one", new_callable=AsyncMock, return_value=True),
    ):
        result = await repo.soft_delete(_SUBJECT_ID)
    assert result is True


# ── 10. API routes ────────────────────────────────────────────────────────────


def _mock_svc() -> SubjectService:
    pool = MagicMock()
    repo = SubjectRepository(pool)
    return SubjectService(repo)


@pytest.mark.asyncio
async def test_api_create_subject(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    with patch.object(svc, "create_subject", new_callable=AsyncMock, return_value=_STORED):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.post(
            "/api/subjects/",
            json={"kind": "character", "name": "Ada", "reference_images": ["img/ada.jpg"]},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["name"] == "Ada"


@pytest.mark.asyncio
async def test_api_get_subject(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    with patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=_STORED):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.get(f"/api/subjects/{_SUBJECT_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["id"] == _SUBJECT_ID


@pytest.mark.asyncio
async def test_api_get_subject_404(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    with patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=None):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.get(f"/api/subjects/{_SUBJECT_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_list_subjects(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    with patch.object(svc, "search_subjects", new_callable=AsyncMock, return_value=[_STORED]):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.get("/api/subjects/")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_api_update_subject(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    updated = {**_STORED, "metadata": {"mood": "calm"}, "version": 2}
    svc = _mock_svc()
    with (
        patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=_STORED),
        patch.object(svc, "update_subject_metadata", new_callable=AsyncMock, return_value=updated),
    ):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.patch(
            f"/api/subjects/{_SUBJECT_ID}",
            json={"metadata": {"mood": "calm"}},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["metadata"]["mood"] == "calm"


@pytest.mark.asyncio
async def test_api_delete_subject(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    with (
        patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=_STORED),
        patch.object(svc, "delete_subject", new_callable=AsyncMock, return_value=True),
    ):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.delete(f"/api/subjects/{_SUBJECT_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_api_delete_subject_404(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    with (
        patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=_STORED),
        patch.object(svc, "delete_subject", new_callable=AsyncMock, return_value=False),
    ):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.delete(f"/api/subjects/{_SUBJECT_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_create_invalid_kind(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    with patch.object(
        svc, "create_subject", new_callable=AsyncMock, side_effect=ValueError("Invalid kind")
    ):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.post(
            "/api/subjects/",
            json={"kind": "alien", "name": "Zork"},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 422


# ── 10b. IDOR / 鉴权 (end-to-end, 真 DB) ──────────────────────────────────────


async def _register(client: Any) -> dict[str, str]:
    email = f"idor_{uuid.uuid4().hex[:8]}@example.com"
    await client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "display_name": "U"}
    )
    login = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_subjects_require_auth(client: Any) -> None:
    """无 token → 401。"""
    resp = await client.get("/api/subjects/")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_subjects_idor_cross_user_404(client: Any) -> None:
    """用户 A 的 subject,用户 B 读取/删除 → 404。"""
    a = await _register(client)
    b = await _register(client)
    created = await client.post(
        "/api/subjects/",
        json={"kind": "character", "name": "Ada", "reference_images": ["img/ada.jpg"]},
        headers=a,
    )
    assert created.status_code == 201
    sid = created.json()["id"]

    # 拥有者可读
    assert (await client.get(f"/api/subjects/{sid}", headers=a)).status_code == 200
    # 他人 404
    assert (await client.get(f"/api/subjects/{sid}", headers=b)).status_code == 404
    assert (await client.delete(f"/api/subjects/{sid}", headers=b)).status_code == 404
    # 列表按 owner 隔离:B 看不到 A 的 subject
    b_list = await client.get("/api/subjects/", headers=b)
    assert all(s["id"] != sid for s in b_list.json())


# ── 11. Route order — list route before /{id} ─────────────────────────────────


def test_list_route_before_detail_route() -> None:
    from hevi.api.routers.subjects import router

    paths = [r.path for r in router.routes]
    assert paths.index("/subjects/") < paths.index("/subjects/{subject_id}")


# ── 角色库:上传照片 → 参考图(2D 锁定入口)──────────────────────────────────


def test_reference_store_save_upload(tmp_path) -> None:
    """save_upload:字节落盘到 subject 目录 + 防路径穿越,返回可读回路径。"""
    store = ReferenceStore(base_dir=tmp_path)
    p = store.save_upload(_SUBJECT_ID, "my photo!.jpg", b"\xff\xd8jpegbytes")
    from pathlib import Path as _P

    assert _P(p).exists()
    assert _P(p).read_bytes() == b"\xff\xd8jpegbytes"
    # 恶意文件名被清洗(无路径穿越)
    p2 = store.save_upload(_SUBJECT_ID, "../../etc/passwd", b"x")
    assert "etc/passwd" not in p2 and _P(p2).parent == store.subject_dir(_SUBJECT_ID)


@pytest.mark.asyncio
async def test_add_reference_upload_appends(tmp_path) -> None:
    """add_reference_upload:落盘 + 把新路径追加到 subject.reference_images。"""
    repo, _ = _make_repo()
    captured: dict[str, Any] = {}

    async def _fake_update(sid, data):
        captured.update(data)
        return {**_STORED, **data}

    with (
        patch(
            "hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=dict(_STORED)
        ),
        patch.object(repo, "update", side_effect=_fake_update),
    ):
        svc = SubjectService(repo, ref_store=ReferenceStore(base_dir=tmp_path))
        result = await svc.add_reference_upload(_SUBJECT_ID, filename="new.jpg", data=b"abc")
        assert result is not None
        refs = captured["reference_images"]
        assert len(refs) == 2  # 原有 1 张 + 新增 1 张
        from pathlib import Path as _P

        assert _P(refs[-1]).read_bytes() == b"abc"


@pytest.mark.asyncio
async def test_add_reference_upload_missing_subject(tmp_path) -> None:
    repo, _ = _make_repo()
    with patch("hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=None):
        svc = SubjectService(repo, ref_store=ReferenceStore(base_dir=tmp_path))
        assert (
            await svc.add_reference_upload(str(uuid.uuid4()), filename="x.jpg", data=b"y") is None
        )
