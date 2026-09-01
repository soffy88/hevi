"""烁皓 B1/D1/P1/P2 确定性门。"""

from __future__ import annotations

from hevi.director.pipeline_schemas import (
    SceneBeat,
    SceneStage,
    SceneStageSet,
    ShotList,
    ShotListDialogueLine,
    ShotListItem,
)
from hevi.director.shuohao_gates import lint_shuohao_storyboard


def _shot(**kw) -> ShotListItem:
    data = {"shot_id": "SH1", "scene_no": 1, "duration_s": 4.0}
    data.update(kw)
    return ShotListItem(**data)


def _stage(*beat_ids: str) -> SceneStageSet:
    beats = [SceneBeat(beat_id=bid, order=i) for i, bid in enumerate(beat_ids, start=1)]
    return SceneStageSet(stages=[SceneStage(scene_ref=1, beats=beats)])


def test_b1_accepts_exact_claim() -> None:
    sl = ShotList(
        shots=[
            _shot(beat_range=["a"]),
            _shot(shot_id="SH2", beat_range=["b"]),
        ]
    )
    assert lint_shuohao_storyboard(sl, _stage("a", "b")) == []


def test_b1_flags_gap_and_skips_unlinked() -> None:
    sl = ShotList(shots=[_shot(beat_range=["a"])])
    rules = {f.rule for f in lint_shuohao_storyboard(sl, _stage("a", "b"))}
    assert rules == {"B1"}
    # 没接场事实 / 镜头没认领 → inert
    assert lint_shuohao_storyboard(ShotList(shots=[_shot()]), _stage("a")) == []
    assert lint_shuohao_storyboard(sl, None) == []


def test_d1_flags_dialogue_overflow() -> None:
    sl = ShotList(
        shots=[
            _shot(
                duration_s=2.0,
                dialogue_lines=[ShotListDialogueLine(character_name="甲", text="字" * 20)],
            )
        ]
    )
    findings = lint_shuohao_storyboard(sl)
    assert {f.rule for f in findings} == {"D1"}


def test_p2_flags_second_line_not_in_d_block() -> None:
    sl = ShotList(
        shots=[
            _shot(
                duration_s=5.0,
                character_names=["甲"],
                dialogue_lines=[
                    ShotListDialogueLine(character_name="甲", text="先说这句"),
                    ShotListDialogueLine(character_name="甲", text="再说一句就会丢"),
                ],
            )
        ]
    )
    rules = {f.rule for f in lint_shuohao_storyboard(sl)}
    assert "P2" in rules


def test_p1_compiled_segment_alignment_passes() -> None:
    sl = ShotList(
        shots=[
            _shot(duration_s=3.0, character_names=["甲"]),
            _shot(shot_id="SH2", duration_s=4.0, character_names=["甲"]),
        ]
    )
    assert [f.rule for f in lint_shuohao_storyboard(sl) if f.rule == "P1"] == []
