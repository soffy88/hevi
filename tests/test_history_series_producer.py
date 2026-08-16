"""P2 自动产线测试（queue/next/produce + 幂等 + 全册产完哨兵）。"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from hevi.history_series.series_producer import (
    PIPELINE_TYPE,
    LessonInfo,
    next_lesson,
    produce_lesson,
)


def _mock_mneme(monkeypatch, lessons: list[dict]):
    """注入 mneme 课节列表（dict-list，模拟 asyncpg Row）。"""
    async def _connect(db_url):
        class M:
            async def fetch(self, query, *args):
                return lessons
            async def close(self): pass
        return M()
    monkeypatch.setattr("asyncpg.connect", _connect)


def _mock_hevi_runs(monkeypatch, runs: list[dict]):
    """注入 hevi TaskRun 查询结果。"""
    @dataclass
    class FakeRun:
        pipeline_type: str = PIPELINE_TYPE
        status: str = "completed"
        task_id: str = "fake-id"
        state_json: dict | None = None
    fake_runs = [FakeRun(status=r["status"], task_id=r.get("task_id", "x"),
                         state_json=r.get("state_json")) for r in runs]

    def _session(*args, **kw):
        class S:
            def exec(self, stmt):
                class R:
                    def all(self): return fake_runs
                return R()
            def add(self, row): pass
            def commit(self): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return S()
    monkeypatch.setattr("sqlmodel.Session", _session)


@pytest.mark.asyncio
async def test_next_lesson_returns_first_when_none_produced(monkeypatch):
    _mock_mneme(monkeypatch, [
        {"display_order": 1, "name": "北京人", "ku_cnt": 5},
        {"display_order": 2, "name": "农耕生活", "ku_cnt": 3},
    ])
    _mock_hevi_runs(monkeypatch, [])
    result = await next_lesson()
    assert result is not None and result.order == 1


@pytest.mark.asyncio
async def test_next_lesson_skips_completed(monkeypatch):
    _mock_mneme(monkeypatch, [
        {"display_order": 1, "name": "第1课", "ku_cnt": 5},
        {"display_order": 2, "name": "第2课", "ku_cnt": 3},
    ])
    _mock_hevi_runs(monkeypatch, [
        {"status": "completed", "state_json": {"lesson_order": 1}},
    ])
    result = await next_lesson()
    assert result is not None and result.order == 2


def test_lesson_info_source_name():
    info = LessonInfo(order=3, title="远古的传说")
    assert "中国历史七年级上册·第3课·远古的传说" in info.source_name


@pytest.mark.asyncio
async def test_produce_lesson_idempotent(monkeypatch):
    _mock_hevi_runs(monkeypatch, [
        {"status": "completed", "task_id": "existing-123",
         "state_json": {"lesson_order": 1}},
    ])
    monkeypatch.setattr("hevi.core.workspace.new_task_id", lambda: "new")
    task_id, req = await produce_lesson(LessonInfo(order=1, title="北京人"))
    assert task_id == "existing-123"
    assert req == {}
