"""INC-001 §A/§G/§I 逐镜头准备台服务层——纯逻辑单测(就绪重算/候选物化/聚合)。

SQL 包装层(extract/confirm/skip)在 director_pipeline 端点测试里以 mock pool 验证交互,
此处只测不碰 DB 的纯逻辑,因为 §A.1 就绪状态机是本特性的正确性核心。
"""

from __future__ import annotations

from hevi.director.pipeline_schemas import ShotListDialogueLine, ShotListItem
from hevi.director.shot_preparation import (
    build_preparation_state,
    candidates_from_shot,
    compute_readiness_status,
)

# ── §A.1 就绪重算 ────────────────────────────────────────────────────────────


def test_readiness_skip_extraction_forces_ready():
    """规则1:skip_extraction → ready,即便有 pending 候选。"""
    assert (
        compute_readiness_status(
            skip_extraction=True,
            extracted=False,
            asset_statuses=["pending"],
            dialogue_statuses=["pending"],
        )
        == "ready"
    )


def test_readiness_never_extracted_is_pending():
    """规则2:从未提取过 → pending。"""
    assert (
        compute_readiness_status(
            skip_extraction=False, extracted=False, asset_statuses=[], dialogue_statuses=[]
        )
        == "pending"
    )


def test_readiness_extracted_but_no_candidates_is_ready():
    """规则3:提取过但无任何候选(空镜)→ ready。"""
    assert (
        compute_readiness_status(
            skip_extraction=False, extracted=True, asset_statuses=[], dialogue_statuses=[]
        )
        == "ready"
    )


def test_readiness_all_confirmed_is_ready():
    """规则4:资产 ∈{linked,ignored} 且 对白 ∈{accepted,ignored} → ready。"""
    assert (
        compute_readiness_status(
            skip_extraction=False,
            extracted=True,
            asset_statuses=["linked", "ignored"],
            dialogue_statuses=["accepted", "ignored"],
        )
        == "ready"
    )


def test_readiness_any_pending_candidate_blocks():
    """铁律:任一候选仍 pending → 不能 ready。"""
    assert (
        compute_readiness_status(
            skip_extraction=False,
            extracted=True,
            asset_statuses=["linked", "pending"],
            dialogue_statuses=["accepted"],
        )
        == "pending"
    )
    assert (
        compute_readiness_status(
            skip_extraction=False,
            extracted=True,
            asset_statuses=["linked"],
            dialogue_statuses=["pending"],
        )
        == "pending"
    )


def test_readiness_extracted_only_assets_no_dialogue_ready():
    """例外:提取后无对白候选(无对白镜)不阻塞 ready。"""
    assert (
        compute_readiness_status(
            skip_extraction=False,
            extracted=True,
            asset_statuses=["linked"],
            dialogue_statuses=[],
        )
        == "ready"
    )


# ── §G 候选物化 ─────────────────────────────────────────────────────────────


def test_candidates_from_shot_materializes_assets_and_dialogue():
    shot = ShotListItem(
        shot_id="SH001",
        scene_no=1,
        scene_name="宫殿",
        character_names=["智伯", "韩康子", "智伯"],  # 重复应去重
        prop_names=["玉玦"],
        dialogue_lines=[
            ShotListDialogueLine(character_name="智伯", text="把地给我。", target_name="韩康子"),
            ShotListDialogueLine(character_name="", text="  "),  # 空文本应跳过
        ],
    )
    assets, dialogue = candidates_from_shot(shot)
    assert ("character", "智伯") in assets
    assert ("character", "韩康子") in assets
    assert assets.count(("character", "智伯")) == 1  # 去重
    assert ("scene", "宫殿") in assets
    assert ("prop", "玉玦") in assets
    assert len(dialogue) == 1  # 空文本行被跳过
    assert dialogue[0]["speaker_name"] == "智伯"
    assert dialogue[0]["target_name"] == "韩康子"  # §H
    assert dialogue[0]["line_index"] == 0


def test_candidates_from_shot_empty_scene_and_dialogue():
    shot = ShotListItem(shot_id="SH002", scene_no=1)
    assets, dialogue = candidates_from_shot(shot)
    assert assets == []
    assert dialogue == []


# ── §L.1 聚合准备态 ─────────────────────────────────────────────────────────


def test_build_preparation_state_counts_pending_and_ready_flag():
    readiness = {
        "shot_id": "SH001",
        "status": "pending",
        "skip_extraction": False,
        "extracted": True,
    }
    asset_rows = [
        {
            "id": "a1",
            "candidate_type": "character",
            "candidate_name": "智伯",
            "candidate_status": "linked",
        },
        {
            "id": "a2",
            "candidate_type": "scene",
            "candidate_name": "宫殿",
            "candidate_status": "pending",
        },
    ]
    dialogue_rows = [
        {"id": "d1", "line_index": 0, "text": "把地给我。", "candidate_status": "accepted"},
        {"id": "d2", "line_index": 1, "text": "不给。", "candidate_status": "pending"},
    ]
    state = build_preparation_state(
        shot=None, readiness=readiness, asset_rows=asset_rows, dialogue_rows=dialogue_rows
    )
    assert state["pending_confirm_count"] == 2  # 1 asset + 1 dialogue pending
    assert state["ready_for_generation"] is False
    assert len(state["saved_dialogue_lines"]) == 1  # 只 accepted 那条
    assert state["saved_dialogue_lines"][0]["id"] == "d1"


def test_build_preparation_state_ready_when_status_ready():
    readiness = {"shot_id": "SH001", "status": "ready", "skip_extraction": True, "extracted": False}
    state = build_preparation_state(shot=None, readiness=readiness, asset_rows=[], dialogue_rows=[])
    assert state["ready_for_generation"] is True
    assert state["pending_confirm_count"] == 0
    assert state["skip_extraction"] is True
