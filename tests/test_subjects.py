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


@pytest.fixture(autouse=True)
def _no_real_vlm_probe(monkeypatch):
    """IP 安全 pass 的图像半边(#36)会在有新参考图上传时探测本地 VL 模型可用性——
    这个探测是真实 HTTP 调用(hevi.providers.local_qwen_vl_adapter.vl_model_available),
    这个测试文件里绝大多数用例测的是身份向量/参考图管理逻辑,不该因为这一步意外
    打真实网络/拖慢整个文件。默认视为"不可用"(_screen_new_uploads 短路返回 []),
    专门测 IP screening 的用例自己覆盖这个 patch。"""
    monkeypatch.setattr("hevi.providers.local_qwen_vl_adapter.vl_model_available", lambda: False)


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


# ── Phase 1:批量传图 / 参考图整体替换(设封面/删除/排序) / 编辑基础字段 / 多图平均向量 ──


@pytest.mark.asyncio
async def test_add_reference_uploads_batch_appends_all(tmp_path) -> None:
    """一次批量传多张 → 全部落盘追加,只重算一次身份向量(mock 掉,不跑真 CLIP)。"""
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
        patch.object(
            SubjectService,
            "_compute_identity_embeddings",
            new_callable=AsyncMock,
            return_value=([0.1, 0.2], [0.3, 0.4]),
        ) as memb,
    ):
        svc = SubjectService(repo, ref_store=ReferenceStore(base_dir=tmp_path))
        result = await svc.add_reference_uploads(
            _SUBJECT_ID, files=[("a.jpg", b"aaa"), ("b.jpg", b"bbb")]
        )
    assert result is not None
    refs = captured["reference_images"]
    assert len(refs) == 3  # 原有 1 张 + 批量 2 张
    assert captured["identity_embedding_face"] == [0.3, 0.4]
    memb.assert_awaited_once()  # 只重算一次,不是每张图重算


