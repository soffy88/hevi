"""Contract tests for story.drama_gates (offline, deterministic, no Monid).

Packages are built with story.episode_prompts so the gates are tested on
the real compiler output shape; fixtures are invented for these tests.
"""

import json
from pathlib import Path

import pytest

from hevi.capabilities import registry
import hevi.capabilities.episode_prompts as ep_cap


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


def _shot(shot_id, dialogue_text="山路难走，先点灯火歇一歇。"):
    return {
        "shot_id": shot_id,
        "scene_id": "SC01",
        "character_ids": ["C01", "C02"],
        "action": "沈青把布包放在石桌上，陆遥扶着竹杖走近，停在门廊下。",
        "dialogue": [{"speaker": "沈青", "text": dialogue_text, "language": "中文"}],
        "camera": "固定机位，中景",
        "duration_sec": 60,
        "style": "写实、暖调",
        "first_frame": "山间驿站门廊下，沈青把布包放在石桌上。",
        "spatial_layout": {
            "door": "北侧木门",
            "table": "中央石桌",
            "key_props": {"石灯": "门廊左侧"},
            "light": "门廊灯火暖光",
            "character_positions": {
                "沈青": {"position": "石桌旁", "facing": "门廊"},
            },
        },
    }


def _clean_package():
    params = {
        "bible": _bible(),
        "episode": {
            "episode_no": 1,
            "title": "驿站灯火",
            "shots": [_shot(f"SH0{i}") for i in range(1, 6)],
        },
        "must_know": [{"fact": "驿站每夜点灯火", "keywords": ["灯火"]}],
    }
    return ep_cap.compile_episode_prompts(params)


def _scenes_with_dialogue(keyword_present=True):
    text = "山路难走，先点灯火歇一歇。" if keyword_present else "山路难走，先歇一歇。"
    return [
        {
            "scene_id": "S01",
            "header": "山间驿站",
            "characters": ["沈青", "陆遥"],
            "action": "沈青把布包放在石桌上，陆遥扶着竹杖走近，停在门廊下。",
            "dialogue": [{"speaker": "沈青", "text": text}],
        }
    ]


def _gates_params(package, **overrides):
    params = {
        "prompt_package": package,
        "episode_scenes": _scenes_with_dialogue(),
        "budget": {"max_credits": 1000, "credits_per_8s": 20},
        "rewrite_round": 0,
    }
    params.update(overrides)
    return params


def _run(params, tmp_path):
    cap = registry.get("story.drama_gates")
    result = cap.render_safe(params, tmp_path, duration=0.0, aspect="16:9", seed=42)
    report = json.loads(Path(result.qa["report_json"]).read_text(encoding="utf-8"))
    return result, report


def test_registration_idempotent():
    import hevi.capabilities.drama_gates as dg_cap

    assert registry.get("story.drama_gates").name == "story.drama_gates"
    assert dg_cap.register_drama_gates_capabilities_once() == []


