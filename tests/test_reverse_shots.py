"""双人对白正反打镜序生成测试(2026-07-25)。含免费结构验证:廷辩剧本 → 反打镜序。"""

from __future__ import annotations

from hevi.director.reverse_shots import (
    expand_debate_reverse_shots,
    is_debate,
    summarize_shot_sequence,
)
from hevi.director.tongjian_v2_bridge import build_v2_scene_script_set
from hevi.tongjian.schemas import Script, ScriptLine, Shot, ShotCamera, ShotList

_ID2NAME = {"C_wang": "王绾", "C_lisi": "李斯", "C_qin": "秦始皇"}


def _tingbian_split() -> tuple[Script, ShotList]:
    """廷辩:王绾请立诸子(场 S1)→ 李斯驳(场 S2)→ 始皇裁(场 S2)。被前端拆成两场(④a),
    靠 target 链接('王绾→秦始皇' 且秦始皇在 S2 说话)判为同一辩论。"""
    script = Script(
        lines=[
            ScriptLine(
                line_id="L1", type="dialogue", speaker="C_wang", target="C_qin", text="请立诸子。"
            ),
            ScriptLine(
                line_id="L2",
                type="dialogue",
                speaker="C_lisi",
                target="C_wang",
                text="置诸侯不便。",
            ),
            ScriptLine(
                line_id="L3", type="dialogue", speaker="C_qin", target="C_lisi", text="廷尉议是。"
            ),
        ]
    )
    shots = ShotList(
        shots=[
            Shot(
                shot_id="SH1",
                line_ids=["L1"],
                scene_id="S1",
                characters=["C_wang"],
                camera=ShotCamera(),
            ),
            Shot(
                shot_id="SH2",
                line_ids=["L2"],
                scene_id="S2",
                characters=["C_lisi"],
                camera=ShotCamera(),
            ),
            Shot(
                shot_id="SH3",
                line_ids=["L3"],
                scene_id="S2",
                characters=["C_qin"],
                camera=ShotCamera(),
            ),
        ]
    )
    return script, shots


def test_tingbian_produces_reverse_shot_sequence() -> None:
    """★ 免费结构验证:廷辩 → master 建轴 + 逐轮 OTS 反打,且跨场被合并成一场。"""
    script, shots = _tingbian_split()
    sss = build_v2_scene_script_set(
        script=script, shot_list=shots, id_to_name=_ID2NAME, drama_only=True
    )

    # ④a:两场合并成一场
    assert len(sss.scripts) == 1
    seq = summarize_shot_sequence(sss.scripts)
    types = [r["shot_type"] for r in seq]
    # ① 镜序:master 建轴 + 两主辩各一 OTS + 君主(始皇)御座正面(A 规则,不进反打轴)
    assert types == ["master", "ots", "ots", "frontal"]
    # side_convention:王绾恒画左、李斯恒画右(首两名主辩锁死),全序不翻
    by_speaker = {r["speaker"]: r["side"] for r in seq if r["speaker"]}
    assert by_speaker["王绾"] == "画左"
    assert by_speaker["李斯"] == "画右"
    # OTS 前景 = **对方主辩**(锁反打轴,不看 target):王绾镜前景李斯、李斯镜前景王绾
    ots = [r for r in seq if r["shot_type"] == "ots"]
    assert ots[0]["speaker"] == "王绾" and ots[0]["fg"] == "李斯"
    assert ots[1]["speaker"] == "李斯" and ots[1]["fg"] == "王绾"
    # 君主始皇:御座正面独立镜,不在反打轴(无 side/fg)
    frontal = [r for r in seq if r["shot_type"] == "frontal"]
    assert frontal[0]["speaker"] == "秦始皇" and not frontal[0]["side"] and not frontal[0]["fg"]