@pytest.mark.asyncio
async def test_add_reference_uploads_missing_subject() -> None:
    repo, _ = _make_repo()
    with patch("hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=None):
        svc = SubjectService(repo)
        assert await svc.add_reference_uploads(str(uuid.uuid4()), files=[("x.jpg", b"y")]) is None


@pytest.mark.asyncio
async def test_update_references_reorders_sets_cover(tmp_path) -> None:
    """PUT 整体替换:前端把"选中的图挪到第 0 位"算好后传回来 → 落库顺序照旧。"""
    repo, _ = _make_repo()
    stored = {**_STORED, "reference_images": ["a.jpg", "b.jpg", "c.jpg"]}
    captured: dict[str, Any] = {}

    async def _fake_update(sid, data):
        captured.update(data)
        return {**stored, **data}

    with (
        patch(
            "hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=dict(stored)
        ),
        patch.object(repo, "update", side_effect=_fake_update),
        patch.object(
            SubjectService,
            "_compute_identity_embeddings",
            new_callable=AsyncMock,
            return_value=(None, None),
        ),
    ):
        svc = SubjectService(repo)
        result = await svc.update_references(_SUBJECT_ID, reference_images=["c.jpg", "a.jpg"])
    assert result is not None
    assert captured["reference_images"] == ["c.jpg", "a.jpg"]  # c 变成第 0 位(新封面)+ b 被删除


@pytest.mark.asyncio
async def test_update_references_missing_subject() -> None:
    repo, _ = _make_repo()
    with patch("hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=None):
        svc = SubjectService(repo)
        assert await svc.update_references(str(uuid.uuid4()), reference_images=["x.jpg"]) is None


# ── reference_role (设计文档 §5.2:参考素材正交角色标签) ─────────────────────────


@pytest.mark.asyncio
async def test_set_reference_role_tags_existing_image() -> None:
    repo, _ = _make_repo()
    stored = {**_STORED, "reference_images": ["a.jpg", "b.jpg"]}
    captured: dict[str, Any] = {}

    async def _fake_update(sid, data):
        captured.update(data)
        return {**stored, **data}

    with (
        patch(
            "hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=dict(stored)
        ),
        patch.object(repo, "update", side_effect=_fake_update),
    ):
        svc = SubjectService(repo)
        result = await svc.set_reference_role(_SUBJECT_ID, path="a.jpg", role="identity_anchor")
    assert result is not None
    assert captured["reference_roles"] == {"a.jpg": "identity_anchor"}


@pytest.mark.asyncio
async def test_set_reference_role_merges_with_existing_tags() -> None:
    repo, _ = _make_repo()
    stored = {
        **_STORED,
        "reference_images": ["a.jpg", "b.jpg"],
        "reference_roles": {"a.jpg": "identity_anchor"},
    }
    captured: dict[str, Any] = {}

    async def _fake_update(sid, data):
        captured.update(data)
        return {**stored, **data}

    with (
        patch(
            "hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=dict(stored)
        ),
        patch.object(repo, "update", side_effect=_fake_update),
    ):
        svc = SubjectService(repo)
        await svc.set_reference_role(_SUBJECT_ID, path="b.jpg", role="composition_ref")
    # 已有的 a.jpg 标签保留,不因为只打 b.jpg 就被冲掉。
    assert captured["reference_roles"] == {
        "a.jpg": "identity_anchor",
        "b.jpg": "composition_ref",
    }


@pytest.mark.asyncio
async def test_set_reference_role_rejects_path_not_in_reference_images() -> None:
    repo, _ = _make_repo()
    stored = {**_STORED, "reference_images": ["a.jpg"]}
    with patch(
        "hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=dict(stored)
    ):
        svc = SubjectService(repo)
        with pytest.raises(ValueError, match="not a reference image"):
            await svc.set_reference_role(_SUBJECT_ID, path="not-there.jpg", role="identity_anchor")


@pytest.mark.asyncio
async def test_set_reference_role_rejects_empty_role() -> None:
    repo, _ = _make_repo()
    stored = {**_STORED, "reference_images": ["a.jpg"]}
    with patch(
        "hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=dict(stored)
    ):
        svc = SubjectService(repo)
        with pytest.raises(ValueError, match="role must not be empty"):
            await svc.set_reference_role(_SUBJECT_ID, path="a.jpg", role="   ")


@pytest.mark.asyncio
async def test_set_reference_role_missing_subject() -> None:
    repo, _ = _make_repo()
    with patch("hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=None):
        svc = SubjectService(repo)
        result = await svc.set_reference_role(str(uuid.uuid4()), path="a.jpg", role="x")
    assert result is None


@pytest.mark.asyncio
async def test_update_subject_fields_name_description_tags() -> None:
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
        svc = SubjectService(repo)
        result = await svc.update_subject_fields(
            _SUBJECT_ID, name="新名字", description="新描述", tags=["主角"]
        )
    assert result is not None
    assert captured == {"name": "新名字", "description": "新描述", "tags": ["主角"]}


@pytest.mark.asyncio
async def test_update_subject_fields_empty_name_raises() -> None:
    repo, _ = _make_repo()
    with patch(
        "hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=dict(_STORED)
    ):
        svc = SubjectService(repo)
        with pytest.raises(ValueError):
            await svc.update_subject_fields(_SUBJECT_ID, name="   ")


@pytest.mark.asyncio
async def test_update_subject_fields_missing_subject() -> None:
    repo, _ = _make_repo()
    with patch("hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=None):
        svc = SubjectService(repo)
        assert await svc.update_subject_fields(str(uuid.uuid4()), name="x") is None


@pytest.mark.asyncio
async def test_update_subject_fields_noop_returns_existing() -> None:
    """三个字段都不传 → 不触发落库,直接回读到的现状。"""
    repo, _ = _make_repo()
    with patch(
        "hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=dict(_STORED)
    ):
        svc = SubjectService(repo)
        result = await svc.update_subject_fields(_SUBJECT_ID)
    assert result == _STORED


@pytest.mark.asyncio
async def test_compute_identity_embeddings_averages_multiple_refs() -> None:
    """多张参考图 → 逐张算向量后取平均 + L2 重归一化(而非只用第一张)。"""
    repo, _ = _make_repo()
    svc = SubjectService(repo)

    def _fake_embed(*, image_path, kind):
        # 两张正交向量,平均后归一化应各占一半再拉伸回单位长度
        return {"a.jpg": [1.0, 0.0], "b.jpg": [0.0, 1.0]}[str(image_path)]

    with patch("hevi.subjects.subject_embed.subject_embed", side_effect=_fake_embed):
        whole, face = await svc._compute_identity_embeddings(["a.jpg", "b.jpg"])
    assert whole is not None and face is not None
    import math

    for vec in (whole, face):
        assert math.isclose(vec[0], vec[1], rel_tol=1e-6)
        assert math.isclose(math.sqrt(vec[0] ** 2 + vec[1] ** 2), 1.0, rel_tol=1e-6)  # 归一化


@pytest.mark.asyncio
async def test_compute_identity_embeddings_caps_at_five_refs() -> None:
    """超过 5 张只取前 5 张算,避免角色攒几十张图后每次都线性变慢(每张图 2 次
    调用:全图 + 脸部区域各一次)。"""
    repo, _ = _make_repo()
    svc = SubjectService(repo)
    calls: list[str] = []

    def _fake_embed(*, image_path, kind):
        calls.append(str(image_path))
        return [1.0, 0.0]

    refs = [f"img{i}.jpg" for i in range(8)]
    with patch("hevi.subjects.subject_embed.subject_embed", side_effect=_fake_embed):
        await svc._compute_identity_embeddings(refs)
    assert set(calls) == set(refs[:5])
    assert len(calls) == 10  # 5 张 * (全图 + 脸部) = 10 次


@pytest.mark.asyncio
async def test_compute_identity_embeddings_skips_failed_images() -> None:
    """某张图算失败(文件缺失等)→ 跳过它,用剩下能算的图平均,不整体失败。"""
    from hevi.subjects.subject_embed import SubjectEmbedError

    repo, _ = _make_repo()
    svc = SubjectService(repo)

    def _fake_embed(*, image_path, kind):
        if image_path == "bad.jpg":
            raise SubjectEmbedError("missing")
        return [1.0, 0.0]

    with patch("hevi.subjects.subject_embed.subject_embed", side_effect=_fake_embed):
        whole, face = await svc._compute_identity_embeddings(["bad.jpg", "good.jpg"])
    assert whole == [1.0, 0.0]
    assert face == [1.0, 0.0]


# ── IP 安全 pass —— 图像半边(HEVI 路线图 Phase2 #36)────────────────────────────


async def test_screen_new_uploads_returns_empty_when_vlm_unavailable() -> None:
    # 依赖上面的 autouse fixture(vl_model_available → False)
    svc = _make_svc()
    assert await svc._screen_new_uploads(["a.jpg"]) == []


async def test_screen_new_uploads_returns_empty_for_no_paths(monkeypatch) -> None:
    monkeypatch.setattr("hevi.providers.local_qwen_vl_adapter.vl_model_available", lambda: True)
    svc = _make_svc()
    assert await svc._screen_new_uploads([]) == []


async def test_screen_new_uploads_flags_when_vlm_available(monkeypatch) -> None:
    monkeypatch.setattr("hevi.providers.local_qwen_vl_adapter.vl_model_available", lambda: True)
    monkeypatch.setattr(
        "hevi.subjects.ip_screening.flag_if_recognizable_person",
        AsyncMock(return_value=["疑似某公众人物"]),
    )
    svc = _make_svc()
    flags = await svc._screen_new_uploads(["a.jpg", "b.jpg"])
    assert flags == ["疑似某公众人物", "疑似某公众人物"]  # 逐张检查,各自结果累加


async def test_create_subject_stores_ip_safety_flags_in_metadata(monkeypatch) -> None:
    """建角色时命中 IP 顾虑 → 写进 metadata.ip_safety_flags,不阻断建号。"""
    repo, _ = _make_repo()
    svc = SubjectService(repo)
    captured: dict[str, Any] = {}

    async def _fake_create(data):
        captured.update(data)
        return data

    monkeypatch.setattr("hevi.providers.local_qwen_vl_adapter.vl_model_available", lambda: True)
    monkeypatch.setattr(
        "hevi.subjects.ip_screening.flag_if_recognizable_person",
        AsyncMock(return_value=["疑似某公众人物"]),
    )
    with (
        patch.object(repo, "create", side_effect=_fake_create),
        patch.object(
            SubjectService,
            "_compute_identity_embeddings",
            new_callable=AsyncMock,
            return_value=(None, None),
        ),
    ):
        await svc.create_subject(kind="character", name="X", reference_images=["a.jpg"])
    assert captured["metadata"]["ip_safety_flags"] == ["疑似某公众人物"]


async def test_add_reference_upload_only_screens_the_newly_added_file(monkeypatch) -> None:
    """只该检查这次新加的文件,不该把已有的 reference_images 也重新过一遍
    (否则每次加图都要把历史图片全跑一遍 VLM,累积开销线性爆炸)。"""
    repo, _ = _make_repo()
    svc = SubjectService(repo, ref_store=ReferenceStore(base_dir="/tmp"))
    checked: list[str] = []

    async def _fake_flag(path, *, vlm):
        checked.append(str(path))
        return []

    monkeypatch.setattr("hevi.providers.local_qwen_vl_adapter.vl_model_available", lambda: True)
    monkeypatch.setattr("hevi.subjects.ip_screening.flag_if_recognizable_person", _fake_flag)
    with (
        patch(
            "hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=dict(_STORED)
        ),
        patch.object(repo, "update", new_callable=AsyncMock, return_value=_STORED),
        patch.object(
            SubjectService,
            "_compute_identity_embeddings",
            new_callable=AsyncMock,
            return_value=(None, None),
        ),
    ):
        await svc.add_reference_upload(_SUBJECT_ID, filename="new.jpg", data=b"data")
    assert len(checked) == 1
    assert checked[0].endswith("new.jpg")


# ── Phase 1 API:批量传图 / 参考图重排 / PATCH 姓名描述标签 ──────────────────────


@pytest.mark.asyncio
async def test_api_upload_references_batch(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    updated = {**_STORED, "reference_images": ["img/ada.jpg", "img/new1.jpg", "img/new2.jpg"]}
    with (
        patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=_STORED),
        patch.object(svc, "add_reference_uploads", new_callable=AsyncMock, return_value=updated),
    ):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.post(
            f"/api/subjects/{_SUBJECT_ID}/references",
            files=[
                ("files", ("a.jpg", b"\xff\xd8fake", "image/jpeg")),
                ("files", ("b.jpg", b"\xff\xd8fake2", "image/jpeg")),
            ],
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert len(resp.json()["reference_images"]) == 3


@pytest.mark.asyncio
async def test_api_reorder_references(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    updated = {**_STORED, "reference_images": ["img/b.jpg", "img/ada.jpg"]}
    with (
        patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=_STORED),
        patch.object(svc, "update_references", new_callable=AsyncMock, return_value=updated) as mu,
    ):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.put(
            f"/api/subjects/{_SUBJECT_ID}/references",
            json={"reference_images": ["img/b.jpg", "img/ada.jpg"]},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["reference_images"] == ["img/b.jpg", "img/ada.jpg"]
    mu.assert_awaited_once_with(_SUBJECT_ID, reference_images=["img/b.jpg", "img/ada.jpg"])


@pytest.mark.asyncio
async def test_api_reorder_references_404(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    with patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=None):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.put(
            f"/api/subjects/{_SUBJECT_ID}/references", json={"reference_images": ["x.jpg"]}
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_set_reference_role(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    updated = {**_STORED, "reference_roles": {"img/ada.jpg": "identity_anchor"}}
    with (
        patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=_STORED),
        patch.object(
            svc, "set_reference_role", new_callable=AsyncMock, return_value=updated
        ) as mset,
    ):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.put(
            f"/api/subjects/{_SUBJECT_ID}/reference-role",
            json={"path": "img/ada.jpg", "role": "identity_anchor"},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["reference_roles"] == {"img/ada.jpg": "identity_anchor"}
    mset.assert_awaited_once_with(_SUBJECT_ID, path="img/ada.jpg", role="identity_anchor")


@pytest.mark.asyncio
async def test_api_set_reference_role_404_for_missing_subject(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    with patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=None):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.put(
            f"/api/subjects/{_SUBJECT_ID}/reference-role",
            json={"path": "img/ada.jpg", "role": "identity_anchor"},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_set_reference_role_422_for_unknown_path(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    with (
        patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=_STORED),
        patch.object(
            svc,
            "set_reference_role",
            new_callable=AsyncMock,
            side_effect=ValueError("'nope.jpg' is not a reference image of this subject"),
        ),
    ):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.put(
            f"/api/subjects/{_SUBJECT_ID}/reference-role",
            json={"path": "nope.jpg", "role": "identity_anchor"},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_api_patch_name_description_tags(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    updated = {**_STORED, "name": "新名字", "description": "新描述", "tags": ["主角"]}
    with (
        patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=_STORED),
        patch.object(
            svc, "update_subject_fields", new_callable=AsyncMock, return_value=updated
        ) as muf,
    ):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.patch(
            f"/api/subjects/{_SUBJECT_ID}",
            json={"name": "新名字", "description": "新描述", "tags": ["主角"]},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["name"] == "新名字"
    muf.assert_awaited_once_with(_SUBJECT_ID, name="新名字", description="新描述", tags=["主角"])


@pytest.mark.asyncio
async def test_api_patch_empty_name_422(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    with (
        patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=_STORED),
        patch.object(
            svc,
            "update_subject_fields",
            new_callable=AsyncMock,
            side_effect=ValueError("name must not be empty"),
        ),
    ):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.patch(f"/api/subjects/{_SUBJECT_ID}", json={"name": "   "})
        app.dependency_overrides.clear()
    assert resp.status_code == 422


# ── Phase 3:声音参考(VibeVoice 克隆用)/ 造型参考图(与身份参考图分开管理)──────


@pytest.mark.asyncio
async def test_add_voice_reference_writes_metadata(tmp_path) -> None:
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
        svc = SubjectService(repo, voice_store=ReferenceStore(base_dir=tmp_path))
        result = await svc.add_voice_reference(_SUBJECT_ID, filename="v.wav", data=b"RIFF...")
    assert result is not None
    assert captured["metadata"]["voice_ref"].endswith("v.wav")
    from pathlib import Path as _P

    assert _P(captured["metadata"]["voice_ref"]).read_bytes() == b"RIFF..."


@pytest.mark.asyncio
async def test_add_voice_reference_missing_subject() -> None:
    repo, _ = _make_repo()
    with patch("hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=None):
        svc = SubjectService(repo)
        assert await svc.add_voice_reference(str(uuid.uuid4()), filename="v.wav", data=b"x") is None


@pytest.mark.asyncio
async def test_add_wardrobe_upload_appends_to_metadata_list(tmp_path) -> None:
    repo, _ = _make_repo()
    stored = {**_STORED, "metadata": {"wardrobe_images": ["old.jpg"]}}
    captured: dict[str, Any] = {}

    async def _fake_update(sid, data):
        captured.update(data)
        return {**stored, **data}

    with (
        patch(
            "hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=dict(stored)
        ),
        patch.object(repo, "update", side_effect=_fake_update),
    ):
        svc = SubjectService(repo, ref_store=ReferenceStore(base_dir=tmp_path))
        result = await svc.add_wardrobe_upload(_SUBJECT_ID, filename="outfit.jpg", data=b"img")
    assert result is not None
    assert len(captured["metadata"]["wardrobe_images"]) == 2  # 旧 1 张 + 新 1 张
    # reference_images(身份参考图)不受影响
    assert "reference_images" not in captured


@pytest.mark.asyncio
async def test_add_wardrobe_upload_missing_subject() -> None:
    repo, _ = _make_repo()
    with patch("hevi.subjects.repository.read_one", new_callable=AsyncMock, return_value=None):
        svc = SubjectService(repo)
        assert await svc.add_wardrobe_upload(str(uuid.uuid4()), filename="x.jpg", data=b"y") is None


@pytest.mark.asyncio
async def test_api_upload_voice(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    updated = {**_STORED, "metadata": {"voice_ref": "output/voice_references/x/v.wav"}}
    with (
        patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=_STORED),
        patch.object(svc, "add_voice_reference", new_callable=AsyncMock, return_value=updated),
    ):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.post(
            f"/api/subjects/{_SUBJECT_ID}/voice",
            files={"file": ("v.wav", b"RIFF....", "audio/wav")},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["metadata"]["voice_ref"].endswith("v.wav")


@pytest.mark.asyncio
async def test_api_upload_voice_rejects_non_audio(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    with patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=_STORED):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.post(
            f"/api/subjects/{_SUBJECT_ID}/voice",
            files={"file": ("x.jpg", b"\xff\xd8fake", "image/jpeg")},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_api_upload_wardrobe(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    updated = {**_STORED, "metadata": {"wardrobe_images": ["output/reference_images/x/outfit.jpg"]}}
    with (
        patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=_STORED),
        patch.object(svc, "add_wardrobe_upload", new_callable=AsyncMock, return_value=updated),
    ):
        app.dependency_overrides[get_subject_service] = lambda: svc
        app.dependency_overrides[get_current_user] = lambda: _AUTH_USER
        resp = await client.post(
            f"/api/subjects/{_SUBJECT_ID}/wardrobe",
            files={"file": ("outfit.jpg", b"\xff\xd8fake", "image/jpeg")},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert len(resp.json()["metadata"]["wardrobe_images"]) == 1


@pytest.mark.asyncio
async def test_api_get_subject_image_wardrobe_source(client: Any, tmp_path) -> None:
    """source=wardrobe → 读 metadata.wardrobe_images,而非身份参考图 reference_images。"""
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    outfit = tmp_path / "outfit.jpg"
    outfit.write_bytes(b"\xff\xd8fake")
    svc = _mock_svc()
    stored = {**_STORED, "user_id": None, "metadata": {"wardrobe_images": [str(outfit)]}}
    with (
        patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=stored),
        patch("hevi.api.routers.subjects.decode_access_token", return_value={"sub": "u1"}),
    ):
        app.dependency_overrides[get_subject_service] = lambda: svc
        resp = await client.get(
            f"/api/subjects/{_SUBJECT_ID}/image",
            params={"token": "tok", "source": "wardrobe", "idx": 0},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_get_subject_image_wardrobe_missing_404(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.subjects import get_subject_service

    svc = _mock_svc()
    stored = {**_STORED, "user_id": None, "metadata": {}}  # 没有 wardrobe_images
    with (
        patch.object(svc, "get_subject", new_callable=AsyncMock, return_value=stored),
        patch("hevi.api.routers.subjects.decode_access_token", return_value={"sub": "u1"}),
    ):
        app.dependency_overrides[get_subject_service] = lambda: svc
        resp = await client.get(
            f"/api/subjects/{_SUBJECT_ID}/image",
            params={"token": "tok", "source": "wardrobe", "idx": 0},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 404
