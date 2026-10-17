"""人工撰稿集编译器测试(2026-07-27)。锁:声明式 spec → 正确路由讲解/演绎、反打就绪、校验拦错。"""

from __future__ import annotations

import pytest

from hevi.tongjian.authored_episode import (
    AuthoredBeat,
    AuthoredCharacter,
    AuthoredEpisode,
    compile_authored_episode,
)


def _mini(beats, locations=None, characters=None) -> AuthoredEpisode:
    return AuthoredEpisode(
        title="t",
        thesis="th",
        raw_text="raw",
        intro="今天我们回到现场",
        characters=characters
        or [
            AuthoredCharacter(id="C_a", name="甲", appearance="甲的样子"),
            AuthoredCharacter(id="C_b", name="乙", appearance="乙的样子"),
        ],
        locations=locations or {"S1": "场景一", "S2": "场景二"},
        beats=beats,
    )


def test_narration_routes_to_jiangjie_dialogue_to_drama() -> None:
    """narration 镜 characters 必须空(→讲解段);dialogue 镜落 speaker/target/在场(→演绎段)。"""
    ep = _mini(
        [
            AuthoredBeat(kind="narration", scene="S1", text="旁白", visual_prompt="一个空镜"),
            AuthoredBeat(kind="dialogue", scene="S2", speaker="C_a", target="C_b", text="你好"),
        ]
    )
    c = compile_authored_episode(ep)
    n_shot, d_shot = c.shotlist.shots
    assert c.script.lines[0].type == "narration" and n_shot.characters == []
    assert n_shot.visual_prompt == "一个空镜"
    assert c.script.lines[1].type == "dialogue" and c.script.lines[1].target == "C_b"
    assert d_shot.characters == ["C_a"]  # 默认 [speaker]


def test_debate_beats_compile_to_reverse_shot_ready() -> None:
    """同场 dialogue 互驳 → 编译后经桥接展开 master+OTS 反打(端到端结构验证,不花钱)。"""
    from hevi.director.reverse_shots import summarize_shot_sequence
    from hevi.director.tongjian_v2_bridge import build_v2_scene_script_set

    ep = _mini(
        [
            AuthoredBeat(kind="dialogue", scene="D", speaker="C_a", target="C_b", text="改。"),
            AuthoredBeat(kind="dialogue", scene="D", speaker="C_b", target="C_a", text="不改。"),
        ],
        locations={"D": "朝堂"},
    )
    c = compile_authored_episode(ep)
    sss = build_v2_scene_script_set(
        script=c.script,
        shot_list=c.shotlist,
        id_to_name={ch.character_id: ch.name for ch in c.character_bible.characters},
        drama_only=True,
    )
    types = [r["shot_type"] for r in summarize_shot_sequence(sss.scripts)]
    assert "master" in types and types.count("ots") >= 2  # 建轴 + 双方 OTS


def test_tier_and_cite_land_on_shot() -> None:
    ep = _mini(
        [
            AuthoredBeat(
                kind="commentary",
                scene="S1",
                text="臣光曰",
                visual_prompt="竹简意象",
                tier="实录",
                cite="资治通鉴·周纪二",
            )
        ]
    )
    shot = compile_authored_episode(ep).shotlist.shots[0]
    assert shot.provenance_tier == "实录" and shot.source_cite == "资治通鉴·周纪二"


def test_voices_map_by_name() -> None:
    ep = _mini(
        [AuthoredBeat(kind="dialogue", scene="S1", speaker="C_a", text="话")],
        characters=[
            AuthoredCharacter(id="C_a", name="甲", appearance="x", voice="zh-CN-YunjianNeural")
        ],
    )
    assert compile_authored_episode(ep).voices == {"甲": "zh-CN-YunjianNeural"}


def test_validation_rejects_bad_spec() -> None:
    # narration 缺 visual_prompt
    with pytest.raises(ValueError, match="visual_prompt"):
        compile_authored_episode(_mini([AuthoredBeat(kind="narration", scene="S1", text="旁白")]))
    # scene 不在 locations
    with pytest.raises(ValueError, match="locations"):
        compile_authored_episode(
            _mini([AuthoredBeat(kind="narration", scene="NOPE", text="x", visual_prompt="v")])
        )
    # dialogue speaker 不在 characters
    with pytest.raises(ValueError, match="speaker"):
        compile_authored_episode(
            _mini([AuthoredBeat(kind="dialogue", scene="S1", speaker="C_x", text="话")])
        )
    # 实录缺 cite
    with pytest.raises(ValueError, match="cite"):
        compile_authored_episode(
            _mini(
                [
                    AuthoredBeat(
                        kind="narration", scene="S1", text="x", visual_prompt="v", tier="实录"
                    )
                ]
            )
        )


def test_shangyang_template_compiles_and_no_repeat_narration() -> None:
    """填好的模板首集能编译;讲解词两两内容不冗余(_is_redundant_narration 全检)。"""
    from hevi.tongjian.episodes.shangyang_bianfa import EPISODE
    from hevi.tongjian.v2_episode import _is_redundant_narration

    c = compile_authored_episode(EPISODE)
    assert len(c.shotlist.shots) == len(EPISODE.beats)
    narrs = [ln.text for ln in c.script.lines if ln.type in ("narration", "commentary")]
    seen: list[str] = []
    for t in narrs:
        assert not _is_redundant_narration(t, seen), f"讲解词冗余: {t[:20]}"
        seen.append(t)
