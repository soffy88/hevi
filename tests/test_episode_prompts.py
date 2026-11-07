"""Contract tests for story.episode_prompts (offline, deterministic).

Fixtures are invented for these tests only: two travellers at a mountain
post station. No external skill text, example plot or person is reused.
"""

import json
from pathlib import Path

import pytest

from hevi.capabilities import registry
from hevi.capabilities.errors import CapabilityError
import hevi.capabilities.episode_prompts as ep_cap

SEGMENTS = [
    "[角色锁定]",
    "[场景锁定]",
    "[动作]",
    "[对白]",
    "[镜头]",
    "[风格]",
    "[时长]",
    "[否定约束]",
    "[首帧参照]",
]


def _bible():
    return {
        "characters": [
            {"id": "C01", "name": "沈青"},
            {"id": "C02", "name": "陆遥"},
        ],
        "scenes": [
            {"id": "SC01", "name": "山间驿站", "block": "山间驿站：木屋、石灯、雨后石板路"},
        ],
        "visual_locks": {
            "C01": "沈青：深色布衣、束发、背旧布包",
            "C02": "陆遥：浅色斗篷、手持竹杖",
        },
    }


def _shot(**overrides):
    shot = {
        "shot_id": "SH01",
        "scene_id": "SC01",
        "character_ids": ["C01", "C02"],
        "action": "沈青把布包放在石桌上，陆遥扶着竹杖走近，停在门廊下。",
        "dialogue": [{"speaker": "沈青", "text": "山路难走，先点灯火歇一歇。", "language": "中文"}],
        "camera": "固定机位，中景",
        "duration_sec": 60,
        "style": "写实、暖调",
        "negatives": ["不出雨水穿帮"],
        "first_frame": "山间驿站门廊下，沈青把布包放在石桌上。",
        "spatial_layout": {
            "door": "北侧木门",
            "table": "中央石桌",
            "key_props": {"石灯": "门廊左侧"},
            "light": "门廊灯火暖光",
            "character_positions": {
                "沈青": {"position": "石桌旁", "facing": "门廊"},
                "陆遥": {"position": "门廊下", "facing": "石桌"},
            },
        },
    }
    shot.update(overrides)
    return shot


def _params(shots=None, must_know=None):
    return {
        "bible": _bible(),
        "episode": {
            "episode_no": 1,
            "title": "驿站灯火",
            "shots": shots if shots is not None else [_shot()],
        },
        "must_know": must_know
        if must_know is not None
        else [{"fact": "驿站每夜点灯火", "keywords": ["灯火"]}],
    }


def _run(params, tmp_path):
    cap = registry.get("story.episode_prompts")
    result = cap.render_safe(params, tmp_path, duration=0.0, aspect="16:9", seed=42)
    report = json.loads(Path(result.qa["report_json"]).read_text(encoding="utf-8"))
    return result, report


def test_registration_idempotent():
    assert registry.get("story.episode_prompts").name == "story.episode_prompts"
    assert ep_cap.register_episode_prompts_capabilities_once() == []


def test_compile_resolves_locked_blocks_and_all_segments(tmp_path):
    _, report = _run(_params(), tmp_path)
    assert report["episode_no"] == 1
    assert report["title"] == "驿站灯火"
    assert report["total_duration_sec"] == 60
    assert report["compile_warnings"] == []
    shot = report["shots"][0]
    text = shot["prompt_text"]
    assert "沈青：深色布衣、束发、背旧布包" in text
    assert "陆遥：浅色斗篷、手持竹杖" in text
    assert "山间驿站：木屋、石灯、雨后石板路" in text
    positions = [text.index(seg) for seg in SEGMENTS]
    assert positions == sorted(positions)
    for seg in SEGMENTS:
        assert seg in text
    # Action is kept verbatim, not rewritten.
    assert "沈青把布包放在石桌上，陆遥扶着竹杖走近，停在门廊下。" in text
    assert "沈青（中文）：山路难走，先点灯火歇一歇。" in text
    assert "不出雨水穿帮" in text
    for default in ["不换脸", "不加无关人物", "不出文字 artifact", "不出品牌 logo"]:
        assert default in text
    assert report["must_know"] == [{"fact": "驿站每夜点灯火", "keywords": ["灯火"]}]
    assert report["total_dialogue_chars"] == len("山路难走，先点灯火歇一歇。")


