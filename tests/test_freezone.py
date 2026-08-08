"""Freezone 无限画布测试:节点图 DAG 执行、失败隔离、候选池提升。

对标 DramaClaw Freezone(无限画布)的 hevi 侧内化:
节点画布自由探索 → 候选 → 提升回主线。纯逻辑测试(不依赖生成服务)。
"""

from __future__ import annotations

import pytest

from hevi.freezone import (
    CANDIDATE,
    PROMOTED,
    FreezoneGraph,
    FreezoneService,
    GraphCycleError,
    NodeSpec,
)


async def _echo_generator(node, upstream):
    return {"kind": node.kind, "prompt": node.params.get("prompt"),
            "upstream": list(upstream)}


@pytest.mark.asyncio
async def test_topo_execution_with_upstream():
    """链式依赖: n1 → n2, n2 拿到 n1 输出。"""
    g = FreezoneGraph([
        NodeSpec("n1", "image", {"prompt": "雨夜"}),
        NodeSpec("n2", "video", {"prompt": "追逐"}, ["n1"]),
    ])
    svc = FreezoneService(generators={"image": _echo_generator,
                                      "video": _echo_generator})
    run = await svc.run_graph(g)
    assert run.ok_count == 2
    n2 = run.results["n2"].output
    assert n2["upstream"] == ["n1"]  # 上游输出已传递


@pytest.mark.asyncio
async def test_failure_isolation():
    """某节点失败不影响兄弟节点。"""
    async def boom(node, upstream):
        raise RuntimeError("生成失败")

    g = FreezoneGraph([
        NodeSpec("a", "image", {}),
        NodeSpec("b", "video", {}),
    ])
    svc = FreezoneService(generators={"image": boom, "video": _echo_generator})
    run = await svc.run_graph(g)
    assert run.results["a"].ok is False
    assert "生成失败" in run.results["a"].error
    assert run.results["b"].ok is True


def test_cycle_detection():
    """环 → GraphCycleError (topo_order 时触发)。"""
    g = FreezoneGraph([
        NodeSpec("a", "image", {}, ["b"]),
        NodeSpec("b", "video", {}, ["a"]),
    ])
    with pytest.raises(GraphCycleError):
        g.topo_order()


def test_unknown_dependency():
    with pytest.raises(GraphCycleError):
        FreezoneGraph([NodeSpec("a", "image", {}, ["ghost"])])


@pytest.mark.asyncio
async def test_candidate_pool_promote():
    """候选收集 → 提升回主线 → 状态机。"""
    g = FreezoneGraph([NodeSpec("n1", "image", {"prompt": "角色"})])
    svc = FreezoneService(generators={"image": _echo_generator})
    run = await svc.run_graph(g, score_fn=lambda nid, out: 0.8)
    assert len(run.candidate_ids) == 1
    cid = run.candidate_ids[0]
    cand = svc.pool.get(cid)
    assert cand is not None and cand.status == CANDIDATE
    assert cand.score == 0.8
    assert svc.promote(cid, "series:1:episode:3:shot:5") is True
    assert svc.pool.get(cid).status == PROMOTED
    # 重复提升被拒
    assert svc.promote(cid, "x") is False


@pytest.mark.asyncio
async def test_candidate_reject_and_list_filter():
    g = FreezoneGraph([NodeSpec("n1", "image", {})])
    svc = FreezoneService()
    run = await svc.run_graph(g)
    cid = run.candidate_ids[0]
    assert svc.reject(cid) is True
    assert svc.pool.list(status=CANDIDATE) == []
    assert len(svc.pool.list(status="rejected")) == 1
