"""Freezone fail-closed: 未注册 kind 不落 stub 候选。"""

from __future__ import annotations

import pytest

from hevi.freezone import FreezoneGraph, FreezoneService, NodeSpec, UnknownGeneratorError


async def test_unregistered_kind_fails_closed_no_candidate() -> None:
    """No generator for kind → node fails, zero candidates (no stub success)."""
    g = FreezoneGraph([NodeSpec("n1", "image", {"prompt": "x"})])
    svc = FreezoneService()
    run = await svc.run_graph(g, user_id="u1")
    assert run.ok_count == 0
    assert run.results["n1"].ok is False
    assert "no generator registered" in run.results["n1"].error
    assert run.candidate_ids == []
    assert svc.pool.list(user_id="u1") == []


async def test_generator_for_raises_unknown_kind() -> None:
    svc = FreezoneService()
    with pytest.raises(UnknownGeneratorError):
        svc._generator_for(NodeSpec("n1", "video", {}))


async def test_non_callable_generator_override_fails_closed() -> None:
    g = FreezoneGraph([NodeSpec("n1", "image", {"_generator": "not-callable"})])
    svc = FreezoneService()
    run = await svc.run_graph(g, user_id="u1")
    assert run.results["n1"].ok is False
    assert "must be callable" in run.results["n1"].error
    assert run.candidate_ids == []
