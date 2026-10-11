"""DRAMAPLAN 三层审稿测试（不调网络，用 fake LLM 响应）。

覆盖：确定性规则检查项（人物名/字数/镜头预算/覆盖率/禁忌）、首轮不通过 → 只改问题场 →
通过、未点名场原样保留、review_log 落盘结构。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    write_review_log,
)
from hevi.storygraph.schemas import (
    AdaptationOutline,
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
