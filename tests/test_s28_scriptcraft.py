"""S28：剧本层（立项 / 人物 / 因果 / 可拍 / 短剧 / 短片 / 三轮审稿）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hevi.ai_drama import rules as drama_rules
from hevi.ai_drama.cost_gate import build_plan
from hevi.ai_drama.schema import normalize_script
from hevi.api.main import app
from hevi.auth.dependencies import get_current_user
from hevi.scriptcraft.causality import check_causality
from hevi.scriptcraft.characters import check_characters
from hevi.scriptcraft.filmability import check_filmability
from hevi.scriptcraft.names import blacklist_names, pick_names
from hevi.scriptcraft.premise import evaluate_premise
from hevi.scriptcraft.review import apply_selected, review_document
from hevi.scriptcraft.shortdrama import plan_short_drama
from hevi.scriptcraft.shortfilm import build_short_film

DRAMA_TOPICS = (
    ("离婚冷静期最后一天，她把公司公章缝进婚纱", "都市复仇"),
    ("外卖骑手救下坠楼孩子，监控却显示他推了人", "现实悬疑"),
)
FILM_TOPICS = (
    ("养老院最会唱戏的老人，把最后一场戏演给空椅子", "家庭剧情"),
    ("深夜自习室，最后一个学生发现管理员每天都在重复同一天", "悬疑"),
)


def test_premise_gate_blocks_and_offers_three_alternates() -> None:
    bad = evaluate_premise(topic="一个很酷的故事", slots={}, questions={})
    assert bad["verdict"] == "change_topic"
    assert len(bad["alternates"]) == 3
    assert bad["must_fix"]

    good = evaluate_premise(
        topic="便利店夜班",
        slots={
            "protagonist": "被裁员后去便利店上夜班的前白领",
            "trigger": "收到一张五年前的小票",
            "goal": "在店长回来前查清小票是谁留下的",
            "stakes": "被当成小偷带走，失去最后的住处",
        },
        questions={
            "genre": "都市悬疑",
            "identification": "被生活压到角落的普通人",
            "strongest_conflict": "小票指向店长，但店长掌握排班",
            "best_payoff": "当众调出监控",
            "secret_reversal": "小票是店长自己留的",
            "route": "悬疑",
        },
    )
    assert good["verdict"] == "pass"
    assert good["one_line"].startswith("一个【")


def test_name_blacklist_and_distinct_surnames() -> None:
    findings = check_characters([
        {"id": "c1", "name": "苏念念", "role": "主角", "bio": "x", "relations": [{"target": "陆景琛"}],
         "arc": "从怕到敢", "defect": "太相信白纸黑字", "visual_markers": ["左手旧疤"]},
        {"id": "c2", "name": "林晚", "role": "反派", "bio": "x", "relations": [{"target": "苏念念"}],
         "arc": "从赢到输", "defect": "傲慢", "visual_markers": ["黑手套"]},
    ])
    rules = {f["rule"] for f in findings if f["severity"] == "must"}
    assert "N-BLACKLIST" in rules or "N-SURNAME" in rules
    names = pick_names("任意一个主题", 4)
    assert len({name[0] for name in names}) == 4
    assert not (set(names) & blacklist_names())


def test_causality_requires_but_or_so() -> None:
    bad = check_causality(["他被开除", "他去送外卖", "他回到公司", "他打开门"])
    assert not bad["passed"]
    assert any(f["rule"] == "X-RATIO" for f in bad["findings"])
    good = check_causality([
        "他被开除",
        {"connector": "所以", "event": "他去送外卖"},
        {"connector": "但是", "event": "前老板点了他的单"},
        {"connector": "所以", "event": "他拿到拖欠的工资"},
    ])
    assert good["passed"] and good["causal_ratio"] == 1.0


def _mini_script() -> dict:
    return {
        "characters": [
            {"id": "c1", "name": "周青禾", "role": "主角", "state": {"pose": "坐", "location": "办公室"},
             "bio": "x", "relations": [{"target": "程见川"}], "arc": "从怕到敢",
             "defect": "用沉默换体面", "visual_markers": ["左手旧疤"]},
            {"id": "c2", "name": "程见川", "role": "反派", "bio": "x", "relations": [{"target": "周青禾"}],
             "arc": "从赢到输", "defect": "傲慢", "visual_markers": ["黑手套"]},
        ],
        "props": [{"name": "公章"}],
        "scenes": [{
            "scene_id": "sc_01", "location": "办公室", "characters_present": ["c1", "c2", "c3", "c4", "c5"],
            "beats": [{
                "beat_id": "sc_01_b01",
                "action": ["△ 周青禾坐到椅子上。", "△ 周青禾很委屈。", "△ 周青禾把手按在公章上。"],
                "dialogue": [{"speaker": "周青禾", "kind": "said", "text": "我今天必须把这件事说清楚否则谁都别想走", "duration_s": 1.0}],
            }],
        }],
    }


def test_filmability_catches_state_emotion_duration_prop_and_crowd() -> None:
    report = check_filmability(_mini_script())
    rule_names = {f["rule"] for f in report["findings"] if f["severity"] == "must"}
    assert "F-STATE" in rule_names
    assert "F-EMOTION" in rule_names
    assert "F-DURATION" in rule_names
    assert "F-PROP-SIZE" in rule_names
    assert "F-CROWD" in rule_names
    assert not report["passed"]


@pytest.mark.parametrize(("topic", "genre"), DRAMA_TOPICS)
def test_short_drama_plan_passes_checks_and_ai_drama_rules(topic: str, genre: str) -> None:
    plan = plan_short_drama(topic=topic, genre=genre, confirm=True)
    assert plan["premise_gate"]["verdict"] == "pass"
    assert plan["gate"]["confirmed"] is True
    assert plan["checks"]["passed"], plan["checks"]["must_count"]
    assert plan["checks"]["must_count"] == 0
    assert len(plan["episode_outline"]) == 10
    assert 5 <= len(plan["ep1_beat_sheet"]) <= 8
    assert plan["review"]["summary"]["must"] == 0

    script = normalize_script(plan["script"])
    blockers = [
        f for f in drama_rules.check_script(script) if f["severity"] == "blocker"
    ]
    assert blockers == []
    assert script["hook"]["first_3s_conflict"]
    assert all(scene["lighting"]["direction"] for scene in script["scenes"])
    characters = script["characters"]
    assert len({c["name"][0] for c in characters}) == len(characters)
    assert all(c["defect"] and c["arc"] and 1 <= len(c["visual_markers"]) <= 3 for c in characters)


@pytest.mark.parametrize(("topic", "genre"), FILM_TOPICS)
def test_short_film_passes_and_is_closed(topic: str, genre: str) -> None:
    plan = build_short_film(topic=topic, genre=genre, confirm=True)
    assert plan["premise_gate"]["verdict"] == "pass"
    assert plan["checks"]["passed"], plan["checks"]["must_count"]
    assert len(plan["master_plan"]["seven_steps"]) == 7
    assert 2 <= len(plan["master_plan"]["reversals"]) <= 3
    assert plan["master_plan"]["motif"]["count"] == 3
    assert plan["master_plan"]["ending"]
    assert plan["review"]["summary"]["must"] == 0
    assert len(plan["scenes"]) >= 7
    assert all(s["step"] for s in plan["scenes"])


def test_review_applies_only_selected_findings() -> None:
    document = {
        "characters": [{"name": "周青禾", "role": "主角", "defect": "x", "arc": "从怕到敢",
                        "visual_markers": ["旧疤"], "relations": [{"target": "程见川"}]}],
        "scenes": [{"scene_id": "sc_01", "characters_present": ["周青禾"], "beats": [{
            "beat_id": "sc_01_b01",
            "action": ["△ 周青禾仿佛被定住。"],
            "dialogue": [{"speaker": "周青禾", "kind": "said", "text": "其实我早就知道了。", "duration_s": 3.0}],
        }]}],
    }
    review = review_document(document, mode="short_drama")
    net = next(f for f in review["findings"] if f["code"] == "W-NET-LIT")
    applied = apply_selected(document, review, [net["id"]])
    text = applied["scenes"][0]["beats"][0]["action"][0]
    assert "仿佛" not in text
    assert "其实" in applied["scenes"][0]["beats"][0]["dialogue"][0]["text"]
    assert applied["review_applied"] == [net["id"]]


def test_short_film_is_a_gated_sub_option_of_drama() -> None:
    from hevi.studio.formats import FORMAT_BY_ID

    for format_id in ("live_drama", "comic_drama"):
        styles = {style.id: style for style in FORMAT_BY_ID[format_id].styles}
        assert "short_film" in styles or "anime_short_film" in styles
        style = styles.get("short_film") or styles.get("anime_short_film")
        assert style is not None and style.gated is True
        assert style.line_id == "ai_drama"


def test_runninghub_credit_wording_is_platform_page() -> None:
    plan = build_plan({"segments": [{"shots": [{"duration_s": 5}]}]}, provider="runninghub_h3")
    assert "平台页面为准" in plan["credits_unit"]
    assert "不充值" in plan["credits_unit"]


@pytest.fixture
def s28_client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: {"id": "s28-test"}
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_api_scriptcraft_contract(s28_client: TestClient) -> None:
    blacklist = s28_client.get("/api/studio/scriptcraft/name-blacklist")
    assert blacklist.status_code == 200
    assert blacklist.json()["total"] > 0

    premise = s28_client.post(
        "/api/studio/scriptcraft/premise",
        json={
            "topic": "便利店夜班",
            "slots": {
                "protagonist": "被裁员的前白领",
                "trigger": "收到一张五年前的小票",
                "goal": "在店长回来前查清小票是谁的",
                "stakes": "被当成小偷带走",
            },
            "questions": {
                "genre": "悬疑", "identification": "普通人", "strongest_conflict": "店长掌握排班",
                "best_payoff": "调出监控", "secret_reversal": "小票是店长留的", "route": "悬疑",
            },
        },
    )
    assert premise.status_code == 200, premise.text
    assert premise.json()["verdict"] == "pass"

    drama = s28_client.post(
        "/api/studio/scriptcraft/short-drama/plan",
        json={"topic": "外卖骑手救下坠楼孩子，监控却显示他推了人", "genre": "现实悬疑", "confirm": True},
    )
    assert drama.status_code == 200, drama.text
    body = drama.json()
    assert body["checks"]["passed"]
    assert body["script"]["scenes"]

    film = s28_client.post(
        "/api/studio/scriptcraft/short-film/plan",
        json={"topic": "深夜自习室，最后一个学生发现管理员每天都在重复同一天", "confirm": True},
    )
    assert film.status_code == 200, film.text
    assert film.json()["checks"]["passed"]

    review = s28_client.post(
        "/api/studio/scriptcraft/review",
        json={"document": body["script"], "mode": "short_drama"},
    )
    assert review.status_code == 200, review.text
    assert "rounds" in review.json()
