"""C4 分镜 + G4 硬规则门测试。"""

from __future__ import annotations

import pytest

from hevi.cinematic.schemas import Beat, BeatDialogue, Scene
from hevi.cinematic.shot_planning import gate_shotlist, plan_shots


@pytest.mark.asyncio
async def test_dialogue_beat_becomes_single_speaker_medium_close_shot():
    scene = Scene(
        scene_id="SC01",
        characters=["a"],
        beats=[Beat(beat_id="B1", dialogue=BeatDialogue(speaker="a", text="你好。"))],
    )
    shotlist = await plan_shots(scene)
    assert len(shotlist.shots) == 1
    shot = shotlist.shots[0]
    assert shot.shot_size == "medium_close"
    assert shot.on_screen == ["a"]
    assert shot.dialogue_inline.text == "你好。"


@pytest.mark.asyncio
async def test_narration_beat_becomes_wide_establishing_shot_with_all_characters():
    scene = Scene(scene_id="SC01", characters=["a", "b"], beats=[Beat(beat_id="B1", action="远景")])
    shotlist = await plan_shots(scene)
    assert len(shotlist.shots) == 1
    shot = shotlist.shots[0]
    assert shot.shot_size == "wide"
    assert set(shot.on_screen) == {"a", "b"}


@pytest.mark.asyncio
async def test_two_person_close_shot_auto_splits_into_shot_reverse_shot():
    """one clean face rule 的核心测试:硬塞 2 人进 medium_close 必须被自动拆开,
    不能让两张脸同时出现在非 wide/full 的镜头里。"""
    scene = Scene(
        scene_id="SC01",
        characters=["a", "b"],
        beats=[
            Beat(
                beat_id="B1",
                action="对峙",
                on_screen_hint=["a", "b"],
                shot_size_hint="medium_close",
            )
        ],
    )
    shotlist = await plan_shots(scene)
    assert len(shotlist.shots) == 2
    assert [s.on_screen for s in shotlist.shots] == [["a"], ["b"]]
    for s in shotlist.shots:
        assert s.shot_size == "medium_close"


@pytest.mark.asyncio
async def test_wide_shot_allows_multiple_people_without_splitting():
    scene = Scene(
        scene_id="SC01",
        characters=["a", "b", "c"],
        beats=[
            Beat(beat_id="B1", action="全景", on_screen_hint=["a", "b", "c"], shot_size_hint="wide")
        ],
    )
    shotlist = await plan_shots(scene)
    assert len(shotlist.shots) == 1
    assert set(shotlist.shots[0].on_screen) == {"a", "b", "c"}


@pytest.mark.asyncio
async def test_long_dialogue_splits_into_multiple_shots_by_sentence_count():
    scene = Scene(
        scene_id="SC01",
        characters=["a"],
        beats=[
            Beat(
                beat_id="B1",
                dialogue=BeatDialogue(speaker="a", text="第一句。第二句！第三句？第四句。"),
            )
        ],
    )
    shotlist = await plan_shots(scene)
    assert len(shotlist.shots) == 2
    assert shotlist.shots[0].dialogue_inline.text == "第一句。第二句！"
    assert shotlist.shots[1].dialogue_inline.text == "第三句？第四句。"


@pytest.mark.asyncio
async def test_beat_ids_filter_restricts_which_beats_become_shots():
    scene = Scene(
        scene_id="SC01",
        characters=["a"],
        beats=[
            Beat(beat_id="B1", action="镜头1"),
            Beat(beat_id="B2", action="镜头2,不应该出镜"),
        ],
    )
    shotlist = await plan_shots(scene, beat_ids=["B1"])
    assert len(shotlist.shots) == 1
    assert shotlist.shots[0].beat_ids == ["B1"]


@pytest.mark.asyncio
async def test_high_motion_beat_gets_shorter_duration_cap():
    scene = Scene(scene_id="SC01", characters=["a"], beats=[Beat(beat_id="B1", action="打斗")])
    shotlist = await plan_shots(scene, high_motion_beat_ids={"B1"})
    assert shotlist.shots[0].est_duration_s == 4.0


@pytest.mark.asyncio
async def test_lint_shot_prompt_blocks_identity_word_leakage():
    """SPEC-02 §11.1 规则1:身份词泄露进 shot prompt 必须 fail fast,不是警告。"""
    scene = Scene(
        scene_id="SC01",
        characters=["a"],
        beats=[Beat(beat_id="B1", action="黑袍老者缓步走来")],
    )
    with pytest.raises(ValueError, match="身份词泄露"):
        await plan_shots(
            scene,
            immutable_traits_by_character={"a": "黑袍,老者,白须"},
        )


def test_gate_shotlist_rejects_two_person_non_wide_shot():
    """双重保险:即便有 bug 绕过了 plan_shots 的自动拆分,gate_shotlist 也要能
    独立发现这条违规。"""
    from hevi.cinematic.schemas import CineShot, CineShotCamera, CineShotList

    scene = Scene(scene_id="SC01", characters=["a", "b"])
    shotlist = CineShotList(
        shots=[
            CineShot(
                shot_id="SH01",
                scene_id="SC01",
                shot_size="medium_close",
                camera=CineShotCamera(shot_size="medium_close"),
                on_screen=["a", "b"],
                est_duration_s=6.0,
            )
        ]
    )
    result = gate_shotlist(shotlist, scene)
    assert result.passed is False
    assert any("one clean face" in e for e in result.errors)


def test_gate_shotlist_rejects_duration_over_limit():
    from hevi.cinematic.schemas import CineShot, CineShotCamera, CineShotList

    scene = Scene(scene_id="SC01", characters=["a"])
    shotlist = CineShotList(
        shots=[
            CineShot(
                shot_id="SH01",
                scene_id="SC01",
                shot_size="medium_close",
                camera=CineShotCamera(shot_size="medium_close"),
                on_screen=["a"],
                est_duration_s=10.0,
            )
        ]
    )
    result = gate_shotlist(shotlist, scene)
    assert result.passed is False