def test_clean_package_all_green_and_ledger(tmp_path):
    _, report = _run(_gates_params(_clean_package()), tmp_path)
    assert report["passed"] is True
    assert report["counts"]["blocker"] == 0
    assert report["failed_checks"] == []
    assert report["total_duration_sec"] == 300
    # ceil(300/8)=38 * 20 = 760
    assert report["est_credits"] == 760
    ledger_path = Path(report["ledger_path"])
    assert ledger_path.is_file()
    entry = json.loads(ledger_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert entry["episode_no"] == 1
    assert entry["passed"] is True
    assert entry["counts"]["blocker"] == 0
    assert entry["failed_checks"] == []
    assert entry["timestamp"]


def test_missing_action_is_blocker(tmp_path):
    package = _clean_package()
    package["shots"][0]["blocks"]["action"] = None
    _, report = _run(_gates_params(package), tmp_path)
    assert report["passed"] is False
    blockers = [f for f in report["findings"] if f["severity"] == "blocker"]
    assert any(f["check"] == "completeness" and "缺动作" in f["issue"] for f in blockers)


def test_over_budget_is_fail_closed_blocker(tmp_path):
    _, report = _run(
        _gates_params(_clean_package(), budget={"max_credits": 100, "credits_per_8s": 20}),
        tmp_path,
    )
    assert report["passed"] is False
    blockers = [f for f in report["findings"] if f["check"] == "budget"]
    assert blockers and blockers[0]["severity"] == "blocker"
    assert "降时长或降单价模型" in blockers[0]["suggestion"]


def test_dialogue_over_1300_is_blocker_with_cut_advice(tmp_path):
    package = _clean_package()
    package["total_dialogue_chars"] = 1500
    _, report = _run(_gates_params(package), tmp_path)
    assert report["passed"] is False
    blockers = [f for f in report["findings"] if f["check"] == "duration_dialogue"]
    assert any(f["severity"] == "blocker" for f in blockers)
    assert any("超了砍场景不加速念" in f["suggestion"] for f in blockers)


def test_script_polish_blocker_passes_through(tmp_path):
    package = _clean_package()
    params = _gates_params(package, episode_scenes=_scenes_with_dialogue(keyword_present=False))
    _, report = _run(params, tmp_path)
    assert report["passed"] is False
    sp_blockers = [f for f in report["findings"] if f["check"] == "script_polish"]
    assert sp_blockers and all(f["severity"] == "blocker" for f in sp_blockers)
    assert any("未向观众交付关键信息" in f["issue"] for f in sp_blockers)


def test_rewrite_round_3_is_stop_and_report_blocker(tmp_path):
    _, report = _run(_gates_params(_clean_package(), rewrite_round=3), tmp_path)
    assert report["passed"] is False
    blockers = [f for f in report["findings"] if f["check"] == "script_polish"]
    assert any("停下报用户" in f["suggestion"] for f in blockers)


def test_ledger_appends_every_run(tmp_path):
    params = _gates_params(_clean_package())
    _run(params, tmp_path)
    _, report = _run(params, tmp_path)
    lines = Path(report["ledger_path"]).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert all(json.loads(line)["passed"] is True for line in lines)


def test_first_frame_without_scene_or_character_is_major_not_blocker(tmp_path):
    package = _clean_package()
    package["shots"][0]["blocks"]["first_frame"] = "一个人在空旷的野地里走着。"
    _, report = _run(_gates_params(package), tmp_path)
    majors = [f for f in report["findings"] if f["check"] == "first_frame"]
    assert majors and majors[0]["severity"] == "major"
    assert report["passed"] is True


def test_pure_visual_shot_dialogue_empty_is_allowed(tmp_path):
    package = _clean_package()
    package["shots"][0]["blocks"]["dialogue"] = []
    _, report = _run(_gates_params(package), tmp_path)
    assert report["passed"] is True
    assert not any(
        f["check"] == "completeness" and "对白" in f["issue"] for f in report["findings"]
    )


def test_report_file_sha(tmp_path):
    result, report = _run(_gates_params(_clean_package()), tmp_path)
    report_path = Path(result.qa["report_json"])
    assert report_path.is_file()
    assert result.sha256 == registry.compute_sha256(report_path)
    assert report["episode_no"] == 1


def _set_nodes(package, shot_idx, nodes):
    package["shots"][shot_idx]["blocks"]["action_nodes"] = nodes


def test_action_nodes_two_is_major_not_blocker(tmp_path):
    package = _clean_package()
    _set_nodes(package, 0, [{"index": 0, "text": "放布包。"}, {"index": 1, "text": "走近。"}])
    _, report = _run(_gates_params(package), tmp_path)
    majors = [f for f in report["findings"] if f["check"] == "action_nodes"]
    assert majors and majors[0]["severity"] == "major"
    assert report["passed"] is True


def test_action_nodes_three_is_blocker(tmp_path):
    package = _clean_package()
    _set_nodes(
        package,
        0,
        [{"index": 0, "text": "放布包。"}, {"index": 1, "text": "走近。"}, {"index": 2, "text": "停下。"}],
    )
    _, report = _run(_gates_params(package), tmp_path)
    assert report["passed"] is False
    assert "action_nodes" in report["failed_checks"]
    blockers = [f for f in report["findings"] if f["check"] == "action_nodes"]
    assert blockers and blockers[0]["severity"] == "blocker"


def test_action_nodes_missing_is_fail_closed_blocker(tmp_path):
    package = _clean_package()
    package["shots"][0]["blocks"].pop("action_nodes", None)
    _, report = _run(_gates_params(package), tmp_path)
    assert report["passed"] is False
    assert any(f["check"] == "action_nodes" and f["severity"] == "blocker" for f in report["findings"])


def test_spatial_layout_missing_is_blocker(tmp_path):
    package = _clean_package()
    package["shots"][0]["blocks"]["spatial_layout"] = None
    _, report = _run(_gates_params(package), tmp_path)
    assert report["passed"] is False
    assert "spatial_continuity" in report["failed_checks"]


def test_spatial_door_mismatch_same_scene_is_blocker(tmp_path):
    package = _clean_package()
    package["shots"][1]["blocks"]["spatial_layout"] = dict(
        package["shots"][1]["blocks"]["spatial_layout"], door="南侧木门"
    )
    _, report = _run(_gates_params(package), tmp_path)
    assert report["passed"] is False
    blockers = [f for f in report["findings"] if f["check"] == "spatial_continuity"]
    assert blockers and "门" in blockers[0]["issue"]


def test_spatial_mismatch_other_scene_is_ignored(tmp_path):
    package = _clean_package()
    shot = package["shots"][1]
    shot["blocks"]["scene_id"] = "SC02"
    shot["blocks"]["spatial_layout"] = dict(shot["blocks"]["spatial_layout"], door="南侧木门")
    _, report = _run(_gates_params(package), tmp_path)
    assert not any(f["check"] == "spatial_continuity" for f in report["findings"])
    assert report["passed"] is True


def test_spatial_key_props_moving_is_not_a_continuity_blocker(tmp_path):
    package = _clean_package()
    shot = package["shots"][1]
    shot["blocks"]["spatial_layout"] = dict(
        shot["blocks"]["spatial_layout"], key_props={"石灯": "移到屋内"}
    )
    _, report = _run(_gates_params(package), tmp_path)
    assert not any(f["check"] == "spatial_continuity" for f in report["findings"])


def test_edit_ready_is_pending_never_a_pass(tmp_path):
    _, report = _run(_gates_params(_clean_package()), tmp_path)
    pendings = [f for f in report["findings"] if f["check"] == "edit_ready"]
    assert pendings and pendings[0]["severity"] == "pending"
    assert report["checks"]["edit_ready"]["status"] == "pending"
    assert report["counts"]["pending"] == 1
    assert report["passed"] is True  # pending does not fail the gate


def test_edit_ready_with_edl_still_pending(tmp_path):
    params = _gates_params(_clean_package(), edl={"events": []})
    _, report = _run(params, tmp_path)
    pendings = [f for f in report["findings"] if f["check"] == "edit_ready"]
    assert pendings and pendings[0]["severity"] == "pending"
    assert report["passed"] is True


def test_edit_ready_passes_with_clean_edit_report(tmp_path):
    edit_report = {"edit_ready": True, "findings": [], "counts": {"blocker": 0}}
    params = _gates_params(_clean_package(), edit_report=edit_report)
    _, report = _run(params, tmp_path)
    assert report["checks"]["edit_ready"] == {"passed": True, "status": "passed"}
    assert not any(f["check"] == "edit_ready" for f in report["findings"])
    assert report["counts"]["pending"] == 0
    assert report["passed"] is True


def test_edit_ready_blocker_from_edit_report(tmp_path):
    edit_report = {
        "edit_ready": False,
        "findings": [
            {
                "check": "edit_ready",
                "severity": "blocker",
                "issue": "镜 SH01 缺成片文件。",
                "suggestion": "补成片文件后重跑。",
                "shot_id": "SH01",
                "scene_id": "SC01",
            }
        ],
    }
    params = _gates_params(_clean_package(), edit_report=edit_report)
    _, report = _run(params, tmp_path)
    assert report["checks"]["edit_ready"] == {"passed": False, "status": "blocker"}
    blockers = [f for f in report["findings"] if f["check"] == "edit_ready"]
    assert blockers and blockers[0]["severity"] == "blocker"
    assert "缺成片文件" in blockers[0]["issue"]
    assert report["passed"] is False
    assert "edit_ready" in report["failed_checks"]


def test_edit_ready_contradictory_report_is_blocker_not_pass(tmp_path):
    edit_report = {
        "edit_ready": True,
        "findings": [
            {
                "check": "edit_ready",
                "severity": "blocker",
                "issue": "镜 SH02 时长不匹配。",
                "suggestion": "核对成片时长后重跑。",
                "shot_id": "SH02",
                "scene_id": "SC01",
            }
        ],
    }
    params = _gates_params(_clean_package(), edit_report=edit_report)
    _, report = _run(params, tmp_path)
    assert report["checks"]["edit_ready"]["passed"] is False
    assert report["passed"] is False
