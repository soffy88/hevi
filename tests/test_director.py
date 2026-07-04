"""L4 导演层测试 —— Producer / Director / Editor(设计 §3 L4)。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from oprim._hevi_types import CanvasNode

from hevi.director import ProducerPlan, build_canvas_graph, produce, review


def _plan(provider: str = "wan_local") -> ProducerPlan:
    return ProducerPlan(
        topic="a fox in snow",
        duration_archetype="1-5min",
        video_provider=provider,
        audio_provider="vibevoice",
        style="cinematic",
        num_characters=1,
        estimated_usd=0.0,
        budget_usd=None,
        budget_ok=True,
        feasible=True,
    )


# ── Producer ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_producer_auto_routes_and_budget_ok():
    with (
        patch(
            "hevi.cost.router.route_video_provider",
            new_callable=AsyncMock,
            return_value="wan_cloud",
        ),
        patch(
            "hevi.director.producer.estimate_cost",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(total_usd=1.2),
        ),
    ):
        plan = await produce(
            topic="AI history", duration_archetype="1-5min", video_provider="auto", budget_usd=2.0
        )
    assert plan.video_provider == "wan_cloud"  # 成本路由选中
    assert plan.estimated_usd == 1.2
    assert plan.budget_ok is True and plan.feasible is True
    assert any("auto-routed" in n for n in plan.notes)


@pytest.mark.asyncio
async def test_producer_budget_exceeded_infeasible():
    with patch(
        "hevi.director.producer.estimate_cost",
        new_callable=AsyncMock,
        return_value=SimpleNamespace(total_usd=5.0),
    ):
        plan = await produce(
            topic="x", duration_archetype="1-5min", video_provider="wan_cloud", budget_usd=2.0
        )
    assert plan.budget_ok is False and plan.feasible is False
    assert any("预算不足" in n for n in plan.notes)


# ── Director ─────────────────────────────────────────────────────────────────


def test_director_builds_graph_structure():
    g = build_canvas_graph(plan=_plan(), shot_prompts=["a fox runs", "a fox sleeps"])
    assert len(g["nodes"]) == 3  # 1 text + 2 video
    assert len(g["edges"]) == 2
    vids = [n for n in g["nodes"] if n["node_type"] == "video"]
    assert vids[0]["config"]["prompt"] == "a fox runs"
    assert all(n["config"]["provider"] == "wan_local" for n in vids)
    assert all(n["config"]["mode"] == "t2v" for n in vids)  # 无角色锁 → t2v


def test_director_character_lock_uses_i2v():
    g = build_canvas_graph(
        plan=_plan(), shot_prompts=["hero fights"], character_reference="/ref/hero.png"
    )
    vid = next(n for n in g["nodes"] if n["node_type"] == "video")
    assert vid["config"]["mode"] == "i2v"
    assert vid["config"]["reference_image"] == "/ref/hero.png"


def test_director_empty_prompts_raises():
    with pytest.raises(ValueError):
        build_canvas_graph(plan=_plan(), shot_prompts=[])


@pytest.mark.asyncio
async def test_director_graph_executes_via_canvas():
    """§7-7 + L4:Director 产的 video 节点交 canvas executor → 走真实生成(可执行图)。"""
    from hevi.canvas.node_mapper import create_node_executor

    g = build_canvas_graph(plan=_plan(), shot_prompts=["a fox runs"])
    vid_dict = next(n for n in g["nodes"] if n["node_type"] == "video")
    vid_node = CanvasNode.model_validate(vid_dict)
    executor = create_node_executor()
    with patch(
        "hevi.video.kernel_service.generate_clip",
        new_callable=AsyncMock,
        return_value=Path("output/canvas/x.mp4"),
    ) as gen:
        res = await executor(vid_node, {"topic": {"type": "text", "output": "a fox in snow"}})
    gen.assert_awaited_once()
    assert res["type"] == "video" and res["output"] == "output/canvas/x.mp4"
    assert gen.call_args.kwargs["prompt"] == "a fox runs"  # 用节点 config 的 prompt


# ── Editor ───────────────────────────────────────────────────────────────────


def test_editor_flags_low_consistency_and_failed_shots():
    shots = [
        {"index": 0, "passed": True, "consistency_score": 0.95},
        {"index": 1, "passed": True, "consistency_score": 0.60},  # 偏低
        {"index": 2, "passed": False, "consistency_score": 0.90},  # 未过
    ]
    d = review(quality={"passed": True}, shots=shots, consistency_floor=0.75)
    assert d.regenerate_shot_ids == [1, 2]
    assert d.deliver is False
    assert 1 in d.hints and 2 in d.hints


def test_editor_delivers_when_all_good():
    d = review(
        quality={"passed": True}, shots=[{"index": 0, "passed": True, "consistency_score": 0.9}]
    )
    assert d.deliver is True
    assert d.regenerate_shot_ids == []


def test_editor_no_deliver_when_quality_failed():
    d = review(
        quality={"passed": False, "violations": ["时长偏离"]},
        shots=[{"index": 0, "passed": True, "consistency_score": 0.9}],
    )
    assert d.deliver is False
    assert any("体检不过" in r for r in d.reasons)


# ── 全自动导演回路 ────────────────────────────────────────────────────────────


class _FakeRepo:
    def __init__(self, task, shots_by_round):
        self._task = task
        self._shots_by_round = shots_by_round  # list of get_shots() 返回(逐轮)
        self.round = 0

    async def get_task(self, task_id):
        return self._task

    async def get_shots(self, task_id):
        return self._shots_by_round[min(self.round, len(self._shots_by_round) - 1)]


class _FakeTaskService:
    def __init__(self, repo):
        self.repository = repo
        self.run_called = 0
        self.regen_calls = []

    async def run_task(self, task_id):
        self.run_called += 1
        return {"status": "completed"}

    async def regenerate_task_shots(self, task_id, *, shot_ids, hints=None):
        self.regen_calls.append(shot_ids)
        self.repository.round += 1  # 下一轮 get_shots 返回改善后的
        # 返回 Editor 格式的 shots(全 index 都 passed 高分,模拟返工成功)
        return {"shots": [{"index": i, "passed": True, "consistency_score": 0.95} for i in (0, 1)]}


@pytest.mark.asyncio
async def test_director_loop_reworks_then_delivers():
    """L4 全自动:首轮有镜头一致性偏低 → 定向返工 → 再评审通过 → 交付。"""
    from hevi.director import run_director_loop

    task = {"config_json": {"quality": {"passed": True}}}
    # round0:index1 分低 → 需返工;round1(regen 后不再读 DB,用 regen 返回)
    repo = _FakeRepo(
        task,
        shots_by_round=[
            [
                {"shot_index": 0, "selection_json": {"passed": True, "consistency_score": 0.95}},
                {"shot_index": 1, "selection_json": {"passed": True, "consistency_score": 0.55}},
            ]
        ],
    )
    svc = _FakeTaskService(repo)
    with (
        patch(
            "hevi.cost.router.route_video_provider",
            new_callable=AsyncMock,
            return_value="wan_local",
        ),
        patch(
            "hevi.director.producer.estimate_cost",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(total_usd=0.5),
        ),
    ):
        res = await run_director_loop(
            task_id="t1",
            task_service=svc,
            intent={"topic": "x", "duration_archetype": "1-5min", "budget_usd": 5.0},
        )
    assert svc.run_called == 1
    assert svc.regen_calls == [[1]]  # 只返工镜头 1
    assert res.rework_rounds == 1
    assert res.delivered is True


@pytest.mark.asyncio
async def test_director_loop_aborts_when_infeasible():
    """预算不够 → Producer 判不可行 → 不烧算力,直接止损。"""
    from hevi.director import run_director_loop

    svc = _FakeTaskService(_FakeRepo({"config_json": {}}, [[]]))
    with patch(
        "hevi.director.producer.estimate_cost",
        new_callable=AsyncMock,
        return_value=SimpleNamespace(total_usd=99.0),
    ):
        res = await run_director_loop(
            task_id="t1",
            task_service=svc,
            intent={
                "topic": "x",
                "duration_archetype": "1-5min",
                "video_provider": "wan_cloud",
                "budget_usd": 2.0,
            },
        )
    assert res.delivered is False
    assert svc.run_called == 0  # 没跑管线
    assert "infeasible" in res.reason


# ── NL 意图 + 自动分镜(LLM 外壳)─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_intent_from_llm():
    from hevi.director import parse_intent

    llm = AsyncMock(
        return_value={
            "content": '{"topic":"猫的一天","duration_archetype":"5-15min",'
            '"num_characters":2,"style":"治愈","budget_usd":3.5}'
        }
    )
    intent = await parse_intent("做个治愈系猫咪视频,两个角色,预算3.5刀", llm=llm)
    assert intent["topic"] == "猫的一天"
    assert intent["duration_archetype"] == "5-15min"
    assert intent["num_characters"] == 2
    assert intent["budget_usd"] == 3.5


@pytest.mark.asyncio
async def test_parse_intent_invalid_archetype_and_failure_fallback():
    from hevi.director import parse_intent

    bad = AsyncMock(return_value={"content": '{"topic":"x","duration_archetype":"nonsense"}'})
    assert (await parse_intent("x", llm=bad))["duration_archetype"] == "1-5min"

    down = AsyncMock(side_effect=RuntimeError("llm down"))
    intent = await parse_intent("原始需求文本", llm=down)
    assert intent["topic"] == "原始需求文本"  # 兜底用原文
    assert intent["duration_archetype"] == "1-5min"


@pytest.mark.asyncio
async def test_plan_shots_from_llm_and_fallback():
    from hevi.director import plan_shots

    llm = AsyncMock(return_value={"content": '["a cat wakes","a cat eats","a cat sleeps"]'})
    shots = await plan_shots(topic="猫的一天", num_shots=3, llm=llm)
    assert shots == ["a cat wakes", "a cat eats", "a cat sleeps"]

    down = AsyncMock(side_effect=RuntimeError("down"))
    fb = await plan_shots(topic="狐狸", num_shots=2, llm=down)
    assert len(fb) == 2 and all("狐狸" in s for s in fb)


@pytest.mark.asyncio
async def test_plan_from_text_end_to_end():
    """输入剧情文本 → 意图 + 可行性 + 分镜 + 可执行 canvas 图。"""
    from hevi.director import plan_from_text

    llm = AsyncMock(
        side_effect=[
            {"content": '{"topic":"狐狸雪地","duration_archetype":"1-5min","style":"电影感"}'},
            {"content": '["fox runs in snow","fox catches prey"]'},
        ]
    )
    with (
        patch(
            "hevi.cost.router.route_video_provider",
            new_callable=AsyncMock,
            return_value="wan_local",
        ),
        patch(
            "hevi.director.producer.estimate_cost",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(total_usd=0.0),
        ),
    ):
        out = await plan_from_text(text="拍个狐狸在雪地的短片", num_shots=2, llm=llm)
    assert out["intent"]["topic"] == "狐狸雪地"
    assert out["shot_prompts"] == ["fox runs in snow", "fox catches prey"]
    assert len([n for n in out["graph"]["nodes"] if n["node_type"] == "video"]) == 2
    assert out["plan"].video_provider == "wan_local"


# ── /api/director 路由(直调 handler)────────────────────────────────────────


@pytest.mark.asyncio
async def test_director_api_plan_serializes_plan():
    """POST /director/plan:返回 intent + 可行性 plan(dataclass→dict)+ 分镜 + 图。"""
    import uuid

    from hevi.api.routers.director import PlanRequest, director_plan

    fake = {
        "intent": {"topic": "狐狸雪地"},
        "plan": _plan("wan_local"),
        "shot_prompts": ["a", "b"],
        "graph": {"name": "g", "nodes": [], "edges": []},
    }
    with patch(
        "hevi.api.routers.director.plan_from_text", new_callable=AsyncMock, return_value=fake
    ):
        out = await director_plan(
            PlanRequest(text="拍狐狸", num_shots=2), user={"id": uuid.uuid4()}
        )
    assert out["intent"]["topic"] == "狐狸雪地"
    assert isinstance(out["plan"], dict)  # ProducerPlan 已序列化
    assert out["plan"]["video_provider"] == "wan_local"


@pytest.mark.asyncio
async def test_director_api_episode_creates_and_queues():
    """POST /director/episodes:可行 → 建任务 + 提交/后台跑,回 task_id。"""
    import uuid

    from fastapi import BackgroundTasks

    from hevi.api.routers.director import EpisodeRequest, director_create_episode

    tid = uuid.uuid4()
    svc = AsyncMock()
    svc.create_task.return_value = {"id": tid, "status": "pending"}
    svc.submit_task.return_value = {"status": "queued"}
    with (
        patch(
            "hevi.api.routers.director.parse_intent",
            new_callable=AsyncMock,
            return_value={
                "topic": "x",
                "duration_archetype": "1-5min",
                "num_characters": 1,
                "style": "cinematic",
            },
        ),
        patch(
            "hevi.api.routers.director.produce",
            new_callable=AsyncMock,
            return_value=_plan("wan_local"),
        ),
    ):
        from unittest.mock import MagicMock

        out = await director_create_episode(
            EpisodeRequest(text="拍狐狸"),
            user={"id": uuid.uuid4()},
            svc=svc,
            pool=MagicMock(),
            background_tasks=BackgroundTasks(),
        )
    assert out["task_id"] == str(tid)
    assert out["status"] == "queued"
    svc.create_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_director_api_episode_infeasible_402():
    """预算不够 → 402,不建任务。"""
    import uuid

    from fastapi import BackgroundTasks, HTTPException

    from hevi.api.routers.director import EpisodeRequest, director_create_episode

    infeasible = _plan("wan_cloud")
    infeasible.feasible = False
    infeasible.notes = ["预算不足"]
    svc = AsyncMock()
    with (
        patch(
            "hevi.api.routers.director.parse_intent",
            new_callable=AsyncMock,
            return_value={
                "topic": "x",
                "duration_archetype": "1-5min",
                "num_characters": 1,
                "style": "cinematic",
            },
        ),
        patch("hevi.api.routers.director.produce", new_callable=AsyncMock, return_value=infeasible),
    ):
        from unittest.mock import MagicMock

        with pytest.raises(HTTPException) as ei:
            await director_create_episode(
                EpisodeRequest(text="拍狐狸", budget_usd=0.01),
                user={"id": uuid.uuid4()},
                svc=svc,
                pool=MagicMock(),
                background_tasks=BackgroundTasks(),
            )
    assert ei.value.status_code == 402
    svc.create_task.assert_not_called()


@pytest.mark.asyncio
async def test_director_api_episode_passes_structured_fields():
    """POST /director/episodes:8 层结构化字段透传 —— 画幅/画质/风格进 create_task,绑角色→i2v。"""
    import uuid

    from fastapi import BackgroundTasks

    from hevi.api.routers.director import EpisodeRequest, director_create_episode

    tid = uuid.uuid4()
    svc = AsyncMock()
    svc.create_task.return_value = {"id": tid, "status": "pending"}
    svc.submit_task.return_value = {"status": "queued"}
    with (
        patch(
            "hevi.api.routers.director.parse_intent",
            new_callable=AsyncMock,
            return_value={
                "topic": "x",
                "duration_archetype": "1-5min",
                "num_characters": 1,
                "style": "cinematic",
            },
        ),
        patch(
            "hevi.api.routers.director.produce",
            new_callable=AsyncMock,
            return_value=_plan("wan_local"),
        ) as mp,
    ):
        from unittest.mock import MagicMock

        out = await director_create_episode(
            EpisodeRequest(
                text="拍狐狸",
                aspect_ratio="16:9",
                quality_profile="high",
                subject_id="sub-1",
                style_preset="赛博朋克",
                duration_archetype="short",
                per_shot_routing=True,
                bgm="warm",
                mood="温暖",
                genre="纪录片",
                narrative_hook="悬念开场",
                scene_notes="雪山之巅",
                props="登山杖",
                sfx="whoosh",
                voice_rate="+10%",
                subtitle_style="large_white",
                bilingual_language="en",
                intro_clip="/tmp/intro.mp4",
            ),
            user={"id": uuid.uuid4()},
            svc=svc,
            pool=MagicMock(),
            background_tasks=BackgroundTasks(),
        )
    # 绑了主体 → produce 用 i2v;时长档覆盖 LLM 猜的
    assert mp.await_args.kwargs["mode"] == "i2v"
    assert mp.await_args.kwargs["duration_archetype"] == "short"
    # 结构化字段进 create_task → config_json
    ck = svc.create_task.await_args.kwargs
    assert ck["duration_archetype"] == "short"
    assert ck["aspect_ratio"] == "16:9"
    assert ck["quality_profile"] == "high"
    assert ck["style_preset"] == "赛博朋克"
    assert ck["subject_id"] == "sub-1"
    assert ck["per_shot_routing"] is True
    assert ck["bgm"] == "warm"
    assert ck["mood"] == "温暖"
    assert ck["genre"] == "纪录片"
    assert ck["narrative_hook"] == "悬念开场"
    assert ck["scene_notes"] == "雪山之巅"
    assert ck["props"] == "登山杖"
    assert ck["sfx"] == "whoosh"
    assert ck["voice_rate"] == "+10%"
    assert ck["subtitle_style"] == "large_white"
    assert ck["bilingual_language"] == "en"
    assert ck["intro_clip"] == "/tmp/intro.mp4"
    # 回执 spec
    assert out["spec"]["aspect_ratio"] == "16:9"
    assert out["spec"]["subject_locked"] is True


@pytest.mark.asyncio
async def test_director_api_episode_preset_sets_provider_base():
    """执行预设 economy → 底层 provider/quality 走本地;显式字段仍可覆盖。"""
    import uuid

    from fastapi import BackgroundTasks

    from hevi.api.routers.director import EpisodeRequest, director_create_episode

    svc = AsyncMock()
    svc.create_task.return_value = {"id": uuid.uuid4(), "status": "pending"}
    svc.submit_task.return_value = {"status": "queued"}
    with (
        patch(
            "hevi.api.routers.director.parse_intent",
            new_callable=AsyncMock,
            return_value={
                "topic": "x",
                "duration_archetype": "1-5min",
                "num_characters": 1,
                "style": "cinematic",
            },
        ),
        patch(
            "hevi.api.routers.director.produce",
            new_callable=AsyncMock,
            return_value=_plan("wan_local"),
        ) as mp,
    ):
        from unittest.mock import MagicMock

        await director_create_episode(
            EpisodeRequest(text="x", preset="economy"),
            user={"id": uuid.uuid4()},
            svc=svc,
            pool=MagicMock(),
            background_tasks=BackgroundTasks(),
        )
    # economy 预设 → video_provider=wan_local, audio=edge_tts 作底传给 produce
    assert mp.await_args.kwargs["video_provider"] == "wan_local"
    assert mp.await_args.kwargs["audio_provider"] == "edge_tts"


@pytest.mark.asyncio
async def test_director_api_render_edit_loop():
    """POST /director/render:存图 + 建任务 + 排后台渲染,回 task_id/graph_id/镜头数。"""
    import uuid
    from unittest.mock import MagicMock

    from fastapi import BackgroundTasks

    from hevi.api.routers.director import RenderRequest, director_render

    tid = uuid.uuid4()
    svc = AsyncMock()
    svc.create_task.return_value = {"id": tid, "status": "pending"}
    gsvc = AsyncMock()
    gsvc.save_graph.return_value = {"id": "g1"}
    bg = BackgroundTasks()
    with (
        patch("hevi.api.routers.director.GraphService", return_value=gsvc),
        patch("hevi.api.routers.director.GraphRepository"),
        patch("hevi.api.routers.director.ExecutorService"),
    ):
        out = await director_render(
            RenderRequest(
                name="x",
                aspect_ratio="16:9",
                quality_profile="high",
                bgm="epic",
                nodes=[
                    {"node_id": "topic", "node_type": "text", "config": {}},
                    {"node_id": "shot_0000", "node_type": "video", "config": {"prompt": "a"}},
                    {"node_id": "shot_0001", "node_type": "video", "config": {"prompt": "b"}},
                ],
                edges=[],
            ),
            user={"id": uuid.uuid4()},
            svc=svc,
            pool=MagicMock(),
            background_tasks=bg,
        )
    assert out["task_id"] == str(tid)
    assert out["graph_id"] == "g1"
    assert out["shot_count"] == 2
    assert len(bg.tasks) == 1  # 后台渲染已排入
    gsvc.save_graph.assert_awaited_once()


@pytest.mark.asyncio
async def test_director_api_render_no_shots_400():
    """图里没有 video 节点 → 400。"""
    import uuid
    from unittest.mock import MagicMock

    from fastapi import BackgroundTasks, HTTPException

    from hevi.api.routers.director import RenderRequest, director_render

    with pytest.raises(HTTPException) as ei:
        await director_render(
            RenderRequest(nodes=[{"node_id": "topic", "node_type": "text"}], edges=[]),
            user={"id": uuid.uuid4()},
            svc=AsyncMock(),
            pool=MagicMock(),
            background_tasks=BackgroundTasks(),
        )
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_render_graph_episode_collects_and_assembles(tmp_path):
    """逐镜编辑回路:执行结果里的 clip → 装配 → 任务标 completed + result_video_path。"""
    import uuid

    clip0 = tmp_path / "shot_0000.mp4"
    clip0.write_bytes(b"\x00" * 128)
    clip1 = tmp_path / "shot_0001.mp4"
    clip1.write_bytes(b"\x00" * 128)
    exe = AsyncMock()
    exe.execute_graph.return_value = {
        "results": {
            "shot_0001": {"node_type": "video", "success": True, "output": {"output": str(clip1)}},
            "shot_0000": {"node_type": "video", "success": True, "output": {"output": str(clip0)}},
            "topic": {"node_type": "text", "success": True, "output": {"output": "x"}},
        }
    }
    tsvc = AsyncMock()
    with patch("hevi.assembly.assembler.assemble_longvideo", new_callable=AsyncMock) as masm:
        from hevi.director.graph_render import render_graph_episode

        await render_graph_episode(
            graph_id="g1",
            task_id=uuid.uuid4(),
            executor_service=exe,
            task_service=tsvc,
            width=1280,
            height=720,
            fps=24,
            transition="fade",
            bgm=None,
        )
    masm.assert_awaited_once()
    assert len(masm.await_args.kwargs["shots"]) == 2  # 两镜都收进装配
    upd = tsvc.repository.update_task.await_args.args[1]
    assert upd["status"] == "completed"
    assert upd["total_shots"] == 2
    assert upd["result_video_path"].endswith("final.mp4")


@pytest.mark.asyncio
async def test_director_api_episode_multi_character_roster():
    """多角色绑定:character_subject_ids 解析成 roster 文本注入 characters kwarg,
    首个 id 用于 i2v 锁脸(誠实边界:其余角色只影响文本描述,不做画面身份锁定)。"""
    import uuid
    from unittest.mock import MagicMock

    from fastapi import BackgroundTasks

    from hevi.api.routers.director import EpisodeRequest, director_create_episode

    tid = uuid.uuid4()
    svc = AsyncMock()
    svc.create_task.return_value = {"id": tid, "status": "pending"}
    svc.submit_task.return_value = {"status": "queued"}

    subjects = {
        "sub-a": {"name": "阿狐", "description": "机灵的向导"},
        "sub-b": {"name": "阿熊", "description": "沉默的守护者"},
    }

    async def fake_get_subject(self, subject_id):
        return subjects.get(subject_id)

    with (
        patch(
            "hevi.api.routers.director.parse_intent",
            new_callable=AsyncMock,
            return_value={"topic": "x", "duration_archetype": "1-5min", "num_characters": 2, "style": "cinematic"},
        ),
        patch("hevi.api.routers.director.produce", new_callable=AsyncMock, return_value=_plan("wan_local")) as mp,
        patch("hevi.subjects.subject_service.SubjectService.get_subject", fake_get_subject),
    ):
        out = await director_create_episode(
            EpisodeRequest(text="拍雪山冒险", character_subject_ids=["sub-a", "sub-b"]),
            user={"id": uuid.uuid4()},
            svc=svc,
            pool=MagicMock(),
            background_tasks=BackgroundTasks(),
        )
    # 首个角色(sub-a)驱动 i2v 锁脸
    assert mp.await_args.kwargs["mode"] == "i2v"
    ck = svc.create_task.await_args.kwargs
    assert ck["subject_id"] == "sub-a"
    assert "阿狐" in ck["characters"] and "阿熊" in ck["characters"]
    assert out["spec"]["character_count"] == 2
    assert out["spec"]["subject_locked"] is True


@pytest.mark.asyncio
async def test_director_api_episode_roster_includes_metadata_and_voice_negative():
    """角色卡的 metadata(人设/年龄/语言风格/关系)并入 roster 文本;voice_ref → 尽力而为
    的 speaker_i 映射;negative_notes 合并成 extra_negative。"""
    import uuid
    from unittest.mock import MagicMock

    from fastapi import BackgroundTasks

    from hevi.api.routers.director import EpisodeRequest, director_create_episode

    tid = uuid.uuid4()
    svc = AsyncMock()
    svc.create_task.return_value = {"id": tid, "status": "pending"}
    svc.submit_task.return_value = {"status": "queued"}

    subjects = {
        "sub-a": {
            "name": "阿狐", "description": "机灵的向导",
            "metadata": {
                "age": "20多岁", "persona": "毒舌但重情义", "speech_style": "爱用东北方言",
                "relationships": "与阿熊是竞争对手", "voice_ref": "output/voice_references/sub-a/v.wav",
                "negative_notes": "避免多指",
            },
        },
        "sub-b": {
            "name": "阿熊", "description": "沉默的守护者",
            "metadata": {"voice_ref": "output/voice_references/sub-b/v2.wav", "negative_notes": "避免崩脸"},
        },
    }

    async def fake_get_subject(self, subject_id):
        return subjects.get(subject_id)

    with (
        patch(
            "hevi.api.routers.director.parse_intent",
            new_callable=AsyncMock,
            return_value={"topic": "x", "duration_archetype": "1-5min", "num_characters": 2, "style": "cinematic"},
        ),
        patch("hevi.api.routers.director.produce", new_callable=AsyncMock, return_value=_plan("wan_local")),
        patch("hevi.subjects.subject_service.SubjectService.get_subject", fake_get_subject),
    ):
        await director_create_episode(
            EpisodeRequest(text="拍雪山冒险", character_subject_ids=["sub-a", "sub-b"]),
            user={"id": uuid.uuid4()},
            svc=svc,
            pool=MagicMock(),
            background_tasks=BackgroundTasks(),
        )
    ck = svc.create_task.await_args.kwargs
    assert "20多岁" in ck["characters"] and "毒舌但重情义" in ck["characters"]
    assert "东北方言" in ck["characters"] and "竞争对手" in ck["characters"]
    assert ck["character_voices"] == {
        "speaker_0": "output/voice_references/sub-a/v.wav",
        "speaker_1": "output/voice_references/sub-b/v2.wav",
    }
    assert "避免多指" in ck["extra_negative"] and "避免崩脸" in ck["extra_negative"]


@pytest.mark.asyncio
async def test_director_api_episode_no_characters_no_voice_negative_keys():
    """没绑角色 → character_voices/extra_negative 干脆不出现在 kwargs 里(而非空字典/空串)。"""
    import uuid
    from unittest.mock import MagicMock

    from fastapi import BackgroundTasks

    from hevi.api.routers.director import EpisodeRequest, director_create_episode

    svc = AsyncMock()
    svc.create_task.return_value = {"id": uuid.uuid4(), "status": "pending"}
    svc.submit_task.return_value = {"status": "queued"}
    with (
        patch(
            "hevi.api.routers.director.parse_intent",
            new_callable=AsyncMock,
            return_value={"topic": "x", "duration_archetype": "1-5min", "num_characters": 1, "style": "cinematic"},
        ),
        patch("hevi.api.routers.director.produce", new_callable=AsyncMock, return_value=_plan("wan_local")),
    ):
        await director_create_episode(
            EpisodeRequest(text="x"),
            user={"id": uuid.uuid4()},
            svc=svc,
            pool=MagicMock(),
            background_tasks=BackgroundTasks(),
        )
    ck = svc.create_task.await_args.kwargs
    assert "character_voices" not in ck
    assert "extra_negative" not in ck