def test_unknown_character_and_scene_raise(tmp_path):
    with pytest.raises(CapabilityError):
        _run(_params([_shot(character_ids=["C99"])]), tmp_path)
    with pytest.raises(CapabilityError):
        _run(_params([_shot(scene_id="SC99")]), tmp_path)


def test_missing_fields_marked_not_silently_filled(tmp_path):
    shot = _shot()
    for key in ("camera", "style", "duration_sec", "first_frame"):
        shot.pop(key, None)
    _, report = _run(_params([shot]), tmp_path)
    text = report["shots"][0]["prompt_text"]
    assert text.count("[缺失]") == 4
    warned = {w["field"] for w in report["compile_warnings"]}
    assert {"camera", "style", "duration", "first_frame"} <= warned
    # Nothing invented: no guessed camera/style/duration text appears.
    assert "固定机位" not in text


def test_explicit_empty_dialogue_is_pure_visual_not_missing(tmp_path):
    _, report = _run(_params([_shot(dialogue=[])]), tmp_path)
    text = report["shots"][0]["prompt_text"]
    assert "纯视觉镜，无对白" in text
    assert "[缺失]" not in text
    assert report["shots"][0]["blocks"]["dialogue"] == []


def test_missing_dialogue_key_is_marked_missing(tmp_path):
    shot = _shot()
    shot.pop("dialogue", None)
    _, report = _run(_params([shot]), tmp_path)
    assert "[缺失]" in report["shots"][0]["prompt_text"]
    assert any(w["field"] == "dialogue" for w in report["compile_warnings"])
    assert report["shots"][0]["blocks"]["dialogue"] is None


def test_missing_bible_or_episode_raises(tmp_path):
    with pytest.raises(CapabilityError):
        _run({"episode": {"shots": []}}, tmp_path)
    with pytest.raises(CapabilityError):
        _run({"bible": _bible()}, tmp_path)


def test_report_file_sha(tmp_path):
    result, report = _run(_params(), tmp_path)
    report_path = Path(result.qa["report_json"])
    assert report_path.is_file()
    assert result.sha256 == registry.compute_sha256(report_path)
    assert report["shots"][0]["shot_id"] == "SH01"


def test_action_nodes_derived_single_by_default(tmp_path):
    _, report = _run(_params(), tmp_path)
    blocks = report["shots"][0]["blocks"]
    assert len(blocks["action_nodes"]) == 1
    assert blocks["action_nodes_source"] == "derived_from_action"
    assert blocks["action_nodes"][0]["text"] == "沈青把布包放在石桌上，陆遥扶着竹杖走近，停在门廊下。"
    assert "动作节点（1）" in report["shots"][0]["prompt_text"]
    assert report["compile_warnings"] == []


def test_action_nodes_explicit_multi_is_warned_not_hidden(tmp_path):
    shot = _shot(action_nodes=["沈青放布包。", "陆遥走近。", "两人停下。"])
    _, report = _run(_params([shot]), tmp_path)
    blocks = report["shots"][0]["blocks"]
    assert len(blocks["action_nodes"]) == 3
    assert blocks["action_nodes_source"] == "explicit"
    assert any(w["field"] == "action_nodes" for w in report["compile_warnings"])
    text = report["shots"][0]["prompt_text"]
    assert "动作节点（1）：沈青放布包。" in text
    assert "动作节点（3）：两人停下。" in text