def test_single_protagonist_scene_not_expanded() -> None:
    """立木式单主角(只卫鞅说话)→ 不是辩论,不展开、不合并(防误伤单人宣令戏)。"""
    script = Script(
        lines=[
            ScriptLine(line_id="L1", type="dialogue", speaker="C_wang", text="能徙者予五十金。"),
            ScriptLine(line_id="L2", type="dialogue", speaker="C_wang", text="以明不欺。"),
        ]
    )
    shots = ShotList(
        shots=[
            Shot(
                shot_id="SH1",
                line_ids=["L1"],
                scene_id="A",
                characters=["C_wang"],
                camera=ShotCamera(),
            ),
            Shot(
                shot_id="SH2",
                line_ids=["L2"],
                scene_id="B",
                characters=["C_wang"],
                camera=ShotCamera(),
            ),
        ]
    )
    sss = build_v2_scene_script_set(
        script=script, shot_list=shots, id_to_name=_ID2NAME, drama_only=True
    )
    # 单主角:两场不合并(combined 说话人<2),不出现 master/ots
    assert all(seg.shot_type == "single" for sc in sss.scripts for seg in sc.segments)


def test_is_debate_predicate() -> None:
    script, shots = _tingbian_split()
    sss = build_v2_scene_script_set(
        script=script, shot_list=shots, id_to_name=_ID2NAME, drama_only=True
    )
    assert is_debate(sss.scripts[0])


def test_expand_idempotent_shape_on_nondebate() -> None:
    # 直接对单说话人 SceneScript 调 expand → 原样返回
    script = Script(
        lines=[ScriptLine(line_id="L1", type="dialogue", speaker="C_wang", text="独白。")]
    )
    shots = ShotList(
        shots=[
            Shot(
                shot_id="SH1",
                line_ids=["L1"],
                scene_id="A",
                characters=["C_wang"],
                camera=ShotCamera(),
            )
        ]
    )
    sss = build_v2_scene_script_set(
        script=script, shot_list=shots, id_to_name=_ID2NAME, drama_only=True
    )
    sc = sss.scripts[0]
    assert expand_debate_reverse_shots(sc) is sc  # 非辩论,同一对象原样返回


# ── 连续性规则:"反打=剪切"(2026-07-25)──────────────────────────────────────
def test_continuity_rule_cut_vs_continuation() -> None:
    """剪切镜(master/ots/frontal)不接上段末帧;连续动作段(single)接。"""
    from hevi.director.pipeline_schemas import SceneScriptSegment
    from hevi.director.reverse_shots import CUT_SHOT_TYPES, segment_continues_prior

    assert {"master", "ots", "frontal"} == CUT_SHOT_TYPES
    # 剪切镜:另起视角 → 不接续
    for st in ("master", "ots", "frontal"):
        assert segment_continues_prior(SceneScriptSegment(shot_type=st)) is False
    # 连续动作段 → 接续
    assert segment_continues_prior(SceneScriptSegment(shot_type="single")) is True
    # 缺字段默认 single → 接续
    assert segment_continues_prior(SceneScriptSegment()) is True


# ── 反打轴识别 + 合并从严(2026-07-26 商鞅廷辩实证)──────────────────────────
def _line(lid, spk, tgt, text="x"):
    return ScriptLine(line_id=lid, type="dialogue", speaker=spk, target=tgt, text=text)


def _shot(sid, lid, scene, chars):
    return Shot(shot_id=sid, line_ids=[lid], scene_id=scene, characters=chars, camera=ShotCamera())


