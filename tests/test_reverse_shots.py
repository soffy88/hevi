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
