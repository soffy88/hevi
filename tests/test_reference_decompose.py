"""Contract tests for story.reference_decompose (offline, deterministic).

The reference used here is invented for these tests only: an old woman
selling roasted sweet potatoes at a night market. No skill example plot,
person or line is reused.
"""

import json
from pathlib import Path

import pytest

from hevi.capabilities import registry
from hevi.capabilities.errors import CapabilityError
import hevi.capabilities.reference_decompose as rd_cap

TRANSCRIPT = (
    "你知道吗，城西夜市那个烤红薯的阿婆，烤了三十年，从没涨过价。"
    "阿婆每天下午四点推车出摊，先把炉火烧旺，再把红薯一个个码好。"
    "没想到最抢手的不是最大的红薯，而是烤裂了口、流着蜜的那几个。"
    "阿婆说，裂了口的才熟透，挑红薯要看裂口，不要看个头。"
    "天黑的时候，排队的人还在，阿婆把最后一个红薯递给一个放学的小孩。"
    "关注我，下期带你去看阿婆收摊之后，推车去哪了。"
)

SHOT_LIST = [
    {"text": "全景：夜市入口，人流走过，阿婆的推车在角落冒着热气。", "duration_sec": 5},
    {"text": "特写：阿婆的手把红薯码进炉膛，炉火旺起来。", "duration_sec": 8},
    {"text": "中景：顾客排队，阿婆递出一个裂了口的红薯。", "duration_sec": 10},
]


def _params(**overrides):
    params = {
        "title": "夜市烤红薯",
        "transcript": TRANSCRIPT,
        "shot_list": SHOT_LIST,
        "description": "城西夜市烤红薯摊的短片：阿婆三十年不涨价，裂口红薯最抢手。",
    }
    params.update(overrides)
    return params


def _run(params, tmp_path):
    cap = registry.get("story.reference_decompose")
    result = cap.render_safe(params, tmp_path, duration=0.0, aspect="16:9", seed=42)
    report = json.loads(Path(result.qa["report_json"]).read_text(encoding="utf-8"))
    return result, report


def test_registration_idempotent():
    assert registry.get("story.reference_decompose").name == "story.reference_decompose"
    assert rd_cap.register_reference_decompose_capabilities_once() == []


def test_five_layers_all_present(tmp_path):
    _, report = _run(_params(), tmp_path)
    layers = report["layers"]
    assert set(layers) == {
        "structure_beats",
        "shot_breakdown",
        "emotion_curve",
        "viral_mechanics",
        "production_brief",
    }
    assert report["coverage"] == {"transcript": True, "shot_list": True, "description": True}
    assert report["uncovered_inputs"] == []
    assert report["source"] == "rules"
    # Structure: hook first, ending last.
    beats = layers["structure_beats"]["beats"]
    assert beats[0]["label"] == "钩子"
    assert "你知道吗" in beats[0]["text_excerpt"]
    assert beats[-1]["label"] == "收尾"
    # Shot breakdown follows the supplied list, with types detected.
    shots = layers["shot_breakdown"]["shots"]
    assert len(shots) == 3
    assert [s["shot_type"] for s in shots] == ["全景", "特写", "中景"]
    assert shots[0]["duration_sec"] == 5
    # Emotion curve has one point per text segment.
    assert layers["emotion_curve"]["points"]
    # Viral mechanics: hook + contrast + CTA detected, each with evidence.
    mechs = {m["mechanism"]: m for m in layers["viral_mechanics"]["mechanisms"]}
    assert mechs["开篇钩子"]["present"] is True
    assert mechs["反差/反转"]["present"] is True
    assert mechs["互动召唤"]["present"] is True
    assert mechs["开篇钩子"]["evidence_keyword"] == "你知道吗"
    # Brief reuses structure/mechanics, never the reference's lines.
    brief = layers["production_brief"]
    assert "钩子" in brief["reusable"]["structure_labels"]
    assert "全景" in brief["reusable"]["shot_types"]
    assert brief["brief_lines"][0].startswith("只复用结构与手法，不复用原文台词")


def test_missing_shot_list_is_not_covered_not_invented(tmp_path):
    params = _params()
    params.pop("shot_list", None)
    _, report = _run(params, tmp_path)
    layer = report["layers"]["shot_breakdown"]
    assert layer["coverage"] == "not_covered"
    assert layer["shots"] == []
    assert report["coverage"]["shot_list"] is False
    assert "shot_list" in report["uncovered_inputs"]
    # Other layers still work from the transcript.
    assert report["layers"]["structure_beats"]["coverage"] == "covered"


def test_no_reference_material_raises(tmp_path):
    with pytest.raises(CapabilityError):
        _run({"title": "空参考"}, tmp_path)
    with pytest.raises(CapabilityError):
        rd_cap.decompose_reference({"title": "空参考", "transcript": "   "})


def test_description_only_still_decomposes(tmp_path):
    _, report = _run(
        {"title": "只有描述", "description": "阿婆烤红薯三十年不涨价，没想到裂口的最抢手。"},
        tmp_path,
    )
    assert report["layers"]["structure_beats"]["coverage"] == "covered"
    assert report["layers"]["shot_breakdown"]["coverage"] == "not_covered"
    assert report["layers"]["viral_mechanics"]["mechanisms"]


def test_absent_mechanism_is_flagged_not_faked(tmp_path):
    _, report = _run(
        {"title": "平铺直叙", "description": "阿婆每天下午出摊，烤红薯，卖完收摊回家。"},
        tmp_path,
    )
    mechs = {m["mechanism"]: m for m in report["layers"]["viral_mechanics"]["mechanisms"]}
    assert mechs["开篇钩子"]["present"] is False
    assert mechs["开篇钩子"]["evidence_excerpt"] is None
    assert mechs["互动召唤"]["present"] is False


def test_full_mode_requires_llm_and_uses_it(tmp_path):
    rd_cap.set_llm_fn(None)
    with pytest.raises(CapabilityError):
        rd_cap.decompose_reference(_params(mode="full"))
    seen = []

    def fake_llm(prompt, kind):
        seen.append(kind)
        return f"要点：{kind}"

    rd_cap.set_llm_fn(fake_llm)
    try:
        payload = rd_cap.decompose_reference(_params(mode="full"))
    finally:
        rd_cap.set_llm_fn(None)
    assert payload["source"] == "llm+rules"
    assert set(payload["llm_notes"]) == set(rd_cap.LLM_KINDS)
    assert payload["llm_failed"] == []
    assert seen == rd_cap.LLM_KINDS


def test_full_mode_llm_failure_degrades_to_rules(tmp_path):
    def failing_llm(prompt, kind):
        raise RuntimeError("llm down")

    rd_cap.set_llm_fn(failing_llm)
    try:
        payload = rd_cap.decompose_reference(_params(mode="full"))
    finally:
        rd_cap.set_llm_fn(None)
    # C-02: all five LLM calls failed, so no LLM content contributed
    # and the source label must say rules; llm_failed keeps the
    # evidence (previously this asserted the misleading "llm+rules").
    assert payload["source"] == "rules"
    assert payload["llm_notes"] == {}
    assert len(payload["llm_failed"]) == 5
    # Rule layers still stand: the failure is recorded, not faked over.
    assert payload["layers"]["structure_beats"]["coverage"] == "covered"


def test_report_file_sha(tmp_path):
    result, report = _run(_params(), tmp_path)
    report_path = Path(result.qa["report_json"])
    assert report_path.is_file()
    assert result.sha256 == registry.compute_sha256(report_path)
    assert report["title"] == "夜市烤红薯"
