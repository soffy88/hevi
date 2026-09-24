"""Freezone API 认证 fail-closed + USER_A/USER_B 租户隔离对抗测试。"""

from __future__ import annotations

import uuid
from typing import Any


async def _register(client: Any) -> dict[str, str]:
    email = f"fz_{uuid.uuid4().hex[:8]}@example.com"
    await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": "FZ"},
    )
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": "password123"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


_GRAPH_BODY = {
    "nodes": [{"id": "n1", "kind": "image", "params": {"prompt": "雨夜"}, "inputs": []}]
}


async def test_freezone_requires_auth(client: Any) -> None:
    """Anonymous → 401/403 on every freezone endpoint."""
    anon = [
        await client.post("/api/freezone/graphs", json=_GRAPH_BODY),
        await client.get("/api/freezone/graphs/fzg_x"),
        await client.post("/api/freezone/graphs/fzg_x/run"),
        await client.get("/api/freezone/candidates"),
        await client.post(
            "/api/freezone/candidates/cand_x/promote", json={"target": "series:1"}
        ),
        await client.post("/api/freezone/candidates/cand_x/reject"),
    ]
    for resp in anon:
        assert resp.status_code in (401, 403), resp.status_code


async def test_freezone_cross_user_graph_404(client: Any) -> None:
    """USER_A graph: USER_B get/run → 404; list does not leak."""
    a = await _register(client)
    b = await _register(client)
    created = await client.post("/api/freezone/graphs", json=_GRAPH_BODY, headers=a)
    assert created.status_code == 200
    gid = created.json()["graph_id"]

    assert (await client.get(f"/api/freezone/graphs/{gid}", headers=a)).status_code == 200
    assert (await client.get(f"/api/freezone/graphs/{gid}", headers=b)).status_code == 404
    assert (await client.post(f"/api/freezone/graphs/{gid}/run", headers=b)).status_code == 404
    # A can still run own graph (fail-closed generator → node error, not auth leak)
    run = await client.post(f"/api/freezone/graphs/{gid}/run", headers=a)
    assert run.status_code == 200


async def test_freezone_cross_user_candidate_isolation(client: Any) -> None:
    """USER_A candidate: USER_B list empty; promote/reject → 404."""
    from hevi.api.routers.freezone import _freezone

    async def _echo(node: Any, upstream: Any) -> Any:
        return {"kind": node.kind, "ok": True}

    _freezone.register("image", _echo)
    try:
        a = await _register(client)
        b = await _register(client)
        created = await client.post("/api/freezone/graphs", json=_GRAPH_BODY, headers=a)
        gid = created.json()["graph_id"]
        run = await client.post(f"/api/freezone/graphs/{gid}/run", headers=a)
        assert run.status_code == 200
        cands = run.json()["candidates"]
        assert len(cands) == 1
        cid = cands[0]

        # provenance on candidate
        listed_a = await client.get("/api/freezone/candidates", headers=a)
        assert listed_a.status_code == 200
        rows = listed_a.json()
        assert any(r["id"] == cid for r in rows)
        assert all(r["user_id"] for r in rows)
        assert all(r["graph_id"] == gid for r in rows)

        # B sees no candidates
        listed_b = await client.get("/api/freezone/candidates", headers=b)
        assert listed_b.status_code == 200
        assert listed_b.json() == []

        # B cannot promote/reject A's candidate
        promo = await client.post(
            f"/api/freezone/candidates/{cid}/promote",
            json={"target": "series:1:episode:1:shot:1"},
            headers=b,
        )
        assert promo.status_code == 404
        rej = await client.post(f"/api/freezone/candidates/{cid}/reject", headers=b)
        assert rej.status_code == 404

        # A can promote own candidate
        ok = await client.post(
            f"/api/freezone/candidates/{cid}/promote",
            json={"target": "series:1:episode:1:shot:1"},
            headers=a,
        )
        assert ok.status_code == 200
    finally:
        _freezone.generators.pop("image", None)
