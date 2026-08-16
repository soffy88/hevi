"""Round 3f(运行时接线)测试: 端点直调 + 返工 hints 自动推导。"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from PIL import Image

from hevi.api.routers import embrace_runtime as er

_USER = {"id": str(uuid.uuid4())}


def _png_bytes(color: tuple[int, int, int] = (200, 60, 60)) -> bytes:
    import io

    buf = io.BytesIO()
    Image.new("RGB", (24, 16), color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeFile:
    def __init__(self, data: bytes, filename: str = "ref.png") -> None:
        self._data = data
        self.filename = filename

    async def read(self) -> bytes:
        return self._data


# ---- chat 端点 ----

def test_chat_endpoint_status():
    res = __import__("asyncio").run(
        er.chat(
            type("R", (), {"project_id": "p1", "message": "进度如何?", "failures": None})(),
            _USER,
        )
    )
    assert res["intent"] == "status"
    assert "进度" in res["reply"]


def test_chat_endpoint_empty_rejected():
    with pytest.raises(HTTPException):
        __import__("asyncio").run(
            er.chat(type("R", (), {"project_id": " ", "message": "hi", "failures": None})(), _USER)
        )


def test_chat_state_endpoint():
    __import__("asyncio").run(
        er.chat(
            type("R", (), {"project_id": "p2", "message": "修复失败的镜头", "failures": None})(),
            _USER,
        )
    )
    state = __import__("asyncio").run(er.chat_state("p2", _USER))
    assert state["turn_count"] >= 1
    assert state["last_intent"] == "repair"


# ---- 候选提升端点 ----

def test_candidate_flow():
    asyncio = __import__("asyncio")
    # 登记
    asyncio.run(
        er.add_candidate(
            "p3",
            type("C", (), {
                "candidate_id": "c1", "kind": "character", "name": "主角",
                "source": "freezone", "score": 0.9, "score_note": "", "payload": {},
            })(),
            _USER,
        )
    )
    # 提升
    res = asyncio.run(
        er.decide_candidate(
            "p3", type("P", (), {"candidate_id": "c1", "action": "promote", "reason": ""})(), _USER
        )
    )
    assert res["promoted"]
    # 状态
    state = asyncio.run(er.promotion_state("p3", _USER))
    assert len(state["locked"]) == 1
    # 重复提升 → 409
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            er.decide_candidate(
                "p3",
                type("P", (), {"candidate_id": "c1", "action": "promote", "reason": ""})(),
                _USER
            )
        )
    assert exc.value.status_code == 409


def test_reject_requires_reason():
    with pytest.raises(HTTPException) as exc:
        __import__("asyncio").run(
            er.decide_candidate(
                "p4",
                type("P", (), {"candidate_id": "x", "action": "reject", "reason": ""})(),
                _USER,
            )
        )
    assert exc.value.status_code == 422


def test_add_candidate_bad_kind():
    with pytest.raises(HTTPException) as exc:
        __import__("asyncio").run(
            er.add_candidate(
                "p5",
                type("C", (), {
                    "candidate_id": "c1", "kind": "nope", "name": "x",
                    "source": "gen", "score": 0, "score_note": "", "payload": {},
                })(),
                _USER,
            )
        )
    assert exc.value.status_code == 422


# ---- 修复计划端点 ----

def test_repair_plan_endpoint():
    res = __import__("asyncio").run(
        er.repair_plan_endpoint(
            type("R", (), {
                "failures": [{"shot_id": "s1", "diagnosis": "参考图角色错配"}],
                "budget_limit": 3,
                "episode_num": 1,
            })(),
            _USER,
        )
    )
    assert res["plan"]["actions"][0]["agent"] == "character_fixer"
    assert "decision" in res


def test_repair_plan_empty_rejected():
    with pytest.raises(HTTPException) as exc:
        __import__("asyncio").run(
            er.repair_plan_endpoint(
                type("R", (), {"failures": [], "budget_limit": 3, "episode_num": 1})(), _USER
            )
        )
    assert exc.value.status_code == 422


# ---- 风格画像端点 ----

def test_style_analyze_endpoint():
    res = __import__("asyncio").run(
        er.style_analyze_endpoint(_USER, _FakeFile(_png_bytes()))
    )
    assert res["palette"]
    assert res["dominant_color"].startswith("#")
    assert res["warmth"] > 0


def test_style_analyze_empty_rejected():
    with pytest.raises(HTTPException):
        __import__("asyncio").run(
            er.style_analyze_endpoint(_USER, _FakeFile(b""))
        )


# ---- 草图编辑端点 ----

def test_sketch_edit_endpoint():
    ops_json = json.dumps([
        {"op": "crop", "params": {"box": [0, 0, 12, 8]}},
        {"op": "reframe", "params": {"width": 32, "height": 32}},
    ])
    res = __import__("asyncio").run(
        er.sketch_edit_endpoint(
            _USER, _FakeFile(_png_bytes((10, 10, 200)), "sketch.png"), ops_json
        )
    )
    assert "crop" in res["applied"] and "reframe" in res["applied"]


def test_sketch_edit_bad_ops_json():
    with pytest.raises(HTTPException) as exc:
        __import__("asyncio").run(
            er.sketch_edit_endpoint(
                _USER, _FakeFile(_png_bytes()), "{not json"
            )
        )
    assert exc.value.status_code == 422


# ---- 返工 hints 自动推导(regenerate 接线)----

def test_hints_from_failures():
    from hevi.director.repair_agents import hints_from_failures

    shots = [
        {
            "shot_index": 1,
            "selection_json": {"diagnosis_category": "参考图角色错配", "retry_count": 1},
        },
        {
            "shot_index": 2,
            "selection_json": {"diagnosis_category": "光照", "retry_count": 1},
        },
        {"shot_index": 3, "selection_json": {"retry_count": 1}},  # 无诊断
    ]
    hints = hints_from_failures(shots, [1, 2, 3])
    assert hints[1]  # 角色错配 → 有指令
    assert hints[2]
    assert 3 in hints  # 无诊断 → 通用回退(plan_repair 未知诊断出 content_rewriter 指令)
    assert len(hints) <= 3


def test_regenerate_endpoint_derives_hints():
    """regenerate 未显式给 hints → 端点自动推导(修复 agent)。"""
    from hevi.api.routers import tasks as tasks_mod

    svc = AsyncMock()
    svc.repository.get_task.return_value = {"user_id": str(_USER["id"]), "status": "completed"}
    svc.repository.get_shots.return_value = [
        {"shot_index": 1, "selection_json": {"diagnosis_category": "光照", "retry_count": 0}}
    ]
    bg = BackgroundTasks()

    res = __import__("asyncio").run(
        tasks_mod.regenerate_task_shots(
            uuid.uuid4(),
            type("B", (), {"shot_ids": [1], "hints": None})(),
            _USER,
            svc,
            bg,
        )
    )
    # 后台任务被正确调度,且 hints 已推导(非 None)
    task = bg.tasks[-1]
    assert task.func is svc.regenerate_task_shots
    assert task.kwargs["shot_ids"] == [1]
    assert task.kwargs["hints"] == {1: "按诊断类别调整光照描述,不动运镜/动作字段"}
    assert res  # 序列化任务返回
