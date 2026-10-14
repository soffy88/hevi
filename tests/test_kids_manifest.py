"""Tests for kids story gate + consistency manifest (单元 K1, RENOISE_EVAL §3.3 / §4).

全部为真实代码路径、无网络、无 mock、确定性可复现。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hevi.kids.story_gate import kids_story_gate, gate_json, StoryInput, StoryBeat
from hevi.kids.consistency_manifest import (
    KidsConsistencyManifest,
    validate_manifest,
    canonical_json,
    to_task_specs,
    attach_to_task_shot_rows,
    read_specs_from_task_shot_rows,
    manifest_from_task_specs,
)
from hevi.capabilities import get

FIX = Path(__file__).parent / "fixtures" / "kids"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


GOOD_STORIES = [
    "story_fox_star.json",
    "story_slide.json",
    "story_brush_monster.json",
    "story_seed_sprout.json",
]

BAD_STORIES = {
    "all_andthen": "story_bad_all_andthen.json",
    "adjacent_emotion": "story_bad_adjacent_emotion.json",
    "missing_theme_char": "story_bad_missing_theme_char.json",
}


# ── 验收 1：4 部试点片单 gate 输出 PASS/WARN/FAIL + 逐条 finding ──
@pytest.mark.parametrize("name", GOOD_STORIES)
def test_pilot_story_gate_pass(name: str) -> None:
    story = _load(name)
    report = kids_story_gate(story)
    assert report.status == "PASS", report.to_dict()
    # 逐条 finding 都带规则名 + 位置无关消息
    assert len(report.findings) >= 7
    for f in report.findings:
        assert f.rule.startswith(("R1_", "R2_", "R3_", "R4_", "R5_", "R6_", "R7_"))


# ── 验收 2：3 类坏样本必 FAIL ──
@pytest.mark.parametrize("key", list(BAD_STORIES))
def test_bad_story_must_fail(key: str) -> None:
    story = _load(BAD_STORIES[key])
    report = kids_story_gate(story)
    assert report.status == "FAIL", report.to_dict()
    rules = {f.rule for f in report.findings if f.severity == "FAIL"}
    expected = {
        "all_andthen": "R3_CAUSAL_RATIO",
        "adjacent_emotion": "R4_ADJACENT_EMOTION",
        "missing_theme_char": "R5_SINGLE_THEME",  # 同时 R6/R7 也失败
    }[key]
    assert expected in rules


def test_bad_story_missing_theme_and_character() -> None:
    story = _load(BAD_STORIES["missing_theme_char"])
    report = kids_story_gate(story)
    failed_rules = {f.rule for f in report.findings if f.severity == "FAIL"}
    assert "R5_SINGLE_THEME" in failed_rules
    assert "R6_FIXED_CHARACTER" in failed_rules
    assert "R7_SPOKEN_LANGUAGE" in failed_rules


# ── 验收 3：manifest 校验 ──
def test_manifest_unknown_shotspec_fails() -> None:
    manifest = _load("manifest_bad_shotspec.json")
    # 未知 transition_in -> ShotSpec 校验器直接失败
    report = validate_manifest(manifest)
    assert report.status == "FAIL"
    m0 = [f for f in report.findings if f.rule == "M0_SHOTSPEC_DELEGATION"]
    assert m0 and m0[0].severity == "FAIL"


def test_manifest_missing_style_bible_fails() -> None:
    manifest = _load("manifest_bad_stylebible.json")
    report = validate_manifest(manifest)
    assert report.status == "FAIL"
    m1 = [f for f in report.findings if f.rule == "M1_STYLE_BIBLE"]
    assert m1 and m1[0].severity == "FAIL"


def test_manifest_unknown_ref_fails() -> None:
    manifest = dict(_load("manifest_fox_star.json"))
    manifest["shots"][0]["line"] = "看看 @char_unknown 吧"
    report = validate_manifest(manifest)
    assert report.status == "FAIL"
    m4 = [f for f in report.findings if f.rule == "M4_REF_RESOLUTION"]
    assert m4 and m4[0].severity == "FAIL"


def test_manifest_short_duration_fails() -> None:
    manifest = dict(_load("manifest_fox_star.json"))
    manifest["shots"][0]["duration"] = 1.0
    manifest["shots"][0]["shot_spec"]["duration"] = 1.0
    report = validate_manifest(manifest)
    assert report.status == "FAIL"
    m5 = [f for f in report.findings if f.rule == "M5_DURATION"]
    assert m5 and m5[0].severity == "FAIL"


def test_manifest_missing_transition_row_fails() -> None:
    manifest = dict(_load("manifest_fox_star.json"))
    manifest["transition_table"] = manifest["transition_table"][:-1]  # 缺一个切点
    report = validate_manifest(manifest)
    assert report.status == "FAIL"
    m2 = [f for f in report.findings if f.rule == "M2_TRANSITION_TABLE"]
    assert m2 and m2[0].severity == "FAIL"


def test_valid_manifests_ok() -> None:
    for name in ["manifest_fox_star.json", "manifest_slide.json"]:
        manifest = _load(name)
        report = validate_manifest(manifest)
        assert report.status == "OK", (name, report.to_dict())


def test_manifest_unknown_style_delegated_to_shotspec() -> None:
    # style 未知同样由 ShotSpec 校验器拒绝（不重复实现规则）
    raw = _load("manifest_fox_star.json")
    raw["shots"][0]["shot_spec"]["style"] = "not_a_real_style"
    report = validate_manifest(raw)
    assert report.status == "FAIL"
    assert any(f.rule == "M0_SHOTSPEC_DELEGATION" for f in report.findings)


# ── 验收 4：确定性（同输入两次 SHA-256 一致）──
def test_story_gate_deterministic() -> None:
    story = _load("story_fox_star.json")
    a = gate_json(story)
    b = gate_json(story)
    assert hashlib.sha256(a.encode()).hexdigest() == hashlib.sha256(b.encode()).hexdigest()


def test_manifest_deterministic() -> None:
    raw = _load("manifest_fox_star.json")
    m1 = KidsConsistencyManifest.model_validate(raw)
    m2 = KidsConsistencyManifest.model_validate(raw)
    a = canonical_json(m1)
    b = canonical_json(m2)
    assert hashlib.sha256(a.encode()).hexdigest() == hashlib.sha256(b.encode()).hexdigest()


# ── 验收 6：全链路 story -> gate -> manifest -> ShotSpec dry-run ──
@pytest.mark.parametrize("story_name,manifest_name", [
    ("story_fox_star.json", "manifest_fox_star.json"),
    ("story_slide.json", "manifest_slide.json"),
])
def test_full_chain_dry_run(story_name: str, manifest_name: str, tmp_path: Path) -> None:
    story = _load(story_name)
    gate = kids_story_gate(story)
    assert gate.status == "PASS", gate.to_dict()

    manifest = _load(manifest_name)
    report = validate_manifest(manifest)
    assert report.status == "OK", report.to_dict()

    # 走 KidsConsistencyManifest 解析，确认 schema 合法
    m = KidsConsistencyManifest.model_validate(manifest)
    # ShotSpec dry-run：每个 shot 的 shot_spec 都能被 ShotSpec 接受（委派）
    specs = to_task_specs(m)
    assert len(specs) == len(m.shots)
    for idx, spec in specs.items():
        assert spec.duration is not None and spec.duration >= 2.5

    # 双向绑定：写回任务 shot_rows 再回读
    shot_rows = [
        {"task_id": "task_k1", "shot_index": sh.shot_index, "selection_json": {}}
        for sh in m.shots
    ]
    written = attach_to_task_shot_rows(m, shot_rows)
    read_back = read_specs_from_task_shot_rows(written)
    assert all(s is not None for s in read_back)
    # 重建的 manifest 仍 OK
    rebuilt = manifest_from_task_specs(
        project_id=m.project_id,
        episode=m.episode,
        audience=m.audience,
        theme=m.theme,
        style_bible=m.style_bible,
        characters=m.characters,
        props=m.props,
        scenes=m.scenes,
        transition_table=m.transition_table,
        spoken_language=m.spoken_language,
        specs_by_index={sh.shot_index: sh.shot_spec for sh in m.shots},
        durations={sh.shot_index: sh.duration for sh in m.shots},
        lines={sh.shot_index: sh.line for sh in m.shots},
    )
    assert validate_manifest(rebuilt).status == "OK"

    # 落库可审阅 manifest JSON（写入 tmp 模拟 docs/kids/manifests）
    out = tmp_path / f"{m.project_id}_ep{m.episode}.json"
    out.write_text(canonical_json(m), encoding="utf-8")
    assert out.exists() and out.stat().st_size > 0


# ── 验收 5/6 辅助：注册表可调用 ──
def test_capabilities_registered_and_callable() -> None:
    gate_cap = get("kids.story_gate")
    assert gate_cap.name == "kids.story_gate"
    manifest_cap = get("kids.consistency_manifest")
    assert manifest_cap.name == "kids.consistency_manifest"
    # 注册表能列出
    from hevi.capabilities import list as list_caps
    names = {c.name for c in list_caps()}
    assert "kids.story_gate" in names
    assert "kids.consistency_manifest" in names


def test_story_gate_capability_render_pass(tmp_path: Path) -> None:
    cap = get("kids.story_gate")
    res = cap.render(
        {"story": _load("story_fox_star.json")},
        tmp_path / "out",
        duration=1.0,
        aspect="9:16",
        seed=1,
    )
    assert res.qa["status"] == "PASS"
    report_file = tmp_path / "out" / "kids_story_gate_report.json"
    assert report_file.exists()


def test_manifest_capability_render_illegal_param_fails(tmp_path: Path) -> None:
    cap = get("kids.consistency_manifest")
    res = cap.render(
        {"manifest": _load("manifest_bad_shotspec.json")},
        tmp_path / "out2",
        duration=1.0,
        aspect="9:16",
        seed=1,
    )
    assert res.qa["status"] == "FAIL"
    report_file = tmp_path / "out2" / "kids_consistency_manifest_report.json"
    assert report_file.exists()


# ── 规则合同：未知 beat kind 与非法 transition 直接校验失败（无静默放行）──
def test_story_unknown_beat_kind_rejected() -> None:
    with pytest.raises(Exception):
        StoryInput.model_validate({
            "theme": "t", "spoken_language": "zh-CN", "fixed_characters": ["c"],
            "beats": [{"kind": "nonsense", "text": "x"}],
        })


def test_story_invalid_transition_rejected() -> None:
    with pytest.raises(Exception):
        StoryBeat.model_validate({"kind": "greeting", "text": "x", "transition": "MAYBE"})
