"""FREEZONE_RESTART_RECOVERY: 图 + 候选(含 provenance)跨进程重启恢复。"""

from __future__ import annotations

from pathlib import Path

from hevi.freezone import (
    CANDIDATE,
    PROMOTED,
    FreezoneGraph,
    FreezoneService,
    FreezoneStateStore,
    NodeSpec,
)


async def _echo(node: NodeSpec, upstream: dict) -> dict:
    return {"kind": node.kind, "prompt": node.params.get("prompt")}


async def test_freezone_restart_recovery(tmp_path: Path) -> None:
    path = tmp_path / "fz_state.json"
    store = FreezoneStateStore(path)

    svc1 = FreezoneService(generators={"image": _echo}, store=store)
    graph = FreezoneGraph([NodeSpec("n1", "image", {"prompt": "角色"})])
    gid = svc1.create_graph(graph, user_id="user_a")
    run = await svc1.run_graph(graph, user_id="user_a", graph_id=gid)
    assert len(run.candidate_ids) == 1
    cid = run.candidate_ids[0]
    assert svc1.promote(cid, "series:1:episode:1:shot:1", user_id="user_a") is True

    # Simulate process restart: new service hydrates from same store
    svc2 = FreezoneService(store=store)
    recovered = svc2.get_owned_graph(gid, user_id="user_a")
    assert recovered is not None
    assert recovered.to_dict() == graph.to_dict()
    # Cross-user still isolated after restart
    assert svc2.get_owned_graph(gid, user_id="user_b") is None

    cand = svc2.pool.get(cid)
    assert cand is not None
    assert cand.user_id == "user_a"
    assert cand.graph_id == gid
    assert cand.status == PROMOTED
    assert cand.promote_target == "series:1:episode:1:shot:1"
    # provenance survives
    assert cand.run_id == run.run_id
    # list is owner-scoped
    assert [c.id for c in svc2.pool.list(user_id="user_a")] == [cid]
    assert svc2.pool.list(user_id="user_b") == []


async def test_freezone_restart_preserves_candidate_status(tmp_path: Path) -> None:
    path = tmp_path / "fz2.json"
    store = FreezoneStateStore(path)
    svc1 = FreezoneService(generators={"image": _echo}, store=store)
    g = FreezoneGraph([NodeSpec("n1", "image", {})])
    run = await svc1.run_graph(g, user_id="u", graph_id="g1")
    cid = run.candidate_ids[0]
    assert svc1.reject(cid, user_id="u") is True

    svc2 = FreezoneService(store=store)
    cand = svc2.pool.get(cid)
    assert cand is not None
    assert cand.status == "rejected"
    # rejected cannot be promoted again after restart
    assert svc2.promote(cid, "x", user_id="u") is False
    assert svc2.pool.get(cid).status == "rejected"
    # empty store path that does not exist yet
    fresh = FreezoneStateStore(tmp_path / "missing.json")
    svc3 = FreezoneService(store=fresh)
    assert svc3.pool.list(user_id="u") == []
    assert CANDIDATE == "candidate"
