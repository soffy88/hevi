"""Agent 画布操作桥（单元 C）可测验收：真实 DB/存储层 + 真实 ShotSpec 校验器，无 mock。

存储层用 ``SqliteOperationsStore``（离线、真实 WAL SQLite，无网络出站、无 mock）。
行内容(ShotSpec)校验复用既有 ``hevi.production.shot_spec.ShotSpec`` 校验器。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.api.routers.ops import _get_store
from hevi.auth.dependencies import get_current_user
from hevi.operations.bridge import SqliteOperationsStore
from hevi.operations.in_memory import InMemorySubjectRepository
from hevi.operations.registry import clear_idempotency, get_operation_names
import asyncio


def _count_tasks() -> int:
    return asyncio.run(_get_store().count_tasks())

USER = {"id": "ops-user", "email": "ops@example.com", "role": "user"}

GRAPH_ID = str(uuid4())
GRAPH_ID_B = str(uuid4())


@pytest.fixture()
def store(tmp_path: Path) -> SqliteOperationsStore:
    db = SqliteOperationsStore(tmp_path / "agent_ops.db")
    # 正式资产写入：经既有 SubjectRepository（非演示数据）。
    subject_repo = InMemorySubjectRepository()
    for i, category in enumerate(("character", "character", "scene", "prop")):
        asyncio.run(
            subject_repo.create(
                {
                    "id": str(uuid4()),
                    "subject_type": category,
                    "name": f"asset-{i}",
                    "version": i + 1,
                }
            )
        )
    # 预置两个画布图（带 script 节点 + revision=0），经既有 GraphRepository 写入。
    for gid in (GRAPH_ID, GRAPH_ID_B):
        asyncio.run(
            db._graph_repo.create(
                {
                    "id": gid,
                    "graph_id": gid,
                    "nodes": [{"type": "script", "rows": []}, {"type": "image", "id": "n1"}],
                    "edges": [],
                    "revision": 0,
                }
            )
        )
    return db


@pytest.fixture()
def client(store: SqliteOperationsStore, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HEVI_AGENT_OPS_DB", str(tmp_path / "agent_ops.db"))
    app.dependency_overrides[get_current_user] = lambda: USER
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()
    clear_idempotency()


def _valid_row() -> dict[str, Any]:
    return {"effect": "warm", "transition_in": "fade", "duration": 3.0}


def _post(client: TestClient, name: str, params: dict[str, Any], **kw: Any) -> Any:
    body: dict[str, Any] = {"params": params}
    if "opId" in kw:
        body["opId"] = kw["opId"]
    if "expectedRevision" in kw:
        body["expectedRevision"] = kw["expectedRevision"]
    return client.post(f"/api/ops/{name}?mode={kw.get('mode', 'read-write')}", json=body)


# ── 验收 1: GET /api/ops ───────────────────────────────────────────────────────


def test_ops_list_fields_complete(client: TestClient) -> None:
    r = client.get("/api/ops")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 8
    names = sorted(o["name"] for o in body["operations"])
    assert names == sorted(get_operation_names())
    for op in body["operations"]:
        assert set(["name", "readOnly", "scope", "params", "replay"]) <= set(op)


def test_ops_readonly_set(client: TestClient) -> None:
    r = client.get("/api/ops")
    ro = set(r.json()["read_only_operations"])
    assert ro == {
        "canvas.get",
        "canvas.generation.propose",
        "asset.list",
        "task.get",
    }


# ── 验收 2: 幂等重放 ────────────────────────────────────────────────────────────


def test_idempotent_append_replays_same_receipt(client: TestClient) -> None:
    p1 = _post(client, "canvas.script.rows.append", {"graph_id": GRAPH_ID, "row": _valid_row()},
               opId="op-1", expectedRevision=0)
    assert p1.status_code == 200, p1.text
    first = p1.json()
    assert first["row_count"] == 1

    p2 = _post(client, "canvas.script.rows.append", {"graph_id": GRAPH_ID, "row": _valid_row()},
               opId="op-1", expectedRevision=first["revision"])
    assert p2.status_code == 200, p2.text
    second = p2.json()
    # 画布行数只 +1（重放未再追加），replayed=true，回执与首次相同。
    assert second["row_count"] == 1
    assert second.get("replayed") is True
    assert second["row_index"] == first["row_index"]
    assert second["revision"] == first["revision"]


def test_idempotent_conflict_different_params(client: TestClient) -> None:
    _post(client, "canvas.script.rows.append", {"graph_id": GRAPH_ID_B, "row": _valid_row()},
          opId="op-x", expectedRevision=0)
    # 同 opId 但不同参数 → 拒绝（不修改画布）。
    r = _post(client, "canvas.script.rows.append",
              {"graph_id": GRAPH_ID_B, "row": {"effect": "mono"}}, opId="op-x", expectedRevision=0)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "idempotency_conflict"


# ── 验收 3: CAS ───────────────────────────────────────────────────────────────


def test_cas_stale_revision_returns_409(client: TestClient) -> None:
    # 用真实 POST 读初始 revision。
    g0 = client.post("/api/ops/canvas.get?mode=read-write",
                     json={"params": {"graph_id": GRAPH_ID}})
    rev0 = g0.json()["revision"]
    # 先成功追加一次 → revision 变成 rev0+1。
    ok = _post(client, "canvas.script.rows.append", {"graph_id": GRAPH_ID, "row": _valid_row()},
               opId="cas-ok", expectedRevision=rev0)
    assert ok.status_code == 200, ok.text
    new_rev = ok.json()["revision"]
    assert new_rev == rev0 + 1
    # 用过期的 expectedRevision(rev0) 再写 → 409，画布未被修改。
    stale = _post(client, "canvas.script.rows.append", {"graph_id": GRAPH_ID, "row": _valid_row()},
                  opId="cas-stale", expectedRevision=rev0)
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["error"] == "revision_conflict"
    # 画布行数未变（仍然只有 1 行）。
    g1 = client.post("/api/ops/canvas.get?mode=read-write",
                    json={"params": {"graph_id": GRAPH_ID}})
    g1j = g1.json()
    assert isinstance(g1j["graph"], dict), g1j
    rows = [n for n in g1j["graph"]["nodes"] if n.get("type") == "script"][0]["rows"]
    assert len(rows) == 1


# ── 验收 4: read-only 会话写操作被拒 ───────────────────────────────────────────


def test_readonly_session_denies_write(client: TestClient) -> None:
    r = _post(client, "canvas.script.rows.append", {"graph_id": GRAPH_ID, "row": _valid_row()},
              mode="read-only")
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "scope_denied"
    # 画布不变（行数 0）。
    g = client.post("/api/ops/canvas.get?mode=read-write",
                   json={"params": {"graph_id": GRAPH_ID}})
    gj = g.json()
    assert isinstance(gj["graph"], dict)
    rows = [n for n in gj["graph"]["nodes"] if n.get("type") == "script"][0]["rows"]
    assert len(rows) == 0


# ── 验收 5: 付费闸 propose ─────────────────────────────────────────────────────


def test_propose_returns_only_proposal_id(client: TestClient) -> None:
    tasks_before = _count_tasks()
    r = _post(client, "canvas.generation.propose",
              {"graph_id": GRAPH_ID, "prompt": "生成一镜小狐狸刷牙", "rows": [0, 1]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "proposalId" in body
    assert set(body.keys()) <= {"proposalId", "graph_id", "operation"}
    # 任务表无新行（未触发生成、未调 provider）。
    tasks_after = _count_tasks()
    assert tasks_after == tasks_before


def test_propose_records_intent_not_task(client: TestClient) -> None:
    store = _get_store()
    tasks_before = asyncio.run(store.count_tasks())
    r = _post(client, "canvas.generation.propose",
              {"graph_id": GRAPH_ID, "prompt": "p", "rows": [0]})
    assert r.status_code == 200
    assert asyncio.run(store.count_tasks()) == tasks_before
    # proposal 已落库（意图记录），但任务表仍为空。
    pid = r.json()["proposalId"]
    assert asyncio.run(store.get_proposal(pid)) is not None
    assert asyncio.run(store.get_task(pid)) is None


def test_confirm_submits_via_local_stub_zero_cost(client: TestClient) -> None:
    """确认后经既有任务接口可提交（本地 stub provider，零费用）。"""
    store = _get_store()
    r = _post(client, "canvas.generation.propose",
              {"graph_id": GRAPH_ID, "prompt": "confirm me", "rows": [0]})
    pid = r.json()["proposalId"]
    c = client.post(f"/api/ops/canvas.generation.propose/confirm?mode=read-write",
                    json={"params": {"proposalId": pid}})
    assert c.status_code == 200, c.text
    body = c.json()
    assert body["status"] == "submitted"
    assert body["provider"] == "local_stub"
    assert body["cost_usd"] == 0.0
    assert asyncio.run(store.count_tasks()) == 1


# ── 验收 6: 非法 ShotSpec 行被既有校验器拒绝 ───────────────────────────────────


def test_invalid_template_rejected_by_existing_validator(client: TestClient) -> None:
    r = _post(client, "canvas.script.rows.append",
              {"graph_id": GRAPH_ID, "row": {"template": "not-a-template"}},
              opId="bad-tpl", expectedRevision=0)
    assert r.status_code == 422, r.text
    assert "装配期不可渲染" in r.text or "unknown template" in r.text


def test_invalid_transition_rejected_by_existing_validator(client: TestClient) -> None:
    r = _post(client, "canvas.script.rows.append",
              {"graph_id": GRAPH_ID, "row": {"transition_in": "not-a-transition"}},
              opId="bad-tr", expectedRevision=0)
    assert r.status_code == 422, r.text


def test_invalid_sfx_rejected_by_existing_validator(client: TestClient) -> None:
    r = _post(client, "canvas.script.rows.append",
              {"graph_id": GRAPH_ID, "row": {"sfx": [{"id": "no-such-sfx"}]}},
              opId="bad-sfx", expectedRevision=0)
    assert r.status_code == 422, r.text


def test_update_with_bad_row_rejected(client: TestClient) -> None:
    # 先追加一行合法行（revision 0→1）。
    a = _post(client, "canvas.script.rows.append", {"graph_id": GRAPH_ID, "row": _valid_row()},
              opId="upd-seed", expectedRevision=0)
    rev = a.json()["revision"]
    r = _post(client, "canvas.script.rows.update",
              {"graph_id": GRAPH_ID, "row_index": 0, "row": {"effect": "bogus-effect"}},
              opId="upd-bad", expectedRevision=rev)
    assert r.status_code == 422, r.text


# ── 其它写操作 ────────────────────────────────────────────────────────────────


def test_bind_asset_requires_cas_and_returns_bound(client: TestClient) -> None:
    r = _post(client, "canvas.node.bind_asset",
              {"graph_id": GRAPH_ID, "node_id": "n1", "asset_id": "asset-fox"},
              opId="bind-1", expectedRevision=0)
    assert r.status_code == 200, r.text
    assert "asset-fox" in r.json()["bound_assets"]
    assert r.json()["revision"] == 1


def test_remove_row(client: TestClient) -> None:
    a = _post(client, "canvas.script.rows.append", {"graph_id": GRAPH_ID_B, "row": _valid_row()},
              opId="rm-seed", expectedRevision=0)
    rev = a.json()["revision"]
    r = _post(client, "canvas.script.rows.remove", {"graph_id": GRAPH_ID_B, "row_index": 0},
              opId="rm-1", expectedRevision=rev)
    assert r.status_code == 200, r.text
    assert r.json()["row_count"] == 0


def test_asset_list_and_task_get(client: TestClient) -> None:
    r = _post(client, "asset.list", {})
    assert r.status_code == 200
    assert r.json()["count"] >= 4
    # task.get 未知 → 404，不触发生成。
    t = _post(client, "task.get", {"task_id": "missing"})
    assert t.status_code == 404


def test_asset_list_reads_existing_subject_repository() -> None:
    """asset.list 必须读既有 SubjectRepository（无 _seed_assets 也能 list）。"""
    from hevi.operations.in_memory import InMemoryStore

    dedicated = InMemoryStore()
    subject_repo = InMemorySubjectRepository(store=dedicated)
    ids = [str(uuid4()) for _ in range(3)]
    for i, asset_id in enumerate(ids):
        asyncio.run(
            subject_repo.create(
                {
                    "id": asset_id,
                    "subject_type": "character",
                    "name": f"existing-{i}",
                    "version": 1,
                }
            )
        )
    # 经 store.list_assets（同一既有 SubjectRepository）读回同一批。
    store = _get_store()
    store._subject_repo = subject_repo
    assets = asyncio.run(store.list_assets())
    got = {a["asset_id"] for a in assets}
    assert set(ids) <= got

    # 再经 /api/ops/asset.list 读回同一批（走真实 HTTP 端点，注入同一 store）。
    from hevi.api.routers import ops as ops_router

    app.dependency_overrides[get_current_user] = lambda: USER
    original_get_store = ops_router._get_store
    ops_router._get_store = lambda: store
    try:
        c = TestClient(app)
        resp = c.post("/api/ops/asset.list?mode=read-write", json={"params": {}})
        assert resp.status_code == 200, resp.text
        http_ids = {a["asset_id"] for a in resp.json()["assets"]}
        assert set(ids) <= http_ids
    finally:
        ops_router._get_store = original_get_store
        app.dependency_overrides.clear()
        clear_idempotency()
