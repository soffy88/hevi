"""tongjian_v2_bridge 测试(SPEC-005-V2 §1)——确定性映射,不碰 LLM/网络。"""

from __future__ import annotations

from hevi.director.tongjian_v2_bridge import (
    _map_camera,
    build_v2_design_list,
    build_v2_inputs_from_tongjian,
    build_v2_scene_script_set,
    character_id_to_name,
    partition_drama_narration,
)
from hevi.tongjian.schemas import (
    CharacterBible,
    CharacterBibleEntry,
    Script,
    ScriptLine,
    Shot,
    ShotCamera,
    ShotList,
)


def _cb() -> CharacterBible:
    return CharacterBible(
        characters=[
            CharacterBibleEntry(
                character_id="c_shang",
                name="商鞅",
                appearance="锐利中年男子",
                era_check="战国秦深衣玄端",
                voice_id="zh_male_deep",
            ),
            CharacterBibleEntry(character_id="c_gong", name="秦孝公", appearance="威严青年君主"),
        ]
    )


def test_character_id_to_name() -> None:
    m = character_id_to_name(_cb())
    assert m == {"c_shang": "商鞅", "c_gong": "秦孝公"}


def test_map_camera_vocab_and_push_in_split() -> None:
    assert _map_camera("static", is_first_shot_in_scene=False) == "静态对话"
    assert _map_camera("pan_left", is_first_shot_in_scene=False) == "横移"
    assert _map_camera("tilt_up", is_first_shot_in_scene=False) == "摇向声源"
    # slow_push_in 首镜→定场推,非首镜→峰值轻推
    assert _map_camera("slow_push_in", is_first_shot_in_scene=True) == "定场推"
    assert _map_camera("slow_push_in", is_first_shot_in_scene=False) == "峰值轻推"
    # 未知 → 静态对话
    assert _map_camera("dolly_zoom", is_first_shot_in_scene=False) == "静态对话"


def test_build_design_list_folds_era_check_into_appearance() -> None:
    dl = build_v2_design_list(character_bible=_cb())
    names = {c.name: c for c in dl.characters}
    assert "战国秦深衣玄端" in names["商鞅"].appearance  # era_check 进 appearance(供考据式 canon)
    assert names["商鞅"].voice_id == "zh_male_deep"
    assert names["秦孝公"].appearance == "威严青年君主"  # 无 era_check 原样


def test_build_scene_script_maps_dialogue_camera_and_provenance() -> None:
    script = Script(
        lines=[
            ScriptLine(
                line_id="ln1",
                type="dialogue",
                speaker="c_shang",
                target="c_gong",
                text="谁能把这根木头搬到北门,赏十金。",
                quote_id="q_042",
                dramatized=False,
            ),
            ScriptLine(line_id="ln2", type="narration", speaker="NARRATOR", text="百姓围观议论。"),
        ]
    )
    shot_list = ShotList(
        shots=[
            Shot(
                shot_id="sh1",
                line_ids=["ln1", "ln2"],
                t_start_ms=0,
                t_end_ms=5000,
                scene_id="scene_market",
                characters=["c_shang", "c_gong"],
                camera=ShotCamera(movement="slow_push_in"),
                visual_prompt="商鞅立于木前",
                blocking=["商鞅:画左,面向北门"],
                action_beats=["立木悬赏"],
            ),
        ]
    )
    sss = build_v2_scene_script_set(
        script=script, shot_list=shot_list, id_to_name=character_id_to_name(_cb())
    )
    assert len(sss.scripts) == 1
    sc = sss.scripts[0]
    assert sc.scene_ref == 1
    assert sc.characters_present == ["商鞅", "秦孝公"]  # id→name
    seg = sc.segments[0]
    assert seg.t_start_s == 0.0 and seg.t_end_s == 5.0  # ms→s
    assert seg.camera_movement == "定场推"  # slow_push_in 首镜
    assert seg.beat_description == "立木悬赏"
    # narrative_text = 视觉 + 走位 + 旁白
    assert "商鞅立于木前" in seg.narrative_text
    assert "走位:商鞅:画左,面向北门" in seg.narrative_text
    assert "百姓围观议论" in seg.narrative_text
    # dialogue:id→name + 溯源审计透传
    assert len(seg.dialogue) == 1
    d = seg.dialogue[0]
    assert d.character_name == "商鞅" and d.target_name == "秦孝公"
    assert d.text == "谁能把这根木头搬到北门,赏十金。"
    assert d.quote_id == "q_042" and d.dramatized is False