def test_spatial_layout_in_blocks_and_prompt(tmp_path):
    _, report = _run(_params(), tmp_path)
    layout = report["shots"][0]["blocks"]["spatial_layout"]
    assert layout["door"] == "北侧木门"
    assert layout["table"] == "中央石桌"
    assert layout["light"] == "门廊灯火暖光"
    assert layout["character_positions"]["沈青"] == {"position": "石桌旁", "facing": "门廊"}
    text = report["shots"][0]["prompt_text"]
    assert "空间布局：门：北侧木门" in text
    assert "光源：门廊灯火暖光" in text


def test_spatial_layout_missing_is_warned(tmp_path):
    shot = _shot()
    shot.pop("spatial_layout", None)
    _, report = _run(_params([shot]), tmp_path)
    assert report["shots"][0]["blocks"]["spatial_layout"] is None
    assert any(w["field"] == "spatial_layout" for w in report["compile_warnings"])


def test_spatial_layout_missing_static_field_is_warned(tmp_path):
    shot = _shot()
    shot["spatial_layout"] = {"door": "北侧木门", "table": "中央石桌"}
    _, report = _run(_params([shot]), tmp_path)
    warned = [w for w in report["compile_warnings"] if w["field"] == "spatial_layout"]
    assert warned and "光源" in warned[0]["message"]


def test_scene_layout_fallback_when_shot_has_none(tmp_path):
    bible = _bible()
    bible["scenes"][0]["layout"] = {
        "door": "西侧木门",
        "table": "靠墙木桌",
        "light": "窗外月光",
    }
    shot = _shot()
    shot.pop("spatial_layout", None)
    _, report = _run({"bible": bible, "episode": {"episode_no": 1, "title": "驿站灯火", "shots": [shot]}}, tmp_path)
    layout = report["shots"][0]["blocks"]["spatial_layout"]
    assert layout["door"] == "西侧木门"
    assert not any(w["field"] == "spatial_layout" for w in report["compile_warnings"])


def _bible_with_identity():
    bible = _bible()
    entry = bible["characters"][0]
    entry["portrait_block"] = "沈青：深色布衣、束发、背旧布包"
    entry["face_anchors"] = "方脸、浓眉"
    entry["hair"] = "束发"
    entry["body_proportions"] = "中等身材"
    entry["outfit"] = "深色布衣"
    entry["signature_props"] = "旧布包"
    return bible


def test_costume_variant_locks_identity_changes_only_outfit(tmp_path):
    bible = _bible_with_identity()
    shot = _shot(
        costume_variants=[
            {"character_id": "C01", "outfit": "灰色雨披", "variant_id": "C01_rain"}
        ]
    )
    params = {"bible": bible, "episode": {"episode_no": 1, "title": "驿站灯火", "shots": [shot]}}
    _, report = _run(params, tmp_path)
    variants = report["shots"][0]["blocks"]["costume_variants"]
    assert len(variants) == 1
    rec = variants[0]
    assert rec["id"] == "C01_rain"
    assert rec["character_id"] == "C01"
    assert rec["face_anchors"] == "方脸、浓眉"
    assert rec["hair"] == "束发"
    assert rec["body_proportions"] == "中等身材"
    assert rec["outfit"] == "灰色雨披"
    assert rec["locked"] == ["face_anchors", "hair", "body_proportions"]
    assert rec["changed"] == ["outfit"]
    assert rec["missing_locked_fields"] == []
    # Identity/style split: identity block is the locked half, style block
    # is the swapped half; the full block still composes from both.
    assert rec["identity_block"] == "方脸、浓眉、束发、中等身材"
    assert rec["style_block"] == "灰色雨披"
    # Registry-compatible field names, and the variant block carries the
    # new outfit while the old outfit mention is gone.
    assert "灰色雨披" in (rec["portrait_block"] or "")
    assert "深色布衣" not in (rec["portrait_block"] or "")
    assert report["costume_variants"][0]["id"] == "C01_rain"
    # Self-contained restatement: the variant shot repeats the full
    # identity block and the new style, and never says "same as above".
    text = report["shots"][0]["prompt_text"]
    assert "换装变体 C01_rain（沈青）：身份：方脸、浓眉、束发、中等身材；造型：灰色雨披。" in text
    assert "同上" not in text


