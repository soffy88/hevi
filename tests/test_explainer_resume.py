"""断点续传:调研缓存落盘/读取 + 装配入口防爆解析(隐患点 A/B)。

覆盖:
- research_cache 原子落盘/读取/会话 id 清洗
- 调研接口响应前落盘 + GET 缓存恢复(不重跑研究)
- 装配接口对双重序列化 body 的强制防爆恢复(『str』 object has no
  attribute 'get' 从根上灭绝)
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import BackgroundTasks, HTTPException

from hevi.api.routers import explainer as router
from hevi.explainer.contracts import (
    ExplainerResearchRequest,
    ExplainerScriptDraft,
    ExplainerServiceResult,
    HookNode,
    ResearchFact,
)
from hevi.explainer.props import deep_unpack_json, ensure_dict
from hevi.explainer.research_cache import (
    ensure_clean_session_id,
    load_research_cache,
    save_research_cache,
)

_USER = {"id": str(uuid.uuid4())}


def _result() -> ExplainerServiceResult:
    hook = HookNode(
        hook_id="H1",
        title="BBGKY 突破口",
        narrative_function="opening_suspense",
        suggested_placement_s=0,
        text="为什么 70 年的 BBGKY 方程没被突破?",
        associated_concepts=["BBGKY 方程"],
    )
    script = ExplainerScriptDraft(
        id="s1",
        title="突破视角",
        viewpoint="从重碰撞到调和分析",
        hook=hook.text,
        facts=[],
        outline=[],
        cues=[
            {
                "text": "为什么 70 年的 BBGKY 方程没被突破?",
                "visual_type": "voiceover",
                "time_estimate_s": 6.0,
            }
        ],
    )
    return ExplainerServiceResult(
        facts=[
            ResearchFact(
                claim="邓煜用拓扑树与调和分析突破 BBGKY 方程", confidence=0.9, source="论文"
            )
        ],
        research_summary="BBGKY 方程长期未被突破,邓煜用拓扑树/重碰撞/调和分析打开缺口。",
        hooks=[hook],
        scripts=[script],
        provider="test",
    )


# ── research_cache 落盘/读取 ─────────────────────────────────────────────


def test_cache_save_and_load_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("EXPLAINER_CACHE_DIR", str(tmp_path / "cache"))
    payload = {"topic_or_url": "邓煜突破 BBGKY 方程", "hooks": [{"hook_id": "H1"}]}
    save_research_cache("abc-123", payload)
    assert (tmp_path / "cache" / "abc-123.json").exists()
    assert load_research_cache("abc-123") == payload


def test_cache_save_is_atomic_and_overwrites(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("EXPLAINER_CACHE_DIR", str(tmp_path / "cache"))
    save_research_cache("abc-123", {"version": 1})
    save_research_cache("abc-123", {"version": 2})
    assert load_research_cache("abc-123") == {"version": 2}
    assert list((tmp_path / "cache").glob("*.tmp")) == []  # 无残留临时文件


def test_cache_load_missing_or_corrupt_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    directory = tmp_path / "cache"
    monkeypatch.setenv("EXPLAINER_CACHE_DIR", str(directory))
    assert load_research_cache("missing-id") is None
    directory.mkdir(parents=True)
    (directory / "bad.json").write_text("{not json", encoding="utf-8")
    assert load_research_cache("bad") is None


def test_cache_dir_cleans_unsafe_session_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("EXPLAINER_CACHE_DIR", str(tmp_path / "cache"))
    # 目录穿越等脏 id 会被清洗成新 uuid,绝不落进文件路径。
    safe = ensure_clean_session_id("../../etc/passwd")
    assert safe != "../../etc/passwd"
    assert safe == ensure_clean_session_id(safe)
    save_research_cache("../../etc/passwd", {"x": 1})
    files = list((tmp_path / "cache").glob("*.json"))
    assert len(files) == 1
    # 落盘文件名是清洗后的合法 uuid(每次调用重新生成),绝不是脏路径。
    assert files[0].stem == ensure_clean_session_id(files[0].stem)
    assert files[0].name != "passwd.json"


# ── 调研接口响应前落盘 + GET 恢复 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_research_endpoint_persists_cache_and_returns_session_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("EXPLAINER_CACHE_DIR", str(tmp_path / "cache"))

    async def fake_research(_body):
        return _result()

    monkeypatch.setattr(router, "research_and_generate", fake_research)
    body = ExplainerResearchRequest(topic_or_url="邓煜突破 BBGKY 方程")
    response = await router.research_explainer(body, _USER)
    assert response.session_id
    assert response.hooks[0].hook_id == "H1"
    # 落盘完成:磁盘上有缓存,且能凭 session_id 原样读回。
    cached = load_research_cache(response.session_id)
    assert cached is not None
    assert cached["topic_or_url"] == "邓煜突破 BBGKY 方程"
    assert cached["hooks"][0]["hook_id"] == "H1"


@pytest.mark.asyncio
async def test_research_cache_restore_endpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    monkeypatch.setenv("EXPLAINER_CACHE_DIR", str(tmp_path / "cache"))

    async def fake_research(_body):
        return _result()

    monkeypatch.setattr(router, "research_and_generate", fake_research)
    first = await router.research_explainer(
        ExplainerResearchRequest(topic_or_url="邓煜突破 BBGKY 方程"), _USER
    )
    restored = await router.get_research_cache(first.session_id, _USER)
    assert restored.session_id == first.session_id
    assert restored.scripts[0].title == "突破视角"
    # 未知 session → 404
    with pytest.raises(HTTPException) as exc:
        await router.get_research_cache("no-such-session", _USER)
    assert exc.value.status_code == 404


# ── 隐患点 A:装配入参双重序列化强制防爆恢复 ──────────────────────────────


def _assemble_payload() -> dict:
    return {
        "topic_or_url": "邓煜突破 BBGKY 方程",
        "selected_hook": "为什么 70 年的 BBGKY 方程没被突破?",
        "selected_hooks": ["为什么 70 年的 BBGKY 方程没被突破?"],
        "hook_combination": "chain",
        "final_script_cues": [
            {
                "time_range": "00:00-00:06",
                "visual_type": "voiceover",
                "text": "开场钩子旁白",
                "visual_config": {"chart_data": {"values": [1, 2]}},
            }
        ],
        "enable_remotion_code_render": True,
        "enable_circle_avatar_mask": True,
        "enable_browser_broll": True,
        "aspect_ratio": "9:16",
    }


def test_parse_assemble_payload_recovers_double_serialized_body() -> None:
    # 前端把整个 body 双重序列化:final_script_cues 变成一长串 str。
    raw = json.dumps(json.dumps(_assemble_payload(), ensure_ascii=False), ensure_ascii=False)
    body = router._parse_assemble_payload(json.loads(raw))
    assert len(body.final_script_cues) == 1
    assert body.final_script_cues[0].text == "开场钩子旁白"


def test_parse_assemble_payload_recovers_stringified_visual_config() -> None:
    # cue 里的 visual_config / chart_data 被序列化成 JSON 字符串。
    payload = _assemble_payload()
    payload["final_script_cues"][0]["visual_config"] = json.dumps(
        {"chart_data": '{"values": [1, 2]}'}, ensure_ascii=False
    )
    body = router._parse_assemble_payload(payload)
    config = body.final_script_cues[0].visual_config
    assert config["chart_data"] == {"values": [1, 2]}


def test_parse_assemble_payload_rejects_garbage_cleanly() -> None:
    with pytest.raises(HTTPException) as exc:
        router._parse_assemble_payload({"final_script_cues": "not-a-list"})
    assert exc.value.status_code == 422


def test_deep_unpack_json_round_trip_is_idempotent() -> None:
    payload = _assemble_payload()
    once = deep_unpack_json(json.dumps(payload, ensure_ascii=False))
    twice = deep_unpack_json(json.dumps(once, ensure_ascii=False))
    assert twice == once


@pytest.mark.asyncio
async def test_assemble_endpoint_recovers_double_serialized_body_and_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """整条 body 被双重序列化时,装配接口仍能恢复 cue 并正常派发任务。"""
    from fastapi import Request

    captured = {}

    async def fake_create_projection(_repo, **kwargs):
        captured["projection"] = kwargs
        return {"id": str(uuid.uuid4())}

    class _StubPool:
        pass

    class _StubRepo:
        def __init__(self):
            self.pool = _StubPool()
            self.created = []

        async def create(self, data):
            self.created.append(data)
            return data

        async def get(self, run_id):
            return None

    monkeypatch.setattr(router, "create_projection", fake_create_projection)
    repo = _StubRepo()

    async def receive() -> dict:
        raw = json.dumps(json.dumps(_assemble_payload(), ensure_ascii=False), ensure_ascii=False)
        return {"type": "http.request", "body": raw.encode(), "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/explainer/assemble",
        "headers": [],
        "query_string": b"",
        "client": ("test", 123),
        "server": ("test", 80),
        "scheme": "http",
        "root_path": "",
        "http_version": "1.1",
        "app": None,
    }
    background = BackgroundTasks()
    accepted = await router.assemble_explainer(
        Request(scope, receive),
        background,
        _USER,
        repo,
    )
    assert accepted.status == "processing"
    assert uuid.UUID(accepted.task_id)  # 合法 uuid
    assert len(background.tasks) == 1  # 后台装配任务已排队
    stored = repo.created[0]["input_json"]
    assert stored["final_script_cues"][0]["text"] == "开场钩子旁白"
    assert stored["final_script_cues"][0]["visual_config"]["chart_data"] == {
        "values": [1, 2]
    }


# ── 隐患点 B:ensure_dict 彻底解构 ────────────────────────────────────────


def test_ensure_dict_unpacks_model_and_json_string() -> None:
    hook = HookNode(
        hook_id="H1",
        title="t",
        narrative_function="opening_suspense",
        suggested_placement_s=0,
        text="钩子",
        associated_concepts=[],
    )
    assert ensure_dict(hook)["hook_id"] == "H1"
    assert ensure_dict('{"a": 1}') == {"a": 1}
    assert ensure_dict("plain") == "plain"
    assert ensure_dict(None) is None