def test_build_scene_script_groups_by_scene_and_skips_transitions() -> None:
    script = Script(
        lines=[ScriptLine(line_id=f"ln{i}", type="narration", text=f"t{i}") for i in range(4)]
    )
    shots = [
        Shot(shot_id="s1", line_ids=["ln0"], scene_id="A", t_end_ms=3000, camera=ShotCamera()),
        Shot(shot_id="s2", line_ids=["ln1"], scene_id="A", t_end_ms=3000, camera=ShotCamera()),
        Shot(shot_id="t1", line_ids=[], scene_id="A", is_transition=True, camera=ShotCamera()),
        Shot(shot_id="s3", line_ids=["ln2"], scene_id="B", t_end_ms=3000, camera=ShotCamera()),
    ]
    sss = build_v2_scene_script_set(script=script, shot_list=ShotList(shots=shots), id_to_name={})
    # 两个 scene(A/B),过场镜跳过
    assert [sc.scene_ref for sc in sss.scripts] == [1, 2]
    assert len(sss.scripts[0].segments) == 2  # A 的两镜(过场不算)
    assert len(sss.scripts[1].segments) == 1  # B 一镜
    assert sss.scripts[0].segments[0].segment_id == "sg001"


async def test_build_v2_inputs_orchestrator_ties_mapping_and_worldbible(monkeypatch) -> None:
    # 编排器:确定性映射 + world_bible(historical)生成串起来。mock world_bible 只验接线。
    import hevi.director.world_bible as wb_mod
    from hevi.director.pipeline_schemas import Concept, WorldBible

    async def _fake_wb(*, concept, material_text, design_list, llm, visual_style):
        assert visual_style == "historical"  # 通鉴走历史档
        assert any(c.name == "商鞅" for c in design_list.characters)  # 桥接的 design_list 喂进来了
        return WorldBible()

    monkeypatch.setattr(wb_mod, "generate_world_bible_draft", _fake_wb)
    script = Script(
        lines=[
            ScriptLine(
                line_id="l1", type="dialogue", speaker="c_shang", text="赏十金", quote_id="q1"
            )
        ]
    )
    shots = ShotList(
        shots=[
            Shot(
                shot_id="s1",
                line_ids=["l1"],
                scene_id="A",
                t_end_ms=4000,
                characters=["c_shang"],
                camera=ShotCamera(),
            )
        ]
    )
    dl, sss, _wb = await build_v2_inputs_from_tongjian(
        script=script,
        shot_list=shots,
        character_bible=_cb(),
        material_text="商鞅立木。",
        concept=Concept(),
        llm=None,
    )
    assert [c.name for c in dl.characters] == ["商鞅", "秦孝公"]
    assert sss.scripts[0].segments[0].dialogue[0].quote_id == "q1"  # 溯源透传贯穿编排器


def test_drama_only_filter_partitions_and_excludes_narration() -> None:
    # SPEC-005:只 drama 镜(有对白/角色)进 produce_v2,narration 镜(无对白无角色)走讲解段。
    script = Script(
        lines=[
            ScriptLine(line_id="d1", type="dialogue", speaker="c_shang", text="赏五十金"),
            ScriptLine(line_id="n1", type="narration", text="三日无人近前"),
        ]
    )
    shots = ShotList(
        shots=[
            Shot(shot_id="drama", line_ids=["d1"], scene_id="A", t_end_ms=3000,
                 characters=["c_shang"], camera=ShotCamera()),
            Shot(shot_id="narr", line_ids=["n1"], scene_id="A", t_end_ms=3000,
                 characters=[], camera=ShotCamera()),
        ]
    )
    drama, narration = partition_drama_narration(script, shots)
    assert [s.shot_id for s in drama] == ["drama"]
    assert [s.shot_id for s in narration] == ["narr"]
    # drama_only=True → 只 drama 段进 SceneScriptSet
    sss = build_v2_scene_script_set(
        script=script, shot_list=shots, id_to_name={"c_shang": "商鞅"}, drama_only=True
    )
    segs = [seg for sc in sss.scripts for seg in sc.segments]
    assert len(segs) == 1 and segs[0].dialogue[0].text == "赏五十金"
    # drama_only=False(默认,非通鉴)→ narration 镜也保留(旧行为不倒退)
    sss_all = build_v2_scene_script_set(
        script=script, shot_list=shots, id_to_name={"c_shang": "商鞅"}
    )
    assert sum(len(sc.segments) for sc in sss_all.scripts) == 2
