"""S17: short-drama industrial checks, anchor locking, makeup rule, GPU plan."""

from __future__ import annotations

from pathlib import Path

from hevi.ai_drama.industrial import (
    check_industrial_storyboard,
    estimate_cost,
    keyframe_plan,
    local_gpu_plan,
    motion_only_prompt,
    run_delivery_qc,
)
from hevi.ai_drama.series import (
    check_makeup_shot,
    ensure_single_anchor,
    lock_generation_to_anchor,
    select_consistent_draws,
)


def _shot(**over):
    base = {
        "shot_id": "s1", "size": "中近景", "camera": "3/4 侧脸，中近景，平视",
        "action": "他递出钥匙，却被推开", "dialogue": [{"speaker": "c1", "text": "给你。"}],
        "duration_s": 3.0, "transition": "cut",
    }
    base.update(over)
    return base


def _storyboard(shots):
    return {"segments": [{"shots": shots}]}


def test_six_fields_and_single_action_pass():
    findings = check_industrial_storyboard(_storyboard([_shot()]))
    assert not [f for f in findings if f["severity"] == "blocker"]
    assert not [f for f in findings if f["rule"] == "I-6FIELD"]


def test_multi_action_and_contact_are_flagged():
    shots = [_shot(action="他抓住钥匙然后推开门", shot_id="s1"),
             _shot(action="她抱住了他", shot_id="s2")]
    rules = {f["rule"] for f in check_industrial_storyboard(_storyboard(shots))}
    assert "I-ONEACTION" in rules
    assert "I-CONTACT-SPLIT" in rules


def test_dialogue_length_uses_duration():
    shot = _shot(duration_s=3.0, dialogue=[{"speaker": "c1", "text": "这是一句超过十个字的长台词用来测试"}])
    rules = {f["rule"] for f in check_industrial_storyboard(_storyboard([shot]))}
    assert "I-DIALOGUE" in rules


def test_closeup_ratio_is_capped():
    shots = [_shot(size="特写", shot_id=f"s{i}", camera="特写，平视") for i in range(5)]
    rules = {f["rule"] for f in check_industrial_storyboard(_storyboard(shots))}
    assert "I-CLOSE-RATIO" in rules


def test_cost_estimate_is_shots_times_2_5():
    assert estimate_cost(10)["estimate_units"] == 25.0


def test_keyframe_plan_requires_approval():
    plan = keyframe_plan(_storyboard([_shot()]), candidates=3)
    assert plan["shots"]["s1"]["approved"] is False
    assert plan["shots"]["s1"]["selection_order"] == ["face", "hand", "composition"]


def test_motion_prompt_is_motion_only():
    text = motion_only_prompt({"action": "伸手", "speed": "慢", "camera": "推近"})
    assert "伸手" in text and "慢" in text and "推近" in text


def test_delivery_qc_missing_measurements_do_not_pass():
    report = run_delivery_qc(storyboard=_storyboard([_shot()]))
    assert not report["passed"]
    assert "face" in report["failed"]
    assert "loudness" in report["failed"]


def test_anchor_locking_adds_reference_to_every_image():
    series = {"cast": [{"id": "c1", "anchor_image": "/tmp/a.png",
                        "portrait_image": "", "name": "A"}]}
    ensure_single_anchor(series)
    assets = {"images": [
        {"kind": "character_identity", "character_id": "c1", "prompt": "identity", "render_prompt": "id"},
        {"kind": "character_portrait", "character_id": "c1", "prompt": "portrait", "render_prompt": "p"},
    ]}
    lock_generation_to_anchor(assets, series)
    portrait = assets["images"][1]
    assert portrait["anchor_reference"] == "/tmp/a.png"
    assert "锚图" in portrait["prompt"]
    assert "anchor image" in portrait["render_prompt"]


def test_makeup_ten_draws_seven_same_face():
    assert select_consistent_draws([0.8] * 7 + [0.4] * 3)["passed"] is True
    assert select_consistent_draws([0.8] * 6 + [0.4] * 4)["passed"] is False
    assert select_consistent_draws([0.8] * 7)["passed"] is False


def test_makeup_shot_rejects_non_flat_image(tmp_path: Path):
    from PIL import Image, ImageDraw

    card = {"id": "c1", "anchor_image": "/tmp/a.png"}
    image = Image.new("RGB", (512, 512), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 100, 512), fill=(0, 0, 0))
    path = tmp_path / "makeup.png"
    image.save(path)
    report = check_makeup_shot(path, card)
    assert not report["passed"]


def test_local_gpu_plan_does_not_run():
    plan = local_gpu_plan()
    assert plan["available"] is False
    assert plan["lora_training"]["run_now"] is False
    assert plan["wan_i2v"]["runner"] == "kaggle"