def test_reciprocal_pair_is_axis_not_appeal_count() -> None:
    """卫鞅↔甘龙 互相驳斥=反打轴;孝公被卫鞅+甘龙都 target(appeal=2)但只是裁决者→御座正面,
    不能因"被≥2人诉诸"把主辩卫鞅误判成君主。"""
    script = Script(
        lines=[
            _line("b1", "C_wei", "C_gong"),  # 卫鞅→孝公
            _line("b2", "C_gan", "C_wei"),  # 甘龙→卫鞅
            _line("b3", "C_wei", "C_gan"),  # 卫鞅→甘龙(与甘龙互驳)
            _line("b4", "C_gong", "C_wei"),  # 孝公→卫鞅(裁决)
        ]
    )
    shots = ShotList(
        shots=[
            _shot("s1", "b1", "A", ["C_wei"]),
            _shot("s2", "b2", "A", ["C_gan"]),
            _shot("s3", "b3", "A", ["C_wei"]),
            _shot("s4", "b4", "A", ["C_gong"]),
        ]
    )
    idmap = {"C_wei": "卫鞅", "C_gan": "甘龙", "C_gong": "秦孝公"}
    sss = build_v2_scene_script_set(
        script=script, shot_list=shots, id_to_name=idmap, drama_only=True
    )
    seq = summarize_shot_sequence(sss.scripts)
    by_spk = {r["speaker"]: (r["shot_type"], r["side"]) for r in seq if r["speaker"]}
    assert by_spk["卫鞅"][0] == "ots" and by_spk["甘龙"][0] == "ots"  # 主辩双方 OTS
    assert by_spk["秦孝公"][0] == "frontal"  # 裁决者御座正面,不上反打轴


def test_no_overmerge_soliloquy_scene() -> None:
    """立木卫鞅宣令(无 target)不该被并进相邻廷辩场——合并要双向跨场 target。"""
    script = Script(
        lines=[
            _line("b1", "C_wei", "C_gan"),
            _line("b2", "C_gan", "C_wei"),  # 廷辩:卫鞅↔甘龙
            ScriptLine(
                line_id="m1", type="dialogue", speaker="C_wei", target="", text="能徙者予五十金"
            ),
        ]
    )
    shots = ShotList(
        shots=[
            _shot("s1", "b1", "BIAN", ["C_wei"]),
            _shot("s2", "b2", "BIAN", ["C_gan"]),
            _shot("s3", "m1", "LIMU", ["C_wei"]),  # 立木,单人无 target
        ]
    )
    idmap = {"C_wei": "卫鞅", "C_gan": "甘龙"}
    sss = build_v2_scene_script_set(
        script=script, shot_list=shots, id_to_name=idmap, drama_only=True
    )
    assert len(sss.scripts) == 2  # 廷辩 + 立木,不合并
    # 立木那场是单人 single(非辩论,不展开反打)
    limu = sss.scripts[1]
    assert all(s.shot_type == "single" for s in limu.segments)


def test_narration_subshots_of_same_line_merge() -> None:
    """同一 line 拆成的连续 narration 子镜头(共用 line_id)合并成一个讲解镜,防解说词重复渲。"""
    from hevi.tongjian.v2_episode import group_shots_by_kind

    script = Script(lines=[ScriptLine(line_id="LN9", type="narration", text="一段长旁白")])
    shots = ShotList(
        shots=[
            Shot(shot_id="SH9_01", line_ids=["LN9"], scene_id="E", camera=ShotCamera()),
            Shot(shot_id="SH9_02", line_ids=["LN9"], scene_id="E", camera=ShotCamera()),
            Shot(shot_id="SH9_03", line_ids=["LN9"], scene_id="E", camera=ShotCamera()),
        ]
    )
    groups = group_shots_by_kind(shots, script)
    assert len(groups) == 1  # 三子镜头合并成一个 narration 组 → 一个讲解镜(不重复 3 遍)
    assert groups[0][0] == "narration" and len(groups[0][1]) == 3


def test_distinct_narration_lines_stay_separate() -> None:
    """不同 line 的相邻 narration 镜不合并(各自成讲解镜)。"""
    from hevi.tongjian.v2_episode import group_shots_by_kind

    script = Script(
        lines=[
            ScriptLine(line_id="L1", type="narration", text="旁白一"),
            ScriptLine(line_id="L2", type="narration", text="旁白二"),
        ]
    )
    shots = ShotList(
        shots=[
            Shot(shot_id="A", line_ids=["L1"], scene_id="E", camera=ShotCamera()),
            Shot(shot_id="B", line_ids=["L2"], scene_id="E", camera=ShotCamera()),
        ]
    )
    groups = group_shots_by_kind(shots, script)
    assert len(groups) == 2  # 两句不同旁白 → 两个讲解镜