def test_costume_variant_prompts_are_self_contained_across_shots(tmp_path):
    bible = _bible_with_identity()
    variant = {"character_id": "C01", "outfit": "灰色雨披", "variant_id": "C01_rain"}
    shot1 = _shot(shot_id="SH01", costume_variants=[variant])
    shot2 = _shot(shot_id="SH02", costume_variants=[variant])
    params = {"bible": bible, "episode": {"episode_no": 1, "title": "驿站灯火", "shots": [shot1, shot2]}}
    _, report = _run(params, tmp_path)
    for shot in report["shots"]:
        assert "身份：方脸、浓眉、束发、中等身材；造型：灰色雨披。" in shot["prompt_text"]
        assert "同上" not in shot["prompt_text"]


def test_costume_variant_missing_locked_fields_flagged_not_invented(tmp_path):
    shot = _shot(
        costume_variants=[{"character_id": "C02", "outfit": "蓑衣", "variant_id": "C02_rain"}]
    )
    _, report = _run(_params([shot]), tmp_path)
    rec = report["shots"][0]["blocks"]["costume_variants"][0]
    assert rec["outfit"] == "蓑衣"
    assert rec["missing_locked_fields"]  # C02 has no face/hair/body in fixture
    assert rec["face_anchors"] is None
    assert any(w["field"] == "costume_variant" for w in report["compile_warnings"])


def test_costume_variant_unknown_character_raises(tmp_path):
    shot = _shot(
        costume_variants=[{"character_id": "C99", "outfit": "蓑衣", "variant_id": "X"}]
    )
    with pytest.raises(CapabilityError):
        _run(_params([shot]), tmp_path)


# Action -> node -> shot mapping table (self-defined for this line).
# Method sources, paraphrased, no code or example text copied:
# - liyue one-shot-one-main-motion (no license: method read-only only);
# - qisi one-shot-one-task;
# - gnipbao phased action checking (only phases actually present count).
# Rules applied here:
# - one main motion, including its enter / main / settle phases, is ONE node;
# - two distinct tasks or motions are TWO nodes (gate: major, split recommended);
# - three or more nodes is a BLOCKER (gate: must split, never compress);
# - a phase not present in the action text is never invented.
# Dispositions: "keep" | "split_recommended" | "must_split".
ACTION_NODE_MAP = [
    # (action sentence, explicit nodes, disposition)
    ("沈青把布包放在石桌上。", ["沈青把布包放在石桌上"], "keep"),
    ("陆遥走近门廊，停在门廊下。",
     ["陆遥走近门廊，停在门廊下"], "keep"),  # enter + settle phases of one motion
    ("沈青把布包放在石桌上，陆遥扶着竹杖走近。",
     ["沈青把布包放在石桌上", "陆遥扶着竹杖走近"], "split_recommended"),
    ("沈青走近石桌，放下布包，坐下。",
     ["沈青走近石桌", "沈青放下布包", "沈青坐下"], "must_split"),
    ("沈青把布包放在石桌上，陆遥扶着竹杖走近，停在门廊下。",
     ["沈青把布包放在石桌上", "陆遥扶着竹杖走近，停在门廊下"], "split_recommended"),
]


def test_action_node_mapping_table_is_consistent(tmp_path):
    # The table must agree with the gate contract: 1 node keeps, 2 nodes
    # is a major (split recommended), 3+ is a blocker (must split).
    for action, nodes, disposition in ACTION_NODE_MAP:
        if len(nodes) == 1:
            assert disposition == "keep", action
        elif len(nodes) == 2:
            assert disposition == "split_recommended", action
        else:
            assert disposition == "must_split", action
        shot = _shot(action=action, action_nodes=nodes)
        _, report = _run(_params([shot]), tmp_path)
        compiled = report["shots"][0]["blocks"]["action_nodes"]
        assert [n["text"] for n in compiled] == nodes
        assert report["shots"][0]["blocks"]["action_nodes_source"] == "explicit"
