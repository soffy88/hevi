"""镜头准备台测试(补 INC-001 缺失的候选确认工作流)。"""

from __future__ import annotations

from hevi.season_planner.preparation import (
    ShotPreparation,
    build_shot_preparation,
    confirm_candidate,
    extract_asset_candidates,
    extract_dialogue_candidates,
    infer_action_beats,
    read_preparation,
    upsert_preparation,
)

# ── 动作节拍推断(零成本确定性) ─────────────────────────────────────────────


def test_infer_action_beats_three_stage():
    text = (
        "王生听到洞外突然传来咆哮声,猛然回头。"
        "他冲向洞口,挥刀砍向黑影,爆发一声怒吼。"
        "黑影倒地,他跪在火堆旁,久久沉默。"
    )
    beats = infer_action_beats(text)
    assert "听到" in beats["trigger"] or "猛然" in beats["trigger"]
    assert "冲向" in beats["peak"] or "挥刀" in beats["peak"]
    assert "倒地" in beats["aftermath"] or "久久" in beats["aftermath"]


def test_infer_action_beats_single_sentence():
    beats = infer_action_beats("他走了。")
    assert beats["trigger"] == beats["peak"] == beats["aftermath"] == "他走了"


def test_infer_action_beats_empty():
    assert infer_action_beats("") == {"trigger": "", "peak": "", "aftermath": ""}


# ── 资产/对白候选提取 ──────────────────────────────────────────────────────


def test_extract_asset_candidates():
    text = "王生手持一把短刀,腰佩令牌,走进山洞。突然火光一闪,他举起火把照向石壁。"
    cands = extract_asset_candidates(
        text=text, known_characters=["王生"], known_scenes=["山洞"]
    )
    types = {c["type"] for c in cands}
    names = [c["name"] for c in cands]
    assert "character" in types and "王生" in names
    assert "scene" in types and "山洞" in names
    assert "prop" in types  # 短刀/火把
    assert all(c["status"] == "pending" for c in cands)


def test_extract_dialogue_candidates():
    text = '他说:"今晚就走。"师父低声道:"天冷,多穿些。"'
    dlgs = extract_dialogue_candidates(text)
    assert len(dlgs) >= 2
    assert all(d["status"] == "pending" for d in dlgs)


# ── 状态机与确认 ───────────────────────────────────────────────────────────


def test_build_preparation_status():
    text = "王生听到动静,突然回头。他冲向洞口,抽出短刀。黑影倒地,他长叹一声。"
    prep = build_shot_preparation(
        script_excerpt=text, known_characters=["王生"]
    )
    assert prep.status == "pending"
    assert prep.pending_count > 0
    assert prep.action_beats["trigger"]
    assert prep.action_beats["peak"]
    assert prep.action_beats["aftermath"]


def test_build_preparation_ready_when_nothing_to_confirm():
    # 无资产/对白候选 → 直接 ready(明确跳过提取,Jellyfish 同语义)
    prep = build_shot_preparation(script_excerpt="一段没有实体和引语的普通描述。")
    assert prep.status == "ready"
    assert prep.ready is True


def test_confirm_candidate_accept_then_ready():
    prep = ShotPreparation(
        candidates=[
            {"id": "prop_0", "type": "prop", "name": "短刀", "status": "pending"}
        ]
    )
    confirm_candidate(prep, candidate_id="prop_0", decision="accept")
    assert prep.candidates[0]["status"] == "accepted"
    # accept 道具 → 实体链接
    assert prep.entity_links == [{"type": "prop", "name": "短刀", "linked": True}]
    assert prep.pending_count == 0
    assert prep.status == "ready"


def test_confirm_candidate_ignore_still_ready():
    prep = ShotPreparation(
        candidates=[{"id": "p0", "type": "prop", "name": "火把", "status": "pending"}]
    )
    confirm_candidate(prep, candidate_id="p0", decision="ignore")
    assert prep.candidates[0]["status"] == "ignored"
    assert prep.entity_links == []  # ignore 不建链接
    assert prep.status == "ready"


# ── 存储往返(selection_json 子字段,零迁移) ─────────────────────────────────


def test_preparation_roundtrip_via_selection_json():
    prep = build_shot_preparation(
        script_excerpt="王生听到动静。他抽刀冲向洞口。黑影倒地。",
        known_characters=["王生"],
    )
    row = {"id": "shot-1", "shot_index": 0, "status": "completed", "selection_json": {}}
    upsert_preparation(row, prep)
    assert row["selection_json"]["preparation"]["status"] == "pending"
    restored = read_preparation(row)
    assert restored is not None
    assert restored.pending_count == prep.pending_count
    assert restored.action_beats == prep.action_beats
    assert restored.candidates == prep.candidates
