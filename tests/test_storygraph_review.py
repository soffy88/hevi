"""DRAMAPLAN 三层审稿测试（不调网络，用 fake LLM 响应）。

覆盖：确定性规则检查项（人物名/字数/镜头预算/覆盖率/禁忌）、首轮不通过 → 只改问题场 →
通过、未点名场原样保留、review_log 落盘结构。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.shortdrama.longform import plan_longform_drama
from hevi.storygraph.review import (
    AdaptationDecision,
    EpisodeScript,
    ReviewIssue,
    ScriptLine,
    ScriptScene,
    deterministic_checks,
    revise_episode_script,
    review_episode,
    run_three_layer_review,
    script_to_storyboard,
    write_review_log,
)
from hevi.storygraph.schemas import (
    AdaptationOutline,
    EpisodeStoryboard,
    OutlineEpisode,
    StoryCharacter,
    StoryEvent,
    StoryGraph,
    StoryMeta,
    StoryQuote,
)


def _book() -> StoryGraph:
    return StoryGraph(
        meta=StoryMeta(source="测试书"),
        characters=[
            StoryCharacter(char_id="C001", name="张三"),
            StoryCharacter(char_id="C002", name="李四"),
        ],
        events=[
            StoryEvent(event_id="CH01E001", summary="张三归乡", actors=["C001"], beat_type="铺垫", dramatic_weight=2),
            StoryEvent(event_id="CH01E002", summary="李四迎接", actors=["C001", "C002"], beat_type="冲突", dramatic_weight=4),
        ],
        quotes=[StoryQuote(quote_id="Q001", speaker="C002", original="你终于回来了。", event_id="CH01E002")],
    )


def _outline() -> AdaptationOutline:
    return AdaptationOutline(
        story_source="测试书",
        target_episodes=1,
        episode_duration_s=20,
        total_shot_budget=4,
        episodes=[
            OutlineEpisode(
                ep_number=1,
                title="第1集",
                event_ids=["CH01E001", "CH01E002"],
                shot_budget=4,
                target_duration_s=20,
                emotion_arc="铺垫→冲突",
            )
        ],
    )


def _decision() -> AdaptationDecision:
    return AdaptationDecision(
        ep_number=1,
        title="第1集",
        event_ids=["CH01E001", "CH01E002"],
        target_shots=4,
        target_duration_s=20.0,
        emotion_arc="铺垫→冲突",
    )


def test_deterministic_checks_catch_all_rule_violations():
    book = _book()
    decision = _decision()
    script = EpisodeScript(
        ep_number=1,
        title="坏稿",
        characters_present=["C001", "C002"],
        scenes=[
            ScriptScene(
                scene_no=1,
                event_ids=["CH01E001"],
                summary="张三归乡",
                dialogue=[ScriptLine(speaker="陌生人", text="这是一句超长台词" + "啊" * 100)],
                shot_count=9,
                duration_s=30.0,
            ),
            ScriptScene(scene_no=2, event_ids=[], summary="", narration="", shot_count=1),
        ],
    )
    issues = deterministic_checks(script, book, decision)
    codes = {i.code for i in issues}
    assert "unknown_speaker" in codes
    assert "dialogue_too_long" in codes
    assert "shot_budget_exceeded" in codes
    assert "coverage_gap" in codes
    assert "empty_scene" in codes
    # 每一条问题都带 scope（可定位到场）
    assert all(i.scope for i in issues)
    assert any(i.scene_no == 1 for i in issues)


def test_deterministic_checks_pass_on_clean_script():
    book = _book()
    decision = _decision()
    script = EpisodeScript(
        ep_number=1,
        characters_present=["C001", "C002"],
        scenes=[
            ScriptScene(
                scene_no=1,
                event_ids=["CH01E001"],
                summary="张三归乡",
                narration="张三归乡",
                dialogue=[ScriptLine(speaker="C001", text="我回来了。")],
                shot_count=2,
                duration_s=10.0,
            ),
            ScriptScene(
                scene_no=2,
                event_ids=["CH01E002"],
                summary="李四迎接",
                narration="李四迎接",
                dialogue=[ScriptLine(speaker="C002", text="你终于回来了。")],
                shot_count=2,
                duration_s=10.0,
            ),
        ],
    )
    assert deterministic_checks(script, book, decision) == []


def test_revise_only_touches_flagged_scenes():
    book = _book()
    decision = _decision()
    clean = ScriptScene(scene_no=3, summary="过渡", narration="过渡旁白", shot_count=1)
    script = EpisodeScript(
        ep_number=1,
        characters_present=["C001", "C002"],
        scenes=[
            ScriptScene(scene_no=1, summary="场一", narration="场一", shot_count=2),
            ScriptScene(scene_no=2, summary="场二", narration="场二", shot_count=2),
            clean,
        ],
    )
    revised = revise_episode_script(
        script,
        [ReviewIssue(code="unknown_speaker", message="x", scope="scene:1", scene_no=1)],
        book,
        decision,
    )
    # 场 2/3 原样复用（对象级同一性）
    assert revised.scenes[1] is script.scenes[1]
    assert revised.scenes[2] is clean


async def test_three_layer_review_fails_then_fixes_only_flagged_scenes():
    book = _book()
    outline = _outline()
    bad_script = {
        "title": "坏稿",
        "scenes": [
            {
                "scene_no": 1,
                "location": "老宅",
                "event_ids": ["CH01E001"],
                "summary": "张三归乡",
                "narration": "张三归乡",
                "dialogue": [{"speaker": "陌生人", "text": "超长台词" + "啊" * 100, "emotion": ""}],
                "shot_count": 5,
                "duration_s": 10.0,
            },
            {
                "scene_no": 2,
                "location": "院子",
                "event_ids": [],
                "summary": "空场",
                "narration": "",
                "dialogue": [],
                "shot_count": 2,
                "duration_s": 5.0,
            },
            {
                "scene_no": 3,
                "location": "",
                "event_ids": [],
                "summary": "过渡",
                "narration": "过渡旁白",
                "dialogue": [],
                "shot_count": 1,
                "duration_s": 5.0,
            },
        ],
    }

    async def fake_llm(*, messages, max_tokens=2048, **kwargs):
        prompt = messages[-1]["content"]
        if "短剧编剧" in prompt:
            return {"content": json.dumps(bad_script, ensure_ascii=False)}
        return {"content": json.dumps({"issues": [], "score": 95})}

    log = await review_episode(book, outline, 1, llm=fake_llm, max_rounds=2)
    assert log.rounds[0].passed is False
    first_codes = {i.code for i in log.rounds[0].issues}
    assert {"unknown_speaker", "dialogue_too_long", "shot_budget_exceeded", "coverage_gap"} <= first_codes
    # 第二轮通过
    assert log.rounds[1].passed is True
    assert log.final_score >= 80
    # 只改了问题场：干净的场 3 不在 diff 里
    changed = {d["scene_no"] for d in log.rounds[1].scene_diffs}
    assert 3 not in changed
    assert 1 in changed
    # 补场覆盖了缺失事件
    assert "CH01E002" in log.script.covered_event_ids()
    # 镜头数落回预算内
    assert log.script.total_shots() <= 4


async def test_three_layer_review_without_llm_uses_deterministic_template():
    book = _book()
    outline = _outline()
    log = await review_episode(book, outline, 1, llm=None, max_rounds=1)
    assert log.script is not None
    assert "CH01E001" in log.script.covered_event_ids()
    assert "CH01E002" in log.script.covered_event_ids()
    assert log.rounds[0].passed is True


async def test_write_review_log_roundtrip(tmp_path: Path):
    book = _book()
    outline = _outline()
    log = await run_three_layer_review(book, outline, llm=None, max_rounds=1)
    out = write_review_log(log, tmp_path / "review_log.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["target_episodes"] == 1
    assert len(data["episodes"]) == 1
    assert data["episodes"][0]["rounds"]


async def test_llm_qualitative_error_triggers_single_scene_llm_revision():
    """P4: LLM 监督给出 severity=error 定性问题进硬门，执行层只针对该场调用 LLM（断言 prompt 只含该场）后通过。"""
    book = _book()
    outline = _outline()

    initial_script = {
        "title": "第1集",
        "scenes": [
            {
                "scene_no": 1,
                "location": "老宅",
                "event_ids": ["CH01E001"],
                "summary": "张三归乡",
                "narration": "张三归乡",
                "dialogue": [{"speaker": "张三", "text": "我终于回来了。", "emotion": "感慨"}],
                "shot_count": 2,
                "duration_s": 10.0,
            },
            {
                "scene_no": 2,
                "location": "门庭",
                "event_ids": ["CH01E002"],
                "summary": "李四迎接",
                "narration": "李四迎接",
                "dialogue": [{"speaker": "李四", "text": "你终于回来了。", "emotion": "欣喜"}],
                "shot_count": 2,
                "duration_s": 10.0,
            },
        ],
    }

    revision_prompts: list[str] = []
    supervisor_round = 0

    async def fake_llm(*, messages, max_tokens=2048, **kwargs):
        nonlocal supervisor_round
        prompt = messages[-1]["content"]
        # 1. 初始剧本生成
        if "短剧编剧" in prompt:
            return {"content": json.dumps(initial_script, ensure_ascii=False)}
        # 2. 监督层
        if "短剧审稿人" in prompt:
            supervisor_round += 1
            if supervisor_round == 1:
                # 首轮给出定性 error，直指第 1 场
                return {
                    "content": json.dumps(
                        {
                            "issues": [
                                {
                                    "scene_no": 1,
                                    "code": "llm:broken_arc",
                                    "message": "张三内心动机铺垫单薄，情绪转折突兀",
                                    "severity": "error",
                                }
                            ],
                            "score": 75,
                        },
                        ensure_ascii=False,
                    )
                }
            # 第二轮审稿通过
            return {"content": json.dumps({"issues": [], "score": 95}, ensure_ascii=False)}
        # 3. 执行层精修指定场
        if "短剧剧本精修师" in prompt:
            revision_prompts.append(prompt)
            return {
                "content": json.dumps(
                    {
                        "scene_no": 1,
                        "location": "老宅正堂",
                        "summary": "张三睹物思人，下定决心回归重整家业",
                        "narration": "老宅依旧，但张三的心境已大不相同。",
                        "dialogue": [
                            {"speaker": "张三", "text": "这一别十年，我定不再逃避。", "emotion": "坚定"}
                        ],
                        "shot_count": 2,
                        "duration_s": 10.0,
                    },
                    ensure_ascii=False,
                )
            }
        return {"content": "{}"}

    log = await review_episode(book, outline, 1, llm=fake_llm, max_rounds=2)

    # 断言首轮失败（被 LLM 定性 error 拦截）
    assert log.rounds[0].passed is False
    assert any(i.code == "llm:broken_arc" and i.severity == "error" for i in log.rounds[0].issues)

    # 断言执行层精修针对性调用 LLM
    assert len(revision_prompts) == 1
    rev_prompt = revision_prompts[0]
    assert "第 1 场" in rev_prompt
    assert "llm:broken_arc" in rev_prompt
    # 严格断言 prompt 只含被点名的第 1 场，不包含未点名的第 2 场
    assert "第 2 场" not in rev_prompt
    assert "李四迎接" not in rev_prompt

    # 断言第二轮通过
    assert log.rounds[1].passed is True
    assert log.final_score >= 80

    # 断言 revised_scenes 准确记录实际被修改的场
    assert log.rounds[1].revised_scenes == [1]
    assert "llm:broken_arc" in log.rounds[1].trigger_issue_codes

    # 断言未点名场对象/哈希不变
    diff_scenes = [d["scene_no"] for d in log.rounds[1].scene_diffs]
    assert diff_scenes == [1]


def test_script_to_storyboard_structure_and_shot_plans():
    """P3: 验证从 EpisodeScript 派生镜头级分镜，满足预算与 ShotPlan 转换。"""
    book = _book()
    outline = _outline()
    script = EpisodeScript(
        ep_number=1,
        title="第1集",
        characters_present=["C001", "C002"],
        scenes=[
            ScriptScene(
                scene_no=1,
                location="老宅",
                event_ids=["CH01E001"],
                summary="张三归乡",
                narration="张三归乡",
                dialogue=[ScriptLine(speaker="张三", text="我回来了。")],
                shot_count=2,
                duration_s=10.0,
            ),
            ScriptScene(
                scene_no=2,
                location="庭院",
                event_ids=["CH01E002"],
                summary="李四迎接",
                narration="李四迎接",
                dialogue=[ScriptLine(speaker="李四", text="你终于回来了。")],
                shot_count=2,
                duration_s=10.0,
            ),
        ],
    )
    outline_ep = outline.episodes[0]
    sb = script_to_storyboard(script, book, outline_ep=outline_ep)

    assert isinstance(sb, EpisodeStoryboard)
    assert sb.ep_number == 1
    assert sb.total_shots() == 4
    assert sb.total_shots() <= outline_ep.shot_budget
    assert sb.total_duration() == pytest.approx(20.0, rel=1e-2)

    known_events = {e.event_id for e in book.events}
    for shot in sb.shots:
        assert shot.event_id in known_events
        assert shot.image_prompt
        assert shot.duration_s > 0

    shot_plans = sb.to_shot_plans()
    assert len(shot_plans) == 4
    assert shot_plans[0].shot_id == sb.shots[0].shot_id
    assert shot_plans[0].image_prompt == sb.shots[0].image_prompt
    assert shot_plans[0].tts_text == sb.shots[0].tts_text


async def test_plan_longform_drama_pipeline(tmp_path: Path):
    """P3: 验证短剧长篇规划全链路：长篇文本 → 事件图 → 大纲 → 审稿 → 分镜落盘。"""
    novel_text = """
第1章 归乡之日
张三历经沧桑回到故乡祖屋，残阳洒在老宅门扉上。

第2章 故人重逢
李四在庭院里迎出，两人的目光在暮色中交汇。
"""
    plan = await plan_longform_drama(
        "测试小说",
        novel_text,
        target_episodes=2,
        episode_duration_s=30.0,
        llm=None,
    )
    assert plan.target_episodes == 2
    assert plan.review_log.passed is True
    assert len(plan.storyboards) == 2
    for sb in plan.storyboards:
        assert sb.total_shots() <= 6
        assert len(sb.shots) == sb.total_shots()

    paths = plan.save(tmp_path / "plan_out")
    assert paths["event_graph"].exists()
    assert paths["adaptation_outline"].exists()
    assert paths["review_log"].exists()
    assert paths["storyboard_ep01"].exists()
    assert paths["storyboard_ep02"].exists()
