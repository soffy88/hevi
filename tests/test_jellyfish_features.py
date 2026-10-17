"""Jellyfish 能力对齐测试。

覆盖 4 个从 Jellyfish 借鉴的功能:
1. 候选确认工作流 (preparation)
2. 资产实体扩展 (props/costumes)
3. 长任务取消 (cancellation)
4. 提示词模板管理 (prompts)
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from hevi.preparation import (
    CandidateStatus,
    CandidateType,
    PreparationService,
    PreparationState,
    ShotCandidate,
    ShotPreparation,
)
from hevi.assets import AssetService, Costume, Prop
from hevi.tasks.cancellation import (
    cancel_running_task,
    get_running_task_ids,
    is_task_running,
    register_running_task,
    unregister_running_task,
)
from hevi.prompts import PromptCategory, PromptTemplate, PromptTemplateService


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 候选确认工作流
# ═══════════════════════════════════════════════════════════════════════════════


class TestPreparationWorkflow:
    """候选确认工作流测试。"""

    def test_create_preparation(self) -> None:
        svc = PreparationService()
        prep = svc.create_preparation(task_id="t1", shot_title="镜头1")
        assert prep.state == PreparationState.DRAFT
        assert prep.shot_title == "镜头1"

    def test_add_candidates_transitions_to_preparing(self) -> None:
        svc = PreparationService()
        prep = svc.create_preparation(task_id="t1")
        svc.add_candidates(prep.shot_id, [
            {"type": "character", "name": "张三", "confidence": 0.9},
            {"type": "scene", "name": "朝堂", "confidence": 0.8},
        ])
        assert prep.state == PreparationState.PREPARING
        assert len(prep.candidates) == 2
        assert len(prep.pending_candidates) == 2

    def test_accept_candidate(self) -> None:
        svc = PreparationService()
        prep = svc.create_preparation(task_id="t1")
        added = svc.add_candidates(prep.shot_id, [
            {"type": "character", "name": "张三", "confidence": 0.9},
        ])
        result = svc.accept_candidate(prep.shot_id, added[0].id)
        assert result is not None
        assert result.status == CandidateStatus.ACCEPTED

    def test_ignore_candidate(self) -> None:
        svc = PreparationService()
        prep = svc.create_preparation(task_id="t1")
        added = svc.add_candidates(prep.shot_id, [
            {"type": "prop", "name": "竹简"},
        ])
        result = svc.ignore_candidate(prep.shot_id, added[0].id)
        assert result is not None
        assert result.status == CandidateStatus.IGNORED

    def test_link_candidate(self) -> None:
        svc = PreparationService()
        prep = svc.create_preparation(task_id="t1")
        added = svc.add_candidates(prep.shot_id, [
            {"type": "character", "name": "张三"},
        ])
        result = svc.link_candidate(prep.shot_id, added[0].id, "subject_001")
        assert result is not None
        assert result.status == CandidateStatus.LINKED
        assert result.linked_id == "subject_001"

    def test_ready_state_when_required_candidates_confirmed(self) -> None:
        svc = PreparationService()
        prep = svc.create_preparation(task_id="t1")
        added = svc.add_candidates(prep.shot_id, [
            {"type": "character", "name": "张三"},
            {"type": "scene", "name": "朝堂"},
            {"type": "dialogue", "name": "你好"},
        ])
        # 接受角色和场景
        svc.accept_candidate(prep.shot_id, added[0].id)
        svc.accept_candidate(prep.shot_id, added[1].id)
        # 对话可选,不确认也应该 ready
        assert prep.state == PreparationState.READY

    def test_not_ready_without_required_character(self) -> None:
        svc = PreparationService()
        prep = svc.create_preparation(task_id="t1")
        svc.add_candidates(prep.shot_id, [
            {"type": "character", "name": "张三"},
        ])
        # 不确认角色
        assert prep.state != PreparationState.READY
        assert not prep.is_ready()

    def test_refresh_candidates_keeps_accepted(self) -> None:
        svc = PreparationService()
        prep = svc.create_preparation(task_id="t1")
        added = svc.add_candidates(prep.shot_id, [
            {"type": "character", "name": "张三"},
            {"type": "prop", "name": "旧道具"},
        ])
        svc.accept_candidate(prep.shot_id, added[0].id)
        # 刷新
        svc.refresh_candidates(prep.shot_id, [
            {"type": "prop", "name": "新道具"},
        ])
        # 张三(已接受)保留,旧道具(已忽略)被清除,新道具加入
        names = [c.name for c in prep.candidates]
        assert "张三" in names
        assert "旧道具" not in names
        assert "新道具" in names

    def test_get_ready_shots(self) -> None:
        svc = PreparationService()
        p1 = svc.create_preparation(task_id="t1")
        p2 = svc.create_preparation(task_id="t1")
        added = svc.add_candidates(p1.shot_id, [{"type": "character", "name": "A"}])
        svc.accept_candidate(p1.shot_id, added[0].id)
        ready = svc.get_ready_shots("t1")
        assert p1.shot_id in ready
        assert p2.shot_id not in ready

    def test_stats(self) -> None:
        svc = PreparationService()
        svc.create_preparation(task_id="t1")
        stats = svc.get_stats("t1")
        assert stats["total_shots"] == 1
        assert stats["states"]["draft"] == 1

    def test_shot_preparation_to_dict_roundtrip(self) -> None:
        prep = ShotPreparation(shot_id="s1", task_id="t1", shot_title="测试")
        prep.add_candidate(
            ShotCandidate(
                id="c1",
                candidate_type=CandidateType.CHARACTER,
                name="张三",
                confidence=0.9,
            )
        )
        d = prep.to_dict()
        prep2 = ShotPreparation.from_dict(d)
        assert prep2.shot_id == "s1"
        assert len(prep2.candidates) == 1
        assert prep2.candidates[0].name == "张三"

    def test_mark_ready_manual(self) -> None:
        svc = PreparationService()
        prep = svc.create_preparation(task_id="t1")
        svc.mark_ready(prep.shot_id)
        assert prep.state == PreparationState.READY


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 资产实体扩展 (道具/服装)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAssetService:
    """道具/服装资产管理测试。"""

    # ── 道具 ──

    def test_create_prop(self) -> None:
        svc = AssetService()
        prop = svc.create_prop(name="竹简", description="战国竹简", era="战国")
        assert prop.name == "竹简"
        assert prop.era == "战国"
        assert prop.id.startswith("prop_")

    def test_prop_name_uniqueness(self) -> None:
        svc = AssetService()
        svc.create_prop(name="竹简")
        with pytest.raises(ValueError, match="已存在"):
            svc.create_prop(name="竹简")

    def test_get_prop_by_name(self) -> None:
        svc = AssetService()
        svc.create_prop(name="竹简")
        prop = svc.get_prop_by_name("竹简")
        assert prop is not None
        assert prop.name == "竹简"
        assert svc.get_prop_by_name("不存在") is None

    def test_update_prop(self) -> None:
        svc = AssetService()
        prop = svc.create_prop(name="竹简")
        updated = svc.update_prop(prop.id, description="更新描述")
        assert updated is not None
        assert updated.description == "更新描述"

    def test_update_prop_name_uniqueness(self) -> None:
        svc = AssetService()
        svc.create_prop(name="竹简")
        p2 = svc.create_prop(name="剑")
        with pytest.raises(ValueError, match="已存在"):
            svc.update_prop(p2.id, name="竹简")

    def test_delete_prop(self) -> None:
        svc = AssetService()
        prop = svc.create_prop(name="竹简")
        assert svc.delete_prop(prop.id) is True
        assert svc.get_prop(prop.id) is None
        assert svc.delete_prop("nonexistent") is False

    def test_link_prop_to_shot(self) -> None:
        svc = AssetService()
        prop = svc.create_prop(name="竹简")
        assert svc.link_prop_to_shot(prop.id, "shot_001") is True
        assert "shot_001" in prop.shot_ids
        # 重复关联不重复添加
        svc.link_prop_to_shot(prop.id, "shot_001")
        assert prop.shot_ids.count("shot_001") == 1

    def test_list_props(self) -> None:
        svc = AssetService()
        svc.create_prop(name="竹简")
        svc.create_prop(name="剑")
        assert len(svc.list_props()) == 2

    # ── 服装 ──

    def test_create_costume(self) -> None:
        svc = AssetService()
        costume = svc.create_costume(
            name="朝服",
            character_name="秦始皇",
            description="黑色玄端朝服",
            era="秦",
        )
        assert costume.name == "朝服"
        assert costume.character_name == "秦始皇"

    def test_costume_name_uniqueness(self) -> None:
        svc = AssetService()
        svc.create_costume(name="朝服", character_name="秦始皇")
        with pytest.raises(ValueError, match="已存在"):
            svc.create_costume(name="朝服", character_name="李斯")

    def test_list_costumes_by_character(self) -> None:
        svc = AssetService()
        svc.create_costume(name="朝服", character_name="秦始皇")
        svc.create_costume(name="便服", character_name="秦始皇")
        svc.create_costume(name="战甲", character_name="蒙恬")
        assert len(svc.list_costumes(character_name="秦始皇")) == 2
        assert len(svc.list_costumes(character_name="蒙恬")) == 1

    def test_costume_color_palette(self) -> None:
        svc = AssetService()
        costume = svc.create_costume(
            name="朝服",
            character_name="秦始皇",
            color_palette=["黑色", "金色", "红色"],
        )
        assert len(costume.color_palette) == 3

    def test_link_costume_to_shot(self) -> None:
        svc = AssetService()
        costume = svc.create_costume(name="朝服", character_name="秦始皇")
        assert svc.link_costume_to_shot(costume.id, "shot_001") is True
        assert "shot_001" in costume.shot_ids

    def test_asset_stats(self) -> None:
        svc = AssetService()
        svc.create_prop(name="竹简")
        svc.create_costume(name="朝服", character_name="秦始皇")
        stats = svc.stats()
        assert stats["total_props"] == 1
        assert stats["total_costumes"] == 1

    # ── 序列化 ──

    def test_prop_to_dict_roundtrip(self) -> None:
        prop = Prop(id="p1", name="竹简", era="战国")
        d = prop.to_dict()
        prop2 = Prop.from_dict(d)
        assert prop2.name == "竹简"
        assert prop2.era == "战国"

    def test_costume_to_dict_roundtrip(self) -> None:
        costume = Costume(
            id="c1", name="朝服", character_name="秦始皇", era="秦"
        )
        d = costume.to_dict()
        costume2 = Costume.from_dict(d)
        assert costume2.name == "朝服"
        assert costume2.character_name == "秦始皇"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 长任务取消
# ═══════════════════════════════════════════════════════════════════════════════


class TestTaskCancellation:
    """长任务取消测试。"""

    def test_register_and_is_running(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            task_id = uuid.uuid4()

            async def _long_task() -> None:
                await asyncio.sleep(100)

            aio_task = loop.create_task(_long_task())
            register_running_task(task_id, aio_task)
            assert is_task_running(task_id) is True
            aio_task.cancel()
            try:
                loop.run_until_complete(aio_task)
            except (asyncio.CancelledError, Exception):
                pass
            assert is_task_running(task_id) is False
        finally:
            loop.close()

    def test_cancel_running_task(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            task_id = uuid.uuid4()

            async def _long_task() -> None:
                await asyncio.sleep(100)

            aio_task = loop.create_task(_long_task())
            register_running_task(task_id, aio_task)
            assert cancel_running_task(task_id) is True
            # cancel() 是异步的,需要给 loop 一个 tick 处理
            loop.run_until_complete(asyncio.sleep(0))
            assert aio_task.cancelled() or aio_task.done()
        finally:
            loop.close()

    def test_cancel_nonexistent_task(self) -> None:
        assert cancel_running_task(uuid.uuid4()) is False

    def test_unregister_task(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            task_id = uuid.uuid4()

            async def _done_task() -> None:
                pass

            aio_task = loop.create_task(_done_task())
            loop.run_until_complete(aio_task)
            register_running_task(task_id, aio_task)
            unregister_running_task(task_id)
            assert is_task_running(task_id) is False
        finally:
            loop.close()

    def test_get_running_task_ids(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            task_id = uuid.uuid4()

            async def _long_task() -> None:
                await asyncio.sleep(100)

            aio_task = loop.create_task(_long_task())
            register_running_task(task_id, aio_task)
            ids = get_running_task_ids()
            assert task_id in ids
            aio_task.cancel()
            try:
                loop.run_until_complete(aio_task)
            except (asyncio.CancelledError, Exception):
                pass
        finally:
            loop.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 提示词模板管理
# ═══════════════════════════════════════════════════════════════════════════════


class TestPromptTemplateService:
    """提示词模板管理测试。"""

    def test_builtin_templates_loaded(self) -> None:
        svc = PromptTemplateService()
        assert svc.stats()["total"] >= 4
        assert svc.get_default_template(PromptCategory.SHOT) is not None

    def test_create_template(self) -> None:
        svc = PromptTemplateService()
        t = svc.create_template(
            name="自定义镜头",
            category=PromptCategory.SHOT,
            template="{scene}, {action}, {camera}",
            description="自定义镜头提示词",
        )
        assert t.name == "自定义镜头"
        assert t.variables == ["scene", "action", "camera"]

    def test_render_template(self) -> None:
        svc = PromptTemplateService()
        result = svc.render(
            "builtin_shot_frame",
            shot_description="角色A站在朝堂",
            camera_movement="静态",
            character_names="角色A",
            scene_description="朝堂大殿",
            style_directive="cinematic",
        )
        assert "角色A站在朝堂" in result
        assert "静态" in result
        assert "cinematic" in result

    def test_render_default_template(self) -> None:
        svc = PromptTemplateService()
        result = svc.render_default(
            PromptCategory.CHARACTER,
            character_name="秦始皇",
            character_description="威严的帝王",
            costume_description="黑色玄端",
            era="秦",
        )
        assert "秦始皇" in result
        assert "黑色玄端" in result

    def test_template_default_values(self) -> None:
        svc = PromptTemplateService()
        # builtin_shot_frame 有 style_directive 默认值 "cinematic, realistic"
        result = svc.render(
            "builtin_shot_frame",
            shot_description="test",
            camera_movement="static",
            character_names="A",
            scene_description="scene",
        )
        assert "cinematic, realistic" in result

    def test_list_by_category(self) -> None:
        svc = PromptTemplateService()
        shot_templates = svc.list_templates(category=PromptCategory.SHOT)
        assert all(t.category == PromptCategory.SHOT for t in shot_templates)

    def test_update_template(self) -> None:
        svc = PromptTemplateService()
        t = svc.create_template(
            name="test",
            category=PromptCategory.VIDEO,
            template="{old_var}",
        )
        updated = svc.update_template(t.id, template="{new_var1} and {new_var2}")
        assert updated is not None
        assert updated.variables == ["new_var1", "new_var2"]

    def test_delete_template(self) -> None:
        svc = PromptTemplateService()
        t = svc.create_template(
            name="temp",
            category=PromptCategory.IMAGE,
            template="{x}",
        )
        assert svc.delete_template(t.id) is True
        assert svc.get_template(t.id) is None

    def test_cannot_delete_builtin(self) -> None:
        svc = PromptTemplateService()
        with pytest.raises(ValueError, match="built-in"):
            svc.delete_template("builtin_shot_frame")

    def test_set_default_template(self) -> None:
        svc = PromptTemplateService()
        t = svc.create_template(
            name="new_default",
            category=PromptCategory.IMAGE,
            template="{img}",
            is_default=True,
        )
        default = svc.get_default_template(PromptCategory.IMAGE)
        assert default is not None
        assert default.id == t.id

    def test_render_nonexistent_raises(self) -> None:
        svc = PromptTemplateService()
        with pytest.raises(ValueError, match="not found"):
            svc.render("nonexistent", x="y")

    def test_render_default_no_default_raises(self) -> None:
        svc = PromptTemplateService()
        # IMAGE 类别没有内置默认模板,但上面测试可能已经设了
        # 用一个肯定没有的类别
        from hevi.prompts.models import PromptCategory as PC

        # 先删除可能的默认
        default = svc.get_default_template(PC.IMAGE)
        if default and not default.id.startswith("builtin_"):
            svc.delete_template(default.id)
        # 现在应该没有 IMAGE 默认模板了(如果没有内置的)
        # 实际上我们没给 IMAGE 设内置默认,所以这应该报错
        # 但为了安全,直接用 render_default 对没有默认的类别
        with pytest.raises(ValueError, match="No default"):
            svc.render_default(PC.IMAGE)

    def test_template_to_dict_roundtrip(self) -> None:
        t = PromptTemplate(
            id="t1",
            name="测试",
            category=PromptCategory.SHOT,
            template="{a} and {b}",
            variables=["a", "b"],
        )
        d = t.to_dict()
        t2 = PromptTemplate.from_dict(d)
        assert t2.name == "测试"
        assert t2.variables == ["a", "b"]

    def test_extract_variables(self) -> None:
        from hevi.prompts.service import _extract_variables

        assert _extract_variables("{a} and {b} and {c}") == ["a", "b", "c"]
        assert _extract_variables("no variables") == []
        # 重复变量只出现一次
        assert _extract_variables("{a} and {a}") == ["a"]

    def test_stats(self) -> None:
        svc = PromptTemplateService()
        stats = svc.stats()
        assert stats["total"] >= 4
        assert "shot" in stats["by_category"]
